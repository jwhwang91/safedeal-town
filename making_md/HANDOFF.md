# 중고타운 (SafeDeal Town) — 세션 인계 문서 (HANDOFF)

> 새 세션이 이 파일만 읽고 바로 이어서 작업할 수 있도록 정리한 문서.
> 작성 시점: 2026-06-29. 작성: 이전 세션(2-사이드 마켓플레이스 업그레이드 완료).

---

## 0. 한 줄 요약

구매자 전용 사기탐지 게임을 **양방향(구매자/판매자) 중고거래 훈련 시뮬레이터**로 업그레이드 완료.
기존 구매자 플로우는 그대로 보존. 백엔드/프론트 전 구간 구현 + 라이브 브라우저 검증까지 끝남.
`python run.py` 로 키 없이 바로 실행됨.

---

## 1. 현재 상태 (무엇이 되어 있나)

- ✅ **Phase 1** 역할/아바타 셋업 (스키마·API·셋업 화면·아바타 렌더)
- ✅ **Phase 2** 절차적 시드 기반 동네 맵 (백엔드 생성 → 프론트 렌더)
- ✅ **Phase 3** NPC 스폰/디스폰 (백엔드 active_spawns + 프론트 폴링)
- ✅ **Phase 4** 판매자 모드 (구매자 페르소나·BuyerAgent·판매자 결정·채점·면책)
- ✅ **Phase 5** 로컬 Claude 어댑터 (AI_MODE=local_claude, 실패 시 mock 폴백)
- ✅ **Phase 6** README/.env.example/.gitignore/테스트 체크리스트
- ✅ **리뷰 9건 수정** (아래 §7 참고) + 캐시 무효화(`?v=`) 적용

### 라이브 검증 완료 (헤드리스 Chrome, 실서버 :8000)
- 로그인 → 셋업 화면 → 디테일한 동네(도로·광장·분수·공원·간판 가게·NPC) 렌더, JS 에러 0
- 구매자/판매자 두 모드 채팅·채점·결과 모달(판매자 면책 고지 포함) 정상
- local_claude: 잘못된 인자/행 위험에도 mock 폴백, 행(hang) 없음

### DB 현재 상태 (중요)
- 실 DB `runtime/safedeal_town.sqlite3` 는 **이미 마이그레이션됨**: NPC 11명(판매자 5 + 구매자 6), 새 컬럼/테이블 존재.
- 기존 계정 **`jwhwang91`**: `setup_completed=0`, `game_role=NULL` → **다음 로그인 시 셋업 화면이 뜸** (정상 동작).
- 마이그레이션은 멱등이며 기존 데이터(회원/거래기록)를 보존함.

---

## 2. 실행 방법

```bash
cd /Users/seungchanboi/github_projects/safedeal-town
cp .env.example .env            # 이미 있으면 생략. Windows: .\start.ps1
pip install -r requirements.txt
python run.py                   # http://localhost:8000
```

- 키 하나도 없어도 동작 (mock + 절차적 맵).
- 시작 배너에 다음 줄이 보이면 **새 코드**가 도는 것:
  `[SafeDeal Town] 맵 제공자: procedural`
- 버전 확인용 빠른 체크:
  `curl -s http://localhost:8000/api/health` → 새 코드는 `map_provider` 필드가 있음.

### ⚠️ 캐시 주의 (지난 세션에서 가장 큰 혼란 포인트)
새 코드인데 브라우저가 **옛 main.js/game.js(같은 파일명)** 를 캐시해서 "네모난 단순 맵 + 셋업 없음"으로 보이는 함정이 있었음.
- 해결책으로 모든 JS/CSS 링크에 `?v=2` 를 붙였고, index.html 은 `Cache-Control: no-cache` 로 서빙함.
- **정적 파일을 수정하면 `static/index.html` 의 `?v=` 숫자를 올릴 것** (예: `?v=2` → `?v=3`). 안 그러면 사용자 브라우저가 옛 파일을 계속 씀.
- 증상이 또 나오면: 서버 완전 재시작(`lsof -ti:8000 | xargs kill -9` 후 `python run.py`) + 브라우저 완전 종료 후 재접속, 또는 DevTools→Application→Service Workers 해제.

---

## 3. 두 가지 모드

| | 구매자 모드 (기존) | 판매자 모드 (신규) |
|---|---|---|
| 상대 | 판매자 NPC (scammer/honest) | 구매자 NPC (정상/빌런/막깎이/잠수/위험/정당한하자) |
| 결정 | 구매 / 거래 중단 / 신고 | 판매 완료 / 환불 거절 / 부분 환불 / 환불 수락 / 플랫폼 분쟁 / 거래 취소 |
| 에이전트 | SellerAgent | BuyerAgent |
| 채점 | JudgeAgent.evaluate | JudgeAgent.evaluate_seller_mode |
| 결과 | verdict + 코칭 | verdict + 코칭 + **면책 고지** |

