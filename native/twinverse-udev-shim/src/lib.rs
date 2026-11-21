//! Pure-Rust `libudev.so.1` passthrough shim for Twinverse's userspace `/dev/uinput`.
//!
//! Exports the full `LIBUDEV_183..247` C ABI (`SONAME: libudev.so.1`), forwards all
//! real devices and monitors to the host/runtime `libudev.so.1` loaded via `dlopen`,
//! and seamlessly injects dynamic userspace input devices (`event3000..3015`) created
//! by the sibling `libtwinverse_uinput.so` interposer.

mod ffi;
mod virtual_dev;

use std::collections::VecDeque;
use std::ffi::{c_char, c_int, c_uint, c_ulonglong, c_void, CStr, CString};
use std::mem::size_of;
use std::ptr;
use std::sync::atomic::{AtomicI32, Ordering};
use std::sync::Arc;

use twinverse_uinput_proto::{cstr_bytes, makedev, HIDRAW_ALLOW_BYTES};

use crate::ffi::{
    close, dev_t, epoll_create1, epoll_ctl, eventfd, fnmatch, get_errno, inotify_add_watch,
    inotify_init1, raw_read, raw_write, real_udev, size_t, socket_dir, udev_log, EpollEvent,
    InotifyEvent, RawDevice, RawEnumerate, RawHwdb, RawListEntry, RawMonitor, RawQueue, RawUdev,
    RealUdev, EAGAIN, EFD_CLOEXEC, EFD_NONBLOCK, EINVAL, ENOMEM, ENOSYS, EPOLLIN, EPOLL_CLOEXEC,
    EPOLL_CTL_ADD, IN_CLOEXEC, IN_CREATE, IN_DELETE, IN_MOVED_TO, IN_NONBLOCK,
};
use crate::virtual_dev::{
    find_by_devnum, find_by_socket_filename, find_by_subsystem_sysname, find_by_syspath,
    hidraw_filter_enabled, is_real_hidraw_hidden, is_real_input_sysname_hidden,
    is_real_syspath_hidden, live_dyn_devices, read_allowed_hidraws, DynDeviceDef, NodeType,
};

const MAGIC_UDEV: usize = 0x5457_5501;
const MAGIC_DEVICE: usize = 0x5457_5502;
const MAGIC_ENUMERATE: usize = 0x5457_5503;
const MAGIC_MONITOR: usize = 0x5457_5504;
const MAGIC_LIST: usize = 0x5457_5505;
const MAGIC_HWDB: usize = 0x5457_5506;
const MAGIC_QUEUE: usize = 0x5457_5507;

const INOTIFY_EVBUF_SIZE: usize = 4096;

/// Exported identity marker so `real_udev` never binds to a copy of this shim.
#[no_mangle]
pub static twinverse_fake_udev_identity: c_int = 1;

#[inline]
unsafe fn is_raw(ptr: *const c_void, magic: usize) -> bool {
    !ptr.is_null() && *(ptr as *const usize) != magic
}

#[inline]
fn get_real() -> &'static RealUdev {
    real_udev(udev_new as *const c_void)
}

/* -------------------------------------------------------------------------- */
/* Wrapper Objects (every struct begins with `magic: usize` under `#[repr(C)]`) */
/* -------------------------------------------------------------------------- */

#[repr(C)]
pub struct Udev {
    magic: usize,
    n_ref: AtomicI32,
    real: RawUdev,
    userdata: *mut c_void,
}

#[repr(C)]
pub struct UdevListEntry {
    magic: usize,
    next: *mut UdevListEntry,
    name: Option<CString>,
    value: Option<CString>,
}

#[repr(C)]
pub struct UdevDevice {
    magic: usize,
    udev_ctx: *mut Udev,
    n_ref: AtomicI32,
    real: RawDevice,
    virt: Option<(Arc<DynDeviceDef>, NodeType)>,
    properties: *mut UdevListEntry,
    sysattrs: *mut UdevListEntry,
    devlinks: *mut UdevListEntry,
    tags: *mut UdevListEntry,
    current_tags: *mut UdevListEntry,
    properties_built: bool,
    sysattrs_built: bool,
    devlinks_built: bool,
    tags_built: bool,
    current_tags_built: bool,
    parents: Vec<(String, *mut UdevDevice)>,
    action: *const c_char,
}

#[repr(C)]
pub struct UdevEnumerate {
    magic: usize,
    udev_ctx: *mut Udev,
    n_ref: AtomicI32,
    real: RawEnumerate,
    real_muted: bool,
    results: *mut UdevListEntry,
    subsystem_filtered: bool,
    input_matched: bool,
    input_excluded: bool,
    sysname_pattern: Option<CString>,
    property_filters: Vec<(CString, Option<CString>)>,
    parent_filter: Option<(i32, NodeType)>,
    extra_syspaths: Vec<CString>,
}

#[repr(C)]
pub struct UdevMonitor {
    magic: usize,
    udev_ctx: *mut Udev,
    n_ref: AtomicI32,
    real: RawMonitor,
    real_fd: c_int,
    fd: c_int,
    inotify_fd: c_int,
    evbuf_efd: c_int,
    evbuf_efd_armed: bool,
    watch_wd: c_int,
    subsystem_filtered: bool,
    input_matched: bool,
    hidraw_matched: bool,
    known_allowed_hidraws: Vec<String>,
    pending_hidraw_adds: VecDeque<String>,
    evbuf: [u8; INOTIFY_EVBUF_SIZE],
    evbuf_len: usize,
    evbuf_off: usize,
}

#[repr(C)]
pub struct UdevHwdb {
    magic: usize,
    n_ref: AtomicI32,
    real: RawHwdb,
    properties: *mut UdevListEntry,
}

#[repr(C)]
pub struct UdevQueue {
    magic: usize,
    udev_ctx: *mut Udev,
    n_ref: AtomicI32,
    real: RawQueue,
    queued: *mut UdevListEntry,
}

/* -------------------------------------------------------------------------- */
/* Linked-list helpers                                                        */
/* -------------------------------------------------------------------------- */

unsafe fn free_list(mut head: *mut UdevListEntry) {
    while !head.is_null() {
        let next = (*head).next;
        (*head).magic = 0;
        drop(Box::from_raw(head));
        head = next;
    }
}

unsafe fn list_append_cstr(
    head: &mut *mut UdevListEntry,
    tail: &mut *mut UdevListEntry,
    name: Option<CString>,
    value: Option<CString>,
) {
    let node = Box::into_raw(Box::new(UdevListEntry {
        magic: MAGIC_LIST,
        next: ptr::null_mut(),
        name,
        value,
    }));
    if (*head).is_null() {
        *head = node;
    } else {
        (**tail).next = node;
    }
    *tail = node;
}

unsafe fn list_append_ptrs(
    head: &mut *mut UdevListEntry,
    tail: &mut *mut UdevListEntry,
    name: *const c_char,
    value: *const c_char,
) {
    let n = if name.is_null() {
        None
    } else {
        Some(CStr::from_ptr(name).to_owned())
    };
    let v = if value.is_null() {
        None
    } else {
        Some(CStr::from_ptr(value).to_owned())
    };
    list_append_cstr(head, tail, n, v);
}

unsafe fn list_copy_real(real_head: RawListEntry) -> *mut UdevListEntry {
    let r = get_real();
    let (Some(get_next), Some(get_name), Some(get_val)) = (
        r.udev_list_entry_get_next,
        r.udev_list_entry_get_name,
        r.udev_list_entry_get_value,
    ) else {
        return ptr::null_mut();
    };
    let mut head = ptr::null_mut();
    let mut tail = ptr::null_mut();
    let mut it = real_head;
    while !it.is_null() {
        list_append_ptrs(&mut head, &mut tail, get_name(it), get_val(it));
        it = get_next(it);
    }
    head
}

