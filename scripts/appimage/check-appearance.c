/* Exercise the bundled GTK's unthemed GResource lookup and actual recoloring.
 * Compile/run in the AppImage builder, not against the workstation's GTK. */
#include <gtk/gtk.h>

int
main (int argc, char **argv)
{
  GError *error = NULL;
  GResource *resource;
  GtkIconTheme *theme;
  GskRenderer *renderer;
  const char *empty_path[] = { NULL };
  const char *icons[] = {
    "sun-outline-symbolic", "moon-outline-symbolic", "fullscreen-square-symbolic",
    "horizontal-square-symbolic", "vertical-square-symbolic", "four-square-symbolic",
    "horizontal-three-square-symbolic", "vertical-three-square-symbolic",
    "gamepad-symbolic", "mouse-wireless-symbolic"
  };

  g_assert_cmpint (argc, ==, 2);
  gtk_init ();
  resource = g_resource_load (argv[1], &error);
  g_assert_no_error (error);
  g_resources_register (resource);
  /* Do not let a matching host icon hide a broken application resource. */
  theme = gtk_icon_theme_new ();
  gtk_icon_theme_set_search_path (theme, empty_path);
  gtk_icon_theme_set_theme_name (theme, "hicolor");
  gtk_icon_theme_add_resource_path (theme, "/io/github/mall0r/Twinverse/icons");
  renderer = gsk_cairo_renderer_new ();
  gsk_renderer_realize (renderer, NULL, &error);
  g_assert_no_error (error);

  for (guint i = 0; i < G_N_ELEMENTS (icons); i++)
    {
      GtkIconPaintable *icon;
      GFile *file;
      char *uri;

      g_assert_true (gtk_icon_theme_has_icon (theme, icons[i]));
      icon = gtk_icon_theme_lookup_icon (theme, icons[i], NULL, 16, 1, GTK_TEXT_DIR_LTR, 0);
      file = gtk_icon_paintable_get_file (icon);
      uri = g_file_get_uri (file);
      g_assert_true (g_str_has_prefix (uri, "resource:///io/github/mall0r/Twinverse/icons/"));
      g_assert_true (gtk_icon_paintable_is_symbolic (icon));
      g_free (uri);

      /* Reuse the paintable across both foreground colors, as on a theme
       * toggle. A plain white SVG or a stale texture must fail this test. */
      for (int light = 0; light < 2; light++)
        {
          GdkRGBA color = { light, light, light, 1 };
          GdkRGBA colors[] = { color, color, color, color };
          GtkSnapshot *snapshot = gtk_snapshot_new ();
          GskRenderNode *node;
          GdkTexture *texture;
          graphene_rect_t viewport = GRAPHENE_RECT_INIT (0, 0, 16, 16);
          guchar pixels[16 * 16 * 4];
          int visible = 0;

          gtk_symbolic_paintable_snapshot_symbolic (GTK_SYMBOLIC_PAINTABLE (icon),
                                                    snapshot, 16, 16, colors, 4);
          node = gtk_snapshot_free_to_node (snapshot);
          g_assert_nonnull (node);
          texture = gsk_renderer_render_texture (renderer, node, &viewport);
          g_assert_cmpint (gdk_texture_get_width (texture), ==, 16);
          g_assert_cmpint (gdk_texture_get_height (texture), ==, 16);
          gdk_texture_download (texture, pixels, 16 * 4);
          for (guint p = 0; p < sizeof pixels; p += 4)
            {
              /* Download uses premultiplied BGRA on this x86_64 package. */
              int alpha = pixels[p + 3];
              if (alpha == 0)
                continue;
              visible++;
              for (int channel = 0; channel < 3; channel++)
                g_assert_cmpint (ABS ((int) pixels[p + channel] - light * alpha), <=, 1);
            }
          g_assert_cmpint (visible, >, 0);
          g_object_unref (texture);
          gsk_render_node_unref (node);
        }
      g_object_unref (icon);
      g_print ("Recolored %s in light and dark foregrounds\n", icons[i]);
    }

  gsk_renderer_unrealize (renderer);
  g_object_unref (renderer);
  g_object_unref (theme);
  g_resources_unregister (resource);
  g_resource_unref (resource);
  return 0;
}
