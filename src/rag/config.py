""".env 파일을 읽어 환경변수로 올린다.

저장소 README 에 적힌 대로 .env.example 을 .env 로 복사해 쓰는데,
뼈대에는 .env 를 읽는 코드가 없어서 값이 프로그램까지 오지 않았다.

이미 환경변수에 있는 값은 덮어쓰지 않는다.
셸에서 임시로 준 값이 파일보다 우선이어야 하기 때문이다.

키 값 자체는 화면에도 로그에도 남기지 않는다.
"""
import os
from pathlib import Path

DEFAULT_PATH = Path('.env')


def parse(text):
    """KEY=VALUE 형식만 읽는다. 주석과 빈 줄은 건너뛴다."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        if key.startswith('export '):
            key = key[len('export '):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path=DEFAULT_PATH, override=False):
    """.env 를 읽어 환경변수에 넣는다. 넣은 키 이름만 돌려준다. 값은 돌려주지 않는다."""
    path = Path(path)
    if not path.exists():
        return []

    applied = []
    for key, value in parse(path.read_text(encoding='utf-8')).items():
        if not value:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value
            applied.append(key)
    return applied
