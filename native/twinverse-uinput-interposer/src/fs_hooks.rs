//! Exported libc hook symbols (`open*`, `access`, `stat*`, `readdir*`, `scandir*`,
//! `read`, `__read_chk`, `write`, `ioctl`, `close`, `inotify_*`, `realpath`).

use core::cell::Cell;
use core::ffi::{c_char, c_int, c_ulong, c_void};
use core::mem::{size_of, zeroed};
use core::ptr;

use twinverse_uinput_proto::{
    cstr_bytes, fmt_u32, is_hidraw_basename, parse_hidraw_dev_path, udyn_index_for_basename,
    udyn_index_for_sysclass_path, virtual_event_devnum, write_cstr_parts, ENV_VIRTUAL_UINPUT,
    UDYN_EVENT_BASE, UDYN_MAX,
};

use crate::ffi::{
    format_syspath, free, get_errno, getenv, hidraw_filter_enabled, is_hidraw_blocked, malloc,
    needs_mode, qsort, readlink, real___fxstat, real___fxstat64, real___lxstat, real___lxstat64,
    real___open64_2, real___open_2, real___openat64_2, real___openat_2, real___read_chk,
    real___xstat, real___xstat64, real_access, real_close, real_closedir, real_fstat, real_fstat64,
    real_ioctl, real_lstat, real_lstat64, real_open, real_open64, real_openat, real_openat64,
    real_opendir, real_read, real_readdir, real_readdir64, real_realpath, real_scandir,
    real_scandir64, real_stat, real_stat64, real_write, realloc, set_errno, strdup, Dirent,
    Dirent64, RecursiveMutex, Scandir64ComparFn, Scandir64FilterFn, ScandirComparFn,
    ScandirFilterFn, Stat, Stat64, AT_FDCWD, DIR, DT_CHR, EFAULT, ENOENT, ENOSYS, PATH_MAX,
    S_IFCHR, W_OK,
};
use crate::inotify::{self, is_dev_input_dir};
use crate::uinput;

const SYNTH_INO_BASE: u64 = 0x0054_5749; // "TWI"
const MAX_DIR_STREAMS: usize = 32;

#[inline]
unsafe fn virtual_uinput_forced() -> bool {
    let p = getenv(ENV_VIRTUAL_UINPUT.as_ptr() as *const c_char);
    !p.is_null() && *p == b'1' as c_char
}

#[inline]
fn is_dev_dir(path: &[u8]) -> bool {
    path == b"/dev" || path == b"/dev/"
}

#[inline]
unsafe fn is_hidraw_path_blocked(path: &[u8]) -> bool {
    if let Some(base) = parse_hidraw_dev_path(path) {
        return is_hidraw_blocked(base);
    }
    false
}

unsafe fn fill_fake_stat(event_num: i32, buf: *mut Stat) {
    ptr::write_bytes(buf, 0, 1);
    let st = &mut *buf;
    st.st_mode = S_IFCHR | 0o666;
    st.st_rdev = virtual_event_devnum(event_num);
    st.st_nlink = 1;
    st.st_blksize = 4096;
}

#[cfg(target_arch = "x86")]
unsafe fn fill_fake_stat64(event_num: i32, buf: *mut Stat64) {
    ptr::write_bytes(buf, 0, 1);
    let st = &mut *buf;
    st.st_mode = S_IFCHR | 0o666;
    st.st_rdev = virtual_event_devnum(event_num);
    st.st_nlink = 1;
    st.st_blksize = 4096;
}

#[cfg(target_arch = "x86_64")]
#[inline]
unsafe fn fill_fake_stat64(event_num: i32, buf: *mut Stat64) {
    fill_fake_stat(event_num, buf);
}

unsafe fn common_open(path_bytes: Option<&[u8]>, flags: c_int) -> Option<c_int> {
    let path = path_bytes?;
    if path == b"/dev/uinput" {
        if !virtual_uinput_forced() {
            if let Some(acc) = real_access() {
                let saved = get_errno();
                let writable = acc(b"/dev/uinput\0".as_ptr() as *const c_char, W_OK) == 0;
                set_errno(saved);
                if writable {
                    return None;
                }
            }
        }
        return Some(uinput::open_creator(flags));
    }
    if is_hidraw_path_blocked(path) {
        set_errno(ENOENT);
        return Some(-1);
    }
    uinput::open_consumer(path, flags)
}

