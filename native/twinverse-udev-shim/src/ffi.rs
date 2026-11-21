//! Raw Linux/glibc FFI declarations and dynamic loader for the real `libudev.so.1`.

#![allow(non_camel_case_types, dead_code)]

use std::env;
use std::ffi::{c_char, c_int, c_long, c_uint, c_ulonglong, c_void, CStr, CString};
use std::fs;
use std::mem::size_of;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::sync::OnceLock;

use twinverse_uinput_proto::{ENV_DEBUG_LOG, ENV_REAL_LIBUDEV, ENV_SOCKET_DIR};

pub type size_t = usize;
pub type ssize_t = isize;
pub type dev_t = u64;

pub const RTLD_LOCAL: c_int = 0x0;
pub const RTLD_NOW: c_int = 0x2;

pub const EINVAL: c_int = 22;
pub const ENOMEM: c_int = 12;
pub const ENOSYS: c_int = 38;
pub const EAGAIN: c_int = 11;

pub const IN_CREATE: u32 = 0x0000_0100;
pub const IN_DELETE: u32 = 0x0000_0200;
pub const IN_MOVED_TO: u32 = 0x0000_0080;
pub const IN_NONBLOCK: c_int = 0x800;
pub const IN_CLOEXEC: c_int = 0x80000;

pub const EFD_NONBLOCK: c_int = 0x800;
pub const EFD_CLOEXEC: c_int = 0x80000;

pub const EPOLL_CLOEXEC: c_int = 0x80000;
pub const EPOLL_CTL_ADD: c_int = 1;
pub const EPOLLIN: u32 = 0x001;

#[cfg(target_arch = "x86_64")]
pub const SYS_READ: c_long = 0;
#[cfg(target_arch = "x86_64")]
pub const SYS_WRITE: c_long = 1;

#[cfg(target_arch = "x86")]
pub const SYS_READ: c_long = 3;
#[cfg(target_arch = "x86")]
pub const SYS_WRITE: c_long = 4;

#[cfg(target_arch = "aarch64")]
pub const SYS_READ: c_long = 63;
#[cfg(target_arch = "aarch64")]
pub const SYS_WRITE: c_long = 64;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct DlInfo {
    pub dli_fname: *const c_char,
    pub dli_fbase: *mut c_void,
    pub dli_sname: *const c_char,
    pub dli_saddr: *mut c_void,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct InotifyEvent {
    pub wd: c_int,
    pub mask: u32,
    pub cookie: u32,
    pub len: u32,
}

#[cfg_attr(any(target_arch = "x86_64", target_arch = "x86"), repr(C, packed))]
#[cfg_attr(not(any(target_arch = "x86_64", target_arch = "x86")), repr(C))]
#[derive(Clone, Copy)]
pub struct EpollEvent {
    pub events: u32,
    pub data: u64,
}

const _: () = {
    assert!(size_of::<InotifyEvent>() == 16);
    #[cfg(any(target_arch = "x86_64", target_arch = "x86"))]
    assert!(size_of::<EpollEvent>() == 12);
    #[cfg(target_arch = "x86_64")]
    assert!(size_of::<DlInfo>() == 32);
    #[cfg(target_arch = "x86")]
    assert!(size_of::<DlInfo>() == 16);
};

extern "C" {
    pub fn __errno_location() -> *mut c_int;
    pub fn dlopen(filename: *const c_char, flags: c_int) -> *mut c_void;
    pub fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    pub fn dlclose(handle: *mut c_void) -> c_int;
    pub fn dladdr(addr: *const c_void, info: *mut DlInfo) -> c_int;
    pub fn fnmatch(pattern: *const c_char, string: *const c_char, flags: c_int) -> c_int;
    pub fn inotify_init1(flags: c_int) -> c_int;
    pub fn inotify_add_watch(fd: c_int, pathname: *const c_char, mask: u32) -> c_int;
    pub fn eventfd(initval: c_uint, flags: c_int) -> c_int;
    pub fn epoll_create1(flags: c_int) -> c_int;
    pub fn epoll_ctl(epfd: c_int, op: c_int, fd: c_int, event: *mut EpollEvent) -> c_int;
    pub fn close(fd: c_int) -> c_int;
    pub fn syscall(num: c_long, ...) -> c_long;
}

#[inline]
pub unsafe fn get_errno() -> c_int {
    *__errno_location()
}

/// Raw `read(2)` syscall bypassing any `LD_PRELOAD` `read` interposer.
#[inline]
pub unsafe fn raw_read(fd: c_int, buf: *mut u8, count: usize) -> isize {
    syscall(SYS_READ, fd as c_long, buf as *mut c_void, count) as isize
}

/// Raw `write(2)` syscall bypassing any `LD_PRELOAD` `write` interposer.
#[inline]
pub unsafe fn raw_write(fd: c_int, buf: *const u8, count: usize) -> isize {
    syscall(SYS_WRITE, fd as c_long, buf as *const c_void, count) as isize
}

pub fn log_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| {
        let key = std::str::from_utf8(&ENV_DEBUG_LOG[..ENV_DEBUG_LOG.len() - 1]).unwrap_or("");
        match env::var(key) {
            Ok(v) => !v.is_empty() && v != "0",
            Err(_) => false,
        }
    })
}

