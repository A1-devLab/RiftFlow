"""Gemini 호출. 표준 라이브러리만 쓴다.

google-genai 패키지를 쓰지 않는다.
의존성을 늘리면 공통 설정 변경이라 팀과 먼저 공유해야 하는데,
REST 로 부르면 urllib 만으로 충분하다.

API 키는 환경변수 GEMINI_API_KEY 에서 읽는다.
코드나 저장소에 키를 적지 않는다. 로그에도 남기지 않는다.
공식 문서는 키를 URL 쿼리에 붙이라고 안내하지만,
쿼리에 넣으면 접속 기록과 오류 로그에 키가 남으므로 헤더로 보낸다.

실제 키로 확인한 것 (2026-09-12)
- 엔드포인트와 x-goog-api-key 헤더가 동작한다.
- 모델 이름 gemini-3.8-flash 가 존재한다. 503 이 왔다는 것은 모델을 찾았다는 뜻이다.
- 키가 틀리면 401 이 아니라 400 에 API_KEY_INVALID 로 온다.
아직 확인하지 못한 것: 성공 응답의 본문 구조. 첫 성공 호출 때 확인해야 한다.
"""
import json
import math
import os
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent'
DEFAULT_MODEL = 'gemini-3.5-flash-lite'
TIMEOUT = 60

# 503 은 모델이 붐빌 때 나온다. 잠깐 뒤 풀리는 경우가 있어 한 번만 더 시도한다.
# 무료 등급은 모델당 하루 20번이라, 재시도 한 번도 하루 한도를 쓸 수 있다.
# 예전에는 2초, 4초 뒤 두 번 더 보내서 한 질문에 최대 3번 나갔다. 지금은 5초 뒤 한 번, 최대 2번이다.
# 429(한도 초과)는 다시 불러도 같은 결과라 재시도하지 않는다.
RETRY_CODES = (500, 502, 503, 504)
RETRIES = 1
BACKOFF_SECONDS = 5

# 근거에 있는 내용을 그대로 옮기는 일이라 창의성은 낮게 둔다.
#
# maxOutputTokens 는 넉넉히 잡는다. Gemini 3 계열은 답변 전에 '생각' 을 하는데
# 그 토큰이 이 한도에 같이 들어간다. 실제로 1024 로 두었더니 생각에 902 를 쓰고
# 답변에 41 만 남아 문장이 중간에 잘렸다. (usageMetadata 의 thoughtsTokenCount 로 확인)
DEFAULT_CONFIG = {
    'temperature': 0.2,
    'maxOutputTokens': 4096,
}


