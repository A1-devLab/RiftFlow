# 게임 단계별 구조

```text
test.py
└── src/game_phases/
    ├── common.py
    ├── before_game/
    │   ├── prompt.py
    │   ├── desktop.py
    │   └── service.py
    ├── in_game/
    │   ├── prompt.py
    │   ├── desktop.py
    │   └── service.py
    ├── after_game/
    │   ├── prompt.py
    │   ├── desktop.py
    │   └── service.py
    └── out_game/
        ├── prompt.py
        └── service.py
```

`before_game`/`in_game`/`after_game`/`out_game`은 개발용 구분입니다. 서비스 화면 이름은 **픽창**(before_game)과 **인게임**(in_game)이며, after_game은 데스크톱 화면 없이 터미널 흐름(`python test.py`)에서만 씁니다.

각 단계 폴더의 역할은 같습니다.

- `prompt.py`: Gemini 역할과 답변 규칙(`SYSTEM`). 프롬프트 담당자는 기본적으로 이 파일만 수정합니다.
- `desktop.py`: 화면용 데이터 정리와 근거 수집, Gemini 호출. 데스크톱 UI와 테스트가 사용합니다.
- `service.py`: 라이엇 API 경계(`get_*_context`)와 터미널 흐름(`run`).

## 실행

저장소 루트에서 `python test.py`를 실행하고 1~4 중 하나를 선택합니다.
데스크톱은 `python -m ui`이며, 롤 클라이언트 상태에 따라 **픽창 → 인게임** 화면으로 자동 전환합니다.

## 공통 수정 금지 영역

- `src/game_phases/common.py`: 공통 Gemini 호출과 결과 출력. 단계별 프롬프트 작업에서는 수정하지 않음
- `src/knowledge/`: 공통 DB 수집·조회. 단계별 프롬프트 작업에서는 수정하지 않음
- `src/rag/`: 공통 검색·근거·Gemini 처리. 단계별 프롬프트 작업에서는 수정하지 않음

## before_game 수정 위치

- `src/game_phases/before_game/prompt.py`: Gemini 역할, 답변 규칙과 게임 전 상황 형식
- `src/game_phases/before_game/service.py`: 터미널에서 받을 질문과 사용자 입력 항목

프롬프트 담당자는 기본적으로 `before_game/prompt.py`의 `SYSTEM` 문구를 수정합니다. DB 근거 형식을 바꾸어야 할 때만 같은 파일의 `build` 함수를 수정합니다. `build`는 공통 RAG가 만든 근거에 상대 챔피언과 플레이 성향을 추가한 뒤 Gemini로 전달합니다.

현재 DB에는 챔피언 요약, 아이템, 룬 설명과 패치 노트가 있습니다. 정확한 챔피언 상성 통계나 완성된 룬 페이지 조합 데이터는 없으므로 프롬프트만으로 만들어내지 않습니다. 이후 해당 자료를 DB에 추가하면 같은 검색 흐름에서 사용할 수 있습니다.

## in_game 수정 위치

- `src/game_phases/in_game/prompt.py`: 게임 중 코치 역할과 답변 규칙. 확인되는 값(레벨·KDA·CS·아이템), 추정값(골드), 아예 없는 값(시야·상대 주문 쿨타임·오브젝트 타이머)을 구분합니다.
- `src/game_phases/in_game/desktop.py`: `describe_scoreboard`가 10명 스코어보드를 아군·상대로 나누고, `answer_in_game`이 공식 아이템·챔피언 문서를 근거로 답합니다.
- `src/knowledge/in_game.py`: 아이템 ID → 공식 이름·가격, 챔피언 역할 태그와 Data Dragon 소개 지표.

'나'는 Live Client의 `/activeplayername`으로 찾습니다. 찾지 못하면 블루팀을 아군으로 두고 화면과 프롬프트에 그 사실을 표시합니다.
골드는 보유 아이템 가격 합계라서 아직 쓰지 않은 골드가 빠져 있습니다. 화면과 프롬프트 모두 '추정'으로 표시합니다.
아이템 추천은 공식 아이템 자료에 있는 아이템만 사용하고, 이미 가진 아이템은 후보에서 뺍니다. 아이템 자료가 없으면 Gemini를 호출하지 않습니다.
상대 조합은 Data Dragon 역할 태그와 attack/magic 소개 지표로만 정리합니다. 실제 딜 비율이나 승률이 아닙니다.

