"""Locally stored observations from the signed-in player's recent Riot matches."""
import hashlib
from contextlib import closing
import json
import sqlite3
from pathlib import Path


_catalog_cache = {}


def _cached(kind, db_path, builder):
    """픽창 폴링이 같은 DB를 반복해서 읽지 않도록 파일 변경 시각 기준으로 캐싱한다."""
    path = Path(db_path)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    key = (kind, str(path))
    hit = _catalog_cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    value = builder(db_path)
    _catalog_cache[key] = (stamp, value)
    return value


def champion_catalog(db_path):
    """Map Data Dragon numeric champion IDs to names and IDs."""
    return _cached('champion', db_path, _champion_catalog)


def _champion_catalog(db_path):
    path = Path(db_path)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT content FROM records WHERE kind='champion' AND version=(SELECT max(version) FROM records WHERE kind='champion')").fetchall()
    catalog = {}
    for (raw,) in rows:
        try:
            champion = json.loads(raw)
            catalog[int(champion['key'])] = {'id': champion['id'], 'name': champion['name']}
        except (ValueError, KeyError, TypeError):
            continue
    return catalog


def canonical_champion(db_path, name):
    if not name:
        return name
    for row in champion_catalog(db_path).values():
        if name.casefold() in (row['id'].casefold(), row['name'].casefold()):
            return row['id']
    return name


def rune_catalog(db_path):
    return _cached('rune', db_path, _rune_catalog)


def _rune_catalog(db_path):
    path = Path(db_path)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT entity_id, name FROM records WHERE kind='rune' AND version=(SELECT max(version) FROM records WHERE kind='rune')").fetchall()
    return {int(key): name for key, name in rows if str(key).isdigit()}


def named_rune_page(page, catalog):
    if not page:
        return None
    return [{'style_id': style.get('style'),
             'runes': [catalog.get(perk) or f'미확인 룬 {perk}' for perk in style.get('perks', [])]}
            for style in page]


def save_recent_matchups(path, puuid, details):
    """Keep compact, account-partitioned observations; repeated refreshes are idempotent."""
    account = hashlib.sha256(puuid.encode()).hexdigest()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS personal_matchups (
            account TEXT NOT NULL, match_id TEXT NOT NULL, played_at INTEGER,
            champion TEXT NOT NULL, opponent TEXT, lane TEXT, won INTEGER NOT NULL,
            kills INTEGER, deaths INTEGER, assists INTEGER, rune_page TEXT,
            PRIMARY KEY(account, match_id))''')
        for detail in details:
            info = detail.get('info') or {}
            if info.get('gameMode') != 'CLASSIC':
                continue
            player = next((p for p in info.get('participants', []) if p.get('puuid') == puuid), None)
            if player is None:
                continue
            lane = (player.get('teamPosition') or player.get('individualPosition') or '').upper()
            opponents = [p for p in info['participants'] if p.get('teamId') != player.get('teamId')
                         and (p.get('teamPosition') or p.get('individualPosition') or '').upper() == lane]
            opponent = opponents[0].get('championName') if lane and len(opponents) == 1 else None
            styles = (player.get('perks') or {}).get('styles') or []
            page = [{'style': style.get('style'),
                     'perks': [selection.get('perk') for selection in style.get('selections', [])]}
                    for style in styles]
            db.execute('''INSERT OR REPLACE INTO personal_matchups
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (account, detail.get('metadata', {}).get('matchId'), info.get('gameStartTimestamp'),
                 player.get('championName'), opponent, lane, int(bool(player.get('win'))),
                 player.get('kills'), player.get('deaths'), player.get('assists'),
                 json.dumps(page) if page else None))
        db.commit()


def personal_context(path, puuid, champion, opponent=None, lane=None):
    path = Path(path)
    empty = {'champion_games': 0, 'champion_wins': 0, 'matchup_games': 0, 'matchup_wins': 0,
             'latest_rune_page': None,
             'scope': '이 계정에서 조회해 저장한 협곡 경기만 포함. 전체 플레이어 상성 통계가 아님.'}
    if not path.exists() or not champion:
        return empty
    account = hashlib.sha256(puuid.encode()).hexdigest()
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute('''SELECT opponent, lane, won, kills, deaths, assists, rune_page
            FROM personal_matchups WHERE account=? AND lower(champion)=lower(?)
            ORDER BY played_at DESC''', (account, champion)).fetchall()
    matches = [r for r in rows if opponent and r[0] and r[0].casefold() == opponent.casefold()
               and (not lane or r[1] == lane.upper())]
    latest = next((json.loads(r[6]) for r in rows if r[6]), None)
    return {'champion_games': len(rows), 'champion_wins': sum(r[2] for r in rows),
            'matchup_games': len(matches), 'matchup_wins': sum(r[2] for r in matches),
            'latest_rune_page': latest,
            'scope': '이 계정에서 조회해 저장한 협곡 경기만 포함. 전체 플레이어 상성 통계가 아님.'}
