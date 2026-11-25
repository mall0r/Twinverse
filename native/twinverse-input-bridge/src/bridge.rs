//! Persistent userspace evdev bridge with hotplug reconnection and safe
//! disconnect neutralization.
//!
//! Presents the assigned physical controller to the sandbox as
//! `/dev/input/event3000` (via `<socket_dir>/tw_event3000.sock` and
//! `tw_event3000.desc`) and maintains `<socket_dir>/tw_hidraw.allow` in sync
//! across physical disconnects and reconnects.

use std::collections::HashSet;
use std::ffi::{c_int, c_long, c_void, CString};
use std::fs;
use std::io::Write;
use std::mem::{size_of, zeroed};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::ptr;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use twinverse_uinput_proto::{
    clear_bit, default_abs_rest_value, set_bit, test_bit, udyn_bytes, NativeInputEvent, UdynDesc,
    ABS_CNT, ABS_MAX, EV_ABS, EV_KEY, EV_SYN, HIDRAW_ALLOW_FILENAME, INPUT_MUTE_FILENAME, KEY_MAX,
    SYN_REPORT, TWCTL_CMD_REGISTER_MONITOR, TWCTL_CMD_SET_SANDBOX_MUTE, TWCTL_MAGIC,
    TWCTL_PACKET_LEN, UDYN_EVENT_BASE, UDYN_MAX_CLIENTS,
};

use crate::evdev::{
    collect_sibling_phys, find_allowed_hidraws, find_and_open_evdev, write_hidraw_allow,
    DeviceIdentity,
};
use crate::ffi::{
    accept4, bind, chmod, close, eviocgrab, geteuid, getsockopt, inotify_add_watch, inotify_init1,
    last_errno, listen, open, pipe2, poll, read, realtime_sec_usec, send, socket, write, PollFd,
    SockaddrUn, Ucred, AF_UNIX, EAGAIN, EINTR, EWOULDBLOCK, IN_ATTRIB, IN_CLOEXEC, IN_CREATE,
    IN_DELETE, IN_MOVED_TO, IN_NONBLOCK, MSG_DONTWAIT, MSG_NOSIGNAL, O_CLOEXEC, O_DIRECTORY,
    O_NONBLOCK, O_RDONLY, POLLERR, POLLHUP, POLLIN, POLLNVAL, SOCK_CLOEXEC, SOCK_NONBLOCK,
    SOCK_STREAM, SOL_SOCKET, SO_PEERCRED,
};

const FAST_RETRY_MS: c_int = 100;
const FALLBACK_POLL_MS: c_int = 500;
const FAST_RETRY_WINDOW: Duration = Duration::from_secs(3);
const UNMUTE_SUPPRESS_TIMEOUT: Duration = Duration::from_millis(1500);

/// Configuration for the physical controller bridge.
#[derive(Clone, Debug)]
pub struct BridgeConfig {
    pub socket_dir: PathBuf,
    pub device_id: PathBuf,
    pub resolved_event: Option<PathBuf>,
    pub event_num: i32,
    pub grab_exclusive: bool,
}

impl BridgeConfig {
    pub fn new(socket_dir: PathBuf, device_id: PathBuf, resolved_event: Option<PathBuf>) -> Self {
        Self {
            socket_dir,
            device_id,
            resolved_event,
            event_num: UDYN_EVENT_BASE,
            grab_exclusive: true,
        }
    }
}

/// Handle to a running background bridge thread.
pub struct BridgeHandle {
    stop_write_fd: c_int,
    join_handle: Option<JoinHandle<()>>,
}

impl BridgeHandle {
    /// Signal the bridge thread to exit cleanly, join it, and clean up socket files.
    pub fn stop_and_join(mut self) {
        self.signal_stop();
        if let Some(handle) = self.join_handle.take() {
            let _ = handle.join();
        }
    }

    fn signal_stop(&mut self) {
        if self.stop_write_fd >= 0 {
            let byte: u8 = 1;
            unsafe {
                let _ = write(self.stop_write_fd, (&byte as *const u8) as *const c_void, 1);
                close(self.stop_write_fd);
            }
            self.stop_write_fd = -1;
        }
    }
}

impl Drop for BridgeHandle {
    fn drop(&mut self) {
        self.signal_stop();
        if let Some(handle) = self.join_handle.take() {
            let _ = handle.join();
        }
    }
}

/// Build a neutralizer frame releasing every held key/button and recentering
/// every displaced `EV_ABS` axis so a mid-session unplug never leaves stuck inputs.
pub fn build_neutralizer_events(
    desc: &UdynDesc,
    pressed_keys: &mut [u8; udyn_bytes(KEY_MAX)],
    abs_values: &mut [i32; ABS_CNT],
    sec: c_long,
    usec: c_long,
) -> Vec<NativeInputEvent> {
    let mut events = Vec::new();

    for code in 0..=KEY_MAX {
        if test_bit(pressed_keys, code, KEY_MAX) {
            clear_bit(pressed_keys, code, KEY_MAX);
            events.push(NativeInputEvent {
                sec,
                usec,
                ev_type: EV_KEY as u16,
                code: code as u16,
                value: 0,
            });
        }
    }

    for code in 0..ABS_CNT {
        if !test_bit(&desc.absbits, code, ABS_MAX) {
            continue;
        }
        let rest = default_abs_rest_value(code, &desc.absinfo[code]);
        if abs_values[code] != rest {
            abs_values[code] = rest;
            events.push(NativeInputEvent {
                sec,
                usec,
                ev_type: EV_ABS as u16,
                code: code as u16,
                value: rest,
            });
        }
    }

    if !events.is_empty() {
        events.push(NativeInputEvent {
            sec,
            usec,
            ev_type: EV_SYN as u16,
            code: SYN_REPORT,
            value: 0,
        });
    }

    events
}

