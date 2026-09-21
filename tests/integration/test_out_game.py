"""out_game 질문 유형 판정 테스트. Gemini 를 부르지 않는다.

질문과 정답은 tests/fixtures/game_phases/out_game_questions.json 에 있다.
blind 는 판정 규칙을 보기 전에 담당자가 쓴 질문이다. 판정이 틀리면 정답이 아니라 규칙을 고친다.
"""
import json
import unittest
from pathlib import Path

from game_phases.out_game.prompt import SYSTEM, TYPE_NAMES, TYPES, UNKNOWN_TYPE, build, classify
from game_phases.out_game.service import PATCH_HINT, search_text
from rag.knowledge_source import DEFAULT_FIXTURE, DocumentSource, fixture_get_documents
from rag.prompt import estimate_tokens, name_map
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


class PromptTest(unittest.TestCase):
    """팀이 정한 out_game 답변 규칙이 SYSTEM 에 들어 있는지 본다. 모델이 지키는지는 실제 호출로만 알 수 있다."""

    @classmethod
    def setUpClass(cls):
        source = DocumentSource(fixture_get_documents(DEFAULT_FIXTURE))
        cls.chunks = source.chunks('26.18')

    def prompt(self, question):
        evidence = search(self.chunks, question, OUT_GAME)
        return build(question, evidence, OUT_GAME, names=name_map(self.chunks))

    def test_system_carries_each_assigned_rule(self):
        rules = {
            'DB 근거만 사용': "'근거' 에 있는 내용만 쓴다",
            '[근거 N] 표시': '[근거 N]',
            '패치 버전 표시': '버전을 그대로 밝힌다',
            '표본 수 표시': '표본 수',
            '없으면 부족하다고 설명': '추측하지 않는다',
            '패치 변경과 통계 구분': '의도한 변경이지 실제 성적이 아니다',
            '숫자 ID 비노출 (공통 규칙에서 옮김)': '숫자 ID 를 보여 주지 않는다',
            '협곡 한정 (공통 규칙에서 옮김)': '소환사의 협곡만',
        }
        for rule, phrase in rules.items():
            with self.subTest(rule=rule):
                self.assertIn(phrase, SYSTEM)

    def test_champion_rule_does_not_invite_picking_retrieved_champions(self):
        # 검색된 챔피언은 우연히 뽑힌다('변경' 이라는 낱말이 스킬 설명에 있어서 등).
        # 근거에 있다는 이유로 추천하게 두면 근거 없는 추천이 근거 있는 것처럼 보인다.
        self.assertIn('근거에 챔피언이 있다는 것만으로 추천하지 않는다', SYSTEM)
        self.assertIn('역할 분류(예: Marksman, Mage)는 포지션이 아니다', SYSTEM)
        # 데이터가 늘어도 틀린 말이 되지 않게 '없다' 고 단정하지 않는다.
        self.assertNotIn('자료에는 포지션, 승률, 상성, 난이도가 없다', SYSTEM)

    def test_system_fixes_from_line_by_line_review(self):
        """문장별 검토(A~J)와 5단계 실제 호출(①~③)에서 고친 내용. 이유는 out_game/prompt.py 의 SYSTEM 위 주석에 있다."""
        present = {
            'A 패치 노트는 일부 조각': '패치 노트 전체가 아니라 일부 조각이다',
            'A 전체 요약인 척 금지': '전체를 요약한 것처럼 말하지 말고',
            'B 변경 후 값끼리만 비교': '패치 노트의 변경 후 값과 게임 데이터의 값',
            'B 변경 전 값은 비교 안 함': '변경 전 값은 지금 값이 아니므로',
            'C 마크다운 금지': '마크다운 서식을 쓰지 않는다',
            'D 되묻지 말고 다시 물을 예시': '다시 물으면 되는지 예시 질문으로',
            'E 통계를 물을 때만 없다고 밝힘': '이런 통계를 묻는 질문인데 근거에 없으면',
            'F 메타도 조건형': '근거에 통계가 없으면 실제 메타와 티어는',
            'G 의도는 전하되 강해졌다고 하지 않음': '라이엇이 밝힌 의도는 전해도 되지만',
            'H 재료와 조합 비용': '하위 재료와 조합 비용',
            'J 출처 주소와 문서ID 생략': '출처 주소와 문서ID 는',
            '① 자료가 없다는 말에는 근거 번호 없음': '자료가 없다는 말에는 [근거 N] 을 붙이지 않는다',
            '② 근거 번호는 하나씩 따로': '[근거 1] [근거 2] 처럼 하나씩 따로',
            '③ 라이엇의 승률 언급은 통계가 아님': '라이엇의 설명이라고 밝히고 통계처럼 말하지 않는다',
        }
        for fix, phrase in present.items():
            with self.subTest(fix=fix):
                self.assertIn(phrase, SYSTEM)
        absent = {
            'E 조건 없는 통계 문구': '. 근거에 통계가 없으면 "지금',
            'F 메타 단정': '통계가 없어 확정할 수 없다',
            'G 판단을 말하게 하는 문구': '판단을 나눠',
            'H 게임 중 골드 상황': '골드가 부족할 때',
            'I 버전 예시 숫자': '26.18',
            'I 버전 예시 숫자 (게임 데이터)': '16.18.1',
            'D 되묻기': '무엇을 알려 주면 되는지 묻는다',
        }
        for fix, phrase in absent.items():
            with self.subTest(fix=fix):
                self.assertNotIn(phrase, SYSTEM)

    def test_system_names_every_question_type(self):
        for name in TYPE_NAMES.values():
            with self.subTest(type=name):
                self.assertIn('- %s:' % name, SYSTEM)

    def test_build_uses_out_game_system_and_type_line(self):
        prompt = self.prompt('무한의 대검 얼마임?')
        self.assertEqual(prompt['system'], SYSTEM)
        self.assertIn('질문 유형: 아이템·룬', prompt['user'])
        self.assertTrue(prompt['user'].rstrip().endswith('무한의 대검 얼마임?'))

    def test_unknown_type_is_left_to_the_model(self):
        self.assertIn('질문 유형: ' + UNKNOWN_TYPE, self.prompt('무한의 대검 언제 사?')['user'])

    def test_size_is_counted_with_out_game_system(self):
        prompt = self.prompt('무한의 대검 얼마임?')
        self.assertEqual(prompt['chars'], len(prompt['system']) + len(prompt['user']))
        self.assertEqual(prompt['estimated_tokens'],
                         estimate_tokens(prompt['system']) + estimate_tokens(prompt['user']))


if __name__ == '__main__':
    unittest.main()
