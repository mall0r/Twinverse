//! Shadow `inotify` watches translating socket-directory activity into
//! `/dev/input/event<N>` create/delete notifications for scanners that bypass `libudev`.

use core::ffi::{c_char, c_int, c_void};
use core::mem::size_of;
use core::ptr;
use core::sync::atomic::{AtomicI32, Ordering};

use twinverse_uinput_proto::{
    cstr_bytes, fmt_u32, parse_socket_or_desc_filename, write_cstr_parts,
};

use crate::ffi::{
    fcntl, get_errno, real_inotify_add_watch, real_inotify_rm_watch, real_read, set_errno,
    socket_dir_bytes, InotifyEvent, RecursiveMutex, EAGAIN, EFAULT, F_GETFL, IN_CREATE, IN_DELETE,
    IN_MOVED_FROM, IN_MOVED_TO, IN_ONLYDIR, NAME_MAX, O_NONBLOCK,
};

const MAX_INOTIFY_WATCHES: usize = 16;

#[derive(Clone, Copy)]
struct WatchEntry {
    used: bool,
    fd: c_int,
    app_wd: c_int,
    sock_wd: c_int,
}

impl WatchEntry {
    const fn empty() -> Self {
        Self {
            used: false,
            fd: -1,
            app_wd: -1,
            sock_wd: -1,
        }
    }
}

static WATCHES: RecursiveMutex<[WatchEntry; MAX_INOTIFY_WATCHES]> =
    RecursiveMutex::new([WatchEntry::empty(); MAX_INOTIFY_WATCHES]);
static WATCHES_USED: AtomicI32 = AtomicI32::new(0);

pub unsafe fn init_mutex() {
    WATCHES.init_recursive();
}

pub fn is_dev_input_dir(path: &[u8]) -> bool {
    let mut len = path.len();
    while len > 1 && path[len - 1] == b'/' {
        len -= 1;
    }
    &path[..len] == b"/dev/input"
}

pub unsafe fn is_tracked(fd: c_int) -> bool {
    if fd < 0 || WATCHES_USED.load(Ordering::Acquire) == 0 {
        return false;
    }
    let table = WATCHES.lock();
    table.iter().any(|w| w.used && w.fd == fd)
}

pub unsafe fn forget_fd(fd: c_int) {
    if fd < 0 || WATCHES_USED.load(Ordering::Acquire) == 0 {
        return;
    }
    let mut table = WATCHES.lock();
    for w in table.iter_mut() {
        if w.used && w.fd == fd {
            w.used = false;
            WATCHES_USED.fetch_sub(1, Ordering::Release);
        }
    }
}

pub unsafe fn handle_add_watch(fd: c_int, pathname: *const c_char, mask: u32) -> c_int {
    let Some(real_add) = real_inotify_add_watch() else {
        set_errno(EFAULT);
        return -1;
    };
    let wd = real_add(fd, pathname, mask);
    if wd < 0 {
        return wd;
    }
    let Some(path_bytes) = cstr_bytes(pathname) else {
        return wd;
    };
    if !is_dev_input_dir(path_bytes) {
        return wd;
    }
    let wanted = mask & (IN_CREATE | IN_DELETE | IN_MOVED_TO | IN_MOVED_FROM);
    if wanted == 0 {
        return wd;
    }
    let dir = socket_dir_bytes();
    if is_dev_input_dir(dir) {
        return wd;
    }
    let mut dir_cstr = [0u8; 256];
    if write_cstr_parts(&mut dir_cstr, &[dir]).is_none() {
        return wd;
    }

    let saved = get_errno();
    let sock_wd = real_add(fd, dir_cstr.as_ptr() as *const c_char, wanted | IN_ONLYDIR);
    set_errno(saved);
    if sock_wd < 0 {
        return wd;
    }

    let mut drop_sock_wd = Some(sock_wd);
    {
        let mut table = WATCHES.lock();
        let mut free_idx: Option<usize> = None;
        let mut exists = false;
        for (i, w) in table.iter().enumerate() {
            if w.used && w.fd == fd && w.app_wd == wd {
                exists = true;
                break;
            }
            if !w.used && free_idx.is_none() {
                free_idx = Some(i);
            }
        }
        if !exists {
            if let Some(idx) = free_idx {
                table[idx] = WatchEntry {
                    used: true,
                    fd,
                    app_wd: wd,
                    sock_wd,
                };
                WATCHES_USED.fetch_add(1, Ordering::Release);
                drop_sock_wd = None;
            }
        }
    }

    if let Some(swd) = drop_sock_wd {
        if let Some(real_rm) = real_inotify_rm_watch() {
            let saved2 = get_errno();
            real_rm(fd, swd);
            set_errno(saved2);
        }
    }
    wd
}