macro_rules! udev_log {
    ($($arg:tt)*) => {{
        if $crate::ffi::log_enabled() {
            let line = format!("[twinverse-udev] {}\n", format_args!($($arg)*));
            #[allow(unused_unsafe)]
            unsafe {
                let _ = $crate::ffi::raw_write(2, line.as_ptr(), line.len());
            }
        }
    }};
}
pub(crate) use udev_log;

/// Resolve the socket directory (`TWINVERSE_UINPUT_SOCKET_DIR` -> `XDG_RUNTIME_DIR` -> `/tmp`).
pub fn socket_dir() -> String {
    let key = std::str::from_utf8(&ENV_SOCKET_DIR[..ENV_SOCKET_DIR.len() - 1]).unwrap_or("");
    if let Ok(v) = env::var(key) {
        if !v.is_empty() {
            return v;
        }
    }
    if let Ok(v) = env::var("XDG_RUNTIME_DIR") {
        if !v.is_empty() {
            return v;
        }
    }
    "/tmp".to_string()
}

/// Opaque pointers for real libudev objects.
pub type RawUdev = *mut c_void;
pub type RawDevice = *mut c_void;
pub type RawEnumerate = *mut c_void;
pub type RawMonitor = *mut c_void;
pub type RawListEntry = *mut c_void;
pub type RawHwdb = *mut c_void;
pub type RawQueue = *mut c_void;

/// Function pointers resolved from the real system `libudev.so.1`.
pub struct RealUdev {
    pub loaded: bool,
    pub _handle: *mut c_void,

    pub udev_new: Option<unsafe extern "C" fn() -> RawUdev>,
    pub udev_ref: Option<unsafe extern "C" fn(RawUdev) -> RawUdev>,
    pub udev_unref: Option<unsafe extern "C" fn(RawUdev) -> RawUdev>,
    pub udev_get_userdata: Option<unsafe extern "C" fn(RawUdev) -> *mut c_void>,
    pub udev_set_userdata: Option<unsafe extern "C" fn(RawUdev, *mut c_void)>,

    pub udev_list_entry_get_next: Option<unsafe extern "C" fn(RawListEntry) -> RawListEntry>,
    pub udev_list_entry_get_by_name:
        Option<unsafe extern "C" fn(RawListEntry, *const c_char) -> RawListEntry>,
    pub udev_list_entry_get_name: Option<unsafe extern "C" fn(RawListEntry) -> *const c_char>,
    pub udev_list_entry_get_value: Option<unsafe extern "C" fn(RawListEntry) -> *const c_char>,

