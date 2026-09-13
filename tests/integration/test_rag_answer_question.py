"""rag 입구 answer_question 검증. 인터넷과 API 키가 필요 없다.

docs/interfaces.md 의 초안
    rag.answer_question(질문, 패치, 선택적 분석 결과) -> 답변, 출처, 근거 부족 여부
    knowledge.get_documents(패치, 챔피언 또는 아이템) -> 근거 자료 목록

get_documents 는 '종류별 전체를 돌려준다' 는 합의 전 가정(B)으로 가짜를 만들어 쓴다.
"""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

import rag  # noqa: E402
from rag.gemini import GeminiError  # noqa: E402
from rag.knowledge_source import KINDS, DocumentSource, fixture_get_documents  # noqa: E402

FIXTURE = ROOT / 'tests' / 'fixtures' / 'rag' / 'documents_ddragon.json'
QUESTION = '상대 팀에 단일 대상 궁극기가 많은데 뭘 올려야 하나요?'


def fake_reply(prompt):
    return {'text': '헤르메스의 시미터를 추천합니다. [근거 1]', 'model': 'fake',
            'usage': {'prompt_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}}


class RecordingGetDocuments:
    """get_documents 가 어떤 인자로 몇 번 불렸는지 기록한다."""

    def __init__(self):
        self.calls = []
        self.inner = fixture_get_documents(FIXTURE)

    def __call__(self, patch, kind):
        self.calls.append((patch, kind))
        return self.inner(patch, kind)


class AnswerQuestionTest(unittest.TestCase):

    def setUp(self):
        self.get_documents = RecordingGetDocuments()
        self.source = DocumentSource(self.get_documents)

    def ask(self, question, patch='26.18', analysis=None, **kwargs):
        return rag.answer_question(question, patch, analysis, source=self.source, **kwargs)

    def test_signature_follows_the_draft(self):
        """초안의 입력 순서: 질문, 패치, 선택적 분석 결과."""
        parameters = list(inspect.signature(rag.answer_question).parameters.values())
        self.assertEqual([p.name for p in parameters[:3]], ['question', 'patch', 'analysis'])
        self.assertIsNone(parameters[2].default)
        for extra in parameters[3:]:
            self.assertEqual(extra.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_output_has_the_draft_fields(self):
        """초안의 출력: 답변, 출처, 근거 부족 여부."""
        result = self.ask(QUESTION, generate=fake_reply)
        self.assertIn('헤르메스의 시미터', result['answer'])
        self.assertTrue(result['sources'])
        self.assertIs(result['insufficient_evidence'], False)
        for source in result['sources']:
            self.assertTrue(source['doc_id'] and source['title'] and source['source_url'])

    def test_documents_come_from_get_documents_by_kind(self):
        """가정 B: 패치와 종류로 부르고, 이름은 넘기지 않는다."""
        self.ask(QUESTION)
        self.assertEqual(sorted(self.get_documents.calls), sorted(('26.18', kind) for kind in KINDS))

    def test_documents_are_fetched_once_per_patch(self):
        """종류 전체를 받는 호출은 무거우므로 같은 패치에서는 한 번만 받는다."""
        self.ask(QUESTION)
        self.ask('무한의 대검 언제 사?')
        self.ask('점심 뭐 먹지')
        self.assertEqual(len(self.get_documents.calls), len(KINDS))

    def test_unknown_patch_means_insufficient_evidence(self):
        result = self.ask('무한의 대검 언제 사?', patch='26.19', generate=fake_reply)
        self.assertIs(result['insufficient_evidence'], True)
        self.assertIsNone(result['answer'])
        self.assertEqual(result['sources'], [])

    def test_unknown_patch_keeps_off_topic_and_scope_decisions(self):
        """자료가 없는 패치라도 롤 질문이 아닌 것과 협곡 밖 질문은 그대로 구분한다."""
        self.assertEqual(self.ask('점심 뭐 먹지', patch='26.19')['status'], 'off_topic')
        self.assertEqual(self.ask('칼바람나락에서 시미터 올릴만 한가요?', patch='26.19')['status'], 'out_of_scope')

    def test_name_only_question_on_unknown_patch_is_not_off_topic(self):
        """'무한의 대검' 처럼 이름만 있는 질문은 자료 속 이름으로 롤 질문임을 안다.

        자료가 없는 패치에서 이름 목록까지 비면 이 질문이 '롤 질문 아님' 으로 막혔다. 실제로 그랬다.
        """
        result = self.ask('무한의 대검 언제 사?', patch='26.19')
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertIn(('26.19', 'item'), self.get_documents.calls)
        self.assertIn((None, 'item'), self.get_documents.calls)

    def test_off_topic_is_not_insufficient_evidence(self):
        """롤 질문이 아닌 것과 근거 자료가 없는 것은 다르다."""
        result = self.ask('점심 뭐 먹지', generate=fake_reply)
        self.assertIs(result['insufficient_evidence'], False)
        self.assertEqual(result['status'], 'off_topic')
        self.assertIsNone(result['answer'])

    def test_analysis_is_optional(self):
        without = self.ask('계속 붙어서 싸우는데 핵심 룬 뭐 들죠?')
        with_analysis = self.ask('계속 붙어서 싸우는데 핵심 룬 뭐 들죠?',
                                 analysis={'champion': 'Garen', 'playstyle': {'trade_preference': '지속'}})
        self.assertEqual(without['status'], 'ready')
        self.assertEqual(with_analysis['status'], 'ready')

    def test_model_failure_is_returned_not_raised(self):
        def broken(prompt):
            raise GeminiError('모델이 지금 혼잡합니다.', status=503)

        result = self.ask(QUESTION, generate=broken)
        self.assertEqual(result['status'], 'model_error')
        self.assertIsNone(result['answer'])
        self.assertIs(result['insufficient_evidence'], False)

    def test_knowledge_failure_is_returned_not_raised(self):
        def broken_get_documents(patch, kind):
            raise RuntimeError('DB 연결 실패')

        result = rag.answer_question(QUESTION, '26.18', source=DocumentSource(broken_get_documents))
        self.assertEqual(result['status'], 'knowledge_error')
        self.assertIs(result['insufficient_evidence'], False)
        self.assertIn('DB 연결 실패', result['error'])

    def test_failed_fetch_is_retried_next_time(self):
        state = {'fail': True}
        inner = fixture_get_documents(FIXTURE)

        def flaky(patch, kind):
            if state['fail']:
                raise RuntimeError('잠깐 실패')
            return inner(patch, kind)

        source = DocumentSource(flaky)
        self.assertEqual(rag.answer_question(QUESTION, '26.18', source=source)['status'], 'knowledge_error')
        state['fail'] = False
        self.assertEqual(rag.answer_question(QUESTION, '26.18', source=source)['status'], 'ready')

    def test_missing_knowledge_module_is_reported(self):
        """knowledge.get_documents 가 아직 없으면 오류 상태로 알려 준다. 예외로 멈추지 않는다."""
        import rag.api
        saved = rag.api._default_source
        rag.api._default_source = None
        try:
            result = rag.answer_question(QUESTION, '26.18')
        finally:
            rag.api._default_source = saved
        self.assertEqual(result['status'], 'knowledge_error')
        self.assertIn('get_documents', result['error'])


if __name__ == '__main__':
    unittest.main()
