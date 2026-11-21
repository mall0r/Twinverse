//! Exercise the bundled GTK's GResource icon lookup and actual recoloring.
//! Compile/run in the AppImage builder, not against the workstation's GTK.

use std::ffi::{c_char, c_int, c_uint, c_void, CStr, CString};
use std::ptr;

const GTK_TEXT_DIR_LTR: c_int = 1;

const ICONS: &[&str] = &[
    "sun-outline-symbolic",
    "moon-outline-symbolic",
    "fullscreen-square-symbolic",
    "horizontal-square-symbolic",
    "vertical-square-symbolic",
    "four-square-symbolic",
    "horizontal-three-square-symbolic",
    "vertical-three-square-symbolic",
    "gamepad-symbolic",
    "mouse-wireless-symbolic",
    "panel-left-symbolic",
    "panel-right-symbolic",
    "twinverse-add-symbolic",
    "twinverse-audio-symbolic",
    "twinverse-close-symbolic",
    "twinverse-gamepad-symbolic",
    "twinverse-menu-symbolic",
    "twinverse-refresh-symbolic",
    "twinverse-play-symbolic",
    "twinverse-stop-symbolic",
    "twinverse-check-symbolic",
    "twinverse-download-symbolic",
    "twinverse-dot-symbolic",
    "twinverse-display-symbolic",
    "twinverse-network-symbolic",
    "twinverse-terminal-symbolic",
    "twinverse-trash-symbolic",
    "twinverse-folder-symbolic",
    "twinverse-folder-open-symbolic",
    "twinverse-window-symbolic",
    "twinverse-info-symbolic",
    "twinverse-error-symbolic",
];

