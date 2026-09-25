"""Live scoreboard with estimated team gold and in-game coaching questions."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget,
)

from game_phases.in_game.desktop import RECOMMEND_QUESTION
from ui.match_assets import MatchAssets
from ui.portraits import ChampionPortraits

ITEM_SLOTS = 7


def label(text='', name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


class GoldBar(QWidget):
    """아군·상대 추정 골드 비율. 정확한 값이 아니므로 숫자는 옆 문구에서 '추정'으로 보여 준다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ally = self.enemy = 0
        self.setMinimumHeight(14)
        self.setMaximumHeight(14)

    def set_values(self, ally, enemy):
        self.ally, self.enemy = max(0, ally), max(0, enemy)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#273850'))
        painter.drawRoundedRect(rect, 7, 7)
        total = self.ally + self.enemy
        if total:
            split = rect.width() * self.ally / total
            painter.setBrush(QColor('#d64e61'))
            painter.drawRoundedRect(rect, 7, 7)
            painter.setBrush(QColor('#397ee8'))
            painter.drawRoundedRect(QRectF(rect.x(), rect.y(), split, rect.height()), 7, 7)
        painter.end()


class PlayerRow(QFrame):
    """스코어보드 한 줄. 폴링마다 새로 만들지 않고 값만 바꿔 깜빡임을 막는다."""

    def __init__(self, portraits, assets, parent=None):
        super().__init__(parent)
        self.setObjectName('playerRow')
        self.portraits, self.assets = portraits, assets
        self.champion_key = None
        self.item_ids = [None] * ITEM_SLOTS
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)
        self.position = label('', 'rowPosition')
        self.position.setFixedWidth(30)
        row.addWidget(self.position)
        self.portrait = label('?', 'rowPortrait')
        self.portrait.setFixedSize(38, 38)
        self.portrait.setAlignment(Qt.AlignCenter)
        row.addWidget(self.portrait)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.champion = label('', 'rowChampion')
        self.player = label('', 'rowPlayer')
        # 긴 이름이 줄 전체 폭을 늘려 아이템 칸을 밀어내지 않게 한다.
        for widget in (self.champion, self.player):
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.champion)
        names.addWidget(self.player)
        row.addLayout(names, 3)
        self.level = label('', 'rowStat')
        self.level.setFixedWidth(38)
        self.kda = label('', 'rowKda')
        self.kda.setFixedWidth(70)
        self.cs = label('', 'rowStat')
        self.cs.setFixedWidth(78)
        self.gold = label('', 'rowGold')
        self.gold.setFixedWidth(68)
        for widget in (self.level, self.kda, self.cs, self.gold):
            row.addWidget(widget)
        self.items = []
        items = QHBoxLayout()
        items.setSpacing(2)
        for _ in range(ITEM_SLOTS):
            icon = label('', 'rowItem')
            icon.setFixedSize(24, 24)
            icon.setAlignment(Qt.AlignCenter)
            items.addWidget(icon)
            self.items.append(icon)
        row.addLayout(items)
        self.clear()

    def _set_me(self, me):
        if self.property('me') != me:
            self.setProperty('me', me)
            self.style().unpolish(self)
            self.style().polish(self)

    def clear(self):
        self._set_me(False)
        self.champion_key = None
        self.portrait.clear()
        self.portrait.setText('—')
        for widget in (self.position, self.champion, self.player, self.level, self.kda, self.cs, self.gold):
            widget.setText('')
        self._set_items([])

    def _set_items(self, items):
        by_slot = {}
        for index, item in enumerate(items):
            slot = item.get('slot')
            by_slot[slot if isinstance(slot, int) and 0 <= slot < ITEM_SLOTS else index] = item
        for slot, icon in enumerate(self.items):
            item = by_slot.get(slot)
            item_id = item['id'] if item else None
            if item_id == self.item_ids[slot]:
                continue
            self.item_ids[slot] = item_id
            icon.clear()
            icon.setToolTip(item['name'] if item else '')
            icon.setAccessibleName(item['name'] if item else '빈 슬롯')
            if item:
                self.assets.attach(icon, 'item', item_id)

    def show_entry(self, entry):
        if entry is None:
            self.clear()
            return
        self._set_me(bool(entry.get('is_me')))
        self.position.setText(entry['position_name'])
        if self.champion_key != entry['champion']:
            self.champion_key = entry['champion']
            self.portrait.clear()
            self.portrait.setText(entry['champion'][:1])
            self.portrait.setToolTip(entry['champion'])
            self.portraits.attach(self.portrait, entry['champion'])
        self.champion.setText(entry['champion'] + ('  (나)' if entry.get('is_me') else ''))
        self.player.setText('부활까지 %d초' % entry['respawn_timer'] if entry['is_dead'] else entry['name'])
        self.player.setObjectName('rowDead' if entry['is_dead'] else 'rowPlayer')
        self.player.style().unpolish(self.player)
        self.player.style().polish(self.player)
        self.level.setText('Lv %d' % entry['level'])
        self.kda.setText(entry['kda'])
        rate = entry.get('cs_per_min')
        self.cs.setText('%d CS' % entry['cs'] + (' (%.1f)' % rate if rate is not None else ''))
        self.gold.setText('≈%s' % f"{entry['estimated_gold']:,}")
        self.gold.setToolTip('보유 아이템 가격 합계 추정치')
        self._set_items(entry['items'])


