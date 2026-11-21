//! Low-level POSIX/glibc ABI declarations, recursive mutex wrapper, and
//! `dlsym(RTLD_NEXT)` resolver for the userspace uinput interposer.
//!
//! No `std::fs` or `std::net` calls are made anywhere in this crate so that
//! interposed `open`/`read`/`write`/`close` hooks can never re-enter themselves.

#![allow(non_camel_case_types, dead_code)]

use core::cell::UnsafeCell;
use core::ffi::{c_char, c_int, c_long, c_ulong, c_void};
use core::mem::{align_of, offset_of, size_of};
use core::ops::{Deref, DerefMut};
use core::ptr;
use core::sync::atomic::{AtomicBool, AtomicPtr, Ordering};
use twinverse_uinput_proto::{
    cstr_bytes, fmt_u32, hidraw_allow_contains, write_cstr_parts, ENV_DEBUG_LOG,
    ENV_HIDRAW_FILTER, ENV_PHYSICAL_BRIDGE, ENV_SOCKET_DIR, HIDRAW_ALLOW_BYTES,
};

pub type size_t = usize;
pub type ssize_t = isize;
pub type mode_t = u32;
pub type pid_t = c_int;
pub type uid_t = u32;
pub type socklen_t = u32;

// Linux errno constants.
pub const EINTR: c_int = 4;
pub const EIO: c_int = 5;
pub const EBADF: c_int = 9;
pub const EAGAIN: c_int = 11;
pub const EWOULDBLOCK: c_int = EAGAIN;
pub const ENOMEM: c_int = 12;
pub const EFAULT: c_int = 14;
pub const ENODEV: c_int = 19;
pub const EINVAL: c_int = 22;
pub const ENFILE: c_int = 23;
pub const ENOTTY: c_int = 25;
pub const ENOSPC: c_int = 28;
pub const ENOSYS: c_int = 38;
pub const ENOENT: c_int = 2;
pub const EADDRINUSE: c_int = 98;
pub const ECONNREFUSED: c_int = 111;

// Open / fcntl / access constants.
pub const F_OK: c_int = 0;
pub const W_OK: c_int = 2;
pub const O_RDONLY: c_int = 0;
pub const O_WRONLY: c_int = 1;
pub const O_CREAT: c_int = 0o100;
pub const O_TRUNC: c_int = 0o1000;
pub const O_NONBLOCK: c_int = 0o4000;
pub const O_DIRECTORY: c_int = 0o200000;
pub const O_CLOEXEC: c_int = 0o2000000;
pub const O_TMPFILE: c_int = 0o20200000;
pub const AT_FDCWD: c_int = -100;
pub const F_GETFL: c_int = 3;
pub const F_SETFL: c_int = 4;

// Socket / poll / clock constants.
pub const AF_UNIX: c_int = 1;
pub const SOCK_STREAM: c_int = 1;
pub const SOCK_NONBLOCK: c_int = 0o4000;
pub const SOCK_CLOEXEC: c_int = 0o2000000;
pub const SOL_SOCKET: c_int = 1;
pub const SO_PEERCRED: c_int = 17;
pub const MSG_PEEK: c_int = 0x2;
pub const MSG_DONTWAIT: c_int = 0x40;
pub const MSG_NOSIGNAL: c_int = 0x4000;
pub const POLLIN: i16 = 0x0001;
pub const POLLOUT: i16 = 0x0004;
pub const CLOCK_MONOTONIC: c_int = 1;

// Stat / dirent constants.
pub const S_IFCHR: u32 = 0o020000;
pub const DT_CHR: u8 = 2;
pub const PATH_MAX: usize = 4096;
pub const NAME_MAX: usize = 255;

// Inotify constants.
pub const IN_MOVED_FROM: u32 = 0x0000_0040;
pub const IN_MOVED_TO: u32 = 0x0000_0080;
pub const IN_CREATE: u32 = 0x0000_0100;
pub const IN_DELETE: u32 = 0x0000_0200;
pub const IN_ONLYDIR: u32 = 0x0100_0000;

// dlfcn / pthread constants.
pub const RTLD_NEXT: *mut c_void = -1isize as *mut c_void;
pub const PTHREAD_MUTEX_RECURSIVE: c_int = 1;

