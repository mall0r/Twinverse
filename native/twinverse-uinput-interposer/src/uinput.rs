//! Userspace `/dev/uinput` creator & `/dev/input/event3000..3015` consumer engine.

use core::ffi::{c_char, c_int, c_ulong, c_void};
use core::mem::{size_of, zeroed};
use core::ptr;
use core::sync::atomic::{AtomicI32, Ordering};

use twinverse_uinput_proto::{
    fmt_u32, ioc_nr, ioc_size, ioc_type, set_bit, translate_events, udyn_index_for_dev_path,
    write_cstr_parts, InputAbsInfo, InputEvent32, InputEvent64, InputId, NativeInputEvent,
    UdynDesc, UinputAbsSetup, UinputSetup, UinputUserDev, ABS_CNT, ABS_MAX, EVDEV_IOCTL_BASE,
    EVIOCGABS_BASE_NR, EVIOCGBIT_BASE_NR, EVIOCGEFFECTS_NR, EVIOCGID_NR, EVIOCGKEY_NR,
    EVIOCGLED_NR, EVIOCGNAME_NR, EVIOCGPHYS_NR, EVIOCGPROP_NR, EVIOCGRAB_NR, EVIOCGSW_NR,
    EVIOCGUNIQ_NR, EVIOCGVERSION_NR, EVIOCREVOKE_NR, EV_ABS, EV_KEY, EV_MAX, EV_MSC, EV_REL,
    EV_VERSION, INPUT_PROP_MAX, KEY_MAX, MSC_MAX, REL_MAX, UDYN_EVENT_BASE, UDYN_MAX,
    UDYN_MAX_CLIENTS, UINPUT_IOCTL_BASE, UI_ABS_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY, UI_DEV_SETUP,
    UI_GET_SYSNAME_NR, UI_GET_VERSION, UI_SET_ABSBIT, UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_MSCBIT,
    UI_SET_PROPBIT, UI_SET_RELBIT,
};

use crate::ffi::{
    accept4, bind, clock_gettime, connect, fcntl, format_desc_path, format_sock_path, get_errno,
    physical_bridge_enabled,
    geteuid, getpid, getsockopt, listen, make_fd_nonblocking, pipe2, poll, pthread_create,
    pthread_join, real_access, real_close, real_fstat, real_open, real_read, real_write, recv,
    rename, send, set_errno, socket, socketpair, unlink, PollFd, PthreadT, RecursiveMutex,
    SockaddrUn, Stat, Timespec, Ucred, AF_UNIX, CLOCK_MONOTONIC, EADDRINUSE, EAGAIN, ECONNREFUSED,
    EFAULT, EINTR, EINVAL, EIO, ENFILE, ENODEV, ENOENT, ENOSPC, ENOTTY, EWOULDBLOCK, F_GETFL, F_OK,
    MSG_DONTWAIT, MSG_NOSIGNAL, MSG_PEEK, O_CLOEXEC, O_CREAT, O_NONBLOCK, O_RDONLY, O_TRUNC,
    O_WRONLY, POLLIN, POLLOUT, SOCK_CLOEXEC, SOCK_NONBLOCK, SOCK_STREAM, SOL_SOCKET, SO_PEERCRED,
};

const MAX_CONSUMERS: usize = UDYN_MAX * 4;
const MAX_EVENT_RECORD: usize = size_of::<InputEvent64>();
const READ_BATCH: usize = 64;
const SEND_COMPLETE_MS: i64 = 50;

/// Fast-path atomic count of active virtual uinput creators + consumers.
/// While zero, `read`/`write`/`ioctl`/`close`/`fstat` never touch `UDYN_STATE`.
static UDYN_ACTIVE: AtomicI32 = AtomicI32::new(0);

#[inline]
pub fn is_active() -> bool {
    UDYN_ACTIVE.load(Ordering::Acquire) > 0
}

#[derive(Clone, Copy)]
struct CreatorSlot {
    token_fd: Option<c_int>,
    peer_fd: Option<c_int>,
    owner_pid: c_int,
    created: bool,
    event_num: i32,
    listen_fd: Option<c_int>,
    stop_pipe: [c_int; 2],
    thread: PthreadT,
    thread_started: bool,
    clients: [c_int; UDYN_MAX_CLIENTS],
    nclients: usize,
    desc: UdynDesc,
}

impl CreatorSlot {
    const fn empty() -> Self {
        Self {
            token_fd: None,
            peer_fd: None,
            owner_pid: 0,
            created: false,
            event_num: -1,
            listen_fd: None,
            stop_pipe: [-1, -1],
            thread: 0,
            thread_started: false,
            clients: [-1; UDYN_MAX_CLIENTS],
            nclients: 0,
            desc: UdynDesc::zeroed(),
        }
    }

    unsafe fn drop_client(&mut self, idx: usize) {
        let fd = self.clients[idx];
        if fd >= 0 {
            if let Some(rc) = real_close() {
                rc(fd);
            }
        }
        self.nclients -= 1;
        self.clients[idx] = self.clients[self.nclients];
        self.clients[self.nclients] = -1;
    }
}

