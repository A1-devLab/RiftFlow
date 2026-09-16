# riot 모듈 (src/riot) 사용 설명서

`src/riot`이 다른 모듈(knowledge, rag, ui)에 제공하는 함수와 데이터 형식을 정리한 문서.
합치는 사람은 이 문서만 보고도 어떤 값을 넣으면 어떤 값이 나오는지 알 수 있어야 한다.

## 준비물

- 환경변수 `RIOT_API_KEY` 필요 (`.env` 파일 또는 시스템 환경변수)
- 선택 환경변수: `RIOT_PLATFORM` (기본값 `"kr"`), `RIOT_REGION` (기본값 `"asia"`)
- 의존성: `requests`, `python-dotenv` (pyproject.toml에 추가 필요)
- 사용법: `from riot import get_player, get_recent_matches, get_solo_rank, get_live_state`

`get_player`, `get_recent_matches`, `get_solo_rank`는 라이엇 API 키가 필요하다.
`get_live_state`는 API 키가 필요 없지만, **이 코드를 실행하는 컴퓨터에서 라이엇 클라이언트가 켜져 있어야** 동작한다.

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
```

## 알아둘 것 (합치기 전 확인)

- 모든 함수는 **동기(sync)**로 작성됨. UI/RAG 쪽이 비동기(asyncio) 구조라면 블로킹될 수 있으니 확인 필요
- 예외 기반 오류 처리를 쓰고 있음 (반환값에 에러 코드를 담지 않음). UI/RAG 쪽 에러 처리 방식과 맞는지 확인 필요
- `contracts.riot`에 정의된 데이터클래스를 그대로 반환함 (dict가 아님) — `player["puuid"]`가 아니라 `player.puuid`로 접근
