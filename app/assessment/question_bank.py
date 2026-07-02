"""
사기 취약도 진단 문항 뱅크 (baseline / post_training / quick_check 공용).

이 문항들은 '사기를 잘하는 법'을 묻지 않는다. 사용자가 '어떤 위험 신호에 약한지'를
측정하기 위해, 실제 상황에서의 '가장 안전한 대응'을 고르게 하는 판단형 문항이다.
모든 프롬프트는 픽션화·방어적으로 작성했고, 실제 전화/링크/계좌/이름은 담지 않는다.

계약(contract):
  - 각 문항의 risk_family 는 rs.DIMENSION_KEYS 중 하나(그 문항이 측정하는 위험 차원)다.
  - question_type 은 전부 single_choice, 정답은 correct_answer_json={"correct_keys":[...]} 로 저장한다.
  - seed_assessment_questions(conn) 는 migrations 가 부팅 때 호출한다(멱등 UPSERT). commit 은 호출자 몫.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.analytics import risk_scoring as rs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------
#  문항 정의 (정적 시드 — 10개 카테고리 전부, 카테고리당 2개 이상)
#  각 항목: id / category / risk_family / prompt / options(a~d) / correct / explanation / difficulty
#  주의: correct 키가 항상 'b' 가 되지 않도록 일부 문항은 정답 위치를 섞었다.
# ------------------------------------------------------------
_QUESTIONS: list[dict] = [
    # ============ 1) 중고 직거래/시세 (used_marketplace) ============
    {
        "id": "q_used_marketplace_01",
        "category": "used_marketplace",
        "risk_family": "price_anomaly_detection",
        "difficulty": "easy",
        "prompt": "인기 최신 스마트폰을 시세의 반값에 '오늘만 급처'로 판다고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "급처 기회이니 바로 선입금한다"},
            {"key": "b", "text": "왜 이렇게 싼지 확인하고, 시세를 비교하며 실물·안전결제 확인 전엔 입금하지 않는다"},
            {"key": "c", "text": "판매자가 친절하니 개인 계좌로 먼저 보낸다"},
            {"key": "d", "text": "다른 사람이 채갈까 봐 예약금부터 빠르게 보낸다"},
        ],
        "correct": ["b"],
        "explanation": "시세보다 지나치게 싼 '급처'는 대표적 미끼예요. 왜 싼지 먼저 묻고, 확인 전 입금은 미루는 게 안전합니다.",
    },
    {
        "id": "q_used_marketplace_02",
        "category": "used_marketplace",
        "risk_family": "evidence_based_response",
        "difficulty": "medium",
        "prompt": "판매자가 실물 사진 대신 인터넷에 흔한 제품 홍보 사진만 보낸다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "사진이 있으니 믿고 진행한다"},
            {"key": "b", "text": "오늘 날짜·특정 각도의 실물 사진과 구성품 인증을 요청하고, 응하지 않으면 보류한다"},
            {"key": "c", "text": "후기가 많다니 그냥 결제한다"},
            {"key": "d", "text": "급하니 우선 절반만 입금한다"},
        ],
        "correct": ["b"],
        "explanation": "홍보용 사진은 누구나 구할 수 있어요. 오늘 날짜가 드러나는 실물 인증을 요청해 근거를 확보하세요.",
    },
    {
        "id": "q_used_marketplace_03",
        "category": "used_marketplace",
        "risk_family": "safe_delivery_trade",
        "difficulty": "medium",
        "prompt": "판매자가 '안전결제 수수료가 아깝다'며 개인 계좌 직접 입금을 요구한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "수수료를 아끼려고 계좌로 보낸다"},
            {"key": "b", "text": "플랫폼 안전결제를 유지하겠다고 하고, 거부하면 거래를 중단한다"},
            {"key": "c", "text": "판매자를 믿고 절반만 계좌로 보낸다"},
            {"key": "d", "text": "수수료를 반씩 나누자고 하고 계좌로 보낸다"},
        ],
        "correct": ["b"],
        "explanation": "안전결제 회피 유도는 위험 신호예요. 수수료보다 거래 안전이 우선입니다.",
    },
    # ============ 2) 전화금융사기류 압박 (voice_phishing) ============
    {
        "id": "q_voice_phishing_01",
        "category": "voice_phishing",
        "risk_family": "voice_phishing_like_pressure",
        "difficulty": "medium",
        "prompt": "'수사기관·은행 직원'이라며 전화로 계좌가 범죄에 연루됐다고 겁을 주고 즉시 확인이 필요하다고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "시키는 대로 앱을 설치하고 정보를 입력한다"},
            {"key": "b", "text": "통화를 끊고, 공식 대표번호로 내가 직접 다시 걸어 사실을 확인한다"},
            {"key": "c", "text": "급하니 우선 계좌 비밀번호를 알려준다"},
            {"key": "d", "text": "상대가 불러주는 번호로 다시 전화한다"},
        ],
        "correct": ["b"],
        "explanation": "공공기관은 전화로 이체·앱 설치를 요구하지 않아요. 반드시 끊고 공식 번호로 직접 확인하세요.",
    },
    {
        "id": "q_voice_phishing_02",
        "category": "voice_phishing",
        "risk_family": "urgency_pressure_resistance",
        "difficulty": "medium",
        "prompt": "전화 상대가 '지금 바로 처리하지 않으면 계좌가 정지된다'며 계속 재촉한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "정지될까 봐 시키는 대로 즉시 이체한다"},
            {"key": "b", "text": "재촉일수록 한 박자 멈추고, 끊은 뒤 공식 채널로 직접 확인한다"},
            {"key": "c", "text": "통화를 유지한 채 은행 앱을 조작한다"},
            {"key": "d", "text": "상대가 보낸 링크로 본인인증을 한다"},
        ],
        "correct": ["b"],
        "explanation": "'지금 당장'이라는 압박 자체가 판단을 흐리려는 수법이에요. 재촉당할수록 결정을 미루세요.",
    },
    {
        "id": "q_voice_phishing_03",
        "category": "voice_phishing",
        "risk_family": "off_platform_link_detection",
        "difficulty": "hard",
        "prompt": "전화 상대가 문자로 보낸 링크를 눌러 '보안 앱'을 설치하라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "보안을 위해 링크의 앱을 설치한다"},
            {"key": "b", "text": "문자 링크는 누르지 않고, 통화를 끊은 뒤 공식 스토어·대표번호로만 확인한다"},
            {"key": "c", "text": "설치는 하되 권한만 일부 허용한다"},
            {"key": "d", "text": "상대에게 인증번호를 불러준다"},
        ],
        "correct": ["b"],
        "explanation": "문자 속 링크로 앱을 설치하면 기기가 통제될 수 있어요. 링크는 누르지 말고 공식 경로만 쓰세요.",
    },
    # ============ 3) 로맨스 스캠 (romance_scam) ============
    {
        "id": "q_romance_scam_01",
        "category": "romance_scam",
        "risk_family": "romance_scam_boundary",
        "difficulty": "medium",
        "prompt": "온라인에서 빠르게 가까워진 상대가 만난 적도 없는데 급한 사정을 대며 송금을 부탁한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "마음이 통했으니 요청한 돈을 보낸다"},
            {"key": "b", "text": "만난 적 없는 상대의 금전 요구는 정중히 거절하고 송금하지 않는다"},
            {"key": "c", "text": "우선 소액만 보내 본다"},
            {"key": "d", "text": "상품권을 대신 사서 보낸다"},
        ],
        "correct": ["b"],
        "explanation": "실제로 만난 적 없는 관계에서의 금전 요구는 위험 신호예요. 감정과 돈 판단을 분리하세요.",
    },
    {
        "id": "q_romance_scam_02",
        "category": "romance_scam",
        "risk_family": "romance_scam_boundary",
        "difficulty": "hard",
        "prompt": "친밀해진 상대가 '둘만 아는 투자'나 '해외 택배 세관비'를 대신 내달라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "신뢰의 증표로 돈을 보낸다"},
            {"key": "b", "text": "어떤 명목이든 대신 결제·송금을 하지 않고, 감정과 금전 판단을 분리한다"},
            {"key": "c", "text": "세관비만 먼저 내준다"},
            {"key": "d", "text": "상대가 보낸 링크로 결제한다"},
        ],
        "correct": ["b"],
        "explanation": "'둘만의 기회', '대신 결제' 요구는 전형적 미끼예요. 명목이 무엇이든 대신 송금은 하지 않습니다.",
    },
    {
        "id": "q_romance_scam_03",
        "category": "romance_scam",
        "risk_family": "evidence_based_response",
        "difficulty": "medium",
        "prompt": "호감을 표한 상대가 영상통화나 실제 만남은 계속 피하면서 돈 얘기만 꺼낸다. 가장 안전한 해석은?",
        "options": [
            {"key": "a", "text": "부끄러워서 그런 것이니 이해한다"},
            {"key": "b", "text": "신원 확인을 회피하며 금전을 요구하는 것은 위험 신호로 보고 거래·송금을 멈춘다"},
            {"key": "c", "text": "진심이니 요구를 들어준다"},
            {"key": "d", "text": "계좌번호를 먼저 공유한다"},
        ],
        "correct": ["b"],
        "explanation": "신원 확인을 피하면서 돈을 요구하는 패턴은 멈춤 신호예요. 확인 없는 송금은 하지 않습니다.",
    },
    # ============ 4) 부업 사기 (side_job_scam) ============
    {
        "id": "q_side_job_scam_01",
        "category": "side_job_scam",
        "risk_family": "urgency_pressure_resistance",
        "difficulty": "easy",
        "prompt": "'하루 몇 분 투자로 고수익' 부업 광고가 지금 등록하면 자리가 마감된다며 재촉한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "자리가 없어질까 봐 바로 가입비를 낸다"},
            {"key": "b", "text": "고수익·마감 압박은 전형적 미끼로 보고, 서두르지 않고 검증부터 한다"},
            {"key": "c", "text": "우선 소액 가입비만 낸다"},
            {"key": "d", "text": "신분증 사진을 먼저 보낸다"},
        ],
        "correct": ["b"],
        "explanation": "'고수익+마감 임박'은 서두르게 만드는 미끼 조합이에요. 압박에 흔들리지 말고 검증하세요.",
    },
    {
        "id": "q_side_job_scam_02",
        "category": "side_job_scam",
        "risk_family": "prepayment_refusal",
        "difficulty": "medium",
        "prompt": "부업을 시작하려면 '교육비·물품 보증금'을 먼저 입금하라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "일하려면 필요하니 보증금을 보낸다"},
            {"key": "b", "text": "일을 주는 대가로 선입금을 요구하는 것은 위험 신호이므로 거절한다"},
            {"key": "c", "text": "절반만 먼저 보낸다"},
            {"key": "d", "text": "카드번호를 알려준다"},
        ],
        "correct": ["b"],
        "explanation": "일자리를 주면서 돈을 먼저 받는 구조는 위험합니다. 선입금 요구는 금액이 작아도 거절하세요.",
    },
    {
        "id": "q_side_job_scam_03",
        "category": "side_job_scam",
        "risk_family": "off_platform_link_detection",
        "difficulty": "medium",
        "prompt": "부업 담당자가 '전용 앱·외부 링크'에서 미션을 하고 충전하면 돈이 불어난다고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "돈이 불어난다니 충전한다"},
            {"key": "b", "text": "외부 링크·앱에서 돈을 충전하라는 요구는 거절하고 참여하지 않는다"},
            {"key": "c", "text": "소액만 충전해 본다"},
            {"key": "d", "text": "계좌 비밀번호를 입력한다"},
        ],
        "correct": ["b"],
        "explanation": "외부 앱에서 '충전하면 불어난다'는 화면은 조작될 수 있어요. 충전 유도는 거절이 안전합니다.",
    },
    # ============ 5) 취업 사기 (job_scam) ============
    {
        "id": "q_job_scam_01",
        "category": "job_scam",
        "risk_family": "off_platform_link_detection",
        "difficulty": "medium",
        "prompt": "채용 담당자가 면접도 없이 합격을 통보하며 메신저 외부 링크로 '온보딩 절차'를 진행하라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "합격했으니 링크대로 진행한다"},
            {"key": "b", "text": "공식 채용 채널·회사 대표번호로 실재 여부를 확인하고, 외부 링크 절차는 보류한다"},
            {"key": "c", "text": "우선 신분증과 계좌 사본을 보낸다"},
            {"key": "d", "text": "요구하는 앱을 설치한다"},
        ],
        "correct": ["b"],
        "explanation": "면접 없는 합격+외부 링크 온보딩은 위험 신호예요. 회사 실재 여부부터 공식 경로로 확인하세요.",
    },
    {
        "id": "q_job_scam_02",
        "category": "job_scam",
        "risk_family": "prepayment_refusal",
        "difficulty": "medium",
        "prompt": "입사 조건으로 '장비 구매비·보증금'을 개인 계좌로 먼저 보내라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "입사를 위해 보증금을 보낸다"},
            {"key": "b", "text": "채용을 빌미로 한 선입금 요구는 거절하고 계약·회사 실재부터 확인한다"},
            {"key": "c", "text": "장비비만 먼저 보낸다"},
            {"key": "d", "text": "카드 정보를 넘긴다"},
        ],
        "correct": ["b"],
        "explanation": "정상 채용은 입사자에게 돈을 먼저 받지 않아요. 선입금 요구는 거절이 원칙입니다.",
    },
    {
        "id": "q_job_scam_03",
        "category": "job_scam",
        "risk_family": "third_party_account_suspicion",
        "difficulty": "hard",
        "prompt": "합격 후 '급여 계좌 등록'을 이유로 내 계좌에 들어온 돈을 다른 계좌로 다시 이체해 달라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "회사 지시이니 그대로 이체한다"},
            {"key": "b", "text": "내 계좌를 거쳐 남의 계좌로 돈을 보내는 요구는 대포통장·자금세탁 위험으로 보고 거절·신고한다"},
            {"key": "c", "text": "수수료만 떼고 보낸다"},
            {"key": "d", "text": "절반만 이체한다"},
        ],
        "correct": ["b"],
        "explanation": "내 계좌를 '중간 통로'로 쓰게 하는 것은 대포통장 연루 위험이 큽니다. 응하지 말고 신고하세요.",
    },
    # ============ 6) 투자 사기 (investment_scam) ============
    {
        "id": "q_investment_scam_01",
        "category": "investment_scam",
        "risk_family": "price_anomaly_detection",
        "difficulty": "easy",
        "prompt": "'원금 보장 + 매달 고정 고수익' 투자를 지금만 받는다고 한다. 가장 안전한 판단은?",
        "options": [
            {"key": "a", "text": "원금 보장이니 목돈을 넣는다"},
            {"key": "b", "text": "원금 보장과 고정 고수익을 동시에 약속하는 것은 비현실적 신호로 보고 참여하지 않는다"},
            {"key": "c", "text": "소액만 우선 넣는다"},
            {"key": "d", "text": "대출을 받아 넣는다"},
        ],
        "correct": ["b"],
        "explanation": "'원금 보장'과 '고정 고수익'을 함께 약속하는 상품은 현실적으로 없습니다. 대표적 미끼예요.",
    },
    {
        "id": "q_investment_scam_02",
        "category": "investment_scam",
        "risk_family": "urgency_pressure_resistance",
        "difficulty": "medium",
        "prompt": "리딩방에서 '지금 안 사면 못 산다'며 매수를 재촉하고 출금 요청은 계속 미룬다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "기회를 놓칠까 봐 더 입금한다"},
            {"key": "b", "text": "매수 재촉과 출금 지연이 겹치면 위험 신호로 보고 추가 입금을 멈춘다"},
            {"key": "c", "text": "본전을 찾으려 더 넣는다"},
            {"key": "d", "text": "지인에게도 권한다"},
        ],
        "correct": ["b"],
        "explanation": "입금은 재촉하고 출금은 미루는 것은 위험한 조합이에요. 더 넣지 말고 출금 가능 여부를 확인하세요.",
    },
    {
        "id": "q_investment_scam_03",
        "category": "investment_scam",
        "risk_family": "off_platform_link_detection",
        "difficulty": "hard",
        "prompt": "투자 담당자가 '공식 앱처럼 보이는' 외부 링크에서 잔고가 늘어나는 걸 보여주며 계속 입금을 유도한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "잔고가 늘었으니 더 입금한다"},
            {"key": "b", "text": "화면상 잔고는 조작될 수 있으므로, 검증 안 된 외부 플랫폼 입금을 멈추고 출금 가능 여부부터 확인한다"},
            {"key": "c", "text": "표시된 수익만큼 재투자한다"},
            {"key": "d", "text": "링크를 지인에게 공유한다"},
        ],
        "correct": ["b"],
        "explanation": "가짜 앱은 잔고 숫자를 마음대로 보여줄 수 있어요. '보이는 수익'이 아니라 '실제 출금'으로 검증하세요.",
    },
    # ============ 7) 계정 탈취 (account_takeover) ============
    {
        "id": "q_account_takeover_01",
        "category": "account_takeover",
        "risk_family": "off_platform_link_detection",
        "difficulty": "medium",
        "prompt": "'로그인 이상 감지, 지금 확인하세요'라는 문자의 링크로 아이디·비밀번호를 입력하라고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "계정을 지키려고 링크에서 로그인한다"},
            {"key": "b", "text": "문자 링크로 로그인하지 않고, 공식 앱·사이트에 직접 접속해 확인한다"},
            {"key": "c", "text": "비밀번호만 입력해 본다"},
            {"key": "d", "text": "인증번호를 회신한다"},
        ],
        "correct": ["b"],
        "explanation": "문자 링크의 로그인 화면은 가짜일 수 있어요. 항상 앱·공식 주소로 직접 접속해 확인하세요.",
    },
    {
        "id": "q_account_takeover_02",
        "category": "account_takeover",
        "risk_family": "voice_phishing_like_pressure",
        "difficulty": "medium",
        "prompt": "지인 계정에서 '인증번호가 잘못 갔으니 대신 받아서 알려달라'는 메시지가 온다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "지인이니 인증번호를 알려준다"},
            {"key": "b", "text": "인증번호는 누구에게도 알려주지 않고, 지인에게 다른 경로로 사실을 확인한다"},
            {"key": "c", "text": "번호 앞자리만 알려준다"},
            {"key": "d", "text": "링크를 눌러 대신 인증한다"},
        ],
        "correct": ["b"],
        "explanation": "인증번호를 대신 받아 알려주면 계정이 넘어갈 수 있어요. 지인 사칭일 수 있으니 다른 경로로 확인하세요.",
    },
    {
        "id": "q_account_takeover_03",
        "category": "account_takeover",
        "risk_family": "urgency_pressure_resistance",
        "difficulty": "hard",
        "prompt": "'해킹 흔적이 있어 지금 잔액을 안전계좌로 옮겨야 한다'며 급하게 안내한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "시키는 '안전계좌'로 즉시 이체한다"},
            {"key": "b", "text": "'안전계좌'로의 이체 요구는 존재하지 않는 절차이므로 거절하고 공식 채널로 확인한다"},
            {"key": "c", "text": "일부만 옮긴다"},
            {"key": "d", "text": "OTP 번호를 불러준다"},
        ],
        "correct": ["b"],
        "explanation": "'안전계좌'라는 절차는 없어요. 돈을 옮기라는 급한 안내는 사기로 의심하고 공식 번호로 확인하세요.",
    },
    # ============ 8) 개인 연락 경계 (private_contact_boundary) ============
    {
        "id": "q_private_contact_boundary_01",
        "category": "private_contact_boundary",
        "risk_family": "personal_contact_boundary",
        "difficulty": "easy",
        "prompt": "거래 상대가 '앱은 불편하니 개인 전화번호·메신저로 옮기자'고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "편하게 개인 연락처를 알려준다"},
            {"key": "b", "text": "대화는 플랫폼 안에서 이어가자고 정중히 거절한다"},
            {"key": "c", "text": "전화번호만 알려준다"},
            {"key": "d", "text": "상대 번호만 저장한다"},
        ],
        "correct": ["b"],
        "explanation": "외부 연락으로 옮기면 기록이 사라지고 보호가 약해져요. 대화는 플랫폼 안에서 유지하세요.",
    },
    {
        "id": "q_private_contact_boundary_02",
        "category": "private_contact_boundary",
        "risk_family": "platform_chat_preservation",
        "difficulty": "medium",
        "prompt": "상대가 '기록이 남으면 불편하니 사라지는 메시지로 얘기하자'고 한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "사생활 보호이니 옮긴다"},
            {"key": "b", "text": "거래 증거 보존을 위해 플랫폼 대화를 그대로 유지하겠다고 한다"},
            {"key": "c", "text": "중요한 얘기만 옮긴다"},
            {"key": "d", "text": "통화로만 합의한다"},
        ],
        "correct": ["b"],
        "explanation": "'기록이 남으면 불편하다'는 요구는 증거를 지우려는 신호일 수 있어요. 대화 기록을 유지하세요.",
    },
    {
        "id": "q_private_contact_boundary_03",
        "category": "private_contact_boundary",
        "risk_family": "personal_contact_boundary",
        "difficulty": "medium",
        "prompt": "상대가 계속 사적 만남·연락처를 요구하며 거절하면 서운함을 표한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "미안해서 연락처를 준다"},
            {"key": "b", "text": "정중하지만 단호하게 거래 범위 밖 요구를 거절하고 경계를 지킨다"},
            {"key": "c", "text": "한 번만 만나 준다"},
            {"key": "d", "text": "SNS 계정을 알려준다"},
        ],
        "correct": ["b"],
        "explanation": "서운함을 이용해 경계를 무너뜨리는 것도 압박이에요. 정중하되 단호하게 선을 지키세요.",
    },
    # ============ 9) 판매자 환불 분쟁 (seller_refund_conflict) ============
    {
        "id": "q_seller_refund_conflict_01",
        "category": "seller_refund_conflict",
        "risk_family": "refund_villain_response",
        "difficulty": "medium",
        "prompt": "판매자인 당신이 정상 발송한 상품에 대해 구매자가 근거 없이 '망가졌다'며 전액 환불을 요구하고 협박한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "무서워서 즉시 전액 환불한다"},
            {"key": "b", "text": "감정에 휘둘리지 않고 발송 상태·고지 내용·기록을 근거로 차분히 대응한다"},
            {"key": "c", "text": "욕설로 맞대응한다"},
            {"key": "d", "text": "연락을 끊고 잠적한다"},
        ],
        "correct": ["b"],
        "explanation": "협박에 즉흥적으로 환불하거나 맞받아치지 말고, 발송·고지 기록을 근거로 침착하게 대응하세요.",
    },
    {
        "id": "q_seller_refund_conflict_02",
        "category": "seller_refund_conflict",
        "risk_family": "legitimate_claim_recognition",
        "difficulty": "medium",
        "prompt": "구매자가 사진과 함께 실제 하자를 구체적으로 제시하며 환불을 요청한다. 판매자로서 가장 바람직한 대응은?",
        "options": [
            {"key": "a", "text": "무조건 거절한다"},
            {"key": "b", "text": "정당한 하자 주장인지 사실을 확인하고, 맞다면 합리적으로 환불·교환을 처리한다"},
            {"key": "c", "text": "연락을 무시한다"},
            {"key": "d", "text": "별점 협박이라고 단정한다"},
        ],
        "correct": ["b"],
        "explanation": "모든 환불 요구가 부당한 건 아니에요. 정당한 하자 주장은 사실을 확인해 합리적으로 처리하는 게 맞습니다.",
    },
    {
        "id": "q_seller_refund_conflict_03",
        "category": "seller_refund_conflict",
        "risk_family": "seller_misconduct_avoidance",
        "difficulty": "medium",
        "prompt": "구매자와 분쟁 중 화가 난 판매자가 취할 수 있는 대응 중 가장 바람직한 것은?",
        "options": [
            {"key": "a", "text": "욕설·협박으로 대응한다"},
            {"key": "b", "text": "개인정보를 유출하겠다고 위협한다"},
            {"key": "c", "text": "침착하게 사실·기록을 근거로 대화하고, 필요하면 플랫폼 중재를 요청한다"},
            {"key": "d", "text": "구매자 신상을 공개한다"},
        ],
        "correct": ["c"],
        "explanation": "불리한 상황에서도 욕설·신상 공개 같은 대응은 오히려 나를 위험에 빠뜨려요. 기록과 중재로 풀어야 합니다.",
    },
    {
        "id": "q_seller_refund_conflict_04",
        "category": "seller_refund_conflict",
        "risk_family": "calm_dispute_handling",
        "difficulty": "hard",
        "prompt": "구매자가 반복적으로 막말과 별점 테러를 예고하며 부당한 추가 보상을 요구한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "요구를 모두 들어준다"},
            {"key": "b", "text": "감정적 대응 대신 기준선을 지키고, 대화를 기록으로 남기며 플랫폼 신고·중재를 활용한다"},
            {"key": "c", "text": "똑같이 막말로 맞선다"},
            {"key": "d", "text": "상대 연락처를 캡처해 공개하겠다고 한다"},
        ],
        "correct": ["b"],
        "explanation": "협박성 요구에는 기준선을 지키는 게 답이에요. 감정 대응 대신 기록을 남기고 공식 절차를 쓰세요.",
    },
    # ============ 10) 택배거래 안전 (delivery_trade_safety) ============
    {
        "id": "q_delivery_trade_safety_01",
        "category": "delivery_trade_safety",
        "risk_family": "safe_delivery_trade",
        "difficulty": "easy",
        "prompt": "택배거래를 하기로 했다. 안전을 위해 먼저 챙길 것으로 가장 알맞은 것은?",
        "options": [
            {"key": "a", "text": "그냥 개인 계좌로 전액 선입금한다"},
            {"key": "b", "text": "안전결제 이용, 실물·구성품 인증, 송장 확인 등 안전 절차를 먼저 챙긴다"},
            {"key": "c", "text": "판매자 말만 믿고 진행한다"},
            {"key": "d", "text": "개인 계좌로 보내고 배송을 기다린다"},
        ],
        "correct": ["b"],
        "explanation": "택배거래는 얼굴을 못 보는 만큼 절차가 중요해요. 안전결제·실물 인증·송장 확인을 먼저 챙기세요.",
    },
    {
        "id": "q_delivery_trade_safety_02",
        "category": "delivery_trade_safety",
        "risk_family": "third_party_account_suspicion",
        "difficulty": "medium",
        "prompt": "대화 상대는 A인데, 입금하라는 계좌 명의는 전혀 다른 사람(B) 이름이다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "가족 계좌겠거니 하고 보낸다"},
            {"key": "b", "text": "대화 상대와 계좌 명의가 다르면 멈추고, 불일치 이유를 확인하기 전엔 입금하지 않는다"},
            {"key": "c", "text": "소액만 먼저 보낸다"},
            {"key": "d", "text": "명의는 신경 쓰지 않는다"},
        ],
        "correct": ["b"],
        "explanation": "판매자와 계좌 명의가 다르면 제3자 계좌(대포통장) 위험이 있어요. 명의가 일치하는지 먼저 확인하세요.",
    },
    {
        "id": "q_delivery_trade_safety_03",
        "category": "delivery_trade_safety",
        "risk_family": "evidence_based_response",
        "difficulty": "medium",
        "prompt": "판매자가 '선입금하면 바로 발송, 송장은 나중에'라며 재촉한다. 가장 안전한 대응은?",
        "options": [
            {"key": "a", "text": "믿고 전액 선입금한다"},
            {"key": "b", "text": "안전결제를 유지하거나, 최소한 실물 인증·송장 확인 전에는 전액 선입금하지 않는다"},
            {"key": "c", "text": "절반만 선입금한다"},
            {"key": "d", "text": "계좌 비밀번호를 확인해 준다"},
        ],
        "correct": ["b"],
        "explanation": "'선입금하면 발송'은 순서를 뒤집는 요구예요. 안전결제나 최소한의 실물·송장 확인으로 근거를 확보하세요.",
    },
]


# ------------------------------------------------------------
#  내부 헬퍼
# ------------------------------------------------------------
def _as_dict(row_or_dict) -> dict:
    """sqlite3.Row 또는 dict 를 평범한 dict 로 변환."""
    if row_or_dict is None:
        return {}
    if isinstance(row_or_dict, dict):
        return dict(row_or_dict)
    try:
        return {k: row_or_dict[k] for k in row_or_dict.keys()}
    except Exception:
        return dict(row_or_dict)


# ------------------------------------------------------------
#  시드 (migrations 가 부팅 때 호출 — 멱등 UPSERT)
# ------------------------------------------------------------
def seed_assessment_questions(conn: sqlite3.Connection) -> None:
    """진단 문항 뱅크를 안정적 id 기준으로 UPSERT 한다(멱등).

    - INSERT OR REPLACE 로 프롬프트/보기/정답/해설이 바뀌어도 최신 정의로 갱신된다.
    - active 는 항상 1 로 유지한다. commit 은 호출자(migrations)가 한다.
    """
    now = _now()
    for q in _QUESTIONS:
        options_json = json.dumps(q["options"], ensure_ascii=False)
        correct_json = json.dumps({"correct_keys": q["correct"]}, ensure_ascii=False)
        conn.execute(
            """
            INSERT OR REPLACE INTO assessment_question_bank
                (id, category, risk_family, question_type, prompt,
                 options_json, correct_answer_json, explanation, difficulty,
                 active, created_at)
            VALUES (?, ?, ?, 'single_choice', ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                q["id"],
                q["category"],
                q["risk_family"],
                q["prompt"],
                options_json,
                correct_json,
                q.get("explanation", ""),
                q.get("difficulty", "medium"),
                now,
            ),
        )


