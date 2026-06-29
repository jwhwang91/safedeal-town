# 중고타운 — 사기꾼은 누구?

중고거래 **양방향 대응 훈련 시뮬레이터**.
위치 기반으로 생성된 도트/픽셀 마을을 돌아다니며 AI NPC 와 직접 채팅하고,
**구매자**로서 사기 판매자를 가려내거나 **판매자**로서 진상·위험 구매자에 안전하게 대응하는 연습을 합니다.

- 백엔드: **FastAPI + SQLite**
- 프론트엔드: **HTML5 Canvas (바닐라 JS)** — 탑다운 2D 마을
- AI: **역할극 에이전트 + 심판/코치 에이전트** (제공자 비의존: mock / openai / local_claude)

---

## 빠른 시작

### Windows (PowerShell)
```powershell
.\start.ps1
```
`start.ps1` 이 `.env` 를 만들고, 패키지를 설치한 뒤 서버를 켭니다.

### 수동 실행 (모든 OS)
```bash
cp .env.example .env          # Windows: copy .env.example .env
pip install -r requirements.txt
python run.py
```
서버가 뜨면 브라우저에서 **http://localhost:8000** 으로 접속하세요. (Python 3.11 기준)

> 키가 하나도 없어도 그대로 실행됩니다. 전부 안전한 로컬 폴백(mock + 절차적 맵)으로 동작해요.

---

## 두 가지 플레이 모드

로그인 후 **설정 화면**에서 역할과 아바타를 고릅니다 (다음 로그인 때 자동 복원).

### 🛒 구매자 모드 (기존 게임플레이 유지)
판매자 NPC(사기꾼/정상)와 대화하고, 수상한 메시지에 **🚩** 표시 후
**구매 / 거래 중단 / 신고** 로 마칩니다. 사기꾼은 중단·신고, 정상은 구매가 정답.

### 🏪 판매자 모드 (신규)
찾아오는 구매자 NPC(정상/환불 빌런/막깎이/잠수러/위험거래 유도)에 대응합니다.
결정: **판매 완료 / 환불 거절 / 부분 환불 / 환불 수락 / 플랫폼 분쟁 / 거래 취소**.
침착함·증거 활용·플랫폼 안전 절차·부당 요구 거절이 높은 점수를 받고,
과잉 환불·욕설/협박·위험 거래 수락은 감점됩니다.

> ⚖️ 판매자 모드 결과는 **중고거래 대응 훈련용 일반 정보이며 법률 자문이 아닙니다.**

---

## AI 모드 (mock / openai / local_claude)

`.env` 의 `AI_MODE` 로 동작이 갈립니다. 어떤 모드든 **실패 시 자동으로 mock 폴백**합니다.

| 모드 | 설명 | 필요한 것 |
|------|------|-----------|
| `mock` (기본) | 내장 시나리오 대사. 키 없이 바로 플레이. | 없음 |
| `openai` | OpenAI 호환 API 로 NPC가 매번 다르게 반응. | `OPENAI_API_KEY` |
| `local_claude` | 내 PC 의 Claude Code/호환 CLI 를 subprocess 로 호출 (개인 로컬용). | 로컬 CLI |

```ini
# openai 예시
AI_MODE=openai
OPENAI_API_KEY=sk-...

# local_claude 예시 (특정 명령을 강제하지 않음 — 본인 환경에 맞게)
AI_MODE=local_claude
CLAUDE_CODE_COMMAND=claude
CLAUDE_CODE_ARGS=
CLAUDE_CODE_TIMEOUT_SECONDS=60
```

`local_claude` 는 system 프롬프트 + 대화기록을 합쳐 **JSON 출력**을 요청하고,
방어적으로 파싱·위생처리하며, 타임아웃/명령없음/오류 시 정적 mock 으로 떨어집니다.
`CLAUDE_CODE_ARGS` 에 `{prompt}` 자리표시자가 있으면 인자로, 없으면 stdin 으로 프롬프트를 전달합니다.

내부적으로 채팅 UI 는 응답 출처(mock/openai/local_claude)를 전혀 모릅니다 — `app/ai/provider.py` 가 추상화합니다.

---

## 맵 제공자 (procedural / google / naver)

| 값 | 설명 |
|----|------|
| `procedural` (기본) | 시드 기반 절차적 동네 생성. 키 불필요, **항상 동작**. |
| `google` | `GOOGLE_MAPS_API_KEY` 없으면 procedural 로 폴백. |
| `naver` | `NAVER_MAP_CLIENT_ID/SECRET` 없으면 procedural 로 폴백. |

설정 화면에서 위치 사용에 동의하면 **대략 좌표(소수 2자리, 약 1km)** 로 마을 시드를 만듭니다.
거부하거나 키가 없어도 사용자 고유 시드로 마을이 생성됩니다.
어떤 경우에도 캔버스는 도트/픽셀 스타일 동네(도로·인도·광장·공원·건물·랜드마크)로 그려집니다.
지도 SDK 키는 프론트로 노출하지 않습니다.

---

## NPC 등장/소멸

