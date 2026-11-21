"""내 챔피언을 고르기 전 픽창 질문에도 아군, 상대 조합을 AI에게 넘긴다."""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ChampSelectMember, ChampSelectSession
from game_phases.before_game.desktop import describe_session, pick_summary

CATALOG = {103: {'id': 'Ahri', 'name': '아리'}, 86: {'id': 'Garen', 'name': '가렌'},
           64: {'id': 'LeeSin', 'name': '리 신'}, 238: {'id': 'Zed', 'name': '제드'}, 17: {'id': 'Teemo', 'name': '티모'}}


def custom_game():
    """사설방: 포지션 없음, 나는 아직 안 고름, 아군 2명과 상대 1명 확정, 금지 1개."""
    mine = ChampSelectMember(1, 0, '', 'mine')
    allies = [mine, ChampSelectMember(2, 86, '', 'a'), ChampSelectMember(3, 64, '', 'b')]
    base = ChampSelectSession(allies, [ChampSelectMember(6, 238, '', 'c')], [17], [], 1)
    return dataclasses.replace(base, game_mode='CLASSIC')


class PickSummaryTests(unittest.TestCase):
    def test_summary_lists_allies_enemies_and_bans(self):
        text = pick_summary(describe_session(custom_game(), CATALOG))
        self.assertIn('내 챔피언: 아직 고르지 않음', text)
        self.assertIn('아군: 가렌, 리 신', text)
        self.assertIn('상대(확정한 챔피언만 보임): 제드', text)
        self.assertIn('금지된 챔피언: 티모', text)
        self.assertIn('내 포지션: 정해지지 않음', text)
        empty = ChampSelectSession([ChampSelectMember(1, 0, '', 'mine')], [], [], [], 1)
        self.assertEqual(pick_summary(describe_session(empty, CATALOG)), '')
        self.assertEqual(pick_summary(None), '')

    def test_question_before_picking_is_sent_with_the_pick_view(self):
        app = QApplication.instance() or QApplication([])
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(tempfile.mkdtemp()) / 'ui')
        window.champ_timer.stop()
        self.addCleanup(window.close)
        window.before_game.show_session(describe_session(custom_game(), CATALOG))
        window.before_game.champion.setText('')
        with patch.dict(os.environ, {'HASA_API_KEY': 'k'}), \
             patch.object(window, 'general_answer', return_value={'answer': '아리를 추천합니다.', 'generated': True}) as general:
            window.ask_before_game(dict(window.before_game._request('조합을 바탕으로 픽 추천해줘.')))
            while window.jobs:
                app.processEvents()
        asked = general.call_args.args[1]
        self.assertIn('아군: 가렌, 리 신', asked)
        self.assertTrue(asked.endswith('질문: 조합을 바탕으로 픽 추천해줘.'))
        self.assertIn('나: 조합을 바탕으로 픽 추천해줘.', window.before_game.answer.toPlainText())   # 대화에는 원래 질문만


if __name__ == '__main__':
    unittest.main()
