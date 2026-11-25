<p align="right">
  <a href="https://mall0r.github.io/Twinverse/?lang=pt"><img src="https://img.shields.io/badge/Docs-GitHub%20Pages-1f6feb.svg?logo=githubpages&logoColor=white" alt="Documentação Interativa"/></a>
  <a href="../README.md"><img src="https://img.shields.io/badge/en-US-darkblue.svg" alt="English"/></a>
  <a href="README.pt-br.md"><img src="https://img.shields.io/badge/pt-BR-darkgreen.svg" alt="Portuguese"/></a>
</p>

<p align="center">
  <img src="../share/icons/hicolor/scalable/apps/io.github.mall0r.Twinverse.svg" alt="Logo do Twinverse" width="160" height="160">
</p>

<p align="center">
  <a href="https://github.com/mall0r/Twinverse/releases"><img src="https://img.shields.io/badge/Version-2.0.0--alpha.3-blue.svg" alt="Versão"/></a>
  <a href="https://mall0r.github.io/Twinverse/?lang=pt"><img src="https://img.shields.io/badge/Documenta%C3%A7%C3%A3o-Online-84b4fa.svg" alt="Documentação"/></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-green.svg" alt="Licença"/></a>
  <a href="https://www.gtk.org/"><img src="https://img.shields.io/badge/GTK-4-orange.svg" alt="GTK"/></a>
  <a href="https://gnome.pages.gitlab.gnome.org/libadwaita/"><img src="https://img.shields.io/badge/libadwaita-1-purple.svg" alt="libadwaita"/></a>
</p>

<p align="center">
  <a href="https://www.python.org" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://www.rust-lang.org/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust"/></a>
  <a href="https://www.gnu.org/software/bash/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Shell-4EAA25?style=for-the-badge&logo=gnu-bash&logoColor=white" alt="Shell"/></a>
  <a href="https://www.javascript.com/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript"/></a>
  <a href="https://www.w3.org/Style/CSS/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/CSS3-66309A?style=for-the-badge&logo=css3&logoColor=white" alt="CSS"/></a>
</p>

# O que é o Twinverse?

O **Twinverse** executa até **8 clientes Steam em um único PC com Linux ou SteamOS**. Cada jogador tem uma pasta pessoal do Steam e pode jogar o mesmo título que os demais ou escolher outro. O Gamescope exibe o Steam Big Picture em tela dividida ou em vários monitores. Por padrão, as instâncias **compartilham a rede do host**.

