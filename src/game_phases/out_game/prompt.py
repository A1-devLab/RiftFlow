"""Gemini prompt for questions asked outside a match.

프롬프트 담당자는 이 파일의 SYSTEM과 build 함수만 수정하면 됩니다.
"""
from rag.prompt import build as build_base


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
