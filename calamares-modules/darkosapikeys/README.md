# DarkOS Calamares API-key module

This directory is an out-of-tree Qt 6 view module for the exact Calamares
3.4.2 ABI used by DarkOS. The installer page accepts optional OpenRouter and
Groq API keys and returns a private C++ job that writes the installed user's
`~/.config/darkos/env` file.

## Step-0 mechanism confirmation (2026-08-25)

The source inspected was the exact archive pinned by `ci/build-calamares.sh`:

```text
URL: https://codeberg.org/Calamares/calamares/releases/download/v3.4.2/calamares-3.4.2.tar.gz
bytes: 4940632
SHA-256: 733bbbb00dc9f84874bd5c22960952f317ea2537565431179fa2152b2fbfdccc
AUR revision: 167151beb537c06cb75c8dbfd409799ba308bb66
package identity: calamares 3.4.2-2
```

Calamares 3.4.2 deliberately installs an external-module SDK:

- root `CMakeLists.txt:693-725` installs `CalamaresConfig.cmake`, exported
  targets, and `CalamaresAddPlugin.cmake`;
- `CalamaresConfig.cmake.in:10-17,24-31,49-64,82-103` exports
  `Calamares::calamares` and `Calamares::calamaresui` and restores its Qt 6
  dependency set;
- `src/libcalamares/CMakeLists.txt:180-210` and
  `src/libcalamaresui/CMakeLists.txt:74-88` install their public headers;
- root `CMakeLists.txt:52-80` identifies release 3.4.2 and ABI series 3.4;
- `CMakeModules/CalamaresAddPlugin.cmake:80-94,130-145,187-225` defines the
  generated plugin and descriptor layout under
  `/usr/lib/calamares/modules/<name>/`.

For those reasons this module uses
`find_package(Calamares 3.4.2 EXACT CONFIG REQUIRED)` instead of patching the
verified upstream archive. It is compiled and packaged against the same
pinned package that enters the ISO, so ABI drift fails the build.

The packaged 3.4.2 SDK has two Arch-specific consumer quirks which the
first-party build helper handles explicitly and fail-closed: its exported
targets hard-code `_IMPORT_PREFIX` as `/usr` and four imported library entries
as `/usr/lib/libcalamares*`, and its generated dependency scanner spells the
KF6 namespace token as lowercase `kf6` although the target is
`KF6::CoreAddons`. The helper redirects only those exact SDK-copy entries to
its private extraction directory; this CMake project resolves
`KF6CoreAddons` before loading Calamares. A full configure, AUTOMOC, compile,
link, install, and Arch package run against `calamares 3.4.2-2` is therefore
the build gate, rather than a header-only compatibility assumption.

`src/modules/welcome/WelcomeViewStep.{h,cpp}` supplies the concrete view-step
and plugin-factory pattern. `src/libcalamaresui/viewpages/ViewStep.h:27-36,
149-155` specifies that a view may construct jobs at runtime. DarkOS follows
the upstream users module's secret-handling pattern
(`src/modules/users/Config.cpp:1070-1112` and `SetPasswordJob.h:17-32`): raw
credentials pass directly into private job members.

Raw keys must never enter Calamares `GlobalStorage`. Its own warning at
`src/libcalamares/GlobalStorage.h:59-76` says dumps and saves can expose
sensitive values, and `GlobalStorage.cpp:105-113` prints every stored value.
This module reads only the non-secret `rootMountPoint` and `username` values
there, after the stock `users` job has created the installed account.

The backend anchors the target root, `etc/passwd`, every home-directory
component, and the private configuration directories with directory file
descriptors. Component-by-component `openat(..., O_NOFOLLOW)` traversal keeps
intermediate symlinks from escaping the installed root. It writes a unique
same-directory file with `openat(O_EXCL|O_NOFOLLOW)`, verifies UID, GID, and
exact mode `0600`, calls `fsync()` on both file and directory, and publishes it
with `renameat()`. No privileged `chown`, `chmod`, write, or cleanup operation
re-resolves an attacker-controlled absolute target pathname.

The installed ReGreet session launches
`/usr/share/wayland-sessions/darkos.desktop`, which executes
`/usr/local/bin/start-hyprland`; it does not run `.bash_profile`. The same
wrapper is also reached by the live and manual-TTY profiles. Therefore that
wrapper—not a display-manager assumption—is the common place that imports the
mode-0600 file before `darkos-shell.py` constructs `AIBrain` and reads its
environment.
