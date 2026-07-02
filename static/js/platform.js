/* ============================================================
   platform.js — 사기 방어 훈련·진단 플랫폼 허브
   HUD 의 "🛡️ 방어훈련" 버튼으로 열리는 탭형 오버레이.
   각 탭은 해당 모듈의 renderPanel(el) 로 지연 렌더한다.
   (진단 / 리포트 / 커뮤니티 / 시나리오 뱅크 / 기관 데모)
   ============================================================ */
(function (global) {
  "use strict";

  const overlay = document.getElementById("platform-overlay");
  const tabsEl = document.getElementById("platform-tabs");
  const panels = {
    assessment: document.getElementById("panel-assessment"),
    report: document.getElementById("panel-report"),
    community: document.getElementById("panel-community"),
    scenarios: document.getElementById("panel-scenarios"),
    dashboard: document.getElementById("panel-dashboard"),
  };

  /* 공용 유틸: HTML 이스케이프 (서버 텍스트는 비식별됐지만 XSS 방지로 항상 이스케이프) */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function toast(m) { if (global.SafeDeal) SafeDeal.toast(m); }

  let currentTab = "assessment";

  function open(tab) {
    if (global.SafeDealGame && SafeDealGame.setPaused) SafeDealGame.setPaused(true);
    overlay.classList.remove("hidden");
    switchTab(tab || currentTab || "assessment");
  }
  function close() {
    overlay.classList.add("hidden");
    if (global.SafeDealGame && SafeDealGame.setPaused) SafeDealGame.setPaused(false);
  }

  function switchTab(tab) {
    if (!panels[tab]) tab = "assessment";
    currentTab = tab;
    tabsEl.querySelectorAll(".platform-tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    Object.keys(panels).forEach((k) => {
      panels[k].classList.toggle("active", k === tab);
    });
    loadPanel(tab);
  }

  function loadingHtml(msg) {
    return '<div class="platform-loading">' + esc(msg || "불러오는 중…") + "</div>";
  }

  function loadPanel(tab) {
    const el = panels[tab];
    if (!el) return;
    el.innerHTML = loadingHtml();
    try {
      if (tab === "assessment" && global.SafeDealAssessment) {
        SafeDealAssessment.renderPanel(el);
      } else if (tab === "report" && global.SafeDealReport) {
        SafeDealReport.renderPanel(el);
      } else if (tab === "community" && global.SafeDealCommunity) {
        SafeDealCommunity.renderPanel(el);
      } else if (tab === "scenarios") {
        renderScenarios(el);
      } else if (tab === "dashboard" && global.SafeDealDashboard) {
        SafeDealDashboard.renderPanel(el);
      } else {
        el.innerHTML = '<div class="platform-empty">이 패널을 불러올 수 없어요.</div>';
      }
    } catch (err) {
      el.innerHTML = '<div class="platform-empty">문제가 생겼어요: ' + esc(err.message || err) + "</div>";
    }
  }

  /* ---------- 시나리오 뱅크 탭 (검색 + 추천) ---------- */
  const CATEGORY_LABELS = {
    used_marketplace: "중고거래", voice_phishing: "보이스피싱", romance_scam: "로맨스스캠",
    side_job_scam: "부업사기", job_scam: "취업사기", investment_scam: "투자사기",
    account_takeover: "계정탈취", private_contact_boundary: "사적연락 경계",
    seller_refund_conflict: "환불분쟁", delivery_trade_safety: "택배거래",
  };
  function catLabel(c) { return CATEGORY_LABELS[c] || c || "기타"; }

  function scenarioCardHtml(s) {
    const flags = (s.red_flags || []).map((f) => "<li>🚩 " + esc(f) + "</li>").join("");
    const counters = (s.safe_counters || []).map((c) => "<li>🛡️ " + esc(c) + "</li>").join("");
    return (
      '<div class="scn-card">' +
      '<div class="scn-card-head"><span class="scn-tag">' + esc(catLabel(s.category)) + "</span>" +
      '<span class="scn-diff">' + esc(s.difficulty || "medium") + "</span></div>" +
      "<h4>" + esc(s.title) + "</h4>" +
      '<p class="scn-summary">' + esc(s.scenario_summary || "") + "</p>" +
      (flags ? '<div class="scn-sub">위험 신호</div><ul class="scn-list">' + flags + "</ul>" : "") +
      (counters ? '<div class="scn-sub">안전한 대응</div><ul class="scn-list">' + counters + "</ul>" : "") +
      "</div>"
    );
  }

  async function renderScenarios(el) {
    el.innerHTML =
      '<div class="platform-section-head"><h3>🎬 방어 시나리오 뱅크</h3>' +
      '<p class="platform-note">비식별·픽션화된 방어 훈련 시나리오예요. 실제 개인정보나 사기 절차는 담기지 않아요.</p></div>' +
      '<div class="scn-search-row">' +
      '<input type="text" id="scn-q" placeholder="키워드 검색 (예: 외부 링크, 택배)" />' +
      '<button class="btn-mini" id="scn-search-btn">검색</button>' +
      '<button class="btn-mini alt" id="scn-recommend-btn">내 약점 추천</button>' +
      "</div>" +
      '<div id="scn-results">' + loadingHtml() + "</div>";

    const results = el.querySelector("#scn-results");
    async function doSearch(q) {
      results.innerHTML = loadingHtml();
      try {
        const data = await API.scenarios.search(q || "");
        const list = (data && data.scenarios) || data || [];
        results.innerHTML = list.length
          ? list.map(scenarioCardHtml).join("")
          : '<div class="platform-empty">시나리오가 없어요. 커뮤니티 사례를 시나리오로 변환해 보세요.</div>';
      } catch (err) {
        results.innerHTML = '<div class="platform-empty">' + esc(err.message || "검색 실패") + "</div>";
      }
    }
    async function doRecommend() {
      results.innerHTML = loadingHtml("내 약점 기반 추천을 찾는 중…");
      try {
        const data = await API.scenarios.recommend();
        const list = (data && data.scenarios) || data || [];
        results.innerHTML = list.length
          ? '<div class="scn-reco-note">🎯 내 약한 위험 차원에 맞춘 추천이에요.</div>' + list.map(scenarioCardHtml).join("")
          : '<div class="platform-empty">아직 추천할 시나리오가 없어요. 진단을 먼저 완료해 보세요.</div>';
      } catch (err) {
        results.innerHTML = '<div class="platform-empty">' + esc(err.message || "추천 실패") + "</div>";
      }
    }
    el.querySelector("#scn-search-btn").addEventListener("click", () => doSearch(el.querySelector("#scn-q").value));
    el.querySelector("#scn-q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(e.target.value); });
    el.querySelector("#scn-recommend-btn").addEventListener("click", doRecommend);
    doSearch("");
  }

  /* ---------- 이벤트 바인딩 ---------- */
  tabsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".platform-tab");
    if (btn) switchTab(btn.dataset.tab);
  });
  document.getElementById("platform-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) close();
  });

  global.SafeDealPlatform = {
    open, close, switchTab,
    reload: () => loadPanel(currentTab),
    esc, toast, catLabel, CATEGORY_LABELS,
  };
})(window);
