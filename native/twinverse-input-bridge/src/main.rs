//! Twinverse physical controller hotplug bridge and instance supervisor.
//!
//! Usage:
//!   twinverse-input-bridge --socket-dir <dir> --device-id <path> \
//!       [--resolved-event <path>] [--no-grab] -- <command> [args...]
//!
//! Runs on the host alongside (and in the same process group as) a sandboxed
//! Twinverse instance. Bridges the assigned physical evdev controller into
//! `<socket_dir>/tw_event3000.sock` + `tw_event3000.desc` (holding an exclusive
//! `EVIOCGRAB` so host applications such as Host Steam ignore it while the
//! session runs) and maintains `<socket_dir>/tw_hidraw.allow` across
//! unplug/reconnect cycles, then waits for `<command>` and exits with its exact
//! status code.

mod bridge;
mod evdev;
mod ffi;

use std::env;
use std::ffi::{c_char, c_int, CString, OsString};
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::process::ExitCode;
use std::ptr;
use std::sync::atomic::{AtomicI32, Ordering};

use crate::bridge::{BridgeConfig, PreparedBridge};
use crate::ffi::{
    _exit, execvp, fork, kill, last_errno, signal, waitpid, EINTR, SIGHUP, SIGINT, SIGPIPE,
    SIGTERM, SIG_IGN,
};

const SIG_DFL: usize = 0;

static CHILD_PID: AtomicI32 = AtomicI32::new(0);
static LAST_SIGNAL: AtomicI32 = AtomicI32::new(0);

extern "C" fn forward_signal_handler(sig: c_int) {
    LAST_SIGNAL.store(sig, Ordering::Relaxed);
    let pid = CHILD_PID.load(Ordering::Acquire);
    if pid > 0 {
        unsafe {
            let _ = kill(pid, sig);
        }
    }
}

struct CliArgs {
    socket_dir: PathBuf,
    device_id: PathBuf,
    resolved_event: Option<PathBuf>,
    grab_exclusive: bool,
    command: Vec<OsString>,
}

fn parse_args<I>(mut iter: I) -> Result<CliArgs, String>
where
    I: Iterator<Item = OsString>,
{
    let mut socket_dir: Option<PathBuf> = None;
    let mut device_id: Option<PathBuf> = None;
    let mut resolved_event: Option<PathBuf> = None;
    let mut grab_exclusive =
        !std::env::var_os("TWINVERSE_BRIDGE_NO_GRAB").is_some_and(|v| !v.is_empty() && v != "0");
    let mut command: Vec<OsString> = Vec::new();

    while let Some(arg) = iter.next() {
        if arg == "--" {
            command.extend(iter);
            break;
        } else if arg == "--socket-dir" {
            let val = iter
                .next()
                .ok_or_else(|| "--socket-dir requires a value".to_string())?;
            socket_dir = Some(PathBuf::from(val));
        } else if arg == "--device-id" {
            let val = iter
                .next()
                .ok_or_else(|| "--device-id requires a value".to_string())?;
            device_id = Some(PathBuf::from(val));
        } else if arg == "--resolved-event" {
            let val = iter
                .next()
                .ok_or_else(|| "--resolved-event requires a value".to_string())?;
            if !val.is_empty() {
                resolved_event = Some(PathBuf::from(val));
            }
        } else if arg == "--no-grab" {
            grab_exclusive = false;
        } else {
            return Err(format!("unknown argument: {}", arg.to_string_lossy()));
        }
    }

    let socket_dir = socket_dir.ok_or_else(|| "--socket-dir is required".to_string())?;
    let device_id = device_id.ok_or_else(|| "--device-id is required".to_string())?;
    if command.is_empty() {
        return Err("missing child command after '--'".to_string());
    }

    Ok(CliArgs {
        socket_dir,
        device_id,
        resolved_event,
        grab_exclusive,
        command,
    })
}

fn spawn_child_posix(command: &[OsString]) -> Result<c_int, String> {
    let mut c_args: Vec<CString> = Vec::with_capacity(command.len());
    for arg in command {
        let cs = CString::new(arg.as_bytes())
            .map_err(|_| "child command argument contains NUL byte".to_string())?;
        c_args.push(cs);
    }
    let mut argv: Vec<*const c_char> = c_args.iter().map(|s| s.as_ptr()).collect();
    argv.push(ptr::null());

    // Process is still single-threaded here, so `fork()` + `execvp()` is
    // strictly async-signal-safe and avoids GLIBC 2.39 `pidfd_spawnp` deps.
    let pid = unsafe { fork() };
    if pid < 0 {
        return Err(format!("fork failed (errno={})", last_errno()));
    }
    if pid == 0 {
        unsafe {
            let _ = signal(SIGPIPE, SIG_DFL);
            let _ = signal(SIGTERM, SIG_DFL);
            let _ = signal(SIGINT, SIG_DFL);
            let _ = signal(SIGHUP, SIG_DFL);
            execvp(argv[0], argv.as_ptr());
            _exit(127);
        }
    }
    Ok(pid)
}

