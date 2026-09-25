import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock


from contracts.riot import MatchSummary, PostGameSummary
from game_phases.after_game.desktop import (analyze_after_game, baseline_from_matches, describe_summary,
                                            wait_for_summary)
from knowledge.collector import connect, save


def summary(champion='Ahri', deaths=0):
    return PostGameSummary(1800, 'WIN', 8, deaths, 12, 190, 190 / 30, 62.5, 24000, 17000, 31, champion)


def match(champion, win, mode='CLASSIC', cs=150, damage=18000):
    return MatchSummary('private-match', 1, 1500, mode, champion, win, 5, 5, 5, cs, damage)


class AfterGameDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        with closing(connect(self.db)) as db, db:
            save(db, 'champion', '16.19.1', 'Ahri', '아리', json.dumps(
                {'key': '103', 'id': 'Ahri', 'name': '아리', 'blurb': '아홉 꼬리 여우', 'tags': ['Mage']},
                ensure_ascii=False), 'https://example.com/champion')

    def test_summary_view_handles_zero_deaths(self):
        view = describe_summary(summary())
        self.assertEqual(view['result_name'], '승리')
        self.assertEqual(view['kda_ratio'], 20.0)
        self.assertEqual(view['cs_per_min'], 6.3)
        self.assertEqual(view['damage_per_min'], 800)
        self.assertEqual(view['clock'], '30:00')
        self.assertIsNone(describe_summary(None))

    def test_baseline_uses_rift_games_and_same_champion_first(self):
        matches = [match('Ahri', True), match('Ahri', False), match('Lux', True), match('Ahri', True, mode='ARAM')]
        baseline = baseline_from_matches(matches, 'Ahri')
        self.assertEqual(baseline['overall']['games'], 3)
        self.assertEqual(baseline['champion']['games'], 2)
        self.assertEqual(baseline['champion']['wins'], 1)
        self.assertEqual(baseline['overall']['cs_per_min'], 6.0)
        self.assertIsNone(baseline_from_matches([match('Ahri', True, mode='ARAM')]))

    def test_wait_for_summary_retries_and_stops(self):
        fetch = Mock(side_effect=[None, None, 'done'])
        self.assertEqual(wait_for_summary(lambda: False, timeout=10, fetch=fetch, sleep=lambda _s: None), 'done')
        self.assertEqual(fetch.call_count, 3)
        never = Mock(return_value=None)
        self.assertIsNone(wait_for_summary(lambda: True, fetch=never))
        never.assert_not_called()
        self.assertIsNone(wait_for_summary(lambda: False, timeout=0, fetch=never))
        never.assert_called_once()

    def test_analysis_prompt_uses_actual_numbers_and_personal_baseline(self):
        generator = Mock(return_value={'text': '한 줄 요약: 승리'})
        matches = [match('Ahri', True), match('Ahri', False)]
        result = analyze_after_game(self.db, summary(champion=None), generate=generator,
                                    champion='아리', matches=matches)
        self.assertTrue(result['generated'])
        prompt = generator.call_args.args[0]
        payload = json.loads(prompt['user'])
        self.assertEqual(payload['game_result']['kill_participation_pct'], 62)
        self.assertEqual(payload['personal_baseline']['champion']['games'], 2)
        self.assertEqual(payload['official_champion']['name'], '아리')
        self.assertIn('잘한 점', payload['request'])
        self.assertNotIn('private-', prompt['user'])
        self.assertIn('사망 원인', prompt['system'])

    def test_missing_summary_does_not_call_model(self):
        generator = Mock()
        result = analyze_after_game(self.db, None, generate=generator)
        generator.assert_not_called()
        self.assertFalse(result['generated'])



if __name__ == '__main__':
    unittest.main()
