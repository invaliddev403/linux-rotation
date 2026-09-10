import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import rotate
import system_install as installer


class SystemTests(unittest.TestCase):
    def test_install_upgrade_uninstall_and_collision(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.multiple(installer, LIB=root / 'lib', LAUNCHER=root / 'bin/linux-rotation',
                                AUTOSTART=root / 'autostart/linux-rotation.desktop'), patch.object(installer.os, 'chown'):
                installer.action('install-system')
                self.assertIn('session-enable', installer.AUTOSTART.read_text())
                self.assertEqual(installer.LAUNCHER.stat().st_mode & 0o777, 0o755)
                installer.action('install-system')
                original = installer.AUTOSTART.read_text()
                installer.AUTOSTART.write_text(original + '# user edit\n')
                with self.assertRaisesRegex(RuntimeError, 'locally modified'):
                    installer.action('uninstall-system')
                installer.AUTOSTART.write_text(original)
                installer.action('uninstall-system')
                self.assertFalse(installer.AUTOSTART.exists())
                self.assertFalse(installer.LAUNCHER.exists())

    def test_each_user_initializes_once(self):
        for user in ('existing', 'new'):
            with self.subTest(user=user), tempfile.TemporaryDirectory() as d, \
                 patch.object(rotate, 'STATE', Path(d)), patch.object(rotate, 'backend', return_value='kde'), \
                 patch.object(rotate, 'sensor_check'), patch.object(rotate, 'native') as native:
                rotate.session_enable()
                rotate.session_enable()
                native.assert_called_once_with('kde', None)

    def test_failed_setup_retries_without_marking_done(self):
        with tempfile.TemporaryDirectory() as d, patch.object(rotate, 'STATE', Path(d)), \
             patch.object(rotate, 'backend', return_value='gnome'), patch.object(rotate, 'sensor_check'), \
             patch.object(rotate, 'native', side_effect=RuntimeError('not ready')) as native, \
             patch.object(rotate.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                rotate.session_enable()
            self.assertEqual(native.call_count, 6)
            self.assertFalse((Path(d) / 'system-setup-gnome.done').exists())


if __name__ == '__main__':
    unittest.main()
