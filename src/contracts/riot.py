"""
src/contracts/riot.py

docs/interfaces.md의 riot 모듈 계약(get_player, get_recent_matches, get_live_state)에
대응하는 공통 데이터 형식. PlayerLiveStats/TeamGoldTotals/PostGameSummary는
챔피언 선택/인게임/경기 결과 기능을 dict에서 데이터클래스로 편입하며 추가됨.

이 파일에는 데이터 형식과 예외만 둔다. 실제 구현은 src/riot/ 아래에 있다.

합의 반영 사항:
- 내부 사용자 식별자는 PUUID 기준
- 경기 시간 단위는 초(seconds)
- 누락된 값은 0과 구분 (Optional[T] = None 사용)
- API 원본 응답은 riot 모듈 내부에서 이 형식으로 변환한 뒤 다른 모듈에 전달
- "게임 미실행"은 정상 상태값(LiveMatchStatus.NOT_IN_GAME)으로 표현하고,
  "호출 제한"/"검색 결과 없음"은 예외로 구분해서 표현한다
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# 1. get_player 출력: 사용자 식별 정보
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerIdentity:
    """소환사 식별 정보. 내부적으로는 puuid를 기준 키로 사용한다."""

    puuid: str                              # 내부 기준 식별자 (필수)
    riot_id: str                            # "gameName#tagLine" 형태
    summoner_level: Optional[int] = None    # 없을 수 있으므로 0과 구분
    profile_icon_id: Optional[int] = None


# ---------------------------------------------------------------------------
# 2. get_recent_matches 출력: 경기 요약 목록
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchSummary:
    """개별 경기 요약. get_recent_matches는 이 타입의 리스트를 반환한다."""

    match_id: str
    played_at_epoch: int             # 경기 시작 시각 (UTC epoch seconds)
    game_duration_seconds: int       # 경기 길이 - 초 단위로 통일
    game_mode: str                   # 예: "CLASSIC", "ARAM"
    champion_name: str
    win: bool
    kills: int
    deaths: int
    assists: int
    cs: Optional[int] = None         # creep score - 큐 타입에 따라 없을 수 있음
    damage_to_champions: Optional[int] = None
    gold_earned: Optional[int] = None
    spell1_id: Optional[int] = None
    spell2_id: Optional[int] = None
    keystone_id: Optional[int] = None


# ---------------------------------------------------------------------------
# 3. 랭크 정보 (interfaces.md 표에는 없지만, 티어 기반 기능을 위해 추가 제안
#    - 팀과 합의 후 확정할 것)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankInfo:
    """특정 큐(예: 솔로랭크)의 티어 정보."""

    queue_type: str          # 예: "RANKED_SOLO_5x5"
    tier: str                # 예: "GOLD"
    division: str            # 예: "II" (로마 숫자)
    league_points: int
    wins: int
    losses: int


# ---------------------------------------------------------------------------
# 4. get_live_state 출력: 경기 상태 + 연결 상태
# ---------------------------------------------------------------------------

class LiveMatchStatus(Enum):
    """게임 실행 여부. '게임 미실행'은 오류가 아니라 정상적인 상태값이다."""
    IN_GAME = "in_game"
    NOT_IN_GAME = "not_in_game"


class ConnectionState(Enum):
    """라이엇 클라이언트(Live Client Data API) 연결 상태."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class LiveState:
    status: LiveMatchStatus
    connection: ConnectionState
    elapsed_seconds: Optional[int] = None   # IN_GAME일 때만 값 존재


# ---------------------------------------------------------------------------
# 5. get_scoreboard 출력: 인게임 실시간 스코어보드 (개별 선수 항목)
#    (구 lcu_client 챔피언 선택/인게임 기능을 dict에서 데이터클래스로 편입 - riot_module_io.md 논의 반영)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerLiveStats:
    """인게임 실시간 스코어보드의 개별 선수 항목. get_scoreboard()는 이 타입의 리스트를 반환한다."""

    summoner_name: Optional[str]     # Riot ID 전환 과정에서 비어올 수 있음
    champion_name: str
    team: str                        # "ORDER" 또는 "CHAOS" (라이엇 API가 주는 값 그대로)
    position: str                    # "TOP"/"JUNGLE"/"MIDDLE"/"BOTTOM"/"UTILITY", 극초반엔 "NONE"
    level: int
    kills: int
    deaths: int
    assists: int
    cs: int                          # 미니언 + 정글 몹 처치 수
    is_dead: bool
    respawn_timer: float
    items: List[dict]                # 아이템 원본 (아직 별도 타입 없음 - 필요해지면 추가)
    estimated_gold: float            # 추정치 - 보유 아이템 가격 합계 기준, 미구매 잔액 미반영


