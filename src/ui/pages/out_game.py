"""Out-game dashboard based on the team's client mock-up."""
import html
from datetime import datetime

from ui.portraits import ChampionPortraits
from ui.match_assets import MatchAssets

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget, QStackedWidget,
)


def _label(text, object_name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if object_name:
        widget.setObjectName(object_name)
    return widget


WEEKDAYS = "월화수목금토일"


def played_at(epoch):
    """경기 시작 시각(UTC epoch)을 이 PC의 현지 날짜·시각으로 바꾼다. 값이 없으면 None."""
    try:
        moment = datetime.fromtimestamp(int(epoch))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return moment.strftime("%Y.%m.%d") + " (%s)" % WEEKDAYS[moment.weekday()], moment.strftime("%H:%M")


class MatchCard(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class OutGamePage(QWidget):
    askRequested = Signal(str)
    profileRequested = Signal()
    matchRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.portraits = ChampionPortraits(self)
        self.assets = MatchAssets(self)
        self.setObjectName("outGame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        history = QWidget()
        left = QVBoxLayout(history)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(16)
        left.addWidget(self._profile_card())
        left.addWidget(self._summary_card())
        left.addWidget(self._matches_panel(), 1)
        self.history_stack = QStackedWidget()
        loading = QFrame(objectName="loadingPanel")
        loading_box = QVBoxLayout(loading)
        self.loading_label = QLabel("Roading .", objectName="loadingText")
        self.loading_label.setAlignment(Qt.AlignCenter)
        loading_box.addWidget(self.loading_label)
        self.history_stack.addWidget(loading)
        self.history_stack.addWidget(history)
        self.loading_step = 1
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(500)
        self.loading_timer.timeout.connect(self._animate_loading)
        self.loading_timer.start()
        root.addWidget(self.history_stack, 8)
        root.addWidget(self._chat_panel(), 4)

    def _animate_loading(self):
        self.loading_step = self.loading_step % 3 + 1
        self.loading_label.setText("Roading " + "." * self.loading_step)

    def _profile_card(self):
        card = QFrame(objectName="lightCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(22, 18, 22, 18)
        avatar = _label("RF", "avatar")
        avatar.setFixedSize(82, 82)
        avatar.setAlignment(Qt.AlignCenter)
        row.addWidget(avatar)
        info = QVBoxLayout()
        title = QHBoxLayout()
        self.player_name = _label("클라이언트 연결 전", "playerName")
        title.addWidget(self.player_name)
        title.addStretch()
        self.refresh_button = QPushButton("클라이언트 확인", objectName="refreshButton")
        self.refresh_button.setMinimumWidth(118)
        self.refresh_button.clicked.connect(self.profileRequested.emit)
        title.addWidget(self.refresh_button)
        info.addLayout(title)
        self.rank = _label("롤 클라이언트 로그인을 자동으로 기다리고 있습니다.", "subtle")
        info.addWidget(self.rank)
        self.record = _label("최근 전적을 불러오지 않았습니다.", "record")
        info.addWidget(self.record)
        row.addLayout(info, 1)
        return card

    def _summary_card(self):
        card = QFrame(objectName="lightCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 12, 18, 12)
        tabs = QHBoxLayout()
        tabs.addWidget(_label("MATCH HISTORY", "activeTab"))
        tabs.addStretch()
        box.addLayout(tabs)
        self.summary = _label("최근 게임 데이터가 연결되면 승·패와 승률을 보여줍니다.", "subtle")
        box.addWidget(self.summary)
        return card

    def _matches_panel(self):
        panel = QFrame(objectName="matchesPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        title = QHBoxLayout()
        title.addWidget(_label("최근 경기", "sectionTitle"))
        title.addStretch()
        self.match_note = _label("최근 경기", "sampleBadge")
        title.addWidget(self.match_note)
        box.addLayout(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.matches = QVBoxLayout(content)
        self.matches.setContentsMargins(0, 0, 6, 0)
        self.matches.setSpacing(12)
        self.matches.addStretch()
        scroll.setWidget(content)
        box.addWidget(scroll, 1)
        return panel

    def _match_card(self, match, sample=False):
        won = bool(match.get("win"))
        card = MatchCard(objectName="winCard" if won else "lossCard")
        if not sample and match.get("match_id"):
            card.setCursor(Qt.PointingHandCursor)
            card.setFocusPolicy(Qt.StrongFocus)
            card.setToolTip("클릭하여 경기 상세 통계 보기")
            card.clicked.connect(lambda: self.matchRequested.emit(match["match_id"]))
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(16)
        name = match.get("champion_name") or "알 수 없음"
        portrait = QLabel("?" if not sample else "RF", objectName="championPortrait")
        portrait.setFixedSize(56, 56)
        portrait.setAlignment(Qt.AlignCenter)
        portrait.setToolTip(name)
        portrait.setAccessibleName(name + " 초상화")
        row.addWidget(portrait)
        if not sample and match.get("champion_name"):
            self.portraits.attach(portrait, name)
        champion = QVBoxLayout()
        champion.setSpacing(5)
        champion.addWidget(_label(name, "champion"))
        champion.addWidget(_label("승리" if won else "패배", "winText" if won else "lossText"))
        row.addLayout(champion, 2)
        when = played_at(match.get("played_at_epoch")) if not sample else None
        if when:
            date = QVBoxLayout()
            date.setSpacing(5)
            day = _label(when[0], "matchDate")
            day.setWordWrap(False)
            date.addWidget(day)
            date.addWidget(_label(when[1], "matchTime"))
            row.addLayout(date, 2)
        icon_row = QHBoxLayout()
        icon_row.setSpacing(4)
        for kind, asset_id, fallback in (
            ('spell', match.get('spell1_id'), 'S1'),
            ('spell', match.get('spell2_id'), 'S2'),
            ('rune', match.get('keystone_id'), '룬'),
        ):
            icon = QLabel(fallback, objectName='matchIcon')
            icon.setFixedSize(30, 30)
            icon.setAlignment(Qt.AlignCenter)
            icon_row.addWidget(icon)
            if not sample:
                self.assets.attach(icon, kind, asset_id)
        row.addLayout(icon_row)
        kda = "%s / %s / %s" % (match.get("kills", 0), match.get("deaths", 0), match.get("assists", 0))
        row.addWidget(_label(kda, "kda"), 2)
        seconds = match.get("game_duration_seconds") or 0
        detail = "%s CS\n%02d:%02d" % (match.get("cs", 0), seconds // 60, seconds % 60)
        row.addWidget(_label(detail, "matchDetail"), 1)
        metrics = QVBoxLayout()
        metrics.setSpacing(3)
        damage = match.get('damage_to_champions')
        gold = match.get('gold_earned')
        metrics.addWidget(_label('Damage  ' + (f'{damage:,}' if damage is not None else '—'), 'matchMetric'))
        metrics.addWidget(_label('Gold  ' + (f'{gold:,}' if gold is not None else '—'), 'matchMetric'))
        metrics.addWidget(_label('상세 통계 보기  ›', 'detailHint'))
        row.addLayout(metrics, 2)
        for child in card.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        return card

    def _chat_panel(self):
        panel = QFrame(objectName="chatPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(18, 14, 18, 14)
        header.addWidget(_label("AI", "aiBadge"))
        header.addWidget(_label("AI에게 질문", "chatTitle"))
        header.addStretch()
        header.addWidget(_label("RiftFlow", "chatBrand"))
        box.addLayout(header)
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_body = QWidget()
        self.messages = QVBoxLayout(self.chat_body)
        self.messages.setContentsMargins(16, 18, 16, 18)
        self.messages.setSpacing(12)
        self.messages.addWidget(self._bubble(
            "롤 전적 분석, 챔피언 추천, 연습 방법과 패치에 대해 질문하세요.", False
        ))
        self.messages.addStretch()
        self.chat_scroll.setWidget(self.chat_body)
        box.addWidget(self.chat_scroll, 1)
        form = QHBoxLayout()
        form.setContentsMargins(14, 12, 14, 14)
        self.question = QLineEdit()
        self.question.setPlaceholderText("챗봇에게 물어보기")
        self.question.setMaxLength(1000)
        self.question.returnPressed.connect(self.submit)
        self.send = QPushButton("↑", objectName="chatSend")
        self.send.clicked.connect(self.submit)
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        box.addLayout(form)
        return panel

    def _bubble(self, text, user):
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(bubble.textFormat())
        bubble.setObjectName("userBubble" if user else "coachBubble")
        bubble.setMaximumWidth(330)
        return bubble

    def submit(self):
        question = self.question.text().strip()
        if not question or not self.send.isEnabled():
            return
        self.messages.insertWidget(self.messages.count() - 1, self._bubble(question, True), 0,
                                   Qt.AlignRight)
        self.question.clear()
        self.askRequested.emit(question)

    def set_busy(self, busy):
        self.send.setEnabled(not busy)
        self.question.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        if busy:
            self.messages.insertWidget(self.messages.count() - 1, self._bubble("자료를 찾고 있습니다…", False))

    def show_answer(self, result):
        answer = result.get("answer") or result.get("message") or result.get("error")
        if not answer:
            answer = "관련 근거를 찾았어요. Gemini를 사용하지 않아 자료 목록만 표시합니다."
        self.messages.insertWidget(self.messages.count() - 1, self._bubble(html.unescape(str(answer)), False))
        self._scroll_bottom()

    def show_error(self, message):
        self.messages.insertWidget(self.messages.count() - 1, self._bubble(message, False))
        self._scroll_bottom()

    def _scroll_bottom(self):
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def show_profile(self, payload):
        self.loading_timer.stop()
        self.history_stack.setCurrentIndex(1)
        player = payload["player"]
        rank = payload.get("rank")
        matches = payload.get("matches") or []
        self.player_name.setText(player.riot_id)
        self.rank.setText(("%s %s · %s LP" % (rank.tier, rank.division, rank.league_points))
                          if rank else "솔로 랭크 기록 없음")
        wins = sum(1 for match in matches if match.win)
        self.record.setText("최근 %d전  %d승 / %d패  %.0f%%" %
                            (len(matches), wins, len(matches) - wins,
                             wins * 100 / len(matches) if matches else 0))
        self.summary.setText("최근 %d게임 · %d승 · %d패" % (len(matches), wins, len(matches) - wins))
        self.match_note.setText("Riot 전적 데이터")
        while self.matches.count():
            item = self.matches.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for match in matches:
            self.matches.addWidget(self._match_card(vars(match)))
        if not matches:
            self.matches.addWidget(_label("최근 경기 기록이 없습니다.", "subtle"))
        self.matches.addStretch()


STYLE = """
QWidget#outGame { font-family: "Malgun Gothic"; font-size: 13px; background: #0c111b; color: #e8edf7; }
QWidget#outGame QLabel { background: transparent; color: #e8edf7; }
QFrame#lightCard, QFrame#chatPanel { background: #121b29; border: 1px solid #253247; border-radius: 16px; }
QFrame#matchesPanel { background: transparent; border: none; }
QFrame#loadingPanel { background: #05070b; border: 1px solid #1c2534; border-radius: 16px; }
QLabel#loadingText { color: #92a4c1; font-size: 26px; font-weight: 600; font-family: Consolas; }
QLabel#avatar { background: #1a2b41; color: #77aaff; border: 1px solid #304d73; border-radius: 18px; font-size: 24px; font-weight: 800; }
QLabel#playerName { font-size: 23px; font-weight: 800; }
QLabel#subtle, QLabel#matchAside { color: #8d9cb3; font-size: 12px; }
QLabel#record { color: #c0cee3; font-size: 15px; }
QPushButton#refreshButton { background: #1c304b; color: #9bc4ff; border: 1px solid #314e72; border-radius: 9px; padding: 9px 14px; font-weight: 700; }
QPushButton#refreshButton:hover { background: #264364; }
QLabel#activeTab { color: #8fa8cb; font-size: 12px; font-weight: 700; padding: 4px 0; }
QLabel#sectionTitle { font-size: 19px; font-weight: 800; }
QLabel#sampleBadge { color: #899bb6; background: #182333; border-radius: 8px; padding: 6px 10px; font-size: 11px; }
QFrame#winCard { background: #111f32; border: 2px solid #397ee8; border-radius: 14px; }
QFrame#lossCard { background: #26191f; border: 2px solid #d64e61; border-radius: 14px; }
QFrame#winCard:hover, QFrame#winCard:focus { background: #172d49; border-color: #75adff; }
QFrame#lossCard:hover, QFrame#lossCard:focus { background: #382129; border-color: #ff8290; }
QLabel#matchIcon { background: #17263a; color: #9db4d4; border: 1px solid #3a4b63; border-radius: 5px; font-size: 9px; font-weight: 700; }
QLabel#matchDate { color: #c0cee3; font-size: 13px; font-weight: 700; }
QLabel#matchTime { color: #8d9cb3; font-size: 12px; }
QLabel#matchMetric { color: #dce7f6; font-size: 13px; font-weight: 700; }
QLabel#detailHint { color: #83b4fa; font-size: 11px; }
QLabel#championPortrait { background: #233449; color: #a7bddb; border: 1px solid #415671; border-radius: 8px; font-size: 18px; font-weight: 700; }
QLabel#champion { font-size: 15px; font-weight: 700; }
QLabel#winText { color: #79b1ff; font-size: 12px; font-weight: 800; }
QLabel#lossText { color: #ff8595; font-size: 12px; font-weight: 800; }
QLabel#kda { font-size: 20px; font-weight: 800; }
QLabel#matchDetail { font-size: 13px; font-weight: 600; color: #aabbd2; }
QFrame#chatPanel { min-width: 320px; }
QLabel#aiBadge { background: #233952; color: #9dc5ff; border-radius: 16px; padding: 8px; font-weight: 800; }
QLabel#chatTitle, QLabel#chatBrand { font-size: 15px; font-weight: 700; }
QLabel#userBubble { background: #203551; border: 1px solid #324d70; border-radius: 14px; padding: 12px; color: #e0edff; }
QLabel#coachBubble { background: #182334; border: 1px solid #2a374c; border-radius: 14px; padding: 12px; color: #b9c8df; }
QLineEdit { background: #0e1724; color: #e8edf7; border: 1px solid #334661; border-radius: 18px; padding: 12px 16px; }
QLineEdit:focus { border-color: #568ddb; }
QPushButton#chatSend { background: #2b5281; color: #dbeaff; border: none; border-radius: 21px; min-width: 42px; min-height: 42px; font-size: 22px; font-weight: 800; padding: 0; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: #101824; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #34465f; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
