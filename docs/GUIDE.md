# MultiScope Guide

Welcome to the MultiScope guide! This document will walk you through the process of setting up and using the MultiScope application to run multiple Steam instances.

[IMAGE]

## 1. Number of Instances

First, you need to decide how many Steam instances you want to run. MultiScope supports up to 8 instances total.

- **Splitscreen:** You can run a maximum of 4 instances per monitor.
- **Fullscreen:** You can run a maximum of 1 instance per monitor.

Use the numeric selector "Number of Instances" to set the desired amount.

[IMAGE]

## 2. Screen Mode

You can choose between two screen modes:

- **Fullscreen:** Each instance will run on a separate monitor.
- **Splitscreen:** Instances will be arranged on a single monitor, either horizontally or vertically.

### Splitscreen Options

When selecting "Splitscreen," you can choose between two orientations:

- **Horizontal:** Instances are arranged side by side.
- **Vertical:** Instances are arranged stacked on top of each other.

Positions and layouts adjust automatically based on the number of instances.

Note: Instance auto-tiling only works with KDE Plasma environments.

[IMAGE]

## 3. Instance Configuration

For each instance, you can configure the following options:

- **Gamepad:** Assign a specific controller to the instance.
- **Capture Mouse & Keyboard:** Dedicate the mouse and keyboard to a single instance. For now, only one instance at a time can use the mouse and keyboard.
- **Audio Device:** Select a specific audio output device for the instance.
- **Refresh Rate:** Set the refresh rate for the instance. Useful if you want to cap FPS or use a specific refresh rate.

[IMAGE]

## 4. Starting an Instance

After configuring an instance, click the **"Start"** button next to it to launch an isolated Steam instance without gamescope. The first time, Steam will be installed automatically — this process may take a few minutes.

Each instance can be started individually via its **"Start"** button. To run multiple instances at once, use the **"Play"** button located at the bottom of the window.

Only instances that already have Steam installed can be launched with the **"Play"** button. You can verify this by the checkmark icon on the instance. If the icon is not present, install Steam by clicking that instance's **"Start"** button. This allows for quick and direct configuration, game, or application setup for a specific instance.

[IMAGE]

## 5. Steam Big Picture Mode

For the best experience, it is recommended to enable "Big Picture Mode" in Steam's settings. This provides a controller-friendly interface, ideal for MultiScope.

To do this, go to `Settings > Interface` and check the box for "Start Steam in Big Picture Mode."

Repeat this process for all instances you wish to start in Big Picture Mode.

[IMAGE]

## 6. Play

When all your instances are configured and running, you can start playing! Each instance will have its own dedicated input and audio devices, allowing you to play with your friends or family on the same computer.

Enjoy your gaming session!

[IMAGE]

## 7. Applications (Optional)

To add applications to your instance, go to `Add a Game` and click "Add a Non-Steam Game...". Select the application you wish to add.

### Why do this?

This allows you to run applications directly from the instance, enabling a unique configuration per instance for that application. This is because each instance has its own unique HOME directory. They can be found at `~/.local/share/multiscope/home_{n}`.

A good example is [mangojuice](https://github.com/radiolamp/mangojuice); if you want to use it with custom settings, you will need to run and configure it for each instance individually.

[IMAGE]
