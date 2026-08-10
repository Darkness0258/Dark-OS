# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DarkOS is an original, AI-first Linux OS.

## Build System & Commands

Detailed build pipeline information and commands for building, running, and verifying the ISO.

### Commands

*   **Build ISO locally:** `sudo bash build-iso.sh`
*   **Run built ISO in VM:** `qemu-system-x86_64 -cdrom out/darkos-*.iso -m 4096 -enable-kvm`
*   **Syntax-check shell script:** `bash -n <file>`
*   **Syntax-check Python script:** `python -m py_compile <file>`
*   **Trigger CI build:** Push to `main` or run `workflow_dispatch`.

## Code Architecture and Structure

High-level overview of the DarkOS architecture.

### Tech Stack

*   Arch base (pacman + AUR)
*   BlackArch (opt-in tool groups)
*   Hyprland (Wayland compositor)
*   Calamares installer

### AI Control Mechanism

AI control is managed via D-Bus + `hyprctl` at the OS level, AT-SPI for in-app control, and screen understanding through periodic screenshots + vision models. Raw input injection (xdotool/spoofing) is explicitly not used.

### Application Strategy

The system features approximately 27 native applications, with most of the roughly 90 features organized as tabs within central hubs. "Settings" is presented as a single application with multiple tabs.

### Key Directories

*   `airootfs/`: Contains the root filesystem for the ISO.
*   `airootfs/usr/local/bin/`: Location for runtime scripts.
*   `ci/`: Continuous Integration scripts.
*   `out/`: Build output directory.

## Linting, Formatting, and Testing

*   **Linting/Formatting:** No specific configuration files for linting or formatting were found in the codebase.
*   **Testing:** The project explicitly states "There are no unit tests — correctness is enforced at build time". Syntax checks for shell and Python scripts are integrated into the build process.

## Current Project Status

*   **Phase 1 (bootable foundation) is complete:** CI publishes ISOs.
*   **Phase 2 (core shell chrome) is active:** `darkos-shell.py` provides the dock/HUD overlay.
*   **Phase 3 (AI assistant) is upcoming:** The AI backend is not yet wired.
*   **Installed-system boot:** Still unverified, with checks focused on `/boot/grub/install.log` and successful login.