#[no_mangle]
pub unsafe extern "C" fn udev_list_entry_get_next(entry: *mut UdevListEntry) -> *mut UdevListEntry {
    if is_raw(entry as *const c_void, MAGIC_LIST) {
        return match get_real().udev_list_entry_get_next {
            Some(f) => f(entry as RawListEntry) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if entry.is_null() {
        ptr::null_mut()
    } else {
        (*entry).next
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_list_entry_get_name(entry: *mut UdevListEntry) -> *const c_char {
    if is_raw(entry as *const c_void, MAGIC_LIST) {
        return match get_real().udev_list_entry_get_name {
            Some(f) => f(entry as RawListEntry),
            None => ptr::null(),
        };
    }
    if entry.is_null() {
        return ptr::null();
    }
    (*entry).name.as_ref().map_or(ptr::null(), |s| s.as_ptr())
}

#[no_mangle]
pub unsafe extern "C" fn udev_list_entry_get_value(entry: *mut UdevListEntry) -> *const c_char {
    if is_raw(entry as *const c_void, MAGIC_LIST) {
        return match get_real().udev_list_entry_get_value {
            Some(f) => f(entry as RawListEntry),
            None => ptr::null(),
        };
    }
    if entry.is_null() {
        return ptr::null();
    }
    (*entry).value.as_ref().map_or(ptr::null(), |s| s.as_ptr())
}

#[no_mangle]
pub unsafe extern "C" fn udev_list_entry_get_by_name(
    entry: *mut UdevListEntry,
    name: *const c_char,
) -> *mut UdevListEntry {
    if is_raw(entry as *const c_void, MAGIC_LIST) {
        return match get_real().udev_list_entry_get_by_name {
            Some(f) => f(entry as RawListEntry, name) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    let Some(target) = cstr_bytes(name) else {
        return ptr::null_mut();
    };
    let mut it = entry;
    while !it.is_null() {
        if let Some(ref s) = (*it).name {
            if s.as_bytes() == target {
                return it;
            }
        }
        it = (*it).next;
    }
    ptr::null_mut()
}

/* -------------------------------------------------------------------------- */
/* Context (`struct udev`)                                                    */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_new() -> *mut Udev {
    let r = get_real();
    let real = if r.loaded {
        r.udev_new.map_or(ptr::null_mut(), |f| f())
    } else {
        ptr::null_mut()
    };
    Box::into_raw(Box::new(Udev {
        magic: MAGIC_UDEV,
        n_ref: AtomicI32::new(1),
        real,
        userdata: ptr::null_mut(),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn udev_ref(udev: *mut Udev) -> *mut Udev {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_ref {
            Some(f) => f(udev as RawUdev) as *mut Udev,
            None => udev,
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    (*udev).n_ref.fetch_add(1, Ordering::Relaxed);
    udev
}

#[no_mangle]
pub unsafe extern "C" fn udev_unref(udev: *mut Udev) -> *mut Udev {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_unref {
            Some(f) => f(udev as RawUdev) as *mut Udev,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    if (*udev).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return udev;
    }
    let real = (*udev).real;
    if !real.is_null() {
        if let Some(f) = get_real().udev_unref {
            f(real);
        }
    }
    (*udev).magic = 0;
    drop(Box::from_raw(udev));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_get_userdata(udev: *mut Udev) -> *mut c_void {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_get_userdata {
            Some(f) => f(udev as RawUdev),
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        ptr::null_mut()
    } else {
        (*udev).userdata
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_set_userdata(udev: *mut Udev, userdata: *mut c_void) {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        if let Some(f) = get_real().udev_set_userdata {
            f(udev as RawUdev, userdata);
        }
        return;
    }
    if !udev.is_null() {
        (*udev).userdata = userdata;
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_set_log_fn(_udev: *mut Udev, _log_fn: *const c_void) {}

#[no_mangle]
pub unsafe extern "C" fn udev_get_log_priority(_udev: *mut Udev) -> c_int {
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_set_log_priority(_udev: *mut Udev, _priority: c_int) {}

/* -------------------------------------------------------------------------- */
/* Devices (`struct udev_device`)                                             */
/* -------------------------------------------------------------------------- */

unsafe fn alloc_device(
    udev: *mut Udev,
    real: RawDevice,
    virt: Option<(Arc<DynDeviceDef>, NodeType)>,
) -> *mut UdevDevice {
    Box::into_raw(Box::new(UdevDevice {
        magic: MAGIC_DEVICE,
        udev_ctx: udev_ref(udev),
        n_ref: AtomicI32::new(1),
        real,
        virt,
        properties: ptr::null_mut(),
        sysattrs: ptr::null_mut(),
        devlinks: ptr::null_mut(),
        tags: ptr::null_mut(),
        current_tags: ptr::null_mut(),
        properties_built: false,
        sysattrs_built: false,
        devlinks_built: false,
        tags_built: false,
        current_tags_built: false,
        parents: Vec::new(),
        action: ptr::null(),
    }))
}

unsafe fn wrap_real_device(udev: *mut Udev, real: RawDevice) -> *mut UdevDevice {
    if real.is_null() {
        return ptr::null_mut();
    }
    alloc_device(udev, real, None)
}

unsafe fn wrap_real_device_visible(udev: *mut Udev, real: RawDevice) -> *mut UdevDevice {
    if real.is_null() {
        return ptr::null_mut();
    }
    let r = get_real();
    let subsys = r.udev_device_get_subsystem.map_or(ptr::null(), |f| f(real));
    let sysname = r.udev_device_get_sysname.map_or(ptr::null(), |f| f(real));
    if let (Some(sub), Some(name)) = (cstr_bytes(subsys), cstr_bytes(sysname)) {
        if (sub == b"input" && is_real_input_sysname_hidden(name))
            || (sub == b"hidraw" && is_real_hidraw_hidden(name))
        {
            if let Some(unref) = r.udev_device_unref {
                unref(real);
            }
            return ptr::null_mut();
        }
    }
    wrap_real_device(udev, real)
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_ref(dev: *mut UdevDevice) -> *mut UdevDevice {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_ref {
            Some(f) => f(dev as RawDevice) as *mut UdevDevice,
            None => dev,
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    (*dev).n_ref.fetch_add(1, Ordering::Relaxed);
    dev
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_unref(dev: *mut UdevDevice) -> *mut UdevDevice {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_unref {
            Some(f) => f(dev as RawDevice) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return dev;
    }
    for (_, parent) in (*dev).parents.drain(..) {
        udev_device_unref(parent);
    }
    free_list((*dev).properties);
    free_list((*dev).sysattrs);
    free_list((*dev).devlinks);
    free_list((*dev).tags);
    free_list((*dev).current_tags);
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_unref {
            f((*dev).real);
        }
    }
    udev_unref((*dev).udev_ctx);
    (*dev).magic = 0;
    drop(Box::from_raw(dev));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_udev(dev: *mut UdevDevice) -> *mut Udev {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_udev {
            Some(f) => f(dev as RawDevice) as *mut Udev,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        ptr::null_mut()
    } else {
        (*dev).udev_ctx
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_new_from_syspath(
    udev: *mut Udev,
    syspath: *const c_char,
) -> *mut UdevDevice {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_device_new_from_syspath {
            Some(f) => f(udev as RawUdev, syspath) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let Some(sp) = cstr_bytes(syspath) else {
        return ptr::null_mut();
    };
    if let Some((def, ty)) = find_by_syspath(sp) {
        return alloc_device(udev, ptr::null_mut(), Some((def, ty)));
    }
    if (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let real = match get_real().udev_device_new_from_syspath {
        Some(f) => f((*udev).real, syspath),
        None => ptr::null_mut(),
    };
    wrap_real_device_visible(udev, real)
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_new_from_devnum(
    udev: *mut Udev,
    ty: c_char,
    devnum: dev_t,
) -> *mut UdevDevice {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_device_new_from_devnum {
            Some(f) => f(udev as RawUdev, ty, devnum) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    if ty == b'c' as c_char {
        if let Some((def, node_ty)) = find_by_devnum(devnum) {
            return alloc_device(udev, ptr::null_mut(), Some((def, node_ty)));
        }
    }
    if (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let real = match get_real().udev_device_new_from_devnum {
        Some(f) => f((*udev).real, ty, devnum),
        None => ptr::null_mut(),
    };
    wrap_real_device_visible(udev, real)
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_new_from_subsystem_sysname(
    udev: *mut Udev,
    subsystem: *const c_char,
    sysname: *const c_char,
) -> *mut UdevDevice {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_device_new_from_subsystem_sysname {
            Some(f) => f(udev as RawUdev, subsystem, sysname) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let (Some(sub), Some(name)) = (cstr_bytes(subsystem), cstr_bytes(sysname)) else {
        return ptr::null_mut();
    };
    if let Some((def, node_ty)) = find_by_subsystem_sysname(sub, name) {
        return alloc_device(udev, ptr::null_mut(), Some((def, node_ty)));
    }
    if (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let real = match get_real().udev_device_new_from_subsystem_sysname {
        Some(f) => f((*udev).real, subsystem, sysname),
        None => ptr::null_mut(),
    };
    wrap_real_device_visible(udev, real)
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_new_from_device_id(
    udev: *mut Udev,
    id: *const c_char,
) -> *mut UdevDevice {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_device_new_from_device_id {
            Some(f) => f(udev as RawUdev, id) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let Some(id_bytes) = cstr_bytes(id) else {
        return ptr::null_mut();
    };
    if let Some((&first, rest)) = id_bytes.split_first() {
        if first == b'c' || first == b'b' {
            if let Ok(s) = std::str::from_utf8(rest) {
                if let Some((maj_s, min_s)) = s.split_once(':') {
                    if let (Ok(maj), Ok(min)) = (maj_s.parse::<u32>(), min_s.parse::<u32>()) {
                        return udev_device_new_from_devnum(
                            udev,
                            first as c_char,
                            makedev(maj, min),
                        );
                    }
                }
            }
        }
    }
    if (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let real = match get_real().udev_device_new_from_device_id {
        Some(f) => f((*udev).real, id),
        None => ptr::null_mut(),
    };
    wrap_real_device_visible(udev, real)
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_new_from_environment(udev: *mut Udev) -> *mut UdevDevice {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_device_new_from_environment {
            Some(f) => f(udev as RawUdev) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() || (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let real = match get_real().udev_device_new_from_environment {
        Some(f) => f((*udev).real),
        None => ptr::null_mut(),
    };
    wrap_real_device_visible(udev, real)
}

macro_rules! device_passthrough {
    ($dev:expr, $field:ident, $dflt:expr $(, $arg:expr)*) => {{
        if is_raw($dev as *const c_void, MAGIC_DEVICE) {
            return match get_real().$field {
                Some(f) => f($dev as RawDevice $(, $arg)*),
                None => $dflt,
            };
        }
        if !$dev.is_null() && !(*$dev).real.is_null() {
            return match get_real().$field {
                Some(f) => f((*$dev).real $(, $arg)*),
                None => $dflt,
            };
        }
    }};
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_syspath(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_syspath, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((def, ty)) => def.syspath(*ty).as_ptr(),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_sysname(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_sysname, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((def, ty)) => def.sysname(*ty).as_ptr(),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_sysnum(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_sysnum, ptr::null());
    let sysname = udev_device_get_sysname(dev);
    let Some(bytes) = cstr_bytes(sysname) else {
        return ptr::null();
    };
    let mut i = bytes.len();
    while i > 0 && bytes[i - 1].is_ascii_digit() {
        i -= 1;
    }
    if i == bytes.len() {
        ptr::null()
    } else {
        sysname.add(i)
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_devpath(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_devpath, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((def, ty)) => def.devpath_ptr(*ty),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_subsystem(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_subsystem, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((_, ty)) => DynDeviceDef::subsystem_cstr(*ty),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_devtype(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_devtype, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((_, ty)) => DynDeviceDef::devtype_cstr(*ty),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_devnode(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_devnode, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    match &(*dev).virt {
        Some((def, ty)) => def.devnode_ptr(*ty),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_devnum(dev: *mut UdevDevice) -> dev_t {
    device_passthrough!(dev, udev_device_get_devnum, 0);
    if dev.is_null() {
        return 0;
    }
    match &(*dev).virt {
        Some((def, ty)) => def.devnum(*ty),
        None => 0,
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_property_value(
    dev: *mut UdevDevice,
    key: *const c_char,
) -> *const c_char {
    if !is_raw(dev as *const c_void, MAGIC_DEVICE)
        && !dev.is_null()
        && !(*dev).action.is_null()
        && cstr_bytes(key) == Some(b"ACTION")
    {
        return (*dev).action;
    }
    device_passthrough!(dev, udev_device_get_property_value, ptr::null(), key);
    if dev.is_null() {
        return ptr::null();
    }
    let Some(k) = cstr_bytes(key) else {
        return ptr::null();
    };
    match &(*dev).virt {
        Some((def, ty)) => def.property_value(*ty, k),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_sysattr_value(
    dev: *mut UdevDevice,
    sysattr: *const c_char,
) -> *const c_char {
    device_passthrough!(dev, udev_device_get_sysattr_value, ptr::null(), sysattr);
    if dev.is_null() {
        return ptr::null();
    }
    let Some(k) = cstr_bytes(sysattr) else {
        return ptr::null();
    };
    match &(*dev).virt {
        Some((def, ty)) => def.sysattr_value(*ty, k),
        None => ptr::null(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_set_sysattr_value(
    dev: *mut UdevDevice,
    sysattr: *const c_char,
    value: *const c_char,
) -> c_int {
    device_passthrough!(dev, udev_device_set_sysattr_value, -ENOSYS, sysattr, value);
    if dev.is_null() {
        -EINVAL
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_driver(dev: *mut UdevDevice) -> *const c_char {
    device_passthrough!(dev, udev_device_get_driver, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    if let Some((def, NodeType::UsbParent)) = &(*dev).virt {
        if def.vendor == 0x045e {
            return b"xpad\0".as_ptr() as *const c_char;
        }
    }
    ptr::null()
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_action(dev: *mut UdevDevice) -> *const c_char {
    if !is_raw(dev as *const c_void, MAGIC_DEVICE) && !dev.is_null() && !(*dev).action.is_null() {
        return (*dev).action;
    }
    device_passthrough!(dev, udev_device_get_action, ptr::null());
    if dev.is_null() {
        return ptr::null();
    }
    if !(*dev).action.is_null() {
        (*dev).action
    } else {
        b"add\0".as_ptr() as *const c_char
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_seqnum(dev: *mut UdevDevice) -> c_ulonglong {
    device_passthrough!(dev, udev_device_get_seqnum, 0);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_usec_since_initialized(
    dev: *mut UdevDevice,
) -> c_ulonglong {
    device_passthrough!(dev, udev_device_get_usec_since_initialized, 0);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_is_initialized(dev: *mut UdevDevice) -> c_int {
    device_passthrough!(dev, udev_device_get_is_initialized, 1);
    1
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_has_tag(dev: *mut UdevDevice, tag: *const c_char) -> c_int {
    device_passthrough!(dev, udev_device_has_tag, 0, tag);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_has_current_tag(
    dev: *mut UdevDevice,
    tag: *const c_char,
) -> c_int {
    device_passthrough!(dev, udev_device_has_current_tag, 0, tag);
    0
}

unsafe fn virtual_parent(
    dev: *mut UdevDevice,
    subsystem: Option<&[u8]>,
    devtype: Option<&[u8]>,
) -> *mut UdevDevice {
    let Some((def, ty)) = &(*dev).virt else {
        return ptr::null_mut();
    };
    let devtype_empty = devtype.is_none_or(|d| d.is_empty());
    let target_ty = match *ty {
        NodeType::Event => {
            if subsystem.is_none() || (subsystem == Some(b"input") && devtype_empty) {
                Some(NodeType::InputParent)
            } else if subsystem == Some(b"usb") && (devtype_empty || devtype == Some(b"usb_device"))
            {
                Some(NodeType::UsbParent)
            } else {
                None
            }
        }
        NodeType::InputParent => {
            if subsystem.is_none()
                || (subsystem == Some(b"usb") && (devtype_empty || devtype == Some(b"usb_device")))
            {
                Some(NodeType::UsbParent)
            } else {
                None
            }
        }
        NodeType::UsbParent => None,
    };
    match target_ty {
        Some(parent_ty) => alloc_device(
            (*dev).udev_ctx,
            ptr::null_mut(),
            Some((Arc::clone(def), parent_ty)),
        ),
        None => ptr::null_mut(),
    }
}

unsafe fn wrap_real_parent(dev: *mut UdevDevice, real_parent: RawDevice) -> *mut UdevDevice {
    if real_parent.is_null() {
        return ptr::null_mut();
    }
    let Some(ref_fn) = get_real().udev_device_ref else {
        return ptr::null_mut();
    };
    wrap_real_device((*dev).udev_ctx, ref_fn(real_parent))
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_parent(dev: *mut UdevDevice) -> *mut UdevDevice {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_parent {
            Some(f) => f(dev as RawDevice) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    for (k, p) in &(*dev).parents {
        if k == "*" {
            return *p;
        }
    }
    let parent = if !(*dev).real.is_null() {
        let rp = get_real()
            .udev_device_get_parent
            .map_or(ptr::null_mut(), |f| f((*dev).real));
        wrap_real_parent(dev, rp)
    } else {
        virtual_parent(dev, None, None)
    };
    if !parent.is_null() {
        (*dev).parents.push(("*".to_string(), parent));
    }
    parent
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_parent_with_subsystem_devtype(
    dev: *mut UdevDevice,
    subsystem: *const c_char,
    devtype: *const c_char,
) -> *mut UdevDevice {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_parent_with_subsystem_devtype {
            Some(f) => f(dev as RawDevice, subsystem, devtype) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    let Some(sub_bytes) = cstr_bytes(subsystem) else {
        return ptr::null_mut();
    };
    let dt_bytes = cstr_bytes(devtype);
    let key = format!(
        "{}/{}",
        String::from_utf8_lossy(sub_bytes),
        dt_bytes.map_or_else(String::new, |b| String::from_utf8_lossy(b).into_owned())
    );
    for (k, p) in &(*dev).parents {
        if *k == key {
            return *p;
        }
    }
    let parent = if !(*dev).real.is_null() {
        let rp = get_real()
            .udev_device_get_parent_with_subsystem_devtype
            .map_or(ptr::null_mut(), |f| f((*dev).real, subsystem, devtype));
        wrap_real_parent(dev, rp)
    } else {
        virtual_parent(dev, Some(sub_bytes), dt_bytes)
    };
    if !parent.is_null() {
        (*dev).parents.push((key, parent));
    }
    parent
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_properties_list_entry(
    dev: *mut UdevDevice,
) -> *mut UdevListEntry {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_properties_list_entry {
            Some(f) => f(dev as RawDevice) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).properties_built {
        return (*dev).properties;
    }
    (*dev).properties_built = true;
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_get_properties_list_entry {
            (*dev).properties = list_copy_real(f((*dev).real));
        }
        return (*dev).properties;
    }
    let Some((def, ty)) = &(*dev).virt else {
        return ptr::null_mut();
    };
    let mut head = ptr::null_mut();
    let mut tail = ptr::null_mut();
    for (k, v) in def.property_table(*ty) {
        list_append_cstr(&mut head, &mut tail, Some(k.clone()), Some(v.clone()));
    }
    list_append_ptrs(
        &mut head,
        &mut tail,
        b"SUBSYSTEM\0".as_ptr() as *const c_char,
        DynDeviceDef::subsystem_cstr(*ty),
    );
    list_append_ptrs(
        &mut head,
        &mut tail,
        b"DEVPATH\0".as_ptr() as *const c_char,
        def.devpath_ptr(*ty),
    );
    (*dev).properties = head;
    head
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_sysattr_list_entry(
    dev: *mut UdevDevice,
) -> *mut UdevListEntry {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_sysattr_list_entry {
            Some(f) => f(dev as RawDevice) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).sysattrs_built {
        return (*dev).sysattrs;
    }
    (*dev).sysattrs_built = true;
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_get_sysattr_list_entry {
            (*dev).sysattrs = list_copy_real(f((*dev).real));
        }
        return (*dev).sysattrs;
    }
    let Some((def, ty)) = &(*dev).virt else {
        return ptr::null_mut();
    };
    let mut head = ptr::null_mut();
    let mut tail = ptr::null_mut();
    for (k, _) in def.sysattr_table(*ty) {
        list_append_cstr(&mut head, &mut tail, Some(k.clone()), None);
    }
    (*dev).sysattrs = head;
    head
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_devlinks_list_entry(
    dev: *mut UdevDevice,
) -> *mut UdevListEntry {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_devlinks_list_entry {
            Some(f) => f(dev as RawDevice) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).devlinks_built {
        return (*dev).devlinks;
    }
    (*dev).devlinks_built = true;
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_get_devlinks_list_entry {
            (*dev).devlinks = list_copy_real(f((*dev).real));
        }
    }
    (*dev).devlinks
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_tags_list_entry(
    dev: *mut UdevDevice,
) -> *mut UdevListEntry {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_tags_list_entry {
            Some(f) => f(dev as RawDevice) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).tags_built {
        return (*dev).tags;
    }
    (*dev).tags_built = true;
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_get_tags_list_entry {
            (*dev).tags = list_copy_real(f((*dev).real));
        }
    }
    (*dev).tags
}

#[no_mangle]
pub unsafe extern "C" fn udev_device_get_current_tags_list_entry(
    dev: *mut UdevDevice,
) -> *mut UdevListEntry {
    if is_raw(dev as *const c_void, MAGIC_DEVICE) {
        return match get_real().udev_device_get_current_tags_list_entry {
            Some(f) => f(dev as RawDevice) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if dev.is_null() {
        return ptr::null_mut();
    }
    if (*dev).current_tags_built {
        return (*dev).current_tags;
    }
    (*dev).current_tags_built = true;
    if !(*dev).real.is_null() {
        if let Some(f) = get_real().udev_device_get_current_tags_list_entry {
            (*dev).current_tags = list_copy_real(f((*dev).real));
        }
    }
    (*dev).current_tags
}

/* -------------------------------------------------------------------------- */
/* Enumerate (`struct udev_enumerate`)                                        */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_new(udev: *mut Udev) -> *mut UdevEnumerate {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_enumerate_new {
            Some(f) => f(udev as RawUdev) as *mut UdevEnumerate,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let real = if !(*udev).real.is_null() {
        get_real()
            .udev_enumerate_new
            .map_or(ptr::null_mut(), |f| f((*udev).real))
    } else {
        ptr::null_mut()
    };
    Box::into_raw(Box::new(UdevEnumerate {
        magic: MAGIC_ENUMERATE,
        udev_ctx: udev_ref(udev),
        n_ref: AtomicI32::new(1),
        real,
        real_muted: false,
        results: ptr::null_mut(),
        subsystem_filtered: false,
        input_matched: false,
        input_excluded: false,
        sysname_pattern: None,
        property_filters: Vec::new(),
        parent_filter: None,
        extra_syspaths: Vec::new(),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_ref(e: *mut UdevEnumerate) -> *mut UdevEnumerate {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_ref {
            Some(f) => f(e as RawEnumerate) as *mut UdevEnumerate,
            None => e,
        };
    }
    if e.is_null() {
        return ptr::null_mut();
    }
    (*e).n_ref.fetch_add(1, Ordering::Relaxed);
    e
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_unref(e: *mut UdevEnumerate) -> *mut UdevEnumerate {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_unref {
            Some(f) => f(e as RawEnumerate) as *mut UdevEnumerate,
            None => ptr::null_mut(),
        };
    }
    if e.is_null() {
        return ptr::null_mut();
    }
    if (*e).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return e;
    }
    if !(*e).real.is_null() {
        if let Some(f) = get_real().udev_enumerate_unref {
            f((*e).real);
        }
    }
    free_list((*e).results);
    udev_unref((*e).udev_ctx);
    (*e).magic = 0;
    drop(Box::from_raw(e));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_get_udev(e: *mut UdevEnumerate) -> *mut Udev {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_get_udev {
            Some(f) => f(e as RawEnumerate) as *mut Udev,
            None => ptr::null_mut(),
        };
    }
    if e.is_null() {
        ptr::null_mut()
    } else {
        (*e).udev_ctx
    }
}

macro_rules! enumerate_passthrough {
    ($e:expr, $field:ident $(, $arg:expr)*) => {{
        if is_raw($e as *const c_void, MAGIC_ENUMERATE) {
            return match get_real().$field {
                Some(f) => f($e as RawEnumerate $(, $arg)*),
                None => -EINVAL,
            };
        }
        if $e.is_null() {
            return -EINVAL;
        }
        if !(*$e).real.is_null() {
            if let Some(f) = get_real().$field {
                let _ = f((*$e).real $(, $arg)*);
            }
        }
    }};
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_subsystem(
    e: *mut UdevEnumerate,
    subsystem: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_subsystem, subsystem);
    let Some(sub) = cstr_bytes(subsystem) else {
        return -EINVAL;
    };
    (*e).subsystem_filtered = true;
    if sub == b"input" {
        (*e).input_matched = true;
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_nomatch_subsystem(
    e: *mut UdevEnumerate,
    subsystem: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_nomatch_subsystem, subsystem);
    if cstr_bytes(subsystem) == Some(b"input") {
        (*e).input_excluded = true;
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_sysname(
    e: *mut UdevEnumerate,
    sysname: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_sysname, sysname);
    if sysname.is_null() {
        return -EINVAL;
    }
    (*e).sysname_pattern = Some(CStr::from_ptr(sysname).to_owned());
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_property(
    e: *mut UdevEnumerate,
    property: *const c_char,
    value: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_property, property, value);
    if property.is_null() {
        return 0;
    }
    let prop = CStr::from_ptr(property).to_owned();
    let val = if value.is_null() {
        None
    } else {
        Some(CStr::from_ptr(value).to_owned())
    };
    (*e).property_filters.push((prop, val));
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_sysattr(
    e: *mut UdevEnumerate,
    sysattr: *const c_char,
    value: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_sysattr, sysattr, value);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_nomatch_sysattr(
    e: *mut UdevEnumerate,
    sysattr: *const c_char,
    value: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_nomatch_sysattr, sysattr, value);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_tag(
    e: *mut UdevEnumerate,
    tag: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_tag, tag);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_is_initialized(e: *mut UdevEnumerate) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_is_initialized);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_parent(
    e: *mut UdevEnumerate,
    parent: *mut UdevDevice,
) -> c_int {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_add_match_parent {
            Some(f) => f(e as RawEnumerate, parent as RawDevice),
            None => -EINVAL,
        };
    }
    if e.is_null() || parent.is_null() {
        return -EINVAL;
    }
    if is_raw(parent as *const c_void, MAGIC_DEVICE) || !(*parent).real.is_null() {
        let real_parent = if is_raw(parent as *const c_void, MAGIC_DEVICE) {
            parent as RawDevice
        } else {
            (*parent).real
        };
        if !(*e).real.is_null() {
            if let Some(f) = get_real().udev_enumerate_add_match_parent {
                let _ = f((*e).real, real_parent);
            }
        }
        (*e).input_excluded = true;
        return 0;
    }
    (*e).real_muted = true;
    if let Some((def, ty)) = &(*parent).virt {
        (*e).parent_filter = Some((def.event_num, *ty));
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_syspath(
    e: *mut UdevEnumerate,
    syspath: *const c_char,
) -> c_int {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_add_syspath {
            Some(f) => f(e as RawEnumerate, syspath),
            None => -EINVAL,
        };
    }
    if e.is_null() || syspath.is_null() {
        return -EINVAL;
    }
    let Some(sp) = cstr_bytes(syspath) else {
        return -EINVAL;
    };
    if find_by_syspath(sp).is_some() {
        (*e).extra_syspaths.push(CStr::from_ptr(syspath).to_owned());
        return 0;
    }
    if !(*e).real.is_null() {
        if let Some(f) = get_real().udev_enumerate_add_syspath {
            return f((*e).real, syspath);
        }
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_sysnum(
    e: *mut UdevEnumerate,
    sysnum: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_sysnum, sysnum);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_add_match_devicenode(
    e: *mut UdevEnumerate,
    devnode: *const c_char,
) -> c_int {
    enumerate_passthrough!(e, udev_enumerate_add_match_devicenode, devnode);
    0
}

unsafe fn virtual_matches(e: &UdevEnumerate, def: &DynDeviceDef, ty: NodeType) -> bool {
    if let Some(ref pat) = e.sysname_pattern {
        if fnmatch(pat.as_ptr(), def.sysname(ty).as_ptr(), 0) != 0 {
            return false;
        }
    }
    if let Some((parent_num, parent_ty)) = e.parent_filter {
        if def.event_num != parent_num {
            return false;
        }
        let is_descendant = match parent_ty {
            NodeType::UsbParent => ty != NodeType::UsbParent,
            NodeType::InputParent => ty == NodeType::Event,
            NodeType::Event => false,
        };
        if !is_descendant {
            return false;
        }
    }
    for (prop, expected) in &e.property_filters {
        let actual_ptr = def.property_value(ty, prop.as_bytes());
        let Some(actual) = cstr_bytes(actual_ptr) else {
            return false;
        };
        if let Some(ref exp) = expected {
            if actual != exp.as_bytes() {
                return false;
            }
        }
    }
    true
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_scan_devices(e: *mut UdevEnumerate) -> c_int {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_scan_devices {
            Some(f) => f(e as RawEnumerate),
            None => -EINVAL,
        };
    }
    if e.is_null() {
        return -EINVAL;
    }
    free_list((*e).results);
    (*e).results = ptr::null_mut();

    let mut head = ptr::null_mut();
    let mut tail = ptr::null_mut();
    let mut real_count = 0usize;
    let mut virt_count = 0usize;

    let r = get_real();
    if !(*e).real.is_null() && !(*e).real_muted {
        if let (Some(scan), Some(get_list), Some(get_next), Some(get_name)) = (
            r.udev_enumerate_scan_devices,
            r.udev_enumerate_get_list_entry,
            r.udev_list_entry_get_next,
            r.udev_list_entry_get_name,
        ) {
            let _ = scan((*e).real);
            let mut it = get_list((*e).real);
            while !it.is_null() {
                let sp = get_name(it);
                if let Some(sp_bytes) = cstr_bytes(sp) {
                    if !is_real_syspath_hidden(sp_bytes) {
                        list_append_ptrs(&mut head, &mut tail, sp, ptr::null());
                        real_count += 1;
                    }
                }
                it = get_next(it);
            }
        }
    }

    if !(*e).input_excluded && (!(*e).subsystem_filtered || (*e).input_matched) {
        let e_ref = &*e;
        for def in live_dyn_devices() {
            if virtual_matches(e_ref, &def, NodeType::Event) {
                list_append_cstr(&mut head, &mut tail, Some(def.event_syspath.clone()), None);
                virt_count += 1;
            }
            if (e_ref.sysname_pattern.is_some() || e_ref.parent_filter.is_some())
                && virtual_matches(e_ref, &def, NodeType::InputParent)
            {
                list_append_cstr(
                    &mut head,
                    &mut tail,
                    Some(def.input_parent_syspath.clone()),
                    None,
                );
                virt_count += 1;
            }
        }
    }

    for extra in &(*e).extra_syspaths {
        list_append_cstr(&mut head, &mut tail, Some(extra.clone()), None);
        virt_count += 1;
    }

    (*e).results = head;
    udev_log!("scan_devices: {} real, {} virtual", real_count, virt_count);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_scan_subsystems(e: *mut UdevEnumerate) -> c_int {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_scan_subsystems {
            Some(f) => f(e as RawEnumerate),
            None => -EINVAL,
        };
    }
    if e.is_null() {
        return -EINVAL;
    }
    free_list((*e).results);
    (*e).results = ptr::null_mut();
    if (*e).real.is_null() {
        return 0;
    }
    let r = get_real();
    let rc = r.udev_enumerate_scan_subsystems.map_or(0, |f| f((*e).real));
    if let Some(get_list) = r.udev_enumerate_get_list_entry {
        (*e).results = list_copy_real(get_list((*e).real));
    }
    rc
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_scan_children(
    e: *mut UdevEnumerate,
    parent: *mut UdevDevice,
) -> c_int {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_scan_children {
            Some(f) => f(e as RawEnumerate, parent as RawDevice),
            None => -EINVAL,
        };
    }
    if e.is_null() || parent.is_null() {
        return -EINVAL;
    }
    free_list((*e).results);
    (*e).results = ptr::null_mut();
    if !(*e).real.is_null() && !(*parent).real.is_null() {
        let r = get_real();
        if let Some(scan) = r.udev_enumerate_scan_children {
            let rc = scan((*e).real, (*parent).real);
            if let Some(get_list) = r.udev_enumerate_get_list_entry {
                (*e).results = list_copy_real(get_list((*e).real));
            }
            return rc;
        }
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_enumerate_get_list_entry(
    e: *mut UdevEnumerate,
) -> *mut UdevListEntry {
    if is_raw(e as *const c_void, MAGIC_ENUMERATE) {
        return match get_real().udev_enumerate_get_list_entry {
            Some(f) => f(e as RawEnumerate) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if e.is_null() {
        ptr::null_mut()
    } else {
        (*e).results
    }
}

/* -------------------------------------------------------------------------- */
/* Monitor (`struct udev_monitor`)                                            */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_new_from_netlink(
    udev: *mut Udev,
    name: *const c_char,
) -> *mut UdevMonitor {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_monitor_new_from_netlink {
            Some(f) => f(udev as RawUdev, name) as *mut UdevMonitor,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let r = get_real();
    let mut real = ptr::null_mut();
    let mut real_fd = -1;
    if !(*udev).real.is_null() {
        if let Some(f) = r.udev_monitor_new_from_netlink {
            real = f((*udev).real, name);
            if !real.is_null() {
                real_fd = r.udev_monitor_get_fd.map_or(-1, |g| g(real));
            }
        }
    }

    let inotify_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    let mut watch_wd = -1;
    if inotify_fd >= 0 {
        let dir = socket_dir();
        if let Ok(cdir) = CString::new(dir.as_str()) {
            watch_wd = inotify_add_watch(
                inotify_fd,
                cdir.as_ptr(),
                IN_CREATE | IN_DELETE | IN_MOVED_TO,
            );
        }
    }
    let evbuf_efd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    let fd = epoll_create1(EPOLL_CLOEXEC);
    if fd >= 0 {
        for watch_fd in [inotify_fd, evbuf_efd, real_fd] {
            if watch_fd < 0 {
                continue;
            }
            let mut ev = EpollEvent {
                events: EPOLLIN,
                data: watch_fd as u64,
            };
            epoll_ctl(fd, EPOLL_CTL_ADD, watch_fd, &mut ev);
        }
    }

    Box::into_raw(Box::new(UdevMonitor {
        magic: MAGIC_MONITOR,
        udev_ctx: udev_ref(udev),
        n_ref: AtomicI32::new(1),
        real,
        real_fd,
        fd,
        inotify_fd,
        evbuf_efd,
        evbuf_efd_armed: false,
        watch_wd,
        subsystem_filtered: false,
        input_matched: false,
        hidraw_matched: false,
        known_allowed_hidraws: if hidraw_filter_enabled() {
            read_allowed_hidraws()
        } else {
            Vec::new()
        },
        pending_hidraw_adds: VecDeque::new(),
        evbuf: [0u8; INOTIFY_EVBUF_SIZE],
        evbuf_len: 0,
        evbuf_off: 0,
    }))
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_ref(mon: *mut UdevMonitor) -> *mut UdevMonitor {
    if is_raw(mon as *const c_void, MAGIC_MONITOR) {
        return match get_real().udev_monitor_ref {
            Some(f) => f(mon as RawMonitor) as *mut UdevMonitor,
            None => mon,
        };
    }
    if mon.is_null() {
        return ptr::null_mut();
    }
    (*mon).n_ref.fetch_add(1, Ordering::Relaxed);
    mon
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_unref(mon: *mut UdevMonitor) -> *mut UdevMonitor {
    if is_raw(mon as *const c_void, MAGIC_MONITOR) {
        return match get_real().udev_monitor_unref {
            Some(f) => f(mon as RawMonitor) as *mut UdevMonitor,
            None => ptr::null_mut(),
        };
    }
    if mon.is_null() {
        return ptr::null_mut();
    }
    if (*mon).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return mon;
    }
    if (*mon).fd >= 0 {
        close((*mon).fd);
    }
    if (*mon).inotify_fd >= 0 {
        close((*mon).inotify_fd);
    }
    if (*mon).evbuf_efd >= 0 {
        close((*mon).evbuf_efd);
    }
    if !(*mon).real.is_null() {
        if let Some(f) = get_real().udev_monitor_unref {
            f((*mon).real);
        }
    }
    udev_unref((*mon).udev_ctx);
    (*mon).magic = 0;
    drop(Box::from_raw(mon));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_get_udev(mon: *mut UdevMonitor) -> *mut Udev {
    if is_raw(mon as *const c_void, MAGIC_MONITOR) {
        return match get_real().udev_monitor_get_udev {
            Some(f) => f(mon as RawMonitor) as *mut Udev,
            None => ptr::null_mut(),
        };
    }
    if mon.is_null() {
        ptr::null_mut()
    } else {
        (*mon).udev_ctx
    }
}

macro_rules! monitor_passthrough {
    ($mon:expr, $field:ident $(, $arg:expr)*) => {{
        if is_raw($mon as *const c_void, MAGIC_MONITOR) {
            return match get_real().$field {
                Some(f) => f($mon as RawMonitor $(, $arg)*),
                None => -EINVAL,
            };
        }
        if $mon.is_null() {
            return -EINVAL;
        }
        if !(*$mon).real.is_null() {
            if let Some(f) = get_real().$field {
                let _ = f((*$mon).real $(, $arg)*);
            }
        }
    }};
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_enable_receiving(mon: *mut UdevMonitor) -> c_int {
    monitor_passthrough!(mon, udev_monitor_enable_receiving);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_set_receive_buffer_size(
    mon: *mut UdevMonitor,
    size: c_int,
) -> c_int {
    monitor_passthrough!(mon, udev_monitor_set_receive_buffer_size, size);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_get_fd(mon: *mut UdevMonitor) -> c_int {
    if is_raw(mon as *const c_void, MAGIC_MONITOR) {
        return match get_real().udev_monitor_get_fd {
            Some(f) => f(mon as RawMonitor),
            None => -1,
        };
    }
    if mon.is_null() {
        return -1;
    }
    if (*mon).fd >= 0 {
        (*mon).fd
    } else {
        (*mon).inotify_fd
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_filter_add_match_subsystem_devtype(
    mon: *mut UdevMonitor,
    subsystem: *const c_char,
    devtype: *const c_char,
) -> c_int {
    monitor_passthrough!(
        mon,
        udev_monitor_filter_add_match_subsystem_devtype,
        subsystem,
        devtype
    );
    if let Some(sub) = cstr_bytes(subsystem) {
        (*mon).subsystem_filtered = true;
        let dt_empty = cstr_bytes(devtype).is_none_or(|d| d.is_empty());
        if sub == b"input" && dt_empty {
            (*mon).input_matched = true;
        } else if sub == b"hidraw" && dt_empty {
            (*mon).hidraw_matched = true;
        }
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_filter_add_match_tag(
    mon: *mut UdevMonitor,
    tag: *const c_char,
) -> c_int {
    monitor_passthrough!(mon, udev_monitor_filter_add_match_tag, tag);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_filter_update(mon: *mut UdevMonitor) -> c_int {
    monitor_passthrough!(mon, udev_monitor_filter_update);
    0
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_filter_remove(mon: *mut UdevMonitor) -> c_int {
    monitor_passthrough!(mon, udev_monitor_filter_remove);
    (*mon).subsystem_filtered = false;
    (*mon).input_matched = false;
    (*mon).hidraw_matched = false;
    0
}

fn monitor_admits_virtual(mon: &UdevMonitor) -> bool {
    !mon.subsystem_filtered || mon.input_matched
}

fn monitor_admits_hidraw(mon: &UdevMonitor) -> bool {
    !mon.subsystem_filtered || mon.hidraw_matched
}

fn extract_inotify_name(buf: &[u8]) -> &[u8] {
    let end = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
    &buf[..end]
}

fn evbuf_has_matching_record(mon: &UdevMonitor) -> bool {
    if !mon.pending_hidraw_adds.is_empty() {
        return true;
    }
    let admit_virt = monitor_admits_virtual(mon);
    let admit_hidraw = hidraw_filter_enabled() && monitor_admits_hidraw(mon);
    if !admit_virt && !admit_hidraw {
        return false;
    }
    let hdr_sz = size_of::<InotifyEvent>();
    let mut off = mon.evbuf_off;
    while off <= mon.evbuf_len && mon.evbuf_len - off >= hdr_sz {
        let ev = unsafe { ptr::read_unaligned(mon.evbuf.as_ptr().add(off) as *const InotifyEvent) };
        let name_len = ev.len as usize;
        if name_len > mon.evbuf_len - off - hdr_sz {
            break;
        }
        let name_slice = &mon.evbuf[off + hdr_sz..off + hdr_sz + name_len];
        off += hdr_sz + name_len;
        if (ev.mask & (IN_CREATE | IN_DELETE | IN_MOVED_TO)) == 0 || name_len == 0 {
            continue;
        }
        let name = extract_inotify_name(name_slice);
        if admit_virt
            && twinverse_uinput_proto::parse_socket_or_desc_filename(name)
                .is_some_and(|(_, is_sock)| is_sock)
        {
            return true;
        }
        if admit_hidraw && name == HIDRAW_ALLOW_BYTES {
            return true;
        }
    }
    false
}

unsafe fn monitor_sync_readable(mon: &mut UdevMonitor) {
    if mon.evbuf_efd < 0 {
        return;
    }
    let want_armed = evbuf_has_matching_record(mon);
    if want_armed && !mon.evbuf_efd_armed {
        let one: u64 = 1;
        if raw_write(
            mon.evbuf_efd,
            (&one as *const u64) as *const u8,
            size_of::<u64>(),
        ) == size_of::<u64>() as isize
        {
            mon.evbuf_efd_armed = true;
        }
    } else if !want_armed && mon.evbuf_efd_armed {
        let mut val: u64 = 0;
        let rc = raw_read(
            mon.evbuf_efd,
            (&mut val as *mut u64) as *mut u8,
            size_of::<u64>(),
        );
        if rc == size_of::<u64>() as isize || get_errno() == EAGAIN {
            mon.evbuf_efd_armed = false;
        }
    }
}

unsafe fn pop_pending_hidraw_add(mon: &mut UdevMonitor) -> *mut UdevDevice {
    while let Some(name) = mon.pending_hidraw_adds.pop_front() {
        if mon.udev_ctx.is_null() || (*mon.udev_ctx).real.is_null() {
            continue;
        }
        let Some(new_fn) = get_real().udev_device_new_from_subsystem_sysname else {
            continue;
        };
        let Ok(cname) = CString::new(name.as_str()) else {
            continue;
        };
        let real = new_fn(
            (*mon.udev_ctx).real,
            b"hidraw\0".as_ptr() as *const c_char,
            cname.as_ptr(),
        );
        let dev = wrap_real_device_visible(mon.udev_ctx, real);
        if !dev.is_null() {
            (*dev).action = b"add\0".as_ptr() as *const c_char;
            udev_log!("hotplug 'add' for hidraw {}", name);
            return dev;
        }
    }
    ptr::null_mut()
}

unsafe fn monitor_dispense_virtual(mon: &mut UdevMonitor) -> *mut UdevDevice {
    let pending = pop_pending_hidraw_add(mon);
    if !pending.is_null() {
        return pending;
    }
    if mon.inotify_fd < 0 {
        return ptr::null_mut();
    }
    let hdr_sz = size_of::<InotifyEvent>();
    loop {
        if mon.evbuf_off > mon.evbuf_len || mon.evbuf_len - mon.evbuf_off < hdr_sz {
            let n = raw_read(mon.inotify_fd, mon.evbuf.as_mut_ptr(), mon.evbuf.len());
            if n <= 0 {
                return ptr::null_mut();
            }
            mon.evbuf_len = n as usize;
            mon.evbuf_off = 0;
            if mon.evbuf_len < hdr_sz {
                return ptr::null_mut();
            }
        }

        let ev = ptr::read_unaligned(mon.evbuf.as_ptr().add(mon.evbuf_off) as *const InotifyEvent);
        let name_len = ev.len as usize;
        if name_len > mon.evbuf_len - mon.evbuf_off - hdr_sz {
            mon.evbuf_off = mon.evbuf_len;
            continue;
        }
        let name_start = mon.evbuf_off + hdr_sz;
        let name = extract_inotify_name(&mon.evbuf[name_start..name_start + name_len]);
        let name_owned = name.to_vec();
        mon.evbuf_off += hdr_sz + name_len;

        let action = if (ev.mask & (IN_CREATE | IN_MOVED_TO)) != 0 {
            b"add\0".as_ptr() as *const c_char
        } else if (ev.mask & IN_DELETE) != 0 {
            b"remove\0".as_ptr() as *const c_char
        } else {
            continue;
        };

        if name_owned.is_empty() {
            continue;
        }

        if name_owned == HIDRAW_ALLOW_BYTES {
            if hidraw_filter_enabled() {
                let current = read_allowed_hidraws();
                if monitor_admits_hidraw(mon) {
                    for h in &current {
                        if !mon.known_allowed_hidraws.iter().any(|k| k == h) {
                            mon.pending_hidraw_adds.push_back(h.clone());
                        }
                    }
                }
                mon.known_allowed_hidraws = current;
                let dev = pop_pending_hidraw_add(mon);
                if !dev.is_null() {
                    return dev;
                }
            }
            continue;
        }

        if !monitor_admits_virtual(mon) {
            continue;
        }

        let Some(def) = find_by_socket_filename(&name_owned) else {
            continue;
        };
        let dev = alloc_device(mon.udev_ctx, ptr::null_mut(), Some((def, NodeType::Event)));
        (*dev).action = action;
        udev_log!(
            "hotplug '{}' for {}",
            CStr::from_ptr(action).to_string_lossy(),
            String::from_utf8_lossy(&name_owned)
        );
        return dev;
    }
}

#[no_mangle]
pub unsafe extern "C" fn udev_monitor_receive_device(mon: *mut UdevMonitor) -> *mut UdevDevice {
    if is_raw(mon as *const c_void, MAGIC_MONITOR) {
        return match get_real().udev_monitor_receive_device {
            Some(f) => f(mon as RawMonitor) as *mut UdevDevice,
            None => ptr::null_mut(),
        };
    }
    if mon.is_null() {
        return ptr::null_mut();
    }
    let mut dev = monitor_dispense_virtual(&mut *mon);
    monitor_sync_readable(&mut *mon);
    if dev.is_null() && !(*mon).real.is_null() {
        if let Some(recv) = get_real().udev_monitor_receive_device {
            while dev.is_null() {
                let real = recv((*mon).real);
                if real.is_null() {
                    break;
                }
                dev = wrap_real_device_visible((*mon).udev_ctx, real);
            }
        }
    }
    dev
}

/* -------------------------------------------------------------------------- */
/* HWDB (`struct udev_hwdb`)                                                  */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_hwdb_new(udev: *mut Udev) -> *mut UdevHwdb {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_hwdb_new {
            Some(f) => f(udev as RawUdev) as *mut UdevHwdb,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() || (*udev).real.is_null() {
        return ptr::null_mut();
    }
    let Some(f) = get_real().udev_hwdb_new else {
        return ptr::null_mut();
    };
    let real = f((*udev).real);
    if real.is_null() {
        return ptr::null_mut();
    }
    Box::into_raw(Box::new(UdevHwdb {
        magic: MAGIC_HWDB,
        n_ref: AtomicI32::new(1),
        real,
        properties: ptr::null_mut(),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn udev_hwdb_ref(hwdb: *mut UdevHwdb) -> *mut UdevHwdb {
    if is_raw(hwdb as *const c_void, MAGIC_HWDB) {
        return match get_real().udev_hwdb_ref {
            Some(f) => f(hwdb as RawHwdb) as *mut UdevHwdb,
            None => hwdb,
        };
    }
    if !hwdb.is_null() {
        (*hwdb).n_ref.fetch_add(1, Ordering::Relaxed);
    }
    hwdb
}

#[no_mangle]
pub unsafe extern "C" fn udev_hwdb_unref(hwdb: *mut UdevHwdb) -> *mut UdevHwdb {
    if is_raw(hwdb as *const c_void, MAGIC_HWDB) {
        return match get_real().udev_hwdb_unref {
            Some(f) => f(hwdb as RawHwdb) as *mut UdevHwdb,
            None => ptr::null_mut(),
        };
    }
    if hwdb.is_null() {
        return ptr::null_mut();
    }
    if (*hwdb).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return hwdb;
    }
    free_list((*hwdb).properties);
    if let Some(f) = get_real().udev_hwdb_unref {
        f((*hwdb).real);
    }
    (*hwdb).magic = 0;
    drop(Box::from_raw(hwdb));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_hwdb_get_properties_list_entry(
    hwdb: *mut UdevHwdb,
    modalias: *const c_char,
    flags: c_uint,
) -> *mut UdevListEntry {
    if is_raw(hwdb as *const c_void, MAGIC_HWDB) {
        return match get_real().udev_hwdb_get_properties_list_entry {
            Some(f) => f(hwdb as RawHwdb, modalias, flags) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if hwdb.is_null() {
        return ptr::null_mut();
    }
    free_list((*hwdb).properties);
    (*hwdb).properties = match get_real().udev_hwdb_get_properties_list_entry {
        Some(f) => list_copy_real(f((*hwdb).real, modalias, flags)),
        None => ptr::null_mut(),
    };
    (*hwdb).properties
}

/* -------------------------------------------------------------------------- */
/* Queue (`struct udev_queue`)                                                */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_queue_new(udev: *mut Udev) -> *mut UdevQueue {
    if is_raw(udev as *const c_void, MAGIC_UDEV) {
        return match get_real().udev_queue_new {
            Some(f) => f(udev as RawUdev) as *mut UdevQueue,
            None => ptr::null_mut(),
        };
    }
    if udev.is_null() {
        return ptr::null_mut();
    }
    let real = if !(*udev).real.is_null() {
        get_real()
            .udev_queue_new
            .map_or(ptr::null_mut(), |f| f((*udev).real))
    } else {
        ptr::null_mut()
    };
    Box::into_raw(Box::new(UdevQueue {
        magic: MAGIC_QUEUE,
        udev_ctx: udev_ref(udev),
        n_ref: AtomicI32::new(1),
        real,
        queued: ptr::null_mut(),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_ref(q: *mut UdevQueue) -> *mut UdevQueue {
    if is_raw(q as *const c_void, MAGIC_QUEUE) {
        return match get_real().udev_queue_ref {
            Some(f) => f(q as RawQueue) as *mut UdevQueue,
            None => q,
        };
    }
    if !q.is_null() {
        (*q).n_ref.fetch_add(1, Ordering::Relaxed);
    }
    q
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_unref(q: *mut UdevQueue) -> *mut UdevQueue {
    if is_raw(q as *const c_void, MAGIC_QUEUE) {
        return match get_real().udev_queue_unref {
            Some(f) => f(q as RawQueue) as *mut UdevQueue,
            None => ptr::null_mut(),
        };
    }
    if q.is_null() {
        return ptr::null_mut();
    }
    if (*q).n_ref.fetch_sub(1, Ordering::AcqRel) > 1 {
        return q;
    }
    if !(*q).real.is_null() {
        if let Some(f) = get_real().udev_queue_unref {
            f((*q).real);
        }
    }
    free_list((*q).queued);
    udev_unref((*q).udev_ctx);
    (*q).magic = 0;
    drop(Box::from_raw(q));
    ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_udev(q: *mut UdevQueue) -> *mut Udev {
    if is_raw(q as *const c_void, MAGIC_QUEUE) {
        return match get_real().udev_queue_get_udev {
            Some(f) => f(q as RawQueue) as *mut Udev,
            None => ptr::null_mut(),
        };
    }
    if q.is_null() {
        ptr::null_mut()
    } else {
        (*q).udev_ctx
    }
}

macro_rules! queue_passthrough {
    ($q:expr, $field:ident, $dflt:expr $(, $arg:expr)*) => {{
        if is_raw($q as *const c_void, MAGIC_QUEUE) {
            return match get_real().$field {
                Some(f) => f($q as RawQueue $(, $arg)*),
                None => $dflt,
            };
        }
        if !$q.is_null() && !(*$q).real.is_null() {
            return match get_real().$field {
                Some(f) => f((*$q).real $(, $arg)*),
                None => $dflt,
            };
        }
        $dflt
    }};
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_kernel_seqnum(q: *mut UdevQueue) -> c_ulonglong {
    queue_passthrough!(q, udev_queue_get_kernel_seqnum, 0)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_udev_seqnum(q: *mut UdevQueue) -> c_ulonglong {
    queue_passthrough!(q, udev_queue_get_udev_seqnum, 0)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_udev_is_active(q: *mut UdevQueue) -> c_int {
    queue_passthrough!(q, udev_queue_get_udev_is_active, 0)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_queue_is_empty(q: *mut UdevQueue) -> c_int {
    queue_passthrough!(q, udev_queue_get_queue_is_empty, 1)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_seqnum_is_finished(
    q: *mut UdevQueue,
    seqnum: c_ulonglong,
) -> c_int {
    queue_passthrough!(q, udev_queue_get_seqnum_is_finished, 1, seqnum)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_seqnum_sequence_is_finished(
    q: *mut UdevQueue,
    start: c_ulonglong,
    end: c_ulonglong,
) -> c_int {
    queue_passthrough!(q, udev_queue_get_seqnum_sequence_is_finished, 1, start, end)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_fd(q: *mut UdevQueue) -> c_int {
    queue_passthrough!(q, udev_queue_get_fd, -1)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_flush(q: *mut UdevQueue) -> c_int {
    queue_passthrough!(q, udev_queue_flush, 0)
}

#[no_mangle]
pub unsafe extern "C" fn udev_queue_get_queued_list_entry(q: *mut UdevQueue) -> *mut UdevListEntry {
    if is_raw(q as *const c_void, MAGIC_QUEUE) {
        return match get_real().udev_queue_get_queued_list_entry {
            Some(f) => f(q as RawQueue) as *mut UdevListEntry,
            None => ptr::null_mut(),
        };
    }
    if q.is_null() {
        return ptr::null_mut();
    }
    free_list((*q).queued);
    (*q).queued = ptr::null_mut();
    if !(*q).real.is_null() {
        if let Some(f) = get_real().udev_queue_get_queued_list_entry {
            (*q).queued = list_copy_real(f((*q).real));
        }
    }
    (*q).queued
}

/* -------------------------------------------------------------------------- */
/* Util                                                                       */
/* -------------------------------------------------------------------------- */

#[no_mangle]
pub unsafe extern "C" fn udev_util_encode_string(
    str_in: *const c_char,
    str_enc: *mut c_char,
    len: size_t,
) -> c_int {
    if let Some(f) = get_real().udev_util_encode_string {
        return f(str_in, str_enc, len);
    }
    if str_in.is_null() || str_enc.is_null() || len == 0 {
        return 0;
    }
    let Some(bytes) = cstr_bytes(str_in) else {
        return 0;
    };
    let copy_len = bytes.len().min(len - 1);
    ptr::copy_nonoverlapping(bytes.as_ptr(), str_enc as *mut u8, copy_len);
    *(str_enc.add(copy_len)) = 0;
    copy_len as c_int
}

// Keep ENOMEM referenced cleanly if unused.
const _: c_int = ENOMEM;
