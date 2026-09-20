"""
src/riot - 라이엇 API 연동 모듈.

다른 모듈(knowledge, rag, ui)은 여기서 공개하는 함수/타입만 사용한다.
"""

from contracts.riot import (
    ClientNotRunning,
    ConnectionState,
    LiveMatchStatus,
    LiveState,
    MatchDataUnavailable,
    MatchSummary,
    PlayerIdentity,
    PlayerNotFound,
    RankInfo,
    RateLimitExceeded,
    RiotApiError,
)

from .lcu_client import get_current_summoner, is_client_logged_in, start_login_watcher
from .live_client import get_live_state
from .service import get_player, get_recent_matches, get_solo_rank

__all__ = [
    # 함수
    "get_player",
    "get_recent_matches",
    "get_solo_rank",
    "get_live_state",
    "get_current_summoner",
    "is_client_logged_in",
    "start_login_watcher",
    # 데이터 형식
    "PlayerIdentity",
    "MatchSummary",
    "RankInfo",
    "LiveState",
    "LiveMatchStatus",
    "ConnectionState",
    # 예외
    "RiotApiError",
    "PlayerNotFound",
    "MatchDataUnavailable",
    "RateLimitExceeded",
    "ClientNotRunning",
]
