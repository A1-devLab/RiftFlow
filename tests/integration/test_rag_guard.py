"""안전장치 검증. 인터넷과 API 키가 필요 없다.

Gemini 를 부르기 전에 네 가지 상태를 구분하는지 본다.

  off_topic              롤 질문이 아니다
  out_of_scope           롤이지만 협곡이 아니다
  insufficient_evidence  협곡 질문인데 자료가 없다
  ready                  근거를 찾았다

앞의 세 가지는 Gemini 를 부르지 않아야 한다. 그것이 토큰 낭비 방지의 목적이다.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from rag.guard import check  # noqa: E402
from rag.pipeline import prepare  # noqa: E402
from rag.store import build_index, load_documents  # noqa: E402

FIXTURES = ROOT / 'tests' / 'fixtures'

OFF_TOPIC = [
    '내일 서울 날씨 어때? 그리고 파이썬으로 크롤러 짜는 법 알려줘',
    '점심 뭐 먹지',
    'ㅁㄴㅇㄹ 아무말',
    # 우리 자료에 있는 낱말을 쓰지만 롤 질문이 아닌 것들.
    # 검색만으로는 걸러지지 않아 안전장치가 필요하다.
    '회복 잘 되는 영양제 추천해줘',
    '대검 같은 칼 어디서 파나요',
    '방어력 높은 자동차 추천',
    '이동 속도 빠른 자전거 뭐 살까',
    '체력 기르는 운동 알려줘',
    '피해 보상 어떻게 받나요',
]

OUT_OF_SCOPE = [
    '칼바람나락에서 시미터 올릴만 한가요?',
    '아람에서 무한의 대검 어때요?',
    '아레나 2대2에서 뭐 사요?',
    '롤체 덱 추천해줘',
    '우르프에서 뭐 가요',
]

# 롤 질문이 맞지만 지금 자료로는 답할 수 없는 것들.
# 차단이 아니라 근거 부족이어야 한다.
NO_EVIDENCE = [
    '한타 때 뭐 사요?',
    '딜교 어떻게 해야 돼?',
]


class GuardTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.chunks = build_index(load_documents(
            FIXTURES / 'rag' / 'documents_ddragon.json'))

    def test_off_topic_is_blocked(self):
        for question in OFF_TOPIC:
            with self.subTest(question=question):
                self.assertEqual(check(question, self.chunks)['decision'], 'off_topic')

    def test_other_modes_are_out_of_scope(self):
        for question in OUT_OF_SCOPE:
            with self.subTest(question=question):
                verdict = check(question, self.chunks)
                self.assertEqual(verdict['decision'], 'out_of_scope')
                self.assertIn('협곡', verdict['message'])

    def test_summoners_rift_questions_pass(self):
        for question in ['상대 팀에 단일 대상 궁극기가 많은데 뭘 올려야 하나요?',
                         '상대 탑이 계속 회복해서 못 잡겠어요',
                         '무한의 대검 언제 올리는 게 좋나요?',
                         '이번 패치에서 카시오페아 뭐 바뀌었어?']:
            with self.subTest(question=question):
                self.assertEqual(check(question, self.chunks)['decision'], 'allow')

    def test_no_evidence_is_not_blocked(self):
        """롤 질문인데 자료가 없는 것과, 롤 질문이 아닌 것은 다르다."""
        for question in NO_EVIDENCE:
            with self.subTest(question=question):
                self.assertEqual(check(question, self.chunks)['decision'], 'allow')
                self.assertEqual(prepare(self.chunks, question)['status'],
                                 'insufficient_evidence')

    def test_model_is_not_called_without_evidence(self):
        """차단, 범위 밖, 근거 부족은 모두 Gemini 를 부르지 않아야 한다."""
        for question in OFF_TOPIC + OUT_OF_SCOPE + NO_EVIDENCE:
            with self.subTest(question=question):
                self.assertFalse(prepare(self.chunks, question)['calls_model'])

    def test_blocked_questions_get_a_message(self):
        for question in OFF_TOPIC + OUT_OF_SCOPE:
            with self.subTest(question=question):
                self.assertTrue(prepare(self.chunks, question)['message'])

    def test_fixture_guard_cases(self):
        """questions.json 의 안전장치 케이스."""
        with open(FIXTURES / 'rag' / 'questions.json', encoding='utf-8') as handle:
            cases = json.load(handle)['cases']
        expected = {'off_topic_guard': 'off_topic', 'out_of_scope_mode': 'out_of_scope'}
        for case in cases:
            if case['case_id'] not in expected:
                continue
            with self.subTest(case=case['case_id']):
                outcome = prepare(self.chunks, case['input']['question'],
                                  case['input'].get('analysis'))
                self.assertEqual(outcome['status'], expected[case['case_id']])
                self.assertFalse(outcome['calls_model'])


if __name__ == '__main__':
    unittest.main()
