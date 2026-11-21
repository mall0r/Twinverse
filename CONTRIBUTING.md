# Twinverse Contributing Guide

Want to help out with the project? We'd love it! There are lots of different ways that you can help, whether it is developing game handlers, contributing to the project codebase, or simply a donation - all are appreciated.


## Issue Contribution

If you encounter an issue while using Twinverse, or have an idea for a new feature, you can [create an issue](https://github.com/mall0r/Twinverse/issues/new/choose). This will take you to a selection page where you can choose the most relevant template for your issue. We are always open to suggestions!


## Security Note

If you identify a security issue in the code of Twinverse, please do not post a public issue identifying the security threat. This potentially highlights the issue for malicious users to take advantage of the vulnerability.

Alternatively you can [create a repository security advisory](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/creating-a-repository-security-advisory)


## Working on the Source Code

If you would like to contribute to the codebase of Twinverse as a developer, we would love to have you! Here are some helpful guidelines to make the process go as smoothly as possible!


### The Process

1.	**Fork the main branch** and clone it into your own development environment. As of right now, the “main” branch is the primary, active branch of the project.

2.	**Work on your changes**. Make sure to check for updates to the main branch before you create a pull request to avoid unnecessary code conflicts.

3.	[**Create a pull request**](https://github.com/mall0r/Twinverse/pulls) once you are done with your changes! Please verify that your fork is caught up with the main branch beforehand.

4.	**Your code will be reviewed**, and changes may be requested. Address any issues and repeat as necessary until your change is accepted!

5.	**Done!** Once your code is reviewed and accepted, it will be merged into the codebase of the project! Congratulations! You should see your changes in the next release build!

Check out the official GitHub articles to learn more about [forking](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo), [cloning](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository), and [pull requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).


### Getting Started

#### What is the Project's Tech Stack?

Twinverse is built for Linux and SteamOS systems using two main layers:

- **Desktop Application (Python 3 + GTK 4 + libadwaita):** Built with PyGObject bindings and libadwaita for the modern GNOME-style Session Studio interface, profile management, process supervision, and KWin D-Bus integration.
- **Native Input Isolation Workspace (`native/`, pure Rust):** A zero-external-dependency Cargo workspace targeting `GLIBC <= 2.35` on both 64-bit (`x86_64-unknown-linux-gnu`) and 32-bit (`i686-unknown-linux-gnu`, required for Steam's 32-bit client alongside 64-bit games):
  - `twinverse-uinput-proto` — shared Unix-socket wire protocol and environment constants.
  - `twinverse-uinput-interposer` (`libtwinverse_uinput.so`) — userspace `/dev/uinput`, `/dev/input/event*`, and dynamic `/dev/hidraw*` interposer keeping Steam Input virtual controllers private to each instance.
  - `twinverse-udev-shim` (`libtwinverse_udev.so`) — `libudev` shim synthesizing virtual evdev devices and hotplug `hidraw` events inside the sandbox.
  - `twinverse-input-bridge` — host-side supervisor that bridges physical controllers over Unix sockets, isolates identical sibling gamepads, updates dynamic `/dev/hidraw*` allowlists, and reconnects controllers on unplug/replug.

On the host, **Gamescope**, **Bubblewrap (`bwrap`)**, and optionally **`pasta`** (`passt`) handle display virtualization, filesystem/process sandboxing, and rootless per-instance networking respectively.

#### Rust Toolchain Prerequisites (Native Input Libraries)

To compile the native Rust libraries locally (for full isolated Steam Input and controller hotplug reconnection), install `rustc`/`cargo`, the 32-bit Rust target, and 32-bit C multilib linking support:

```bash
rustup target add x86_64-unknown-linux-gnu i686-unknown-linux-gnu
# Plus your distro's 32-bit multilib C runtime (e.g., gcc-multilib on Debian/Ubuntu,
# glibc-devel.i686 + libgcc.i686 on Fedora, lib32-glibc + gcc-multilib on Arch).
```

To build only the native artifacts into `res/native/`:

```bash
make build-native
# Or directly:
./scripts/build-native.sh
```


### Running, Testing, and Packaging Changes

When you are ready to test any changes you make, you can run **Twinverse** directly using the run script from the project root directory:

```bash
./run.sh
```

This script compiles the GResource files, builds the native Rust libraries (if `cargo` is available), creates a virtual environment if needed, installs dependencies, and runs the application directly from source. This is the quickest way to test your changes during development.

> [!IMPORTANT]
> Your project path should not contain folders with spaces in their name, otherwise Twinverse may not run correctly.

For testing your changes, first ensure you have the development dependencies installed and virtual environment set up:

```bash
make dev
```

Or, if you prefer to do it manually in your terminal, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

This will create a virtual environment (if it doesn't exist), install all necessary dependencies, and set up pre-commit hooks.

Then run the comprehensive test suite using:

```bash
make test
```

This runs the native Rust unit tests (`./scripts/build-native.sh --test`), the Python `pytest` suite, and all `pre-commit` hooks to ensure code quality.

For cleaning up build artifacts, cached files, and temporary directories, you can use:

```bash
make clean
```

> [!IMPORTANT]
> The `make clean` command will remove all temporary files, build artifacts, virtual environments, and cached data. This includes the `.venv` directory, `__pycache__` directories, and build outputs. Only use this if you want to completely reset your development environment.

- For native Rust libraries only: `make build-native`
- For Flatpak (primary distribution format): `make flatpak` (automatically sets up the development environment if needed)
- For AppImage: `make appimage` (builds inside an Ubuntu 22.04 Podman/Docker container)
- For a local install in `.venv` (including native libraries): `make build`

As a reminder, please take care to follow the [Code Standards](#code-standards) for the project when adding any code-based contributions.

Test your changes **thoroughly** before submitting a Pull Request. Whenever appropriate, it is strongly recommended that you develop unit-tests with a good test spread to make sure that your new features are working as intended and are capable of handling anticipated edge cases. In cases where this is not possible, please be sure to follow a similar testing paradigm where both average and edge use cases are tested. In the long run, this will save the project a lot of time, avoiding tedious backtracking and bug-smashing by proactively ensuring that easily preventable bugs don't sneak into the main build.

### Building from Source

Twinverse provides a Makefile to manage builds and versioning. For more details, use:

```bash
make help
```

### Packaging an AppImage

The `scripts/package-appimage.sh` script builds in an Ubuntu 22.04 container using Podman or Docker. Inside the container, it compiles the 64-bit and 32-bit native Rust libraries, bundles the Python runtime and GTK 4 / libadwaita dependencies with PyInstaller and linuxdeploy (targeting `GLIBC <= 2.35`), and verifies symbolic icon rendering with the Rust helper `scripts/appimage/check-appearance.rs`.

```bash
make appimage
```

Or using the script directly:

```bash
./scripts/package-appimage.sh
```

The build produces `Twinverse-<version>-x86_64.AppImage` and its `.AppImage.zsync`
file. Update metadata embedded in the AppImage lets AppImageUpdate and compatible
tools find the latest stable release in `mall0r/Twinverse`:

```text
gh-releases-zsync|mall0r|Twinverse|latest|Twinverse-*-x86_64.AppImage.zsync
```

Publish both files as assets of the same GitHub release, keeping their generated
names. The tag workflow uploads both automatically. The build checks that the
`.zsync` file exists and the embedded metadata matches. To inspect it manually:

```bash
./Twinverse-<version>-x86_64.AppImage --appimage-updateinformation
```

Previously distributed AppImages without this metadata require a one-time manual
download of a new build before update tools can discover future releases.

### Packaging a Flatpak

The `scripts/package-flatpak.sh` script automates building and packaging the Flatpak into a `.flatpak` bundle, including compiling the 64-bit and 32-bit native Rust libraries inside the Flatpak SDK (`org.freedesktop.Sdk.Extension.rust-stable`, `org.freedesktop.Sdk.Compat.i386`, and `org.freedesktop.Sdk.Extension.toolchain-i386`, installed automatically by `flatpak-builder --install-deps-from=flathub`).

```bash
make flatpak
```

Or using the script directly:

```bash
./scripts/package-flatpak.sh
```

### Submitting Changes

#### Create a Pull Request
Once you have finished building and testing your changes, it's time to submit them! From the /mall0r/Twinverse repository, go to the Pull Requests section and click the "New Pull Request" button.

**Make sure that the _base_ repository is set to "/mall0r/Twinverse"!**

Otherwise, you will be attempting to merge your changes with a different repository. Double-check that you will be merging with the correct head branch as well (generally "main").

It is a good idea to create a detailed (but concise) comment to accompany the initial pull request to explain:
* The issue the pull request is addressing
* What is changed
* Testing procedures used and their results
* Potential issues or challenges encountered
* Any questions or other comments for contribution reviewers

#### Review Process

Before approving changes, reviewers will make sure that:
* Changes do not interfere with existing features or design plans
* There are no overlap issues (i.e. other developers are already assigned to it)
* Sufficient testing occurred
* Quality standards are upheld

While it is certainly _possible_ that a quality pull request might be accepted right away, change requests, questions, and discussions should be expected before the pull request can be merged. Discussions around the pull request should preferably be held in the pull request comments. This way it is easy for multiple people to follow progress... but do not hesitate to reach out directly to the developers and maintainers either!


### Implementing Changes

#### Approval
Once the review process is complete and approved, the pull request will be merged into the "main" branch, incorporating all the changes present in the request.

At this point, the contributor's work is complete! If your pull request has reached this point, congratulations! Your contribution is now part of the project!
Thank you for contributing!

#### Release Builds
Periodically, the current lead developer(s) of Twinverse will decide when enough changes have been incorporated into the main branch to justify a new release. To ensure build stability, a release will be created and published alongside a change log of implemented changes after sufficient testing by maintainers. The releases include the source code and packages in flatpak and appimage formats.

Currently, there is no set release schedule, and releases will be published when ready and verified stable.

### Code Standards
* When in doubt, structure your code to prioritize readability!
* Comment large blocks of abstract code with concise descriptions.
* Use type hints wherever possible to improve code maintainability.
* Keep the `native/` Rust workspace free of external Cargo dependencies and compatible with `GLIBC <= 2.35`.
* Follow the existing code structure and naming conventions in the project.
* Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification and [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) when creating commits and proposing changes.

## Donations
If you would like to contribute financially to support the project, check out the links under the "Sponsor this Project" section of the [repository homepage](https://github.com/mall0r/Twinverse), or select one of the options below.
<p align="center">
  <a href="https://ko-fi.com/mallor" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white" alt="Ko-fi"/></a>
  <a href="https://github.com/sponsors/mall0r" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/GitHub%20Sponsors-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="GitHub Sponsors"/></a>
</p>

Donations are always appreciated, but completely voluntary!
