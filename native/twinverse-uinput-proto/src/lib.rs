//! Shared binary protocol, Linux input ABI structures, and ioctl constants for
//! Twinverse's userspace `/dev/uinput` interposer, `libudev` shim, and hotplug
//! physical controller bridge.
//!
//! Every serialized structure uses fixed-width integer types so 32-bit (`i686`)
//! creators (such as the Linux Steam client) and 64-bit (`x86_64`) consumers
//! (such as Proton's `winebus.so` and native 64-bit games) share an identical
//! on-disk descriptor layout.

use core::ffi::{c_char, c_int, c_long, c_uint, c_ulong};
use core::mem::{align_of, size_of};

/// First synthetic `/dev/input/event<N>` number assigned to userspace uinput devices.
pub const UDYN_EVENT_BASE: i32 = 3000;
/// Maximum number of concurrent userspace uinput devices per sandbox.
pub const UDYN_MAX: usize = 16;
/// Maximum number of concurrent consumer connections per created device.
pub const UDYN_MAX_CLIENTS: usize = 64;

/// Magic value identifying a Twinverse userspace uinput descriptor (`"TWUI"`).
pub const UDYN_DESC_MAGIC: u32 = 0x5457_5549;
/// Current descriptor schema version.
pub const UDYN_DESC_VERSION: u32 = 1;

/// Input device major number (`INPUT_MAJOR` in Linux).
pub const INPUT_MAJOR: u32 = 13;
/// Base minor number for evdev nodes (`EVDEV_MINOR_BASE` in Linux).
pub const EVDEV_MINOR_BASE: u32 = 64;

/// Environment variable that forces `/dev/uinput` emulation even when a
/// read-only `/dev/uinput` node exists in the sandbox.
pub const ENV_VIRTUAL_UINPUT: &[u8] = b"TWINVERSE_VIRTUAL_UINPUT\0";
/// Environment variable selecting the short directory for `.sock`/`.desc` files.
pub const ENV_SOCKET_DIR: &[u8] = b"TWINVERSE_UINPUT_SOCKET_DIR\0";
/// Environment variable enabling stderr diagnostics.
pub const ENV_DEBUG_LOG: &[u8] = b"TWINVERSE_UINPUT_LOG\0";
/// Environment variable overriding the real `libudev.so.1` path (`"none"` disables passthrough).
pub const ENV_REAL_LIBUDEV: &[u8] = b"TWINVERSE_REAL_LIBUDEV\0";
/// Environment variable indicating that slot 0 (`event3000`) is reserved for
/// the host hotplug physical controller bridge (`twinverse-input-bridge`).
pub const ENV_PHYSICAL_BRIDGE: &[u8] = b"TWINVERSE_PHYSICAL_BRIDGE\0";
/// Environment variable enabling dynamic `/dev/hidraw*` allowlist filtering
/// backed by `<socket_dir>/tw_hidraw.allow`.
pub const ENV_HIDRAW_FILTER: &[u8] = b"TWINVERSE_HIDRAW_FILTER\0";
/// Basename of the dynamic hidraw allowlist file inside `ENV_SOCKET_DIR`.
pub const HIDRAW_ALLOW_FILENAME: &str = "tw_hidraw.allow";
pub const HIDRAW_ALLOW_BYTES: &[u8] = b"tw_hidraw.allow";

/// Linux input constants from `<linux/input-event-codes.h>` and `<linux/uinput.h>`.
pub const EV_SYN: usize = 0x00;
pub const EV_KEY: usize = 0x01;
pub const EV_REL: usize = 0x02;
pub const EV_ABS: usize = 0x03;
pub const EV_MSC: usize = 0x04;
pub const EV_FF: usize = 0x15;
pub const EV_MAX: usize = 0x1f;

pub const SYN_REPORT: u16 = 0;

