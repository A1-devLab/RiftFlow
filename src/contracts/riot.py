"""
src/contracts/riot.py

docs/interfaces.md의 riot 모듈 계약(get_player, get_recent_matches, get_live_state)에
대응하는 공통 데이터 형식.

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
from typing import Optional


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
# 5. 오류 표현: "호출 제한 / 검색 결과 없음"은 예외로 구분
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
