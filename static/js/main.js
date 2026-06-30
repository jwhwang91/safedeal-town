/* ============================================================
   main.js — 부트스트랩 & 화면 라우팅
   - 페이지 로딩 시 토큰이 있으면 자동 로그인 시도
   - 로그인 성공 → 월드 로드 → 게임 화면 진입
   - HUD 버튼(전적실/도움말/나가기) 연결
   - 토스트, HUD 갱신 같은 공용 유틸 제공
   ============================================================ */
(function (global) {
  "use strict";

  const authScreen = document.getElementById("auth-screen");
  const setupScreen = document.getElementById("setup-screen");
  const gameScreen = document.getElementById("game-screen");
  const helpOverlay = document.getElementById("help-overlay");
  const toastEl = document.getElementById("toast");

  /* ---------- 화면 전환 ---------- */
  function showScreen(name) {
    authScreen.classList.toggle("active", name === "auth");
    setupScreen.classList.toggle("active", name === "setup");
    gameScreen.classList.toggle("active", name === "game");
  }

  /* ---------- 토스트 ---------- */
  let toastTimer = null;
  function toast(message, ms) {
    toastEl.textContent = message;
    toastEl.classList.remove("hidden");
    // 재생성으로 애니메이션 다시 트리거
    void toastEl.offsetWidth;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.add("hidden");
    }, ms || 3200);
  }

  /* ---------- HUD ---------- */
  function updateHud(playerData) {
    if (!playerData) return;
    const lvl = playerData.level || 1;
    const xp = playerData.xp || 0;
    const trust = playerData.trust_score != null ? playerData.trust_score : 50;
    document.getElementById("hud-level").textContent = lvl;
    document.getElementById("hud-xp-text").textContent = xp;
    document.getElementById("hud-trust").textContent = trust;
    // 레벨 = 1 + xp//100  →  현재 레벨 안에서의 진행도
    const within = xp % 100;
    document.getElementById("hud-xp-fill").style.width = within + "%";
    if (playerData.coins != null) document.getElementById("hud-coins").textContent = playerData.coins;
    if (playerData.items != null) document.getElementById("hud-items").textContent = playerData.items;
    if (playerData.game_role) setRoleHud(playerData.game_role);
    // 마켓 요약(찾는 물건 / 내 판매글)은 /world 응답에만 들어온다. 있을 때만 갱신.
    if (playerData.market) setMarketHud(playerData.market, playerData.game_role || "buyer");
  }

  function setRoleHud(role) {
    const el = document.getElementById("hud-role");
    if (!el) return;
    if (role === "seller") {
      el.textContent = "🏪 판매자 모드";
      el.className = "hud-role seller";
    } else {
      el.textContent = "🛒 구매자 모드";
      el.className = "hud-role buyer";
    }
  }

  // HUD 마켓 바: 구매자=찾는 물건(카테고리), 판매자=내 판매글. 편집 버튼 라벨도 모드별.
  function setMarketHud(market, role) {
    const wrap = document.getElementById("hud-market");
    const txt = document.getElementById("hud-market-text");
    const btn = document.getElementById("btn-market-edit");
    if (!wrap || !txt || !btn) return;
    if (role === "seller") {
      const title = (market && market.seller_listing_title) || "판매글 미등록";
      txt.textContent = "🏪 내 판매글: " + title;
      btn.textContent = "판매글 수정";
    } else {
      const label = (market && market.buyer_category_label) || "전체";
      txt.textContent = "🔎 찾는 물건: " + label;
      btn.textContent = "검색 변경";
    }
    wrap.classList.remove("hidden");
  }

  // '검색 변경' / '판매글 수정' → 셋업 화면을 다시 연다 (카테고리/판매글 프리필).
  async function openMarketSetup() {
    try {
      const setup = await API.game.getSetup();
      SafeDealGame.setPaused(true);  // 셋업 입력 중 이동키가 먹지 않도록
      if (global.SafeDealSetup) SafeDealSetup.open(setup);
    } catch (err) {
      toast(err.message || "마켓 설정을 열 수 없어요.");
    }
  }

  /* ---------- 게임 진입 (셋업 미완료면 셋업 화면) ---------- */
  async function enterGame() {
    try {
      const setup = await API.game.getSetup();
      if (!setup.setup_completed) {
        if (global.SafeDealSetup) SafeDealSetup.open(setup);
        return;
      }
      await SafeDealGame.loadWorld(); // 내부에서 updateHud 호출
      showScreen("game");
      SafeDealGame.start();
    } catch (err) {
      // 토큰이 만료됐거나 서버 문제 → 인증 화면으로
      API.clearToken();
      showScreen("auth");
      if (global.SafeDealAuth) SafeDealAuth.resetAuthForms();
      toast(err.message || "다시 로그인해 주세요.");
      throw err;
    }
  }

  /* ---------- 로그아웃 ---------- */
  function logout() {
    API.auth.logout();
    SafeDealGame.reset();
    showScreen("auth");
    if (global.SafeDealAuth) SafeDealAuth.resetAuthForms();
    toast("마을에서 나왔어요. 또 들러주세요!");
  }

  /* ---------- 역할 전환 (게임 중) ---------- */
  let switchingRole = false;
  async function switchRole() {
    if (switchingRole) return;
    switchingRole = true;
    const roleEl = document.getElementById("hud-role");
    const cur = roleEl.classList.contains("seller") ? "seller" : "buyer";
    const next = cur === "seller" ? "buyer" : "seller";
    try {
      await API.game.setRole(next);
      await SafeDealGame.loadWorld(); // 새 역할의 NPC로 다시 채우고 HUD/배너 갱신
      toast(
        next === "seller"
          ? "🏪 판매자 모드로 전환! 찾아오는 구매자에 대응해 물건을 파세요."
          : "🛒 구매자 모드로 전환! 좋은 판매자를 찾아 안전하게 구매하세요."
      );
    } catch (err) {
      toast(err.message || "역할 전환에 실패했어요.");
    } finally {
      switchingRole = false;
    }
  }

  /* ---------- HUD 버튼 ---------- */
  document.getElementById("btn-role").addEventListener("click", switchRole);
  document.getElementById("btn-market-edit").addEventListener("click", openMarketSetup);
  document.getElementById("btn-record").addEventListener("click", () => {
    SafeDealChat.openRecord();
  });
  document.getElementById("btn-help").addEventListener("click", () => {
    helpOverlay.classList.remove("hidden");
  });
  document.getElementById("help-close").addEventListener("click", () => {
    helpOverlay.classList.add("hidden");
  });
  document.getElementById("btn-logout").addEventListener("click", logout);

  // 오버레이 바깥(어두운 영역) 클릭 시 닫기 — 전적실/도움말만.
  // (채팅·결과 모달은 실수로 닫히면 안 되니 제외)
  [helpOverlay, document.getElementById("record-overlay")].forEach((ov) => {
    ov.addEventListener("click", (e) => {
      if (e.target === ov) ov.classList.add("hidden");
    });
  });
  // ESC 로 전적실/도움말 닫기
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      helpOverlay.classList.add("hidden");
      document.getElementById("record-overlay").classList.add("hidden");
    }
  });

  /* ---------- 공개 유틸 ---------- */
  global.SafeDeal = { enterGame, updateHud, setRoleHud, toast, showScreen };

  /* ---------- 부팅 ---------- */
  async function boot() {
    if (API.hasToken()) {
      try {
        await API.auth.me(); // 토큰 유효성 확인
        await enterGame();
        return;
      } catch (_) {
        API.clearToken();
      }
    }
    showScreen("auth");
    if (global.SafeDealAuth) SafeDealAuth.resetAuthForms();
  }

  boot();
})(window);
