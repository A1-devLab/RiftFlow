"""증바람 증강 추천도: 증강 목록 만들기, 비율 계산, 모델 답 검증, 서버 API, 인게임 화면."""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from knowledge import augments as catalog
from game_phases.in_game.augments import NOT_WIN_RATE, recommend_augments, split_percent, validate
from game_phases.in_game.desktop import prompt_player

HAS_SERVER = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
LISTS = [{'modeName': 'CHERRY', 'augmentList': ['Maps/ModeSpecificData/Augments/ArenaOnly']},
         {'modeName': 'KIWI', 'augmentList': ['Maps/ModeSpecificData/Augments/ARAM_BigBrain',
                                              'Maps/ModeSpecificData/Augments/Overloaded',
                                              'Maps/ModeSpecificData/Augments/ARAM_BangBang',
                                              'Maps/ModeSpecificData/Augments/Duplicate',
                                              'Maps/ModeSpecificData/Augments/NoText']}]
AUGMENTS = [
    {'id': 1180, 'augmentNameId': 'ARAM_BigBrain', 'nameTRA': '전술적 대비', 'rarity': 'kGold',
     'augmentSmallIconPath': '/lol-game-data/assets/ASSETS/UX/Cherry/Augments/Icons/BigBrain_small.png'},
    {'id': 1200, 'augmentNameId': 'Overloaded', 'nameTRA': '과충전', 'rarity': 'kPrismatic'},
    {'id': 1300, 'augmentNameId': 'ARAM_BangBang', 'nameTRA': '초장거리 저격', 'rarity': 'kSilver'},
    {'id': 1400, 'augmentNameId': 'Duplicate', 'nameTRA': '과충전', 'rarity': 'kSilver'},
    {'id': 1500, 'augmentNameId': 'NoText', 'nameTRA': '헤비', 'rarity': 'kSilver'},
    {'id': 9, 'augmentNameId': 'ArenaOnly', 'nameTRA': '아레나 전용', 'rarity': 'kGold'},
]
STRINGS = {'entries': {
    'kiwi_bigbrain_tooltip': '<shield>@TotalShield@의 보호막</shield>을 얻습니다.<br>사망 시 초기화됩니다.',
    'cherry_bigbrain_tooltip': '각 라운드 시작 시 보호막 (아레나 설명이라 쓰면 안 됨)',
    'augment_overloaded_tooltip': '{{Augment_Overloaded_Summary}} 초기화 효율: @Rate*100@%',
    'augment_overloaded_summary': '다른 스킬 사용 시 재사용 대기시간이 초기화됩니다.',
    'augment_bangbang_tooltip': '{{Augment_BangBang_Tooltip}} 빵야! 멋진 사격이군요!',
}}


def fake_get(url):
    name = url.rsplit('/', 1)[-1]
    return json.dumps({'augment-lists.json': LISTS, 'cherry-augments.json': AUGMENTS,
                       'lol.stringtable.json': STRINGS}[name], ensure_ascii=False)


OFFERED = [{'id': 1180, 'name': '전술적 대비', 'rarity': '골드', 'description': '보호막을 얻습니다.'},
           {'id': 1200, 'name': '과충전', 'rarity': '프리즘', 'description': '재사용 대기시간이 초기화됩니다.'},
           {'id': 1300, 'name': '초장거리 저격', 'rarity': '실버', 'description': ''}]
VIEW = {'in_game': True, 'clock': '07:10', 'game_mode': 'KIWI', 'mode_name': '증바람',
        'me': {'champion': '럭스', 'level': 7, 'kda': '2/1/3', 'items': [{'id': 6655, 'name': '루덴의 메아리'}], 'is_me': True},
        'allies': [{'champion': '럭스', 'is_me': True}, {'champion': '가렌'}], 'enemies': [{'champion': '제드'}]}


def reply(options, summary='앞라인이 약하면 1번'):
    return {'text': json.dumps({'options': options, 'summary': summary}, ensure_ascii=False)}