NPC 는 고정 배치가 아니라 백엔드(`app/spawns.py`)가 관리합니다.
역할에 맞는 NPC 풀에서 랜덤으로 골라 보행 가능한 자리에 등장하고,
랜덤 수명이 지나면 사라지고 다른 NPC 가 다른 자리에 나타납니다.
프론트는 `/api/game/spawns` 를 주기적으로 폴링해 마을을 갱신합니다.
NPC 의 정체(role)·수법(tactics)은 절대 프론트로 내려가지 않습니다.

---

## 외부 접속

`.env` 의 `HOST=0.0.0.0` 이면 같은 와이파이의 다른 기기에서 `http://<내 PC IP>:8000` 으로 접속 가능합니다.
인터넷 공개는 공유기 **포트포워딩(8000)** + **방화벽 인바운드 허용** 이 필요합니다.
배포 시 `JWT_SECRET`, `PASSWORD_PEPPER` 를 반드시 길고 랜덤한 값으로 바꾸세요.

---

## 프로젝트 구조

```
safedeal-town/
├─ run.py / start.ps1 / requirements.txt / .env.example / .gitignore
├─ app/
│  ├─ main.py             FastAPI 앱 / 라우터 / 정적파일
│  ├─ config.py           .env 로더 (AI/맵/로컬CLI 설정 포함)
│  ├─ database.py         SQLite 연결 + 초기화(스키마→마이그레이션→시드)
│  ├─ migrations.py       멱등 마이그레이션 (기존 데이터 보존)  ★신규
│  ├─ schema.sql          DB 스키마
│  ├─ seed.py             NPC 시드 (안전한 UPSERT)
│  ├─ worldgen.py         시드 기반 절차적 동네 생성  ★신규
│  ├─ spawns.py           NPC 등장/소멸 관리  ★신규
│  ├─ security.py / models.py / deps.py
│  ├─ routers/
│  │  ├─ auth.py          회원가입/로그인/내 정보
│  │  ├─ game.py          셋업·아바타·위치·월드·스폰·진행도·전적
│  │  └─ chat.py          거래 대화 (구매자/판매자 모드 모두)
│  └─ ai/
│     ├─ personas.py      판매자 NPC + 구매자 NPC + 수법/행동 사전
│     ├─ prompts.py       역할극/심판 프롬프트 (인젝션 방어 포함)
│     ├─ provider.py      제공자 라우팅 (mock/openai/local_claude)  ★신규
│     ├─ llm_client.py    OpenAI 호환 API 래퍼
│     ├─ local_claude_adapter.py  로컬 CLI 어댑터  ★신규
│     ├─ roleplay.py      BaseRoleplayAgent / SellerAgent / BuyerAgent  ★신규
│     ├─ seller_agent.py  하위호환 재노출 shim
│     ├─ judge_agent.py   심판/코치 (구매자 + 판매자 모드)
│     └─ privacy.py       AI 출력 위생처리  ★신규
└─ static/
   ├─ index.html / css/style.css
   └─ js/  api · auth · avatar · sprites · world_map · spawn_manager · game · setup · chat · main
```

---

## 주요 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET/POST | `/api/game/setup` | 역할/아바타/카테고리 조회·저장 |
| POST | `/api/game/avatar` | 아바타만 갱신 |
| POST | `/api/game/location` | 대략 위치 저장 → 맵 시드 |
| GET | `/api/game/world` | 맵 + 플레이어(아바타/역할) + 스폰 |
| GET | `/api/game/spawns` | 활성 스폰 목록 (만료 정리/충원) |
| POST | `/api/game/spawns/refresh` | 스폰 강제 새로고침 (개발용) |
| POST | `/api/chat/start·message·flag·resolve` | 거래 대화 (모드 자동 판별) |

---

## 수동 테스트 체크리스트

1. `python run.py` 로 서버가 뜬다 (키 없이).
2. 회원가입/로그인이 된다.
3. 셋업 미완료 시 **설정 화면**이 먼저 뜬다.
4. 역할(구매자/판매자) 선택 + 아바타 커스터마이즈가 된다.
5. 새로고침 후에도 아바타/역할이 유지된다.
6. 구매자 모드: 판매자와 대화 → 🚩 → 구매/중단/신고 → 채점.
7. 판매자 모드: 구매자와 대화 → 판매자 결정 → 채점 + **면책 고지** 표시.
8. 맵이 단순 격자가 아니라 도로·건물·공원·랜드마크가 있는 동네로 보인다.
9. 위치를 거부해도 마을이 생성되고 플레이된다.
10. NPC가 시간이 지나면 사라지고 다시 나타난다.
11. NPC 외형이 카테고리/유형마다 다르다.
12. `AI_MODE=mock` 은 키 없이 동작한다.
13. `AI_MODE=openai` 는 키가 있으면 실시간 응답, 없으면 mock 폴백.
14. `AI_MODE=local_claude` 는 CLI 가 없으면 안전하게 mock 폴백.
15. 브라우저 개발자도구로 봐도 사기꾼/구매자 정체(role/tactics)가 안 보인다.
16. 지도/AI API 키가 프론트로 노출되지 않는다.

빠른 자동 점검(선택):
```bash
python -m compileall app            # 파이썬 컴파일 점검
for f in static/js/*.js; do node --check "$f"; done   # JS 문법 점검
```