> [!TIP]
> Veja as telas de configuração no [guia ilustrado](https://mall0r.github.io/Twinverse/?lang=pt#step-by-step).

<p align="center">
  <img alt="Twinverse" src="../share/screenshots/twinverse-session-dark.png" />
</p>

> [!WARNING]
> Cada jogador precisa ter acesso legítimo aos títulos que joga. O Twinverse não fornece jogos nem licenças.

## ✨ Principais Funcionalidades

- **Layout:** Escolha entre seis moldes por monitor (até quatro jogadores por tela) e arraste os jogadores entre os espaços. No KDE Plasma 6, o KWin posiciona as janelas do Gamescope e o Twinverse restaura as configurações dos painéis ao encerrar a sessão.
- **Controles:** Cada controle físico só pode ser atribuído a um jogador. Os demais veem o número de quem o usa (por exemplo, `01`) e não podem selecioná-lo. O perfil mantém a atribuição mesmo ao desconectar o controle ou reiniciar o aplicativo. A ponte nativa reconecta o mesmo controle até durante a partida.
- **Áudio:** Mantenha **Padrão** ou escolha uma saída PulseAudio/PipeWire por jogador. Vários jogadores podem usar a mesma saída; os números indicam quem mais a selecionou, sem bloquear a escolha.

As listas de controles e monitores se atualizam ao conectar ou desconectar dispositivos; **Atualizar dispositivos** (`F5`) também faz uma busca. Nos menus de controle e áudio, um ponto azul marca a seleção atual. Um ponto amarelo com **(Desconectado)** indica que a seleção foi salva, mas o dispositivo está ausente.

---

[1920x1080-RX_6600_XT-demo](https://github.com/user-attachments/assets/e0ca4937-fd38-48cf-b56c-1c825b047572)

---

## 📦 Requisitos

Instale o **Steam nativo** e o **Bubblewrap** (`bwrap`) no host, mesmo ao usar Flatpak ou AppImage. Sessões em Big Picture com layout por monitor também precisam do [Gamescope e de um driver gráfico compatível](https://github.com/ValveSoftware/gamescope). A seleção de saída de áudio usa `pactl` com PulseAudio ou PipeWire-Pulse. O `pasta` (do pacote `passt`) é opcional; só a [rede isolada](#rede) precisa dele no `PATH` do host.

Seu usuário precisa de acesso a `/dev/input` para os controles e a `/dev/uinput` para o joystick virtual usado na ausência de um controle atribuído. Para conceder acesso pelo grupo `input`, use o comando da sua distribuição e depois saia e entre novamente na sessão do sistema ou reinicie o computador:

```bash
# Maioria das distribuições Linux
sudo usermod -aG input "$USER"

# Bazzite
ujust add-user-to-input-group
```


## 📦 Instalação

Escolha o Flatpak, o AppImage ou o arquivo com o código-fonte da versão **2.0.0-alpha.3** em [Releases](https://github.com/mall0r/Twinverse/releases).

### Flatpak

No diretório em que baixou o pacote:

```bash
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./Twinverse-*.flatpak
flatpak run io.github.mall0r.Twinverse
```

### AppImage

No diretório em que baixou o AppImage:

```bash
chmod +x Twinverse-*.AppImage
./Twinverse-*.AppImage
```

O [Gear Lever](https://github.com/mijorus/gearlever) é opcional para integrar o AppImage ao menu e gerenciar atualizações.

### Executando a Partir do Código-Fonte

Execute `./run.sh` no diretório do código-fonte extraído. O script compila os GResources, instala as dependências Python em `.venv` e tenta compilar os componentes nativos de entrada que faltarem. Sem eles, o Twinverse usa montagens estáticas de dispositivos, sem reconexão pela ponte nem captura exclusiva no host. Veja os [pré-requisitos para compilar em Rust](../CONTRIBUTING.md#rust-toolchain-prerequisites-native-input-libraries).

## 🎮 Iniciar uma sessão

1. Em **Seu grupo**, use **Adicionar Jogador** e marque quem vai jogar. No **Layout da sessão**, escolha um molde com espaço para cada jogador marcado.
2. Selecione cada jogador para abrir a **Configuração do jogador**. Escolha o controle e a saída de áudio. Para transferir um controle, primeiro selecione **Nenhum** para quem o usa. Só um jogador pode ativar **Capturar mouse**.
3. Para cada jogador com o status **Não instalado**, clique em **Instalar Steam**. O Steam abre em modo desktop, sem Gamescope. Entre na conta desse jogador e depois encerre esse cliente Steam. Após a instalação, **Iniciar Jogador** abre apenas esse cliente para ajustes.
4. Quando todos os jogadores marcados estiverem com o status **Pronto**, clique em **Iniciar Sessão** (`Ctrl+Enter`). O Twinverse minimiza a janela quando os clientes estão em execução. **Parar Jogador** encerra um cliente; **Encerrar Sessão** na janela principal encerra todos.

### Encerrar a sessão pelo controle

Pressione **HOME + L3** juntos no **mesmo controle** (HOME/Guia + **clique no analógico esquerdo**). A confirmação abre na hora, sem precisar segurar, com **Cancelar** selecionado. Só o controle que abriu o diálogo pode navegar nele. Enquanto o diálogo está aberto, a ponte nativa suspende a entrada desse controle no Steam e no jogo do jogador; os demais continuam jogando.

Solte os dois botões. Escolha entre esquerda e direita com o direcional ou o analógico esquerdo; **A** ativa a opção selecionada e **B** cancela. As setas, Enter, Esc e cliques do mouse também funcionam. Cancelar devolve o controle sem interromper a partida; confirmar **Encerrar** fecha todas as instâncias do Twinverse e traz a janela principal de volta.

## 📖 Documentação e Guias

- **Guia ilustrado:** [Português BR](https://mall0r.github.io/Twinverse/?lang=pt#step-by-step) | [English](https://mall0r.github.io/Twinverse/#step-by-step)
- **Depuração e logs:** [Português BR](DEBUGGING.pt-br.md) | [English](DEBUGGING.md)

---

## ⚙️ Como Funciona

**Arquivos dos jogadores.** O Bubblewrap monta uma pasta pessoal separada (`home_1`–`home_8`) para cada cliente Steam. Reaproveita as pastas de jogos instalados em `~/.local/share/Steam/steamapps/common/` no host e as versões personalizadas do Proton em `compatibilitytools.d/`; o Twinverse sincroniza os manifestos `.acf` ao iniciar o Steam. Em **Preferências → Dados das instâncias**, é possível abrir a pasta do jogador, iniciar um terminal na sandbox ou redefinir o jogador e apagar essa pasta.

**Isolamento de entrada.** A ponte `twinverse-input-bridge` solicita acesso exclusivo (`EVIOCGRAB`) à entrada evdev do controle atribuído enquanto a instância está em execução. Durante a captura, pressionar HOME não traz o Steam do host para a frente. Encerrar a instância libera o controle; controles não atribuídos não são capturados. As bibliotecas nativas de `uinput` e `libudev` mantêm os controles virtuais do Steam Input dentro da própria instância. Jogadores sem controle atribuído usam um joystick virtual substituto.

### Rede

- **Compartilhada (padrão para novos perfis):** Deixe **Preferências → Motor → Isolar rede** desativado para jogar online e descobrir partidas na LAN. Isso evita conflitos de portas de origem UDP do `pasta`. Portas de loopback separadas para o Steam3Master encaminham a entrada ao cliente correto. Cada cliente também informa um IP privado distinto no login do Steam para evitar “Session Replaced”; isso **não** cria outro endereço na LAN.
- **Isolada (opcional):** Para jogos em LAN ou servidores dedicados que exigem IPs locais distintos, ative **Isolar rede** para a próxima inicialização. Com o `pasta` instalado no host, cada instância recebe um namespace de rede. Deixe **IP convidado** em branco para buscar um IPv4 livre na sub-rede do host ou informe um endereço disponível. Desativar o isolamento desabilita o campo sem apagar o valor. Sem o `pasta`, as instâncias continuam compartilhando a rede do host.

---

## 🛠️ Para Desenvolvedores

Se deseja contribuir com o Twinverse, consulte [CONTRIBUTING.md](../CONTRIBUTING.md) para instruções de ambiente, fluxo de trabalho e padrões de código.

---

## 📜 Licença

Este projeto está licenciado sob a **Licença Pública Geral GNU v3.0 (GPL-3.0-or-later)**. Veja [LICENSE](../LICENSE) para detalhes.

> [!NOTE]
> ## Aviso Legal
>
> O Twinverse é um projeto independente de código aberto e não é afiliado, endossado ou oficialmente conectado à Valve Corporation ou ao Steam.
>
> O Twinverse inicia o cliente oficial do Steam sem modificar seus binários. Os jogadores são responsáveis por cumprir o [Acordo de Assinante do Steam](https://store.steampowered.com/subscriber_agreement/).

---

## 🙏 Créditos

Este projeto foi inspirado pelo trabalho de:

- [NaviVani-dev](https://github.com/NaviVani-dev) e seu script [dualscope.sh](https://gist.github.com/NaviVani-dev/9a8a704a31313fd5ed5fa68babf7bc3a).
- [Tau5](https://github.com/Tau5) e seu projeto [Co-op-on-Linux](https://github.com/Tau5/Co-op-on-Linux).
- [wunnr](https://github.com/wunnr) e seu projeto [Partydeck](https://github.com/wunnr/partydeck) (recomendado caso você procure uma abordagem mais próxima ao [Nucleus Co-op](https://github.com/SplitScreen-Me/splitscreenme-nucleus)).
