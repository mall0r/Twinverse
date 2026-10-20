"""Verification of Steam installations."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SteamVerifier:
    """Confirms an instance home actually holds a usable Steam client."""

    def verify(self, instance_path: Path) -> bool:
        """Verify if Steam is properly installed at the given instance path."""
        steam_path = instance_path / ".local/share/Steam/steamclient64.dll"
        logger.info("Verifying Steam installation at %s", steam_path)
        is_verified = steam_path.exists()
        logger.info("Verification result for %s: %s", instance_path, "passed" if is_verified else "failed")
        return is_verified