#[derive(Clone, Copy)]
struct ConsumerSlot {
    fd: Option<c_int>,
    event_num: i32,
    desc: UdynDesc,
    src_size: usize,
    partial: [u8; MAX_EVENT_RECORD],
    partial_len: usize,
}

impl ConsumerSlot {
    const fn empty() -> Self {
        Self {
            fd: None,
            event_num: -1,
            desc: UdynDesc::zeroed(),
            src_size: 0,
            partial: [0; MAX_EVENT_RECORD],
            partial_len: 0,
        }
    }
}

struct UdynTable {
    creators: [CreatorSlot; UDYN_MAX],
    consumers: [ConsumerSlot; MAX_CONSUMERS],
}

impl UdynTable {
    const fn new() -> Self {
        Self {
            creators: [CreatorSlot::empty(); UDYN_MAX],
            consumers: [ConsumerSlot::empty(); MAX_CONSUMERS],
        }
    }

    fn creator_idx(&self, fd: c_int) -> Option<usize> {
        if fd < 0 {
            return None;
        }
        self.creators.iter().position(|c| c.token_fd == Some(fd))
    }

    fn consumer_idx(&self, fd: c_int) -> Option<usize> {
        if fd < 0 {
            return None;
        }
        self.consumers.iter().position(|c| c.fd == Some(fd))
    }
}

static UDYN_STATE: RecursiveMutex<UdynTable> = RecursiveMutex::new(UdynTable::new());

pub unsafe fn init_mutex() {
    UDYN_STATE.init_recursive();
}

unsafe fn make_unix_addr(sock_path: &[u8]) -> Option<SockaddrUn> {
    let mut addr: SockaddrUn = zeroed();
    addr.sun_family = AF_UNIX as u16;
    if sock_path.len() >= addr.sun_path.len() {
        return None;
    }
    addr.sun_path[..sock_path.len()].copy_from_slice(sock_path);
    addr.sun_path[sock_path.len()] = 0;
    Some(addr)
}

unsafe fn peer_is_session_user(fd: c_int) -> bool {
    let mut cred: Ucred = zeroed();
    let mut len = size_of::<Ucred>() as u32;
    if getsockopt(
        fd,
        SOL_SOCKET,
        SO_PEERCRED,
        (&mut cred as *mut Ucred) as *mut c_void,
        &mut len,
    ) != 0
    {
        return false;
    }
    let me = geteuid();
    cred.uid == me || cred.uid == 0
}

unsafe fn file_is_session_user(fd: c_int) -> bool {
    let Some(fstat_fn) = real_fstat() else {
        return false;
    };
    let mut st: Stat = zeroed();
    if fstat_fn(fd, &mut st) != 0 {
        return false;
    }
    let me = geteuid();
    st.st_uid == me || st.st_uid == 0
}

/// True when `tw_event<num>.sock` exists on disk (preserves `errno`).
pub unsafe fn node_live(num: i32) -> bool {
    let Some(access_fn) = real_access() else {
        return false;
    };
    let mut path = [0u8; 256];
    if format_sock_path(num, &mut path).is_none() {
        return false;
    }
    let saved = get_errno();
    let ok = access_fn(path.as_ptr() as *const c_char, F_OK) == 0;
    set_errno(saved);
    ok
}

/// True when BOTH `tw_event<num>.sock` and `tw_event<num>.desc` exist on disk.
pub unsafe fn node_ready(num: i32) -> bool {
    if !node_live(num) {
        return false;
    }
    let Some(access_fn) = real_access() else {
        return false;
    };
    let mut path = [0u8; 256];
    if format_desc_path(num, &mut path).is_none() {
        return false;
    }
    let saved = get_errno();
    let ok = access_fn(path.as_ptr() as *const c_char, F_OK) == 0;
    set_errno(saved);
    ok
}

pub unsafe fn path_live(path: &[u8]) -> Option<i32> {
    let num = udyn_index_for_dev_path(path)?;
    if node_live(num) {
        Some(num)
    } else {
        None
    }
}

unsafe fn node_accepting(num: i32) -> bool {
    let mut path = [0u8; 256];
    let Some(len) = format_sock_path(num, &mut path) else {
        return true;
    };
    let Some(addr) = make_unix_addr(&path[..len]) else {
        return true;
    };
    let fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if fd < 0 {
        return true;
    }
    let saved = get_errno();
    let rc = connect(
        fd,
        (&addr as *const SockaddrUn) as *const c_void,
        size_of::<SockaddrUn>() as u32,
    );
    let err = get_errno();
    let refused = rc < 0 && (err == ECONNREFUSED || err == ENOENT);
    if let Some(rc_fn) = real_close() {
        rc_fn(fd);
    }
    set_errno(saved);
    !refused
}