모드는 **상대 NPC 종류(npc_kind)** 로 자동 결정됨. 역할은 셋업 화면에서 고름.

---

## 4. 아키텍처 / 핵심 계약

- **맵은 백엔드가 단독 생성**(`app/worldgen.py`), 프론트(`static/js/world_map.js`)는 받은 대로만 그림.
  같은 시드 → 같은 동네(결정적). 위경도 대략값(소수 2자리) 또는 사용자 고유 시드.
- **스폰은 백엔드가 관리**(`app/spawns.py`, 테이블 `active_spawns`). 프론트는 `/api/game/spawns` 폴링(6초).
- **정답지 보호 불변식**: NPC 의 `role`/`tactics`, 그리고 **role 을 노출하는 `npc_id` 슬러그**, 구매자 외형 테마/이름은
  절대 클라이언트로 안 내려감. 클라이언트는 `spawn_instance_id` 만 들고 다니고, 채팅 시작 시 서버가 npc_id 로 매핑.
- **AI 제공자 추상화**(`app/ai/provider.py`): mock / openai / local_claude. 채팅 UI 는 출처를 모름. 실패는 전부 mock 폴백.
- **정오(correct)/verdict 는 규칙 기반**. LLM 은 코칭 문구·뉘앙스에만 사용.

### API 요약
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET/POST | `/api/game/setup` | 역할/아바타/카테고리 조회·저장 |
| POST | `/api/game/avatar` | 아바타만 갱신 |
| POST | `/api/game/location` | 대략 위치 저장 → 맵 시드 (스폰 비우고 재생성) |
| GET | `/api/game/world` | 맵 + 플레이어(아바타/역할) + 스폰 |
| GET | `/api/game/spawns` | 활성 스폰(만료 정리 + 충원) |
| POST | `/api/game/spawns/refresh` | 강제 새로고침(개발용) |
| POST | `/api/chat/start` | `{spawn_instance_id}` 로 시작 (npc_id 는 서버가 매핑) |
| POST | `/api/chat/{message,flag,resolve}` | 대화/의심표시/종료채점 |

---

## 5. 파일 맵

### 새 백엔드 파일
- `app/migrations.py` — 멱등 마이그레이션 (기존 데이터 보존)
- `app/worldgen.py` — 시드 기반 절차적 동네 생성
- `app/spawns.py` — NPC 등장/소멸 관리
- `app/ai/provider.py` — 제공자 라우팅(mock/openai/local_claude)
- `app/ai/roleplay.py` — BaseRoleplayAgent / SellerAgent / BuyerAgent
- `app/ai/local_claude_adapter.py` — 로컬 CLI subprocess 어댑터(타임아웃/트리킬/JSON/위생)
- `app/ai/privacy.py` — AI 출력 위생처리(길이 제한 등)

### 수정된 백엔드
- `app/config.py` (AI/맵/로컬CLI 설정, `ai_provider`/`map_provider_effective` 프로퍼티)
- `app/database.py` (init 시 migrations 호출), `app/schema.sql`, `app/seed.py`(UPSERT)
- `app/models.py`, `app/main.py`(배너/health/no-cache), `app/routers/{auth,game,chat}.py`
- `app/ai/{personas,prompts,judge_agent,seller_agent(shim),llm_client}.py`

### 새 프론트
- `static/js/{avatar,sprites,world_map,spawn_manager,setup}.js`

### 수정된 프론트
- `static/index.html`(셋업 화면·판매자 버튼·면책·`?v=2`·script 순서)
- `static/css/style.css`(셋업/아바타/역할배지/판매자버튼/면책 스타일)
- `static/js/{api,game,chat,main}.js`

### 문서/설정
- `README.md`(재작성), `.env.example`(채움), `.gitignore`(신규)

### 스크립트 로드 순서 (index.html, 중요)
`api → auth → avatar → sprites → world_map → spawn_manager → game → setup → chat → main`

---

## 6. AI 모드 / 맵 제공자 (.env)

```ini
AI_MODE=mock            # mock | openai | local_claude
OPENAI_API_KEY=         # openai 모드일 때
CLAUDE_CODE_COMMAND=claude
CLAUDE_CODE_ARGS=       # "{prompt}" 자리표시자 가능, 없으면 stdin
CLAUDE_CODE_TIMEOUT_SECONDS=60
MAP_PROVIDER=procedural # procedural | google | naver (키 없으면 procedural 폴백)
GOOGLE_MAPS_API_KEY=
NAVER_MAP_CLIENT_ID=
NAVER_MAP_CLIENT_SECRET=
```