#[repr(C)]
struct GError {
    domain: u32,
    code: c_int,
    message: *const c_char,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct GdkRGBA {
    red: f32,
    green: f32,
    blue: f32,
    alpha: f32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct GraphenePoint {
    x: f32,
    y: f32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct GrapheneSize {
    width: f32,
    height: f32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct GrapheneRect {
    origin: GraphenePoint,
    size: GrapheneSize,
}

enum GResource {}
enum GFile {}
enum GtkIconTheme {}
enum GtkIconPaintable {}
enum GtkSnapshot {}
enum GskRenderer {}
enum GskRenderNode {}
enum GdkTexture {}

extern "C" {
    fn g_error_free(error: *mut GError);
    fn g_free(mem: *mut c_void);
    fn g_object_unref(object: *mut c_void);

    fn g_resource_load(filename: *const c_char, error: *mut *mut GError) -> *mut GResource;
    fn g_resources_register(resource: *mut GResource);
    fn g_resources_unregister(resource: *mut GResource);
    fn g_resource_unref(resource: *mut GResource);
    fn g_file_get_uri(file: *mut GFile) -> *mut c_char;

    fn gtk_init();
    fn gtk_icon_theme_new() -> *mut GtkIconTheme;
    fn gtk_icon_theme_set_search_path(theme: *mut GtkIconTheme, path: *const *const c_char);
    fn gtk_icon_theme_set_theme_name(theme: *mut GtkIconTheme, theme_name: *const c_char);
    fn gtk_icon_theme_add_resource_path(theme: *mut GtkIconTheme, path: *const c_char);
    fn gtk_icon_theme_has_icon(theme: *mut GtkIconTheme, icon_name: *const c_char) -> c_int;
    fn gtk_icon_theme_lookup_icon(
        theme: *mut GtkIconTheme,
        icon_name: *const c_char,
        fallbacks: *const *const c_char,
        size: c_int,
        scale: c_int,
        direction: c_int,
        flags: c_uint,
    ) -> *mut GtkIconPaintable;
    fn gtk_icon_paintable_get_file(icon: *mut GtkIconPaintable) -> *mut GFile;
    fn gtk_icon_paintable_is_symbolic(icon: *mut GtkIconPaintable) -> c_int;

    fn gtk_snapshot_new() -> *mut GtkSnapshot;
    fn gtk_snapshot_free_to_node(snapshot: *mut GtkSnapshot) -> *mut GskRenderNode;
    fn gtk_symbolic_paintable_snapshot_symbolic(
        paintable: *mut GtkIconPaintable,
        snapshot: *mut GtkSnapshot,
        width: f64,
        height: f64,
        colors: *const GdkRGBA,
        n_colors: usize,
    );

    fn gsk_cairo_renderer_new() -> *mut GskRenderer;
    fn gsk_renderer_realize(
        renderer: *mut GskRenderer,
        surface: *mut c_void,
        error: *mut *mut GError,
    ) -> c_int;
    fn gsk_renderer_unrealize(renderer: *mut GskRenderer);
    fn gsk_renderer_render_texture(
        renderer: *mut GskRenderer,
        root: *mut GskRenderNode,
        viewport: *const GrapheneRect,
    ) -> *mut GdkTexture;
    fn gsk_render_node_unref(node: *mut GskRenderNode);

    fn gdk_texture_get_width(texture: *mut GdkTexture) -> c_int;
    fn gdk_texture_get_height(texture: *mut GdkTexture) -> c_int;
    fn gdk_texture_download(texture: *mut GdkTexture, data: *mut u8, stride: usize);
}

unsafe fn assert_no_error(error: *mut GError, context: &str) {
    if !error.is_null() {
        let msg = if (*error).message.is_null() {
            "<null>".to_string()
        } else {
            CStr::from_ptr((*error).message)
                .to_string_lossy()
                .into_owned()
        };
        let code = (*error).code;
        g_error_free(error);
        panic!("{context} failed (code {code}): {msg}");
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(args.len(), 2, "usage: check-appearance <path-to-gresource>");
    let resource_path = CString::new(args[1].as_str()).expect("valid gresource path");
    let hicolor = CString::new("hicolor").unwrap();
    let icons_resource_path = CString::new("/io/github/mall0r/Twinverse/icons").unwrap();
    let empty_path: [*const c_char; 1] = [ptr::null()];

    unsafe {
        gtk_init();

        let mut error: *mut GError = ptr::null_mut();
        let resource = g_resource_load(resource_path.as_ptr(), &mut error);
        assert_no_error(error, "g_resource_load");
        assert!(!resource.is_null(), "g_resource_load returned null");
        g_resources_register(resource);

        // Do not let a matching host icon hide a broken application resource.
        let theme = gtk_icon_theme_new();
        gtk_icon_theme_set_search_path(theme, empty_path.as_ptr());
        gtk_icon_theme_set_theme_name(theme, hicolor.as_ptr());
        gtk_icon_theme_add_resource_path(theme, icons_resource_path.as_ptr());

        let renderer = gsk_cairo_renderer_new();
        let realized = gsk_renderer_realize(renderer, ptr::null_mut(), &mut error);
        assert_no_error(error, "gsk_renderer_realize");
        assert_ne!(realized, 0, "gsk_renderer_realize returned false");

        for &name in ICONS {
            let icon_c = CString::new(name).unwrap();
            assert_ne!(
                gtk_icon_theme_has_icon(theme, icon_c.as_ptr()),
                0,
                "icon theme missing '{name}'"
            );

            let icon = gtk_icon_theme_lookup_icon(
                theme,
                icon_c.as_ptr(),
                ptr::null(),
                16,
                1,
                GTK_TEXT_DIR_LTR,
                0,
            );
            assert!(!icon.is_null(), "lookup failed for '{name}'");

            let file = gtk_icon_paintable_get_file(icon);
            assert!(!file.is_null(), "icon '{name}' has no backing file");
            let uri_ptr = g_file_get_uri(file);
            assert!(
                !uri_ptr.is_null(),
                "g_file_get_uri returned null for '{name}'"
            );
            let uri = CStr::from_ptr(uri_ptr).to_string_lossy().into_owned();
            g_free(uri_ptr as *mut c_void);
            g_object_unref(file as *mut c_void);

            assert!(
                uri.starts_with("resource:///io/github/mall0r/Twinverse/icons/"),
                "unexpected icon URI for '{name}': {uri}"
            );
            assert_ne!(
                gtk_icon_paintable_is_symbolic(icon),
                0,
                "icon '{name}' is not symbolic"
            );

            // Reuse the paintable across both foreground colors, as on a theme
            // toggle. A plain white SVG or a stale texture must fail this test.
            for light in 0..2 {
                let c = light as f32;
                let color = GdkRGBA {
                    red: c,
                    green: c,
                    blue: c,
                    alpha: 1.0,
                };
                let colors = [color; 4];
                let snapshot = gtk_snapshot_new();
                gtk_symbolic_paintable_snapshot_symbolic(
                    icon,
                    snapshot,
                    16.0,
                    16.0,
                    colors.as_ptr(),
                    colors.len(),
                );
                let node = gtk_snapshot_free_to_node(snapshot);
                assert!(!node.is_null(), "snapshot node is null for '{name}'");

                let viewport = GrapheneRect {
                    origin: GraphenePoint { x: 0.0, y: 0.0 },
                    size: GrapheneSize {
                        width: 16.0,
                        height: 16.0,
                    },
                };
                let texture = gsk_renderer_render_texture(renderer, node, &viewport);
                assert!(!texture.is_null(), "rendered texture is null for '{name}'");
                assert_eq!(gdk_texture_get_width(texture), 16);
                assert_eq!(gdk_texture_get_height(texture), 16);

                let mut pixels = [0u8; 16 * 16 * 4];
                gdk_texture_download(texture, pixels.as_mut_ptr(), 16 * 4);

                let mut visible = 0usize;
                for px in pixels.chunks_exact(4) {
                    // Download uses premultiplied BGRA on this x86_64 package.
                    let alpha = px[3] as i32;
                    if alpha == 0 {
                        continue;
                    }
                    visible += 1;
                    let expected = light * alpha;
                    for &channel in &px[..3] {
                        assert!(
                            (channel as i32 - expected).abs() <= 1,
                            "icon '{name}' channel {} != expected {expected} (light={light}, alpha={alpha})",
                            channel
                        );
                    }
                }
                assert!(visible > 0, "icon '{name}' rendered 0 visible pixels");

                g_object_unref(texture as *mut c_void);
                gsk_render_node_unref(node);
            }

            g_object_unref(icon as *mut c_void);
            println!("Recolored {name} in light and dark foregrounds");
        }

        gsk_renderer_unrealize(renderer);
        g_object_unref(renderer as *mut c_void);
        g_object_unref(theme as *mut c_void);
        g_resources_unregister(resource);
        g_resource_unref(resource);
    }
}
