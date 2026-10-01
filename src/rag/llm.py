"""AI 제공자 고르기. 기본은 HASA(OpenAI 호환). LLM_PROVIDER=gemini면 Gemini.

데스크톱·서버·터미널이 모두 여기의 generate를 부른다. 프롬프트와 결과 형식은 제공자와 상관없이 같다.

HASA만 쓰는 것이 기본이다 (1.0.0부터). LLM_FALLBACK=gemini를 따로 주면 HASA가 실패할 때 Gemini로 넘긴다.
대체 모델이 없으므로 HASA 키가 모두 바쁘면 차례를 길게 기다린다 (FALLBACK_SLOT_WAIT, 없을 때 NO_FALLBACK_SLOT_WAIT).
모델 선택 기록: HASA 모델끼리 같은 픽창으로 비교해 nemotron-super-120b를 골랐다 (2026-10, 정석 룬을 첫 시도에 통과,
룬 18초·아이템 10초). qwen3-next-80b는 키 권한이 열리면 앞에 넣어 비교한 뒤 쓴다.
"""
import os

from . import gemini, openai_compat

PROVIDERS = {'gemini': (gemini, 'GEMINI_API_KEY', 'GEMINI_MODEL'),
             'hasa': (openai_compat, 'HASA_API_KEY', 'HASA_MODEL')}


def provider(name=None):
    name = (name or os.environ.get('LLM_PROVIDER') or 'hasa').strip().lower()
    return name if name in PROVIDERS else 'hasa'


def key_env(name=None):
    return PROVIDERS[provider(name)][1]


def has_key(name=None):
    return bool(os.environ.get(key_env(name)))


def default_model(name=None):
    module, _key, model_env = PROVIDERS[provider(name)]
    return os.environ.get(model_env) or module.DEFAULT_MODEL


def with_fallback(first, second):
    """first가 GeminiError로 실패하면 second로 다시 부른다. second가 없으면 first의 오류를 그대로 낸다."""
    if second is None:
        return first

    def call(prompt, **options):
        try:
            return first(prompt, **options)
        except gemini.GeminiError:
            result = second(prompt, **options)
            result['fallback'] = True
            return result
    return call


FALLBACK_SLOT_WAIT = 8
NO_FALLBACK_SLOT_WAIT = 60


def fallback_enabled():
    return (os.environ.get('LLM_FALLBACK') or '').strip().lower() == 'gemini' and bool(os.environ.get('GEMINI_API_KEY'))


def generate(prompt, model=None, provider_name=None, **options):
    name = provider(provider_name)
    if name != 'hasa':
        return gemini.generate(prompt, model=model or default_model(name), **options)
    fallback = fallback_enabled()
    wait = FALLBACK_SLOT_WAIT if fallback else NO_FALLBACK_SLOT_WAIT
    first = lambda p, **o: openai_compat.generate(p, model=model or default_model(name), slot_wait=wait, **o)
    second = (lambda p, **o: gemini.generate(p, model=default_model('gemini'), **o)) if fallback else None
    return with_fallback(first, second)(prompt, **options)
