"""
src/riot/live_client.py

get_live_state 구현.

주의: 공식 SPECTATOR API가 아니라, 라이엇 클라이언트가 실행 중일 때만 열리는
로컬 Live Client Data API(https://127.0.0.1:2999)를 사용한다.
- 인증(API 키) 불필요
- 자체 서명 인증서라 verify=False 필요
- 게임이 실행 중이 아니면 연결 자체가 실패하는데, 이는 오류가 아니라
  LiveMatchStatus.NOT_IN_GAME으로 표현한다 (docs/interfaces.md 합의사항).
"""

import requests
import urllib3

from contracts.riot import ConnectionState, LiveMatchStatus, LiveState

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LIVE_CLIENT_BASE = "https://127.0.0.1:2999/liveclientdata"


def get_live_state() -> LiveState:
    try:
        response = requests.get(
            f"{_LIVE_CLIENT_BASE}/gamestats", timeout=1.0, verify=False
        )
    except requests.exceptions.RequestException:
        # 클라이언트가 꺼져있거나 게임 중이 아님 - 정상적인 상태로 취급
        return LiveState(
            status=LiveMatchStatus.NOT_IN_GAME,
            connection=ConnectionState.DISCONNECTED,
        )

    if response.status_code != 200:
        return LiveState(
            status=LiveMatchStatus.NOT_IN_GAME,
            connection=ConnectionState.CONNECTED,
        )

    data = response.json()
    return LiveState(
        status=LiveMatchStatus.IN_GAME,
        connection=ConnectionState.CONNECTED,
        elapsed_seconds=int(data.get("gameTime", 0)),
    )
