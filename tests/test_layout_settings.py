"""Testes para a funcionalidade de limites de instâncias na página de configurações de layout."""

from unittest.mock import MagicMock, patch

import pytest

from src.gui.pages.layout_settings_page import LayoutSettingsPage


def make_page(num_monitors):
    """Cria uma página sem GTK, com um adjustment falso e o número de monitores dado."""
    with patch.object(LayoutSettingsPage, "__init__", lambda x: None):
        page = LayoutSettingsPage()

    page._num_monitors = num_monitors
    page.num_players_row = MagicMock()

    adjustment = MagicMock()
    adjustment.get_value.return_value = 1
    adjustment.get_upper.return_value = 8
    page.num_players_row.get_adjustment.return_value = adjustment

    return page, adjustment


@pytest.mark.parametrize("num_monitors", [1, 2, 3, 10])
def test_fullscreen_is_not_limited_by_monitors(num_monitors):
    """Modo fullscreen sempre libera as 8 instâncias, mesmo sem monitores suficientes."""
    page, adjustment = make_page(num_monitors)

    page._update_num_players_limits(is_splitscreen=False)

    adjustment.set_upper.assert_called_once_with(8)


@pytest.mark.parametrize(
    "num_monitors, expected",
    [
        (1, 4),
        (2, 8),
        (3, 8),
        (10, 8),
    ],
)
def test_splitscreen_limit_follows_monitors(num_monitors, expected):
    """Modo splitscreen continua limitado a 4 instâncias por monitor."""
    page, adjustment = make_page(num_monitors)

    page._update_num_players_limits(is_splitscreen=True)

    adjustment.set_upper.assert_called_once_with(expected)
