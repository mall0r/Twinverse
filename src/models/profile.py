"""Data models for the profiles that define how a set of Steam instances is launched."""

import json
import logging
import os
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from pydantic.functional_validators import field_validator, model_validator

from src.core import Config, Utils
from src.core.config import ensure_private_dir
from src.core.i18n import (
    LANGUAGE_AUTO,
    TRANSLATIONS,
    LanguagePreference,
    normalize_language_preference,
    t,
)
from src.core.layout import LayoutCalculator
from src.core.tiling import TEMPLATES

logger = logging.getLogger(__name__)

DEFAULT_PLAYER_NAME = "Player"
_DEFAULT_PLAYER_NAMES = frozenset({DEFAULT_PLAYER_NAME, *(cat["player.default_name"] for cat in TRANSLATIONS.values())})


class PlayerInstanceConfig(BaseModel):
    """Defines the specific configuration for a single player's game instance."""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, alias="NAME")
    physical_device_id: Optional[str] = Field(default=None, alias="PHYSICAL_DEVICE_ID")
    grab_input_devices: bool = Field(default=False, alias="GRAB_INPUT_DEVICES")
    audio_device_id: Optional[str] = Field(default=None, alias="AUDIO_DEVICE_ID")
    env: Optional[Dict[str, str]] = Field(default=None, alias="ENV")
    guest_ip: Optional[str] = Field(default=None, alias="GUEST_IP")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Trim custom player names and omit empty or default values."""
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned or cleaned in _DEFAULT_PLAYER_NAMES:
            return None
        return cleaned

    @property
    def display_name(self) -> str:
        """Return the player's configured name or the localized default label."""
        return self.name or t("player.default_name")


class SplitscreenConfig(BaseModel):
    """Configuration for splitscreen mode."""

    model_config = ConfigDict(populate_by_name=True)
    orientation: str = Field(default="vertical", alias="ORIENTATION")

    @field_validator("orientation")
    def validate_orientation(cls, v):
        """Validate that orientation is either horizontal or vertical."""
        if v not in ["horizontal", "vertical"]:
            raise ValueError("Orientation must be 'horizontal' or 'vertical'.")
        return v


class MonitorLayoutConfig(BaseModel):
    """Saved template and optional instance reservations for one connector."""

    template: Literal["fullscreen", "columns", "rows", "main-left", "main-top", "grid"] = "fullscreen"
    players: list[StrictInt | None] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_players(self):
        """Reject excess slots and duplicate or negative player IDs."""
        assigned = [player for player in self.players if player is not None]
        if len(self.players) > TEMPLATES[self.template].capacity:
            raise ValueError("Players exceed the template capacity.")
        if any(player < 0 for player in assigned) or len(assigned) != len(set(assigned)):
            raise ValueError("Players must contain unique, non-negative instance IDs.")
        return self