pub const KEY_A: usize = 30;
pub const BTN_MOUSE: usize = 0x110;
pub const BTN_JOYSTICK: usize = 0x120;
pub const BTN_GAMEPAD: usize = 0x130;
pub const KEY_MAX: usize = 0x2ff;

pub const REL_MAX: usize = 0x0f;
pub const ABS_Z: usize = 0x02;
pub const ABS_RZ: usize = 0x05;
pub const ABS_THROTTLE: usize = 0x06;
pub const ABS_RUDDER: usize = 0x07;
pub const ABS_GAS: usize = 0x09;
pub const ABS_BRAKE: usize = 0x0a;
pub const ABS_MAX: usize = 0x3f;
pub const ABS_CNT: usize = ABS_MAX + 1;
pub const MSC_MAX: usize = 0x07;
pub const INPUT_PROP_MAX: usize = 0x1f;

pub const BUS_USB: u16 = 0x03;
pub const BUS_VIRTUAL: u16 = 0x06;

pub const UINPUT_MAX_NAME_SIZE: usize = 80;
pub const EV_VERSION: c_int = 0x010001;

pub const fn udyn_bytes(max: usize) -> usize {
    (max / 8) + 1
}

/// Linux `struct input_id`.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputId {
    pub bustype: u16,
    pub vendor: u16,
    pub product: u16,
    pub version: u16,
}

/// Linux `struct input_absinfo`.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputAbsInfo {
    pub value: i32,
    pub minimum: i32,
    pub maximum: i32,
    pub fuzz: i32,
    pub flat: i32,
    pub resolution: i32,
}

/// Linux `struct uinput_setup`.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct UinputSetup {
    pub id: InputId,
    pub name: [u8; UINPUT_MAX_NAME_SIZE],
    pub ff_effects_max: u32,
}

/// Linux `struct uinput_abs_setup`.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct UinputAbsSetup {
    pub code: u16,
    pub _pad: u16,
    pub absinfo: InputAbsInfo,
}

/// Legacy Linux `struct uinput_user_dev`.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct UinputUserDev {
    pub name: [u8; UINPUT_MAX_NAME_SIZE],
    pub id: InputId,
    pub ff_effects_max: u32,
    pub absmax: [i32; ABS_CNT],
    pub absmin: [i32; ABS_CNT],
    pub absfuzz: [i32; ABS_CNT],
    pub absflat: [i32; ABS_CNT],
}

/// `i686` Linux `struct input_event` (16 bytes).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputEvent32 {
    pub sec: i32,
    pub usec: i32,
    pub ev_type: u16,
    pub code: u16,
    pub value: i32,
}

/// `x86_64` Linux `struct input_event` (24 bytes).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputEvent64 {
    pub sec: i64,
    pub usec: i64,
    pub ev_type: u16,
    pub code: u16,
    pub value: i32,
}

/// Native `struct input_event` for the current target architecture.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct NativeInputEvent {
    pub sec: c_long,
    pub usec: c_long,
    pub ev_type: u16,
    pub code: u16,
    pub value: i32,
}

/// Architecture-independent descriptor written to `tw_event<N>.desc`.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct UdynDesc {
    pub magic: u32,
    pub version: u32,
    pub bustype: u16,
    pub vendor: u16,
    pub product: u16,
    pub version_id: u16,
    pub name: [u8; UINPUT_MAX_NAME_SIZE],
    pub evbits: [u8; udyn_bytes(EV_MAX)],
    pub keybits: [u8; udyn_bytes(KEY_MAX)],
    pub relbits: [u8; udyn_bytes(REL_MAX)],
    pub absbits: [u8; udyn_bytes(ABS_MAX)],
    pub mscbits: [u8; udyn_bytes(MSC_MAX)],
    pub propbits: [u8; udyn_bytes(INPUT_PROP_MAX)],
    pub absinfo: [InputAbsInfo; ABS_CNT],
    pub event_size: u32,
}