## after_game 수정 위치

- `src/game_phases/after_game/prompt.py`: 경기 후 분석 역할과 답변 형식(한 줄 요약 / 잘한 점 / 아쉬운 점 / 다음 게임에서 해볼 것).
- `src/game_phases/after_game/desktop.py`: 결과 화면 요약 정리, 최근 경기 평균 계산, 결과 화면 대기, 분석 요청.

데스크톱 화면은 없고 `python test.py`의 `3. after game`에서 사용합니다.

분석 근거는 LCU 결과 화면의 KDA·CS·킬 관여·딜량·받은 피해·시야 점수, 게임 중 마지막 스코어보드, 로그인 계정의 최근 협곡 경기 평균입니다. 같은 챔피언 평균이 있으면 먼저 비교하고 표본 경기 수를 함께 밝힙니다.
최근 경기 평균은 앱이 마지막으로 불러온 전적이라 방금 끝난 경기는 들어 있지 않습니다. 전체 이용자 통계가 아닙니다.
사망 원인, 와드 위치, 한타 포지셔닝은 데이터에 없으므로 관찰한 것처럼 말하지 않게 했습니다.

## out_game 수정 위치

- `src/game_phases/out_game/prompt.py`: 메타·패치 질문용 Gemini 역할과 답변 규칙
- `src/game_phases/out_game/service.py`: 터미널 질문과 모호한 메타 질문의 검색어 보강

`요즘 뭐가 좋아?`처럼 짧은 질문은 최근 패치 변경 자료를 우선 검색합니다. 현재 DB에는 전체 이용자의 승률·픽률 통계가 없으므로 패치 변화는 설명할 수 있지만 객관적인 티어표를 확정할 수는 없습니다.

## 데스크톱 단계 전환

`python -m ui`는 2.5초마다 게임 단계를 한 번에 확인합니다 (`ui.__main__.collect_phase`).

1. Live Client(2999)에서 게임 중이면 **인게임** 화면에 스코어보드를 표시합니다.
2. LCU 게임 진행 단계가 `GameStart`/`InProgress`/`Reconnect`인데 스코어보드가 아직 없으면 로딩 화면으로 보고 **인게임** 화면에 로딩 중이라고 표시합니다. 픽창이 끝난 뒤 전적 화면으로 튕기지 않게 하려는 구분입니다.
3. 아니면 LCU 픽창을 확인해 **픽창** 화면에 확정 픽·밴을 표시합니다.
4. 셋 다 아니면 대기입니다.

화면 전환은 단계가 바뀔 때만 일어납니다. 픽창이 열리면 픽창 화면으로, 로딩·게임이 시작되면 인게임 화면으로 넘어갑니다. 같은 단계가 이어지는 동안 사용자가 다른 화면으로 옮기면 그대로 둡니다. 게임이 끝나거나 닷지로 픽창이 닫히면, 그 화면을 보고 있던 경우에만 전적 화면으로 돌아갑니다. 게임이 끝나면 90초 뒤 전적을 다시 불러와 방금 경기를 반영합니다.
AI 질문을 처리하는 동안에도 폴링은 계속됩니다.
LCU 인증 정보는 클라이언트 프로세스가 살아 있는 동안 재사용합니다. 프로세스 목록 전체를 훑는 작업이 윈도우에서 1초 이상 걸릴 수 있기 때문입니다.

## 데스크톱 픽창 (before_game)

**픽창** 화면은 확정된 아군·상대 픽과 밴을 표시합니다. 내 챔피언과 맞라인 상대가 확인되면 질문 입력에 자동 반영합니다. 픽창이 없을 때는 직접 입력할 수 있습니다. `src/game_phases/before_game/desktop.py`가 공식 DB 문서와 픽창 상황, 확인된 개인 경기 통계를 묶어 Gemini에 보냅니다.

최근 전적 조회 시 같은 MATCH-V5 응답에서 개인 상성·사용 룬 페이지를 `data/personal_matches.db`에 저장합니다. 새로고침 중복은 경기 ID로 제거합니다. 맞라인 상대가 확실하지 않은 경기는 상성 표본으로 세지 않으며, 표시한 승률은 전체 이용자 통계가 아닙니다. 공식 Data Dragon에는 챔피언별 완성 룬 추천 페이지와 전체 이용자 상성 승률이 없으므로 둘을 만들어내지 않습니다.
