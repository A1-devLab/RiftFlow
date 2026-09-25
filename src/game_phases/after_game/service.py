"""Post-game result summary and future analysis flow."""
from riot import get_post_game_summary


def get_after_game_context():
    """결과 화면이 열려 있을 때 본인의 경기 요약을 반환한다."""
    return get_post_game_summary()


def run():
    print("\n[게임 종료 후 분석]")
    summary = get_after_game_context()
    if summary is None:
        print("결과 화면 데이터가 없습니다. 게임 종료 직후 다시 확인하세요.")
        return
    print("%s · %d/%d/%d · CS %d · 시야 점수 %d" % (
        summary.result, summary.kills, summary.deaths, summary.assists,
        summary.cs, summary.vision_score,
    ))