- 키 노출 안 함. google/naver 도 결국 도트 스타일 절차적 동네로 그림(타일 SDK 미로드).

---

## 7. 지난 리뷰에서 고친 9건 (재발 방지용 기록)

1. `npc_id` 슬러그가 role 을 노출 → 클라이언트에 npc_id 미전송, `spawn_instance_id` 로 서버 매핑.
2. 구매자 `visual_theme`/이름이 role 노출 → 테마는 스폰별 무작위(역할 무관), 이름 중립화(도윤/보라/형석/유진/재희/민서).
3. `missed_legitimate_claim` verdict 도달 불가 → **`legit_claim_buyer`(민서) 페르소나 추가** + 판정표 보강.
4. 거래중(engaged) NPC 중복 스폰 → `_fill` 이 active+engaged 둘 다 점유로 계산.
5. `LLMClient._post` 의 JSON/Type 오류 누수 → except 확대 + content:null → LLMError.
6. `chat_json` content:null TypeError → 가드 + except 확대.
7. `shlex.split(CLAUDE_CODE_ARGS)` ValueError 누수 → try→LLMError.
8. 에이전트/심판이 LLMError 만 잡음 → `except Exception` 으로 확대(어떤 제공자 오류든 mock 폴백).
9. local_claude 윈도우 hang → Popen + 프로세스 트리 킬(killpg/taskkill) + 파이프 정리.

추가: 스폰 RNG 가 초 단위 시드라 특정 유형 누락 → `random.Random()`(엔트로피)로 변경해 6종 고르게 등장.

---

## 8. 알려진 한계 / 주의

- `local_claude` 는 임의 CLI 대상 best-effort. 정확한 인자는 사용자 CLI에 따라 다름. 게임은 절대 안 멈춤(타임아웃→mock).
- google/naver 는 메타데이터 라벨일 뿐, 실제 지도 타일은 안 불러옴(키 비노출·오프라인 보장 목적).
- 위치는 ~1km 반올림만 저장, 정밀 위치 저장 안 함.
- 윈도우 트리킬 경로는 코드로 구현했으나 실제 윈도우에서 직접 실행 검증은 안 됨(맥에서 검증).
- 판매자 모드 채점은 의도적으로 규칙 기반 휴리스틱(LLM 은 코칭 문구만). 교육용이지 법률 자문 아님.
- 게임 내 역할 변경 UI 는 없음(셋업에서 정함). 필요하면 추가 가능(아래 §10).

---

## 9. 수동 테스트 체크리스트

1. `python run.py` 키 없이 기동 (배너에 "맵 제공자" 줄 확인).
2. 회원가입/로그인.
3. 셋업 미완료 시 셋업 화면.
4. 역할(구매자/판매자)+아바타(+카테고리) 선택.
5. 새로고침 후 아바타/역할 유지.
6. 구매자: 대화→🚩→구매/중단/신고→채점.
7. 판매자: 대화→판매자 결정→채점+면책 고지.
8. 맵이 단순 격자가 아니라 동네로 보임.
9. 위치 거부해도 마을 생성+플레이.
10. NPC 가 시간 지나면 사라지고 다시 나타남.
11. NPC 외형이 카테고리/유형마다 다름.
12~14. mock/openai/local_claude 동작 또는 mock 폴백.
15~16. 네트워크 응답에 role/tactics/npc_id/키 없음.

빠른 점검:
```bash
python -m compileall app
for f in static/js/*.js; do node --check "$f"; done
```

---

## 10. 다음에 해볼만한 것 (선택 / 백로그)

- 게임 내 "역할 변경/아바타 변경" 버튼 (현재는 셋업에서만).
- 화면 구석에 빌드 태그(예: `v2`) 노출 → 캐시 최신 여부 한눈에 확인.
- 판매자 모드 NPC/시나리오 다양화(정당한 하자 케이스 더 추가 등).
- google/naver 실제 타일을 도트화해서 깔아보기(키 있을 때).
- 자동 테스트 스위트(pytest)로 §9 체크리스트 일부 자동화.
- 사운드/간단한 등장 연출 등 폴리시.

---

## 11. 새 세션 시작 멘트(복붙용)

> 이 프로젝트는 `safedeal-town` 이고, `making_md/HANDOFF.md` 에 현재 상태가 정리돼 있어.
> 그걸 먼저 읽고, [여기에 다음 작업 적기] 를 이어서 해줘.
> 정적 파일 고치면 `static/index.html` 의 `?v=` 숫자를 올려야 브라우저 캐시가 갱신돼.
