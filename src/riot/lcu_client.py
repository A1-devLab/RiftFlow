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

챔피언 선택(픽창) 실시간 정보:
- 상대의 픽/밴 실시간 상태는 어차피 본인 클라이언트 로컬에서만 봐야 하므로
  (다른 사람 픽창을 원격으로 가져오는 건 애초에 불가능) LCU의
  /lol-champ-select/v1/session 을 그대로 쓰면 된다.
- 폴링용: get_champ_select_session() / start_champ_select_watcher()
- 실시간 push용: ChampSelectSocket (websocket-client 패키지 필요,
  pip install websocket-client). 폴링보다 지연이 적고 요청 부담이 없다.
- 반환값은 ChampSelectSession(픽/밴 현황만) 데이터클래스로 가공한다 - 턴
  순서/타이머/채팅방 정보는 범위 밖으로 뒀다 (필요해지면 확장).
- 주의: 상대팀 정보는 라이엇이 의도적으로 제한한다 — 밴 완료 및 픽 완료된
  것만 세션에 노출되고, 상대가 아직 고르는 중인 실시간 호버 상태는 안 보인다.

경기 종료 후 결과 요약:
- Live Client Data API(2999)에는 딜량/받은 피해량/시야 점수 필드가 없다.
  이 값들은 게임이 끝난 직후 클라이언트가 결과 화면을 띄울 때 쓰는
  LCU의 /lol-end-of-game/v1/eog-stats-block 에서만 가져올 수 있다.
- 원본: get_end_of_game_stats() / 가공된 요약: get_post_game_summary()
- 결과 화면이 뜨기까지 살짝 지연이 있을 수 있어서, live_client의 on_end
  콜백 직후에는 wait_for_post_game_summary()로 잠깐 재시도하며 기다리는 걸
  권장한다.
