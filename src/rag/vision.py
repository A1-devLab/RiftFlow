"""증바람 증강 선택 화면 캡처에서 증강 이름을 읽는다 (HASA의 OpenAI 호환 이미지 입력 모델).

사용자가 F10을 눌렀을 때 찍은 화면 한 장만 보낸다. 화면을 계속 지켜보거나 저장하지 않는다.
모델은 이름을 읽기만 하고, 어떤 증강인지는 코드가 증강 목록과 맞춰 정한다(목록에 없는 이름은 버린다).
"""
import base64
import difflib
import json
import os
import re
import urllib.error
import urllib.request

from .gemini import GeminiError
from .openai_compat import DEFAULT_BASE_URL, api_keys, classify

DEFAULT_MODEL = 'qwen3-vl-32b'
TIMEOUT = 60
MAX_IMAGE = 1_500_000
PICKS = 3
READ_SYSTEM = """너는 리그 오브 레전드 증바람(무작위 총력전 증강 모드) 화면에서 글자를 읽는다.
이미지는 증강 선택 화면 캡처다. 화면에 카드로 제시된 증강의 이름만 읽는다 (보통 3개, 왼쪽부터).
known_names는 이번 패치 증바람 증강 이름 목록이다. 화면의 이름과 같은 것이 있으면 목록의 표기를 그대로 쓴다.
설명 문장, 등급, 버튼 글자, 채팅, 스코어보드 글자는 이름이 아니다. 화면에 증강 카드가 없으면 빈 목록을 돌려준다.
반드시 {"names": ["이름1", "이름2", "이름3"]} 형식의 JSON만 답한다."""


def _key(name):
    return re.sub(r'[\s\W_]+', '', str(name or '')).lower()


def match_names(read, catalog, limit=PICKS):
    """모델이 읽은 이름 → 목록의 증강. 띄어쓰기, 문장부호 차이와 한두 글자 오인식까지 받는다."""
    by_key = {_key(a['name']): a for a in catalog if a.get('name')}
    keys = list(by_key)
    found = []
    for name in read:
        key = _key(name)
        if not key:
            continue
        hit = by_key.get(key)
        if hit is None:
            close = difflib.get_close_matches(key, keys, n=1, cutoff=0.75)
            hit = by_key[close[0]] if close else None
        if hit is not None and hit not in found:
            found.append(hit)
        if len(found) == limit:
            break
    return found


def _names(text):
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    fenced = re.search(r'\{.*\}', text, flags=re.S)
    try:
        data = json.loads(fenced.group(0) if fenced else text)
    except (ValueError, AttributeError):
        return []
    names = data.get('names') if isinstance(data, dict) else data
    return [str(n) for n in names if isinstance(n, (str, int))] if isinstance(names, list) else []


def read_augments(image, catalog, *, key=None, model=None, base_url=None, opener=None):
    """캡처(JPEG/PNG 바이트) → 목록에서 찾은 증강들 [{id, name, ...}]. 실패하면 GeminiError."""
    if not image:
        raise GeminiError('게임 화면을 캡처하지 못했습니다.')
    if len(image) > MAX_IMAGE:
        raise GeminiError('캡처 이미지가 너무 큽니다.')
    if not catalog:
        raise GeminiError('증강 목록이 없습니다. 잠시 뒤 다시 시도해 주세요.')
    model = model or os.environ.get('HASA_VISION_MODEL') or DEFAULT_MODEL
    url = (base_url or os.environ.get('HASA_BASE_URL') or DEFAULT_BASE_URL).rstrip('/') + '/chat/completions'
    mime = 'image/png' if image[:4] == b'\x89PNG' else 'image/jpeg'
    known = [a['name'] for a in catalog if a.get('name')]
    body = json.dumps({'model': model, 'temperature': 0, 'max_tokens': 300, 'messages': [
        {'role': 'system', 'content': READ_SYSTEM},
        {'role': 'user', 'content': [
            {'type': 'text', 'text': json.dumps({'known_names': known}, ensure_ascii=False)},
            {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime, base64.b64encode(image).decode('ascii'))}}]}]},
        ensure_ascii=False).encode('utf-8')
    send = opener or urllib.request.urlopen
    failure = None
    for api_key in api_keys(key):
        request = urllib.request.Request(url, data=body, method='POST',
                                         headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key})
        try:
            with send(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            failure = classify(error.code, error.read().decode('utf-8', 'replace'), model)
            if error.code in (401, 403, 429):
                continue
            raise failure
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise GeminiError('화면 인식 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.')
        try:
            text = payload['choices'][0]['message'].get('content') or ''
        except (KeyError, IndexError, TypeError, AttributeError):
            text = ''
        return match_names(_names(text), catalog)
    raise GeminiError('화면 인식을 잠시 쓸 수 없습니다. 잠시 뒤 다시 눌러 주세요.',
                      status=getattr(failure, 'status', None), detail=getattr(failure, 'message', None))
