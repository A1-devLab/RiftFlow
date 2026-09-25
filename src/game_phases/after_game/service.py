"""Post-game result summary and terminal review flow."""
from pathlib import Path

from riot import get_post_game_summary


def get_after_game_context():
    """결과 화면이 열려 있을 때 본인의 경기 요약을 반환한다."""
    return get_post_game_summary()


def run(db_path=Path("data/riftflow.db")):
    from game_phases.common import gemini_generator
    from .desktop import analyze_after_game

    print("\n[게임 종료 후 분석]")
    summary = get_after_game_context()
    if summary is None:
        print("결과 화면 데이터가 없습니다. 게임 종료 직후 다시 확인하세요.")
        return
    print("%s · %s · %d/%d/%d · CS %d · 시야 점수 %d" % (
        summary.result, summary.champion_name or "챔피언 확인 안 됨",
        summary.kills, summary.deaths, summary.assists, summary.cs, summary.vision_score,
    ))
    question = input("추가로 궁금한 점 (엔터: 기본 분석): ").strip()
    result = analyze_after_game(db_path, summary, generate=gemini_generator(), question=question)
    print("\n" + (result["answer"] or result["message"] or "답변이 없습니다."))
