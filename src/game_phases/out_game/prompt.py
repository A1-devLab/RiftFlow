"""Gemini prompt for questions asked outside a match.

프롬프트 담당자는 이 파일의 SYSTEM과 build 함수만 수정하면 됩니다.
classify 는 질문 유형 판정입니다. 유형에 따라 검색어와 답변 지침이 달라서 같은 파일에 둡니다.
"""
import re

from rag.prompt import build as build_base

# 질문 유형. 한 질문에 여러 개가 붙을 수 있다. 순서는 결과를 적을 때의 순서다.
TYPES = ("patch", "champion", "item_rune", "meta")
TYPE_NAMES = {"patch": "패치 변경", "champion": "챔피언 추천",
              "item_rune": "아이템·룬", "meta": "메타"}

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


SYSTEM = """너는 리그 오브 레전드 메타와 패치 정보를 설명하는 코치다.
사용자는 현재 좋은 챔피언, 아이템, 룬, 최근 패치 변화와 메타 흐름을 묻는다.
반드시 제공된 근거만 사용하고, 승률·픽률·티어표처럼 근거에 없는 통계는 만들지 않는다.
패치 노트만으로 전체 메타를 확정할 수 없으면 확인 가능한 변화와 추정의 한계를 구분한다.
추천마다 이유와 [근거 N]을 붙이고 자료의 버전을 명시한다.
한국어로 간결하게 답하며 초보자가 이해할 수 있게 게임 용어를 설명한다."""


def build(question, evidence, analysis=None, patch=None, **kwargs):
    prompt = build_base(question, evidence, analysis, patch, **kwargs)
    prompt["system"] = SYSTEM
    prompt["user"] = "게임 단계: 게임 외부의 일반 정보·메타 질문\n\n" + prompt["user"]
    prompt["chars"] = len(prompt["system"]) + len(prompt["user"])
    return prompt
