# riot 모듈 (src/riot) 사용 설명서

`src/riot`이 다른 모듈(knowledge, rag, ui)에 제공하는 함수와 데이터 형식을 정리한 문서.

## 준비물

- 환경변수 `RIOT_API_KEY` 필요 (`.env` 파일)
- 사용법: `from riot import get_player, get_recent_matches, get_solo_rank, get_live_state, get_scoreboard, get_team_gold_totals, get_post_game_summary`
- 의존성: pyproject.toml 내의 dependencies에 추가해놨으니 터미널에서 'pip install -e .' 을 입력하여 설치. 추가로 필요한 패키지 없음(표준 라이브러리 `dataclasses`/`enum`/`typing`만 사용)

`get_player`, `get_recent_matches`, `get_solo_rank`는 라이엇 API 키가 필요 (테스트 용으로 riot developer portal에서 로그인 후 발급 or 호영님께 요청)
`get_live_state`, `get_scoreboard`, `get_team_gold_totals`, `get_post_game_summary`는 API 키가 필요 없지만, **이 코드를 실행하는 컴퓨터에서 라이엇 클라이언트가 켜져 있어야** 동작함.

---

## 1. get_player

Riot ID로 소환사 식별 정보를 조회한다.

**입력**

| 이름 | 타입 | 설명 |
|---|---|---|
| `riot_id` | `str` | `"게임명#태그"` 형식. 예: `"hide on bush#KR1"` |

**출력**: `PlayerIdentity`

| 필드 | 타입 | 설명 |
|---|---|---|
| `puuid` | `str` | 내부 기준 식별자. 다른 함수 호출 시 이 값을 넘긴다 |
| `riot_id` | `str` | `"게임명#태그"` (API가 확인해준 정확한 표기) |
| `summoner_level` | `int \| None` | 없을 수 있음 |
| `profile_icon_id` | `int \| None` | 없을 수 있음 |

**예외**

| 예외 | 발생 조건 |
|---|---|
| `ValueError` | `riot_id`에 `#`이 없는 형식일 때 |
| `PlayerNotFound` | 존재하지 않는 Riot ID |
| `RateLimitExceeded` | API 호출 제한(429) |
| `RiotApiError` | API 키 오류 등 그 외 오류 |

---

## 2. get_recent_matches

PUUID로 최근 경기 요약 목록을 조회한다.

**입력**

| 이름 | 타입 | 설명 |
|---|---|---|
| `puuid` | `str` | `get_player`가 반환한 puuid |
| `count` | `int` | 조회할 경기 수 |

**출력**: `list[MatchSummary]`

| 필드 | 타입 | 설명 |
|---|---|---|
| `match_id` | `str` | 경기 고유 ID |
| `played_at_epoch` | `int` | 경기 시작 시각 (UTC epoch seconds) |
| `game_duration_seconds` | `int` | 경기 길이 (초 단위로 통일) |
| `game_mode` | `str` | 예: `"CLASSIC"`, `"ARAM"` |
| `champion_name` | `str` | 챔피언 영문 ID (예: `"Katarina"`) |
| `win` | `bool` | 승리 여부 |
| `kills` / `deaths` / `assists` | `int` | KDA |
| `cs` | `int \| None` | 미니언+정글 몹 처치 수 |

**예외**

| 예외 | 발생 조건 |
|---|---|
| `MatchDataUnavailable` | 최근 경기 기록이 없음 |
| `RateLimitExceeded` | API 호출 제한(429) |
| `RiotApiError` | 그 외 오류 |

---

## 3. get_solo_rank

솔로랭크(RANKED_SOLO_5x5) 티어 정보를 조회한다.

**입력**

| 이름 | 타입 | 설명 |
|---|---|---|
| `puuid` | `str` | `get_player`가 반환한 puuid |

**출력**: `RankInfo | None`

- 솔로랭크 기록이 없으면(언랭크) **예외가 아니라 `None`을 반환**한다. 호출하는 쪽에서 `None` 체크 필요.

| 필드 | 타입 | 설명 |
|---|---|---|
| `queue_type` | `str` | `"RANKED_SOLO_5x5"` |
| `tier` | `str` | 예: `"GOLD"` |
| `division` | `str` | 예: `"II"` |
| `league_points` | `int` | LP |
| `wins` / `losses` | `int` | 승/패 수 |