"""

import base64
import json
import ssl
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

import psutil
import requests
import urllib3

from contracts.riot import (
    ChampSelectMember,
    ChampSelectSession,
    ClientNotRunning,
    PlayerIdentity,
    PostGameSummary,
    RiotApiError,
)

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


def _lcu_get(port: int, password: str, endpoint: str) -> Optional[Any]:
    """LCU에 GET 요청을 보내고 JSON을 반환한다.

    통신 실패나 200이 아닌 응답은 예외 대신 None으로 처리한다 — 이 값을 쓰는
    폴링 루프(get_champ_select_session 등)에서는 "아직 그 단계가 아님"과
    "에러"를 굳이 구분할 필요가 없기 때문이다. 예외가 필요한 곳(예: 로그인
    조회)에서는 호출부에서 별도로 처리한다.
    """
    token = base64.b64encode(f"riot:{password}".encode()).decode()
    try:
        response = requests.get(
            f"https://127.0.0.1:{port}{endpoint}",
            headers={"Authorization": f"Basic {token}"},
            timeout=3.0,
            verify=False,
        )
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


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


def get_gameflow_phase() -> Optional[str]:
    """현재 게임 진행 단계를 반환한다.

    예: "None", "Lobby", "Matchmaking", "ChampSelect", "InProgress",
    "EndOfGame" 등. 클라이언트가 꺼져있거나 조회에 실패하면 None.
    """
    credentials = _find_lcu_credentials()
    if credentials is None:
        return None

    port, password = credentials
    phase = _lcu_get(port, password, "/lol-gameflow/v1/gameflow-phase")
    return phase if isinstance(phase, str) else None


def _parse_champ_select_member(raw: dict) -> ChampSelectMember:
    """myTeam/theirTeam의 원본 슬롯 항목 하나를 ChampSelectMember로 변환한다."""
    return ChampSelectMember(
        cell_id=raw.get("cellId"),
        champion_id=raw.get("championId", 0),
        assigned_position=raw.get("assignedPosition", ""),
        puuid=raw.get("puuid") or None,
    )


def _parse_bans(raw: dict) -> Tuple[List[int], List[int]]:
    """확정된 밴 목록을 뽑아낸다.

    주의 (실제로 겪은 문제): raw["bans"]["myTeamBans"]/["theirTeamBans"]는
    밴이 확정돼도 계속 빈 리스트로 온다 (적어도 지금 클라이언트 버전에서는
    믿을 수 없음). 실제 밴 정보는 raw["actions"]의 각 액션 중
    type=="ban"이고 completed==True인 것의 championId에만 있다 - 그래서
    이쪽에서 직접 집계하고, 혹시 비어있으면(클라이언트 버전에 따라 다를 수
    있으니) bans 필드로 폴백한다.
    """
    my_bans: List[int] = []
    their_bans: List[int] = []
    for action_group in raw.get("actions", []):
        for action in action_group:
            if action.get("type") != "ban" or not action.get("completed"):
                continue
            champion_id = action.get("championId")
            if not champion_id:
                continue
            if action.get("isAllyAction"):
                my_bans.append(champion_id)
            else:
                their_bans.append(champion_id)

    if not my_bans and not their_bans:
        bans = raw.get("bans", {})
        my_bans = bans.get("myTeamBans", [])
        their_bans = bans.get("theirTeamBans", [])

    return my_bans, their_bans


def _parse_champ_select_session(raw: dict) -> ChampSelectSession:
    """LCU 원본 챔피언 선택 세션을 ChampSelectSession(픽/밴 현황만)으로 가공한다.

    턴 순서/타이머/채팅방 정보 등은 범위 밖으로 뒀다 (필요해지면 확장).
    """
    my_bans, their_bans = _parse_bans(raw)
    return ChampSelectSession(
        my_team=[_parse_champ_select_member(m) for m in raw.get("myTeam", [])],
        their_team=[_parse_champ_select_member(m) for m in raw.get("theirTeam", [])],
        my_bans=my_bans,
        their_bans=their_bans,
        local_player_cell_id=raw.get("localPlayerCellId"),
    )


def get_champ_select_session() -> Optional[ChampSelectSession]:
    """현재 챔피언 선택(픽창)의 픽/밴 현황을 가져온다.

    반환: ChampSelectSession (필드는 contracts.riot.ChampSelectSession 참고).
    상대팀(their_team)은 밴 완료 및 픽 완료된 것만 champion_id가 채워지고,
    아직 고르는 중인 실시간 호버는 반영되지 않는다 (라이엇이 의도적으로
    막아놓은 부분).

    챔피언 선택 중이 아니거나 클라이언트가 꺼져있으면 None을 반환한다
    (예외를 던지지 않음 — 폴링 루프에서 그대로 쓰기 편하도록).
    """
    credentials = _find_lcu_credentials()
    if credentials is None:
        return None

    port, password = credentials
    raw = _lcu_get(port, password, "/lol-champ-select/v1/session")
    if raw is None:
        return None
    return _parse_champ_select_session(raw)


def get_end_of_game_stats() -> Optional[dict]:
    """게임이 끝난 직후(결과 화면)에 LCU가 주는 원본 종료 통계를 가져온다.

    가한 피해, 받은 피해, 시야 점수 등 Live Client Data API(2999)에는 없는
    값들이 여기 다 들어있다 - 클라이언트가 결과 화면을 띄울 때 쓰는 바로 그
    데이터라 정확하다. 결과 화면이 뜨기 전(로딩/이동 중)이거나 이미 다음
    로비로 넘어간 뒤에는 None을 반환한다.

    주의: 이 경로는 공식 문서가 없는 내부 API라 클라이언트 버전이 바뀌면서
    실제로 한 번 바뀐 적이 있다(예전엔 eogstats였는데 지금은 이 이름이다).
    또 404가 나면, 클라이언트에 로그인된 채로 GET /help를 호출해서
    "end-of-game"/"eog"가 들어간 함수 이름을 다시 찾아봐야 한다.
    """
    credentials = _find_lcu_credentials()
    if credentials is None:
        return None

    port, password = credentials
    return _lcu_get(port, password, "/lol-end-of-game/v1/eog-stats-block")


def _find_local_player_and_team(data: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """teams[*].players 중에서 isLocalPlayer=True인 본인 항목과 소속 팀을 찾는다.

    최상위의 data["localPlayer"]가 사실 같은 항목을 미리 뽑아둔 편의 필드인데,
    거기엔 팀의 승/패(isWinningTeam)가 없어서 teams 쪽에서 다시 찾아야 한다.
    teams에서 못 찾으면 최상위 localPlayer로 폴백하고, teamId로 소속 팀만
    다시 매칭한다.
    """
    teams = data.get("teams", [])

    for team in teams:
        for player in team.get("players", []):
            if player.get("isLocalPlayer"):
                return player, team

    local_player = data.get("localPlayer")
    if local_player is not None:
        team = next(
            (t for t in teams if t.get("teamId") == local_player.get("teamId")), None
        )
        return local_player, team

    return None, None


def _stat(stats: dict, camel_key: str, caps_key: str, default: int = 0):
    """camelCase 필드를 우선 쓰고, 없으면 예전 ALL_CAPS 이름으로 폴백한다.

    지금 클라이언트는 같은 값을 두 이름 체계(예: "kills"와 "CHAMPIONS_KILLED")
    로 같이 주지만, 혹시 한쪽만 오는 경우에 대비해 폴백을 둔다.
    """
    if camel_key in stats:
        return stats[camel_key]
    return stats.get(caps_key, default)


def get_post_game_summary() -> Optional[PostGameSummary]:
    """get_end_of_game_stats()를 화면에서 바로 쓰기 편한 형태로 가공한다.

    반환: PostGameSummary (필드는 contracts.riot.PostGameSummary 참고).
    결과 화면이 아직 없거나(게임 중/로비) 본인 항목을 못 찾으면 None.
    """
    data = get_end_of_game_stats()
    if data is None:
        return None

    my_player, my_team = _find_local_player_and_team(data)
    if my_player is None or my_team is None:
        return None

    stats = my_player.get("stats", {})

    kills = _stat(stats, "kills", "CHAMPIONS_KILLED")
    deaths = _stat(stats, "deaths", "NUM_DEATHS")
    assists = _stat(stats, "assists", "ASSISTS")
    cs = _stat(stats, "totalMinionsKilled", "MINIONS_KILLED") + _stat(
        stats, "neutralMinionsKilled", "NEUTRAL_MINIONS_KILLED"
    )
    damage_dealt = _stat(stats, "totalDamageDealtToChampions", "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS")
    damage_taken = _stat(stats, "totalDamageTaken", "TOTAL_DAMAGE_TAKEN")
    vision_score = _stat(stats, "visionScore", "VISION_SCORE")

    game_duration = data.get("gameLength", 0)
    minutes = game_duration / 60 if game_duration else 0

    team_kills = sum(
        _stat(p.get("stats", {}), "kills", "CHAMPIONS_KILLED")
        for p in my_team.get("players", [])
    )
    kill_participation = (kills + assists) / team_kills * 100 if team_kills > 0 else 0.0

    return PostGameSummary(
        game_duration_seconds=game_duration,
        result="WIN" if my_team.get("isWinningTeam") else "LOSS",
        kills=kills,
        deaths=deaths,
        assists=assists,
        cs=cs,
        cs_per_min=(cs / minutes) if minutes > 0 else 0.0,
        kill_participation_pct=kill_participation,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        vision_score=vision_score,
    )



def wait_for_post_game_summary(
    timeout: float = 15.0, interval: float = 1.0
) -> Optional[PostGameSummary]:
    """결과 화면이 뜰 때까지 잠깐 기다렸다가 get_post_game_summary()를 반환한다.

    live_client의 on_end 콜백이 호출된 직후 이걸 부르면 된다 - Live Client
    Data API가 끊긴 시점과 결과 화면(eogstats)이 뜨는 시점 사이의 짧은 지연을
    흡수해준다. timeout 동안도 못 찾으면 None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        summary = get_post_game_summary()
        if summary is not None:
            return summary
        time.sleep(interval)
    return None


