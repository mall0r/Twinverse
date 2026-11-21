//! Dynamic virtual device definitions built from `tw_event<N>.desc` files.

use std::env;
use std::ffi::{c_char, CString};
use std::fs;
use std::mem::size_of;
use std::path::Path;
use std::sync::{Arc, Mutex};

use twinverse_uinput_proto::{
    dev_major, dev_minor, hidraw_allow_contains, is_hidraw_basename, parse_socket_or_desc_filename,
    test_bit, udyn_index_for_basename, udyn_index_for_sysclass_path, virtual_event_devnum,
    UdynDesc, BTN_GAMEPAD, BTN_JOYSTICK, BTN_MOUSE, BUS_USB, EVDEV_MINOR_BASE, EV_KEY, EV_MAX,
    EV_REL, HIDRAW_ALLOW_FILENAME, INPUT_MAJOR, KEY_A, KEY_MAX, UDYN_EVENT_BASE, UDYN_MAX,
};

use crate::ffi::socket_dir;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NodeType {
    Event,
    InputParent,
    UsbParent,
}

pub struct DynDeviceDef {
    pub event_num: i32,
    pub vendor: u16,
    raw_desc: Vec<u8>,

    pub event_sysname: CString,
    pub event_syspath: CString,
    pub event_devnode: CString,
    pub event_properties: Vec<(CString, CString)>,

    pub input_parent_sysname: CString,
    pub input_parent_syspath: CString,
    pub input_parent_sysattrs: Vec<(CString, CString)>,
    pub input_parent_properties: Vec<(CString, CString)>,

    pub usb_parent_sysname: CString,
    pub usb_parent_syspath: CString,
    pub usb_parent_sysattrs: Vec<(CString, CString)>,
}

fn cstr(s: &str) -> CString {
    // Strip interior NULs defensively so CString::new never fails.
    let clean: Vec<u8> = s.bytes().filter(|&b| b != 0).collect();
    CString::new(clean).unwrap_or_else(|_| CString::new("").unwrap())
}

