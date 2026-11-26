"""Unit and GTK integration tests for English / Brazilian Portuguese (PT-BR) i18n."""

# flake8: noqa: E402

import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import gi
import pytest

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from src.core.config import Config
from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError
from src.core.i18n import (
    LANGUAGE_AUTO,
    LANGUAGE_EN,
    LANGUAGE_PT_BR,
    TRANSLATIONS,
    detect_system_language,
    get_language,
    get_language_preference,
    ngettext,
    normalize_language_preference,
    resolve_language,
    set_language,
    subscribe,
    t,
    translate_template_title,
    unsubscribe,
)
from src.gui.dialogs import ConfirmationDialog, ErrorDialog, TextInputDialog
from src.gui.notifications import BUSY, ERROR, INFO
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.gui.presenters.main_presenter import MainPresenter
from src.gui.utils.error_handler import ErrorHandler
from src.gui.widgets.player_row import (
    INSTANCE_RUNNING,
    INSTANCE_STARTING,
    INSTANCE_STOPPING,
)
from src.gui.widgets.toast import ToastOverlay
from src.gui.windows.main_window import MainWindow
from src.gui.windows.preferences_window import PreferencesWindow
from src.models.profile import PlayerInstanceConfig, Profile

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text))


@pytest.fixture
def gtk_display():
    """Initialize GTK/Adwaita when a display is available, otherwise skip."""
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required")
    Adw.init()


def test_translation_catalog_parity_and_placeholders():
    """Every catalog key and format placeholder must match between EN and PT-BR."""
    en_keys = set(TRANSLATIONS[LANGUAGE_EN].keys())
    pt_keys = set(TRANSLATIONS[LANGUAGE_PT_BR].keys())
    assert en_keys == pt_keys

    for key in sorted(en_keys):
        en_text = TRANSLATIONS[LANGUAGE_EN][key]
        pt_text = TRANSLATIONS[LANGUAGE_PT_BR][key]
        assert en_text, f"Empty EN translation for {key}"
        assert pt_text, f"Empty PT-BR translation for {key}"
        assert _placeholders(en_text) == _placeholders(pt_text), f"Placeholder mismatch for {key}"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"LC_ALL": "pt_BR.UTF-8"}, LANGUAGE_PT_BR),
        ({"LC_MESSAGES": "pt_PT.UTF-8"}, LANGUAGE_PT_BR),
        ({"LANG": "pt-BR"}, LANGUAGE_PT_BR),
        ({"LANGUAGE": "pt_BR:en_US"}, LANGUAGE_PT_BR),
        ({"LC_ALL": "en_US.UTF-8", "LANG": "pt_BR.UTF-8"}, LANGUAGE_EN),
        ({"LC_ALL": "C", "LANG": "pt_BR.UTF-8"}, LANGUAGE_PT_BR),
        ({"LC_ALL": "fr_FR.UTF-8"}, LANGUAGE_EN),
    ],
)
def test_detect_system_language_from_environment(monkeypatch, env, expected):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)

    assert detect_system_language() == expected
    assert resolve_language(LANGUAGE_AUTO) == expected


def test_normalize_and_set_language_notifications():
    assert normalize_language_preference("pt-br") == LANGUAGE_PT_BR
    assert normalize_language_preference("pt_BR.UTF-8") == LANGUAGE_PT_BR
    assert normalize_language_preference("en_US") == LANGUAGE_EN
    assert normalize_language_preference("auto") == LANGUAGE_AUTO
    assert normalize_language_preference("unknown") == LANGUAGE_AUTO
    assert normalize_language_preference(None) == LANGUAGE_AUTO

    events: list[str] = []

    def listener(lang: str) -> None:
        events.append(lang)

    subscribe(listener)
    try:
        set_language(LANGUAGE_PT_BR)
        assert get_language() == LANGUAGE_PT_BR
        assert get_language_preference() == LANGUAGE_PT_BR
        assert events == [LANGUAGE_PT_BR]

        # Re-setting the same preference does not emit a redundant notification.
        set_language(LANGUAGE_PT_BR)
        assert events == [LANGUAGE_PT_BR]

        set_language(LANGUAGE_EN)
        assert get_language() == LANGUAGE_EN
        assert events == [LANGUAGE_PT_BR, LANGUAGE_EN]
    finally:
        unsubscribe(listener)


def test_t_ngettext_and_template_titles():
    set_language(LANGUAGE_PT_BR)
    assert t("session.launch_button") == "Iniciar Sessão"
    assert ngettext("stage.display_one", "stage.display_many", 1) == "1 monitor"
    assert ngettext("stage.display_one", "stage.display_many", 2) == "2 monitores"
    assert translate_template_title("main-left", "Main left") == "Principal à esquerda"
    assert translate_template_title("unknown-id", "Fallback") == "Fallback"
    assert t("missing.key.fallback") == "missing.key.fallback"


