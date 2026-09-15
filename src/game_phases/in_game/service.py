"""Current RAG question flow, classified as in-game guidance."""
from game_phases.common import ask, show


def run():
    print("\n[게임 중 가이드]")
    question = input("현재 상황 또는 질문: ").strip()
    if question:
        show(ask(question))
