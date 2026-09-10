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

Python 3.8 or later must already be installed (package `python3` on Debian/Fedora/openSUSE, `python` on Arch). The script uses only Python's standard library.

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

For `watch`, stop the process; its initial display rotation and optional X11 touch matrix are restored. Undo does not uninstall packages or stop the shared sensor service. Only the explicit `login-*` commands touch login-screen configuration. No bootloader, kernel, udev, sensor mount matrix, or tablet-mode driver changes are made.

## Verification and limits

Native KDE JSON detection and sensor status were checked on the owner's CachyOS KDE Wayland laptop. Automated tests use mocked CLI output for other backends and command construction. Debian/Ubuntu/Fedora installation, GNOME, XFCE/X11, COSMIC, Sway, and wlroots behavior have not been tested on live installations. Always test physical landscape, both portrait positions, upside-down orientation, and touchscreen alignment before adding startup automation.

No accelerometer in `status` means kernel/driver/service support needs attention first. This helper does not install out-of-tree drivers or implement keyboard disabling/tablet-mode detection. `status` makes no configuration changes, although connecting to the sensor service can cause normal D-Bus service activation.

## Sources

- [KDE display CLI implementation](https://raw.githubusercontent.com/KDE/libkscreen/master/src/doctor/doctor.cpp)
- [KWin panel-relative sensor mapping](https://raw.githubusercontent.com/KDE/kwin/master/src/outputconfigurationstore.cpp)
- [GNOME orientation-lock implementation](https://gnome.pages.gitlab.gnome.org/gnome-settings-daemon/plugins/media-keys/gsd-media-keys-manager.c.gcov.html)
- [COSMIC CLI source](https://github.com/pop-os/cosmic-randr/blob/master/cli/src/main.rs)
- [wlr-randr source](https://github.com/emersion/wlr-randr/blob/master/main.c)
- [X11 touchscreen transformation matrices](https://wiki.ubuntu.com/X/InputCoordinateTransformation)
- [Plasma Login Manager](https://github.com/KDE/plasma-login-manager)