impl UdynDesc {
    pub const fn zeroed() -> Self {
        Self {
            magic: 0,
            version: 0,
            bustype: 0,
            vendor: 0,
            product: 0,
            version_id: 0,
            name: [0; UINPUT_MAX_NAME_SIZE],
            evbits: [0; udyn_bytes(EV_MAX)],
            keybits: [0; udyn_bytes(KEY_MAX)],
            relbits: [0; udyn_bytes(REL_MAX)],
            absbits: [0; udyn_bytes(ABS_MAX)],
            mscbits: [0; udyn_bytes(MSC_MAX)],
            propbits: [0; udyn_bytes(INPUT_PROP_MAX)],
            absinfo: [InputAbsInfo {
                value: 0,
                minimum: 0,
                maximum: 0,
                fuzz: 0,
                flat: 0,
                resolution: 0,
            }; ABS_CNT],
            event_size: 0,
        }
    }

    pub fn new_default() -> Self {
        let mut d = Self::zeroed();
        d.magic = UDYN_DESC_MAGIC;
        d.version = UDYN_DESC_VERSION;
        d.bustype = BUS_VIRTUAL;
        d.event_size = size_of::<NativeInputEvent>() as u32;
        set_bit(&mut d.evbits, EV_SYN as c_int, EV_MAX);
        d
    }

    pub fn is_valid(&self) -> bool {
        self.magic == UDYN_DESC_MAGIC && self.version == UDYN_DESC_VERSION
    }

    /// Return the NUL-terminated device name as a byte slice (without NUL).
    pub fn name_bytes(&self) -> &[u8] {
        let len = self
            .name
            .iter()
            .position(|&b| b == 0)
            .unwrap_or(self.name.len());
        &self.name[..len]
    }
}

// Compile-time ABI verification matching Linux kernel UAPI on both x86_64 and i686.
const _: () = {
    assert!(size_of::<InputId>() == 8);
    assert!(align_of::<InputId>() == 2);
    assert!(size_of::<InputAbsInfo>() == 24);
    assert!(align_of::<InputAbsInfo>() == 4);
    assert!(size_of::<UinputSetup>() == 92);
    assert!(align_of::<UinputSetup>() == 4);
    assert!(size_of::<UinputAbsSetup>() == 28);
    assert!(align_of::<UinputAbsSetup>() == 4);
    assert!(size_of::<UinputUserDev>() == 1116);
    assert!(align_of::<UinputUserDev>() == 4);
    assert!(size_of::<InputEvent32>() == 16);
    assert!(size_of::<InputEvent64>() == 24);
    #[cfg(target_pointer_width = "64")]
    assert!(size_of::<NativeInputEvent>() == 24);
    #[cfg(target_pointer_width = "32")]
    assert!(size_of::<NativeInputEvent>() == 16);
};

// Linux ioctl encoding helpers (`<asm-generic/ioctl.h>`).
pub const IOC_NRBITS: u32 = 8;
pub const IOC_TYPEBITS: u32 = 8;
pub const IOC_SIZEBITS: u32 = 14;
pub const IOC_NRSHIFT: u32 = 0;
pub const IOC_TYPESHIFT: u32 = IOC_NRSHIFT + IOC_NRBITS;
pub const IOC_SIZESHIFT: u32 = IOC_TYPESHIFT + IOC_TYPEBITS;
pub const IOC_DIRSHIFT: u32 = IOC_SIZESHIFT + IOC_SIZEBITS;

pub const IOC_NONE: u32 = 0;
pub const IOC_WRITE: u32 = 1;
pub const IOC_READ: u32 = 2;

pub const fn ioc(dir: u32, ty: u8, nr: u32, size: u32) -> c_ulong {
    (((dir) << IOC_DIRSHIFT)
        | ((ty as u32) << IOC_TYPESHIFT)
        | ((nr) << IOC_NRSHIFT)
        | ((size) << IOC_SIZESHIFT)) as c_ulong
}