unsafe fn write_desc_atomic(num: i32, desc: &UdynDesc) -> bool {
    let (Some(open_fn), Some(write_fn), Some(close_fn)) = (real_open(), real_write(), real_close())
    else {
        return false;
    };
    let mut path = [0u8; 256];
    let Some(plen) = format_desc_path(num, &mut path) else {
        return false;
    };
    let mut pid_buf = [0u8; 16];
    let pid_bytes = fmt_u32(getpid() as u32, &mut pid_buf);
    let mut tmp = [0u8; 320];
    if write_cstr_parts(&mut tmp, &[&path[..plen], b".tmp.", pid_bytes]).is_none() {
        return false;
    }

    let fd = open_fn(
        tmp.as_ptr() as *const c_char,
        O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC,
        0o600u32,
    );
    if fd < 0 {
        return false;
    }

    let raw = core::slice::from_raw_parts(
        (desc as *const UdynDesc) as *const u8,
        size_of::<UdynDesc>(),
    );
    let mut sent = 0usize;
    let mut ok = true;
    while sent < raw.len() {
        let w = write_fn(
            fd,
            raw.as_ptr().add(sent) as *const c_void,
            raw.len() - sent,
        );
        if w <= 0 {
            ok = false;
            break;
        }
        sent += w as usize;
    }
    close_fn(fd);

    if !ok
        || rename(
            tmp.as_ptr() as *const c_char,
            path.as_ptr() as *const c_char,
        ) != 0
    {
        unlink(tmp.as_ptr() as *const c_char);
        return false;
    }
    true
}

unsafe extern "C" fn server_thread(arg: *mut c_void) -> *mut c_void {
    let slot_idx = arg as usize;
    let (listen_fd, stop_read_fd) = {
        let tbl = UDYN_STATE.lock();
        let c = &tbl.creators[slot_idx];
        match (c.created, c.listen_fd, c.stop_pipe[0]) {
            (true, Some(lfd), sfd) if sfd >= 0 => (lfd, sfd),
            _ => return ptr::null_mut(),
        }
    };

    loop {
        let mut pfds = [
            PollFd {
                fd: listen_fd,
                events: POLLIN,
                revents: 0,
            },
            PollFd {
                fd: stop_read_fd,
                events: POLLIN,
                revents: 0,
            },
        ];
        let r = poll(pfds.as_mut_ptr(), 2, -1);
        if r < 0 {
            if get_errno() == EINTR {
                continue;
            }
            break;
        }
        if (pfds[1].revents & POLLIN) != 0 {
            break;
        }
        if (pfds[0].revents & POLLIN) != 0 {
            let cfd = accept4(listen_fd, ptr::null_mut(), ptr::null_mut(), SOCK_CLOEXEC);
            if cfd < 0 {
                continue;
            }
            let mut tbl = UDYN_STATE.lock();
            let c = &mut tbl.creators[slot_idx];
            if !c.created || c.listen_fd != Some(listen_fd) {
                if let Some(rc) = real_close() {
                    rc(cfd);
                }
                break;
            }
            // Reap disconnected clients so repeated device scans never exhaust slots.
            let mut i = c.nclients;
            while i > 0 {
                i -= 1;
                let mut probe: u8 = 0;
                let pr = recv(
                    c.clients[i],
                    (&mut probe as *mut u8) as *mut c_void,
                    1,
                    MSG_PEEK | MSG_DONTWAIT,
                );
                if pr == 0 {
                    c.drop_client(i);
                } else if pr < 0 {
                    let e = get_errno();
                    if e != EAGAIN && e != EWOULDBLOCK && e != EINTR {
                        c.drop_client(i);
                    }
                }
            }
            if c.nclients < UDYN_MAX_CLIENTS {
                c.clients[c.nclients] = cfd;
                c.nclients += 1;
            } else if let Some(rc) = real_close() {
                rc(cfd);
            }
        }
    }
    ptr::null_mut()
}

/// Handle `open("/dev/uinput", flags)`.
pub unsafe fn open_creator(flags: c_int) -> c_int {
    let mut pair = [-1 as c_int; 2];
    let sock_type = SOCK_STREAM
        | SOCK_CLOEXEC
        | if (flags & O_NONBLOCK) != 0 {
            SOCK_NONBLOCK
        } else {
            0
        };
    if socketpair(AF_UNIX, sock_type, 0, &mut pair) != 0 {
        set_errno(ENODEV);
        return -1;
    }

    let fd = pair[0];
    {
        let mut tbl = UDYN_STATE.lock();
        let Some(slot) = tbl.creators.iter_mut().find(|c| c.token_fd.is_none()) else {
            drop(tbl);
            if let Some(rc) = real_close() {
                rc(pair[0]);
                rc(pair[1]);
            }
            set_errno(ENFILE);
            return -1;
        };
        *slot = CreatorSlot::empty();
        slot.token_fd = Some(fd);
        slot.peer_fd = Some(pair[1]);
        slot.owner_pid = getpid();
        slot.desc = UdynDesc::new_default();
    }
    UDYN_ACTIVE.fetch_add(1, Ordering::Release);
    fd
}

