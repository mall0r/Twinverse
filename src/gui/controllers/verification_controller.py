"""
Verification controller module.

This module manages Steam instance verification.
"""

from typing import Callable, Optional

from src.core import Config, Logger
from src.services import SteamVerifier


class VerificationController:
    """Manages Steam instance verification."""

    def __init__(self, steam_verifier: SteamVerifier, logger: Logger):
        """Initialize the verification controller."""
        self._steam_verifier = steam_verifier
        self._logger = logger
        self._verification_statuses: dict[int, bool] = {}

    def verify_instance(self, instance_num: int) -> bool:
        """
        Verify a specific instance.

        Args:
            instance_num: The instance number to verify

        Returns:
            True if verified, False otherwise
        """
        instance_path = Config.get_steam_home_path(instance_num)
        is_verified = self._steam_verifier.verify(instance_path)
        self._verification_statuses[instance_num] = is_verified
        self._logger.info(f"Instance {instance_num} verification: {is_verified}")
        return is_verified

    def verify_all_instances(
        self,
        num_instances: int,
        on_each_complete: Optional[Callable[[int, bool], None]] = None,
    ):
        """
        Verify all instances.

        Args:
            num_instances: Number of instances to verify
            on_each_complete: Callback for each instance (called with instance_num, is_verified)
        """
        for i in range(num_instances):
            is_verified = self.verify_instance(i)
            if on_each_complete:
                on_each_complete(i, is_verified)

    def get_verification_status(self, instance_num: int) -> bool:
        """
        Get cached verification status.

        Args:
            instance_num: The instance number

        Returns:
            True if verified, False otherwise
        """
        return self._verification_statuses.get(instance_num, False)

    def get_all_statuses(self) -> dict[int, bool]:
        """Get all verification statuses."""
        return self._verification_statuses.copy()

    def clear_cache(self):
        """Clear the verification cache."""
        self._verification_statuses.clear()
