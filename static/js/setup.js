/* ============================================================
   setup.js — 입장 전 역할/아바타/카테고리 설정 화면
   - 역할: 구매자 / 판매자
   - 아바타: 피부/모자/상의/하의/액세서리
   - 판매자면 판매 카테고리
   - (선택) 대략 위치로 마을 시드 만들기
   저장은 /api/game/setup, 위치는 /api/game/location.
   ============================================================ */
(function (global) {
  "use strict";

  const screen = document.getElementById("setup-screen");
  const previewCanvas = document.getElementById("avatar-canvas");
  const controlsEl = document.getElementById("avatar-controls");
  const catBlock = document.getElementById("category-block");
  const catChoices = document.getElementById("cat-choices");
  const msgEl = document.getElementById("setup-msg");
  const saveBtn = document.getElementById("setup-save");
  const geoOptin = document.getElementById("geo-optin");
  const roleBtns = document.querySelectorAll(".role-btn");

  const GROUP_LABELS = {
    skin: "피부", shirt: "상의", pants: "하의", hat: "모자", accessory: "액세서리",
  };
  const COLOR_GROUPS = { skin: "SKIN", shirt: "SHIRT", pants: "PANTS" };
  const CATS = [
    { key: "electronics", label: "전자제품", icon: "📱" },
    { key: "camping", label: "캠핑", icon: "⛺" },
    { key: "beauty", label: "뷰티", icon: "💄" },
    { key: "home", label: "생활/가구", icon: "🛋️" },
    { key: "fashion", label: "패션", icon: "👕" },
    { key: "books", label: "도서", icon: "📚" },
    { key: "general", label: "잡화", icon: "📦" },
  ];

  let state = {
    game_role: "buyer",
    avatar: Object.assign({}, SafeDealAvatar.DEFAULT_AVATAR),
    seller_category: "electronics",
  };

  /* ---------- 미리보기 ---------- */
  function drawPreview() {
    const ctx = previewCanvas.getContext("2d");
    ctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
    // 부드러운 배경 원
    ctx.fillStyle = "#f0e3cc";
    ctx.beginPath();
    ctx.ellipse(60, 80, 46, 52, 0, 0, Math.PI * 2);
    ctx.fill();
    SafeDealAvatar.draw(ctx, 60, 78, state.avatar, { scale: 2.1, facing: "down" });
  }

  /* ---------- 아바타 컨트롤 만들기 ---------- */
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

  /* ---------- 카테고리 만들기 ---------- */
  function buildCategories() {
    catChoices.innerHTML = "";
    CATS.forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cat-btn" + (state.seller_category === c.key ? " active" : "");
      b.dataset.key = c.key;
      b.innerHTML = '<span class="cat-icon">' + c.icon + "</span>" + c.label;
      b.addEventListener("click", () => {
        state.seller_category = c.key;
        catChoices.querySelectorAll(".cat-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
      });
      catChoices.appendChild(b);
    });
  }

  /* ---------- 역할 ---------- */
  function applyRole(role) {
    state.game_role = role;
    roleBtns.forEach((b) => b.classList.toggle("active", b.dataset.role === role));
    catBlock.style.display = role === "seller" ? "" : "none";
  }
  roleBtns.forEach((b) =>
    b.addEventListener("click", () => applyRole(b.dataset.role))
  );

  /* ---------- 위치 (선택) ---------- */
  function tryGeolocate() {
    return new Promise((resolve) => {
      if (!geoOptin.checked || !navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        // 정밀 좌표는 기기 밖으로 내보내지 않는다 — 보내기 전에 소수 2자리(약 1km)로 반올림.
        (pos) => resolve({
          lat: Math.round(pos.coords.latitude * 100) / 100,
          lng: Math.round(pos.coords.longitude * 100) / 100,
        }),
        () => resolve(null), // 거부/실패 → 그냥 절차적 맵
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
      if (state.game_role === "seller") payload.seller_category = state.seller_category;
      await API.game.saveSetup(payload);

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
  function open(prefill) {
    if (prefill) {
      if (prefill.game_role) state.game_role = prefill.game_role;
      if (prefill.avatar) state.avatar = Object.assign({}, SafeDealAvatar.DEFAULT_AVATAR, prefill.avatar);
      if (prefill.seller_category) state.seller_category = prefill.seller_category;
    }
    applyRole(state.game_role);
    buildControls();
    buildCategories();
    drawPreview();
    setMsg("", null);
    saveBtn.disabled = false;
    SafeDeal.showScreen("setup");
  }

  global.SafeDealSetup = { open };
})(window);
