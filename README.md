# Portable Linux laptop rotation helper

This Python 3 script enables native desktop rotation or runs a sensor-driven rotation helper. It was created for a Chuwi MiniBook X N150 after CachyOS KDE was found to have automatic rotation disabled. It does not assume every MiniBook revision needs the same accelerometer correction.

## Quick start

Open a terminal in your graphical desktop, in this directory. Run as your regular user, **not with sudo**:

```bash
python3 rotate.py status
# If sensor support is missing or stopped:
python3 rotate.py deps
# KDE Wayland or GNOME Wayland:
python3 rotate.py enable
```

`deps` supports Debian/Ubuntu derivatives, Arch/CachyOS/Manjaro, Fedora/RHEL derivatives with DNF, and openSUSE with Zypper. It installs `iio-sensor-proxy` if `monitor-sensor` is absent, then starts the sensor service on systemd systems. Package-manager prompts remain interactive. It does not refresh repositories or upgrade the OS. On Arch, update your system normally before installing if your repository database is stale. Immutable Fedora requires its own package layering workflow if the package is missing. Non-systemd systems need the distribution's service/D-Bus activation setup.

Python 3.8 or later must already be installed (package `python3` on Debian/Fedora/openSUSE, `python` on Arch). The script uses only Python's standard library. Keep `rotate.py`, `boot_rotation.py`, and `system_install.py` together when copying the helper to another machine.

## Install for all existing and future users

Boot and login-screen fixes already apply system-wide. Native desktop rotation is a per-user preference. Install the helper and a system-wide XDG autostart task with:

```bash
sudo python3 rotate.py install-system
```

This installs root-owned code under `/usr/local/lib/linux-rotation`, the `linux-rotation` command under `/usr/local/bin`, and `/etc/xdg/autostart/linux-rotation.desktop`. It does not depend on the original checkout staying in a user's home directory. Run the install command again from an updated checkout to update the system copy. Existing files must match the install manifest; unrelated or locally edited files are not overwritten.

Every existing or newly created **KDE/GNOME Wayland** user gets native rotation enabled at their next graphical login. It runs as that user and backs up their prior setting, rather than editing other users' home directories as root. After successful setup, a per-backend marker under `~/.local/state/linux-rotation/` prevents subsequent logins from overriding the user's later preference. Failed setup retries briefly at login and is retried at the next login; no success marker is written on failure. A working sensor service and desktop display utility are still required; install sensor support with `deps` first if needed.

For a currently logged-in user, apply immediately from their own desktop terminal:

```bash
linux-rotation session-enable
```

This does not force logout or restart any other session. Existing users who are already logged in can run the same command or wait until their next login. System/service users and the greeter do not receive a separate desktop configuration. On X11, COSMIC, Sway and other desktops, the installed command is available, but this autostart task does not launch a watcher; use the documented `watch` setup after testing that session's output/touch mapping. Users with an existing personal autostart override or customized XDG search paths may need to enable the task explicitly.

To opt out after initialization, run `linux-rotation undo` as the user or change the native display setting; the completion marker preserves that choice. To opt out before initialization, place a file named `linux-rotation.desktop` in `~/.config/autostart/` containing:

```ini
[Desktop Entry]
Type=Application
Name=Disable rotation initialization
Hidden=true
```

To remove the shared helper and autostart task:

```bash
sudo linux-rotation uninstall-system
```

Uninstall leaves per-user preferences, completion markers, backups, and existing boot/login fixes intact. Run the relevant `undo`, `boot-undo` or `login-undo` command before uninstalling if you also want those settings restored. It does not uninstall dependencies. This setup is a one-time default for each user, not an enforced policy.

## Boot menu, Linux console, and splash (Limine)

Boot rotation is separate from desktop and login-screen rotation. The `boot-*` commands support **Limine with limine-entry-tool-style `/etc/default/limine`, explicit kernel command lines, and non-UKI `protocol: linux` entries**, as used on this CachyOS laptop. They do not support GRUB, systemd-boot, UKIs, Secure Boot/enrolled configurations, or arbitrary Limine setups. Secure Boot must be disabled for this helper; it refuses enabled or indeterminate states rather than bypassing configuration signing. Check that your installed Limine documents `interface_rotation` before using the menu option.

For the MiniBook X N150, preview the change first:

