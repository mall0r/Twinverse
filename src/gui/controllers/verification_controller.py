"""Steam instance verification."""

import logging
from collections.abc import Iterable
from typing import Callable, Optional

from src.core import Config
from src.services import SteamVerifier

logger = logging.getLogger(__name__)


class VerificationController:
    """Caches verification results so the UI can query them cheaply."""

    def __init__(self, steam_verifier: SteamVerifier):
        """Initialize the verification controller."""
        self._steam_verifier = steam_verifier
        self._verification_statuses: dict[int, bool] = {}

    def verify_instance(self, instance_num: int) -> bool:
        """
        Verify a specific instance and cache the result.

        Args:
            instance_num: Zero-based instance index.

        Returns:
            True if verified, False otherwise.
        """
        instance_path = Config.get_steam_home_path(instance_num)
        is_verified = self._steam_verifier.verify(instance_path)
        self._verification_statuses[instance_num] = is_verified
        logger.info("Instance %s verification: %s", instance_num + 1, is_verified)
        return is_verified

    def verify_instances(
        self,
        instance_nums: Iterable[int],
        on_each_complete: Optional[Callable[[int, bool], None]] = None,
    ):
        """Verify an explicit sequence of zero-based instance IDs."""
        for instance_num in instance_nums:
            is_verified = self.verify_instance(instance_num)
            if on_each_complete:
                on_each_complete(instance_num, is_verified)

    def verify_all_instances(
        self,
        num_instances: int,
        on_each_complete: Optional[Callable[[int, bool], None]] = None,
    ):
        """
        Verify all instances.

        Args:
            num_instances: How many instances to verify, from index 0.
            on_each_complete: Called with (instance_num, is_verified) as each
                verification finishes.
        """
        self.verify_instances(range(num_instances), on_each_complete=on_each_complete)

    def get_verification_status(self, instance_num: int) -> bool:
        """
        Get cached verification status, False when never verified.

        Args:
            instance_num: Zero-based instance index.

        Returns:
            True if verified, False otherwise.
        """
        return self._verification_statuses.get(instance_num, False)

    def get_all_statuses(self) -> dict[int, bool]:
        """Get all verification statuses."""
        return self._verification_statuses.copy()

    def clear_cache(self):
        """Clear the verification cache."""
        self._verification_statuses.clear()
