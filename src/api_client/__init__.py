"""RiftFlow 서버 통신. 배포판 앱은 라이엇·Gemini 대신 이 모듈로 우리 서버만 부른다.

기기 토큰은 처음 요청할 때 서버에서 받아 파일에 저장한다. 토큰은 사용량 제한 단위일 뿐 개인을 식별하지 않는다.
"""
import os
import threading
import time
from importlib import metadata
from pathlib import Path
from urllib.parse import quote as _quote

import requests

from contracts.riot import RateLimitExceeded, RiotApiError

MAX_WAIT_SECONDS = 10     # 서버가 이보다 오래 기다리라고 하면 재시도하지 않고 사용자에게 알린다


def _app_version():
    try:
        return metadata.version("riftflow")
    except metadata.PackageNotFoundError:
        return "0"


class ServerClient:
    def __init__(self, base_url, token_path=None, session=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.token_path = Path(token_path or os.environ.get("RIFTFLOW_DEVICE_TOKEN_PATH") or "data/device_token")
        self.session = session or requests.Session()
        self.sleep = sleep
        self._lock = threading.Lock()
        self._token = None

    @staticmethod
    def quote(value):
        return _quote(str(value), safe="")

    def _headers(self, token=None):
        headers = {"X-RiftFlow-Version": _app_version()}
        if token:
            headers["Authorization"] = "Bearer " + token
        return headers

    def _send(self, method, path, **kwargs):
        try:
            return self.session.request(method, self.base_url + path, timeout=20, **kwargs)
        except requests.exceptions.RequestException as error:
            raise RiotApiError("RiftFlow 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from error

    def token(self, renew=False):
        """저장된 기기 토큰. 없거나 renew면 서버에서 새로 받는다."""
        with self._lock:
            if not renew:
                if self._token:
                    return self._token
                try:
                    saved = self.token_path.read_text(encoding="utf-8").strip()
                except OSError:
                    saved = ""
                if saved:
                    self._token = saved
                    return saved
            response = self._send("POST", "/v1/devices", headers=self._headers())
            if response.status_code != 200:
                raise self._error(response)
            self._token = response.json()["token"]
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(self._token, encoding="utf-8")
            return self._token

    @staticmethod
    def _error(response):
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = "RiftFlow 서버 요청이 실패했습니다 (%s)." % response.status_code
        if response.status_code in (429, 503):
            retry = response.headers.get("Retry-After")
            error = RateLimitExceeded(float(retry) if retry else None)
            error.args = (message,)
            return error
        return RiotApiError(message)

    def get_json(self, path, params=None):
        """GET 요청. 404는 None(찾을 수 없음), 그 밖의 실패는 예외. 잠깐 기다리라는 응답은 한 번 재시도한다."""
        renewed = waited = False
        while True:
            response = self._send("GET", path, params=params, headers=self._headers(self.token()))
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None
            if response.status_code == 401 and not renewed:
                renewed = True
                self.token(renew=True)
                continue
            retry = response.headers.get("Retry-After")
            if response.status_code in (429, 503) and not waited and retry:
                try:
                    seconds = float(retry)
                except ValueError:
                    seconds = MAX_WAIT_SECONDS + 1
                if seconds <= MAX_WAIT_SECONDS:
                    waited = True
                    self.sleep(seconds)
                    continue
            raise self._error(response)


_clients = {}
_clients_lock = threading.Lock()


def shared_client(base_url):
    with _clients_lock:
        if base_url not in _clients:
            _clients[base_url] = ServerClient(base_url)
        return _clients[base_url]
