"""
Steam Input disabler module for the Twinverse application.

Steam stores both the global controller toggle (``CSettingsPanelGameController.TurnOff``)
and the per-game override (``UseSteamControllerConfig``) in the account local config,
which only exists once the instance has logged in. The change is therefore applied on
the first launch that already finds an account, and the marker written afterwards keeps
Twinverse from touching those settings again, so anything the user changes later sticks.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from src.core import Logger
from src.core.exceptions import TwinverseError

# Steam's KeyValues layout, as written by the Linux client: one tab per level, a block
# name on its own line and two tabs between a key and its value.
_SCALAR = re.compile(r'^(\t*)"((?:[^"\\]|\\.)*)"\t\t"((?:[^"\\]|\\.)*)"$')
_HEADER = re.compile(r'^(\t*)"((?:[^"\\]|\\.)*)"$')
_BLOCK_START = re.compile(r"^(\t*)\{$")
_BLOCK_END = re.compile(r"^(\t*)\}$")
_APPID = re.compile(r'"appid"\s*"(-?\d+)"')

ROOT_KEY = "UserLocalConfigStore"
APPS_KEY = "apps"
GLOBAL_TOGGLE_KEY = "CSettingsPanelGameController.TurnOff"
PER_GAME_TOGGLE_KEY = "UseSteamControllerConfig"
GLOBAL_TOGGLE_OFF = "1"
PER_GAME_TOGGLE_OFF = "0"

# The pre-login account, which Steam recreates on every fresh installation.
_PRE_LOGIN_ACCOUNT = "0"


class VdfFormatError(TwinverseError):
    """Raised when a Steam VDF file does not follow the layout this editor understands."""

    pass


class _Node:
    """A key or a block of a VDF document, kept together with its position in the file."""

    __slots__ = ("name", "line", "value", "children", "close_line")

    def __init__(self, name: str, line: int, value: Optional[str] = None):
        self.name = name
        self.line = line
        self.value = value
        self.children: dict[str, "_Node"] = {}
        self.close_line: Optional[int] = None

    @property
    def is_block(self) -> bool:
        """Report whether this node holds other keys instead of a value."""
        return self.close_line is not None


def _parse(lines: list[str]) -> _Node:
    """
    Index a VDF document, rejecting any layout this editor cannot round-trip.

    Steam rewrites the whole file whenever a setting changes, so refusing an
    unexpected file is safer than writing back a partially understood copy.
    """
    root = _Node("", -1)
    stack: list[_Node] = [root]
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        # The document root is a virtual level above the top-level key.
        level = len(stack) - 1
        indent = "\t" * level
        end = _BLOCK_END.match(line)
        if end:
            if level == 0 or end.group(1) != "\t" * (level - 1):
                raise VdfFormatError(f"Unexpected closing brace on line {index + 1}")
            stack.pop().close_line = index
            index += 1
            continue

        scalar = _SCALAR.match(line)
        if scalar and scalar.group(1) == indent:
            _add_child(stack[-1], _Node(scalar.group(2), index, scalar.group(3)), index)
            index += 1
            continue

        header = _HEADER.match(line)
        if header and header.group(1) == indent:
            if index + 1 >= len(lines):
                raise VdfFormatError(f"Missing block start after line {index + 1}")
            start = _BLOCK_START.match(lines[index + 1])
            if not start or start.group(1) != indent:
                raise VdfFormatError(f"Missing block start after line {index + 1}")
            node = _Node(header.group(2), index)
            _add_child(stack[-1], node, index)
            stack.append(node)
            index += 2
            continue

        raise VdfFormatError(f"Unsupported content on line {index + 1}")

    if len(stack) != 1:
        raise VdfFormatError("Unterminated block")
    return root


def _add_child(parent: _Node, node: _Node, index: int) -> None:
    """Attach a node, refusing duplicates that would hide an existing value."""
    if node.name in parent.children:
        raise VdfFormatError(f"Duplicate key '{node.name}' on line {index + 1}")
    parent.children[node.name] = node


class VdfDocument:
    """Editor for the Valve KeyValues files Steam keeps its settings in."""

    def __init__(self, text: str):
        """Index the given document, raising VdfFormatError when it is not editable."""
        self._lines = text.splitlines()
        self._root = _parse(self._lines)
        self._modified = False

    @property
    def modified(self) -> bool:
        """Report whether any change was applied to the document."""
        return self._modified

    def child_names(self, path: tuple[str, ...]) -> list[str]:
        """Return the names of the keys of a block, or an empty list when absent."""
        node = self._find(path)
        if node is None or not node.is_block:
            return []
        return list(node.children)

    def set_value(self, path: tuple[str, ...], value: str) -> None:
        """Force a key to a value, creating the blocks leading to it when missing."""
        node = self._find(path)
        if node is not None:
            if node.is_block:
                raise VdfFormatError(f"'{self._label(path)}' is a block, not a value")
            if node.value != value:
                self._lines[node.line] = self._scalar_line(len(path) - 1, path[-1], value)
                self._modified = True
            return

        # Create what is missing under the deepest block that already exists.
        depth = len(path) - 1
        parent = None
        while depth > 0:
            parent = self._find(path[:depth])
            if parent is not None:
                break
            depth -= 1
        if parent is None or parent.close_line is None:
            raise VdfFormatError(f"Cannot create '{self._label(path)}' without a parent block")

        missing = path[depth:-1]
        # Build the missing blocks from the inside out, closing each one it opens.
        additions = [self._scalar_line(depth + len(missing), path[-1], value)]
        for level, name in reversed(list(enumerate(missing, start=depth))):
            additions = [self._scalar_line(level, name), "\t" * level + "{", *additions, "\t" * level + "}"]
        self._insert(parent.close_line, additions)

    def dumps(self) -> str:
        """Render the document back to Valve's layout."""
        return "\n".join(self._lines) + "\n"

    def save(self, path: Path) -> None:
        """Replace the file atomically, keeping the permissions Steam expects."""
        temporary = path.with_name(f"{path.name}.twinverse")
        try:
            temporary.write_text(self.dumps(), encoding="utf-8")
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise

    def _find(self, path: tuple[str, ...]) -> Optional[_Node]:
        """Return the node of a key path, or None when any step is missing."""
        node = self._root
        for name in path:
            node = node.children.get(name)  # type: ignore[assignment]
            if node is None:
                return None
        return node

    def _insert(self, index: int, lines: list[str]) -> None:
        """Insert lines before an index and reindex the document."""
        self._lines[index:index] = lines
        self._modified = True
        self._root = _parse(self._lines)

    @staticmethod
    def _scalar_line(depth: int, name: str, value: Optional[str] = None) -> str:
        """Render a key line, with the value Valve writes after two tabs."""
        line = "\t" * depth + f'"{name}"'
        return line if value is None else f'{line}\t\t"{value}"'

    @staticmethod
    def _label(path: tuple[str, ...]) -> str:
        """Join a key path for messages."""
        return "/".join(path)


