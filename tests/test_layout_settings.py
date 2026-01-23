"""Testes para a funcionalidade de limites de instâncias na página de configurações de layout."""

import os
import sys
from unittest.mock import MagicMock

from src.gui.pages.layout_settings_page import LayoutSettingsPage

# Adicionando o caminho src para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_update_num_players_limits():
    """Testa a função _update_num_players_limits com diferentes cenários."""
    # Criando uma instância simulada da página de configurações de layout
    layout_page = LayoutSettingsPage()

    # Simulando o ajuste (adjustment) do widget de número de jogadores
    mock_adjustment = MagicMock()
    mock_adjustment.get_value.return_value = 1  # Valor inicial

    # Substituindo o adjustment real pelo mock
    layout_page.num_players_row = MagicMock()
    layout_page.num_players_row.get_adjustment.return_value = mock_adjustment

    # Teste 1: Modo fullscreen com 1 monitor (limite deve ser 1)
    layout_page._num_monitors = 1
    layout_page._update_num_players_limits(is_splitscreen=False)
    mock_adjustment.set_upper.assert_called_with(1)  # min(8, 1) = 1

    # Teste 2: Modo fullscreen com 2 monitores (limite deve ser 2)
    mock_adjustment.reset_mock()
    mock_adjustment.get_value.return_value = 1
    layout_page._num_monitors = 2
    layout_page._update_num_players_limits(is_splitscreen=False)
    mock_adjustment.set_upper.assert_called_with(2)  # min(8, 2) = 2

    # Teste 3: Modo fullscreen com 10 monitores (limite deve ser 8 porque é o máximo)
    mock_adjustment.reset_mock()
    mock_adjustment.get_value.return_value = 1
    layout_page._num_monitors = 10
    layout_page._update_num_players_limits(is_splitscreen=False)
    mock_adjustment.set_upper.assert_called_with(8)  # min(8, 10) = 8

    # Teste 4: Modo splitscreen com 1 monitor (limite deve ser 4)
    mock_adjustment.reset_mock()
    mock_adjustment.get_value.return_value = 1
    layout_page._num_monitors = 1
    layout_page._update_num_players_limits(is_splitscreen=True)
    mock_adjustment.set_upper.assert_called_with(4)  # min(8, 1*4) = 4

    # Teste 5: Modo splitscreen com 2 monitores (limite deve ser 8)
    mock_adjustment.reset_mock()
    mock_adjustment.get_value.return_value = 1
    layout_page._num_monitors = 2
    layout_page._update_num_players_limits(is_splitscreen=True)
    mock_adjustment.set_upper.assert_called_with(8)  # min(8, 2*4) = 8

    # Teste 6: Modo splitscreen com 3 monitores (limite ainda deve ser 8)
    mock_adjustment.reset_mock()
    mock_adjustment.get_value.return_value = 1
    layout_page._num_monitors = 3
    layout_page._update_num_players_limits(is_splitscreen=True)
    mock_adjustment.set_upper.assert_called_with(8)  # min(8, 3*4) = 8

    print("Todos os testes passaram!")


if __name__ == "__main__":
    test_update_num_players_limits()
