"""AI provider switch: Gemini by default, HASA (OpenAI-compatible) with LLM_PROVIDER=hasa. No network or real key."""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from rag import llm, openai_compat
from rag.gemini import GeminiError

PROMPT = {'system': '시스템', 'user': '질문'}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reply(text, reason='stop'):
    return FakeResponse(json.dumps({'choices': [{'message': {'content': text}, 'finish_reason': reason}],
                                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}).encode())


def http_error(code, body='', headers=None):
    return urllib.error.HTTPError('u', code, 'x', headers or {}, io.BytesIO(body.encode()))


class OpenAICompatTests(unittest.TestCase):
    def test_request_shape_auth_header_and_json_mode(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return reply('<think>생각</think>{"a": 1}')
        result = openai_compat.generate(PROMPT, model='qwen3-next-80b', key='sk-dev-test', opener=opener,
                                        config={'responseMimeType': 'application/json', 'responseSchema': {
                                            'type': 'OBJECT', 'properties': {'ids': {'type': 'ARRAY', 'items': {'type': 'INTEGER'}}},
                                            'required': ['ids'], 'propertyOrdering': ['ids']}},
                                        base_url='https://example.test/v1')
        self.assertEqual(result['text'], '{"a": 1}')                     # 생각 태그는 지운다
        request = sent[0]
        self.assertEqual(request.full_url, 'https://example.test/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer sk-dev-test')
        body = json.loads(request.data)
        self.assertEqual(body['model'], 'qwen3-next-80b')
        self.assertEqual([m['role'] for m in body['messages']], ['system', 'user'])
        self.assertEqual(body['response_format']['type'], 'json_schema')   # Gemini 스키마를 JSON Schema로 옮김
        self.assertEqual(body['response_format']['json_schema']['schema'],
                         {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'integer'}}},
                          'required': ['ids']})
        self.assertNotIn('sk-dev-test', json.dumps(body))                 # 키는 헤더에만

    def test_drops_json_mode_when_model_rejects_it(self):
        bodies = []

        def opener(request, timeout):
            bodies.append(json.loads(request.data))
            if len(bodies) == 1:
                raise http_error(400, '{"error": "response_format is not supported"}')
            return reply('{"ok": true}')
        result = openai_compat.generate(PROMPT, model='m', key='k', opener=opener,
                                        config={'responseMimeType': 'application/json'})
        self.assertEqual(result['text'], '{"ok": true}')
        self.assertNotIn('response_format', bodies[1])

    def test_empty_reply_with_format_is_resent_without_format(self):
        bodies = []

        def opener(request, timeout):
            bodies.append(json.loads(request.data))
            return reply('' if len(bodies) < 3 else '{"page": 1}')       # gpt-oss: 형식을 걸면 빈 답
        result = openai_compat.generate(PROMPT, model='m', key='k', opener=opener,
                                        config={'responseMimeType': 'application/json', 'responseSchema': {'type': 'OBJECT'}})
        self.assertEqual(result['text'], '{"page": 1}')
        self.assertEqual([b.get('response_format', {}).get('type') for b in bodies], ['json_schema', 'json_object', None])

    def test_model_without_permission_falls_back_and_is_skipped_for_a_while(self):
        models = []
        now = [1000.0]

        def opener(request, timeout):
            model = json.loads(request.data)['model']
            models.append(model)
            if model == 'qwen3-next-80b':
                raise http_error(403, '{"detail": {"error": "model_not_on_key"}}')
            return reply('ok')
        openai_compat._blocked.clear()
        call = lambda: openai_compat.generate(PROMPT, model='qwen3-next-80b,gpt-oss-120b', key='k', opener=opener,
                                              clock=lambda: now[0])
        self.assertEqual(call()['model'], 'gpt-oss-120b')
        call()
        self.assertEqual(models, ['qwen3-next-80b', 'gpt-oss-120b', 'gpt-oss-120b'])   # 10분 동안 건너뜀
        now[0] += openai_compat.BLOCK_SECONDS + 1
        call()
        self.assertEqual(models[-2:], ['qwen3-next-80b', 'gpt-oss-120b'])               # 권한이 생겼는지 다시 확인
        openai_compat._blocked.clear()
        only = []
        no_permission = lambda request, timeout: (only.append(1), (_ for _ in ()).throw(
            http_error(403, '{"detail": {"error": "model_not_on_key"}}')))[1]
        for _ in range(2):
            with self.assertRaises(GeminiError) as caught:
                openai_compat.generate(PROMPT, model='qwen3-next-80b', key='k', opener=no_permission, clock=lambda: now[0])
            self.assertEqual(caught.exception.kind, 'model_not_allowed')
        self.assertEqual(len(only), 1)                  # 막힌 모델은 다시 부르지 않고 바로 다음(Gemini)으로
        openai_compat._blocked.clear()

    def test_short_429_waits_once_then_reports_quota(self):
        waits = []
        calls = []

        def opener(request, timeout):
            calls.append(1)
            raise http_error(429, 'busy', {'Retry-After': '4'})
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, key='k', opener=opener, sleep=waits.append, retries=1)
        self.assertEqual((len(calls), waits), (2, [4]))
        self.assertEqual(caught.exception.status, 429)
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, key='k', opener=lambda r, timeout: (_ for _ in ()).throw(http_error(401)))
        self.assertIn('HASA_API_KEY', caught.exception.message)

    def test_read_timeout_becomes_a_handled_error(self):
        """읽기 시간 초과는 URLError가 아니라 TimeoutError라서 예전에는 룬 추천 작업을 그대로 깨뜨렸다."""
        from rag import gemini

        def slow(request, timeout):
            raise TimeoutError('The read operation timed out')
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, model='m', key='k', opener=slow)
        self.assertIn('TimeoutError', caught.exception.message)
        with self.assertRaises(GeminiError):
            gemini.generate(PROMPT, key='k', opener=slow, retries=0)

    def test_missing_key_is_a_clear_error(self):
        with patch.dict(os.environ, {'HASA_API_KEY': ''}):
            with self.assertRaises(GeminiError) as caught:
                openai_compat.generate(PROMPT, opener=lambda r, timeout: reply('x'))
        self.assertIn('HASA_API_KEY', caught.exception.message)