unsafe fn resolve_at_path<'a>(
    dirfd: c_int,
    pathname: *const c_char,
    full_buf: &'a mut [u8; PATH_MAX],
) -> Option<&'a [u8]> {
    let rel = cstr_bytes(pathname)?;
    if rel.starts_with(b"/") || dirfd == AT_FDCWD {
        return Some(rel);
    }
    let mut procfd = [0u8; 64];
    let mut nbuf = [0u8; 16];
    let dfd_str = fmt_u32(dirfd as u32, &mut nbuf);
    write_cstr_parts(&mut procfd, &[b"/proc/self/fd/", dfd_str])?;
    let mut dir_buf = [0u8; PATH_MAX];
    let len = readlink(
        procfd.as_ptr() as *const c_char,
        dir_buf.as_mut_ptr() as *mut c_char,
        dir_buf.len() - 1,
    );
    if len <= 0 {
        return Some(rel);
    }
    let dlen = len as usize;
    let total = write_cstr_parts(full_buf, &[&dir_buf[..dlen], b"/", rel])?;
    Some(&full_buf[..total])
}

// ---- access ---------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn access(pathname: *const c_char, mode: c_int) -> c_int {
    let Some(real_fn) = real_access() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if path == b"/dev/uinput" && virtual_uinput_forced() {
            set_errno(0);
            return 0;
        }
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if uinput::path_live(path).is_some() {
            set_errno(0);
            return 0;
        }
    }
    real_fn(pathname, mode)
}

// ---- open / open64 / openat / openat64 / __open*_2 ------------------------

#[no_mangle]
pub unsafe extern "C" fn open(pathname: *const c_char, flags: c_int, mode: u32) -> c_int {
    let Some(real_fn) = real_open() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(fd) = common_open(cstr_bytes(pathname), flags) {
        return fd;
    }
    if needs_mode(flags) {
        real_fn(pathname, flags, mode)
    } else {
        real_fn(pathname, flags)
    }
}

#[no_mangle]
pub unsafe extern "C" fn open64(pathname: *const c_char, flags: c_int, mode: u32) -> c_int {
    let real_fn = real_open64().or_else(|| real_open());
    let Some(real_fn) = real_fn else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(fd) = common_open(cstr_bytes(pathname), flags) {
        return fd;
    }
    if needs_mode(flags) {
        real_fn(pathname, flags, mode)
    } else {
        real_fn(pathname, flags)
    }
}

#[no_mangle]
pub unsafe extern "C" fn openat(
    dirfd: c_int,
    pathname: *const c_char,
    flags: c_int,
    mode: u32,
) -> c_int {
    let Some(real_fn) = real_openat() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut full = [0u8; PATH_MAX];
    let resolved = resolve_at_path(dirfd, pathname, &mut full);
    if let Some(fd) = common_open(resolved, flags) {
        return fd;
    }
    if needs_mode(flags) {
        real_fn(dirfd, pathname, flags, mode)
    } else {
        real_fn(dirfd, pathname, flags)
    }
}

#[no_mangle]
pub unsafe extern "C" fn openat64(
    dirfd: c_int,
    pathname: *const c_char,
    flags: c_int,
    mode: u32,
) -> c_int {
    let real_fn = real_openat64().or_else(|| real_openat());
    let Some(real_fn) = real_fn else {
        set_errno(EFAULT);
        return -1;
    };
    let mut full = [0u8; PATH_MAX];
    let resolved = resolve_at_path(dirfd, pathname, &mut full);
    if let Some(fd) = common_open(resolved, flags) {
        return fd;
    }
    if needs_mode(flags) {
        real_fn(dirfd, pathname, flags, mode)
    } else {
        real_fn(dirfd, pathname, flags)
    }
}

#[no_mangle]
pub unsafe extern "C" fn __open_2(file: *const c_char, oflag: c_int) -> c_int {
    let Some(real_fn) = real___open_2() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(fd) = common_open(cstr_bytes(file), oflag) {
        return fd;
    }
    real_fn(file, oflag)
}

#[no_mangle]
pub unsafe extern "C" fn __open64_2(file: *const c_char, oflag: c_int) -> c_int {
    let Some(real_fn) = real___open64_2() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(fd) = common_open(cstr_bytes(file), oflag) {
        return fd;
    }
    real_fn(file, oflag)
}