unsafe fn create_device_locked(tbl: &mut UdynTable, slot_idx: usize) -> c_int {
    if tbl.creators[slot_idx].created {
        return 0;
    }

    let mut chosen_fd: Option<c_int> = None;
    let mut chosen_num: i32 = -1;

    let start_slot = if physical_bridge_enabled() { 1 } else { 0 };
    for i in start_slot..UDYN_MAX {
        let num = UDYN_EVENT_BASE + i as i32;
        let mut sock_path = [0u8; 256];
        let Some(slen) = format_sock_path(num, &mut sock_path) else {
            set_errno(ENOSPC);
            return -1;
        };
        let Some(addr) = make_unix_addr(&sock_path[..slen]) else {
            set_errno(ENOSPC);
            return -1;
        };
        let fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if fd < 0 {
            return -1;
        }
        if bind(
            fd,
            (&addr as *const SockaddrUn) as *const c_void,
            size_of::<SockaddrUn>() as u32,
        ) < 0
        {
            if get_errno() == EADDRINUSE && !node_accepting(num) {
                let mut desc_path = [0u8; 256];
                unlink(sock_path.as_ptr() as *const c_char);
                if format_desc_path(num, &mut desc_path).is_some() {
                    unlink(desc_path.as_ptr() as *const c_char);
                }
                if bind(
                    fd,
                    (&addr as *const SockaddrUn) as *const c_void,
                    size_of::<SockaddrUn>() as u32,
                ) < 0
                {
                    if let Some(rc) = real_close() {
                        rc(fd);
                    }
                    continue;
                }
            } else {
                if let Some(rc) = real_close() {
                    rc(fd);
                }
                continue;
            }
        }
        if listen(fd, 8) < 0 {
            if let Some(rc) = real_close() {
                rc(fd);
            }
            unlink(sock_path.as_ptr() as *const c_char);
            continue;
        }
        chosen_fd = Some(fd);
        chosen_num = num;
        break;
    }

    let Some(listen_fd) = chosen_fd else {
        set_errno(ENOSPC);
        return -1;
    };

    let mut sock_path = [0u8; 256];
    let _ = format_sock_path(chosen_num, &mut sock_path);

    let desc_snapshot = tbl.creators[slot_idx].desc;
    if !write_desc_atomic(chosen_num, &desc_snapshot) {
        if let Some(rc) = real_close() {
            rc(listen_fd);
        }
        unlink(sock_path.as_ptr() as *const c_char);
        set_errno(EIO);
        return -1;
    }

    let mut sp = [-1 as c_int; 2];
    if pipe2(&mut sp, O_CLOEXEC) != 0 {
        let mut desc_path = [0u8; 256];
        if let Some(rc) = real_close() {
            rc(listen_fd);
        }
        unlink(sock_path.as_ptr() as *const c_char);
        if format_desc_path(chosen_num, &mut desc_path).is_some() {
            unlink(desc_path.as_ptr() as *const c_char);
        }
        set_errno(EIO);
        return -1;
    }

    let c = &mut tbl.creators[slot_idx];
    c.listen_fd = Some(listen_fd);
    c.event_num = chosen_num;
    c.stop_pipe = sp;
    c.created = true;

    let mut th: PthreadT = 0;
    if pthread_create(&mut th, ptr::null(), server_thread, slot_idx as *mut c_void) != 0 {
        c.created = false;
        c.listen_fd = None;
        c.stop_pipe = [-1, -1];
        if let Some(rc) = real_close() {
            rc(sp[0]);
            rc(sp[1]);
            rc(listen_fd);
        }
        let mut desc_path = [0u8; 256];
        unlink(sock_path.as_ptr() as *const c_char);
        if format_desc_path(chosen_num, &mut desc_path).is_some() {
            unlink(desc_path.as_ptr() as *const c_char);
        }
        set_errno(EIO);
        return -1;
    }
    c.thread = th;
    c.thread_started = true;
    0
}

/// Tear down a created device while `UDYN_STATE` is locked. Unlocks around
/// `pthread_join` and `unlink`, then re-locks before returning.
unsafe fn destroy_created_locked(tbl: &mut UdynTable, slot_idx: usize) {
    let c = &mut tbl.creators[slot_idx];
    if !c.created {
        return;
    }
    let num = c.event_num;
    let listen_fd = c.listen_fd.take();
    let sp0 = c.stop_pipe[0];
    let sp1 = c.stop_pipe[1];
    let th = c.thread;
    let started = c.thread_started;
    let nclients = c.nclients;
    let clients = c.clients;
    let inherited = c.owner_pid != getpid();

    c.created = false;
    c.thread_started = false;
    c.stop_pipe = [-1, -1];
    c.nclients = 0;
    c.clients = [-1; UDYN_MAX_CLIENTS];

    // Release mutex while joining thread and closing sockets.
    UDYN_STATE.unlock_raw();

    if !inherited && started && sp1 >= 0 {
        if let Some(w) = real_write() {
            let b: u8 = 1;
            let _ = w(sp1, (&b as *const u8) as *const c_void, 1);
        }
        pthread_join(th, ptr::null_mut());
    }

    if let Some(rc) = real_close() {
        for &cfd in &clients[..nclients] {
            if cfd >= 0 {
                rc(cfd);
            }
        }
        if sp0 >= 0 {
            rc(sp0);
        }
        if sp1 >= 0 {
            rc(sp1);
        }
        if let Some(lfd) = listen_fd {
            rc(lfd);
        }
    }

    if !inherited {
        let mut sock_path = [0u8; 256];
        let mut desc_path = [0u8; 256];
        if format_sock_path(num, &mut sock_path).is_some() {
            unlink(sock_path.as_ptr() as *const c_char);
        }
        if format_desc_path(num, &mut desc_path).is_some() {
            unlink(desc_path.as_ptr() as *const c_char);
        }
    }

    UDYN_STATE.lock_raw();
}

