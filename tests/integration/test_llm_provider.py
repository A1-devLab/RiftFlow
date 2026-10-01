"""AI provider: HASA (OpenAI-compatible) by default with several keys; Gemini only on request. No network or real key."""
import io
import json
import os
import time
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


def auth(request):
    return request.get_header('Authorization').split()[-1]


class OpenAICompatTests(unittest.TestCase):
    def setUp(self):
        openai_compat.reset_state()
        self.addCleanup(openai_compat.reset_state)

    def test_request_shape_auth_header_and_json_schema(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return reply('<think>생각</think>{"a": 1}')
        result = openai_compat.generate(PROMPT, model='nemotron-super-120b', key='sk-dev-test', opener=opener,
                                        config={'responseMimeType': 'application/json', 'responseSchema': {
                                            'type': 'OBJECT', 'properties': {'ids': {'type': 'ARRAY', 'items': {'type': 'INTEGER'}}},
                                            'required': ['ids'], 'propertyOrdering': ['ids']}},
                                        base_url='https://example.test/v1')
        self.assertEqual(result['text'], '{"a": 1}')                     # 생각 태그는 지운다
        request = sent[0]
        self.assertEqual(request.full_url, 'https://example.test/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer sk-dev-test')
        body = json.loads(request.data)
        self.assertEqual(body['model'], 'nemotron-super-120b')
        self.assertEqual(body['response_format']['json_schema']['schema'],
                         {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'integer'}}},
                          'required': ['ids']})
        self.assertNotIn('sk-dev-test', json.dumps(body))                 # 키는 헤더에만

    def test_format_is_lowered_step_by_step(self):
        bodies = []

        def rejects(request, timeout):
            bodies.append(json.loads(request.data))
            if len(bodies) == 1:
                raise http_error(400, '{"error": "response_format is not supported"}')
            return reply('{"ok": true}')
        openai_compat.generate(PROMPT, model='m', key='k', opener=rejects, config={'responseMimeType': 'application/json'})
        self.assertNotIn('response_format', bodies[1])
        bodies.clear()

        def empty(request, timeout):
            bodies.append(json.loads(request.data))
            return reply('' if len(bodies) < 3 else '{"page": 1}')       # gpt-oss: 형식을 걸면 빈 답
        result = openai_compat.generate(PROMPT, model='m', key='k', opener=empty,
                                        config={'responseMimeType': 'application/json', 'responseSchema': {'type': 'OBJECT'}})
        self.assertEqual(result['text'], '{"page": 1}')
        self.assertEqual([b.get('response_format', {}).get('type') for b in bodies], ['json_schema', 'json_object', None])

    def test_two_keys_share_the_load_and_a_limited_key_hands_over(self):
        used = []

        def opener(request, timeout):
            used.append(auth(request))
            if auth(request) == 'mine' and used.count('mine') == 2:
                raise http_error(429, 'quota_txn_daily')
            return reply('ok')
        for _ in range(3):
            openai_compat.generate(PROMPT, model='m', key='mine,team', opener=opener)
        # 1번째: 내 키, 2번째: 내 키가 하루 한도 → 같은 요청을 팀원 키로 바로 다시, 3번째: 쉬는 내 키를 건너뛰고 팀원 키
        self.assertEqual(used, ['mine', 'mine', 'team', 'team'])

    def test_busy_key_is_skipped_for_a_free_one(self):
        import threading
        used, release = [], threading.Event()

        def opener(request, timeout):
            used.append(auth(request))
            if auth(request) == 'mine':
                release.wait(5)                  # 내 키로 보낸 요청이 오래 걸리는 중
            return reply('ok')
        worker = threading.Thread(target=lambda: openai_compat.generate(PROMPT, model='m', key='mine,team', opener=opener))
        worker.start()
        while not used:
            time.sleep(0.01)
        openai_compat.generate(PROMPT, model='m', key='mine,team', opener=opener)
        release.set()
        worker.join(5)
        self.assertEqual(used, ['mine', 'team'])  # 동시 1건 한도라 비어 있는 팀원 키로 보낸다

    def test_invalid_key_is_rested_to_avoid_hasa_strikes(self):
        calls = []

        def opener(request, timeout):
            calls.append(auth(request))
            raise http_error(403, '{"error": "security_policy_blocked", "violation_code": "invalid_api_key"}')
        for _ in range(3):
            with self.assertRaises(GeminiError) as caught:
                openai_compat.generate(PROMPT, model='m', key='old', opener=opener)
        self.assertEqual(calls, ['old'])        # 경고가 쌓이지 않게 30분 동안 다시 보내지 않는다
        self.assertEqual(caught.exception.kind, 'invalid_key')

    def test_model_permission_is_per_key_and_rechecked_later(self):
        models, now = [], [1000.0]

        def opener(request, timeout):
            model = json.loads(request.data)['model']
            models.append(model)
            if model == 'qwen3-next-80b':
                raise http_error(403, '{"detail": {"error": "model_not_on_key"}}')
            return reply('ok')
        call = lambda: openai_compat.generate(PROMPT, model='qwen3-next-80b,nemotron-super-120b', key='k',
                                              opener=opener, clock=lambda: now[0])
        self.assertEqual(call()['model'], 'nemotron-super-120b')
        call()
        self.assertEqual(models, ['qwen3-next-80b', 'nemotron-super-120b', 'nemotron-super-120b'])
        now[0] += openai_compat.MODEL_BLOCK + 1
        call()
        self.assertEqual(models[-2:], ['qwen3-next-80b', 'nemotron-super-120b'])   # 권한이 생겼는지 다시 확인

    def test_quota_rest_is_reported_as_busy_not_as_missing_model(self):
        def opener(request, timeout):
            raise http_error(429, 'daily limit')
        with self.assertRaises(GeminiError):
            openai_compat.generate(PROMPT, model='m', key='k', opener=opener)
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, model='m', key='k', opener=opener)
        self.assertEqual(caught.exception.kind, 'quota')
        self.assertNotIn('쓸 수 없습니다', caught.exception.message)    # 예전: '쓸 수 있는 모델이 없습니다'

    def test_rpm_and_server_errors(self):
        now = time.time()
        openai_compat._sent[openai_compat.key_id('k')] = [now] * openai_compat.RPM_LIMIT
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, model='m', key='k', opener=lambda r, timeout: reply('ok'), slot_wait=0.05)
        self.assertEqual(caught.exception.kind, 'busy')                   # 분당 한도를 넘기지 않는다
        openai_compat.reset_state()
        waits, calls = [], []

        def flaky(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise http_error(502, 'bad gateway', {'Retry-After': '2'})
            return reply('ok')
        self.assertEqual(openai_compat.generate(PROMPT, model='m', key='k', opener=flaky, sleep=waits.append)['text'], 'ok')
        self.assertEqual(waits, [2])

    def test_read_timeout_becomes_a_handled_error(self):
        from rag import gemini

        def slow(request, timeout):
            raise TimeoutError('The read operation timed out')
        with self.assertRaises(GeminiError) as caught:
            openai_compat.generate(PROMPT, model='m', key='k', opener=slow)
        self.assertEqual(caught.exception.kind, 'timeout')
        with self.assertRaises(GeminiError):
            gemini.generate(PROMPT, key='k', opener=slow, retries=0)

    def test_missing_key_is_a_clear_error(self):
        with patch.dict(os.environ, {'HASA_API_KEY': ''}):
            with self.assertRaises(GeminiError) as caught:
                openai_compat.generate(PROMPT, opener=lambda r, timeout: reply('x'))
        self.assertIn('HASA_API_KEY', caught.exception.message)


class ProviderSwitchTests(unittest.TestCase):
    def test_hasa_is_the_default_and_gemini_needs_explicit_fallback(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': '', 'HASA_API_KEY': 'h', 'HASA_MODEL': '', 'LLM_FALLBACK': '',
                                     'GEMINI_API_KEY': 'g'}):
            self.assertEqual((llm.provider(), llm.key_env(), llm.default_model()),
                             ('hasa', 'HASA_API_KEY', 'nemotron-super-120b'))
            with patch('rag.openai_compat.generate', side_effect=GeminiError('혼잡', status=503)), \
                 patch('rag.gemini.generate') as gem:
                with self.assertRaises(GeminiError):
                    llm.generate(PROMPT)
            gem.assert_not_called()                                       # Gemini 키가 있어도 넘기지 않는다
        with patch.dict(os.environ, {'LLM_PROVIDER': 'hasa', 'HASA_API_KEY': 'h', 'LLM_FALLBACK': 'gemini',
                                     'GEMINI_API_KEY': 'g'}), \
             patch('rag.openai_compat.generate', side_effect=GeminiError('혼잡', status=503)), \
             patch('rag.gemini.generate', return_value={'text': 'gemini'}):
            self.assertTrue(llm.generate(PROMPT)['fallback'])

    def test_server_uses_hasa_only_with_all_keys(self):
        from server.config import Settings
        with patch.dict(os.environ, {'RIOT_API_KEY': 'r', 'LLM_PROVIDER': '', 'HASA_API_KEY': 'mine,team',
                                     'HASA_MODEL': '', 'LLM_FALLBACK': '', 'GEMINI_API_KEY': 'g'}):
            settings = Settings.from_env()
        self.assertEqual((settings.llm_provider, settings.hasa_model, settings.llm_fallback),
                         ('hasa', 'nemotron-super-120b', ''))
        try:
            from server.app import gemini_generator
        except ImportError:
            self.skipTest('fastapi not installed')
        with patch('rag.openai_compat.generate', side_effect=GeminiError('혼잡', status=503)) as hasa, \
             patch('rag.gemini.generate') as gem:
            with self.assertRaises(GeminiError):
                gemini_generator(settings)(PROMPT)
        self.assertEqual(hasa.call_args.kwargs['key'], 'mine,team')
        self.assertEqual(hasa.call_args.kwargs['slot_wait'], llm.NO_FALLBACK_SLOT_WAIT)   # 대체가 없으니 차례를 기다린다
        gem.assert_not_called()


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

    def test_reasons_fall_back_to_requested_order(self):
        from game_phases.before_game.runes import rune_reasons
        names = {8112: '감전', 8126: '비열한 한 방'}
        self.assertEqual(rune_reasons([{'rune_id': '8112', 'reason': 'a'}], names), [{'rune': '감전', 'reason': 'a'}])
        english = [{'rune': 'Electrocute', 'reason': '연계 피해'}, {'rune': 'Cheap Shot', 'reason': '고정 피해'}]
        self.assertEqual([r['rune'] for r in rune_reasons(english, names)], ['감전', '비열한 한 방'])

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
