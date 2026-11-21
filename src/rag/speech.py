"""음성 질문을 글자로 바꾼다 (HASA의 OpenAI 호환 /audio/transcriptions, whisper-large-v3-turbo).

openai_compat.py와 같은 키(HASA_API_KEY, 쉼표로 여러 개)를 쓰고 표준 라이브러리만 쓴다. 음성은 바꾸는 데만 쓰고 저장하지 않는다.
키가 무효로 거절되면 다음 키로 넘긴다. 같은 무효 키를 계속 보내면 HASA가 경고를 쌓으므로 다시 보내지 않는다.
"""
import json
import os
import uuid
import urllib.error
import urllib.request

from .gemini import GeminiError
from .openai_compat import DEFAULT_BASE_URL, api_keys, classify

DEFAULT_MODEL = 'whisper-large-v3-turbo'
TIMEOUT = 30
MAX_AUDIO = 2 * 1024 * 1024       # 앱은 16kHz 단일 채널로 최대 10초(약 320KB)를 보낸다
# 용어 힌트(prompt)는 보내지 않는다. HASA whisper에 한국어 prompt를 주면 받아 적기가 깨졌다 (2026-11-21 확인).
# 소리가 거의 없을 때 whisper가 지어내는 영상 끝인사류 문장. 이런 답은 알아듣지 못한 것으로 본다.
HALLUCINATIONS = ('시청해 주셔서 감사합니다', '시청해주셔서 감사합니다', '구독과 좋아요', '구독 좋아요', 'MBC 뉴스',
                  '자막 제공', '감사합니다.')


def _multipart(fields, audio, filename='question.wav'):
    boundary = 'riftflow-%s' % uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode('utf-8'))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: audio/wav\r\n\r\n'
                  % (boundary, filename)).encode('utf-8') + audio + b'\r\n')
    parts.append(('--%s--\r\n' % boundary).encode('utf-8'))
    return b''.join(parts), 'multipart/form-data; boundary=%s' % boundary


def transcribe(audio, *, key=None, model=None, language='ko', base_url=None, opener=None):
    """WAV 바이트 → 받아 적은 문장. 실패하면 GeminiError(사용자에게 보여 줄 message)."""
    if not audio:
        raise GeminiError('녹음된 음성이 없습니다.')
    if len(audio) > MAX_AUDIO:
        raise GeminiError('음성이 너무 깁니다. 10초 안으로 짧게 말해 주세요.')
    model = model or os.environ.get('HASA_STT_MODEL') or DEFAULT_MODEL
    url = (base_url or os.environ.get('HASA_BASE_URL') or DEFAULT_BASE_URL).rstrip('/') + '/audio/transcriptions'
    body, content_type = _multipart({'model': model, 'language': language, 'response_format': 'json'}, audio)
    send = opener or urllib.request.urlopen
    failure = None
    for api_key in api_keys(key):
        request = urllib.request.Request(url, data=body, method='POST',
                                         headers={'Content-Type': content_type, 'Authorization': 'Bearer ' + api_key})
        try:
            with send(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            failure = classify(error.code, error.read().decode('utf-8', 'replace'), model)
            if error.code in (401, 403, 429):
                continue                   # 이 키는 못 쓰니 다음 키로
            raise failure
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise GeminiError('음성 인식 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.')
        text = ' '.join(str(payload.get('text') or '').split())
        if not text or any(text == h or (text.startswith(h) and len(text) < len(h) + 6) for h in HALLUCINATIONS):
            raise GeminiError('목소리를 알아듣지 못했습니다. 조금 더 크게 다시 말해 주세요.')
        return text
    # 모든 키가 거절됐다. 짧은 시간에 여러 번 보내면 HASA가 음성 인식만 잠깐 막기도 해서(채팅은 됨) 키 문제로 단정하지 않는다.
    raise GeminiError('음성 인식을 잠시 쓸 수 없습니다. 잠시 뒤 다시 말해 주세요.',
                      status=getattr(failure, 'status', None), detail=getattr(failure, 'message', None))
