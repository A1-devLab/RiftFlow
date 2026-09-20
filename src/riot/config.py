"""
src/riot/config.py

.env / 환경변수에서 라이엇 API 설정을 읽어온다.

필요한 환경변수:
- RIOT_API_KEY   (필수, .env.example에 정의된 이름과 동일)
- RIOT_PLATFORM  (선택, 기본값 "kr")   - SUMMONER-V4, LEAGUE-V4용 플랫폼 라우팅
- RIOT_REGION    (선택, 기본값 "asia") - ACCOUNT-V1, MATCH-V5용 대륙 라우팅
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()  # .env 파일이 있으면 읽어서 환경변수로 등록 (없어도 에러 아님)
except ImportError:
    # python-dotenv가 설치되어 있지 않아도 실제 환경변수(RIOT_API_KEY 등)만
    # 설정되어 있으면 동작하도록 조용히 넘어간다.
    pass


@dataclass(frozen=True)
class RiotConfig:
    api_key: str
    platform: str = "kr"
    region: str = "asia"

    @classmethod
    def from_env(cls) -> "RiotConfig":
        api_key = os.environ.get("RIOT_API_KEY")
        if not api_key:
            raise RuntimeError(
                "RIOT_API_KEY 환경변수가 설정되어 있지 않습니다. "
                ".env.example을 .env로 복사한 뒤 키를 채워주세요."
            )
        return cls(
            api_key=api_key,
            platform=os.environ.get("RIOT_PLATFORM", "kr"),
            region=os.environ.get("RIOT_REGION", "asia"),
        )
