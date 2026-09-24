"""Out-of-game meta question flow.

질문 유형을 판정해 검색어를 정하고, 판정 결과를 analysis 로 build 에 넘긴다.
"""
import re

from game_phases.common import ask, show
from .prompt import build

# 질문 유형. 한 질문에 여러 개가 붙을 수 있다. 순서는 결과를 적을 때의 순서다.
TYPES = ("patch", "champion", "item_rune", "meta")

# 단어 규칙으로 판정한다. Gemini 에 판정을 맡기면 질문마다 호출이 한 번 더 들어가
# 하루 호출 한도와 응답 시간을 두 배로 쓴다.
# 띄어쓰기를 지우고 소문자로 바꾼 질문에서 찾는다. '뭐 해야' 와 '뭐해야' 를 같게 보기 위해서다.
PATCH_WORDS = ("패치", "버프", "너프", "상향", "하향", "바뀌", "바뀐", "바뀜", "변경")
# 26.18 처럼 패치 번호를 직접 쓴 경우
PATCH_NUMBER = re.compile(r"\d{1,2}\.\d{1,2}")

ITEM_RUNE_WORDS = ("아이템", "템", "룬", "빌드", "가격", "얼마", "조합", "코어",
                   "살까", "사야", "가야", "갈까", "가는게", "올려")

# '요즘' 은 넣지 않는다. '요즘 원딜 뭐가 좋아?' 는 추천이고 메타가 아니다 (fixture 정답).
META_WORDS = ("메타", "티어", "대세", "사기", "op", "할만", "쎄", "쎔", "쎈",
              "강해", "강함", "세졌", "좋아졌", "요즘흐름")

# 추천은 '무엇을 할지' 를 묻는 말과 '챔피언' 을 가리키는 말이 함께 있어야 한다.
# '점심 메뉴 추천해줘' 처럼 추천만 있으면 롤 질문이 아니다.
RECOMMEND_WORDS = ("추천", "뭐해", "뭐할", "뭐하지", "뭐함", "뭐하면", "뭐가좋", "뭐좋", "픽")
CHAMPION_WORDS = ("챔", "원딜", "미드", "탑", "정글", "서폿", "서포터", "ad", "ap")


# 유형 단어를 품고 있지만 그 뜻이 아닌 말. 찾기 전에 지운다. '시스템' 의 '템' 이 아이템으로 잡혔다.
NOT_WORDS = ("시스템",)


def compact(question):
    text = re.sub(r"\s+", "", question or "").lower()
    for word in NOT_WORDS:
        text = text.replace(word, "")
    return text


def classify(question):
    """질문 유형을 판정한다. 해당하는 유형을 TYPES 순서로 돌려준다. 없으면 빈 목록이다."""
    text = compact(question)
    found = set()
    if any(word in text for word in PATCH_WORDS) or PATCH_NUMBER.search(text):
        found.add("patch")
    if any(word in text for word in ITEM_RUNE_WORDS):
        found.add("item_rune")
    if any(word in text for word in META_WORDS):
        found.add("meta")
    if any(word in text for word in RECOMMEND_WORDS) and any(word in text for word in CHAMPION_WORDS):
        # '원딜 아이템 뭐가 좋아?' 는 아이템 질문이다. 아이템·룬 질문이면 '챔' 이 직접 있을 때만 추천으로 본다.
        if "item_rune" not in found or "챔" in text:
            found.add("champion")
    return [kind for kind in TYPES if kind in found]


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
    return ask(question, analysis={"phase": "out_game", "question_types": types}, prompt_builder=build,
               retrieval_question=search_text(question, types))


def run():
    print("\n[게임 외부 메타·정보]")
    question = input("메타 또는 게임 정보 질문: ").strip()
    if question:
        show(ask_out_game(question))