#[inline]
pub fn needs_mode(flags: c_int) -> bool {
    (flags & O_CREAT) != 0 || (flags & O_TMPFILE) == O_TMPFILE
}

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

#[cfg(target_arch = "x86_64")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Stat {
    pub st_dev: u64,
    pub st_ino: u64,
    pub st_nlink: u64,
    pub st_mode: u32,
    pub st_uid: u32,
    pub st_gid: u32,
    pub __pad0: u32,
    pub st_rdev: u64,
    pub st_size: i64,
    pub st_blksize: i64,
    pub st_blocks: i64,
    pub st_atim: Timespec,
    pub st_mtim: Timespec,
    pub st_ctim: Timespec,
    pub __glibc_reserved: [i64; 3],
}

#[cfg(target_arch = "x86_64")]
pub type Stat64 = Stat;

#[cfg(target_arch = "x86")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Stat {
    pub st_dev: u64,
    pub __pad1: u16,
    pub __pad1b: u16,
    pub st_ino: u32,
    pub st_mode: u32,
    pub st_nlink: u32,
    pub st_uid: u32,
    pub st_gid: u32,
    pub st_rdev: u64,
    pub __pad2: u16,
    pub __pad2b: u16,
    pub st_size: i32,
    pub st_blksize: i32,
    pub st_blocks: i32,
    pub st_atim: Timespec,
    pub st_mtim: Timespec,
    pub st_ctim: Timespec,
    pub __glibc_reserved4: u32,
    pub __glibc_reserved5: u32,
}

#[cfg(target_arch = "x86")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Stat64 {
    pub st_dev: u64,
    pub __pad1: u32,
    pub __st_ino: u32,
    pub st_mode: u32,
    pub st_nlink: u32,
    pub st_uid: u32,
    pub st_gid: u32,
    pub st_rdev: u64,
    pub __pad2: u32,
    pub st_size: i64,
    pub st_blksize: i32,
    pub st_blocks: i64,
    pub st_atim: Timespec,
    pub st_mtim: Timespec,
    pub st_ctim: Timespec,
    pub st_ino: u64,
}

#[cfg(target_arch = "x86_64")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Dirent {
    pub d_ino: u64,
    pub d_off: i64,
    pub d_reclen: u16,
    pub d_type: u8,
    pub d_name: [c_char; 256],
}

#[cfg(target_arch = "x86_64")]
pub type Dirent64 = Dirent;

#[cfg(target_arch = "x86")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Dirent {
    pub d_ino: u32,
    pub d_off: i32,
    pub d_reclen: u16,
    pub d_type: u8,
    pub d_name: [c_char; 256],
}

#[cfg(target_arch = "x86")]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Dirent64 {
    pub d_ino: u64,
    pub d_off: i64,
    pub d_reclen: u16,
    pub d_type: u8,
    pub d_name: [c_char; 256],
}

#[repr(C)]
pub struct DIR {
    _opaque: [u8; 0],
}

#[cfg(target_arch = "x86_64")]
#[repr(C, align(8))]
pub struct PthreadMutexT {
    _data: [u8; 40],
}

#[cfg(target_arch = "x86")]
#[repr(C, align(4))]
pub struct PthreadMutexT {
    _data: [u8; 24],
}

#[repr(C, align(4))]
pub struct PthreadMutexAttrT {
    _data: [u8; 4],
}

pub type PthreadT = c_ulong;

