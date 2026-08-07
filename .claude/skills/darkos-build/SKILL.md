---
name: darkos-build
description: Build and verify the DarkOS ISO correctly — run the local build, syntax-check shipped scripts, and add or modify packages, config files, and runtime scripts without tripping the build-time enforcement. Use for anything touching build-iso.sh, ci/verify-iso.sh, ci/build-calamares.sh, profiledef.sh, packages.x86_64, or airootfs/.
---

# DarkOS Build & Verification

DarkOS has **no unit tests** — correctness is enforced at build time. `build-iso.sh` and `ci/verify-iso.sh` fail the build on any missing shebang, CRLF byte, wrong mode, or content drift in a shipped script. A loud build failure is the intended way a broken script surfaces.

## Commands

- Build the ISO (Arch host, must be root): `sudo bash build-iso.sh`
  - Preserve temp dirs on failure for debugging: `DARKOS_KEEP_WORK=1 sudo bash build-iso.sh`
  - Output: `out/darkos-*.iso`
- Syntax-check a script before building: `bash -n <file>` (shell) or `python -m py_compile <file>` (`.py`)
- Run the built ISO in a VM (UEFI only): `qemu-system-x86_64 -cdrom out/darkos-*.iso -m 4096 -enable-kvm`
- Inspect a committed blob's real bytes (CRLF check): `git show HEAD:<path> | od -c | head -3`

## The invariants (don't bypass)

Every script in `runtime_scripts` (`build-iso.sh`) and in the `payload`/`scripts` arrays (`ci/verify-iso.sh`) must be:
- Mode `755` in the source profile, the staged profile, **and** the built squashfs — asserted by `assert_runtime_scripts`
- Have a `#!` shebang
- Free of CRLF bytes (CRLF makes QProcess exit with 126)
- Byte-identical between source and the packaged squashfs (`cmp -s`)
- Listed in `bash_scripts` if it's a shell script, and pass `bash -n`

`assert_profile_permissions` re-sources `profiledef.sh` in a way that reproduces mkarchiso's function-local scoping and compares every entry against the expected permission map.

## Adding or modifying a runtime script

1. Write the script under `airootfs/usr/local/bin/`, LF line endings.
2. Make it executable in git: `git update-index --chmod=+x <file>`, then verify `git ls-files -s <file>` shows `100755`.
3. Add its `file_permissions` entry in `profiledef.sh`: `["/usr/local/bin/<name>"]="0:0:755"`.
4. Add it to **both** `runtime_scripts` and `bash_scripts` in `build-iso.sh`, and to the `payload` + `scripts` arrays in `ci/verify-iso.sh`, or the build fails.
5. **Never** write `declare -A file_permissions` inside `profiledef.sh` — mkarchiso sources it from inside a function, so `declare -A` makes the map function-local and silently resets every permission to 0644.

## Adding a package

One name per line in `packages.x86_64`. The pinned Calamares build comes from the `[darkos-local]` repo created by `ci/build-calamares.sh` (reuse a cached package via `DARKOS_CALAMARES_PACKAGE` + `DARKOS_CALAMARES_PACKAGE_SHA256`, identity and checksum are re-verified).

## Adding a config file

Place under `airootfs/` matching the target path (`airootfs/etc/foo.conf` → `/etc/foo.conf`), add permissions to `profiledef.sh`'s `file_permissions`. `.gitattributes` already forces `eol=lf` on all text. Releng base files (`airootfs/`, `efiboot/`) are copied fresh at build time — do not commit files that conflict with them.

## Calamares sequence gotchas

- `airootfs/etc/calamares/settings.conf` uses only `show:` and `exec:` phases — any other phase name causes `FATAL: no sequence set`.
- The bootloader is installed via `shellprocess@bootloader-install`, which runs `bash /usr/local/bin/darkos-grub-install.sh` inside the target chroot. Invoke scripts via `bash` in any shellprocess job — it survives a lost exec bit.
- Module config keys must match what the Python module expects exactly (`source:`/`destination:`, not `src:`/`dest:`) or it throws `KeyError`.