def start_champ_select_watcher(
    on_update: Callable[[ChampSelectSession], None],
    on_end: Optional[Callable[[], None]] = None,
    interval: float = 1.0,
) -> threading.Thread:
    """백그라운드 스레드에서 챔피언 선택 세션을 주기적으로 폴링한다.

    - 아직 챔피언 선택에 들어가기 전에는 조용히 기다린다 (에러 없음).
    - 챔피언 선택 중에는 매 interval마다 on_update(session)을 호출한다
      (변경 여부와 무관하게 매번 호출 — 필요하면 상위에서 이전 값과 diff
      비교해서 실제로 바뀐 것만 UI에 반영하면 된다).
    - 챔피언 선택이 끝나면(게임 시작 또는 dodge) on_end()를 한 번 호출하고
      스레드를 종료한다.

    폴링 부담이 걱정되거나 지연을 더 줄이고 싶으면 ChampSelectSocket(웹소켓
    기반 실시간 push)을 대신 쓴다.
    """

    def _watch():
        entered = False
        while True:
            session = get_champ_select_session()
            if session is not None:
                entered = True
                on_update(session)
            elif entered:
                if on_end is not None:
                    on_end()
                return
            time.sleep(interval)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


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


class ChampSelectSocket:
    """LCU 웹소켓을 통해 챔피언 선택 세션 변경을 실시간(push)으로 받는다.

    start_champ_select_watcher()의 폴링과 달리 요청을 계속 반복하지 않고,
    세션이 실제로 바뀔 때만 이벤트를 받는다 (지연이 적고 부담이 없다).
    pip install websocket-client 필요.

    사용 예:
        socket = ChampSelectSocket(on_update=lambda session: print(session))
        socket.start()
        ...
        socket.stop()

    주의: 클라이언트가 꺼져있거나 재시작되면 자동으로 재연결을 시도한다.
    """

    _SUBSCRIBE_URI = "/lol-champ-select/v1/session"

    def __init__(
        self,
        on_update: Callable[[ChampSelectSession], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        self._on_update = on_update
        self._on_error = on_error
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False

    def start(self) -> None:
        """백그라운드 스레드에서 연결을 시작한다."""
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """연결을 끊고 백그라운드 스레드를 종료한다."""
        self._stop_requested = True
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            import websocket  # websocket-client 패키지 (지연 import: 폴링만
            # 쓰는 경우에는 이 패키지가 없어도 lcu_client.py 자체는 문제없이
            # 동작하도록)
        except ImportError as e:
            if self._on_error is not None:
                self._on_error(e)
            return

        while not self._stop_requested:
            credentials = _find_lcu_credentials()
            if credentials is None:
                time.sleep(2.0)
                continue

            port, password = credentials
            token = base64.b64encode(f"riot:{password}".encode()).decode()

            try:
                ws = websocket.create_connection(
                    f"wss://127.0.0.1:{port}/",
                    header=[f"Authorization: Basic {token}"],
                    sslopt={"cert_reqs": ssl.CERT_NONE},  # LCU는 자체 서명 인증서 사용
                    timeout=5.0,
                )
            except Exception as e:
                if self._on_error is not None:
                    self._on_error(e)
                time.sleep(2.0)
                continue

            self._ws = ws
            # LCU의 WAMP 기반 프로토콜: [5, "OnJsonApiEvent"]를 보내면 모든 LCU
            # JSON API 엔드포인트의 변경 이벤트를 구독하게 된다. 특정 URI만
            # 구독하는 필터도 있지만, 여기서는 받은 뒤 uri로 직접 걸러낸다.
            try:
                ws.send(json.dumps([5, "OnJsonApiEvent"]))
            except Exception as e:
                if self._on_error is not None:
                    self._on_error(e)
                self._close_ws()
                time.sleep(2.0)
                continue

            try:
                while not self._stop_requested:
                    message = ws.recv()
                    if message:
                        self._handle_message(message)
            except Exception as e:
                if not self._stop_requested and self._on_error is not None:
                    self._on_error(e)
            finally:
                self._close_ws()

            if not self._stop_requested:
                time.sleep(1.0)  # 클라이언트 재시작 등에 대비한 재연결 대기

    def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _handle_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except (ValueError, TypeError):
            return

        # LCU 이벤트 프레임 형식: [8, "OnJsonApiEvent", {"uri": ..., "data": ...}]
        if not isinstance(payload, list) or len(payload) < 3:
            return

        event = payload[2]
        if not isinstance(event, dict):
            return

        if event.get("uri") == self._SUBSCRIBE_URI:
            data = event.get("data")
            if isinstance(data, dict):
                self._on_update(_parse_champ_select_session(data))
