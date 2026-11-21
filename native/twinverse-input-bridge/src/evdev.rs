//! Linux evdev discovery, descriptor probing, identity matching, and dynamic
//! sibling `/dev/hidraw*` resolution.

use std::collections::HashSet;
use std::ffi::{c_int, CString};
use std::fs;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};

use twinverse_uinput_proto::{
    clear_bit, is_hidraw_basename, set_bit, test_bit, udyn_bytes, UdynDesc, ABS_CNT, ABS_MAX,
    EV_ABS, EV_FF, EV_KEY, EV_MAX, EV_MSC, EV_REL, EV_SYN, HIDRAW_ALLOW_FILENAME, KEY_MAX,
};

use crate::ffi::{
    close, eviocgabs, eviocgbit, eviocgid, eviocgkey, eviocgname, eviocgphys, eviocgprop,
    eviocguniq, last_errno, open, EACCES, O_CLOEXEC, O_NONBLOCK, O_RDONLY,
};

/// Stable hardware fingerprint captured when a physical controller is opened.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeviceIdentity {
    pub bustype: u16,
    pub vendor: u16,
    pub product: u16,
    pub version: u16,
    pub name: Vec<u8>,
    pub phys: Vec<u8>,
    pub uniq: Vec<u8>,
}

/// An open physical evdev handle paired with its probed descriptor and state.
pub struct ProbedEvdev {
    pub fd: c_int,
    pub resolved_path: PathBuf,
    pub identity: DeviceIdentity,
    pub desc: UdynDesc,
    pub initial_keys: [u8; udyn_bytes(KEY_MAX)],
}

impl Drop for ProbedEvdev {
    fn drop(&mut self) {
        if self.fd >= 0 {
            unsafe {
                close(self.fd);
            }
            self.fd = -1;
        }
    }
}

impl ProbedEvdev {
    /// Take ownership of the raw fd without closing it on drop.
    pub fn into_parts(
        mut self,
    ) -> (
        c_int,
        PathBuf,
        DeviceIdentity,
        UdynDesc,
        [u8; udyn_bytes(KEY_MAX)],
    ) {
        let fd = self.fd;
        self.fd = -1;
        let path = std::mem::take(&mut self.resolved_path);
        let identity = self.identity.clone();
        let desc = self.desc;
        let keys = self.initial_keys;
        (fd, path, identity, desc, keys)
    }
}

/// Outcome of attempting to probe a candidate evdev path.
pub enum ProbeOutcome {
    Opened(ProbedEvdev),
    PermissionDenied,
    Unavailable,
}

