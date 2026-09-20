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

구현 위치: `src/knowledge/`. SQLite 저장 경로 기본값: `data/riftflow.db`.
기존 `get_documents()` 인자와 RAG가 사용하는 kind 목록을 유지합니다.

### 공통 메타데이터

| 필드 | 의미 |
|---|---|
| data_type | champion, item, rune, patch, patch_change |
| patch_version | 원본 버전. 정적 자료는 Data Dragon 버전, 패치 변경은 표시 패치 |
| collected_at | 마지막으로 수집에 성공한 UTC ISO 8601 시각 |
| sample_match_count | 표본 경기 수. 공식 정적 자료·패치 노트에는 해당하지 않아 **null** |
| source | 현재 수집기에서 Riot Games |
| source_url | 실제로 수집한 원문 URL |

경기 수를 0으로 채우거나 정적 자료를 승률 통계처럼 해석하지 않습니다.
기존 records 테이블의 `kind`, `version`이 각각 자료 종류와 원본 버전입니다.
DB 연결 시 `collected_at`, `sample_match_count`, `source` 열을 추가하며 기존 행을 삭제하지 않습니다.
이전 행은 수집 시각을 알 수 없으므로 재수집 전까지 collected_at=null입니다.
updated_at은 마지막 내용/이름/출처 변경 시각, collected_at은 같은 자료의 재확인에도 갱신됩니다.

### 저장 및 업데이트

- `collector.update(db, limit=3)`: 최신 Data Dragon 챔피언·아이템·룬과 최근 패치 1~12개 수집.
  호출 전체를 한 트랜잭션으로 저장합니다. 도중 다운로드나 파싱에 실패하면 이번 데이터 변경을 되돌립니다.
- `sync_patch(patch, *, source_url=None, db_path=...)`: 한국어 공식 패치 한 개 수집.
  `patch="25.18"` 형식이며 제목의 버전과 일치해야 합니다. 정적 자료의 버전 변환은 하지 않습니다.
  반환: `{patch_version, status: new|updated|unchanged, source_url, entity_count}`.
- 예외: 잘못된 인자·제목·본문은 ValueError, 네트워크·SQLite 오류는 원래 예외를 전달합니다.
  CLI는 메시지와 종료 코드 1을 반환합니다.
- records의 기본키 `(kind, version, entity_id)`를 유지합니다.
- 새 `patch_changes` 테이블의 기본키는 `(version, source_url, entity_id)`입니다.
  열: version, source_url, entity_id, entity_kind, name, change_type, content(JSON),
  collected_at, sample_match_count, source.
- 같은 원문의 재수집은 해당 원문의 구조화 결과만 교체합니다. 수정·삭제된 항목이 남지 않으며
  다른 패치와 다른 출처의 행은 보존됩니다. 원문 텍스트는 records에 계속 저장합니다.
- 구조화 결과가 처음부터 없으면 원문만 저장하고 경고를 출력합니다.
  기존 구조화 결과가 있었는데 전부 사라지는 경우는 파서 변경 가능성이 있어 실패 처리합니다.

### 변경 사항 조회

```python
from knowledge import get_documents, get_patch_changes, sync_patch

sync_patch("25.18")
buffs = get_patch_changes("25.18", kind="champion", change_type="buff")
nerfs = get_patch_changes("25.18", kind="champion", change_type="nerf")
items = get_patch_changes("25.18", kind="item")
runes = get_patch_changes("25.18", kind="rune")
documents = get_documents("25.18", "patch")
```

`get_patch_changes(patch=None, *, kind=None, change_type=None, name=None, db_path=...)`

- patch=None: 구조화 테이블의 최신 숫자 버전. 없는 DB/기존 스키마는 빈 목록이며 파일을 만들지 않습니다.
- kind: champion/item/rune. name: 이름 부분 일치. 필터는 SQL 매개변수로 전달합니다.
- change_type: buff/nerf/adjusted/unknown/unchanged.
- 각 결과: 공통 메타데이터 + entity_id, entity_kind, entity_name, section_id,
  summary, change_type, classification_basis, changes.
- entity_id는 패치 기사 내 섹션 식별자와 순번이며 **Data Dragon ID가 아닙니다**.
- changes 항목: ability, stat, before, after, raw_text, direction, parse_status.
  before/after는 단위와 레벨별 수치를 보존한 문자열입니다. 추출 불가는 null 및 unparsed입니다.

예시(테스트용 가상 수치):

```json
{"ability":"Q","stat":"재사용 대기시간","before":"8초","after":"10초",
 "raw_text":"재사용 대기시간: 8초 → 10초","direction":"nerf","parse_status":"parsed"}
```

### RAG 문서와 분류 범위

- 기존 get_documents의 챔피언·아이템·룬 문서는 설명과 메타데이터를 반환합니다.
  챔피언에는 기본 능력치, 아이템에는 가격·조합, 룬에는 설명 필드를 제공합니다.
- `kind="patch"`는 패치 원문과 대상별 구조화 문서를 함께 반환합니다.
  구조화 문서도 RAG 호환을 위해 kind=patch이며 data_type=patch_change입니다.
  fields에 전체 변경 정보를 넣고 text에 대상명·버프/너프·원문 수치를 넣습니다.
- 버프/너프는 공식 summary의 명시적 표현 또는 알려진 능력치의 단순 수치 비교로 분류합니다.
  `classification_basis`로 official_summary/numeric_heuristic를 구분합니다.
  동일한 형태의 계수식은 대응 숫자를 비교합니다. 식 구조가 바뀌거나 서술형·해석이 불확실한
  수치는 unknown이며, 방향이 섞인 대상은 adjusted입니다.
  buff/nerf 필터는 확실하게 분류된 대상만 반환하므로 모든 버프/너프를 망라하지 않습니다.
- 현재 Riot의 h2 섹션과 h3.change-title, h4, li 구조를 지원합니다.
  기본 챔피언·아이템·룬 섹션만 대상으로 하며 ARAM/아레나 및 별도 긴급 수정 섹션은
  구조화 대상이 아닙니다. 그 내용은 패치 원문 문서에 남습니다.
- 패치 데이터는 밸런스 변경 근거이며 챔피언 승률·픽률 또는 메타 우위를 입증하지 않습니다.
- 표시 패치와 Data Dragon 버전을 추측해 연결하지 않습니다. 예: 25.18 질문에 15.18.1
  정적 자료가 자동으로 섞이지 않습니다. 대응표는 추후 별도 합의가 필요합니다.
- 상주 RAG DocumentSource는 패치별 캐시를 사용하므로 업데이트 후 새 인스턴스를 생성해야 합니다.
  GUI ask_database는 매 질문마다 새 인스턴스를 사용합니다.

### 실행 및 검증

```powershell
$env:PYTHONPATH="src"
python -m knowledge update --patches 3
python -m knowledge sync-patch 25.18
python -m knowledge changes --patch 25.18 --kind champion --type buff
python -m knowledge changes --patch 25.18 --kind rune
python -m unittest discover -s tests/integration -v
```

`--db`로 다른 DB를 사용할 때는 하위 명령 앞에 둡니다.
검증용 가상 HTML은 `tests/integration/test_out_game_knowledge.py`에 있으며,
실제 게임 수치로 사용하지 않습니다. 라이브 확인은 25.18 원문 및 최신 목록의 26.18 원문,
Data Dragon 16.18.1 자료를 사용했습니다. 신규 `league-of-legends-patch-*` URL도 지원합니다.
