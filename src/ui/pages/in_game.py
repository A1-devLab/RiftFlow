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
ITEM_PICKS = 3


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
        if entry.get('current_gold') is not None:
            self.gold.setText('보유 %s' % f"{entry['current_gold']:,}")
            self.gold.setToolTip('지금 가진 골드 (정확한 값). 아이템 가격 합계 추정 %s' % f"{entry['estimated_gold']:,}")
        else:
            self.gold.setText('≈%s' % f"{entry['estimated_gold']:,}")
            self.gold.setToolTip('산 아이템 가격 합계 추정치 (가진 돈이 아님)')
        self._set_items(entry['items'])


class ItemPick(QFrame):
    """추천 아이템 한 칸: 아이콘, 이름, 가격, 짧은 이유."""

    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.setObjectName('itemPick')
        self.assets = assets
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(9)
        self.icon = label('', 'pickIcon')
        self.icon.setFixedSize(36, 36)
        row.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        head = QHBoxLayout()
        self.name = label('', 'pickName')
        self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.price = label('', 'pickPrice')
        head.addWidget(self.name, 1)
        head.addWidget(self.price)
        text.addLayout(head)
        self.reason = label('', 'pickReason')
        self.reason.setWordWrap(True)
        text.addWidget(self.reason)
        row.addLayout(text, 1)
        self.show_option(None)

    def show_option(self, option):
        self.setVisible(option is not None)
        self.icon.clear()
        if option is None:
            return
        self.name.setText(option['name'])
        self.name.setToolTip(option['name'])
        self.price.setText(f"{option['price']:,}")
        # 보유 골드는 글로 안내하지 않고 가격 색으로만 보여 준다: 초록 = 지금 살 수 있음.
        affordable = option.get('affordable')
        self.price.setProperty('affordable', 'yes' if affordable else 'no' if affordable is False else 'unknown')
        self.price.style().unpolish(self.price)
        self.price.style().polish(self.price)
        remaining = option.get('remaining_cost')
        self.price.setToolTip('가진 재료를 빼면 %s골드' % f'{remaining:,}'
                              if remaining is not None and remaining != option['price'] else '')
        self.reason.setText(option.get('reason') or '')
        self.assets.attach(self.icon, 'item', option['item_id'])


class ItemCard(QFrame):
    """인게임 아이템 추천 칸. 후보 3개와 가격을 대화와 따로 보여 준다."""
    requested = Signal()

    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.setObjectName('itemCard')
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label('추천 아이템', 'panelTitle'))
        head.addStretch()
        self.button = QPushButton('추천 받기')
        self.button.setObjectName('primary')
        self.button.clicked.connect(self.requested.emit)
        head.addWidget(self.button)
        box.addLayout(head)
        self.caption = label('', 'subtle')
        self.caption.setWordWrap(True)
        box.addWidget(self.caption)
        self.picks = [ItemPick(assets) for _ in range(ITEM_PICKS)]
        for pick in self.picks:
            box.addWidget(pick)
        self.clear()

    def clear(self, text='게임 중 버튼을 누르면 지금 상황에 맞는 아이템 3개를 골라 줍니다.'):
        self.caption.setText(text)
        self.button.setText('추천 받기')
        for pick in self.picks:
            pick.show_option(None)

    def show_result(self, result):
        options = result.get('options') or []
        if not options:
            self.caption.setText(result.get('message') or '추천을 만들지 못했습니다.')
            return
        for index, pick in enumerate(self.picks):
            pick.show_option(options[index] if index < len(options) else None)
        summary = result.get('summary') or ''
        source = ' · '.join(x for x in (result.get('mode_name'), result.get('version')) if x)
        self.caption.setText(summary + ('  (%s)' % source if source and summary else source))
        self.button.setText('다시 추천')


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
        self.total.setText('킬 %d' % kills + (' · 아이템 가격 합계 %s' % f'{total:,}' if total is not None else ''))


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

        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        self.items = ItemCard(self.assets)
        self.items.requested.connect(lambda: self._emit(RECOMMEND_QUESTION))
        self.recommend = self.items.button
        column.addWidget(self.items)
        coach = QFrame(objectName='coachPanel')
        right = QVBoxLayout(coach)
        right.setContentsMargins(14, 12, 14, 12)
        right.addWidget(label('AI에게 질문', 'panelTitle'))
        self.answer = QTextBrowser()
        self.answer.setToolTip('스코어보드(레벨·KDA·CS·아이템)와 공식 자료로만 답합니다. '
                               '시야, 상대 주문 쿨타임, 오브젝트 타이머는 알 수 없습니다.')
        self.answer.setPlainText('게임에 접속하면 현재 스코어보드를 바탕으로 질문에 답합니다.')
        right.addWidget(self.answer, 1)
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
        column.addWidget(coach, 1)
        side.setMinimumWidth(300)
        root.addWidget(side, 3)
        self.show_disconnected()

    def show_view(self, view):
        self.view = view
        self.clock.setText(view.get('clock') or '--:--')
        mode = ' · %s' % view['mode_name'] if view.get('mode_name') else ''
        if view.get('perspective_known'):
            self.state.setText('게임 연결됨%s · 2~3초 간격으로 갱신합니다.' % mode)
        else:
            self.state.setText('게임 연결됨 · 내 소환사를 스코어보드에서 찾지 못해 블루팀을 아군으로 표시합니다.')
        gold = view.get('team_gold')
        if gold:
            self.gold_bar.set_values(gold['ally'], gold['enemy'])
            self.gold_text.setText('아이템 가격 합계  아군 %s · 상대 %s (%+d)' % (
                f"{gold['ally']:,}", f"{gold['enemy']:,}", gold['diff']))
            self.gold_text.setToolTip('산 아이템 가격을 더한 값입니다. 아직 쓰지 않은 골드는 빠져 있습니다.')
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
        self.items.clear()
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
QFrame#teamPanel, QFrame#coachPanel, QFrame#itemCard { background: #151f2e; border: 1px solid #2a3a4f; border-radius: 12px; }
QFrame#itemPick { background: #182536; border-radius: 8px; }
QLabel#pickIcon { background: #0e1724; border: 1px solid #2e3f56; border-radius: 5px; }
QLabel#pickName { color: #edf4ff; font-size: 14px; font-weight: 700; }
QLabel#pickPrice { color: #f0c86b; font-size: 13px; font-weight: 700; }
QLabel#pickPrice[affordable="yes"] { color: #56d7b6; }
QLabel#pickReason { color: #a9bad0; font-size: 12px; }
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
