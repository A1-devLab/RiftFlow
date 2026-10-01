"""OpenAI 호환 Chat Completions 호출 (HASA Open AI Service Hub 등). 표준 라이브러리만 쓴다.

gemini.py와 같은 형태로 부르고 같은 결과를 돌려준다: generate(prompt, ...) → {'text', 'model', ...}.
실패하면 GeminiError를 던진다. 호출하는 쪽(룬·아이템·질문)이 이미 GeminiError만 처리하므로 오류 종류를 늘리지 않는다.

키는 환경변수 HASA_API_KEY에서 읽는다. 쉼표로 여러 개를 줄 수 있다 (내 키, 팀원 키).
HASA 한도는 키마다 따로라서(개발키: 분당 10회, 동시 1건, 하루 성공 500회) 키가 둘이면 한도도 두 배가 된다.
코드·저장소·로그에 키를 남기지 않는다. 키는 내부에서 해시 앞 8자리로만 구분한다.

키마다 상태를 따로 둔다.
- 동시 1건: 키마다 자리 하나. 비어 있는 키를 먼저 쓰고, 모두 바쁘면 slot_wait초까지 기다린다.
- 분당 한도: 키마다 최근 1분 동안 보낸 시각. 넘길 것 같으면 그 키는 건너뛴다.
- 하루 한도(429)·키 무효(403 invalid_api_key): 그 키만 잠시 쉬게 하고 다른 키로 바로 다시 보낸다.
  키 무효를 계속 보내면 HASA가 경고를 쌓다가 차단하므로(10회 초과부터 1→32분) 30분 동안 쓰지 않는다.
- 모델 권한 없음(403 model_not_on_key): 그 키에서 그 모델만 10분 동안 건너뛴다. 권한이 생기면 자동으로 다시 쓴다.
- 서버 일시 오류(5xx)는 자리를 놓은 뒤 잠깐 쉬고 다시 보낸다 (자리를 쥔 채 잠들지 않는다).

모델도 쉼표로 여러 개를 줄 수 있다 (HASA_MODEL=qwen3-next-80b,nemotron-super-120b). 앞 모델을 어느 키로도 쓸 수 없으면 다음 모델.
"""
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from .gemini import GeminiError, parse_seconds

DEFAULT_BASE_URL = 'https://open.hasa.re.kr/v1'
DEFAULT_MODEL = 'nemotron-super-120b'
MODEL_BLOCK = 600          # 권한 없음·시간 초과가 난 모델을 건너뛰는 시간
QUOTA_BLOCK = 600          # 한도에 걸린 키를 쉬게 하는 시간
INVALID_BLOCK = 1800       # 무효로 거절된 키를 쓰지 않는 시간 (HASA 경고 누적 방지)
SLOT_WAIT = 8              # 모든 키가 바쁠 때 기다리는 시간. 대체 모델이 없으면 호출하는 쪽이 길게 준다
RPM_LIMIT = 10             # 개발키 분당 한도
TIMEOUT = 90               # 한 번 응답을 기다리는 시간. 앱은 AI 요청을 180초까지 기다린다 (api_client.coach.AI_TIMEOUT)
MAX_WAIT = 20              # 5xx에 Retry-After가 이보다 짧으면 기다렸다 한 번 더 보낸다
DEFAULT_CONFIG = {'temperature': 0.2, 'maxOutputTokens': 4096}
THINK = re.compile(r'<think>.*?</think>', re.S)
RETRYABLE = (500, 502, 503, 504)

_lock = threading.Lock()
_free = threading.Condition(_lock)
_busy = set()              # 지금 요청 중인 키 ID (키마다 동시 1건)
_sent = {}                 # 키 ID → 최근 1분 동안 보낸 시각
_key_blocked = {}          # 키 ID → (다시 쓸 시각, 사유)
_model_blocked = {}        # (키 ID, 모델) → 다시 쓸 시각. 키 ID '*'는 모든 키 (공용 GPU 시간 초과)


def api_keys(explicit=None):
    raw = explicit or os.environ.get('HASA_API_KEY') or ''
    keys = [key.strip() for key in str(raw).split(',') if key.strip()]
    if not keys:
        raise GeminiError('HASA_API_KEY가 없습니다. .env(또는 서버의 server.env)에 설정하세요.')
    return keys


def api_key(explicit=None):
    """첫 번째 키."""
    return api_keys(explicit)[0]


def key_id(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:8]


def reset_state():
    """키·모델 상태를 비운다 (테스트, 키를 바꾼 뒤)."""
    with _lock:
        _busy.clear()
        _sent.clear()
        _key_blocked.clear()
        _model_blocked.clear()


