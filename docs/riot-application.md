# RiftFlow — Riot API 신청 자료

작성일: 2026-09-15. 아래는 제출용 초안이며 접수·승인 완료를 의미하지 않습니다.

## 신청 경로

1. https://developer.riotgames.com/ 에서 본인 라이엇 계정으로 로그인합니다.
2. 기존 RiftFlow 제품 등록이 있는지 확인합니다. 있으면 중복 신청 대신 기존 제품을 갱신합니다.
3. 비공개 5인 캡스톤 개발이므로 Personal API Key / Personal Project 경로를 우선 선택합니다.
4. 아래 문안을 실제 신청 화면의 항목에 맞춰 입력합니다.
5. 라이엇이 요청하는 정보가 있으면 실제 값만 기입합니다. 심사 중에는 개발용 키로 비공개 개발합니다.

개발용 키는 24시간마다 비활성화됩니다. 공개 알파·베타는 Personal Key 범위가 아닙니다.
공개 운영 전 Production Key와 서버 측 키 보관 구조를 준비합니다.
로그인만으로 사용할 수 있는 Development Key와 심사하는 Personal Key 신청은 구분합니다.

## Product name

RiftFlow

## Project URL

https://github.com/A1-devLab/RiftFlow

MVP source branch: codex/mvp-desktop
기본 브랜치에는 MVP가 아직 병합되지 않았을 수 있으므로 브랜치와 실행 방법을 함께 제공합니다.

## Short description

A private, five-person university capstone prototype for League of Legends learning, combining official game knowledge with source-grounded explanations and planned post-game self-review.

## Detailed description — copy into the application

RiftFlow is a private university capstone project developed by a five-person team. The target platform is a Python/PySide6 Windows desktop application. We are requesting a Personal API Key for non-public development and testing within our team, primarily for Korean-region player data.

The current MVP collects official Data Dragon champion summaries, items and runes, along with recent Korean patch notes, into a local SQLite database. Users can browse the documents and retrieve relevant evidence for League of Legends questions. Optional Gemini integration generates Korean explanations using the retrieved public game documents and displays source references. A clearly labeled offline example mode is available without API credentials. This MVP does not yet call the Riot server APIs or automatically detect a logged-in League account.

With API access, the next development milestone is to let a team member enter their own Riot ID, resolve it using ACCOUNT-V1, and retrieve their completed games and timelines using MATCH-V5. We plan to calculate transparent self-review metrics, including CS, gold progression, deaths, vision and item purchase timings. LEAGUE-V4 may be used for the player's current rank context. We will show the actual number and period of retrieved games rather than promise complete seasonal history. We will not create MMR/ELO estimates or identify anonymized players.

The current MVP does not implement in-game overlays, live item recommendations, automated rune changes, enemy cooldown tracking, hidden-position inference, or gameplay automation. These are not features we consider approved by this application. Possible future LCU account/champion-selection detection, user-triggered rune application, and live decision-support features will be described separately for Riot's review before use or release, including confirmation of the rules applicable in Korea.

The project is non-commercial and limited to private team testing. Credentials are not committed to the repository. Public distribution of API credentials is not supported. The current optional Gemini requests contain the user's typed question and retrieved public game documentation; the MVP does not automatically send Riot account identifiers or match histories to Gemini. We will review data handling before adding any player-data-based AI feature. We will comply with rate limits, handle HTTP 429 responses, minimize retained data and provide the required Riot non-endorsement notice. Before any public beta or commercial launch, we will apply for the appropriate production access and revise the architecture and product registration accordingly.

## Requested services

- ACCOUNT-V1: resolve the user's own Riot ID to PUUID.
- MATCH-V5: completed match IDs, match details and timelines for self-review.
- LEAGUE-V4: current rank context, if needed.
- No tournament API or RSO access is requested for this milestone.

## Separate policy questions — not a claim of approval

We may later explore the following features and would appreciate confirmation of the permitted scope for Korean users:

1. LCU-based current-account and champion-selection detection.
2. Rune-page creation/selection only after an explicit user click, preserving existing personal pages.
3. In-game educational item alternatives using client-visible data, with explanations and trade-offs rather than hidden information or automated actions.

These features are not enabled in our current MVP. Please advise on the applicable endpoint restrictions and review procedure.

## Demo flow

1. Install and run `python -m ui` following README.md.
2. Inspect the clearly labeled offline examples.
3. Switch to the knowledge library and select a document to see its source.
4. Ask a question with Gemini disabled to view retrieved evidence without paid calls.
5. Run the official-data update, then search the collected SQLite data.
6. Optional: configure a local Gemini key/model and explicitly enable AI answers.

## Official references

- https://developer.riotgames.com/docs/portal
- https://developer.riotgames.com/docs/lol
- https://developer.riotgames.com/policies/general
