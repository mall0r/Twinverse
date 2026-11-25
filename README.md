<p align="right">
  <a href="https://mall0r.github.io/Twinverse/"><img src="https://img.shields.io/badge/Docs-GitHub%20Pages-1f6feb.svg?logo=githubpages&logoColor=white" alt="Interactive Documentation"/></a>
  <a href="README.md"><img src="https://img.shields.io/badge/en-US-darkblue.svg" alt="English"/></a>
  <a href="docs/README.pt-br.md"><img src="https://img.shields.io/badge/pt-BR-darkgreen.svg" alt="Portuguese"/></a>
</p>

<p align="center">
  <img src="share/icons/hicolor/scalable/apps/io.github.mall0r.Twinverse.svg" alt="Twinverse Logo" width="160" height="160">
</p>

<p align="center">
  <a href="https://github.com/mall0r/Twinverse/releases"><img src="https://img.shields.io/badge/Version-2.0.0--alpha.3-blue.svg" alt="Version"/></a>
  <a href="https://mall0r.github.io/Twinverse/"><img src="https://img.shields.io/badge/Documentation-Live-84b4fa.svg" alt="Documentation"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-green.svg" alt="License"/></a>
  <a href="https://www.gtk.org/"><img src="https://img.shields.io/badge/GTK-4-orange.svg" alt="GTK Version"/></a>
  <a href="https://gnome.pages.gitlab.gnome.org/libadwaita/"><img src="https://img.shields.io/badge/libadwaita-1-purple.svg" alt="libadwaita Version"/></a>
</p>

<p align="center">
  <a href="https://www.python.org" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://www.rust-lang.org/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust"/></a>
  <a href="https://www.gnu.org/software/bash/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Shell-4EAA25?style=for-the-badge&logo=gnu-bash&logoColor=white" alt="Shell"/></a>
  <a href="https://www.javascript.com/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript"/></a>
  <a href="https://www.w3.org/Style/CSS/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/CSS3-66309A?style=for-the-badge&logo=css3&logoColor=white" alt="CSS"/></a>
</p>

# What is Twinverse?

**Twinverse** runs up to **8 Steam clients on one Linux PC**. Each player has a separate Steam home and can play the same game as the others or a different one. Gamescope displays Steam Big Picture in split screen or across monitors. By default, the instances **share the host network**.