#[no_mangle]
pub unsafe extern "C" fn __openat_2(dirfd: c_int, file: *const c_char, oflag: c_int) -> c_int {
    let Some(real_fn) = real___openat_2() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut full = [0u8; PATH_MAX];
    let resolved = resolve_at_path(dirfd, file, &mut full);
    if let Some(fd) = common_open(resolved, oflag) {
        return fd;
    }
    real_fn(dirfd, file, oflag)
}

#[no_mangle]
pub unsafe extern "C" fn __openat64_2(dirfd: c_int, file: *const c_char, oflag: c_int) -> c_int {
    let Some(real_fn) = real___openat64_2() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut full = [0u8; PATH_MAX];
    let resolved = resolve_at_path(dirfd, file, &mut full);
    if let Some(fd) = common_open(resolved, oflag) {
        return fd;
    }
    real_fn(dirfd, file, oflag)
}

// ---- close / read / __read_chk / write / ioctl ----------------------------

#[no_mangle]
pub unsafe extern "C" fn close(fd: c_int) -> c_int {
    let Some(real_fn) = real_close() else {
        set_errno(EFAULT);
        return -1;
    };
    inotify::forget_fd(fd);
    uinput::handle_close(fd);
    real_fn(fd)
}

#[no_mangle]
pub unsafe extern "C" fn read(fd: c_int, buf: *mut c_void, count: usize) -> isize {
    let Some(real_fn) = real_read() else {
        set_errno(EFAULT);
        return -1;
    };
    if inotify::is_tracked(fd) {
        return inotify::handle_read(fd, buf, count);
    }
    if let Some(ret) = uinput::try_read(fd, buf, count) {
        return ret;
    }
    real_fn(fd, buf, count)
}

#[no_mangle]
pub unsafe extern "C" fn __read_chk(
    fd: c_int,
    buf: *mut c_void,
    nbytes: usize,
    buflen: usize,
) -> isize {
    let Some(real_fn) = real___read_chk() else {
        set_errno(EFAULT);
        return -1;
    };
    if nbytes > buflen {
        return real_fn(fd, buf, nbytes, buflen);
    }
    if inotify::is_tracked(fd) {
        return inotify::handle_read(fd, buf, nbytes);
    }
    if uinput::is_consumer_fd(fd) {
        return read(fd, buf, nbytes);
    }
    real_fn(fd, buf, nbytes, buflen)
}

#[no_mangle]
pub unsafe extern "C" fn write(fd: c_int, buf: *const c_void, count: usize) -> isize {
    let Some(real_fn) = real_write() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(ret) = uinput::try_write(fd, buf, count) {
        return ret;
    }
    real_fn(fd, buf, count)
}

#[no_mangle]
pub unsafe extern "C" fn ioctl(fd: c_int, request: c_ulong, arg: *mut c_void) -> c_int {
    let Some(real_fn) = real_ioctl() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(ret) = uinput::try_ioctl(fd, request, arg) {
        return ret;
    }
    real_fn(fd, request, arg)
}

// ---- stat / lstat / fstat + 64 + __*xstat* --------------------------------

