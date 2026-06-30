/* ============================================================
   checklist.js — 거래 체크리스트 + 장착 도구 기반 답변칩
   - 거래 노트처럼 가볍게: 토글로 펼치는 체크리스트 (튜토리얼 팝업 아님)
   - 장착한 거래 도구(effect_key)에 따라 관련 항목을 강조하고 답변칩을 제공
   - 체크 상태는 세션마다 초기화, resolve 시 함께 전송(소폭 가점) + 결과에 표시
   정답을 대신 알려주지 않는다 — 어디까지나 '확인 습관'을 돕는 도구다.
   ============================================================ */
(function (global) {
  "use strict";

  const panel = document.getElementById("checklist-panel");
  const toggle = document.getElementById("checklist-toggle");
  const suggestEl = document.getElementById("chat-suggest");

  // 모드별 체크리스트 (키는 서버 _BUYER/_SELLER_CHECKLIST_KEYS 와 일치)
  const BUYER_ITEMS = [
    { key: "price_check", label: "시세 확인" },
    { key: "condition_check", label: "하자/구성품 확인" },
    { key: "proof_request", label: "실물 인증 요청" },
    { key: "safe_method", label: "직거래/안전결제 확인" },
    { key: "account_match", label: "계좌/명의 일치 확인" },
    { key: "refuse_link", label: "외부 링크 거절" },
    { key: "keep_in_platform", label: "플랫폼 내 대화 유지" },
  ];
  const SELLER_ITEMS = [
    { key: "disclose_condition", label: "상품 상태 고지" },
    { key: "keep_evidence", label: "하자 사진/영상 보관" },
    { key: "disclose_accessories", label: "구성품 명확히 고지" },
    { key: "clear_terms", label: "거래 조건/환불 원칙 명확화" },
    { key: "keep_in_platform", label: "플랫폼 내 대화 유지" },
    { key: "stay_calm", label: "부당 요구에 감정적 대응 금지" },
    { key: "organize_evidence", label: "분쟁 시 증거 정리" },
  ];

  // 도구 효과 → 강조할 체크리스트 항목 키
  const TOOL_HIGHLIGHT = {
    price_radar: ["price_check"],
    link_warning: ["refuse_link", "keep_in_platform"],
    account_check: ["account_match"],
    proof_request_kit: ["proof_request", "condition_check"],
    evidence_folder: ["keep_evidence", "organize_evidence"],
    refund_response_card: ["clear_terms", "stay_calm"],
    dispute_guide: ["keep_in_platform", "organize_evidence"],
    safe_trade_checklist: [], // 전체 펼치기
  };

  // 도구 효과 → 답변칩 (입력창에 넣어주는 현실적 문구)
  const TOOL_CHIPS = {
    proof_request_kit: [
      "실물 사진 더 볼 수 있을까요?",
      "오늘 날짜 적은 메모와 같이 찍어주실 수 있나요?",
      "구성품 사진도 부탁드려요.",
    ],
    refund_response_card: [
      "거래 당시 상태를 분명히 고지드렸고, 기록도 가지고 있어요. 환불은 어렵습니다.",
      "원하시면 합리적인 선에서 부분 환불은 검토해볼게요.",
      "이 부분은 플랫폼 분쟁/고객센터 절차로 진행하는 게 서로 안전할 것 같아요.",
    ],
    dispute_guide: [
      "플랫폼 분쟁 절차로 정리하고 대화 기록을 근거로 제출할게요.",
    ],
    account_check: [
      "혹시 입금 계좌 명의가 판매자분 성함과 같은지 확인 부탁드려요.",
    ],
  };

  let state = { mode: "buyer", checked: new Set(), effects: [] };
  let onSuggest = null;

  function build() {
    panel.innerHTML = "";
    const items = state.mode === "seller" ? SELLER_ITEMS : BUYER_ITEMS;
    const highlights = new Set();
    state.effects.forEach((e) => (TOOL_HIGHLIGHT[e] || []).forEach((k) => highlights.add(k)));

    items.forEach((it) => {
      const row = document.createElement("label");
      row.className = "checklist-item" + (highlights.has(it.key) ? " hot" : "");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.checked.has(it.key);
      cb.addEventListener("change", () => {
        if (cb.checked) state.checked.add(it.key);
        else state.checked.delete(it.key);
      });
      const span = document.createElement("span");
      span.textContent = it.label;
      row.appendChild(cb);
      row.appendChild(span);
      if (highlights.has(it.key)) {
        const tip = document.createElement("span");
        tip.className = "checklist-hot";
        tip.textContent = "도구";
        row.appendChild(tip);
      }
      panel.appendChild(row);
    });
  }

  function buildSuggestions() {
    suggestEl.innerHTML = "";
    const chips = [];
    state.effects.forEach((e) => (TOOL_CHIPS[e] || []).forEach((t) => chips.push(t)));
    // 판매자 모드 환불 카드엔 면책 고지 한 줄
    let disclaimerShown = false;
    chips.forEach((text) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "suggest-chip";
      b.textContent = text.length > 22 ? text.slice(0, 22) + "…" : text;
      b.title = text;
      b.addEventListener("click", () => { if (onSuggest) onSuggest(text); });
      suggestEl.appendChild(b);
    });
    if (state.effects.includes("refund_response_card") || state.effects.includes("dispute_guide")) {
      const note = document.createElement("span");
      note.className = "suggest-note";
      note.textContent = "※ 일반 훈련 정보이며 법률 자문이 아니에요.";
      suggestEl.appendChild(note);
      disclaimerShown = true;
    }
    suggestEl.style.display = chips.length || disclaimerShown ? "" : "none";
  }

  /* 세션 시작 시 호출 */
  function begin(mode, effects, suggestCb) {
    state = { mode: mode || "buyer", checked: new Set(), effects: effects || [] };
    onSuggest = suggestCb || null;
    build();
    buildSuggestions();
    // safe_trade_checklist 도구가 있으면 체크리스트를 펼친 상태로 시작
    const open = (effects || []).includes("safe_trade_checklist");
    panel.classList.toggle("hidden", !open);
    toggle.classList.toggle("open", open);
  }

  function getChecked() { return Array.from(state.checked); }

  toggle.addEventListener("click", () => {
    const willOpen = panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !willOpen);
    toggle.classList.toggle("open", willOpen);
  });

  global.SafeDealChecklist = { begin, getChecked };
})(window);