class SteamInputDisabler:
    """Turns Steam Input off in an instance, once, as soon as the account config exists."""

    MARKER_VERSION = 1
    MARKER = Path(".config/twinverse/steam_input_disabled.json")

    def __init__(self, logger: Logger):
        """Initialize the disabler with a logger."""
        self.logger = logger

    def disable_once(self, instance_num: int, home_path: Path) -> bool:
        """
        Disable Steam Input in an instance, on its first launch that has an account.

        Args:
            instance_num: The instance number, used for logging.
            home_path: The isolated Steam home of the instance.

        Returns:
            True when the settings were changed, False when nothing had to be done.
        """
        marker = home_path / self.MARKER
        handled = self._handled_accounts(instance_num, marker)
        accounts = self._account_configs(instance_num, home_path)
        names = [account for account, _ in accounts]

        if handled is not None and set(handled) == set(names):
            self.logger.debug(
                f"Instance {instance_num}: Steam Input was already handled, keeping the current settings."
            )
            return False

        if not accounts:
            self.logger.info(
                f"Instance {instance_num}: no Steam account yet, Steam Input will be disabled on a later launch."
            )
            return False

        appids = self._library_appids(instance_num, home_path)
        # Only the accounts the recorded state does not cover yet are touched, so a
        # setting changed in an already handled account survives a later login.
        pending = [entry for entry in accounts if handled is None or entry[0] not in handled]

        disabled = []
        for account, config_path in pending:
            try:
                if self._disable_in_account(instance_num, account, config_path, appids):
                    self.logger.info(
                        f"Instance {instance_num}: Steam Input disabled for account {account} "
                        f"({len(appids)} games in the library)."
                    )
                disabled.append(account)
            except (OSError, VdfFormatError) as e:
                self.logger.warning(f"Instance {instance_num}: could not disable Steam Input for {account}: {e}")

        if len(disabled) < len(pending):
            self.logger.info(
                f"Instance {instance_num}: Steam Input still pending, it will be retried on the next launch."
            )
            return False

        # The marker ends up listing the accounts present now, so an account removed
        # from the instance and added back later is handled again.
        kept = {account for account in (handled or []) if account in names}
        self._write_marker(instance_num, marker, sorted(kept | set(disabled)), appids)
        return bool(pending)

    def _handled_accounts(self, instance_num: int, marker: Path) -> Optional[list[str]]:
        """
        Return the accounts the marker already covers, or None when it vouches for none.

        None means the marker is missing, unreadable or from an older version, in which
        case every account of the instance has to be covered again.
        """
        if not marker.is_file():
            return None
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if payload["version"] != self.MARKER_VERSION:
                self.logger.info(
                    f"Instance {instance_num}: applying the Steam Input settings again, "
                    f"the recorded state comes from an older version."
                )
                return None
            return sorted(payload["accounts"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.debug(f"Instance {instance_num}: cannot read '{marker}': {e}")
            return None

    def _account_configs(self, instance_num: int, home_path: Path) -> list[tuple[str, Path]]:
        """Return the account configs of the instance, ignoring the pre-login account."""
        userdata = home_path / ".local/share/Steam/userdata"
        try:
            entries = sorted(userdata.iterdir())
        except OSError as e:
            self.logger.debug(f"Instance {instance_num}: cannot read '{userdata}': {e}")
            return []

        accounts = []
        for entry in entries:
            if entry.name == _PRE_LOGIN_ACCOUNT:
                continue
            config = entry / "config/localconfig.vdf"
            try:
                if entry.is_dir() and config.is_file():
                    accounts.append((entry.name, config))
            except OSError as e:
                self.logger.debug(f"Instance {instance_num}: skipping account '{entry.name}': {e}")
        return accounts

    def _library_appids(self, instance_num: int, home_path: Path) -> list[str]:
        """Collect the app IDs of the library Twinverse synchronized into the instance."""
        steamapps = home_path / ".local/share/Steam/steamapps"
        appids = set()
        try:
            manifests = sorted(steamapps.glob("appmanifest_*.acf"))
        except OSError as e:
            self.logger.debug(f"Instance {instance_num}: cannot read '{steamapps}': {e}")
            return []

        for manifest in manifests:
            try:
                content = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self.logger.debug(f"Instance {instance_num}: cannot read manifest '{manifest.name}': {e}")
                continue
            match = _APPID.search(content)
            if match:
                appids.add(match.group(1))
        return sorted(appids, key=int)

    def _disable_in_account(self, instance_num: int, account: str, config_path: Path, appids: list[str]) -> bool:
        """Turn the global toggle and every known game off in one account config."""
        document = VdfDocument(config_path.read_text(encoding="utf-8"))
        # Games Steam already knows about are covered too, even without a manifest.
        known = {appid for appid in document.child_names((ROOT_KEY, APPS_KEY)) if _is_appid(appid)}
        targets = sorted(set(appids) | known, key=int)

        document.set_value((ROOT_KEY, GLOBAL_TOGGLE_KEY), GLOBAL_TOGGLE_OFF)
        for appid in targets:
            document.set_value((ROOT_KEY, APPS_KEY, appid, PER_GAME_TOGGLE_KEY), PER_GAME_TOGGLE_OFF)

        if not document.modified:
            self.logger.debug(f"Instance {instance_num}: account {account} already has Steam Input disabled.")
            return False
        document.save(config_path)
        return True

    def _write_marker(self, instance_num: int, marker: Path, accounts: list[str], appids: list[str]) -> None:
        """Record that the instance was handled, so user changes are never overwritten."""
        payload = {
            "version": self.MARKER_VERSION,
            "instance": instance_num + 1,
            "accounts": accounts,
            "library_apps": len(appids),
            "timestamp": int(time.time()),
        }
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            self.logger.warning(f"Instance {instance_num}: could not record the Steam Input state: {e}")
            self.logger.info("Twinverse will check the settings again on the next launch.")


def _is_appid(name: str) -> bool:
    """Report whether a key of the apps block is an app ID."""
    return bool(re.fullmatch(r"-?\d+", name))
