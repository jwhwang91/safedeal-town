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

두 모드는 **느낌이 근본적으로 다릅니다.**

### 🛒 구매자 모드 — "검색하고, 돌아다니며 고른다"
입장 전에 **찾는 물건의 카테고리**(스마트폰·노트북·게임·캠핑·패션 … 15종, 또는 `랜덤`)를 고릅니다.
마을에는 **그 카테고리의 판매자 NPC만** 등장합니다 — 당근/번개에서 한 품목을 검색해
여러 판매글을 둘러보는 느낌입니다. (게임을 고르면 캠핑 의자가, 캠핑을 고르면 게임기가 **안** 나옵니다.)
돌아다니다 마음에 드는 판매자에게 다가가 **매물 카드 → 대화 → 🚩 → 구매/거래 중단/신고**로 마칩니다.
사기꾼은 중단·신고, 정상은 구매가 정답. HUD 의 **`🔎 찾는 물건`** + **`검색 변경`** 으로 언제든 카테고리를 바꿉니다.

### 🏪 판매자 모드 — "판매글을 올리면, 구매자가 찾아온다"
입장 전에 **한 줄 판매글**을 등록합니다(예: `아이폰 14 Pro 128GB 팔아요`). 제목에서 **카테고리를 자동 추론**하고
(직접 고르면 그 선택이 우선), 상태·가격·구성품·하자·환불원칙·준비한 증거를 덧붙일 수 있습니다.
입장하면 플레이어는 **좌판을 차린 판매자**로 한자리에 있고, **구매자 NPC 가 알아서 찾아옵니다:**

- 구매자들은 처음엔 마을을 **배회(roaming)** 하다가, 일부가 내 판매글에 **관심(👀 interested)** 을 보이고
  → **다가오며(approaching)** → 내 옆에 와서 **대기(waiting)** 하며 말풍선으로 문의합니다
  (`이거 아직 판매 중인가요?`, `상태 좀 볼 수 있을까요?`, `가격 조정 되나요?`).
- 한꺼번에 몰리지 않습니다 — **시차를 두고** 한둘이 먼저, 다른 이는 20~40초 뒤, 또 일부는 둘러보기만 하다 떠납니다.
- 가까운 구매자가 생기면 우상단에 **`🔔 구매자 문의 N건`** 알림이 뜨고, **클릭**하거나 **E/Space**로 응대를 시작합니다.
- 대화 상대는 정상/환불 빌런/막깎이/잠수러/위험거래 유도/정당한 하자 주장 중 하나(겉으론 구분 불가).
  결정: **판매 완료 / 환불 거절 / 부분 환불 / 환불 수락 / 플랫폼 분쟁 / 거래 취소**.
  침착함·증거 활용·플랫폼 안전 절차·부당 요구 거절이 높은 점수, 과잉 환불·욕설/협박·위험 거래 수락은 감점.
- HUD 의 **`🏪 내 판매글`** + **`판매글 수정`** 으로 언제든 판매글을 바꿀 수 있습니다.

> ⚖️ 판매자 모드 결과는 **중고거래 대응 훈련용 일반 정보이며 법률 자문이 아닙니다.**

---

## 마켓 · 동적 매물 · 거래 가방 (확장 시스템)

고정 NPC/아이템 게임에서 → **현실적인 중고장터 훈련 시뮬레이션**으로 확장했습니다.

### 입장 전 설정
- 🛒 **구매자**: '오늘 찾는 물건'(카테고리 15종 + 가격 민감도 + 선호 거래방식)을 고르면,
  마을에 **그 카테고리의 판매자만** 등장합니다(랜덤 선택 시 전 카테고리). 같은 카테고리 안에서 매번 다른 매물이 나옵니다.
- 🏪 **판매자**: **한 줄 판매글 제목**이 가장 중요한 필드입니다 — 제목에서 카테고리를 추론
  (`app/market/category_infer.py`, 예: `아이폰`→스마트폰, `맥북`→노트북, `닌텐도/플스`→게임, `텐트/캠핑`→캠핑,
  `패딩/신발`→패션). 직접 고르면 그 선택이 우선합니다. 상태/가격/구성품/하자/환불원칙/준비한 증거를 더하면
  찾아오는 구매자 NPC 가 **그 물건을 보고** 반응합니다. (상품 선택 시 시세·구성품 자동완성)

### 판매자 모드 — 구매자 접근 행동 (서버 + 프론트)
- 서버(`app/spawns.py`)가 구매자 스폰마다 **역할과 무관한**(정체 비노출) 접근 메타를 붙입니다:
  `approach_state`(roaming) · `interest_level` · `approach_delay_seconds`(시차) · `inquiry_preview`(중립 문의) · `target=player`.
- 프론트(`static/js/game.js`)가 이 값으로 **roaming → interested → approaching → waiting** 상태머신을 연출하고,
  관심을 보인 구매자를 **플레이어 쪽으로 이동**시키며, 머리 위 **문의 말풍선**과 우상단 **문의 알림**을 띄웁니다.
- 알림 클릭/근처에서 E·Space → **구매자 문의 카드**(닉네임·매너/후기·중립 문의 미리보기) → 대화 시작.
  **구매자의 숨은 유형(빌런/막깎이 등)은 카드/말풍선/알림 어디에도 노출되지 않습니다.**

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

---

## 🎯 미션 / 돌발 퀘스트 시스템

