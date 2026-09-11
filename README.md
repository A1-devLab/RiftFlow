# RiftFlow

리그 오브 레전드 맞춤형 가이드 프로그램을 위한 팀 프로젝트입니다.
현재는 협업용 폴더 구조와 문서만 구성되어 있습니다. Python 파일은 기능 구현 시 추가합니다.

## 개발 환경

- Python 3.11 이상
- 최종 대상 플랫폼: Windows

## 개발 환경 준비

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

실행 방법과 필요한 의존성은 기능 구현 시 추가합니다.

## 환경변수

실제 연동을 구현할 때 `.env.example`을 `.env`로 복사하여 로컬에서 설정합니다.
현재 뼈대는 `.env`를 자동으로 읽지 않습니다.
실제 키와 인증정보는 Git에 올리지 않습니다. 공개 배포 시 서버 API 키를 앱에 포함하지 않습니다.

## 구조

```text
docs/                   설계 및 협업 문서
src/
  contracts/            공통 데이터 형식
  riot/                 라이엇 API 연동
  knowledge/            자료 수집 및 DB 업데이트
  rag/                  검색 및 Gemini 답변
  ui/                   PC 화면
tests/fixtures/         가짜 데이터 및 샘플
tests/integration/      통합 검증
data/                   로컬 DB 및 캐시 (내용은 Git 제외)
```

## 협업

- 담당 범위: `docs/architecture.md`
- 모듈 간 약속: `docs/interfaces.md`
- 기능별 브랜치에서 작업한 뒤 PR로 병합합니다.
- 공통 설정, 의존성, 데이터 형식 변경은 팀과 먼저 공유합니다.
- 실제 API 기능, 추천 엔진, DB, 챗봇 및 UI는 아직 구현하지 않았습니다.