pub const fn ioc_type(req: c_ulong) -> u8 {
    (((req as u32) >> IOC_TYPESHIFT) & 0xff) as u8
}

pub const fn ioc_nr(req: c_ulong) -> u32 {
    ((req as u32) >> IOC_NRSHIFT) & 0xff
}

pub const fn ioc_size(req: c_ulong) -> usize {
    (((req as u32) >> IOC_SIZESHIFT) & 0x3fff) as usize
}

// `uinput` ioctls (`type = 'U'`).
pub const UINPUT_IOCTL_BASE: u8 = b'U';
pub const UI_DEV_CREATE: c_ulong = ioc(IOC_NONE, UINPUT_IOCTL_BASE, 1, 0);
pub const UI_DEV_DESTROY: c_ulong = ioc(IOC_NONE, UINPUT_IOCTL_BASE, 2, 0);
pub const UI_DEV_SETUP: c_ulong = ioc(
    IOC_WRITE,
    UINPUT_IOCTL_BASE,
    3,
    size_of::<UinputSetup>() as u32,
);
pub const UI_ABS_SETUP: c_ulong = ioc(
    IOC_WRITE,
    UINPUT_IOCTL_BASE,
    4,
    size_of::<UinputAbsSetup>() as u32,
);
pub const UI_GET_VERSION: c_ulong =
    ioc(IOC_READ, UINPUT_IOCTL_BASE, 45, size_of::<c_uint>() as u32);
pub const UI_SET_EVBIT: c_ulong = ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 100, size_of::<c_int>() as u32);
pub const UI_SET_KEYBIT: c_ulong =
    ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 101, size_of::<c_int>() as u32);
pub const UI_SET_RELBIT: c_ulong =
    ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 102, size_of::<c_int>() as u32);
pub const UI_SET_ABSBIT: c_ulong =
    ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 103, size_of::<c_int>() as u32);
pub const UI_SET_MSCBIT: c_ulong =
    ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 104, size_of::<c_int>() as u32);
pub const UI_SET_PROPBIT: c_ulong =
    ioc(IOC_WRITE, UINPUT_IOCTL_BASE, 110, size_of::<c_int>() as u32);
pub const UI_GET_SYSNAME_NR: u32 = 44;

// `evdev` ioctl numbers (`type = 'E'`).
pub const EVDEV_IOCTL_BASE: u8 = b'E';
pub const EVIOCGVERSION_NR: u32 = 0x01;
pub const EVIOCGID_NR: u32 = 0x02;
pub const EVIOCGNAME_NR: u32 = 0x06;
pub const EVIOCGPHYS_NR: u32 = 0x07;
pub const EVIOCGUNIQ_NR: u32 = 0x08;
pub const EVIOCGPROP_NR: u32 = 0x09;
pub const EVIOCGKEY_NR: u32 = 0x18;
pub const EVIOCGLED_NR: u32 = 0x19;
pub const EVIOCGSW_NR: u32 = 0x1b;
pub const EVIOCGBIT_BASE_NR: u32 = 0x20;
pub const EVIOCGABS_BASE_NR: u32 = 0x40;
pub const EVIOCGEFFECTS_NR: u32 = 0x84;
pub const EVIOCGRAB_NR: u32 = 0x90;
pub const EVIOCREVOKE_NR: u32 = 0x91;

const _: () = {
    assert!(UI_DEV_CREATE == 0x5501);
    assert!(UI_DEV_DESTROY == 0x5502);
    assert!(UI_DEV_SETUP == 0x405c5503);
    assert!(UI_ABS_SETUP == 0x401c5504);
    assert!(UI_GET_VERSION == 0x8004552d);
    assert!(UI_SET_EVBIT == 0x40045564);
    assert!(UI_SET_KEYBIT == 0x40045565);
    assert!(UI_SET_RELBIT == 0x40045566);
    assert!(UI_SET_ABSBIT == 0x40045567);
    assert!(UI_SET_MSCBIT == 0x40045568);
    assert!(UI_SET_PROPBIT == 0x4004556e);
};