**예외**

| 예외 | 발생 조건 |
|---|---|
| `RateLimitExceeded` | API 호출 제한(429) |
| `RiotApiError` | 그 외 오류 |

---

## 4. get_live_state

현재 라이엇 클라이언트의 실시간 게임 상태를 조회한다. **API 키 불필요.**

**입력**: 없음

**출력**: `LiveState`

| 필드 | 타입 | 설명 |
|---|---|---|
| `status` | `LiveMatchStatus` | `IN_GAME` 또는 `NOT_IN_GAME` |
| `connection` | `ConnectionState` | `CONNECTED` 또는 `DISCONNECTED` |
| `elapsed_seconds` | `int \| None` | `IN_GAME`일 때만 값 존재 |

**예외 없음** — 게임이 실행 중이 아닌 상태는 오류가 아니라 `status=NOT_IN_GAME`으로 표현한다.

**주의**: 로컬 Live Client Data API(`127.0.0.1:2999`)를 사용하므로, **이 함수를 호출하는 프로세스와 게임이 반드시 같은 컴퓨터에서 실행 중이어야** 한다.

---

## 5. get_scoreboard

인게임 실시간 스코어보드를 조회한다. **API 키 불필요**, 실제 게임 접속 중에만 동작.

**입력**: 없음

**출력**: `list[PlayerLiveStats] | None` (게임 중이 아니면 `None`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `summoner_name` | `str \| None` | Riot ID 전환 과정에서 비어올 수 있음 |
| `champion_name` | `str` | |
| `team` | `str` | `"ORDER"`(블루팀) 또는 `"CHAOS"`(레드팀) - 라이엇 API가 주는 값 그대로 |
| `position` | `str` | `"TOP"`/`"JUNGLE"`/`"MIDDLE"`/`"BOTTOM"`/`"UTILITY"`, 극초반엔 `"NONE"` |
| `level` | `int` | |
| `kills` / `deaths` / `assists` | `int` | |
| `cs` | `int` | 미니언 + 정글 몹 처치 수 |
| `is_dead` | `bool` | |
| `respawn_timer` | `float` | |
| `items` | `list[dict]` | 아이템 원본 (아직 별도 타입 없음) |
| `estimated_gold` | `float` | 추정치 - 보유 아이템 가격 합계(Data Dragon 정식 가격표 기준). **미구매 잔액은 반영 안 됨** |

**예외 없음** — 게임 중이 아니면 `None`.

---

## 6. get_team_gold_totals

팀별 추정 골드 합계("글로벌 골드")를 계산한다.

**입력**

| 이름 | 타입 | 설명 |
|---|---|---|
| `scoreboard` | `list[PlayerLiveStats] \| None` | 생략하면 내부에서 `get_scoreboard()`를 직접 호출 |

**출력**: `TeamGoldTotals | None` (게임 중이 아니면 `None`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `order` | `float` | `team == "ORDER"`인 선수들의 `estimated_gold` 합 |
| `chaos` | `float` | `team == "CHAOS"`인 선수들의 `estimated_gold` 합 |

**예외 없음**.

---

## 7. get_post_game_summary / wait_for_post_game_summary

경기 종료 후 결과 화면의 요약 통계를 조회한다.

**입력**

| 함수 | 입력 |
|---|---|
| `get_post_game_summary()` | 없음 |
| `wait_for_post_game_summary(timeout=15.0, interval=1.0)` | 결과 화면이 뜰 때까지 재시도하며 대기 (Live Client Data API 연결이 끊긴 시점과 결과 화면이 뜨는 시점 사이의 짧은 지연을 흡수) |

**출력**: `PostGameSummary | None` (결과 화면이 아직 없거나 본인 항목을 못 찾으면 `None`, `wait_for_post_game_summary`는 timeout 지나도 못 찾으면 `None`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `game_duration_seconds` | `int` | |
| `result` | `str` | `"WIN"` 또는 `"LOSS"` |
| `kills` / `deaths` / `assists` | `int` | |
| `cs` | `int` | |
| `cs_per_min` | `float` | |
| `kill_participation_pct` | `float` | `(kills+assists) / 팀 전체 킬 * 100` |
| `damage_dealt` | `int` | 챔피언 대상 딜량 |
| `damage_taken` | `int` | |
| `vision_score` | `int` | |

**예외 없음**.

**주의**: 이 함수가 쓰는 LCU 경로(`/lol-end-of-game/v1/eog-stats-block`)는 비공식 API라 클라이언트 버전이 바뀌면서 실제로 한 번 바뀐 적이 있다(예전 `eogstats` → 지금 `eog-stats-block`). 다시 데이터가 안 나오면, 클라이언트에 로그인된 채로 `GET /help`를 호출해서 함수 목록에서 `end`+`game`이 들어간 이름을 다시 찾아봐야 한다.

---

## 8. get_champ_select_session / start_champ_select_watcher / ChampSelectSocket

챔피언 선택(픽창)의 **픽/밴 현황**을 조회한다. LCU 인증 필요(클라이언트 로그인 상태). 턴 순서·타이머·채팅방 정보는 범위 밖 (필요해지면 확장 예정).

**입력**

| 함수 | 입력 |
|---|---|
| `get_champ_select_session()` | 없음 |
| `start_champ_select_watcher(on_update, on_end=None, interval=1.0)` | 콜백 `on_update(session: ChampSelectSession)`, `on_end()` |
| `ChampSelectSocket(on_update, on_error=None)` | 콜백 `on_update(session: ChampSelectSession)`. `.start()`/`.stop()`로 제어. 폴링 대신 웹소켓 push (`pip install websocket-client` 필요) |

**출력**: `ChampSelectSession | None` (챔피언 선택 중이 아니면 `None`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `my_team` | `list[ChampSelectMember]` | 우리팀 5명 |
| `their_team` | `list[ChampSelectMember]` | 상대팀 - 밴 완료/픽 완료된 것만 노출 (호버 상태 안 보임) |
| `my_bans` | `list[int]` | 우리팀이 밴한 championId 목록 |
| `their_bans` | `list[int]` | 상대팀이 밴한 championId 목록 |
| `local_player_cell_id` | `int` | `my_team` 중 본인 슬롯의 `cell_id` |

`ChampSelectMember` 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `cell_id` | `int` | 슬롯 번호 |
| `champion_id` | `int` | `0`이면 아직 픽 안 함 |
| `assigned_position` | `str` | 예: `"top"`/`"jungle"`/`"middle"`/`"bottom"`/`"utility"`, 없으면 `""` |
| `puuid` | `str \| None` | 상대팀은 픽 완료 전까지 `None`일 수 있음 |

**예외 없음** — 챔피언 선택 중이 아니면 `None`, 조회 실패도 `None`.

**주의**: `start_champ_select_watcher`는 즉시 리턴하고 **콜백은 별도 백그라운드 스레드에서 호출**된다 (아래 "알아둘 것" 참고).

---

## 사용 예시

```python
import riot

player = riot.get_player("hide on bush#KR1")
print(player.puuid, player.summoner_level)

matches = riot.get_recent_matches(player.puuid, count=3)
for m in matches:
    print(m.champion_name, m.win, m.kills, m.deaths, m.assists)

rank = riot.get_solo_rank(player.puuid)
if rank:
    print(rank.tier, rank.division, rank.league_points)
else:
    print("언랭크")

state = riot.get_live_state()
print(state.status, state.connection, state.elapsed_seconds)

scoreboard = riot.get_scoreboard()
if scoreboard:
    for p in scoreboard:
        print(p.champion_name, p.kills, p.deaths, p.assists, p.estimated_gold)

    totals = riot.get_team_gold_totals(scoreboard)
    print("ORDER 골드:", totals.order, "| CHAOS 골드:", totals.chaos)

summary = riot.wait_for_post_game_summary()
if summary:
    print(summary.result, summary.kills, summary.deaths, summary.assists)

def on_champ_select_update(session):
    for member in session.my_team:
        print(member.cell_id, member.champion_id, member.assigned_position)

riot.start_champ_select_watcher(on_update=on_champ_select_update)
```

---

## 아직 정식 인터페이스에 없는 것 (서브모듈 직접 import 필요)

경기 결과의 **원본** 데이터(10명 전원의 raw 통계)와 인게임 원본 데이터는 아직 `__init__.py`의 `__all__`에 편입되지 않았다. 필요하면 서브모듈을 직접 가져와서 써야 한다:

```python
from riot import lcu_client, live_client
```

이 함수들은 (위 8개와 달리) **`contracts.riot`의 데이터클래스가 아니라 일반 `dict`/`list`를 반환**한다 — 예: `data["teams"]`처럼 키로 접근. 다른 모듈에서 정식으로 쓰게 되면, `contracts.riot`에 타입을 추가하고 `__init__.py`에 편입하는 걸 권장한다.

### `lcu_client` (LCU 인증 필요)

| 함수 | 설명 |
|---|---|
| `get_gameflow_phase()` | `"Lobby"`/`"ChampSelect"`/`"InProgress"`/`"EndOfGame"` 등 현재 단계. `str \| None` |
| `get_end_of_game_stats()` | 결과 화면 원본 - **10명 전원**의 통계 포함 (`get_post_game_summary()`는 이 중 본인 것만 가공). `dict \| None` |

### `live_client` (인증 불필요, 게임 접속 중에만 동작)

| 함수 | 설명 |
|---|---|
| `is_in_game()` | 실제 게임에 접속해서 데이터를 받을 수 있는지. `bool` |
| `get_game_time()` | 경과 시간(초). `float \| None` |
| `get_active_player()` | 본인 상세 정보 (`currentGold` 등 본인만 정확한 필드 포함). `dict \| None` |
| `get_all_players()` | 전체 10명 원본 데이터. `get_scoreboard()`가 이걸 가공한 것. `list[dict] \| None` |
| `estimate_gold(items)` | 아이템 리스트로 골드 추정 (`get_scoreboard()`가 내부적으로 씀). `float` |
| `get_event_data()` | 게임 이벤트 로그 원본 (`TurretKilled`, `DragonKill`, `GameEnd` 등). `list[dict] \| None` |
| `get_game_result(events=None)` | `GameEnd` 이벤트로 승패 판정. `"WIN" \| "LOSS" \| None` |
| `start_live_watcher(on_update, on_end=None, interval=1.0, on_result=None)` | 매 interval마다 `on_update(scoreboard)`, 승패 확정되면 `on_result(...)` 한 번, 게임 끝나면 `on_end()`. `threading.Thread` 반환 |

**주의**: `start_champ_select_watcher`/`start_live_watcher`는 즉시 리턴하고, **콜백은 별도 백그라운드 스레드에서 호출**된다. Tkinter/PyQt 등에서 콜백 안에서 UI 위젯을 직접 갱신하면 스레드 안전 문제가 생기니, 각 프레임워크의 메인 스레드 전달 방식(예: Tkinter의 `root.after()`)을 거쳐야 한다.

---

## 알아둘 것 (합치기 전 확인)

- `get_player`, `get_recent_matches`, `get_solo_rank`, `get_live_state`, `get_scoreboard`, `get_team_gold_totals`, `get_post_game_summary`, `wait_for_post_game_summary`, `get_champ_select_session`는 **동기(sync)**로 작성됨 (호출하면 바로 값이 리턴됨). `start_champ_select_watcher`/`ChampSelectSocket`은 이름처럼 백그라운드에서 계속 도는 것이므로 아래 스레드 주의사항 참고. UI/RAG 쪽이 비동기(asyncio) 구조라면 블로킹될 수 있으니 확인 필요
- 예외 기반 오류 처리를 쓰고 있음 (반환값에 에러 코드를 담지 않음). UI/RAG 쪽 에러 처리 방식과 맞는지 확인 필요
- 위 8개 함수는 `contracts.riot`에 정의된 데이터클래스를 그대로 반환함 (dict가 아님) — `player["puuid"]`가 아니라 `player.puuid`로 접근
- `team` 필드는 라이엇이 실제로 쓰는 값 그대로 `"ORDER"`(블루팀) / `"CHAOS"`(레드팀)이다
- 서브모듈 전용 함수(`lcu_client`/`live_client`의 챔피언 선택·원본 데이터 관련)는 dict/list를 반환하고, 실패/미진행 상태를 예외 대신 `None`으로 표현한다