    pub udev_device_ref: Option<unsafe extern "C" fn(RawDevice) -> RawDevice>,
    pub udev_device_unref: Option<unsafe extern "C" fn(RawDevice) -> RawDevice>,
    pub udev_device_get_udev: Option<unsafe extern "C" fn(RawDevice) -> RawUdev>,
    pub udev_device_new_from_syspath:
        Option<unsafe extern "C" fn(RawUdev, *const c_char) -> RawDevice>,
    pub udev_device_new_from_devnum:
        Option<unsafe extern "C" fn(RawUdev, c_char, dev_t) -> RawDevice>,
    pub udev_device_new_from_subsystem_sysname:
        Option<unsafe extern "C" fn(RawUdev, *const c_char, *const c_char) -> RawDevice>,
    pub udev_device_new_from_device_id:
        Option<unsafe extern "C" fn(RawUdev, *const c_char) -> RawDevice>,
    pub udev_device_new_from_environment: Option<unsafe extern "C" fn(RawUdev) -> RawDevice>,
    pub udev_device_get_parent: Option<unsafe extern "C" fn(RawDevice) -> RawDevice>,
    pub udev_device_get_parent_with_subsystem_devtype:
        Option<unsafe extern "C" fn(RawDevice, *const c_char, *const c_char) -> RawDevice>,
    pub udev_device_get_devpath: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_subsystem: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_devtype: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_syspath: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_sysname: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_sysnum: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_devnode: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_is_initialized: Option<unsafe extern "C" fn(RawDevice) -> c_int>,
    pub udev_device_get_devlinks_list_entry:
        Option<unsafe extern "C" fn(RawDevice) -> RawListEntry>,
    pub udev_device_get_properties_list_entry:
        Option<unsafe extern "C" fn(RawDevice) -> RawListEntry>,
    pub udev_device_get_tags_list_entry: Option<unsafe extern "C" fn(RawDevice) -> RawListEntry>,
    pub udev_device_get_current_tags_list_entry:
        Option<unsafe extern "C" fn(RawDevice) -> RawListEntry>,
    pub udev_device_get_sysattr_list_entry: Option<unsafe extern "C" fn(RawDevice) -> RawListEntry>,
    pub udev_device_get_property_value:
        Option<unsafe extern "C" fn(RawDevice, *const c_char) -> *const c_char>,
    pub udev_device_get_driver: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_devnum: Option<unsafe extern "C" fn(RawDevice) -> dev_t>,
    pub udev_device_get_action: Option<unsafe extern "C" fn(RawDevice) -> *const c_char>,
    pub udev_device_get_seqnum: Option<unsafe extern "C" fn(RawDevice) -> c_ulonglong>,
    pub udev_device_get_usec_since_initialized:
        Option<unsafe extern "C" fn(RawDevice) -> c_ulonglong>,
    pub udev_device_get_sysattr_value:
        Option<unsafe extern "C" fn(RawDevice, *const c_char) -> *const c_char>,
    pub udev_device_set_sysattr_value:
        Option<unsafe extern "C" fn(RawDevice, *const c_char, *const c_char) -> c_int>,
    pub udev_device_has_tag: Option<unsafe extern "C" fn(RawDevice, *const c_char) -> c_int>,
    pub udev_device_has_current_tag:
        Option<unsafe extern "C" fn(RawDevice, *const c_char) -> c_int>,

    pub udev_monitor_ref: Option<unsafe extern "C" fn(RawMonitor) -> RawMonitor>,
    pub udev_monitor_unref: Option<unsafe extern "C" fn(RawMonitor) -> RawMonitor>,
    pub udev_monitor_get_udev: Option<unsafe extern "C" fn(RawMonitor) -> RawUdev>,
    pub udev_monitor_new_from_netlink:
        Option<unsafe extern "C" fn(RawUdev, *const c_char) -> RawMonitor>,
    pub udev_monitor_enable_receiving: Option<unsafe extern "C" fn(RawMonitor) -> c_int>,
    pub udev_monitor_set_receive_buffer_size:
        Option<unsafe extern "C" fn(RawMonitor, c_int) -> c_int>,
    pub udev_monitor_get_fd: Option<unsafe extern "C" fn(RawMonitor) -> c_int>,
    pub udev_monitor_receive_device: Option<unsafe extern "C" fn(RawMonitor) -> RawDevice>,
    pub udev_monitor_filter_add_match_subsystem_devtype:
        Option<unsafe extern "C" fn(RawMonitor, *const c_char, *const c_char) -> c_int>,
    pub udev_monitor_filter_add_match_tag:
        Option<unsafe extern "C" fn(RawMonitor, *const c_char) -> c_int>,
    pub udev_monitor_filter_update: Option<unsafe extern "C" fn(RawMonitor) -> c_int>,
    pub udev_monitor_filter_remove: Option<unsafe extern "C" fn(RawMonitor) -> c_int>,