/// glibc-compatible `makedev(major, minor)` encoding.
pub const fn makedev(major: u32, minor: u32) -> u64 {
    let maj = major as u64;
    let min = minor as u64;
    ((maj & 0x0000_0fff) << 8)
        | ((maj & 0xffff_f000) << 32)
        | (min & 0x0000_00ff)
        | ((min & 0xffff_ff00) << 12)
}

/// glibc-compatible `major(dev)` decoding.
pub const fn dev_major(dev: u64) -> u32 {
    (((dev >> 8) & 0x0000_0fff) | ((dev >> 32) & 0xffff_f000)) as u32
}

/// glibc-compatible `minor(dev)` decoding.
pub const fn dev_minor(dev: u64) -> u32 {
    ((dev & 0x0000_00ff) | ((dev >> 12) & 0xffff_ff00)) as u32
}

/// Canonical `dev_t` for virtual evdev node `/dev/input/event<num>`.
pub const fn virtual_event_devnum(event_num: i32) -> u64 {
    makedev(INPUT_MAJOR, EVDEV_MINOR_BASE + (event_num as u32))
}

#[inline]
pub fn set_bit(arr: &mut [u8], bit: c_int, max: usize) {
    if bit >= 0 {
        let b = bit as usize;
        if b <= max && (b / 8) < arr.len() {
            arr[b / 8] |= 1u8 << (b % 8);
        }
    }
}

#[inline]
pub fn clear_bit(arr: &mut [u8], bit: usize, max: usize) {
    if bit <= max && (bit / 8) < arr.len() {
        arr[bit / 8] &= !(1u8 << (bit % 8));
    }
}

#[inline]
pub fn test_bit(arr: &[u8], bit: usize, max: usize) -> bool {
    bit <= max && (bit / 8) < arr.len() && ((arr[bit / 8] >> (bit % 8)) & 1) != 0
}

/// Compute a safe neutral/resting value for an `EV_ABS` axis when a physical
/// controller disconnects mid-session so inputs never remain stuck.
pub const fn default_abs_rest_value(code: usize, info: &InputAbsInfo) -> i32 {
    match code {
        ABS_Z | ABS_RZ | ABS_THROTTLE | ABS_RUDDER | ABS_GAS | ABS_BRAKE => info.minimum,
        _ => {
            if info.minimum < 0 && info.maximum > 0 {
                0
            } else {
                ((info.minimum as i64 + info.maximum as i64) / 2) as i32
            }
        }
    }
}

/// Parse an unsigned decimal integer immediately following `prefix`.
pub fn parse_index_after(path: &[u8], prefix: &[u8]) -> Option<i32> {
    let rest = path.strip_prefix(prefix)?;
    if rest.is_empty() {
        return None;
    }
    let mut val: i32 = 0;
    for &b in rest {
        if !b.is_ascii_digit() {
            return None;
        }
        val = val.checked_mul(10)?.checked_add((b - b'0') as i32)?;
    }
    Some(val)
}

/// Return true if `name` is a `hidraw<N>` basename (e.g. `b"hidraw0"`).
pub fn is_hidraw_basename(name: &[u8]) -> bool {
    parse_index_after(name, b"hidraw").is_some()
}

/// Return the `hidraw<N>` basename if `path` is `/dev/hidraw<N>`.
pub fn parse_hidraw_dev_path(path: &[u8]) -> Option<&[u8]> {
    let base = path.strip_prefix(b"/dev/")?;
    if is_hidraw_basename(base) {
        Some(base)
    } else {
        None
    }
}

/// Return true if `basename` appears as a trimmed line in `tw_hidraw.allow`.
pub fn hidraw_allow_contains(contents: &[u8], basename: &[u8]) -> bool {
    if basename.is_empty() {
        return false;
    }
    for line in contents.split(|&b| b == b'\n') {
        let trimmed = match line.strip_suffix(b"\r") {
            Some(s) => s,
            None => line,
        };
        if trimmed == basename {
            return true;
        }
    }
    false
}