> **왜 필요한가**: "직거래만 할게요" 는 실제로도 자주 안전한 선택이지만, 항상 그렇게만 하면
> 게임이 너무 쉬워집니다. 미션은 **직거래가 불가능한 상황을 자기 선언적으로 설정**해서
> 택배거래·플랫폼 안전결제·실물 인증·경계 설정·침착한 분쟁 대응 같은 **현실적인 대안**도
> 연습하게 합니다. 직거래 자체가 나쁜 게 아니라, **이번 미션에서만 쓸 수 없을 뿐**입니다.

- 마을에 입장하거나(👉 셋업 완료 직후) 역할을 전환할 때, 활성 미션이 없으면 **미션 제안 카드**가
  뜹니다 (수락/건너뛰기 자유 — 게임을 막지 않습니다).
- 수락하면 HUD 좌측에 **작은 접이식 칩**(`🎯 미션 제목`)으로 표시되고, 펼치면 상황/제약/보상 미리보기 +
  **미션 포기** 버튼을 볼 수 있습니다.
- 미션을 수락한 뒤 대화를 시작하면 그 세션에 자동으로 연결되고, **거래를 종료(resolve)할 때** 채점됩니다.
- 채점은 **전부 규칙 기반**입니다(`app/missions.py::evaluate_mission_completion`) — LLM 은 코칭 문구를
  다듬지 않고, 성공/실패 판정에도 전혀 관여하지 않습니다. 체크리스트 자기보고(`checklist`) + 대화 내용
  키워드 + 기존 심판(JudgeAgent)의 `verdict/correct/missed_flags` 를 함께 봅니다.
- **핵심 거래 판정(사기냐 아니냐)은 항상 그대로**입니다 — 미션은 그 위에 "훈련 목표를 달성했는가"를
  별도로 얹을 뿐, 기존 안전/사기 채점을 대체하지 않습니다.
  예) `직거래만 할게요` 라고만 말하고 구매하면, 상대가 정상 판매자라 기본 거래는 `safe` 로 채점돼도
  **`delivery_only_buyer` 미션은 실패**합니다 (직거래가 불가능한 상황을 가정한 훈련이었으므로).
- 성공하면 **XP/신뢰도 보너스** + **미션 전용 배지**(거래 가방에 아이템으로 지급) + **보너스 아이템 확률**을 받습니다.
  실패해도 기본 거래 보상/채점에는 영향이 없습니다(미션 보너스만 0).

### 미션 목록

| 모드 | 미션 키 | 제목 | 훈련 목표 |
|------|---------|------|-----------|
| 구매자 | `delivery_only_buyer` | 택배거래로 안전하게 구매하기 | 직거래 없이 인증·안전 절차로 구매 |
| 구매자 | `safe_payment_buyer` | 안전결제로 거래 완료하기 | 플랫폼 안전결제만 사용, 외부 결제 거절 |
| 구매자 | `proof_first_buyer` | 실물 인증 받고 구매하기 | 실물/날짜 인증·구성품 확인 후 판단 |
| 구매자 | `boundary_keeper_buyer` | 사적 연락 유도 거절하기 | 플랫폼 밖 연락 요구 거절 |
| 판매자 | `delivery_safe_seller` | 택배거래로 안전하게 판매하기 | 상태 고지 + 증거 + 플랫폼 대화 유지 |
| 판매자 | `refund_boundary_seller` | 부당 환불 요구 대응하기 | 감정 대신 기록/근거로 침착 대응 |
| 판매자 | `private_contact_refusal_seller` | 사적 연락 요구 거절하기 | 플랫폼 밖 연락 요구 거절 |
| 판매자 | `lowball_boundary_seller` | 과도한 네고에 기준선 지키기 | 침착하게 기준선 유지, 필요시 거래 정리 |

### DB / API
- 테이블: `user_active_missions` (UUID id, `mission_json`/`reward_json` 은 TEXT-JSON, ISO-8601 UTC 타임스탬프,
  `CREATE TABLE IF NOT EXISTS` 로 멱등 생성 — 기존 데이터에 영향 없음). `trade_sessions` 에도
  `active_mission_id` 컬럼이, `chat_messages` 에도 `image_data_uri` 컬럼이 (멱등) 추가됩니다
  (`proof_first_buyer` 미션이 생성한 인증사진 저장용 — 아래 "미션 인증사진 생성" 참고).
- API: `GET/POST /api/game/missions/available·accept·skip·active·clear-current` (모두 `app/routers/game.py`,
  로그인 사용자 본인 것만 조회/조작 가능). `/api/chat/start` 응답에 `mission`(연결된 활성 미션),
  `/api/chat/message` 응답에 `reply.image_data_uri`(생성됐을 때만), `/api/chat/resolve` 응답에
  `mission`(채점 결과: 성공여부/사유/교훈/보너스/획득 배지)이 추가됩니다.
- 적응형 엔진 연동은 아직 하지 않습니다 — 다만 `mission_key`/`status`/타임스탬프가 `user_active_missions` 에
  누적 저장되므로, 나중에 "직거래 과의존 시 택배 미션을 더 자주 제안" 같은 적응형 로직을 얹을 수 있는
  기반 데이터는 이미 쌓입니다.

---

## 🧠 적응형 시나리오 엔진 (Adaptive Scenario Evolution Engine)

> ⚠️ **이것은 방어 훈련 시스템입니다. 사기 생성 시스템이 아닙니다.**
> "AI 가 사용자를 더 잘 속이도록 학습한다"가 **아니라**,
> **"사용자의 약한 위험 신호를 더 자주, 강한 신호는 덜 훈련시키는 적응형 방어 훈련 커리큘럼"** 입니다.
> 실제 사기 절차·가짜 결제 페이지·자격증명 수집·플랫폼 우회·실제 링크/계좌를 **생성하지 않습니다.**