    pub udev_enumerate_ref: Option<unsafe extern "C" fn(RawEnumerate) -> RawEnumerate>,
    pub udev_enumerate_unref: Option<unsafe extern "C" fn(RawEnumerate) -> RawEnumerate>,
    pub udev_enumerate_get_udev: Option<unsafe extern "C" fn(RawEnumerate) -> RawUdev>,
    pub udev_enumerate_new: Option<unsafe extern "C" fn(RawUdev) -> RawEnumerate>,
    pub udev_enumerate_add_match_subsystem:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_nomatch_subsystem:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_sysattr:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char, *const c_char) -> c_int>,
    pub udev_enumerate_add_nomatch_sysattr:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_property:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_sysname:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_tag:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_parent:
        Option<unsafe extern "C" fn(RawEnumerate, RawDevice) -> c_int>,
    pub udev_enumerate_add_match_is_initialized:
        Option<unsafe extern "C" fn(RawEnumerate) -> c_int>,
    pub udev_enumerate_add_syspath:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_sysnum:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_add_match_devicenode:
        Option<unsafe extern "C" fn(RawEnumerate, *const c_char) -> c_int>,
    pub udev_enumerate_scan_devices: Option<unsafe extern "C" fn(RawEnumerate) -> c_int>,
    pub udev_enumerate_scan_subsystems: Option<unsafe extern "C" fn(RawEnumerate) -> c_int>,
    pub udev_enumerate_scan_children:
        Option<unsafe extern "C" fn(RawEnumerate, RawDevice) -> c_int>,
    pub udev_enumerate_get_list_entry: Option<unsafe extern "C" fn(RawEnumerate) -> RawListEntry>,

    pub udev_queue_ref: Option<unsafe extern "C" fn(RawQueue) -> RawQueue>,
    pub udev_queue_unref: Option<unsafe extern "C" fn(RawQueue) -> RawQueue>,
    pub udev_queue_get_udev: Option<unsafe extern "C" fn(RawQueue) -> RawUdev>,
    pub udev_queue_new: Option<unsafe extern "C" fn(RawUdev) -> RawQueue>,
    pub udev_queue_get_kernel_seqnum: Option<unsafe extern "C" fn(RawQueue) -> c_ulonglong>,
    pub udev_queue_get_udev_seqnum: Option<unsafe extern "C" fn(RawQueue) -> c_ulonglong>,
    pub udev_queue_get_udev_is_active: Option<unsafe extern "C" fn(RawQueue) -> c_int>,
    pub udev_queue_get_queue_is_empty: Option<unsafe extern "C" fn(RawQueue) -> c_int>,
    pub udev_queue_get_seqnum_is_finished:
        Option<unsafe extern "C" fn(RawQueue, c_ulonglong) -> c_int>,
    pub udev_queue_get_seqnum_sequence_is_finished:
        Option<unsafe extern "C" fn(RawQueue, c_ulonglong, c_ulonglong) -> c_int>,
    pub udev_queue_get_fd: Option<unsafe extern "C" fn(RawQueue) -> c_int>,
    pub udev_queue_flush: Option<unsafe extern "C" fn(RawQueue) -> c_int>,
    pub udev_queue_get_queued_list_entry: Option<unsafe extern "C" fn(RawQueue) -> RawListEntry>,

    pub udev_hwdb_new: Option<unsafe extern "C" fn(RawUdev) -> RawHwdb>,
    pub udev_hwdb_ref: Option<unsafe extern "C" fn(RawHwdb) -> RawHwdb>,
    pub udev_hwdb_unref: Option<unsafe extern "C" fn(RawHwdb) -> RawHwdb>,
    pub udev_hwdb_get_properties_list_entry:
        Option<unsafe extern "C" fn(RawHwdb, *const c_char, c_uint) -> RawListEntry>,

    pub udev_util_encode_string:
        Option<unsafe extern "C" fn(*const c_char, *mut c_char, size_t) -> c_int>,
}

unsafe impl Sync for RealUdev {}
unsafe impl Send for RealUdev {}

