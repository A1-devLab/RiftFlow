import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from game_phases.before_game.runes import JSON_CONFIG, format_explanation, parse_reply, recommend_runes
from knowledge.before_game import save_recent_matchups
from knowledge.collector import connect, rune_rows, save
from knowledge.runes import describe_page, ensure_rune_trees, rune_trees, validate_page
from rag.gemini import GeminiError
from ui.pages.before_game import BeforeGamePage

TREES = [
    {'id': 8000, 'key': 'Precision', 'name': '정밀', 'icon': 'perk-images/Styles/7201_Precision.png', 'slots': [
        {'runes': [{'id': 8005, 'name': '집중 공격'}, {'id': 8010, 'name': '정복자'}]},
        {'runes': [{'id': 9111, 'name': '승전보'}, {'id': 8009, 'name': '침착'}]},
        {'runes': [{'id': 9104, 'name': '전설: 민첩함'}, {'id': 9105, 'name': '전설: 강인함'}]},
        {'runes': [{'id': 8014, 'name': '최후의 일격'}, {'id': 8017, 'name': '체력차 극복'}]}]},
    {'id': 8100, 'key': 'Domination', 'name': '지배', 'icon': 'perk-images/Styles/7200_Domination.png', 'slots': [
        {'runes': [{'id': 8112, 'name': '감전'}, {'id': 8128, 'name': '어둠의 수확'}]},
        {'runes': [{'id': 8126, 'name': '비열한 한 방'}, {'id': 8139, 'name': '피의 맛'}]},
        {'runes': [{'id': 8136, 'name': '좀비 와드'}, {'id': 8120, 'name': '유령 포로'}]},
        {'runes': [{'id': 8135, 'name': '보물 사냥꾼'}, {'id': 8105, 'name': '끈질긴 사냥꾼'}]}]},
]
VALID = {'primary_style': 8100, 'keystone': 8112, 'primary': [8135, 8126, 8136],
         'secondary_style': 8000, 'secondary': [8014, 9111], 'shards': [5008, 5008, 5011],
         'summary': '짧은 교전에 강한 페이지입니다.',
         'reasons': [{'rune_id': 8112, 'reason': '감전은 짧은 연계에 추가 피해를 줍니다.'},
                     {'rune_id': 424242, 'reason': '페이지에 없는 룬'}]}
VIEW = {'mine': {'champion': '아리', 'position': 'middle', 'locked': True},
        'allies': [{'champion': '아리', 'position': 'middle', 'locked': True}],
        'enemies': [{'champion': '럭스', 'position': 'middle', 'locked': True},
                    {'champion': '선택 전', 'position': 'top', 'locked': False}],
        'ally_bans': [], 'enemy_bans': []}


def reply(page):
    return {'text': json.dumps(page, ensure_ascii=False)}


class RuneRecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        self.personal = Path(self.temp.name) / 'personal.db'
        with closing(connect(self.db)) as db, db:
            for rune_id, entity in rune_rows([dict(tree, slots=[{'runes': [dict(r, shortDesc='<b>%s</b> 효과' % r['name'])
                                                                           for r in slot['runes']]}
                                                                for slot in tree['slots']]) for tree in TREES]):
                save(db, 'rune', '16.19.1', rune_id, entity['name'], json.dumps(entity, ensure_ascii=False), 'https://example.com/runes')
            for key, id_, name, tags in ((103, 'Ahri', '아리', ['Mage']), (99, 'Lux', '럭스', ['Mage'])):
                save(db, 'champion', '16.19.1', id_, name, json.dumps(
                    {'key': str(key), 'id': id_, 'name': name, 'blurb': name + ' 스킬 설명', 'tags': tags,
                     'info': {'attack': 2, 'magic': 9}}, ensure_ascii=False), 'https://example.com/champion')
        self.trees = rune_trees(self.db)

    def test_collector_keeps_tree_and_slot_structure(self):
        self.assertEqual(sorted(self.trees), [8000, 8100])
        self.assertEqual([r['id'] for r in self.trees[8100]['slots'][0]], [8112, 8128])
        self.assertEqual(self.trees[8100]['name'], '지배')
        self.assertEqual(self.trees[8100]['slots'][0][0]['description'], '감전 효과')
        old = Path(self.temp.name) / 'old.db'
        with closing(connect(old)) as db, db:
            save(db, 'rune', '16.18.1', '8112', '감전', json.dumps({'id': 8112, 'name': '감전'}), 'https://example.com')
        self.assertIsNone(rune_trees(old))

    def test_missing_structure_is_downloaded_for_the_stored_version(self):
        old = Path(self.temp.name) / 'old.db'
        with closing(connect(old)) as db, db:
            save(db, 'rune', '16.18.1', '8112', '감전', json.dumps({'id': 8112, 'name': '감전'}), 'https://example.com')
        fetch = Mock(return_value=json.dumps(TREES, ensure_ascii=False))
        trees = ensure_rune_trees(old, fetch=fetch)
        self.assertEqual(sorted(trees), [8000, 8100])
        self.assertIn('/cdn/16.18.1/data/ko_KR/runesReforged.json', fetch.call_args.args[0])
        again = Mock()
        self.assertIsNotNone(ensure_rune_trees(old, fetch=again))
        again.assert_not_called()
        offline = Path(self.temp.name) / 'offline.db'
        self.assertIsNone(ensure_rune_trees(offline, fetch=Mock(side_effect=OSError('offline'))))

    def test_recommend_downloads_structure_only_when_allowed(self):
        old = Path(self.temp.name) / 'old.db'
        with closing(connect(old)) as db, db:
            save(db, 'rune', '16.19.1', '8112', '감전', json.dumps({'id': 8112, 'name': '감전'}), 'https://example.com')
        generate = Mock(return_value=reply(VALID))
        with patch('knowledge.collector.fetch', side_effect=OSError('offline')):
            failed = recommend_runes(old, self.personal, None, VIEW, generate=generate, download=True)
        self.assertIn('내려받지 못했습니다', failed['message'])
        with patch('knowledge.collector.fetch', return_value=json.dumps(TREES, ensure_ascii=False)) as fetch:
            demo = recommend_runes(old, self.personal, None, VIEW, generate=generate)
            fetch.assert_not_called()
            result = recommend_runes(old, self.personal, None, VIEW, generate=generate, download=True)
        self.assertIn('예시 자료에는', demo['message'])
        self.assertTrue(result['generated'])

    def test_valid_page_is_ordered_for_the_client(self):
        page, errors = validate_page(VALID, self.trees)
        self.assertEqual(errors, [])
        self.assertEqual(page['primary'], [8126, 8136, 8135])
        self.assertEqual(page['secondary'], [9111, 8014])
        self.assertEqual(page['selected_perk_ids'], [8112, 8126, 8136, 8135, 9111, 8014, 5008, 5008, 5011])
        described = describe_page(page, self.trees)
        self.assertEqual(described['keystone']['name'], '감전')
        self.assertEqual(described['shards'][2]['name'], '체력')

    def test_rule_violations_are_reported(self):
        cases = {
            'keystone': dict(VALID, keystone=8010),
            'row2에서 고르지 않음': dict(VALID, primary=[8126, 8139, 8135]),
            'secondary_style은': dict(VALID, secondary_style=8100, secondary=[8139, 8120]),
            'secondary의 8010': dict(VALID, secondary=[8010, 8014]),
            '서로 다른 줄(row)': dict(VALID, secondary=[8014, 8017]),
            '방어 줄': dict(VALID, shards=[5008, 5008, 5005]),
            '정수 ID 3개': dict(VALID, primary=[8126, 8136]),
        }
        for expected, page in cases.items():
            with self.subTest(expected):
                normalized, errors = validate_page(page, self.trees)
                self.assertIsNone(normalized)
                self.assertTrue(any(expected in error for error in errors), errors)
        self.assertEqual(validate_page([1, 2], self.trees), (None, ['응답이 JSON 객체가 아닙니다.']))

    def test_invalid_reply_is_retried_once_with_errors(self):
        save_recent_matchups(self.personal, 'mine', [{'metadata': {'matchId': 'KR_1'}, 'info': {
            'gameMode': 'CLASSIC', 'gameStartTimestamp': 1, 'participants': [
                {'puuid': 'mine', 'teamId': 100, 'teamPosition': 'MIDDLE', 'championName': 'Ahri', 'win': False,
                 'perks': {'styles': [{'style': 8000, 'selections': [{'perk': 8010}]}]}},
                {'puuid': 'x', 'teamId': 200, 'teamPosition': 'MIDDLE', 'championName': 'Lux'}]}}])
        generate = Mock(side_effect=[reply(dict(VALID, keystone=8010)), reply(VALID)])
        result = recommend_runes(self.db, self.personal, 'mine', VIEW, generate=generate,
                                 user_requests=['초반 운영 알려줘', '공격적으로 하고 싶어'])
        self.assertTrue(result['generated'])
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args.kwargs['config'], JSON_CONFIG)
        first = json.loads(generate.call_args_list[0].args[0]['user'])
        second = json.loads(generate.call_args_list[1].args[0]['user'])
        self.assertNotIn('previous_errors', first)
        self.assertTrue(any('keystone' in error for error in second['previous_errors']))
        self.assertEqual(first['opponent']['name'], '럭스')
        self.assertEqual(first['enemy_composition']['champions'][0]['champion'], '럭스')
        self.assertEqual(first['my_recent_pages'], [{'won': False, 'opponent': 'Lux',
                                                     'page': [{'tree': '정밀', 'runes': ['정복자']}]}])
        self.assertEqual(len(first['rune_catalog']), 2)
        self.assertEqual(sorted(first['rune_catalog'][0])[:3], ['keystones', 'row1', 'row2'])   # 줄 이름을 붙여 준다
        self.assertEqual(first['user_requests'], ['초반 운영 알려줘', '공격적으로 하고 싶어'])
        self.assertEqual(result['page']['primary'][0]['name'], '비열한 한 방')
        self.assertEqual(result['reasons'], [{'rune': '감전', 'reason': '감전은 짧은 연계에 추가 피해를 줍니다.'}])
        text = format_explanation(result)
        self.assertIn('감전: 감전은', text)
        self.assertIn('승률 통계가 아니라', text)

    def test_gives_up_after_third_invalid_reply(self):
        generate = Mock(return_value={'text': 'not json'})
        result = recommend_runes(self.db, self.personal, None, VIEW, generate=generate)
        self.assertIsNone(result['page'])
        self.assertEqual(generate.call_count, 3)
        self.assertIn('규칙에 맞는', result['message'])

    def test_missing_structure_or_champion_does_not_call_model(self):
        generate = Mock()
        missing = recommend_runes(Path(self.temp.name) / 'none.db', self.personal, None, VIEW, generate=generate)
        self.assertIn('예시 자료에는', missing['message'])
        empty = recommend_runes(self.db, self.personal, None, {'mine': None}, generate=generate)
        self.assertIn('챔피언', empty['message'])
        generate.assert_not_called()

    def test_model_error_is_reported(self):
        generate = Mock(side_effect=GeminiError('한도 초과'))
        result = recommend_runes(self.db, self.personal, None, VIEW, generate=generate)
        self.assertEqual(result['message'], '한도 초과')
        self.assertFalse(result['generated'])

    def test_parse_reply_accepts_fenced_json(self):
        self.assertEqual(parse_reply('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertIsNone(parse_reply('[1, 2]'))

    def test_page_preview_and_stale_champion(self):
        page = BeforeGamePage()
        requests = []
        page.runeRequested.connect(requests.append)
        page.request_runes()
        self.assertEqual(requests, [])
        page.champion.setText('아리')
        page.request_runes()
        self.assertEqual(requests[0]['champion'], '아리')
        normalized, _ = validate_page(VALID, self.trees)
        page.show_rune_result({'page': describe_page(normalized, self.trees)}, '아리')
        self.assertEqual(page.rune_view.stack.currentIndex(), 1)
        self.assertEqual(page.rune_view.primary.slots[0].name.text(), '감전')
        self.assertEqual(page.rune_view.secondary.style_name.text(), '정밀')
        self.assertEqual(page.rune_view.shards[0].text(), '공격 · 적응형 능력치')
        page.champion.setText('럭스')
        self.assertEqual(page.rune_view.stack.currentIndex(), 0)
        self.assertIn('챔피언이 바뀌었습니다', page.rune_view.placeholder.text())
        page.close()


if __name__ == '__main__':
    unittest.main()
