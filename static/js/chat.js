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
  const cardOverlay = document.getElementById("card-overlay");
  const elCardAvatar = document.getElementById("card-avatar");
  const elCardName = document.getElementById("card-name");
  const elCardSub = document.getElementById("card-sub");
  const elCardProfile = document.getElementById("card-profile");
  const elCardInquiry = document.getElementById("card-inquiry");
  const elCardListing = document.getElementById("card-listing");

  const elAvatar = document.getElementById("chat-avatar");
  const elNpcName = document.getElementById("chat-npc-name");
  const elNpcDesc = document.getElementById("chat-npc-desc");
  const elItem = document.getElementById("listing-item");
  const elPrice = document.getElementById("listing-price");
  const elMarket = document.getElementById("listing-market");
  const elLocation = document.getElementById("listing-location");
  const elBody = document.getElementById("chat-body");
  const elQuick = document.getElementById("chat-quick");
  const elInput = document.getElementById("chat-input");
  const elSend = document.getElementById("chat-send");
  const elTurn = document.getElementById("chat-turn-text");
  const elClose = document.getElementById("chat-close");
  const elDecisionLabel = document.querySelector(".decision-label");
  const buyerDecisions = document.getElementById("buyer-decisions");
  const sellerDecisions = document.getElementById("seller-decisions");
  const allDecisionBtns = document.querySelectorAll(".btn-decision");
  // 리디자인: 접히는 매물 카드 / ＋도구 / 거래판단 / 하단 시트
  const listingCard = document.getElementById("listing-card");
  const elHeadMeta = document.getElementById("listing-headmeta");
  const elPlus = document.getElementById("chat-plus");
  const elDecide = document.getElementById("btn-decide");
  const elToolsQuick = document.getElementById("tools-quick");
  const toolsSheet = document.getElementById("tools-sheet");
  const decisionSheet = document.getElementById("decision-sheet");

  // 모드별 기본 빠른 답변 (2~3개만 노출, 나머지는 답변 도구 시트에서)
  const DEFAULT_QUICK = {
    buyer: ["아직 판매 중인가요?", "실물 사진 더 볼 수 있을까요?", "직거래 가능할까요?"],
    seller: ["네, 아직 판매 중입니다.", "상태는 판매글에 적은 내용과 같습니다.", "거래는 플랫폼 안에서 진행할게요."],
  };

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
    flagBtn.textContent = "🚩";
    flagBtn.title = "의심 표시";
    flagBtn.setAttribute("aria-label", "이 메시지 의심 표시");
    flagBtn.addEventListener("click", () => toggleFlag(messageId, bubble, flagBtn));
    tools.appendChild(flagBtn);
    wrap.appendChild(tools);
    // 링크 경고기(도구): 외부 링크가 감지되면 경고만 표시 (사기로 단정하지 않음)
    if (session && (session.effects || []).indexOf("link_warning") >= 0 && hasLink(content)) {
      const warn = document.createElement("div");
      warn.className = "link-warning";
      warn.textContent = "⚠️ 외부 링크가 감지됐어요. 누르지 말고 앱 안에서 거래하세요.";
      wrap.appendChild(warn);
    }
    elBody.appendChild(wrap);
    scrollBottom();
  }
  function hasLink(text) {
    return /(\[\.\]|https?:\/\/|www\.|\b[\w-]+\.(com|net|kr|org|example)\b)/i.test(String(text || ""));
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

  /* ---------- 구매자 모드: 빈 채팅 안내 + 빠른 문의 칩 ---------- */
  // 실제 중고앱처럼 판매자 NPC 는 먼저 말하지 않는다. 플레이어가 첫 문의를 보낸다.
  function renderEmptyState() {
    const div = document.createElement("div");
    div.className = "chat-empty";
    div.id = "chat-empty";
    div.innerHTML =
      '<div class="chat-empty-emoji">💬</div>' +
      "<p>판매자에게 먼저 문의해보세요.</p>" +
      '<span class="chat-empty-hint">아래 빠른 문의를 누르거나 직접 입력해 보세요.</span>';
    elBody.appendChild(div);
  }
  function clearEmptyState() {
    const e = document.getElementById("chat-empty");
    if (e) e.remove();
  }
  function fillInput(text) {
    // '채우기' — 키보드 흐름 유지: 입력란에 넣고 포커스 (사용자가 검토 후 전송)
    if (!session || session.resolved || session.busy) return;
    elInput.value = text;
    elInput.focus();
  }
  function makeQuickChip(text, onClick) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "suggest-chip";
    chip.textContent = text;
    chip.addEventListener("click", onClick);
    return chip;
  }
  // 기본 뷰: 2~3개만. 나머지 전체 목록은 '답변 도구' 시트에 있다.
  function renderQuickChips(messages, hasMore) {
    elQuick.innerHTML = "";
    if (!messages || !messages.length) {
      elQuick.classList.add("hidden");
      return;
    }
    messages.slice(0, 3).forEach((text) =>
      elQuick.appendChild(makeQuickChip(text, () => fillInput(text)))
    );
    if (hasMore) {
      const more = makeQuickChip("답변 더보기 ⋯", () => openSheet("tools-sheet"));
      more.classList.add("quick-more");
      elQuick.appendChild(more);
    }
    elQuick.classList.remove("hidden");
  }
  // 답변 도구 시트: 전체 빠른 답변. 누르면 입력창에 채우고 시트를 닫는다.
  function renderToolsQuick(messages) {
    if (!elToolsQuick) return;
    elToolsQuick.innerHTML = "";
    (messages || []).forEach((text) =>
      elToolsQuick.appendChild(makeQuickChip(text, () => { fillInput(text); closeSheets(); }))
    );
    const sec = document.getElementById("tools-quick-sec");
    if (sec) sec.style.display = (messages && messages.length) ? "" : "none";
  }
  function hideQuickChips() {
    elQuick.innerHTML = "";
    elQuick.classList.add("hidden");
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

  /* ---------- 하단 시트 (답변 도구 / 거래 판단) ---------- */
  function closeSheets() {
    [toolsSheet, decisionSheet].forEach((s) => {
      if (!s) return;
      s.classList.add("hidden");
      s.setAttribute("aria-hidden", "true"); // 접근성: 닫히면 보조기기에서도 숨김
    });
    if (elPlus) elPlus.classList.remove("active");
  }
  function openSheet(id) {
    const target = id === "tools-sheet" ? toolsSheet : decisionSheet;
    if (!target) return;
    const wasOpen = !target.classList.contains("hidden");
    closeSheets();
    if (!wasOpen) {
      target.classList.remove("hidden");
      target.setAttribute("aria-hidden", "false"); // 열리면 보조기기에서도 노출
      if (id === "tools-sheet" && elPlus) elPlus.classList.add("active");
    }
  }
  function setListingCollapsed(collapsed) {
    if (!listingCard) return;
    listingCard.classList.toggle("collapsed", collapsed);
    listingCard.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }

  /* ---------- 프로필/매물 카드 (대화 전) ---------- */
  let cardSpawn = null;

  async function openCard(spawn) {
    SafeDealGame.setPaused(true);
    try {
      const card = await API.chat.card(spawn.spawn_instance_id);
      cardSpawn = spawn;
      renderCard(card);
      cardOverlay.classList.remove("hidden");
    } catch (err) {
      SafeDeal.toast(err.message);
      SafeDealGame.setPaused(false);
    }
  }

  function addCardMeta(label, value) {
    if (!value) return;
    const row = document.createElement("div");
    row.className = "card-l-meta";
    row.innerHTML =
      '<span class="card-l-k">' + escapeHtml(label) + "</span>" +
      "<span>" + escapeHtml(value) + "</span>";
    elCardListing.appendChild(row);
  }

  function renderCard(card) {
    const seller = card.mode === "seller";
    elCardAvatar.style.background = card.sprite_color || "#d9744f";
    elCardName.textContent = card.display_name || (seller ? "구매자" : "판매자");
    const roleWord = seller ? "구매 문의" : "판매자";
    elCardSub.textContent =
      (card.appearance ? card.appearance + " · " : "") +
      roleWord + " · 난이도 " + diffLabel(card.difficulty);

    // 판매자 모드: 구매자가 보낸 '첫 문의' 미리보기 (중립 — 유형은 대화로 알아내야 함)
    if (elCardInquiry) {
      if (seller && card.inquiry_preview) {
        elCardInquiry.textContent = "💬 “" + card.inquiry_preview + "”";
        elCardInquiry.classList.remove("hidden");
      } else {
        elCardInquiry.classList.add("hidden");
      }
    }

    // 프로필 메타 (사기꾼도 좋아 보일 수 있음 — 정답 아님)
    const p = card.profile || {};
    elCardProfile.innerHTML = "";
    [
      ["📅", p.join_text],
      ["⭐", p.review_count != null ? "후기 " + p.review_count : null],
      ["😊", p.manner_score != null ? "매너 " + p.manner_score : null],
      [p.verification_label === "본인인증 완료" ? "✅" : "⬜", p.verification_label],
    ].forEach(([ic, txt]) => {
      if (!txt) return;
      const b = document.createElement("span");
      b.className = "card-badge";
      b.textContent = ic + " " + txt;
      elCardProfile.appendChild(b);
    });

    // 매물
    const L = card.listing || {};
    elCardListing.innerHTML = "";
    const title = document.createElement("div");
    title.className = "card-l-title";
    title.textContent = L.listing_title || L.item_name || "";
    elCardListing.appendChild(title);

    const priceRow = document.createElement("div");
    priceRow.className = "card-l-price-row";
    const ps = document.createElement("span");
    ps.className = "card-l-price";
    ps.textContent = won(L.listing_price || 0);
    priceRow.appendChild(ps);
    if (L.market_price) {
      const mk = document.createElement("span");
      mk.className = "card-l-market";
      mk.textContent = (L.market_price_min && L.market_price_max)
        ? "시세 " + won(L.market_price_min) + "~" + won(L.market_price_max)
        : "시세 약 " + won(L.market_price);
      priceRow.appendChild(mk);
    }
    elCardListing.appendChild(priceRow);

    addCardMeta("상태", L.condition_label);
    if ((L.disclosed_defects || []).length) addCardMeta("고지된 하자", L.disclosed_defects.join(", "));
    if ((L.accessories || []).length) addCardMeta("구성품", L.accessories.join(", "));
    if ((L.trade_methods || []).length) addCardMeta("거래방식", L.trade_methods.join(" · "));
    addCardMeta("위치", L.region_label);
    if (L.listing_description) {
      const d = document.createElement("p");
      d.className = "card-l-desc";
      d.textContent = L.listing_description;
      elCardListing.appendChild(d);
    }
    // 시세 레이더(도구) 힌트 — 정답을 알려주지 않는 '주의' 신호일 뿐
    if (card.price_radar) {
      const r = document.createElement("div");
      r.className = "card-radar";
      r.textContent = "📡 " + card.price_radar;
      elCardListing.appendChild(r);
    }
  }

  function closeCard() {
    cardOverlay.classList.add("hidden");
    cardSpawn = null;
    SafeDealGame.setPaused(false);
  }
  function startFromCard() {
    cardOverlay.classList.add("hidden");
    const s = cardSpawn;
    cardSpawn = null;
    if (s) openChat(s);
  }

  /* ---------- 대화 시작 ---------- */
  async function openChat(spawn) {
    // spawn: { spawn_instance_id, name, ... } (npc_id/role 은 클라이언트에 없음)
    SafeDealGame.setPaused(true);
    try {
      // 판매자 모드 인바운드 문의에서 시작하면 inquiry_id 를 함께 보내 '수락됨' 처리한다.
      const data = await API.chat.start(spawn.spawn_instance_id, spawn.inquiry_id);
      const effects = (SafeDealGame.effects && SafeDealGame.effects()) || [];
      session = {
        sessionId: data.session_id,
        npc: data.npc,
        mode: data.mode || "buyer",
        maxTurns: data.max_turns,
        playerTurns: 0,
        busy: false,
        resolved: false,
        effects: effects,
        // 구매자 모드: 판매자 NPC 는 먼저 말하지 않는다 → 플레이어가 첫 문의를 보내야 함
        requiresPlayerFirst: !!data.requires_player_first_message,
      };

      // 헤더
      elAvatar.style.background = data.npc.sprite_color || "#d9744f";
      const roleWord = session.mode === "seller" ? "구매자" : "판매자";
      elNpcName.textContent = data.npc.name;
      elNpcDesc.textContent =
        (data.npc.appearance ? data.npc.appearance + " · " : "") +
        roleWord + " · 난이도 " + diffLabel(data.npc.difficulty);

      const seller = session.mode === "seller";

      // 접히는 매물 카드 (기본은 한 줄 요약)
      elItem.textContent = data.npc.item_name;
      elHeadMeta.textContent = "· " + (seller ? "내 매물" : (data.npc.location || "동네 직거래"));
      if (seller) {
        elPrice.textContent = "";
        elMarket.textContent = "내가 올린 중고 매물";
      } else {
        elPrice.textContent = won(data.npc.listing_price);
        elMarket.textContent = "시세 약 " + won(data.npc.market_price);
      }
      elLocation.textContent = "📍 " + data.npc.location;
      setListingCollapsed(true);

      // 결정 버튼 그룹 전환 (거래 판단 시트 안)
      buyerDecisions.style.display = seller ? "none" : "";
      sellerDecisions.style.display = seller ? "" : "none";
      if (elDecisionLabel) elDecisionLabel.textContent = "대화를 충분히 보고 최종 대응을 선택하세요.";
      closeSheets();

      elBody.innerHTML = "";
      if (session.requiresPlayerFirst || !data.opening) {
        // 빈 채팅 — 판매자 NPC 오프닝은 렌더하지 않는다 (플레이어가 먼저 문의).
        renderEmptyState();
      } else {
        addNpcMessage(data.opening.message_id, data.opening.content);
      }

      // 기본 빠른 답변 (2~3개만 노출, 전체는 답변 도구 시트에)
      const serverQuick = (data.suggested_messages && data.suggested_messages.length)
        ? data.suggested_messages : null;
      const quickAll = seller ? DEFAULT_QUICK.seller : (serverQuick || DEFAULT_QUICK.buyer);
      renderQuickChips(quickAll, quickAll.length > 3);
      renderToolsQuick(quickAll);
      updateTurn();

      elInput.value = "";
      elInput.placeholder = seller ? "구매자에게 메시지 보내기..." : "판매자에게 메시지 보내기...";

      // 체크리스트 + 장착 도구 답변칩 (세션마다 초기화)
      if (global.SafeDealChecklist) {
        SafeDealChecklist.begin(session.mode, session.effects, (text) => {
          elInput.value = text;
          elInput.focus();
        });
      }

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
    // 첫 메시지: 빈 채팅 안내/빠른 문의 칩을 걷어낸다 (이 메시지가 '플레이어 첫 발화').
    clearEmptyState();
    hideQuickChips();
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
    closeSheets();
    setInputEnabled(false);
    showTyping();
    try {
      const checklist = global.SafeDealChecklist ? SafeDealChecklist.getChecked() : [];
      const result = await API.chat.resolve(session.sessionId, decision, checklist);
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
    // 플레이어 본인 부적절 행위 (양쪽 모드)
    player_misconduct: { cls: "bad", emoji: "🚫", title: "부적절한 대응이었어요" },
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
    if (r.checklist && r.checklist.length) {
      chips.appendChild(makeChip(
        "📋 체크 " + r.checklist.length + (r.checklist_bonus ? " (+" + r.checklist_bonus + ")" : ""),
        "up"
      ));
    }

    // 인벤토리 아이템 보상 (거래 도구/배지/코스튬)
    renderRewardItems(r.reward_items || []);

    document.getElementById("result-coaching").textContent = r.coaching || "";

    // 거래 후 상황 + 현실 교훈
    const after = r.aftermath || {};
    const afterSec = document.getElementById("aftermath-section");
    if (after.situation || after.lesson) {
      document.getElementById("aftermath-situation").textContent = after.situation || "";
      document.getElementById("aftermath-lesson").textContent = after.lesson || "";
      afterSec.classList.remove("hidden");
    } else {
      afterSec.classList.add("hidden");
    }

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

    // 적응형 학습 피드백 (결과 이후에만 — 라벨/원칙만)
    renderLearning(r.learning);

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

  /* ---------- 적응형 학습 피드백 (결과 모달) ---------- */
  function renderLearning(learning) {
    const sec = document.getElementById("learning-section");
    const box = document.getElementById("result-learning");
    const next = document.getElementById("learning-next");
    box.innerHTML = "";
    next.classList.add("hidden");
    next.textContent = "";
    const signals = (learning && learning.trained_signals) || [];
    if (!learning || signals.length === 0) {
      sec.classList.add("hidden");
      return;
    }
    signals.forEach((s) => {
      const row = document.createElement("div");
      row.className = "learning-line " + (s.caught ? "caught" : "missed");
      row.innerHTML =
        '<div class="learning-head">' +
        '<span class="learning-ic">' + (s.caught ? "✅" : "⚠️") + "</span>" +
        '<span class="learning-label">' + escapeHtml(s.label) + "</span>" +
        '<span class="learning-tag">' + (s.caught ? "잘 잡음" : "놓침") + "</span>" +
        "</div>" +
        (s.red_flag ? '<div class="learning-rf">위험 신호 — ' + escapeHtml(s.red_flag) + "</div>" : "") +
        (s.safe_counter ? '<div class="learning-sc">💡 ' + escapeHtml(s.safe_counter) + "</div>" : "");
      box.appendChild(row);
    });
    if (learning.next_principle) {
      next.textContent = "🧭 비슷한 상황에서 적용할 원칙 — " + learning.next_principle;
      next.classList.remove("hidden");
    }
    sec.classList.remove("hidden");
  }

  const REWARD_ICON = {
    cosmetic: "✨", badge: "🏅", tool: "🧰", profile_frame: "🖼️", checklist: "📋",
  };
  const RARITY_KO = {
    common: "흔함", uncommon: "고급", rare: "희귀", epic: "에픽", legendary: "전설",
  };
  function renderRewardItems(items) {
    const sec = document.getElementById("reward-items-section");
    const box = document.getElementById("result-reward-items");
    box.innerHTML = "";
    if (!items.length) { sec.classList.add("hidden"); return; }
    items.forEach((it) => {
      const card = document.createElement("div");
      card.className = "reward-item rarity-" + it.rarity;
      card.innerHTML =
        '<span class="reward-item-ic">' + (REWARD_ICON[it.item_type] || "📦") + "</span>" +
        '<div class="reward-item-body">' +
        '<div class="reward-item-name">' + escapeHtml(it.name) +
        ' <span class="reward-item-rarity rarity-text-' + it.rarity + '">' + (RARITY_KO[it.rarity] || it.rarity) + "</span></div>" +
        '<div class="reward-item-desc">' + escapeHtml(it.description || "") + "</div>" +
        "</div>";
      box.appendChild(card);
    });
    sec.classList.remove("hidden");
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
    closeSheets();
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

  /* ---------- 실력 분석 / 훈련 리포트 (적응형) ---------- */
  const trainingOverlay = document.getElementById("training-overlay");
  const trainingBody = document.getElementById("training-body");

  async function openTraining() {
    try {
      const data = await API.game.trainingProfile();
      renderTraining(data);
      trainingOverlay.classList.remove("hidden");
    } catch (err) { SafeDeal.toast(err.message); }
  }

  function trainingListCard(title, icon, lines, cls) {
    const box = document.createElement("div");
    box.className = "habit-card " + (cls || "");
    box.innerHTML = "<h4>" + icon + " " + escapeHtml(title) + "</h4>";
    const ul = document.createElement("ul");
    if (!lines || !lines.length) {
      const li = document.createElement("li");
      li.className = "habit-muted";
      li.textContent = "아직 없어요.";
      ul.appendChild(li);
    } else {
      lines.forEach((t) => {
        const li = document.createElement("li");
        li.textContent = t;
        ul.appendChild(li);
      });
    }
    box.appendChild(ul);
    return box;
  }

  function trainingRoleBlock(title, icon, role) {
    const wrap = document.createElement("div");
    wrap.className = "training-role";
    const h = document.createElement("h3");
    h.textContent = icon + " " + title;
    wrap.appendChild(h);

    const cards = (role && role.mastery_cards) || [];
    if (!cards.length) {
      const muted = document.createElement("p");
      muted.className = "habit-muted";
      muted.textContent = (role && role.history_count)
        ? "이 모드의 위험 신호 훈련 기록이 아직 적어요."
        : "아직 이 모드의 거래 기록이 없어요. 마을에서 거래해 보면 분석이 쌓여요!";
      wrap.appendChild(muted);
    }
    wrap.appendChild(trainingListCard("잘 잡아낸 위험 신호", "💪", role.strengths, "good"));
    wrap.appendChild(trainingListCard("자주 놓친 위험 신호", "🚩", role.weaknesses, "weak"));

    const rec = document.createElement("div");
    rec.className = "habit-card next";
    rec.innerHTML = "<h4>🎯 다음 훈련 추천</h4><p>" +
      escapeHtml(role.recommended_next_training || "") + "</p>";
    wrap.appendChild(rec);

    if (cards.length) {
      const bars = document.createElement("div");
      bars.className = "training-bars";
      cards.forEach((c) => {
        const cls = c.mastery_pct >= 80 ? "strong" : (c.mastery_pct < 40 ? "weakbar" : "mid");
        const row = document.createElement("div");
        row.className = "training-bar-row";
        row.innerHTML =
          '<span class="training-bar-label">' + escapeHtml(c.label) + "</span>" +
          '<span class="training-bar-track"><span class="training-bar-fill ' + cls +
          '" style="width:' + c.mastery_pct + '%"></span></span>' +
          '<span class="training-bar-pct">' + c.mastery_pct + "%</span>";
        bars.appendChild(row);
      });
      wrap.appendChild(bars);
    }
    return wrap;
  }

  function renderTraining(data) {
    trainingBody.innerHTML = "";
    if (data && data.adaptive_enabled === false) {
      const warn = document.createElement("p");
      warn.className = "habit-muted";
      warn.textContent =
        "적응형 훈련 엔진이 꺼져 있어요. (ADAPTIVE_SCENARIOS_ENABLED=false) — 켜면 분석이 쌓여요.";
      trainingBody.appendChild(warn);
    }
    [["구매자 모드", "🛒", data.buyer], ["판매자 모드", "🏪", data.seller]].forEach(
      ([t, ic, role]) => {
        if (role) trainingBody.appendChild(trainingRoleBlock(t, ic, role));
      }
    );
  }

  async function resetTraining() {
    if (!window.confirm("이 계정의 적응형 훈련 메모리만 초기화할까요?\n(거래 기록·계정·인벤토리는 그대로 유지돼요)")) {
      return;
    }
    try {
      await API.game.resetTrainingProfile();
      SafeDeal.toast("훈련 메모리를 초기화했어요.");
      openTraining();
    } catch (err) { SafeDeal.toast(err.message); }
  }

  function closeTraining() { trainingOverlay.classList.add("hidden"); }

  /* ---------- 이벤트 ---------- */
  elSend.addEventListener("click", sendMessage);
  elInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); sendMessage(); }
  });
  allDecisionBtns.forEach((btn) =>
    btn.addEventListener("click", () => resolveTrade(btn.dataset.decision))
  );
  elClose.addEventListener("click", closeChat);

  /* 리디자인: 접히는 매물 카드 / ＋도구 / 거래판단 / 시트 닫기 */
  if (listingCard) {
    listingCard.addEventListener("click", () =>
      setListingCollapsed(!listingCard.classList.contains("collapsed"))
    );
    listingCard.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setListingCollapsed(!listingCard.classList.contains("collapsed"));
      }
    });
  }
  if (elPlus) elPlus.addEventListener("click", () => openSheet("tools-sheet"));
  if (elDecide) elDecide.addEventListener("click", () => openSheet("decision-sheet"));
  document.querySelectorAll(".sheet-close").forEach((b) =>
    b.addEventListener("click", closeSheets)
  );
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const anyOpen = (toolsSheet && !toolsSheet.classList.contains("hidden")) ||
                    (decisionSheet && !decisionSheet.classList.contains("hidden"));
    if (anyOpen) { e.preventDefault(); closeSheets(); }
  });
  document.getElementById("result-close").addEventListener("click", closeResult);
  document.getElementById("record-close").addEventListener("click", closeRecord);

  // 실력 분석 / 훈련 리포트
  document.getElementById("btn-training").addEventListener("click", openTraining);
  document.getElementById("training-close").addEventListener("click", closeTraining);
  document.getElementById("btn-training-reset").addEventListener("click", resetTraining);
  trainingOverlay.addEventListener("click", (e) => {
    if (e.target === trainingOverlay) closeTraining();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") trainingOverlay.classList.add("hidden");
  });

  // 프로필/매물 카드
  document.getElementById("card-start").addEventListener("click", startFromCard);
  document.getElementById("card-cancel").addEventListener("click", closeCard);
  document.getElementById("card-close").addEventListener("click", closeCard);
  cardOverlay.addEventListener("click", (e) => { if (e.target === cardOverlay) closeCard(); });
  // 카드가 열려 있을 때 키보드로도 시작/닫기 (게임 루프는 멈춰 있음)
  window.addEventListener("keydown", (e) => {
    if (cardOverlay.classList.contains("hidden")) return;
    if (e.key === "Enter" || e.code === "KeyE" || e.code === "Space") {
      e.preventDefault(); startFromCard();
    } else if (e.key === "Escape") {
      e.preventDefault(); closeCard();
    }
  });

  global.SafeDealChat = { openCard, openChat, openRecord, openTraining, closeChat };
})(window);
