"""Riot API access for the server: per-routing rate limiting, 429 handling and caching.

경기 상세는 끝난 경기라 바뀌지 않으므로 한 번 받으면 영구 저장한다.
새로고침 때는 새 경기 ID만 라이엇에 요청하므로, 게임 한 판 뒤 새로고침이 약 24회에서 3회로 줄어든다.
"""
import threading
import time
from collections import deque
from dataclasses import asdict
from urllib.parse import quote

from contracts.riot import RateLimitExceeded
from riot.client import RiotApiClient
from riot.config import RiotConfig
from riot.service import _to_match_summary, matchup_observation

ACCOUNT_TTL = 24 * 3600
RANK_TTL = 5 * 60
MATCH_LIST_TTL = 60
MAX_RIOT_WAIT = 20.0         # 한도 때문에 이보다 오래 기다려야 하면 사용자에게 잠시 뒤 다시 시도하라고 한다


class RiotBusy(Exception):
    """라이엇 한도 때문에 지금은 처리할 수 없음. retry_after초 뒤 다시 시도."""

    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after + 0.999))
        super().__init__(self.retry_after)


class NotFound(Exception):
    pass


class RateLimiter:
    """창(초)마다 허용 요청 수를 지키는 제한기. 라이엇이 429로 기다리라 하면 그 시간까지 막는다."""

    def __init__(self, limits, clock=time.monotonic, sleep=time.sleep):
        self.limits = tuple(limits)
        self.clock, self.sleep = clock, sleep
        self.calls = deque()
        self.blocked_until = 0.0
        self.lock = threading.Lock()

    def _wait_time(self, now):
        longest = max(seconds for _, seconds in self.limits)
        while self.calls and self.calls[0] <= now - longest:
            self.calls.popleft()
        wait = max(0.0, self.blocked_until - now)
        for count, seconds in self.limits:
            recent = [t for t in self.calls if t > now - seconds]
            if len(recent) >= count:
                wait = max(wait, recent[len(recent) - count] + seconds - now)
        return wait

    def acquire(self, max_wait=MAX_RIOT_WAIT):
        waited = 0.0
        while True:
            with self.lock:
                now = self.clock()
                wait = self._wait_time(now)
                if wait <= 0:
                    self.calls.append(now)
                    return
            if waited + wait > max_wait:
                raise RiotBusy(wait)
            step = min(wait, 1.0)
            self.sleep(step)
            waited += step

    def block(self, seconds):
        with self.lock:
            self.blocked_until = max(self.blocked_until, self.clock() + seconds)


class RiotGateway:
    """ASIA(계정·경기)와 KR(소환사·랭크) 라우팅의 한도를 따로 관리하며 라이엇을 부른다."""

    def __init__(self, settings, client=None, limiters=None, sleep=time.sleep):
        self.client = client or RiotApiClient(RiotConfig(settings.riot_api_key, settings.riot_platform,
                                                         settings.riot_region))
        self.limiters = limiters or {"region": RateLimiter(settings.riot_limits),
                                     "platform": RateLimiter(settings.riot_limits)}
        self.sleep = sleep

    def get(self, routing, path, params=None):
        limiter = self.limiters[routing]
        call = self.client.get_region if routing == "region" else self.client.get_platform
        for attempt in range(2):
            limiter.acquire()
            try:
                return call(path, params)
            except RateLimitExceeded as error:
                retry = error.retry_after_seconds or 5.0
                limiter.block(retry)
                if attempt == 0 and retry <= 10:
                    self.sleep(retry)
                    continue
                raise RiotBusy(retry)


class RiotData:
    """앱이 부르는 라이엇 데이터 기능. 결과는 앱의 contracts 형식과 같은 JSON이다."""

    def __init__(self, db, gateway, clock=time.time):
        self.db, self.gateway, self.clock = db, gateway, clock

    def account(self, game_name, tag_line):
        now = self.clock()
        key = "%s#%s" % (game_name.casefold(), tag_line.casefold())
        cached, hit = self.db.cached_json("riot_accounts", "name_key", key, "data", ACCOUNT_TTL, now)
        if hit:
            return cached
        account = self.gateway.get("region", "/riot/account/v1/accounts/by-riot-id/%s/%s"
                                   % (quote(game_name, safe=""), quote(tag_line, safe="")))
        if account is None:
            raise NotFound("player_not_found")
        summoner = self.gateway.get("platform", "/lol/summoner/v4/summoners/by-puuid/%s" % account["puuid"])
        if summoner is None:
            raise NotFound("player_not_found")
        data = {"puuid": account["puuid"], "riot_id": "%s#%s" % (account["gameName"], account["tagLine"]),
                "summoner_level": summoner.get("summonerLevel"), "profile_icon_id": summoner.get("profileIconId")}
        self.db.save_account(key, data, now)
        return data

    def rank(self, puuid):
        now = self.clock()
        cached, hit = self.db.cached_json("league_entries", "puuid", puuid, "data", RANK_TTL, now)
        if hit:
            return cached
        entries = self.gateway.get("platform", "/lol/league/v4/entries/by-puuid/%s" % puuid) or []
        entry = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
        data = None if entry is None else {
            "queue_type": entry["queueType"], "tier": entry["tier"], "division": entry["rank"],
            "league_points": entry["leaguePoints"], "wins": entry["wins"], "losses": entry["losses"]}
        self.db.save_league(puuid, data, now)
        return data

    def match_detail(self, match_id):
        detail = self.db.match(match_id)
        if detail is not None:
            return detail
        detail = self.gateway.get("region", "/lol/match/v5/matches/%s" % quote(match_id, safe=""))
        if not detail or not (detail.get("info") or {}).get("participants"):
            raise NotFound("match_not_found")
        self.db.save_match(match_id, detail, self.clock())
        return detail

    def matches(self, puuid, count):
        now = self.clock()
        match_ids = self.db.match_list(puuid, count, MATCH_LIST_TTL, now)
        if match_ids is None:
            match_ids = self.gateway.get("region", "/lol/match/v5/matches/by-puuid/%s/ids" % puuid,
                                         {"start": 0, "count": count}) or []
            self.db.save_match_list(puuid, count, match_ids, now)
        if not match_ids:
            raise NotFound("match_data_unavailable")
        summaries, observations = [], []
        for match_id in match_ids:
            try:
                detail = self.match_detail(match_id)
            except NotFound:
                continue
            if not any(p.get("puuid") == puuid for p in detail["info"]["participants"]):
                continue
            summaries.append(asdict(_to_match_summary(detail, puuid)))
            observation = matchup_observation(detail, puuid)
            if observation:
                observations.append(observation)
        return {"matches": summaries, "observations": observations}