/// Open `path` read-only non-blocking and query its evdev capabilities and identity.
pub fn probe_evdev(path: &Path) -> ProbeOutcome {
    let resolved = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let Ok(cpath) = CString::new(resolved.as_os_str().as_bytes()) else {
        return ProbeOutcome::Unavailable;
    };
    let fd = unsafe { open(cpath.as_ptr(), O_RDONLY | O_NONBLOCK | O_CLOEXEC) };
    if fd < 0 {
        if last_errno() == EACCES {
            return ProbeOutcome::PermissionDenied;
        }
        return ProbeOutcome::Unavailable;
    }

    let Some(id) = eviocgid(fd) else {
        unsafe {
            close(fd);
        }
        return ProbeOutcome::Unavailable;
    };

    let mut name_buf = [0u8; 256];
    let name_len = eviocgname(fd, &mut name_buf);
    let mut phys_buf = [0u8; 256];
    let phys_len = eviocgphys(fd, &mut phys_buf);
    let mut uniq_buf = [0u8; 256];
    let uniq_len = eviocguniq(fd, &mut uniq_buf);

    let mut desc = UdynDesc::new_default();
    desc.bustype = id.bustype;
    desc.vendor = id.vendor;
    desc.product = id.product;
    desc.version_id = id.version;

    let copy_name = name_len.min(desc.name.len().saturating_sub(1));
    desc.name[..copy_name].copy_from_slice(&name_buf[..copy_name]);
    desc.name[copy_name] = 0;

    let _ = eviocgbit(fd, 0, &mut desc.evbits);
    set_bit(&mut desc.evbits, EV_SYN as c_int, EV_MAX);
    // Clear EV_FF because the read-only userspace bridge does not accept FF uploads.
    clear_bit(&mut desc.evbits, EV_FF, EV_MAX);

    if test_bit(&desc.evbits, EV_KEY, EV_MAX) {
        let _ = eviocgbit(fd, EV_KEY as u32, &mut desc.keybits);
    }
    if test_bit(&desc.evbits, EV_REL, EV_MAX) {
        let _ = eviocgbit(fd, EV_REL as u32, &mut desc.relbits);
    }
    if test_bit(&desc.evbits, EV_ABS, EV_MAX) {
        let _ = eviocgbit(fd, EV_ABS as u32, &mut desc.absbits);
        for code in 0..ABS_CNT {
            if test_bit(&desc.absbits, code, ABS_MAX) {
                if let Some(info) = eviocgabs(fd, code as u32) {
                    desc.absinfo[code] = info;
                }
            }
        }
    }
    if test_bit(&desc.evbits, EV_MSC, EV_MAX) {
        let _ = eviocgbit(fd, EV_MSC as u32, &mut desc.mscbits);
    }
    let _ = eviocgprop(fd, &mut desc.propbits);

    let mut initial_keys = [0u8; udyn_bytes(KEY_MAX)];
    let _ = eviocgkey(fd, &mut initial_keys);

    let identity = DeviceIdentity {
        bustype: id.bustype,
        vendor: id.vendor,
        product: id.product,
        version: id.version,
        name: name_buf[..name_len].to_vec(),
        phys: phys_buf[..phys_len].to_vec(),
        uniq: uniq_buf[..uniq_len].to_vec(),
    };

    ProbeOutcome::Opened(ProbedEvdev {
        fd,
        resolved_path: resolved,
        identity,
        desc,
        initial_keys,
    })
}

/// Score how closely `candidate` matches `target` (`Some(3)` best, `None` rejected).
///
/// `excluded_phys` contains the `phys` strings of OTHER identical-model controllers
/// that were already plugged in alongside `target` at startup, preventing a
/// disconnected instance from stealing another player's identical controller.
pub fn match_identity_score(
    target: &DeviceIdentity,
    candidate: &DeviceIdentity,
    excluded_phys: &HashSet<Vec<u8>>,
) -> Option<u8> {
    if candidate.vendor != target.vendor || candidate.product != target.product {
        return None;
    }
    if !target.name.is_empty() && candidate.name != target.name {
        return None;
    }

    // If the original controller had a hardware serial / Bluetooth MAC (`uniq`),
    // require an exact `uniq` match so multiple identical wireless pads never cross-talk.
    if !target.uniq.is_empty() {
        return if candidate.uniq == target.uniq {
            Some(3)
        } else {
            None
        };
    }

    // Reject a candidate that carries a distinct non-empty `uniq` when target had none.
    if !candidate.uniq.is_empty() {
        return None;
    }

    // Exact physical bus/port match (handles kernel event number increment on same USB port).
    if !target.phys.is_empty() && candidate.phys == target.phys {
        return Some(2);
    }

    // Port-change fallback: allow reconnecting the same controller model on a new USB port,
    // unless that port belonged to a sibling identical controller at startup.
    if !candidate.phys.is_empty() && excluded_phys.contains(&candidate.phys) {
        return None;
    }
    Some(1)
}

/// Snapshot the `phys` paths of all OTHER currently connected evdev devices
/// sharing `(vendor, product, name)` with `target` so we never steal them.
pub fn collect_sibling_phys(target: &DeviceIdentity, own_resolved_path: &Path) -> HashSet<Vec<u8>> {
    let mut siblings = HashSet::new();
    if !target.uniq.is_empty() {
        // Unique serial/MAC already disambiguates siblings.
        return siblings;
    }
    for path in list_dev_input_events(Path::new("/dev/input")) {
        if path == own_resolved_path {
            continue;
        }
        if let ProbeOutcome::Opened(probed) = probe_evdev(&path) {
            if probed.identity.vendor == target.vendor
                && probed.identity.product == target.product
                && probed.identity.name == target.name
                && !probed.identity.phys.is_empty()
                && probed.identity.phys != target.phys
            {
                siblings.insert(probed.identity.phys.clone());
            }
        }
    }
    siblings
}