impl RealUdev {
    fn empty() -> Self {
        Self {
            loaded: false,
            _handle: std::ptr::null_mut(),
            udev_new: None,
            udev_ref: None,
            udev_unref: None,
            udev_get_userdata: None,
            udev_set_userdata: None,
            udev_list_entry_get_next: None,
            udev_list_entry_get_by_name: None,
            udev_list_entry_get_name: None,
            udev_list_entry_get_value: None,
            udev_device_ref: None,
            udev_device_unref: None,
            udev_device_get_udev: None,
            udev_device_new_from_syspath: None,
            udev_device_new_from_devnum: None,
            udev_device_new_from_subsystem_sysname: None,
            udev_device_new_from_device_id: None,
            udev_device_new_from_environment: None,
            udev_device_get_parent: None,
            udev_device_get_parent_with_subsystem_devtype: None,
            udev_device_get_devpath: None,
            udev_device_get_subsystem: None,
            udev_device_get_devtype: None,
            udev_device_get_syspath: None,
            udev_device_get_sysname: None,
            udev_device_get_sysnum: None,
            udev_device_get_devnode: None,
            udev_device_get_is_initialized: None,
            udev_device_get_devlinks_list_entry: None,
            udev_device_get_properties_list_entry: None,
            udev_device_get_tags_list_entry: None,
            udev_device_get_current_tags_list_entry: None,
            udev_device_get_sysattr_list_entry: None,
            udev_device_get_property_value: None,
            udev_device_get_driver: None,
            udev_device_get_devnum: None,
            udev_device_get_action: None,
            udev_device_get_seqnum: None,
            udev_device_get_usec_since_initialized: None,
            udev_device_get_sysattr_value: None,
            udev_device_set_sysattr_value: None,
            udev_device_has_tag: None,
            udev_device_has_current_tag: None,
            udev_monitor_ref: None,
            udev_monitor_unref: None,
            udev_monitor_get_udev: None,
            udev_monitor_new_from_netlink: None,
            udev_monitor_enable_receiving: None,
            udev_monitor_set_receive_buffer_size: None,
            udev_monitor_get_fd: None,
            udev_monitor_receive_device: None,
            udev_monitor_filter_add_match_subsystem_devtype: None,
            udev_monitor_filter_add_match_tag: None,
            udev_monitor_filter_update: None,
            udev_monitor_filter_remove: None,
            udev_enumerate_ref: None,
            udev_enumerate_unref: None,
            udev_enumerate_get_udev: None,
            udev_enumerate_new: None,
            udev_enumerate_add_match_subsystem: None,
            udev_enumerate_add_nomatch_subsystem: None,
            udev_enumerate_add_match_sysattr: None,
            udev_enumerate_add_nomatch_sysattr: None,
            udev_enumerate_add_match_property: None,
            udev_enumerate_add_match_sysname: None,
            udev_enumerate_add_match_tag: None,
            udev_enumerate_add_match_parent: None,
            udev_enumerate_add_match_is_initialized: None,
            udev_enumerate_add_syspath: None,
            udev_enumerate_add_match_sysnum: None,
            udev_enumerate_add_match_devicenode: None,
            udev_enumerate_scan_devices: None,
            udev_enumerate_scan_subsystems: None,
            udev_enumerate_scan_children: None,
            udev_enumerate_get_list_entry: None,
            udev_queue_ref: None,
            udev_queue_unref: None,
            udev_queue_get_udev: None,
            udev_queue_new: None,
            udev_queue_get_kernel_seqnum: None,
            udev_queue_get_udev_seqnum: None,
            udev_queue_get_udev_is_active: None,
            udev_queue_get_queue_is_empty: None,
            udev_queue_get_seqnum_is_finished: None,
            udev_queue_get_seqnum_sequence_is_finished: None,
            udev_queue_get_fd: None,
            udev_queue_flush: None,
            udev_queue_get_queued_list_entry: None,
            udev_hwdb_new: None,
            udev_hwdb_ref: None,
            udev_hwdb_unref: None,
            udev_hwdb_get_properties_list_entry: None,
            udev_util_encode_string: None,
        }
    }
}

static REAL_UDEV: OnceLock<RealUdev> = OnceLock::new();

#[cfg(target_arch = "x86_64")]
const LIB_DIRS: &[&str] = &[
    "/usr/lib/x86_64-linux-gnu",
    "/lib/x86_64-linux-gnu",
    "/usr/lib64",
    "/lib64",
    "/usr/lib",
    "/lib",
    "/usr/local/lib",
    "/usr/local/lib64",
    "/run/host/usr/lib/x86_64-linux-gnu",
    "/run/host/usr/lib64",
    "/run/host/usr/lib",
    "/overrides/lib/x86_64-linux-gnu",
];