class Profile(BaseModel):
    """A profile for launching a set of Steam instances with a specific configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    num_players: int = Field(default=2, alias="NUM_PLAYERS")
    # Explicit zero-based instance IDs present in the party roster. None falls
    # back to range(num_players) for backward compatibility with older profiles.
    party_players: Optional[List[StrictInt]] = Field(default=None, alias="PARTY_PLAYERS")
    instance_width: Optional[int] = Field(default=1920, alias="INSTANCE_WIDTH")
    instance_height: Optional[int] = Field(default=1080, alias="INSTANCE_HEIGHT")
    mode: Optional[str] = Field(default="splitscreen", alias="MODE")
    enable_kwin_script: bool = Field(default=True, alias="ENABLE_KWIN_SCRIPT")
    splitscreen: Optional[SplitscreenConfig] = Field(default_factory=SplitscreenConfig, alias="SPLITSCREEN")
    env: Optional[Dict[str, str]] = Field(default=None, alias="ENV")
    player_configs: List[PlayerInstanceConfig] = Field(
        default_factory=lambda: [PlayerInstanceConfig(), PlayerInstanceConfig()],
        alias="PLAYERS",
    )
    selected_players: List[int] = Field(default_factory=list, alias="selected_players")
    # None preserves the automatic layout of existing profiles. A list is the
    # custom instance order, independent of selection and launch timing.
    layout_order: Optional[List[StrictInt]] = Field(default=None, alias="LAYOUT_ORDER")
    monitor_layouts: dict[str, MonitorLayoutConfig] = Field(default_factory=dict, alias="MONITOR_LAYOUTS")
    use_steamdeck_tag: bool = Field(default=True, alias="USE_STEAMDECK_TAG")
    use_gamescope: bool = Field(default=True, alias="USE_GAMESCOPE")
    enable_gamescope_wsi: bool = Field(default=Utils.is_wayland(), alias="ENABLE_GAMESCOPE_WSI")
    isolate_network: bool = Field(default=True, alias="ISOLATE_NETWORK")
    language: LanguagePreference = Field(default=LANGUAGE_AUTO, alias="LANGUAGE")

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, value):
        """Normalize saved language preferences with safe fallback to auto."""
        return normalize_language_preference(value)

    @field_validator("party_players")
    def validate_party_players(cls, value):
        """Reject empty, duplicate or negative instance IDs in a saved party."""
        if value is not None and (not value or any(index < 0 for index in value) or len(value) != len(set(value))):
            raise ValueError("Party players must contain unique, non-negative instance indices.")
        return value

    @field_validator("layout_order")
    def validate_layout_order(cls, value):
        """Reject duplicate or negative instance IDs in a saved custom layout."""
        if value is not None and (any(index < 0 for index in value) or len(value) != len(set(value))):
            raise ValueError("Layout order must contain unique, non-negative instance indices.")
        return value

    @classmethod
    def load(cls) -> "Profile":
        """Load the profile from the default JSON file."""
        profile_path = Config.get_profile_path()
        if not profile_path.exists():
            default_profile = cls()
            default_profile.save()
            return default_profile

        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Could not read the profile at %s: %s", profile_path, e)
            raise ValueError(f"Error reading profile file {profile_path}: {e}") from e

        try:
            profile = cls(**data)
        except ValidationError as e:
            logger.error(
                "Profile data validation failed for %s (%s error(s))",
                profile_path,
                len(e.errors()),
            )
            raise ValueError(f"Profile data validation failed: {e}") from e
        return profile

    def save(self):
        """Save the profile atomically with private permissions."""
        profile_path = Config.get_profile_path()
        ensure_private_dir(profile_path.parent)
        data_to_save = self.model_dump(by_alias=True, exclude_none=True)
        json_data = json.dumps(data_to_save, indent=4) + "\n"
        temporary = profile_path.with_name(f".{profile_path.name}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json_data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, profile_path)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @property
    def is_splitscreen_mode(self) -> bool:
        """Check if the profile is configured for splitscreen mode."""
        return self.mode == "splitscreen"

    def party_indices(self) -> List[int]:
        """Return the zero-based instance IDs currently present in the party."""
        if self.party_players is not None:
            return list(self.party_players)
        return list(range(max(0, self.num_players)))

    def launch_indices(self) -> List[int]:
        """
        Return the indices of the instances that take part in a launch.

        Launch timing stays in instance-number order. Display placement is
        independent and is returned by layout_indices().
        """
        party = self.party_indices()
        if self.selected_players:
            party_set = set(party)
            return sorted({index for index in self.selected_players if index in party_set})
        return sorted(party)

    def effective_num_players(self) -> int:
        """Return how many instances take part in a launch."""
        return len(self.launch_indices())

    def layout_indices(self) -> List[int]:
        """Return selected instances in display-slot order, without changing launch order."""
        return LayoutCalculator.order_instances(self.launch_indices(), self.layout_order)

    def get_player_name(self, instance_idx: int) -> str:
        """Return the display name for a given zero-based instance index."""
        if 0 <= instance_idx < len(self.player_configs):
            return self.player_configs[instance_idx].display_name
        return t("player.default_name")

    def get_env_for_instance(self, instance_idx: int) -> Dict[str, str]:
        """Return the merged environment variables for a given instance index (0-based).

        Per-player ENV overrides values from the global ENV.
        """
        base_env: Dict[str, str] = dict(self.env or {})
        if 0 <= instance_idx < len(self.player_configs):
            player_env = self.player_configs[instance_idx].env or {}
            player_env = {str(k): str(v) for k, v in player_env.items()}
            base_env.update(player_env)
        base_env = {str(k): str(v) for k, v in base_env.items()}
        return base_env
