import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import boot_rotation as boot

DEFAULTS = 'ESP_PATH="/boot"\nKERNEL_CMDLINE[default]+="quiet splash root=UUID=test rootflags=subvol=/@"\n'
CONFIG = '''timeout: 5
/Linux
  //main
  protocol: linux
  path: boot():/kernel#abcdef
  module_path: boot():/initramfs#123456
  cmdline: quiet splash root=UUID=test rootflags=subvol=/@
  //lts
  protocol: linux
  cmdline: root=UUID=test rootflags=subvol=/@ quiet
  //Snapshots
    ///snapshot
    protocol: linux
    cmdline: root=UUID=test rootflags=subvol=/@/.snapshots/1/snapshot quiet
/Other Linux
protocol: linux
cmdline: root=UUID=other quiet
'''


class BootTests(unittest.TestCase):
    def test_file_apply_backup_undo_and_later_edit_protection(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            defaults, config, cmdline = (directory / name for name in ('defaults', 'config', 'cmdline'))
            defaults.write_text(DEFAULTS)
            config.write_text(CONFIG)
            cmdline.write_text('root=UUID=test rootflags=subvol=/@')
            args = SimpleNamespace(command='boot-enable', boot_config=str(config), output='DSI-1',
                                   menu_rotation=90, panel_orientation='right_side_up', console_rotation=1,
                                   dry_run=True)
            with patch.multiple(boot, DEFAULTS=defaults, BACKUP=directory / 'state/backup',
                                CMDLINE=cmdline, LOCK=directory / 'lock'), patch.object(boot, 'secure_boot_check'):
                boot.action(args)
                self.assertFalse(boot.BACKUP.exists())
                self.assertEqual(config.read_text(), CONFIG)
                args.dry_run = False
                boot.action(args)
                boot.action(args)
                applied = config.read_text()
                config.write_text(applied + '# later kernel update\n')
                args.command = 'boot-undo'
                with self.assertRaisesRegex(RuntimeError, 'changed since setup'):
                    boot.action(args)
                self.assertTrue(boot.BACKUP.exists())
                config.write_text(applied)
                boot.action(args)
                self.assertEqual(config.read_text(), CONFIG)
                self.assertEqual(defaults.read_text(), DEFAULTS)
                self.assertFalse(boot.BACKUP.exists())

    def plan(self, defaults=DEFAULTS, config=CONFIG):
        return boot.plan(defaults, config, 'root=UUID=test', 'DSI-1', 'right_side_up', 1, 90)

    def test_preserve_boot_paths_and_recovery_entries(self):
        defaults, config, count = self.plan()
        self.assertEqual(count, 2)
        self.assertTrue(config.startswith('interface_rotation: 90\n'))
        self.assertIn('root=UUID=test rootflags=subvol=/@', defaults)
        self.assertIn('path: boot():/kernel#abcdef', config)
        self.assertIn('module_path: boot():/initramfs#123456', config)
        self.assertIn('cmdline: root=UUID=test rootflags=subvol=/@/.snapshots/1/snapshot quiet\n', config)
        self.assertIn('cmdline: root=UUID=other quiet\n', config)
        self.assertEqual(config.count('fbcon=rotate:1'), 2)

    def test_idempotent(self):
        defaults, config, _ = self.plan()
        again = self.plan(defaults, config)
        self.assertEqual(again, (defaults, config, 2))

    def test_replaces_existing_rotation(self):
        before = 'root=x video=DSI-1:panel_orientation=left_side_up fbcon=rotate:3 quiet'
        after = boot.parameters(before, 'DSI-1', 'right_side_up', 1)
        self.assertEqual(after, 'root=x quiet video=DSI-1:panel_orientation=right_side_up fbcon=rotate:1')

    def test_rejects_combined_video_and_complex_defaults(self):
        with self.assertRaises(RuntimeError):
            boot.parameters('video=DSI-1:1200x1920,panel_orientation=normal', 'DSI-1', 'right_side_up', 1)
        for defaults in ['KERNEL_CMDLINE[default]="$CMDLINE"\n', 'KERNEL_CMDLINE[default]="foo"\n' * 2]:
            with self.assertRaises(RuntimeError):
                self.plan(defaults)

    def test_rejects_uki_and_missing_current_root(self):
        with self.assertRaises(RuntimeError):
            self.plan(config=CONFIG.replace('protocol: linux', 'protocol: efi'))
        with self.assertRaises(RuntimeError):
            self.plan(config=CONFIG.replace('root=UUID=test', 'root=UUID=other'))


if __name__ == '__main__':
    unittest.main()