pub unsafe fn handle_rm_watch(fd: c_int, wd: c_int) -> c_int {
    let Some(real_rm) = real_inotify_rm_watch() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut sock_wd: Option<c_int> = None;
    if WATCHES_USED.load(Ordering::Acquire) > 0 {
        let mut table = WATCHES.lock();
        for w in table.iter_mut() {
            if w.used && w.fd == fd && w.app_wd == wd {
                sock_wd = Some(w.sock_wd);
                w.used = false;
                WATCHES_USED.fetch_sub(1, Ordering::Release);
            }
        }
    }
    let ret = real_rm(fd, wd);
    if let Some(swd) = sock_wd {
        let saved = get_errno();
        real_rm(fd, swd);
        set_errno(saved);
    }
    ret
}

pub unsafe fn handle_read(fd: c_int, buf: *mut c_void, count: usize) -> isize {
    let Some(read_fn) = real_read() else {
        set_errno(EFAULT);
        return -1;
    };
    let ev_sz = size_of::<InotifyEvent>();

    loop {
        let n = read_fn(fd, buf, count);
        if n <= 0 {
            return n;
        }
        let mut local = [WatchEntry::empty(); MAX_INOTIFY_WATCHES];
        let mut nwatch = 0usize;
        {
            let table = WATCHES.lock();
            for w in table.iter() {
                if w.used && w.fd == fd {
                    local[nwatch] = *w;
                    nwatch += 1;
                }
            }
        }

        let p = buf as *mut u8;
        let total = n as usize;
        let mut inp = 0usize;
        let mut out = 0usize;

        while inp + ev_sz <= total {
            let ev = ptr::read_unaligned(p.add(inp) as *const InotifyEvent);
            let rec = ev_sz + ev.len as usize;
            if inp + rec > total {
                break;
            }
            let matched = local[..nwatch].iter().find(|w| w.sock_wd == ev.wd);
            let Some(watch) = matched else {
                if out != inp {
                    ptr::copy(p.add(inp), p.add(out), rec);
                }
                out += rec;
                inp += rec;
                continue;
            };

            let mut ev_num: Option<i32> = None;
            if ev.len > 0 {
                let name_slice = core::slice::from_raw_parts(p.add(inp + ev_sz), ev.len as usize);
                let nl = name_slice
                    .iter()
                    .position(|&b| b == 0)
                    .unwrap_or(name_slice.len());
                if nl <= NAME_MAX {
                    if let Some((num, _is_sock)) = parse_socket_or_desc_filename(&name_slice[..nl])
                    {
                        ev_num = Some(num);
                    }
                }
            }
            inp += rec;

            let Some(num) = ev_num else {
                continue;
            };
            let mut nbuf = [0u8; 16];
            let digits = fmt_u32(num as u32, &mut nbuf);
            let mut node = [0u8; 32];
            let Some(node_str_len) = write_cstr_parts(&mut node, &[b"event", digits]) else {
                continue;
            };
            let node_with_nul = node_str_len + 1;
            let padded_len = ((node_with_nul + ev_sz - 1) / ev_sz) * ev_sz;

            let outev = InotifyEvent {
                wd: watch.app_wd,
                mask: ev.mask,
                cookie: ev.cookie,
                len: padded_len as u32,
            };
            ptr::write_unaligned(p.add(out) as *mut InotifyEvent, outev);
            ptr::write_bytes(p.add(out + ev_sz), 0, padded_len);
            ptr::copy_nonoverlapping(node.as_ptr(), p.add(out + ev_sz), node_with_nul);
            out += ev_sz + padded_len;
        }

        if inp < total {
            ptr::copy(p.add(inp), p.add(out), total - inp);
            out += total - inp;
        }
        if out > 0 {
            return out as isize;
        }
        let fl = fcntl(fd, F_GETFL, 0);
        if fl >= 0 && (fl & O_NONBLOCK) != 0 {
            set_errno(EAGAIN);
            return -1;
        }
    }
}