class CatalogTests(unittest.TestCase):
    def test_kiwi_list_names_rarity_and_official_text(self):
        built = {a['name']: a for a in catalog.build_catalog(get=fake_get)}
        self.assertEqual(list(built), ['전술적 대비', '과충전', '초장거리 저격', '헤비'])   # 아레나 전용, 같은 이름은 빠짐
        self.assertEqual(built['전술적 대비']['rarity'], '골드')
        # 증바람 설명을 아레나 설명보다 먼저 쓰고, 서식과 변수 자리를 걷어 낸다
        self.assertEqual(built['전술적 대비']['description'], '(수치)의 보호막을 얻습니다. 사망 시 초기화됩니다.')
        self.assertEqual(built['과충전']['description'], '다른 스킬 사용 시 재사용 대기시간이 초기화됩니다. 초기화 효율: (수치)%')
        self.assertEqual(built['초장거리 저격']['description'], '빵야! 멋진 사격이군요!')      # 자기 참조는 한 번만
        self.assertEqual(built['헤비']['description'], '')
        self.assertTrue(built['전술적 대비']['icon'].endswith('/assets/ux/cherry/augments/icons/bigbrain_small.png'))

    def test_cache_is_reused_for_a_day_and_kept_when_download_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = catalog.catalog_path(folder)
            now = [1000.0]
            first = catalog.ensure_catalog(path, get=fake_get, clock=lambda: now[0])
            self.assertEqual(len(first), 4)
            broken = Mock(side_effect=OSError('offline'))
            now[0] += 60
            self.assertEqual(catalog.ensure_catalog(path, get=broken, clock=lambda: now[0]), first)
            broken.assert_not_called()                         # 하루가 안 지났으면 받지 않는다
            now[0] += catalog.MAX_AGE
            self.assertEqual(catalog.ensure_catalog(path, get=broken, clock=lambda: now[0]), first)   # 실패하면 예전 목록
            broken.assert_called()


class RecommendationTests(unittest.TestCase):
    def test_percent_keeps_valid_answers_and_fixes_the_rest(self):
        self.assertEqual(split_percent([40, 30, 30]), [40, 30, 30])
        self.assertEqual(split_percent([100, 0, 0]), [90, 5, 5])       # 한 증강에 몰아주지 않는다
        self.assertEqual(sum(split_percent([50, 30, 10])), 100)
        self.assertEqual(split_percent([0, 0]), [50, 50])

    def test_validate_accepts_names_and_rejects_missing_or_unknown(self):
        options, errors = validate({'options': [{'augment_id': '1200', 'percent': 50, 'reason': 'a'},
                                                {'name': '전술적 대비', 'percent': 30, 'reason': 'b'},
                                                {'augment_id': 1300, 'percent': 20, 'reason': 'c'}]}, OFFERED)
        self.assertEqual(errors, [])
        self.assertEqual([(o['name'], o['percent']) for o in options],
                         [('과충전', 50), ('전술적 대비', 30), ('초장거리 저격', 20)])
        options, errors = validate({'options': [{'augment_id': 1180, 'percent': 60, 'reason': 'a'},
                                                {'augment_id': 77, 'percent': 40, 'reason': 'b'}]}, OFFERED)
        self.assertIsNone(options)
        self.assertTrue(any('offered에 없습니다' in e for e in errors))
        self.assertTrue(any('과충전' in e for e in errors))

    def test_retries_once_then_returns_shares_that_are_not_win_rates(self):
        generate = Mock(side_effect=[
            reply([{'augment_id': 1180, 'percent': 100, 'reason': '보호막'}]),
            reply([{'augment_id': 1180, 'percent': 45, 'reason': '제드 돌진을 보호막으로 버팀'},
                   {'augment_id': 1200, 'percent': 35, 'reason': '스킬 연사로 견제'},
                   {'augment_id': 1300, 'percent': 20, 'reason': '효과 정보 부족'}])])
        result = recommend_augments('missing.db', VIEW, OFFERED, generate=generate, prompt_player=prompt_player)
        self.assertTrue(result['generated'])
        self.assertEqual([o['percent'] for o in result['options']], [45, 35, 20])
        self.assertEqual(result['basis'], NOT_WIN_RATE)
        self.assertIn('증강 추천도: 전술적 대비 45%', result['answer'])
        second = json.loads(generate.call_args_list[1].args[0]['user'])
        self.assertTrue(second['previous_errors'])
        self.assertEqual([a['augment_id'] for a in second['offered']], [1180, 1200, 1300])
        self.assertEqual(second['me']['items'], ['루덴의 메아리'])
        self.assertIn('승률이나 통계가 아니므로', generate.call_args_list[0].args[0]['system'])

    def test_needs_two_or_three_different_augments(self):
        generate = Mock()
        for offered in (OFFERED[:1], OFFERED + [{'id': 5, 'name': 'x'}], [OFFERED[0], OFFERED[0]]):
            result = recommend_augments('missing.db', VIEW, offered, generate=generate, prompt_player=prompt_player)
            self.assertFalse(result['generated'])
        generate.assert_not_called()


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
class ServerAugmentTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        from test_server_ai import knowledge_db
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        knowledge = knowledge_db(self.temp.name)
        path = catalog.catalog_path(Path(knowledge).parent)
        path.write_text(json.dumps({'mode': 'KIWI', 'fetched_at': time.time(), 'augments': OFFERED},
                                   ensure_ascii=False), encoding='utf-8')
        settings = Settings(riot_api_key='test', db_path=str(Path(self.temp.name) / 'server.db'),
                            knowledge_db_path=str(knowledge), device_daily_ai=5)
        self.generate = Mock(return_value=reply([{'augment_id': 1180, 'percent': 50, 'reason': 'a'},
                                                 {'augment_id': 1200, 'percent': 50, 'reason': 'b'}]))
        self.http = TestClient(create_app(settings, gateway=Mock(), generate=self.generate))
        self.auth = {'Authorization': 'Bearer ' + self.http.post('/v1/devices').json()['token']}

    def test_catalog_and_recommendation_endpoints(self):
        listed = self.http.get('/v1/augments', headers=self.auth)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([a['name'] for a in listed.json()['augments']], ['전술적 대비', '과충전', '초장거리 저격'])
        answer = self.http.post('/v1/coach/augments', json={'augment_ids': [1180, 1200], 'view': VIEW}, headers=self.auth)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual([o['percent'] for o in answer.json()['options']], [50, 50])
        self.assertEqual(self.http.post('/v1/coach/augments', json={'augment_ids': [1180]}, headers=self.auth).status_code, 422)
        self.assertEqual(self.http.get('/v1/augments').status_code, 401)


class AugmentCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_pick_by_name_request_and_show_shares(self):
        from ui.pages.in_game import AugmentCard
        card = AugmentCard()
        card.set_catalog(OFFERED)
        sent = []
        card.requested.connect(sent.append)
        card.choices[0].setEditText('과충전')
        card.request()
        self.assertEqual(sent, [])                               # 하나만 고르면 보내지 않는다
        self.assertIn('2개 이상', card.caption.text())
        card.choices[1].setEditText('전술적 대비')
        card.choices[2].setEditText('없는 증강')
        card.request()
        self.assertEqual(sent, [[1200, 1180]])
        card.show_result({'options': [{'name': '과충전', 'rarity': '프리즘', 'percent': 60, 'reason': '연사'},
                                      {'name': '전술적 대비', 'rarity': '골드', 'percent': 40, 'reason': '버팀'}],
                          'summary': '요약'})
        self.assertEqual(card.picks[0].percent.text(), '60%')
        self.assertTrue(card.picks[2].isHidden())
        self.assertIn('승률 아님', card.basis.text())
        card.close()

    def test_mayhem_game_opens_the_augment_tab_once(self):
        from ui.pages.in_game import InGamePage
        page = InGamePage()
        page.portraits.attach = page.assets.attach = Mock()
        self.assertEqual(page.side_stack.currentIndex(), 0)
        page.show_view(dict(VIEW, allies=[], enemies=[]))
        self.assertEqual(page.side_stack.currentIndex(), 1)
        page.show_tab(0)
        page.show_view(dict(VIEW, allies=[], enemies=[]))
        self.assertEqual(page.side_stack.currentIndex(), 0)      # 사용자가 바꾸면 다시 넘기지 않는다
        requested = []
        page.augmentRequested.connect(requested.append)
        page.augments.set_catalog(OFFERED)
        page.augments.choices[0].setEditText('과충전')
        page.augments.choices[1].setEditText('초장거리 저격')
        page.augments.request()
        self.assertEqual(requested[0]['augment_ids'], [1200, 1300])
        self.assertEqual(requested[0]['view']['game_mode'], 'KIWI')
        page.close()


if __name__ == '__main__':
    unittest.main()
