"""Testes para a funcionalidade de limites de instâncias na página de configurações de layout."""

from unittest.mock import MagicMock, patch

import pytest

from src.gui.pages.layout_settings_page import LayoutSettingsPage


def make_page(num_monitors, party_players=(0, 1)):
    """Cria uma página sem GTK, com o número de monitores e controles falsos."""
    with patch.object(LayoutSettingsPage, "__init__", lambda x: None):
        page = LayoutSettingsPage()

    page._num_monitors = num_monitors
    page._max_players = 8
    page._party_controls_sensitive = True
    page._party_players = list(party_players)
    page.player_rows = []
    page.add_player_button = MagicMock()
    page._roster_remove_buttons = [MagicMock() for _ in party_players]
    return page


@pytest.mark.parametrize("num_monitors", [1, 2, 3, 10])
def test_fullscreen_is_not_limited_by_monitors(num_monitors):
    """Modo fullscreen sempre libera as 8 instâncias, mesmo sem monitores suficientes."""
    page = make_page(num_monitors)

    page._update_num_players_limits(is_splitscreen=False)

    assert page._max_players == 8
    page.add_player_button.set_sensitive.assert_called_once_with(True)


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
    page = make_page(num_monitors)

    page._update_num_players_limits(is_splitscreen=True)

    assert page._max_players == expected


def test_add_button_disables_when_splitscreen_limit_is_reached():
    """Botão Add player é desabilitado ao atingir o limite do modo splitscreen."""
    page = make_page(num_monitors=1, party_players=(0, 1, 2, 3))

    page._update_num_players_limits(is_splitscreen=True)

    assert page._max_players == 4
    page.add_player_button.set_sensitive.assert_called_once_with(False)
