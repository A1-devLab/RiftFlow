"""Out-of-game meta question flow."""
from game_phases.common import ask, show
from .prompt import build


def ask_out_game(question):
    # '요즘 뭐가 좋아?'처럼 검색어가 모호해도 최근 패치 변경 근거를 먼저 찾는다.
    retrieval_question = question + " 이번 패치 변경 버프 너프 상향 하향"
    return ask(question, analysis={"phase": "out_game"}, prompt_builder=build,
               retrieval_question=retrieval_question)


def run():
    print("\n[게임 외부 메타·정보]")
    question = input("메타 또는 게임 정보 질문: ").strip()
    if question:
        show(ask_out_game(question))
