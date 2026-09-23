"""Out-game dashboard based on the team's client mock-up."""
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)


def _label(text, object_name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if object_name:
        widget.setObjectName(object_name)
    return widget


class OutGamePage(QWidget):
    askRequested = Signal(str)
    profileRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("outGame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._profile_card())
        left.addWidget(self._summary_card())
        left.addWidget(self._matches_panel(), 1)
        root.addLayout(left, 7)
        root.addWidget(self._chat_panel(), 4)

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
        crest = _label("R", "crest")
        crest.setFixedSize(82, 82)
        crest.setAlignment(Qt.AlignCenter)
        row.addWidget(crest)
        return card

    def _summary_card(self):
        card = QFrame(objectName="lightCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 12, 18, 12)
        tabs = QHBoxLayout()
        tabs.addWidget(_label("전체", "activeTab"))
        tabs.addWidget(_label("개인/2인 랭크", "inactiveTab"))
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
        self.match_note = _label("연결 전 화면 예시", "sampleBadge")
        title.addWidget(self.match_note)
        box.addLayout(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.matches = QVBoxLayout(content)
        self.matches.setContentsMargins(0, 0, 6, 0)
        self.matches.setSpacing(12)
        for won in (True, False, True):
            self.matches.addWidget(self._match_card({
                "win": won, "champion_name": "예시 챔피언", "kills": 12,
                "deaths": 3, "assists": 8, "cs": 248,
                "game_duration_seconds": 1934,
            }, sample=True))
        self.matches.addStretch()
        scroll.setWidget(content)
        box.addWidget(scroll, 1)
        return panel

    def _match_card(self, match, sample=False):
        won = bool(match.get("win"))
        card = QFrame(objectName="winCard" if won else "lossCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 14, 18, 14)
        champion = QVBoxLayout()
        champion.addWidget(_label(match.get("champion_name") or "알 수 없음", "champion"))
        champion.addWidget(_label(("승리" if won else "패배") + (" · 예시" if sample else ""),
                                  "winText" if won else "lossText"))
        row.addLayout(champion, 3)
        kda = "%s / %s / %s" % (match.get("kills", 0), match.get("deaths", 0), match.get("assists", 0))
        row.addWidget(_label(kda, "kda"), 3)
        seconds = match.get("game_duration_seconds") or 0
        detail = "%s CS\n%02d:%02d" % (match.get("cs", 0), seconds // 60, seconds % 60)
        row.addWidget(_label(detail, "matchDetail"), 2)
        row.addWidget(_label("아이템·팀 조합\n데이터 연결 예정", "matchAside"), 3)
        return card

    def _chat_panel(self):
        panel = QFrame(objectName="chatPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(18, 14, 18, 14)
        header.addWidget(_label("AI", "aiBadge"))
        header.addWidget(_label("게임 밖 코치", "chatTitle"))
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
            "현재 메타, 패치 변경, 챔피언·아이템·룬을 물어보세요. DB 근거와 출처를 함께 보여드릴게요.", False
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
        sources = result.get("sources") or []
        if sources:
            answer += "\n\n출처\n" + "\n".join("· %s (%s)" % (s["title"], s["version"]) for s in sources)
        self.messages.insertWidget(self.messages.count() - 1, self._bubble(html.unescape(str(answer)), False))
        self._scroll_bottom()

    def show_error(self, message):
        self.messages.insertWidget(self.messages.count() - 1, self._bubble(message, False))
        self._scroll_bottom()

    def _scroll_bottom(self):
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def show_profile(self, payload):
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
QWidget#outGame { background-color: #eef1f5; color: #111827; }
QWidget#outGame QLabel { background: transparent; color: #111827; }
QFrame#lightCard, QFrame#chatPanel { background: #ffffff; border: 1px solid #e7ebf0; border-radius: 16px; }
QFrame#matchesPanel { background: transparent; border: none; }
QLabel#avatar { background: #162a36; color: #72e2c7; border-radius: 16px; font-size: 24px; font-weight: 800; }
QLabel#crest { background: #dcecff; color: #2764b5; border-radius: 41px; font-size: 30px; font-weight: 800; }
QLabel#playerName { font-size: 22px; font-weight: 800; }
QLabel#subtle, QLabel#matchAside { color: #77808d; }
QLabel#record { color: #252b33; font-size: 15px; }
QPushButton#refreshButton { background: #dcecff; color: #1674da; border: none; border-radius: 9px; padding: 9px 14px; font-weight: 700; }
QLabel#activeTab { font-size: 17px; font-weight: 800; border-bottom: 2px solid #111827; padding: 4px 8px 8px; }
QLabel#inactiveTab { color: #9299a3; font-size: 17px; font-weight: 700; padding: 4px 8px 8px; }
QLabel#sectionTitle { font-size: 19px; font-weight: 800; }
QLabel#sampleBadge { color: #667085; background: #ffffff; border-radius: 8px; padding: 6px 10px; }
QFrame#winCard { background: #cfe3fb; border-left: 8px solid #3478da; border-radius: 14px; }
QFrame#lossCard { background: #f5c8cb; border-left: 8px solid #d73b43; border-radius: 14px; }
QLabel#champion { font-size: 17px; font-weight: 800; }
QLabel#winText { color: #2368c4; font-weight: 800; }
QLabel#lossText { color: #bf3139; font-weight: 800; }
QLabel#kda { font-size: 22px; font-weight: 800; }
QLabel#matchDetail { font-size: 15px; font-weight: 700; color: #313946; }
QFrame#chatPanel { min-width: 340px; }
QLabel#aiBadge { background: #deebff; color: #111827; border-radius: 18px; padding: 8px; font-weight: 800; }
QLabel#chatTitle, QLabel#chatBrand { font-size: 16px; font-weight: 800; }
QLabel#userBubble { background: #e9f1fc; border: 1px solid #cbd9eb; border-radius: 16px; padding: 11px 14px; color: #1c2735; }
QLabel#coachBubble { background: #f5f6f8; border: 1px solid #e1e4e8; border-radius: 16px; padding: 11px 14px; color: #1c2735; }
QLineEdit { background: #ffffff; color: #20252c; border: 1px solid #89919d; border-radius: 22px; padding: 12px 16px; }
QPushButton#chatSend { background: #dce6f4; color: #557aa7; border: none; border-radius: 21px; min-width: 42px; min-height: 42px; font-size: 22px; font-weight: 800; padding: 0; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
"""
