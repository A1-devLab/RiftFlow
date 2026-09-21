"""
src/riot/lcu_client.py

라이엇 클라이언트(LCU)에 로그인된 소환사 정보를 가져온다.

Live Client Data API(2999)와의 차이:
- Live Client Data API는 실제 게임에 "접속 중"일 때만 동작한다 (인증 불필요)
- LCU API는 클라이언트에 "로그인만" 해도 동작한다 (인증 필요)
  -> "게임에 로그인하면 바로 UI 전환" 요구사항에는 이쪽을 써야 한다

주의 (실제로 겪은 문제): LCU가 주는 puuid/summonerId/accountId는 클라이언트
내부용 원본 ID라서, 공식 개발자 API가 요구하는 "암호화된" ID와 다르다
(공식 puuid는 78자, LCU가 주는 값은 36자짜리 일반 UUID). 그래서 LCU의 puuid를
그대로 MATCH-V5 같은 공식 API에 넘기면 400 오류가 난다.
-> LCU에서는 gameName/tagLine만 가져오고, 진짜 puuid는 ACCOUNT-V1(get_player)로
   다시 조회해서 얻는다.

인증 정보(포트/비밀번호)는 실행 중인 LeagueClientUx 프로세스의
커맨드라인 인자에서 추출한다. pip install psutil 필요.
"""

import base64
import threading
import time
from typing import Callable, Optional, Tuple

import psutil
import requests
import urllib3

from contracts.riot import ClientNotRunning, PlayerIdentity, RiotApiError

from .service import get_player

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROCESS_NAMES = {"LeagueClientUx.exe", "LeagueClientUx"}


def _find_lcu_credentials() -> Optional[Tuple[int, str]]:
    """실행 중인 LeagueClientUx 프로세스에서 포트/비밀번호를 찾는다."""
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] not in _PROCESS_NAMES:
                continue
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        port = password = None
        for arg in cmdline:
            if arg.startswith("--app-port="):
                port = int(arg.split("=", 1)[1])
            elif arg.startswith("--remoting-auth-token="):
                password = arg.split("=", 1)[1]
        if port and password:
            return port, password
    return None


def _current_summoner_data(credentials: Tuple[int, str]) -> Optional[dict]:
    """LCU의 현재 소환사 응답을 확인한다. 로그인 전에는 None을 반환한다."""
    port, password = credentials
    token = base64.b64encode(f"riot:{password}".encode()).decode()
    response = requests.get(
        f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
        headers={"Authorization": f"Basic {token}"},
        timeout=3.0,
        verify=False,
    )
    if response.status_code != 200:
        return None
    data = response.json()
    if not isinstance(data, dict):
        return None
    return data


def is_client_logged_in() -> bool:
    """프로세스 존재뿐 아니라 LCU의 현재 소환사 응답으로 로그인을 확인한다."""
    credentials = _find_lcu_credentials()
    if credentials is None:
        return False
    try:
        data = _current_summoner_data(credentials)
    except (requests.exceptions.RequestException, ValueError):
        return False
    return bool(data and data.get("gameName") and data.get("tagLine"))


def get_current_summoner() -> PlayerIdentity:
    """현재 클라이언트에 로그인된 소환사 정보를 가져온다 (게임 접속 불필요).

    LCU에서 gameName/tagLine만 가져오고, 실제 puuid는 ACCOUNT-V1을 통해
    다시 조회한다 (LCU의 puuid는 공식 API와 호환되지 않는 내부 ID이기 때문).

    Raises:
        ClientNotRunning: 클라이언트가 꺼져있거나 로그인 전
        PlayerNotFound: LCU에서 가져온 이름으로 ACCOUNT-V1 조회가 실패한 경우
        RiotApiError: 그 외 통신 오류 (RIOT_API_KEY 필요)
    """
    credentials = _find_lcu_credentials()
    if credentials is None:
        raise ClientNotRunning("라이엇 클라이언트가 꺼져있거나 로그인 전입니다.")

    try:
        data = _current_summoner_data(credentials)
    except requests.exceptions.RequestException as e:
        raise RiotApiError("LCU 통신 오류입니다.") from e

    if data is None:
        raise ClientNotRunning("아직 로그인이 완료되지 않았습니다.")

    game_name = data.get("gameName")
    tag_line = data.get("tagLine")

    if not game_name or not tag_line:
        raise RiotApiError("LCU 응답에 gameName/tagLine이 없습니다.")

    # LCU의 puuid/summonerId는 내부 ID라 공식 API와 호환되지 않으므로,
    # gameName#tagLine으로 공식 API(ACCOUNT-V1)를 다시 조회해서
    # 진짜 암호화된 puuid가 담긴 PlayerIdentity를 만든다.
    return get_player(f"{game_name}#{tag_line}")


def start_login_watcher(
    on_login: Callable[[PlayerIdentity], None],
    interval: float = 2.0,
) -> threading.Thread:
    """백그라운드 스레드에서 로그인 여부를 주기적으로 확인하다가,
    로그인이 감지되면 on_login(player)를 한 번 호출하고 스레드를 종료한다.

    UI 프레임워크(Tkinter, PyQt 등)에 상관없이 쓸 수 있게 별도 스레드로 동작한다.
    주의: on_login 콜백에서 UI 위젯을 직접 갱신하면 스레드 안전 문제가 생길 수 있으니,
    각 프레임워크의 메인 스레드 전달 방식(예: Tkinter의 root.after())을 거쳐야 한다.
    """

    def _watch():
        while True:
            try:
                player = get_current_summoner()
                on_login(player)
                return
            except RiotApiError:
                time.sleep(interval)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread
