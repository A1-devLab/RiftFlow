# RiftFlow

리그 오브 레전드 플레이를 돕는 데스크톱 코칭 프로그램입니다.
롤 클라이언트와 연동해 전적, 픽창, 인게임 상황을 보여 주고, 라이엇 공식 게임 자료를 근거로 AI가 질문에 답합니다.

Python 3.11 이상, PySide6 기반이며 Windows를 대상으로 합니다.

## 주요 기능

### 전적

- 롤 클라이언트에 로그인하면 계정을 자동으로 인식합니다.
- 솔로 랭크 티어와 최근 20경기(챔피언, 날짜, KDA, CS, Damage, Gold)를 보여 줍니다.
- 경기를 클릭하면 10명 전체 비교와 전투·피해량·시야·골드·오브젝트 상세 통계를 그래프나 수치로 볼 수 있습니다.

### 픽창

- 챔피언 선택이 시작되면 자동으로 픽창 화면으로 넘어갑니다.
- 확정된 아군·상대 픽과 밴, 맞라인 상대를 표시합니다. 상대가 아직 고르는 중인 챔피언은 표시하지 않습니다.
- 내 챔피언과 상대, 선호하는 라인전·딜교환 성향을 바탕으로 룬과 초반 운영을 질문할 수 있습니다.
- 내 최근 경기에서 같은 상대를 만났던 기록과 최근 사용한 룬 페이지를 함께 보여 줍니다.

### 인게임

- 게임이 로딩되면 자동으로 인게임 화면으로 넘어가고, 끝나면 전적 화면으로 돌아옵니다.
- 10명의 레벨, KDA, CS, 아이템, 부활 대기 시간을 실시간으로 보여 줍니다.
- 팀별 골드를 비교합니다. 보유 아이템 가격을 합한 추정치라서 아직 쓰지 않은 골드는 포함되지 않습니다.
- 현재 상황을 질문하거나 다음에 살 아이템을 추천받을 수 있습니다. 추천은 공식 아이템 자료에 있는 아이템만 사용합니다.
- 시야, 상대 소환사 주문 쿨타임, 오브젝트 타이머는 게임에서 제공하지 않아 확인할 수 없습니다.

### AI에게 질문

- 전적 분석, 챔피언 추천, 연습 방법, 패치 변경 등 롤과 관련된 질문에 답합니다.
- 패치·아이템·수치처럼 사실을 묻는 질문은 공식 자료로 확인되는 내용만 답합니다.

### 게임 자료

- Data Dragon의 챔피언·아이템·룬 정보와 최근 한국어 패치 노트를 내려받아 로컬에 저장합니다.
- API 키 없이 둘러볼 수 있는 예시 자료가 기본으로 들어 있습니다. 예시 자료는 최신 게임 정보가 아닙니다.

## 설치

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

```bash
python -m pip install -e .
```

## 실행

```bash
python -m ui
```

설치 후에는 `riftflow` 명령으로도 실행할 수 있습니다. 저장소 루트에서 실행하세요.

처음 실행하면 예시 자료로 동작합니다. **설정 및 데이터 → 공식 게임 자료 수집 / 업데이트**를 누르면 최신 공식 자료를 내려받고, 이후에는 수집한 자료를 사용합니다.

## 환경변수

`.env.example`을 `.env`로 복사한 뒤 값을 채웁니다. `.env`는 Git에 올라가지 않습니다.

| 이름 | 설명 |
|---|---|
| `RIOT_API_KEY` | 로그인 계정 인식, 랭크와 전적 조회에 사용합니다. [Riot Developer Portal](https://developer.riotgames.com/)에서 발급합니다. |
| `GEMINI_API_KEY` | AI 답변에 사용합니다. Google AI Studio에서 발급합니다. |
| `GEMINI_MODEL` | 사용할 Gemini 모델입니다. 기본값은 `gemini-3.5-flash-lite`입니다. |
| `RIOT_PLATFORM` | 선택. 플랫폼 라우팅, 기본값 `kr` |
| `RIOT_REGION` | 선택. 대륙 라우팅, 기본값 `asia` |

픽창과 인게임 정보는 로컬 롤 클라이언트에서 직접 읽으므로 API 키가 필요하지 않습니다.
AI 요청은 질문을 보낼 때만 한 번 호출하며, 대화 내용은 저장하지 않습니다.

## 데이터

- `data/demo.db`: 예시 자료. 앱을 실행하면 자동으로 준비됩니다.
- `data/riftflow.db`: 내려받은 공식 게임 자료
- `data/personal_matches.db`: 로그인 계정의 최근 경기에서 뽑은 맞라인 상대·룬 기록

데이터 파일과 키는 Git에 올라가지 않습니다.
자료는 원본 버전 번호를 그대로 유지합니다. 패치 노트 번호(예: `26.18`)와 게임 데이터 버전(예: `16.18.1`)은 서로 바꿔 쓰지 않습니다.
개인 상성 기록은 내 계정의 경기만 집계한 것이며 전체 이용자의 승률 통계가 아닙니다.

## 명령줄 도구

```bash
python -m ui.ask "무한의 대검 가격과 조합 재료를 알려줘"
python -m ui.ask --local "무한의 대검 가격과 조합 재료를 알려줘"
python -m knowledge update
python -m knowledge status
```

`--local`은 AI를 호출하지 않고 검색된 근거만 보여 줍니다. `knowledge update`는 공식 자료를 내려받고, `status`는 저장된 자료를 확인합니다.

## 개발

게임 단계별 기능을 터미널에서 확인할 수 있습니다.

```bash
python test.py
```

테스트:

```bash
python -m unittest discover -s tests/integration -v
```

패키지를 설치하지 않았다면 앞에 `PYTHONPATH=src`를 붙여 실행합니다. 테스트는 모두 오프라인으로 동작하며 실제 Gemini·라이엇 API를 호출하지 않습니다.

관련 문서:

- `docs/architecture.md`: 전체 구조
- `docs/interfaces.md`: 모듈 간 데이터 형식
- `docs/game-phases.md`: 게임 단계별 폴더, 프롬프트 수정 위치, 화면 자동 전환
- `docs/riot-application.md`: 라이엇 API 키 신청 안내
- `docs/ui/README.md`: 화면 설계 자료

## 고지

RiftFlow isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
