"""Out-of-game meta question flow."""
from game_phases.common import ask, show
from .prompt import build, classify

# 검색할 때 질문 뒤에 붙이는 말. 패치 노트가 검색되게 한다.
# '요즘 뭐가 좋아?' 는 이 말이 없으면 검색 결과가 0건이다.
PATCH_HINT = " 이번 패치 변경 버프 너프 상향 하향"


def search_text(question, types):
    """검색에 쓸 문장을 만든다.

    아이템·룬 질문에는 패치 말을 붙이지 않는다. 붙이면 검색기가 '패치를 묻는 질문' 으로 보고
    패치 노트에 가산점을 더해, 질문과 관계없는 패치 노트가 8점대로 올라간다.
    단, 패치나 메타도 함께 묻는 질문('이번 패치 아이템 뭐 바뀜?')은 붙인다.

    이것만으로 아이템이 1위가 되지는 않는다. rag/retrieve.py 가 out_game 의 모든 패치 노트에
    최저 점수 5 를 주기 때문이다 (tests/integration/test_out_game.py 의 알려진 한계 테스트).

    유형을 모르는 질문(빈 목록)은 예전처럼 붙인다. '요즘 뭐가 좋아?' 같은 모호한 질문이
    여기에 들어가고, 이름만 있는 '무한의 대검 언제 사?' 도 들어간다 (알려진 한계).
    """
    if "item_rune" in types and not {"patch", "meta"} & set(types):
        return question
    return question + PATCH_HINT


def ask_out_game(question):
    types = classify(question)
    return ask(question, analysis={"phase": "out_game"}, prompt_builder=build,
               retrieval_question=search_text(question, types))


def run():
    print("\n[게임 외부 메타·정보]")
    question = input("메타 또는 게임 정보 질문: ").strip()
    if question:
        show(ask_out_game(question))
