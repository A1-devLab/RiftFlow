"""Non-blocking, cached Data Dragon champion portraits for match cards."""
import json
import weakref

from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from shiboken6 import isValid

BASE = 'https://ddragon.leagueoflegends.com'


class ChampionPortraits(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.started = False
        self.catalog = None
        self.version = None
        self.waiting = {}
        self.cache = {}
        self.inflight = set()

    def attach(self, label, champion):
        key = champion.casefold()
        # MATCH-V5 historically uses FiddleSticks; Data Dragon uses Fiddlesticks.
        self.waiting.setdefault(key, []).append(weakref.ref(label))
        if key in self.cache:
            self._display(key)
        elif self.catalog is not None:
            self._portrait(key)
        elif not self.started:
            self.started = True
            self._get(BASE + '/api/versions.json', self._versions)

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
            versions = json.loads(data)
            self.version = versions[0]
            if not isinstance(self.version, str) or not all(c.isdigit() or c == '.' for c in self.version):
                raise ValueError('Invalid version')
        except (ValueError, IndexError, KeyError, TypeError):
            self.started = False
            return
        self._get(f'{BASE}/cdn/{self.version}/data/ko_KR/champion.json', self._catalog)

    def _catalog(self, data):
        try:
            champions = json.loads(data)['data'].values()
            catalog = {}
            for champion in champions:
                filename = champion['image']['full']
                if '/' in filename or '\\' in filename:
                    continue
                for name in (champion['id'], champion['name']):
                    catalog[name.casefold()] = filename
            self.catalog = catalog
        except (ValueError, KeyError, TypeError, AttributeError):
            self.started = False
            return
        for key in list(self.waiting):
            self._portrait(key)

    def _portrait(self, key):
        filename = self.catalog.get(key)
        if not filename or key in self.inflight:
            return
        self.inflight.add(key)
        self._get(f'{BASE}/cdn/{self.version}/img/champion/{filename}',
                  lambda data: self._loaded(key, data))

    def _loaded(self, key, data):
        self.inflight.discard(key)
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.cache[key] = pixmap
            self._display(key)

    def _display(self, key):
        for reference in self.waiting.pop(key, []):
            label = reference()
            if label is not None and isValid(label):
                label.setPixmap(self.cache[key].scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