/// Return the virtual event number `3000..3016` if `path` is `/dev/input/event<N>`.
pub fn udyn_index_for_dev_path(path: &[u8]) -> Option<i32> {
    let num = parse_index_after(path, b"/dev/input/event")?;
    if (UDYN_EVENT_BASE..UDYN_EVENT_BASE + UDYN_MAX as i32).contains(&num) {
        Some(num)
    } else {
        None
    }
}

/// Return the virtual event number `3000..3016` if `name` is `event<N>`.
pub fn udyn_index_for_basename(name: &[u8]) -> Option<i32> {
    let num = parse_index_after(name, b"event")?;
    if (UDYN_EVENT_BASE..UDYN_EVENT_BASE + UDYN_MAX as i32).contains(&num) {
        Some(num)
    } else {
        None
    }
}

/// Return the virtual event number `3000..3016` if `path` is `/sys/class/input/event<N>`.
pub fn udyn_index_for_sysclass_path(path: &[u8]) -> Option<i32> {
    let num = parse_index_after(path, b"/sys/class/input/event")?;
    if (UDYN_EVENT_BASE..UDYN_EVENT_BASE + UDYN_MAX as i32).contains(&num) {
        Some(num)
    } else {
        None
    }
}

/// Parse `tw_event<N>.sock` or `tw_event<N>.desc` into `(event_num, is_sock)`.
pub fn parse_socket_or_desc_filename(name: &[u8]) -> Option<(i32, bool)> {
    let rest = name.strip_prefix(b"tw_event")?;
    let (digits, is_sock) = if let Some(d) = rest.strip_suffix(b".sock") {
        (d, true)
    } else if let Some(d) = rest.strip_suffix(b".desc") {
        (d, false)
    } else {
        return None;
    };
    let num = parse_index_after(digits, b"")?;
    if (UDYN_EVENT_BASE..UDYN_EVENT_BASE + UDYN_MAX as i32).contains(&num) {
        Some((num, is_sock))
    } else {
        None
    }
}

/// Translate `count` records of `src_size` bytes (`16` or `24`) into native
/// [`NativeInputEvent`] structs.
///
/// # Safety
/// `src` must have at least `count * src_size` readable bytes and `dst` must
/// have at least `count * size_of::<NativeInputEvent>()` writable bytes.
pub unsafe fn translate_events(
    src: *const u8,
    count: usize,
    src_size: usize,
    dst: *mut u8,
) -> usize {
    let native_sz = size_of::<NativeInputEvent>();
    if src_size == native_sz {
        core::ptr::copy_nonoverlapping(src, dst, count * native_sz);
        return count;
    }
    let out = dst as *mut NativeInputEvent;
    for i in 0..count {
        let ev = if src_size == size_of::<InputEvent32>() {
            let mut raw = InputEvent32::default();
            core::ptr::copy_nonoverlapping(
                src.add(i * src_size),
                (&mut raw as *mut InputEvent32) as *mut u8,
                size_of::<InputEvent32>(),
            );
            NativeInputEvent {
                sec: raw.sec as c_long,
                usec: raw.usec as c_long,
                ev_type: raw.ev_type,
                code: raw.code,
                value: raw.value,
            }
        } else {
            let mut raw = InputEvent64::default();
            core::ptr::copy_nonoverlapping(
                src.add(i * src_size),
                (&mut raw as *mut InputEvent64) as *mut u8,
                size_of::<InputEvent64>(),
            );
            NativeInputEvent {
                sec: raw.sec as c_long,
                usec: raw.usec as c_long,
                ev_type: raw.ev_type,
                code: raw.code,
                value: raw.value,
            }
        };
        core::ptr::write_unaligned(out.add(i), ev);
    }
    count
}