fn write_desc_atomic(desc_path: &Path, desc: &UdynDesc) -> std::io::Result<()> {
    let tmp = desc_path.with_extension(format!("desc.{}.tmp", std::process::id()));
    let bytes = unsafe {
        std::slice::from_raw_parts(
            (desc as *const UdynDesc) as *const u8,
            size_of::<UdynDesc>(),
        )
    };
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.flush()?;
    }
    if let Err(err) = fs::rename(&tmp, desc_path) {
        let _ = fs::remove_file(&tmp);
        return Err(err);
    }
    Ok(())
}

fn bind_unix_listener(sock_path: &Path) -> Option<c_int> {
    let path_bytes = sock_path.as_os_str().as_bytes();
    if path_bytes.is_empty() {
        return None;
    }
    let _ = fs::remove_file(sock_path);

    // If the host path exceeds the 108-byte `sun_path` limit (e.g. Flatpak
    // instance homes with long usernames), bind via `/proc/self/fd/<dirfd>/<name>`.
    let mut dir_fd: c_int = -1;
    let bind_path_owned: Vec<u8>;
    let bind_bytes: &[u8] = if path_bytes.len() < 108 {
        path_bytes
    } else {
        let parent = sock_path.parent()?;
        let fname = sock_path.file_name()?;
        let cparent = CString::new(parent.as_os_str().as_bytes()).ok()?;
        dir_fd = unsafe { open(cparent.as_ptr(), O_RDONLY | O_DIRECTORY | O_CLOEXEC) };
        if dir_fd < 0 {
            return None;
        }
        bind_path_owned = format!("/proc/self/fd/{dir_fd}/{}", fname.to_string_lossy()).into_bytes();
        if bind_path_owned.len() >= 108 {
            unsafe {
                close(dir_fd);
            }
            return None;
        }
        &bind_path_owned
    };

    let fd = unsafe { socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0) };
    if fd < 0 {
        if dir_fd >= 0 {
            unsafe {
                close(dir_fd);
            }
        }
        return None;
    }

    let mut addr: SockaddrUn = unsafe { zeroed() };
    addr.sun_family = AF_UNIX as u16;
    addr.sun_path[..bind_bytes.len()].copy_from_slice(bind_bytes);
    let addrlen = (size_of::<u16>() + bind_bytes.len() + 1) as u32;

    let bind_rc = unsafe { bind(fd, &addr as *const SockaddrUn, addrlen) };
    if dir_fd >= 0 {
        unsafe {
            close(dir_fd);
        }
    }
    if bind_rc != 0 {
        unsafe {
            close(fd);
        }
        return None;
    }

    if let Ok(cpath) = CString::new(path_bytes) {
        unsafe {
            let _ = chmod(cpath.as_ptr(), 0o600);
        }
    }

    if unsafe { listen(fd, 16) } != 0 {
        unsafe {
            close(fd);
        }
        let _ = fs::remove_file(sock_path);
        return None;
    }

    Some(fd)
}

struct BridgeClient {
    fd: c_int,
    is_monitor: bool,
    mute_requested: bool,
    rx_buf: [u8; TWCTL_PACKET_LEN],
    rx_len: usize,
}

impl BridgeClient {
    fn new(fd: c_int) -> Self {
        Self {
            fd,
            is_monitor: false,
            mute_requested: false,
            rx_buf: [0u8; TWCTL_PACKET_LEN],
            rx_len: 0,
        }
    }
}

struct BridgeState {
    cfg: BridgeConfig,
    desc_path: PathBuf,
    sock_path: PathBuf,
    allow_path: PathBuf,
    mute_path: PathBuf,
    stop_read_fd: c_int,
    listen_fd: c_int,
    phys_fd: c_int,
    phys_grabbed: bool,
    inotify_fd: c_int,
    by_id_wd: c_int,
    identity: Option<DeviceIdentity>,
    excluded_phys: HashSet<Vec<u8>>,
    desc: Option<UdynDesc>,
    pressed_keys: [u8; udyn_bytes(KEY_MAX)],
    suppressed_keys: [u8; udyn_bytes(KEY_MAX)],
    suppress_until: Option<Instant>,
    abs_values: [i32; ABS_CNT],
    sandbox_muted: bool,
    mute_file_active: bool,
    clients: Vec<BridgeClient>,
    fast_retry_until: Option<Instant>,
    log_enabled: bool,
}

impl BridgeState {
    fn new(cfg: BridgeConfig, stop_read_fd: c_int) -> Self {
        let desc_path = cfg
            .socket_dir
            .join(format!("tw_event{}.desc", cfg.event_num));
        let sock_path = cfg
            .socket_dir
            .join(format!("tw_event{}.sock", cfg.event_num));
        let allow_path = cfg.socket_dir.join(HIDRAW_ALLOW_FILENAME);
        let mute_path = cfg.socket_dir.join(INPUT_MUTE_FILENAME);
        let log_enabled =
            std::env::var_os("TWINVERSE_UINPUT_LOG").is_some_and(|v| !v.is_empty() && v != "0");

        let inotify_fd = unsafe { inotify_init1(IN_NONBLOCK | IN_CLOEXEC) };
        let mut by_id_wd = -1;
        if inotify_fd >= 0 {
            unsafe {
                let _ = inotify_add_watch(
                    inotify_fd,
                    b"/dev/input\0".as_ptr() as *const i8,
                    IN_CREATE | IN_MOVED_TO | IN_DELETE | IN_ATTRIB,
                );
                by_id_wd = inotify_add_watch(
                    inotify_fd,
                    b"/dev/input/by-id\0".as_ptr() as *const i8,
                    IN_CREATE | IN_MOVED_TO | IN_DELETE,
                );
                let _ = inotify_add_watch(
                    inotify_fd,
                    b"/dev/input/by-path\0".as_ptr() as *const i8,
                    IN_CREATE | IN_MOVED_TO | IN_DELETE,
                );
            }
        }

        Self {
            cfg,
            desc_path,
            sock_path,
            allow_path,
            mute_path,
            stop_read_fd,
            listen_fd: -1,
            phys_fd: -1,
            phys_grabbed: false,
            inotify_fd,
            by_id_wd,
            identity: None,
            excluded_phys: HashSet::new(),
            desc: None,
            pressed_keys: [0u8; udyn_bytes(KEY_MAX)],
            suppressed_keys: [0u8; udyn_bytes(KEY_MAX)],
            suppress_until: None,
            abs_values: [0i32; ABS_CNT],
            sandbox_muted: false,
            mute_file_active: false,
            clients: Vec::new(),
            fast_retry_until: None,
            log_enabled,
        }
    }