impl DynDeviceDef {
    pub fn from_desc(num: i32, desc: &UdynDesc, raw_desc: Vec<u8>) -> Self {
        let is_js = test_bit(&desc.keybits, BTN_GAMEPAD, KEY_MAX)
            || test_bit(&desc.keybits, BTN_JOYSTICK, KEY_MAX);
        let is_gamepad = test_bit(&desc.keybits, BTN_GAMEPAD, KEY_MAX);
        let is_mouse =
            test_bit(&desc.evbits, EV_REL, EV_MAX) && test_bit(&desc.keybits, BTN_MOUSE, KEY_MAX);
        let is_key =
            test_bit(&desc.evbits, EV_KEY, EV_MAX) && test_bit(&desc.keybits, KEY_A, KEY_MAX);

        let raw_name = desc.name_bytes();
        let name = if raw_name.is_empty() {
            "Twinverse Virtual Input".to_string()
        } else {
            String::from_utf8_lossy(raw_name).into_owned()
        };

        let bus = if desc.bustype != 0 {
            desc.bustype
        } else {
            BUS_USB
        };

        let vid_hex = format!("{:04x}", desc.vendor);
        let pid_hex = format!("{:04x}", desc.product);
        let ver_hex = format!("{:04x}", desc.version_id);
        let bus_hex = format!("{:04x}", bus);
        let phys = format!("twinverse/virtinput/event{num}/input0");
        let uniq = format!("TWIN{num}");

        let input_uevent = format!(
            "PRODUCT={bus:x}/{:x}/{:x}/{:x}\nNAME=\"{name}\"\nPHYS=\"{phys}\"\nUNIQ=\"{uniq}\"\n",
            desc.vendor, desc.product, desc.version_id
        );
        let usb_uevent = format!(
            "PRODUCT={:x}/{:x}/{:x}\nDEVTYPE=usb_device\n",
            desc.vendor, desc.product, desc.version_id
        );

        let input_parent_sysname = cstr(&format!("input{num}"));
        let input_parent_syspath = cstr(&format!(
            "/sys/devices/virtual/twinverse_uinput{num}/input/input{num}"
        ));
        let input_parent_sysattrs = vec![
            (cstr("id/vendor"), cstr(&vid_hex)),
            (cstr("id/product"), cstr(&pid_hex)),
            (cstr("id/version"), cstr(&ver_hex)),
            (cstr("name"), cstr(&name)),
            (cstr("phys"), cstr(&phys)),
            (cstr("uniq"), cstr(&uniq)),
            (cstr("id/bustype"), cstr(&bus_hex)),
            (cstr("uevent"), cstr(&input_uevent)),
        ];

        let mut input_parent_properties = vec![(cstr("ID_INPUT"), cstr("1"))];
        if is_js {
            input_parent_properties.push((cstr("ID_INPUT_JOYSTICK"), cstr("1")));
        } else if is_mouse {
            input_parent_properties.push((cstr("ID_INPUT_MOUSE"), cstr("1")));
        } else if is_key {
            input_parent_properties.push((cstr("ID_INPUT_KEYBOARD"), cstr("1")));
        }

        let event_sysname = cstr(&format!("event{num}"));
        let event_syspath = cstr(&format!(
            "/sys/devices/virtual/twinverse_uinput{num}/input/input{num}/event{num}"
        ));
        let event_devnode = cstr(&format!("/dev/input/event{num}"));

        let mut event_properties = vec![
            (cstr("DEVNAME"), event_devnode.clone()),
            (cstr("ID_INPUT"), cstr("1")),
            (cstr("ID_VENDOR_ID"), cstr(&vid_hex)),
            (cstr("ID_MODEL_ID"), cstr(&pid_hex)),
        ];
        if bus == BUS_USB {
            event_properties.push((cstr("ID_BUS"), cstr("usb")));
        }
        if is_js {
            event_properties.push((cstr("ID_INPUT_JOYSTICK"), cstr("1")));
            if is_gamepad {
                event_properties.push((cstr("ID_INPUT_GAMEPAD"), cstr("1")));
            }
        } else if is_mouse {
            event_properties.push((cstr("ID_INPUT_MOUSE"), cstr("1")));
        } else if is_key {
            event_properties.push((cstr("ID_INPUT_KEYBOARD"), cstr("1")));
        }

        let usb_parent_sysname = cstr(&format!("twinverse_uinput_usb{num}"));
        let usb_parent_syspath = cstr(&format!(
            "/sys/devices/virtual/usb/twinverse_uinput_usb{num}"
        ));
        let usb_parent_sysattrs = vec![
            (cstr("idVendor"), cstr(&vid_hex)),
            (cstr("idProduct"), cstr(&pid_hex)),
            (cstr("product"), cstr(&name)),
            (cstr("bcdDevice"), cstr(&ver_hex)),
            (cstr("uevent"), cstr(&usb_uevent)),
        ];

        Self {
            event_num: num,
            vendor: desc.vendor,
            raw_desc,
            event_sysname,
            event_syspath,
            event_devnode,
            event_properties,
            input_parent_sysname,
            input_parent_syspath,
            input_parent_sysattrs,
            input_parent_properties,
            usb_parent_sysname,
            usb_parent_syspath,
            usb_parent_sysattrs,
        }
    }

    pub fn syspath(&self, ty: NodeType) -> &CString {
        match ty {
            NodeType::Event => &self.event_syspath,
            NodeType::InputParent => &self.input_parent_syspath,
            NodeType::UsbParent => &self.usb_parent_syspath,
        }
    }

    pub fn sysname(&self, ty: NodeType) -> &CString {
        match ty {
            NodeType::Event => &self.event_sysname,
            NodeType::InputParent => &self.input_parent_sysname,
            NodeType::UsbParent => &self.usb_parent_sysname,
        }
    }

    pub fn devpath_ptr(&self, ty: NodeType) -> *const c_char {
        // Every syspath starts with "/sys/..." (4 bytes).
        unsafe { self.syspath(ty).as_ptr().add(4) }
    }

    pub fn subsystem_cstr(ty: NodeType) -> *const c_char {
        match ty {
            NodeType::UsbParent => b"usb\0".as_ptr() as *const c_char,
            NodeType::Event | NodeType::InputParent => b"input\0".as_ptr() as *const c_char,
        }
    }

    pub fn devtype_cstr(ty: NodeType) -> *const c_char {
        match ty {
            NodeType::UsbParent => b"usb_device\0".as_ptr() as *const c_char,
            NodeType::Event | NodeType::InputParent => std::ptr::null(),
        }
    }

    pub fn devnode_ptr(&self, ty: NodeType) -> *const c_char {
        match ty {
            NodeType::Event => self.event_devnode.as_ptr(),
            NodeType::InputParent | NodeType::UsbParent => std::ptr::null(),
        }
    }

    pub fn devnum(&self, ty: NodeType) -> u64 {
        match ty {
            NodeType::Event => virtual_event_devnum(self.event_num),
            NodeType::InputParent | NodeType::UsbParent => 0,
        }
    }

