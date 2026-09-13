# rag 샘플 데이터

**대상 범위는 소환사의 협곡(맵 11)입니다.** 칼바람나락과 아레나는 범위 밖입니다.
같은 이름의 아이템이 모드별로 다른 ID, 다른 골드, 다른 능력치를 가지므로 섞으면 틀린 근거가 됩니다.

개인정보가 없는 데이터만 둡니다. 실제 계정, Riot ID, PUUID, 소환사명, 대화 로그는 넣지 않습니다.
아래 형식은 **논의용 초안**입니다. 공통 데이터 형식은 팀 합의 후 `src/contracts/`에 작성합니다.

## 폴더

```text
tests/fixtures/rag/
  README.md                         이 문서
  documents_ddragon.json            근거 자료 목록
  documents_empty.json              검색 결과 없음
  questions.json                    챗봇 질문과 검증 조건
  tools/build_ddragon_fixtures.py   근거 자료 생성 스크립트
```

rag 담당이 만들고 rag 테스트만 쓰는 파일은 모두 이 폴더에 둡니다. `tests/fixtures/` 바로 아래에는 두지 않습니다.
다른 담당자의 fixture 와 섞여 이 문서나 스크립트가 공용처럼 보이지 않게 하려는 것입니다.

테스트 코드는 `tests/integration/test_rag_*.py` 에 있습니다.
knowledge 담당의 `test_knowledge.py` 와 같은 방식이고, `tests` 아래에 `__init__.py` 가 없어
하위 폴더로 옮기면 `unittest discover` 가 찾지 못하기 때문에 그대로 둡니다.

근거 자료는 knowledge 모듈이 돌려줄 결과를 흉내 낸 것이지만 `knowledge/` 폴더에 두지 않습니다.

- `docs/interfaces.md` 는 각 담당자가 자기 예시를 추가하도록 정합니다. knowledge 결과물의 예시는 knowledge 담당의 몫입니다.
- 이 파일은 knowledge 의 공식 출력이 아닙니다. `get_documents` 는 아직 없고 반환 형식도 합의 전이라,
  rag 담당이 Data Dragon 에서 받아 초안 형식으로 만든 것입니다.

knowledge 의 실제 출력 형식이 정해지면 그 담당자가 자기 예시를 따로 추가하고, rag 는 그 형식에 맞춥니다.

파일을 폴더로 나눌지 `knowledge_patch.html` 처럼 이름 앞에 모듈명을 붙일지는 팀 규칙이 아직 없습니다.
지금은 두 방식이 섞여 있으니 합의 후 한쪽으로 맞춥니다.

## 근거 자료 (`documents_ddragon.json`)

**Riot Games Data Dragon의 실제 데이터**입니다. 지어낸 수치가 아닙니다.
Data Dragon은 공개 정적 데이터라 API 키가 필요 없고 개인정보가 들어가지 않습니다.

| `kind` | 수 | 범위 |
|---|---|---|
| `item` | 177 | 협곡에서 살 수 있는 500골드 이상 아이템 전부 |
| `rune` | 62 | 핵심 룬과 하위 룬 전부 |
| `champion` | 173 | 전부. 스킬, 패시브, 라이엇의 운영 조언(`allytips`, `enemytips`) 포함 |
| `patch` | 1 | 최신 패치 노트 발췌 |

파일 크기는 약 900KB 입니다. 챔피언 상세 파일을 173번 받으므로 재생성에 20초쯤 걸립니다.

**Data Dragon 에는 포지션(탑, 정글, 미드 등) 정보가 없습니다.**
`recommended` 필드도 비어 있습니다. "탑 챔피언 추천" 에 답하려면 다른 출처가 필요하며, 아직 정하지 않았습니다.

재생성:

```powershell
python tests/fixtures/rag/tools/build_ddragon_fixtures.py tests/fixtures/rag/documents_ddragon.json
```

항상 최신 패치를 받아오므로 결과의 `patch` 값과 `doc_id` 접미사가 바뀝니다.
`rag/questions.json`의 `must_cite_doc_ids`도 같이 갱신해야 합니다.

이 스크립트는 fixture 생성용이며, 운영에서 쓸 자료 수집기가 아닙니다.
실제 수집과 DB는 `src/knowledge/` 담당자가 관리합니다 (`docs/architecture.md`).

### 문서 형식

