/* ============================================================
   missions.js — 미션(퀘스트) 시스템
   - 마을 입장/역할 전환 시 활성 미션이 없으면 새 미션을 제안 (checkAndOffer)
   - HUD 에 진행중인 미션을 작은 칩으로 보여주고, 펼치면 상세/포기 가능
   - 거래 결과 모달에 미션 성공/실패 결과를 덧붙여 표시 (renderResult)
   보조 시스템이라 항상 조용히 실패해야 한다 — API 가 없거나 에러가 나도
   본 게임 흐름(입장/대화/채점)을 절대 막지 않는다.
   ============================================================ */
(function (global) {
  "use strict";

  /* ---------- DOM: 미션 제안 오버레이 ---------- */
  const offerOverlay = document.getElementById("mission-overlay");
  const elTitle = document.getElementById("mission-title");
  const elSituation = document.getElementById("mission-situation");
  const elConstraints = document.getElementById("mission-constraints");
  const elRewardPreview = document.getElementById("mission-reward-preview");
  const acceptBtn = document.getElementById("mission-accept");
  const skipBtn = document.getElementById("mission-skip");
  const closeBtn = document.getElementById("mission-close");

  /* ---------- DOM: 무대 미션 칩 + 사이드 도크 상세 패널 ---------- */
  const hudChip = document.getElementById("hud-mission");
  const hudChipText = document.getElementById("hud-mission-text");
  const hudToggle = document.getElementById("hud-mission-toggle");
  const detailPanel = document.getElementById("mission-detail-panel"); // .side-dock (aside)
  const detailBody = document.getElementById("mission-detail-body");   // 실제 내용이 들어가는 곳
  const detailClose = document.getElementById("mission-detail-close");

  /* ---------- DOM: 결과 모달 미션 섹션 ---------- */
  const resultSection = document.getElementById("mission-result-section");
  const elOutcomeChip = document.getElementById("mission-outcome-chip");
  const elReason = document.getElementById("mission-reason");
  const elLesson = document.getElementById("mission-lesson");
  const elBonusChips = document.getElementById("mission-bonus-chips");

  /* 제안 오버레이에 현재 표시 중인 미션(수락 전, 카탈로그 항목) */
  let offeredMission = null;

  /* ---------- 제약 조건 → 한국어 라벨 ---------- */
  const CONSTRAINT_LABELS = {
    direct_trade_allowed: function (v) {
      return v === false ? "🚫 직거래는 안 돼요 — 택배/안전결제로만 진행하세요" : null;
    },
    delivery_required: function (v) {
      return v ? "📦 무조건 택배 거래로만 진행해야 해요" : null;
    },
    platform_chat_required: function (v) {
      return v ? "💬 플랫폼 채팅 안에서만 대화하세요" : null;
    },
    external_link_forbidden: function (v) {
      return v ? "🔗 외부 링크는 절대 열지 마세요" : null;
    },
    safe_payment_required: function (v) {
      return v ? "🔒 플랫폼 안전결제만 이용하세요" : null;
    },
    external_payment_forbidden: function (v) {
      return v ? "🚫 외부 결제 페이지는 이용하지 마세요" : null;
    },
    private_payment_link_forbidden: function (v) {
      return v ? "🚫 개인 결제 링크는 거절하세요" : null;
    },
    proof_required: function (v) {
      return v ? "🔍 실물 인증을 꼭 요청하세요" : null;
    },
    private_contact_forbidden: function (v) {
      return v ? "☎️ 개인 연락처 요구는 거절하세요" : null;
    },
    evidence_based_response_required: function (v) {
      return v ? "🗂️ 감정적으로 대응하지 말고 근거/기록으로 답하세요" : null;
    },
    price_boundary_required: function (v) {
      return v ? "💰 정해둔 가격선을 지키세요" : null;
    },
  };

  function buildConstraintList(listEl, constraints) {
    listEl.innerHTML = "";
    Object.entries(constraints || {}).forEach(function (entry) {
      const key = entry[0];
      const value = entry[1];
      const fn = CONSTRAINT_LABELS[key];
      if (!fn) return; // 모르는 키는 조용히 건너뛴다
      const label = fn(value);
      if (!label) return;
      const li = document.createElement("li");
      li.className = "mission-constraint-item";
      li.textContent = label;
      listEl.appendChild(li);
    });
  }

  function rewardPreviewText(rewardPreview) {
    const rp = rewardPreview || {};
    const parts = [];
    if (rp.xp_bonus) parts.push("XP +" + rp.xp_bonus);
    if (rp.trust_bonus) parts.push("신뢰도 +" + rp.trust_bonus);
    if (rp.badge_name) parts.push("🏅 " + rp.badge_name);
    if (rp.item_bonus) parts.push("🎁 보너스 아이템");
    return parts.length ? "보상: " + parts.join(" · ") : "";
  }

  /* ---------- 미션 제안 오버레이 ---------- */
  function showOffer(mission) {
    offeredMission = mission;
    elTitle.textContent = mission.title || "새 미션";
    elSituation.textContent = mission.situation || "";
    buildConstraintList(elConstraints, mission.constraints);
    elRewardPreview.textContent = rewardPreviewText(mission.reward_preview);
    offerOverlay.classList.remove("hidden");
  }

  function hideOffer() {
    offerOverlay.classList.add("hidden");
    offeredMission = null;
  }

  async function acceptOffer() {
    if (!offeredMission) return;
    const missionKey = offeredMission.mission_key;
    const title = offeredMission.title;
    try {
      await API.game.acceptMission(missionKey);
      hideOffer();
      if (global.SafeDeal) SafeDeal.toast("🎯 '" + title + "' 미션을 수락했어요!");
      refreshActive();
    } catch (err) {
      if (global.SafeDeal) SafeDeal.toast((err && err.message) || "미션을 수락하지 못했어요.");
    }
  }

  acceptBtn.addEventListener("click", acceptOffer);
  skipBtn.addEventListener("click", hideOffer);
  closeBtn.addEventListener("click", hideOffer);
  offerOverlay.addEventListener("click", function (e) {
    if (e.target === offerOverlay) hideOffer();
  });

  /* ---------- HUD 미션 칩 + 상세 패널 ---------- */
  async function giveUpMission(missionId) {
    try {
      await API.game.skipMission(missionId);
      if (global.SafeDeal) SafeDeal.toast("미션을 포기했어요.");
    } catch (err) {
      if (global.SafeDeal) SafeDeal.toast((err && err.message) || "미션을 포기하지 못했어요.");
    }
    refreshActive();
  }

  function buildDetailPanel(mission) {
    detailBody.innerHTML = "";

    const situationP = document.createElement("p");
    situationP.textContent = mission.situation || "";
    detailBody.appendChild(situationP);

    const list = document.createElement("ul");
    list.className = "mission-constraint-list";
    buildConstraintList(list, mission.constraints);
    detailBody.appendChild(list);

    const rewardText = rewardPreviewText(mission.reward_preview);
    if (rewardText) {
      const rewardP = document.createElement("p");
      rewardP.className = "mission-reward-preview";
      rewardP.textContent = rewardText;
      detailBody.appendChild(rewardP);
    }

    const giveUpBtn = document.createElement("button");
    giveUpBtn.type = "button";
    giveUpBtn.id = "mission-give-up";
    giveUpBtn.className = "mission-give-up-btn";
    giveUpBtn.textContent = "미션 포기";
    giveUpBtn.addEventListener("click", function () {
      giveUpMission(mission.id);
    });
    detailBody.appendChild(giveUpBtn);
  }

  // 사이드 도크 열기/닫기 (칩 토글 라벨도 함께 갱신)
  function setPanelOpen(open) {
    detailPanel.classList.toggle("hidden", !open);
    hudToggle.classList.toggle("open", open);
    hudToggle.textContent = open ? "접기 ▴" : "펼치기 ▾";
    // 인벤토리 도크와 우측을 공유하므로 열 때 겹치지 않게 닫아준다
    if (open && global.SafeDealInventory && SafeDealInventory.close) SafeDealInventory.close();
  }
  function closePanel() { setPanelOpen(false); }

  function renderHud(mission) {
    if (!mission) {
      hudChip.classList.add("hidden");
      detailPanel.classList.add("hidden");
      detailBody.innerHTML = "";
      hudToggle.classList.remove("open");
      hudToggle.textContent = "펼치기 ▾";
      return;
    }
    hudChipText.textContent = "🎯 " + mission.title;
    hudChip.classList.remove("hidden");
    buildDetailPanel(mission);
  }

  hudToggle.addEventListener("click", function () {
    setPanelOpen(detailPanel.classList.contains("hidden"));
  });
  if (detailClose) detailClose.addEventListener("click", closePanel);

  /* ---------- 결과 모달: 미션 성공/실패 ---------- */
  function makeChip(text, kind) {
    const c = document.createElement("span");
    c.className = "reward-chip" + (kind ? " " + kind : "");
    c.textContent = text;
    return c;
  }

  function renderResult(missionResult) {
    if (!missionResult) {
      resultSection.classList.add("hidden");
      return;
    }
    resultSection.classList.remove("hidden");

    elOutcomeChip.innerHTML = "";
    const outcomeText =
      (missionResult.success ? "✅ 미션 성공" : "❌ 미션 실패") +
      " — " + (missionResult.title || "");
    elOutcomeChip.appendChild(makeChip(outcomeText, missionResult.success ? "up" : "down"));

    elReason.textContent = missionResult.reason || "";
    elLesson.textContent = missionResult.lesson ? "💡 " + missionResult.lesson : "";

    elBonusChips.innerHTML = "";
    if (missionResult.xp_bonus > 0) {
      elBonusChips.appendChild(makeChip("🎯 미션 보너스 XP +" + missionResult.xp_bonus, "up"));
    }
    if (missionResult.trust_bonus > 0) {
      elBonusChips.appendChild(makeChip("🎯 미션 보너스 신뢰도 +" + missionResult.trust_bonus, "up"));
    }
    if (missionResult.badge_gained) {
      elBonusChips.appendChild(makeChip("🏅 " + missionResult.badge_gained.name + " 획득!", "up"));
    }
    (missionResult.bonus_items || []).forEach(function (item) {
      elBonusChips.appendChild(makeChip("📦 " + item.name + " 추가 획득!", "up"));
    });
  }

  /* ---------- 공개 API ---------- */

  // 마을 입장/역할 전환 직후 호출: 활성 미션 HUD 갱신 + (없으면) 새 미션 제안.
  // 베스트에포트 — 실패해도 절대 던지지 않는다(게임 진입을 막으면 안 됨).
  async function checkAndOffer() {
    try {
      const data = await API.game.getMissions();
      renderHud(data.active || null);
      if (!data.active && data.suggested) {
        showOffer(data.suggested);
      } else {
        hideOffer();
      }
    } catch (err) {
      // 조용히 무시 — 미션 시스템은 부가 기능이라 게임 흐름을 막지 않는다.
    }
  }

  // 거래 종료 등으로 활성 미션이 바뀌었을 수 있을 때 HUD 만 다시 갱신.
  async function refreshActive() {
    try {
      const data = await API.game.getActiveMission();
      renderHud(data.mission || null);
    } catch (err) {
      // 조용히 무시
    }
  }

  global.SafeDealMissions = { checkAndOffer, refreshActive, renderResult, closePanel };
})(window);
