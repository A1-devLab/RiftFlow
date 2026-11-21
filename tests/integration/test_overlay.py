"""게임 화면 위 안내 카드: 게임 창이 있을 때만, 클릭이 통과하게, 음성 질문과 F8 결과를 보여 준다."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.overlay import GameOverlay, reading_ms


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_card_shows_only_over_a_running_game_and_never_takes_input(self):
        screen = QApplication.primaryScreen()
        overlay = GameOverlay(find_screen=lambda: screen)
        self.addCleanup(overlay.close)
        flags = overlay.windowFlags()
        self.assertTrue(flags & Qt.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(overlay.show_card('RiftFlow 답변', '지금은 바론보다 드래곤입니다.', question='바론 칠까?'))
        self.assertTrue(overlay.isVisible())
        self.assertTrue(overlay.hide_timer.isActive())
        self.assertEqual(overlay.question.text(), '바론 칠까?')
        self.assertTrue(overlay.show_card('RiftFlow 음성 질문', '듣고 있습니다…', sticky=True))
        self.assertFalse(overlay.hide_timer.isActive())          # 듣는 중에는 사라지지 않는다
        no_game = GameOverlay(find_screen=lambda: None)
        self.addCleanup(no_game.close)
        self.assertFalse(no_game.show_card('RiftFlow 답변', '답'))
        self.assertFalse(no_game.isVisible())
        overlay.enabled = False
        overlay.hide()
        self.assertFalse(overlay.show_card('RiftFlow 답변', '답'))

    def test_reading_time_grows_with_the_answer(self):
        self.assertEqual(reading_ms(''), 6000)
        self.assertGreater(reading_ms('가' * 200), reading_ms('가' * 50))
        self.assertEqual(reading_ms('가' * 5000), 25000)

    def test_voice_question_and_answer_go_to_the_overlay(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(tempfile.mkdtemp()) / 'ui')
        window.champ_timer.stop()
        window.speaker = Mock()
        window.overlay = Mock()
        self.addCleanup(window.close)
        window.on_voice_started()
        self.assertIn('듣고 있습니다', window.overlay.show_card.call_args.args[1])
        with patch.object(window, 'ask_out_game'):
            window.ask_voice('요즘 탑 뭐가 좋아?')
        window.show_out_game_answer({'answer': '요즘은 사이온이 좋습니다.', 'generated': True}, '요즘 탑 뭐가 좋아?')
        args, kwargs = window.overlay.show_card.call_args
        self.assertEqual(args[1], '요즘은 사이온이 좋습니다.')
        self.assertEqual(kwargs['question'], '요즘 탑 뭐가 좋아?')
        window.overlay.show_card.reset_mock()
        window.show_out_game_answer({'answer': '글로 물은 질문', 'generated': True}, '글 질문')
        window.overlay.show_card.assert_not_called()            # 글로 물은 질문은 띄우지 않는다


if __name__ == '__main__':
    unittest.main()