unsafe fn creator_ioctl_locked(
    tbl: &mut UdynTable,
    slot_idx: usize,
    request: c_ulong,
    arg: *mut c_void,
) -> c_int {
    if ioc_type(request) != UINPUT_IOCTL_BASE {
        set_errno(ENOTTY);
        return -1;
    }

    let bit = arg as isize as c_int;
    match request {
        UI_SET_EVBIT => {
            set_bit(&mut tbl.creators[slot_idx].desc.evbits, bit, EV_MAX);
            return 0;
        }
        UI_SET_KEYBIT => {
            set_bit(&mut tbl.creators[slot_idx].desc.keybits, bit, KEY_MAX);
            return 0;
        }
        UI_SET_RELBIT => {
            set_bit(&mut tbl.creators[slot_idx].desc.relbits, bit, REL_MAX);
            return 0;
        }
        UI_SET_ABSBIT => {
            set_bit(&mut tbl.creators[slot_idx].desc.absbits, bit, ABS_MAX);
            return 0;
        }
        UI_SET_MSCBIT => {
            set_bit(&mut tbl.creators[slot_idx].desc.mscbits, bit, MSC_MAX);
            return 0;
        }
        UI_SET_PROPBIT => {
            set_bit(
                &mut tbl.creators[slot_idx].desc.propbits,
                bit,
                INPUT_PROP_MAX,
            );
            return 0;
        }
        UI_DEV_CREATE => return create_device_locked(tbl, slot_idx),
        UI_DEV_DESTROY => {
            destroy_created_locked(tbl, slot_idx);
            return 0;
        }
        _ => {}
    }

    if arg.is_null() {
        return 0;
    }

    if request == UI_DEV_SETUP {
        let s = ptr::read_unaligned(arg as *const UinputSetup);
        let d = &mut tbl.creators[slot_idx].desc;
        d.bustype = s.id.bustype;
        d.vendor = s.id.vendor;
        d.product = s.id.product;
        d.version_id = s.id.version;
        d.name = s.name;
        d.name[d.name.len() - 1] = 0;
        return 0;
    }

    if request == UI_ABS_SETUP {
        let s = ptr::read_unaligned(arg as *const UinputAbsSetup);
        if (s.code as usize) < ABS_CNT {
            tbl.creators[slot_idx].desc.absinfo[s.code as usize] = s.absinfo;
        }
        return 0;
    }

    if ioc_nr(request) == UI_GET_SYSNAME_NR {
        let len = ioc_size(request);
        if len == 0 {
            return 0;
        }
        let c = &tbl.creators[slot_idx];
        let out = core::slice::from_raw_parts_mut(arg as *mut u8, len);
        let mut nbuf = [0u8; 16];
        let name_len = if c.created && c.event_num >= 0 {
            let num = fmt_u32(c.event_num as u32, &mut nbuf);
            write_cstr_parts(out, &[b"event", num])
        } else {
            write_cstr_parts(out, &[b"event-1"])
        };
        if name_len.is_none() && len > 0 {
            out[0] = 0;
        }
        return 0;
    }

    if request == UI_GET_VERSION {
        ptr::write_unaligned(arg as *mut u32, 5);
        return 0;
    }

    // Other valid `'U'` setup ioctls (e.g. `UI_SET_PHYS`, `UI_SET_FFBIT`): accept.
    0
}

unsafe fn send_whole(fd: c_int, buf: *const u8, count: usize) -> bool {
    let w = send(fd, buf as *const c_void, count, MSG_NOSIGNAL | MSG_DONTWAIT);
    if w < 0 {
        let e = get_errno();
        return e == EAGAIN || e == EWOULDBLOCK || e == EINTR;
    }
    let mut sent = w as usize;
    if sent >= count {
        return true;
    }
    let mut start: Timespec = zeroed();
    clock_gettime(CLOCK_MONOTONIC, &mut start);
    while sent < count {
        let mut now: Timespec = zeroed();
        clock_gettime(CLOCK_MONOTONIC, &mut now);
        let elapsed_ms = (now.tv_sec as i64 - start.tv_sec as i64) * 1000
            + (now.tv_nsec as i64 - start.tv_nsec as i64) / 1_000_000;
        if elapsed_ms >= SEND_COMPLETE_MS {
            return false;
        }
        let mut pfd = PollFd {
            fd,
            events: POLLOUT,
            revents: 0,
        };
        if poll(&mut pfd, 1, (SEND_COMPLETE_MS - elapsed_ms) as c_int) < 0 && get_errno() != EINTR {
            return false;
        }
        let w2 = send(
            fd,
            buf.add(sent) as *const c_void,
            count - sent,
            MSG_NOSIGNAL | MSG_DONTWAIT,
        );
        if w2 > 0 {
            sent += w2 as usize;
        } else if w2 < 0 {
            let e = get_errno();
            if e != EAGAIN && e != EWOULDBLOCK && e != EINTR {
                return false;
            }
        }
    }
    true
}