class GeminiError(Exception):
    """호출 실패. 사용자에게 보여 줄 메시지를 message 에 담는다."""

    def __init__(self, message, status=None, retry_after=None, kind=None, detail=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after     # 몇 초 뒤 다시 시도할지. 기다려도 소용없으면 None
        self.kind = kind                   # daily_quota, minute_quota, quota 등
        self.detail = detail               # 대화 기록에 남길 원인. 사용자에게 보여 주지 않는다


def parse_seconds(value):
    """'59s', '59.77s', '30' 같은 대기 시간을 초 단위 정수로 바꾼다. 없거나 읽을 수 없으면 None."""
    if value is None:
        return None
    text = str(value).strip().rstrip('s')
    try:
        return int(math.ceil(float(text)))
    except ValueError:
        return None


def quota_error(body, model):
    """429 본문에서 어떤 한도에 걸렸는지 읽어 알맞은 안내를 만든다.

    Gemini 는 하루 한도에 걸려도 'Please retry in 59s' 를 붙여 보낸다.
    그 말대로 1분 기다려도 풀리지 않아서, 한도 ID(quotaId)로 하루 한도인지 먼저 가린다.
    실제로 받은 값: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue 20 (2026-09-13)
    """
    quota_id = limit = delay = None
    try:
        error = json.loads(body).get('error') or {}
    except (ValueError, AttributeError):
        error = {}
    for item in error.get('details') or []:
        item_type = str(item.get('@type', ''))
        if item_type.endswith('QuotaFailure'):
            for violation in item.get('violations') or []:
                quota_id = quota_id or violation.get('quotaId')
                limit = limit or violation.get('quotaValue')
        elif item_type.endswith('RetryInfo'):
            delay = parse_seconds(item.get('retryDelay'))

    quota = quota_id or ''
    tier = '무료 ' if 'FreeTier' in quota else ''
    detail = {
        'status': 429,
        'model': model,
        'quota_id': quota_id,
        'quota_limit': int(limit) if limit is not None and str(limit).isdigit() else limit,
        'server_retry_delay': delay,
    }

    if 'PerDay' in quota:
        count = '%s회' % limit if limit is not None else '한도'
        message = ('오늘 %s %s호출 %s를 다 썼습니다. 태평양 시간 자정에 초기화되며, '
                   '한국 시간으로 오후 4시(11월 초~3월 초에는 오후 5시)입니다. 그 전에는 기다려도 풀리지 않습니다.'
                   % (model, tier, count))
        return GeminiError(message, status=429, retry_after=None, kind='daily_quota', detail=detail)
    if 'PerMinute' in quota:
        wait = '%d초 뒤' % delay if delay else '잠시 뒤'
        return GeminiError('분당 호출 한도를 넘었습니다. %s 다시 시도하세요.' % wait,
                           status=429, retry_after=delay, kind='minute_quota', detail=detail)
    return GeminiError('호출 한도를 넘었습니다. 한도 종류를 알 수 없어 잠시 뒤 다시 시도하고, '
                       '계속되면 https://ai.dev/rate-limit 에서 사용량을 확인하세요.',
                       status=429, retry_after=delay, kind='quota', detail=detail)


def api_key(explicit=None):
    key = explicit or os.environ.get('GEMINI_API_KEY')
    if not key:
        raise GeminiError('GEMINI_API_KEY 가 없습니다. .env 에 설정한 뒤 다시 실행하세요.')
    return key


def build_request(prompt, model=DEFAULT_MODEL, config=None):
    """보낼 본문을 만든다. 키는 여기에 넣지 않는다."""
    return {
        'systemInstruction': {'parts': [{'text': prompt['system']}]},
        'contents': [{'role': 'user', 'parts': [{'text': prompt['user']}]}],
        'generationConfig': dict(DEFAULT_CONFIG, **(config or {})),
    }


def read_text(payload):
    """응답에서 본문과 종료 사유를 꺼낸다. 비어 있으면 이유를 알려 준다."""
    candidates = payload.get('candidates') or []
    if not candidates:
        blocked = (payload.get('promptFeedback') or {}).get('blockReason')
        raise GeminiError('모델이 답변을 돌려주지 않았습니다. 사유: %s' % (blocked or '알 수 없음'))

    candidate = candidates[0]
    reason = candidate.get('finishReason', '알 수 없음')
    parts = (candidate.get('content') or {}).get('parts') or []
    text = ''.join(part.get('text', '') for part in parts).strip()
    if not text:
        raise GeminiError('답변이 비어 있습니다. 종료 사유: %s' % reason)
    return text, reason


def classify(code, detail, model):
    """HTTP 오류를 사용자에게 보여 줄 말로 바꾼다.

    본문 JSON 을 그대로 보여 주지 않는다. 사용자가 읽을 내용이 아니다.
    """
    # 키가 틀리면 401 이 아니라 400 에 API_KEY_INVALID 로 온다. 실제 응답으로 확인했다.
    if code in (401, 403) or 'API_KEY_INVALID' in detail:
        return GeminiError('API 키가 거부되었습니다. GEMINI_API_KEY 값을 확인하세요.', status=code)
    if code == 404:
        return GeminiError('모델을 찾을 수 없습니다: %s. 모델 이름을 확인하세요.' % model, status=404)
    if code == 429:
        return quota_error(detail, model)
    if code == 503:
        return GeminiError('모델이 지금 혼잡합니다. 잠시 뒤 다시 시도하세요. '
                           '계속되면 --model 로 다른 모델을 지정해 보세요.', status=503)
    if code >= 500:
        return GeminiError('Gemini 서버 오류입니다 (%s). 잠시 뒤 다시 시도하세요.' % code, status=code)
    return GeminiError('Gemini 호출이 실패했습니다 (%s): %s' % (code, detail[:200]), status=code)


def generate(prompt, model=DEFAULT_MODEL, key=None, config=None, opener=None,
             retries=RETRIES, sleep=time.sleep):
    """Gemini 를 부른다. opener 를 넣으면 테스트에서 가짜 응답을 쓸 수 있다.

    503 과 500 대 오류는 잠깐 뒤 풀리는 경우가 많아 몇 번 더 시도한다.
    키가 틀렸거나 모델 이름이 틀린 경우는 다시 시도해도 소용없으므로 바로 멈춘다.
    """
    body = json.dumps(build_request(prompt, model, config)).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key(key)}
    send = opener or urllib.request.urlopen

    for attempt in range(retries + 1):
        request = urllib.request.Request(ENDPOINT % model, data=body,
                                         headers=headers, method='POST')
        try:
            with send(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')
            failure = classify(error.code, detail, model)
            # 하루 한도는 기다려도 풀리지 않으므로 헤더의 대기 시간을 따르지 않는다.
            if failure.retry_after is None and failure.kind != 'daily_quota':
                failure.retry_after = parse_seconds(error.headers.get('Retry-After'))
            if error.code in RETRY_CODES and attempt < retries:
                sleep(BACKOFF_SECONDS * (attempt + 1))
                continue
            raise failure
        except urllib.error.URLError as error:
            if attempt < retries:
                sleep(BACKOFF_SECONDS * (attempt + 1))
                continue
            raise GeminiError('Gemini 에 연결하지 못했습니다: %s' % error.reason)

    usage = payload.get('usageMetadata') or {}
    text, reason = read_text(payload)
    return {
        'text': text,
        'model': model,
        'finish_reason': reason,
        'truncated': reason == 'MAX_TOKENS',
        'usage': {
            'prompt_tokens': usage.get('promptTokenCount'),
            'output_tokens': usage.get('candidatesTokenCount'),
            # 생각 토큰도 요금과 한도에 들어간다. 따로 봐야 한도를 맞출 수 있다.
            'thinking_tokens': usage.get('thoughtsTokenCount'),
            'total_tokens': usage.get('totalTokenCount'),
        },
    }
