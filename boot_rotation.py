"""Conservative boot rotation for limine-entry-tool managed, non-UKI Linux entries."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

DEFAULTS = Path('/etc/default/limine')
BACKUP = Path('/var/lib/linux-rotation/boot-backup.json')
CMDLINE = Path('/proc/cmdline')
LOCK = Path('/run/lock/boot-partition.lock')


def parameters(text, output, panel, console):
    """Change only rotation tokens; preserve other command-line bytes."""
    video = f'video={output}:panel_orientation={panel}'
    # A combined resolution/video argument needs manual handling, not replacement.
    for token in text.split():
        if token.startswith(f'video={output}:') and not re.fullmatch(
                re.escape(f'video={output}:panel_orientation=') + r'[a-z_]+', token):
            raise RuntimeError('Existing combined video argument requires manual review: ' + token)
    text = re.sub(r'(?:^|[ \t]+)video=' + re.escape(output) + r':panel_orientation=\S+', '', text)
    text = re.sub(r'(?:^|[ \t]+)fbcon=rotate:[0-3](?!\S)', '', text)
    return text.rstrip() + ' ' + video + f' fbcon=rotate:{console}'


def plan(defaults, config, root, output, panel, console, menu):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', output):
        raise RuntimeError('Invalid connector name.')
    # Only documented, simple command-line assignments. Never execute configuration as shell.
    pattern = r'(?m)^(KERNEL_CMDLINE\[[^\]\n]+\]\+?=)([^\n]*)$'
    assignments = list(re.finditer(pattern, defaults))
    if not assignments or not any(m[1].startswith('KERNEL_CMDLINE[default]') for m in assignments):
        raise RuntimeError('Expected an explicit KERNEL_CMDLINE[default] assignment in /etc/default/limine.')
    keys = [m[1].split(']')[0] for m in assignments]
    if len(keys) != len(set(keys)):
        raise RuntimeError('Repeated kernel assignments need manual review.')
    def assignment(m):
        value = m[2].strip()
        quote = value[0] if value and value[0] in ('"', "'") else ''
        if quote:
            if not value.endswith(quote) or quote in value[1:-1]:
                raise RuntimeError('Complex quoted kernel assignment is unsupported.')
            value = value[1:-1]
        if any(c in value for c in ('$', '`', '\\', '#')):
            raise RuntimeError('Complex kernel assignment is unsupported.')
        return m[1] + quote + parameters(value, output, panel, console) + quote
    new_defaults = re.sub(pattern, assignment, defaults)
    lines = config.splitlines(keepends=True)
    first_entry = next((i for i, line in enumerate(lines) if line.lstrip().startswith('/')), len(lines))
    header = ''.join(lines[:first_entry])
    if re.search(r'(?mi)^\s*graphics:\s*no\s*$', header):
        raise RuntimeError('Limine is configured for text mode; interface rotation requires graphics.')
    header = re.sub(r'(?mi)^interface_rotation:.*\n?', '', header)
    header = f'interface_rotation: {menu}\n' + header
    changed = 0
    protocol = None
    for i in range(first_entry, len(lines)):
        line = lines[i]
        if line.lstrip().startswith('/'):
            protocol = None
        p = re.match(r'\s*protocol:\s*(\S+)', line)
        if p:
            protocol = p[1]
        m = re.match(r'(\s*(?:cmdline|kernel_cmdline):\s*)(.*?)(\n?)$', line)
        if not m or root not in m[2].split() or '/.snapshots/' in m[2]:
            continue
        if protocol != 'linux':
            raise RuntimeError('Only non-UKI protocol: linux entries are supported.')
        lines[i] = m[1] + parameters(m[2], output, panel, console) + m[3]
        changed += 1
    if not changed:
        raise RuntimeError('No non-snapshot Linux entries match the running root device.')
    return new_defaults, header + ''.join(lines[first_entry:]), changed


def write(path, content):
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix='.rotation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def secure_boot_check():
    directory = Path('/sys/firmware/efi/efivars')
    if Path('/sys/firmware/efi').exists():
        files = list(directory.glob('SecureBoot-*'))
        if len(files) != 1:
            raise RuntimeError('Cannot determine Secure Boot state; no boot changes made.')
        value = files[0].read_bytes()
        if len(value) != 5 or value[4] != 0:
            raise RuntimeError('Secure Boot enabled/unknown: enrolled Limine config needs its signing workflow; unsupported here.')


def action(args):
    config = Path(args.boot_config)
    if not config.is_absolute():
        raise RuntimeError('--boot-config must be an absolute path.')
    for path in (config, DEFAULTS, BACKUP):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise RuntimeError('Refusing symlink in boot configuration path: ' + str(path))
    if not DEFAULTS.is_file() or not config.is_file():
        raise RuntimeError('Boot commands require /etc/default/limine and an existing Limine config.')
    if args.command == 'boot-status':
        print('Limine config:', config, '\nDefaults:', DEFAULTS, '\nBackup:', BACKUP if BACKUP.exists() else 'none')
        for path in (DEFAULTS, config):
            for line in path.read_text().splitlines():
                if re.search(r'KERNEL_CMDLINE|interface_rotation:|^\s*(?:kernel_)?cmdline:', line):
                    print(line)
        print('Running kernel:', CMDLINE.read_text().strip())
        return
    secure_boot_check()
    # Share the lock used by CachyOS's limine-entry-tool wrappers.
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another boot configuration operation is running; retry later.')
        if args.command == 'boot-undo':
            if not BACKUP.exists():
                raise RuntimeError('No boot backup created by this script.')
            saved = json.loads(BACKUP.read_text())
            if set(saved) != {str(config), str(DEFAULTS)}:
                raise RuntimeError('Backup paths differ; use the original --boot-config.')
            for path in (DEFAULTS, config):
                if path.read_text() != saved[str(path)]['applied']:
                    raise RuntimeError(f'{path} changed since setup. Refusing to overwrite later kernel/config updates; '
                                       f'use the original/applied texts in {BACKUP} for a selective rollback.')
            for path in (DEFAULTS, config):
                write(path, saved[str(path)]['original'])
            BACKUP.unlink()
            print('Original boot configuration restored. No reboot performed.')
            return
        if None in (args.menu_rotation, args.panel_orientation, args.console_rotation) or not args.output:
            raise RuntimeError('boot-enable requires --output, --menu-rotation, --panel-orientation and --console-rotation.')
        current = CMDLINE.read_text()
        roots = [token for token in current.split() if token.startswith('root=')]
        if len(roots) != 1 or '/.snapshots/' in current:
            raise RuntimeError('Run from a normal installed system, not a snapshot or live environment.')
        old = {str(path): path.read_text() for path in (DEFAULTS, config)}
        default_text, config_text, count = plan(old[str(DEFAULTS)], old[str(config)], roots[0],
                                              args.output, args.panel_orientation, args.console_rotation,
                                              args.menu_rotation)
        new = {str(DEFAULTS): default_text, str(config): config_text}
        print(f'Plan: {count} installed Linux entries, menu {args.menu_rotation}, '
              f'panel {args.panel_orientation}, console {args.console_rotation}. Snapshots untouched.')
        if args.dry_run:
            print('Dry run: no files changed.')
            return
        if BACKUP.exists():
            saved = json.loads(BACKUP.read_text())
            if set(saved) != set(old) or any(saved[p]['applied'] != old[p] for p in old):
                raise RuntimeError('Boot files changed since previous setup. Review the existing backup before proceeding.')
        else:
            saved = {p: {'original': text, 'applied': text} for p, text in old.items()}
        BACKUP.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(BACKUP.parent, 0o700)
        write(BACKUP, json.dumps(saved, indent=2))
        try:
            for path in (DEFAULTS, config):
                write(path, new[str(path)])
            for path in (DEFAULTS, config):
                if path.read_text() != new[str(path)]:
                    raise RuntimeError('Boot configuration read-back verification failed.')
            for p in saved:
                saved[p]['applied'] = new[p]
            write(BACKUP, json.dumps(saved, indent=2))
        except Exception:
            for path in (DEFAULTS, config):
                write(path, old[str(path)])
            raise
        print('Boot configuration saved and verified. Backup:', BACKUP)
        print('No kernel images rebuilt and no reboot performed. Verify all stages after your next reboot.')
