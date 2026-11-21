"""F8 증강 화면 읽기: 이름 맞추기, 이미지 인식 호출, 서버 API, 검은 캡처, 읽은 뒤 추천도까지 이어지는 흐름."""
import base64
import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge import augments as catalog
from rag import vision
from rag.gemini import GeminiError

HAS_SERVER = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
CATALOG = [{'id': 1180, 'name': '전술적 대비', 'rarity': '골드', 'description': '보호막'},
           {'id': 1002, 'name': '최첨단 발명가', 'rarity': '골드', 'description': '아이템 가속'},
           {'id': 1195, 'name': '거인 학살자', 'rarity': '프리즘', 'description': '이동 속도'},
           {'id': 1300, 'name': '초장거리 저격', 'rarity': '실버', 'description': ''}]
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 200


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def chat_reply(text):
    return Response(json.dumps({'choices': [{'message': {'content': text}}]}, ensure_ascii=False).encode())


class MatchTests(unittest.TestCase):
    def test_spacing_typos_and_unknown_names(self):
        found = vision.match_names(['전술적대비', '최첨단 발명 가', '거인 학살지', '다시 뽑기', '전술적 대비'], CATALOG)
        self.assertEqual([a['id'] for a in found], [1180, 1002, 1195])     # 한 글자 오인식까지, 중복과 버튼 글자는 뺀다
        self.assertEqual(vision.match_names(['킬 12', '골드 6,420'], CATALOG), [])

    def test_reads_json_from_the_model_and_sends_the_image_with_known_names(self):
        sent = []

        def opener(request, timeout):
            sent.append(json.loads(request.data.decode()))
            return chat_reply('```json\n{"names": ["거인 학살자", "전술적 대비", "초장거리 저격"]}\n```')
        found = vision.read_augments(JPEG, CATALOG, key='k', opener=opener)
        self.assertEqual([a['name'] for a in found], ['거인 학살자', '전술적 대비', '초장거리 저격'])
        content = sent[0]['messages'][1]['content']
        self.assertIn('초장거리 저격', content[0]['text'])
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))

    def test_empty_image_or_catalog_is_refused(self):
        with self.assertRaises(GeminiError):
            vision.read_augments(b'', CATALOG, key='k', opener=Mock())
        with self.assertRaises(GeminiError):
            vision.read_augments(JPEG, [], key='k', opener=Mock())


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_black_fullscreen_capture_is_detected(self):
        from PySide6.QtGui import QColor, QImage
        from ui.capture import is_blank
        black = QImage(320, 180, QImage.Format_RGB32)
        black.fill(QColor('#000000'))
        self.assertTrue(is_blank(black))
        game = QImage(320, 180, QImage.Format_RGB32)
        game.fill(QColor('#1b2a3a'))
        self.assertFalse(is_blank(game))


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
class ServerScreenTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        knowledge = Path(self.temp.name) / 'knowledge.db'
        catalog.catalog_path(self.temp.name).write_text(json.dumps(
            {'mode': 'KIWI', 'fetched_at': time.time(), 'augments': CATALOG}, ensure_ascii=False), encoding='utf-8')
        settings = Settings(riot_api_key='test', db_path=str(Path(self.temp.name) / 'server.db'),
                            knowledge_db_path=str(knowledge), device_daily_ai=5)
        self.read = Mock(return_value=CATALOG[:3])
        self.http = TestClient(create_app(settings, gateway=Mock(), generate=Mock(), read_screen=self.read))
        self.auth = {'Authorization': 'Bearer ' + self.http.post('/v1/devices').json()['token']}

    def test_capture_is_read_against_the_server_catalog(self):
        ok = self.http.post('/v1/augments/detect', json={'image_base64': base64.b64encode(JPEG).decode()}, headers=self.auth)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual([a['id'] for a in ok.json()['augments']], [1180, 1002, 1195])
        image, known = self.read.call_args.args
        self.assertEqual(image, JPEG)
        self.assertEqual(len(known), 4)
        text = base64.b64encode(b'not an image' * 20).decode()
        self.assertEqual(self.http.post('/v1/augments/detect', json={'image_base64': text}, headers=self.auth).json()['augments'], [])
        self.assertEqual(self.http.post('/v1/augments/detect', json={'image_base64': 'x'}, headers=self.auth).status_code, 422)


class WindowScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def window(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
        window.champ_timer.stop()
        window.speaker = Mock()
        window.voice = Mock(value=lambda name, default: default)
        self.addCleanup(window.close)
        return window

    def test_read_names_fill_the_augment_tab_then_shares_are_asked_and_spoken(self):
        from ui.__main__ import INGAME
        window = self.window()
        window.on_augments_read({'augments': CATALOG[:3], 'message': None})
        self.assertEqual(window.stack.currentIndex(), INGAME)
        self.assertEqual(window.in_game.side_stack.currentIndex(), 1)
        self.assertEqual([c.currentText() for c in window.in_game.augments.choices], ['전술적 대비', '최첨단 발명가', '거인 학살자'])
        self.assertEqual(window.in_game.augments.selected_ids(), [1180, 1002, 1195])
        self.assertEqual(window.pending_augments, [1180, 1002, 1195])
        with patch.object(window, 'ask_augments') as ask:
            job = Mock()
            window.jobs.append(job)
            window.job_done(job)                  # 읽기 작업이 끝나면 추천도를 묻는다
            for _ in range(5):
                self.app.processEvents()
        self.assertEqual(ask.call_args.args[0]['augment_ids'], [1180, 1002, 1195])
        self.assertTrue(window.speak_augments)
        window.show_augment_result({'answer': '증강 추천도: 전술적 대비 50%, 최첨단 발명가 30%, 거인 학살자 20%',
                                    'options': [], 'generated': True}, '')
        window.speaker.say.assert_called_once_with('증강 추천도: 전술적 대비 50%, 최첨단 발명가 30%, 거인 학살자 20%')

    def test_unreadable_screen_is_spoken_and_nothing_is_asked(self):
        window = self.window()
        window.on_augments_read({'augments': CATALOG[:1], 'message': None})
        self.assertIsNone(window.pending_augments)
        self.assertIn('읽지 못했습니다', window.speaker.say.call_args.args[0])

    def test_old_f8_voice_key_moves_to_f10_and_voice_outside_games_opens_the_home_chat(self):
        from ui.__main__ import AUGMENT_HOTKEY, HOME
        window = self.window()
        self.assertEqual(AUGMENT_HOTKEY, 'F8')
        window.voice = Mock(value=lambda name, default: 'F8' if name == 'voice/hotkey' else default)
        self.assertEqual(window.voice_hotkey(), 'F10')        # 예전에 고른 F8은 이제 증강 읽기 키
        window.navigate(3)
        with patch.object(window.out_game, 'submit') as submit:
            window.ask_voice('요즘 탑 뭐가 좋아?')
        submit.assert_called_once()
        self.assertEqual(window.stack.currentIndex(), HOME)
        self.assertEqual(window.out_game.question.text(), '요즘 탑 뭐가 좋아?')

    def test_no_game_window_is_explained_without_calling_the_server(self):
        window = self.window()
        with patch('ui.__main__.capture_game', return_value=(None, '롤 게임 창을 찾지 못했습니다.')), \
             patch.object(window, 'ai_ready', return_value=True), patch.object(window, 'start_job') as start:
            window.read_augment_screen()
        start.assert_not_called()
        window.speaker.say.assert_called_once_with('롤 게임 창을 찾지 못했습니다.')


if __name__ == '__main__':
    unittest.main()