class TeamPanel(QFrame):
    def __init__(self, title, portraits, assets, parent=None):
        super().__init__(parent)
        self.setObjectName('teamPanel')
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)
        head = QHBoxLayout()
        self.title = label(title, 'teamTitle')
        self.total = label('', 'teamTotal')
        head.addWidget(self.title)
        head.addStretch()
        head.addWidget(self.total)
        box.addLayout(head)
        self.rows = [PlayerRow(portraits, assets) for _ in range(5)]
        for row in self.rows:
            box.addWidget(row)

    def show_team(self, entries, total=None):
        for index, row in enumerate(self.rows):
            row.show_entry(entries[index] if index < len(entries) else None)
        kills = sum(e['kills'] for e in entries)
        self.total.setText('킬 %d' % kills + (' · 추정 골드 %s' % f'{total:,}' if total is not None else ''))


class InGamePage(QWidget):
    askRequested = Signal(object)
    refreshRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('inGame')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.portraits = ChampionPortraits(self)
        self.assets = MatchAssets(self)
        self.view = {'in_game': False}
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        board = QWidget()
        left = QVBoxLayout(board)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(label('인게임', 'title'))
        self.clock = label('--:--', 'clock')
        header.addWidget(self.clock)
        header.addStretch()
        self.refresh = QPushButton('스코어보드 새로고침')
        self.refresh.clicked.connect(self.refreshRequested.emit)
        header.addWidget(self.refresh)
        left.addLayout(header)
        self.state = label('', 'subtle')
        self.state.setWordWrap(True)
        left.addWidget(self.state)
        self.gold_bar = GoldBar()
        left.addWidget(self.gold_bar)
        self.gold_text = label('', 'subtle')
        self.gold_text.setWordWrap(True)
        left.addWidget(self.gold_text)
        self.ally = TeamPanel('아군', self.portraits, self.assets)
        self.enemy = TeamPanel('상대', self.portraits, self.assets)
        left.addWidget(self.ally)
        left.addWidget(self.enemy)
        left.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(board)
        root.addWidget(scroll, 5)

        coach = QFrame(objectName='coachPanel')
        right = QVBoxLayout(coach)
        right.setContentsMargins(14, 14, 14, 14)
        right.addWidget(label('인게임 코치', 'panelTitle'))
        note = label('스코어보드에 있는 값(레벨·KDA·CS·아이템)과 공식 아이템 자료로만 답합니다. '
                     '시야, 상대 주문 쿨타임, 오브젝트 타이머는 확인할 수 없습니다.', 'subtle')
        note.setWordWrap(True)
        right.addWidget(note)
        self.answer = QTextBrowser()
        self.answer.setPlainText('게임에 접속하면 현재 스코어보드를 바탕으로 질문에 답합니다.')
        right.addWidget(self.answer, 1)
        self.recommend = QPushButton('지금 살 아이템 추천')
        self.recommend.setObjectName('primary')
        self.recommend.clicked.connect(lambda: self._emit(RECOMMEND_QUESTION))
        right.addWidget(self.recommend)
        form = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setMaxLength(1000)
        self.question.setPlaceholderText('예: 지금 우리 팀이 불리해?')
        self.question.returnPressed.connect(self.submit)
        self.send = QPushButton('질문')
        self.send.clicked.connect(self.submit)
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        right.addLayout(form)
        coach.setMinimumWidth(300)
        root.addWidget(coach, 3)
        self.show_disconnected()

    def show_view(self, view):
        self.view = view
        self.clock.setText(view.get('clock') or '--:--')
        if view.get('perspective_known'):
            self.state.setText('게임 연결됨 · 2~3초 간격으로 갱신합니다.')
        else:
            self.state.setText('게임 연결됨 · 내 소환사를 스코어보드에서 찾지 못해 블루팀을 아군으로 표시합니다.')
        gold = view.get('team_gold')
        if gold:
            self.gold_bar.set_values(gold['ally'], gold['enemy'])
            self.gold_text.setText('아군 추정 %s · 상대 추정 %s · 차이 %+d  —  보유 아이템 가격 합계 기준이라 '
                                   '아직 쓰지 않은 골드는 빠져 있습니다.' % (
                                       f"{gold['ally']:,}", f"{gold['enemy']:,}", gold['diff']))
        else:
            self.gold_bar.set_values(0, 0)
            self.gold_text.setText('팀 골드 추정치를 계산하지 못했습니다.')
        self.ally.show_team(view.get('allies') or [], gold['ally'] if gold else None)
        self.enemy.show_team(view.get('enemies') or [], gold['enemy'] if gold else None)

    def show_loading(self):
        if self.view.get('in_game'):
            self.show_disconnected()
        self.state.setText('게임을 불러오고 있습니다. 로딩이 끝나면 스코어보드를 자동으로 표시합니다.')

    def show_disconnected(self):
        self.view = {'in_game': False}
        self.clock.setText('--:--')
        self.state.setText('게임 접속을 기다리고 있습니다. 게임이 시작되면 자동으로 이 화면으로 넘어옵니다.')
        self.gold_bar.set_values(0, 0)
        self.gold_text.setText('')
        self.ally.show_team([])
        self.enemy.show_team([])
        self.ally.total.setText('')
        self.enemy.total.setText('')

    def _emit(self, question):
        if not question or not self.send.isEnabled():
            return
        self.askRequested.emit({'question': question, 'view': self.view})

    def submit(self):
        self._emit(self.question.text().strip())

    def set_busy(self, busy):
        for widget in (self.send, self.recommend, self.refresh):
            widget.setEnabled(not busy)


