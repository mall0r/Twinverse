#!/usr/bin/env python3
"""Módulo de teste mínimo para a aplicação Twinverse."""

from src.core import Config
from src.models import Profile
from src.models.instance import SteamInstance


def test_minimal_functionality():
    """Testa a funcionalidade mínima da aplicação Twinverse sem GUI."""
    print("Testing minimal functionality without GUI...")

    # Testa importações principais sem inicializar GUI
    try:
        # Importa módulos principais
        import gi  # noqa: F401

        from src.core.logger import Logger  # noqa: F401
        from src.services import DeviceManager, InstanceService  # noqa: F401

        print("All core modules imported successfully")

        # Testa criação de objetos básicos
        Config()

        print("Config created successfully")

        # Testa modelos
        Profile(name="test_profile", num_players=2)
        SteamInstance(instance_num=1, name="test_instance")

        print("Profile and SteamInstance created successfully")

        assert True  # Se chegou até aqui, tudo funcionou
        print("Minimal functionality test passed!")

    except Exception as e:
        print(f"Error in minimal functionality test: {e}")
        raise AssertionError(f"Falha no teste de funcionalidade mínima: {e}")


def run_minimal_test():
    """Executa o teste mínimo da aplicação Twinverse."""
    print("Setting up minimal test...")
    test_minimal_functionality()


if __name__ == "__main__":
    run_minimal_test()