#[cfg(target_arch = "x86")]
const LIB_DIRS: &[&str] = &[
    "/usr/lib/i386-linux-gnu",
    "/lib/i386-linux-gnu",
    "/usr/lib32",
    "/lib32",
    "/usr/lib",
    "/lib",
    "/usr/local/lib",
    "/run/host/usr/lib/i386-linux-gnu",
    "/run/host/usr/lib32",
    "/run/host/usr/lib",
    "/overrides/lib/i386-linux-gnu",
];

#[cfg(not(any(target_arch = "x86_64", target_arch = "x86")))]
const LIB_DIRS: &[&str] = &[
    "/usr/lib/aarch64-linux-gnu",
    "/lib/aarch64-linux-gnu",
    "/usr/lib64",
    "/lib64",
    "/usr/lib",
    "/lib",
    "/run/host/usr/lib64",
    "/run/host/usr/lib",
];

unsafe fn is_self_path(path: &Path, self_sym: *const c_void) -> bool {
    let mut info = DlInfo {
        dli_fname: std::ptr::null(),
        dli_fbase: std::ptr::null_mut(),
        dli_sname: std::ptr::null(),
        dli_saddr: std::ptr::null_mut(),
    };
    if dladdr(self_sym, &mut info) == 0 || info.dli_fname.is_null() {
        return false;
    }
    let self_name = CStr::from_ptr(info.dli_fname).to_bytes();
    let self_path = Path::new(std::ffi::OsStr::from_bytes(self_name));
    match (fs::metadata(self_path), fs::metadata(path)) {
        (Ok(a), Ok(b)) => a.dev() == b.dev() && a.ino() == b.ino(),
        _ => false,
    }
}

unsafe fn load_sym<T>(handle: *mut c_void, name: &[u8]) -> Option<T> {
    let ptr = dlsym(handle, name.as_ptr() as *const c_char);
    if ptr.is_null() {
        None
    } else {
        Some(std::mem::transmute_copy(&ptr))
    }
}