    pub fn property_table(&self, ty: NodeType) -> &[(CString, CString)] {
        match ty {
            NodeType::Event => &self.event_properties,
            NodeType::InputParent => &self.input_parent_properties,
            NodeType::UsbParent => &[],
        }
    }

    pub fn sysattr_table(&self, ty: NodeType) -> &[(CString, CString)] {
        match ty {
            NodeType::InputParent => &self.input_parent_sysattrs,
            NodeType::UsbParent => &self.usb_parent_sysattrs,
            NodeType::Event => &[],
        }
    }

    pub fn property_value(&self, ty: NodeType, key: &[u8]) -> *const c_char {
        for (k, v) in self.property_table(ty) {
            if k.as_bytes() == key {
                return v.as_ptr();
            }
        }
        if key == b"SUBSYSTEM" {
            return Self::subsystem_cstr(ty);
        }
        if key == b"DEVPATH" {
            return self.devpath_ptr(ty);
        }
        std::ptr::null()
    }

    pub fn sysattr_value(&self, ty: NodeType, key: &[u8]) -> *const c_char {
        for (k, v) in self.sysattr_table(ty) {
            if k.as_bytes() == key {
                return v.as_ptr();
            }
        }
        std::ptr::null()
    }
}

static DYN_SLOTS: Mutex<[Option<Arc<DynDeviceDef>>; UDYN_MAX]> =
    Mutex::new([const { None }; UDYN_MAX]);

pub fn is_socket_live(event_num: i32) -> bool {
    let path = format!("{}/tw_event{event_num}.sock", socket_dir());
    Path::new(&path).exists()
}

fn read_desc(event_num: i32) -> Option<(UdynDesc, Vec<u8>)> {
    let path = format!("{}/tw_event{event_num}.desc", socket_dir());
    let bytes = fs::read(&path).ok()?;
    if bytes.len() != size_of::<UdynDesc>() {
        return None;
    }
    let mut desc = UdynDesc::zeroed();
    unsafe {
        std::ptr::copy_nonoverlapping(
            bytes.as_ptr(),
            (&mut desc as *mut UdynDesc) as *mut u8,
            size_of::<UdynDesc>(),
        );
    }
    if !desc.is_valid() {
        return None;
    }
    Some((desc, bytes))
}

/// Refresh cached dynamic definitions from `tw_event<N>.desc` for all live sockets.
/// Existing slots are retained on removal so `"remove"` monitor events still resolve.
pub fn refresh_dyn_devices() {
    let mut slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    for i in 0..UDYN_MAX {
        let num = UDYN_EVENT_BASE + i as i32;
        if !is_socket_live(num) {
            continue;
        }
        let Some((desc, bytes)) = read_desc(num) else {
            continue;
        };
        let unchanged = slots[i]
            .as_ref()
            .is_some_and(|existing| existing.raw_desc == bytes);
        if !unchanged {
            slots[i] = Some(Arc::new(DynDeviceDef::from_desc(num, &desc, bytes)));
        }
    }
}

/// Return all currently live dynamic devices.
pub fn live_dyn_devices() -> Vec<Arc<DynDeviceDef>> {
    refresh_dyn_devices();
    let slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    let mut out = Vec::new();
    for slot in slots.iter().flatten() {
        if is_socket_live(slot.event_num) {
            out.push(Arc::clone(slot));
        }
    }
    out
}

pub fn find_by_syspath(syspath: &[u8]) -> Option<(Arc<DynDeviceDef>, NodeType)> {
    refresh_dyn_devices();
    let slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };

    if let Some(num) = udyn_index_for_sysclass_path(syspath) {
        let idx = (num - UDYN_EVENT_BASE) as usize;
        if let Some(def) = slots.get(idx).and_then(|s| s.as_ref()) {
            return Some((Arc::clone(def), NodeType::Event));
        }
    }

    for def in slots.iter().flatten() {
        if def.event_syspath.as_bytes() == syspath {
            return Some((Arc::clone(def), NodeType::Event));
        }
        if def.input_parent_syspath.as_bytes() == syspath {
            return Some((Arc::clone(def), NodeType::InputParent));
        }
        if def.usb_parent_syspath.as_bytes() == syspath {
            return Some((Arc::clone(def), NodeType::UsbParent));
        }
    }
    None
}

pub fn find_by_devnum(devnum: u64) -> Option<(Arc<DynDeviceDef>, NodeType)> {
    if dev_major(devnum) != INPUT_MAJOR {
        return None;
    }
    let minor = dev_minor(devnum);
    if minor < EVDEV_MINOR_BASE {
        return None;
    }
    let event_num = (minor - EVDEV_MINOR_BASE) as i32;
    if !(UDYN_EVENT_BASE..UDYN_EVENT_BASE + UDYN_MAX as i32).contains(&event_num) {
        return None;
    }
    refresh_dyn_devices();
    let idx = (event_num - UDYN_EVENT_BASE) as usize;
    let slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    slots[idx]
        .as_ref()
        .map(|d| (Arc::clone(d), NodeType::Event))
}

