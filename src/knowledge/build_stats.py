"""상위 랭커 실전 빌드 통계 (서버가 밤마다 모은다).

이 통계는 결론이 아니라 근거다. 아이템 추천은 통계에 오른 아이템을 후보로 삼고,
AI가 지금 판의 상황(상대 조합, 내 상태와 가진 아이템, 골드, 모드)을 보고 그중에서 고른다.

수집: 솔로 랭크 챌린저·그랜드마스터 플레이어의 최근 경기(MATCH-V5)에서 참가자마다
챔피언, 포지션, 마지막 아이템 6칸, 핵심 룬, 승패를 저장한다. 소환사 이름·PUUID는 저장하지 않는다.
저장 위치는 공식 게임 자료와 같은 DB(knowledge DB)라서 추천 코드가 같은 경로로 읽는다.
"""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .documents import cached

SCHEMA = """
CREATE TABLE IF NOT EXISTS build_matches (
    match_id TEXT PRIMARY KEY,
    patch TEXT NOT NULL,
    collected_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS build_samples (
    match_id TEXT NOT NULL,
    patch TEXT NOT NULL,
    champion TEXT NOT NULL,
    position TEXT,
    items TEXT NOT NULL,
    keystone INTEGER,
    primary_style INTEGER,
    sub_style INTEGER,
    win INTEGER NOT NULL,
    PRIMARY KEY (match_id, champion)
);
CREATE INDEX IF NOT EXISTS build_samples_champion ON build_samples (champion, patch);
"""
QUEUE = 420                 # 솔로 랭크
MIN_GAMES = 15              # 이보다 적으면 통계 대신 분류별 규칙으로 후보를 정한다
MIN_RATE = 0.05             # 이 비율 이상 완성한 아이템만 후보로 쓴다
KEEP_PATCHES = 3            # 최근 패치 몇 개까지 남길지


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.executescript(SCHEMA)
    if 'perks' not in {row[1] for row in db.execute('PRAGMA table_info(build_samples)')}:
        db.execute('ALTER TABLE build_samples ADD COLUMN perks TEXT')    # 룬 통계용 (1.0.3부터)
    return db


def patch_of(game_version):
    """'16.19.734.1234' → '16.19'."""
    parts = str(game_version or '').split('.')
    return '.'.join(parts[:2]) if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() else None


def samples_from_match(detail):
    """경기 상세 하나 → 참가자별 표본. 협곡 솔로 랭크가 아니거나 다시하기(조기 종료) 경기면 빈 목록."""
    info = (detail or {}).get('info') or {}
    if info.get('queueId') != QUEUE or (info.get('gameDuration') or 0) < 15 * 60:
        return [], None
    patch = patch_of(info.get('gameVersion'))
    if patch is None:
        return [], None
    samples = []
    for player in info.get('participants') or []:
        champion = player.get('championName')
        if not champion:
            continue
        items = [player.get('item%d' % slot) for slot in range(6)]
        perks = player.get('perks') or {}
        styles = perks.get('styles') or []
        primary = styles[0] if styles else {}
        selections = primary.get('selections') or []
        secondary = styles[1] if len(styles) > 1 else {}
        shards = perks.get('statPerks') or {}
        samples.append({
            'champion': champion, 'position': (player.get('teamPosition') or '').upper() or None,
            'items': [int(i) for i in items if isinstance(i, int) and i > 0],
            'keystone': selections[0].get('perk') if selections else None,
            'primary_style': primary.get('style'), 'sub_style': secondary.get('style'),
            'perks': {'primary': [s.get('perk') for s in selections[1:4]],
                      'secondary': [s.get('perk') for s in (secondary.get('selections') or [])[:2]],
                      'shards': [shards.get(k) for k in ('offense', 'flex', 'defense')]},
            'win': bool(player.get('win'))})
    return samples, patch


def save_match(db, match_id, detail, now=None):
    samples, patch = samples_from_match(detail)
    if patch is None:
        patch = 'skip'                          # 다시 받지 않도록 기록만 남긴다
    db.execute('INSERT OR IGNORE INTO build_matches VALUES (?, ?, ?)', (match_id, patch, now or time.time()))
    for sample in samples:
        db.execute('INSERT OR REPLACE INTO build_samples (match_id, patch, champion, position, items, keystone, '
                   'primary_style, sub_style, win, perks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (match_id, patch, sample['champion'], sample['position'], json.dumps(sample['items']),
                    sample['keystone'], sample['primary_style'], sample['sub_style'], int(sample['win']),
                    json.dumps(sample.get('perks'))))
    return len(samples)


def prune(db, keep=KEEP_PATCHES):
    """최근 패치 keep개만 남긴다 (오래된 메타가 근거로 섞이지 않게, DB가 계속 커지지 않게)."""
    patches = sorted({row[0] for row in db.execute("SELECT DISTINCT patch FROM build_samples")},
                     key=lambda p: tuple(int(n) for n in p.split('.')), reverse=True)
    for old in patches[keep:]:
        db.execute('DELETE FROM build_samples WHERE patch=?', (old,))


class Patient:
    """한도 초과(RiotBusy 등 retry_after가 있는 오류)면 기다렸다 같은 요청을 다시 보낸다.

    수집기는 API 서버(사용자 전적 조회)와 같은 라이엇 키를 써서 키 전체 한도에 걸릴 수 있다.
    밤새 시간이 넉넉하므로 그만두지 않고 기다린다. 연속으로 max_waits번 막히면 그때 멈춘다.
    """

    def __init__(self, gateway, sleep=time.sleep, max_waits=8, log=print):
        self.gateway, self.sleep, self.max_waits, self.log = gateway, sleep, max_waits, log

    def get(self, routing, path, params=None):
        waits = 0
        while True:
            try:
                return self.gateway.get(routing, path, params)
            except Exception as error:          # noqa: BLE001 - retry_after가 있는 한도 오류만 기다린다
                retry = getattr(error, 'retry_after', None)
                if retry is None or waits >= self.max_waits:
                    raise
                waits += 1
                self.log('요청 속도 한도에 맞춰 %d초 쉬었다 이어서 받습니다 (%d/%d)' % (int(retry) + 5, waits, self.max_waits))
                self.sleep(retry + 5)


