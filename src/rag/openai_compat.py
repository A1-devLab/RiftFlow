"""OpenAI 호환 Chat Completions 호출 (HASA Open AI Service Hub 등). 표준 라이브러리만 쓴다.

gemini.py와 같은 형태로 부르고 같은 결과를 돌려준다: generate(prompt, ...) → {'text', 'model', ...}.
실패하면 GeminiError를 던진다. 호출하는 쪽(룬·아이템·질문)이 이미 GeminiError만 처리하므로 오류 종류를 늘리지 않는다.

키는 환경변수 HASA_API_KEY에서 읽는다. 코드·저장소·로그에 키를 남기지 않는다.

모델은 쉼표로 여러 개를 줄 수 있다 (HASA_MODEL=qwen3-next-80b,gpt-oss-120b). 앞 모델을 키가 쓸 수 없으면
(403 model_not_on_key, 404) 다음 모델로 넘어가고, 그 모델은 10분 동안 건너뛴다. 권한이 생기면 자동으로 앞 모델로 돌아온다.

HASA 개발키 한도 (2026-10 이용안내 기준): 분당 10회, 동시 1건, 하루 성공 호출 500회, 하루 토큰 2천만.
동시 1건이라 같은 프로세스 안에서는 세마포어로 한 번에 하나씩만 보낸다 (서버에 5명이 동시에 물어도 429가 나지 않게).
"""
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
DEFAULT_MODEL = 'qwen3-next-80b'
BLOCK_SECONDS = 600
_blocked = {}              # 모델 → 다시 시도할 시각 (키에 권한이 없던 모델)
TIMEOUT = 150             # 공용 GPU가 붐비면 추론형 모델(gpt-oss) 룬 추천이 90초를 넘긴 적이 있다
MAX_WAIT = 20              # 429에 Retry-After가 이보다 짧으면 기다렸다 한 번 더 보낸다 (동시·분당 한도)
DEFAULT_CONFIG = {'temperature': 0.2, 'maxOutputTokens': 4096}
_slots = threading.BoundedSemaphore(max(1, int(os.environ.get('HASA_CONCURRENCY') or 1)))
THINK = re.compile(r'<think>.*?</think>', re.S)


def api_key(explicit=None):
    key = explicit or os.environ.get('HASA_API_KEY')
    if not key:
        raise GeminiError('HASA_API_KEY가 없습니다. .env(또는 서버의 server.env)에 설정하세요.')
    return key


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
    choice = choices[0]
    reason = choice.get('finish_reason') or '알 수 없음'
    text = THINK.sub('', (choice.get('message') or {}).get('content') or '').strip()
    if not text:
        raise GeminiError('답변이 비어 있습니다. 종료 사유: %s' % reason)
    return text, reason


def classify(code, detail, model):
    if code == 404 or (code == 403 and 'model_not_on_key' in detail):
        return GeminiError('이 키로 %s 모델을 쓸 수 없습니다.' % model, status=code, kind='model_not_allowed')
    if code in (401, 403):
        return GeminiError('API 키가 거부되었거나 이 키로 %s 모델을 쓸 수 없습니다. HASA_API_KEY를 확인하세요.' % model,
                           status=code)
    if code == 429:
        return GeminiError('AI 호출 한도를 넘었습니다. 잠시 뒤 다시 시도하세요. 계속되면 오늘 한도(하루 500회)를 다 쓴 것입니다.',
                           status=429, kind='quota', detail={'status': 429, 'model': model, 'body': detail[:300]})
    if code == 503:
        return GeminiError('AI 서버가 준비 중이거나 혼잡합니다. 잠시 뒤 다시 시도하세요.', status=503)
    if code >= 500:
        return GeminiError('AI 서버 오류입니다 (%s). 잠시 뒤 다시 시도하세요.' % code, status=code)
    return GeminiError('AI 호출이 실패했습니다 (%s): %s' % (code, detail[:200]), status=code)


def _post(url, body, headers, send):
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
    with send(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode('utf-8'))


def generate(prompt, model=DEFAULT_MODEL, key=None, config=None, opener=None, retries=1, sleep=time.sleep,
             base_url=None, clock=time.time):
    models = [m.strip() for m in str(model or DEFAULT_MODEL).split(',') if m.strip()]
    error = None
    for name in models:
        if _blocked.get(name, 0) > clock():
            continue                    # 권한 없던 모델: 10분 동안 호출하지 않는다 (매번 403을 받으며 늦어지지 않게)
        try:
            return _generate(prompt, name, key, config, opener, retries, sleep, base_url)
        except GeminiError as failure:
            if failure.kind != 'model_not_allowed':
                raise
            _blocked[name] = clock() + BLOCK_SECONDS
            error = failure
    raise error or GeminiError('이 키로 쓸 수 있는 모델이 없습니다: %s' % ', '.join(models), kind='model_not_allowed')


def _downgrade(body):
    """보낸 형식에서 한 단계 낮춘다: json_schema → json_object → 형식 없음."""
    return 'object' if body.get('response_format', {}).get('type') == 'json_schema' else False


def _generate(prompt, model, key, config, opener, retries, sleep, base_url):
    url = (base_url or os.environ.get('HASA_BASE_URL') or DEFAULT_BASE_URL).rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key(key)}
    send = opener or urllib.request.urlopen
    json_mode = True
    attempt = 0
    with _slots:
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
                wait = parse_seconds(error.headers.get('Retry-After')) if error.headers else None
                failure.retry_after = wait
                retryable = error.code in (429, 500, 502, 503, 504)
                if retryable and attempt < retries and (wait or 3) <= MAX_WAIT:
                    attempt += 1
                    sleep(wait or 3)
                    continue
                raise failure
            except urllib.error.URLError as error:
                if attempt < retries:
                    attempt += 1
                    sleep(3)
                    continue
                raise GeminiError('AI 서버에 연결하지 못했습니다: %s' % error.reason)
            except (TimeoutError, OSError, http.client.HTTPException, ValueError) as error:
                # 읽기 시간 초과·연결 끊김·깨진 본문. 시간 초과를 다시 보내면 같은 시간을 또 기다리므로 재시도하지 않는다.
                raise GeminiError('AI 응답이 늦거나 끊겼습니다 (%s). 공용 GPU가 붐비는 중일 수 있으니 잠시 뒤 다시 시도하세요.'
                                  % type(error).__name__)
    usage = payload.get('usage') or {}
    text, reason = read_text(payload)
    return {'text': text, 'model': model, 'finish_reason': reason, 'truncated': reason == 'length',
            'usage': {'prompt_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'),
                      'thinking_tokens': None, 'total_tokens': usage.get('total_tokens')}}
