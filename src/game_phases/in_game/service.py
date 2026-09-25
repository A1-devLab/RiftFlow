"""In-game live context and terminal interaction."""
from pathlib import Path

from game_phases.common import ask, gemini_generator, show
from riot import get_active_player_name, get_live_state, get_scoreboard, get_team_gold_totals


def get_in_game_context(state=None):
    """현재 게임 상태와 10명 스코어보드, 팀별 사용 골드 추정치, 내 소환사 이름을 묶는다."""
    scoreboard = get_scoreboard()
    return {
        "state": state if state is not None else get_live_state(),
        "scoreboard": scoreboard,
        "team_gold": get_team_gold_totals(scoreboard) if scoreboard is not None else None,
        "active_player_name": get_active_player_name() if scoreboard is not None else None,
    }


def run(db_path=Path("data/riftflow.db")):
    from knowledge.in_game import item_catalog
    from .desktop import answer_in_game, describe_scoreboard
    from .prompt import build

    print("\n[게임 중 가이드]")
    view = describe_scoreboard(get_in_game_context(), item_catalog(db_path))
    if view.get("in_game"):
        me = view.get("me") or {}
        print("%s · %s %s · 팀 추정 골드 차이 %s" % (
            view["clock"], me.get("champion", "내 챔피언 확인 안 됨"), me.get("kda", ""),
            (view.get("team_gold") or {}).get("diff", "—")))
    else:
        print("실시간 게임에 연결되지 않았습니다. 상황을 직접 적어 질문하세요.")
    question = input("현재 상황 또는 질문: ").strip()
    if not question:
        return
    if view.get("in_game"):
        result = answer_in_game(db_path, view, question, generate=gemini_generator())
        print("\n" + (result["answer"] or result["message"] or "답변이 없습니다."))
    else:
        show(ask(question, analysis={"phase": "in_game"}, prompt_builder=build, db_path=db_path))
