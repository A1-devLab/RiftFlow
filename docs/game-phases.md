# 게임 단계별 구조

```text
test.py
└── src/game_phases/
    ├── common.py
    ├── before_game/
    │   ├── prompt.py
    │   └── service.py
    ├── in_game/
    │   └── service.py
    └── after_game/
        └── service.py
```

## 실행

저장소 루트에서 `python test.py`를 실행하고 1~3 중 하나를 선택합니다.

## before_game 수정 위치

- `src/game_phases/before_game/prompt.py`: Gemini 역할, 답변 규칙과 게임 전 상황 형식
- `src/game_phases/before_game/service.py`: 터미널에서 받을 질문과 사용자 입력 항목
- `src/game_phases/common.py`: 공통 Gemini 호출과 결과 출력. 단계별 프롬프트 작업에서는 수정하지 않음
- `src/knowledge/`: 공통 DB 수집·조회. 단계별 프롬프트 작업에서는 수정하지 않음
- `src/rag/`: 공통 검색·근거·Gemini 처리. 단계별 프롬프트 작업에서는 수정하지 않음

프롬프트 담당자는 기본적으로 `before_game/prompt.py`의 `SYSTEM` 문구를 수정합니다. DB 근거 형식을 바꾸어야 할 때만 같은 파일의 `build` 함수를 수정합니다. `build`는 공통 RAG가 만든 근거에 상대 챔피언과 플레이 성향을 추가한 뒤 Gemini로 전달합니다.

현재 DB에는 챔피언 요약, 아이템, 룬 설명과 패치 노트가 있습니다. 정확한 챔피언 상성 통계나 완성된 룬 페이지 조합 데이터는 없으므로 프롬프트만으로 만들어내지 않습니다. 이후 해당 자료를 DB에 추가하면 같은 검색 흐름에서 사용할 수 있습니다.
