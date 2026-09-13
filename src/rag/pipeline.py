"""질문 하나를 처리하는 흐름. 아직 Gemini 를 부르지 않는다.

  질문 -> 안전장치 -> 검색 -> (여기까지 구현) -> 프롬프트 조립 -> Gemini -> 답변

상태를 네 가지로 나눈다. docs/interfaces.md 의 '서로 구분한다' 를 따른다.

  off_topic              롤 질문이 아니다. 검색도 생성도 하지 않는다.
  out_of_scope           협곡 밖 모드다. 검색도 생성도 하지 않는다.
  insufficient_evidence  롤 질문이고 협곡인데 근거 자료가 없다. 생성하지 않는다.
  ready                  근거를 찾았다. 프롬프트 조립으로 넘어간다.

앞의 세 가지는 Gemini 를 부르지 않는다. 토큰을 쓰지 않는다는 뜻이다.
"""
from .guard import check
from .prompt import build, name_map
from .retrieve import search, sources_of

NO_EVIDENCE = '가지고 있는 자료로는 답할 수 없습니다. 근거 없이 추측해서 답하지 않습니다.'


def prepare(chunks, question, analysis=None, top_k=5):
    """질문을 판정하고 근거를 모은다.

    돌려주는 값의 calls_model 이 False 면 Gemini 를 부르지 않는다.
    """
    verdict = check(question, chunks)
    if verdict['decision'] != 'allow':
        return {
            'status': verdict['decision'],
            'reason': verdict['reason'],
            'message': verdict['message'],
            'evidence': [],
            'sources': [],
            'calls_model': False,
        }

    results = search(chunks, question, analysis, top_k=top_k)
    if not results:
        return {
            'status': 'insufficient_evidence',
            'reason': '검색 결과 없음',
            'message': NO_EVIDENCE,
            'evidence': [],
            'sources': [],
            'calls_model': False,
        }

    return {
        'status': 'ready',
        'reason': verdict['reason'],
        'message': None,
        'evidence': results,
        'sources': sources_of(results),
        'calls_model': True,
    }


def answer(chunks, question, analysis=None, patch=None, top_k=5,
           generate=None, store=None, conversation_id=None, provider='gemini'):
    """질문 하나를 끝까지 처리한다.

    generate 를 넣지 않으면 프롬프트만 만들고 모델을 부르지 않는다.
    키가 없어도 여기까지 확인할 수 있다.

    store 를 넣으면 결과를 남긴다. 막힌 질문도 남긴다.
    어떤 질문이 왜 막혔는지 봐야 안전장치를 고칠 수 있다.
    """
    outcome = prepare(chunks, question, analysis, top_k)
    prompt = reply = error = None

    if outcome['calls_model']:
        prompt = build(question, outcome['evidence'], analysis, patch,
                       names=name_map(chunks))
        if generate is not None:
            try:
                reply = generate(prompt)
            except Exception as failure:          # noqa: BLE001
                error = getattr(failure, 'message', str(failure))
                outcome = dict(outcome, status='model_error', message=error)

    if store is not None:
        from .conversation import save
        save(store['db'], conversation_id or store['conversation_id'],
             question, outcome, prompt, reply, provider, patch, analysis)

    return {
        'status': outcome['status'],
        'reason': outcome['reason'],
        'message': outcome['message'],
        'sources': outcome['sources'],
        'evidence': outcome['evidence'],
        'prompt': prompt,
        'answer': (reply or {}).get('text'),
        'usage': (reply or {}).get('usage'),
        'error': error,
    }
