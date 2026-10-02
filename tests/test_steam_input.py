"""Check that Steam Input is turned off once per instance and never touched again."""

import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.models import Profile
from src.services.instance import InstanceService
from src.services.steam_input import SteamInputDisabler, VdfDocument, VdfFormatError

ACCOUNT = "320393707"
SECOND_ACCOUNT = "1548552487"
APPS_KEY = "apps"
ROOT = "UserLocalConfigStore"
GLOBAL = "CSettingsPanelGameController.TurnOff"
PER_GAME = "UseSteamControllerConfig"


def _manifest(steamapps: Path, appid: str) -> None:
    """Write an app manifest like the ones Steam and Twinverse keep."""
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{appid}.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"' + appid + '"\n\t"name"\t\t"Game"\n}\n'
    )


def _account_config(home: Path, account: str) -> Path:
    """Return the config of an account, writing a fresh one when it is missing."""
    config = home / ".local/share/Steam/userdata" / account / "config/localconfig.vdf"
    if not config.exists():
        config.parent.mkdir(parents=True)
        config.write_text(f'"{ROOT}"\n{{\n\t"RemotePlay"\n\t{{\n\t\t"RemotePlayEnable"\t\t"1"\n\t}}\n}}\n')
    return config


@pytest.fixture
def instance(tmp_path):
    """Build an instance home with a logged-in account and two games."""
    home = tmp_path / "home_1"
    config = home / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    config.parent.mkdir(parents=True)
    config.write_text(
        '"UserLocalConfigStore"\n'
        "{\n"
        f'\t"{GLOBAL}"\t\t"0"\n'
        '\t"RemotePlay"\n'
        "\t{\n"
        '\t\t"RemotePlayEnable"\t\t"1"\n'
        "\t}\n"
        f'\t"{APPS_KEY}"\n'
        "\t{\n"
        '\t\t"582010"\n'
        "\t\t{\n"
        '\t\t\t"DefaultLaunchOption"\n'
        "\t\t\t{\n"
        '\t\t\t\t"1650923e"\t\t"0"\n'
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )
    steamapps = home / ".local/share/Steam/steamapps"
    _manifest(steamapps, "582010")
    _manifest(steamapps, "1245620")
    return home


def _read(path: Path) -> str:
    """Read a Steam config file."""
    return path.read_text(encoding="utf-8")


def test_turns_off_global_and_known_games(instance, tmp_path):
    """Disable the controller toggle and every game of the instance library."""
    disabler = SteamInputDisabler(Mock())
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"

    assert disabler.disable_once(0, instance) is True

    document = VdfDocument(_read(config))
    games = document.child_names((ROOT, APPS_KEY))
    assert set(games) == {"582010", "1245620"}
    for appid in games:
        node = document._find((ROOT, APPS_KEY, appid, PER_GAME))
        assert node is not None and node.value == "0"
    assert document._find((ROOT, GLOBAL)).value == "1"
    # Untouched settings and the original layout survive the edit.
    assert document._find((ROOT, "RemotePlay", "RemotePlayEnable")).value == "1"
    assert document._find((ROOT, APPS_KEY, "582010", "DefaultLaunchOption", "1650923e")).value == "0"
    assert '\t\t\t\t"1650923e"\t\t"0"\n' in _read(config)


def test_marker_records_the_handled_instance(instance):
    """Store the state that stops Twinverse from touching the settings again."""
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, instance) is True

    marker = instance / ".config/twinverse/steam_input_disabled.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["version"] == SteamInputDisabler.MARKER_VERSION
    assert payload["instance"] == 1
    assert payload["accounts"] == [ACCOUNT]
    assert payload["library_apps"] == 2


def test_later_user_choice_is_preserved(instance):
    """Never overwrite a Steam Input setting the user changed after the first run."""
    disabler = SteamInputDisabler(Mock())
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    disabler.disable_once(0, instance)

    text = _read(config).replace(f'"{PER_GAME}"\t\t"0"', f'"{PER_GAME}"\t\t"1"', 1)
    config.write_text(text, encoding="utf-8")
    before = _read(config)

    assert disabler.disable_once(0, instance) is False
    assert _read(config) == before


