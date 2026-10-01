"""Server phase 2: AI endpoints, shared rune cache, AI quota, and the desktop's server-mode AI calls."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from game_phases import payloads

HAS_SERVER = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
TREES = [
    {'id': 8000, 'key': 'Precision', 'name': '정밀', 'icon': 'p.png', 'slots': [
        {'runes': [{'id': 8005, 'name': '집중 공격'}, {'id': 8010, 'name': '정복자'}]},
        {'runes': [{'id': 9111, 'name': '승전보'}]}, {'runes': [{'id': 9104, 'name': '전설: 민첩함'}]},
        {'runes': [{'id': 8014, 'name': '최후의 일격'}, {'id': 8017, 'name': '체력차 극복'}]}]},
    {'id': 8100, 'key': 'Domination', 'name': '지배', 'icon': 'd.png', 'slots': [
        {'runes': [{'id': 8112, 'name': '감전'}]}, {'runes': [{'id': 8126, 'name': '비열한 한 방'}]},
        {'runes': [{'id': 8136, 'name': '좀비 와드'}]}, {'runes': [{'id': 8135, 'name': '보물 사냥꾼'}]}]},
]
PAGE = {'primary_style': 8100, 'keystone': 8112, 'primary': [8126, 8136, 8135], 'secondary_style': 8000,
        'secondary': [9111, 8014], 'shards': [5008, 5008, 5011], 'summary': '요약',
        'reasons': [{'rune_id': 8112, 'reason': '이유'}]}
PICK_VIEW = {'game_mode': 'CLASSIC', 'mode_name': '소환사의 협곡',
             'mine': {'champion': '아리', 'position': 'middle', 'locked': True, 'selected': True, 'puuid': 'secret-puuid'},
             'allies': [{'champion': '아리', 'position': 'middle', 'locked': True}],
             'enemies': [{'champion': '럭스', 'position': 'middle', 'locked': True}], 'ally_bans': [], 'enemy_bans': []}


def knowledge_db(folder):
    from knowledge.collector import connect, rune_rows, save
    path = Path(folder) / 'knowledge.db'
    with closing(connect(path)) as db, db:
        for rune_id, entity in rune_rows(TREES):
            save(db, 'rune', '16.19.1', rune_id, entity['name'], json.dumps(entity, ensure_ascii=False), 'https://x')
        for key, id_, name in ((103, 'Ahri', '아리'), (99, 'Lux', '럭스')):
            save(db, 'champion', '16.19.1', id_, name, json.dumps(
                {'key': str(key), 'id': id_, 'name': name, 'blurb': name + ' 스킬', 'tags': ['Mage'],
                 'info': {'attack': 2, 'magic': 9}}, ensure_ascii=False), 'https://x')
        save(db, 'item', '16.19.1', '3157', '존야의 모래시계', json.dumps(
            {'name': '존야의 모래시계', 'description': '주문력 방어력', 'gold': {'total': 3250}, 'maps': {'11': True}},
            ensure_ascii=False), 'https://x')
    return path


class PayloadTests(unittest.TestCase):
    def test_personal_fields_are_dropped_and_sizes_capped(self):
        view = payloads.pick_view(PICK_VIEW)
        self.assertNotIn('puuid', view['mine'])
        live = payloads.live_view({'in_game': True, 'clock': '10:00', 'me': {'name': 'Hide on bush', 'champion': 'Ahri',
                                   'items': [{'id': 3157, 'slot': 0, 'name': '존야'}] * 10},
                                   'allies': [{'name': f'p{i}', 'champion': 'X'} for i in range(9)], 'enemies': []})
        self.assertNotIn('name', live['me'])
        self.assertEqual(len(live['me']['items']), 7)
        self.assertEqual(len(live['allies']), 5)
        self.assertEqual(payloads.user_requests(['a'] * 9 + ['x' * 5000])[-1], 'x' * 1000)
        self.assertEqual(len(payloads.user_requests(['a'] * 9)), 5)


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
class ServerAiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(riot_api_key='test', db_path=str(Path(self.temp.name) / 'server.db'),
                                 knowledge_db_path=str(knowledge_db(self.temp.name)), device_daily_ai=5)
        self.generate = Mock(return_value={'text': json.dumps(PAGE, ensure_ascii=False)})
        self.app = create_app(self.settings, gateway=Mock(), generate=self.generate)
        self.http = TestClient(self.app)
        self.auth = self.token()

    def token(self):
        return {'Authorization': 'Bearer ' + self.http.post('/v1/devices').json()['token']}

    def post(self, path, body, auth=None):
        return self.http.post(path, json=body, headers=auth or self.auth)

    def test_auto_rune_recommendation_is_shared_between_devices(self):
        body = {'champion': '아리', 'opponent': '럭스', 'view': PICK_VIEW,
                'recent_pages': [{'won': True, 'opponent': 'Lux', 'page': [{'style': 8000, 'perks': [8010]}]}]}
        first = self.post('/v1/runes/recommend', body).json()
        self.assertEqual(first['page']['keystone']['name'], '감전')
        self.assertFalse(first['cached'])
        prompt = json.loads(self.generate.call_args.args[0]['user'])
        self.assertEqual(prompt['my_recent_pages'], [])          # 공유 캐시용 추천에는 개인 기록을 넣지 않음
        self.assertNotIn('secret-puuid', self.generate.call_args.args[0]['user'])
        other_device = self.post('/v1/runes/recommend', body, auth=self.token()).json()
        self.assertTrue(other_device['cached'])
        self.assertEqual(self.generate.call_count, 1)

    def test_chat_request_is_personal_and_not_cached(self):
        body = {'champion': '아리', 'opponent': '럭스', 'view': PICK_VIEW, 'user_requests': ['공격적으로 룬 짜줘'],
                'recent_pages': [{'won': True, 'opponent': 'Lux', 'page': [{'style': 8000, 'perks': [8010]}]}]}
        self.post('/v1/runes/recommend', body)
        self.post('/v1/runes/recommend', body)
        self.assertEqual(self.generate.call_count, 2)
        prompt = json.loads(self.generate.call_args.args[0]['user'])
        self.assertEqual(prompt['user_requests'], ['공격적으로 룬 짜줘'])
        self.assertEqual(prompt['my_recent_pages'][0]['page'], [{'tree': '정밀', 'runes': ['정복자']}])

    def test_pick_in_game_and_general_answers(self):
        self.generate.return_value = {'text': '답변입니다'}
        pick = self.post('/v1/coach/pick', {'question': '초반은?', 'champion': '아리', 'opponent': '럭스',
                                             'view': PICK_VIEW, 'observations': {'matchup_games': 3, 'matchup_wins': 2}}).json()
        self.assertEqual(pick['answer'], '답변입니다')
        sent = json.loads(self.generate.call_args.args[0]['user'])
        self.assertEqual(sent['personal_observations']['matchup_games'], 3)
        live = {'in_game': True, 'clock': '12:00', 'perspective_known': True,
                'me': {'name': 'Hide on bush', 'champion': '아리', 'kda': '1/0/0', 'items': []},
                'allies': [], 'enemies': [{'name': 'Enemy', 'champion': '럭스', 'items': []}]}
        self.assertEqual(self.post('/v1/coach/in-game', {'question': '불리해?', 'view': live}).json()['answer'], '답변입니다')
        self.assertNotIn('Hide on bush', self.generate.call_args.args[0]['user'])
        general = self.post('/v1/coach/general', {'question': 'CS 연습은?', 'context': {'rank': None, 'recent_matches': []}}).json()
        self.assertEqual(set(general), {'status', 'message', 'answer', 'generated', 'error'})

    def test_ai_quota_is_separate_from_riot_quota(self):
        self.generate.return_value = {'text': '답'}
        for _ in range(5):
            self.assertEqual(self.post('/v1/coach/general', {'question': '질문'}).status_code, 200)
        blocked = self.post('/v1/coach/general', {'question': '질문'})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()['error']['code'], 'daily_ai_limit')
        from server.db import Database
        db = Database(self.settings.db_path)
        self.assertIsNone(db.one("SELECT riot_requests FROM usage_daily WHERE riot_requests > 0"))
        self.assertEqual(db.one("SELECT requests FROM ai_usage WHERE scope LIKE 'device:%'")["requests"], 5)

    def test_concurrent_requests_cannot_exceed_the_daily_limit(self):
        """예전에는 확인과 증가가 따로라 동시에 10번 보내면 한도 5에서도 10번 다 통과했다."""
        import threading
        import time as clock
        from fastapi.testclient import TestClient
        self.generate.side_effect = lambda prompt, **options: (clock.sleep(0.05), {'text': '답'})[1]
        codes, threads = [], []
        for _ in range(10):
            client = TestClient(self.app)
            threads.append(threading.Thread(target=lambda c=client: codes.append(
                c.post('/v1/coach/general', json={'question': '질문'}, headers=self.auth).status_code)))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertLessEqual(codes.count(200), 5)
        self.assertLessEqual(self.generate.call_count, 5)

    def test_no_model_call_is_not_charged(self):
        """모델을 부르지 않은 답(게임 중이 아님 등)은 한도에서 빼 준다."""
        for _ in range(7):
            self.assertEqual(self.post('/v1/coach/in-game', {'question': '어때?', 'view': {}}).status_code, 200)
        self.generate.assert_not_called()
        self.assertEqual(self.post('/v1/coach/general', {'question': '질문'}).status_code, 200)

    def test_malformed_nested_fields_are_400_free_and_riot_errors_are_502(self):
        bad = self.post('/v1/coach/pick', {'question': 'q', 'champion': '아리', 'view': {'ally_bans': 5, 'enemy_bans': {}}})
        self.assertEqual(bad.status_code, 200)
        bad = self.post('/v1/coach/general', {'question': 'q', 'context': {'recent_matches': {}}})
        self.assertEqual(bad.status_code, 200)
        from contracts.riot import RiotApiError
        from fastapi.testclient import TestClient
        from server.app import create_app
        gateway = Mock()
        gateway.get.side_effect = RiotApiError('API 키가 없거나 유효하지 않습니다.')
        app = create_app(self.settings, gateway=gateway, generate=self.generate)
        http = TestClient(app)
        auth = {'Authorization': 'Bearer ' + http.post('/v1/devices').json()['token']}
        response = http.get('/v1/riot/rank/' + 'a' * 78, headers=auth)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error']['code'], 'riot_unavailable')
        self.assertNotIn('키', response.json()['error']['message'])          # 서버 설정 정보는 사용자에게 보내지 않음

    def test_validation_and_disabled_ai(self):
        self.assertEqual(self.post('/v1/coach/general', {'question': ''}).status_code, 422)
        self.assertEqual(self.post('/v1/runes/recommend', {'champion': '아리', 'user_requests': ['a'] * 6}).status_code, 422)
        from fastapi.testclient import TestClient
        from server.app import create_app
        settings = self.settings.__class__(**{**self.settings.__dict__, 'gemini_api_key': '',
                                              'db_path': str(Path(self.temp.name) / 'noai.db')})
        http = TestClient(create_app(settings, gateway=Mock()))
        auth = {'Authorization': 'Bearer ' + http.post('/v1/devices').json()['token']}
        response = http.post('/v1/coach/general', json={'question': '질문'}, headers=auth)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'ai_unavailable')

    def test_desktop_coach_calls_through_server(self):
        from api_client import ServerClient
        from api_client import coach
        client = ServerClient('http://testserver', token_path=Path(self.temp.name) / 'token', session=self.http)
        result = coach.recommend_runes(client, PICK_VIEW, champion='아리', opponent='럭스', user_requests=[],
                                       recent_pages=[])
        self.assertEqual(result['page']['keystone']['name'], '감전')
        self.generate.return_value = {'text': '서버 답변'}
        self.assertEqual(coach.coach_general(client, 'CS 연습은?', None)['answer'], '서버 답변')
        offline = ServerClient('http://127.0.0.1:9', token_path=Path(self.temp.name) / 'token2')
        failed = coach.coach_in_game(offline, {'in_game': True}, '질문')
        self.assertFalse(failed['generated'])
        self.assertIn('RiftFlow 서버에 연결하지 못했습니다', failed['message'])


if __name__ == "__main__":
    unittest.main()