```bash
sudo python3 rotate.py boot-status
sudo python3 rotate.py boot-enable --output DSI-1 \
  --menu-rotation 90 --panel-orientation right_side_up --console-rotation 1 --dry-run
```

Apply by removing `--dry-run`:

```bash
sudo python3 rotate.py boot-enable --output DSI-1 \
  --menu-rotation 90 --panel-orientation right_side_up --console-rotation 1
```

All three rotation options and `--output` are required. The conventions differ:

| Option | Purpose | MiniBook setting |
|---|---|---|
| `--menu-rotation` | Limine graphical interface rotation in degrees (clockwise renderer convention) | `90` |
| `--panel-orientation` | Linux DRM panel mounting hint, used by supporting splash/compositor software | `right_side_up` |
| `--console-rotation` | Linux framebuffer-console quarter-turns clockwise | `1` |

These correspond to this laptop's working KDE `Rotated270` orientation; do not assume the same numeric angle across interfaces. They configure fixed startup orientation, not accelerometer-based boot rotation. The firmware CHUWI logo and BIOS setup cannot be changed by these Linux settings. Plymouth should honor the panel hint after the native DRM driver takes over; earlier simpledrm frames or themes may still need separate handling. The kernel must support framebuffer console rotation. The original machine has `CONFIG_FRAMEBUFFER_CONSOLE_ROTATION=y` and early KMS in its initramfs.

The helper backs up and edits `/etc/default/limine` and `/boot/limine.conf` (override the latter with `--boot-config /absolute/path/limine.conf`). It preserves existing kernel/initramfs paths, hashes, root-device arguments, and unrelated options. Only Linux entries matching the running root device are changed; Btrfs `.snapshots` recovery entries and other OS roots are excluded. It refuses complex/combined video arguments rather than discarding their resolution or other settings. The defaults change carries kernel rotation into future generated entries; verify any separate drop-in or kernel-specific overrides on customized installations. The menu setting is in Limine's global header, which normal entry regeneration preserves; replacing the entire theme/config may remove it.

No kernel/initramfs rebuilding is necessary for these external, non-UKI command-line changes. The helper does not reinstall Limine or run `limine-update`; it updates the current entries and their persistent defaults directly under the boot-partition lock. No reboot is performed automatically. Reboot when convenient and check the menu, splash, console, login screen, and desktop.

Rollback:

```bash
sudo python3 rotate.py boot-undo
```

The first originals and latest applied texts are retained in `/var/lib/linux-rotation/boot-backup.json`. Repeated setup preserves the first originals. Undo restores both files if they still match the last applied texts. If a kernel update or other tool has changed them, undo refuses to overwrite newer entries: use the backup's original/applied texts to selectively remove the rotation options. This deliberately avoids restoring stale kernel paths after updates. Dry run does not write boot settings or a backup (it does acquire the normal boot-partition lock). There is no automated protection against power loss between the two file replacements.

## Login screen (Plasma Login Manager)

The login screen has a separate display configuration from your desktop. The `login-*` commands support **Plasma Login Manager** (`plasmalogin.service`, KWin Wayland), including the version installed on this MiniBook's CachyOS system. They detect the active manager through the systemd `display-manager.service` symlink. SDDM, GDM, LightDM, COSMIC greeter, and non-systemd display-manager setups are explicitly unsupported by these commands; their desktop-session support above does not imply greeter support.

These commands require administrator privileges because they edit the greeter account's configuration. Run from this directory:

```bash
sudo python3 rotate.py login-status
# Chuwi MiniBook X N150: fixed landscape on its portrait-native panel
sudo python3 rotate.py login-enable --output DSI-1 --rotation 270 \
  --source "$HOME/.config/kwinoutputconfig.json"
```

`--rotation` is an **absolute** angle (0, 90, 180, 270), not a sensor offset. Choose the angle that works for your panel. Both `--output` and `--rotation` are required to apply a change. The greeter uses fixed rotation; desktop auto-rotation is unaffected.

The helper updates only the selected connector's rotation and automatic-rotation policy in the existing greeter JSON. If that configuration does not exist, `--source` seeds it from a working KDE configuration; this initial copy includes its other display settings. The source must be an absolute path. Missing connector entries cause an error rather than a guessed setup.

