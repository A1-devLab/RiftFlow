import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch, Mock
from PySide6.QtWidgets import QApplication, QTableWidget
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from ui.pages.out_game import OutGamePage
from ui.match_detail import MatchDetailDialog
from riot.service import get_match_detail
from contracts.riot import MatchDataUnavailable


class MatchDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_click_and_keyboard_open_correct_match(self):
        page = OutGamePage()
        card = page._match_card(dict(match_id='KR_42', win=True))
        selected = []
        page.matchRequested.connect(selected.append)
        card.show()
        QTest.mouseClick(card, Qt.LeftButton)
        QTest.keyClick(card, Qt.Key_Return)
        self.assertEqual(selected, ['KR_42', 'KR_42'])
        card.close()
        page.close()

    def test_card_shows_local_play_date_and_english_metrics(self):
        from datetime import datetime
        from PySide6.QtWidgets import QLabel
        page = OutGamePage()
        epoch = 1790000000
        card = page._match_card(dict(match_id='KR_1', win=True, champion_name='Ahri', played_at_epoch=epoch,
                                     damage_to_champions=21000, gold_earned=12000))
        texts = [label.text() for label in card.findChildren(QLabel)]
        moment = datetime.fromtimestamp(epoch)
        self.assertIn(moment.strftime('%Y.%m.%d'), ' '.join(texts))
        self.assertIn(moment.strftime('%H:%M'), texts)
        self.assertIn('Damage  21,000', texts)
        self.assertIn('Gold  12,000', texts)
        sample = page._match_card(dict(win=False), sample=True)
        self.assertFalse(sample.findChildren(QLabel, 'matchDate'))
        page.close()

    def test_selected_player_stats_and_missing_values(self):
        detail = {'info': {'participants': [
            {'puuid': 'other', 'teamId': 100, 'championName': 'Ahri'},
            {'puuid': 'me', 'teamId': 200, 'championName': 'Lux', 'totalHeal': 1234, 'visionScore': 0},
        ]}}
        dialog = MatchDetailDialog(detail, 'me')
        self.assertEqual(dialog.player.currentIndex(), 1)
        healing = dialog.tabs.widget(3).widget(0)
        self.assertEqual(healing.item(0, 1).text(), '1,234')
        self.assertEqual(healing.item(1, 1).text(), '—')
        self.assertEqual(dialog.tabs.widget(4).widget(0).item(0, 1).text(), '0')
        dialog.chart_button.click()
        self.assertEqual(dialog.tabs.widget(3).currentIndex(), 1)
        self.assertEqual(dialog.tabs.widget(4).currentIndex(), 1)
        dialog.number_button.click()
        self.assertEqual(dialog.tabs.widget(3).currentIndex(), 0)
        dialog.player.setCurrentIndex(0)
        self.assertEqual(dialog.tabs.widget(3).widget(0).item(0, 1).text(), '—')
        dialog.close()

    def test_service_fetch_and_missing_match(self):
        client = Mock()
        detail = {'info': {'participants': [{'puuid': 'me'}]}}
        with patch('riot.service._get_client', return_value=client):
            client.get_region.return_value = detail
            self.assertEqual(get_match_detail('KR_42'), detail)
            client.get_region.assert_called_with('/lol/match/v5/matches/KR_42')
            client.get_region.return_value = None
            with self.assertRaises(MatchDataUnavailable):
                get_match_detail('KR_42')
