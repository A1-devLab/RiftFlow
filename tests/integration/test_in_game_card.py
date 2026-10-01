"""In-game item card (3 picks with prices) and chat bubbles that are not clipped."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtWidgets import QApplication, QLabel

from game_phases.in_game.desktop import RECOMMEND_QUESTION

OPTIONS = [
    {'item_id': 3089, 'name': '라바돈의 죽음모자', 'price': 3500, 'remaining_cost': 3500, 'affordable': False, 'reason': '화력'},
    {'item_id': 3157, 'name': '존야의 모래시계', 'price': 3250, 'remaining_cost': 2350, 'affordable': True, 'reason': '생존'},
    {'item_id': 3065, 'name': '정령의 형상', 'price': 2900, 'remaining_cost': 2900, 'affordable': None, 'reason': '마저'},
]


class ItemCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_card_shows_three_picks_with_price_color_instead_of_gold_text(self):
        from ui.pages.in_game import InGamePage
        page = InGamePage()
        asked = []
        page.askRequested.connect(asked.append)
        page.items.button.click()
        self.assertEqual(asked[0]['question'], RECOMMEND_QUESTION)
        page.items.show_result({'options': OPTIONS, 'summary': '물리면 2번', 'mode_name': '소환사의 협곡', 'version': '16.1.1'})
        picks = page.items.picks
        self.assertEqual([p.name.text() for p in picks], ['라바돈의 죽음모자', '존야의 모래시계', '정령의 형상'])
        self.assertEqual([p.price.text() for p in picks], ['3,500', '3,250', '2,900'])
        self.assertEqual([p.price.property('affordable') for p in picks], ['no', 'yes', 'unknown'])
        self.assertIn('2,350', picks[1].price.toolTip())                  # 재료 반영 비용은 툴팁에만
        self.assertNotIn('골드', page.items.caption.text())
        self.assertEqual(page.items.button.text(), '다시 추천')
        page.items.show_result({'options': [], 'message': '자료가 없습니다.'})
        self.assertEqual(page.items.caption.text(), '자료가 없습니다.')
        page.show_disconnected()
        self.assertTrue(all(not p.isVisibleTo(page) for p in picks))
        page.close()


class BubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_long_question_bubble_gets_full_height(self):
        from ui.pages.out_game import OutGamePage
        page = OutGamePage()
        page.resize(1280, 760)
        page.show()
        question = '트런들 룬과 아이템 추천해줘 상대는 유미 정글할거야. 유미정글 템트리도 알려줘 ' * 2
        page.add_exchange(question, None)
        self.app.processEvents()
        bubble = next(b for b in page.chat_body.findChildren(QLabel) if b.objectName() == 'userBubble')
        self.assertGreaterEqual(bubble.height(), bubble.heightForWidth(bubble.width()))   # 위아래가 잘리지 않음
        page.close()


if __name__ == '__main__':
    unittest.main()
