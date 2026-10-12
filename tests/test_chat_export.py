"""Behavioral export tests use synthetic messages only."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import export_chat as export
import archive_render as render


class ExportTests(unittest.TestCase):
    def test_group_resolution_handles_emoji_and_rejects_ambiguity(self):
        self.assertEqual(export.choose_chat('Study 38', [{'chat': '📈 STUDY38 ✨', 'username': 'one@chatroom'}]), 'one@chatroom')
        with self.assertRaises(RuntimeError):
            export.choose_chat('Study', [{'chat': 'Study 38', 'username': 'one'}, {'chat': 'Study 39', 'username': 'two'}])

    def test_fixed_window_expands_limit_without_dropping_same_second_rows(self):
        all_rows = [{'local_id': i, 'timestamp': 1700000000, 'content': str(i)} for i in range(501)]
        requested = []
        def fake(args):
            requested.append(args)
            limit = int(args[args.index('-n') + 1])
            return json.dumps({'messages': all_rows[-limit:], 'meta': {'unknown_shards': []}})
        with patch.object(export, 'run', side_effect=fake):
            data = export.fetch_messages('wx', 'synthetic@chatroom', 1699999900, 1700000100)
        self.assertEqual(len(data['messages']), 501)
        self.assertEqual(len({m['local_id'] for m in data['messages']}), 501)
        self.assertEqual([a[a.index('--after') + 1] for a in requested], ['1700000101'] * 2)
        self.assertEqual([a[a.index('--before') + 1] for a in requested], ['1699999899'] * 2)

    def test_local_dst_ambiguity_requires_explicit_offset(self):
        zone = ZoneInfo('America/Los_Angeles')
        with self.assertRaises(ValueError):
            export.parse_time('2026-11-01T01:30:00', zone)
        with self.assertRaises(ValueError):
            export.parse_time('2026-03-08T02:30:00', zone)
        a = export.parse_time('2026-11-01T01:30:00-07:00', zone)
        b = export.parse_time('2026-11-01T01:30:00-08:00', zone)
        self.assertEqual(b - a, 3600)

    def test_untrusted_filename_cannot_escape_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(export.file_matches(root, '../../private.txt'), [])
            self.assertEqual(export.file_matches(root, '/private.txt'), [])

    def test_render_keeps_all_rows_quotes_warnings_and_offline_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'archive'
            out.mkdir()
            (out / 'attachments').mkdir()
            (out / 'attachments/image.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            raw = '<msg><appmsg><title>Full reply</title><refermsg><displayname>Alice</displayname><content>Full quoted text\nsecond line</content></refermsg></appmsg></msg>'
            data = {'chat': '<script>untrusted()</script>', 'meta': {}, 'messages': [
                {'local_id': 1, 'timestamp': 1700000000, 'sender': 'Alice', 'content': '<img src=x onerror=alert(1)>', 'type_id': 'text'},
                {'local_id': 1, 'timestamp': 1700000001, 'sender': 'Bob', 'content': '[quote]', 'appmsg_type': 57, 'original': {'message_content': raw}},
            ], 'export': {'start': 1699999900, 'end': 1700000100, 'timezone': 'America/Los_Angeles',
                         'missing_shards': ['message_2.db'], 'warnings': [],
                         'attachments': [{'index': 1, 'kind': 'image', 'status': 'exported', 'preview_file': 'attachments/image.png'}]}}
            result = render.render_archive(data, out)
            content = Path(result['html']).read_text()
            class Inspect(HTMLParser):
                def __init__(self): super().__init__(); self.messages = []; self.scripts = 0; self.images = []
                def handle_starttag(self, name, attrs):
                    attrs = dict(attrs)
                    if name == 'script': self.scripts += 1
                    if name == 'article': self.messages.append(attrs['id'])
                    if name == 'img': self.images.append(attrs['src'])
            inspector = Inspect(); inspector.feed(content)
            self.assertEqual(inspector.scripts, 1)
            self.assertEqual(inspector.messages, ['msg-1', 'msg-2'])
            self.assertTrue(all(src.startswith('data:image/') for src in inspector.images))
            self.assertIn('Full quoted text\nsecond line', content)
            self.assertIn('Missing database key: message_2.db', content)
            self.assertNotIn('<script>untrusted()', content)
            with zipfile.ZipFile(result['zip']) as stream:
                self.assertIsNone(stream.testzip())
                self.assertIn('archive/messages.json', stream.namelist())


if __name__ == '__main__':
    unittest.main()
