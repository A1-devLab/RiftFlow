"""out_game 질문 유형 판정 테스트. Gemini 를 부르지 않는다.

질문과 정답은 tests/fixtures/game_phases/out_game_questions.json 에 있다.
blind 는 판정 규칙을 보기 전에 담당자가 쓴 질문이다. 판정이 틀리면 정답이 아니라 규칙을 고친다.
"""
import json
import unittest
from pathlib import Path

from game_phases.out_game.prompt import TYPES, classify

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'game_phases' / 'out_game_questions.json'


def load_cases():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


class ClassifyFixtureTest(unittest.TestCase):
    def check_set(self, name):
        cases = [case for case in load_cases() if case['set'] == name]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(id=case['id'], question=case['question']):
                self.assertEqual(classify(case['question']), case['types'])

    def test_blind_questions(self):
        self.check_set('blind')

    def test_dev_questions(self):
        self.check_set('dev')


class ClassifyRuleTest(unittest.TestCase):
    def test_result_follows_type_order(self):
        self.assertEqual(classify('이번 패치 이후 메타 어때?'), ['patch', 'meta'])
        for kind in classify('이번 패치 이후 메타 어때?'):
            self.assertIn(kind, TYPES)

    def test_spacing_does_not_matter(self):
        self.assertEqual(classify('정글 뭐 해야 돼?'), classify('정글뭐해야돼?'))

    def test_recommend_alone_is_not_champion(self):
        self.assertEqual(classify('점심 메뉴 추천해줘'), [])

    def test_position_item_question_is_not_champion(self):
        self.assertEqual(classify('원딜 아이템 뭐가 좋아?'), ['item_rune'])

    def test_empty_question(self):
        self.assertEqual(classify(''), [])
        self.assertEqual(classify(None), [])


if __name__ == '__main__':
    unittest.main()
