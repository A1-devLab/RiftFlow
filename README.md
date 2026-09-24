# RiftFlow

공식 게임 자료에서 선택의 이유를 찾는 League of Legends 데스크톱 MVP.
Python 3.11+ / PySide6. 현재는 비공개 팀 개발용이며 Riot Personal API 제품이 승인된 상태입니다.

## 구현된 기능

- Data Dragon과 최근 한국어 패치 노트를 SQLite로 저장·갱신
- 실제 DB → 공통 문서 형식 → 이찬영의 RAG 검색 연결
- 전적 대시보드, 자료 검색·상세·출처, 질문 화면, 설정·데이터 관리
- 롤 클라이언트 로그인 자동 감지와 로그인 계정의 랭크·최근 20경기 조회
- 키 없이 사용할 수 있는 고정 버전 예시 10건 (최신 게임 정보 아님)
- 선택적으로 Gemini 답변 요청. 기본은 로컬 근거 검색만 수행
- 업데이트·질문 처리를 백그라운드에서 실행해 UI 응답 유지

전적 분석, 룬 자동 적용, 실시간 아이템 추천은 아직 구현하지 않았습니다.

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
python -m ui
```

터미널에서 실제 로컬 DB에 바로 질문할 수도 있습니다.

```bash
python -m ui.ask "무한의 대검 가격과 조합 재료를 알려줘"
python -m ui.ask --local "무한의 대검 가격과 조합 재료를 알려줘"
```

첫 번째 명령은 DB 검색 후 Gemini까지 호출하고, `--local`은 API 사용 없이 검색 근거만 보여 줍니다.

게임 단계별 임시 터미널 UI는 저장소 루트에서 실행합니다.

```bash
python test.py
```

`1. before game`은 챔피언, 상대 챔피언, 딜교환·라인전 성향을 받아 게임 전 전용 프롬프트로 답합니다. `2. in game`은 기존 RAG 질문 기능이며, `3. after game`은 MATCH-V5 연동 전 안내 화면입니다. `4. out game`은 현재 메타와 패치 정보를 묻는 전용 공간입니다.

설치 후 `riftflow`로도 실행할 수 있습니다. 저장소 루트에서 실행하세요.
설치 없이 이미 PySide6가 있는 환경에서는 `PYTHONPATH=src python -m ui`로 실행 가능합니다.
최종 대상은 Windows이며 현재 통합 검증은 macOS 및 Qt offscreen 환경에서 수행했습니다.

## 사용 순서

1. 기본 예시 모드에서 게임 자료를 확인합니다.
2. 코치에게 질문에서 `무한의 대검 가격과 조합 재료를 알려줘`를 입력합니다.
3. 기본 모드에서는 AI 답변 대신 검색한 근거를 보여줍니다.
4. 설정 및 데이터 → 공식 게임 자료 수집/업데이트를 누릅니다.
5. 완료 후 수집한 로컬 DB로 자동 전환합니다.
6. 실제 AI 답변은 `.env` 설정 후 앱을 다시 실행하고 Gemini 사용을 켭니다.

## 의존성

```bash
pip install -e .
```

## 환경변수

`.env.example`을 `.env`로 복사하여 로컬에서만 설정합니다.

- `GEMINI_API_KEY`: Google AI Studio에서 발급한 키
- `GEMINI_MODEL`: 기본값은 `gemini-3.5-flash-lite`입니다. 다른 모델을 쓰려면 `.env`에서 변경합니다.
- `RIOT_API_KEY`: 후속 전적 API 개발용. 현재 MVP에서는 사용하지 않습니다.

GUI의 Gemini 요청은 재시도 없이 1회, 약 60초 타임아웃으로 실행합니다.
키가 설정돼 있어도 Gemini 사용을 켜고 질문을 보내기 전에는 호출하지 않습니다.
GUI 대화는 저장하지 않습니다. 기존 `python -m rag` CLI는 기본 저장 정책이 다르므로 해당 README를 확인하세요.

## 데이터와 버전

- `data/demo.db`: 고정 예시 자료, 앱 실행 시 준비
- `data/riftflow.db`: 공식 수집 자료
- DB와 키는 Git에서 제외합니다.
- 자료에는 실제 원본 버전을 유지합니다. `26.18`과 `16.18.1`을 임의 변환하지 않습니다.
- 버전을 지정하면 정확히 일치하는 문서만 사용합니다.
- 버전 미지정은 종류별 최신 수집 자료를 사용하므로 서로 다른 번호 체계가 섞일 수 있습니다. 각 출처 버전을 확인하세요.
- 챔피언은 현재 요약 정보만 수집합니다. 상세 스킬·상성 판단은 범위 밖입니다.
- 공식 자료가 업데이트되면 다음 질문부터 다시 읽어 같은 버전의 수정도 반영합니다.
- 같은 모드 안에서도 아이템 중복·모드별 데이터는 추가 검증이 필요합니다.

## 독립 모듈 실행

```bash
python -m knowledge update
python -m knowledge status
python -m rag ask "무한의 대검 가격 알려줘" --no-save
```

RAG CLI는 기존 팀원 테스트용 fixture를 기본으로 사용합니다. **실제 DB 연동은 GUI 또는 `ui.services.ask_database`를 사용하세요.**

## 테스트

```bash
python -m unittest discover -s tests/integration -v
```

현재 85개 오프라인 테스트와 GUI 작업 완료 검증을 수행합니다. 실제 Gemini 호출과 Windows 환경은 별도 검증이 필요합니다.

## 협업 문서

- `docs/interfaces.md`: 실제 DB/RAG 연결 규격
- `docs/game-phases.md`: 단계별 폴더와 게임 전 프롬프트 수정 위치
- `docs/riot-application.md`: 라이엇 Personal Key 신청용 문안·실행 순서
- `docs/ui/README.md`: 박선제의 원본 설계 자료

팀원 원본 기능은 유지하며 통합 작업은 `codex/mvp-desktop` 브랜치에서 진행합니다.

RiftFlow isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
