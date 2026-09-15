"""Focused regressions for stream copy, conversion fallback and file protection."""
import array
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import audio


class MP3CopyTests(unittest.TestCase):
    def test_copy_order_payload_and_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / "first '\\ file\n.mp3", root / 'second.mp3']
            for path, hz in zip(paths, [330, 770]):
                subprocess.run([audio.tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                                f'sine=frequency={hz}:duration=1', '-c:a', 'libmp3lame', str(path)], check=True)
            before = [hashlib.sha256(p.read_bytes()).digest() for p in paths]
            items = audio.inspect(paths)
            events = []
            output = root / 'merged.mp3'
            with patch.object(audio, 'copy_mp3', wraps=audio.copy_mp3) as copying:
                audio.merge(items, output, events.append)
                self.assertEqual(copying.call_count, 1)
            self.assertFalse(any('compatibility' in e.get('message', '') for e in events))
            self.assertEqual(events[-1]['event'], 'complete')
            # Packet hashes establish copying rather than another lossy encode.
            def packets(path):
                import json
                result = subprocess.check_output([audio.tool('ffprobe'), '-v', 'error',
                    '-select_streams', 'a:0', '-show_packets', '-show_data_hash', 'sha256',
                    '-show_entries', 'packet=data_hash', '-of', 'json', str(path)])
                return [p['data_hash'] for p in json.loads(result)['packets']]
            self.assertEqual(packets(output), packets(paths[0]) + packets(paths[1]))
            raw = subprocess.check_output([audio.tool('ffmpeg'), '-v', 'error', '-i', str(output),
                '-ac', '1', '-ar', '8000', '-f', 'f32le', 'pipe:1'])
            samples = array.array('f'); samples.frombytes(raw)
            for start, expected in [(0.3, 330), (1.4, 770)]:
                window = samples[int(start*8000):int((start+.3)*8000)]
                hz = sum(a <= 0 < b for a, b in zip(window, window[1:])) / .3
                self.assertLess(abs(hz-expected), 5)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                audio.merge(items, output, events.append)
            with patch.object(audio, 'copy_mp3', return_value=None):
                audio.merge(items, root / 'fallback.mp3', events.append)
            self.assertTrue(any('compatibility' in e.get('message', '') for e in events))
            # Bad frame-duration evidence must fall back, then fail the existing
            # per-input decoded-duration guard instead of publishing lost audio.
            with self.assertRaisesRegex(RuntimeError, 'could be read'):
                audio.merge([{**items[0], 'duration': 600}, items[1]], root / 'short.mp3', events.append)
            self.assertFalse((root / 'short.mp3').exists())
            self.assertEqual(before, [hashlib.sha256(p.read_bytes()).digest() for p in paths])
            self.assertFalse(list(root.glob('.smart-audio-merge-*')))
            self.assertFalse(audio.CHILDREN)
            def cancel(event):
                if event.get('fraction', 0) > 0:
                    raise KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                audio.merge(items, root / 'cancelled.mp3', cancel)
            self.assertFalse((root / 'cancelled.mp3').exists())
            self.assertFalse(list(root.glob('.smart-audio-merge-*')))
            self.assertFalse(audio.CHILDREN)

    def test_compatibility_selection(self):
        item = {'codec': 'mp3', 'sample_rate': 44100, 'channels': 2, 'duration': 1}
        self.assertTrue(audio.can_copy_mp3([item, item], Path('out.MP3')))
        for field, value in [('codec', 'aac'), ('sample_rate', 48000), ('channels', 1), ('duration', 0)]:
            self.assertFalse(audio.can_copy_mp3([item, {**item, field: value}], Path('out.mp3')))
        self.assertFalse(audio.can_copy_mp3([item, item], Path('out.m4a')))


if __name__ == '__main__':
    unittest.main()
