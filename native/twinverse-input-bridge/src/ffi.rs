//! Minimal POSIX / Linux FFI declarations for `twinverse-input-bridge`.
//!
//! Uses only standard libc symbols present in GLIBC <= 2.35 so the compiled
//! binary stays portable across all target Linux distributions, AppImage,
//! and Flatpak runtimes.

#![allow(dead_code, non_camel_case_types)]

use core::ffi::{c_char, c_int, c_long, c_ulong, c_void};
use core::mem::{size_of, zeroed};

use twinverse_uinput_proto::{
    ioc, InputAbsInfo, InputId, EVDEV_IOCTL_BASE, EVIOCGABS_BASE_NR, EVIOCGBIT_BASE_NR,
    EVIOCGID_NR, EVIOCGKEY_NR, EVIOCGNAME_NR, EVIOCGPHYS_NR, EVIOCGPROP_NR, EVIOCGUNIQ_NR,
    IOC_READ,
};

pub type pid_t = c_int;
pub type uid_t = u32;
pub type socklen_t = u32;
pub type mode_t = u32;

// Linux errno constants.
pub const EINTR: c_int = 4;
pub const EIO: c_int = 5;
pub const EAGAIN: c_int = 11;
pub const EWOULDBLOCK: c_int = EAGAIN;
pub const EACCES: c_int = 13;
pub const ENODEV: c_int = 19;
pub const EPIPE: c_int = 32;

// Signals.
pub const SIGHUP: c_int = 1;
pub const SIGINT: c_int = 2;
pub const SIGPIPE: c_int = 13;
pub const SIGTERM: c_int = 15;
pub const SIG_IGN: usize = 1;

// Open / socket / poll / inotify constants.
pub const O_RDONLY: c_int = 0;
pub const O_NONBLOCK: c_int = 0o4000;
pub const O_DIRECTORY: c_int = 0o200000;
pub const O_CLOEXEC: c_int = 0o2000000;

pub const AF_UNIX: c_int = 1;
pub const SOCK_STREAM: c_int = 1;
pub const SOCK_NONBLOCK: c_int = 0o4000;
pub const SOCK_CLOEXEC: c_int = 0o2000000;
pub const SOL_SOCKET: c_int = 1;
pub const SO_PEERCRED: c_int = 17;
pub const MSG_DONTWAIT: c_int = 0x40;
pub const MSG_NOSIGNAL: c_int = 0x4000;

pub const POLLIN: i16 = 0x0001;
pub const POLLERR: i16 = 0x0008;
pub const POLLHUP: i16 = 0x0010;
pub const POLLNVAL: i16 = 0x0020;

pub const IN_NONBLOCK: c_int = 0o4000;
pub const IN_CLOEXEC: c_int = 0o2000000;
pub const IN_MOVED_TO: u32 = 0x0000_0080;
pub const IN_CREATE: u32 = 0x0000_0100;
pub const IN_DELETE: u32 = 0x0000_0200;
pub const IN_ATTRIB: u32 = 0x0000_0004;

