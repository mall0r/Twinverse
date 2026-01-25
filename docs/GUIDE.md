<p align="right">
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.md"><img src="https://img.shields.io/badge/EN-🇬🇧-darkblue.svg" alt="English"/></a>
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.pt-br.md"><img src="https://img.shields.io/badge/PT-🇧🇷-darkgreen.svg" alt="Portuguese"/></a>
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.es.md"><img src="https://img.shields.io/badge/ES-🇪🇸-darkred.svg" alt="Spanish"/></a>
</p>

# Twinverse Guide

Welcome to the Twinverse guide! This document will walk you through the process of setting up and using the Twinverse application to run multiple Steam instances.

## 1. Number of Instances

First, you need to decide how many Steam instances you want to run. Twinverse supports up to 8 instances total.

- **Splitscreen:** You can run a maximum of 4 instances per monitor.
- **Fullscreen:** You can run a maximum of 1 instance per monitor.

Use the numeric selector "Number of Instances" to set the desired amount.

<img width="708" height="127" alt="general-layout" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/general-layout.png" />

## 2. Screen Mode

> [!NOTE]
> For window auto-tiling to work properly, it is recommended to use KDE Plasma 6.0+.
> In other DEs, you will need to move the windows yourself, everything else should work fine.

You can choose between two screen modes:

- **Fullscreen:** Each instance will run on a separate monitor.
- **Splitscreen:** Instances will be arranged on a single monitor, either horizontally or vertically.

<img width="708" height="204" alt="screen-settings" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/screen-settings.png" />

### Splitscreen Options

When selecting "Splitscreen," you can choose between two orientations:

- **Horizontal:** Instances are arranged stacked on top of each other.
- **Vertical:** Instances are arranged side by side.

Positions and layouts adjust automatically based on the number of instances.
You can see a preview of the layout by clicking the icon <img width="32" height="32" alt="fullscreen-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/fullscreen-square-symbolic.svg" /> on the left in Screen Settings.

<img width="32" height="32" alt="horizontal-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/horizontal-square-symbolic.svg" />
<img width="1280" height="720" alt="horizontal-game" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/horizontal-game.png" />
<img width="32" height="32" alt="vertical-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/vertical-square-symbolic.svg" />
<img width="1280" height="720" alt="vertical-game" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/vertical-game.png" />

## 3. Instance Configuration

> [!IMPORTANT]
> To use Twinverse, it's necessary to add your user to the `input` group to allow the program to manage input devices.
> ```bash
> sudo usermod -aG input $USER
> ```
> in the Bazzite:
> ```bash
> ujust add-user-to-input-group
> ```
> **Restart the system for the changes to take effect.**

For each instance, you can configure the following options:

- **Gamepad:** Assign a specific controller to the instance.
- **Capture Mouse:** Dedicate the mouse to a single instance. For now, only one instance at a time can use the mouse and keyboard.
- **Audio Device:** Select a specific audio output device for the instance.
- **Refresh Rate:** Set the refresh rate for the instance. Useful if you want to cap FPS or use a specific refresh rate.
- **Environment Variables:** Define specific environment variables for the instance.

<img width="595" height="409" alt="player-config" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/player-config.png" />

## 4. Starting an Instance

After setting up an instance, click the **"Start"** button next to it to launch a Steam instance in desktop mode. The first time, the Steam Client will be downloaded and installed automatically — this process may take a few minutes.

You must log in to desktop mode. After logging in and configuring your Steam Client, simply close the instance.

The **"Play"** button runs all selected instances, and with a checkmark, it will run them all with the gamescope and resize each one.

If you are using KDE Plasma, it will also automatically move them to ideally split the screen for your main monitor, or move them between your monitors if you have selected fullscreen.

Only instances that already have Steam installed can be started with **"Play"**. You can verify this by the check icon <img width="16" height="16" alt="check-icon" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/check-icon.svg" /> on the instance. If the icon is an <img width="16" height="16" alt="alert-icon" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/alert-icon.svg" />, install Steam by clicking the **"Install"** button on that instance.

<img width="651" height="178" alt="instance-config" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/instance-config.png" />

## 5. Disable Shader Pre-Caching (Optional)

To save disk space, disable shader pre-caching on Steam. I also recommend doing this if you have any problems with pre-caching downloads.

To do this, go to `Settings > Downloads` and disable the `Enable shader pre-caching` option.

<img width="850" height="722" alt="disable-shader-pre_caching" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/disable-shader-pre_caching.png" />

## 6. Play

When all your instances are configured and running, you can start playing! Each instance will have its own dedicated input and audio devices, allowing you to play with your friends or family on the same computer.

Enjoy your gaming session!

## Keyboard shortcuts:
```
Super + F      Toggle fullscreen
```
```
Super + N      Toggle nearest neighbour filtering
```
```
Super + U      Toggle FSR upscaling
```
```
Super + Y      Toggle NIS upscaling
```
```
Super + I      Increase FSR sharpness by 1
```
```
Super + O      Decrease FSR sharpness by 1
```
```
Super + S      Take a screenshot
```
```
Super + G      Toggle keyboard grab
```
# Optional

## Multi GPU Support

> [!NOTE]
> This should be added directly to the game's arguments, do not add it to the environment variables.

Twinverse supports running multiple games on different GPUs.

Add the following line to your game's Steam arguments:

```bash
DRI_PRIME=1!

```

This makes GPU 1 be used in the game. You can adjust the numbers according to your system configuration.

## Home Directories

You can delete or manage the files in the home directory of each instance by accessing `Preferences` -> `Instances`.

<img alt="preferences-instances" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/preferences-instances.png" />
