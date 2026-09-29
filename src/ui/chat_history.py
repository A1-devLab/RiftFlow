"""AI 대화 기록 (데스크톱). 사용자 PC에만 저장하고 서버로 보내지 않는다.

rag/conversation.py는 CLI 실험용으로 보낸 프롬프트 전체를 저장한다. 데스크톱 기록은 사용자가 다시 보고
대화를 이어 가기 위한 것이라 질문과 답의 글만 남긴다(프롬프트에 들어간 전적 요약 같은 자료는 저장하지 않음).
"""
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

SCREEN_NAMES = {'general': '일반', 'pick': '픽창', 'in_game': '인게임'}
CONTEXT_MESSAGES = 6          # 모델에 넘기는 최근 대화 수 (질문·답 합계)
CONTEXT_CHARS = 1200          # 한 메시지에서 모델에 넘기는 최대 글자 수

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    screen TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (conversation_id, seq)
);
"""


class ChatHistory:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def new_id():
        return uuid.uuid4().hex

    def add(self, conversation_id, screen, role, text):
        """메시지 한 개를 저장한다. 대화의 첫 질문이 목록에 보일 제목이 된다."""
        text = (text or '').strip()
        if not text:
            return
        now = self.clock()
        with closing(self._db()) as db, db:
            db.execute("""INSERT INTO conversations (id, screen, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
                          ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""",
                       (conversation_id, screen, text[:40] if role == 'user' else '(대화)', now, now))
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id=?",
                             (conversation_id,)).fetchone()[0]
            db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", (conversation_id, seq, role, text, now))

    def messages(self, conversation_id):
        with closing(self._db()) as db:
            rows = db.execute("SELECT role, text, created_at FROM messages WHERE conversation_id=? ORDER BY seq",
                              (conversation_id,)).fetchall()
        return [dict(row) for row in rows]

    def context(self, conversation_id):
        """모델에 넘길 최근 대화: [{'role': 'user'|'assistant', 'text': ...}]."""
        if not conversation_id:
            return []
        recent = self.messages(conversation_id)[-CONTEXT_MESSAGES:]
        return [{'role': m['role'], 'text': m['text'][:CONTEXT_CHARS]} for m in recent]

    def latest(self, screen):
        with closing(self._db()) as db:
            row = db.execute("SELECT id FROM conversations WHERE screen=? ORDER BY updated_at DESC LIMIT 1",
                             (screen,)).fetchone()
        return row['id'] if row else None

    def conversations(self, limit=100):
        with closing(self._db()) as db:
            rows = db.execute("""SELECT c.id, c.screen, c.title, c.updated_at, COUNT(m.seq) AS count
                                 FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                                 GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def clear(self):
        with closing(self._db()) as db, db:
            db.execute("DELETE FROM messages")
            db.execute("DELETE FROM conversations")