# ---------------------------------------------------------------------------
# 6. get_team_gold_totals 출력: 팀별 추정 골드 합계
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamGoldTotals:
    """팀별 추정 골드 합계. live_client.get_team_gold_totals()가 반환한다."""

    order: float    # team == "ORDER"인 선수들의 estimated_gold 합
    chaos: float    # team == "CHAOS"인 선수들의 estimated_gold 합


# ---------------------------------------------------------------------------
# 7. get_post_game_summary 출력: 경기 종료 후 결과 화면 요약
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PostGameSummary:
    """경기 종료 후 결과 화면 요약. lcu_client.get_post_game_summary()가 반환한다."""

    game_duration_seconds: int
    result: str                      # "WIN" 또는 "LOSS"
    kills: int
    deaths: int
    assists: int
    cs: int
    cs_per_min: float
    kill_participation_pct: float    # (kills+assists) / 팀 전체 킬 * 100
    damage_dealt: int                # 챔피언 대상 딜량
    damage_taken: int
    vision_score: int
    champion_name: Optional[str] = None   # 결과 화면에서 확인되면 채움. 못 읽으면 None


# ---------------------------------------------------------------------------
# 8. get_champ_select_session 출력: 챔피언 선택(픽창)의 픽/밴 현황
#    범위는 픽/밴 현황만으로 한정 - 턴 순서/타이머는 아직 포함하지 않음 (필요해지면 확장)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChampSelectMember:
    """챔피언 선택의 개별 슬롯(팀원 한 명)의 픽 현황."""

    cell_id: int
    champion_id: int                    # 0 = 아직 픽 안 함
    assigned_position: str              # 예: "top"/"jungle"/"middle"/"bottom"/"utility", 없으면 ""
    puuid: Optional[str] = None         # 상대팀은 픽 완료 전까지 비어있을 수 있음


@dataclass(frozen=True)
class ChampSelectSession:
    """챔피언 선택 세션의 픽/밴 현황. lcu_client.get_champ_select_session()이 반환한다.

    상대팀(their_team)은 라이엇이 의도적으로 제한한다 - 밴 완료 및 픽 완료된
    것만 champion_id가 채워지고, 아직 고르는 중인 실시간 호버 상태는 반영되지
    않는다.
    """

    my_team: List[ChampSelectMember]
    their_team: List[ChampSelectMember]
    my_bans: List[int]                  # championId 목록 - actions의 완료된 ban에서 집계 (raw bans 필드는 안 믿음)
    their_bans: List[int]
    local_player_cell_id: int           # my_team 중 본인 슬롯의 cell_id


# ---------------------------------------------------------------------------
# 9. 오류 표현: "호출 제한 / 검색 결과 없음"은 예외로 구분
#    ("게임 미실행"은 위의 LiveMatchStatus.NOT_IN_GAME으로 이미 표현하므로 예외 아님)
# ---------------------------------------------------------------------------

class RiotApiError(Exception):
    """riot 모듈에서 발생하는 모든 오류의 기반 클래스."""


class PlayerNotFound(RiotApiError):
    """Riot ID 또는 PUUID로 소환사를 찾을 수 없을 때."""

    def __init__(self, identifier: str):
        self.identifier = identifier
        super().__init__(f"소환사를 찾을 수 없습니다: {identifier}")


class MatchDataUnavailable(RiotApiError):
    """검색 결과 없음 (예: 최근 경기 기록이 없는 계정)."""

    def __init__(self, puuid: str):
        self.puuid = puuid
        super().__init__(f"경기 기록을 찾을 수 없습니다: {puuid}")


class ClientNotRunning(RiotApiError):
    """라이엇 클라이언트가 꺼져있거나 아직 로그인 전일 때."""


class RateLimitExceeded(RiotApiError):
    """라이엇 API 호출 제한(429)에 걸렸을 때."""

    def __init__(self, retry_after_seconds: Optional[float] = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"API 호출 제한 초과. 재시도 대기 시간: {retry_after_seconds}초"
            if retry_after_seconds is not None
            else "API 호출 제한 초과."
        )
