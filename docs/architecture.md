# 프로젝트 구조

## 모듈

| 모듈 | 역할 | 위치 |
|---|---|---|
| UI 설계 | 프로그램 구상, 화면 설계 자료 | docs/ui/ |
| riot | 라이엇 API 연동 | src/riot/ |
| knowledge | 패치 자료 수집, DB 및 업데이트 | src/knowledge/ |
| rag | 근거 검색과 Gemini 답변 | src/rag/ |
| 공통 | 공통 데이터 형식, 모듈 통합 | src/contracts/ 및 공통 규격 문서 |

## 연결 방향

- riot → 공통 경기 데이터 → 분석 또는 UI
- knowledge → 근거 자료 → rag → 답변과 출처 → UI
- `test.py` → `game_phases` → 공통 DB/RAG/Gemini 연결
- `before_game` → 게임 전 전용 프롬프트와 사용자 성향
- `in_game` → 현재 구현된 일반 RAG 질문
- `after_game` → 향후 MATCH-V5 경기 분석
- `out_game` → 게임 외부의 메타·패치·일반 지식 질문

각 모듈은 담당 기능에 필요한 로직과 문서를 관리합니다.
DB 구조는 knowledge 담당자가 관리하며 RAG에서는 합의한 조회 기능을 이용합니다.
실제 데이터 대신 tests/fixtures의 샘플로도 개발할 수 있도록 설계합니다.

## 현재 상태

자료 수집 DB, RAG, Gemini 호출, 데스크톱 MVP와 단계별 터미널 UI가 구현되어 있습니다.
데스크톱 전적 화면은 롤 클라이언트 로그인을 자동 감지하고 로그인 계정의 랭크와 최근 20경기를 조회합니다.
픽창의 확정 픽·밴, 인게임 스코어보드·아이템·사용 골드 추정, 종료 직후 경기 요약은
각 `game_phases` 서비스에서 Riot 모듈과 연결됩니다. 전용 화면과 아이템 추천에는 아직 연결하지 않았습니다.
