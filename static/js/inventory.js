/* ============================================================
   inventory.js — 거래 가방(인벤토리) + 장착 + 거래 습관 리포트
   - 보유 아이템 조회/장착/해제
   - 코스튬 장착 시 아바타 즉시 반영(SafeDealGame.refreshWorld)
   - 도구 장착 시 대화 중 체크리스트/답변칩에 반영(효과키는 서버가 관리)
   - '내 거래 습관' 리포트(GET /habit-report)
   ============================================================ */
(function (global) {
  "use strict";

  const overlay = document.getElementById("inventory-overlay");
  const equippedEl = document.getElementById("inv-equipped");
  const gridEl = document.getElementById("inv-grid");
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

  /* ---------- 열기 ---------- */
  async function open() {
    try {
      const inv = await API.game.inventory();
      render(inv);
      overlay.classList.remove("hidden");
    } catch (err) {
      SafeDeal.toast(err.message);
    }
  }

  function render(inv) {
    const items = inv.items || [];
    const equip = inv.equipment || {};

    // 장착 현황
    equippedEl.innerHTML = "";
    const equippedItems = items.filter((i) => i.equipped);
    if (equippedItems.length === 0) {
      equippedEl.innerHTML = '<p class="inv-empty-eq">아직 장착한 아이템이 없어요.</p>';
    } else {
      equippedItems.forEach((it) => {
        const chip = document.createElement("div");
        chip.className = "inv-eq-chip rarity-" + it.rarity;
        chip.innerHTML =
          '<span class="inv-eq-slot">' + escapeHtml(SLOT_LABEL[it.equipped_slot] || it.equipped_slot) + "</span>" +
          '<span>' + iconFor(it) + " " + escapeHtml(it.name) + "</span>";
        const x = document.createElement("button");
        x.className = "inv-eq-x"; x.textContent = "✕"; x.title = "해제";
        x.addEventListener("click", () => doUnequip(it.equipped_slot));
        chip.appendChild(x);
        equippedEl.appendChild(chip);
      });
    }

    // 보유 그리드
    gridEl.innerHTML = "";
    if (items.length === 0) {
      gridEl.innerHTML =
        '<p class="inv-empty">거래를 성공하면 도구·배지·코스튬을 얻을 수 있어요. 마을에서 좋은 거래를 해보세요!</p>';
      return;
    }
    items.forEach((it) => {
      const card = document.createElement("div");
      card.className = "inv-card rarity-" + it.rarity + (it.equipped ? " equipped" : "");
      card.innerHTML =
        '<div class="inv-card-top">' +
        '<span class="inv-icon">' + iconFor(it) + "</span>" +
        '<span class="inv-rarity rarity-text-' + it.rarity + '">' + (RARITY_LABEL[it.rarity] || it.rarity) + "</span>" +
        "</div>" +
        '<div class="inv-name">' + escapeHtml(it.name) + (it.quantity > 1 ? ' <span class="inv-qty">×' + it.quantity + "</span>" : "") + "</div>" +
        '<div class="inv-type">' + (TYPE_LABEL[it.item_type] || it.item_type) + "</div>" +
        '<div class="inv-desc">' + escapeHtml(it.description || "") + "</div>";
      const btn = document.createElement("button");
      btn.className = "inv-btn" + (it.equipped ? " on" : "");
      btn.textContent = it.equipped ? "해제" : "장착";
      btn.addEventListener("click", () => {
        if (it.equipped) doUnequip(it.equipped_slot);
        else doEquip(it.id);
      });
      card.appendChild(btn);
      gridEl.appendChild(card);
    });
  }

  async function doEquip(itemId, slot) {
    try {
      const inv = await API.game.equip(itemId, slot);
      render(inv);
      if (SafeDealGame && SafeDealGame.refreshWorld) SafeDealGame.refreshWorld();
    } catch (err) { SafeDeal.toast(err.message); }
  }
  async function doUnequip(slot) {
    try {
      const inv = await API.game.unequip(slot);
      render(inv);
      if (SafeDealGame && SafeDealGame.refreshWorld) SafeDealGame.refreshWorld();
    } catch (err) { SafeDeal.toast(err.message); }
  }

  function close() { overlay.classList.add("hidden"); }

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
  document.getElementById("btn-bag").addEventListener("click", open);
  document.getElementById("inventory-close").addEventListener("click", close);
  document.getElementById("btn-habit").addEventListener("click", openHabit);
  document.getElementById("habit-close").addEventListener("click", closeHabit);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  habitOverlay.addEventListener("click", (e) => { if (e.target === habitOverlay) closeHabit(); });
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    overlay.classList.add("hidden");
    habitOverlay.classList.add("hidden");
  });

  global.SafeDealInventory = { open, openHabit };
})(window);