// Compile-time verification against glibc x86_64 and i686 ABI layouts.
const _: () = {
    assert!(size_of::<SockaddrUn>() == 110);
    assert!(size_of::<Ucred>() == 12);
    assert!(size_of::<PollFd>() == 8);
    assert!(size_of::<InotifyEvent>() == 16);
    assert!(size_of::<PthreadMutexAttrT>() == 4);

    #[cfg(target_arch = "x86_64")]
    {
        assert!(size_of::<Stat>() == 144);
        assert!(align_of::<Stat>() == 8);
        assert!(offset_of!(Stat, st_mode) == 24);
        assert!(offset_of!(Stat, st_uid) == 28);
        assert!(offset_of!(Stat, st_rdev) == 40);
        assert!(offset_of!(Stat, st_size) == 48);
        assert!(size_of::<Dirent>() == 280);
        assert!(offset_of!(Dirent, d_name) == 19);
        assert!(size_of::<PthreadMutexT>() == 40);
        assert!(size_of::<PthreadT>() == 8);
    }

    #[cfg(target_arch = "x86")]
    {
        assert!(size_of::<Stat>() == 88);
        assert!(align_of::<Stat>() == 4);
        assert!(offset_of!(Stat, st_ino) == 12);
        assert!(offset_of!(Stat, st_mode) == 16);
        assert!(offset_of!(Stat, st_uid) == 24);
        assert!(offset_of!(Stat, st_rdev) == 32);
        assert!(offset_of!(Stat, st_size) == 44);
        assert!(size_of::<Stat64>() == 96);
        assert!(offset_of!(Stat64, st_mode) == 16);
        assert!(offset_of!(Stat64, st_rdev) == 32);
        assert!(offset_of!(Stat64, st_ino) == 88);
        assert!(size_of::<Dirent>() == 268);
        assert!(offset_of!(Dirent, d_name) == 11);
        assert!(size_of::<Dirent64>() == 276);
        assert!(offset_of!(Dirent64, d_name) == 19);
        assert!(size_of::<PthreadMutexT>() == 24);
        assert!(size_of::<PthreadT>() == 4);
    }
};

extern "C" {
    pub fn __errno_location() -> *mut c_int;
    pub fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    pub fn getenv(name: *const c_char) -> *const c_char;
    pub fn getpid() -> pid_t;
    pub fn geteuid() -> uid_t;
    pub fn socket(domain: c_int, ty: c_int, protocol: c_int) -> c_int;
    pub fn socketpair(domain: c_int, ty: c_int, protocol: c_int, sv: *mut [c_int; 2]) -> c_int;
    pub fn bind(sockfd: c_int, addr: *const c_void, addrlen: socklen_t) -> c_int;
    pub fn listen(sockfd: c_int, backlog: c_int) -> c_int;
    pub fn accept4(
        sockfd: c_int,
        addr: *mut c_void,
        addrlen: *mut socklen_t,
        flags: c_int,
    ) -> c_int;
    pub fn connect(sockfd: c_int, addr: *const c_void, addrlen: socklen_t) -> c_int;
    pub fn send(sockfd: c_int, buf: *const c_void, len: size_t, flags: c_int) -> ssize_t;
    pub fn recv(sockfd: c_int, buf: *mut c_void, len: size_t, flags: c_int) -> ssize_t;
    pub fn getsockopt(
        sockfd: c_int,
        level: c_int,
        optname: c_int,
        optval: *mut c_void,
        optlen: *mut socklen_t,
    ) -> c_int;
    pub fn poll(fds: *mut PollFd, nfds: c_ulong, timeout: c_int) -> c_int;
    pub fn pipe2(fds: *mut [c_int; 2], flags: c_int) -> c_int;
    pub fn fcntl(fd: c_int, cmd: c_int, ...) -> c_int;
    pub fn unlink(path: *const c_char) -> c_int;
    pub fn rename(old: *const c_char, new: *const c_char) -> c_int;
    pub fn readlink(path: *const c_char, buf: *mut c_char, bufsiz: size_t) -> ssize_t;
    pub fn clock_gettime(clk_id: c_int, tp: *mut Timespec) -> c_int;
    pub fn malloc(size: size_t) -> *mut c_void;
    pub fn realloc(ptr: *mut c_void, size: size_t) -> *mut c_void;
    pub fn free(ptr: *mut c_void);
    pub fn strdup(s: *const c_char) -> *mut c_char;
    pub fn qsort(
        base: *mut c_void,
        nmemb: size_t,
        size: size_t,
        compar: unsafe extern "C" fn(*const c_void, *const c_void) -> c_int,
    );
    pub fn pthread_mutexattr_init(attr: *mut PthreadMutexAttrT) -> c_int;
    pub fn pthread_mutexattr_settype(attr: *mut PthreadMutexAttrT, kind: c_int) -> c_int;
    pub fn pthread_mutexattr_destroy(attr: *mut PthreadMutexAttrT) -> c_int;
    pub fn pthread_mutex_init(mutex: *mut PthreadMutexT, attr: *const PthreadMutexAttrT) -> c_int;
    pub fn pthread_mutex_lock(mutex: *mut PthreadMutexT) -> c_int;
    pub fn pthread_mutex_unlock(mutex: *mut PthreadMutexT) -> c_int;
    pub fn pthread_create(
        thread: *mut PthreadT,
        attr: *const c_void,
        start_routine: unsafe extern "C" fn(*mut c_void) -> *mut c_void,
        arg: *mut c_void,
    ) -> c_int;
    pub fn pthread_join(thread: PthreadT, retval: *mut *mut c_void) -> c_int;
}

