import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import rotate


class RotationTests(unittest.TestCase):
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
