"""Champion-select view with live picks, bans, rune recommendation and coaching chat."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ui.match_assets import MatchAssets
from ui.portraits import ChampionPortraits


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


class TeamList(QWidget):
    """아군·상대 픽 목록(초상화 + 라인 · 챔피언). 폴링마다 다시 만들지 않고 값만 바꿔 깜빡임을 막는다."""

    def __init__(self, portraits, empty, parent=None):
        super().__init__(parent)
        self.portraits = portraits
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        self.empty = label(empty, 'teamText')
        box.addWidget(self.empty)
        self.rows = []
        for _ in range(5):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            portrait = QLabel(objectName='pickPortrait')
            portrait.setFixedSize(28, 28)
            portrait.setAlignment(Qt.AlignCenter)
            text = label('', 'teamText')
            line.addWidget(portrait)
            line.addWidget(text, 1)
            row.hide()
            box.addWidget(row)
            self.rows.append({'row': row, 'portrait': portrait, 'text': text, 'champion': None})

    def show_team(self, team):
        self.empty.setVisible(not team)
        for index, slot in enumerate(self.rows):
            if index >= len(team):
                slot['row'].hide()
                continue
            player = team[index]
            slot['row'].show()
            slot['text'].setText(f"{player['position']}  ·  {player['champion']}"
                                 + ('  (선택 중)' if player.get('hovering') else ''))
            champion = player.get('id') or (player['champion'] if player.get('selected') else None)
            if champion != slot['champion']:
                slot['champion'] = champion
                slot['portrait'].clear()
                slot['portrait'].setText('?' if champion else '')
                slot['portrait'].setToolTip(player['champion'] if champion else '')
                if champion:
                    self.portraits.attach(slot['portrait'], champion)

    def text(self):
        lines = [slot['text'].text() for slot in self.rows if not slot['row'].isHidden()]
        return '\n'.join(lines) or self.empty.text()


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
        self.placeholder = label('픽창에서 챔피언을 올려놓으면 룬을 자동으로 추천하고 클라이언트에 적용합니다. '
                                 '챔피언을 직접 입력했다면 룬 추천을 누르세요.', 'subtle')
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
    runeApplyRequested = Signal(object)
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
        self.rune_page = None
        self.busy = False
        self.user_requests = []   # 이번 픽창에서 사용자가 채팅으로 한 말. 성향은 여기서 읽는다.
        self.portraits = ChampionPortraits(self)
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
        self.ally = TeamList(self.portraits, '아군 선택 전')
        self.enemy = TeamList(self.portraits, '상대 선택 전')
        self.bans = label('확정된 밴 없음', 'teamText')
        for col, (title, body) in enumerate((('아군 픽', self.ally), ('상대 픽', self.enemy), ('확정된 밴', self.bans))):
            card = QFrame(objectName='panel')
            box = QVBoxLayout(card)
            box.addWidget(label(title, 'cardTitle'))
            box.addWidget(body)
            box.addStretch()
            teams.addWidget(card, 0, col)
            teams.setColumnStretch(col, 1)
        root.addLayout(teams)
        context = QHBoxLayout()
        self.champion = QLineEdit()
        self.champion.setPlaceholderText('내 챔피언 (픽창에서 자동 입력)')
        self.opponent = QLineEdit()
        self.opponent.setPlaceholderText('맞라인 상대 (확정 시 자동 입력)')
        context.addWidget(self.champion, 1)
        context.addWidget(self.opponent, 1)
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
        self.apply_button = QPushButton('클라이언트에 적용')
        self.apply_button.setToolTip('RiftFlow 이름의 룬 페이지를 만들거나 교체합니다. 직접 만든 페이지는 건드리지 않습니다.')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.request_apply)
        rune_head.addWidget(self.apply_button)
        self.rune_button = QPushButton('룬 추천')
        self.rune_button.setObjectName('primary')
        self.rune_button.clicked.connect(self.request_runes)
        rune_head.addWidget(self.rune_button)
        root.addLayout(rune_head)
        self.rune_view = RunePageView(self.assets)
        root.addWidget(self.rune_view)
        self.rune_status = label('', 'subtle')
        self.rune_status.hide()
        root.addWidget(self.rune_status)
        self.champion.textChanged.connect(self._rune_champion_changed)
        self.answer = QTextBrowser()
        self.answer.setPlainText('챔피언을 고르면 공식 자료와 실제 픽창 정보를 바탕으로 질문에 답합니다.')
        root.addWidget(self.answer, 1)
        form = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setMaxLength(1000)
        self.question.setPlaceholderText('예: 이 상대 초반 운영은? / 공격적으로 하고 싶어, 룬 다시 짜줘')
        self.question.returnPressed.connect(self.submit)
        self.send = QPushButton('질문')
        self.send.setObjectName('primary')
        self.send.clicked.connect(self.submit)
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        root.addLayout(form)

    def show_session(self, view):
        self.view = view
        mode = ' · %s' % view['mode_name'] if view.get('mode_name') else ''
        self.state.setText('픽창 연결됨%s · 상대는 확정된 픽만 보입니다.' % mode)
        self.ally.show_team(view['allies'])
        self.enemy.show_team(view['enemies'])
        self.bans.setText('아군: ' + (', '.join(view['ally_bans']) or '없음') + '\n상대: ' + (', '.join(view['enemy_bans']) or '없음'))
        mine = view.get('mine') or {}
        # 확정 전에 올려놓은 챔피언도 내 챔피언으로 채운다 (룬 추천을 미리 받을 수 있게).
        if mine.get('selected', mine.get('locked')):
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
        self.ally.show_team([])
        self.enemy.show_team([])
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
                'user_requests': list(self.user_requests[-5:])}

    def reset_conversation(self):
        self.user_requests = []

    def submit(self):
        """채팅 한 줄. 룬 이야기면 그 말을 반영해 룬을 새로 추천하고, 아니면 코치가 답한다.

        어느 쪽이든 말한 내용은 기억해 두고 이후 추천·답변에 성향으로 반영한다.
        """
        question = self.question.text().strip()
        if not question or self.busy:
            return
        self.user_requests.append(question)
        self.question.clear()
        if '룬' in question and self.champion.text().strip():
            self.runeRequested.emit(self._request(question))
        else:
            self.askRequested.emit(self._request(question))

    def request_runes(self):
        if not self.champion.text().strip():
            self.rune_view.show_message('내 챔피언을 선택하거나 입력한 뒤 룬 추천을 눌러 주세요.')
            return
        self.runeRequested.emit(self._request())

    def show_rune_result(self, result, champion):
        self.show_apply_status('')
        if result.get('page'):
            self.rune_champion, self.rune_page = champion, result['page']
            self.rune_view.show_page(result['page'])
        else:
            self.rune_champion, self.rune_page = None, None
            self.rune_view.show_message(result.get('message') or '룬 추천을 받지 못했습니다.')
        self._sync_buttons()

    def request_apply(self):
        if self.rune_page is not None and not self.busy:
            self.runeApplyRequested.emit({'page': self.rune_page, 'champion': self.rune_champion})

    def show_apply_status(self, text, ok=None):
        """적용 결과 한 줄. 실패(ok=False)면 주황색으로 보이고 적용 버튼을 강조해 누르도록 유도한다."""
        self.rune_status.setText(text)
        self.rune_status.setVisible(bool(text))
        self._restyle(self.rune_status, {True: 'applyOk', False: 'applyWarn'}.get(ok, 'subtle'))
        self._restyle(self.apply_button, 'attention' if ok is False else '')

    @staticmethod
    def _restyle(widget, name):
        if widget.objectName() != name:
            widget.setObjectName(name)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_busy(self, busy):
        self.busy = busy
        self._sync_buttons()

    def _sync_buttons(self):
        for button in (self.send, self.refresh, self.rune_button):
            button.setEnabled(not self.busy)
        self.apply_button.setEnabled(not self.busy and self.rune_page is not None)

    def _rune_champion_changed(self, text):
        if self.rune_champion and text.strip() != self.rune_champion:
            self.rune_champion, self.rune_page = None, None
            self.show_apply_status('')
            self.rune_view.show_message('챔피언이 바뀌었습니다. 픽창에서는 잠시 뒤 자동으로 다시 추천하고, 바로 받으려면 룬 추천을 누르세요.')
            self._sync_buttons()


STYLE = """
QWidget#beforeGame { background: #101722; color: #e8edf4; }
QLabel#title { color: #edf4ff; font-size: 27px; font-weight: 700; }
QLabel#subtle { color: #94a8c2; }
QFrame#panel QLabel, QFrame#panel QWidget { background: transparent; }
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
QLabel#pickPortrait { background: #0e1724; color: #6f829c; border: 1px solid #2e3f56; border-radius: 6px; font-size: 11px; }
QLabel#applyOk { color: #72e2c7; }
QLabel#applyWarn { color: #ffb86b; font-weight: 700; }
QPushButton#attention { background: #f0a14a; color: #2b1a05; border: none; font-weight: 700; }
QLabel#shardChip { background: #0e1724; color: #dce9f7; border: 1px solid #2e3f56; border-radius: 6px; padding: 4px 8px; font-size: 12px; }
"""