#[inline]
pub unsafe fn get_errno() -> c_int {
    *__errno_location()
}

#[inline]
pub unsafe fn set_errno(e: c_int) {
    *__errno_location() = e;
}

/// Recursive pthread mutex suitable for `LD_PRELOAD` hooks (signal/re-entrancy safe).
pub struct RecursiveMutex<T> {
    raw: UnsafeCell<PthreadMutexT>,
    inited: AtomicBool,
    data: UnsafeCell<T>,
}

unsafe impl<T: Send> Sync for RecursiveMutex<T> {}
unsafe impl<T: Send> Send for RecursiveMutex<T> {}

impl<T> RecursiveMutex<T> {
    pub const fn new(val: T) -> Self {
        #[cfg(target_arch = "x86_64")]
        let raw = PthreadMutexT { _data: [0; 40] };
        #[cfg(target_arch = "x86")]
        let raw = PthreadMutexT { _data: [0; 24] };
        Self {
            raw: UnsafeCell::new(raw),
            inited: AtomicBool::new(false),
            data: UnsafeCell::new(val),
        }
    }

    /// Initialize as `PTHREAD_MUTEX_RECURSIVE` (call from `.init_array` before threads spawn).
    pub unsafe fn init_recursive(&self) {
        if self
            .inited
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            let mut attr = PthreadMutexAttrT { _data: [0; 4] };
            if pthread_mutexattr_init(&mut attr) == 0 {
                pthread_mutexattr_settype(&mut attr, PTHREAD_MUTEX_RECURSIVE);
                pthread_mutex_init(self.raw.get(), &attr);
                pthread_mutexattr_destroy(&mut attr);
            }
        }
    }

    #[inline]
    pub unsafe fn lock(&self) -> RecursiveGuard<'_, T> {
        // Static zero-initialized pthread_mutex_t on glibc is already a valid
        // default mutex even if a hook runs before `.init_array`.
        pthread_mutex_lock(self.raw.get());
        RecursiveGuard { mutex: self }
    }

    #[inline]
    pub unsafe fn unlock_raw(&self) {
        pthread_mutex_unlock(self.raw.get());
    }

    #[inline]
    pub unsafe fn lock_raw(&self) {
        pthread_mutex_lock(self.raw.get());
    }
}

pub struct RecursiveGuard<'a, T> {
    mutex: &'a RecursiveMutex<T>,
}

impl<T> Deref for RecursiveGuard<'_, T> {
    type Target = T;
    #[inline]
    fn deref(&self) -> &T {
        unsafe { &*self.mutex.data.get() }
    }
}

impl<T> DerefMut for RecursiveGuard<'_, T> {
    #[inline]
    fn deref_mut(&mut self) -> &mut T {
        unsafe { &mut *self.mutex.data.get() }
    }
}

impl<T> Drop for RecursiveGuard<'_, T> {
    #[inline]
    fn drop(&mut self) {
        unsafe {
            pthread_mutex_unlock(self.mutex.raw.get());
        }
    }
}

