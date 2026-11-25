"""Lightweight internationalization (EN / PT-BR) with live UI language switching."""

import locale
import os
import weakref
from typing import Any, Callable, Literal

LanguagePreference = Literal["auto", "en", "pt_BR"]
ResolvedLanguage = Literal["en", "pt_BR"]

LANGUAGE_AUTO: Literal["auto"] = "auto"
LANGUAGE_EN: Literal["en"] = "en"
LANGUAGE_PT_BR: Literal["pt_BR"] = "pt_BR"

SUPPORTED_PREFERENCES: tuple[LanguagePreference, ...] = (
    LANGUAGE_AUTO,
    LANGUAGE_EN,
    LANGUAGE_PT_BR,
)

TRANSLATIONS: dict[ResolvedLanguage, dict[str, str]] = {
    "en": {
        # General / language choices
        "lang.auto": "System default",
        "lang.en": "English",
        "lang.pt_BR": "Português (Brasil)",
        "common.ok": "OK",
        "common.cancel": "Cancel",
        "common.error": "Error",
        "player.default_name": "Player",
        # Main window header, menu & shortcuts
        "menu.preferences": "Preferences",
        "menu.refresh_devices": "Refresh devices",
        "menu.language": "Language",
        "menu.about": "About Twinverse",
        "header.theme_tooltip": "Switch light / dark appearance",
        "header.menu_tooltip": "Application menu",
        "panel.player_setup": "player setup",
        "panel.show_tooltip": "Show {title} ({shortcut})",
        "panel.hide_tooltip": "Hide {title} ({shortcut})",
        "panel.show_label": "Show {title}",
        "panel.hide_label": "Hide {title}",
        # Session summary & footer
        "session.setup_title": "Session setup",
        "session.starting_title": "Starting your session",
        "session.starting_detail": "Steam progress is shown beside each player.",
        "session.stopping_title": "Ending the session",
        "session.stopping_detail": "Waiting for all instances to close.",
        "session.running_title": "You're live",
        "session.running_detail": "{count} running. Select any player to manage their instance.",
        "session.empty_title": "Your party is empty",
        "session.empty_detail": "Check a player to include them in the session.",
        "session.needs_setup_title": "Setup needed",
        "session.needs_setup_detail": "{ready} of {total} ready. Select a player and install their Steam instance.",
        "session.ready_title": "Ready to play",
        "session.ready_detail_one": "{count} player selected. Your space is ready.",
        "session.ready_detail_many": "{count} players selected. Your space is ready.",
        "session.launch_button": "Launch session",
        "session.end_button": "End session",
        "session.starting_button": "Starting…",
        "session.stopping_button": "Stopping…",
        "session.launch_tooltip": "Launch all selected players (Ctrl+Enter)",
        "session.stop_tooltip": "Stop all instances",
        # Roster & stage
        "roster.heading": "Your party",
        "roster.add_player": "Add player",
        "roster.add_player_tooltip": "Add a player to the party",
        "roster.configure_a11y": "Configure {name} {num}",
        "roster.remove_tooltip": "Remove {name} ({num}) from party",
        "roster.remove_a11y": "Remove {name} {num}",
        "stage.eyebrow": "SESSION LAYOUT",
        "stage.detecting_displays": "Detecting displays",
        "stage.display_one": "{count} display",
        "stage.display_many": "{count} displays",
        "stage.no_display": "No display detected",
        "stage.direct_title": "Direct Steam mode",
        "stage.direct_description": (
            "Players run in independent windows. Enable Gamescope in Preferences to arrange a split-screen session."
        ),
        "stage.drag_hint": "Drag players between spaces to swap them.",
        "stage.split_direction": "SPLIT DIRECTION",
        "stage.placement": "PLACEMENT",
        "stage.mode.fullscreen": "Fullscreen",
        "stage.mode.splitscreen": "Splitscreen",
        "stage.orientation.horizontal": "Horizontal",
        "stage.orientation.vertical": "Vertical",
        "stage.placement.automatic": "Automatic",
        "stage.placement.custom": "Custom",
        "stage.layout_error": (
            "Players {players} have no display space. Choose a larger template or exclude them from the party."
        ),
        "inspector.eyebrow": "PLAYER SETUP",
        # Tiling templates & picker
        "tiling.fullscreen": "Fullscreen",
        "tiling.columns": "Columns",
        "tiling.rows": "Rows",
        "tiling.main-left": "Main left",
        "tiling.main-top": "Main top",
        "tiling.grid": "Grid",
        "tiling.capacity_one": "{count} player",
        "tiling.capacity_many": "{count} players",
        "tiling.tooltip": "{title} · {capacity}",
        # Layout preview
        "preview.empty": "Your session canvas is empty.\nSelect at least one instance from the roster to begin.",
        "preview.not_detected": "Not detected",
        "preview.split_screen_meta": "Split screen · {orientation}",
        "preview.fullscreen_meta": "Fullscreen",
        "preview.player_badge_one": "{count} PLAYER",
        "preview.player_badge_many": "{count} PLAYERS",
        "preview.capacity_badge": "{occupied} / {total} PLAYERS",
        "preview.shared_display_warning": "No dedicated display for this group; it shares {name}.",
        "preview.no_display_warning": "No display detected. Using a 1920 × 1080 preview until one is available.",
        "preview.unassigned_title": "Players without a space",
        "preview.unassigned_warning": (
            "These players have no monitor assignment. Choose a larger layout or drop them into an empty space."
        ),
        "preview.unassigned_slot_label": "Unassigned · Players without a space",
        "preview.unassigned_monitor": "Unassigned (preview geometry only)",
        "preview.space_header": "SPACE {num}",
        "preview.space_label": "{name} · Space {num}",
        "preview.mouse_grab_tooltip": "Mouse grab enabled",
        "preview.controller_assigned": "Controller assigned",
        "preview.empty_space": "Empty space",
        "preview.drop_here": "Drop a player here",
        "preview.empty_slot_tooltip": "Empty space · Drop a player here\n{location}",
        "preview.empty_slot_desc": "{location} Drop a player here.",
        "preview.slot_location": "Space {num} on {monitor}. {width} by {height} pixels at x {x}, y {y}.",
        "preview.ready_to_configure": "Ready to configure",
        "preview.selected_prefix": "Selected player. ",
        "preview.drag_interaction": " Drag to another space to swap players.",
        "preview.slot_desc": "{selected}{location} Activate to configure this player.{interaction}",
        "preview.slot_tooltip": "Configure {name} ({num}) · {status}\n{location}{interaction}",
        # PlayerRow inspector
        "player.edit_name_tooltip": "Edit player name",
        "player.include_tooltip": "Include {label} in the session",
        "player.include_a11y": "Include {label}",
        "player.controls_section": "Controls",
        "player.refresh_controllers": "Refresh controllers",
        "player.controller_label": "_Controller",
        "player.controller_none": "None",
        "player.controller_disconnected_label": "{name} (Disconnected)",
        "player.controller_tooltip": (
            "Assign a gamepad to this player. The last assigned controller is remembered even when disconnected "
            "and connects automatically once turned on. If controllers are missing after refreshing, "
            "check that your user belongs to the input group; see the guide for details."
        ),
        "player.grab_mouse_label": "_Grab mouse",
        "player.grab_mouse_help": "Only one player can capture the mouse.",
        "player.audio_section": "Audio",
        "player.audio_default": "Default",
        "player.output_device_label": "_Output device",
        "player.network_section": "Network",
        "player.guest_ip_placeholder": "Automatic",
        "player.guest_ip_label": "_Guest IP (optional)",
        "player.guest_ip_tooltip": (
            "Optional IPv4 address for this instance on the LAN, for example 192.168.1.50. "
            "Leave empty to select a free address automatically."
        ),
        "player.guest_ip_help": "Leave blank to choose a free LAN address.",
        "player.guest_ip_help_disabled": (
            "Network isolation is disabled in Preferences. Instances share the host network."
        ),
        "player.env_section": "Environment variables",
        "player.env_help": "Override variables for this player. Values are kept exactly as entered.",
        "player.env_add": "Add variable",
        "env.key_label": "_Key",
        "env.key_placeholder": "VARIABLE_NAME",
        "env.value_label": "_Value",
        "env.value_placeholder": "Value (may be empty)",
        "env.remove_tooltip": "Remove environment variable",
        # Player status & action buttons
        "status.stopping": "Stopping…",
        "status.updating": "Updating Steam…",
        "status.updating_percent": "Updating Steam · {percent}%",
        "status.starting": "Starting Steam…",
        "status.running": "Running",
        "status.ready": "Ready",
        "status.not_installed": "Not installed",
        "player.action.stop": "Stop player",
        "player.action.stop_tooltip": "Stop this player's Steam client",
        "player.action.cancel": "Cancel startup",
        "player.action.cancel_tooltip": "Cancel this player's startup",
        "player.action.stopping": "Stopping…",
        "player.action.stopping_tooltip": "Waiting for this player to stop",
        "player.action.start": "Start player",
        "player.action.start_tooltip": "Start this player's Steam client",
        "player.action.install": "Install Steam",
        "player.action.install_tooltip": "Install and configure Steam for this player",
        # Preferences window
        "prefs.title": "Preferences",
        "prefs.tab.engine": "Engine",
        "prefs.tab.instances": "Instance data",
        "prefs.engine.heading": "Launch engine",
        "prefs.engine.description": "Choose how every player runs. Changes save immediately and apply to the next launch.",
        "prefs.language.title": "Language",
        "prefs.language.description": "Choose the interface language. Changes apply immediately.",
        "prefs.gamescope.title": "Use Gamescope",
        "prefs.gamescope.description": (
            "Give each player a Gamescope compositor. Turn this off to run Steam directly in Bubblewrap."
        ),
        "prefs.steamdeck.title": "Steam Deck tag",
        "prefs.steamdeck.description": "Add --mangoapp to Gamescope and -steamdeck to Steam.",
        "prefs.wsi.title": "Gamescope WSI",
        "prefs.wsi.description": "Enable the Gamescope Wayland Support Interface (WSI).",
        "prefs.isolate_network.title": "Isolate network",
        "prefs.isolate_network.description": (
            "Give each player an isolated network namespace and LAN IP with pasta. "
            "Leave off to share the host network (recommended for online play and LAN discovery); "
            "turn on for local LAN games or dedicated servers that require distinct local IPs."
        ),
        "prefs.reset.title": "Start from defaults",
        "prefs.reset.description": "Reset engine options, player settings and layout. Instance files stay on disk.",
        "prefs.reset.button": "Reset all settings",
        "prefs.reset.tooltip": "Reset all settings to default values without deleting instance files",
        "prefs.instances.heading": "Player files",
        "prefs.instances.description": (
            "Each player has an isolated Steam home. Open its files, launch a terminal, or reset just that player."
        ),
        "prefs.instances.empty_title": "No instance data yet",
        "prefs.instances.empty_description": (
            "Launch a player to create its Steam home.\nIts files and reset tools will appear here."
        ),
        "prefs.instances.open_home_tooltip": "Open home directory for {name} ({num})",
        "prefs.instances.open_terminal_tooltip": "Open terminal for {name} ({num})",
        "prefs.instances.reset_tooltip": "Reset {name} ({num}) settings and remove home directory",
        "prefs.instances.confirm_heading": "Reset {player}?",
        "prefs.instances.confirm_body": (
            "This will reset the player settings to default and permanently delete {player}'s home directory, "
            "along with all its contents. This action cannot be undone."
        ),
        "prefs.instances.confirm_reset": "Reset Player",
        "prefs.instances.remove_error": "The home directory could not be removed completely:\n{error}",
        # Toast overlay & presenter messages
        "toast.level.info": "NOTICE",
        "toast.level.error": "ERROR",
        "toast.level.busy": "WORKING",
        "toast.dismiss_tooltip": "Dismiss",
        "toast.dismiss_a11y": "Dismiss notification",
        "presenter.starting_instance": "Starting the Steam client of instance {num}… please wait",
        "presenter.started_instance": "Steam started for instance {num}",
        "presenter.failed_instance": "The Steam client of instance {num} failed: {reason}",
        "presenter.stopped_instance": "Instance {num} stopped",
        "presenter.stopped_unexpectedly": "Instance {num} stopped unexpectedly",
        "presenter.cancelled_instance": "Cancelled the start of instance {num}",
        "presenter.all_stopped": "All instances stopped",
        "presenter.no_instances_selected": "No instances selected to launch.",
        # About dialog
        "about.comments": (
            "Twinverse is a tool for Linux/SteamOS that allows you to create and manage multiple "
            "instances of gamescope and steam simultaneously. Twinverse uses Bubblewrap (bwrap), "
            "a low-level Linux sandboxing tool, to isolate each Steam Client instance."
        ),
        "about.contributing": "Contributing",
        "about.donate": "Donate",
        # Error handler
        "error.missing_dependency": "Missing dependency: {error}",
        "error.virtual_device": "Virtual device error: {error}",
        "error.twinverse": "Twinverse error: {error}",
        "error.command_not_found": "Required command '{filename}' not found. Please install the missing dependency.",
        "error.file_not_found": "Required file or command not found: {error}",
        "error.system": "System error: {error}",
        "error.launch_failed": "Could not launch: {error}",
    },
    "pt_BR": {
        # General / language choices
        "lang.auto": "Padrão do sistema",
        "lang.en": "English",
        "lang.pt_BR": "Português (Brasil)",
        "common.ok": "OK",
        "common.cancel": "Cancelar",
        "common.error": "Erro",
        "player.default_name": "Jogador",
        # Main window header, menu & shortcuts
        "menu.preferences": "Preferências",
        "menu.refresh_devices": "Atualizar dispositivos",
        "menu.language": "Idioma",
        "menu.about": "Sobre o Twinverse",
        "header.theme_tooltip": "Alternar aparência clara / escura",
        "header.menu_tooltip": "Menu do aplicativo",
        "panel.player_setup": "configuração do jogador",
        "panel.show_tooltip": "Mostrar {title} ({shortcut})",
        "panel.hide_tooltip": "Ocultar {title} ({shortcut})",
        "panel.show_label": "Mostrar {title}",
        "panel.hide_label": "Ocultar {title}",
        # Session summary & footer
        "session.setup_title": "Configuração da sessão",
        "session.starting_title": "Iniciando sua sessão",
        "session.starting_detail": "O progresso do Steam aparece ao lado de cada jogador.",
        "session.stopping_title": "Encerrando a sessão",
        "session.stopping_detail": "Aguardando todas as instâncias fecharem.",
        "session.running_title": "Sessão ativa",
        "session.running_detail": "{count} em execução. Selecione um jogador para gerenciar sua instância.",
        "session.empty_title": "Seu grupo está vazio",
        "session.empty_detail": "Marque um jogador para incluí-lo na sessão.",
        "session.needs_setup_title": "Configuração necessária",
        "session.needs_setup_detail": "{ready} de {total} prontos. Selecione um jogador e instale o Steam dele.",
        "session.ready_title": "Pronto para jogar",
        "session.ready_detail_one": "{count} jogador selecionado. Seu espaço está pronto.",
        "session.ready_detail_many": "{count} jogadores selecionados. Seu espaço está pronto.",
        "session.launch_button": "Iniciar sessão",
        "session.end_button": "Encerrar sessão",
        "session.starting_button": "Iniciando…",
        "session.stopping_button": "Parando…",
        "session.launch_tooltip": "Iniciar todos os jogadores selecionados (Ctrl+Enter)",
        "session.stop_tooltip": "Parar todas as instâncias",
        # Roster & stage
        "roster.heading": "Seu grupo",
        "roster.add_player": "Adicionar jogador",
        "roster.add_player_tooltip": "Adicionar um jogador ao grupo",
        "roster.configure_a11y": "Configurar {name} {num}",
        "roster.remove_tooltip": "Remover {name} ({num}) do grupo",
        "roster.remove_a11y": "Remover {name} {num}",
        "stage.eyebrow": "LAYOUT DA SESSÃO",
        "stage.detecting_displays": "Detectando monitores",
        "stage.display_one": "{count} monitor",
        "stage.display_many": "{count} monitores",
        "stage.no_display": "Nenhum monitor detectado",
        "stage.direct_title": "Modo Steam direto",
        "stage.direct_description": (
            "Os jogadores executam em janelas independentes. Ative o Gamescope nas Preferências "
            "para organizar uma sessão em tela dividida."
        ),
        "stage.drag_hint": "Arraste jogadores entre os espaços para trocá-los de lugar.",
        "stage.split_direction": "DIREÇÃO DA DIVISÃO",
        "stage.placement": "POSICIONAMENTO",
        "stage.mode.fullscreen": "Tela cheia",
        "stage.mode.splitscreen": "Tela dividida",
        "stage.orientation.horizontal": "Horizontal",
        "stage.orientation.vertical": "Vertical",
        "stage.placement.automatic": "Automático",
        "stage.placement.custom": "Personalizado",
        "stage.layout_error": (
            "Os jogadores {players} estão sem espaço de monitor. Escolha um molde maior ou remova-os do grupo."
        ),
        "inspector.eyebrow": "CONFIGURAÇÃO DO JOGADOR",
        # Tiling templates & picker
        "tiling.fullscreen": "Tela cheia",
        "tiling.columns": "Colunas",
        "tiling.rows": "Linhas",
        "tiling.main-left": "Principal à esquerda",
        "tiling.main-top": "Principal no topo",
        "tiling.grid": "Grade",
        "tiling.capacity_one": "{count} jogador",
        "tiling.capacity_many": "{count} jogadores",
        "tiling.tooltip": "{title} · {capacity}",
        # Layout preview
        "preview.empty": "O canvas da sessão está vazio.\nSelecione pelo menos uma instância na lista para começar.",
        "preview.not_detected": "Não detectado",
        "preview.split_screen_meta": "Tela dividida · {orientation}",
        "preview.fullscreen_meta": "Tela cheia",
        "preview.player_badge_one": "{count} JOGADOR",
        "preview.player_badge_many": "{count} JOGADORES",
        "preview.capacity_badge": "{occupied} / {total} JOGADORES",
        "preview.shared_display_warning": "Sem monitor dedicado para este grupo; ele compartilha {name}.",
        "preview.no_display_warning": "Nenhum monitor detectado. Usando prévia 1920 × 1080 até que um fique disponível.",
        "preview.unassigned_title": "Jogadores sem espaço",
        "preview.unassigned_warning": (
            "Estes jogadores não têm monitor atribuído. Escolha um layout maior ou arraste-os para um espaço vazio."
        ),
        "preview.unassigned_slot_label": "Sem espaço · Jogadores sem espaço",
        "preview.unassigned_monitor": "Sem espaço (apenas prévia de geometria)",
        "preview.space_header": "ESPAÇO {num}",
        "preview.space_label": "{name} · Espaço {num}",
        "preview.mouse_grab_tooltip": "Captura de mouse ativada",
        "preview.controller_assigned": "Controle atribuído",
        "preview.empty_space": "Espaço vazio",
        "preview.drop_here": "Solte um jogador aqui",
        "preview.empty_slot_tooltip": "Espaço vazio · Solte um jogador aqui\n{location}",
        "preview.empty_slot_desc": "{location} Solte um jogador aqui.",
        "preview.slot_location": "Espaço {num} em {monitor}. {width} por {height} pixels em x {x}, y {y}.",
        "preview.ready_to_configure": "Pronto para configurar",
        "preview.selected_prefix": "Jogador selecionado. ",
        "preview.drag_interaction": " Arraste para outro espaço para trocar jogadores.",
        "preview.slot_desc": "{selected}{location} Ative para configurar este jogador.{interaction}",
        "preview.slot_tooltip": "Configurar {name} ({num}) · {status}\n{location}{interaction}",
        # PlayerRow inspector
        "player.edit_name_tooltip": "Editar nome do jogador",
        "player.include_tooltip": "Incluir {label} na sessão",
        "player.include_a11y": "Incluir {label}",
        "player.controls_section": "Controles",
        "player.refresh_controllers": "Atualizar controles",
        "player.controller_label": "_Controle",
        "player.controller_none": "Nenhum",
        "player.controller_disconnected_label": "{name} (Desconectado)",
        "player.controller_tooltip": (
            "Atribua um controle a este jogador. O último controle atribuído é lembrado mesmo desconectado "
            "e conecta automaticamente ao ser ligado. Se os controles não aparecerem após atualizar, "
            "verifique se seu usuário pertence ao grupo input; consulte o guia para mais detalhes."
        ),
        "player.grab_mouse_label": "_Capturar mouse",
        "player.grab_mouse_help": "Apenas um jogador pode capturar o mouse.",
        "player.audio_section": "Áudio",
        "player.audio_default": "Padrão",
        "player.output_device_label": "_Dispositivo de saída",
        "player.network_section": "Rede",
        "player.guest_ip_placeholder": "Automático",
        "player.guest_ip_label": "_IP convidado (opcional)",
        "player.guest_ip_tooltip": (
            "Endereço IPv4 opcional para esta instância na rede local, por exemplo 192.168.1.50. "
            "Deixe vazio para escolher um endereço livre automaticamente."
        ),
        "player.guest_ip_help": "Deixe em branco para escolher um endereço LAN livre.",
        "player.guest_ip_help_disabled": (
            "O isolamento de rede está desativado nas Preferências. As instâncias compartilham a rede do host."
        ),
        "player.env_section": "Variáveis de ambiente",
        "player.env_help": "Sobrescreve variáveis para este jogador. Os valores são mantidos exatamente como digitados.",
        "player.env_add": "Adicionar variável",
        "env.key_label": "_Chave",
        "env.key_placeholder": "NOME_DA_VARIAVEL",
        "env.value_label": "_Valor",
        "env.value_placeholder": "Valor (pode ficar vazio)",
        "env.remove_tooltip": "Remover variável de ambiente",
        # Player status & action buttons
        "status.stopping": "Parando…",
        "status.updating": "Atualizando Steam…",
        "status.updating_percent": "Atualizando Steam · {percent}%",
        "status.starting": "Iniciando Steam…",
        "status.running": "Em execução",
        "status.ready": "Pronto",
        "status.not_installed": "Não instalado",
        "player.action.stop": "Parar jogador",
        "player.action.stop_tooltip": "Parar o cliente Steam deste jogador",
        "player.action.cancel": "Cancelar inicialização",
        "player.action.cancel_tooltip": "Cancelar a inicialização deste jogador",
        "player.action.stopping": "Parando…",
        "player.action.stopping_tooltip": "Aguardando este jogador parar",
        "player.action.start": "Iniciar jogador",
        "player.action.start_tooltip": "Iniciar o cliente Steam deste jogador",
        "player.action.install": "Instalar Steam",
        "player.action.install_tooltip": "Instalar e configurar o Steam para este jogador",
        # Preferences window
        "prefs.title": "Preferências",
        "prefs.tab.engine": "Motor",
        "prefs.tab.instances": "Dados das instâncias",
        "prefs.engine.heading": "Motor de execução",
        "prefs.engine.description": (
            "Escolha como cada jogador executa. As alterações são salvas imediatamente e valem na próxima inicialização."
        ),
        "prefs.language.title": "Idioma",
        "prefs.language.description": "Escolha o idioma da interface. As alterações são aplicadas imediatamente.",
        "prefs.gamescope.title": "Usar Gamescope",
        "prefs.gamescope.description": (
            "Dá a cada jogador um compositor Gamescope. Desative para executar o Steam diretamente no Bubblewrap."
        ),
        "prefs.steamdeck.title": "Tag Steam Deck",
        "prefs.steamdeck.description": "Adiciona --mangoapp ao Gamescope e -steamdeck ao Steam.",
        "prefs.wsi.title": "Gamescope WSI",
        "prefs.wsi.description": "Ativa a interface Gamescope Wayland Support Interface (WSI).",
        "prefs.isolate_network.title": "Isolar rede",
        "prefs.isolate_network.description": (
            "Dá a cada jogador um namespace de rede e IP local isolados com pasta. "
            "Deixe desativado para compartilhar a rede do host (recomendado para multiplayer online e descoberta LAN); "
            "ative para jogos em LAN ou servidores dedicados que exigem IPs locais distintos."
        ),
        "prefs.reset.title": "Restaurar padrões",
        "prefs.reset.description": (
            "Redefine opções do motor, configurações de jogadores e layout. Os arquivos das instâncias continuam no disco."
        ),
        "prefs.reset.button": "Redefinir tudo",
        "prefs.reset.tooltip": "Redefine todas as configurações para os valores padrão sem apagar os arquivos",
        "prefs.instances.heading": "Arquivos dos jogadores",
        "prefs.instances.description": (
            "Cada jogador tem uma pasta Steam isolada. Abra os arquivos, inicie um terminal ou redefina apenas esse jogador."
        ),
        "prefs.instances.empty_title": "Nenhum dado de instância ainda",
        "prefs.instances.empty_description": (
            "Inicie um jogador para criar sua pasta Steam.\nOs arquivos e ferramentas de redefinição aparecerão aqui."
        ),
        "prefs.instances.open_home_tooltip": "Abrir pasta de arquivos de {name} ({num})",
        "prefs.instances.open_terminal_tooltip": "Abrir terminal para {name} ({num})",
        "prefs.instances.reset_tooltip": "Redefinir configurações de {name} ({num}) e remover pasta",
        "prefs.instances.confirm_heading": "Redefinir {player}?",
        "prefs.instances.confirm_body": (
            "Isso redefinirá as configurações do jogador para o padrão e apagará permanentemente a pasta de {player}, "
            "junto com todo o seu conteúdo. Esta ação não pode ser desfeita."
        ),
        "prefs.instances.confirm_reset": "Redefinir jogador",
        "prefs.instances.remove_error": "Não foi possível remover completamente a pasta da instância:\n{error}",
        # Toast overlay & presenter messages
        "toast.level.info": "AVISO",
        "toast.level.error": "ERRO",
        "toast.level.busy": "EM ANDAMENTO",
        "toast.dismiss_tooltip": "Dispensar",
        "toast.dismiss_a11y": "Dispensar notificação",
        "presenter.starting_instance": "Iniciando o cliente Steam da instância {num}… aguarde",
        "presenter.started_instance": "Steam iniciado na instância {num}",
        "presenter.failed_instance": "Falha no cliente Steam da instância {num}: {reason}",
        "presenter.stopped_instance": "Instância {num} parada",
        "presenter.stopped_unexpectedly": "A instância {num} parou inesperadamente",
        "presenter.cancelled_instance": "Inicialização da instância {num} cancelada",
        "presenter.all_stopped": "Todas as instâncias foram paradas",
        "presenter.no_instances_selected": "Nenhuma instância selecionada para iniciar.",
        # About dialog
        "about.comments": (
            "Twinverse é uma ferramenta para Linux/SteamOS que permite criar e gerenciar múltiplas "
            "instâncias de Gamescope e Steam simultaneamente. O Twinverse usa Bubblewrap (bwrap), "
            "uma ferramenta de sandbox Linux de baixo nível, para isolar cada cliente Steam."
        ),
        "about.contributing": "Contribuir",
        "about.donate": "Apoiar",
        # Error handler
        "error.missing_dependency": "Dependência ausente: {error}",
        "error.virtual_device": "Erro de dispositivo virtual: {error}",
        "error.twinverse": "Erro do Twinverse: {error}",
        "error.command_not_found": "Comando obrigatório '{filename}' não encontrado. Instale a dependência ausente.",
        "error.file_not_found": "Arquivo ou comando obrigatório não encontrado: {error}",
        "error.system": "Erro do sistema: {error}",
        "error.launch_failed": "Não foi possível iniciar: {error}",
    },
}

