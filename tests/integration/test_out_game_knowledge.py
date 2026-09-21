import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from knowledge import get_documents, get_patch_changes, sync_patch
from knowledge.collector import connect, save, store_patch
from knowledge.patches import direction, parse_patch


HTML = '''<main><h1>25.18 패치 노트</h1>
<p>이 문서는 테스트를 위해 작성한 가상 패치입니다. 실제 게임 수치가 아닙니다.</p>
<h2 id="patch-champions">챔피언</h2>
<h3 class="change-title" id="patch-a">가상 챔피언 A</h3>
<p class="summary">공격력이 증가합니다.</p><h4>기본 능력치</h4>
<ul><li><strong>공격력</strong>: 50 ⇒ <strong>55</strong></li></ul>
<h3 class="change-title" id="patch-b">가상 챔피언 B</h3><h4>Q</h4>
<ul><li>재사용 대기시간: 8초 → 10초</li></ul>
<h3 class="change-title" id="patch-c">가상 챔피언 C</h3><h4>W</h4>
<ul><li>피해량: 10/20 ⇒ 15/18</li><li>새로운 시각 효과가 추가됩니다.</li></ul>
<h2 id="patch-items">아이템</h2>
<h3 class="change-title" id="patch-item">가상 검</h3>
<ul><li>공격력: 20 ⇒ 25</li></ul>
<h2 id="patch-runes">룬</h2>
<h3 class="change-title" id="patch-rune">가상 룬</h3>
<ul><li>회복량: 10 ⇒ 8</li></ul>
<h2 id="patch-aram">무작위 총력전</h2>
<h3 class="change-title">다른 모드 챔피언</h3><ul><li>공격력: 1 ⇒ 100</li></ul>
</main>'''


class OutGameKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db.sqlite'
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.url = 'https://www.leagueoflegends.com/ko-kr/news/game-updates/patch-25-18-notes/'

    def store(self, html=HTML):
        with self.db:
            return store_patch(self.db, html, self.url)

    def test_extract_types_values_and_ignore_other_modes(self):
        changes = parse_patch(HTML)
        self.assertEqual(len(changes), 5)
        self.assertEqual([c['change_type'] for c in changes], ['buff', 'nerf', 'adjusted', 'buff', 'nerf'])
        self.assertEqual(changes[0]['changes'][0]['before'], '50')
        self.assertEqual(changes[0]['changes'][0]['after'], '55')
        self.assertEqual(changes[2]['changes'][1]['parse_status'], 'unparsed')
        self.assertIsNone(changes[2]['changes'][1]['before'])
        self.assertEqual(direction('피해량', '10 (+주문력 20%)', '20 (+주문력 10%)'), 'adjusted')
        self.assertEqual(direction('공격력', '61 + 레벨당 3.3', '58 + 레벨당 3.3'), 'nerf')
        self.assertEqual(direction('재사용 대기시간', '11/10/9초', '11초'), 'nerf')
        self.assertEqual(direction('체력 회복량', '공격력 100당 2%', '공격력 200당 2%'), 'unknown')

    def test_query_and_rag_metadata(self):
        self.store()
        buffs = get_patch_changes('25.18', kind='champion', change_type='buff', db_path=self.path)
        self.assertEqual(len(buffs), 1)
        self.assertIsNone(buffs[0]['sample_match_count'])
        self.assertTrue(buffs[0]['collected_at'].endswith('+00:00'))
        docs = get_documents('25.18', 'patch', db_path=self.path)
        self.assertEqual(len(docs), 6)
        for doc in docs:
            for field in ('data_type', 'patch_version', 'collected_at', 'sample_match_count', 'source', 'source_url'):
                self.assertIn(field, doc)
        self.assertTrue(any('버프 상향' in doc['text'] for doc in docs))

    def test_repeated_update_and_hotfix_replaces_old_values(self):
        self.assertEqual(self.store(), 'new')
        self.assertEqual(self.store(), 'unchanged')
        self.store(HTML.replace('55</strong>', '60</strong>'))
        changes = get_patch_changes(name='가상 챔피언 A', db_path=self.path)
        self.assertEqual(changes[0]['changes'][0]['after'], '60')
        self.assertEqual(len(get_patch_changes(db_path=self.path)), 5)

    def test_transaction_and_parser_regression_keep_previous_data(self):
        self.store()
        with self.assertRaises(RuntimeError), self.db:
            store_patch(self.db, HTML.replace('55</strong>', '70</strong>'), self.url)
            raise RuntimeError('later download failure')
        self.assertEqual(get_patch_changes(name='가상 챔피언 A', db_path=self.path)[0]['changes'][0]['after'], '55')
        with self.assertRaises(ValueError):
            self.store('<main><h1>25.18 패치 노트</h1>' + '본문 구조 변경 ' * 100 + '</main>')
        self.assertEqual(len(get_patch_changes(db_path=self.path)), 5)

    def test_static_metadata_refresh_without_content_change(self):
        with self.db:
            save(self.db, 'item', '15.18.1', '1', '검', json.dumps({'description': '설명'}), self.url)
            self.db.execute("UPDATE records SET collected_at='old'")
        old = self.db.execute('SELECT updated_at FROM records').fetchone()[0]
        with self.db:
            self.assertEqual(save(self.db, 'item', '15.18.1', '1', '검', json.dumps({'description': '설명'}), self.url), 'unchanged')
        doc = get_documents(kind='item', db_path=self.path)[0]
        self.assertNotEqual(doc['collected_at'], 'old')
        self.assertEqual(doc['updated_at'], old)
        self.assertEqual(get_documents('25.18', 'item', db_path=self.path), [])

    def test_old_database_migration(self):
        old_path = Path(self.tmp.name) / 'old.db'
        with closing(sqlite3.connect(old_path)) as old, old:
            old.execute('CREATE TABLE records(kind TEXT, version TEXT, entity_id TEXT, name TEXT, content TEXT, source_url TEXT, content_hash TEXT, updated_at TEXT, PRIMARY KEY(kind,version,entity_id))')
            old.execute("INSERT INTO records VALUES ('patch','25.1','1','title','old','url','hash','time')")
        db = connect(old_path)
        try:
            row = db.execute('SELECT content, collected_at, sample_match_count FROM records').fetchone()
            self.assertEqual(row, ('old', None, None))
        finally:
            db.close()

    def test_sync_validates_version_before_writing(self):
        with patch('knowledge.collector.fetch', return_value=HTML):
            result = sync_patch('25.18', db_path=self.path)
            self.assertEqual(result['entity_count'], 5)
            with self.assertRaises(ValueError):
                sync_patch('25.19', db_path=self.path)
        self.assertEqual(get_patch_changes('25.19', db_path=self.path), [])

    def test_empty_missing_and_filters(self):
        missing = Path(self.tmp.name) / 'missing.db'
        self.assertEqual(get_patch_changes(db_path=missing), [])
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            get_patch_changes(change_type='invalid', db_path=self.path)

    def test_new_article_slug_fallback(self):
        with patch('knowledge.collector.fetch', side_effect=[HTTPError(self.url, 404, 'missing', {}, None), HTML]) as fetch:
            result = sync_patch('25.18', db_path=self.path)
        self.assertIn('/league-of-legends-patch-', result['source_url'])
        self.assertEqual(fetch.call_count, 2)

    def test_latest_documents_do_not_mix_older_structured_patch(self):
        self.store()
        with self.db:
            save(self.db, 'patch', '25.19', 'new', '25.19 패치', '새 원문', self.url)
        docs = get_documents(kind='patch', db_path=self.path)
        self.assertTrue(docs)
        self.assertEqual({d['version'] for d in docs}, {'25.19'})


if __name__ == '__main__':
    unittest.main()
