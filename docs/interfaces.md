# 모듈 간 입출력 약속

아래는 논의용 초안입니다. 실제 함수와 데이터 모델은 아직 구현하지 않았습니다.
팀 합의 후 contracts/에 공통 데이터 형식을 작성합니다.

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