fn is_stable_symlink_path(path: &Path) -> bool {
    let s = path.as_os_str().as_bytes();
    s.starts_with(b"/dev/input/by-id/") || s.starts_with(b"/dev/input/by-path/")
}

/// Return all `/dev/input/event<N>` paths sorted numerically.
pub fn list_dev_input_events(dev_input: &Path) -> Vec<PathBuf> {
    let Ok(rd) = fs::read_dir(dev_input) else {
        return Vec::new();
    };
    let mut items: Vec<(u32, PathBuf)> = Vec::new();
    for entry in rd.flatten() {
        let name = entry.file_name();
        let bytes = name.as_bytes();
        if let Some(rest) = bytes.strip_prefix(b"event") {
            if !rest.is_empty() && rest.iter().all(|b| b.is_ascii_digit()) {
                if let Ok(num) = std::str::from_utf8(rest).unwrap_or("").parse::<u32>() {
                    items.push((num, entry.path()));
                }
            }
        }
    }
    items.sort_by_key(|(num, _)| *num);
    items.into_iter().map(|(_, p)| p).collect()
}

/// Attempt to locate and open the physical controller for `device_id`.
///
/// Returns `(Option<ProbedEvdev>, saw_eacces)`. When `saw_eacces` is true, the
/// caller should retry shortly because `systemd-udevd` may still be applying
/// `uaccess` ACLs to the newly hotplugged device node.
pub fn find_and_open_evdev(
    device_id: &Path,
    initial_resolved: Option<&Path>,
    target_identity: Option<&DeviceIdentity>,
    excluded_phys: &HashSet<Vec<u8>>,
) -> (Option<ProbedEvdev>, bool) {
    let mut saw_eacces = false;

    // Priority 1: Direct lookup via `device_id` (and `initial_resolved` on first startup).
    let mut direct_candidates: Vec<&Path> = Vec::new();
    if !device_id.as_os_str().is_empty() {
        direct_candidates.push(device_id);
    }
    if target_identity.is_none() {
        if let Some(res) = initial_resolved {
            if !res.as_os_str().is_empty() && res != device_id {
                direct_candidates.push(res);
            }
        }
    }

    for candidate in direct_candidates {
        match probe_evdev(candidate) {
            ProbeOutcome::Opened(probed) => {
                if let Some(target) = target_identity {
                    // For stable by-id/by-path symlinks, verify vendor/product match
                    // (or accept if match_identity_score succeeds); for raw eventN paths,
                    // always verify identity so a reused event number is never mistaken.
                    let ok = if is_stable_symlink_path(candidate) {
                        probed.identity.vendor == target.vendor
                            && probed.identity.product == target.product
                    } else {
                        match_identity_score(target, &probed.identity, excluded_phys).is_some()
                    };
                    if ok {
                        return (Some(probed), false);
                    }
                } else {
                    return (Some(probed), false);
                }
            }
            ProbeOutcome::PermissionDenied => saw_eacces = true,
            ProbeOutcome::Unavailable => {}
        }
    }

    // Priority 2: Scan `/dev/input/event*` when we already have a captured identity
    // (handles Bluetooth reconnects, event number changes, and USB port changes).
    let Some(target) = target_identity else {
        return (None, saw_eacces);
    };

    let mut best: Option<(u8, ProbedEvdev)> = None;
    for path in list_dev_input_events(Path::new("/dev/input")) {
        match probe_evdev(&path) {
            ProbeOutcome::Opened(probed) => {
                if let Some(score) = match_identity_score(target, &probed.identity, excluded_phys) {
                    let replace = best.as_ref().is_none_or(|(best_s, _)| score > *best_s);
                    if replace {
                        best = Some((score, probed));
                        if score == 3 {
                            break;
                        }
                    }
                }
            }
            ProbeOutcome::PermissionDenied => saw_eacces = true,
            ProbeOutcome::Unavailable => {}
        }
    }

    (best.map(|(_, p)| p), saw_eacces)
}

fn find_usb_device_ancestor(sysdev: &Path) -> Option<PathBuf> {
    for candidate in sysdev.ancestors() {
        if candidate.join("idVendor").is_file() && candidate.join("idProduct").is_file() {
            return Some(candidate.to_path_buf());
        }
    }
    None
}

fn resolve_event_sysdev(event_path: &Path, sysfs_root: &Path) -> Option<PathBuf> {
    let resolved = fs::canonicalize(event_path).unwrap_or_else(|_| event_path.to_path_buf());
    let name = resolved.file_name()?.as_bytes();
    if !name.starts_with(b"event") {
        return None;
    }
    let sysdev = sysfs_root
        .join("class/input")
        .join(resolved.file_name()?)
        .join("device");
    fs::canonicalize(&sysdev).ok()
}

/// Find all `hidraw<N>` basenames belonging to the same physical HID or USB
/// device as `event_path` (matching `src/services/virtual_uinput.py`).
pub fn find_allowed_hidraws(event_path: &Path, sysfs_root: &Path) -> Vec<String> {
    let hidraw_class = sysfs_root.join("class/hidraw");
    let Ok(rd) = fs::read_dir(&hidraw_class) else {
        return Vec::new();
    };
    let Some(event_sysdev) = resolve_event_sysdev(event_path, sysfs_root) else {
        return Vec::new();
    };
    let event_usb_parent = find_usb_device_ancestor(&event_sysdev);

    let mut allowed = Vec::new();
    for entry in rd.flatten() {
        let name = entry.file_name();
        let bytes = name.as_bytes();
        if !is_hidraw_basename(bytes) {
            continue;
        }
        let Ok(hid_sysdev) = fs::canonicalize(entry.path().join("device")) else {
            continue;
        };
        let belongs = event_sysdev == hid_sysdev
            || event_sysdev.starts_with(&hid_sysdev)
            || (event_usb_parent.is_some()
                && find_usb_device_ancestor(&hid_sysdev) == event_usb_parent);
        if belongs {
            if let Ok(s) = std::str::from_utf8(bytes) {
                allowed.push(s.to_string());
            }
        }
    }
    allowed.sort();
    allowed
}

