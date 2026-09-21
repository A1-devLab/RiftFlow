"""out_game 질문 유형 판정 테스트. Gemini 를 부르지 않는다.

질문과 정답은 tests/fixtures/game_phases/out_game_questions.json 에 있다.
blind 는 판정 규칙을 보기 전에 담당자가 쓴 질문이다. 판정이 틀리면 정답이 아니라 규칙을 고친다.
"""
import json
import unittest
from pathlib import Path

from game_phases.out_game.prompt import TYPES, classify
from game_phases.out_game.service import PATCH_HINT, search_text
from rag.knowledge_source import DEFAULT_FIXTURE, DocumentSource, fixture_get_documents
from rag.retrieve import search

OUT_GAME = {'phase': 'out_game'}
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


class SearchTextTest(unittest.TestCase):
    def test_item_rune_question_is_searched_as_is(self):
        self.assertEqual(search_text('무한의 대검 얼마임?', ['item_rune']), '무한의 대검 얼마임?')
        self.assertEqual(search_text('원딜 챔 템 추천', ['champion', 'item_rune']), '원딜 챔 템 추천')

    def test_patch_hint_is_added_otherwise(self):
        for types in (['patch'], ['meta'], ['champion'], ['patch', 'item_rune'], []):
            with self.subTest(types=types):
                self.assertTrue(search_text('질문', types).endswith(PATCH_HINT))


class SearchEffectTest(unittest.TestCase):
    """검색어를 나눈 효과를 실제 out_game 흐름(analysis 에 phase 가 있는 검색)으로 확인한다.

    rag/retrieve.py 는 out_game 이면 모든 패치 노트 조각에 최저 점수 5 를 준다.
    그래서 검색어를 나눠도 아이템 질문의 1, 2위는 여전히 패치 노트다.
    검색어를 나눈 효과는 패치 노트가 '패치 질문' 가산점까지 받아 8점대로 올라가던 것을 막는 데까지다.
    """

    ITEM_QUESTIONS = (('무한의 대검 얼마임?', '무한의 대검'),
                      ('정복자 룬 효과 뭐야', '정복자'),
                      ('마법공학 총검 조합법 알려줘', '마법공학 총검'))

    @classmethod
    def setUpClass(cls):
        source = DocumentSource(fixture_get_documents(DEFAULT_FIXTURE))
        cls.chunks = source.chunks('26.18')

    def results(self, question):
        return search(self.chunks, search_text(question, classify(question)), OUT_GAME)

    def test_item_questions_keep_their_own_document(self):
        for question, name in self.ITEM_QUESTIONS:
            with self.subTest(question=question):
                names = [row['chunk']['subject_name'] for row in self.results(question)]
                self.assertIn(name, names)

    def test_item_questions_do_not_boost_patch_notes_as_patch_questions(self):
        for question, _ in self.ITEM_QUESTIONS:
            with self.subTest(question=question):
                for row in self.results(question):
                    if row['chunk']['kind'] == 'patch':
                        self.assertNotIn('종류:patch', row['reasons'])

    def test_vague_meta_question_still_finds_patch_notes(self):
        results = self.results('요즘 뭐가 좋아?')
        self.assertTrue(results)
        self.assertEqual(results[0]['chunk']['kind'], 'patch')

    @unittest.expectedFailure
    def test_item_question_ranks_item_first(self):
        """알려진 한계. out_game 패치 노트 최저 점수(5)가 아이템 점수(3.3)보다 높다.

        rag/retrieve.py 의 최저 점수가 바뀌면 이 테스트가 '예상치 못한 성공' 으로 알려 준다.
        그때 expectedFailure 를 뗀다.
        """
        self.assertEqual(self.results('무한의 대검 얼마임?')[0]['chunk']['subject_name'], '무한의 대검')


if __name__ == '__main__':
    unittest.main()