### 무엇을 하나
- 거래 한 판이 끝날 때마다 **구조화된 학습 데이터**를 DB에 저장합니다 (원문 대화는 기본 저장 안 함).
- 다음 세션이 시작될 때:
  - 사용자가 **이미 숙달한** 위험 신호는 잠시 덜 등장시켜 **지루한 반복을 피하고**,
  - **자주 놓치거나 약한** 위험 신호를 **우선 훈련**시키며,
  - 페르소나 말투·페이싱·난이도를 **안전하게 변주**합니다.
- 모든 숨은 적응 로직은 **서버 전용**입니다. 프론트는 **결과 화면 이전에 숨은 역할/수법/패턴 메타데이터를 절대 받지 않습니다.**

### 핵심 모듈 (`app/ai/`)
| 모듈 | 책임 |
|------|------|
| `pattern_taxonomy.py` | 안전한 훈련 패턴 분류표(가족/라벨/위험신호/안전대응/금지 디테일) + 내부 tactic↔패턴 매핑 |
| `transcript_redactor.py` | 저장 전 전화/이메일/URL/계좌/주소/주민번호류/토큰 비식별화 + 안전 요약(digest) |
| `adaptive_repository.py` | 적응형 테이블 **DB 접근 전담**(UUID/ISO-UTC/JSON TEXT) — 미래 PostgreSQL 이전 지점 |
| `adaptive_memory.py` | 결과 기록 + 패턴별 **숙련도(mastery)·우선순위(priority)** 갱신 (규칙기반, 투명) |
| `adaptive_selector.py` | 약점 우선 + 숙달/최근 회피 + 무작위성으로 미래 패턴·난이도 선택 |
| `persona_variant.py` | 선택 패턴 기반 **안전 페르소나 변주** (template 기본 / local_claude·openai 선택, 검증·폴백) |
| `adaptive_debug.py` | (선택) `ADAPTIVE_DEBUG_EXPLAIN=true` 일 때만 선택 사유 설명 |

### 숙련도/우선순위 (투명하고 튜닝 쉬움)
```
mastery  = clamp(0.15 + 0.35·detection_rate + 0.35·resistance_rate − 0.25·failure_rate, 0, 1)
priority = clamp((1 − mastery) + 0.15(최근 놓침) − 0.15(너무 최근 반복), 0, 1)
```
- mastery 0.0 = 자주 놓침/실패, 1.0 = 꾸준히 잘 막음.
- **규칙기반 JudgeAgent 가 여전히 공식 정답의 권위입니다. LLM 은 정오를 정하지 않습니다.**
  적응형 엔진은 *시나리오 선택*만 바꾸고 *정답 라벨*은 바꾸지 않습니다.

### 안전·프라이버시 기본값
- **원문 대화 미저장**: 기본은 구조화 메타데이터 + 짧은 요약(digest)만 저장합니다.
  `STORE_REDACTED_TRANSCRIPTS=true` 일 때만, 그것도 **비식별화 후에만** 원문을 옵트인 저장합니다.
- **다중 사용자**: 모든 적응형 데이터는 `user_id` 로 분리됩니다. 단일 로컬 계정에 의존하지 않습니다.
- **실패해도 게임은 계속**: 적응형 엔진이 꺼져 있거나(`ADAPTIVE_SCENARIOS_ENABLED=false`)
  어떤 예외가 나도 기존 정적/동적 페르소나 흐름으로 **그대로 진행**합니다.

### 실력 분석 / 훈련 메모리 초기화
- 📒 전적실 → **🎓 실력 분석**: 구매자/판매자 모드별 **강점·약점·다음 훈련 추천·패턴 숙련도**를 봅니다
  (라벨/원칙만 노출, 내부 패턴 키는 비공개).
- 결과 모달의 **"🎓 이번 훈련에서 다룬 위험 신호 / 비슷한 상황에서 적용할 원칙"** 도 라벨/대응만 보여줍니다.
- **데모용 초기화**: 실력 분석 화면의 **♻️ 메모리 초기화** 또는 `POST /api/game/training-profile/reset`
  → **현재 로그인 사용자의 적응형 메모리만** 지웁니다. 계정·거래 기록·인벤토리는 **그대로** 유지됩니다.
  전역 삭제 엔드포인트는 제공하지 않습니다.

### 로컬 데모 DB ↔ 미래 서버 DB
- 지금은 **SQLite** 가 데모의 단일 진실원입니다. 단, **논리 스키마는 서버 이식을 염두에 두고** 설계했습니다:
  - 기본키는 앱 코드에서 **UUID 문자열**로 생성 (SQLite autoincrement 비의존).
  - 타임스탬프는 **ISO-8601 UTC 문자열**, JSON 페이로드는 **TEXT(JSON)** — PostgreSQL **JSONB 로 무손실 이전** 가능.
  - 적응형 SQL 은 전부 `adaptive_repository.py`(=DB 계층)에만 둡니다. **서버 전환 시 이 계층만 교체**하면 됩니다.
  - 핵심 비즈니스 로직은 SQLite 전용 동작에 의존하지 않습니다.
- 마이그레이션은 **멱등**이며 기존 데이터를 **절대 지우지 않습니다**(앱 시작 때 빠진 테이블/컬럼만 보강).

### 적응형 테이블
`ai_session_outcomes` (완료 세션 요약) · `ai_user_training_memory` (패턴별 숙련도) ·
`ai_persona_evolution_events` (선택 사유 — 디버그/분석) · `ai_pattern_catalog_snapshot` (분류표 스냅샷) ·
`ai_session_adaptive_context` (세션별 선택/변주 — **서버 전용**).

