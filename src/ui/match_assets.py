"""Asynchronous Data Dragon spell, keystone and item icons for match and live screens."""
import json
import weakref

from PySide6.QtCore import QObject, QRectF, Qt, QUrl
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from shiboken6 import isValid

from .portraits import BASE


def rounded(pixmap, radius):
    """모서리를 둥글게 자른 그림. QLabel의 border-radius는 그림을 자르지 않아서 직접 자른다."""
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(result.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


class MatchAssets(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.version = None
        self.spells = None
        self.perks = None
        self.items = None
        self.pending = {}
        self.cache = {}
        self.inflight = set()
        self.version_requested = False
        self.catalog_requested = False

    def attach(self, label, kind, asset_id):
        if asset_id is None:
            label.setToolTip('정보 없음')
            return
        key = (kind, int(asset_id))
        label.setProperty('assetKey', '%s:%d' % key)
        self.pending.setdefault(key, []).append(weakref.ref(label))
        if key in self.cache:
            self._display(key)
        elif self.version:
            self._catalogs()
            self._icon(key)
        elif not self.version_requested:
            self.version_requested = True
            self._get(f'{BASE}/api/versions.json', self._versions)

    def _get(self, url, callback):
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(10000)
        reply = self.network.get(request)
        def finished():
            data = bytes(reply.readAll()) if reply.error() == QNetworkReply.NoError else b''
            reply.deleteLater()
            callback(data)
        reply.finished.connect(finished)

    def _versions(self, data):
        try:
            version = json.loads(data)[0]
            if not version or not all(c.isdigit() or c == '.' for c in version):
                return
            self.version = version
            self._catalogs()
            for key in list(self.pending):
                if key[0] == 'profile':
                    self._icon(key)
        except (ValueError, IndexError, TypeError):
            self.version_requested = False

    def _catalogs(self):
        if self.catalog_requested:
            return
        self.catalog_requested = True
        self._get(f'{BASE}/cdn/{self.version}/data/ko_KR/summoner.json', self._spells)
        self._get(f'{BASE}/cdn/{self.version}/data/ko_KR/runesReforged.json', self._perks)
        self._get(f'{BASE}/cdn/{self.version}/data/ko_KR/item.json', self._items)

    def _spells(self, data):
        try:
            catalog = json.loads(data)['data'].values()
            self.spells = {int(row['key']): (row['image']['full'], row['name']) for row in catalog}
        except (ValueError, KeyError, TypeError):
            self.spells = {}
        for key in list(self.pending):
            if key[0] == 'spell':
                self._icon(key)

    def _perks(self, data):
        try:
            catalog = json.loads(data)
            self.perks = {rune['id']: (rune['icon'], rune['name'])
                          for style in catalog for slot in style['slots'] for rune in slot['runes']}
            # 룬 트리(정밀, 지배 …) 아이콘도 같은 'rune' 종류로 보여 준다. 트리 ID와 룬 ID는 겹치지 않는다.
            self.perks.update({style['id']: (style['icon'], style['name']) for style in catalog})
        except (ValueError, KeyError, TypeError):
            self.perks = {}
        for key in list(self.pending):
            if key[0] == 'rune':
                self._icon(key)

    def _items(self, data):
        try:
            catalog = json.loads(data)['data']
            self.items = {int(key): (row['image']['full'], row['name']) for key, row in catalog.items()}
        except (ValueError, KeyError, TypeError):
            self.items = {}
        for key in list(self.pending):
            if key[0] == 'item':
                self._icon(key)

    def _icon(self, key):
        kind, asset_id = key
        if kind == 'profile':
            # 소환사 아이콘은 목록 없이 버전과 ID만으로 주소가 정해진다.
            if self.version and key not in self.inflight:
                self.inflight.add(key)
                self._get(f'{BASE}/cdn/{self.version}/img/profileicon/{asset_id}.png',
                          lambda data: self._loaded(key, '소환사 아이콘', data))
            return
        catalog = {'spell': self.spells, 'rune': self.perks, 'item': self.items}.get(kind)
        if catalog is None or key in self.inflight or asset_id not in catalog:
            return
        filename, name = catalog[asset_id]
        parts = filename.split('/')
        if any(part in ('', '.', '..') for part in parts):
            return
        self.inflight.add(key)
        if kind == 'spell':
            url = f'{BASE}/cdn/{self.version}/img/spell/{filename}'
        elif kind == 'item':
            url = f'{BASE}/cdn/{self.version}/img/item/{filename}'
        else:
            url = f'{BASE}/cdn/img/{filename}'
        self._get(url, lambda data: self._loaded(key, name, data))

    def _loaded(self, key, name, data):
        self.inflight.discard(key)
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.cache[key] = (pixmap, name)
            self._display(key)

    def _display(self, key):
        pixmap, name = self.cache[key]
        for reference in self.pending.pop(key, []):
            label = reference()
            if label is not None and isValid(label) and label.property('assetKey') == '%s:%d' % key:
                scaled = pixmap.scaled(label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                radius = label.property('roundedRadius')
                label.setPixmap(rounded(scaled, radius) if radius else
                                pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                label.setToolTip(name)
                label.setAccessibleName(name)

