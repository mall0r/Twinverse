#!/usr/bin/env python3
"""Módulo de teste mínimo para a aplicação Twinverse."""

import os
import sys

import gi
from gi.repository import Adw, Gtk

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class MinimalTestApp(Adw.Application):
    """Aplicação de teste mínima para a Twinverse."""

    def __init__(self):
        """Inicializa a aplicação de teste mínima."""
        super().__init__(application_id="io.github.mall0r.Twinverse.MinimalTest")
        self.connect("activate", self.on_activate)
        print("MinimalTestApp initialized")

    def on_activate(self, app):
        """Ativa a janela principal da aplicação."""
        print("MinimalTestApp activated!")
        window = Gtk.Window(application=app)
        window.set_title("Minimal Test App")
        window.set_default_size(400, 300)
        window.present()
        print("Minimal window presented")


def run_minimal_test():
    """Executa o teste mínimo da aplicação Twinverse."""
    print("Setting up minimal test...")
    os.environ["GSK_RENDERER"] = "gl"

    # Set the dark theme
    style_manager = Adw.StyleManager.get_default()
    style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    app = MinimalTestApp()
    print("About to run minimal test app...")
    result = app.run(sys.argv)
    print(f"Minimal test app finished with result: {result}")


if __name__ == "__main__":
    run_minimal_test()