unsafe fn creator_write_locked(c: &mut CreatorSlot, buf: *const c_void, count: usize) -> isize {
    if !c.created && count == size_of::<UinputUserDev>() {
        let u = ptr::read_unaligned(buf as *const UinputUserDev);
        c.desc.name = u.name;
        c.desc.name[c.desc.name.len() - 1] = 0;
        c.desc.bustype = u.id.bustype;
        c.desc.vendor = u.id.vendor;
        c.desc.product = u.id.product;
        c.desc.version_id = u.id.version;
        for a in 0..ABS_CNT {
            c.desc.absinfo[a].minimum = u.absmin[a];
            c.desc.absinfo[a].maximum = u.absmax[a];
            c.desc.absinfo[a].fuzz = u.absfuzz[a];
            c.desc.absinfo[a].flat = u.absflat[a];
        }
        return count as isize;
    }
    if !c.created {
        set_errno(EINVAL);
        return -1;
    }
    let mut i = c.nclients;
    while i > 0 {
        i -= 1;
        if !send_whole(c.clients[i], buf as *const u8, count) {
            c.drop_client(i);
        }
    }
    count as isize
}

/// Handle `open("/dev/input/event<N>", flags)` for a live dynamic node.
/// Returns `Some(fd_or_neg1)` when intercepted, or `None` to fall through.
pub unsafe fn open_consumer(path: &[u8], flags: c_int) -> Option<c_int> {
    let num = path_live(path)?;
    let (Some(open_fn), Some(read_fn), Some(close_fn)) = (real_open(), real_read(), real_close())
    else {
        return None;
    };

    let mut dpath = [0u8; 256];
    format_desc_path(num, &mut dpath)?;
    let dfd = open_fn(dpath.as_ptr() as *const c_char, O_RDONLY | O_CLOEXEC);
    if dfd < 0 {
        return None;
    }
    if !file_is_session_user(dfd) {
        close_fn(dfd);
        return None;
    }

    let mut desc = UdynDesc::zeroed();
    let raw = core::slice::from_raw_parts_mut(
        (&mut desc as *mut UdynDesc) as *mut u8,
        size_of::<UdynDesc>(),
    );
    let mut got = 0usize;
    while got < raw.len() {
        let r = read_fn(
            dfd,
            raw.as_mut_ptr().add(got) as *mut c_void,
            raw.len() - got,
        );
        if r <= 0 {
            break;
        }
        got += r as usize;
    }
    close_fn(dfd);

    if got != size_of::<UdynDesc>() || !desc.is_valid() {
        return None;
    }

    let src_size = match desc.event_size as usize {
        s if s == size_of::<InputEvent32>() || s == size_of::<InputEvent64>() => s,
        _ => size_of::<NativeInputEvent>(),
    };

    let fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if fd < 0 {
        set_errno(EIO);
        return Some(-1);
    }

    let mut sock_path = [0u8; 256];
    let Some(slen) = format_sock_path(num, &mut sock_path) else {
        close_fn(fd);
        return None;
    };
    let Some(addr) = make_unix_addr(&sock_path[..slen]) else {
        close_fn(fd);
        return None;
    };

    if connect(
        fd,
        (&addr as *const SockaddrUn) as *const c_void,
        size_of::<SockaddrUn>() as u32,
    ) < 0
    {
        close_fn(fd);
        return None;
    }

    if !peer_is_session_user(fd) {
        close_fn(fd);
        return None;
    }

    if (flags & O_NONBLOCK) != 0 {
        let _ = make_fd_nonblocking(fd);
    }

    {
        let mut tbl = UDYN_STATE.lock();
        let Some(slot) = tbl.consumers.iter_mut().find(|c| c.fd.is_none()) else {
            drop(tbl);
            close_fn(fd);
            set_errno(ENFILE);
            return Some(-1);
        };
        *slot = ConsumerSlot::empty();
        slot.fd = Some(fd);
        slot.event_num = num;
        slot.desc = desc;
        slot.src_size = src_size;
    }
    UDYN_ACTIVE.fetch_add(1, Ordering::Release);
    Some(fd)
}

unsafe fn copy_cstr_ioctl(arg: *mut c_void, len: usize, bytes: &[u8]) -> c_int {
    if arg.is_null() || len == 0 {
        set_errno(EFAULT);
        return -1;
    }
    let out = core::slice::from_raw_parts_mut(arg as *mut u8, len);
    let n = bytes.len().min(len - 1);
    out[..n].copy_from_slice(&bytes[..n]);
    out[n] = 0;
    n as c_int
}