STYLE = """
QWidget#inGame { background: #101722; color: #e8edf4; }
QWidget#inGame QLabel { background: transparent; }
QLabel#title { color: #edf4ff; font-size: 27px; font-weight: 700; }
QLabel#clock { background: #173a38; color: #72e2c7; border-radius: 8px; padding: 6px 10px; font-size: 16px; font-weight: 700; }
QLabel#subtle { color: #94a8c2; font-size: 12px; }
QLabel#panelTitle { color: #edf4ff; font-size: 18px; font-weight: 700; }
QFrame#teamPanel, QFrame#coachPanel { background: #151f2e; border: 1px solid #2a3a4f; border-radius: 12px; }
QLabel#teamTitle { color: #7dc9e9; font-size: 16px; font-weight: 700; }
QLabel#teamTotal { color: #aabbd2; font-size: 12px; }
QFrame#playerRow { background: #182536; border: 1px solid transparent; border-radius: 8px; }
QFrame#playerRow[me="true"] { background: #1b3439; border: 1px solid #56d7b6; }
QLabel#rowPosition { color: #8d9cb3; font-size: 12px; }
QLabel#rowPortrait { background: #233449; color: #a7bddb; border: 1px solid #415671; border-radius: 6px; font-weight: 700; }
QLabel#rowChampion { font-size: 14px; font-weight: 700; color: #e8edf4; }
QLabel#rowPlayer { font-size: 11px; color: #8d9cb3; }
QLabel#rowDead { font-size: 11px; color: #ff8595; font-weight: 700; }
QLabel#rowStat { color: #c0cee3; }
QLabel#rowKda { color: #ffffff; font-size: 15px; font-weight: 700; }
QLabel#rowGold { color: #f0c86b; font-weight: 700; }
QLabel#rowItem { background: #0e1724; border: 1px solid #2e3f56; border-radius: 4px; }
QTextBrowser { background: #101a28; color: #e8edf4; border: 1px solid #2a3a4f; border-radius: 10px; padding: 10px; }
QLineEdit { background: #172334; color: #e8edf4; border: 1px solid #354860; border-radius: 7px; padding: 9px; }
QPushButton { background: #223247; color: #e8edf4; border: 1px solid #34475e; border-radius: 7px; padding: 9px 13px; }
QPushButton:disabled { color: #64758a; background: #18212e; }
QPushButton#primary { background: #56d7b6; color: #09291f; border: none; font-weight: 700; }
QPushButton#primary:disabled { background: #2c5a50; color: #88a89f; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
"""
