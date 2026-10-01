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


class InvalidApiKey(RiotApiError):
    """키가 없거나 만료됨 (401/403). 다시 시도해도 같으므로 감시 루프는 멈춘다."""


def _seconds(value):
    """Retry-After 값을 초로. 숫자가 아니면(HTTP 날짜 등) None."""
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


class RiotApiClient:
    def __init__(self, config: RiotConfig, timeout: float = 10.0):
        self._config = config
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-Riot-Token": config.api_key})

    def _get(self, host: str, path: str, params: Optional[dict] = None) -> Any:
        url = f"https://{host}.api.riotgames.com{path}"
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.exceptions.RequestException as error:
            # 와이파이 끊김·DNS 실패를 RiotApiError로 바꾼다. 그대로 두면 RiotApiError만 잡는 로그인 감시 스레드가 죽었다.
            raise RiotApiError("Riot 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from error

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as error:
                raise RiotApiError("Riot 응답을 읽지 못했습니다.") from error
        if response.status_code in (401, 403):
            raise InvalidApiKey("API 키가 없거나 유효하지 않습니다. RIOT_API_KEY를 확인하세요.")
        if response.status_code == 404:
            return None  # 호출한 쪽에서 PlayerNotFound / MatchDataUnavailable 등으로 변환
        if response.status_code == 429:
            raise RateLimitExceeded(_seconds(response.headers.get("Retry-After")))
        raise RiotApiError(f"요청 실패 ({response.status_code}): {url}")

    def get_platform(self, path: str, params: Optional[dict] = None) -> Any:
        """SUMMONER-V4, LEAGUE-V4 등 플랫폼 라우팅 호출."""
        return self._get(self._config.platform, path, params)

    def get_region(self, path: str, params: Optional[dict] = None) -> Any:
        """ACCOUNT-V1, MATCH-V5 등 대륙 라우팅 호출."""
        return self._get(self._config.region, path, params)
