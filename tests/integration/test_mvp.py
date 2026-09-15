import json
import tempfile
import unittest
from pathlib import Path
from knowledge.collector import connect, save
from knowledge.documents import get_documents
from game_phases.before_game.prompt import SYSTEM as BEFORE_SYSTEM, build as build_before
from ui.services import ask_database, create_demo


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db.sqlite'

    def insert(self, version='16.18.1', price=3500):
        db = connect(self.path)
        with db:
            save(db, 'item', version, '3031', '무한의 대검',
                 json.dumps({'name': '무한의 대검', 'description': '공격력과 치명타를 제공합니다.',
                             'gold': {'total': price, 'base': 725}, 'from': ['1038'],
                             'maps': {'11': True}}), 'https://ddragon.leagueoflegends.com/example')
        db.close()

    def test_real_collector_schema_reaches_rag(self):
        self.insert()
        docs = get_documents('16.18.1', 'item', db_path=self.path)
        self.assertEqual(docs[0]['fields']['gold_total'], 3500)
        self.assertIn('3500', docs[0]['text'])
        result = ask_database(self.path, '무한의 대검 가격 알려줘')
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['generated'])
        self.assertIn('3500', result['prompt']['user'])
        self.assertTrue(result['sources'])

    def test_no_guessed_patch_conversion(self):
        self.insert()
        self.assertEqual(get_documents('26.18', 'item', db_path=self.path), [])

    def test_latest_version_numeric_and_hotfix_visible(self):
        self.insert('16.9.1', 1000)
        self.insert('16.18.1', 3500)
        self.assertEqual(get_documents(kind='item', db_path=self.path)[0]['fields']['gold_total'], 3500)
        ask_database(self.path, '무한의 대검 가격 알려줘')
        self.insert('16.18.1', 3600)
        self.assertIn('3600', ask_database(self.path, '무한의 대검 가격 알려줘')['prompt']['user'])

    def test_missing_database_does_not_create_file(self):
        self.assertEqual(get_documents(db_path=self.path), [])
        self.assertFalse(self.path.exists())
        result = ask_database(self.path, '롤 아이템 가격 알려줘')
        self.assertNotEqual(result['status'], 'ready')

    def test_example_mode_with_mock_model(self):
        create_demo(self.path)
        calls = []
        def model(prompt):
            calls.append(prompt)
            return {'text': '테스트 답변 [근거 1]', 'usage': {}}
        result = ask_database(self.path, '무한의 대검 가격 알려줘', generate=model)
        self.assertTrue(result['generated'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['sources'])

    def test_before_game_uses_its_own_prompt_and_context(self):
        create_demo(self.path)
        analysis = {'champion': '아리', 'opponent': '가렌',
                    'playstyle': {'trade_preference': '순간',
                                  'lane_aggression': '공격적'}}
        result = ask_database(self.path, '아리 룬을 추천해줘', analysis=analysis,
                              prompt_builder=build_before)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['prompt']['system'], BEFORE_SYSTEM)
        self.assertIn('상대 챔피언: 가렌', result['prompt']['user'])
        self.assertIn('선호하는 라인전: 공격적', result['prompt']['user'])

    def test_selected_short_champion_establishes_before_game_context(self):
        create_demo(self.path)
        result = ask_database(self.path, '룬과 초반 운영 추천',
                              analysis={'champion': '아리'},
                              prompt_builder=build_before)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['reason'], '선택된 챔피언: 아리')

    def test_other_map_item_filtered(self):
        db = connect(self.path)
        with db:
            save(db, 'item', '16.18.1', '9999', '다른 모드', json.dumps({'maps': {'11': False}}), 'https://example.com')
        db.close()
        self.assertEqual(get_documents(db_path=self.path), [])
