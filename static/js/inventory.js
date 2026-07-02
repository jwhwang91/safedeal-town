/* ============================================================
   inventory.js — 거래 가방(인벤토리): Diablo/Lineage 식 페이퍼돌
   - 좌: 아바타 미리보기 + 주변 장비 슬롯 (드래그&드롭 / 탭 장착)
   - 우: 보유 아이템 그리드 + 선택 아이템 상세
   - 코스튬 장착 시 아바타 즉시 반영(미리보기 + SafeDealGame.refreshWorld)
   - 도구 장착 시 대화 중 체크리스트/답변칩에 반영(효과키는 서버가 관리)
   - '내 거래 습관' 리포트(GET /habit-report)
   무대 안 사이드 도크(#inventory-dock)로 떠서, 플레이 중에도 열어둘 수 있다.
   ============================================================ */
(function (global) {
  "use strict";

  const dock = document.getElementById("inventory-dock");
  const gridEl = document.getElementById("inv-grid");
  const detailEl = document.getElementById("inv-detail");
  const dollFrame = document.getElementById("inv-doll-frame");
  const avatarCanvas = document.getElementById("inv-avatar-canvas");
  const habitOverlay = document.getElementById("habit-overlay");
  const habitBody = document.getElementById("habit-body");

  const RARITY_LABEL = {
    common: "흔함", uncommon: "고급", rare: "희귀", epic: "에픽", legendary: "전설",
  };
  const TYPE_LABEL = {
    cosmetic: "코스튬", badge: "신뢰 배지", tool: "거래 도구",
    profile_frame: "프로필", checklist: "체크리스트",
  };
  const SLOT_LABEL = {
    hat: "모자", shirt: "상의", pants: "하의", accessory: "액세서리",
    badge: "배지", tool_1: "도구1", tool_2: "도구2", profile_frame: "프레임", tool: "도구",
  };
  const EFFECT_ICON = {
    price_radar: "📡", link_warning: "🔗", account_check: "🧾",
    proof_request_kit: "📷", evidence_folder: "🗂️", refund_response_card: "💳",
    safe_trade_checklist: "✅", dispute_guide: "⚖️",
  };
  // 빈 슬롯에 흐릿하게 보여줄 유령 아이콘 (무엇을 넣는 칸인지 힌트)
  const SLOT_GHOST = {
    hat: "🧢", accessory: "🕶️", badge: "🏅", shirt: "👕",
    pants: "👖", profile_frame: "🖼️", tool_1: "🧰", tool_2: "🧰",
  };

  let currentInv = null;   // 마지막 인벤토리 응답
  let selectedId = null;   // 상세에 표시 중인 아이템 id
  let dragItem = null;     // 드래그 중인 아이템

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function iconFor(it) {
    if (it.item_type === "tool") return EFFECT_ICON[it.effect_key] || "🧰";
    if (it.item_type === "badge") return "🏅";
    if (it.item_type === "profile_frame") return "🖼️";
    if (it.item_type === "cosmetic") {
      return { hat: "🧢", shirt: "👕", pants: "👖", accessory: "🕶️" }[it.slot] || "✨";
    }
    return "📦";
  }

  function itemById(id) { return currentInv && (currentInv.items || []).find((i) => i.id === id); }
  function equippedInSlot(slotName) {
    return currentInv && (currentInv.items || []).find((i) => i.equipped && i.equipped_slot === slotName);
  }
  // 슬롯이 이 아이템을 받을 수 있나? (도구는 tool_1/2 아무곳, 나머지는 지정 슬롯)
  function slotAccepts(slotName, item) {
    if (!item) return false;
    if (item.item_type === "tool") return slotName === "tool_1" || slotName === "tool_2";
    return item.slot === slotName;
  }

  /* ---------- 아바타 미리보기 (base + 코스튬 오버라이드) ---------- */
  function drawAvatar() {
    if (!avatarCanvas || !global.SafeDealAvatar) return;
    const base = (currentInv && currentInv.avatar_base) || SafeDealAvatar.DEFAULT_AVATAR;
    const ov = (currentInv && currentInv.cosmetic_overrides) || {};
    const merged = Object.assign({}, base, ov);
    const ctx = avatarCanvas.getContext("2d");
    ctx.clearRect(0, 0, avatarCanvas.width, avatarCanvas.height);
    SafeDealAvatar.draw(ctx, 60, 84, merged, { scale: 2.3, facing: "down" });
  }

  /* ---------- 렌더 ---------- */
  function render(inv) {
    currentInv = inv;
    // 선택 아이템이 사라졌으면 상세 닫기
    if (selectedId && !itemById(selectedId)) selectedId = null;
    renderSlots();
    renderGrid();
    renderDetail();
    drawAvatar();
  }

  function renderSlots() {
    dollFrame.querySelectorAll(".eq-slot").forEach((slotEl) => {
      const slotName = slotEl.dataset.slot;
      const it = equippedInSlot(slotName);
      slotEl.classList.toggle("filled", !!it);
      slotEl.classList.toggle("empty", !it);
      if (it) {
        slotEl.innerHTML = '<span class="eq-icon">' + iconFor(it) + "</span>";
        slotEl.title = (SLOT_LABEL[slotName] || slotName) + ": " + it.name + " — 탭하면 해제";
      } else {
        slotEl.innerHTML = '<span class="eq-ghost">' + (SLOT_GHOST[slotName] || "") + "</span>";
        slotEl.title = SLOT_LABEL[slotName] || slotName;
      }
    });
  }

  function renderGrid() {
    const items = (currentInv && currentInv.items) || [];
    gridEl.innerHTML = "";
    if (!items.length) {
      gridEl.innerHTML =
        '<p class="inv-empty">거래를 성공하면 도구·배지·코스튬을 얻을 수 있어요. 마을에서 좋은 거래를 해보세요!</p>';
      return;
    }
    items.forEach((it) => {
      const card = document.createElement("div");
      card.className =
        "inv-card rarity-" + it.rarity +
        (it.equipped ? " equipped" : "") + (it.id === selectedId ? " selected" : "");
      card.dataset.id = it.id;
      card.setAttribute("draggable", "true");
      card.innerHTML =
        '<div class="inv-card-top">' +
        '<span class="inv-icon">' + iconFor(it) + "</span>" +
        '<span class="inv-rarity rarity-text-' + it.rarity + '">' + (RARITY_LABEL[it.rarity] || it.rarity) + "</span>" +
        "</div>" +
        '<div class="inv-name">' + escapeHtml(it.name) + (it.quantity > 1 ? ' <span class="inv-qty">×' + it.quantity + "</span>" : "") + "</div>" +
        '<div class="inv-type">' + (TYPE_LABEL[it.item_type] || it.item_type) + "</div>";
      card.addEventListener("click", () => selectItem(it.id));
      card.addEventListener("dblclick", () => toggleEquip(it));
      card.addEventListener("dragstart", (e) => onDragStart(e, it));
      card.addEventListener("dragend", onDragEnd);
      gridEl.appendChild(card);
    });
  }

  function selectItem(id) {
    selectedId = id;
    renderDetail();
    gridEl.querySelectorAll(".inv-card").forEach((c) => c.classList.toggle("selected", c.dataset.id === id));
  }

  function renderDetail() {
    if (!selectedId) { detailEl.classList.add("hidden"); detailEl.innerHTML = ""; return; }
    const it = itemById(selectedId);
    if (!it) { detailEl.classList.add("hidden"); detailEl.innerHTML = ""; return; }
    detailEl.className = "inv-detail rarity-" + it.rarity;
    detailEl.innerHTML =
      '<div class="inv-detail-head">' +
      '<span class="inv-icon">' + iconFor(it) + "</span>" +
      '<span class="inv-detail-name">' + escapeHtml(it.name) + "</span>" +
      '<span class="inv-rarity rarity-text-' + it.rarity + '">' + (RARITY_LABEL[it.rarity] || it.rarity) + "</span>" +
      "</div>" +
      '<div class="inv-detail-type">' + (TYPE_LABEL[it.item_type] || it.item_type) +
      (it.slot ? " · " + (SLOT_LABEL[it.slot] || it.slot) : "") + "</div>" +
      '<div class="inv-detail-desc">' + escapeHtml(it.description || "") + "</div>" +
      (it.effect_key ? '<div class="inv-detail-effect">' + (EFFECT_ICON[it.effect_key] || "🧰") + " 대화 중 효과가 적용돼요</div>" : "");
    const actions = document.createElement("div");
    actions.className = "inv-detail-actions";
    const btn = document.createElement("button");
    btn.className = "inv-mini-btn" + (it.equipped ? " off" : "");
    btn.textContent = it.equipped ? "해제하기" : "장착하기";
    btn.addEventListener("click", () => toggleEquip(it));
    actions.appendChild(btn);
    detailEl.appendChild(actions);
    detailEl.classList.remove("hidden");
  }

  /* ---------- 드래그 & 드롭 ---------- */
  function onDragStart(e, it) {
    dragItem = it;
    try {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", it.id);
    } catch (_) { /* 일부 브라우저 무시 */ }
    e.currentTarget.classList.add("dragging");
    dollFrame.querySelectorAll(".eq-slot").forEach((s) => {
      if (slotAccepts(s.dataset.slot, it)) s.classList.add("drop-ok");
    });
  }
  function onDragEnd(e) {
    e.currentTarget.classList.remove("dragging");
    dollFrame.querySelectorAll(".eq-slot").forEach((s) => s.classList.remove("drop-ok", "drop-hot"));
    dragItem = null;
  }
  // 슬롯 이벤트: 드롭(장착) + 탭(해제)
  dollFrame.querySelectorAll(".eq-slot").forEach((slotEl) => {
    slotEl.addEventListener("dragover", (e) => {
      if (dragItem && slotAccepts(slotEl.dataset.slot, dragItem)) {
        e.preventDefault();
        slotEl.classList.add("drop-hot");
      }
    });
    slotEl.addEventListener("dragleave", () => slotEl.classList.remove("drop-hot"));
    slotEl.addEventListener("drop", (e) => {
      e.preventDefault();
      slotEl.classList.remove("drop-hot");
      if (dragItem && slotAccepts(slotEl.dataset.slot, dragItem)) doEquip(dragItem.id, slotEl.dataset.slot);
    });
    slotEl.addEventListener("click", () => {
      const it = equippedInSlot(slotEl.dataset.slot);
      if (it) doUnequip(slotEl.dataset.slot);
    });
  });

  function toggleEquip(it) {
    if (it.equipped) doUnequip(it.equipped_slot);
    else doEquip(it.id, null); // 슬롯은 서버가 추론 (도구는 빈 도구슬롯 우선)
  }

  async function doEquip(itemId, slot) {
    try {
      const inv = await API.game.equip(itemId, slot);
      selectedId = itemId; // 방금 장착한 걸 상세에 유지
      render(inv);
      if (global.SafeDealGame && SafeDealGame.refreshWorld) SafeDealGame.refreshWorld();
    } catch (err) { SafeDeal.toast(err.message); }
  }
  async function doUnequip(slot) {
    try {
      const inv = await API.game.unequip(slot);
      render(inv);
      if (global.SafeDealGame && SafeDealGame.refreshWorld) SafeDealGame.refreshWorld();
    } catch (err) { SafeDeal.toast(err.message); }
  }

  /* ---------- 열기 / 닫기 (사이드 도크) ---------- */
  async function open() {
    try {
      const inv = await API.game.inventory();
      render(inv);
    } catch (err) {
      SafeDeal.toast(err.message);
      return;
    }
    // 미션 도크와 우측을 공유하므로 겹치지 않게 닫아준다
    if (global.SafeDealMissions && SafeDealMissions.closePanel) SafeDealMissions.closePanel();
    dock.classList.remove("hidden");
  }
  function close() { dock.classList.add("hidden"); }
  function toggle() { if (dock.classList.contains("hidden")) open(); else close(); }

  /* ---------- 거래 습관 리포트 ---------- */
  async function openHabit() {
    try {
      const rep = await API.game.habitReport();
      renderHabit(rep);
      habitOverlay.classList.remove("hidden");
    } catch (err) { SafeDeal.toast(err.message); }
  }
  function habitCard(title, icon, lines, cls) {
    const box = document.createElement("div");
    box.className = "habit-card " + (cls || "");
    box.innerHTML = "<h4>" + icon + " " + escapeHtml(title) + "</h4>";
    const ul = document.createElement("ul");
    if (!lines || lines.length === 0) {
      const li = document.createElement("li");
      li.className = "habit-muted";
      li.textContent = "아직 데이터가 부족해요.";
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
  function renderHabit(rep) {
    habitBody.innerHTML = "";
    const s = rep.summary || {};
    const statRow = document.createElement("div");
    statRow.className = "habit-stats";
    [
      ["거래", s.total_trades || 0],
      ["구매 정확도", (s.buyer_accuracy != null ? s.buyer_accuracy : 0) + "%"],
      ["판매 정확도", (s.seller_accuracy != null ? s.seller_accuracy : 0) + "%"],
      ["평균 점수", s.avg_score || 0],
    ].forEach(([lbl, num]) => {
      const b = document.createElement("div");
      b.className = "stat-box";
      b.innerHTML = '<div class="num">' + escapeHtml(num) + '</div><div class="lbl">' + escapeHtml(lbl) + "</div>";
      statRow.appendChild(b);
    });
    habitBody.appendChild(statRow);
    habitBody.appendChild(habitCard("잘하는 것", "💪", rep.strengths, "good"));
    habitBody.appendChild(habitCard("보완할 것", "🩹", rep.weaknesses, "weak"));
    habitBody.appendChild(habitCard("다음 훈련 추천", "🎯", rep.recommendations, "next"));
    if (rep.common_missed_flags && rep.common_missed_flags.length) {
      habitBody.appendChild(habitCard("자주 놓친 위험 신호", "🚩", rep.common_missed_flags, "weak"));
    }
    if (rep.common_correct && rep.common_correct.length) {
      habitBody.appendChild(habitCard("자주 잘 잡아낸 신호", "✅", rep.common_correct, "good"));
    }
  }
  function closeHabit() { habitOverlay.classList.add("hidden"); }

  /* ---------- 이벤트 ---------- */
  document.getElementById("btn-bag").addEventListener("click", toggle);
  document.getElementById("inventory-close").addEventListener("click", close);
  document.getElementById("btn-habit").addEventListener("click", openHabit);
  document.getElementById("habit-close").addEventListener("click", closeHabit);
  habitOverlay.addEventListener("click", (e) => { if (e.target === habitOverlay) closeHabit(); });
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!habitOverlay.classList.contains("hidden")) { closeHabit(); return; }
    if (!dock.classList.contains("hidden")) close();
  });

  global.SafeDealInventory = { open, close, toggle, openHabit };
})(window);
