"""RiftFlow 맛보기: Python 3.10+ 표준 라이브러리만 사용합니다."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

PATCH_LIST = 'https://www.leagueoflegends.com/ko-kr/news/tags/patch-notes/'
DDRAGON = 'https://ddragon.leagueoflegends.com'
DB_PATH = Path('data/riftflow.db')


def fetch(url):
    request = Request(url, headers={'User-Agent': 'RiftFlow-Study-Demo/0.1'})
    with urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8')


class Page(HTMLParser):
    """공식 페이지의 링크와 본문을 읽는 간단한 HTML 파서."""
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
    return db


def save(db, kind, version, entity_id, name, content, url):
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    key = (kind, version, str(entity_id))
    old = db.execute('SELECT content_hash FROM records WHERE kind=? AND version=? AND entity_id=?', key).fetchone()
    if old and old[0] == digest:
        return 'unchanged'
    db.execute('''INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kind, version, entity_id) DO UPDATE SET
        name=excluded.name, content=excluded.content, source_url=excluded.source_url,
        content_hash=excluded.content_hash, updated_at=excluded.updated_at''',
        (*key, name, content, url, digest, datetime.now(timezone.utc).isoformat()))
    return 'updated' if old else 'new'


def update(db, limit):
    counts = dict(new=0, updated=0, unchanged=0)

    def add(kind, version, entity_id, name, content, url):
        counts[save(db, kind, version, entity_id, name, content, url)] += 1

    # 모든 다운로드가 성공한 경우에만 이번 업데이트를 DB에 반영합니다.
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
                    and '/ko-kr/news/game-updates/' in url and 'patch' in url
                    and url not in urls):
                urls.append(url)
        if not urls:
            raise ValueError('패치 링크를 찾지 못했습니다. 공식 사이트 구조를 확인하세요.')
        for url in urls[:limit]:
            page = Page(fetch(url))
            title = ' '.join(page.heading)
            content = '\n'.join(page.main or page.text)
            if not title or len(content) < 200:
                raise ValueError(f'패치 본문을 읽지 못했습니다: {url}')
            match = re.search(r'\b(\d{1,2}\.\d{1,2})\b', title)
            patch = match.group(1) if match else 'unknown'
            add('patch', patch, url, title, content, url)
            print(f'패치 확인: {title}', flush=True)
    print(f"완료: 신규 {counts['new']} / 변경 {counts['updated']} / 동일 {counts['unchanged']}")
    return counts