The original configuration and its file ownership/mode are backed up once in `/var/lib/linux-rotation/plasmalogin-backup.json`. Repeated setup retains the first backup. Writes are atomic, the result is read back for verification, and the new file belongs to the greeter account. To undo:

```bash
sudo python3 rotate.py login-undo
```

Undo restores the original file or removes the generated configuration if none existed. It then removes the backup. It does not delete the greeter's configuration directory. Status and undo do not need access to the sensor or your graphical session.

The change takes effect when the greeter next starts. Reboot when convenient to verify it. The script never restarts the login manager, logs you out, or reboots automatically. It does not modify the boot splash or console orientation.

On the original laptop, the earlier manual fix already set `Rotated270` and `Never`; running this command there would back up that already-corrected state. Its earlier pre-fix backup remains separate. The equivalent manual change was applied successfully; visual confirmation after restarting the greeter is still pending.

## Desktop/session coverage

Wayland and X11 are display systems, not desktops. The script selects controls for the actual session.

| Desktop/session | Behavior | Required display utility |
|---|---|---|
| KDE Plasma Wayland | `enable` uses native auto-rotation, saves prior policy and rotation; `undo` restores them | `kscreen-doctor` (usually package `kscreen`) |
| Older KDE Wayland | If native CLI policy is unavailable, use KDE Display Settings; `watch` can use manual rotation after native rotation is disabled | `kscreen-doctor` |
| GNOME Wayland | `enable` unlocks native rotation; `undo` restores the previous lock | `gsettings` |
| XFCE, MATE, Cinnamon, LXQt, KDE or other X11 desktops | `watch` uses XRandR; optional touchscreen mapping | `xrandr`, optional `xinput` |
| GNOME X11 | `watch` uses XRandR; lock GNOME native rotation first to avoid competing controllers | `xrandr`, `gsettings` |
| COSMIC Wayland | `watch` reads COSMIC's current mode and applies transforms with its CLI | `cosmic-randr` |
| Sway Wayland | `watch` uses Sway output IPC | `swaymsg` |
| XFCE Wayland / other wlroots-based sessions | `watch` works only if the compositor exposes output-management and `wlr-randr --json` succeeds | `wlr-randr` with JSON support |
| Hyprland and other Wayland compositors | Capability-based wlroots fallback only; no dedicated Hyprland IPC adapter. If the protocol is unavailable, the script reports the failure | `wlr-randr` if supported |

This is not universal Wayland support: GNOME, KDE, and COSMIC have distinct interfaces. It never uses XRandR to control a Wayland session through Xwayland. GNOME can still gate native rotation on touchscreen/tablet-mode detection; unlocking its setting does not force that hardware detection.

Install missing display tools using your distribution. Common X11 package names: Debian/Ubuntu `x11-xserver-utils xinput`; Arch `xorg-xrandr xorg-xinput`; Fedora `xrandr xinput`. Backend tools are not installed automatically, because availability depends on the desktop and distribution version.

## XFCE/X11, COSMIC, Sway, or compatible Wayland sessions

```bash
python3 rotate.py status
python3 rotate.py watch
# Specify a connector if automatic detection is ambiguous:
python3 rotate.py watch --output DSI-1
```

Keep the process running. Ctrl+C or SIGTERM stops it and attempts to restore the initial rotation. Only one watcher per user is allowed. It refuses multiple active displays and stops if another display becomes active. It does not rearrange monitors. Disable any other automatic rotation helper before using it. For KDE, native automatic rotation must be disabled before `watch`.

For COSMIC, the current resolution and refresh rate are retained in transform commands; scale and position are omitted so the compositor retains them. The parser checks the expected generated KDL format and fails if it cannot identify the current mode and transform.

### Correcting an observed offset

First test all four orientations with the default mapping. If a consistent quarter-turn offset remains:

```bash
python3 rotate.py watch --offset 90
# Or, after stopping that watcher:
python3 rotate.py watch --offset 270
```

The offset adds to the sensor's panel-relative angle. Default mapping: normal=0, left-up=90, bottom-up=180, right-up=270. Do not add 270 merely because this laptop has a portrait-native panel: the sensor may already account for that. Offset only applies to `watch`, not native `enable`. Mirrored or inconsistent axes need measured sensor calibration, which this script does not guess or install.

### X11 touchscreen

List devices with `xinput list`, then specify the touchscreen explicitly:

```bash
python3 rotate.py watch --touch 'Goodix Capacitive TouchScreen'
```