> [!TIP]
> See the [illustrated walkthrough](https://mall0r.github.io/Twinverse/#step-by-step) for screenshots of the setup.

<p align="center">
  <img alt="Twinverse" src="share/screenshots/twinverse-session-dark.png" />
</p>

> [!WARNING]
> Each player needs legitimate access to the games they play. Twinverse does not provide games or licenses.

## ✨ Key Features

- **Layout:** Choose from six templates per monitor (up to four players per display) and drag players between spaces. On KDE Plasma 6, KWin places the Gamescope windows and Twinverse restores the panel settings when the session ends.
- **Controllers:** A physical pad belongs to one player. Other players see its owner's number (e.g. `01`) and cannot select it. The profile remembers the assignment across disconnects and restarts. The native bridge reconnects the same pad even mid-session.
- **Audio:** Choose **Default** or a PulseAudio/PipeWire output per player. Several players can use the same output; number badges show who else has selected it without blocking selection.

Controller and monitor lists refresh automatically on plug or unplug; **Refresh devices** (`F5`) also rescans them. In the controller and audio menus, a blue dot marks the current selection. A yellow dot and **(Disconnected)** mean the selection is saved but the device is absent.

---

[1920x1080-RX_6600_XT-demo](https://github.com/user-attachments/assets/e0ca4937-fd38-48cf-b56c-1c825b047572)

---

## 📦 Requirements

Install **native Steam** and **Bubblewrap** (`bwrap`) on the host, even when using Flatpak or AppImage. Tiled Big Picture sessions also need [Gamescope and a compatible graphics driver](https://github.com/ValveSoftware/gamescope). Audio output selection uses `pactl` with PulseAudio or PipeWire-Pulse. `pasta` (from `passt`) is optional; only [isolated networking](#networking) needs it on the host `PATH`.

Your user needs access to `/dev/input` for controllers and to `/dev/uinput` for the placeholder joystick. To grant access via the `input` group, use the command for your distribution, then sign out and back in or reboot:

```bash
# Most Linux distributions
sudo usermod -aG input "$USER"

# Bazzite
ujust add-user-to-input-group
```


## 📦 Installation

Choose the Flatpak, AppImage or source archive for **2.0.0-alpha.3** from [Releases](https://github.com/mall0r/Twinverse/releases).

### Flatpak

From the directory containing the downloaded bundle:

```bash
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./Twinverse-*.flatpak
flatpak run io.github.mall0r.Twinverse
```

### AppImage

From the directory containing the downloaded AppImage:

```bash
chmod +x Twinverse-*.AppImage
./Twinverse-*.AppImage
```

[Gear Lever](https://github.com/mijorus/gearlever) is optional for AppImage menu integration and updates.

### Running from Source

Run `./run.sh` from the extracted source directory. It compiles GResources, installs Python dependencies in `.venv` and tries to build any missing native input components. Without them, Twinverse falls back to static device mounts without bridge hotplug or exclusive host capture. See the [Rust build prerequisites](CONTRIBUTING.md#rust-toolchain-prerequisites-native-input-libraries).

## 🎮 Start a session

1. In **Your party**, add players with **Add Player** and check those who will play. In **Session Layout**, choose a template with a space for every checked player.
2. Select each player to open **Player Setup**. Choose their controller and audio output. To move a pad to someone else, first choose **None** for its current owner. Only one player can enable **Grab mouse**.
3. For each player marked **Not installed**, click **Install Steam**. Steam opens in desktop mode without Gamescope. Sign in to that player's account, then exit that Steam client. Once installed, **Start Player** opens just that client for setup.
4. When all checked players are **Ready**, click **Launch Session** (`Ctrl+Enter`). Twinverse minimizes after their clients are running. **Stop Player** stops one client; **End Session** in the main window stops them all.

### End a session from a controller

Press **HOME + L3** together on the **same controller** (HOME/Guide + **click the left stick**). The confirmation opens immediately, without a long press, with **Cancel** selected. Only the controller that opened it can navigate it. While it is open, the native bridge pauses that pad's input to its Steam client and game; other players keep control.

Release both buttons. Choose left or right with the D-pad or left stick; **A** activates the selected option and **B** cancels. Arrow keys, Enter, Esc and mouse clicks also work. Cancelling returns control without stopping play; confirming **End Session** closes all Twinverse instances and brings back the main window.

## 📖 Documentation & Guides

- **Illustrated guide:** [English](https://mall0r.github.io/Twinverse/#step-by-step) | [Português BR](https://mall0r.github.io/Twinverse/?lang=pt#step-by-step)
- **Debugging & logs:** [English](docs/DEBUGGING.md) | [Português BR](docs/DEBUGGING.pt-br.md)

---

## ⚙️ How It Works

**Player files.** Bubblewrap mounts a separate home (`home_1`–`home_8`) for each Steam client. It reuses installed game folders from the host's `~/.local/share/Steam/steamapps/common/` and custom Proton builds from `compatibilitytools.d/`; Twinverse syncs `.acf` manifests at Steam launch. Under **Preferences → Instance data** you can open a player's folder, launch a sandboxed terminal, or reset the player and delete that home.

**Input isolation.** `twinverse-input-bridge` requests exclusive access (`EVIOCGRAB`) to the assigned pad's evdev input while its instance runs. While grabbed, pressing HOME does not bring host Steam to the front. Stopping the instance releases the pad; unassigned pads are not grabbed. Native `uinput` and `libudev` shims keep Steam Input's virtual controllers inside their instance. A player with no assigned pad uses a placeholder virtual joystick instead.

### Networking

- **Shared (default for new profiles):** Leave **Preferences → Engine → Isolate network** off for online multiplayer and LAN discovery. This avoids `pasta` UDP source-port conflicts. Separate Steam3Master loopback ports keep controller input routed to the right client. Each client also reports a distinct private IP at Steam login to avoid “Session Replaced”; this is **not** another LAN address.
- **Isolated (opt-in):** For LAN games or dedicated servers that need distinct local IPs, enable **Isolate network** for the next launch. With `pasta` installed on the host, each instance gets a network namespace. Leave **Guest IP** blank to look for a free IPv4 in the host subnet, or enter an unused address. Turning isolation off disables the field without erasing it. If `pasta` is missing, instances still share the host network.

---

## 🛠️ For Developers

If you wish to contribute to Twinverse, please refer to [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, workflows, and code standards.

---

## 📜 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0-or-later)**. See [LICENSE](LICENSE) for details.

> [!NOTE]
> ## Legal Disclaimer
>
> Twinverse is an independent open-source project and is not affiliated with, endorsed by, or in any way officially connected to Valve Corporation or Steam.
>
> Twinverse launches the official Steam client without patching its binaries. Players are responsible for complying with the [Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/).

---

## 🙏 Credits

This project was inspired by the work of:

- [NaviVani-dev](https://github.com/NaviVani-dev) and their script [dualscope.sh](https://gist.github.com/NaviVani-dev/9a8a704a31313fd5ed5fa68babf7bc3a).
- [Tau5](https://github.com/Tau5) and their project [Co-op-on-Linux](https://github.com/Tau5/Co-op-on-Linux).
- [wunnr](https://github.com/wunnr) and their project [Partydeck](https://github.com/wunnr/partydeck) (recommended if you're looking for an approach closer to [Nucleus Co-op](https://github.com/SplitScreen-Me/splitscreenme-nucleus)).
