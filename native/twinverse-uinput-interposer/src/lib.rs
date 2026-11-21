//! Twinverse userspace `/dev/uinput` interposer (`libtwinverse_uinput.so`).
//!
//! Preloaded inside Twinverse's sandboxed Steam instances so that Steam Input
//! can create virtual controllers without writing to the host kernel's
//! `/dev/uinput`, preventing controller leaks across splitscreen instances.

mod ffi;
mod fs_hooks;
mod inotify;
mod uinput;

pub use fs_hooks::*;

unsafe extern "C" fn init_interposer() {
    ffi::init_logging();
    uinput::init_mutex();
    inotify::init_mutex();
    fs_hooks::init_dir_mutex();
    ffi::preload_real_symbols();
    ffi::debug_log_bytes(b"[twinverse_uinput] initialized\n");
}

#[used]
#[link_section = ".init_array"]
static INIT_ARRAY: unsafe extern "C" fn() = init_interposer;
