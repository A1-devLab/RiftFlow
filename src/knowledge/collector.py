import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from .patches import parse_patch

PATCH_LIST = 'https://www.leagueoflegends.com/ko-kr/news/tags/patch-notes/'
DDRAGON = 'https://ddragon.leagueoflegends.com'
DB_PATH = Path('data/riftflow.db')


def fetch(url):
    request = Request(url, headers={'User-Agent': 'RiftFlow-Study-Demo/0.1'})
    with urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8')


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self.main, self.heading = [], [], [], []
        self.skip = 0
        self.in_main = False
        self.in_heading = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'main':
            self.in_main = True
        if tag == 'h1':
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag == 'main':
            self.in_main = False
        if tag == 'h1':
            self.in_heading = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())
            if self.in_main:
                self.main.append(data.strip())
            if self.in_heading:
                self.heading.append(data.strip())


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('''CREATE TABLE IF NOT EXISTS records (
        kind TEXT NOT NULL, version TEXT NOT NULL, entity_id TEXT NOT NULL,
        name TEXT NOT NULL, content TEXT NOT NULL, source_url TEXT NOT NULL,
        content_hash TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (kind, version, entity_id))''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(records)')}
    for name, definition in [('collected_at', 'TEXT'), ('sample_match_count', 'INTEGER'),
                             ('source', "TEXT NOT NULL DEFAULT 'Riot Games'")]:
        if name not in columns:
            db.execute(f'ALTER TABLE records ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS patch_changes (
        version TEXT NOT NULL, source_url TEXT NOT NULL, entity_id TEXT NOT NULL,
        entity_kind TEXT NOT NULL, name TEXT NOT NULL, change_type TEXT NOT NULL,
        content TEXT NOT NULL, collected_at TEXT NOT NULL,
        sample_match_count INTEGER, source TEXT NOT NULL,
        PRIMARY KEY (version, source_url, entity_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS patch_changes_filter ON patch_changes(version, entity_kind, change_type)')
    db.commit()
    return db


def save(db, kind, version, entity_id, name, content, url):
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    key = (kind, version, str(entity_id))
    now = datetime.now(timezone.utc).isoformat()
    old = db.execute('SELECT content_hash, name, source_url FROM records WHERE kind=? AND version=? AND entity_id=?', key).fetchone()
    if old and old == (digest, name, url):
        db.execute('UPDATE records SET collected_at=? WHERE kind=? AND version=? AND entity_id=?', (now, *key))
        return 'unchanged'
    db.execute('''INSERT INTO records
        (kind, version, entity_id, name, content, source_url, content_hash, updated_at, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kind, version, entity_id) DO UPDATE SET
        name=excluded.name, content=excluded.content, source_url=excluded.source_url,
        content_hash=excluded.content_hash, updated_at=excluded.updated_at,
        collected_at=excluded.collected_at''',
        (*key, name, content, url, digest, now, now))
    return 'updated' if old else 'new'


def store_patch(db, html, url):
    page = Page(html)
    title = ' '.join(page.heading)
    content = '\n'.join(page.main or page.text)
    match = re.search(r'\b(\d{1,2}\.\d{1,2})\b', title)
    if not match or len(content) < 200:
        raise ValueError(f'패치 버전 또는 본문을 읽지 못했습니다: {url}')
    version = match.group(1)
    entities = parse_patch(html)
    old_count = db.execute('SELECT COUNT(*) FROM patch_changes WHERE version=? AND source_url=?',
                           (version, url)).fetchone()[0]
    if old_count and not entities:
        raise ValueError('기존 구조화 자료를 빈 파싱 결과로 대체할 수 없습니다.')
    if not entities:
        print(f'주의: 구조화 가능한 변경 섹션이 없어 원문만 저장합니다: {url}', flush=True)
    status = save(db, 'patch', version, url, title, content, url)
    db.execute('DELETE FROM patch_changes WHERE version=? AND source_url=?', (version, url))
    now = datetime.now(timezone.utc).isoformat()
    for index, entity in enumerate(entities):
        entity_id = f"{entity['section_id']}:{index}"
        db.execute('INSERT INTO patch_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (version, url, entity_id, entity['entity_kind'], entity['entity_name'],
             entity['change_type'], json.dumps(entity, ensure_ascii=False, sort_keys=True),
             now, None, 'Riot Games'))
    return status


def update(db, limit=3):
    if not isinstance(limit, int) or not 1 <= limit <= 12:
        raise ValueError('패치 수는 1~12여야 합니다.')
    counts = dict(new=0, updated=0, unchanged=0)

    def add(kind, version, entity_id, name, content, url):
        counts[save(db, kind, version, entity_id, name, content, url)] += 1

    with db:
        version = json.loads(fetch(f'{DDRAGON}/api/versions.json'))[0]
        print(f'Data Dragon 버전: {version}', flush=True)
        for kind, filename in [('champion', 'champion.json'), ('item', 'item.json'), ('rune', 'runesReforged.json')]:
            url = f'{DDRAGON}/cdn/{version}/data/ko_KR/{filename}'
            data = json.loads(fetch(url))
            if kind == 'rune':
                rows = [(str(r['id']), r) for tree in data for slot in tree['slots'] for r in slot['runes']]
            else:
                rows = data['data'].items()
            for entity_id, entity in rows:
                add(kind, version, entity_id, entity['name'], json.dumps(entity, ensure_ascii=False, sort_keys=True), url)

        listing = Page(fetch(PATCH_LIST))
        urls = []
        for href in listing.links:
            url = urljoin(PATCH_LIST, href).split('?')[0].rstrip('/') + '/'
            if (urlsplit(url).hostname == 'www.leagueoflegends.com'
                    and re.search(r'/ko-kr/news/game-updates/(?:league-of-legends-)?patch-\d+-\d+-notes/$', url)
                    and url not in urls):
                urls.append(url)
        if not urls:
            raise ValueError('패치 링크를 찾지 못했습니다. 공식 사이트 구조를 확인하세요.')
        for url in urls[:limit]:
            counts[store_patch(db, fetch(url), url)] += 1
            print(f'패치 확인: {url}', flush=True)
    print(f"완료: 신규 {counts['new']} / 변경 {counts['updated']} / 동일 {counts['unchanged']}")
    return counts