unsafe fn try_load_real(path: &Path, self_sym: *const c_void) -> Option<RealUdev> {
    let cpath = CString::new(path.as_os_str().as_bytes()).ok()?;
    let handle = dlopen(cpath.as_ptr(), RTLD_NOW | RTLD_LOCAL);
    if handle.is_null() {
        return None;
    }
    let real_new = dlsym(handle, b"udev_new\0".as_ptr() as *const c_char);
    let has_identity = !dlsym(
        handle,
        b"twinverse_fake_udev_identity\0".as_ptr() as *const c_char,
    )
    .is_null();
    if real_new.is_null() || (real_new as *const c_void) == self_sym || has_identity {
        dlclose(handle);
        return None;
    }

    macro_rules! bind {
        ($field:ident) => {
            load_sym(handle, concat!(stringify!($field), "\0").as_bytes())
        };
    }

    let r = RealUdev {
        loaded: true,
        _handle: handle,
        udev_new: bind!(udev_new),
        udev_ref: bind!(udev_ref),
        udev_unref: bind!(udev_unref),
        udev_get_userdata: bind!(udev_get_userdata),
        udev_set_userdata: bind!(udev_set_userdata),
        udev_list_entry_get_next: bind!(udev_list_entry_get_next),
        udev_list_entry_get_by_name: bind!(udev_list_entry_get_by_name),
        udev_list_entry_get_name: bind!(udev_list_entry_get_name),
        udev_list_entry_get_value: bind!(udev_list_entry_get_value),
        udev_device_ref: bind!(udev_device_ref),
        udev_device_unref: bind!(udev_device_unref),
        udev_device_get_udev: bind!(udev_device_get_udev),
        udev_device_new_from_syspath: bind!(udev_device_new_from_syspath),
        udev_device_new_from_devnum: bind!(udev_device_new_from_devnum),
        udev_device_new_from_subsystem_sysname: bind!(udev_device_new_from_subsystem_sysname),
        udev_device_new_from_device_id: bind!(udev_device_new_from_device_id),
        udev_device_new_from_environment: bind!(udev_device_new_from_environment),
        udev_device_get_parent: bind!(udev_device_get_parent),
        udev_device_get_parent_with_subsystem_devtype: bind!(
            udev_device_get_parent_with_subsystem_devtype
        ),
        udev_device_get_devpath: bind!(udev_device_get_devpath),
        udev_device_get_subsystem: bind!(udev_device_get_subsystem),
        udev_device_get_devtype: bind!(udev_device_get_devtype),
        udev_device_get_syspath: bind!(udev_device_get_syspath),
        udev_device_get_sysname: bind!(udev_device_get_sysname),
        udev_device_get_sysnum: bind!(udev_device_get_sysnum),
        udev_device_get_devnode: bind!(udev_device_get_devnode),
        udev_device_get_is_initialized: bind!(udev_device_get_is_initialized),
        udev_device_get_devlinks_list_entry: bind!(udev_device_get_devlinks_list_entry),
        udev_device_get_properties_list_entry: bind!(udev_device_get_properties_list_entry),
        udev_device_get_tags_list_entry: bind!(udev_device_get_tags_list_entry),
        udev_device_get_current_tags_list_entry: bind!(udev_device_get_current_tags_list_entry),
        udev_device_get_sysattr_list_entry: bind!(udev_device_get_sysattr_list_entry),
        udev_device_get_property_value: bind!(udev_device_get_property_value),
        udev_device_get_driver: bind!(udev_device_get_driver),
        udev_device_get_devnum: bind!(udev_device_get_devnum),
        udev_device_get_action: bind!(udev_device_get_action),
        udev_device_get_seqnum: bind!(udev_device_get_seqnum),
        udev_device_get_usec_since_initialized: bind!(udev_device_get_usec_since_initialized),
        udev_device_get_sysattr_value: bind!(udev_device_get_sysattr_value),
        udev_device_set_sysattr_value: bind!(udev_device_set_sysattr_value),
        udev_device_has_tag: bind!(udev_device_has_tag),
        udev_device_has_current_tag: bind!(udev_device_has_current_tag),
        udev_monitor_ref: bind!(udev_monitor_ref),
        udev_monitor_unref: bind!(udev_monitor_unref),
        udev_monitor_get_udev: bind!(udev_monitor_get_udev),
        udev_monitor_new_from_netlink: bind!(udev_monitor_new_from_netlink),
        udev_monitor_enable_receiving: bind!(udev_monitor_enable_receiving),
        udev_monitor_set_receive_buffer_size: bind!(udev_monitor_set_receive_buffer_size),
        udev_monitor_get_fd: bind!(udev_monitor_get_fd),
        udev_monitor_receive_device: bind!(udev_monitor_receive_device),
        udev_monitor_filter_add_match_subsystem_devtype: bind!(
            udev_monitor_filter_add_match_subsystem_devtype
        ),
        udev_monitor_filter_add_match_tag: bind!(udev_monitor_filter_add_match_tag),
        udev_monitor_filter_update: bind!(udev_monitor_filter_update),
        udev_monitor_filter_remove: bind!(udev_monitor_filter_remove),
        udev_enumerate_ref: bind!(udev_enumerate_ref),
        udev_enumerate_unref: bind!(udev_enumerate_unref),
        udev_enumerate_get_udev: bind!(udev_enumerate_get_udev),
        udev_enumerate_new: bind!(udev_enumerate_new),
        udev_enumerate_add_match_subsystem: bind!(udev_enumerate_add_match_subsystem),
        udev_enumerate_add_nomatch_subsystem: bind!(udev_enumerate_add_nomatch_subsystem),
        udev_enumerate_add_match_sysattr: bind!(udev_enumerate_add_match_sysattr),
        udev_enumerate_add_nomatch_sysattr: bind!(udev_enumerate_add_nomatch_sysattr),
        udev_enumerate_add_match_property: bind!(udev_enumerate_add_match_property),
        udev_enumerate_add_match_sysname: bind!(udev_enumerate_add_match_sysname),
        udev_enumerate_add_match_tag: bind!(udev_enumerate_add_match_tag),
        udev_enumerate_add_match_parent: bind!(udev_enumerate_add_match_parent),
        udev_enumerate_add_match_is_initialized: bind!(udev_enumerate_add_match_is_initialized),
        udev_enumerate_add_syspath: bind!(udev_enumerate_add_syspath),
        udev_enumerate_add_match_sysnum: bind!(udev_enumerate_add_match_sysnum),
        udev_enumerate_add_match_devicenode: bind!(udev_enumerate_add_match_devicenode),
        udev_enumerate_scan_devices: bind!(udev_enumerate_scan_devices),
        udev_enumerate_scan_subsystems: bind!(udev_enumerate_scan_subsystems),
        udev_enumerate_scan_children: bind!(udev_enumerate_scan_children),
        udev_enumerate_get_list_entry: bind!(udev_enumerate_get_list_entry),
        udev_queue_ref: bind!(udev_queue_ref),
        udev_queue_unref: bind!(udev_queue_unref),
        udev_queue_get_udev: bind!(udev_queue_get_udev),
        udev_queue_new: bind!(udev_queue_new),
        udev_queue_get_kernel_seqnum: bind!(udev_queue_get_kernel_seqnum),
        udev_queue_get_udev_seqnum: bind!(udev_queue_get_udev_seqnum),
        udev_queue_get_udev_is_active: bind!(udev_queue_get_udev_is_active),
        udev_queue_get_queue_is_empty: bind!(udev_queue_get_queue_is_empty),
        udev_queue_get_seqnum_is_finished: bind!(udev_queue_get_seqnum_is_finished),
        udev_queue_get_seqnum_sequence_is_finished: bind!(
            udev_queue_get_seqnum_sequence_is_finished
        ),
        udev_queue_get_fd: bind!(udev_queue_get_fd),
        udev_queue_flush: bind!(udev_queue_flush),
        udev_queue_get_queued_list_entry: bind!(udev_queue_get_queued_list_entry),
        udev_hwdb_new: bind!(udev_hwdb_new),
        udev_hwdb_ref: bind!(udev_hwdb_ref),
        udev_hwdb_unref: bind!(udev_hwdb_unref),
        udev_hwdb_get_properties_list_entry: bind!(udev_hwdb_get_properties_list_entry),
        udev_util_encode_string: bind!(udev_util_encode_string),
    };
    udev_log!("passing through to real libudev {}", path.display());
    Some(r)
}

