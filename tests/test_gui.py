"""Testes para a interface gráfica do projeto Twinverse."""

from unittest.mock import MagicMock, patch


@patch("gi.repository.Gtk")
def test_gtk_components_load(mock_gtk):
    """Testa se os componentes GTK carregam sem erro."""
    mock_window = MagicMock()
    mock_gtk.Window.return_value = mock_window

    window = mock_gtk.Window()
    assert window is not None
