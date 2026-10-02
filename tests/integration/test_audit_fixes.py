"""Regression tests for the full-program audit: polling cost, UI state bugs, watcher, clients, knowledge reads."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ChampSelectMember, ChampSelectSession, ConnectionState, LiveMatchStatus, LiveState


class PollerTests(unittest.TestCase):
    def test_live_client_is_only_probed_when_a_game_can_be_running(self):
        from ui.__main__ import collect_phase
        live = Mock(return_value=LiveState(LiveMatchStatus.NOT_IN_GAME, ConnectionState.DISCONNECTED))
        with patch('ui.__main__.get_gameflow_phase', return_value='ChampSelect'), \
             patch('ui.__main__.get_live_state', live), \
             patch('ui.__main__.get_before_game_context', return_value=None):
            self.assertEqual(collect_phase('missing.db'), {'phase': 'idle'})
        live.assert_not_called()                         # 픽창에서는 2999에 연결하지 않는다 (예전: 매번 1초 대기)
        with patch('ui.__main__.get_gameflow_phase', return_value=None), \
             patch('ui.__main__.get_live_state', live):
            self.assertEqual(collect_phase('missing.db'), {'phase': 'idle'})
        self.assertEqual(live.call_args.kwargs['timeout'], 0.3)   # 클라이언트가 없으면 짧게만 확인


class WindowStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)

    def window(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}), \
             patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}):
            window = Window(Path(self.temp.name) / 'ui')
        window.champ_timer.stop()
        self.addCleanup(window.close)
        return window

    def test_auto_rune_recommendation_restarts_in_the_next_champ_select(self):
        """예전에는 rune_shown_key가 남아 같은 챔피언으로 다음 픽창에 들어가면 자동 추천이 멈췄다."""
        window = self.window()
        requested = []

        def fake_request(request):
            requested.append(request['champion'])
            window.rune_shown_key = window.rune_key(request)
            return True
        window.request_runes = fake_request
        session = ChampSelectSession([ChampSelectMember(1, 7, 'middle', 'mine')], [], [], [], 1)
        catalog = {7: {'id': 'Leblanc', 'name': '르블랑'}}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}):
            for _ in range(2):
                window.on_phase({'phase': 'champ_select', 'session': session, 'catalog': catalog})
            window.on_phase({'phase': 'idle'})
            for _ in range(2):
                window.on_phase({'phase': 'champ_select', 'session': session, 'catalog': catalog})
        self.assertEqual(requested, ['르블랑', '르블랑'])

    def test_one_missed_live_response_keeps_scoreboard_and_item_picks(self):
        window = self.window()
        window.phase = 'in_game'
        window.in_game.view = {'in_game': True}
        window.in_game.items.show_result({'options': [{'item_id': 3089, 'name': '라바돈의 죽음모자', 'price': 3500,
                                                       'reason': '화력'}], 'summary': ''})
        window.on_phase({'phase': 'loading'})
        self.assertEqual(window.phase, 'in_game')
        self.assertTrue(window.in_game.items.picks[0].isVisibleTo(window.in_game))
        for _ in range(2):
            window.on_phase({'phase': 'loading'})
        self.assertEqual(window.phase, 'loading')        # 계속 못 받으면 로딩으로
        self.assertTrue(window.in_game.items.picks[0].isVisibleTo(window.in_game))   # 추천은 새 게임에서만 지운다

    def test_poll_failures_do_not_wipe_champ_select_until_repeated(self):
        window = self.window()
        window.before_game.champion.setText('르블랑')
        window.on_poll_failed('x')
        window.on_poll_failed('x')
        self.assertEqual(window.before_game.champion.text(), '르블랑')

    def test_chat_shows_one_pending_bubble_and_errors_stay_on_their_screen(self):
        window = self.window()
        page = window.out_game
        page.askRequested.disconnect()                   # 실제 AI 요청을 띄우지 않는다
        before = page.messages.count()
        page.set_busy(True)                              # 룬 추천 같은 다른 작업
        self.assertEqual(page.messages.count(), before)
        page.set_busy(False)
        page.question.setText('질문')
        page.submit()
        self.assertEqual(page.messages.count(), before + 2)   # 질문 + '자료를 찾고 있습니다…'
        page.show_answer({'answer': '<img src="file:///C:/x.png"> 답'})
        self.assertEqual(page.messages.count(), before + 2)   # 대기 말풍선은 답으로 바뀜
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        bubbles = [b for b in page.chat_body.findChildren(QLabel) if b.objectName() == 'coachBubble']
        self.assertTrue(all(b.textFormat() == Qt.PlainText for b in bubbles))
        window.before_game.answer.setPlainText('픽창 대화')
        window.failed('룬 적용 실패')
        self.assertEqual(window.before_game.answer.toPlainText(), '픽창 대화')

    def test_pick_chat_without_champion_uses_the_general_coach(self):
        window = self.window()
        window.before_game.champion.setText('')
        with patch.dict(os.environ, {'HASA_API_KEY': 'k'}),              patch.object(window, 'general_answer', return_value={'answer': '원딜과 잘 맞습니다.', 'generated': True}) as general,              patch('ui.__main__.answer_before_game') as pick:
            window.ask_before_game(dict(window.before_game._request('티모 서폿이랑 어울리는거 뭐 있어?')))
            while window.jobs:
                self.app.processEvents()
        general.assert_called_once()
        pick.assert_not_called()
        self.assertIn('원딜과 잘 맞습니다.', window.before_game.answer.toPlainText())

    def test_missing_key_ends_the_loading_screen(self):
        from ui.pages.out_game import OutGamePage
        page = OutGamePage()
        page.show_unavailable('Riot API 키를 설정하면…')
        self.assertEqual(page.history_stack.currentIndex(), 1)
        self.assertFalse(page.loading_timer.isActive())
        page.close()


class LoginWatcherTests(unittest.TestCase):
    def test_watcher_survives_errors_notices_account_switch_and_stops_on_bad_key(self):
        from riot import lcu_client
        from riot.client import InvalidApiKey
        names = iter([{'gameName': 'A', 'tagLine': 'KR'}, {'gameName': 'A', 'tagLine': 'KR'},
                      {'gameName': 'B', 'tagLine': 'KR'}, {'gameName': 'C', 'tagLine': 'KR'}])
        players = iter([ConnectionError('wifi'), 'player-A', 'player-B', InvalidApiKey('expired')])

        def summoner():
            value = next(players)
            if isinstance(value, Exception):
                raise value
            return value
        seen, errors, done = [], [], threading.Event()
        with patch.object(lcu_client, '_find_lcu_credentials', return_value=(1, 's')), \
             patch.object(lcu_client, '_current_summoner_data', side_effect=lambda creds: next(names)), \
             patch.object(lcu_client, 'get_current_summoner', side_effect=summoner):
            thread = lcu_client.start_login_watcher(seen.append, interval=0.01, max_delay=0.02,
                                                     on_error=lambda m: (errors.append(m), done.set()))
            done.wait(5)
            thread.join(5)
        self.assertEqual(seen, ['player-A', 'player-B'])       # 오류 뒤에도 계속, 계정이 바뀌면 다시 알림
        self.assertEqual(len(errors), 1)                        # 잘못된 키는 알리고 멈춤
        self.assertFalse(thread.is_alive())


class ClientRobustnessTests(unittest.TestCase):
    def test_server_client_handles_html_bodies_and_http_date_retry_after(self):
        from api_client import ServerClient
        from contracts.riot import RateLimitExceeded, RiotApiError
        html = Mock(status_code=200, headers={})
        html.json.side_effect = ValueError('not json')
        busy = Mock(status_code=429, headers={'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT'})
        busy.json.return_value = {'error': {'message': '잠시 뒤'}}
        with tempfile.TemporaryDirectory() as folder:
            session = Mock()
            client = ServerClient('https://example.test', token_path=Path(folder) / 't', session=session)
            client._token = 'tok'
            session.request.return_value = html
            with self.assertRaises(RiotApiError):
                client.get_json('/v1/x')
            session.request.return_value = busy
            with self.assertRaises(RateLimitExceeded) as caught:
                client.get_json('/v1/x')
            self.assertIsNone(caught.exception.retry_after_seconds)

    def test_item_price_download_failure_is_retried_later(self):
        from riot import live_client
        live_client._prices_cache, live_client._prices_failed_at = None, 0.0
        self.addCleanup(setattr, live_client, '_prices_cache', None)
        self.addCleanup(setattr, live_client, '_prices_failed_at', 0.0)
        with patch.object(live_client, '_download_ddragon_item_prices', side_effect=[{}, {1001: 300}]) as download:
            self.assertEqual(live_client._get_ddragon_item_prices(), {})
            self.assertEqual(live_client._get_ddragon_item_prices(), {})          # 5분 안에는 다시 받지 않음
            live_client._prices_failed_at -= live_client._PRICES_RETRY + 1
            self.assertEqual(live_client._get_ddragon_item_prices(), {1001: 300})  # 예전: 빈 표를 끝까지 기억
        self.assertEqual(download.call_count, 2)

    def test_server_json_with_new_fields_does_not_break_installed_apps(self):
        from contracts.riot import RankInfo
        from riot.service import _build
        rank = _build(RankInfo, {'queue_type': 'RANKED_SOLO_5x5', 'tier': 'GOLD', 'division': 'II', 'league_points': 10, 'wins': 1, 'losses': 2,
                                 'new_field_from_future_server': True})
        self.assertEqual(rank.tier, 'GOLD')


class KnowledgeReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from knowledge.collector import connect, save
        self.path = Path(self.temp.name) / 'k.db'
        with closing(connect(self.path)) as db, db:
            for version, name in (('16.9.1', '옛 아리'), ('16.19.1', '아리')):
                save(db, 'champion', version, 'Ahri', name, json.dumps(
                    {'id': 'Ahri', 'key': '103', 'name': name, 'blurb': '구미호', 'tags': ['Mage', 'Assassin'],
                     'partype': '마나', 'info': {'attack': 3, 'defense': 4, 'magic': 8, 'difficulty': 5},
                     'stats': {'hp': 590}}, ensure_ascii=False), 'https://example.test')
            save(db, 'item', '16.19.1', '3065', '정령의 형상', json.dumps(
                {'name': '정령의 형상', 'description': '체력 회복', 'gold': {'total': 2900, 'purchasable': True},
                 'stats': {'FlatSpellBlockMod': 60}, 'maps': {'11': True}, 'tags': []}, ensure_ascii=False),
                 'https://example.test')

    def test_latest_version_is_numeric_and_champion_is_one_readable_chunk(self):
        from knowledge.before_game import champion_catalog
        from knowledge.documents import get_documents
        from rag.store import chunk_document
        self.assertEqual(champion_catalog(self.path)[103]['name'], '아리')       # '16.9.1' > '16.19.1' 문자열 비교 버그
        champion = get_documents(kind='champion', db_path=self.path)
        self.assertEqual([d['version'] for d in champion], ['16.19.1'])
        self.assertNotIn('"hp"', champion[0]['text'])                            # 능력치 JSON 대신 읽을 수 있는 문장
        self.assertIn('역할: Mage, Assassin', champion[0]['text'])
        self.assertEqual(len(chunk_document(champion[0])), 1)                     # 예전: 이름 한 줄짜리 첫 조각
        self.assertEqual(champion[0]['situation_tags'], ['마법사', '암살'])
        item = get_documents(kind='item', db_path=self.path)[0]
        self.assertIn('상대AP위주', item['situation_tags'])                       # 공식 능력치에서 만든 상황 태그

    def test_collector_keeps_only_recent_versions(self):
        from knowledge.collector import connect, prune_versions, save
        with closing(connect(self.path)) as db, db:
            save(db, 'champion', '16.18.1', 'Ahri', '아리', '{}', 'https://example.test')
            prune_versions(db, 'champion', keep=2)
            versions = sorted(r[0] for r in db.execute("SELECT DISTINCT version FROM records WHERE kind='champion'"))
        self.assertEqual(versions, ['16.18.1', '16.19.1'])



class SetKeyTests(unittest.TestCase):
    def test_pasted_control_character_is_refused(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
        import set_key
        self.assertIsNotNone(set_key.check_key('HASA_API_KEY', ''))      # Ctrl+V가 글자로 들어간 경우
        self.assertIsNotNone(set_key.check_key('HASA_API_KEY', 'abc'))
        self.assertIsNone(set_key.check_key('HASA_API_KEY', 'sk-dev-' + 'a' * 32))
        self.assertEqual(set_key.merged('sk-a', 'sk-b'), 'sk-a,sk-b')


if __name__ == '__main__':
    unittest.main()