`docs/interfaces.md`의 "자료에는 문서 ID, 기준 패치, 제목, 출처 URL을 연결한다"를 따릅니다.

| 필드 | 설명 | 출처 |
|---|---|---|
| `doc_id` | `출처:kind:entity_id:버전` 형태의 고유 ID | 생성 |
| `kind` | `item`, `rune`, `champion`, `patch` | 생성 |
| `entity_id` | 아이템 ID, 룬 ID, 챔피언 키 또는 패치 글 slug | Data Dragon / 패치 노트 |
| `version` | `kind` 에 따라 의미가 다릅니다. 아래 참고 | Data Dragon / 패치 노트 |
| `subject_name` | 표시용 이름 | Data Dragon |
| `title` | 문서 제목 | 생성 |
| `source_url` | 출처 URL. 답변에서 사용자에게 보여 줄 근거 | 생성 |
| `text` | 검색 및 답변 근거가 되는 본문. 마크업 제거 | Data Dragon |
| `fields` | 골드, 능력치, 조합식, 룬 계열 등 | Data Dragon |
| `situation_tags` | 어떤 상황에서 유효한지 | 아래 참고 |
| `content_hash` | 원본 내용의 sha256. 변경 감지용 | 생성 |
| `updated_at` | 수집 시점. UTC ISO 8601 | 생성 |

`situation_tags` 는 출처가 섞여 있습니다.

| 대상 | 태그 출처 |
|---|---|
| 아이템 10개, 핵심 룬 14개 | **RiftFlow 자체 주석** (`SITUATION_OVERLAY`). 검증되지 않은 판단입니다 |
| 나머지 아이템 | Data Dragon 의 아이템 `tags` 를 옮긴 것 (`SpellBlock` → `상대AP위주` 등) |
| 챔피언 | Data Dragon 의 역할 `tags` 와 `info` 에서 옮긴 것 (`Fighter` → `브루저`, 공격 점수 > 마법 점수 → `AD챔피언`) |

"왜 사야 하는지"를 설명하는 재료이며, 근거로 인용할 때는 이 태그가 아니라 `text`와 `source_url`을 씁니다.

챔피언의 `fields.damage_type` 은 `info.attack` 과 `info.magic` 을 비교한 값입니다.
아크샨, 렐, 세라핀, 벡스는 `info` 가 난이도까지 전부 `0` 입니다. 난이도 0 인 챔피언은 없으므로
점수가 아니라 값이 비어 있는 것으로 보고 `damage_type` 을 `null` 로 둡니다. `혼합` 으로 적지 않습니다.

### `version` 은 `kind` 에 따라 의미가 다릅니다

`src/knowledge/` 의 `records` 테이블과 **같은 규칙**입니다.

| `kind` | `version` 값 | 어디서 오나 |
|---|---|---|
| `item`, `rune`, `champion` | `16.18.1` | `api/versions.json` 의 첫 항목 |
| `patch` | `26.18` | 패치 노트 제목에서 추출 |

**번호 체계가 서로 다르며 한쪽에서 다른 쪽을 계산할 수 없습니다.**
`16.18.1` 을 잘라서 `16.18` 을 만들면 존재하지 않는 값이 됩니다. 실제 패치 번호는 `26.18` 입니다.
둘을 이어 주는 대응표는 아직 없습니다. 필요해지면 팀에서 정합니다.

`kind`, `entity_id`, `version`, `content_hash`, `updated_at` 은 모두 `records` 테이블 용어를 그대로 쓴 것입니다.
fixture 를 실제 DB 로 바꿀 때 조회 코드를 고치지 않아도 되게 하기 위해서입니다.

### `content_hash` 는 `text` 가 아니라 원본을 해싱합니다

`src/knowledge/` 의 `save()` 와 같은 방식입니다.

| `kind` | 해시 대상 |
|---|---|
| `item`, `rune`, `champion` | `json.dumps(entity, ensure_ascii=False, sort_keys=True)` |
| `patch` | 본문 **전문** (발췌가 아님) |

가공한 `text` 를 해싱하면 DB 값과 달라지므로 원본을 씁니다.
실제로 `ddragon:item:3031:16.18.1` 의 해시는 `records` 테이블에 들어갈 값과 같습니다.

다만 두 군데는 원본 자체가 달라 해시도 다릅니다.