_preference: LanguagePreference = LANGUAGE_EN
_active_language: ResolvedLanguage = LANGUAGE_EN
_listeners: list[weakref.ref[Any]] = []


def detect_system_language() -> ResolvedLanguage:
    """Resolve the best supported UI language from the host locale environment."""
    candidates: list[str] = []
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        raw = os.environ.get(var, "").strip()
        if raw:
            candidates.extend(part.strip() for part in raw.split(":") if part.strip())
    try:
        loc, _encoding = locale.getlocale()
        if loc:
            candidates.append(loc)
    except ValueError:
        pass

    for candidate in candidates:
        normalized = candidate.split(".", 1)[0].split("@", 1)[0].replace("-", "_").lower()
        if normalized in ("c", "posix", ""):
            continue
        if normalized.startswith("pt"):
            return LANGUAGE_PT_BR
        if normalized.startswith("en"):
            return LANGUAGE_EN
        return LANGUAGE_EN
    return LANGUAGE_EN


def resolve_language(preference: str | None) -> ResolvedLanguage:
    """Convert a language preference ('auto', 'en', 'pt_BR') to a concrete catalog key."""
    if preference == LANGUAGE_PT_BR:
        return LANGUAGE_PT_BR
    if preference == LANGUAGE_EN:
        return LANGUAGE_EN
    if preference == LANGUAGE_AUTO:
        return detect_system_language()
    return LANGUAGE_EN


