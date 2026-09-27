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
    device_creations_per_hour: int = 20    # IP당 시간당 기기 등록 수 (토큰 대량 발급 방지)

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
            device_creations_per_hour=int(env("RIFTFLOW_DEVICE_CREATIONS_PER_HOUR", "20")),
        )
