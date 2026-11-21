"""게임 화면 위에 뜨는 작은 안내 카드 (음성 질문, F8 증강 추천도).

- 롤 게임 창이 있는 모니터 오른쪽 위에 뜬다. 게임 창이 없으면 띄우지 않는다.
- 마우스 클릭이 그대로 게임으로 지나가고(입력 투명), 포커스를 가져가지 않아 알트탭이 필요 없다.
- 답은 길이에 맞춰 몇 초 뒤 저절로 사라진다. 듣는 중, 받아 적는 중에는 사라지지 않는다.
- 롤의 화면 모드가 '전체 화면'(독점)이면 윈도우가 다른 창을 게임 위에 그리지 못한다. '테두리 없음'에서 보인다.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

WIDTH = 440
MARGIN_RIGHT = 24
MARGIN_TOP = 110             # 화면 맨 위 점수판을 가리지 않게 조금 내린다


def reading_ms(text):
    """읽는 데 필요한 시간. 최소 6초, 최대 25초."""
    return int(min(25.0, max(6.0, len(text or '') / 11.0)) * 1000)


class GameOverlay(QWidget):
    def __init__(self, find_screen=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if find_screen is None:
            from ui.capture import game_screen
            find_screen = game_screen
        self.find_screen = find_screen
        self.enabled = True
        card = QFrame(objectName='overlayCard')
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(6)
        self.title = QLabel(objectName='overlayTitle')
        self.question = QLabel(objectName='overlayQuestion')
        self.body = QLabel(objectName='overlayBody')
        for label in (self.title, self.question, self.body):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            box.addWidget(label)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(STYLE)
        self.hide_timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_card(self, title, body, question=None, sticky=False):
        """카드를 띄운다. sticky면 다음 카드가 올 때까지 남는다. 게임 창이 없거나 꺼 두면 아무것도 하지 않는다."""
        if not self.enabled:
            return False
        screen = self.find_screen()
        if screen is None:
            self.hide()
            return False
        self.title.setText(title)
        self.question.setText(question or '')
        self.question.setVisible(bool(question))
        self.body.setText(body or '')
        self.adjustSize()
        area = screen.geometry()
        self.move(area.right() - WIDTH - MARGIN_RIGHT, area.top() + MARGIN_TOP)
        self.show()
        self.raise_()
        self.hide_timer.stop()
        if not sticky:
            self.hide_timer.start(reading_ms((question or '') + (body or '')))
        return True


STYLE = """
QFrame#overlayCard { background: rgba(14, 18, 26, 228); border: 1px solid rgba(80, 220, 180, 150); border-radius: 12px; }
QLabel { background: transparent; font-family: 'Segoe UI', 'Malgun Gothic'; }
QLabel#overlayTitle { color: #5be0b8; font-size: 12px; font-weight: 700; }
QLabel#overlayQuestion { color: #aab4c3; font-size: 13px; }
QLabel#overlayBody { color: #f2f5f8; font-size: 15px; }
"""