// Function pointer types for real libc symbols resolved via `dlsym(RTLD_NEXT)`.
pub type AccessFn = unsafe extern "C" fn(*const c_char, c_int) -> c_int;
pub type OpenFn = unsafe extern "C" fn(*const c_char, c_int, ...) -> c_int;
pub type OpenAtFn = unsafe extern "C" fn(c_int, *const c_char, c_int, ...) -> c_int;
pub type Open2Fn = unsafe extern "C" fn(*const c_char, c_int) -> c_int;
pub type OpenAt2Fn = unsafe extern "C" fn(c_int, *const c_char, c_int) -> c_int;
pub type CloseFn = unsafe extern "C" fn(c_int) -> c_int;
pub type ReadFn = unsafe extern "C" fn(c_int, *mut c_void, size_t) -> ssize_t;
pub type ReadChkFn = unsafe extern "C" fn(c_int, *mut c_void, size_t, size_t) -> ssize_t;
pub type WriteFn = unsafe extern "C" fn(c_int, *const c_void, size_t) -> ssize_t;
pub type IoctlFn = unsafe extern "C" fn(c_int, c_ulong, ...) -> c_int;
pub type StatFn = unsafe extern "C" fn(*const c_char, *mut Stat) -> c_int;
pub type FstatFn = unsafe extern "C" fn(c_int, *mut Stat) -> c_int;
pub type Stat64Fn = unsafe extern "C" fn(*const c_char, *mut Stat64) -> c_int;
pub type Fstat64Fn = unsafe extern "C" fn(c_int, *mut Stat64) -> c_int;
pub type XstatFn = unsafe extern "C" fn(c_int, *const c_char, *mut Stat) -> c_int;
pub type FxstatFn = unsafe extern "C" fn(c_int, c_int, *mut Stat) -> c_int;
pub type Xstat64Fn = unsafe extern "C" fn(c_int, *const c_char, *mut Stat64) -> c_int;
pub type Fxstat64Fn = unsafe extern "C" fn(c_int, c_int, *mut Stat64) -> c_int;
pub type OpendirFn = unsafe extern "C" fn(*const c_char) -> *mut DIR;
pub type ReaddirFn = unsafe extern "C" fn(*mut DIR) -> *mut Dirent;
pub type Readdir64Fn = unsafe extern "C" fn(*mut DIR) -> *mut Dirent64;
pub type ClosedirFn = unsafe extern "C" fn(*mut DIR) -> c_int;
pub type ScandirFilterFn = Option<unsafe extern "C" fn(*const Dirent) -> c_int>;
pub type ScandirComparFn =
    Option<unsafe extern "C" fn(*mut *const Dirent, *mut *const Dirent) -> c_int>;
pub type ScandirFn = unsafe extern "C" fn(
    *const c_char,
    *mut *mut *mut Dirent,
    ScandirFilterFn,
    ScandirComparFn,
) -> c_int;
pub type Scandir64FilterFn = Option<unsafe extern "C" fn(*const Dirent64) -> c_int>;
pub type Scandir64ComparFn =
    Option<unsafe extern "C" fn(*mut *const Dirent64, *mut *const Dirent64) -> c_int>;
pub type Scandir64Fn = unsafe extern "C" fn(
    *const c_char,
    *mut *mut *mut Dirent64,
    Scandir64FilterFn,
    Scandir64ComparFn,
) -> c_int;
pub type InotifyAddWatchFn = unsafe extern "C" fn(c_int, *const c_char, u32) -> c_int;
pub type InotifyRmWatchFn = unsafe extern "C" fn(c_int, c_int) -> c_int;
pub type RealpathFn = unsafe extern "C" fn(*const c_char, *mut c_char) -> *mut c_char;

macro_rules! real_sym {
    ($fn_name:ident, $static_name:ident, $c_name:literal, $ty:ty) => {
        static $static_name: AtomicPtr<c_void> = AtomicPtr::new(ptr::null_mut());

        #[inline]
        #[allow(non_snake_case)]
        pub unsafe fn $fn_name() -> Option<$ty> {
            let mut p = $static_name.load(Ordering::Acquire);
            if p.is_null() {
                p = dlsym(RTLD_NEXT, concat!($c_name, "\0").as_ptr() as *const c_char);
                if !p.is_null() {
                    $static_name.store(p, Ordering::Release);
                }
            }
            if p.is_null() {
                None
            } else {
                Some(core::mem::transmute::<*mut c_void, $ty>(p))
            }
        }
    };
}

