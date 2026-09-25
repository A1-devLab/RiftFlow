"""
src/riot/live_client.py

get_live_state 구현.

주의: 공식 SPECTATOR API가 아니라, 라이엇 클라이언트가 실행 중일 때만 열리는
로컬 Live Client Data API(https://127.0.0.1:2999)를 사용한다.
- 인증(API 키) 불필요
- 자체 서명 인증서라 verify=False 필요
- 게임이 실행 중이 아니면 연결 자체가 실패하는데, 이는 오류가 아니라
  LiveMatchStatus.NOT_IN_GAME으로 표현한다 (docs/interfaces.md 합의사항).

아래는 get_live_state() 이후에 추가된 부분이다 (라인/K,D,A/CS, 골드 추정,
게임 종료 승패 추적). get_live_state()/LiveState 계약은 그대로 유지하고,
이 함수들은 별도의 일반 dict/list를 반환하는 보조 함수들이다 - 아직
contracts.riot에 없는 값들(스코어보드 등)까지 LiveState에 넣기 시작하면
계약이 커지므로, 필요해지면 그때 contracts.riot 쪽과 상의해서 정식으로
편입하는 걸 권장한다.

- 라인, K/D/A, CS: get_scoreboard()에서 그대로 노출
- 골드: 본인 외에는 API에 정확한 골드 필드가 없어서 estimate_gold()로
  대략치만 계산한다. 아이템 가격은 Live Client Data API가 주는 "price"
  필드 대신 Data Dragon(라이엇 정적 데이터 CDN)에서 itemID -> 정식 총
  가격표를 받아와 대조한다 - LCU 쪽 price 필드가 실제 상점 가격과 다르게
  나오는 경우가 있어서다. 다만 이것도 "이미 쓴 돈"이라 미구매 잔액은
  반영 안 됨 - UI 참고용, 정확한 값 아님 (estimate_gold 참고).
- 승패: eventdata의 GameEnd 이벤트의 Result("Win"/"Lose")를 사용한다.
"""

import functools
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests
import urllib3

from contracts.riot import ConnectionState, LiveMatchStatus, LiveState, PlayerLiveStats, TeamGoldTotals

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LIVE_CLIENT_BASE = "https://127.0.0.1:2999/liveclientdata"

# Data Dragon(라이엇 정적 데이터 CDN) - 로컬 LCU/Live Client Data와는 별개로
# 인터넷 접속이 필요하다. 아이템의 정식 총 가격표를 가져오는 데만 쓴다.
_DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
_DDRAGON_ITEM_URL_TEMPLATE = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"


def get_live_state() -> LiveState:
    try:
        response = requests.get(
            f"{_LIVE_CLIENT_BASE}/gamestats", timeout=1.0, verify=False
        )
    except requests.exceptions.RequestException:
        # 클라이언트가 꺼져있거나 게임 중이 아님 - 정상적인 상태로 취급
        return LiveState(
            status=LiveMatchStatus.NOT_IN_GAME,
            connection=ConnectionState.DISCONNECTED,
        )

    if response.status_code != 200:
        return LiveState(
            status=LiveMatchStatus.NOT_IN_GAME,
            connection=ConnectionState.CONNECTED,
        )

    data = response.json()
    return LiveState(
        status=LiveMatchStatus.IN_GAME,
        connection=ConnectionState.CONNECTED,
        elapsed_seconds=int(data.get("gameTime", 0)),
    )


# ---------------------------------------------------------------------------
# 아래부터 추가된 기능 (스코어보드 / 골드 추정 / 승패).
# get_live_state()와는 별개로, 각자 필요할 때 직접 호출해서 쓰는 보조
# 함수들이다.
# ---------------------------------------------------------------------------


def _get(endpoint: str) -> Optional[Any]:
    """Live Client Data API에 GET 요청. 인증 불필요, 실패 시 None.

    get_live_state()는 자체적으로 요청을 처리하므로(위 참고) 건드리지
    않고, 아래 새 함수들만 이 헬퍼를 공통으로 쓴다.
    """
    try:
        response = requests.get(f"{_LIVE_CLIENT_BASE}{endpoint}", timeout=2.0, verify=False)
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None
    return response.json()


def is_in_game() -> bool:
    """실제 게임에 접속해서 데이터를 받아올 수 있는 상태인지 확인한다.

    get_live_state().status == LiveMatchStatus.IN_GAME 와 같은 뜻이지만,
    이 파일의 새 함수들(get_scoreboard 등)을 쓸 때 매번 LiveState를 만들
    필요 없이 바로 쓰기 편하도록 별도로 둔다.
    """
    return _get("/gamestats") is not None


def get_game_time() -> Optional[float]:
    """게임 시작 후 경과 시간(초)을 반환한다. 게임 중이 아니면 None."""
    data = _get("/gamestats")
    if data is None:
        return None
    return data.get("gameTime")


def get_active_player() -> Optional[dict]:
    """본인(클라이언트 접속 중인 플레이어)의 상세 정보를 가져온다.

    currentGold(정확한 골드), level, championStats, abilities 등이 담겨
    있다 - 정확한 골드가 오는 건 본인뿐이다. 게임 중이 아니면 None.
    """
    return _get("/activeplayer")


def get_active_player_name() -> Optional[str]:
    """본인의 소환사 이름을 반환한다 (스코어보드에서 '나'를 찾을 때 쓴다).

    /playerlist 항목에는 본인 표시가 없어서, 이 이름으로 대조해야 한다.
    클라이언트 버전에 따라 "이름" 또는 "이름#태그"로 온다.
    게임 중이 아니면 None.
    """
    name = _get("/activeplayername")
    if isinstance(name, str) and name.strip():
        return name.strip()
    player = get_active_player()
    if isinstance(player, dict):
        value = player.get("summonerName") or player.get("riotId")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def get_all_players() -> Optional[List[dict]]:
    """전체 10명의 원본 데이터를 그대로 반환한다.

    각 항목에 championName, team("ORDER"/"CHAOS"), position(TOP/JUNGLE/
    MIDDLE/BOTTOM/UTILITY, 극초반엔 "NONE"), isDead, respawnTimer,
    scores(kills/deaths/assists/creepScore/wardScore), items 등이 있다.
    본인 외 9명은 골드 필드가 아예 없다 (estimate_gold 참고).
    게임 중이 아니면 None.
    """
    return _get("/playerlist")


def get_scoreboard() -> Optional[List[PlayerLiveStats]]:
    """get_all_players()를 화면에서 바로 쓰기 편한 형태로 가공해서 반환한다.

    반환: PlayerLiveStats 리스트 (필드는 contracts.riot.PlayerLiveStats 참고).
    게임 중이 아니면 None.
    """
    players = get_all_players()
    if players is None:
        return None

    scoreboard = []
    for player in players:
        scores = player.get("scores", {})
        items = player.get("items", [])
        scoreboard.append(
            PlayerLiveStats(
                summoner_name=player.get("summonerName") or player.get("riotIdGameName"),
                champion_name=player.get("championName") or "",
                team=player.get("team") or "",
                position=player.get("position") or "NONE",
                level=int(player.get("level") or 0),
                kills=int(scores.get("kills") or 0),
                deaths=int(scores.get("deaths") or 0),
                assists=int(scores.get("assists") or 0),
                cs=scores.get("creepScore", 0),
                is_dead=bool(player.get("isDead")),
                respawn_timer=float(player.get("respawnTimer") or 0),
                items=items,
                estimated_gold=estimate_gold(items),
            )
        )
    return scoreboard


def get_team_gold_totals(
    scoreboard: Optional[List[PlayerLiveStats]] = None,
) -> Optional[TeamGoldTotals]:
    """팀별 추정 골드 합계("글로벌 골드" 추정치)를 계산한다.

    scoreboard를 안 넘기면 get_scoreboard()를 직접 호출한다. 각 선수의
    estimate_gold() 결과(보유 아이템 가격 합계 기준)를 팀별로 더한 값이라,
    개인 추정 골드와 마찬가지로 "이미 쓴 돈" 기준이다 - 미구매 잔액은
    반영되지 않으므로 실제 팀 전체 골드보다 항상 적게(또는 같게) 나온다.

    반환: TeamGoldTotals(order=..., chaos=...). 게임 중이 아니면 None.
    """
    if scoreboard is None:
        scoreboard = get_scoreboard()
    if scoreboard is None:
        return None

    order_total = 0.0
    chaos_total = 0.0
    for player in scoreboard:
        if player.team == "ORDER":
            order_total += player.estimated_gold
        elif player.team == "CHAOS":
            chaos_total += player.estimated_gold
    return TeamGoldTotals(order=order_total, chaos=chaos_total)


@functools.lru_cache(maxsize=1)
def _get_ddragon_item_prices() -> Dict[int, int]:
    """Data Dragon에서 최신 패치의 아이템 가격표(itemID -> 정식 총 가격)를
    가져와 캐싱한다.

    itemID -> 가격 매핑은 패치가 바뀌지 않는 한 안 변하므로, 프로세스
    생애주기 동안 한 번만 요청한다(lru_cache). 로컬 LCU/Live Client Data
    와는 별개로 인터넷 접속이 필요하다 - 실패하면(오프라인 등) 빈 dict를
    반환하고, estimate_gold()는 그 경우 Live Client Data API 자체의
    price 필드로 폴백한다.
    """
    try:
        versions_response = requests.get(_DDRAGON_VERSIONS_URL, timeout=3.0)
        versions_response.raise_for_status()
        latest_version = versions_response.json()[0]

        item_response = requests.get(
            _DDRAGON_ITEM_URL_TEMPLATE.format(version=latest_version), timeout=5.0
        )
        item_response.raise_for_status()
        item_data = item_response.json().get("data", {})
    except (requests.exceptions.RequestException, ValueError, IndexError, KeyError):
        return {}

    prices: Dict[int, int] = {}
    for item_id_str, info in item_data.items():
        try:
            prices[int(item_id_str)] = int(info.get("gold", {}).get("total", 0))
        except (TypeError, ValueError):
            continue
    return prices