def normalize_language_preference(preference: str | None) -> LanguagePreference:
    """Coerce arbitrary input to a valid language preference."""
    if preference in SUPPORTED_PREFERENCES:
        return preference  # type: ignore[return-value]
    if isinstance(preference, str):
        cleaned = preference.strip().replace("-", "_").lower()
        if cleaned == "auto":
            return LANGUAGE_AUTO
        if cleaned.startswith("pt"):
            return LANGUAGE_PT_BR
        if cleaned.startswith("en"):
            return LANGUAGE_EN
    return LANGUAGE_AUTO


def get_language() -> ResolvedLanguage:
    """Return the currently active concrete UI language ('en' or 'pt_BR')."""
    return _active_language


def get_language_preference() -> LanguagePreference:
    """Return the configured language preference ('auto', 'en', or 'pt_BR')."""
    return _preference


def set_language(preference: str) -> ResolvedLanguage:
    """Set the UI language preference and notify all subscribed live widgets."""
    global _preference, _active_language
    normalized = normalize_language_preference(preference)
    resolved = resolve_language(normalized)
    changed = normalized != _preference or resolved != _active_language
    _preference = normalized
    _active_language = resolved
    if changed:
        _notify_listeners(resolved)
    return resolved


def _make_weak_callback(callback: Callable[[ResolvedLanguage], None]) -> weakref.ref[Any]:
    if getattr(callback, "__self__", None) is not None and getattr(callback, "__func__", None) is not None:
        return weakref.WeakMethod(callback)
    return weakref.ref(callback)