real_sym!(real_access, REAL_ACCESS, "access", AccessFn);
real_sym!(real_open, REAL_OPEN, "open", OpenFn);
real_sym!(real_open64, REAL_OPEN64, "open64", OpenFn);
real_sym!(real_openat, REAL_OPENAT, "openat", OpenAtFn);
real_sym!(real_openat64, REAL_OPENAT64, "openat64", OpenAtFn);
real_sym!(real___open_2, REAL___OPEN_2, "__open_2", Open2Fn);
real_sym!(real___open64_2, REAL___OPEN64_2, "__open64_2", Open2Fn);
real_sym!(real___openat_2, REAL___OPENAT_2, "__openat_2", OpenAt2Fn);
real_sym!(
    real___openat64_2,
    REAL___OPENAT64_2,
    "__openat64_2",
    OpenAt2Fn
);
real_sym!(real_close, REAL_CLOSE, "close", CloseFn);
real_sym!(real_read, REAL_READ, "read", ReadFn);
real_sym!(real___read_chk, REAL___READ_CHK, "__read_chk", ReadChkFn);
real_sym!(real_write, REAL_WRITE, "write", WriteFn);
real_sym!(real_ioctl, REAL_IOCTL, "ioctl", IoctlFn);
real_sym!(real_stat, REAL_STAT, "stat", StatFn);
real_sym!(real_lstat, REAL_LSTAT, "lstat", StatFn);
real_sym!(real_fstat, REAL_FSTAT, "fstat", FstatFn);
real_sym!(real_stat64, REAL_STAT64, "stat64", Stat64Fn);
real_sym!(real_lstat64, REAL_LSTAT64, "lstat64", Stat64Fn);
real_sym!(real_fstat64, REAL_FSTAT64, "fstat64", Fstat64Fn);
real_sym!(real___xstat, REAL___XSTAT, "__xstat", XstatFn);
real_sym!(real___lxstat, REAL___LXSTAT, "__lxstat", XstatFn);
real_sym!(real___fxstat, REAL___FXSTAT, "__fxstat", FxstatFn);
real_sym!(real___xstat64, REAL___XSTAT64, "__xstat64", Xstat64Fn);
real_sym!(real___lxstat64, REAL___LXSTAT64, "__lxstat64", Xstat64Fn);
real_sym!(real___fxstat64, REAL___FXSTAT64, "__fxstat64", Fxstat64Fn);
real_sym!(real_opendir, REAL_OPENDIR, "opendir", OpendirFn);
real_sym!(real_readdir, REAL_READDIR, "readdir", ReaddirFn);
real_sym!(real_readdir64, REAL_READDIR64, "readdir64", Readdir64Fn);
real_sym!(real_closedir, REAL_CLOSEDIR, "closedir", ClosedirFn);
real_sym!(real_scandir, REAL_SCANDIR, "scandir", ScandirFn);
real_sym!(real_scandir64, REAL_SCANDIR64, "scandir64", Scandir64Fn);
real_sym!(
    real_inotify_add_watch,
    REAL_INOTIFY_ADD_WATCH,
    "inotify_add_watch",
    InotifyAddWatchFn
);
real_sym!(
    real_inotify_rm_watch,
    REAL_INOTIFY_RM_WATCH,
    "inotify_rm_watch",
    InotifyRmWatchFn
);
real_sym!(real_realpath, REAL_REALPATH, "realpath", RealpathFn);

/// Pre-resolve frequently used real libc symbols at library load time.
pub unsafe fn preload_real_symbols() {
    let _ = real_access();
    let _ = real_open();
    let _ = real_open64();
    let _ = real_openat();
    let _ = real_openat64();
    let _ = real___open_2();
    let _ = real___open64_2();
    let _ = real___openat_2();
    let _ = real___openat64_2();
    let _ = real_close();
    let _ = real_read();
    let _ = real___read_chk();
    let _ = real_write();
    let _ = real_ioctl();
    let _ = real_stat();
    let _ = real_lstat();
    let _ = real_fstat();
    let _ = real_stat64();
    let _ = real_lstat64();
    let _ = real_fstat64();
    let _ = real_opendir();
    let _ = real_readdir();
    let _ = real_readdir64();
    let _ = real_closedir();
    let _ = real_scandir();
    let _ = real_scandir64();
    let _ = real_inotify_add_watch();
    let _ = real_inotify_rm_watch();
    let _ = real_realpath();
}

static LOG_ENABLED: AtomicBool = AtomicBool::new(false);

pub unsafe fn init_logging() {
    let p = getenv(ENV_DEBUG_LOG.as_ptr() as *const c_char);
    if !p.is_null() && *p != 0 && *p != b'0' as c_char {
        LOG_ENABLED.store(true, Ordering::Release);
    }
}

#[inline]
pub fn log_enabled() -> bool {
    LOG_ENABLED.load(Ordering::Relaxed)
}

