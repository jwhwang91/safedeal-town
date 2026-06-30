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

## 마켓 · 동적 매물 · 거래 가방 (확장 시스템)

고정 NPC/아이템 게임에서 → **현실적인 중고장터 훈련 시뮬레이션**으로 확장했습니다.

### 입장 전 설정
- 🛒 **구매자**: '오늘 찾는 물건'(카테고리 15종 + 가격 민감도 + 선호 거래방식)을 고르면,
  마을에 그 카테고리의 **매번 다른 매물**이 등장합니다.
- 🏪 **판매자**: '내 판매글'(상품/상태/가격/구성품/하자/환불원칙/준비한 증거)을 정의하면,
  찾아오는 구매자 NPC 가 **그 물건을 보고** 반응합니다. (상품 선택 시 시세·구성품 자동완성)

### 시장 데이터 어댑터 (`app/market/`)
NPC 매물은 '시장 맥락 제공자'로 생성됩니다. `.env` 의 `MARKET_LISTING_PROVIDER` 로 선택:

| 값 | 설명 |
|----|------|
| `synthetic` (기본) | 내장 카탈로그로 합성. 키 불필요, **오프라인 항상 동작**. |
| `manual_import` | 개발자가 둔 안전한 CSV/JSON 을 **개인정보 제거 후** 사용 (`runtime/imports/`). |
| `trend_cache` | 비식별·집계된 시장 트렌드 캐시 기반 생성 (`runtime/market_trends.json`). |
| `official_stub` | (미구현) 공식 API 자리표시자 — **실제 호출/스크래핑 없음**. |

> 🔒 **안전/법적 경계**: 당근마켓·번개장터 등 실서비스 **스크래핑/크롤링/로그인 자동화는 하지 않습니다.**
> 실제 게시글 원문·이미지·사용자명·연락처·정확한 주소·계좌번호를 복제·표시하지 않습니다.
> 수동 import 데이터는 `normalizer` 가 개인정보(이름/전화/이메일/주소 지번/계좌/URL/핸들)를
> 모두 제거한 비식별 메타데이터만 사용합니다. 선택한 제공자가 실패하면 자동으로 `synthetic` 폴백합니다.
> 프레이밍은 **"실시장 트렌드를 참고한 가상 NPC/매물 생성"** 이지 "실제 게시글 복제"가 아닙니다.

### 동적 NPC + 프로필/매물 카드
- `app/ai/persona_factory.py` 가 기본 페르소나를 '앵커'로 삼아 매물·이름·성격·말투·대사를 매번 새로 입힙니다.
  (정답지인 role/tactics 는 앵커에서 유지 → 검증된 채점/FK 무결성 보존)
- 대화 전 **프로필/매물 카드**(시세·상태·구성품·거래방식 + 가입/후기/매너/인증 같은 공개 메타데이터)를 보여줍니다.
  사기꾼도 좋아 보이는 프로필을 가질 수 있어, **카드만으로는 정답을 알 수 없습니다.**

### 거래 가방(인벤토리) · 보상 · 거래 도구
- 거래를 성공하면 **거래 도구 / 신뢰 배지 / 코스튬**을 보상으로 얻습니다 (희귀도는 점수·난이도·판정에 따라).
- 🎒 **가방** 버튼으로 보유 아이템을 장착/해제합니다.
  - **코스튬**(후드/탐정 안경/고수 모자 등)은 아바타에 즉시 반영됩니다.
  - **거래 도구**(최대 2개)는 대화 중 현실적인 **체크리스트/답변칩/주의 신호**를 제공합니다.
    예) 시세 레이더(가격 주의), 링크 경고기(외부 링크 경고), 사진 인증 키트(요청 답변칩),
    환불 대응 카드(침착 거절/부분환불/분쟁 템플릿), 거래 기록 폴더(증거 활용 알림).
  - 도구는 **정답을 대신 알려주지 않습니다** — 확인 습관을 돕는 도구일 뿐입니다.
- 모든 거래 결정 화면에 **거래 체크리스트**(시세 확인/실물 인증/외부 링크 거절 등)가 있고,
  올바른 결정일 때 소폭 가점됩니다 (자기보고식이라 상한 +4).

### 거래 후 상황 + 거래 습관 리포트
- 결과 모달에 **"거래 후 상황" + "현실에서의 교훈"** 을 짧게 보여줍니다 (교육적, 비자극적).
- 🎒 가방 → **내 거래 습관**: 기존 거래 기록으로 강점/보완점/다음 훈련 추천을 요약합니다.

