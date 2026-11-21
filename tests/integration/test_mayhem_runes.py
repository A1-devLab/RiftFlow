"""증바람(ARAM: Mayhem)은 룬 페이지가 없다: 대기열 번호로 알아보고, 룬 추천과 적용을 하지 않는다."""
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ChampSelectMember, ChampSelectSession
from game_phases.before_game.desktop import describe_session
from game_phases.before_game.runes import recommend_runes

CATALOG = {103: {'id': 'Ahri', 'name': '아리'}}


def session(queue_id, game_mode='ARAM'):
    base = ChampSelectSession([ChampSelectMember(1, 103, '', 'mine')], [], [], [], 1)
    return dataclasses.replace(base, game_mode=game_mode, queue_id=queue_id)


class MayhemRuneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mayhem_queue_is_mayhem_even_when_the_client_says_aram(self):
        view = describe_session(session(2400), CATALOG)
        self.assertEqual((view['game_mode'], view['mode_name']), ('KIWI', '증바람'))
        self.assertEqual(describe_session(session(450), CATALOG)['game_mode'], 'ARAM')      # 일반 칼바람은 그대로

    def test_no_rune_recommendation_or_model_call_in_mayhem(self):
        generate = Mock()
        result = recommend_runes(Path(tempfile.mkdtemp()) / 'x.db', None, None,
                                 describe_session(session(2400), CATALOG), generate=generate, champion='아리')
        generate.assert_not_called()
        self.assertIsNone(result['page'])
        self.assertIn('증바람', result['message'])

    def test_pick_page_disables_runes_and_sends_rune_talk_to_the_coach(self):
        from ui.pages.before_game import RUNE_PLACEHOLDER, BeforeGamePage
        page = BeforeGamePage()
        page.portraits.attach = Mock()
        page.show_session(describe_session(session(2400), CATALOG))
        self.assertFalse(page.rune_button.isEnabled())
        self.assertFalse(page.apply_button.isEnabled())
        self.assertIn('룬 페이지를 쓰지 않아', page.rune_view.placeholder.text())
        self.assertIn('F8', page.rune_view.placeholder.text())
        runes, asks = [], []
        page.runeRequested.connect(runes.append)
        page.askRequested.connect(asks.append)
        page.question.setText('공격적으로 룬 짜줘')
        page.submit()
        page.request_runes()
        self.assertEqual(runes, [])
        self.assertEqual(len(asks), 1)
        page.show_disconnected()
        self.assertEqual(page.rune_view.placeholder.text(), RUNE_PLACEHOLDER)      # 다음 픽창에는 안내가 남지 않는다
        page.show_session(describe_session(session(450), CATALOG))
        self.assertTrue(page.rune_button.isEnabled())
        page.close()

    def test_game_data_saying_aram_after_a_mayhem_pick_is_shown_as_mayhem(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(tempfile.mkdtemp()) / 'ui')
        window.champ_timer.stop()
        self.addCleanup(window.close)
        window.on_phase({'phase': 'champ_select', 'session': session(2400), 'catalog': CATALOG})
        self.assertEqual(window.pick_mode, 'KIWI')
        window.on_phase({'phase': 'in_game', 'view': {'in_game': True, 'game_mode': 'ARAM', 'mode_name': '칼바람 나락',
                                                      'allies': [], 'enemies': [], 'clock': '01:00'}})
        self.assertEqual(window.in_game.view['game_mode'], 'KIWI')
        self.assertEqual(window.in_game.side_stack.currentIndex(), 1)       # 증강 탭이 열린다


if __name__ == '__main__':
    unittest.main()