unsafe fn search_dir(dir: &Path, self_sym: *const c_void) -> Option<RealUdev> {
    let entries = fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_bytes = name.as_bytes();
        if !name_bytes.starts_with(b"libudev.so.1") {
            continue;
        }
        if name_bytes.windows(4).any(|w| w == b"fake")
            || name_bytes.windows(9).any(|w| w == b"twinverse")
        {
            continue;
        }
        let path = entry.path();
        if is_self_path(&path, self_sym) {
            continue;
        }
        if let Some(real) = try_load_real(&path, self_sym) {
            return Some(real);
        }
    }
    None
}

/// Resolve and cache the real system `libudev.so.1` once per process.
pub fn real_udev(self_sym: *const c_void) -> &'static RealUdev {
    REAL_UDEV.get_or_init(|| unsafe {
        let explicit_key =
            std::str::from_utf8(&ENV_REAL_LIBUDEV[..ENV_REAL_LIBUDEV.len() - 1]).unwrap_or("");
        if let Ok(explicit) = env::var(explicit_key) {
            if explicit.is_empty() || explicit == "none" {
                udev_log!("passthrough disabled by {}", explicit_key);
                return RealUdev::empty();
            }
            if let Some(real) = try_load_real(Path::new(&explicit), self_sym) {
                return real;
            }
            udev_log!(
                "{}={} unusable, falling back to directory scan",
                explicit_key,
                explicit
            );
        }

        if let Ok(ld_path) = env::var("LD_LIBRARY_PATH") {
            for dir in ld_path.split(':') {
                if !dir.is_empty() {
                    if let Some(real) = search_dir(Path::new(dir), self_sym) {
                        return real;
                    }
                }
            }
        }

        for dir in LIB_DIRS {
            if let Some(real) = search_dir(Path::new(dir), self_sym) {
                return real;
            }
        }

        udev_log!("no real libudev found; serving virtual uinput devices only");
        RealUdev::empty()
    })
}

/// Return the already-initialized `RealUdev` if loaded (for internal re-entry before `udev_new`).
pub fn real_udev_if_loaded() -> Option<&'static RealUdev> {
    REAL_UDEV.get()
}
