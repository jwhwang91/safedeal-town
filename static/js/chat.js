/* ============================================================
   chat.js — NPC 와의 거래(대화) 한 판
   start → message... → flag → resolve 흐름을 화면에 연결한다.
   구매자 모드와 판매자 모드 둘 다 지원 (결정 버튼/결과가 모드별로 다름).
   결과 모달과 전적실 모달 렌더링도 여기서 담당.
   ============================================================ */
(function (global) {
  "use strict";

  /* ---------- DOM ---------- */
  const chatOverlay = document.getElementById("chat-overlay");
  const resultOverlay = document.getElementById("result-overlay");
  const recordOverlay = document.getElementById("record-overlay");

  const elAvatar = document.getElementById("chat-avatar");
  const elNpcName = document.getElementById("chat-npc-name");
  const elNpcDesc = document.getElementById("chat-npc-desc");
  const elItem = document.getElementById("listing-item");
  const elPrice = document.getElementById("listing-price");
  const elMarket = document.getElementById("listing-market");
  const elLocation = document.getElementById("listing-location");
  const elBody = document.getElementById("chat-body");
  const elInput = document.getElementById("chat-input");
  const elSend = document.getElementById("chat-send");
  const elTurn = document.getElementById("chat-turn-text");
  const elClose = document.getElementById("chat-close");
  const elDecisionLabel = document.querySelector(".decision-label");
  const buyerDecisions = document.getElementById("buyer-decisions");
  const sellerDecisions = document.getElementById("seller-decisions");
  const allDecisionBtns = document.querySelectorAll(".btn-decision");

  /* ---------- 상태 ---------- */
  let session = null; // { sessionId, npc, mode, maxTurns, playerTurns, busy, resolved }

  /* ---------- 헬퍼 ---------- */
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function won(n) { return "₩" + Number(n).toLocaleString("ko-KR"); }
  function scrollBottom() { elBody.scrollTop = elBody.scrollHeight; }
  function setInputEnabled(on) {
    elInput.disabled = !on;
    elSend.disabled = !on;
    allDecisionBtns.forEach((b) => (b.disabled = !on));
    if (on) elInput.focus();
  }

  /* ---------- 메시지 렌더 ---------- */
  function addNpcMessage(messageId, content) {
    const wrap = document.createElement("div");
    wrap.className = "msg msg-npc";
    wrap.dataset.messageId = messageId;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = content;
    wrap.appendChild(bubble);
    const tools = document.createElement("div");
    tools.className = "msg-tools";
    const flagBtn = document.createElement("button");
    flagBtn.className = "flag-btn";
    flagBtn.type = "button";
    flagBtn.textContent = "🚩 의심";
    flagBtn.addEventListener("click", () => toggleFlag(messageId, bubble, flagBtn));
    tools.appendChild(flagBtn);
    wrap.appendChild(tools);
    elBody.appendChild(wrap);
    scrollBottom();
  }
  function addPlayerMessage(content) {
    const wrap = document.createElement("div");
    wrap.className = "msg msg-player";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = content;
    wrap.appendChild(bubble);
    elBody.appendChild(wrap);
    scrollBottom();
  }

  let typingEl = null;
  function showTyping() {
    typingEl = document.createElement("div");
    typingEl.className = "msg msg-npc msg-typing";
    const b = document.createElement("div");
    b.className = "bubble";
    b.textContent = "입력 중...";
    typingEl.appendChild(b);
    elBody.appendChild(typingEl);
    scrollBottom();
  }
  function hideTyping() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
  }

  /* ---------- 의심 표시 ---------- */
  async function toggleFlag(messageId, bubble, btn) {
    if (!session || session.resolved) return;
    const next = !btn.classList.contains("on");
    btn.classList.toggle("on", next);
    bubble.classList.toggle("flagged", next);
    try {
      await API.chat.flag(session.sessionId, messageId, next);
    } catch (err) {
      btn.classList.toggle("on", !next);
      bubble.classList.toggle("flagged", !next);
      SafeDeal.toast(err.message);
    }
  }

  function updateTurn() {
    elTurn.textContent = "대화 " + session.playerTurns + " / " + session.maxTurns;
  }

  /* ---------- 대화 시작 ---------- */
  async function openChat(spawn) {
    // spawn: { spawn_instance_id, name, ... } (npc_id/role 은 클라이언트에 없음)
    SafeDealGame.setPaused(true);
    try {
      const data = await API.chat.start(spawn.spawn_instance_id);
      session = {
        sessionId: data.session_id,
        npc: data.npc,
        mode: data.mode || "buyer",
        maxTurns: data.max_turns,
        playerTurns: 0,
        busy: false,
        resolved: false,
      };

      // 헤더
      elAvatar.style.background = data.npc.sprite_color || "#d9744f";
      const roleWord = session.mode === "seller" ? "구매자" : "판매자";
      elNpcName.textContent = data.npc.name;
      elNpcDesc.textContent =
        (data.npc.appearance ? data.npc.appearance + " · " : "") +
        roleWord + " · 난이도 " + diffLabel(data.npc.difficulty);

      // 매물 카드 (모드별 표시)
      elItem.textContent = data.npc.item_name;
      if (session.mode === "seller") {
        elPrice.textContent = "";
        elMarket.textContent = "내가 올린 중고 매물";
      } else {
        elPrice.textContent = won(data.npc.listing_price);
        elMarket.textContent = "시세 약 " + won(data.npc.market_price);
      }
      elLocation.textContent = "📍 " + data.npc.location;

      // 결정 버튼 그룹 전환
      const seller = session.mode === "seller";
      buyerDecisions.style.display = seller ? "none" : "";
      sellerDecisions.style.display = seller ? "" : "none";
      elDecisionLabel.textContent = seller
        ? "어떻게 대응할지 정했다면 선택하세요"
        : "거래를 마칠 준비가 됐다면 선택하세요";

      elBody.innerHTML = "";
      addNpcMessage(data.opening.message_id, data.opening.content);
      updateTurn();

      elInput.value = "";
      elInput.placeholder = seller ? "구매자에게 메시지 보내기..." : "판매자에게 메시지 보내기...";
      chatOverlay.classList.remove("hidden");
      setInputEnabled(true);
    } catch (err) {
      SafeDeal.toast(err.message);
      SafeDealGame.setPaused(false);
    }
  }
  function diffLabel(d) {
    return { easy: "쉬움", medium: "보통", hard: "어려움" }[d] || d || "보통";
  }

  /* ---------- 메시지 전송 ---------- */
  async function sendMessage() {
    if (!session || session.busy || session.resolved) return;
    const text = elInput.value.trim();
    if (!text) return;
    if (session.playerTurns >= session.maxTurns) {
      SafeDeal.toast("대화가 다 찼어요. 이제 거래를 마무리하세요.");
      return;
    }
    session.busy = true;
    setInputEnabled(false);
    addPlayerMessage(text);
    elInput.value = "";
    showTyping();
    try {
      const data = await API.chat.message(session.sessionId, text);
      hideTyping();
      addNpcMessage(data.reply.message_id, data.reply.content);
      session.playerTurns = data.player_turns_used;
      updateTurn();
      if (session.playerTurns >= session.maxTurns) {
        SafeDeal.toast("대화 횟수를 다 썼어요. 아래 버튼으로 거래를 마치세요.");
      }
    } catch (err) {
      hideTyping();
      SafeDeal.toast(err.message);
    } finally {
      session.busy = false;
      setInputEnabled(!session.resolved);
    }
  }

  /* ---------- 거래 종료 + 채점 ---------- */
  async function resolveTrade(decision) {
    if (!session || session.busy || session.resolved) return;
    session.busy = true;
    setInputEnabled(false);
    showTyping();
    try {
      const result = await API.chat.resolve(session.sessionId, decision);
      hideTyping();
      session.resolved = true;
      chatOverlay.classList.add("hidden");
      renderResult(result);
      SafeDealGame.refreshWorld();
    } catch (err) {
      hideTyping();
      SafeDeal.toast(err.message);
      session.busy = false;
      setInputEnabled(true);
    }
  }

  /* ---------- 결과 메타 ---------- */
  const VERDICT_META = {
    // 구매자 모드
    good_catch: { cls: "", emoji: "🎯", title: "사기꾼을 잡았다!" },
    safe: { cls: "", emoji: "🤝", title: "안전한 거래 성공!" },
    missed_deal: { cls: "ok", emoji: "😯", title: "정상 거래를 놓쳤어요" },
    scammed: { cls: "bad", emoji: "💸", title: "사기를 당했어요..." },
    // 판매자 모드
    fair_sale: { cls: "", emoji: "🤝", title: "깔끔한 거래!" },
    handled_refund_villain: { cls: "", emoji: "🛡️", title: "환불 빌런 격퇴!" },
    handled_lowballer: { cls: "", emoji: "💪", title: "가격선 사수!" },
    handled_risky: { cls: "", emoji: "🧯", title: "위험 거래 차단!" },
    ok_walkaway: { cls: "", emoji: "🚶", title: "담담하게 잘 정리" },
    over_refunded: { cls: "ok", emoji: "😵", title: "과하게 환불했어요" },
    unsafe_response: { cls: "bad", emoji: "⚠️", title: "위험한 대응이었어요" },
    lost_sale: { cls: "ok", emoji: "😢", title: "정상 거래를 놓쳤어요" },
    missed_legitimate_claim: { cls: "bad", emoji: "🙁", title: "정당한 요구를 놓쳤어요" },
  };
  const DECISION_LABEL = {
    buy: "구매", walk_away: "거래 중단", report: "신고",
    complete_sale: "판매 완료", refuse_refund: "환불 거절", accept_refund: "환불 수락",
    partial_refund: "부분 환불", escalate_platform: "플랫폼 분쟁", cancel_trade: "거래 취소",
  };

  function renderResult(r) {
    const meta = VERDICT_META[r.verdict] || VERDICT_META.safe;
    const seller = r.mode === "seller";

    const banner = document.getElementById("result-banner");
    banner.className = "result-banner" + (meta.cls ? " " + meta.cls : "");
    document.getElementById("result-emoji").textContent = meta.emoji;
    document.getElementById("result-title").textContent = meta.title;

    let roleText;
    if (seller) {
      roleText = "이 구매자는 '" + (r.counterparty_label || "구매자") + "' 였습니다.";
    } else {
      roleText = r.npc_role === "scammer"
        ? "이 판매자는 사기꾼이었습니다."
        : "이 판매자는 정상 판매자였습니다.";
    }
    const decText = "당신의 선택: " + (DECISION_LABEL[r.decision] || r.decision);
    document.getElementById("result-subtitle").textContent = roleText + "  ·  " + decText;
    document.getElementById("result-score").textContent = r.score;

    // 보상 칩
    const rw = r.rewards || {};
    const chips = document.getElementById("result-rewards");
    chips.innerHTML = "";
    chips.appendChild(makeChip("XP " + signed(rw.xp_delta), rw.xp_delta >= 0 ? "up" : "down"));
    chips.appendChild(makeChip("신뢰도 " + signed(rw.trust_delta), rw.trust_delta >= 0 ? "up" : "down"));
    if (rw.coin_delta != null && rw.coin_delta !== 0) {
      chips.appendChild(makeChip("💰 " + signed(rw.coin_delta), rw.coin_delta >= 0 ? "up" : "down"));
    }
    if (rw.item_gained) chips.appendChild(makeChip("📦 " + rw.item_gained + " 획득!", "up"));
    if (rw.item_lost) chips.appendChild(makeChip("💔 " + rw.item_lost + " 빼앗김", "down"));
    if (rw.leveled_up) chips.appendChild(makeChip("🎉 레벨 업! Lv." + rw.new_level, "up"));

    document.getElementById("result-coaching").textContent = r.coaching || "";

    // 플래그 복기
    const flagsHeading = document.querySelector("#flags-section h4");
    if (flagsHeading) flagsHeading.textContent = seller ? "🔍 대응 복기" : "🔍 위험 신호 복기";
    const flagsBox = document.getElementById("result-flags");
    flagsBox.innerHTML = "";
    const detected = r.detected_flags || [];
    const missed = r.missed_flags || [];
    if (detected.length === 0 && missed.length === 0) {
      const e = document.createElement("p");
      e.className = "flag-empty";
      e.textContent = seller
        ? "특별히 짚을 위험 행동이 없었어요."
        : (r.npc_role === "honest"
          ? "이 거래엔 위험 신호가 없었어요. 정상 판매자였거든요."
          : "복기할 위험 신호가 없네요.");
      flagsBox.appendChild(e);
    } else {
      detected.forEach((f) => flagsBox.appendChild(makeFlagLine("caught", "✔", f)));
      missed.forEach((f) => flagsBox.appendChild(makeFlagLine("missed", "✘", f)));
    }

    // 대화 다시 보기
    const tr = document.getElementById("result-transcript");
    tr.innerHTML = "";
    const speakerWord = seller ? "구매자" : "판매자";
    (r.annotated_transcript || []).forEach((m) => {
      const row = document.createElement("div");
      row.className =
        "tr-msg " + (m.speaker === "npc" ? "tr-npc" : "tr-player") +
        (m.flagged_by_player ? " was-flagged" : "");
      const who = document.createElement("span");
      who.className = "tr-speaker";
      who.textContent = (m.speaker === "npc" ? speakerWord : "나") + ": ";
      row.appendChild(who);
      row.appendChild(document.createTextNode(m.content));
      if (m.tactic) {
        const tag = document.createElement("span");
        tag.className = "tr-tactic";
        tag.textContent = "🎭 " + m.tactic.label + " — " + m.tactic.red_flag;
        tag.title = "대응법: " + (m.tactic.counter || "");
        row.appendChild(document.createElement("br"));
        row.appendChild(tag);
      }
      tr.appendChild(row);
    });

    // 면책 고지 (판매자 모드)
    const disc = document.getElementById("result-disclaimer");
    if (disc) {
      if (seller && r.disclaimer) {
        disc.textContent = "⚖️ " + r.disclaimer;
        disc.classList.remove("hidden");
      } else {
        disc.classList.add("hidden");
      }
    }

    resultOverlay.classList.remove("hidden");
  }

  function makeChip(text, kind) {
    const c = document.createElement("span");
    c.className = "reward-chip" + (kind ? " " + kind : "");
    c.textContent = text;
    return c;
  }
  function makeFlagLine(kind, icon, text) {
    const line = document.createElement("div");
    line.className = "flag-line " + kind;
    const ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = icon;
    const tx = document.createElement("span");
    tx.textContent = text;
    line.appendChild(ic);
    line.appendChild(tx);
    return line;
  }
  function signed(n) { n = n || 0; return n > 0 ? "+" + n : String(n); }

  /* ---------- 전적실 ---------- */
  async function openRecord() {
    try {
      const [profile, lb] = await Promise.all([API.game.profile(), API.game.leaderboard()]);
      renderRecord(profile, lb);
      recordOverlay.classList.remove("hidden");
    } catch (err) {
      SafeDeal.toast(err.message);
    }
  }
  function renderRecord(profile, lb) {
    const s = profile.stats || {};
    const statsBox = document.getElementById("record-stats");
    statsBox.innerHTML = "";
    [
      ["거래 수", s.total_trades || 0],
      ["정답", s.correct || 0],
      ["사기 피해", s.scammed || 0],
      ["정확도", (s.accuracy || 0) + "%"],
    ].forEach(([lbl, num]) => {
      const box = document.createElement("div");
      box.className = "stat-box";
      box.innerHTML = '<div class="num">' + escapeHtml(num) + "</div>" +
        '<div class="lbl">' + escapeHtml(lbl) + "</div>";
      statsBox.appendChild(box);
    });

    const lbBox = document.getElementById("record-leaderboard");
    lbBox.innerHTML = "";
    const rows = (lb && lb.leaderboard) || [];
    if (rows.length === 0) {
      lbBox.innerHTML = '<p class="record-empty">아직 순위가 없어요.</p>';
    } else {
      rows.forEach((u, i) => {
        const row = document.createElement("div");
        row.className = "lb-row";
        row.innerHTML =
          '<span class="lb-rank">' + (i + 1) + "</span>" +
          '<span class="lb-name">' + escapeHtml(u.display_name) + "</span>" +
          '<span class="lb-xp">Lv.' + u.level + " · XP " + u.xp + "</span>";
        lbBox.appendChild(row);
      });
    }

    const histBox = document.getElementById("record-history");
    histBox.innerHTML = "";
    const hist = profile.history || [];
    if (hist.length === 0) {
      histBox.innerHTML = '<p class="record-empty">아직 거래 기록이 없어요. 마을에서 첫 거래를 해보세요!</p>';
    } else {
      hist.forEach((h) => {
        const meta = VERDICT_META[h.verdict] || VERDICT_META.safe;
        const row = document.createElement("div");
        row.className = "hist-row";
        const tag = h.game_role === "seller" ? "🏪" : "🛒";
        row.innerHTML =
          '<span class="hist-verdict">' + meta.emoji + "</span>" +
          '<div class="hist-main">' +
          '<div class="hist-npc">' + tag + " " + escapeHtml(h.npc_name) +
          ' <span class="hist-coach">· ' + escapeHtml(h.item_name) + "</span></div>" +
          '<div class="hist-coach">' + escapeHtml(h.coaching || "") + "</div>" +
          "</div>" +
          '<span class="hist-score">' + h.score + "점</span>";
        histBox.appendChild(row);
      });
    }
  }

  /* ---------- 닫기 ---------- */
  function closeChat() {
    chatOverlay.classList.add("hidden");
    session = null;
    SafeDealGame.setPaused(false);
  }
  function closeResult() {
    resultOverlay.classList.add("hidden");
    session = null;
    SafeDealGame.setPaused(false);
  }
  function closeRecord() { recordOverlay.classList.add("hidden"); }

  /* ---------- 이벤트 ---------- */
  elSend.addEventListener("click", sendMessage);
  elInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); sendMessage(); }
  });
  allDecisionBtns.forEach((btn) =>
    btn.addEventListener("click", () => resolveTrade(btn.dataset.decision))
  );
  elClose.addEventListener("click", closeChat);
  document.getElementById("result-close").addEventListener("click", closeResult);
  document.getElementById("record-close").addEventListener("click", closeRecord);

  global.SafeDealChat = { openChat, openRecord, closeChat };
})(window);