unsafe fn consumer_ioctl(
    desc: &UdynDesc,
    event_num: i32,
    request: c_ulong,
    arg: *mut c_void,
) -> c_int {
    if ioc_type(request) != EVDEV_IOCTL_BASE {
        set_errno(ENOTTY);
        return -1;
    }

    let nr = ioc_nr(request);
    let len = ioc_size(request);

    if nr == EVIOCGVERSION_NR {
        if arg.is_null() || len < size_of::<c_int>() {
            set_errno(EFAULT);
            return -1;
        }
        ptr::write_unaligned(arg as *mut c_int, EV_VERSION);
        return 0;
    }

    if nr == EVIOCGID_NR {
        if arg.is_null() || len < size_of::<InputId>() {
            set_errno(EFAULT);
            return -1;
        }
        let id = InputId {
            bustype: desc.bustype,
            vendor: desc.vendor,
            product: desc.product,
            version: desc.version_id,
        };
        ptr::write_unaligned(arg as *mut InputId, id);
        return 0;
    }

    if nr == EVIOCGNAME_NR {
        return copy_cstr_ioctl(arg, len, desc.name_bytes());
    }

    if nr == EVIOCGPHYS_NR {
        let mut buf = [0u8; 64];
        let mut nbuf = [0u8; 16];
        let num = fmt_u32(event_num as u32, &mut nbuf);
        let n = write_cstr_parts(&mut buf, &[b"twinverse/virtinput/event", num, b"/input0"])
            .unwrap_or(0);
        return copy_cstr_ioctl(arg, len, &buf[..n]);
    }

    if nr == EVIOCGUNIQ_NR {
        let mut buf = [0u8; 32];
        let mut nbuf = [0u8; 16];
        let num = fmt_u32(event_num as u32, &mut nbuf);
        let n = write_cstr_parts(&mut buf, &[b"TWIN", num]).unwrap_or(0);
        return copy_cstr_ioctl(arg, len, &buf[..n]);
    }

    if nr == EVIOCGPROP_NR {
        if arg.is_null() || len == 0 {
            set_errno(EFAULT);
            return -1;
        }
        let n = len.min(desc.propbits.len());
        ptr::copy_nonoverlapping(desc.propbits.as_ptr(), arg as *mut u8, n);
        if n < len {
            ptr::write_bytes((arg as *mut u8).add(n), 0, len - n);
        }
        return n as c_int;
    }

    if nr >= EVIOCGBIT_BASE_NR && nr < EVIOCGBIT_BASE_NR + EV_MAX as u32 {
        if arg.is_null() || len == 0 {
            set_errno(EFAULT);
            return -1;
        }
        let ev = (nr - EVIOCGBIT_BASE_NR) as usize;
        let src: Option<&[u8]> = match ev {
            0 => Some(&desc.evbits),
            EV_KEY => Some(&desc.keybits),
            EV_REL => Some(&desc.relbits),
            EV_ABS => Some(&desc.absbits),
            EV_MSC => Some(&desc.mscbits),
            _ => None,
        };
        if let Some(bits) = src {
            let n = len.min(bits.len());
            ptr::copy_nonoverlapping(bits.as_ptr(), arg as *mut u8, n);
            if n < len {
                ptr::write_bytes((arg as *mut u8).add(n), 0, len - n);
            }
            return n as c_int;
        }
        ptr::write_bytes(arg as *mut u8, 0, len);
        return len as c_int;
    }

    if nr >= EVIOCGABS_BASE_NR && nr < EVIOCGABS_BASE_NR + ABS_CNT as u32 {
        if arg.is_null() || len < size_of::<InputAbsInfo>() {
            set_errno(EFAULT);
            return -1;
        }
        let code = (nr - EVIOCGABS_BASE_NR) as usize;
        ptr::write_unaligned(arg as *mut InputAbsInfo, desc.absinfo[code]);
        return 0;
    }

    if nr == EVIOCGKEY_NR || nr == EVIOCGLED_NR || nr == EVIOCGSW_NR {
        if !arg.is_null() && len > 0 {
            ptr::write_bytes(arg as *mut u8, 0, len);
        }
        return len as c_int;
    }

    if nr == EVIOCGEFFECTS_NR {
        if arg.is_null() || len < size_of::<c_int>() {
            set_errno(EFAULT);
            return -1;
        }
        ptr::write_unaligned(arg as *mut c_int, 0);
        return 0;
    }

    if nr == EVIOCGRAB_NR || nr == EVIOCREVOKE_NR {
        return 0;
    }

    set_errno(ENOTTY);
    -1
}

/// Dispatch `ioctl()` if `fd` is a virtual creator or consumer.
pub unsafe fn try_ioctl(fd: c_int, request: c_ulong, arg: *mut c_void) -> Option<c_int> {
    if !is_active() || fd < 0 {
        return None;
    }
    let mut tbl = UDYN_STATE.lock();
    if let Some(cidx) = tbl.creator_idx(fd) {
        set_errno(0);
        return Some(creator_ioctl_locked(&mut tbl, cidx, request, arg));
    }
    if let Some(coidx) = tbl.consumer_idx(fd) {
        let desc = tbl.consumers[coidx].desc;
        let ev_num = tbl.consumers[coidx].event_num;
        drop(tbl);
        set_errno(0);
        return Some(consumer_ioctl(&desc, ev_num, request, arg));
    }
    None
}

/// Dispatch `write()` if `fd` is a virtual creator or consumer.
pub unsafe fn try_write(fd: c_int, buf: *const c_void, count: usize) -> Option<isize> {
    if !is_active() || fd < 0 {
        return None;
    }
    let mut tbl = UDYN_STATE.lock();
    if let Some(cidx) = tbl.creator_idx(fd) {
        return Some(creator_write_locked(&mut tbl.creators[cidx], buf, count));
    }
    if tbl.consumer_idx(fd).is_some() {
        // Evdev writes (e.g. LEDs/FF) on a consumer node are accepted and discarded.
        return Some(count as isize);
    }
    None
}

