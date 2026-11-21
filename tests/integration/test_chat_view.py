"""픽창, 인게임 AI 질문 칸이 말풍선 대화로 보인다."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from ui.chat_view import ChatView



class ChatViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_conversation_pending_question_and_notes_are_bubbles(self):
        view = ChatView()
        view.setPlainText('질문해 보세요.')
        self.app.processEvents()
        self.assertEqual(view.toPlainText(), '질문해 보세요.')
        view.set_pending('초반 운영은?')
        view.setPlainText('자료를 확인하고 있습니다…')
        self.app.processEvents()
        names = [(b.objectName(), b.text()) for b in view.body.findChildren(QLabel)]
        self.assertEqual(names, [('userBubble', '초반 운영은?'), ('coachBubble', '자료를 확인하고 있습니다…')])
        view.show_messages([{'role': 'user', 'text': '초반 운영은?'}, {'role': 'assistant', 'text': '<b>라인</b>을 지키세요.'}])
        self.app.processEvents()
        labels = view.body.findChildren(QLabel)
        self.assertEqual([b.objectName() for b in labels], ['userBubble', 'coachBubble'])
        self.assertTrue(all(b.textFormat() == Qt.PlainText for b in labels))     # 답의 HTML은 글자로만
        self.assertEqual(view.toPlainText(), '나: 초반 운영은?\n\nAI: <b>라인</b>을 지키세요.')
        view.show_messages([])
        self.app.processEvents()
        self.assertEqual(view.body.findChildren(QLabel), [])

    def test_pick_and_in_game_pages_show_the_question_right_away(self):
        from ui.pages.before_game import BeforeGamePage
        from ui.pages.in_game import InGamePage
        pick = BeforeGamePage()
        pick.champion.setText('')
        pick.question.setText('티모 상대 팁?')
        pick.submit()
        self.assertIn('나: 티모 상대 팁?', pick.answer.toPlainText())
        game = InGamePage()
        game.question.setText('지금 불리해?')
        game.submit()
        self.assertIn('나: 지금 불리해?', game.answer.toPlainText())
        pick.close()
        game.close()


if __name__ == '__main__':
    unittest.main()
