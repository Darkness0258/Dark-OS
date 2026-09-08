# Through-Phase-7 audit — 2026-09-06

The repository is not yet complete through Phase 7. This audit separates
implementation, automated checks, and target-system acceptance.

## Fixes and additions

- All native Python launchers are included in executable-mode repair, profile
  permissions, source/squashfs comparisons, and ISO syntax checks.
- Docker and CI share pinned BlackArch bootstrapping, verified Chaotic package
  signatures, explicit trusted repository configuration, and fail-closed sync.
  Bootstrap packages cannot downgrade an installed newer version. Calamares
  dependency setup performs a full Arch upgrade transaction. Docker stages the
  Windows checkout on a Linux filesystem before enforcing executable modes,
  and publishes only a successfully verified ISO.
- ISO checks validate the mpv MPRIS absolute symlink against the extracted
  library instead of accidentally following it into the build host.
- Dock/rail/AI launch targets now use the native apps and declared hosted
  defaults. Empty mpv launches open its player UI.
- Secondary Files, Reader, Notes, and Terminal launches retain their own file,
  command, and working-directory arguments. Notes flushes pending autosave.
- Vault files are private and atomically published. Create cannot replace an
  existing vault; locking a newly created vault returns to Unlock. Encryption
  and decryption refuse to overwrite existing files. Vault deletion confirms.
- Shield supports cancellable on-demand ClamAV scans without deleting files.
  Missing definitions, empty scans, scanner errors, and incomplete/truncated
  reports never become a clean verdict.
- Connect uses upstream KDE Connect D-Bus state and guarded pair/unpair/ring/
  file-transfer actions. Wi-Fi parsing preserves escaped SSIDs. Network probes
  run outside GTK and display real errors.
- Gaming status does not launch Steam or Proton. Bottles supports its upstream
  Flatpak ID; Waydroid reports startup prerequisites and command diagnostics.
- Store queries run in bounded background jobs and preserve backend errors.
  AUR response reads now have a 2 MiB cap and an elapsed-time deadline. Install
  actions remain disabled pending the full Shield gate.
- Shield drains a nonblocking subprocess pipe instead of an unbounded disk
  spool. Crossing its 128 KiB report cap stops/reaps the scanner and reports an
  incomplete/error result; cancellation and timeout also terminate/reap it.
- Native Mail provides session-only account settings, verified IMAPS/SMTPS,
  bounded read-only text previews, and an explicit review/confirmation before
  sending. It never automatically retries an uncertain send. HTML, attachments,
  OAuth, persistent credentials, and mailto links are outside this basic scope.
- Settings offers only the power profiles reported by power-profiles-daemon,
  requests changes as the desktop user, and checks the resulting active profile.
  This does not implement the separate kernel/scheduler selection requirement.
- File copy/move refuses overwrite, including racing targets; archive extraction
  uses a fresh destination and rejects unsafe paths. Backup preserves empty
  directories, avoids including its own output, fails on unreadable input, and
  uses unique archives and atomic validated manifests. Calendar persistence is
  validated and atomic, with failures shown instead of discarded.
- Calculator accepts its own Unicode minus button and bounds expensive numeric
  expressions. Timer countdown uses elapsed monotonic time instead of assuming
  every GTK callback runs exactly one second apart.
- Hosted Camera uses GNOME Camera (`snapshot`); the real package-resolution
  build found that the former `cheese` package is unavailable.
- Seven development-agent metadata files were removed from the ISO payload;
  they remain recoverable from Git history.

## Reproducible validation

Run the complete suite in Arch Linux (not a substitute for a booted DarkOS system):

```bash
bash ci/test-build-bootstrap.sh
bash ci/test-docker-workspace.sh
python ci/test-phase3-linux.py
python ci/test-app-kit.py
python ci/test-gaming.py
python ci/test-network-connect.py
python ci/test-store.py
python ci/test-calculator-clock.py
python ci/test-mail.py
python ci/test-performance.py
python ci/test-native-storage.py
python ci/test-shield.py
xvfb-run -a dbus-run-session -- python ci/test-native-apps-linux.py
```

