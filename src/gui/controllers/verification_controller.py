"""Steam instance verification."""

from typing import Callable, Optional

from src.core import Config, Logger
from src.services import SteamVerifier


class VerificationController:
    """Caches verification results so the UI can query them cheaply."""

    def __init__(self, steam_verifier: SteamVerifier, logger: Logger):
        """Initialize the verification controller."""
        self._steam_verifier = steam_verifier
        self._logger = logger
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
            num_instances: How many instances to verify, from index 0.
            on_each_complete: Called with (instance_num, is_verified) as each
                verification finishes.
        """
        for i in range(num_instances):
            is_verified = self.verify_instance(i)
            if on_each_complete:
                on_each_complete(i, is_verified)

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