def test_marker_from_an_older_version_runs_the_change_again(instance):
    """Apply the settings again when the recorded state predates this version."""
    marker = instance / ".config/twinverse/steam_input_disabled.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"version": SteamInputDisabler.MARKER_VERSION - 1, "instance": 1, "accounts": [ACCOUNT]}),
        encoding="utf-8",
    )
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, instance) is True

    document = VdfDocument(_read(config))
    assert document._find((ROOT, APPS_KEY, "1245620", PER_GAME)).value == "0"
    assert json.loads(_read(marker))["version"] == SteamInputDisabler.MARKER_VERSION


def test_a_second_account_is_covered_without_touching_the_first(instance):
    """Configure a newly logged-in account while leaving the handled one alone."""
    disabler = SteamInputDisabler(Mock())
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    assert disabler.disable_once(0, instance) is True

    # The user turns Steam Input back on in the account Twinverse already handled.
    config.write_text(_read(config).replace(f'"{GLOBAL}"\t\t"1"', f'"{GLOBAL}"\t\t"0"', 1), encoding="utf-8")
    second = _account_config(instance, SECOND_ACCOUNT)

    assert disabler.disable_once(0, instance) is True

    assert VdfDocument(_read(config))._find((ROOT, GLOBAL)).value == "0"
    document = VdfDocument(_read(second))
    assert document._find((ROOT, GLOBAL)).value == "1"
    assert document._find((ROOT, APPS_KEY, "582010", PER_GAME)).value == "0"
    marker = json.loads(_read(instance / ".config/twinverse/steam_input_disabled.json"))
    assert marker["accounts"] == sorted([ACCOUNT, SECOND_ACCOUNT])


def test_an_account_removed_from_the_instance_is_dropped_from_the_marker(instance):
    """Forget an account that left the instance, so logging into it again configures it."""
    disabler = SteamInputDisabler(Mock())
    second = _account_config(instance, SECOND_ACCOUNT)
    assert disabler.disable_once(0, instance) is True
    marker = instance / ".config/twinverse/steam_input_disabled.json"
    assert json.loads(_read(marker))["accounts"] == sorted([ACCOUNT, SECOND_ACCOUNT])

    shutil.rmtree(second.parent.parent)

    assert disabler.disable_once(0, instance) is False
    assert json.loads(_read(marker))["accounts"] == [ACCOUNT]

    # Logging into the account again must configure it once more.
    _account_config(instance, SECOND_ACCOUNT)
    assert disabler.disable_once(0, instance) is True
    assert json.loads(_read(marker))["accounts"] == sorted([ACCOUNT, SECOND_ACCOUNT])


def test_waits_for_the_account_to_log_in(tmp_path):
    """Leave a brand-new instance untouched until the account config shows up."""
    home = tmp_path / "home_1"
    steamapps = home / ".local/share/Steam/steamapps"
    steamapps.mkdir(parents=True)
    _manifest(steamapps, "582010")
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, home) is False
    assert not (home / ".config/twinverse").exists()

    config = home / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    config.parent.mkdir(parents=True)
    config.write_text(f'"{ROOT}"\n{{\n\t"RemotePlay"\n\t{{\n\t\t"RemotePlayEnable"\t\t"1"\n\t}}\n}}\n')

    assert disabler.disable_once(0, home) is True
    document = VdfDocument(_read(config))
    assert document._find((ROOT, APPS_KEY, "582010", PER_GAME)).value == "0"
    assert document._find((ROOT, "RemotePlay", "RemotePlayEnable")).value == "1"


def test_ignores_the_pre_login_account(tmp_path):
    """Do not record the instance as handled using Steam's placeholder account."""
    home = tmp_path / "home_1"
    config = home / ".local/share/Steam/userdata/0/config/localconfig.vdf"
    config.parent.mkdir(parents=True)
    config.write_text(f'"{ROOT}"\n{{\n}}\n')
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, home) is False
    assert _read(config) == f'"{ROOT}"\n{{\n}}\n'


def test_unreadable_config_is_retried_on_the_next_launch(instance):
    """Keep the instance pending when the account config cannot be parsed."""
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    config.write_text('"UserLocalConfigStore"\n{\n\t"Broken" "value"\n}\n', encoding="utf-8")
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, instance) is False
    assert not (instance / ".config/twinverse/steam_input_disabled.json").exists()
    assert _read(config) == '"UserLocalConfigStore"\n{\n\t"Broken" "value"\n}\n'

    config.write_text(f'"{ROOT}"\n{{\n\t"RemotePlay"\n\t{{\n\t\t"RemotePlayEnable"\t\t"1"\n\t}}\n}}\n')
    assert disabler.disable_once(0, instance) is True


