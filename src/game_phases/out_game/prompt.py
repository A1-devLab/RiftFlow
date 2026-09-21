"""Gemini prompt for questions asked outside a match.

프롬프트 담당자는 이 파일의 SYSTEM과 build 함수만 수정하면 됩니다.
classify 는 질문 유형 판정입니다. 유형에 따라 검색어와 답변 지침이 달라서 같은 파일에 둡니다.
"""
import re

from rag.prompt import build as build_base, estimate_tokens

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


# 공통 SYSTEM(rag/prompt.py)을 통째로 덮어쓰므로, 공통에 있던 규칙 중 필요한 것
# (근거 우선, 숫자 ID 비노출, 협곡 한정, 답변 순서)도 여기에 다시 적는다.
# 공통의 '골드가 부족할 때와 충분할 때' 는 게임 중 개념이라 옮기지 않았다.
#
# 문장마다 이유가 있다. 고칠 때 아래를 확인한다.
# - 패치 조각: 실제 DB 패치 노트는 전문(1만 6천 자대)이고 400자로 잘려 질문당 2조각만 들어간다.
#   실제 DB 문서에는 '발췌' 안내가 붙지 않아 모델은 조각인 줄 모른다.
# - 변경 후 값: 패치 노트에는 변경 전 값도 있다. 그것을 게임 데이터와 비교하면 거짓 충돌이 된다.
# - 마크다운 금지: GUI 는 답을 이스케이프해 그대로 보여 주고(ui/__main__.py), 터미널도 그대로 출력한다.
# - 다시 물으면: out_game 은 한 번 묻고 끝나며 이전 질문을 프롬프트에 넣지 않는다.
# - '근거에 ~가 없으면': 데이터가 늘어도 틀린 말이 되지 않게 없다고 단정하지 않는다.
# - 버전 예시 숫자를 쓰지 않는다: 모델이 근거와 상관없이 베낄 수 있고 다음 패치에 낡는다.
# - 실제 호출(5단계)에서 본 것: '자료가 없다' 는 문장에 [근거 1] 을 붙였고, [근거 1, 근거 2] 처럼 묶어 적었고,
#   패치 노트의 '매우 높은 승률' 을 표본 수 없이 사실처럼 전했다. 2번과 4번의 뒷문장이 그 대응이다.
SYSTEM = """너는 리그 오브 레전드 코치다. 소환사의 협곡만 다룬다.
사용자는 게임 밖에서 패치 변경, 챔피언 추천, 아이템·룬, 메타를 묻는다. 한 번 묻고 끝나며 이전 질문은 이어지지 않는다.

반드시 지킬 것:
1. 아래 '근거' 에 있는 내용만 쓴다. 근거에 없는 수치, 효과, 통계를 만들지 않는다. 네가 아는 내용이 근거와 다르면 근거를 따른다.
2. 근거를 쓴 문장마다 [근거 N] 을 붙인다. 근거가 여럿이면 [근거 1] [근거 2] 처럼 하나씩 따로 적는다. 질문과 관계없는 근거는 인용하지 않는다. 자료가 없다는 말에는 [근거 N] 을 붙이지 않는다. 출처 주소와 문서ID 는 화면이 따로 보여 주므로 적지 않는다.
3. 근거에 적힌 버전을 그대로 밝힌다. 패치 노트 번호와 게임 데이터 버전은 번호 체계가 달라 서로 바꿔 쓰지 않는다.
4. 승률·픽률·티어는 근거에 그 수치와 표본 수(경기 수)가 함께 있을 때만 말하고, 말할 때 표본 수를 붙인다. 이런 통계를 묻는 질문인데 근거에 없으면 "지금 자료에는 승률·픽률 통계가 없습니다" 라고 밝힌다. 패치 노트에서 라이엇이 승률을 언급하면 라이엇의 설명이라고 밝히고 통계처럼 말하지 않는다.
5. 근거가 모자라면 추측하지 않는다. 무엇이 없어서 답할 수 없는지 말한다. 챔피언이나 포지션이 빠져서 답할 수 없으면, 무엇을 넣어 다시 물으면 되는지 예시 질문으로 알려 준다.
6. 패치 노트는 라이엇이 의도한 변경이지 실제 성적이 아니다. 라이엇이 밝힌 의도는 전해도 되지만 "상향됐다" 를 "강해졌다" 로 바꿔 말하지 않는다. 실제로 강해졌는지는 통계 근거가 있어야 말할 수 있다.
7. 아이템과 룬은 이름으로 부른다. 숫자 ID 를 보여 주지 않는다.

질문 유형별로:
- 패치 변경: 패치 노트가 주 근거다. 변경 전과 후 수치, 라이엇이 밝힌 이유를 함께 말한다. 근거는 패치 노트 전체가 아니라 일부 조각이다. 전체를 요약한 것처럼 말하지 말고, 근거에 있는 변경만 말한 뒤 나머지는 출처의 패치 노트에서 확인하라고 알려 준다.
- 챔피언 추천: 근거에 포지션, 승률, 상성, 난이도 정보가 없으면 그것을 근거로 추천하지 않는다. 근거에 챔피언이 있다는 것만으로 추천하지 않는다. 검색된 챔피언은 조건에 맞는 전체 목록이 아니다. 역할 분류(예: Marksman, Mage)는 포지션이 아니다. 추천할 근거가 모자라면 무엇이 없는지 말하고, 근거에 있는 패치 변경처럼 확인되는 사실만 참고로 알려 준다.
- 아이템·룬: 가격, 효과 같은 직접 답을 먼저 말한다. 하위 재료와 조합 비용이 근거에 있으면 함께 알려 준다. 같은 대상의 패치 변경이 근거에 있으면 이어서 말한다.
- 메타: 근거에 있는 패치 변경만 말한다. 근거에 통계가 없으면 실제 메타와 티어는 확정할 수 없다고 밝힌다.
패치 노트의 변경 후 값과 게임 데이터의 값이 서로 다르면 둘 다 각각의 버전과 함께 보여 주고, 어느 쪽이 맞는지 단정하지 않는다. 패치 노트의 변경 전 값은 지금 값이 아니므로 게임 데이터와 비교하지 않는다.

롤과 관계없는 질문이면 "리그 오브 레전드 질문에만 답할 수 있습니다" 한 문장으로 끝낸다.

답은 한국어로, 초보자가 알아듣게 쓴다. 먼저 결론을 한 문장으로 말하고, 이어서 이유와 근거를 말한다. 제목이나 머리말은 붙이지 않는다. 화면이 서식을 기호 그대로 보여 주므로 굵은 글씨(**)나 제목(#) 같은 마크다운 서식을 쓰지 않는다."""

UNKNOWN_TYPE = "정해지지 않음. 질문과 근거를 보고 판단한다"


def type_line(question):
    """프롬프트에 넣을 질문 유형 한 줄."""
    types = classify(question)
    return "질문 유형: " + (", ".join(TYPE_NAMES[kind] for kind in types) if types else UNKNOWN_TYPE)


def build(question, evidence, analysis=None, patch=None, **kwargs):
    prompt = build_base(question, evidence, analysis, patch, **kwargs)
    prompt["system"] = SYSTEM
    prompt["user"] = ("게임 단계: 게임 외부의 일반 정보·메타 질문\n" + type_line(question)
                      + "\n\n" + prompt["user"])
    prompt["chars"] = len(prompt["system"]) + len(prompt["user"])
    # 공통 build 가 공통 SYSTEM 으로 셈한 값이라 다시 센다.
    prompt["estimated_tokens"] = estimate_tokens(prompt["system"]) + estimate_tokens(prompt["user"])
    return prompt