def estimate_gold(items: List[dict]) -> float:
    """보유(구매)한 아이템 가격의 합으로 골드를 추정한다 (정확한 값이 아님).

    아이템 가격은 Live Client Data API가 각 아이템과 같이 주는 "price"
    필드를 그대로 쓰지 않고, Data Dragon(라이엇 정적 데이터 CDN)에서
    itemID -> 정식 총 가격표를 받아와 대조한다 - LCU 쪽 price 필드가 실제
    상점 가격과 다르게 나오는 경우가 있었기 때문이다. Data Dragon 조회에
    실패했거나 표에 없는 itemID(모드 전용 특수 아이템 등)는 LCU가 준
    price 필드로 폴백한다.

    주의: 이건 여전히 "이미 아이템에 쓴 돈"이지 "지금 갖고 있는 돈(다음
    아이템 사려고 모아둔 잔액)"이 아니다. 그래서 실제 보유 골드보다 항상
    적게(또는 같게) 나온다 - "누가 얼마나 투자했는지" 참고용으로 쓰는 걸
    권장한다.
    """
    price_map = _get_ddragon_item_prices()
    total = 0.0
    for item in items:
        count = item.get("count", 1)
        price = price_map.get(item.get("itemID"))
        if price is None:
            price = item.get("price", 0)  # Data Dragon에 없으면 LCU 값으로 폴백
        total += price * count
    return total


def get_event_data() -> Optional[List[dict]]:
    """게임 시작부터 지금까지 발생한 이벤트 로그를 원본 그대로 반환한다.

    EventName 예시: GameStart, MinionsSpawning, FirstBlood, FirstBrick,
    TurretKilled, InhibKilled, DragonKill, HeraldKill, BaronKill,
    ChampionKill, Multikill, Ace, GameEnd 등.
    게임 중이 아니면 None.
    """
    data = _get("/eventdata")
    if data is None:
        return None
    return data.get("Events")


def get_game_result(events: Optional[List[dict]] = None) -> Optional[str]:
    """게임 종료 결과를 반환한다.

    Live Client Data API의 GameEnd 이벤트에 있는 Result 필드를 사용한다.
    Result는 이 클라이언트의 로컬 플레이어 기준으로 "Win" 또는 "Lose"가
    기록되므로, 이를 외부에서 쓰기 편하게 "WIN" / "LOSS"로 정규화한다.

    아직 GameEnd 이벤트가 발생하지 않았거나 게임 중이 아니면 None.
    """
    if events is None:
        events = get_event_data()
    if events is None:
        return None

    for event in reversed(events):
        if event.get("EventName") != "GameEnd":
            continue

        result = str(event.get("Result", "")).strip().lower()
        if result == "win":
            return "WIN"
        if result in {"lose", "loss"}:
            return "LOSS"

    return None


def start_live_watcher(
    on_update: Callable[[List[PlayerLiveStats]], None],
    on_end: Optional[Callable[[], None]] = None,
    interval: float = 1.0,
    on_result: Optional[Callable[[str], None]] = None,
) -> threading.Thread:
    """백그라운드 스레드에서 스코어보드/승패를 주기적으로 폴링한다.

    - 아직 게임에 접속하기 전에는 조용히 기다린다.
    - 게임 중에는 매 interval마다 on_update(scoreboard)를 호출한다.
    - GameEnd 이벤트가 확인되면 get_game_result()로 WIN/LOSS를 확정한다.
    - 승패가 처음 확인되는 순간 on_result("WIN" | "LOSS")를 한 번 호출한다.
    - 이후 게임 데이터 API가 종료되면 기존과 동일하게 on_end()를 한 번 호출하고
      watcher를 종료한다.

    승패를 받고 싶으면 on_result 콜백을 추가하면 된다.
    """

    def _watch():
        entered = False
        reported_result: Optional[str] = None

        while True:
            scoreboard = get_scoreboard()

            if scoreboard is not None:
                entered = True

                # GameEnd 이벤트가 API에서 사라지기 전에 먼저 확인한다.
                result = get_game_result()

                if result is not None and result != reported_result:
                    reported_result = result
                    if on_result is not None:
                        on_result(result)

                on_update(scoreboard)

            elif entered:
                # 기존 API 계약을 유지: 게임 종료 시 on_end() 호출.
                if on_end is not None:
                    on_end()
                return

            time.sleep(interval)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread
