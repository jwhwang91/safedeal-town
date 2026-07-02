/* ============================================================
   dashboard.js — 기관 / 코호트 데모 대시보드 (B2B/B2G 데모)
   학교·시니어센터·지자체·금융사가 훈련 성과를 '집계'로 보는 데모.
   원본 대화/개인 식별정보는 절대 노출하지 않고 집계 지표만 보여준다.
   ============================================================ */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function toast(m) { if (global.SafeDeal) SafeDeal.toast(m); }

  const ORG_TYPES = [
    ["school", "학교"], ["senior_center", "시니어센터"], ["local_gov", "지자체"],
    ["financial", "금융사"], ["other", "기타"],
  ];

  let selectedCohort = null;

  async function renderPanel(el) {
    el.innerHTML = '<div class="platform-loading">기관 데모를 불러오는 중…</div>';
    let list;
    try {
      list = await API.orgs.list();
    } catch (err) {
      if (err.status === 404) {
        el.innerHTML = '<div class="platform-empty">기관 대시보드가 비활성화되어 있어요. (ORG_DEMO_DASHBOARD_ENABLED)</div>';
      } else {
        el.innerHTML = '<div class="platform-empty">' + esc(err.message || "불러오기 실패") + "</div>";
      }
      return;
    }
    const orgs = (list && list.organizations) || (list && list.orgs) || list || [];

    let html =
      '<div class="platform-section-head"><h3>🏫 기관 리포트 데모</h3>' +
      '<p class="platform-note">학교·시니어센터·지자체·금융사가 코호트 훈련 성과를 <b>집계</b>로 보는 데모예요. ' +
      "개별 대화·개인정보는 표시하지 않아요.</p></div>";

    // 생성 폼
    html += '<div class="dash-create">' +
      '<input type="text" id="dash-name" maxlength="40" placeholder="기관/반 이름 (예: 행복초 6학년 2반)" />' +
      '<select id="dash-type">' + ORG_TYPES.map(([v, l]) => '<option value="' + v + '">' + esc(l) + "</option>").join("") + "</select>" +
      '<button class="btn-mini primary" id="dash-create-btn">데모 기관 만들기</button>' +
      "</div>";

    if (orgs.length) {
      html += '<div class="dash-cohorts" id="dash-cohorts">' +
        orgs.map(orgRow).join("") + "</div>";
    } else {
      html += '<div class="platform-empty">아직 기관이 없어요. 위에서 데모 기관을 만들어 현재 계정을 코호트에 넣어 보세요.</div>';
    }
    html += '<div class="dash-metrics" id="dash-metrics"></div>';
    el.innerHTML = html;

    el.querySelector("#dash-create-btn").addEventListener("click", async () => {
      const name = (el.querySelector("#dash-name").value || "").trim();
      const type = el.querySelector("#dash-type").value;
      if (!name) { toast("기관 이름을 입력해 주세요."); return; }
      try {
        const r = await API.orgs.createDemo(name, type);
        const cohort = r.cohort || (r.organization && r.organization.cohort);
        toast("데모 기관을 만들고 현재 계정을 코호트에 추가했어요.");
        selectedCohort = cohort ? cohort.id : null;
        renderPanel(el);
      } catch (e) { toast(e.message || "생성 실패"); }
    });

    el.querySelectorAll(".dash-cohort-btn").forEach((b) => {
      b.addEventListener("click", () => {
        selectedCohort = b.dataset.cohort;
        loadMetrics(el, selectedCohort);
      });
    });
    el.querySelectorAll(".dash-join-btn").forEach((b) => {
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          await API.orgs.addCurrentUser(b.dataset.cohort);
          toast("현재 계정을 코호트에 추가했어요.");
          renderPanel(el);
        } catch (err) { toast(err.message || "추가 실패"); }
      });
    });

    // 자동으로 첫 코호트 지표 로드
    const firstCohort = selectedCohort || firstCohortId(orgs);
    if (firstCohort) loadMetrics(el, firstCohort);
  }

  function firstCohortId(orgs) {
    for (const o of orgs) {
      const cs = o.cohorts || [];
      if (cs.length) return cs[0].id;
    }
    return null;
  }

  function orgRow(o) {
    const cohorts = (o.cohorts || []);
    const cohortBtns = cohorts.map((c) =>
      '<div class="dash-cohort-row">' +
      '<button class="dash-cohort-btn" data-cohort="' + esc(c.id) + '">📂 ' + esc(c.name) +
      ' <small>(' + esc(c.member_count != null ? c.member_count : 0) + "명)</small></button>" +
      '<button class="btn-mini dash-join-btn" data-cohort="' + esc(c.id) + '">+ 내 계정</button>' +
      "</div>").join("");
    return '<div class="dash-org"><div class="dash-org-head">🏢 ' + esc(o.name) +
      ' <span class="dash-org-type">' + esc(orgTypeLabel(o.org_type)) + "</span></div>" +
      cohortBtns + "</div>";
  }
  function orgTypeLabel(t) { return (ORG_TYPES.find((x) => x[0] === t) || [t, t])[1]; }

  async function loadMetrics(el, cohortId) {
    const box = el.querySelector("#dash-metrics");
    if (!box) return;
    box.innerHTML = '<div class="platform-loading">지표를 계산하는 중…</div>';
    let resp;
    try {
      resp = await API.orgs.dashboard(cohortId);
    } catch (err) {
      box.innerHTML = '<div class="platform-empty">' + esc(err.message || "지표 불러오기 실패") + "</div>";
      return;
    }
    const d = resp.cards || resp; // 지표는 cards 아래에 중첩됨 (구버전 호환 위해 폴백)
    const cards = [
      ["👥 인원", d.member_count != null ? d.member_count + "명" : "—"],
      ["📋 평균 사전점수", fmt(d.avg_baseline_score)],
      ["🎓 평균 최근점수", fmt(d.avg_latest_score)],
      ["📈 평균 개선도", fmtDelta(d.avg_improvement)],
      ["✅ 미션 완료율", d.mission_completion_rate != null ? Math.round(d.mission_completion_rate * 100) + "%" : "—"],
    ];
    const dimLabel = (x) => (x && typeof x === "object" ? (x.label || x.key) : x);
    const weak = (d.weakest_dimensions || []).map(dimLabel);
    const strong = (d.strongest_dimensions || []).map(dimLabel);
    const cats = d.scenario_categories_trained || [];
    const curr = d.recommended_next_curriculum || [];
    const footer = resp.disclaimer || resp.note || d.disclaimer;

    box.innerHTML =
      '<h4 class="dash-metrics-title">📊 코호트 성과 (집계)</h4>' +
      '<div class="dash-cards">' + cards.map((c) =>
        '<div class="dash-card"><div class="dash-card-val">' + esc(c[1]) + "</div><div class=\"dash-card-lbl\">" + esc(c[0]) + "</div></div>"
      ).join("") + "</div>" +
      '<div class="report-two-col">' +
      '<div class="report-block"><h4>💪 강한 차원</h4>' + chipList(strong, "good") + "</div>" +
      '<div class="report-block"><h4>🎯 약한 차원</h4>' + chipList(weak, "warn") + "</div>" +
      "</div>" +
      (cats.length ? '<div class="report-block"><h4>🎬 훈련된 카테고리</h4>' + chipList(cats.map(catLabel), "") + "</div>" : "") +
      (curr.length ? '<div class="report-block"><h4>🧭 추천 다음 커리큘럼</h4><ul class="report-actions">' +
        curr.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>" : "") +
      '<p class="platform-disclaimer2">' + esc(footer || "집계 데모 지표예요. 원본 대화·개인정보는 포함하지 않아요.") + "</p>";
  }

  function fmt(v) { return v == null ? "—" : Math.round(v) + "점"; }
  function fmtDelta(v) {
    if (v == null) return "—";
    const r = Math.round(v);
    return (r > 0 ? "+" : "") + r + "점";
  }
  function chipList(arr, cls) {
    if (!arr || !arr.length) return '<p class="report-muted">데이터가 아직 부족해요.</p>';
    return '<div class="chip-row">' + arr.map((s) => '<span class="chip ' + cls + '">' + esc(s) + "</span>").join("") + "</div>";
  }
  function catLabel(c) {
    if (global.SafeDealPlatform && SafeDealPlatform.catLabel) return SafeDealPlatform.catLabel(c);
    return c;
  }

  global.SafeDealDashboard = { renderPanel };
})(window);
