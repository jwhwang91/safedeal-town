/* ============================================================
   setup.js — 입장 전 역할/아바타/위시리스트/판매글 설정 화면
   - 역할: 구매자 / 판매자
   - 아바타: 피부/모자/상의/하의/액세서리
   - 구매자: '오늘 찾는 물건'(카테고리/가격민감도/거래방식)  → listing_setup.js
   - 판매자: '내 판매글'(상품/상태/가격/구성품/하자/증거)      → listing_setup.js
   - (선택) 대략 위치로 마을 시드 만들기
   저장: /api/game/setup + /api/game/preferences 또는 /api/game/listing, 위치는 /location.
   ============================================================ */
(function (global) {
  "use strict";

  const previewCanvas = document.getElementById("avatar-canvas");
  const controlsEl = document.getElementById("avatar-controls");
  const buyerBlock = document.getElementById("buyer-wishlist-block");
  const sellerBlock = document.getElementById("seller-listing-block");
  const buyerWishlistEl = document.getElementById("buyer-wishlist");
  const sellerListingEl = document.getElementById("seller-listing");
  const msgEl = document.getElementById("setup-msg");
  const saveBtn = document.getElementById("setup-save");
  const geoOptin = document.getElementById("geo-optin");
  const roleBtns = document.querySelectorAll(".role-btn");

  const GROUP_LABELS = {
    skin: "피부", shirt: "상의", pants: "하의", hat: "모자", accessory: "액세서리",
  };
  const COLOR_GROUPS = { skin: "SKIN", shirt: "SHIRT", pants: "PANTS" };

  let state = {
    game_role: "buyer",
    avatar: Object.assign({}, SafeDealAvatar.DEFAULT_AVATAR),
    preferences: null,
    panelsBuilt: false,
  };

  /* ---------- 미리보기 ---------- */
  function drawPreview() {
    const ctx = previewCanvas.getContext("2d");
    ctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
    ctx.fillStyle = "#f0e3cc";
    ctx.beginPath();
    ctx.ellipse(60, 80, 46, 52, 0, 0, Math.PI * 2);
    ctx.fill();
    SafeDealAvatar.draw(ctx, 60, 78, state.avatar, { scale: 2.1, facing: "down" });
  }

  /* ---------- 아바타 컨트롤 ---------- */
  function buildControls() {
    controlsEl.innerHTML = "";
    Object.keys(GROUP_LABELS).forEach((group) => {
      const row = document.createElement("div");
      row.className = "ctrl-row";
      const lbl = document.createElement("span");
      lbl.className = "ctrl-label";
      lbl.textContent = GROUP_LABELS[group];
      row.appendChild(lbl);

      const swatches = document.createElement("div");
      swatches.className = "swatches";
      SafeDealAvatar.OPTIONS[group].forEach((opt) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "swatch" + (state.avatar[group] === opt.key ? " active" : "");
        b.dataset.group = group;
        b.dataset.key = opt.key;
        if (COLOR_GROUPS[group]) {
          b.style.background = SafeDealAvatar[COLOR_GROUPS[group]][opt.key] || "#ccc";
          b.title = opt.label;
        } else {
          b.textContent = opt.label;
          b.classList.add("swatch-text");
        }
        b.addEventListener("click", () => {
          state.avatar[group] = opt.key;
          swatches.querySelectorAll(".swatch").forEach((s) => s.classList.remove("active"));
          b.classList.add("active");
          drawPreview();
        });
        swatches.appendChild(b);
      });
      row.appendChild(swatches);
      controlsEl.appendChild(row);
    });
  }

  /* ---------- 위시리스트 / 판매글 패널 ---------- */
  async function ensureCatalog() {
    if (SafeDealListingSetup.hasCatalog()) return true;
    try {
      const meta = await API.game.catalog();
      SafeDealListingSetup.setCatalog(meta);
      return true;
    } catch (_) {
      return false;
    }
  }

  function buildPanels() {
    const prefs = state.preferences || {};
    SafeDealListingSetup.buildBuyer(buyerWishlistEl, prefs);
    SafeDealListingSetup.buildSeller(sellerListingEl, prefs.seller_listing || {});
    state.panelsBuilt = true;
  }

  /* ---------- 역할 ---------- */
  function applyRole(role) {
    state.game_role = role;
    roleBtns.forEach((b) => b.classList.toggle("active", b.dataset.role === role));
    buyerBlock.style.display = role === "seller" ? "none" : "";
    sellerBlock.style.display = role === "seller" ? "" : "none";
  }
  roleBtns.forEach((b) =>
    b.addEventListener("click", () => applyRole(b.dataset.role))
  );

  /* ---------- 위치 (선택) ---------- */
  function tryGeolocate() {
    return new Promise((resolve) => {
      if (!geoOptin.checked || !navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({
          lat: Math.round(pos.coords.latitude * 100) / 100,
          lng: Math.round(pos.coords.longitude * 100) / 100,
        }),
        () => resolve(null),
        { timeout: 6000, maximumAge: 600000 }
      );
    });
  }

  /* ---------- 저장 ---------- */
  function setMsg(t, kind) {
    msgEl.textContent = t || "";
    msgEl.className = "setup-msg" + (kind ? " " + kind : "");
  }

  async function save() {
    saveBtn.disabled = true;
    setMsg("저장하는 중...", null);
    try {
      const payload = { game_role: state.game_role, avatar: state.avatar };
      if (state.game_role === "seller") {
        // 판매글 카테고리를 부스 카테고리로 환원하는 건 백엔드가 한다.
        payload.seller_category = SafeDealListingSetup.getSeller().category;
      }
      await API.game.saveSetup(payload);

      // 역할별 추가 저장 (위시리스트 / 판매글)
      if (state.game_role === "seller") {
        await API.game.saveListing(SafeDealListingSetup.getSeller());
      } else {
        await API.game.savePreferences(SafeDealListingSetup.getBuyer());
      }

      // 위치 동의 시 대략 좌표로 맵 시드 갱신 (거부해도 진행)
      const geo = await tryGeolocate();
      if (geo) {
        try {
          await API.game.setLocation({ lat: geo.lat, lng: geo.lng });
        } catch (_) { /* 위치 저장 실패해도 게임은 진행 */ }
      }

      setMsg("완료! 마을로 들어갑니다...", "success");
      await SafeDeal.enterGame();
    } catch (err) {
      setMsg(err.message || "저장에 실패했어요.", "error");
      saveBtn.disabled = false;
    }
  }
  saveBtn.addEventListener("click", save);

  /* ---------- 열기 (main.js 가 호출) ---------- */
  async function open(prefill) {
    if (prefill) {
      if (prefill.game_role) state.game_role = prefill.game_role;
      if (prefill.avatar) state.avatar = Object.assign({}, SafeDealAvatar.DEFAULT_AVATAR, prefill.avatar);
      if (prefill.preferences) state.preferences = prefill.preferences;
    }
    SafeDeal.showScreen("setup");
    buildControls();
    drawPreview();
    setMsg("", null);
    saveBtn.disabled = false;

    const ok = await ensureCatalog();
    if (ok) {
      buildPanels();
    } else {
      setMsg("카탈로그를 불러오지 못했어요. 기본값으로 진행됩니다.", "error");
    }
    applyRole(state.game_role);
  }

  global.SafeDealSetup = { open };
})(window);
