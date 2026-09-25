"""Current RAG question flow, classified as in-game guidance."""
from game_phases.common import ask, show
from riot import get_live_state, get_scoreboard, get_team_gold_totals


def get_in_game_context():
    """현재 게임 상태와 10명 스코어보드, 팀별 사용 골드 추정치를 묶는다."""
    scoreboard = get_scoreboard()
    return {
        "state": get_live_state(),
        "scoreboard": scoreboard,
        "team_gold": get_team_gold_totals(scoreboard) if scoreboard is not None else None,
    }


def run():
    print("\n[게임 중 가이드]")
    question = input("현재 상황 또는 질문: ").strip()
    if question:
        show(ask(question))
