"""Gemini prompt for champion select and pre-game preparation.

프롬프트 담당자는 이 파일의 SYSTEM과 build 함수만 수정하면 됩니다.
DB 검색과 Gemini 호출 코드는 다른 폴더에 있습니다.
"""
from rag.prompt import build as build_base


SYSTEM = """너는 리그 오브 레전드 게임 시작 전 코치다.
사용자가 고른 챔피언, 상대 챔피언과 플레이 성향을 바탕으로 룬과 초반 운영 방향을 설명한다.
반드시 제공된 근거만 사용하고, 근거에 없는 룬 효과나 상성 수치는 추측하지 않는다.
추천마다 선택 이유와 [근거 N]을 붙인다.
사용자 취향과 일반적인 안정성 사이에 차이가 있으면 두 선택지를 구분한다.
한국어로 간결하게 답하고 아이템이나 룬의 숫자 ID는 보여 주지 않는다.
근거가 부족하면 필요한 데이터가 무엇인지 분명히 말한다."""


def build(question, evidence, analysis=None, patch=None, **kwargs):
    """공통 RAG 근거 형식에 게임 전 상황과 전용 시스템 지시를 넣습니다."""
    prompt = build_base(question, evidence, analysis, patch, **kwargs)
    analysis = analysis or {}
    lines = ["게임 단계: 게임 시작 전"]
    if analysis.get("opponent"):
        lines.append("상대 챔피언: %s" % analysis["opponent"])
    style = analysis.get("playstyle") or {}
    if style.get("lane_aggression"):
        lines.append("선호하는 라인전: %s" % style["lane_aggression"])
    if style.get("trade_preference"):
        lines.append("선호하는 딜교환: %s" % style["trade_preference"])
    prompt["system"] = SYSTEM
    prompt["user"] = "\n".join(lines) + "\n\n" + prompt["user"]
    prompt["chars"] = len(prompt["system"]) + len(prompt["user"])
    return prompt