class ProviderSwitchTests(unittest.TestCase):
    def test_env_picks_provider_key_and_model(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': '', 'GEMINI_API_KEY': 'g', 'HASA_API_KEY': ''}):
            self.assertEqual((llm.provider(), llm.key_env(), llm.has_key()), ('gemini', 'GEMINI_API_KEY', True))
        with patch.dict(os.environ, {'LLM_PROVIDER': 'HASA', 'HASA_API_KEY': '', 'HASA_MODEL': ''}):
            self.assertEqual((llm.provider(), llm.key_env(), llm.has_key()), ('hasa', 'HASA_API_KEY', False))
            self.assertEqual(llm.default_model(), 'qwen3-next-80b')                  # Qwen3 Next가 1순위
            with patch('rag.openai_compat.generate', return_value={'text': 'ok'}) as call:
                llm.generate(PROMPT, retries=0)
            self.assertEqual(call.call_args.kwargs['model'], 'qwen3-next-80b')

    def test_server_uses_hasa_when_configured(self):
        from server.config import Settings
        with patch.dict(os.environ, {'RIOT_API_KEY': 'r', 'LLM_PROVIDER': 'hasa', 'HASA_API_KEY': 'h', 'GEMINI_API_KEY': ''}):
            settings = Settings.from_env()
        self.assertEqual((settings.llm_provider, settings.ai_key, settings.hasa_model),
                         ('hasa', 'h', 'qwen3-next-80b'))
        try:
            from server.app import gemini_generator
        except ImportError:
            self.skipTest('fastapi not installed')
        with patch('rag.openai_compat.generate', return_value={'text': 'ok'}) as call:
            gemini_generator(settings)(PROMPT, config={'temperature': 0})
        self.assertEqual(call.call_args.kwargs['key'], 'h')
        both = settings.__class__(**dict(settings.__dict__, gemini_api_key='g'))
        with patch('rag.openai_compat.generate', side_effect=GeminiError('권한 없음', kind='model_not_allowed')), \
             patch('rag.gemini.generate', return_value={'text': 'gemini'}) as gem:
            result = gemini_generator(both)(PROMPT)
        self.assertEqual((result['text'], result['fallback'], gem.call_args.kwargs['key']), ('gemini', True, 'g'))

    def test_desktop_falls_back_to_gemini_only_when_gemini_key_exists(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'hasa', 'HASA_API_KEY': 'h', 'GEMINI_API_KEY': 'g', 'HASA_MODEL': ''}), \
             patch('rag.openai_compat.generate', side_effect=GeminiError('혼잡', status=503)), \
             patch('rag.gemini.generate', return_value={'text': 'gemini'}):
            self.assertTrue(llm.generate(PROMPT)['fallback'])
        with patch.dict(os.environ, {'LLM_PROVIDER': 'hasa', 'HASA_API_KEY': 'h', 'GEMINI_API_KEY': ''}), \
             patch('rag.openai_compat.generate', side_effect=GeminiError('혼잡', status=503)):
            with self.assertRaises(GeminiError):
                llm.generate(PROMPT)