def json_schema(schema):
    """Gemini responseSchema(OBJECT, INTEGER …)를 JSON Schema(object, integer …)로 바꾼다."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == 'type':
            result['type'] = str(value).lower()
        elif key == 'properties':
            result['properties'] = {name: json_schema(sub) for name, sub in value.items()}
        elif key == 'items':
            result['items'] = json_schema(value)
        elif key in ('required', 'enum', 'description'):
            result[key] = value
    return result


def build_request(prompt, model=DEFAULT_MODEL, config=None, json_mode=True):
    """Gemini 형식 설정(generationConfig)을 OpenAI 형식으로 옮긴다. 키는 넣지 않는다.

    json_mode: True면 스키마가 있을 때 json_schema(정수 ID·이유 구조를 강제), 없으면 json_object.
    'object'면 json_object만, False면 형식 없이 보낸다 (형식을 걸면 빈 답을 주는 모델용).
    """
    config = dict(DEFAULT_CONFIG, **(config or {}))
    body = {'model': model,
            'messages': [{'role': 'system', 'content': prompt['system']},
                         {'role': 'user', 'content': prompt['user']}],
            'temperature': config.get('temperature', 0.2),
            'max_tokens': config.get('maxOutputTokens', 4096)}
    if json_mode and config.get('responseMimeType') == 'application/json':
        if json_mode is True and config.get('responseSchema'):
            body['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'riftflow', 'schema': json_schema(config['responseSchema'])}}
        else:
            body['response_format'] = {'type': 'json_object'}
    return body


def _content(payload):
    choices = payload.get('choices') or [{}]
    return THINK.sub('', ((choices[0] or {}).get('message') or {}).get('content') or '').strip()


def read_text(payload):
    choices = payload.get('choices') or []
    if not choices:
        raise GeminiError('모델이 답변을 돌려주지 않았습니다.')
    reason = choices[0].get('finish_reason') or '알 수 없음'
    text = _content(payload)
    if not text:
        raise GeminiError('답변이 비어 있습니다. 종료 사유: %s' % reason)
    return text, reason


def classify(code, detail, model):
    if code == 404 or (code == 403 and 'model_not_on_key' in detail):
        return GeminiError('이 키로 %s 모델을 쓸 수 없습니다.' % model, status=code, kind='model_not_allowed')
    if code == 401 or (code == 403 and ('invalid_api_key' in detail or 'security_policy' in detail)):
        return GeminiError('AI 키가 거부되었습니다. HASA_API_KEY를 확인하세요.', status=code, kind='invalid_key')
    if code == 403:
        return GeminiError('AI 키로 이 요청을 할 수 없습니다 (403).', status=code)
    if code == 429:
        return GeminiError('AI 호출 한도를 넘었습니다. 잠시 뒤 다시 시도하세요.', status=429, kind='quota',
                           detail={'status': 429, 'model': model, 'body': detail[:300]})
    if code == 503:
        return GeminiError('AI 서버가 준비 중이거나 혼잡합니다. 잠시 뒤 다시 시도하세요.', status=503)
    if code >= 500:
        return GeminiError('AI 서버 오류입니다 (%s). 잠시 뒤 다시 시도하세요.' % code, status=code)
    return GeminiError('AI 호출이 실패했습니다 (%s): %s' % (code, detail[:200]), status=code)


def _post(url, body, headers, send):
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
    with send(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode('utf-8'))


def _downgrade(body):
    """보낸 형식에서 한 단계 낮춘다: json_schema → json_object → 형식 없음."""
    return 'object' if body.get('response_format', {}).get('type') == 'json_schema' else False


def _usable(keys, model, now):
    result = []
    for key in keys:
        kid = key_id(key)
        blocked = _key_blocked.get(kid)
        if blocked and blocked[0] > now:
            continue
        if _model_blocked.get((kid, model), 0) > now or _model_blocked.get(('*', model), 0) > now:
            continue
        result.append(key)
    return result


def _acquire(keys, model, clock, slot_wait):
    """쓸 수 있는 키 중 비어 있고 분당 한도가 남은 키 하나를 잡는다. 쓸 키가 없으면 None, 모두 바쁘면 기다린다."""
    deadline = time.monotonic() + slot_wait
    with _free:
        while True:
            now = clock()
            usable = _usable(keys, model, now)
            if not usable:
                return None
            for key in usable:
                kid = key_id(key)
                sent = _sent.setdefault(kid, [])
                sent[:] = [at for at in sent if at > now - 60]
                if kid not in _busy and len(sent) < RPM_LIMIT:
                    _busy.add(kid)
                    sent.append(now)
                    return key
            left = deadline - time.monotonic()
            if left <= 0:
                raise GeminiError('AI 요청이 몰려 있습니다. 잠시 뒤 다시 시도해 주세요.', status=503, kind='busy')
            _free.wait(min(left, 1.0))


def _release(key):
    with _free:
        _busy.discard(key_id(key))
        _free.notify_all()


def _block_reason(keys, model, now):
    """왜 보낼 키가 없는지. 한도로 쉬는 중인데 '모델이 없다'고 잘못 안내하지 않게 사유를 구분한다."""
    reasons = set()
    for key in keys:
        kid = key_id(key)
        blocked = _key_blocked.get(kid)
        if blocked and blocked[0] > now:
            reasons.add(blocked[1])
        elif _model_blocked.get(('*', model), 0) > now:
            reasons.add('timeout')
        elif _model_blocked.get((kid, model), 0) > now:
            reasons.add('model_not_allowed')
    if reasons & {'quota', 'timeout'}:
        return GeminiError('AI 사용량이 많아 잠시 쉬는 중입니다. 잠시 뒤 다시 시도해 주세요.', status=429, kind='quota')
    if reasons == {'invalid_key'}:
        return GeminiError('AI 키가 거부되어 잠시 쓰지 않고 있습니다. HASA_API_KEY를 확인하세요.', status=403,
                           kind='invalid_key')
    return GeminiError('이 키로 %s 모델을 쓸 수 없습니다.' % model, status=403, kind='model_not_allowed')


def generate(prompt, model=DEFAULT_MODEL, key=None, config=None, opener=None, retries=1, sleep=time.sleep,
             base_url=None, clock=time.time, slot_wait=SLOT_WAIT):
    keys = api_keys(key)
    models = [m.strip() for m in str(model or DEFAULT_MODEL).split(',') if m.strip()]
    error = None
    for name in models:
        try:
            return _generate_with_keys(prompt, name, keys, config, opener, retries, sleep, base_url, clock, slot_wait)
        except GeminiError as failure:
            if failure.kind != 'model_not_allowed':
                raise
            error = failure                     # 어느 키로도 이 모델을 못 쓰면 다음 모델
    raise error


def _generate_with_keys(prompt, model, keys, config, opener, retries, sleep, base_url, clock, slot_wait):
    attempt = 0
    while True:
        key = _acquire(keys, model, clock, slot_wait)
        if key is None:
            raise _block_reason(keys, model, clock())
        kid, wait = key_id(key), None
        try:
            return _call(prompt, model, key, config, opener, base_url)
        except GeminiError as failure:
            now = clock()
            with _lock:
                if failure.kind == 'quota':
                    _key_blocked[kid] = (now + QUOTA_BLOCK, 'quota')
                elif failure.kind == 'invalid_key':
                    _key_blocked[kid] = (now + INVALID_BLOCK, 'invalid_key')
                elif failure.kind == 'model_not_allowed':
                    _model_blocked[(kid, model)] = now + MODEL_BLOCK
                elif failure.kind == 'timeout':
                    _model_blocked[('*', model)] = now + MODEL_BLOCK
            if failure.kind == 'timeout':
                raise                           # 공용 GPU가 막힌 것이라 다른 키로 보내도 같다
            if failure.kind is None:
                retryable = failure.status in RETRYABLE or failure.status is None
                if not retryable or attempt >= retries or (failure.retry_after or 3) > MAX_WAIT:
                    raise
                attempt += 1
                wait = failure.retry_after or 3
            # 한도·무효·권한처럼 이 키만의 문제면 다른 키로 바로 다시 보낸다
        finally:
            _release(key)
        if wait:
            sleep(wait)                         # 자리를 놓은 뒤에 쉰다


def _call(prompt, model, key, config, opener, base_url):
    """키 하나로 한 번 요청한다 (형식 낮추기 포함). 자리는 호출한 쪽이 쥐고 있다."""
    url = (base_url or os.environ.get('HASA_BASE_URL') or DEFAULT_BASE_URL).rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
    send = opener or urllib.request.urlopen
    json_mode = True
    while True:
        body = build_request(prompt, model, config, json_mode)
        try:
            payload = _post(url, body, headers, send)
            if 'response_format' in body and not _content(payload):
                # 스키마를 걸면 빈 답을 주는 모델이 있다 (gpt-oss: 추론 형식과 충돌). 한 단계 낮춰 다시 보낸다.
                # 형식을 아예 빼면 gpt-oss는 JSON 대신 글로 답하므로 json_object를 먼저 시도한다.
                json_mode = _downgrade(body)
                continue
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')
            # 형식을 지원하지 않는 모델이면 한 단계씩 낮춰 다시 보낸다 (형식은 프롬프트와 코드 검증이 지킨다).
            if error.code == 400 and 'response_format' in body and 'response_format' in detail:
                json_mode = _downgrade(body)
                continue
            failure = classify(error.code, detail, model)
            failure.retry_after = parse_seconds(error.headers.get('Retry-After')) if error.headers else None
            raise failure
        except urllib.error.URLError as error:
            raise GeminiError('AI 서버에 연결하지 못했습니다: %s' % error.reason)
        except (TimeoutError, OSError, http.client.HTTPException, ValueError) as error:
            # 읽기 시간 초과·연결 끊김·깨진 본문. 시간 초과를 다시 보내면 같은 시간을 또 기다리므로 재시도하지 않는다.
            raise GeminiError('AI 응답이 늦거나 끊겼습니다 (%s). 공용 GPU가 붐비는 중일 수 있으니 잠시 뒤 다시 시도하세요.'
                              % type(error).__name__, kind='timeout')
    usage = payload.get('usage') or {}
    text, reason = read_text(payload)
    return {'text': text, 'model': model, 'finish_reason': reason, 'truncated': reason == 'length',
            'usage': {'prompt_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'),
                      'thinking_tokens': None, 'total_tokens': usage.get('total_tokens')}}
