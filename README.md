[English](./README.md) | [Português (Brasil)](./docs/README.pt-br.md) | [Français](./docs/README.fr.md) | [Español](./docs/README.es.md)

# MultiScope

**MultiScope** is an open-source tool for Linux that enables the creation and management of multiple gamescope instances, allowing several players to play simultaneously on a single computer.

---

## Project Status

MultiScope is currently under active development but is already fully functional for users with **AMD graphics cards**. Tests on **NVIDIA** hardware have not yet been conducted, so compatibility is not guaranteed.

- **Compatibility:**
  - ✅ **AMD:** Fully compatible
  - ⚠️ **NVIDIA:** Requires testing
  - ⚠️ **Intel:** Requires testing

## The Problem MultiScope Solves

Many gamers who switch to Linux miss tools like **Nucleus Coop**, which facilitate local multiplayer in games that do not natively support it. MultiScope was created to fill this gap, offering a robust and easy-to-use solution for friends and family to play together on the same PC, even if they don't have multiple computers.

## Features

- **Profile Management:** Create, edit, and remove profiles for different games and configurations.
- **User-Friendly GUI:** An intuitive interface to manage game profiles and instances.
- **Multi-Screen Support:** Configure each game instance to run on a specific screen.
- **Audio Settings:** Direct the audio of each instance to different output devices.
- **Multiple Keyboards and Mice Support:** Assign specific input devices to each player.

## Demonstration

*(Placeholder for screenshots, GIFs, or videos of MultiScope in action. To add an image, use the following syntax:)*
`![Image Description](IMAGE_URL)`

## Installation

The easiest way to install MultiScope is by using the release package, which handles everything for you.

1.  **Download the latest release:**
    Go to the [Releases](https://github.com/Mallor705/MultiScope/releases) page and download the `MultiScope.tar.gz` file.

2.  **Extract the archive:**
    ```bash
    tar -xzvf MultiScope.tar.gz
    ```

3.  **Navigate into the extracted folder:**
    (The folder name may vary depending on the release version)
    ```bash
    cd MultiScope-*
    ```

4.  **Run the installation script:**
    ```bash
    ./install.sh
    ```

After installation, you can find MultiScope in your system's application menu or run it from the terminal with the command `multi-scope gui`. The package also includes an `uninstall.sh` script to remove the application.

## How to Use

1.  **Open MultiScope:** Launch the application from the applications menu or the terminal.
2.  **Create a Profile:**
    - Click "Add Profile".
    - Name the profile (e.g., "Stardew Valley - Player 1").
    - Configure the screen, audio, and input device options.
    - Save the profile.
3.  **Launch a Game:**
    - Select the desired profile.
    - Click "Start" to open the game with the defined settings.

## Building from Source

If you are a developer and wish to compile the project manually, follow the steps below:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Mallor705/MultiScope.git
    cd MultiScope
    ```

2.  **To run directly from source:**
    - Create and activate a virtual environment:
      ```bash
      python3 -m venv .venv
      source .venv/bin/activate
      ```
    - Install the dependencies:
      ```bash
      pip install -r requirements.txt
      ```
    - Run the application:
      ```bash
      ./run.sh
      ```
    
3.  **To build and install from source:**
    ```bash
    ./build.sh
    ./install.sh
    ```

## How to Contribute

We appreciate your interest in contributing to MultiScope! If you wish to help, please follow these guidelines:

1.  **Fork the Repository:** Create a copy of the project in your GitHub account.
2.  **Create a Branch:** Create a branch for your new feature or fix (`git checkout -b my-feature`).
3.  **Make Your Changes:** Implement your improvements or fixes.
4.  **Submit a Pull Request:** Open a Pull Request detailing your changes.

All contributions are welcome, from bug fixes to the implementation of new features.

## License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. For more details, see the [LICENSE](LICENSE) file.
