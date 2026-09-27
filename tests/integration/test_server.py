"""RiftFlow API server (phase 1) and the desktop app's server mode.

fastapi가 없으면(서버 추가 설치를 안 한 팀원) 건너뛴다: pip install -e ".[server]"
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_SERVER = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
PUUID = "p" * 40
OPPONENT = "o" * 40


def detail(match_id, start, champion="Leblanc", win=True):
    return {"metadata": {"matchId": match_id},
            "info": {"gameMode": "CLASSIC", "gameStartTimestamp": start, "gameDuration": 1800,
                     "participants": [
                         {"puuid": PUUID, "teamId": 100, "teamPosition": "MIDDLE", "championName": champion,
                          "win": win, "kills": 7, "deaths": 2, "assists": 5, "totalMinionsKilled": 180,
                          "perks": {"styles": [{"style": 8100, "selections": [{"perk": 8112}]}]}},
                         {"puuid": OPPONENT, "teamId": 200, "teamPosition": "MIDDLE", "championName": "Zed"}]}}


class FakeRiot:
    """라이엇 대역. 모든 요청을 기록해 캐시가 실제로 호출을 줄이는지 확인한다."""

    def __init__(self):
        self.calls = []
        self.ids = ["KR_2", "KR_1"]
        self.details = {"KR_1": detail("KR_1", 1_000_000), "KR_2": detail("KR_2", 2_000_000, win=False)}
        self.fail_with = []

    def _record(self, routing, path, params):
        self.calls.append((routing, path))
        if self.fail_with:
            raise self.fail_with.pop(0)

    def get_region(self, path, params=None):
        self._record("region", path, params)
        if path.startswith("/riot/account/v1/accounts/by-riot-id/"):
            name = path.rsplit("/", 2)[-2]
            return None if name == "nobody" else {"puuid": PUUID, "gameName": "Faker", "tagLine": "KR1"}
        if path.endswith("/ids"):
            return list(self.ids)
        return self.details.get(path.rsplit("/", 1)[-1])

    def get_platform(self, path, params=None):
        self._record("platform", path, params)
        if "/summoner/" in path:
            return {"summonerLevel": 512, "profileIconId": 4568}
        if "/league/" in path:
            return []
        return None


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
class ServerTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        from server.riot_data import RateLimiter, RiotGateway
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1_800_000_000.0]
        self.riot = FakeRiot()
        self.sleeps = []
        self.settings = Settings(riot_api_key="test", db_path=str(Path(self.temp.name) / "server.db"),
                                 riot_limits=((100, 1.0), (1000, 120.0)), device_daily_requests=50)
        limits = self.settings.riot_limits
        self.mono = [0.0]
        def limiter_sleep(seconds):          # 실제로 기다리지 않고 가짜 시계만 넘긴다
            self.mono[0] += seconds
        make = lambda: RateLimiter(limits, clock=lambda: self.mono[0], sleep=limiter_sleep)
        self.gateway = RiotGateway(self.settings, client=self.riot, sleep=self.sleeps.append,
                                   limiters={"region": make(), "platform": make()})
        self.app = create_app(self.settings, gateway=self.gateway, clock=lambda: self.now[0])
        self.http = TestClient(self.app)
        token = self.http.post("/v1/devices").json()["token"]
        self.auth = {"Authorization": "Bearer " + token}

    def get(self, path, **kwargs):
        return self.http.get(path, headers=self.auth, **kwargs)

    def test_device_token_is_required(self):
        self.assertEqual(self.http.get("/v1/health").json(), {"status": "ok"})
        response = self.http.get("/v1/riot/rank/" + PUUID)
        self.assertEqual(response.status_code, 401)
        self.assertIn("기기 인증", response.json()["error"]["message"])

    def test_account_is_cached_and_missing_player_is_404(self):
        first = self.get("/v1/riot/account/Faker/KR1").json()
        self.assertEqual(first, {"puuid": PUUID, "riot_id": "Faker#KR1", "summoner_level": 512, "profile_icon_id": 4568})
        calls = len(self.riot.calls)
        self.assertEqual(self.get("/v1/riot/account/faker/kr1").json(), first)   # 대소문자만 다른 같은 계정
        self.assertEqual(len(self.riot.calls), calls)
        missing = self.get("/v1/riot/account/nobody/KR1")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "player_not_found")

    def test_refresh_after_a_game_fetches_only_the_new_match(self):
        body = self.get("/v1/riot/matches/" + PUUID).json()
        self.assertEqual([m["match_id"] for m in body["matches"]], ["KR_2", "KR_1"])
        self.assertEqual(body["observations"][0]["opponent"], "Zed")
        self.assertEqual(len(self.riot.calls), 3)            # 경기 ID 목록 1 + 경기 상세 2
        self.get("/v1/riot/matches/" + PUUID)
        self.assertEqual(len(self.riot.calls), 3)            # 1분 안에는 라이엇을 부르지 않음
        self.now[0] += 61
        self.riot.ids.insert(0, "KR_3")
        self.riot.details["KR_3"] = detail("KR_3", 3_000_000)
        body = self.get("/v1/riot/matches/" + PUUID).json()
        self.assertEqual(len(body["matches"]), 3)
        self.assertEqual(self.riot.calls[3:], [("region", "/lol/match/v5/matches/by-puuid/%s/ids" % PUUID),
                                               ("region", "/lol/match/v5/matches/KR_3")])

    def test_unranked_is_null_and_cached(self):
        self.assertIsNone(self.get("/v1/riot/rank/" + PUUID).json())
        self.get("/v1/riot/rank/" + PUUID)
        self.assertEqual([c for c in self.riot.calls if "/league/" in c[1]].__len__(), 1)

    def test_bad_ids_are_rejected_without_calling_riot(self):
        self.assertEqual(self.get("/v1/riot/rank/short").status_code, 400)
        self.assertEqual(self.get("/v1/riot/matches/detail/../../etc").status_code, 404)
        self.assertEqual(self.get("/v1/riot/matches/detail/not-a-match").status_code, 400)
        self.assertEqual(self.riot.calls, [])

    def test_daily_limit_per_device(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        settings = self.settings.__class__(**{**self.settings.__dict__, "device_daily_requests": 2,
                                              "db_path": str(Path(self.temp.name) / "limit.db")})
        http = TestClient(create_app(settings, gateway=self.gateway, clock=lambda: self.now[0]))
        auth = {"Authorization": "Bearer " + http.post("/v1/devices").json()["token"]}
        for _ in range(2):
            self.assertEqual(http.get("/v1/riot/rank/" + PUUID, headers=auth).status_code, 200)
        blocked = http.get("/v1/riot/rank/" + PUUID, headers=auth)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)

    def test_riot_429_is_retried_or_reported_with_retry_after(self):
        from contracts.riot import RateLimitExceeded
        self.riot.fail_with = [RateLimitExceeded(2)]
        self.assertEqual(self.get("/v1/riot/rank/" + PUUID).status_code, 200)
        self.assertEqual(self.sleeps, [2])
        self.now[0] += 400
        self.riot.fail_with = [RateLimitExceeded(30)]
        busy = self.get("/v1/riot/rank/" + PUUID)
        self.assertEqual(busy.status_code, 503)
        self.assertEqual(busy.headers["Retry-After"], "30")

    def test_device_registration_is_limited_per_ip(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        settings = self.settings.__class__(**{**self.settings.__dict__, "device_creations_per_hour": 1,
                                              "db_path": str(Path(self.temp.name) / "ip.db")})
        http = TestClient(create_app(settings, gateway=self.gateway, clock=lambda: self.now[0]))
        self.assertEqual(http.post("/v1/devices").status_code, 200)
        self.assertEqual(http.post("/v1/devices").status_code, 429)

    def test_desktop_server_mode_end_to_end(self):
        """앱의 riot 함수들이 라이엇 키 없이 서버를 거쳐 같은 데이터 형식을 돌려준다."""
        from api_client import ServerClient
        from contracts.riot import MatchSummary, PlayerIdentity, PlayerNotFound
        from riot import service
        token_path = Path(self.temp.name) / "device_token"
        client = ServerClient("http://testserver", token_path=token_path, session=self.http, sleep=self.sleeps.append)
        with patch.dict(os.environ, {"RIFTFLOW_SERVER_URL": "http://testserver", "RIOT_API_KEY": ""}), \
             patch("api_client.shared_client", return_value=client):
            player = service.get_player("Faker#KR1")
            self.assertEqual(player, PlayerIdentity(PUUID, "Faker#KR1", 512, 4568))
            history = service.get_recent_history(player.puuid, 20)
            self.assertIsInstance(history["summaries"][0], MatchSummary)
            self.assertEqual(history["details"], [])
            self.assertEqual(history["observations"][1]["match_id"], "KR_1")
            self.assertIsNone(service.get_solo_rank(player.puuid))
            self.assertEqual(service.get_match_detail("KR_1")["metadata"]["matchId"], "KR_1")
            with self.assertRaises(PlayerNotFound):
                service.get_player("nobody#KR1")
            token_path.write_text("stale-token", encoding="utf-8")      # 서버가 모르는 토큰 → 다시 등록
            client._token = None
            self.assertEqual(service.get_player("Faker#KR1").puuid, PUUID)
            self.assertNotEqual(token_path.read_text(encoding="utf-8"), "stale-token")


class RateLimiterTests(unittest.TestCase):
    @unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
    def test_waits_for_the_window_and_gives_up_when_too_long(self):
        from server.riot_data import RateLimiter, RiotBusy
        clock = [0.0]
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds
        limiter = RateLimiter(((2, 1.0),), clock=lambda: clock[0], sleep=sleep)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()                      # 1초 창이 비워질 때까지 기다림
        self.assertAlmostEqual(sum(waits), 1.0)
        limiter.block(60)
        with self.assertRaises(RiotBusy) as busy:
            limiter.acquire(max_wait=5)
        self.assertEqual(busy.exception.retry_after, 60)


class ObservationTests(unittest.TestCase):
    def test_observation_matches_saved_personal_record(self):
        from knowledge.before_game import personal_context, save_observations
        from riot.service import matchup_observation
        observation = matchup_observation(detail("KR_1", 1), PUUID)
        self.assertEqual((observation["champion"], observation["opponent"], observation["lane"]), ("Leblanc", "Zed", "MIDDLE"))
        aram = detail("KR_9", 1)
        aram["info"]["gameMode"] = "ARAM"
        self.assertIsNone(matchup_observation(aram, PUUID))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "personal.db"
            save_observations(path, PUUID, [observation, observation])
            record = personal_context(path, PUUID, "Leblanc", "Zed", "middle")
        self.assertEqual((record["matchup_games"], record["matchup_wins"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
