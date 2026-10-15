"""Screen layout calculation for splitscreen modes."""

from typing import List, Tuple, cast


class LayoutCalculator:
    """Coordinate tables and per-instance placement in pixels."""

    @staticmethod
    def get_layout_coordinates(
        num_players: int, orientation: str = "horizontal"
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """
        Get proportional coordinates and dimensions for a player count.

        Args:
            num_players: Number of players (0-4).
            orientation: "horizontal" or "vertical".

        Returns:
            (x_coords, y_coords, widths, heights) as lists of floats on a 0-1
            scale, one entry per player.
        """
        horizontal_layouts = {
            "x": [[], [0], [0, 0], [0, 0, 0.5], [0, 0.5, 0, 0.5]],
            "y": [[], [0], [0, 0.5], [0, 0.5, 0.5], [0, 0, 0.5, 0.5]],
            "width": [[], [1], [1, 1], [1, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]],
            "height": [[], [1], [0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]],
        }

        vertical_layouts = {
            "x": [[], [0], [0, 0.5], [0, 0.5, 0.5], [0, 0.5, 0, 0.5]],
            "y": [[], [0], [0, 0], [0, 0, 0.5], [0, 0, 0.5, 0.5]],
            "width": [[], [1], [0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]],
            "height": [[], [1], [1, 1], [1, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]],
        }

        layout = horizontal_layouts if orientation.lower() == "horizontal" else vertical_layouts

        if num_players < 0 or num_players > 4:
            raise ValueError("Number of players must be between 0 and 4")

        x_coords = cast(List[float], layout["x"][num_players])
        y_coords = cast(List[float], layout["y"][num_players])
        widths = cast(List[float], layout["width"][num_players])
        heights = cast(List[float], layout["height"][num_players])

        return x_coords, y_coords, widths, heights

    @staticmethod
    def calculate_position(
        monitor_width: int,
        monitor_height: int,
        num_players: int,
        instance_in_group: int,
        orientation: str = "horizontal",
    ) -> Tuple[int, int, int, int]:
        """
        Calculate the position and dimensions for a specific instance in a group.

        Args:
            monitor_width: Width of the monitor in pixels.
            monitor_height: Height of the monitor in pixels.
            num_players: Total number of players in the group.
            instance_in_group: Index of the instance in the group (0-3).
            orientation: "horizontal" or "vertical".

        Returns:
            (x, y, width, height) for the instance, in pixels.
        """
        if num_players == 0:
            return 0, 0, monitor_width, monitor_height

        if num_players == 1:
            return 0, 0, monitor_width, monitor_height

        x_coords, y_coords, widths, heights = LayoutCalculator.get_layout_coordinates(num_players, orientation)

        x = int(x_coords[instance_in_group] * monitor_width)
        y = int(y_coords[instance_in_group] * monitor_height)
        width = int(widths[instance_in_group] * monitor_width)
        height = int(heights[instance_in_group] * monitor_height)

        return x, y, width, height