pub fn find_by_subsystem_sysname(
    subsystem: &[u8],
    sysname: &[u8],
) -> Option<(Arc<DynDeviceDef>, NodeType)> {
    refresh_dyn_devices();
    let slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    for def in slots.iter().flatten() {
        if subsystem == b"input" {
            if def.event_sysname.as_bytes() == sysname {
                return Some((Arc::clone(def), NodeType::Event));
            }
            if def.input_parent_sysname.as_bytes() == sysname {
                return Some((Arc::clone(def), NodeType::InputParent));
            }
        } else if subsystem == b"usb" && def.usb_parent_sysname.as_bytes() == sysname {
            return Some((Arc::clone(def), NodeType::UsbParent));
        }
    }
    None
}

/// Resolve a socket filename (`tw_event<N>.sock`) to its cached `DynDeviceDef`.
pub fn find_by_socket_filename(filename: &[u8]) -> Option<Arc<DynDeviceDef>> {
    let (num, is_sock) = parse_socket_or_desc_filename(filename)?;
    if !is_sock {
        return None;
    }
    refresh_dyn_devices();
    let idx = (num - UDYN_EVENT_BASE) as usize;
    let slots = match DYN_SLOTS.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(def) = &slots[idx] {
        return Some(Arc::clone(def));
    }
    // Fallback if a remove event arrived before we ever saw the descriptor:
    // synthesize a minimal definition so the consumer receives the remove event.
    let desc = UdynDesc::new_default();
    Some(Arc::new(DynDeviceDef::from_desc(num, &desc, Vec::new())))
}

/// Return true when dynamic `hidraw` filtering is enabled via `TWINVERSE_HIDRAW_FILTER=1`.
pub fn hidraw_filter_enabled() -> bool {
    env::var_os("TWINVERSE_HIDRAW_FILTER").is_some_and(|v| v == "1")
}

fn parse_allowed_hidraws(bytes: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    for line in bytes.split(|&b| b == b'\n' || b == b'\r') {
        if is_hidraw_basename(line) {
            if let Ok(s) = std::str::from_utf8(line) {
                if !out.iter().any(|existing: &String| existing == s) {
                    out.push(s.to_string());
                }
            }
        }
    }
    out
}

/// Read the list of currently permitted `hidraw<N>` basenames from `tw_hidraw.allow`.
pub fn read_allowed_hidraws() -> Vec<String> {
    let path = format!("{}/{HIDRAW_ALLOW_FILENAME}", socket_dir());
    match fs::read(&path) {
        Ok(bytes) => parse_allowed_hidraws(&bytes),
        Err(_) => Vec::new(),
    }
}

fn is_hidraw_hidden_with_bytes(
    filter_enabled: bool,
    allow_bytes: Option<&[u8]>,
    sysname: &[u8],
) -> bool {
    if !filter_enabled || !is_hidraw_basename(sysname) {
        return false;
    }
    match allow_bytes {
        Some(bytes) => !hidraw_allow_contains(bytes, sysname),
        None => true,
    }
}

/// True if `hidraw<N>` should be hidden from this sandboxed instance.
pub fn is_real_hidraw_hidden(sysname: &[u8]) -> bool {
    if !hidraw_filter_enabled() || !is_hidraw_basename(sysname) {
        return false;
    }
    let path = format!("{}/{HIDRAW_ALLOW_FILENAME}", socket_dir());
    let bytes = fs::read(&path).ok();
    is_hidraw_hidden_with_bytes(true, bytes.as_deref(), sysname)
}

/// True if a real `input` node collides with our synthetic `event3000..3015` range.
pub fn is_real_input_sysname_hidden(sysname: &[u8]) -> bool {
    udyn_index_for_basename(sysname).is_some()
}

#[cfg(test)]
fn is_real_syspath_hidden_with_hidraw(
    syspath: &[u8],
    filter_enabled: bool,
    allow_bytes: Option<&[u8]>,
) -> bool {
    let Some(slash) = syspath.iter().rposition(|&b| b == b'/') else {
        return false;
    };
    let basename = &syspath[slash + 1..];
    if syspath.windows(7).any(|w| w == b"/input/") && is_real_input_sysname_hidden(basename) {
        return true;
    }
    if syspath.windows(8).any(|w| w == b"/hidraw/")
        && is_hidraw_hidden_with_bytes(filter_enabled, allow_bytes, basename)
    {
        return true;
    }
    false
}