def test_account_without_known_games_still_gets_the_toggle(instance):
    """Cover games Steam knows about even without a manifest in the instance."""
    config = instance / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    text = _read(config).replace(
        '\t\t"582010"\n\t\t{\n',
        '\t\t"-1563516638"\n\t\t{\n\t\t\t"UseSteamControllerConfig"\t\t"2"\n\t\t}\n\t\t"582010"\n\t\t{\n',
    )
    config.write_text(text, encoding="utf-8")
    disabler = SteamInputDisabler(Mock())

    assert disabler.disable_once(0, instance) is True

    document = VdfDocument(_read(config))
    assert document._find((ROOT, APPS_KEY, "-1563516638", PER_GAME)).value == "0"
    assert document._find((ROOT, APPS_KEY, "1245620", PER_GAME)).value == "0"


def test_instance_launch_applies_the_change_before_steam(monkeypatch, tmp_path):
    """Check the launch preparation disables Steam Input once per Steam launch."""
    order = []
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    service.steam_input = Mock()
    service.steam_input.disable_once.side_effect = lambda *args: order.append("steam-input")
    service.processes = {}
    service.device_manager = Mock()
    service._virtual_joystick_path = None
    home = tmp_path / "home_1"
    monkeypatch.setattr("src.services.instance.Config.get_steam_home_path", lambda i: home)
    service._prepare_home = Mock()
    service._sync_app_manifests = Mock(side_effect=lambda *args: order.append("manifests"))
    service._validate_input_devices = Mock(return_value={})
    service._prepare_environment = Mock(return_value={})
    builder = Mock()
    builder.build_command.return_value = ["steam"]
    builder.prepare_overlay_environment.return_value = {}
    monkeypatch.setattr("src.services.cmd_builder.CommandBuilder", Mock(return_value=builder))

    service._prepare_instance_launch(Profile(), 0)

    # The manifests are refreshed first, so the library the change covers is current.
    assert order == ["manifests", "steam-input"]
    service.steam_input.disable_once.assert_called_once_with(0, home)


def test_terminal_launch_leaves_the_account_config_alone(instance, monkeypatch):
    """Skip the Steam settings when the instance only opens a terminal."""
    home = instance
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    service.steam_input = SteamInputDisabler(Mock())
    service.processes = {}
    service.device_manager = Mock()
    service._virtual_joystick_path = None
    config = home / ".local/share/Steam/userdata" / ACCOUNT / "config/localconfig.vdf"
    before = _read(config)

    service._sync_app_manifests = Mock()
    service._validate_input_devices = Mock(return_value={})
    service._prepare_environment = Mock(return_value={})
    builder = Mock()
    builder.build_command.return_value = ["bash"]
    builder.prepare_overlay_environment.return_value = {}
    monkeypatch.setattr("src.services.cmd_builder.CommandBuilder", Mock(return_value=builder))

    service._prepare_instance_launch(Profile(), 0, application_command=["bash"])

    service._sync_app_manifests.assert_not_called()
    assert _read(config) == before
    assert not (home / ".config/twinverse/steam_input_disabled.json").exists()


class VdfDocumentTests:
    """Check the layout rules of the Valve KeyValues editor."""

    def test_rejects_wrapped_values(self):
        """Refuse a document this editor would rewrite into a different file."""
        with pytest.raises(VdfFormatError):
            VdfDocument('"Root"\n{\n\t"Key"\t\t"first\nsecond"\n}\n')

    def test_rejects_duplicate_keys(self):
        """Refuse a document where a value could be shadowed."""
        with pytest.raises(VdfFormatError):
            VdfDocument('"Root"\n{\n\t"Key"\t\t"1"\n\t"Key"\t\t"2"\n}\n')

    def test_rejects_wrong_indentation(self):
        """Refuse a document whose braces do not line up with their keys."""
        with pytest.raises(VdfFormatError):
            VdfDocument('"Root"\n{\n\t\t"Key"\t\t"1"\n}\n')

    def test_rejects_a_key_where_a_block_is_expected(self):
        """Refuse to replace an existing block with a value."""
        document = VdfDocument('"Root"\n{\n\t"Key"\n\t{\n\t\t"Other"\t\t"1"\n\t}\n}\n')
        with pytest.raises(VdfFormatError):
            document.set_value(("Root", "Key"), "2")
