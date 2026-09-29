"""AI chat history: saved on this PC, reopened later, and passed back as context for follow-up questions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from game_phases import payloads
from ui.chat_history import CONTEXT_CHARS, CONTEXT_MESSAGES, ChatHistory
from ui.services import ask_general


class ChatHistoryStoreTests(unittest.TestCase):
    def test_store_lists_conversations_and_limits_context(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = iter(range(100, 200))
            chats = ChatHistory(Path(folder) / 'chat.db', clock=lambda: next(clock))
            first = ChatHistory.new_id()
            for i in range(5):
                chats.add(first, 'general', 'user', '질문 %d' % i)
                chats.add(first, 'general', 'assistant', '답 %d ' % i + 'x' * 2000)
            other = ChatHistory.new_id()
            chats.add(other, 'pick', 'user', '초반 운영은?')
            context = chats.context(first)
            self.assertEqual(len(context), CONTEXT_MESSAGES)
            self.assertEqual(context[-1]['role'], 'assistant')
            self.assertEqual(len(context[-1]['text']), CONTEXT_CHARS)
            self.assertEqual(chats.latest('general'), first)
            listed = chats.conversations()
            self.assertEqual([c['screen'] for c in listed], ['pick', 'general'])
            self.assertEqual(listed[1]['title'], '질문 0')
            self.assertEqual(listed[1]['count'], 10)
            chats.clear()
            self.assertEqual(chats.conversations(), [])

    def test_payload_history_keeps_only_roles_and_caps_size(self):
        messages = [{'role': 'system', 'text': 'x'}] + [{'role': 'user', 'text': 'q' * 5000}] * 10
        cleaned = payloads.history(messages)
        self.assertEqual(len(cleaned), 8)
        self.assertTrue(all(m['role'] == 'user' and len(m['text']) == 1200 for m in cleaned))


class FollowUpContextTests(unittest.TestCase):
    def test_general_question_carries_conversation_and_searches_with_previous_question(self):
        generate = Mock(return_value={'text': '3,250골드입니다.'})
        history = [{'role': 'user', 'text': '존야의 모래시계 효과 알려줘'},
                   {'role': 'assistant', 'text': '경직 효과가 있습니다.'}]
        with tempfile.TemporaryDirectory() as folder, patch('rag.retrieve.search', return_value=[]) as search:
            ask_general(Path(folder) / 'missing.db', '그건 얼마야?', generate=generate, history=history)
        prompt = generate.call_args.args[0]
        self.assertEqual(json.loads(prompt['user'])['conversation'], history)
        self.assertIn('conversation은', prompt['system'])


class WindowHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'GEMINI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)

    def window(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
        window.champ_timer.stop()
        return window

    def test_general_chat_survives_restart_and_feeds_the_next_question(self):
        window = self.window()
        window.show_answer({'answer': '연습 모드에서 막타 연습을 하세요.', 'status': 'ready', 'generated': True},
                           'CS 연습 방법 알려줘')
        self.assertIn('막타 연습', window.reply.toPlainText())
        window.close()
        reopened = self.window()
        self.assertIn('CS 연습 방법 알려줘', reopened.reply.toPlainText())
        self.assertEqual(reopened.chat_list.count(), 2)                  # '현재 대화' + 저장된 대화 1개
        with patch('ui.__main__.ask_general', return_value={'answer': 'ok', 'status': 'ready', 'generated': True}) as ask:
            reopened.general_answer(reopened.db_path, '더 쉬운 방법은?', None, 'model',
                                    reopened.chat_context('general'))
        self.assertEqual([m['text'] for m in ask.call_args.kwargs['history']],
                         ['CS 연습 방법 알려줘', '연습 모드에서 막타 연습을 하세요.'])
        reopened.new_chat()
        self.assertEqual(reopened.chat_context('general'), [])
        reopened.open_chat(1)                                           # 지난 대화를 다시 열면 이어서 질문
        self.assertEqual(len(reopened.chat_context('general')), 2)
        reopened.close()

    def test_pick_conversation_resets_on_new_champ_select(self):
        from contracts.riot import ChampSelectMember, ChampSelectSession
        window = self.window()
        session = ChampSelectSession([ChampSelectMember(1, 103, 'middle', 'mine')], [], [], [], 1)
        window.on_phase({'phase': 'champ_select', 'session': session, 'catalog': {}})
        window.show_before_game_answer({'answer': '초반엔 라인을 지키세요.', 'generated': True}, '초반 운영은?')
        self.assertIn('나: 초반 운영은?', window.before_game.answer.toPlainText())
        self.assertEqual(len(window.chat_context('pick')), 2)
        window.on_phase({'phase': 'idle'})
        window.on_phase({'phase': 'champ_select', 'session': session, 'catalog': {}})
        self.assertEqual(window.chat_context('pick'), [])
        self.assertEqual(len(window.chats.conversations()), 1)          # 지난 픽창 대화는 기록에 남음
        window.close()

    def test_history_screen_chat_can_be_reloaded(self):
        from ui.pages.out_game import OutGamePage
        page = OutGamePage()
        page.load_history([{'role': 'user', 'text': 'q1'}, {'role': 'assistant', 'text': 'a1'}])
        self.assertEqual(page.messages.count(), 4)                      # 안내 + 질문 + 답 + 여백
        page.load_history([])
        self.assertEqual(page.messages.count(), 2)
        page.close()


@unittest.skipUnless(all(importlib.util.find_spec(n) for n in ('fastapi', 'httpx')), 'fastapi/httpx not installed')
class ServerHistoryTests(unittest.TestCase):
    def test_server_passes_history_but_does_not_store_it(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            generate = Mock(return_value={'text': '답'})
            app = create_app(Settings(riot_api_key='t', db_path=str(Path(folder) / 's.db'),
                                      knowledge_db_path=str(Path(folder) / 'k.db')), gateway=Mock(), generate=generate)
            http = TestClient(app)
            auth = {'Authorization': 'Bearer ' + http.post('/v1/devices').json()['token']}
            history = [{'role': 'user', 'text': '이전 질문'}, {'role': 'assistant', 'text': '이전 답'}]
            http.post('/v1/coach/general', json={'question': '이어서', 'history': history}, headers=auth)
            self.assertEqual(json.loads(generate.call_args.args[0]['user'])['conversation'], history)
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(Path(folder) / 's.db')) as db:
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertFalse(any('message' in t or 'conversation' in t for t in tables))


if __name__ == '__main__':
    unittest.main()
