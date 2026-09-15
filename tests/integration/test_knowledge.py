import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from knowledge.collector import Page, connect, save, update, PATCH_LIST


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / 'nested/demo.db')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)
        self.html = (ROOT / 'tests/fixtures/knowledge_patch.html').read_text(encoding='utf-8')

    def fake_fetch(self, url):
        if url.endswith('versions.json'):
            return '["16.18.1"]'
        if url.endswith('champion.json') or url.endswith('item.json'):
            return json.dumps({'data': {'1': {'name': '가상 대상', 'id': '1'}}})
        if url.endswith('runesReforged.json'):
            return '[{"slots":[{"runes":[{"id":1,"name":"가상 룬"}]}]}]'
        if url == PATCH_LIST:
            return '<a href="/ko-kr/news/game-updates/patch-26-18-notes/">패치</a>'
        return self.html

    def test_parser_excludes_scripts_and_navigation(self):
        page = Page(self.html)
        self.assertIn('26.18 패치 노트', page.heading)
        self.assertNotIn('hidden javascript', page.main)
        self.assertNotIn('메뉴', page.main)

    def test_sync_is_repeatable(self):
        with patch('knowledge.collector.fetch', side_effect=self.fake_fetch), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(update(self.db, 3)['new'], 4)
            self.assertEqual(update(self.db, 3)['unchanged'], 4)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 4)

    def test_changes_and_new_versions(self):
        with self.db:
            self.assertEqual(save(self.db, 'item', '1', '1', '이름', 'old', 'https://example.com'), 'new')
            self.assertEqual(save(self.db, 'item', '1', '1', '이름', 'new', 'https://example.com'), 'updated')
            self.assertEqual(save(self.db, 'item', '2', '1', '이름', 'new', 'https://example.com'), 'new')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)

    def test_failure_rolls_back_new_rows(self):
        with self.db:
            save(self.db, 'item', 'old', '1', '이전', '유지', 'https://example.com')
        def fail_at_listing(url):
            if url == PATCH_LIST:
                raise OSError('가상 연결 실패')
            return self.fake_fetch(url)
        with patch('knowledge.collector.fetch', side_effect=fail_at_listing), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                update(self.db, 3)
        self.assertEqual(self.db.execute('SELECT version FROM records').fetchall(), [('old',)])


if __name__ == '__main__':
    unittest.main()