class NameResolutionTests(unittest.TestCase):
    """스키마 없이 답한 모델(gpt-oss)이 ID 대신 이름을 써도 같은 룬·아이템이면 받는다."""

    def test_rune_names_become_ids_but_unknown_runes_still_fail(self):
        from knowledge.runes import resolve_names, validate_page
        from game_phases.before_game.runes import rune_reasons
        trees = {8100: {'id': 8100, 'name': '지배', 'slots': [[{'id': 8112, 'name': '감전'}], [{'id': 8126, 'name': '비열한 한 방'}],
                                                             [{'id': 8137, 'name': '육감'}], [{'id': 8105, 'name': '끈질긴 사냥꾼'}]]},
                 8200: {'id': 8200, 'name': '마법', 'slots': [[{'id': 8214, 'name': '콩콩이 소환'}], [{'id': 8226, 'name': '마나순환 팔찌'}],
                                                             [{'id': 8233, 'name': '절대 집중'}], [{'id': 8237, 'name': '주문 작열'}]]}}
        answer = {'primary_style': '지배', 'keystone': '감전', 'primary': ['비열한 한 방', '육감', '끈질긴 사냥꾼'],
                  'secondary_style': '마법', 'secondary': ['마나순환 팔찌', '8233'], 'shards': ['적응형 능력치', '이동 속도', '체력']}
        page, errors = validate_page(resolve_names(answer, trees), trees)
        self.assertEqual(errors, [])
        self.assertEqual((page['keystone'], page['secondary'], page['shards']), (8112, [8226, 8233], [5008, 5010, 5011]))
        bad, errors = validate_page(resolve_names(dict(answer, keystone='정복자'), trees), trees)
        self.assertIsNone(bad)                                            # 이번 패치 목록에 없는 이름은 그대로 거절
        names = {8112: '감전', 8126: '비열한 한 방'}
        self.assertEqual(rune_reasons(['감전은 3번 적중 시 추가 피해', {'rune': '비열한 한 방', 'reason': '고정 피해'},
                                       '관계없는 문장'], names),
                         [{'rune': '감전', 'reason': '감전은 3번 적중 시 추가 피해'}, {'rune': '비열한 한 방', 'reason': '고정 피해'}])

    def test_item_names_and_digit_strings_are_accepted_from_candidates_only(self):
        from game_phases.in_game.items import validate
        pool = [{'item_id': i, 'name': n, 'price': 3000, 'remaining_cost': 3000, 'role': '공격'}
                for i, n in ((3089, '라바돈의 죽음모자'), (3157, '존야의 모래시계'), (3065, '정령의 형상'))]
        options, errors = validate({'options': [{'item_id': '라바돈의 죽음모자', 'reason': 'a'}, {'item_id': '3157', 'reason': 'b'},
                                                {'name': '정령의 형상', 'reason': 'c'}]}, pool)
        self.assertEqual(([o['item_id'] for o in options], errors), ([3089, 3157, 3065], []))
        options, errors = validate({'options': [{'item_id': '무한의 대검'}, {'item_id': 3157}, {'item_id': 3065}]}, pool)
        self.assertIsNone(options)                                       # 후보에 없는 이름은 거절


if __name__ == '__main__':
    unittest.main()