pub fn is_real_syspath_hidden(syspath: &[u8]) -> bool {
    let Some(slash) = syspath.iter().rposition(|&b| b == b'/') else {
        return false;
    };
    let basename = &syspath[slash + 1..];
    if syspath.windows(7).any(|w| w == b"/input/") && is_real_input_sysname_hidden(basename) {
        return true;
    }
    if syspath.windows(8).any(|w| w == b"/hidraw/") && is_real_hidraw_hidden(basename) {
        return true;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use twinverse_uinput_proto::set_bit;

    #[test]
    fn test_dyn_device_def_formatting() {
        let mut desc = UdynDesc::new_default();
        desc.bustype = BUS_USB;
        desc.vendor = 0x28de;
        desc.product = 0x11ff;
        desc.version_id = 0x0001;
        let name = b"Microsoft X-Box 360 pad";
        desc.name[..name.len()].copy_from_slice(name);
        set_bit(&mut desc.evbits, EV_KEY as i32, EV_MAX);
        set_bit(&mut desc.keybits, BTN_GAMEPAD as i32, KEY_MAX);

        let def = DynDeviceDef::from_desc(3000, &desc, Vec::new());
        assert_eq!(
            def.event_syspath.to_str().unwrap(),
            "/sys/devices/virtual/twinverse_uinput3000/input/input3000/event3000"
        );
        assert_eq!(def.event_devnode.to_str().unwrap(), "/dev/input/event3000");
        assert_eq!(def.devnum(NodeType::Event), virtual_event_devnum(3000));

        unsafe {
            let v =
                std::ffi::CStr::from_ptr(def.sysattr_value(NodeType::InputParent, b"id/vendor"));
            assert_eq!(v.to_str().unwrap(), "28de");
            let p =
                std::ffi::CStr::from_ptr(def.sysattr_value(NodeType::InputParent, b"id/product"));
            assert_eq!(p.to_str().unwrap(), "11ff");
            let uev = std::ffi::CStr::from_ptr(def.sysattr_value(NodeType::InputParent, b"uevent"));
            assert!(uev.to_str().unwrap().contains("PRODUCT=3/28de/11ff/1\n"));
            let prop =
                std::ffi::CStr::from_ptr(def.property_value(NodeType::Event, b"ID_INPUT_JOYSTICK"));
            assert_eq!(prop.to_str().unwrap(), "1");
            let vid =
                std::ffi::CStr::from_ptr(def.property_value(NodeType::Event, b"ID_VENDOR_ID"));
            assert_eq!(vid.to_str().unwrap(), "28de");
            let pid = std::ffi::CStr::from_ptr(def.property_value(NodeType::Event, b"ID_MODEL_ID"));
            assert_eq!(pid.to_str().unwrap(), "11ff");
            let bus = std::ffi::CStr::from_ptr(def.property_value(NodeType::Event, b"ID_BUS"));
            assert_eq!(bus.to_str().unwrap(), "usb");
        }
    }

    #[test]
    fn test_real_syspath_hidden_only_for_synthetic_range() {
        assert!(!is_real_syspath_hidden(
            b"/sys/devices/pci0000:00/input/input5/event12"
        ));
        assert!(is_real_syspath_hidden(
            b"/sys/devices/virtual/input/input3000/event3000"
        ));
        assert!(!is_real_syspath_hidden(
            b"/sys/devices/virtual/input/input1/js0"
        ));
    }

    #[test]
    fn test_hidraw_filtering_and_allowlist_parsing() {
        assert_eq!(
            parse_allowed_hidraws(b"hidraw1\nhidraw4\ninvalid\nhidraw1\n"),
            vec!["hidraw1".to_string(), "hidraw4".to_string()]
        );
        let allow = Some(b"hidraw2\nhidraw5\n".as_slice());
        assert!(!is_real_syspath_hidden_with_hidraw(
            b"/sys/devices/pci0000:00/hidraw/hidraw2",
            true,
            allow
        ));
        assert!(is_real_syspath_hidden_with_hidraw(
            b"/sys/devices/pci0000:00/hidraw/hidraw3",
            true,
            allow
        ));
        assert!(is_real_syspath_hidden_with_hidraw(
            b"/sys/devices/pci0000:00/hidraw/hidraw2",
            true,
            None
        ));
        assert!(!is_real_syspath_hidden_with_hidraw(
            b"/sys/devices/pci0000:00/hidraw/hidraw3",
            false,
            None
        ));
    }
}