def test_profile_language_persistence_and_default_player_names():
    profile = Profile()
    assert profile.language == LANGUAGE_AUTO
    assert profile.get_player_name(0) == "Player"

    set_language(LANGUAGE_PT_BR)
    assert profile.get_player_name(0) == "Jogador"

    # Default localized names ("Player" and "Jogador") normalize to None so
    # switching languages never freezes the default label into profile.json.
    assert PlayerInstanceConfig(NAME="Player").name is None
    assert PlayerInstanceConfig(NAME="Jogador").name is None
    assert PlayerInstanceConfig(NAME="Alice").name == "Alice"

    profile.language = LANGUAGE_PT_BR
    profile.save()

    raw = json.loads(Config.get_profile_path().read_text(encoding="utf-8"))
    assert raw["LANGUAGE"] == "pt_BR"

    loaded = Profile.load()
    assert loaded.language == LANGUAGE_PT_BR


def test_error_handler_localizes_in_pt_br():
    set_language(LANGUAGE_PT_BR)
    assert "Dependência ausente" in ErrorHandler.format_error(DependencyError("gamescope"))
    assert "Erro de dispositivo virtual" in ErrorHandler.format_error(VirtualDeviceError("uinput"))
    assert "Erro do Twinverse" in ErrorHandler.format_error(TwinverseError("boom"))
    not_found = FileNotFoundError(2, "No such file", "bwrap")
    assert "Comando obrigatório 'bwrap' não encontrado" in ErrorHandler.format_error(not_found)


def test_dialogs_localize_in_pt_br(gtk_display):
    set_language(LANGUAGE_PT_BR)

    confirm = ConfirmationDialog(None, "Título", "Mensagem")
    assert confirm.get_response_label("ok") == "OK"
    assert confirm.get_response_label("cancel") == "Cancelar"

    err = ErrorDialog(None, t("common.error"), "Falha")
    assert err.get_title() == "Erro"
    assert err.get_response_label("ok") == "OK"

    text_dialog = TextInputDialog(None, "Entrada", "Digite:")
    assert text_dialog.get_response_label("cancel") == "Cancelar"


def test_toast_overlay_live_retranslation(gtk_display):
    toast = ToastOverlay()
    toast.show_toast("Working...", level=BUSY, timeout=0)
    assert toast._title.get_text() == "WORKING"

    set_language(LANGUAGE_PT_BR)
    assert toast._title.get_text() == "EM ANDAMENTO"
    assert toast._dismiss_button.get_tooltip_text() == "Dispensar"

    toast.show_toast("Aviso", level=INFO, timeout=0)
    assert toast._title.get_text() == "AVISO"
    toast.show_toast("Falha", level=ERROR, timeout=0)
    assert toast._title.get_text() == "ERRO"


