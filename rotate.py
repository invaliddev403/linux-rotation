#!/usr/bin/env python3
"""Native rotation setup and session rotation helper. Python 3.8+, standard library."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import pwd
import tempfile

LOGIN_STATE = Path('/var/lib/linux-rotation/plasmalogin-backup.json')

SCHEMA = 'org.gnome.settings-daemon.peripherals.touchscreen'
ANGLES = {'normal': 0, 'left-up': 90, 'bottom-up': 180, 'right-up': 270}
POLICIES = {0: 'never', 1: 'inTabletMode', 2: 'always'}
ROTATIONS = {1: 'none', 2: 'left', 4: 'inverted', 8: 'right'}
STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'linux-rotation'


def run(*args, check=True):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env=dict(os.environ, LC_ALL='C'), timeout=30)
    if check and p.returncode:
        raise RuntimeError(f'{shlex.join(args)}: {p.stderr.strip() or p.stdout.strip()}')
    return p.stdout


def backend():
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    session = os.environ.get('XDG_SESSION_TYPE', '')
    if session == 'x11':
        return 'x11'
    if session != 'wayland':
        raise RuntimeError('Run from a graphical desktop terminal with XDG_SESSION_TYPE set.')
    if 'cosmic' in desktop:
        return 'cosmic'
    if 'kde' in desktop:
        return 'kde'
    if 'gnome' in desktop or 'unity' in desktop:
        return 'gnome'
    if os.environ.get('SWAYSOCK'):
        return 'sway'
    return 'wlr'


def outputs(b):
    if b == 'kde':
        return [o for o in json.loads(run('kscreen-doctor', '-j'))['outputs']
                if o.get('connected') and o.get('enabled')]
    if b == 'x11':
        found = []
        for line in run('xrandr', '--query').splitlines():
            m = re.match(r'^(\S+) connected (?:primary )?\d+x\d+\+\d+\+\d+\s+(.*)', line)
            if m:
                rotation = m[2].split('(')[0].strip() or 'normal'
                if rotation not in ('normal', 'left', 'right', 'inverted'):
                    raise RuntimeError('Reflected X11 outputs are not supported.')
                found.append({'name': m[1], 'transform': rotation})
        return found
    if b == 'sway':
        return [o for o in json.loads(run('swaymsg', '-t', 'get_outputs', '-r')) if o['active']]
    if b == 'wlr':
        return [o for o in json.loads(run('wlr-randr', '--json')) if o['enabled']]
    if b == 'cosmic':
        found = []
        # Only read the small, known subset of cosmic-randr's generated KDL.
        for block in re.split(r'(?m)(?=^output ")', run('cosmic-randr', 'list', '--kdl')):
            head = re.match(r'output "([\w-]+)" enabled=#true', block)
            if not head:
                continue
            mode = re.search(r'mode (\d+) (\d+) (\d+)[^\n]*current=#true', block)
            transform = re.search(r'\n  transform "(\w+)"', block)
            if not mode or not transform:
                raise RuntimeError('Unrecognized COSMIC output format; no display settings changed.')
            found.append({'name': head[1], 'transform': transform[1],
                          'mode': [int(x) for x in mode.groups()]})
        return found
    return []


def choose(items, name=None):
    choices = [o for o in items if o['name'] == name] if name else [
        o for o in items if re.match(r'^(eDP|DSI|LVDS)', o['name'], re.I)]
    if len(choices) != 1:
        raise RuntimeError('Specify --output NAME; active outputs: ' + ', '.join(o['name'] for o in items))
    if not re.fullmatch(r'[\w-]+', choices[0]['name']):
        raise RuntimeError('Unsupported output name.')
    return choices[0]


def transform(b, o, angle=None):
    name = o['name']
    if angle is None:
        value = ROTATIONS[o['rotation']] if b == 'kde' else o['transform']
    elif b in ('x11', 'kde'):
        value = {0: 'normal' if b == 'x11' else 'none', 90: 'left', 180: 'inverted', 270: 'right'}[angle]
    elif b == 'cosmic':
        value = 'normal' if angle == 0 else f'rotate{angle}'
    else:
        value = 'normal' if angle == 0 else str(angle)
    if b == 'kde':
        run('kscreen-doctor', f'output.{name}.rotation.{value}')
    elif b == 'x11':
        run('xrandr', '--output', name, '--rotate', value)
    elif b == 'cosmic':
        w, h, refresh = o['mode']
        run('cosmic-randr', 'mode', name, str(w), str(h), '--refresh', str(refresh / 1000), '--transform', value)
    elif b == 'sway':
        response = json.loads(run('swaymsg', '-r', 'output', name, 'transform', value))
        if not all(r.get('success') for r in response):
            raise RuntimeError('Sway rejected rotation: ' + str(response))
    else:
        run('wlr-randr', '--output', name, '--transform', value)


def dependencies():
    # Use the distribution's native package manager, not just the first installed executable.
    info = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k] = v.strip('"')
    family = (info.get('ID', '') + ' ' + info.get('ID_LIKE', '')).split()
    if any(x in family for x in ('debian', 'ubuntu')):
        cmd = ['apt-get', 'install', 'iio-sensor-proxy']
    elif any(x in family for x in ('arch', 'cachyos', 'manjaro')):
        cmd = ['pacman', '-S', '--needed', 'iio-sensor-proxy']
    elif any(x in family for x in ('fedora', 'rhel', 'centos')):
        if shutil.which('rpm-ostree'):
            raise RuntimeError('Immutable Fedora: install iio-sensor-proxy with rpm-ostree if missing, reboot, then retry.')
        cmd = ['dnf', 'install', 'iio-sensor-proxy']
    elif any('suse' in x for x in family):
        cmd = ['zypper', 'install', 'iio-sensor-proxy']
    else:
        raise RuntimeError('Install iio-sensor-proxy using your distribution package manager.')
    if not shutil.which('monitor-sensor'):
        subprocess.run(['sudo'] + cmd, check=True)
    if Path('/run/systemd/system').exists():
        subprocess.run(['sudo', 'systemctl', 'start', 'iio-sensor-proxy.service'], check=True)
    print('Sensor package available. No service enable is needed for the usual D-Bus-activated service.')


def sensor_check():
    if not shutil.which('monitor-sensor'):
        raise RuntimeError('Missing monitor-sensor: run the deps command first.')
    try:
        p = subprocess.run(['monitor-sensor'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=4, env=dict(os.environ, LC_ALL='C'))
        text = p.stdout
    except subprocess.TimeoutExpired as e:
        text = e.stdout or b''
        if isinstance(text, bytes):
            text = text.decode(errors='replace')
    print(text.strip())
    if 'Has accelerometer' not in text:
        raise RuntimeError('No accelerometer reported. Check kernel support and iio-sensor-proxy before rotation setup.')


def statefile(b):
    return STATE / (b + '.json')


def save(b, value):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = statefile(b)
    if not path.exists():
        with path.open('x') as f:
            json.dump(value, f, indent=2)


def native(b, name):
    if b == 'gnome':
        old = run('gsettings', 'get', SCHEMA, 'orientation-lock').strip()
        if old not in ('true', 'false'):
            raise RuntimeError('GNOME orientation-lock setting unavailable.')
        save(b, {'orientation-lock': old})
        run('gsettings', 'set', SCHEMA, 'orientation-lock', 'false')
        if run('gsettings', 'get', SCHEMA, 'orientation-lock').strip() != 'false':
            raise RuntimeError('GNOME did not accept orientation unlock.')
        print('GNOME rotation unlocked. Tablet/touchscreen detection may still gate rotation.')
    elif b == 'kde':
        o = choose(outputs(b), name)
        if o.get('autoRotatePolicy') not in POLICIES:
            raise RuntimeError('This KDE version lacks the native CLI policy. Use Display Settings to enable automatic rotation, or use watch.')
        if o.get('rotation') not in ROTATIONS:
            raise RuntimeError('Reflected KDE output is not supported by this helper.')
        if statefile(b).exists() and json.loads(statefile(b).read_text())['name'] != o['name']:
            raise RuntimeError('Undo the previous output setup before selecting another output.')
        save(b, o)
        run('kscreen-doctor', f"output.{o['name']}.autoRotatePolicy.always")
        if choose(outputs(b), o['name']).get('autoRotatePolicy') != 2:
            raise RuntimeError('KDE did not accept automatic rotation; use its Display Settings.')
        print('KDE automatic rotation enabled and verified.')
    else:
        raise RuntimeError('This desktop uses the watch command; see README for session autostart.')


def undo(b):
    path = statefile(b)
    if not path.exists():
        raise RuntimeError('No native-setting backup for this desktop.')
    old = json.loads(path.read_text())
    if b == 'gnome':
        run('gsettings', 'set', SCHEMA, 'orientation-lock', old['orientation-lock'])
    elif b == 'kde':
        choose(outputs(b), old['name'])
        run('kscreen-doctor', f"output.{old['name']}.autoRotatePolicy.{POLICIES[old['autoRotatePolicy']]}",
            f"output.{old['name']}.rotation.{ROTATIONS[old['rotation']]}")
    else:
        raise RuntimeError('Stop watch with Ctrl+C; it restores the starting rotation.')
    path.unlink()
    print('Previous native setting restored.')


def watch(b, args):
    if b == 'gnome':
        raise RuntimeError('GNOME Wayland uses native rotation: run enable. It does not expose the generic wlroots output API.')
    items = outputs(b)
    if b == 'x11' and 'gnome' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower():
        if run('gsettings', 'get', SCHEMA, 'orientation-lock').strip() != 'true':
            raise RuntimeError('Lock GNOME native rotation first before starting the X11 watcher.')
    o = choose(items, args.output)
    if len(items) != 1:
        raise RuntimeError('watch currently requires one active display to avoid layout/touch mapping conflicts.')
    sensor_check()
    if b == 'kde' and o.get('autoRotatePolicy', 0) != 0:
        raise RuntimeError('Disable KDE native automatic rotation in Display Settings before using watch, to avoid competing controllers.')
    if b == 'kde' and o.get('rotation') not in ROTATIONS:
        raise RuntimeError('Reflected KDE output is not supported.')
    original_touch = None
    if args.touch:
        if b != 'x11':
            raise RuntimeError('--touch is only for X11; Wayland input mapping belongs to the compositor.')
        props = run('xinput', 'list-props', args.touch)
        m = re.search(r'Coordinate Transformation Matrix \(\d+\):\s*([^\n]+)', props)
        if not m:
            raise RuntimeError('Touch device has no Coordinate Transformation Matrix property.')
        original_touch = [str(float(x.strip())) for x in m[1].split(',')]
        if len(original_touch) != 9:
            raise RuntimeError('Invalid touchscreen matrix.')
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'watch.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another rotation watcher is already running.')
        process = subprocess.Popen(['monitor-sensor'], stdout=subprocess.PIPE, text=True,
                                   env=dict(os.environ, LC_ALL='C'))
        def stop(_sig, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        last = None
        print(f"Watching {o['name']} via {b}; Ctrl+C restores starting rotation.", flush=True)
        try:
            for line in process.stdout:
                m = re.search(r'(?:orientation: |orientation changed: )(normal|left-up|right-up|bottom-up)', line)
                if not m:
                    continue
                angle = (ANGLES[m[1]] + args.offset) % 360
                if angle == last:
                    continue
                if len(outputs(b)) != 1:
                    raise RuntimeError('Display topology changed; stopping rotation watcher.')
                transform(b, o, angle)
                if original_touch:
                    matrix = {0: [1,0,0,0,1,0,0,0,1], 90: [0,-1,1,1,0,0,0,0,1],
                              180: [-1,0,1,0,-1,1,0,0,1], 270: [0,1,0,-1,0,1,0,0,1]}[angle]
                    run('xinput', 'set-prop', args.touch, 'Coordinate Transformation Matrix', *map(str, matrix))
                last = angle
                print(f'{m[1]} -> {angle} degrees', flush=True)
            raise RuntimeError('Sensor monitor exited unexpectedly.')
        except KeyboardInterrupt:
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            try:
                transform(b, o)
            finally:
                if original_touch:
                    run('xinput', 'set-prop', args.touch, 'Coordinate Transformation Matrix', *original_touch)


def login_target():
    manager = Path('/etc/systemd/system/display-manager.service').resolve().name
    if manager != 'plasmalogin.service':
        raise RuntimeError(f'Login-screen automation supports Plasma Login Manager only; detected {manager}. '
                           'SDDM, GDM, LightDM and COSMIC greeters need their own configuration.')
    account = pwd.getpwnam('plasmalogin')
    return Path(account.pw_dir) / '.config/kwinoutputconfig.json', account


def login_config(data, name, rotation):
    matches = [o for group in data if group.get('name') == 'outputs'
               for o in group['data'] if o.get('connectorName') == name]
    if not matches:
        raise RuntimeError(f'No {name} entry in greeter configuration; no changes made.')
    for output in matches:
        output['transform'] = {0: 'Normal', 90: 'Rotated90', 180: 'Rotated180', 270: 'Rotated270'}[rotation]
        output['autoRotation'] = 'Never'
    return data


def atomic_file(path, content, uid, gid, mode):
    fd, temporary = tempfile.mkstemp(prefix='.linux-rotation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def login_action(args):
    target, account = login_target()
    # Do not follow greeter-controlled symlinks while running with root privileges.
    for path in (target, target.parent, Path(account.pw_dir), LOGIN_STATE, LOGIN_STATE.parent):
        if path.is_symlink():
            raise RuntimeError(f'Refusing symlink: {path}')
    if args.command == 'login-status':
        print('Manager: Plasma Login Manager\nConfiguration:', target)
        if target.exists():
            data = json.loads(target.read_text())
            print(json.dumps([o for g in data if g.get('name') == 'outputs' for o in g['data']], indent=2))
        else:
            print('No greeter display configuration yet.')
        print('Undo backup:', LOGIN_STATE if LOGIN_STATE.exists() else 'none')
        return
    if args.command == 'login-undo':
        if not LOGIN_STATE.exists():
            raise RuntimeError('No login-screen backup created by this script.')
        backup = json.loads(LOGIN_STATE.read_text())
        if backup['target'] != str(target):
            raise RuntimeError('Backup target differs from current login-manager home.')
        if backup['existed']:
            atomic_file(target, backup['content'], backup['uid'], backup['gid'], backup['mode'])
        else:
            target.unlink(missing_ok=True)
        LOGIN_STATE.unlink()
        print('Previous greeter configuration restored. Takes effect when the greeter next starts.')
        return
    if args.rotation is None or not args.output:
        raise RuntimeError('login-enable requires --output and --rotation (absolute angle, not offset).')
    existed = target.exists()
    if not existed and not args.source:
        raise RuntimeError('No greeter configuration. Supply --source /absolute/path/to/kwinoutputconfig.json from a working KDE session.')
    source = target if existed else Path(args.source)
    if not source.is_absolute():
        raise RuntimeError('--source must be an absolute path.')
    original = source.read_text()
    data = login_config(json.loads(original), args.output, args.rotation)
    if LOGIN_STATE.exists():
        if json.loads(LOGIN_STATE.read_text())['target'] != str(target):
            raise RuntimeError('Existing backup belongs to another target; undo it first.')
    else:
        LOGIN_STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chown(LOGIN_STATE.parent, 0, 0)
        os.chmod(LOGIN_STATE.parent, 0o700)
        metadata = target.stat() if existed else None
        backup = {'target': str(target), 'existed': existed, 'content': original if existed else None,
                  'uid': metadata.st_uid if existed else None, 'gid': metadata.st_gid if existed else None,
                  'mode': metadata.st_mode & 0o777 if existed else None}
        atomic_file(LOGIN_STATE, json.dumps(backup), 0, 0, 0o600)
    if not target.parent.exists():
        target.parent.mkdir(mode=0o700)
        os.chown(target.parent, account.pw_uid, account.pw_gid)
    atomic_file(target, json.dumps(data, indent=4) + '\n', account.pw_uid, account.pw_gid, 0o600)
    if json.loads(target.read_text()) != data:
        raise RuntimeError('Greeter configuration verification failed; use login-undo.')
    print(f'Verified {args.output}: fixed {args.rotation} degrees. Backup: {LOGIN_STATE}')
    print('Effective when the greeter next starts. No restart or logout was performed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'deps', 'enable', 'undo', 'watch',
                                          'login-status', 'login-enable', 'login-undo',
                                          'boot-status', 'boot-enable', 'boot-undo'])
    parser.add_argument('--output', help='Built-in output, e.g. DSI-1 or eDP-1')
    parser.add_argument('--offset', type=int, choices=[0,90,180,270], default=0,
                        help='Additional panel-relative rotation for watch only (default: 0)')
    parser.add_argument('--touch', help='X11 touchscreen name or ID; watch only')
    parser.add_argument('--rotation', type=int, choices=[0,90,180,270], help='Absolute login-screen rotation; login-enable only')
    parser.add_argument('--source', help='Working KDE output JSON to seed a missing greeter config; login-enable only')
    parser.add_argument('--boot-config', default='/boot/limine.conf', help='Limine config path for boot commands')
    parser.add_argument('--menu-rotation', type=int, choices=[0,90,180,270], help='Limine interface rotation; boot-enable only')
    parser.add_argument('--panel-orientation', choices=['normal','left_side_up','right_side_up','upside_down'], help='DRM panel hint; boot-enable only')
    parser.add_argument('--console-rotation', type=int, choices=[0,1,2,3], help='fbcon quarter-turns clockwise; boot-enable only')
    parser.add_argument('--dry-run', action='store_true', help='Preview boot-enable without writing files')
    args = parser.parse_args()
    if args.command != 'watch' and (args.offset or args.touch):
        parser.error('--offset and --touch apply only to watch')
    if args.command != 'login-enable' and (args.rotation is not None or args.source):
        parser.error('--rotation and --source apply only to login-enable')
    if args.command != 'boot-enable' and (args.menu_rotation is not None or args.panel_orientation is not None
                                         or args.console_rotation is not None or args.dry_run):
        parser.error('Boot rotation options apply only to boot-enable')
    if args.command.startswith('boot-'):
        if os.geteuid() != 0:
            parser.error('Boot commands require sudo; see README.')
        import boot_rotation
        boot_rotation.action(args)
        return
    if args.command.startswith('login-'):
        if os.geteuid() != 0:
            parser.error('Login-screen commands require sudo; see README. Desktop commands run as your regular user.')
        login_action(args)
        return
    if os.geteuid() == 0:
        parser.error('Run as your desktop user, not sudo/root. deps invokes sudo only where needed.')
    if args.command == 'deps':
        dependencies()
        return
    b = backend()
    print('Desktop:', os.environ.get('XDG_CURRENT_DESKTOP'), '| backend:', b)
    if args.command == 'status':
        if b == 'gnome':
            print('Orientation locked:', run('gsettings', 'get', SCHEMA, 'orientation-lock').strip())
        else:
            print(json.dumps(outputs(b), indent=2))
        sensor_check()
    elif args.command == 'enable':
        sensor_check()
        native(b, args.output)
    elif args.command == 'undo':
        undo(b)
    else:
        watch(b, args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Error:', exc, file=sys.stderr)
        sys.exit(1)
