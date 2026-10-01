"""AI 제공자 고르기. LLM_PROVIDER=hasa면 HASA(OpenAI 호환), 그 밖에는 Gemini.

데스크톱·서버·터미널이 모두 여기의 generate를 부른다. 프롬프트와 결과 형식은 제공자와 상관없이 같다.

HASA를 고르고 Gemini 키도 있으면, HASA가 실패할 때(키에 모델 권한 없음, 한도, 혼잡, 시간 초과) Gemini로 넘긴다.
같은 르블랑 픽창으로 비교했을 때 Gemini는 2.7초에 정석 룬을 골랐고, 지금 키로 쓸 수 있는 HASA 모델(gpt-oss-120b)은
10~90초가 걸리고 결과가 흔들렸다 (2026-10). 그래서 HASA는 Qwen3 Next 하나만 두고, 안 되면 Gemini가 답한다.
"""
import os

from . import gemini, openai_compat

PROVIDERS = {'gemini': (gemini, 'GEMINI_API_KEY', 'GEMINI_MODEL'),
             'hasa': (openai_compat, 'HASA_API_KEY', 'HASA_MODEL')}


def provider(name=None):
    name = (name or os.environ.get('LLM_PROVIDER') or 'gemini').strip().lower()
    return name if name in PROVIDERS else 'gemini'


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


def generate(prompt, model=None, provider_name=None, **options):
    name = provider(provider_name)
    module = PROVIDERS[name][0]
    first = lambda p, **o: module.generate(p, model=model or default_model(name), **o)
    second = None
    if name == 'hasa' and os.environ.get('GEMINI_API_KEY'):
        second = lambda p, **o: gemini.generate(p, model=default_model('gemini'), **o)
    return with_fallback(first, second)(prompt, **options)