def collect(db, gateway, *, players=300, matches=900, days=7, log=print, clock=time.time, sleep=time.sleep):
    """챌린저·그랜드마스터 플레이어의 최근 솔로 랭크 경기를 matches개까지 모은다. 이미 받은 경기는 건너뛴다.

    gateway.get(routing, path, params)는 server.riot_data.RiotGateway와 같다 (한도·재시도 포함).
    """
    gateway = Patient(gateway, sleep=sleep, log=log)
    puuids = []
    for tier in ('challengerleagues', 'grandmasterleagues'):
        league = gateway.get('platform', '/lol/league/v4/%s/by-queue/RANKED_SOLO_5x5' % tier) or {}
        entries = sorted(league.get('entries') or [], key=lambda e: -(e.get('leaguePoints') or 0))
        puuids += [e['puuid'] for e in entries if e.get('puuid')]
        if len(puuids) >= players:
            break
    known = {row[0] for row in db.execute('SELECT match_id FROM build_matches')}
    since = int(clock() - days * 86400)
    fetched = saved = logged = 0
    for puuid in puuids[:players]:
        if fetched >= matches:
            break
        ids = gateway.get('region', '/lol/match/v5/matches/by-puuid/%s/ids' % puuid,
                          {'queue': QUEUE, 'type': 'ranked', 'startTime': since, 'start': 0, 'count': 10}) or []
        for match_id in ids:
            if match_id in known or fetched >= matches:
                continue
            known.add(match_id)
            detail = gateway.get('region', '/lol/match/v5/matches/%s' % match_id)
            fetched += 1
            if detail:
                with db:
                    saved += save_match(db, match_id, detail)
        if fetched >= logged + 50:                   # 50경기마다 한 줄 (예전: 같은 줄이 여러 번 찍힘)
            logged = fetched
            log('경기 %d개 받음, 표본 %d개 저장' % (fetched, saved))
    with db:
        prune(db)
    log('완료: 경기 %d개, 표본 %d개' % (fetched, saved))
    return fetched, saved


def item_popularity(db_path, champion, position=None):
    """{'games', 'patch', 'items': {아이템: 완성 비율}, 'keystones': {룬: 비율}, 'runes': {일반 룬: 비율},
    'secondary_styles': {보조 트리: 비율}, 'rune_games': 룬 전체 정보가 있는 표본 수}.

    최근 패치 2개를 합쳐 센다. 포지션을 주면 그 포지션 표본만 (표본이 MIN_GAMES보다 적으면 포지션 구분 없이).
    """
    return cached('build-popularity:%s:%s' % (champion, position), db_path,
                  lambda path: _popularity(path, champion, position))


def _popularity(db_path, champion, position):
    empty = {'games': 0, 'patch': [], 'items': {}, 'keystones': {}, 'runes': {}, 'secondary_styles': {}, 'rune_games': 0}
    if not champion or not Path(db_path).exists():
        return empty
    try:
        with closing(sqlite3.connect(str(db_path))) as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='build_samples'").fetchone():
                return empty
            has_perks = 'perks' in {row[1] for row in db.execute('PRAGMA table_info(build_samples)')}
            columns = 'items, keystone, sub_style' + (', perks' if has_perks else ', NULL')
            # 경기 기록의 챔피언 이름과 Data Dragon ID는 대소문자가 다를 수 있다 (FiddleSticks / Fiddlesticks).
            patches = sorted({r[0] for r in db.execute('SELECT DISTINCT patch FROM build_samples WHERE lower(champion)=lower(?)',
                                                       (champion,))},
                             key=lambda p: tuple(int(n) for n in p.split('.')), reverse=True)[:2]
            if not patches:
                return empty
            marks = ','.join('?' * len(patches))
            rows = []
            if position:
                rows = db.execute('SELECT %s FROM build_samples WHERE lower(champion)=lower(?) AND position=? '
                                  'AND patch IN (%s)' % (columns, marks), (champion, position, *patches)).fetchall()
            if len(rows) < MIN_GAMES:
                rows = db.execute('SELECT %s FROM build_samples WHERE lower(champion)=lower(?) AND patch IN (%s)'
                                  % (columns, marks), (champion, *patches)).fetchall()
    except sqlite3.Error:
        return empty
    items, keystones, runes, secondary, rune_games = {}, {}, {}, {}, 0
    for raw, keystone, sub_style, perks in rows:
        for item_id in set(json.loads(raw)):
            items[item_id] = items.get(item_id, 0) + 1
        if keystone:
            keystones[keystone] = keystones.get(keystone, 0) + 1
        if sub_style:
            secondary[sub_style] = secondary.get(sub_style, 0) + 1
        page = json.loads(perks) if perks else None
        if page:
            rune_games += 1
            for rune in set((page.get('primary') or []) + (page.get('secondary') or [])):
                if rune:
                    runes[rune] = runes.get(rune, 0) + 1
    games = len(rows)
    rate = lambda counts, total: {key: round(count / total, 3) for key, count in counts.items()} if total else {}
    return {'games': games, 'patch': patches, 'items': rate(items, games), 'keystones': rate(keystones, games),
            'secondary_styles': rate(secondary, games), 'runes': rate(runes, rune_games), 'rune_games': rune_games}
