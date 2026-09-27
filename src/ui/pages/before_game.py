"""Champion-select view with live picks, bans, playstyle, rune recommendation and coaching question."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ui.match_assets import MatchAssets


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


class RuneSlot(QWidget):
    """룬 아이콘 하나와 이름. 아이콘은 Data Dragon에서 비동기로 받아 온다."""

    def __init__(self, assets, size, parent=None):
        super().__init__(parent)
        self.assets = assets
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        self.icon = QLabel(objectName='runeIcon')
        self.icon.setFixedSize(size, size)
        self.icon.setStyleSheet('border-radius: %dpx;' % (size // 2))
        self.icon.setAlignment(Qt.AlignCenter)
        self.name = label('', 'runeName')
        self.name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.name.setFixedWidth(max(size + 22, 70))
        box.addWidget(self.icon, 0, Qt.AlignHCenter)
        box.addWidget(self.name)

    def show_rune(self, rune):
        self.icon.clear()
        self.icon.setToolTip(rune['name'])
        self.name.setText(rune['name'])
        self.assets.attach(self.icon, 'rune', rune['id'])


class RuneTree(QWidget):
    """트리 이름과 그 트리에서 고른 룬들."""

    def __init__(self, assets, sizes, parent=None):
        super().__init__(parent)
        self.assets = assets
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        head = QHBoxLayout()
        self.style_icon = QLabel(objectName='styleIcon')
        self.style_icon.setFixedSize(20, 20)
        self.style_name = label('', 'runeTree')
        head.addWidget(self.style_icon)
        head.addWidget(self.style_name, 1)
        box.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.slots = [RuneSlot(assets, size) for size in sizes]
        for slot in self.slots:
            row.addWidget(slot, 0, Qt.AlignTop)
        row.addStretch()
        box.addLayout(row)

    def show_tree(self, style, runes):
        self.style_icon.clear()
        self.style_name.setText(style['name'])
        self.assets.attach(self.style_icon, 'rune', style['id'])
        for slot, rune in zip(self.slots, runes):
            slot.show_rune(rune)


class RunePageView(QFrame):
    """추천받은 룬 페이지 미리보기. 클라이언트에는 아무것도 쓰지 않는다."""

    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.setObjectName('runePanel')
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 10)
        self.stack = QStackedWidget()
        self.placeholder = label('챔피언을 정한 뒤 룬 추천을 누르면 이 픽창에 맞는 룬 페이지를 보여 줍니다.', 'subtle')
        self.stack.addWidget(self.placeholder)
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        self.primary = RuneTree(assets, (44, 32, 32, 32))
        self.secondary = RuneTree(assets, (32, 32))
        row.addWidget(self.primary)
        row.addWidget(self.secondary)
        shards = QVBoxLayout()
        shards.setSpacing(4)
        shards.addWidget(label('능력치 파편', 'runeTree'))
        self.shards = [label('', 'shardChip') for _ in range(3)]
        for chip in self.shards:
            shards.addWidget(chip)
        shards.addStretch()
        row.addLayout(shards)
        row.addStretch()
        self.stack.addWidget(page)
        box.addWidget(self.stack)

    def show_message(self, text):
        self.placeholder.setText(text)
        self.stack.setCurrentIndex(0)

    def show_page(self, page):
        self.primary.show_tree(page['primary_style'], [page['keystone']] + page['primary'])
        self.secondary.show_tree(page['secondary_style'], page['secondary'])
        for chip, shard in zip(self.shards, page['shards']):
            chip.setText('%s · %s' % (shard['row'], shard['name']))
        self.stack.setCurrentIndex(1)


class BeforeGamePage(QWidget):
    askRequested = Signal(object)
    runeRequested = Signal(object)
    refreshRequested = Signal()
    personalContextChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('beforeGame')
        self.setStyleSheet(STYLE)
        self.auto_champion = ''
        self.auto_opponent = ''
        self.view = {'mine': None, 'allies': [], 'enemies': [], 'ally_bans': [], 'enemy_bans': []}
        self.assets = MatchAssets(self)
        self.rune_champion = None
        root = QVBoxLayout(self)
        root.setSpacing(13)
        header = QHBoxLayout()
        header.addWidget(label('픽창', 'title'))
        header.addStretch()
        self.refresh = QPushButton('픽창 새로고침')
        self.refresh.clicked.connect(self.refreshRequested.emit)
        header.addWidget(self.refresh)
        root.addLayout(header)
        self.state = label('픽창을 기다리고 있습니다. 롤 클라이언트에서 챔피언 선택을 시작하세요.', 'subtle')
        root.addWidget(self.state)
        teams = QGridLayout()
        teams.setSpacing(12)
        self.ally = label('아군 선택 전', 'teamText')
        self.enemy = label('상대 선택 전', 'teamText')
        self.bans = label('확정된 밴 없음', 'teamText')
        for col, (title, body) in enumerate((('아군 픽', self.ally), ('상대 픽', self.enemy), ('확정된 밴', self.bans))):
            card = QFrame(objectName='panel')
            box = QVBoxLayout(card)
            box.addWidget(label(title, 'cardTitle'))
            box.addWidget(body)
            box.addStretch()
            teams.addWidget(card, 0, col)
        root.addLayout(teams)
        context = QHBoxLayout()
        self.champion = QLineEdit()
        self.champion.setPlaceholderText('내 챔피언 (픽창에서 자동 입력)')
        self.opponent = QLineEdit()
        self.opponent.setPlaceholderText('맞라인 상대 (확정 시 자동 입력)')
        context.addWidget(self.champion, 2)
        context.addWidget(self.opponent, 2)
        self.trade = QComboBox()
        self.trade.addItems(['딜교환 성향 선택', '순간 교전', '지속 교전'])
        self.aggression = QComboBox()
        self.aggression.addItems(['라인전 성향 선택', '공격적', '안정적'])
        context.addWidget(self.trade, 1)
        context.addWidget(self.aggression, 1)
        root.addLayout(context)
        self.champion.editingFinished.connect(self.personalContextChanged.emit)
        self.opponent.editingFinished.connect(self.personalContextChanged.emit)
        self.personal = label('개인 상성 기록은 로그인한 계정의 최근 조회 경기에서 확인합니다.', 'subtle')
        root.addWidget(self.personal)
        self.runes = label('이 챔피언으로 사용한 룬 페이지 기록이 없습니다.', 'subtle')
        root.addWidget(self.runes)
        rune_head = QHBoxLayout()
        rune_head.addWidget(label('추천 룬', 'cardTitle'))
        rune_head.addStretch()
        self.rune_button = QPushButton('룬 추천')
        self.rune_button.setObjectName('primary')
        self.rune_button.clicked.connect(self.request_runes)
        rune_head.addWidget(self.rune_button)
        root.addLayout(rune_head)
        self.rune_view = RunePageView(self.assets)
        root.addWidget(self.rune_view)
        self.champion.textChanged.connect(self._rune_champion_changed)
        self.answer = QTextBrowser()
        self.answer.setPlainText('챔피언을 고르면 공식 자료와 실제 픽창 정보를 바탕으로 질문에 답합니다.')
        root.addWidget(self.answer, 1)
        form = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setMaxLength(1000)
        self.question.setPlaceholderText('예: 이 상대를 만났을 때 초반 운영은?')
        self.question.returnPressed.connect(self.submit)
        self.send = QPushButton('질문')
        self.send.setObjectName('primary')
        self.send.clicked.connect(self.submit)
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        root.addLayout(form)

    def show_session(self, view):
        self.view = view
        self.state.setText('픽창 연결됨 · 확정된 선택만 표시합니다.')
        def line(team):
            return '\n'.join(f"{p['position']}  ·  {p['champion']}" for p in team) or '선택 전'
        self.ally.setText(line(view['allies']))
        self.enemy.setText(line(view['enemies']))
        self.bans.setText('아군: ' + (', '.join(view['ally_bans']) or '없음') + '\n상대: ' + (', '.join(view['enemy_bans']) or '없음'))
        mine = view.get('mine') or {}
        if mine.get('locked'):
            self.auto_champion = mine['champion']
            self.champion.setText(self.auto_champion)
        elif self.champion.text() == self.auto_champion:
            self.champion.clear()
            self.auto_champion = ''
        from game_phases.before_game.desktop import opponent_for_lane
        opponent = opponent_for_lane(view)
        if opponent:
            self.auto_opponent = opponent
            self.opponent.setText(opponent)
        elif self.opponent.text() == self.auto_opponent:
            self.opponent.clear()
            self.auto_opponent = ''

    def show_disconnected(self):
        self.state.setText('픽창을 기다리고 있습니다. 롤 클라이언트에서 챔피언 선택을 시작하세요.')
        self.view = {'mine': None, 'allies': [], 'enemies': [], 'ally_bans': [], 'enemy_bans': []}
        self.ally.setText('아군 선택 전')
        self.enemy.setText('상대 선택 전')
        self.bans.setText('확정된 밴 없음')
        if self.champion.text() == self.auto_champion:
            self.champion.clear()
        if self.opponent.text() == self.auto_opponent:
            self.opponent.clear()
        self.auto_champion = ''
        self.auto_opponent = ''

    def _request(self, question=None):
        return {'view': self.view, 'question': question,
                'champion': self.champion.text().strip(),
                'opponent': self.opponent.text().strip(),
                'trade_preference': self.trade.currentText() if self.trade.currentIndex() else None,
                'lane_aggression': self.aggression.currentText() if self.aggression.currentIndex() else None}

    def submit(self):
        question = self.question.text().strip()
        if not question:
            return
        self.askRequested.emit(self._request(question))

    def request_runes(self):
        if not self.champion.text().strip():
            self.rune_view.show_message('내 챔피언을 선택하거나 입력한 뒤 룬 추천을 눌러 주세요.')
            return
        self.runeRequested.emit(self._request())

    def show_rune_result(self, result, champion):
        if result.get('page'):
            self.rune_champion = champion
            self.rune_view.show_page(result['page'])
        else:
            self.rune_champion = None
            self.rune_view.show_message(result.get('message') or '룬 추천을 받지 못했습니다.')

    def _rune_champion_changed(self, text):
        if self.rune_champion and text.strip() != self.rune_champion:
            self.rune_champion = None
            self.rune_view.show_message('챔피언이 바뀌었습니다. 룬 추천을 다시 눌러 주세요.')


STYLE = """
QWidget#beforeGame { background: #101722; color: #e8edf4; }
QLabel#title { color: #edf4ff; font-size: 27px; font-weight: 700; }
QLabel#subtle { color: #94a8c2; }
QFrame#panel QLabel { background: transparent; }
QFrame#panel { background: #182536; border: 1px solid #31445e; border-radius: 12px; min-height: 128px; }
QLabel#cardTitle { color: #7dc9e9; font-size: 16px; font-weight: 700; }
QLabel#teamText { color: #dce9f7; font-size: 14px; }
QTextBrowser { background: #151f2e; color: #e8edf4; border: 1px solid #31445e; border-radius: 10px; padding: 12px; }
QLineEdit, QComboBox { background: #172334; color: #e8edf4; border: 1px solid #354860; border-radius: 7px; padding: 9px; }
QPushButton { background: #223247; color: #e8edf4; border: 1px solid #34475e; border-radius: 7px; padding: 9px 13px; }
QPushButton#primary { background: #56d7b6; color: #09291f; border: none; font-weight: 700; }
QPushButton:disabled, QPushButton#primary:disabled { background: #2c5a50; color: #88a89f; }
QFrame#runePanel { background: #182536; border: 1px solid #31445e; border-radius: 12px; }
QFrame#runePanel QLabel, QFrame#runePanel QWidget { background: transparent; }
QLabel#runeIcon { background: #0e1724; border: 1px solid #2e3f56; }
QLabel#runeName { color: #c0cee3; font-size: 11px; }
QLabel#runeTree { color: #7dc9e9; font-size: 13px; font-weight: 700; }
QLabel#shardChip { background: #0e1724; color: #dce9f7; border: 1px solid #2e3f56; border-radius: 6px; padding: 4px 8px; font-size: 12px; }
"""