# ------------------------------------------------------------
#  조회 / 선택 / 공개 직렬화
# ------------------------------------------------------------
def get_question(conn: sqlite3.Connection, question_id: str) -> dict | None:
    """문항 한 개를 dict 로 반환(없으면 None). 정답 포함(서버 전용)."""
    row = conn.execute(
        "SELECT * FROM assessment_question_bank WHERE id = ?", (question_id,)
    ).fetchone()
    if not row:
        return None
    return _as_dict(row)


def select_question_ids(conn: sqlite3.Connection, assessment_type: str) -> list[str]:
    """세션에 낼 문항 id 를 순서대로 고른다.

    - baseline / post_training : 카테고리마다 1개씩(있는 것만) → 최대 10개.
    - quick_check              : 앞쪽 5개 카테고리에서 1개씩 → 최대 5개.
    결정적(ORDER BY)이며 난수를 쓰지 않는다.
    """
    categories = list(rs.ASSESSMENT_CATEGORIES)
    if (assessment_type or "").strip() == "quick_check":
        categories = categories[:5]

    ids: list[str] = []
    for cat in categories:
        row = conn.execute(
            """
            SELECT id FROM assessment_question_bank
            WHERE category = ? AND active = 1
            ORDER BY difficulty, id
            LIMIT 1
            """,
            (cat,),
        ).fetchone()
        if row:
            ids.append(row["id"])
    return ids


def public_question(row_or_dict) -> dict:
    """클라이언트 안전 형태(정답 없음)로 직렬화.

    {"id","category","risk_family","question_type","prompt",
     "options":[{key,text}], "difficulty"}
    """
    d = _as_dict(row_or_dict)

    options = d.get("options")
    if not isinstance(options, list):
        try:
            options = json.loads(d.get("options_json") or "[]")
        except Exception:
            options = []

    safe_options = []
    for o in options:
        if isinstance(o, dict):
            safe_options.append({"key": o.get("key"), "text": o.get("text")})

    return {
        "id": d.get("id"),
        "category": d.get("category"),
        "risk_family": d.get("risk_family"),
        "question_type": d.get("question_type") or "single_choice",
        "prompt": d.get("prompt"),
        "options": safe_options,
        "difficulty": d.get("difficulty") or "medium",
    }