The helper saves the original Coordinate Transformation Matrix, applies a full-screen rotation matrix after display rotation, and restores the original matrix on exit. This assumes a single full-screen touchscreen and replaces any existing calibration during monitoring; do not use it with a custom-calibrated touchscreen. It does not modify touchpads or all pointer devices automatically. On Wayland, input transformation is the compositor's responsibility.

## Starting the watcher at login

Test it in a terminal first. Then add a startup application using your desktop's Startup Applications/Session and Startup settings. Use an absolute path, for example:

```text
python3 /home/YOUR_USER/Documents/linux-rotation/rotate.py watch --output DSI-1
```

On XFCE use **Session and Startup → Application Autostart**. Use the equivalent startup facility for COSMIC or your compositor's startup configuration. Do not start this as a root service: it needs the graphical session environment. Remove that startup entry to disable persistence, and stop the existing watcher with Ctrl+C or SIGTERM. Native KDE/GNOME `enable` is already persistent and does not need a startup helper.

No automatic startup entries are created by the script. The original session rotation cannot be restored after SIGKILL, a crash, or power loss; use the desktop display settings if needed. The helper does not reconnect after sensor-service failure; restart it after fixing the service.

## Undo and backups

For native KDE/GNOME changes:

```bash
python3 rotate.py undo
```

The first pre-change setting is preserved in `$XDG_STATE_HOME/linux-rotation/` (default `~/.local/state/linux-rotation/`). Repeated `enable` commands retain the original backup. Successful undo removes that backup. If automatic rotation was already enabled before running the script, undo appropriately leaves it enabled.

For `watch`, stop the process; its initial display rotation and optional X11 touch matrix are restored. Undo does not uninstall packages or stop the shared sensor service. Only explicit `login-*` commands touch login-screen configuration, and only `boot-*` commands touch bootloader settings and kernel command lines. No udev, sensor mount matrix, or tablet-mode driver changes are made.

## Verification and limits

Native KDE JSON detection and sensor status were checked on the owner's CachyOS KDE Wayland laptop. The Limine boot command passed a live dry run, then applied and read back both installed kernel entries and persistent defaults successfully; visual verification after reboot is pending. The test suite contains 15 tests, including boot planning, preservation of recovery entries, repeated setup, and rollback that rejects later edits. Run it with `python3 -m unittest -v`.

Automated desktop tests use mocked CLI output for other backends and command construction. Debian/Ubuntu/Fedora installation, GNOME, XFCE/X11, COSMIC, Sway, and wlroots behavior have not been tested on live installations. Always test physical landscape, both portrait positions, upside-down orientation, and touchscreen alignment before adding startup automation.

No accelerometer in `status` means kernel/driver/service support needs attention first. This helper does not install out-of-tree drivers or implement keyboard disabling/tablet-mode detection. `status` makes no configuration changes, although connecting to the sensor service can cause normal D-Bus service activation.

## Sources

- [KDE display CLI implementation](https://raw.githubusercontent.com/KDE/libkscreen/master/src/doctor/doctor.cpp)
- [KWin panel-relative sensor mapping](https://raw.githubusercontent.com/KDE/kwin/master/src/outputconfigurationstore.cpp)
- [GNOME orientation-lock implementation](https://gnome.pages.gitlab.gnome.org/gnome-settings-daemon/plugins/media-keys/gsd-media-keys-manager.c.gcov.html)
- [COSMIC CLI source](https://github.com/pop-os/cosmic-randr/blob/master/cli/src/main.rs)
- [wlr-randr source](https://github.com/emersion/wlr-randr/blob/master/main.c)
- [X11 touchscreen transformation matrices](https://wiki.ubuntu.com/X/InputCoordinateTransformation)
- [Plasma Login Manager](https://github.com/KDE/plasma-login-manager)
- [Limine interface rotation](https://github.com/Limine-Bootloader/Limine/blob/v12.x/CONFIG.md)
- [Framebuffer console rotation](https://www.kernel.org/doc/html/v5.9/fb/fbcon.html)
- [CachyOS boot-manager configuration](https://wiki.cachyos.org/configuration/boot_manager_configuration/)
- [Flanterm framebuffer rotation implementation](https://github.com/mintsuki/flanterm/blob/trunk/src/flanterm_backends/fb.c)