---

## 🛡️ 사기 방어 훈련·진단 플랫폼 (Business Demo Layer)

게임 위에 얹히는 **"AI 기반 개인맞춤형 디지털 사기 방어 훈련·진단 플랫폼"** 레이어입니다.
사업계획 관점의 6가지를 증명하기 위한 데모 기능입니다:

1. 현실적인 AI 사기 방어 시나리오로 **훈련**한다.
2. 개인의 **약점(위험 차원)** 을 측정한다.
3. **전/후 개선도**를 보여준다.
4. 사용자가 올린 **실제 사례를 비식별·라벨링**해 훈련 시나리오로 만든다.
5. 학교·시니어센터·지자체·금융사가 쓸 **집계 리포트/대시보드**를 제공한다.
6. DB 구조는 향후 **B2B/B2G 확장**에 대비해 서버 이식형으로 설계한다.

> 🔒 **핵심 원칙 — AI 는 "사기를 더 잘하는 법"을 절대 배우지 않습니다.** 실제 사례에서 *위험 신호만*
> 추출·비식별·라벨링해 **방어 훈련 시나리오**로 바꿉니다. 실행 가능한 사기 절차·실제 개인정보·
> 진짜 링크/계좌/전화번호는 생성하지 않습니다. 점수는 **훈련용 데모 지표**이며 의료·법률·공식 진단이 아닙니다.

게임 화면 상단 HUD 의 **🛡️ 방어훈련** 버튼으로 허브를 열면 5개 탭이 있습니다:
**취약도 진단 · 내 리포트 · 사례 공유 · 시나리오 뱅크 · 기관 데모**.

### 🎬 Business Demo Flow (핵심 데모 흐름)

1. **회원가입/로그인** → 마을 입장.
2. **사전(baseline) 진단** — 🛡️ 방어훈련 → *취약도 진단* → "사전 진단 시작". 10개 상황 문항으로 위험 차원별 판단력 측정.
3. **훈련(거래/미션 플레이)** — 구매자/판매자 모드로 거래하고, 돌발 미션(택배거래·안전결제·경계 지키기·환불 대응)을 수행.
4. **내 리포트 확인** — *내 리포트* 탭. 방어 점수 + 위험 차원별 막대 + **"왜 이 점수인가"** 근거 + 강점/보완점 + 추천 다음 행동.
5. **피해 사례 공유** — *사례 공유* 탭에서 사례 작성. 제출 즉시 **자동 비식별**(전화/이메일/URL/계좌/카톡ID 등 마스킹) 후 저장.
6. **사례 → 방어 시나리오 변환** — 사례 상세에서 "🎬 방어 시나리오로 변환". 원문을 **복제하지 않고** 위험 패턴만 추출해 픽션화된 시나리오 후보 생성(기본 검토 대기).
7. **시나리오 뱅크 검색/추천** — *시나리오 뱅크* 탭에서 키워드 검색 + "내 약점 추천"(약한 차원 기반 승인 시나리오 추천).
8. **훈련 후(post-training) 진단 + 전/후 리포트** — 다시 진단 후, *내 리포트* 하단에서 **"외부 링크 감지율 40% → 80%"** 식 개선도 비교.
9. **기관 대시보드 데모** — *기관 데모* 탭에서 데모 기관/코호트 생성 → 현재 계정을 코호트에 추가 → **집계 지표**(평균 사전/최근 점수·개선도·약한/강한 차원·미션 완료율·추천 커리큘럼) 확인.

### 위험 차원(risk dimension) 15종 — 채점의 의미 계약

`app/analytics/risk_scoring.py` 가 진단·게임·미션·부정행위를 하나로 묶는 **레지스트리**입니다.
각 진단 문항의 `risk_family` 는 이 차원 키 중 하나이고, 게임 taxonomy `pattern_family` 와 미션 키도
이 차원으로 환산됩니다. 점수는 **0~100, 높을수록 방어 역량이 강함**입니다.

시세 이상 감지 · 시간 압박 저항 · 외부 링크 유도 감지 · 선입금 거절 · 제3자 계좌 의심 · 안전한 택배거래 ·
플랫폼 대화 유지 · 개인 연락 경계 · 통화·인증 압박 대응 · 감정 신뢰 조작 경계 · 부당 환불 요구 대응 ·
판매자 부정행위 회피 · 증거 중심 대응 · 침착한 분쟁 대응 · 정당한 요구 인정.

### 프라이버시 / 비식별 동작 (`app/privacy/`)

- **저장 전 비식별이 원칙**입니다. 커뮤니티 사례·댓글은 `redactor.redact_sensitive_text()` 로
  다음을 토큰으로 가린 뒤에만 저장합니다: `[PHONE] [EMAIL] [URL] [ACCOUNT] [ID_NUMBER] [ADDRESS] [SECRET] [PRIVATE_CONTACT]`
  (카카오/텔레그램/라인/오픈채팅 등 사적 연락 채널 포함). **원문은 기본적으로 저장하지 않습니다**(`raw_body_stored=0`).
- `moderation.check_submission()` 규칙 기반 모더레이션: 개인정보가 과도하면 **자동 공개 대신 검토 대기**(pending),
  신상 공개·폭력·괴롭힘 유도는 **거부**(reject). 제출 전 사용자에게 경고 문구를 노출합니다.
- 시나리오 생성기는 **원문을 그대로 복제하지 않으며**, 생성물은 검증기를 통과해야 저장됩니다
  (숫자/링크/전화 흔적이 남으면 template 폴백).

