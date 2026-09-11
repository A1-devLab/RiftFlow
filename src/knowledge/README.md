# RiftFlow 파이썬 맛보기

라이엇의 게임 정보와 최근 한국어 패치 노트를 SQLite 파일에 저장하는 작은 예제입니다. Python 3.11 이상과 인터넷 연결만 필요합니다. 별도 패키지 설치나 API 키는 필요 없습니다.

## 실행

저장소 루트에서 먼저 `python -m pip install -e .`를 실행하세요. 실행 시 추가 패키지는 필요하지 않으며, 설치에는 프로젝트의 기존 setuptools 설정을 사용합니다.

설치하지 않고 PowerShell에서 실행하려면 `$env:PYTHONPATH="src"` 설정 후 아래 명령을 실행하세요.

DB 경로 변경: `python -m knowledge --db data/demo.db update`

## 명령

이 파일들이 들어 있는 폴더에서 터미널을 열고 실행하세요. Windows에서 `python`이 인식되지 않으면 `py`로 바꿔 실행할 수 있습니다.

```sh
python -m knowledge update
python -m knowledge status
python -m knowledge search 아리 --kind champion
python -m knowledge search 아리 --kind patch
python -m knowledge search 무한의 --kind item
```

처음 `update`를 실행하면 실행 폴더 아래 `data/riftflow.db`가 만들어집니다. 다시 실행하면 새 데이터는 추가하고, 동일한 버전에서 내용이 달라진 데이터는 수정하며, 동일한 내용은 그대로 둡니다. 새 버전이 나오더라도 기존 버전의 데이터는 남습니다.

최근 패치 개수는 `python -m knowledge update --patches 5`처럼 지정합니다. 공식 목록에 노출된 최신 글부터 최대 12개까지 확인합니다. 실행 중 다운로드가 실패하면 이번 업데이트는 취소하고 기존 데이터를 유지합니다.

## 들어 있는 기능

- Data Dragon 최신 버전의 한국어 챔피언 요약, 아이템, 룬 데이터 저장
- 최근 패치 노트 3개의 제목, 본문 텍스트, 출처 저장
- 중복 방지 및 내용 해시 비교로 수정 감지
- 종류·버전별 개수 확인, 키워드 검색(최대 10건)

DB의 `records` 테이블에는 종류, 버전, 대상 ID, 이름, 내용, 출처, 내용 해시, 변경 시각이 저장됩니다. 게임 데이터는 JSON 문자열로 보관합니다. `kind + version + entity_id` 조합이 중복 저장을 방지합니다.

## 맛보기 범위

- 업데이트는 명령을 실행할 때 이루어집니다. 자동 예약 실행, 웹 화면, 챗봇·벡터 검색은 포함하지 않았습니다.
- 패치 본문을 저장하며 챔피언별 변경 전·후 수치나 상향·하향을 자동 판정하지 않습니다.
- 챔피언 데이터는 목록 파일의 요약 정보입니다. 모든 챔피언의 상세 스킬 파일을 수집하지 않습니다.
- Data Dragon 버전과 패치 노트의 표시 버전은 별개로 보관합니다. 최신 Data Dragon이 한국 서버 최신 패치와 일치한다고 가정하지 않습니다.
- 최신 버전부터 수집을 시작합니다. 과거의 전체 게임 데이터를 소급해서 가져오거나 동일 글의 수정 전 원문을 따로 보존하지는 않습니다.
- 패치 글은 공식 페이지의 순서를 사용합니다. 최근 N개 밖의 오래된 글 수정은 이번 실행에서 확인하지 않습니다.
- 공식 사이트 HTML 구조가 바뀌면 패치 수집 부분을 수정해야 할 수 있습니다.

## 공식 출처

- [라이엇 Data Dragon 문서](https://developer.riotgames.com/docs/lol#data-dragon)
- [한국어 패치 노트](https://www.leagueoflegends.com/ko-kr/news/tags/patch-notes/)

발표 설명 예시: “라이엇의 게임 정보와 패치 노트를 수집해 DB에 저장하고, 다시 실행하면 신규 정보와 변경 내용을 반영하는 초기 프로토타입입니다.”

## 팀 연동 범위

현재는 독립 실행용 프로토타입입니다. 공통 contracts 및 docs/interfaces.md의 get_documents/sync_patch 후보 함수는 아직 구현하지 않았습니다. 팀 합의 후 연결합니다.

## 검증

저장소 루트에서 `python -m unittest discover -s tests/integration -p "test_knowledge*.py" -v`로 오프라인 테스트를 실행합니다. 테스트는 임시 DB와 공개 정보 형식의 가짜 응답을 사용하며 인터넷에 연결하지 않습니다.
