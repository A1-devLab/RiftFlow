"""Champion-select view with live picks, bans, playstyle and coaching question."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


class BeforeGamePage(QWidget):
    askRequested = Signal(object)
    refreshRequested = Signal()
    personalContextChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('beforeGame')
        self.setStyleSheet(STYLE)
        self.auto_champion = ''
        self.auto_opponent = ''
        self.view = {'mine': None, 'allies': [], 'enemies': [], 'ally_bans': [], 'enemy_bans': []}
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

    def submit(self):
        question = self.question.text().strip()
        if not question:
            return
        payload = {'view': self.view, 'question': question,
                   'champion': self.champion.text().strip(),
                   'opponent': self.opponent.text().strip(),
                   'trade_preference': self.trade.currentText() if self.trade.currentIndex() else None,
                   'lane_aggression': self.aggression.currentText() if self.aggression.currentIndex() else None}
        self.askRequested.emit(payload)


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
"""
