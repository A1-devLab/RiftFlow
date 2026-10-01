"""서버 모드의 AI 기능. 결과 형식은 직접 모드 함수와 같아서 화면 코드는 그대로 쓴다.

보내기 전에 game_phases.payloads로 정리해 소환사 이름 같은 개인 정보를 빼고 크기를 제한한다.
서버와 통신하지 못하면 예외 대신 화면에 보여 줄 안내 문장을 담아 돌려준다.
"""
from contracts.riot import RiotApiError
from game_phases import payloads

# 서버는 HASA(최대 90초)가 실패하면 Gemini(최대 60초)로 넘기므로 그보다 길게 기다린다.
AI_TIMEOUT = 180


def _answer_failure(error):
    return {'answer': None, 'message': str(error), 'generated': False}


def recommend_runes(client, view, *, champion, opponent, user_requests, recent_pages):
    body = {'champion': payloads.text(champion, 40), 'opponent': payloads.text(opponent, 40) or None,
            'view': payloads.pick_view(view), 'user_requests': payloads.user_requests(user_requests),
            'recent_pages': payloads.recent_pages(recent_pages)}
    try:
        return client.post_json('/v1/runes/recommend', body, timeout=AI_TIMEOUT)
    except RiotApiError as error:
        return {'page': None, 'summary': None, 'reasons': [], 'generated': False, 'message': str(error), 'attempts': 0}


def coach_pick(client, view, question, *, champion, opponent, user_requests, observations, history=None):
    body = {'question': payloads.text(question, 1000), 'champion': payloads.text(champion, 40),
            'opponent': payloads.text(opponent, 40) or None, 'view': payloads.pick_view(view),
            'user_requests': payloads.user_requests(user_requests),
            'observations': payloads.observations(observations), 'history': payloads.history(history)}
    try:
        return client.post_json('/v1/coach/pick', body, timeout=AI_TIMEOUT)
    except RiotApiError as error:
        return _answer_failure(error)


def coach_in_game(client, view, question, history=None):
    try:
        return client.post_json('/v1/coach/in-game', {'question': payloads.text(question, 1000),
                                                      'view': payloads.live_view(view),
                                                      'history': payloads.history(history)}, timeout=AI_TIMEOUT)
    except RiotApiError as error:
        return _answer_failure(error)


def coach_general(client, question, context, history=None):
    try:
        result = client.post_json('/v1/coach/general', {'question': payloads.text(question, 1000),
                                                        'context': payloads.general_context(context),
                                                        'history': payloads.history(history)}, timeout=AI_TIMEOUT)
    except RiotApiError as error:
        message = str(error)
        return {'status': 'model_error', 'message': message, 'answer': None, 'generated': False, 'error': message,
                'evidence': [], 'sources': []}
    return dict(result, evidence=[], sources=[])
