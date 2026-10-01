"""Install pre-commit with host execution support for Flatpak Git clients."""

import subprocess
import sys
from pathlib import Path


def main():
    """Install the standard hook and add an idempotent Flatpak bridge."""
    subprocess.run([sys.executable, "-m", "pre_commit", "install"], check=True)
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks/pre-commit"],
        check=True,
        capture_output=True,
        text=True,
    )
    hook = Path(result.stdout.strip())
    contents = hook.read_text()
    marker = "# Twinverse: run hooks on the host when Git runs inside Flatpak."
    if marker in contents:
        return

    anchor = 'if [ -x "$INSTALL_PYTHON" ]; then\n'
    if anchor not in contents:
        raise RuntimeError("Unrecognized pre-commit hook format; cannot install Flatpak support.")

    bridge = (
        f"{marker}\n"
        "if [ -f /.flatpak-info ]; then\n"
        '    exec flatpak-spawn --host --directory="$PWD" "$INSTALL_PYTHON" -mpre_commit "${ARGS[@]}"\n'
        "fi\n\n"
    )
    hook.write_text(contents.replace(anchor, bridge + anchor, 1))
    print("Installed Flatpak host support for pre-commit.")


if __name__ == "__main__":
    main()