pub const CLOCK_REALTIME: c_int = 0;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Timespec {
    pub tv_sec: c_long,
    pub tv_nsec: c_long,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct PollFd {
    pub fd: c_int,
    pub events: i16,
    pub revents: i16,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct SockaddrUn {
    pub sun_family: u16,
    pub sun_path: [u8; 108],
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Ucred {
    pub pid: pid_t,
    pub uid: uid_t,
    pub gid: uid_t,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct InotifyEvent {
    pub wd: c_int,
    pub mask: u32,
    pub cookie: u32,
    pub len: u32,
}

extern "C" {
    pub fn __errno_location() -> *mut c_int;
    pub fn open(pathname: *const c_char, flags: c_int, ...) -> c_int;
    pub fn close(fd: c_int) -> c_int;
    pub fn read(fd: c_int, buf: *mut c_void, count: usize) -> isize;
    pub fn write(fd: c_int, buf: *const c_void, count: usize) -> isize;
    pub fn ioctl(fd: c_int, request: c_ulong, ...) -> c_int;
    pub fn poll(fds: *mut PollFd, nfds: c_ulong, timeout: c_int) -> c_int;
    pub fn pipe2(fds: *mut c_int, flags: c_int) -> c_int;
    pub fn socket(domain: c_int, ty: c_int, protocol: c_int) -> c_int;
    pub fn bind(sockfd: c_int, addr: *const SockaddrUn, addrlen: socklen_t) -> c_int;
    pub fn listen(sockfd: c_int, backlog: c_int) -> c_int;
    pub fn accept4(
        sockfd: c_int,
        addr: *mut c_void,
        addrlen: *mut socklen_t,
        flags: c_int,
    ) -> c_int;
    pub fn send(sockfd: c_int, buf: *const c_void, len: usize, flags: c_int) -> isize;
    pub fn getsockopt(
        sockfd: c_int,
        level: c_int,
        optname: c_int,
        optval: *mut c_void,
        optlen: *mut socklen_t,
    ) -> c_int;
    pub fn chmod(pathname: *const c_char, mode: mode_t) -> c_int;
    pub fn inotify_init1(flags: c_int) -> c_int;
    pub fn inotify_add_watch(fd: c_int, pathname: *const c_char, mask: u32) -> c_int;
    pub fn geteuid() -> uid_t;
    pub fn clock_gettime(clk_id: c_int, tp: *mut Timespec) -> c_int;
    pub fn signal(signum: c_int, handler: usize) -> usize;
    pub fn kill(pid: pid_t, sig: c_int) -> c_int;
    pub fn fork() -> pid_t;
    pub fn execvp(file: *const c_char, argv: *const *const c_char) -> c_int;
    pub fn waitpid(pid: pid_t, status: *mut c_int, options: c_int) -> pid_t;
    pub fn _exit(status: c_int) -> !;
}

#[inline]
pub fn last_errno() -> c_int {
    unsafe { *__errno_location() }
}

/// Current wall-clock `(sec, usec)` suitable for `struct input_event` timestamps.
pub fn realtime_sec_usec() -> (c_long, c_long) {
    let mut ts = Timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    unsafe {
        if clock_gettime(CLOCK_REALTIME, &mut ts) == 0 {
            return (ts.tv_sec, ts.tv_nsec / 1000);
        }
    }
    (0, 0)
}

pub fn eviocgid(fd: c_int) -> Option<InputId> {
    let mut id = InputId::default();
    let req = ioc(
        IOC_READ,
        EVDEV_IOCTL_BASE,
        EVIOCGID_NR,
        size_of::<InputId>() as u32,
    );
    let rc = unsafe { ioctl(fd, req, &mut id as *mut InputId) };
    if rc >= 0 {
        Some(id)
    } else {
        None
    }
}

pub fn eviocg_string(fd: c_int, nr: u32, buf: &mut [u8]) -> usize {
    if buf.is_empty() {
        return 0;
    }
    buf.fill(0);
    let req = ioc(IOC_READ, EVDEV_IOCTL_BASE, nr, buf.len() as u32);
    let rc = unsafe { ioctl(fd, req, buf.as_mut_ptr()) };
    if rc < 0 {
        return 0;
    }
    buf.iter().position(|&b| b == 0).unwrap_or(buf.len())
}

pub fn eviocgname(fd: c_int, buf: &mut [u8]) -> usize {
    eviocg_string(fd, EVIOCGNAME_NR, buf)
}

pub fn eviocgphys(fd: c_int, buf: &mut [u8]) -> usize {
    eviocg_string(fd, EVIOCGPHYS_NR, buf)
}

pub fn eviocguniq(fd: c_int, buf: &mut [u8]) -> usize {
    eviocg_string(fd, EVIOCGUNIQ_NR, buf)
}

pub fn eviocgbit(fd: c_int, ev_type: u32, buf: &mut [u8]) -> bool {
    buf.fill(0);
    let req = ioc(
        IOC_READ,
        EVDEV_IOCTL_BASE,
        EVIOCGBIT_BASE_NR + ev_type,
        buf.len() as u32,
    );
    unsafe { ioctl(fd, req, buf.as_mut_ptr()) >= 0 }
}

pub fn eviocgprop(fd: c_int, buf: &mut [u8]) -> bool {
    buf.fill(0);
    let req = ioc(IOC_READ, EVDEV_IOCTL_BASE, EVIOCGPROP_NR, buf.len() as u32);
    unsafe { ioctl(fd, req, buf.as_mut_ptr()) >= 0 }
}

pub fn eviocgkey(fd: c_int, buf: &mut [u8]) -> bool {
    buf.fill(0);
    let req = ioc(IOC_READ, EVDEV_IOCTL_BASE, EVIOCGKEY_NR, buf.len() as u32);
    unsafe { ioctl(fd, req, buf.as_mut_ptr()) >= 0 }
}

pub fn eviocgabs(fd: c_int, abs_code: u32) -> Option<InputAbsInfo> {
    let mut info: InputAbsInfo = unsafe { zeroed() };
    let req = ioc(
        IOC_READ,
        EVDEV_IOCTL_BASE,
        EVIOCGABS_BASE_NR + abs_code,
        size_of::<InputAbsInfo>() as u32,
    );
    let rc = unsafe { ioctl(fd, req, &mut info as *mut InputAbsInfo) };
    if rc >= 0 {
        Some(info)
    } else {
        None
    }
}
