"""
src/riot/service.py

docs/interfaces.md에 정의된 riot 모듈의 실제 기능 구현.
API 원본 응답을 여기서 contracts의 공통 형식으로 변환한다.
"""

import os
from typing import List, Optional

from contracts.riot import (
    MatchDataUnavailable,
    MatchSummary,
    PlayerIdentity,
    PlayerNotFound,
    RankInfo,
)

from .client import RiotApiClient
from .config import RiotConfig

_client: Optional[RiotApiClient] = None


def _server():
    """RIFTFLOW_SERVER_URL이 있으면 라이엇 대신 RiftFlow 서버를 쓴다 (배포판에는 라이엇 키가 없다)."""
    url = os.environ.get("RIFTFLOW_SERVER_URL")
    if not url:
        return None
    from api_client import shared_client
    return shared_client(url)


def _get_client() -> RiotApiClient:
    """클라이언트를 지연 생성해서, 모듈을 import하는 시점에는
    RIOT_API_KEY가 없어도 에러가 나지 않게 한다 (실제 호출 시점에만 필요)."""
    global _client
    if _client is None:
        _client = RiotApiClient(RiotConfig.from_env())
    return _client


def get_player(riot_id: str) -> PlayerIdentity:
    """"게임명#태그" 형식의 Riot ID로 소환사 식별 정보를 조회한다.

    Raises:
        PlayerNotFound: 존재하지 않는 Riot ID인 경우
        RateLimitExceeded: API 호출 제한에 걸린 경우
    """
    if "#" not in riot_id:
        raise ValueError('riot_id는 "게임명#태그" 형식이어야 합니다. 예: "홍길동#KR1"')
    game_name, tag_line = riot_id.split("#", 1)

    server = _server()
    if server is not None:
        data = server.get_json(f"/v1/riot/account/{server.quote(game_name)}/{server.quote(tag_line)}")
        if data is None:
            raise PlayerNotFound(riot_id)
        return PlayerIdentity(**data)

    client = _get_client()

    account = client.get_region(
        f"/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    )
    if account is None:
        raise PlayerNotFound(riot_id)

    puuid = account["puuid"]
    summoner = client.get_platform(f"/lol/summoner/v4/summoners/by-puuid/{puuid}")
    if summoner is None:
        raise PlayerNotFound(riot_id)

    return PlayerIdentity(
        puuid=puuid,
        riot_id=f"{account['gameName']}#{account['tagLine']}",
        summoner_level=summoner.get("summonerLevel"),
        profile_icon_id=summoner.get("profileIconId"),
    )


def get_recent_matches(puuid: str, count: int) -> List[MatchSummary]:
    summaries, _ = get_recent_matches_with_details(puuid, count)
    return summaries


def get_recent_history(puuid: str, count: int = 20) -> dict:
    """전적 화면용 묶음: {'summaries': [MatchSummary], 'observations': [개인 상성 기록], 'details': [경기 상세]}.

    서버 모드에서는 경기 상세 원본을 받지 않는다(details는 빈 목록). 상세 통계 창은 get_match_detail로 따로 받는다.
    """
    server = _server()
    if server is not None:
        data = server.get_json(f"/v1/riot/matches/{server.quote(puuid)}", params={"count": count})
        if data is None:
            raise MatchDataUnavailable(puuid)
        return {"summaries": [MatchSummary(**m) for m in data["matches"]],
                "observations": data["observations"], "details": []}
    summaries, details = get_recent_matches_with_details(puuid, count)
    observations = [o for o in (matchup_observation(d, puuid) for d in details) if o]
    return {"summaries": summaries, "observations": observations, "details": details}


def matchup_observation(match_detail: dict, puuid: str) -> Optional[dict]:
    """경기 상세 하나에서 개인 상성 기록 한 줄을 뽑는다. 협곡이 아니거나 본인이 없으면 None.

    맞라인 상대는 같은 포지션의 상대가 정확히 한 명일 때만 적는다 (추정하지 않음).
    서버와 앱이 같은 규칙을 쓰도록 여기 한 곳에 둔다.
    """
    info = match_detail.get("info") or {}
    if info.get("gameMode") != "CLASSIC":
        return None
    participants = info.get("participants") or []
    player = next((p for p in participants if p.get("puuid") == puuid), None)
    if player is None:
        return None
    lane = (player.get("teamPosition") or player.get("individualPosition") or "").upper()
    opponents = [p for p in participants if p.get("teamId") != player.get("teamId")
                 and (p.get("teamPosition") or p.get("individualPosition") or "").upper() == lane]
    styles = (player.get("perks") or {}).get("styles") or []
    page = [{"style": style.get("style"), "perks": [s.get("perk") for s in style.get("selections", [])]}
            for style in styles]
    return {"match_id": (match_detail.get("metadata") or {}).get("matchId"),
            "played_at": info.get("gameStartTimestamp"),
            "champion": player.get("championName"),
            "opponent": opponents[0].get("championName") if lane and len(opponents) == 1 else None,
            "lane": lane, "won": bool(player.get("win")),
            "kills": player.get("kills"), "deaths": player.get("deaths"), "assists": player.get("assists"),
            "rune_page": page or None}


def get_recent_matches_with_details(puuid: str, count: int):
    """Fetch each match once, returning both card summaries and full data for local analysis."""
    client = _get_client()
    match_ids = client.get_region(
        f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
        params={"start": 0, "count": count},
    )
    if not match_ids:
        raise MatchDataUnavailable(puuid)
    summaries, details = [], []
    for match_id in match_ids:
        detail = client.get_region(f"/lol/match/v5/matches/{match_id}")
        if detail is None:
            continue
        summaries.append(_to_match_summary(detail, puuid))
        details.append(detail)
    return summaries, details


def get_solo_rank(puuid: str) -> Optional[RankInfo]:
    """솔로랭크(RANKED_SOLO_5x5) 티어 정보를 조회한다.

    솔로랭크 기록이 없으면(언랭크) None을 반환한다 - 이는 오류가 아니다.

    참고: interfaces.md 표에는 없는 함수라 팀 합의 후 이름/위치를 확정할 것.
    """
    server = _server()
    if server is not None:
        data = server.get_json(f"/v1/riot/rank/{server.quote(puuid)}")
        return RankInfo(**data) if data else None

    client = _get_client()

    entries = client.get_platform(f"/lol/league/v4/entries/by-puuid/{puuid}")
    if not entries:
        return None

    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            return RankInfo(
                queue_type=entry["queueType"],
                tier=entry["tier"],
                division=entry["rank"],
                league_points=entry["leaguePoints"],
                wins=entry["wins"],
                losses=entry["losses"],
            )
    return None


def _to_match_summary(match_detail: dict, puuid: str) -> MatchSummary:
    info = match_detail["info"]
    participant = next(p for p in info["participants"] if p["puuid"] == puuid)

    return MatchSummary(
        match_id=match_detail["metadata"]["matchId"],
        played_at_epoch=info["gameStartTimestamp"] // 1000,
        game_duration_seconds=info["gameDuration"],
        game_mode=info["gameMode"],
        champion_name=participant["championName"],
        win=participant["win"],
        kills=participant["kills"],
        deaths=participant["deaths"],
        assists=participant["assists"],
        cs=participant.get("totalMinionsKilled", 0)
        + participant.get("neutralMinionsKilled", 0),
        damage_to_champions=participant.get("totalDamageDealtToChampions"),
        gold_earned=participant.get("goldEarned"),
        spell1_id=participant.get("summoner1Id"),
        spell2_id=participant.get("summoner2Id"),
        keystone_id=next((selection.get("perk") for style in
                          participant.get("perks", {}).get("styles", [])
                          for selection in style.get("selections", [])[:1]), None),
    )


def get_match_detail(match_id: str) -> dict:
    """Retrieve the completed match for the statistics dialog."""
    from urllib.parse import quote
    server = _server()
    if server is not None:
        detail = server.get_json(f"/v1/riot/matches/detail/{quote(match_id, safe='')}")
    else:
        detail = _get_client().get_region(f"/lol/match/v5/matches/{quote(match_id, safe='')}")
    if not detail or not detail.get('info', {}).get('participants'):
        raise MatchDataUnavailable(match_id)
    return detail