### 시나리오 뱅크 동작 (`app/scenarios/`)

- `case_labeler.extract_case_labels()` — 규칙 기반으로 사례에서 카테고리/위험가족/압박유형/요구행동/안전대응/훈련모듈 라벨 추출.
- `generator.generate_scenario_from_case()` — **기본값 template**(규칙/템플릿). `CASE_SCENARIO_GENERATOR_PROVIDER`
  로 `local_claude`/`openai` 도 선택 가능하나, **모든 LLM 출력은 검증**되고 실패 시 template 로 폴백합니다.
- `retriever.search_scenarios()` / `recommend_scenarios()` — **RAG-lite**: 무거운 의존성 없이 SQLite `LIKE`
  검색 + 카테고리/위험가족 필터(가능하면 FTS5, 없으면 자동 LIKE 폴백). 추천은 사용자 **약점 차원**을 고려하며,
  **승인(approved)된 시나리오만** 사용합니다.
- 훈련 연결(`training_link.py`, Phase F) — 승인된 시나리오 seed 를 세션 훈련에 **비권위적 참고 힌트**로만 연결하고
  서버 전용 텔레메트리에 남깁니다. **NPC role/tactics/페르소나는 절대 바꾸지 않으므로 기존 NPC 생성이 그대로 유지**되고,
  seed 가 없거나 실패하면 기존 플로우로 폴백합니다.

### 위험 점수 계산 방식 (`app/analytics/`)

`risk_profile.build_user_risk_profile()` 가 4개 소스를 위험 차원별로 **투명하게** 합칩니다:
① 최근 진단(차원별 정답률) ② 게임 숙련도(적응형 메모리) ③ 미션 성공/실패 ④ 부정행위 신호.
각 차원은 근거(`evidence`) 문장을 함께 반환해 **"왜 이 점수인가"** 를 설명합니다. 근거가 없는 차원은
`unknown` 으로 두고 총점에서 제외합니다. `confidence` 는 근거 총량으로 `demo_low/medium/high` 를 붙입니다.

### 기관 대시보드 동작 (`app/routers/orgs.py`)

- 데모용으로 현재 사용자가 **기관/코호트를 만들고 자신을 코호트에 추가**할 수 있습니다(운영급 관리자 인증 아님).
- 대시보드는 **집계 지표만** 반환합니다: 인원 · 평균 사전/최근 점수 · 평균 개선도 · 약한/강한 차원 ·
  미션 완료율 · 훈련 카테고리 · 추천 다음 커리큘럼. **개별 대화 원문·개인 식별정보는 노출하지 않습니다.**
- 기능 게이트: `ORG_DEMO_DASHBOARD_ENABLED=false` 면 관련 API 가 404, `COMMUNITY_CASES_ENABLED=false` 면 커뮤니티 API 가 404.

### 플랫폼 레이어 테이블 (멱등 생성, `app/migrations.py`)

`assessment_question_bank` / `user_assessment_sessions` / `user_assessment_answers` ·
`community_cases` / `community_case_reactions` / `community_case_comments` / `community_case_reports` ·
`scenario_bank` / `scenario_labels` · `organizations` / `cohorts` / `cohort_members`.
적응형 테이블과 동일하게 **UUID PK · ISO-UTC · JSON(TEXT)** 로 서버 이식형이며, 앱 시작 시 멱등 생성되어
**기존 데이터를 보존**합니다.

### 설정 플래그 (`.env`)

```ini
COMMUNITY_CASES_ENABLED=true          # 커뮤니티 사례 공유 on/off (off 면 관련 API 404)
ORG_DEMO_DASHBOARD_ENABLED=true       # 기관/코호트 데모 대시보드 on/off
CASE_SCENARIO_GENERATOR_PROVIDER=template   # template | local_claude | openai (기본 template)
CASE_SCENARIO_REQUIRES_REVIEW=true    # 생성 시나리오를 승인 전 검토 대기로 둘지
```

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

### 미션 인증사진 생성 (`proof_first_buyer`, openai 모드 전용)

`실물 인증 받고 구매하기`(`proof_first_buyer`) 미션은 구매자가 판매자에게 실물/날짜 인증사진을
요청하는 습관을 훈련합니다. 이 사진은 `AI_MODE=openai` 일 때만 **OpenAI Images API**
(`app/ai/image_gen.py`)로 실제 생성됩니다 — `Settings.photo_generation_available` 이
mock/local_claude 에서는 항상 false 이므로, 그런 환경에서는 이 미션 자체가 목록/제안/직접
수락 어디에서도 노출되지 않습니다(`app/missions.py` 의 카탈로그 필터링 + `POST
/api/game/missions/accept` 의 서버 측 재검증).

```ini
OPENAI_IMAGE_MODEL=gpt-image-1          # 선택, 기본값
OPENAI_IMAGE_TIMEOUT_SECONDS=45         # 선택, 기본값 (OPENAI_API_KEY 는 위 openai 설정과 공유)
```

- 세션당 **최대 한 장**만 생성합니다(비용/스팸 방지) — 플레이어가 사진/인증을 요청하는 것처럼
  보이는 메시지(`missions.looks_like_proof_request`, 미션 채점과 동일한 키워드 기준)를 보낸
  다음 NPC 답장에 한 번만 붙습니다.
- 이미지는 파일로 저장하지 않고 **data URI(base64)** 로 `chat_messages.image_data_uri` 에
  저장해 채팅/결과 모달(대화 다시 보기)에 그대로 렌더링합니다.
