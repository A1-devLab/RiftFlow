"""Before-game terminal interaction and application service."""
from game_phases.common import ask, show
from .prompt import build


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