Earlier Arch Linux baseline, before the final Store/Shield resource-limit edits:

- Bootstrap mocked regressions and Docker staging/publication fixtures pass.
- All seven Phase 3 unit/mock verification groups pass. They are not a new
  live-provider, microphone, Btrfs, or compositor acceptance test.
- 83 focused regressions pass: Gaming 15, Network 13, Store 8, Shield 10,
  Mail 14, Performance 7, Storage 10, Calculator/Clock 4, and App Kit 2.
- Shield includes a real ClamAV clean/detection/empty-database check with a
  harmless custom signature. This does not measure real-world detection rates.
- All 21 native GTK windows construct and realize under Xvfb. Notes autosave,
  vault/password failures, encryption round trips and overwrite refusal, and
  concurrent terminal command/cwd execution pass.
- All 49 Python files, shell scripts, 17 YAML files (including CI), and desktop launchers pass
  syntax/format validation. Desktop-category hints are non-fatal.
- CI runs the new regressions before building an ISO.
- The pinned Calamares 3.4.2-2 package and first-party API-key view module compile
  successfully in Arch Linux. The full ISO was last observed downloading
  packages; its final result could not be recovered after Docker/WSL stopped.
  No new verified ISO or boot/install acceptance is claimed.

Final Windows source pass after those resource-limit edits:

- 94 focused tests discovered: **90 passed, 4 explicitly skipped**. Store now
  has 12 tests and Shield 17. The skips are the real GIO copy/move test, real
  ClamAV integration, and two Linux subprocess/pipe integration tests.
- All 49 Python files compile, 17 YAML files parse, Bash syntax checks pass
  through Git Bash, runtime scripts remain LF-only, and `git diff --check` passes.
- The latest scanner pipe/real-engine behavior and the final ISO must be rerun
  under Linux. The earlier real-ClamAV result is not evidence for this changed
  collector implementation.

## Build environment blocker

On resuming at 2026-09-06 21:32 PKT, Docker Desktop could not restart its Linux
engine: `HCS_E_HYPERV_NOT_INSTALLED`. Read-only host checks show firmware
virtualization enabled and `HypervisorPresent=False`. Boot-configuration and
Windows optional-feature inspection require administrator access in this
session. No boot setting, Windows feature, firmware setting, or reboot was
changed. The Docker data disk remains present; its build/container contents
cannot be inspected until the engine runs again.

The previous Arch container was `darkos-audit-20260905`. Its Linux workspace
was `/workspace`, with a read-only checkout at `/source`. Once the engine is
restored, rerun the source regressions and a clean build of the final checkout;
do not publish a partially generated or older ISO as the current revision.
The locally built pinned Calamares cache, if still present, is:

```text
/tmp/darkos-audit-calamares-repo/calamares-3.4.2-2-x86_64.pkg.tar.zst
SHA256 91994bb43ca503ee39bc4676fd0532f862124e953038118ff15b1e80d9377cc0
```

Windows recovery guidance: [Microsoft's WSL troubleshooting documentation](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting).

## Remaining acceptance gates

| Phase | Still required |
| --- | --- |
| 1–2 | Build and verify the changed ISO; boot/install/reboot it; inspect the HUD in Hyprland. Historical VM evidence does not certify this revision. |
| 3 | Real microphone gesture/audio and installed-Btrfs safety snapshot acceptance. |
| 4 | Target Wayland/font/window-rule checks for the native apps. |
| 5 | Kernel/scheduler performance-profile choice, permission/accessibility enforcement, phone pairing/transfer, continuous Shield, integrity baselines, quarantine, and PHANTOM-backed network transparency. |
| 6 | A verified Shield installation gate and working package installation/update workflows. |
| 7 | Native/hosted-mail send/receive with a real account; actual Windows/Steam workload; Waydroid initialization and Android app; camera and Wayland capture. |

PHANTOM's source is absent from this checkout. Its actual monitoring core cannot
be reused until its repository or local path is supplied. Geary remains an
optional full hosted mail client alongside the new basic native Mail app.
No real mailbox was connected, message sent, phone paired, or host power profile
changed by these tests.
