import argparse
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import rotate


class RotationTests(unittest.TestCase):
    def test_login_changes_only_selected_output(self):
        data = [{'name': 'outputs', 'data': [
            {'connectorName': 'DSI-1', 'transform': 'Normal', 'autoRotation': 'Always', 'scale': 1.45},
            {'connectorName': 'HDMI-1', 'transform': 'Normal'}]}, {'name': 'setups', 'data': []}]
        result = rotate.login_config(data, 'DSI-1', 270)
        self.assertEqual(result[0]['data'][0], {'connectorName': 'DSI-1', 'transform': 'Rotated270',
                                               'autoRotation': 'Never', 'scale': 1.45})
        self.assertEqual(result[0]['data'][1], {'connectorName': 'HDMI-1', 'transform': 'Normal'})
        with self.assertRaises(RuntimeError):
            rotate.login_config(data, 'missing', 90)

    def test_login_backup_repeat_and_undo(self):
        for existed in (True, False):
            with self.subTest(existed=existed), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                target = root / '.config/kwinoutputconfig.json'
                target.parent.mkdir()
                original = '[{"name":"outputs","data":[{"connectorName":"DSI-1","transform":"Normal"}]}]\n'
                source = root / 'source.json'
                source.write_text(original)
                if existed:
                    target.write_text(original)
                account = SimpleNamespace(pw_dir=d, pw_uid=os.getuid(), pw_gid=os.getgid())
                args = SimpleNamespace(command='login-enable', output='DSI-1', rotation=270, source=str(source))
                with patch.object(rotate, 'LOGIN_STATE', root / 'state/backup.json'), \
                     patch.object(rotate, 'login_target', return_value=(target, account)), \
                     patch.object(rotate.os, 'chown'):
                    rotate.login_action(args)
                    first = rotate.LOGIN_STATE.read_text()
                    args.rotation = 90
                    rotate.login_action(args)
                    self.assertEqual(rotate.LOGIN_STATE.read_text(), first)
                    args.command = 'login-undo'
                    rotate.login_action(args)
                    self.assertEqual(target.exists(), existed)
                    if existed:
                        self.assertEqual(target.read_text(), original)
                    self.assertFalse(rotate.LOGIN_STATE.exists())

    def test_login_rejects_symlink_and_other_manager(self):
        with patch.object(rotate.Path, 'resolve', return_value=Path('/usr/lib/systemd/system/gdm.service')):
            with self.assertRaisesRegex(RuntimeError, 'supports Plasma Login Manager only'):
                rotate.login_target()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'kwinoutputconfig.json'
            target.symlink_to(Path(d) / 'somewhere')
            account = SimpleNamespace(pw_dir=d)
            with patch.object(rotate, 'login_target', return_value=(target, account)):
                with self.assertRaisesRegex(RuntimeError, 'Refusing symlink'):
                    rotate.login_action(SimpleNamespace(command='login-status'))

    def test_session_detection_never_uses_xrandr_on_wayland(self):
        for desktop, session, expected in [('XFCE', 'x11', 'x11'), ('COSMIC', 'wayland', 'cosmic'),
                                           ('KDE', 'wayland', 'kde'), ('GNOME', 'wayland', 'gnome'),
                                           ('XFCE', 'wayland', 'wlr')]:
            with self.subTest(desktop=desktop, session=session), patch.dict(
                    os.environ, {'XDG_CURRENT_DESKTOP': desktop, 'XDG_SESSION_TYPE': session}, clear=True):
                self.assertEqual(rotate.backend(), expected)

    def test_cosmic_mode_and_transform_parsing(self):
        fixture = '''output "DSI-1" enabled=#true {
  transform "rotate270"
  modes {
    mode 1200 1920 50002 current=#true preferred=#true
  }
}
output "HDMI-A-1" enabled=#false {
}
'''
        with patch.object(rotate, 'run', return_value=fixture):
            o = rotate.outputs('cosmic')[0]
        with patch.object(rotate, 'run') as run:
            rotate.transform('cosmic', o, 90)
            run.assert_called_once_with('cosmic-randr', 'mode', 'DSI-1', '1200', '1920',
                                        '--refresh', '50.002', '--transform', 'rotate90')
        with patch.object(rotate, 'run', return_value='output "DSI-1" enabled=#true {\n}'):
            with self.assertRaises(RuntimeError):
                rotate.outputs('cosmic')

    def test_x11_rotation_parsing_and_restore(self):
        fixture = ('DSI-1 connected primary 1920x1200+0+0 right (normal left inverted right x axis y axis)\n'
                   'HDMI-1 disconnected (normal left inverted right x axis y axis)\n')
        with patch.object(rotate, 'run', return_value=fixture):
            o = rotate.outputs('x11')[0]
        self.assertEqual(o['transform'], 'right')
        with patch.object(rotate, 'run') as run:
            rotate.transform('x11', o)
            run.assert_called_once_with('xrandr', '--output', 'DSI-1', '--rotate', 'right')

    def test_kde_backup_is_idempotent_and_undo_restores(self):
        old = {'name': 'DSI-1', 'rotation': 8, 'autoRotatePolicy': 0}
        new = dict(old, autoRotatePolicy=2)
        with tempfile.TemporaryDirectory() as d, patch.object(rotate, 'STATE', Path(d)), \
                patch.object(rotate, 'run') as run:
            with patch.object(rotate, 'outputs', side_effect=[[old], [new], [new], [new]]):
                rotate.native('kde', None)
                rotate.native('kde', None)
            self.assertEqual(json.loads(rotate.statefile('kde').read_text()), old)
            with patch.object(rotate, 'outputs', return_value=[new]):
                rotate.undo('kde')
            run.assert_called_with('kscreen-doctor', 'output.DSI-1.autoRotatePolicy.never',
                                   'output.DSI-1.rotation.right')
            self.assertFalse(rotate.statefile('kde').exists())

    def test_ambiguous_panels_and_multi_monitor_watch_rejected(self):
        items = [{'name': 'DSI-1'}, {'name': 'eDP-1'}]
        with self.assertRaises(RuntimeError):
            rotate.choose(items)
        args = argparse.Namespace(output='DSI-1', touch=None, offset=0)
        with patch.object(rotate, 'outputs', return_value=items), patch.object(rotate, 'run') as run:
            with self.assertRaises(RuntimeError):
                rotate.watch('cosmic', args)
            run.assert_not_called()

    def test_wlr_and_sway_commands(self):
        o = {'name': 'eDP-1', 'transform': 'normal'}
        with patch.object(rotate, 'run', return_value='[{"success": true}]') as run:
            rotate.transform('sway', o, 270)
            run.assert_called_with('swaymsg', '-r', 'output', 'eDP-1', 'transform', '270')
            rotate.transform('wlr', o, 90)
            run.assert_called_with('wlr-randr', '--output', 'eDP-1', '--transform', '90')
        with patch.object(rotate, 'run', return_value='[{"success": false}]'):
            with self.assertRaises(RuntimeError):
                rotate.transform('sway', o, 90)


if __name__ == '__main__':
    unittest.main()