- 생성 실패(키 없음/네트워크 오류/타임아웃/거부 등)는 **항상 조용히 무시**되고 텍스트만으로
  대화가 계속됩니다 — 이미지 생성은 절대 거래 흐름을 막지 않습니다.
- 프롬프트에는 실제 사람 얼굴·신분증/서류·화폐·바코드/QR·읽을 수 있는 실제 브랜드 로고/일련번호를
  **명시적으로 금지**합니다(허구의 훈련 콘텐츠임을 매번 프롬프트에 포함).
- 사진이 왔다고 해서 거래가 안전하다는 뜻은 아닙니다 — 실제로도 사기꾼이 도용한 사진을
  보여주는 경우가 있으므로, 채점(`evaluate_mission_completion`)은 여전히 "요청했는가"와
  기존 심판(JudgeAgent)의 판정만 봅니다. 사진 자체의 내용은 채점에 쓰이지 않습니다.

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
│  ├─ missions.py         미션/돌발 퀘스트 카탈로그 + 수락·포기·규칙기반 채점  ★신규
│  ├─ aftermath.py        거래 후 상황 + 현실 교훈  ★신규
│  ├─ market/             시장 데이터 어댑터 + 상품 카탈로그  ★신규
│  │  ├─ catalog.py           상품 카탈로그 + 매물 생성기
│  │  ├─ category_infer.py     판매글 한 줄 제목 → 카테고리 추론(수동 우선)  ★신규
│  │  ├─ providers.py         ListingProvider 인터페이스 + MarketListingSeed + 팩토리
│  │  ├─ synthetic_provider.py / manual_import_provider.py / trend_cache.py
│  │  └─ normalizer.py        개인정보 제거 + 정규화
│  ├─ analytics/          위험 점수·프로필·리포트  ★플랫폼
│  │  ├─ risk_scoring.py      위험 차원 15종 레지스트리(의미 계약) + 점수 헬퍼
│  │  ├─ risk_profile.py      진단+게임+미션+부정행위 통합 프로필(투명 근거)
│  │  └─ report_builder.py    개인 리포트 / 전·후 비교 / 근거 번들
│  ├─ privacy/            제출물 비식별·모더레이션  ★플랫폼
│  │  ├─ redactor.py          redact_sensitive_text (PHONE/URL/ACCOUNT/PRIVATE_CONTACT…)
│  │  └─ moderation.py        규칙 기반 accept/pending/reject 게이트
│  ├─ assessment/         사기 취약도 진단  ★플랫폼
│  │  ├─ question_bank.py     10개 카테고리 문항 시드 + 선택/공개(정답 비노출)
│  │  └─ scoring.py           답변 채점 + 세션 집계(차원별 점수/강약점)
│  ├─ scenarios/          방어 시나리오 뱅크  ★플랫폼
│  │  ├─ scenario_bank.py     저장/조회 + 데모 시나리오 시드(승인)
│  │  ├─ case_labeler.py      규칙 기반 사례 라벨 추출
│  │  ├─ retriever.py         RAG-lite 검색/추천(LIKE/FTS5, 승인만)
│  │  ├─ generator.py         사례→픽션 시나리오(template 기본·검증·폴백)
│  │  └─ training_link.py     승인 seed↔훈련 비권위적 연결(NPC 생성 불변)  ★Phase F
│  ├─ routers/
│  │  ├─ auth.py          회원가입/로그인/내 정보
│  │  ├─ game.py          셋업·선호·판매글·아바타·위치·월드·스폰·전적·인벤토리·습관리포트·미션
│  │  ├─ chat.py          거래 대화 + 프로필카드 + 보상/체크리스트/거래후상황/미션 채점
│  │  ├─ assessment.py    진단 start/answer/complete/latest/history  ★플랫폼
│  │  ├─ report.py        개인 리포트 / 전·후 / 근거  ★플랫폼
│  │  ├─ community.py     피해 사례 제출/목록/상세/댓글/공감/신고 (비식별)  ★플랫폼
│  │  ├─ scenarios.py     시나리오 검색/사례변환/추천  ★플랫폼
│  │  └─ orgs.py          기관/코호트 데모 + 집계 대시보드  ★플랫폼
│  └─ ai/
│     ├─ personas.py      판매자 NPC + 구매자 NPC + 수법/행동 사전 (동적 생성의 앵커)
│     ├─ persona_factory.py  동적 NPC/매물/프로필 카드 생성  ★신규
│     ├─ prompts.py       역할극/심판 프롬프트 (인젝션 방어 + 판매글 인지)
│     ├─ provider.py      제공자 라우팅 (mock/openai/local_claude)
│     ├─ llm_client.py    OpenAI 호환 API 래퍼
│     ├─ image_gen.py     미션 인증사진 생성 (OpenAI Images API, openai 모드 전용)  ★신규
│     ├─ local_claude_adapter.py  로컬 CLI 어댑터
│     ├─ roleplay.py      BaseRoleplayAgent / SellerAgent / BuyerAgent (판매글 인지)
│     ├─ seller_agent.py  하위호환 재노출 shim
│     ├─ judge_agent.py   심판/코치 (구매자 + 판매자 모드) — 규칙기반 정답 권위
│     ├─ privacy.py       AI 출력 위생처리
│     ├─ pattern_taxonomy.py     안전 훈련 패턴 분류표 + tactic↔패턴 매핑  ★적응형
│     ├─ transcript_redactor.py  저장 전 비식별화 + 안전 요약  ★적응형
│     ├─ adaptive_repository.py  적응형 테이블 DB 접근 전담(서버 이식 지점)  ★적응형
│     ├─ adaptive_memory.py      결과 기록 + 숙련도/우선순위 갱신  ★적응형
│     ├─ adaptive_selector.py    약점 우선 패턴/난이도 선택  ★적응형
│     ├─ persona_variant.py      안전 페르소나 변주(template 기본·검증·폴백)  ★적응형
│     └─ adaptive_debug.py       (선택) 선택 사유 설명  ★적응형
└─ static/
   ├─ index.html / css/style.css
   └─ js/  api · auth · avatar · sprites · world_map · spawn_manager · game ·
           listing_setup · setup · checklist · chat · inventory · missions · main ·
           platform · assessment · report · community · dashboard  ★플랫폼
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
| GET | `/api/game/habit-report` | 내 거래 습관 요약 (기존 거래 기록 기반) |
| GET | `/api/game/training-profile` | 🎓 실력 분석 — 모드별 강점/약점/추천/숙련도 (적응형, 사용자 안전 노출만) |
| POST | `/api/game/training-profile/reset` | 현재 사용자 적응형 메모리만 초기화 (계정·거래기록 보존) |
| POST | `/api/chat/card` | 대화 전 프로필/매물 카드 (정답지 미포함) |
| POST | `/api/chat/start·message·flag·resolve` | 거래 대화 (모드 자동 판별) — start 응답에 연결된 미션, resolve 응답에 적응형 학습 피드백 + 미션 채점 결과 포함 |
| GET | `/api/game/missions/available` | 현재 모드의 미션 카탈로그 + 활성 미션 + 지금 제안할 미션 |
| POST | `/api/game/missions/accept` | 미션 수락(활성화) — `{mission_key, session_id?}` |
| POST | `/api/game/missions/skip` | 활성 미션 포기 — `{mission_id}` |
| GET | `/api/game/missions/active` | 현재 활성 미션 (`?session_id=` 로 특정 세션 것만) |
| POST | `/api/game/missions/clear-current` | 현재 모드의 활성 미션 포기(다른 미션 다시 받기용) |

