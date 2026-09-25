"""
src/riot - 라이엇 API 연동 모듈.

다른 모듈(knowledge, rag, ui)은 여기서 공개하는 함수/타입만 사용한다.
"""

from contracts.riot import (
    ChampSelectMember,
    ChampSelectSession,
    ClientNotRunning,
    ConnectionState,
    LiveMatchStatus,
    LiveState,
    MatchDataUnavailable,
    MatchSummary,
    PlayerIdentity,
    PlayerLiveStats,
    PlayerNotFound,
    PostGameSummary,
    RankInfo,
    RateLimitExceeded,
    RiotApiError,
    TeamGoldTotals,
)

from .lcu_client import (
    ChampSelectSocket,
    get_champ_select_session,
    get_current_summoner,
    get_gameflow_phase,
    get_post_game_summary,
    is_client_logged_in,
    start_champ_select_watcher,
    start_login_watcher,
    wait_for_post_game_summary,
)
from .live_client import (
    get_active_player,
    get_active_player_name,
    get_all_players,
    get_event_data,
    get_game_result,
    get_live_state,
    get_scoreboard,
    get_team_gold_totals,
    start_live_watcher,
)
from .service import get_player, get_recent_matches, get_recent_matches_with_details, get_solo_rank, get_match_detail

__all__ = [
    # 함수
    "get_player",
    "get_match_detail",
    "get_recent_matches",
    "get_recent_matches_with_details",
    "get_solo_rank",
    "get_live_state",
    "get_current_summoner",
    "is_client_logged_in",
    "start_login_watcher",
    "get_gameflow_phase",
    "get_active_player",
    "get_active_player_name",
    "get_all_players",
    "get_event_data",
    "get_game_result",
    "start_live_watcher",
    "get_scoreboard",
    "get_team_gold_totals",
    "get_post_game_summary",
    "wait_for_post_game_summary",
    "get_champ_select_session",
    "start_champ_select_watcher",
    "ChampSelectSocket",
    # 데이터 형식
    "PlayerIdentity",
    "MatchSummary",
    "RankInfo",
    "LiveState",
    "LiveMatchStatus",
    "ConnectionState",
    "PlayerLiveStats",
    "TeamGoldTotals",
    "PostGameSummary",
    "ChampSelectMember",
    "ChampSelectSession",
    # 예외
    "RiotApiError",
    "PlayerNotFound",
    "MatchDataUnavailable",
    "RateLimitExceeded",
    "ClientNotRunning",
]