    fn log(&self, msg: &str) {
        if self.log_enabled {
            eprintln!("[twinverse-input-bridge] {msg}");
        }
    }

    fn release_physical_fd(&mut self) {
        if self.phys_fd >= 0 {
            if self.phys_grabbed {
                let _ = eviocgrab(self.phys_fd, false);
                self.phys_grabbed = false;
            }
            unsafe {
                close(self.phys_fd);
            }
            self.phys_fd = -1;
        }
    }

    fn init_before_spawn(&mut self) {
        let _ = fs::create_dir_all(&self.cfg.socket_dir);
        let _ = fs::remove_file(&self.mute_path);
        self.mute_file_active = false;
        // Always start with an explicit allowlist file so hidraw filtering has
        // deterministic state before the sandbox starts.
        let _ = write_hidraw_allow(&self.cfg.socket_dir, &[]);
        if !self.try_connect_physical() {
            self.log(&format!(
                "controller {:?} not currently present; waiting for hotplug",
                self.cfg.device_id
            ));
        }
    }

    fn try_connect_physical(&mut self) -> bool {
        if self.phys_fd >= 0 {
            return true;
        }
        let (found, saw_eacces) = find_and_open_evdev(
            &self.cfg.device_id,
            self.cfg.resolved_event.as_deref(),
            self.identity.as_ref(),
            &self.excluded_phys,
        );
        if saw_eacces {
            self.fast_retry_until = Some(Instant::now() + FAST_RETRY_WINDOW);
        }
        let Some(probed) = found else {
            return false;
        };

        let (fd, resolved_path, identity, desc, initial_keys) = probed.into_parts();
        if self.identity.is_none() {
            self.excluded_phys = collect_sibling_phys(&identity, &resolved_path);
            self.identity = Some(identity.clone());
        }

        if let Err(err) = write_desc_atomic(&self.desc_path, &desc) {
            self.log(&format!("failed to write {:?}: {err}", self.desc_path));
            unsafe {
                close(fd);
            }
            return false;
        }

        if self.listen_fd < 0 {
            let Some(lfd) = bind_unix_listener(&self.sock_path) else {
                self.log(&format!("failed to bind {:?}", self.sock_path));
                unsafe {
                    close(fd);
                }
                return false;
            };
            self.listen_fd = lfd;
        }

        let allowed_hidraws = find_allowed_hidraws(&resolved_path, Path::new("/sys"));
        if let Err(err) = write_hidraw_allow(&self.cfg.socket_dir, &allowed_hidraws) {
            self.log(&format!("failed to update {:?}: {err}", self.allow_path));
        }

        let grabbed = if self.cfg.grab_exclusive {
            let ok = eviocgrab(fd, true);
            if !ok {
                self.log(&format!(
                    "EVIOCGRAB failed for {:?} (errno={}); continuing without exclusive grab",
                    resolved_path,
                    last_errno()
                ));
            }
            ok
        } else {
            false
        };

        self.pressed_keys = initial_keys;
        for code in 0..ABS_CNT {
            self.abs_values[code] = desc.absinfo[code].value;
        }
        self.desc = Some(desc);
        self.phys_fd = fd;
        self.phys_grabbed = grabbed;
        self.fast_retry_until = None;

        self.log(&format!(
            "connected {:?} (vid={:04x} pid={:04x}) -> event{}, grabbed={}, hidraw={:?}",
            resolved_path,
            identity.vendor,
            identity.product,
            self.cfg.event_num,
            grabbed,
            allowed_hidraws
        ));
        true
    }

    fn has_suppressed_keys(&self) -> bool {
        self.suppressed_keys.iter().any(|&b| b != 0)
    }

    fn set_mute_file(&mut self, active: bool) {
        if self.mute_file_active == active {
            return;
        }
        if active {
            let _ = fs::write(&self.mute_path, b"1\n");
        } else {
            let _ = fs::remove_file(&self.mute_path);
        }
        self.mute_file_active = active;
    }

