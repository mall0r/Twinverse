
# Changelog

All notable changes to this project will be documented in this file. This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

## [1.1.2] - 2026-10-01

### Fixed

- Restore controller navigation of the Steam side menus while a game is running in splitscreen instances.
- Build the AppImage in an Ubuntu 22.04 container that compiles its own GTK 4.16, libadwaita 1.6 and GLib 2.82 stack, instead of copying the libraries of the build workstation.
- Reject the AppImage when a bundled library requires a newer glibc than 2.35.

### Changed

- Verify in CI that the AppImage opens a window on Ubuntu 22.04 and Ubuntu 24.04 before it is attached to a release.
- Publish the Flatpak and the AppImage from separate CI jobs.

## [1.1.1] - 2026-10-01

### Fixed

- Restore Steam performance-menu control of MangoApp using a shared configuration file per instance.
- Prevent duplicated overlay elements by removing inline MangoHud configuration in native and Flatpak launches.
