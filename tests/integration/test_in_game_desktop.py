import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ConnectionState, LiveMatchStatus, LiveState, PlayerLiveStats, TeamGoldTotals
from game_phases.in_game.desktop import answer_in_game, describe_scoreboard, is_item_question
from knowledge.collector import connect, save
from knowledge.in_game import champion_profiles, item_catalog, team_composition
from ui.__main__ import HOME, INGAME, PICK, Window, collect_phase


def player(name, champion, team, position, items=(), kills=0, dead=False):
    return PlayerLiveStats(name, champion, team, position, 9, kills, 1, 2, 120, dead, 12.0 if dead else 0.0,
                           [{'itemID': item_id, 'slot': slot} for slot, item_id in enumerate(items)], 1000.0)


def context(active='Me#KR1'):
    board = [player('Enemy', 'Lux', 'ORDER', 'MIDDLE', kills=3),
             player('Buddy', 'Garen', 'CHAOS', 'TOP'),
             player('Me', 'Ahri', 'CHAOS', 'MIDDLE', items=[1056], dead=True)]
    return {'state': LiveState(LiveMatchStatus.IN_GAME, ConnectionState.CONNECTED, 610),
            'scoreboard': board, 'team_gold': TeamGoldTotals(order=5000, chaos=6500),
            'active_player_name': active}


class InGameDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        with closing(connect(self.db)) as db, db:
            for key, id_, name, tags, info in ((103, 'Ahri', '아리', ['Mage'], {'attack': 3, 'magic': 8}),
                                               (99, 'Lux', '럭스', ['Mage'], {'attack': 2, 'magic': 9}),
                                               (86, 'Garen', '가렌', ['Fighter', 'Tank'], {'attack': 7, 'magic': 1})):
                save(db, 'champion', '16.19.1', id_, name, json.dumps(
                    {'key': str(key), 'id': id_, 'name': name, 'blurb': name + ' 챔피언', 'tags': tags, 'info': info},
                    ensure_ascii=False), 'https://example.com/champion')
            for item_id, name, text, gold in (('1056', '도란의 반지', '주문력 +18 체력', 400),
                                              ('3157', '존야의 모래시계', '주문력 방어력 경직', 3250),
                                              ('3089', '라바돈의 죽음모자', '주문력 대폭 증가', 3500)):
                save(db, 'item', '16.19.1', item_id, name, json.dumps(
                    {'name': name, 'description': text, 'gold': {'total': gold}, 'maps': {'11': True}},
                    ensure_ascii=False), 'https://example.com/item')

    def test_scoreboard_uses_my_team_and_official_item_names(self):
        view = describe_scoreboard(context(), item_catalog(self.db))
        self.assertTrue(view['perspective_known'])
        self.assertEqual(view['clock'], '10:10')
        self.assertEqual(view['me']['champion'], 'Ahri')
        self.assertEqual([e['champion'] for e in view['allies']], ['Garen', 'Ahri'])
        self.assertEqual([e['champion'] for e in view['enemies']], ['Lux'])
        self.assertEqual(view['team_gold']['diff'], 1500)
        self.assertEqual(view['me']['items'][0]['name'], '도란의 반지')
        self.assertTrue(view['me']['is_dead'])
        self.assertEqual(view['me']['cs_per_min'], 11.8)

    def test_unknown_perspective_is_explicit(self):
        view = describe_scoreboard(context(active=None), {})
        self.assertFalse(view['perspective_known'])
        self.assertIsNone(view['me'])
        self.assertEqual([e['champion'] for e in view['allies']], ['Lux'])
        self.assertEqual(view['team_gold']['diff'], -1500)
        self.assertEqual(describe_scoreboard({'scoreboard': None}, {}), {'in_game': False})

    def test_composition_uses_only_official_tags(self):
        composition = team_composition(['럭스', 'Garen', '없는챔프'], champion_profiles(self.db))
        self.assertEqual(composition['damage_rating_counts'], {'AP': 1, 'AD': 1})
        self.assertEqual(composition['unverified_champions'], ['없는챔프'])

    def test_item_recommendation_prompt_excludes_owned_items_and_ids(self):
        view = describe_scoreboard(context(), item_catalog(self.db))
        generator = Mock(return_value={'text': '존야의 모래시계를 추천합니다.'})
        result = answer_in_game(self.db, view, '지금 뭐 사야 해?', generate=generator)
        self.assertTrue(result['generated'])
        payload = json.loads(generator.call_args.args[0]['user'])
        names = [item['name'] for item in payload['official_items']]
        self.assertIn('존야의 모래시계', names)
        self.assertNotIn('도란의 반지', names)
        self.assertEqual(payload['me']['items'], ['도란의 반지'])
        self.assertNotIn('1056', generator.call_args.args[0]['user'])
        self.assertIn('추정', payload['team_gold_estimate']['note'])

    def test_item_question_without_item_documents_does_not_call_model(self):
        view = describe_scoreboard(context(), {})
        generator = Mock()
        result = answer_in_game(Path(self.temp.name) / 'missing.db', view, '아이템 추천해줘', generate=generator)
        generator.assert_not_called()
        self.assertFalse(result['generated'])
        self.assertTrue(is_item_question('다음 템 뭐 가?'))

    def test_not_in_game_does_not_call_model(self):
        generator = Mock()
        result = answer_in_game(self.db, {'in_game': False}, '불리해?', generate=generator)
        generator.assert_not_called()
        self.assertIn('게임 중이 아닙니다', result['message'])

    @patch('ui.__main__.get_before_game_context', return_value=None)
    @patch('ui.__main__.get_gameflow_phase', return_value='InProgress')
    @patch('ui.__main__.get_live_state',
           return_value=LiveState(LiveMatchStatus.NOT_IN_GAME, ConnectionState.DISCONNECTED))
    def test_loading_screen_is_its_own_phase(self, _state, flow, _session):
        self.assertEqual(collect_phase(self.db), {'phase': 'loading'})
        flow.return_value = 'EndOfGame'
        self.assertEqual(collect_phase(self.db), {'phase': 'idle'})

    def test_window_follows_client_through_pick_loading_game_and_back(self):
        from contracts.riot import ChampSelectMember, ChampSelectSession
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
            window.champ_timer.stop()
            session = ChampSelectSession([ChampSelectMember(1, 103, 'middle', 'mine')], [], [], [], 1)
            champ_select = {'phase': 'champ_select', 'session': session, 'catalog': {}}
            window.navigate(3)
            window.on_phase(champ_select)
            self.assertEqual(window.stack.currentIndex(), PICK)
            window.on_phase({'phase': 'loading'})
            self.assertEqual(window.stack.currentIndex(), INGAME)
            view = describe_scoreboard(context(), item_catalog(self.db))
            window.on_phase({'phase': 'in_game', 'view': view})
            self.assertEqual(window.stack.currentIndex(), INGAME)
            self.assertEqual(window.in_game.clock.text(), '10:10')
            self.assertEqual(window.in_game.ally.rows[1].champion.text(), 'Ahri  (나)')
            self.assertEqual(window.in_game.ally.rows[1].player.text(), '부활까지 12초')
            window.navigate(3)
            window.on_phase({'phase': 'in_game', 'view': view})
            self.assertEqual(window.stack.currentIndex(), 3)   # 같은 단계 동안에는 사용자가 옮긴 화면을 유지
            window.navigate(INGAME)
            window.on_phase({'phase': 'idle'})
            self.assertEqual(window.stack.currentIndex(), HOME)
            self.assertEqual(window.in_game.clock.text(), '--:--')
            window.on_phase(champ_select)
            window.on_phase({'phase': 'idle'})   # 닷지
            self.assertEqual(window.stack.currentIndex(), HOME)
            if window.poll_job is not None:
                window.poll_job.wait(4000)
            window.close()


if __name__ == '__main__':
    unittest.main()
