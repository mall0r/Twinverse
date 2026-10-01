"""Check that both launch paths really remove inherited inline HUD settings."""

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.core import Utils
from src.models import Profile
from src.services.cmd_builder import CommandBuilder
from src.services.instance import InstanceService


class OverlayLaunchEnvironmentTests(unittest.TestCase):
    """Verify overlay environment handling across launch paths and sandboxes."""

    def test_launch_paths_unset_inline_config(self):
        """Check native and Flatpak launches remove inherited inline settings."""
        service = InstanceService.__new__(InstanceService)
        service.logger = Mock()
        process = Mock(pid=123)
        process.poll.return_value = None
        process.stdout.readline.return_value = b"123\n"
        # Exercise quoting for non-default data paths in the Flatpak host shell.
        with TemporaryDirectory(prefix="twinverse espaço ' $ ") as directory:
            builder = CommandBuilder(
                Mock(), Profile(use_gamescope=True, use_steamdeck_tag=True), {}, Mock(), 0, Path(directory), None
            )
            env = builder.prepare_overlay_environment()
            with patch.dict(os.environ, {"MANGOHUD_CONFIG": "read_cfg"}), patch("time.sleep"):
                with patch("subprocess.Popen", return_value=process) as spawn:
                    service._launch_natively(0, ["true"], env)
                native_env = spawn.call_args.kwargs["env"]
                self.assertNotIn("MANGOHUD_CONFIG", native_env)
                self.assertEqual(native_env["MANGOHUD_CONFIGFILE"], env["MANGOHUD_CONFIGFILE"])

                # Run the generated host shell with its actual unset/export
                # statements, using env as the child instead of starting Steam.
                with patch.object(Utils, "flatpak_spawn_host", return_value=process) as spawn:
                    service._launch_in_flatpak(0, ["env"], env)
                output = subprocess.check_output(spawn.call_args.args[0], text=True)
                lines = output.splitlines()
                self.assertFalse(any(line.startswith("MANGOHUD_CONFIG=") for line in lines))
                self.assertIn(f"MANGOHUD_CONFIGFILE={env['MANGOHUD_CONFIGFILE']}", lines)

    def test_config_mapping_for_native_flatpak_and_custom_data_paths(self):
        """Check config sharing and instance isolation across data locations."""
        with TemporaryDirectory() as directory:
            host_home = Path(directory) / "home with spaces"
            data_paths = [
                host_home / ".local/share/twinverse",
                host_home / ".var/app/io.github.mall0r.Twinverse/data/twinverse",
                Path(directory) / "custom data outside home/twinverse",
            ]
            with patch.object(Path, "home", return_value=host_home):
                for data_path in data_paths:
                    with self.subTest(data_path=data_path):
                        configs = []
                        for i in range(2):
                            home = data_path / f"home_{i + 1}"
                            builder = CommandBuilder(
                                Mock(),
                                Profile(use_gamescope=True, use_steamdeck_tag=True),
                                {},
                                Mock(),
                                i,
                                home,
                                None,
                            )
                            env = builder.prepare_overlay_environment()
                            command = builder._build_bwrap_command(i)
                            index = command.index("MANGOHUD_CONFIGFILE")
                            sandbox_config = Path(command[index + 1])
                            host_config = home / sandbox_config.relative_to(host_home)
                            self.assertEqual(str(host_config), env["MANGOHUD_CONFIGFILE"])
                            configs.append(host_config)
                        configs[0].write_text("preset=1\n")
                        self.assertEqual(configs[1].read_text(), "no_display\n")

    def test_sandbox_unsets_profile_inline_config(self):
        """Ensure sandbox cleanup overrides inline settings from the profile."""
        with TemporaryDirectory() as directory:
            builder = CommandBuilder(
                Mock(), Profile(use_gamescope=True, use_steamdeck_tag=True), {}, Mock(), 0, Path(directory), None
            )
            with patch.object(Profile, "get_env_for_instance", return_value={"MANGOHUD_CONFIG": "full"}):
                command = builder._build_bwrap_command(0)
            unset = command.index("--unsetenv")
            self.assertEqual(command[unset + 1], "MANGOHUD_CONFIG")
            self.assertLess(command.index("full"), unset)


if __name__ == "__main__":
    unittest.main()
