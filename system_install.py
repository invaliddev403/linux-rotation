"""Install a root-owned helper and one-time native session setup for all users."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

LIB = Path('/usr/local/lib/linux-rotation')
LAUNCHER = Path('/usr/local/bin/linux-rotation')
AUTOSTART = Path('/etc/xdg/autostart/linux-rotation.desktop')
FILES = ('rotate.py', 'boot_rotation.py', 'system_install.py')


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def write(path, text, mode):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.linux-rotation-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.chown(name, 0, 0)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def action(command):
    manifest = LIB / 'manifest.json'
    targets = [LIB / name for name in FILES] + [LAUNCHER, AUTOSTART]
    for path in targets + [manifest]:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise RuntimeError('Refusing symlink in installation path: ' + str(path))
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if previous and set(previous) != {str(path) for path in targets}:
        raise RuntimeError('Unexpected install manifest; no changes made.')
    for path in targets:
        if path.exists() and (str(path) not in previous or digest(path.read_text()) != previous[str(path)]):
            raise RuntimeError('Refusing to overwrite/remove unmanaged or locally modified file: ' + str(path))
    if command == 'uninstall-system':
        if not previous:
            raise RuntimeError('No managed system installation found.')
        # Remove autostart first so no new session starts the helper during removal.
        for path in [AUTOSTART, LAUNCHER] + [LIB / name for name in FILES]:
            path.unlink(missing_ok=True)
        manifest.unlink()
        print('System helper and autostart removed. Per-user preferences/backups and boot/login fixes retained.')
        return
    source = Path(__file__).resolve().parent
    content = {LIB / name: ((source / name).read_text(), 0o644) for name in FILES}
    content[LAUNCHER] = (f'#!/bin/sh\nexec /usr/bin/python3 -B {LIB}/rotate.py "$@"\n', 0o755)
    content[AUTOSTART] = (f'''[Desktop Entry]
Type=Application
Name=Initialize screen rotation
Comment=Enable native rotation once for this user
Exec={LAUNCHER} session-enable
TryExec={LAUNCHER}
OnlyShowIn=KDE;GNOME;
Terminal=false
NoDisplay=true
''', 0o644)
    for path, (text, mode) in content.items():
        write(path, text, mode)
    write(manifest, json.dumps({str(p): digest(t) for p, (t, _) in content.items()}, indent=2), 0o644)
    for path, (text, _) in content.items():
        if path.read_text() != text or path.stat().st_uid != os.geteuid():
            raise RuntimeError('Installed file verification failed: ' + str(path))
    print('Installed:', LAUNCHER)
    print('All existing and future KDE/GNOME Wayland users receive native rotation setup at their next login.')
    print('No sessions restarted. Run linux-rotation session-enable as the current desktop user to apply now.')
