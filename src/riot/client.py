"""
src/riot/client.py

플랫폼 라우팅(kr, na1 ...)과 대륙 라우팅(asia, americas ...)을 감춘
저수준 HTTP 클라이언트. 상태 코드를 contracts의 예외로 변환하는 역할까지만 하고,
"어떤 종류의 없음인지"(소환사 없음 vs 경기 없음)는 호출하는 쪽(service.py)이 판단한다.
"""

from typing import Any, Optional

import requests

from contracts.riot import RiotApiError, RateLimitExceeded

from .config import RiotConfig


class RiotApiClient:
    def __init__(self, config: RiotConfig, timeout: float = 10.0):
        self._config = config
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-Riot-Token": config.api_key})

    def _get(self, host: str, path: str, params: Optional[dict] = None) -> Any:
        url = f"https://{host}.api.riotgames.com{path}"
        response = self._session.get(url, params=params, timeout=self._timeout)

        if response.status_code == 200:
            return response.json()
        if response.status_code in (401, 403):
            raise RiotApiError("API 키가 없거나 유효하지 않습니다. RIOT_API_KEY를 확인하세요.")
        if response.status_code == 404:
            return None  # 호출한 쪽에서 PlayerNotFound / MatchDataUnavailable 등으로 변환
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitExceeded(float(retry_after) if retry_after else None)
        raise RiotApiError(f"요청 실패 ({response.status_code}): {url}")

    def get_platform(self, path: str, params: Optional[dict] = None) -> Any:
        """SUMMONER-V4, LEAGUE-V4 등 플랫폼 라우팅 호출."""
        return self._get(self._config.platform, path, params)

    def get_region(self, path: str, params: Optional[dict] = None) -> Any:
        """ACCOUNT-V1, MATCH-V5 등 대륙 라우팅 호출."""
        return self._get(self._config.region, path, params)