/// Atomically write `<socket_dir>/tw_hidraw.allow` via temp file + rename so
/// consumers see either the old or new allowlist and `inotify` receives `IN_MOVED_TO`.
pub fn write_hidraw_allow(socket_dir: &Path, allowed: &[String]) -> std::io::Result<()> {
    let target = socket_dir.join(HIDRAW_ALLOW_FILENAME);
    let tmp = socket_dir.join(format!(
        ".{HIDRAW_ALLOW_FILENAME}.{}.tmp",
        std::process::id()
    ));
    let mut content = String::new();
    for name in allowed {
        content.push_str(name);
        content.push('\n');
    }
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(content.as_bytes())?;
        f.flush()?;
    }
    if let Err(err) = fs::rename(&tmp, &target) {
        let _ = fs::remove_file(&tmp);
        return Err(err);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn make_id(vendor: u16, product: u16, name: &str, phys: &str, uniq: &str) -> DeviceIdentity {
        DeviceIdentity {
            bustype: 3,
            vendor,
            product,
            version: 0x0114,
            name: name.as_bytes().to_vec(),
            phys: phys.as_bytes().to_vec(),
            uniq: uniq.as_bytes().to_vec(),
        }
    }

    #[test]
    fn test_identity_matching_and_sibling_isolation() {
        let pad1 = make_id(
            0x045e,
            0x028e,
            "Microsoft X-Box 360 pad",
            "usb-0000:00:14.0-5/input0",
            "",
        );
        let pad2 = make_id(
            0x045e,
            0x028e,
            "Microsoft X-Box 360 pad",
            "usb-0000:00:14.0-6/input0",
            "",
        );
        let pad1_new_port = make_id(
            0x045e,
            0x028e,
            "Microsoft X-Box 360 pad",
            "usb-0000:00:14.0-7/input0",
            "",
        );
        let mouse = make_id(
            0x046d,
            0xc077,
            "USB Optical Mouse",
            "usb-0000:00:14.0-1/input0",
            "",
        );

        let mut excluded = HashSet::new();
        excluded.insert(pad2.phys.clone());

        // Same port reconnect -> score 2
        assert_eq!(match_identity_score(&pad1, &pad1, &excluded), Some(2));
        // Player 2's identical pad -> blocked by excluded_phys!
        assert_eq!(match_identity_score(&pad1, &pad2, &excluded), None);
        // Replugged into a free third USB port -> score 1
        assert_eq!(
            match_identity_score(&pad1, &pad1_new_port, &excluded),
            Some(1)
        );
        // Unrelated device -> rejected
        assert_eq!(match_identity_score(&pad1, &mouse, &excluded), None);

        // Bluetooth controllers with MAC in `uniq` never cross-talk even without excluded_phys
        let ds1 = make_id(
            0x054c,
            0x0ce6,
            "DualSense Wireless Controller",
            "",
            "aa:bb:cc:dd:ee:01",
        );
        let ds2 = make_id(
            0x054c,
            0x0ce6,
            "DualSense Wireless Controller",
            "",
            "aa:bb:cc:dd:ee:02",
        );
        let empty = HashSet::new();
        assert_eq!(match_identity_score(&ds1, &ds1, &empty), Some(3));
        assert_eq!(match_identity_score(&ds1, &ds2, &empty), None);
    }

    #[test]
    fn test_find_allowed_hidraws_synthetic_sysfs() {
        let tmp = std::env::temp_dir().join(format!("tw_bridge_sysfs_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);

        let sysfs = tmp.join("sys");
        let usb1 = sysfs.join("devices/pci0/usb1/1-5");
        let usb2 = sysfs.join("devices/pci0/usb1/1-6");
        let input1 = usb1.join("1-5:1.0/0003:045E:028E.0001/input/input10");
        let hid1 = usb1.join("1-5:1.0/0003:045E:028E.0001");
        let hid_sibling = usb1.join("1-5:1.1/0003:045E:028E.0002");
        let hid_other = usb2.join("1-6:1.0/0003:054C:0CE6.0003");

        fs::create_dir_all(&input1).unwrap();
        fs::create_dir_all(&hid_sibling).unwrap();
        fs::create_dir_all(&hid_other).unwrap();
        fs::write(usb1.join("idVendor"), "045e\n").unwrap();
        fs::write(usb1.join("idProduct"), "028e\n").unwrap();
        fs::write(usb2.join("idVendor"), "054c\n").unwrap();
        fs::write(usb2.join("idProduct"), "0ce6\n").unwrap();

        fs::create_dir_all(sysfs.join("class/input/event24")).unwrap();
        symlink(&input1, sysfs.join("class/input/event24/device")).unwrap();

        fs::create_dir_all(sysfs.join("class/hidraw/hidraw1")).unwrap();
        symlink(&hid1, sysfs.join("class/hidraw/hidraw1/device")).unwrap();
        fs::create_dir_all(sysfs.join("class/hidraw/hidraw4")).unwrap();
        symlink(&hid_sibling, sysfs.join("class/hidraw/hidraw4/device")).unwrap();
        fs::create_dir_all(sysfs.join("class/hidraw/hidraw2")).unwrap();
        symlink(&hid_other, sysfs.join("class/hidraw/hidraw2/device")).unwrap();

        let allowed = find_allowed_hidraws(Path::new("/dev/input/event24"), &sysfs);
        assert_eq!(allowed, vec!["hidraw1".to_string(), "hidraw4".to_string()]);

        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn test_write_hidraw_allow_atomic() {
        let tmp = std::env::temp_dir().join(format!("tw_bridge_allow_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        write_hidraw_allow(&tmp, &["hidraw1".into(), "hidraw4".into()]).unwrap();
        let data = fs::read_to_string(tmp.join(HIDRAW_ALLOW_FILENAME)).unwrap();
        assert_eq!(data, "hidraw1\nhidraw4\n");

        write_hidraw_allow(&tmp, &[]).unwrap();
        let data = fs::read_to_string(tmp.join(HIDRAW_ALLOW_FILENAME)).unwrap();
        assert_eq!(data, "");

        let _ = fs::remove_dir_all(&tmp);
    }
}