### 🛡️ 방어 훈련 플랫폼 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/assessment/start` | 진단 시작 — `{assessment_type: baseline\|post_training\|quick_check}` → 세션+첫 문항 |
| POST | `/api/assessment/answer` | 답변 제출 → 정오답·해설·다음 문항 (정답지는 문항 페이로드에 노출 안 됨) |
| POST | `/api/assessment/complete` | 진단 완료 → 총점 + 차원별 점수 + 강점/보완점 + 추천 훈련 |
| GET | `/api/assessment/latest` · `/history` | 최근 완료 진단 / 진단 이력 |
| GET | `/api/report/personal` | 개인 방어 리포트 (점수+차원+"왜 이 점수인가"+추천) |
| GET | `/api/report/before-after` | 훈련 전/후 개선도 (baseline·post 둘 다 있으면) |
| GET | `/api/report/evidence` | 점수 근거 번들 (집계만, 원문 대화 없음) |
| POST | `/api/community/cases` | 사례 제출 (저장 전 자동 비식별 + 모더레이션) |
| GET | `/api/community/cases` · `/{id}` | 사례 목록(승인만 기본) / 상세(비식별) |
| POST | `/api/community/cases/{id}/comment·react·report` | 댓글(비식별)·공감·신고 |
| GET | `/api/scenarios/search` | 시나리오 뱅크 검색 (RAG-lite: LIKE/FTS5, 승인만) |
| POST | `/api/scenarios/from-case/{case_id}` | 사례 → 픽션화된 방어 시나리오 후보 변환 |
| GET | `/api/scenarios/recommend` | 내 약점 차원 기반 승인 시나리오 추천 |
| POST | `/api/orgs/demo/create` | 데모 기관+코호트 생성 (현재 계정 자동 추가) |
| POST | `/api/orgs/demo/cohort/add-current-user` | 현재 계정을 코호트에 추가 |
| GET | `/api/orgs/demo/dashboard` · `/list` | 코호트 **집계** 대시보드 / 내 기관·코호트 목록 |

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

### 미션 / 돌발 퀘스트 점검
24. 마을 입장 직후(또는 역할 전환 직후) 활성 미션이 없으면 **미션 제안 카드**가 뜬다. 건너뛰어도 게임은 그대로 진행된다.
25. 구매자 모드에서 `delivery_only_buyer` 미션을 수락하면 HUD에 **작은 미션 칩**이 뜬다.
26. 대화에서 **"직거래만 할게요" 류로만 말하고** 구매하면, 기본 거래 채점(사기/정상)과 별개로
    **미션은 실패**로 표시되고 "직거래가 불가능한 상황에서 택배거래를 훈련하는 미션이었다"는 설명이 뜬다.
27. 다시 미션을 받아 **실물 인증 요청 + 안전한 절차(택배/안전결제) 언급**을 하고 정상 거래를 완료하면
    **미션이 성공**하고, XP/신뢰도 보너스 + 배지가 결과 모달에 보인다.
28. 판매자 모드에서 `refund_boundary_seller` 미션을 수락하고 **기록/근거 중심으로 침착하게** 환불을 거절하면
    미션이 성공한다.
