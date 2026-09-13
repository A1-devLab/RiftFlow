"""대화 기록 저장.

챗봇 규약: 나중에 다른 챗봇 API 를 쓸 수 있으므로 데이터는 전부 저장한다.
그래서 Gemini 에 묶이지 않는 형태로 남긴다.
보낸 프롬프트까지 그대로 저장하므로 다른 모델로 같은 입력을 다시 돌려볼 수 있다.

저장 위치는 data/ 아래다. .gitignore 가 /data/* 를 제외하므로 Git 에 올라가지 않는다.
질문에는 Riot ID 같은 개인정보가 섞일 수 있어 저장소에 올리면 안 된다.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path('data/conversations.db')

SCHEMA = '''CREATE TABLE IF NOT EXISTS turns (
    conversation_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    answer TEXT,
    provider TEXT,
    model TEXT,
    prompt_system TEXT,
    prompt_user TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    evidence_doc_ids TEXT NOT NULL,
    sources TEXT NOT NULL,
    patch TEXT,
    analysis TEXT,
    PRIMARY KEY (conversation_id, turn))'''


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute(SCHEMA)
    return db


def new_conversation_id():
    return uuid.uuid4().hex


def next_turn(db, conversation_id):
    row = db.execute('SELECT MAX(turn) FROM turns WHERE conversation_id=?',
                     (conversation_id,)).fetchone()
    return (row[0] or 0) + 1


def save(db, conversation_id, question, outcome, prompt=None, reply=None,
         provider=None, patch=None, analysis=None):
    """한 번의 질문과 그 결과를 남긴다.

    차단되거나 근거가 없어서 모델을 부르지 않은 경우도 남긴다.
    어떤 질문이 왜 막혔는지 나중에 봐야 안전장치를 고칠 수 있다.
    """
    usage = (reply or {}).get('usage') or {}
    # 모델을 부르지 않았으면 토큰을 쓰지 않은 것이 확실하다. 0 으로 남긴다.
    # 부르려다 실패했거나 응답에 사용량이 없으면 얼마나 썼는지 모른다. None 으로 남긴다.
    # 둘을 섞으면 '안 썼다' 와 '모른다' 가 구분되지 않는다. (docs/interfaces.md: 누락값과 0 구분)
    if not outcome.get('model_called'):
        usage = {'prompt_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
    turn = next_turn(db, conversation_id)
    with db:
        db.execute('INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            conversation_id,
            turn,
            datetime.now(timezone.utc).isoformat(),
            question,
            outcome['status'],
            (reply or {}).get('text') or outcome.get('message'),
            provider if reply else None,
            (reply or {}).get('model'),
            (prompt or {}).get('system'),
            (prompt or {}).get('user'),
            usage.get('prompt_tokens'),
            usage.get('output_tokens'),
            usage.get('total_tokens'),
            json.dumps([row['chunk']['doc_id'] for row in outcome.get('evidence') or []],
                       ensure_ascii=False),
            json.dumps(outcome.get('sources') or [], ensure_ascii=False),
            patch,
            json.dumps(analysis, ensure_ascii=False) if analysis else None,
        ))
    return turn


def history(db, conversation_id):
    rows = db.execute(
        'SELECT turn, created_at, question, status, answer FROM turns '
        'WHERE conversation_id=? ORDER BY turn', (conversation_id,)).fetchall()
    return [{'turn': r[0], 'created_at': r[1], 'question': r[2],
             'status': r[3], 'answer': r[4]} for r in rows]


def stats(db):
    """상태별 건수와 토큰 사용량. 안전장치가 실제로 토큰을 아꼈는지 본다.

    tokens 는 알려진 사용량의 합이다. 하나도 모르면 None 이다. 0 으로 채우지 않는다.
    tokens_unknown 은 사용량을 모르는 행의 수다.
    """
    rows = db.execute(
        'SELECT status, COUNT(*), SUM(total_tokens), '
        'SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END) '
        'FROM turns GROUP BY status ORDER BY COUNT(*) DESC').fetchall()
    return [{'status': r[0], 'count': r[1], 'tokens': r[2], 'tokens_unknown': r[3]}
            for r in rows]