/// Write a diagnostic line directly to stderr using `real_write` (never recurses).
pub unsafe fn debug_log_bytes(msg: &[u8]) {
    if !log_enabled() {
        return;
    }
    if let Some(w) = real_write() {
        let saved = get_errno();
        let _ = w(2, msg.as_ptr() as *const c_void, msg.len());
        set_errno(saved);
    }
}

/// Resolve the socket directory from `TWINVERSE_UINPUT_SOCKET_DIR`, falling back
/// to `XDG_RUNTIME_DIR`, then `/tmp`.
pub unsafe fn socket_dir_bytes<'a>() -> &'a [u8] {
    let p = getenv(ENV_SOCKET_DIR.as_ptr() as *const c_char);
    if let Some(b) = cstr_bytes(p) {
        if !b.is_empty() {
            return b;
        }
    }
    let xdg = getenv(b"XDG_RUNTIME_DIR\0".as_ptr() as *const c_char);
    if let Some(b) = cstr_bytes(xdg) {
        if !b.is_empty() {
            return b;
        }
    }
    b"/tmp"
}

pub unsafe fn format_sock_path(event_num: i32, out: &mut [u8]) -> Option<usize> {
    let dir = socket_dir_bytes();
    let mut nbuf = [0u8; 16];
    let num = fmt_u32(event_num as u32, &mut nbuf);
    write_cstr_parts(out, &[dir, b"/tw_event", num, b".sock"])
}

pub unsafe fn format_desc_path(event_num: i32, out: &mut [u8]) -> Option<usize> {
    let dir = socket_dir_bytes();
    let mut nbuf = [0u8; 16];
    let num = fmt_u32(event_num as u32, &mut nbuf);
    write_cstr_parts(out, &[dir, b"/tw_event", num, b".desc"])
}

pub unsafe fn format_hidraw_allow_path(out: &mut [u8]) -> Option<usize> {
    let dir = socket_dir_bytes();
    write_cstr_parts(out, &[dir, b"/", HIDRAW_ALLOW_BYTES])
}

#[inline]
pub unsafe fn physical_bridge_enabled() -> bool {
    let p = getenv(ENV_PHYSICAL_BRIDGE.as_ptr() as *const c_char);
    !p.is_null() && *p == b'1' as c_char
}

#[inline]
pub unsafe fn hidraw_filter_enabled() -> bool {
    let p = getenv(ENV_HIDRAW_FILTER.as_ptr() as *const c_char);
    !p.is_null() && *p == b'1' as c_char
}

/// Return true when dynamic `/dev/hidraw*` filtering is enabled and `basename`
/// (e.g. `b"hidraw2"`) is NOT currently present in `<socket_dir>/tw_hidraw.allow`.
pub unsafe fn is_hidraw_blocked(basename: &[u8]) -> bool {
    if !hidraw_filter_enabled() {
        return false;
    }
    let saved = get_errno();
    let mut path = [0u8; 256];
    let mut allowed = false;
    if format_hidraw_allow_path(&mut path).is_some() {
        if let (Some(open_fn), Some(read_fn), Some(close_fn)) =
            (real_open(), real_read(), real_close())
        {
            let fd = open_fn(path.as_ptr() as *const c_char, O_RDONLY | O_CLOEXEC);
            if fd >= 0 {
                let mut buf = [0u8; 1024];
                let n = read_fn(fd, buf.as_mut_ptr() as *mut c_void, buf.len());
                let _ = close_fn(fd);
                if n > 0 {
                    allowed = hidraw_allow_contains(&buf[..n as usize], basename);
                }
            }
        }
    }
    set_errno(saved);
    !allowed
}

pub unsafe fn format_syspath(event_num: i32, out: &mut [u8]) -> Option<usize> {
    let mut nbuf = [0u8; 16];
    let num = fmt_u32(event_num as u32, &mut nbuf);
    write_cstr_parts(
        out,
        &[
            b"/sys/devices/virtual/twinverse_uinput",
            num,
            b"/input/input",
            num,
            b"/event",
            num,
        ],
    )
}

pub unsafe fn make_fd_nonblocking(fd: c_int) -> bool {
    let flags = fcntl(fd, F_GETFL, 0);
    if flags < 0 {
        return false;
    }
    if (flags & O_NONBLOCK) != 0 {
        return true;
    }
    fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0
}