/// Format a NUL-terminated path into `out` without heap allocation.
/// Returns the string length excluding the trailing NUL, or `None` if it did not fit.
pub fn write_cstr_parts(out: &mut [u8], parts: &[&[u8]]) -> Option<usize> {
    let mut pos = 0usize;
    for part in parts {
        if pos + part.len() + 1 > out.len() {
            return None;
        }
        out[pos..pos + part.len()].copy_from_slice(part);
        pos += part.len();
    }
    if pos >= out.len() {
        return None;
    }
    out[pos] = 0;
    Some(pos)
}

/// Format a non-negative integer into `buf` and return the formatted ASCII slice.
pub fn fmt_u32(mut n: u32, buf: &mut [u8; 16]) -> &[u8] {
    if n == 0 {
        buf[15] = b'0';
        return &buf[15..];
    }
    let mut i = buf.len();
    while n > 0 {
        i -= 1;
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    &buf[i..]
}

/// Helper to view a C string pointer as a byte slice (without trailing NUL).
///
/// # Safety
/// If `ptr` is non-null, it must point to a valid NUL-terminated string.
#[inline]
pub unsafe fn cstr_bytes<'a>(ptr: *const c_char) -> Option<&'a [u8]> {
    if ptr.is_null() {
        return None;
    }
    let mut len = 0usize;
    while *ptr.add(len) != 0 {
        len += 1;
    }
    Some(core::slice::from_raw_parts(ptr as *const u8, len))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_makedev_roundtrip() {
        let dev = virtual_event_devnum(3000);
        assert_eq!(dev_major(dev), INPUT_MAJOR);
        assert_eq!(dev_minor(dev), 3064);
    }

    #[test]
    fn test_path_parsers() {
        assert_eq!(udyn_index_for_dev_path(b"/dev/input/event3000"), Some(3000));
        assert_eq!(udyn_index_for_dev_path(b"/dev/input/event3015"), Some(3015));
        assert_eq!(udyn_index_for_dev_path(b"/dev/input/event2999"), None);
        assert_eq!(udyn_index_for_dev_path(b"/dev/input/event3016"), None);
        assert_eq!(udyn_index_for_dev_path(b"/dev/input/event3000x"), None);

        assert_eq!(
            udyn_index_for_sysclass_path(b"/sys/class/input/event3003"),
            Some(3003)
        );
        assert_eq!(udyn_index_for_basename(b"event3001"), Some(3001));
        assert_eq!(
            parse_socket_or_desc_filename(b"tw_event3002.sock"),
            Some((3002, true))
        );
        assert_eq!(
            parse_socket_or_desc_filename(b"tw_event3002.desc"),
            Some((3002, false))
        );
        assert_eq!(parse_socket_or_desc_filename(b"tw_event3002.tmp"), None);
    }

    #[test]
    fn test_hidraw_helpers() {
        assert!(is_hidraw_basename(b"hidraw0"));
        assert!(is_hidraw_basename(b"hidraw14"));
        assert!(!is_hidraw_basename(b"hidraw"));
        assert!(!is_hidraw_basename(b"hidraw0x"));
        assert_eq!(
            parse_hidraw_dev_path(b"/dev/hidraw3"),
            Some(&b"hidraw3"[..])
        );
        assert_eq!(parse_hidraw_dev_path(b"/dev/hidraw3/foo"), None);
        assert_eq!(parse_hidraw_dev_path(b"/dev/input/event0"), None);

        let allow = b"hidraw1\nhidraw4\r\n";
        assert!(hidraw_allow_contains(allow, b"hidraw1"));
        assert!(hidraw_allow_contains(allow, b"hidraw4"));
        assert!(!hidraw_allow_contains(allow, b"hidraw0"));
        assert!(!hidraw_allow_contains(allow, b"hidraw"));
        assert!(!hidraw_allow_contains(b"", b"hidraw1"));
    }

    #[test]
    fn test_bit_and_abs_helpers() {
        let mut desc = UdynDesc::new_default();
        assert!(desc.is_valid());
        assert!(test_bit(&desc.evbits, EV_SYN, EV_MAX));
        assert!(!test_bit(&desc.keybits, BTN_GAMEPAD, KEY_MAX));
        set_bit(&mut desc.keybits, BTN_GAMEPAD as c_int, KEY_MAX);
        assert!(test_bit(&desc.keybits, BTN_GAMEPAD, KEY_MAX));
        clear_bit(&mut desc.keybits, BTN_GAMEPAD, KEY_MAX);
        assert!(!test_bit(&desc.keybits, BTN_GAMEPAD, KEY_MAX));
        set_bit(&mut desc.keybits, -1, KEY_MAX);
        set_bit(&mut desc.keybits, 99999, KEY_MAX);

        let stick = InputAbsInfo {
            minimum: -32768,
            maximum: 32767,
            ..Default::default()
        };
        assert_eq!(default_abs_rest_value(0, &stick), 0);
        let unsigned_stick = InputAbsInfo {
            minimum: 0,
            maximum: 255,
            ..Default::default()
        };
        assert_eq!(default_abs_rest_value(0, &unsigned_stick), 127);
        let trigger = InputAbsInfo {
            minimum: 0,
            maximum: 255,
            ..Default::default()
        };
        assert_eq!(default_abs_rest_value(ABS_Z, &trigger), 0);
        assert_eq!(default_abs_rest_value(ABS_RZ, &trigger), 0);
    }

    #[test]
    fn test_translate_32_to_native() {
        let src = [
            InputEvent32 {
                sec: 123,
                usec: 456,
                ev_type: EV_KEY as u16,
                code: BTN_GAMEPAD as u16,
                value: 1,
            },
            InputEvent32 {
                sec: 123,
                usec: 457,
                ev_type: EV_SYN as u16,
                code: 0,
                value: 0,
            },
        ];
        let mut dst = [NativeInputEvent::default(); 2];
        let n = unsafe {
            translate_events(
                src.as_ptr() as *const u8,
                2,
                size_of::<InputEvent32>(),
                dst.as_mut_ptr() as *mut u8,
            )
        };
        assert_eq!(n, 2);
        assert_eq!(dst[0].sec, 123);
        assert_eq!(dst[0].usec, 456);
        assert_eq!(dst[0].ev_type, EV_KEY as u16);
        assert_eq!(dst[0].code, BTN_GAMEPAD as u16);
        assert_eq!(dst[0].value, 1);
        assert_eq!(dst[1].ev_type, EV_SYN as u16);
    }

    #[test]
    fn test_translate_64_to_native() {
        let src = [InputEvent64 {
            sec: 999,
            usec: 111,
            ev_type: EV_ABS as u16,
            code: 0,
            value: -16384,
        }];
        let mut dst = [NativeInputEvent::default(); 1];
        let n = unsafe {
            translate_events(
                src.as_ptr() as *const u8,
                1,
                size_of::<InputEvent64>(),
                dst.as_mut_ptr() as *mut u8,
            )
        };
        assert_eq!(n, 1);
        assert_eq!(dst[0].sec, 999);
        assert_eq!(dst[0].usec, 111);
        assert_eq!(dst[0].ev_type, EV_ABS as u16);
        assert_eq!(dst[0].value, -16384);
    }

    #[test]
    fn test_fmt_and_write_cstr() {
        let mut nbuf = [0u8; 16];
        assert_eq!(fmt_u32(0, &mut nbuf), b"0");
        assert_eq!(fmt_u32(3000, &mut nbuf), b"3000");

        let mut out = [0u8; 64];
        let len =
            write_cstr_parts(&mut out, &[b"/tmp/tw", b"/tw_event", b"3000", b".sock"]).unwrap();
        assert_eq!(&out[..len], b"/tmp/tw/tw_event3000.sock");
        assert_eq!(out[len], 0);
    }
}