#[no_mangle]
pub unsafe extern "C" fn stat(pathname: *const c_char, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real_stat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat(num, buf);
            return 0;
        }
    }
    real_fn(pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn lstat(pathname: *const c_char, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real_lstat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat(num, buf);
            return 0;
        }
    }
    real_fn(pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn fstat(fd: c_int, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real_fstat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(num) = uinput::consumer_event_num(fd) {
        fill_fake_stat(num, buf);
        return 0;
    }
    real_fn(fd, buf)
}

#[no_mangle]
pub unsafe extern "C" fn stat64(pathname: *const c_char, buf: *mut Stat64) -> c_int {
    let Some(real_fn) = real_stat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat64(num, buf);
            return 0;
        }
    }
    real_fn(pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn lstat64(pathname: *const c_char, buf: *mut Stat64) -> c_int {
    let Some(real_fn) = real_lstat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat64(num, buf);
            return 0;
        }
    }
    real_fn(pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn fstat64(fd: c_int, buf: *mut Stat64) -> c_int {
    let Some(real_fn) = real_fstat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(num) = uinput::consumer_event_num(fd) {
        fill_fake_stat64(num, buf);
        return 0;
    }
    real_fn(fd, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __xstat(ver: c_int, pathname: *const c_char, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real___xstat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat(num, buf);
            return 0;
        }
    }
    real_fn(ver, pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __lxstat(ver: c_int, pathname: *const c_char, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real___lxstat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat(num, buf);
            return 0;
        }
    }
    real_fn(ver, pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __fxstat(ver: c_int, fd: c_int, buf: *mut Stat) -> c_int {
    let Some(real_fn) = real___fxstat() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(num) = uinput::consumer_event_num(fd) {
        fill_fake_stat(num, buf);
        return 0;
    }
    real_fn(ver, fd, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __xstat64(ver: c_int, pathname: *const c_char, buf: *mut Stat64) -> c_int {
    let Some(real_fn) = real___xstat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat64(num, buf);
            return 0;
        }
    }
    real_fn(ver, pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __lxstat64(
    ver: c_int,
    pathname: *const c_char,
    buf: *mut Stat64,
) -> c_int {
    let Some(real_fn) = real___lxstat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(path) = cstr_bytes(pathname) {
        if is_hidraw_path_blocked(path) {
            set_errno(ENOENT);
            return -1;
        }
        if let Some(num) = uinput::path_live(path) {
            fill_fake_stat64(num, buf);
            return 0;
        }
    }
    real_fn(ver, pathname, buf)
}

#[no_mangle]
pub unsafe extern "C" fn __fxstat64(ver: c_int, fd: c_int, buf: *mut Stat64) -> c_int {
    let Some(real_fn) = real___fxstat64() else {
        set_errno(EFAULT);
        return -1;
    };
    if let Some(num) = uinput::consumer_event_num(fd) {
        fill_fake_stat64(num, buf);
        return 0;
    }
    real_fn(ver, fd, buf)
}

// ---- opendir / readdir / readdir64 / closedir / scandir / scandir64 -------

#[derive(Clone, Copy, PartialEq, Eq)]
enum DirKind {
    Input,
    Dev,
}

struct DirStream {
    dir: usize, // `*mut DIR as usize` so `DirStream` is `Send`
    kind: DirKind,
    seen_mask: u32,
    emitted_mask: u32,
    cursor: usize,
    buf: Dirent,
    buf64: Dirent64,
}

impl DirStream {
    const fn empty() -> Self {
        Self {
            dir: 0,
            kind: DirKind::Input,
            seen_mask: 0,
            emitted_mask: 0,
            cursor: 0,
            buf: Dirent {
                d_ino: 0,
                d_off: 0,
                d_reclen: 0,
                d_type: 0,
                d_name: [0; 256],
            },
            buf64: Dirent64 {
                d_ino: 0,
                d_off: 0,
                d_reclen: 0,
                d_type: 0,
                d_name: [0; 256],
            },
        }
    }
}

static DIR_STREAMS: RecursiveMutex<[DirStream; MAX_DIR_STREAMS]> =
    RecursiveMutex::new([const { DirStream::empty() }; MAX_DIR_STREAMS]);

pub unsafe fn init_dir_mutex() {
    DIR_STREAMS.init_recursive();
}

unsafe fn next_synth_slot(st: &mut DirStream) -> Option<usize> {
    while st.cursor < UDYN_MAX {
        let slot = st.cursor;
        st.cursor += 1;
        let bit = 1u32 << slot;
        if (st.seen_mask & bit) != 0 || (st.emitted_mask & bit) != 0 {
            continue;
        }
        if !uinput::node_ready(UDYN_EVENT_BASE + slot as i32) {
            continue;
        }
        st.emitted_mask |= bit;
        return Some(slot);
    }
    None
}

unsafe fn fill_dirent(d: &mut Dirent, slot: usize) {
    *d = zeroed();
    #[cfg(target_arch = "x86_64")]
    {
        d.d_ino = SYNTH_INO_BASE + slot as u64;
    }
    #[cfg(target_arch = "x86")]
    {
        d.d_ino = (SYNTH_INO_BASE + slot as u64) as u32;
    }
    d.d_type = DT_CHR;
    d.d_reclen = size_of::<Dirent>() as u16;
    let mut nbuf = [0u8; 16];
    let digits = fmt_u32((UDYN_EVENT_BASE + slot as i32) as u32, &mut nbuf);
    let name_bytes =
        core::slice::from_raw_parts_mut(d.d_name.as_mut_ptr() as *mut u8, d.d_name.len());
    let _ = write_cstr_parts(name_bytes, &[b"event", digits]);
}

unsafe fn fill_dirent64(d: &mut Dirent64, slot: usize) {
    *d = zeroed();
    d.d_ino = SYNTH_INO_BASE + slot as u64;
    d.d_type = DT_CHR;
    d.d_reclen = size_of::<Dirent64>() as u16;
    let mut nbuf = [0u8; 16];
    let digits = fmt_u32((UDYN_EVENT_BASE + slot as i32) as u32, &mut nbuf);
    let name_bytes =
        core::slice::from_raw_parts_mut(d.d_name.as_mut_ptr() as *mut u8, d.d_name.len());
    let _ = write_cstr_parts(name_bytes, &[b"event", digits]);
}

#[no_mangle]
pub unsafe extern "C" fn opendir(name: *const c_char) -> *mut DIR {
    let Some(real_fn) = real_opendir() else {
        set_errno(EFAULT);
        return ptr::null_mut();
    };
    let dir = real_fn(name);
    if !dir.is_null() {
        if let Some(bytes) = cstr_bytes(name) {
            let kind = if is_dev_input_dir(bytes) {
                Some(DirKind::Input)
            } else if hidraw_filter_enabled() && is_dev_dir(bytes) {
                Some(DirKind::Dev)
            } else {
                None
            };
            if let Some(kind) = kind {
                let mut streams = DIR_STREAMS.lock();
                if let Some(st) = streams.iter_mut().find(|s| s.dir == 0) {
                    *st = DirStream::empty();
                    st.dir = dir as usize;
                    st.kind = kind;
                }
            }
        }
    }
    dir
}

#[no_mangle]
pub unsafe extern "C" fn closedir(dirp: *mut DIR) -> c_int {
    let Some(real_fn) = real_closedir() else {
        set_errno(EFAULT);
        return -1;
    };
    let key = dirp as usize;
    if key != 0 {
        let mut streams = DIR_STREAMS.lock();
        if let Some(st) = streams.iter_mut().find(|s| s.dir == key) {
            st.dir = 0;
        }
    }
    real_fn(dirp)
}

#[no_mangle]
pub unsafe extern "C" fn readdir(dirp: *mut DIR) -> *mut Dirent {
    let Some(real_fn) = real_readdir() else {
        set_errno(EFAULT);
        return ptr::null_mut();
    };
    let key = dirp as usize;
    let kind = if key == 0 {
        None
    } else {
        let streams = DIR_STREAMS.lock();
        streams.iter().find(|s| s.dir == key).map(|s| s.kind)
    };
    let Some(kind) = kind else {
        return real_fn(dirp);
    };

    if kind == DirKind::Dev {
        loop {
            let ent = real_fn(dirp);
            if ent.is_null() {
                return ptr::null_mut();
            }
            if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
                if is_hidraw_basename(name) && is_hidraw_blocked(name) {
                    continue;
                }
            }
            return ent;
        }
    }

    let saved = get_errno();
    let ent = real_fn(dirp);
    if !ent.is_null() {
        if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
            if let Some(num) = udyn_index_for_basename(name) {
                let slot = (num - UDYN_EVENT_BASE) as usize;
                let mut streams = DIR_STREAMS.lock();
                if let Some(st) = streams.iter_mut().find(|s| s.dir == key) {
                    st.seen_mask |= 1u32 << slot;
                }
            }
        }
        return ent;
    }

    let mut out: *mut Dirent = ptr::null_mut();
    {
        let mut streams = DIR_STREAMS.lock();
        if let Some(st) = streams.iter_mut().find(|s| s.dir == key) {
            if let Some(slot) = next_synth_slot(st) {
                fill_dirent(&mut st.buf, slot);
                out = &mut st.buf as *mut Dirent;
            }
        }
    }
    set_errno(saved);
    out
}

#[no_mangle]
pub unsafe extern "C" fn readdir64(dirp: *mut DIR) -> *mut Dirent64 {
    let Some(real_fn) = real_readdir64() else {
        set_errno(EFAULT);
        return ptr::null_mut();
    };
    let key = dirp as usize;
    let kind = if key == 0 {
        None
    } else {
        let streams = DIR_STREAMS.lock();
        streams.iter().find(|s| s.dir == key).map(|s| s.kind)
    };
    let Some(kind) = kind else {
        return real_fn(dirp);
    };

    if kind == DirKind::Dev {
        loop {
            let ent = real_fn(dirp);
            if ent.is_null() {
                return ptr::null_mut();
            }
            if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
                if is_hidraw_basename(name) && is_hidraw_blocked(name) {
                    continue;
                }
            }
            return ent;
        }
    }

    let saved = get_errno();
    let ent = real_fn(dirp);
    if !ent.is_null() {
        if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
            if let Some(num) = udyn_index_for_basename(name) {
                let slot = (num - UDYN_EVENT_BASE) as usize;
                let mut streams = DIR_STREAMS.lock();
                if let Some(st) = streams.iter_mut().find(|s| s.dir == key) {
                    st.seen_mask |= 1u32 << slot;
                }
            }
        }
        return ent;
    }

    let mut out: *mut Dirent64 = ptr::null_mut();
    {
        let mut streams = DIR_STREAMS.lock();
        if let Some(st) = streams.iter_mut().find(|s| s.dir == key) {
            if let Some(slot) = next_synth_slot(st) {
                fill_dirent64(&mut st.buf64, slot);
                out = &mut st.buf64 as *mut Dirent64;
            }
        }
    }
    set_errno(saved);
    out
}

thread_local! {
    static SCANDIR_COMPAR: Cell<ScandirComparFn> = const { Cell::new(None) };
    static SCANDIR64_COMPAR: Cell<Scandir64ComparFn> = const { Cell::new(None) };
}

unsafe extern "C" fn scandir_qsort_cmp(a: *const c_void, b: *const c_void) -> c_int {
    let cmp = SCANDIR_COMPAR.with(|c| c.get());
    if let Some(f) = cmp {
        f(a as *mut *const Dirent, b as *mut *const Dirent)
    } else {
        0
    }
}

unsafe extern "C" fn scandir64_qsort_cmp(a: *const c_void, b: *const c_void) -> c_int {
    let cmp = SCANDIR64_COMPAR.with(|c| c.get());
    if let Some(f) = cmp {
        f(a as *mut *const Dirent64, b as *mut *const Dirent64)
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn scandir(
    dirp: *const c_char,
    namelist: *mut *mut *mut Dirent,
    filter: ScandirFilterFn,
    compar: ScandirComparFn,
) -> c_int {
    let Some(real_fn) = real_scandir() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut n = real_fn(dirp, namelist, filter, compar);
    if n < 0 {
        return n;
    }
    let Some(bytes) = cstr_bytes(dirp) else {
        return n;
    };
    if hidraw_filter_enabled() && is_dev_dir(bytes) && !namelist.is_null() && !(*namelist).is_null()
    {
        let mut keep = 0usize;
        for i in 0..(n as usize) {
            let ent = *(*namelist).add(i);
            let hide = !ent.is_null()
                && cstr_bytes((*ent).d_name.as_ptr())
                    .is_some_and(|name| is_hidraw_basename(name) && is_hidraw_blocked(name));
            if hide {
                free(ent as *mut c_void);
            } else {
                *(*namelist).add(keep) = ent;
                keep += 1;
            }
        }
        return keep as c_int;
    }
    if !is_dev_input_dir(bytes) {
        return n;
    }

    let mut seen = 0u32;
    for i in 0..(n as usize) {
        let ent = *(*namelist).add(i);
        if !ent.is_null() {
            if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
                if let Some(num) = udyn_index_for_basename(name) {
                    seen |= 1u32 << (num - UDYN_EVENT_BASE);
                }
            }
        }
    }

    for slot in 0..UDYN_MAX {
        if (seen & (1u32 << slot)) != 0 || !uinput::node_ready(UDYN_EVENT_BASE + slot as i32) {
            continue;
        }
        let ent = malloc(size_of::<Dirent>()) as *mut Dirent;
        if ent.is_null() {
            break;
        }
        fill_dirent(&mut *ent, slot);
        if let Some(flt) = filter {
            if flt(ent as *const Dirent) == 0 {
                free(ent as *mut c_void);
                continue;
            }
        }
        let grown = realloc(
            (*namelist) as *mut c_void,
            (n as usize + 1) * size_of::<*mut Dirent>(),
        ) as *mut *mut Dirent;
        if grown.is_null() {
            free(ent as *mut c_void);
            break;
        }
        *namelist = grown;
        *grown.add(n as usize) = ent;
        n += 1;
    }

    if compar.is_some() && n > 1 {
        SCANDIR_COMPAR.with(|c| c.set(compar));
        qsort(
            (*namelist) as *mut c_void,
            n as usize,
            size_of::<*mut Dirent>(),
            scandir_qsort_cmp,
        );
    }
    n
}

#[no_mangle]
pub unsafe extern "C" fn scandir64(
    dirp: *const c_char,
    namelist: *mut *mut *mut Dirent64,
    filter: Scandir64FilterFn,
    compar: Scandir64ComparFn,
) -> c_int {
    let Some(real_fn) = real_scandir64() else {
        set_errno(EFAULT);
        return -1;
    };
    let mut n = real_fn(dirp, namelist, filter, compar);
    if n < 0 {
        return n;
    }
    let Some(bytes) = cstr_bytes(dirp) else {
        return n;
    };
    if hidraw_filter_enabled() && is_dev_dir(bytes) && !namelist.is_null() && !(*namelist).is_null()
    {
        let mut keep = 0usize;
        for i in 0..(n as usize) {
            let ent = *(*namelist).add(i);
            let hide = !ent.is_null()
                && cstr_bytes((*ent).d_name.as_ptr())
                    .is_some_and(|name| is_hidraw_basename(name) && is_hidraw_blocked(name));
            if hide {
                free(ent as *mut c_void);
            } else {
                *(*namelist).add(keep) = ent;
                keep += 1;
            }
        }
        return keep as c_int;
    }
    if !is_dev_input_dir(bytes) {
        return n;
    }

    let mut seen = 0u32;
    for i in 0..(n as usize) {
        let ent = *(*namelist).add(i);
        if !ent.is_null() {
            if let Some(name) = cstr_bytes((*ent).d_name.as_ptr()) {
                if let Some(num) = udyn_index_for_basename(name) {
                    seen |= 1u32 << (num - UDYN_EVENT_BASE);
                }
            }
        }
    }

    for slot in 0..UDYN_MAX {
        if (seen & (1u32 << slot)) != 0 || !uinput::node_ready(UDYN_EVENT_BASE + slot as i32) {
            continue;
        }
        let ent = malloc(size_of::<Dirent64>()) as *mut Dirent64;
        if ent.is_null() {
            break;
        }
        fill_dirent64(&mut *ent, slot);
        if let Some(flt) = filter {
            if flt(ent as *const Dirent64) == 0 {
                free(ent as *mut c_void);
                continue;
            }
        }
        let grown = realloc(
            (*namelist) as *mut c_void,
            (n as usize + 1) * size_of::<*mut Dirent64>(),
        ) as *mut *mut Dirent64;
        if grown.is_null() {
            free(ent as *mut c_void);
            break;
        }
        *namelist = grown;
        *grown.add(n as usize) = ent;
        n += 1;
    }

    if compar.is_some() && n > 1 {
        SCANDIR64_COMPAR.with(|c| c.set(compar));
        qsort(
            (*namelist) as *mut c_void,
            n as usize,
            size_of::<*mut Dirent64>(),
            scandir64_qsort_cmp,
        );
    }
    n
}

// ---- inotify_add_watch / inotify_rm_watch ---------------------------------

#[no_mangle]
pub unsafe extern "C" fn inotify_add_watch(fd: c_int, pathname: *const c_char, mask: u32) -> c_int {
    inotify::handle_add_watch(fd, pathname, mask)
}

#[no_mangle]
pub unsafe extern "C" fn inotify_rm_watch(fd: c_int, wd: c_int) -> c_int {
    inotify::handle_rm_watch(fd, wd)
}

// ---- realpath -------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn realpath(path: *const c_char, resolved_path: *mut c_char) -> *mut c_char {
    if let Some(bytes) = cstr_bytes(path) {
        if let Some(num) = udyn_index_for_sysclass_path(bytes) {
            if uinput::node_live(num) {
                let mut synth = [0u8; 256];
                if let Some(len) = format_syspath(num, &mut synth) {
                    if !resolved_path.is_null() {
                        let copy_len = len.min(PATH_MAX - 1);
                        ptr::copy_nonoverlapping(
                            synth.as_ptr(),
                            resolved_path as *mut u8,
                            copy_len,
                        );
                        *resolved_path.add(copy_len) = 0;
                        return resolved_path;
                    }
                    return strdup(synth.as_ptr() as *const c_char);
                }
            }
        }
    }
    let Some(real_fn) = real_realpath() else {
        set_errno(ENOSYS);
        return ptr::null_mut();
    };
    real_fn(path, resolved_path)
}
