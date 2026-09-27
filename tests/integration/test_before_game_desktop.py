import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from contracts.riot import ChampSelectMember, ChampSelectSession
from game_phases.before_game.desktop import describe_session, opponent_for_lane, answer_before_game
from knowledge.before_game import champion_catalog, personal_context, save_recent_matchups, rune_catalog, named_rune_page, canonical_champion
from knowledge.collector import connect, save
from ui.__main__ import Window


def sample_detail(match_id='KR_1'):
    return {'metadata': {'matchId': match_id}, 'info': {'gameMode': 'CLASSIC', 'gameStartTimestamp': 123000,
        'participants': [
            {'puuid': 'mine', 'teamId': 100, 'teamPosition': 'MIDDLE', 'championName': 'Ahri',
             'win': True, 'kills': 8, 'deaths': 2, 'assists': 9,
             'perks': {'styles': [{'style': 8000, 'selections': [{'perk': 8005}]}]}},
            {'puuid': 'enemy', 'teamId': 200, 'teamPosition': 'MIDDLE', 'championName': 'Lux'},
        ]}}


class BeforeGameDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # .env의 실제 Gemini 키로 자동 룬 추천이 호출되지 않게 한다. 키가 필요한 테스트는 직접 넣는다.
        env = patch.dict(os.environ, {'GEMINI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        self.personal = Path(self.temp.name) / 'personal.db'
        with closing(connect(self.db)) as db, db:
            import json
            for key, id_, name in ((103, 'Ahri', '아리'), (99, 'Lux', '럭스')):
                save(db, 'champion', '16.19.1', id_, name,
                     json.dumps({'key': str(key), 'id': id_, 'name': name, 'blurb': name + ' 챔피언'}, ensure_ascii=False), 'https://example.com/champion')
            save(db, 'rune', '16.19.1', '8005', '집중 공격',
                 json.dumps({'id': 8005, 'name': '집중 공격', 'shortDesc': '공격 효과'}, ensure_ascii=False), 'https://example.com/runes')

    def test_pick_ban_position_and_personal_matchup(self):
        catalog = champion_catalog(self.db)
        session = ChampSelectSession(
            [ChampSelectMember(1, 103, 'middle', 'mine')],
            [ChampSelectMember(6, 99, 'middle', None)], [103], [99], 1)
        view = describe_session(session, catalog)
        self.assertEqual(view['mine']['champion'], '아리')
        self.assertEqual(canonical_champion(self.db, '아리'), 'Ahri')
        self.assertEqual(opponent_for_lane(view), '럭스')
        hidden = ChampSelectSession(session.my_team, [ChampSelectMember(6, 0, 'middle', None)], [], [], 1)
        self.assertIsNone(opponent_for_lane(describe_session(hidden, catalog)))
        self.assertEqual(view['ally_bans'], ['아리'])
        save_recent_matchups(self.personal, 'mine', [sample_detail(), sample_detail()])
        record = personal_context(self.personal, 'mine', 'Ahri', 'Lux', 'middle')
        self.assertEqual((record['matchup_games'], record['matchup_wins']), (1, 1))
        self.assertEqual(named_rune_page(record['latest_rune_page'], rune_catalog(self.db))[0]['runes'], ['집중 공격'])
        self.assertEqual(personal_context(self.personal, 'other', 'Ahri', 'Lux')['matchup_games'], 0)

    def test_hovered_champion_counts_as_mine_before_lock(self):
        from riot import lcu_client
        catalog = champion_catalog(self.db)
        raw = {'myTeam': [{'cellId': 1, 'championId': 0, 'championPickIntent': 7, 'assignedPosition': 'middle'},
                          {'cellId': 2, 'championId': 103, 'assignedPosition': 'top'}],
               'theirTeam': [{'cellId': 6, 'championId': 99, 'assignedPosition': 'middle'}],
               'actions': [[{'type': 'pick', 'actorCellId': 2, 'completed': False, 'championId': 103},
                            {'type': 'pick', 'actorCellId': 6, 'completed': True, 'championId': 99}]],
               'localPlayerCellId': 1}
        session = lcu_client._parse_champ_select_session(raw)
        self.assertEqual(session.locked_cell_ids, (6,))
        view = describe_session(session, {**catalog, 7: {'id': 'Leblanc', 'name': '르블랑'}})
        self.assertEqual(view['mine']['champion'], '르블랑')
        self.assertTrue(view['mine']['hovering'])
        self.assertFalse(view['mine']['locked'])
        self.assertTrue(view['allies'][1]['hovering'])      # 내 차례에 올려놓기만 한 아군
        self.assertTrue(view['enemies'][0]['locked'])
        self.assertEqual(opponent_for_lane(view), '럭스')
        aram = lcu_client._parse_champ_select_session({'myTeam': [{'cellId': 1, 'championId': 103}],
                                                       'theirTeam': [], 'actions': [], 'localPlayerCellId': 1})
        self.assertIsNone(aram.locked_cell_ids)
        self.assertTrue(describe_session(aram, catalog)['mine']['locked'])

    def test_prompt_uses_verified_sources_and_small_sample(self):
        save_recent_matchups(self.personal, 'mine', [sample_detail()])
        view = {'mine': {'champion': 'Ahri', 'position': 'middle'}, 'allies': [], 'enemies': [],
                'ally_bans': [], 'enemy_bans': []}
        generator = Mock(return_value={'text': '게임 전 답변'})
        result = answer_before_game(self.db, self.personal, 'mine', view, '초반 운영?',
                                    champion='아리', opponent='럭스', generate=generator)
        self.assertTrue(result['generated'])
        import json
        prompt = json.loads(generator.call_args.args[0]['user'])
        self.assertEqual(prompt['personal_observations']['matchup_games'], 1)
        self.assertEqual(prompt['personal_observations']['latest_rune_page'][0]['runes'], ['집중 공격'])
        self.assertTrue(prompt['official_references'])

    def test_window_has_live_before_game_navigation(self):
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
            self.assertEqual([b.text() for b in window.nav_buttons],
                             ['전적', '픽창', '인게임', 'AI에게 질문', '설정 및 데이터'])
            session = ChampSelectSession([ChampSelectMember(1, 103, 'middle', 'mine')],
                                         [], [], [], 1)
            window.on_phase({'phase': 'champ_select', 'session': session,
                             'catalog': {103: {'id': 'Ahri', 'name': '아리'}}})
            self.assertEqual(window.stack.currentIndex(), 1)
            self.assertEqual(window.before_game.champion.text(), '아리')
            hover = ChampSelectSession([ChampSelectMember(1, 0, 'middle', 'mine', champion_pick_intent=7)],
                                       [], [], [], 1, locked_cell_ids=())
            window.on_phase({'phase': 'champ_select', 'session': hover,
                             'catalog': {7: {'id': 'Leblanc', 'name': '르블랑'}}})
            self.assertEqual(window.before_game.champion.text(), '르블랑')
            self.assertIn('(선택 중)', window.before_game.ally.text())
            window.before_game.show_disconnected()
            window.before_game.champion.setText('직접 입력한 챔피언')
            window.before_game.show_disconnected()
            self.assertEqual(window.before_game.champion.text(), '직접 입력한 챔피언')
            window.champ_timer.stop()
            if window.poll_job is not None:
                window.poll_job.wait(4000)
            window.close()

    def test_auto_recommend_waits_for_a_stable_pick_and_uses_cache(self):
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}), \
             patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}):
            window = Window(Path(self.temp.name) / 'ui')
            window.champ_timer.stop()
            requested = []
            def fake_request(request):
                requested.append(request['champion'])
                window.rune_shown_key = window.rune_key(request)
                return True
            window.request_runes = fake_request
            window.before_game.champion.setText('르블랑')
            window.maybe_auto_recommend()
            self.assertEqual(requested, [])                 # 첫 폴링: 아직 올려 보는 중일 수 있음
            window.maybe_auto_recommend()
            self.assertEqual(requested, ['르블랑'])
            window.maybe_auto_recommend()
            self.assertEqual(requested, ['르블랑'])         # 같은 조건은 다시 부르지 않음
            window.before_game.champion.setText('아리')
            cached = {'page': None, 'message': '캐시된 결과', 'generated': True}
            window.rune_cache[window.rune_key(window.before_game._request())] = cached
            window.maybe_auto_recommend()
            window.maybe_auto_recommend()
            self.assertEqual(requested, ['르블랑'])         # 캐시가 있으면 호출하지 않음
            self.assertIn('캐시된 결과', window.before_game.answer.toPlainText())
            if window.poll_job is not None:
                window.poll_job.wait(4000)
            window.close()