29. 같은 미션에서 **욕설/협박성 표현**으로 대응하면 기본 판정이 `unsafe_response` 로 깎이고 **미션도 실패**한다.
30. HUD 미션 칩 → 펼치기 → **미션 포기** 버튼으로 언제든 미션을 취소할 수 있다.
31. 미션은 NPC 의 숨은 역할/수법을 전혀 노출하지 않는다 (미션 카드/HUD/결과 어디에도 정답지 없음).
32. `python run.py` 재시작 후에도 기존 계정/거래 기록이 보존되고 `user_active_missions` 테이블이 생성돼 있다.
33. `AI_MODE=mock` 또는 `local_claude` 에서는 `proof_first_buyer` 미션이 목록/제안/직접 수락(400) 어디서도 노출되지 않는다.
34. `AI_MODE=openai` + 유효한 `OPENAI_API_KEY` 로 `proof_first_buyer` 를 수락하고 대화에서 실물/인증사진을
    요청하면, NPC 답장에 **실제 생성된 인증사진**이 한 번(세션당 최대 1장) 붙고 결과 모달의
    "대화 다시 보기"에도 남는다. 키가 없거나 이미지 생성이 실패해도 채팅/채점은 그대로 계속된다.

### 적응형 엔진 점검
35. 구매자 모드 한 판을 마치면 `ai_session_outcomes` 에 행이 생기고 `ai_user_training_memory` 가 갱신된다.
36. 여러 판을 더 하면 셀렉터가 **숙달·최근 패턴은 덜**, **약한 패턴은 더** 고른다.
37. 판매자 모드 패턴은 구매자 모드와 **분리 저장**된다(`game_role` 구분).
38. 📒 전적실 → **🎓 실력 분석** 에 모드별 강점/약점/추천/숙련도가 보인다.
39. `ADAPTIVE_SCENARIOS_ENABLED=false` 면 게임이 **이전과 동일**하게 동작(적응형 기록 없음).
40. `STORE_REDACTED_TRANSCRIPTS=true` 로 두고 채팅에 전화/이메일/URL 을 입력하면 저장된 대화가 **비식별화**된다.
41. `AI_MODE=local_claude` 에서 CLI 실패 시에도 게임/적응형 기록이 **mock 폴백**으로 이어진다.
42. 프론트는 **결과 화면 이전에 숨은 역할/수법/패턴 키를 받지 않는다**(개발자도구로도 안 보임).
43. **♻️ 메모리 초기화** 또는 `POST /api/game/training-profile/reset` 후 적응형 데이터만 지워지고 **계정·거래 기록은 유지**된다.

### 🛡️ 방어 훈련 플랫폼 점검
44. HUD **🛡️ 방어훈련** → 허브의 5개 탭(진단/리포트/사례/시나리오/기관)이 열린다.
45. *취약도 진단* → "사전 진단 시작" → 10문항을 끝까지 풀면 **총점 + 위험 차원별 점수 + 강점/보완점 + 추천 훈련**이 뜬다.
46. 진단 중 **정답이 문항 페이로드에 노출되지 않는다**(개발자도구 네트워크 탭 확인) — 답을 내야 해설/정답이 온다.
47. 거래/미션 몇 판 후 *내 리포트* 에 **방어 점수 + "왜 이 점수인가" 근거** + 위험 차원 막대 + 추천 다음 행동이 보인다.
48. *사례 공유* → "사례 나누기" 에서 **가짜 전화/이메일/URL/계좌/카톡ID** 를 적어 제출하면, 목록/상세에 뜨는 본문이
    `[PHONE]/[URL]/[ACCOUNT]/[PRIVATE_CONTACT]` 등으로 **가려져** 있다(원문 노출 없음). 개인정보가 많으면 **검토 대기**로 접수된다.
49. 사례 상세 → "🎬 방어 시나리오로 변환" 시 생성 시나리오에 **원문·개인정보가 들어있지 않다**(위험 패턴만 픽션화).
50. *시나리오 뱅크* 에서 키워드 검색 + "내 약점 추천"이 동작한다(승인 시나리오만).
51. *취약도 진단* 을 `post_training` 으로 한 번 더 하면 *내 리포트* 하단에 **전/후 개선도**가 나온다.
52. *기관 데모* 에서 데모 기관/코호트 생성 → 내 계정 추가 → **집계 대시보드**(인원·평균 점수·개선도·약한/강한 차원·완료율)가 보인다. 원문 대화·개인정보는 없다.
53. 모바일 폭(≈390px)으로 줄여도 **가로 스크롤이 없고** 탭/카드/폼이 사용 가능하다.
54. `COMMUNITY_CASES_ENABLED=false` / `ORG_DEMO_DASHBOARD_ENABLED=false` 로 두면 해당 API 가 404 이고, 프론트가 "비활성화" 안내를 보여준다.
55. `python run.py` 재시작 후에도 기존 데이터가 보존되고, 새 플랫폼 테이블이 생성돼 있으며 콘솔에 JS 에러가 없다.

빠른 자동 점검(선택):
```bash
python -m compileall app            # 파이썬 컴파일 점검
for f in static/js/*.js; do node --check "$f"; done   # JS 문법 점검

# 수동 import 위생처리 빠른 확인 (샘플을 복사해서 테스트)
cp runtime/imports/market_listings.example.json runtime/imports/market_listings.json
MARKET_LISTING_PROVIDER=manual_import python -c "from app.market import fetch_seeds; print([s.product_name for s in fetch_seeds('random', 5)])"

# 적응형 메모리만 초기화 (CLI, DB 직접) — runtime DB 를 백업해두고 실험할 때
python -c "import sqlite3; from app.config import get_settings; \
c=sqlite3.connect(get_settings().database_path); \
[c.execute('DELETE FROM '+t) for t in ('ai_session_outcomes','ai_user_training_memory','ai_persona_evolution_events','ai_session_adaptive_context')]; \
c.commit(); print('적응형 메모리 초기화 완료 (계정/거래기록 보존)')"
```