def subscribe(callback: Callable[[ResolvedLanguage], None]) -> None:
    """Subscribe a callable or bound method to live language changes without creating reference cycles."""
    ref = _make_weak_callback(callback)
    for existing in list(_listeners):
        if existing() is None:
            _listeners.remove(existing)
        elif existing == ref:
            return
    _listeners.append(ref)


def unsubscribe(callback: Callable[[ResolvedLanguage], None]) -> None:
    """Remove a previously subscribed language listener."""
    target = _make_weak_callback(callback)
    for existing in list(_listeners):
        if existing() is None or existing == target:
            _listeners.remove(existing)


def _notify_listeners(language: ResolvedLanguage) -> None:
    alive: list[weakref.ref[Any]] = []
    callbacks: list[Callable[[ResolvedLanguage], None]] = []
    for ref in list(_listeners):
        cb = ref()
        if cb is not None:
            alive.append(ref)
            callbacks.append(cb)
    _listeners[:] = alive
    for cb in callbacks:
        cb(language)


def t(key: str, **kwargs: Any) -> str:
    """Translate a message key into the active language, falling back to English."""
    template = TRANSLATIONS.get(_active_language, TRANSLATIONS[LANGUAGE_EN]).get(key)
    if template is None:
        template = TRANSLATIONS[LANGUAGE_EN].get(key, key)
    if kwargs:
        return template.format(**kwargs)
    return template


def ngettext(singular_key: str, plural_key: str, count: int, **kwargs: Any) -> str:
    """Translate a count-dependent message using singular or plural catalog keys."""
    key = singular_key if count == 1 else plural_key
    return t(key, count=count, **kwargs)


def translate_template_title(template_id: str, fallback: str = "") -> str:
    """Return the localized title for a monitor tiling template ID."""
    key = f"tiling.{template_id}"
    translated = t(key)
    return translated if translated != key else (fallback or template_id)
