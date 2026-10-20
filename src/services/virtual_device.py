"""Creation and management of virtual input devices, particularly virtual joysticks."""

import logging
import time

from evdev import AbsInfo, InputDevice, UInput
from evdev import ecodes as e
from evdev import list_devices

from src.core import VirtualDeviceError

logger = logging.getLogger(__name__)


class VirtualDeviceService:
    """Creates a virtual joystick for instances without a physical one."""

    def __init__(self):
        """Initialize the virtual device service."""
        self._ui = None

    def create_virtual_joystick(self):
        """Create a minimal virtual joystick and find its event node."""
        if self._ui:
            logger.warning("Virtual joystick already exists.")
            return self._ui.devnode

        device_name = "Virtual Joystick by Twinverse"
        try:
            capabilities = {
                e.EV_KEY: [e.BTN_A],
                e.EV_ABS: [
                    (
                        e.ABS_X,
                        AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0),
                    ),
                    (
                        e.ABS_Y,
                        AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0),
                    ),
                ],
            }
            self._ui = UInput(capabilities, name=device_name, vendor=0x1234, product=0x5678)
            logger.info("Virtual device object created; searching for its event node")

            start_time = time.time()
            timeout = 5
            while time.time() - start_time < timeout:
                devices = [InputDevice(path) for path in list_devices()]
                for device in devices:
                    if device.name == device_name:
                        logger.info("Found virtual joystick at %s", device.path)
                        self._ui.devnode = device.path
                        return device.path
                time.sleep(0.1)

            raise VirtualDeviceError("Virtual joystick created but its event node could not be found.")

        except Exception as ex:
            logger.exception("Failed to create virtual joystick")
            if self._ui:
                self._ui.close()
                self._ui = None
            raise VirtualDeviceError(f"Failed to create virtual joystick: {ex}") from ex

    def destroy_virtual_joystick(self):
        """Destroy the virtual joystick if it exists."""
        if self._ui:
            try:
                self._ui.close()
                logger.info("Virtual joystick destroyed")
            except Exception:
                logger.exception("Error destroying virtual joystick")
            finally:
                self._ui = None
