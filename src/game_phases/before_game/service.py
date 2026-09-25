"""Before-game terminal interaction and application service."""
from game_phases.common import ask, show
from riot import get_champ_select_session
from .prompt import build


def get_before_game_context():
    """현재 픽창의 아군·상대 픽과 확정된 밴을 반환한다."""
    return get_champ_select_session()


def ask_before_game(champion, opponent, trade_preference, lane_aggression, question):
    analysis = {
        "champion": champion,
        "opponent": opponent,
        "playstyle": {
            "trade_preference": trade_preference,
            "lane_aggression": lane_aggression,
        },
    }
    return ask(question, analysis=analysis, prompt_builder=build)


def run():
    print("\n[게임 전 가이드]")
    champion = input("내 챔피언: ").strip()
    opponent = input("상대 챔피언: ").strip()
    trade = input("선호 딜교환 (순간/지속): ").strip()
    lane = input("선호 라인전 (공격적/안정적): ").strip()
    question = input("질문: ").strip() or "%s의 룬과 초반 운영을 추천해줘" % champion
    show(ask_before_game(champion, opponent, trade, lane, question))