def test_player_row_and_layout_page_live_language_switch(gtk_display):
    devices = {
        "joystick": [{"id": "pad-0", "name": "DualSense"}],
        "audio": [{"id": "sink-0", "name": "HDMI"}],
        "displays": [{"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080}],
    }
    profile = Profile(
        MODE="splitscreen",
        SPLITSCREEN={"ORIENTATION": "vertical"},
        PLAYERS=[PlayerInstanceConfig(NAME=None, PHYSICAL_DEVICE_ID="pad-0", AUDIO_DEVICE_ID="sink-0", ENV={"A": "1"})],
        PARTY_PLAYERS=[0, 1],
    )
    page = LayoutSettingsPage()
    page.load_data(profile, devices, {0: True, 1: False})

    row0 = page.get_player_row(0)
    row1 = page.get_player_row(1)
    assert row0.get_player_name() == "Player"
    assert row0.get_status_text() == "Ready"
    assert row1.get_status_text() == "Not installed"

    # Switch live to Brazilian Portuguese
    set_language(LANGUAGE_PT_BR)

    assert page._roster_heading_label.get_label() == "Seu grupo"
    assert page._add_player_content.get_label() == "Adicionar Jogador"
    assert page._stage_eyebrow_label.get_label() == "LAYOUT DA SESSÃO"
    assert page._inspector_eyebrow_label.get_label() == "CONFIGURAÇÃO DO JOGADOR"
    assert page.display_summary.get_label() == "1 monitor"
    assert row0.get_player_name() == "Jogador"
    assert row0._grab_heading_label.get_text() == "Capturar mouse"
    assert row0.get_status_text() == "Pronto"
    assert row0.launch_button.get_label() == "Iniciar Jogador"
    assert row1.get_status_text() == "Não instalado"
    assert row1.launch_button.get_label() == "Instalar Steam"

    # Verify ready check icon is still shown in LayoutPreview for PT-BR "Pronto"
    slot0 = page.layout_preview._slots[0]
    assert "slot-status-ready" in slot0.status_icon.get_css_classes()
    assert slot0.name.get_label() == "Jogador"

    # Verify dropdown selections and canonical data export remain intact in PT-BR
    assert row0.joystick_row.get_selected() == 1
    assert row0.audio_row.get_selected() == 1
    assert row0.joystick_row.get_model().get_string(0) == "Nenhum"
    assert row0.audio_row.get_model().get_string(0) == "Padrão"
    assert row0._env_rows[0].key_label.get_label() == "_Chave"
    assert row0._env_rows[0].value_label.get_label() == "_Valor"

    data = page.get_data()
    assert data["mode"] == "splitscreen"
    assert data["orientation"] == "vertical"
    assert data["player_configs"][0].name is None

    # Runtime states in PT-BR
    row0.set_instance_state(INSTANCE_STARTING)
    assert row0.get_status_text() == "Iniciando Steam…"
    assert row0.launch_button.get_label() == "Cancelar Inicialização"
    row0.set_update_progress("Downloading", 42)
    assert row0.get_status_text() == "Atualizando Steam · 42%"
    row0.clear_update_progress()
    row0.set_instance_state(INSTANCE_RUNNING)
    assert row0.get_status_text() == "Em execução"
    assert row0.launch_button.get_label() == "Parar Jogador"
    row0.set_instance_state(INSTANCE_STOPPING)
    assert row0.get_status_text() == "Parando…"


def test_main_window_and_preferences_language_switching(gtk_display):
    app = Adw.Application(application_id="io.github.mall0r.Twinverse.test.i18n")
    profile = Profile()
    recorded: list[tuple[str, object]] = []

    def on_pref_changed(key, value):
        recorded.append((key, value))
        if hasattr(profile, key):
            setattr(profile, key, value)
        if key == "language":
            set_language(str(value))

    presenter = SimpleNamespace(
        on_settings_changed=lambda: None,
        on_verification_completed=lambda: None,
        on_instance_launch_requested=lambda _n: None,
        on_devices_refresh_requested=lambda: None,
        on_launch_clicked=lambda: None,
        on_about_clicked=lambda: None,
        on_preferences_clicked=lambda: None,
        on_close_requested=lambda: None,
    )

    win = MainWindow(app, presenter)
    prefs = PreferencesWindow(win, profile, on_pref_changed)

    assert win.launch_label.get_label() == "Launch Session"
    assert prefs.get_title() == "Preferences"

    # Switch to PT-BR via Preferences dropdown (index 2 -> pt_BR)
    prefs.language_row.set_selected(2)
    assert profile.language == LANGUAGE_PT_BR
    assert get_language() == LANGUAGE_PT_BR
    assert prefs.get_title() == "Preferências"
    assert prefs._engine_heading_label.get_label() == "Motor de execução"
    assert prefs._gamescope_title_label.get_label() == "Usar Gamescope"
    assert prefs._reset_button.get_label() == "Redefinir Tudo"
    assert win.launch_label.get_label() == "Iniciar Sessão"

    # Switch back to English via Preferences dropdown
    prefs.language_row.set_selected(1)
    assert profile.language == LANGUAGE_EN
    assert get_language() == LANGUAGE_EN
    assert prefs.get_title() == "Preferences"
    assert prefs.language_row.get_selected() == 1
    assert win.launch_label.get_label() == "Launch Session"


def test_main_presenter_applies_saved_profile_language_on_startup(gtk_display):
    profile = Profile(LANGUAGE=LANGUAGE_PT_BR)
    profile.save()

    app = Adw.Application(application_id="io.github.mall0r.Twinverse.test.presenter.i18n")
    with (
        patch("src.gui.presenters.main_presenter.DeviceManager") as mock_dm,
        patch("src.gui.presenters.main_presenter.SteamVerifier") as mock_sv,
        patch("src.gui.presenters.main_presenter.InstanceService") as mock_is,
        patch("src.gui.presenters.main_presenter.KdeManager"),
    ):
        mock_dm.return_value.get_all_devices.return_value = {"joystick": [], "audio": [], "displays": []}
        mock_sv.return_value.is_steam_healthy.return_value = True
        mock_is.return_value.recovered_instances = []
        mock_is.return_value.processes = {}

        presenter = MainPresenter(app)
        assert get_language() == LANGUAGE_PT_BR
        assert presenter.window.launch_label.get_label() == "Iniciar Sessão"
        assert presenter.window.session_title.get_label() == "Pronto para jogar"

        presenter._on_preference_changed("language", LANGUAGE_EN)
        assert get_language() == LANGUAGE_EN
        assert presenter.window.launch_label.get_label() == "Launch Session"
        assert Profile.load().language == LANGUAGE_EN
