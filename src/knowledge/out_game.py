"""Read-only structured patch queries and explicit patch synchronization."""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError


def get_patch_changes(patch=None, *, kind=None, change_type=None, name=None,
                      db_path='data/riftflow.db'):
    if kind not in (None, 'champion', 'item', 'rune'):
        raise ValueError('kind는 champion, item, rune 중 하나여야 합니다.')
    if change_type not in (None, 'buff', 'nerf', 'adjusted', 'unknown', 'unchanged'):
        raise ValueError('지원하지 않는 변경 종류입니다.')
    path = Path(db_path).resolve()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='patch_changes'").fetchone():
            return []
        if patch is None:
            versions = [r[0] for r in db.execute('SELECT DISTINCT version FROM patch_changes')]
            patch = max(versions, key=lambda v: tuple(map(int, v.split('.'))), default=None)
        rows = db.execute('''SELECT * FROM patch_changes WHERE version=?
            AND (? IS NULL OR entity_kind=?) AND (? IS NULL OR change_type=?)
            AND (? IS NULL OR instr(name, ?)>0) ORDER BY entity_kind, name, entity_id''',
            (patch, kind, kind, change_type, change_type, name, name)).fetchall()
        return [dict(json.loads(r['content']), entity_id=r['entity_id'],
                     data_type='patch_change', patch_version=r['version'],
                     source_url=r['source_url'], source=r['source'],
                     collected_at=r['collected_at'], sample_match_count=r['sample_match_count'])
                for r in rows]


def sync_patch(patch, *, source_url=None, db_path='data/riftflow.db'):
    """Update one official Korean article; no Data Dragon version inference."""
    from .collector import Page, connect, fetch, store_patch
    if not re.fullmatch(r'\d{1,2}\.\d{1,2}', patch):
        raise ValueError('패치는 25.18 같은 표시 버전이어야 합니다.')
    url = source_url or f"https://www.leagueoflegends.com/ko-kr/news/game-updates/patch-{patch.replace('.', '-')}-notes/"
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != 'www.leagueoflegends.com' or not parts.path.startswith('/ko-kr/news/game-updates/'):
        raise ValueError('한국어 라이엇 공식 패치 URL만 허용합니다.')
    try:
        html = fetch(url)
    except HTTPError as error:
        if source_url is not None or error.code != 404:
            raise
        url = url.replace('/patch-', '/league-of-legends-patch-')
        html = fetch(url)
    match = re.search(r'\b(\d{1,2}\.\d{1,2})\b', ' '.join(Page(html).heading))
    if not match or match.group(1) != patch:
        raise ValueError('요청 패치와 원문 제목의 패치가 다릅니다.')
    with closing(connect(db_path)) as db, db:
        status = store_patch(db, html, url)
    return {'patch_version': patch, 'status': status, 'source_url': url,
            'entity_count': len(get_patch_changes(patch, db_path=db_path))}