    fn sync_mute_file(&mut self) {
        if self
            .suppress_until
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            self.suppressed_keys = [0u8; udyn_bytes(KEY_MAX)];
            self.suppress_until = None;
        }
        let want_file = self.sandbox_muted || self.has_suppressed_keys();
        self.set_mute_file(want_file);
    }

    fn update_sandbox_mute(&mut self) {
        let want_muted = self
            .clients
            .iter()
            .any(|c| c.is_monitor && c.mute_requested);
        if want_muted == self.sandbox_muted {
            return;
        }
        if want_muted {
            self.sandbox_muted = true;
            self.suppressed_keys = [0u8; udyn_bytes(KEY_MAX)];
            self.suppress_until = None;
            self.sync_mute_file();
            if let Some(desc) = self.desc {
                let (sec, usec) = realtime_sec_usec();
                // Neutralize sandbox state from a copy so physical held-key tracking remains exact.
                let mut sandbox_keys = self.pressed_keys;
                let mut sandbox_abs = self.abs_values;
                let neutral = build_neutralizer_events(
                    &desc,
                    &mut sandbox_keys,
                    &mut sandbox_abs,
                    sec,
                    usec,
                );
                if !neutral.is_empty() {
                    self.broadcast_events_to(&neutral, false);
                }
            }
            self.log("sandbox controller input muted by host overlay monitor");
        } else {
            self.sandbox_muted = false;
            // Suppress trailing releases of buttons still held when closing the overlay
            // (e.g. releasing Cancel/B) so they never leak into Steam or the game.
            self.suppressed_keys = self.pressed_keys;
            self.suppress_until = if self.has_suppressed_keys() {
                Some(Instant::now() + UNMUTE_SUPPRESS_TIMEOUT)
            } else {
                None
            };
            self.sync_mute_file();
            self.log("sandbox controller input unmuted by host overlay monitor");
        }
    }

    fn handle_disconnect(&mut self) {
        self.release_physical_fd();
        let _ = write_hidraw_allow(&self.cfg.socket_dir, &[]);
        self.suppressed_keys = [0u8; udyn_bytes(KEY_MAX)];
        self.suppress_until = None;
        self.sync_mute_file();

        if let Some(desc) = self.desc {
            let (sec, usec) = realtime_sec_usec();
            let neutral = build_neutralizer_events(
                &desc,
                &mut self.pressed_keys,
                &mut self.abs_values,
                sec,
                usec,
            );
            if !neutral.is_empty() {
                self.broadcast_events_to(&neutral, true);
                if !self.sandbox_muted {
                    self.broadcast_events_to(&neutral, false);
                }
            }
        }
        self.log("physical controller disconnected; keeping virtual slot alive for reconnection");
    }

    fn track_event_state(&mut self, ev: &NativeInputEvent) {
        if ev.ev_type == EV_KEY as u16 {
            let code = ev.code as usize;
            if ev.value != 0 {
                set_bit(&mut self.pressed_keys, code as c_int, KEY_MAX);
            } else {
                clear_bit(&mut self.pressed_keys, code, KEY_MAX);
            }
        } else if ev.ev_type == EV_ABS as u16 {
            let code = ev.code as usize;
            if code < ABS_CNT {
                self.abs_values[code] = ev.value;
            }
        }
    }

    fn broadcast_events_to(&mut self, events: &[NativeInputEvent], monitors_only: bool) {
        if events.is_empty() || self.clients.is_empty() {
            return;
        }
        let byte_len = events.len() * size_of::<NativeInputEvent>();
        let ptr = events.as_ptr() as *const c_void;
        let mut idx = 0;
        let mut removed_monitor = false;
        while idx < self.clients.len() {
            if self.clients[idx].is_monitor != monitors_only {
                idx += 1;
                continue;
            }
            let cfd = self.clients[idx].fd;
            let rc = unsafe { send(cfd, ptr, byte_len, MSG_DONTWAIT | MSG_NOSIGNAL) };
            let drop_client = if rc < 0 {
                let err = last_errno();
                err != EAGAIN && err != EWOULDBLOCK && err != EINTR
            } else {
                (rc as usize) != byte_len
            };
            if drop_client {
                unsafe {
                    close(cfd);
                }
                let removed = self.clients.swap_remove(idx);
                if removed.is_monitor && removed.mute_requested {
                    removed_monitor = true;
                }
            } else {
                idx += 1;
            }
        }
        if removed_monitor {
            self.update_sandbox_mute();
        }
    }

    fn forward_physical_batch(&mut self, batch: &[NativeInputEvent]) {
        for ev in batch {
            self.track_event_state(ev);
        }
        // Host monitors always receive raw events so the exit overlay stays responsive.
        self.broadcast_events_to(batch, true);

        if self.sandbox_muted {
            return;
        }

        self.sync_mute_file();
        if !self.has_suppressed_keys() {
            self.broadcast_events_to(batch, false);
            return;
        }

        let mut filtered = Vec::with_capacity(batch.len());
        let mut frame_has_non_syn = false;
        for &ev in batch {
            if ev.ev_type == EV_KEY as u16 {
                let code = ev.code as usize;
                if test_bit(&self.suppressed_keys, code, KEY_MAX) {
                    if ev.value == 0 {
                        clear_bit(&mut self.suppressed_keys, code, KEY_MAX);
                        continue;
                    } else if ev.value == 2 {
                        continue;
                    } else {
                        clear_bit(&mut self.suppressed_keys, code, KEY_MAX);
                    }
                }
                frame_has_non_syn = true;
                filtered.push(ev);
            } else if ev.ev_type == EV_SYN as u16 && ev.code == SYN_REPORT {
                if frame_has_non_syn {
                    filtered.push(ev);
                    frame_has_non_syn = false;
                }
            } else {
                frame_has_non_syn = true;
                filtered.push(ev);
            }
        }
        if !self.has_suppressed_keys() {
            self.suppress_until = None;
            self.sync_mute_file();
        }
        if !filtered.is_empty() {
            self.broadcast_events_to(&filtered, false);
        }
    }

    fn read_client_control(&mut self, cfd: c_int) -> bool {
        let Some(pos) = self.clients.iter().position(|c| c.fd == cfd) else {
            return false;
        };
        let mut tmp = [0u8; 64];
        let mut disconnected = false;
        let mut mute_changed = false;
        loop {
            let rc = unsafe { read(cfd, tmp.as_mut_ptr() as *mut c_void, tmp.len()) };
            if rc > 0 {
                let client = &mut self.clients[pos];
                for &byte in &tmp[..(rc as usize)] {
                    client.rx_buf[client.rx_len] = byte;
                    client.rx_len += 1;
                    if client.rx_len == TWCTL_PACKET_LEN {
                        let pkt = client.rx_buf;
                        client.rx_len = 0;
                        if pkt[..5] == TWCTL_MAGIC {
                            match pkt[5] {
                                TWCTL_CMD_REGISTER_MONITOR => {
                                    client.is_monitor = true;
                                }
                                TWCTL_CMD_SET_SANDBOX_MUTE => {
                                    if client.is_monitor {
                                        let want = pkt[6] != 0;
                                        if client.mute_requested != want {
                                            client.mute_requested = want;
                                            mute_changed = true;
                                        }
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                }
                if (rc as usize) < tmp.len() {
                    break;
                }
            } else if rc == 0 {
                disconnected = true;
                break;
            } else {
                let err = last_errno();
                if err == EAGAIN || err == EWOULDBLOCK {
                    break;
                }
                if err == EINTR {
                    continue;
                }
                disconnected = true;
                break;
            }
        }
        if mute_changed {
            self.update_sandbox_mute();
        }
        disconnected
    }

    fn accept_clients(&mut self) {
        if self.listen_fd < 0 {
            return;
        }
        let my_uid = unsafe { geteuid() };
        loop {
            let cfd = unsafe {
                accept4(
                    self.listen_fd,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    SOCK_NONBLOCK | SOCK_CLOEXEC,
                )
            };
            if cfd < 0 {
                break;
            }
            let mut cred: Ucred = unsafe { zeroed() };
            let mut cred_len = size_of::<Ucred>() as u32;
            let cred_ok = unsafe {
                getsockopt(
                    cfd,
                    SOL_SOCKET,
                    SO_PEERCRED,
                    (&mut cred as *mut Ucred) as *mut c_void,
                    &mut cred_len,
                ) == 0
                    && cred.uid == my_uid
            };
            if !cred_ok || self.clients.len() >= UDYN_MAX_CLIENTS {
                unsafe {
                    close(cfd);
                }
                continue;
            }
            self.clients.push(BridgeClient::new(cfd));
        }
    }

    fn drain_physical_events(&mut self) {
        if self.phys_fd < 0 {
            return;
        }
        let mut batch = [NativeInputEvent::default(); 64];
        let byte_cap = batch.len() * size_of::<NativeInputEvent>();
        loop {
            let rc = unsafe { read(self.phys_fd, batch.as_mut_ptr() as *mut c_void, byte_cap) };
            if rc > 0 {
                let count = (rc as usize) / size_of::<NativeInputEvent>();
                if count > 0 {
                    self.forward_physical_batch(&batch[..count]);
                }
                if (rc as usize) < byte_cap {
                    break;
                }
            } else if rc == 0 {
                self.handle_disconnect();
                break;
            } else {
                let err = last_errno();
                if err == EAGAIN || err == EWOULDBLOCK {
                    break;
                }
                if err == EINTR {
                    continue;
                }
                // ENODEV, EIO, etc. -> physical unplug.
                self.handle_disconnect();
                break;
            }
        }
    }

    fn drain_inotify(&mut self) -> bool {
        if self.inotify_fd < 0 {
            return false;
        }
        let mut saw_any = false;
        let mut buf = [0u8; 4096];
        loop {
            let rc = unsafe { read(self.inotify_fd, buf.as_mut_ptr() as *mut c_void, buf.len()) };
            if rc > 0 {
                saw_any = true;
            } else {
                break;
            }
        }
        if saw_any && self.by_id_wd < 0 {
            self.by_id_wd = unsafe {
                inotify_add_watch(
                    self.inotify_fd,
                    b"/dev/input/by-id\0".as_ptr() as *const i8,
                    IN_CREATE | IN_MOVED_TO | IN_DELETE,
                )
            };
            unsafe {
                let _ = inotify_add_watch(
                    self.inotify_fd,
                    b"/dev/input/by-path\0".as_ptr() as *const i8,
                    IN_CREATE | IN_MOVED_TO | IN_DELETE,
                );
            }
        }
        saw_any
    }

    fn run_loop(&mut self) {
        let mut pollfds: Vec<PollFd> = Vec::with_capacity(16);
        loop {
            pollfds.clear();

            let stop_idx = pollfds.len();
            pollfds.push(PollFd {
                fd: self.stop_read_fd,
                events: POLLIN,
                revents: 0,
            });

            let listen_idx = if self.listen_fd >= 0 {
                let i = pollfds.len();
                pollfds.push(PollFd {
                    fd: self.listen_fd,
                    events: POLLIN,
                    revents: 0,
                });
                Some(i)
            } else {
                None
            };

            let phys_idx = if self.phys_fd >= 0 {
                let i = pollfds.len();
                pollfds.push(PollFd {
                    fd: self.phys_fd,
                    events: POLLIN,
                    revents: 0,
                });
                Some(i)
            } else {
                None
            };

            let inotify_idx = if self.inotify_fd >= 0 {
                let i = pollfds.len();
                pollfds.push(PollFd {
                    fd: self.inotify_fd,
                    events: POLLIN,
                    revents: 0,
                });
                Some(i)
            } else {
                None
            };

            let clients_start = pollfds.len();
            for client in &self.clients {
                // Watch POLLIN for host-monitor TWCTL commands as well as POLLHUP/POLLERR.
                pollfds.push(PollFd {
                    fd: client.fd,
                    events: POLLIN,
                    revents: 0,
                });
            }

            let mut timeout_ms = if self.phys_fd >= 0 {
                -1
            } else if self
                .fast_retry_until
                .is_some_and(|deadline| Instant::now() < deadline)
            {
                FAST_RETRY_MS
            } else {
                FALLBACK_POLL_MS
            };
            if let Some(deadline) = self.suppress_until {
                let remaining = deadline
                    .saturating_duration_since(Instant::now())
                    .as_millis()
                    .min(c_int::MAX as u128) as c_int;
                timeout_ms = if timeout_ms < 0 {
                    remaining.max(1)
                } else {
                    timeout_ms.min(remaining.max(1))
                };
            }

            let rc = unsafe { poll(pollfds.as_mut_ptr(), pollfds.len() as u64, timeout_ms) };
            if rc < 0 {
                if last_errno() == EINTR {
                    continue;
                }
                break;
            }

            if (pollfds[stop_idx].revents & (POLLIN | POLLHUP | POLLERR)) != 0 {
                break;
            }

            if self.suppress_until.is_some() {
                self.sync_mute_file();
            }

            // Process incoming TWCTL packets and reap disconnected clients BEFORE
            // accepting new ones or broadcasting, matching by fd so indices never desync.
            let mut clients_removed = false;
            for pfd in &pollfds[clients_start..] {
                let mut drop_client = (pfd.revents & (POLLHUP | POLLERR | POLLNVAL)) != 0;
                if (pfd.revents & POLLIN) != 0 && self.read_client_control(pfd.fd) {
                    drop_client = true;
                }
                if drop_client {
                    if let Some(pos) = self.clients.iter().position(|c| c.fd == pfd.fd) {
                        let client = self.clients.swap_remove(pos);
                        unsafe {
                            close(client.fd);
                        }
                        clients_removed = true;
                    }
                }
            }
            if clients_removed {
                self.update_sandbox_mute();
            }

            if let Some(i) = listen_idx {
                if (pollfds[i].revents & POLLIN) != 0 {
                    self.accept_clients();
                }
            }

            if let Some(i) = phys_idx {
                let rev = pollfds[i].revents;
                if (rev & POLLIN) != 0 {
                    self.drain_physical_events();
                } else if (rev & (POLLHUP | POLLERR | POLLNVAL)) != 0 {
                    self.handle_disconnect();
                }
            }

            let mut hotplug_hint = false;
            if let Some(i) = inotify_idx {
                if (pollfds[i].revents & POLLIN) != 0 && self.drain_inotify() {
                    hotplug_hint = true;
                }
            }

            if self.phys_fd < 0 {
                if hotplug_hint {
                    self.fast_retry_until = Some(Instant::now() + FAST_RETRY_WINDOW);
                }
                let _ = self.try_connect_physical();
            }
        }
    }
}

impl Drop for BridgeState {
    fn drop(&mut self) {
        self.release_physical_fd();
        if self.listen_fd >= 0 {
            unsafe {
                close(self.listen_fd);
            }
            self.listen_fd = -1;
        }
        for client in self.clients.drain(..) {
            unsafe {
                close(client.fd);
            }
        }
        if self.inotify_fd >= 0 {
            unsafe {
                close(self.inotify_fd);
            }
            self.inotify_fd = -1;
        }
        if self.stop_read_fd >= 0 {
            unsafe {
                close(self.stop_read_fd);
            }
            self.stop_read_fd = -1;
        }
        let _ = fs::remove_file(&self.sock_path);
        let _ = fs::remove_file(&self.desc_path);
        let _ = fs::remove_file(&self.allow_path);
        let _ = fs::remove_file(&self.mute_path);
    }
}

/// A synchronously initialized bridge ready to spawn its background thread
/// after the parent process forks the supervised child.
pub struct PreparedBridge {
    stop_write_fd: c_int,
    state: BridgeState,
}

impl PreparedBridge {
    /// Initialize the bridge synchronously on the main thread so
    /// `tw_event3000.desc`, `tw_event3000.sock`, and `tw_hidraw.allow` exist
    /// before the child process is forked.
    pub fn prepare(cfg: BridgeConfig) -> std::io::Result<Self> {
        let mut fds = [-1 as c_int; 2];
        if unsafe { pipe2(fds.as_mut_ptr(), O_NONBLOCK | O_CLOEXEC) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
        let stop_read_fd = fds[0];
        let stop_write_fd = fds[1];

        let mut state = BridgeState::new(cfg, stop_read_fd);
        state.init_before_spawn();

        Ok(Self {
            stop_write_fd,
            state,
        })
    }

    /// Launch the background hotplug and event-forwarding thread.
    pub fn spawn_thread(self) -> std::io::Result<BridgeHandle> {
        let stop_write_fd = self.stop_write_fd;
        let mut state = self.state;
        let join_handle = thread::Builder::new()
            .name("twinverse-input-bridge".to_string())
            .spawn(move || {
                state.run_loop();
            })?;

        Ok(BridgeHandle {
            stop_write_fd,
            join_handle: Some(join_handle),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use twinverse_uinput_proto::{InputAbsInfo, ABS_RZ, ABS_Z, BTN_GAMEPAD};

    #[test]
    fn test_bridge_config_defaults_to_exclusive_grab() {
        let cfg = BridgeConfig::new(
            PathBuf::from("/tmp/sock"),
            PathBuf::from("/dev/input/by-id/usb-pad"),
            None,
        );
        assert!(cfg.grab_exclusive);
        assert_eq!(cfg.event_num, UDYN_EVENT_BASE);
    }

    #[test]
    fn test_neutralizer_releases_keys_and_recenters_axes() {
        let mut desc = UdynDesc::new_default();
        set_bit(&mut desc.absbits, 0, ABS_MAX); // ABS_X: signed stick [-32768, 32767]
        desc.absinfo[0] = InputAbsInfo {
            minimum: -32768,
            maximum: 32767,
            ..Default::default()
        };
        set_bit(&mut desc.absbits, ABS_Z as c_int, ABS_MAX); // Left trigger [0, 255]
        desc.absinfo[ABS_Z] = InputAbsInfo {
            minimum: 0,
            maximum: 255,
            ..Default::default()
        };
        set_bit(&mut desc.absbits, ABS_RZ as c_int, ABS_MAX); // Right trigger [0, 255]
        desc.absinfo[ABS_RZ] = InputAbsInfo {
            minimum: 0,
            maximum: 255,
            ..Default::default()
        };

        let mut pressed = [0u8; udyn_bytes(KEY_MAX)];
        set_bit(&mut pressed, BTN_GAMEPAD as c_int, KEY_MAX);
        set_bit(&mut pressed, (BTN_GAMEPAD + 1) as c_int, KEY_MAX);

        let mut abs = [0i32; ABS_CNT];
        abs[0] = 28000; // tilted right
        abs[ABS_Z] = 200; // held trigger
        abs[ABS_RZ] = 0; // already at rest

        let events = build_neutralizer_events(&desc, &mut pressed, &mut abs, 100, 200);
        // Expect: 2 key releases + 2 abs resets (ABS_X -> 0, ABS_Z -> 0) + 1 SYN_REPORT
        assert_eq!(events.len(), 5);
        assert_eq!(events[0].ev_type, EV_KEY as u16);
        assert_eq!(events[0].code, BTN_GAMEPAD as u16);
        assert_eq!(events[0].value, 0);
        assert_eq!(events[1].ev_type, EV_KEY as u16);
        assert_eq!(events[1].code, (BTN_GAMEPAD + 1) as u16);
        assert_eq!(events[1].value, 0);
        assert_eq!(events[2].ev_type, EV_ABS as u16);
        assert_eq!(events[2].code, 0);
        assert_eq!(events[2].value, 0);
        assert_eq!(events[3].ev_type, EV_ABS as u16);
        assert_eq!(events[3].code, ABS_Z as u16);
        assert_eq!(events[3].value, 0);
        assert_eq!(events[4].ev_type, EV_SYN as u16);
        assert_eq!(events[4].code, SYN_REPORT);

        // Calling again when already neutral produces zero events.
        let second = build_neutralizer_events(&desc, &mut pressed, &mut abs, 101, 0);
        assert!(second.is_empty());
    }

    #[test]
    fn test_run_loop_accepts_and_reaps_clients_without_panic() {
        use std::os::unix::net::UnixStream;

        let tmp = std::env::temp_dir().join(format!("tw_bridge_loop_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        let mut pipe_fds = [-1 as c_int; 2];
        assert_eq!(unsafe { pipe2(pipe_fds.as_mut_ptr(), O_NONBLOCK | O_CLOEXEC) }, 0);
        let cfg = BridgeConfig::new(tmp.clone(), PathBuf::from("/dev/input/nonexistent"), None);
        let mut state = BridgeState::new(cfg, pipe_fds[0]);
        let lfd = bind_unix_listener(&state.sock_path).expect("bind listener");
        state.listen_fd = lfd;
        let sock_path = state.sock_path.clone();

        let worker = thread::spawn(move || {
            state.run_loop();
        });

        // Connect first client while clients list is empty (regression for pollfds OOB).
        let c1 = UnixStream::connect(&sock_path).expect("connect c1");
        let c2 = UnixStream::connect(&sock_path).expect("connect c2");
        thread::sleep(Duration::from_millis(50));
        drop(c1);
        thread::sleep(Duration::from_millis(50));
        let c3 = UnixStream::connect(&sock_path).expect("connect c3");
        thread::sleep(Duration::from_millis(50));
        drop(c2);
        drop(c3);

        // Signal stop and verify worker thread joins cleanly with zero panics.
        let byte: u8 = 1;
        unsafe {
            let _ = write(pipe_fds[1], (&byte as *const u8) as *const c_void, 1);
            close(pipe_fds[1]);
        }
        worker.join().expect("bridge worker panicked!");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn test_monitor_mute_neutralizes_sandbox_and_suppresses_trailing_release() {
        use std::io::Read;
        use std::os::unix::net::UnixStream;

        let tmp = std::env::temp_dir().join(format!("tw_bridge_mute_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        let mut stop_pipe = [-1 as c_int; 2];
        assert_eq!(unsafe { pipe2(stop_pipe.as_mut_ptr(), O_NONBLOCK | O_CLOEXEC) }, 0);
        let mut phys_pipe = [-1 as c_int; 2];
        assert_eq!(unsafe { pipe2(phys_pipe.as_mut_ptr(), O_NONBLOCK | O_CLOEXEC) }, 0);

        let cfg = BridgeConfig::new(tmp.clone(), PathBuf::from("/dev/input/nonexistent"), None);
        let mut state = BridgeState::new(cfg, stop_pipe[0]);
        state.desc = Some(UdynDesc::new_default());
        state.phys_fd = phys_pipe[0];
        let lfd = bind_unix_listener(&state.sock_path).expect("bind listener");
        state.listen_fd = lfd;
        let sock_path = state.sock_path.clone();
        let mute_path = state.mute_path.clone();

        let worker = thread::spawn(move || {
            state.run_loop();
        });

        let mut sandbox = UnixStream::connect(&sock_path).expect("connect sandbox");
        let mut monitor = UnixStream::connect(&sock_path).expect("connect monitor");
        sandbox.set_read_timeout(Some(Duration::from_millis(400))).unwrap();
        monitor.set_read_timeout(Some(Duration::from_millis(400))).unwrap();

        // Register monitor client via TWCTL.
        monitor
            .write_all(&[b'T', b'W', b'C', b'T', b'L', TWCTL_CMD_REGISTER_MONITOR, 0, 0])
            .unwrap();
        thread::sleep(Duration::from_millis(40));

        let send_phys = |ev_type: u16, code: u16, value: i32| {
            let events = [
                NativeInputEvent { sec: 1, usec: 0, ev_type, code, value },
                NativeInputEvent { sec: 1, usec: 1, ev_type: EV_SYN as u16, code: SYN_REPORT, value: 0 },
            ];
            let bytes = unsafe {
                std::slice::from_raw_parts(
                    events.as_ptr() as *const u8,
                    events.len() * size_of::<NativeInputEvent>(),
                )
            };
            unsafe {
                let _ = write(phys_pipe[1], bytes.as_ptr() as *const c_void, bytes.len());
            }
        };

        let read_events = |stream: &mut UnixStream, count: usize| -> Vec<NativeInputEvent> {
            let mut raw = vec![0u8; count * size_of::<NativeInputEvent>()];
            stream.read_exact(&mut raw).expect("read_exact events");
            let mut out = Vec::with_capacity(count);
            for chunk in raw.chunks_exact(size_of::<NativeInputEvent>()) {
                let ev = unsafe { ptr::read_unaligned(chunk.as_ptr() as *const NativeInputEvent) };
                out.push(ev);
            }
            out
        };

        // 1. Hold BTN_MODE (316) before muting -> both sandbox and monitor receive it.
        send_phys(EV_KEY as u16, 316, 1);
        let sb_ev = read_events(&mut sandbox, 2);
        let mon_ev = read_events(&mut monitor, 2);
        assert_eq!(sb_ev[0].code, 316);
        assert_eq!(sb_ev[0].value, 1);
        assert_eq!(mon_ev[0].code, 316);
        assert_eq!(mon_ev[0].value, 1);
        assert!(!mute_path.exists());

        // 2. Monitor enables sandbox mute -> sandbox gets neutralizer releasing BTN_MODE,
        //    and tw_input.mute flag file is created.
        monitor
            .write_all(&[b'T', b'W', b'C', b'T', b'L', TWCTL_CMD_SET_SANDBOX_MUTE, 1, 0])
            .unwrap();
        let sb_neutral = read_events(&mut sandbox, 2);
        assert_eq!(sb_neutral[0].ev_type, EV_KEY as u16);
        assert_eq!(sb_neutral[0].code, 316);
        assert_eq!(sb_neutral[0].value, 0);
        assert_eq!(sb_neutral[1].ev_type, EV_SYN as u16);
        assert!(mute_path.exists());

        // 3. While muted, release BTN_MODE and press BTN_EAST (305 / Cancel):
        //    only monitor receives them; sandbox receives nothing.
        send_phys(EV_KEY as u16, 316, 0);
        send_phys(EV_KEY as u16, 305, 1);
        let mon_while_muted = read_events(&mut monitor, 4);
        assert_eq!(mon_while_muted[0].code, 316);
        assert_eq!(mon_while_muted[0].value, 0);
        assert_eq!(mon_while_muted[2].code, 305);
        assert_eq!(mon_while_muted[2].value, 1);

        sandbox.set_read_timeout(Some(Duration::from_millis(80))).unwrap();
        let mut probe = [0u8; 24];
        assert!(sandbox.read(&mut probe).is_err());

        // 4. Unmute while BTN_EAST is still held, then release BTN_EAST:
        //    the trailing release is swallowed for sandbox, tw_input.mute clears,
        //    and the next fresh BTN_SOUTH (304) press reaches sandbox cleanly.
        monitor
            .write_all(&[b'T', b'W', b'C', b'T', b'L', TWCTL_CMD_SET_SANDBOX_MUTE, 0, 0])
            .unwrap();
        thread::sleep(Duration::from_millis(40));
        send_phys(EV_KEY as u16, 305, 0); // trailing release -> suppressed
        send_phys(EV_KEY as u16, 304, 1); // fresh press -> forwarded

        sandbox.set_read_timeout(Some(Duration::from_millis(400))).unwrap();
        let sb_after = read_events(&mut sandbox, 2);
        assert_eq!(sb_after[0].code, 304);
        assert_eq!(sb_after[0].value, 1);
        assert!(!mute_path.exists());

        // 5. Re-mute and drop monitor abruptly -> sandbox auto-unmutes and mute file clears.
        monitor
            .write_all(&[b'T', b'W', b'C', b'T', b'L', TWCTL_CMD_SET_SANDBOX_MUTE, 1, 0])
            .unwrap();
        // Neutralizer for held BTN_SOUTH (304)
        let _ = read_events(&mut sandbox, 2);
        assert!(mute_path.exists());
        drop(monitor);
        thread::sleep(Duration::from_millis(60));
        send_phys(EV_KEY as u16, 304, 0); // trailing release clears suppressed_keys
        thread::sleep(Duration::from_millis(40));
        assert!(!mute_path.exists());

        let byte: u8 = 1;
        unsafe {
            let _ = write(stop_pipe[1], (&byte as *const u8) as *const c_void, 1);
            close(stop_pipe[1]);
            close(phys_pipe[1]);
        }
        worker.join().expect("bridge worker panicked");
        let _ = fs::remove_dir_all(&tmp);
    }
}