- **챔피언**: fixture 는 `champion/{id}.json`(상세), `src/knowledge/` 는 `champion.json`(목록)을 해싱합니다.
  상세 수집이 추가되면 같아집니다.
- **패치 노트**: fixture 의 `text` 는 발췌지만 해시는 전문 기준입니다. 그래야 DB 와 비교됩니다.

### 재생성하면 `updated_at` 이 바뀝니다

`updated_at` 은 생성 시각이라 내용이 그대로여도 매번 달라집니다.
`records` 테이블과 같은 동작이며, 내용이 바뀌었는지는 `content_hash` 로 판단합니다.
diff 에 시각만 바뀐 줄이 보이면 실제 변경이 없다는 뜻입니다.

파일 맨 위의 `ddragon_version` 과 `patch` 는 이 fixture 를 만든 시점의 정보이며, 문서별 값이 아닙니다.

### 값 규칙

- 없는 값은 `null`로 씁니다. 숫자 `0`과 구분합니다 (`docs/interfaces.md`).
- 경기 시간을 쓰게 되면 단위는 초입니다.
- 검색 결과 없음은 빈 배열(`documents_empty.json`)로 나타냅니다. 호출 제한이나 게임 미실행과는 다른 상황입니다.
- 아이템은 소환사의 협곡(맵 11)에서 쓸 수 있는 것만 담습니다. `maps` 검사는 "협곡 전용인가"가 아니라
  "협곡에서 쓸 수 있는가"입니다. 예를 들어 헤르메스의 시미터는 `3139`(3200골드, 협곡 사용 가능),
  `223139`(2500골드), `773139`(3700골드)로 나뉘며 `3139`만 담습니다.
- **맵 검사만으로는 부족합니다.** 6자리 ID 아이템 중에도 `maps["11"]` 이 참인 것이 있어서, 4자리 ID 아이템만 담습니다.
  이 규칙으로 협곡 표시가 켜진 6자리 아이템 43개가 빠집니다.
  - 6자리 ID 는 다른 모드용 사본으로 보고 뺍니다. 예: `322065` 는 `2065`(슈렐리아의 군가) 앞에 `32` 를 붙인 것이고 이름도 같습니다.
    6자리 440개 중 279개가 이런 모양입니다.
  - 나머지 161개(예: `663193`)는 이름이 같은 짝이 없는데도 같이 뺍니다.
  - 실제 경기 기록에서 협곡 아이템이 4자리로 오는지는 아직 확인하지 않았습니다.
    6자리로 오는 협곡 아이템이 있으면 이 규칙을 고쳐야 합니다.
- 룬과 챔피언에는 모드별 변형이 없어 이 검사를 적용하지 않습니다.
- 챔피언은 `champion.json`(목록)이 아니라 `champion/{id}.json`(상세)에서 읽습니다.
  목록 파일에는 `spells` 와 `passive` 가 없어서 룬 추천 근거를 만들 수 없습니다.
  **`src/knowledge/` 프로토타입은 현재 목록 파일만 수집하므로, 상세 수집 추가를 요청해야 합니다.**
- `kind='patch'` 문서의 `text` 는 **발췌**입니다. 패치 노트 본문은 저작물이고 전문이 16000자가 넘어
  저장소에 두지 않습니다. `fields.full_text_chars` 에 전체 길이를, `source_url` 에 원문 주소를 남깁니다.
  전문은 `src/knowledge/` DB 에서 읽습니다.

## 질문 샘플 (`rag/questions.json`)

기대 답변 문장 대신 만족해야 할 **조건**을 적습니다. 생성 결과는 매번 달라지기 때문입니다.
`must_cite_doc_ids`는 답변이 반드시 인용해야 할 근거 문서입니다.

## 전적 데이터를 넣을 때

아직 없습니다. 추가한다면 아래를 지켜야 합니다.

- Riot ID, PUUID, 소환사명은 제거합니다. 본인과 나머지 참가자 9명 모두 해당합니다.
- 챔피언, 포지션, KDA, CS, 골드, 아이템 구매 순서, 타임라인 등 분석에 쓰는 지표만 남깁니다.
- 원본 API 응답은 `data/` 아래에 두며 Git에 올리지 않습니다 (`.gitignore`가 `/data/*`를 제외합니다).
- Riot API 호출은 `src/riot/` 담당자가 맡고, RAG는 변환된 공통 형식을 받아 씁니다.
