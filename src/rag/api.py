"""rag 의 입구. docs/interfaces.md 의 answer_question(질문, 패치, 선택적 분석 결과) 을 따른다.

    초안의 출력: 답변, 출처, 근거 부족 여부
    이 함수의 출력: answer, sources, insufficient_evidence

합의 전 임시로 정한 것 (docs/interfaces.md '합의할 사항' 에 따라 팀과 정해야 함)
- 근거 자료는 knowledge.get_documents(patch, 종류) 로 종류별 전체를 받는다 (가정 B, knowledge_source.py).
- 동기 함수다.
- 오류는 예외로 던지지 않고 status 와 error 로 돌려준다.
- status, reason, message, error, usage 는 초안에 없는 추가 정보다.
- analysis 의 모양({'champion': ..., 'playstyle': {...}})도 합의되지 않았다.

rag 는 riot 을 부르지 않는다. 분석 결과는 호출하는 쪽이 riot 의 결과를 분석해 넘긴다.
"""
from .knowledge_source import DocumentSource, KnowledgeUnavailable, knowledge_get_documents
from .pipeline import answer

_default_source = None


def default_source():
    """knowledge.get_documents 를 쓰는 기본 자료원. 처음 부를 때 한 번 만든다."""
    global _default_source
    if _default_source is None:
        _default_source = DocumentSource(knowledge_get_documents())
    return _default_source


def failed(status, reason, error):
    return {
        'answer': None,
        'sources': [],
        'insufficient_evidence': False,
        'status': status,
        'reason': reason,
        'message': error,
        'error': error,
        'usage': None,
    }


def answer_question(question, patch, analysis=None, *, source=None, generate=None, store=None):
    """질문에 답한다.

    question  사용자 질문
    patch     패치 번호. 예 '26.18'. 모르면 None
    analysis  선택적 분석 결과. 없으면 None

    아래는 초안에 없는 인자다. 테스트와 개발 도구가 바꿔 끼우기 위해 있다.
    source    근거 자료원. 주지 않으면 knowledge.get_documents 를 쓴다
    generate  모델 호출 함수. 주지 않으면 프롬프트만 만들고 모델을 부르지 않는다
    store     대화 저장소. 주지 않으면 남기지 않는다

    반환
    answer                 답변 문장. 모델을 부르지 않았거나 실패했으면 None
    sources                출처 목록. 각 항목에 doc_id, title, source_url, version
    insufficient_evidence  근거 자료가 없어 답하지 않았으면 True
    status, reason, message, error, usage   초안에 없는 추가 정보
    """
    try:
        source = source or default_source()
        chunks = source.chunks(patch)
    except KnowledgeUnavailable as error:
        return failed('knowledge_error', 'knowledge 모듈 없음', str(error))
    except Exception as error:                      # noqa: BLE001
        return failed('knowledge_error', '근거 자료를 받지 못함',
                      '근거 자료를 받지 못했습니다: %s' % error)

    result = answer(chunks, question, analysis, patch=patch, generate=generate, store=store,
                    name_chunks=source.name_chunks(patch))
    return {
        'answer': result['answer'],
        'sources': result['sources'],
        'insufficient_evidence': result['status'] == 'insufficient_evidence',
        'status': result['status'],
        'reason': result['reason'],
        'message': result['message'],
        'error': result['error'],
        'usage': result['usage'],
    }