/// Returns true if `fd` is a virtual consumer (used by `__read_chk`).
pub unsafe fn is_consumer_fd(fd: c_int) -> bool {
    if !is_active() || fd < 0 {
        return false;
    }
    let tbl = UDYN_STATE.lock();
    tbl.consumer_idx(fd).is_some()
}

/// Returns the virtual `event<N>` number if `fd` is a consumer fd (for `fstat*`).
pub unsafe fn consumer_event_num(fd: c_int) -> Option<i32> {
    if !is_active() || fd < 0 {
        return None;
    }
    let tbl = UDYN_STATE.lock();
    let idx = tbl.consumer_idx(fd)?;
    Some(tbl.consumers[idx].event_num)
}

unsafe fn stash_consumer_partial(fd: c_int, bytes: &[u8]) {
    if bytes.is_empty() || bytes.len() > MAX_EVENT_RECORD {
        return;
    }
    let mut tbl = UDYN_STATE.lock();
    if let Some(idx) = tbl.consumer_idx(fd) {
        let co = &mut tbl.consumers[idx];
        co.partial[..bytes.len()].copy_from_slice(bytes);
        co.partial_len = bytes.len();
    }
}

/// Dispatch `read()` if `fd` is a virtual consumer.
pub unsafe fn try_read(fd: c_int, buf: *mut c_void, count: usize) -> Option<isize> {
    if !is_active() || fd < 0 {
        return None;
    }

    let (src_size, mut raw, mut have) = {
        let mut tbl = UDYN_STATE.lock();
        let idx = tbl.consumer_idx(fd)?;
        let co = &mut tbl.consumers[idx];
        let mut raw = [0u8; READ_BATCH * MAX_EVENT_RECORD];
        let have = co.partial_len;
        if have > 0 {
            raw[..have].copy_from_slice(&co.partial[..have]);
            co.partial_len = 0;
        }
        (co.src_size, raw, have)
    };

    let esz = size_of::<NativeInputEvent>();
    if count == 0 {
        if have > 0 {
            stash_consumer_partial(fd, &raw[..have]);
        }
        return Some(0);
    }
    if count < esz {
        if have > 0 {
            stash_consumer_partial(fd, &raw[..have]);
        }
        set_errno(EINVAL);
        return Some(-1);
    }

    let fl = fcntl(fd, F_GETFL, 0);
    let nonblock = fl >= 0 && (fl & O_NONBLOCK) != 0;

    let records = (count / esz).min(READ_BATCH);
    let want = records * src_size;

    loop {
        let whole = (have / src_size) * src_size;
        if whole > 0 {
            let leftover = have - whole;
            if leftover > 0 {
                stash_consumer_partial(fd, &raw[whole..have]);
            }
            let cnt = translate_events(raw.as_ptr(), whole / src_size, src_size, buf as *mut u8);
            return Some((cnt * esz) as isize);
        }

        let r = recv(
            fd,
            raw.as_mut_ptr().add(have) as *mut c_void,
            want - have,
            0,
        );
        if r > 0 {
            have += r as usize;
            continue;
        }
        if r == 0 {
            if have > 0 {
                stash_consumer_partial(fd, &raw[..have]);
            }
            return Some(0);
        }
        let err = get_errno();
        if err == EINTR {
            continue;
        }
        if err == EAGAIN || err == EWOULDBLOCK {
            if nonblock {
                if have > 0 {
                    stash_consumer_partial(fd, &raw[..have]);
                }
                set_errno(err);
                return Some(-1);
            }
            let mut pfd = PollFd {
                fd,
                events: POLLIN,
                revents: 0,
            };
            if poll(&mut pfd, 1, -1) < 0 && get_errno() != EINTR {
                if have > 0 {
                    stash_consumer_partial(fd, &raw[..have]);
                }
                return Some(-1);
            }
            continue;
        }
        if have > 0 {
            stash_consumer_partial(fd, &raw[..have]);
        }
        set_errno(err);
        return Some(-1);
    }
}

/// Retire a creator or consumer fd on `close(fd)`.
pub unsafe fn handle_close(fd: c_int) {
    if !is_active() || fd < 0 {
        return;
    }
    let mut peer_to_close: Option<c_int> = None;
    let mut retired = false;
    {
        let mut tbl = UDYN_STATE.lock();
        if let Some(cidx) = tbl.creator_idx(fd) {
            destroy_created_locked(&mut tbl, cidx);
            peer_to_close = tbl.creators[cidx].peer_fd.take();
            tbl.creators[cidx].token_fd = None;
            retired = true;
        } else if let Some(coidx) = tbl.consumer_idx(fd) {
            tbl.consumers[coidx].fd = None;
            tbl.consumers[coidx].partial_len = 0;
            retired = true;
        }
    }
    if let Some(pfd) = peer_to_close {
        if let Some(rc) = real_close() {
            rc(pfd);
        }
    }
    if retired {
        UDYN_ACTIVE.fetch_sub(1, Ordering::Release);
    }
}
