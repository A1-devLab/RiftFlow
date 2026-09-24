# 모듈 간 입출력 약속

아래 표는 초기 논의용 초안이며, 구현된 계약은 하단의 날짜별 절을 기준으로 합니다.

| 모듈 | 기능 후보 | 입력 | 출력 |
|---|---|---|---|
| riot | get_player | Riot ID | 사용자 식별 정보 |
| riot | get_recent_matches | PUUID, 경기 수 | 경기 요약 목록 |
| riot | get_live_state | 없음 | 경기 상태 및 연결 상태 |
| knowledge | get_documents | 패치, 챔피언 또는 아이템 | 근거 자료 목록 |
| knowledge | sync_patch | 패치 | 업데이트 결과 |
| rag | answer_question | 질문, 패치, 선택적 분석 결과 | 답변, 출처, 근거 부족 여부 |

## 합의할 사항

- 내부 사용자 식별자는 PUUID를 기준으로 합니다.
- 경기 시간의 단위는 초로 통일합니다.
- 누락된 값은 숫자 0과 구분합니다.
- 자료에는 문서 ID, 기준 패치, 제목, 출처 URL을 연결합니다.
- API 원본 응답은 riot 모듈에서 공통 형식으로 변환합니다.
- 게임 미실행, 호출 제한, 검색 결과 없음은 서로 구분합니다.
- 함수의 동기/비동기 방식과 오류 표현은 구현 전에 합의합니다.

## 샘플

각 담당자는 실제 연결에 앞서 tests/fixtures/에 개인정보 없는 예시를 추가합니다.

## MVP에서 구현한 연결 (2026-09-15)

`knowledge.get_documents(patch=None, kind=None, *, db_path="data/riftflow.db")`

- kind: item, champion, rune, patch 또는 None(전체).
- patch 인자는 **원본 version의 정확한 일치**로 처리. 표시 패치와 Data Dragon 버전 대응은 아직 미구현.
- None은 종류별 최신 저장 버전. 서로 같은 패치임을 의미하지 않음.
- 결과: doc_id, kind, entity_id, version, title, subject_name, text, source_url, fields 등 RAG용 문서 목록.
- DB가 없으면 빈 목록. DB 손상 등 실제 읽기 실패는 예외.
- 매 호출마다 읽기 전용 연결을 새로 열며 쓰기·수집은 수행하지 않음.

`ui.services.ask_database(path, question, version=None, *, generate=None)`

- GUI의 실제 DB 연결 진입점. 매 질문마다 새 DocumentSource로 핫픽스 캐시 문제를 방지.
- generate=None이면 근거 검색·프롬프트만 준비. AI 답변을 생성했다고 표시하지 않음.
- 모델 함수는 설정을 확인한 GUI가 명시적으로 전달.
- 반환: 기존 rag.pipeline.answer 결과 + generated.
- GUI는 QThread에서 수집과 질문을 실행하며 진행 중 중복 요청·모드 전환·종료를 막음.
- GUI에서는 대화 저장 없이 실행. CLI와 저장 정책이 다름.

## Out game DB 구현 (2026-09-20)

구현: `src/knowledge/` · DB: `data/riftflow.db` (SQLite)

### 주요 함수

| 함수 | 기능 |
|---|---|
| `collector.update(db, limit=3)` | 최신 챔피언·아이템·룬과 최근 패치 수집 |
| `sync_patch(patch, *, source_url=None, db_path=...)` | 지정한 공식 패치 수집. 버전·처리 상태·출처·대상 수 반환 |
| `get_patch_changes(patch=None, *, kind=None, change_type=None, name=None, db_path=...)` | 대상 종류·변경 방향·이름으로 패치 변경 조회 |
| `get_documents(patch=None, kind=None, *, db_path=...)` | 기존 RAG 형식으로 자료 반환. `kind="patch"`에 대상별 변경도 포함 |

`get_patch_changes`의 kind는 champion/item/rune,
change_type은 buff/nerf/adjusted/unknown/unchanged입니다.
patch=None이면 최신 구조화 패치를 조회하며, 자료가 없으면 빈 목록을 반환합니다.

### 저장 정보

| 필드 | 내용 |
|---|---|
| data_type / patch_version | 데이터 종류 / 원본 버전 |
| collected_at | 마지막 수집 시각 (UTC) |
| sample_match_count | 표본 경기 수. 정적 자료와 패치 노트는 `null` |
| source / source_url | 출처 이름 / 원문 URL |
| changes | 스킬·능력치, 변경 전후 값, 원문, 변경 방향, 파싱 상태 |

변경 전후 값(`before`, `after`)은 단위를 포함한 문자열이며, 추출하지 못하면 null입니다.
대상별 결과에는 이름·종류·요약·분류 근거도 포함됩니다.

### DB 변경 및 주의사항

- 기존 `records`에 수집 시각·표본 경기 수·출처 열을 추가하고, 대상별 변경은 새 `patch_changes` 테이블에 저장합니다. 기존 데이터는 유지합니다.
- 재수집 시 같은 원문의 변경 내용을 교체하며, 수집 실패 시 이번 업데이트를 되돌립니다. 기존 행의 수집 시각은 재수집 전까지 null입니다.
- 표시 패치와 Data Dragon 버전은 자동 변환하지 않습니다. 패치 내부 대상 ID도 Data Dragon ID와 다릅니다.
- 애매한 변경은 unknown/adjusted로 남깁니다. 기본 챔피언·아이템·룬 섹션만 구조화하며, 다른 모드와 별도 긴급 수정은 원문으로 보존합니다.
- RAG 문서의 kind는 기존 값인 patch를 유지하고, data_type=patch_change와 fields로 구조화 정보를 구분합니다. 업데이트 후 상주 RAG 캐시는 다시 생성해야 합니다.

### 사용 예시

```python
from knowledge import sync_patch, get_patch_changes, get_documents

sync_patch("26.18")
buffs = get_patch_changes("26.18", kind="champion", change_type="buff")
items = get_patch_changes("26.18", kind="item")
documents = get_documents("26.18", "patch")
```

전체 수집: `python -m knowledge update --patches 3`
