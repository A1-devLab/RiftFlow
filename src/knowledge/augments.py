"""증바람(ARAM: Mayhem, 모드 코드 KIWI) 증강 목록과 공식 효과 설명.

CommunityDragon의 클라이언트 자료에서 받는다: cherry-augments.json(이름, 등급), augment-lists.json(모드별 증강 목록),
게임 문자열표(효과 설명). 경기 결과 통계(승률, 픽률)는 받지 않는다. 라이엇 정책이 증강 승률 표시를 금지한다
("Products cannot display win rates for Augments", developer.riotgames.com/docs/lol).

문자열표는 35MB라 서버가 하루에 한 번 받아 목록 파일로 줄여 둔다.
"""
import json
import re
import time
from pathlib import Path

from .collector import fetch

CDRAGON = 'https://raw.communitydragon.org/latest'
GAME_DATA = CDRAGON + '/plugins/rcp-be-lol-game-data/global/ko_kr/v1'
STRINGS = CDRAGON + '/game/ko_kr/data/menu/en_us/lol.stringtable.json'
ICONS = CDRAGON + '/plugins/rcp-be-lol-game-data/global/default/'
MODE = 'KIWI'
RARITY = {'kSilver': '실버', 'kGold': '골드', 'kPrismatic': '프리즘'}
MAX_AGE = 24 * 3600
SUFFIXES = ('_tooltip', '_tooltipsummary', '_summary', '_desc')
# 문자열표 키 앞부분. 앞쪽일수록 우선한다 (증바람 전용 설명 → 공용 증강 설명 → 아레나 설명).
PREFIXES = ('kiwi_', 'augment_', 'aram_', 'cherry_')


def catalog_path(folder):
    return Path(folder) / ('augments_%s.json' % MODE.lower())


def plain(text):
    """문자열표 설명에서 서식 태그와 변수 자리를 걷어 낸다. 수치는 레벨마다 달라 변수로만 들어 있다."""
    text = re.sub(r'<br\s*/?>', ' ', text or '')
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'%i:[^%]+%', '', text)
    text = re.sub(r'@[^@]+@', '(수치)', text)
    return ' '.join(text.split())


def expand(text, strings, key=None, depth=3):
    """{{Augment_X_Summary}} 같은 다른 문자열 참조를 실제 문장으로 바꾼다 (문자열표 키는 소문자).

    자기 자신을 가리키는 참조는 지운다. 그대로 펼치면 같은 문장이 여러 번 반복된다.
    """
    seen = {key} if key else set()

    def lookup(match):
        name = match.group(1).lower()
        if name in seen:
            return ''
        seen.add(name)
        return strings.get(name, '')
    for _ in range(depth):
        if '{{' not in (text or ''):
            break
        text = re.sub(r'\{\{\s*([A-Za-z0-9_]+)[^}]*\}\}', lookup, text)
    return re.sub(r'\{\{[^}]*\}\}', '', text or '')


def _token(name):
    """증강 키를 문자열표 키의 가운데 부분과 맞추는 형태로. 예: ARAM_BigBrain → bigbrain."""
    name = name.lower()
    while name.startswith(('aram_', 'augment_')):
        name = name.split('_', 1)[1]
    return name


def description_index(strings):
    """{증강 토큰: (문자열표 키, 설명)}. kiwi_(증바람) 설명을 먼저 쓰고, 없으면 공용(augment_, aram_), 그다음 아레나(cherry_) 설명을 쓴다.

    키 모양이 증강마다 조금씩 달라서(kiwi_bigbrain_tooltip, kiwi_aram_x_tooltip, augment_x_desc) 한 번 훑어 묶는다.
    """
    found = {}
    for key, value in strings.items():
        if not value or not isinstance(value, str):
            continue
        prefix = next((p for p in PREFIXES if key.startswith(p)), None)
        suffix = next((s for s in SUFFIXES if key.endswith(s)), None)
        if prefix is None or suffix is None or len(key) <= len(prefix) + len(suffix):
            continue
        token = _token(key[len(prefix):-len(suffix)])
        rank = (PREFIXES.index(prefix), SUFFIXES.index(suffix))      # 작을수록 우선
        if token not in found or rank < found[token][0]:
            found[token] = (rank, key, value)
    return {token: (key, value) for token, (_, key, value) in found.items()}


def _icon(path):
    path = (path or '').lower()
    return ICONS + path[len('/lol-game-data/assets/'):] if path.startswith('/lol-game-data/assets/') else None


def build_catalog(mode=MODE, get=fetch):
    """모드의 증강 목록 [{id, key, name, rarity, description, icon}]. 이름이 같은 증강은 처음 것만 남긴다."""
    lists = json.loads(get(GAME_DATA + '/augment-lists.json'))
    paths = next((entry.get('augmentList') for entry in lists if entry.get('modeName') == mode), None)
    if not paths:
        raise ValueError('augment list for %s not found' % mode)
    augments = {a.get('augmentNameId'): a for a in json.loads(get(GAME_DATA + '/cherry-augments.json'))}
    strings = json.loads(get(STRINGS))
    strings = strings.get('entries', strings)
    index = description_index(strings)
    catalog, names = [], set()
    for path in paths:
        key = str(path).rsplit('/', 1)[-1]
        augment = augments.get(key)
        name = (augment or {}).get('nameTRA')
        if not name or name in names or not isinstance(augment.get('id'), int):
            continue
        names.add(name)
        string_key, text = index.get(_token(key), (None, ''))
        catalog.append({'id': augment['id'], 'key': key, 'name': name,
                        'rarity': RARITY.get(augment.get('rarity'), ''),
                        'description': plain(expand(text, strings, string_key))[:300],
                        'icon': _icon(augment.get('augmentSmallIconPath'))})
    return catalog


def load_catalog(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get('augments'), list) else None


def ensure_catalog(path, *, download=True, get=fetch, clock=time.time):
    """저장해 둔 목록을 돌려준다. 하루가 지났거나 없으면 새로 받고, 받지 못하면 예전 목록을 그대로 쓴다."""
    cached = load_catalog(path)
    if cached and clock() - cached.get('fetched_at', 0) < MAX_AGE:
        return cached['augments']
    if download:
        try:
            augments = build_catalog(get=get)
        except (OSError, ValueError, KeyError, TypeError):
            augments = None
        if augments:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({'mode': MODE, 'fetched_at': clock(), 'augments': augments},
                                             ensure_ascii=False), encoding='utf-8')
            return augments
    return cached['augments'] if cached else []
