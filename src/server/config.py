"""Server settings from environment variables (server.env on the host)."""
import os
from dataclasses import dataclass
from typing import Tuple


def parse_limits(text):
    """'20/1,100/120' → ((20, 1.0), (100, 120.0)): 창(초)마다 허용 요청 수."""
    limits = []
    for part in text.split(","):
        count, seconds = part.strip().split("/")
        limits.append((int(count), float(seconds)))
    return tuple(limits)


@dataclass(frozen=True)
class Settings:
    riot_api_key: str
    riot_platform: str = "kr"
    riot_region: str = "asia"
    db_path: str = "riftflow-server.db"
    # Personal 키 한도(1초 20회, 2분 100회)보다 조금 낮게 잡는다. 같은 키를 개발용 앱이 함께 쓸 수 있어서다.
    # Production 키로 바꾸면 RIFTFLOW_RIOT_LIMITS=480/10,29000/600 처럼 올린다.
    riot_limits: Tuple[Tuple[int, float], ...] = ((18, 1.0), (90, 120.0))
    device_daily_requests: int = 300       # 기기당 하루 라이엇 데이터 요청 수 (우리 API 기준)
    device_creations_per_hour: int = 5     # IP당 시간당 기기 등록 수 (토큰 대량 발급 방지)
    # AI (2단계). 키가 없으면 AI 경로는 '사용할 수 없음'으로 응답한다.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    # LLM_PROVIDER=hasa면 HASA(OpenAI 호환) 모델만 쓴다 (기본). gemini면 Gemini만.
    llm_provider: str = "hasa"
    hasa_api_key: str = ""                  # 쉼표로 여러 개 (내 키, 팀원 키). 한도가 키마다 더해진다
    hasa_model: str = "nemotron-super-120b"  # 쉼표로 여러 개. 앞 모델을 못 쓰면 다음 모델
    llm_fallback: str = ""                  # 'gemini'면 HASA가 실패할 때 Gemini로 넘긴다 (기본: 넘기지 않음)
    knowledge_db_path: str = "riftflow.db"   # 공식 게임 자료 DB (서버에서 하루 한 번 갱신)
    device_daily_ai: int = 40              # 기기당 하루 AI 요청 수 (룬 추천 재요청 포함)
    # 기기 토큰은 누구나 새로 받을 수 있어서 기기 한도만으로는 막을 수 없다. IP와 서버 전체 한도를 함께 둔다.
    ip_daily_ai: int = 150                 # IP당 하루 AI 요청 수
    global_daily_ai: int = 1500            # 서버 전체 하루 AI 요청 수 (HASA 500회 + Gemini)
    ai_concurrency: int = 4                # 동시에 처리하는 AI 요청 수. 넘으면 바로 '잠시 뒤 다시' (스레드를 붙잡지 않음)

    @property
    def ai_key(self):
        return self.hasa_api_key if self.llm_provider == "hasa" else self.gemini_api_key

    @classmethod
    def from_env(cls):
        key = os.environ.get("RIOT_API_KEY")
        if not key:
            raise RuntimeError("RIOT_API_KEY가 없습니다. server.env에 설정하세요.")
        env = os.environ.get
        return cls(
            riot_api_key=key,
            riot_platform=env("RIOT_PLATFORM", "kr"),
            riot_region=env("RIOT_REGION", "asia"),
            db_path=env("RIFTFLOW_DB_PATH", "riftflow-server.db"),
            riot_limits=parse_limits(env("RIFTFLOW_RIOT_LIMITS", "18/1,90/120")),
            device_daily_requests=int(env("RIFTFLOW_DEVICE_DAILY_REQUESTS", "300")),
            device_creations_per_hour=int(env("RIFTFLOW_DEVICE_CREATIONS_PER_HOUR", "5")),
            gemini_api_key=env("GEMINI_API_KEY", ""),
            gemini_model=env("GEMINI_MODEL") or "gemini-3.5-flash-lite",
            llm_provider=(env("LLM_PROVIDER") or "hasa").strip().lower(),
            hasa_api_key=env("HASA_API_KEY", ""),
            hasa_model=env("HASA_MODEL") or "nemotron-super-120b",
            llm_fallback=(env("LLM_FALLBACK") or "").strip().lower(),
            knowledge_db_path=env("RIFTFLOW_KNOWLEDGE_DB", "riftflow.db"),
            device_daily_ai=int(env("RIFTFLOW_DEVICE_DAILY_AI", "40")),
            ip_daily_ai=int(env("RIFTFLOW_IP_DAILY_AI", "150")),
            global_daily_ai=int(env("RIFTFLOW_GLOBAL_DAILY_AI", "1500")),
            ai_concurrency=int(env("RIFTFLOW_AI_CONCURRENCY", "4")),
        )