fn wait_for_child(pid: c_int) -> ExitCode {
    let mut status: c_int = 0;
    loop {
        let rc = unsafe { waitpid(pid, &mut status, 0) };
        if rc < 0 {
            if last_errno() == EINTR {
                continue;
            }
            return ExitCode::from(1);
        }
        break;
    }

    // Standard POSIX wait status decoding (Linux):
    // WIFEXITED:   (status & 0x7f) == 0        -> WEXITSTATUS: (status >> 8) & 0xff
    // WIFSIGNALED: ((status & 0x7f) + 1) >> 1 > 0 -> WTERMSIG: status & 0x7f
    let sig = status & 0x7f;
    if sig == 0 {
        ExitCode::from(((status >> 8) & 0xff) as u8)
    } else {
        ExitCode::from(((128 + sig) & 0xff) as u8)
    }
}

fn main() -> ExitCode {
    unsafe {
        let _ = signal(SIGPIPE, SIG_IGN);
        let handler = forward_signal_handler as *const () as usize;
        let _ = signal(SIGTERM, handler);
        let _ = signal(SIGINT, handler);
        let _ = signal(SIGHUP, handler);
    }

    let args = match parse_args(env::args_os().skip(1)) {
        Ok(a) => a,
        Err(msg) => {
            eprintln!("[twinverse-input-bridge] {msg}");
            return ExitCode::from(2);
        }
    };

    let mut cfg = BridgeConfig::new(args.socket_dir, args.device_id, args.resolved_event);
    cfg.grab_exclusive = args.grab_exclusive;
    let prepared = match PreparedBridge::prepare(cfg) {
        Ok(p) => p,
        Err(err) => {
            eprintln!("[twinverse-input-bridge] failed to prepare bridge: {err}");
            return ExitCode::from(1);
        }
    };

    let pid = match spawn_child_posix(&args.command) {
        Ok(p) => p,
        Err(err) => {
            eprintln!("[twinverse-input-bridge] {err}");
            drop(prepared);
            return ExitCode::from(127);
        }
    };

    CHILD_PID.store(pid, Ordering::Release);
    let early_sig = LAST_SIGNAL.load(Ordering::Relaxed);
    if early_sig != 0 {
        unsafe {
            let _ = kill(pid, early_sig);
        }
    }

    let bridge = match prepared.spawn_thread() {
        Ok(h) => h,
        Err(err) => {
            eprintln!("[twinverse-input-bridge] failed to start bridge thread: {err}");
            let code = wait_for_child(pid);
            CHILD_PID.store(0, Ordering::Release);
            return code;
        }
    };

    let code = wait_for_child(pid);
    CHILD_PID.store(0, Ordering::Release);
    bridge.stop_and_join();
    code
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_args_valid_and_errors() {
        let args = parse_args(
            [
                "--socket-dir",
                "/tmp/sock",
                "--device-id",
                "/dev/input/by-id/usb-pad",
                "--resolved-event",
                "/dev/input/event23",
                "--",
                "bwrap",
                "--ro-bind",
                "/",
                "/",
            ]
            .into_iter()
            .map(OsString::from),
        )
        .unwrap();

        assert_eq!(args.socket_dir, PathBuf::from("/tmp/sock"));
        assert_eq!(args.device_id, PathBuf::from("/dev/input/by-id/usb-pad"));
        assert_eq!(
            args.resolved_event,
            Some(PathBuf::from("/dev/input/event23"))
        );
        assert!(args.grab_exclusive);
        assert_eq!(args.command.len(), 4);
        assert_eq!(args.command[0], OsString::from("bwrap"));

        let no_grab = parse_args(
            [
                "--socket-dir",
                "/tmp/sock",
                "--device-id",
                "/dev/input/event0",
                "--no-grab",
                "--",
                "true",
            ]
            .into_iter()
            .map(OsString::from),
        )
        .unwrap();
        assert!(!no_grab.grab_exclusive);

        // Missing child command -> error
        assert!(parse_args(
            [
                "--socket-dir",
                "/tmp/sock",
                "--device-id",
                "/dev/input/event0"
            ]
            .into_iter()
            .map(OsString::from)
        )
        .is_err());
    }
}
