"""픽창, 인게임의 AI 질문 칸을 홈 화면처럼 말풍선 대화로 보여 준다.

예전 답변 칸(QTextBrowser)과 같은 방식으로 부를 수 있게 setPlainText, toPlainText, verticalScrollBar를 둔다.
- show_messages(대화): 저장된 대화 전체를 말풍선으로 다시 그린다 (최신이 아래).
- set_pending(질문): 답을 기다리는 동안 내 질문을 먼저 보여 준다.
- setPlainText(안내): 대화 아래에 안내 말풍선 하나를 붙인다 ('확인하고 있습니다…', 오류 등). 대화가 없으면 안내만 보인다.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui.theme import theme

BUBBLE_WIDTH = 330


class ChatView(QScrollArea):
    def __init__(self, parent=None, bubble_width=BUBBLE_WIDTH):
        super().__init__(parent)
        self.bubble_width = bubble_width
        self.setObjectName('chatView')
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget(objectName='chatBody')
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(4, 8, 4, 8)
        self.layout_.setSpacing(10)
        self.layout_.addStretch()
        self.setWidget(self.body)
        self.messages, self.pending, self.note = [], None, ''
        # 말풍선 높이는 그린 뒤에 잡히므로, 내용 높이가 바뀔 때마다 맨 아래(최신)로 따라간다.
        self.verticalScrollBar().rangeChanged.connect(lambda _low, high: self.verticalScrollBar().setValue(high))
        theme.style(self, STYLE)

    # --- 예전 QTextBrowser처럼 부르는 쪽
    def setPlainText(self, text):
        self.note = text or ''
        self._render()

    def toPlainText(self):
        lines = [('나: ' if m['role'] == 'user' else 'AI: ') + m['text'] for m in self.messages]
        if self.pending:
            lines.append('나: ' + self.pending)
        if self.note:
            lines.append(self.note)
        return '\n\n'.join(lines)

    # --- 대화
    def show_messages(self, messages):
        self.messages = [{'role': m['role'], 'text': str(m['text'])} for m in messages]
        self.pending, self.note = None, ''
        self._render()

    def set_pending(self, question):
        self.pending = question or None
        self._render()

    def _bubble(self, text, user):
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.PlainText)          # 답에 HTML이 섞여도 글자로만 보인다
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setObjectName('userBubble' if user else 'coachBubble')
        bubble.setMaximumWidth(self.bubble_width)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        # 줄바꿈 QLabel은 폭을 좁게 잡으므로 글 길이만큼(최대 bubble_width) 넓힌다. 26 = 좌우 여백 + 테두리.
        bubble.ensurePolished()
        natural = 4 + max((bubble.fontMetrics().horizontalAdvance(t) for t in text.splitlines()), default=0)
        bubble.setMinimumWidth(min(self.bubble_width, natural + 26))
        if user:                                    # 내 질문은 오른쪽, AI 답은 왼쪽
            line.addStretch(1)
            line.addWidget(bubble)
        else:
            line.addWidget(bubble)
            line.addStretch(1)
        return row

    def _render(self):
        while self.layout_.count() > 1:
            widget = self.layout_.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)          # 바로 화면과 목록에서 뺀다 (deleteLater만으로는 다음 이벤트까지 남는다)
                widget.deleteLater()
        entries = [(m['text'], m['role'] == 'user') for m in self.messages]
        if self.pending:
            entries.append((self.pending, True))
        if self.note:
            entries.append((self.note, False))
        for text, user in entries:
            self.layout_.insertWidget(self.layout_.count() - 1, self._bubble(text, user))
        QTimer.singleShot(0, self.scroll_bottom)      # 말풍선 높이가 잡힌 뒤에 맨 아래로

    def scroll_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


STYLE = """
QScrollArea#chatView { background: transparent; border: none; }
QWidget#chatBody { background: transparent; }
QLabel#userBubble { background: @blue; border: none; border-radius: 14px; padding: 10px 12px; color: #ffffff; }
QLabel#coachBubble { background: @raised; border: 1px solid @border; border-radius: 14px; padding: 10px 12px; color: @text; }
"""