> 🧩 적응형 장기 메모리(Adaptive Scenario Evolution Engine)는 **아직 미구현**입니다.
> 위 시스템들은 향후 그 엔진과 호환되도록(선호/판매글/매물 씨앗을 일반화) 설계되었습니다.

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
│  ├─ preferences.py      구매 위시리스트 + 판매글 저장소  ★신규
│  ├─ rewards.py          인벤토리 아이템 정의/지급/장착 + 보상 굴리기  ★신규
│  ├─ aftermath.py        거래 후 상황 + 현실 교훈  ★신규
│  ├─ market/             시장 데이터 어댑터 + 상품 카탈로그  ★신규
│  │  ├─ catalog.py           상품 카탈로그 + 매물 생성기
│  │  ├─ providers.py         ListingProvider 인터페이스 + MarketListingSeed + 팩토리
│  │  ├─ synthetic_provider.py / manual_import_provider.py / trend_cache.py
│  │  └─ normalizer.py        개인정보 제거 + 정규화
│  ├─ routers/
│  │  ├─ auth.py          회원가입/로그인/내 정보
│  │  ├─ game.py          셋업·선호·판매글·아바타·위치·월드·스폰·전적·인벤토리·습관리포트
│  │  └─ chat.py          거래 대화 + 프로필카드 + 보상/체크리스트/거래후상황
│  └─ ai/
│     ├─ personas.py      판매자 NPC + 구매자 NPC + 수법/행동 사전 (동적 생성의 앵커)
│     ├─ persona_factory.py  동적 NPC/매물/프로필 카드 생성  ★신규
│     ├─ prompts.py       역할극/심판 프롬프트 (인젝션 방어 + 판매글 인지)
│     ├─ provider.py      제공자 라우팅 (mock/openai/local_claude)
│     ├─ llm_client.py    OpenAI 호환 API 래퍼
│     ├─ local_claude_adapter.py  로컬 CLI 어댑터
│     ├─ roleplay.py      BaseRoleplayAgent / SellerAgent / BuyerAgent (판매글 인지)
│     ├─ seller_agent.py  하위호환 재노출 shim
│     ├─ judge_agent.py   심판/코치 (구매자 + 판매자 모드)
│     └─ privacy.py       AI 출력 위생처리
└─ static/
   ├─ index.html / css/style.css
   └─ js/  api · auth · avatar · sprites · world_map · spawn_manager · game ·
           listing_setup · setup · checklist · chat · inventory · main
```

---

## 주요 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET/POST | `/api/game/setup` | 역할/아바타/카테고리 조회·저장 (+ 선호 프리필) |
| GET | `/api/game/catalog` | 카탈로그 메타 (카테고리/상태/상품 자동완성) |
| GET/POST | `/api/game/preferences` | 구매 위시리스트 (카테고리/가격/거래방식) |
| GET/POST | `/api/game/listing` | 판매자 판매글 (위생처리 저장) |
| POST | `/api/game/avatar` | 아바타만 갱신 |
| POST | `/api/game/location` | 대략 위치 저장 → 맵 시드 |
| GET | `/api/game/world` | 맵 + 플레이어(아바타+장착효과) + 스폰 |
| GET | `/api/game/spawns` · POST `/spawns/refresh` | 활성 스폰 목록 / 강제 새로고침 |
| GET | `/api/game/inventory` · POST `/equip` · `/unequip` | 거래 가방 / 장착·해제 |
| GET | `/api/game/rewards/catalog` | 아이템 도감 |
| GET | `/api/game/habit-report` | 내 거래 습관 요약 |
| POST | `/api/chat/card` | 대화 전 프로필/매물 카드 (정답지 미포함) |
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
17. 구매자 셋업에서 카테고리를 고르면 그 카테고리의 **다양한 매물**이 등장한다(같은 카테고리도 매번 다른 물건/가격/상태/성격).
18. 판매자 셋업에서 판매글을 만들면 구매자 NPC 가 **그 물건/하자**를 보고 반응한다.
19. NPC 가까이서 E/Space → **프로필/매물 카드** → '대화 시작'.
20. 거래 성공 시 보상 아이템이 드랍되고, 🎒 가방에서 장착하면 아바타/체크리스트에 반영된다.
21. 결과 모달에 **거래 후 상황 + 현실 교훈**, 🎒 → **내 거래 습관** 리포트가 보인다.
22. `MARKET_LISTING_PROVIDER=manual_import` 로 둔 샘플(JSON)의 **개인정보(이름/전화/이메일/주소/계좌/URL)가 제거**된다.
23. 어떤 마켓 제공자도 **실서비스 스크래핑을 하지 않는다** (synthetic 폴백 보장).

빠른 자동 점검(선택):
```bash
python -m compileall app            # 파이썬 컴파일 점검
for f in static/js/*.js; do node --check "$f"; done   # JS 문법 점검

# 수동 import 위생처리 빠른 확인 (샘플을 복사해서 테스트)
cp runtime/imports/market_listings.example.json runtime/imports/market_listings.json
MARKET_LISTING_PROVIDER=manual_import python -c "from app.market import fetch_seeds; print([s.product_name for s in fetch_seeds('random', 5)])"
```
