"""Pick-phase chat preferences, game modes, automatic rune apply, portraits and profile icon."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ChampSelectMember, ChampSelectSession, PlayerIdentity
from game_phases.before_game.desktop import answer_before_game, describe_session
from game_phases.before_game.runes import recommend_runes
from riot import lcu_client
from ui.__main__ import PICK, Window
from ui.match_assets import MatchAssets
from ui.pages.before_game import BeforeGamePage
from ui.pages.out_game import OutGamePage

PAGE = {'primary_style': {'id': 8100, 'name': '지배'}, 'keystone': {'id': 8112, 'name': '감전'},
        'primary': [{'id': 8126, 'name': '비열한 한 방'}, {'id': 8136, 'name': '좀비 와드'}, {'id': 8135, 'name': '보물 사냥꾼'}],
        'secondary_style': {'id': 8000, 'name': '정밀'},
        'secondary': [{'id': 9111, 'name': '승전보'}, {'id': 8014, 'name': '최후의 일격'}],
        'shards': [{'id': 5008, 'name': '적응형 능력치', 'row': '공격'}, {'id': 5008, 'name': '적응형 능력치', 'row': '유연'},
                   {'id': 5011, 'name': '체력', 'row': '방어'}],
        'selected_perk_ids': [8112, 8126, 8136, 8135, 9111, 8014, 5008, 5008, 5011]}


class PickChatAndModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'GEMINI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)

    def test_chat_routes_rune_talk_to_recommendation_and_remembers_preferences(self):
        page = BeforeGamePage()
        asked, runes = [], []
        page.askRequested.connect(asked.append)
        page.runeRequested.connect(runes.append)
        self.assertFalse(hasattr(page, 'trade') or hasattr(page, 'aggression'))
        page.champion.setText('르블랑')
        page.question.setText('초반 운영 어떻게 해?')
        page.submit()
        page.question.setText('공격적으로 하고 싶어, 룬 다시 짜줘')
        page.submit()
        self.assertEqual(len(asked), 1)
        self.assertEqual(runes[0]['user_requests'], ['초반 운영 어떻게 해?', '공격적으로 하고 싶어, 룬 다시 짜줘'])
        self.assertEqual(page.question.text(), '')
        page.reset_conversation()
        self.assertEqual(page._request()['user_requests'], [])
        page.close()

    def test_coach_answer_receives_earlier_messages(self):
        db = Path(self.temp.name) / 'game.db'
        from knowledge.collector import connect, save
        from contextlib import closing
        with closing(connect(db)) as conn, conn:
            save(conn, 'champion', '16.19.1', 'Leblanc', '르블랑', json.dumps(
                {'key': '7', 'id': 'Leblanc', 'name': '르블랑', 'blurb': '기만의 마법사'}, ensure_ascii=False), 'https://x')
        generate = Mock(return_value={'text': '답'})
        answer_before_game(db, Path(self.temp.name) / 'p.db', None, {'mine': {'champion': '르블랑'}}, '초반은?',
                           generate=generate, user_requests=['공격적으로 하고 싶어', '초반은?'])
        payload = json.loads(generate.call_args.args[0]['user'])
        self.assertEqual(payload['earlier_messages'], ['공격적으로 하고 싶어'])
        self.assertNotIn('playstyle', payload)

    def test_game_mode_is_read_and_arena_skips_runes(self):
        raw = {'myTeam': [{'cellId': 1, 'championId': 7}], 'theirTeam': [], 'actions': [], 'localPlayerCellId': 1}
        flow = {'gameData': {'queue': {'id': 450, 'gameMode': 'ARAM'}}}
        with patch.object(lcu_client, '_find_lcu_credentials', return_value=(1, 's')), \
             patch.object(lcu_client, '_lcu_get', side_effect=lambda p, w, endpoint: raw if 'champ-select' in endpoint else flow):
            session = lcu_client.get_champ_select_session()
        self.assertEqual((session.game_mode, session.queue_id), ('ARAM', 450))
        view = describe_session(session, {7: {'id': 'Leblanc', 'name': '르블랑'}})
        self.assertEqual(view['mode_name'], '칼바람 나락')
        generate = Mock()
        arena = dict(view, game_mode='CHERRY', mode_name='아레나')
        result = recommend_runes(Path(self.temp.name) / 'x.db', None, None, arena, generate=generate)
        generate.assert_not_called()
        self.assertIn('아레나는 룬 페이지를 쓰지 않는', result['message'])

    def test_pick_lists_show_portraits_and_hover_state(self):
        page = BeforeGamePage()
        page.portraits.attach = Mock()
        session = ChampSelectSession([ChampSelectMember(1, 0, 'middle', 'mine', champion_pick_intent=7),
                                      ChampSelectMember(2, 0, 'top', None)],
                                     [ChampSelectMember(6, 99, 'middle', None)], [], [], 1, locked_cell_ids=(6,))
        page.show_session(describe_session(session, {7: {'id': 'Leblanc', 'name': '르블랑'},
                                                     99: {'id': 'Lux', 'name': '럭스'}}))
        self.assertEqual(page.ally.text(), 'middle  ·  르블랑  (선택 중)\ntop  ·  선택 전')
        attached = [call.args[1] for call in page.portraits.attach.call_args_list]
        self.assertEqual(attached, ['Leblanc', 'Lux'])      # 고르기 전 칸에는 초상화를 요청하지 않음
        page.show_session(describe_session(session, {7: {'id': 'Leblanc', 'name': '르블랑'},
                                                     99: {'id': 'Lux', 'name': '럭스'}}))
        self.assertEqual(page.portraits.attach.call_count, 2)   # 같은 챔피언이면 다시 요청하지 않음
        page.show_disconnected()
        self.assertEqual(page.enemy.text(), '상대 선택 전')
        page.close()

    def test_recommendation_is_applied_automatically_once_in_champ_select(self):
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
            window.champ_timer.stop()
            window.apply_runes = Mock()
            window.phase = 'champ_select'
            result = {'page': PAGE, 'summary': None, 'reasons': [], 'generated': True, 'version': '16.19.1'}
            key = ('르블랑', '', None)
            window.show_rune_recommendation(result, '르블랑', key)
            window.apply_runes.assert_called_once()
            self.assertTrue(window.apply_runes.call_args.args[0]['auto'])
            window.rune_applied_page = PAGE
            window.show_rune_recommendation(result, '르블랑', key)       # 캐시된 같은 페이지
            self.assertEqual(window.apply_runes.call_count, 1)
            window.phase = 'idle'
            window.show_rune_recommendation(dict(result, page=dict(PAGE)), '르블랑', key)
            self.assertEqual(window.apply_runes.call_count, 1)          # 픽창 밖에서는 자동 적용하지 않음
            window.close()

    def test_failed_auto_apply_asks_for_the_button(self):
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
            window.champ_timer.stop()
            window.show_rune_applied({'applied': False, 'message': '룬 페이지 칸이 가득 찼습니다.'},
                                     {'page': PAGE, 'auto': True})
            status = window.before_game.rune_status
            self.assertTrue(status.text().startswith('자동 적용하지 못했습니다.'))
            self.assertIn("'클라이언트에 적용'을 누르면", status.text())
            self.assertEqual(status.objectName(), 'applyWarn')
            self.assertEqual(window.before_game.apply_button.objectName(), 'attention')
            window.show_rune_applied({'applied': True, 'message': '적용했습니다.'}, {'page': PAGE})
            self.assertEqual(status.objectName(), 'applyOk')
            self.assertEqual(window.before_game.apply_button.objectName(), '')
            self.assertIs(window.rune_applied_page, PAGE)
            window.close()

    def test_profile_icon_replaces_placeholder(self):
        page = OutGamePage()
        page.assets.attach = Mock()
        page.show_profile({'player': PlayerIdentity('p', 'Player#KR1', 30, 4568), 'rank': None, 'matches': []})
        page.assets.attach.assert_any_call(page.avatar, 'profile', 4568)
        page.close()
        assets = MatchAssets()
        assets.version = '16.19.1'
        assets._get = Mock()
        assets._icon(('profile', 4568))
        self.assertEqual(assets._get.call_args.args[0],
                         'https://ddragon.leagueoflegends.com/cdn/16.19.1/img/profileicon/4568.png')


if __name__ == '__main__':
    unittest.main()
