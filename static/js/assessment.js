/* ============================================================
   assessment.js — 사기 취약도 진단 (baseline / post_training / quick_check)
   허브의 "취약도 진단" 탭 + 문항 러너 오버레이(#assessment-overlay).
   ============================================================ */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function toast(m) { if (global.SafeDeal) SafeDeal.toast(m); }

  const overlay = document.getElementById("assessment-overlay");
  const bodyEl = document.getElementById("assess-body");
  const progText = document.getElementById("assess-progress-text");
  const fillEl = document.getElementById("assess-fill");

  const TYPE_LABELS = {
    baseline: "사전 진단 (baseline)",
    post_training: "훈련 후 진단 (post-training)",
    quick_check: "빠른 점검 (quick check)",
  };
  const LEVEL_CLASS = { weak: "lv-weak", moderate: "lv-moderate", strong: "lv-strong", unknown: "lv-unknown" };

  let state = null; // {sessionId, type, total, index, question}

  /* ---------- 탭 패널 ---------- */
  async function renderPanel(el) {
    el.innerHTML = '<div class="platform-loading">진단 정보를 불러오는 중…</div>';
    let latest = null;
    try { latest = await API.assessment.latest(); } catch (_) { latest = null; }

    let latestHtml = "";
    if (latest && latest.score != null) {
      latestHtml =
        '<div class="assess-latest">' +
        '<div class="assess-latest-score"><span>' + esc(latest.score) + '</span><small>점</small></div>' +
        '<div class="assess-latest-meta">' +
        "<b>" + esc(TYPE_LABELS[latest.assessment_type] || latest.assessment_type || "최근 진단") + "</b>" +
        "<p>가장 최근 완료한 진단 점수예요. (높을수록 방어 역량이 강함)</p>" +
        "</div></div>";
    } else {
      latestHtml = '<div class="assess-empty">아직 완료한 진단이 없어요. 사전 진단으로 시작해 보세요!</div>';
    }

    el.innerHTML =
      '<div class="platform-section-head"><h3>🧭 사기 취약도 진단</h3>' +
      '<p class="platform-note">여러 사기 유형 상황에서의 판단력을 측정해, 약한 위험 차원을 찾아 훈련을 개인화해요.</p></div>' +
      latestHtml +
      '<div class="assess-start-grid">' +
      '<button class="assess-start-btn primary" data-type="baseline">📋 사전 진단 시작<small>훈련 전 기준점 측정</small></button>' +
      '<button class="assess-start-btn" data-type="post_training">🔁 훈련 후 진단<small>개선도 비교용</small></button>' +
      '<button class="assess-start-btn" data-type="quick_check">⚡ 빠른 점검<small>짧게 5문항</small></button>' +
      "</div>" +
      '<p class="platform-hint">사전 진단 → 훈련(미션/거래) → 훈련 후 진단 순서로 하면 "내 리포트" 탭에서 개선도를 볼 수 있어요.</p>';

    el.querySelectorAll(".assess-start-btn").forEach((b) => {
      b.addEventListener("click", () => startAssessment(b.dataset.type));
    });
  }

  /* ---------- 러너 ---------- */
  async function startAssessment(type) {
    try {
      const data = await API.assessment.start(type);
      state = {
        sessionId: data.session_id,
        type: data.assessment_type || type,
        total: data.total_questions || 0,
        index: data.index || 0,
        question: data.question || null,
      };
      if (!state.question) { toast("진단 문항을 불러올 수 없어요."); return; }
      overlay.classList.remove("hidden");
      renderQuestion();
    } catch (err) {
      toast(err.message || "진단을 시작할 수 없어요.");
    }
  }

  function updateProgress() {
    const done = state.index;
    progText.textContent = "문항 " + Math.min(done + 1, state.total) + " / " + state.total;
    const pct = state.total ? Math.round((done / state.total) * 100) : 0;
    fillEl.style.width = pct + "%";
  }

  function renderQuestion() {
    updateProgress();
    const q = state.question;
    const opts = (q.options || [])
      .map((o) => '<button class="assess-opt" data-key="' + esc(o.key) + '">' +
        '<span class="assess-opt-key">' + esc((o.key || "").toUpperCase()) + "</span>" +
        '<span class="assess-opt-text">' + esc(o.text) + "</span></button>")
      .join("");
    bodyEl.innerHTML =
      '<div class="assess-q-cat">' + esc(catLabel(q.category)) + "</div>" +
      '<div class="assess-q-prompt">' + esc(q.prompt) + "</div>" +
      '<div class="assess-opts">' + opts + "</div>" +
      '<div class="assess-feedback hidden" id="assess-feedback"></div>';
    bodyEl.querySelectorAll(".assess-opt").forEach((b) => {
      b.addEventListener("click", () => submitAnswer(b.dataset.key, b));
    });
  }

  async function submitAnswer(key, btn) {
    bodyEl.querySelectorAll(".assess-opt").forEach((b) => (b.disabled = true));
    try {
      const res = await API.assessment.answer(state.sessionId, state.question.id, { key });
      // 정오답 시각화
      const correctKeys = res.correct_keys || [];
      bodyEl.querySelectorAll(".assess-opt").forEach((b) => {
        const k = b.dataset.key;
        if (correctKeys.indexOf(k) >= 0) b.classList.add("correct");
        else if (k === key) b.classList.add("wrong");
      });
      const fb = document.getElementById("assess-feedback");
      fb.classList.remove("hidden");
      fb.innerHTML =
        '<div class="assess-fb-verdict ' + (res.is_correct ? "ok" : "no") + '">' +
        (res.is_correct ? "✅ 안전한 판단이에요" : "⚠️ 더 안전한 대응이 있어요") + "</div>" +
        (res.explanation ? '<p class="assess-fb-explain">' + esc(res.explanation) + "</p>" : "") +
        '<button class="btn-primary assess-next" id="assess-next">' +
        (res.done ? "결과 보기" : "다음 문항") + "</button>";
      document.getElementById("assess-next").addEventListener("click", () => {
        if (res.done) {
          finishAssessment();
        } else {
          state.index = res.next_index != null ? res.next_index : state.index + 1;
          state.question = res.question;
          renderQuestion();
        }
      });
    } catch (err) {
      toast(err.message || "답변을 저장하지 못했어요.");
      bodyEl.querySelectorAll(".assess-opt").forEach((b) => (b.disabled = false));
    }
  }

  async function finishAssessment() {
    bodyEl.innerHTML = '<div class="platform-loading">결과를 계산하는 중…</div>';
    progText.textContent = "완료";
    fillEl.style.width = "100%";
    try {
      const r = await API.assessment.complete(state.sessionId);
      renderResult(r);
    } catch (err) {
      bodyEl.innerHTML = '<div class="assess-empty">결과를 불러오지 못했어요: ' + esc(err.message || "") + "</div>";
    }
  }

  function dimRow(d) {
    const lvl = d.level || "unknown";
    const score = d.score == null ? "—" : d.score;
    return (
      '<div class="assess-dim">' +
      '<div class="assess-dim-top"><span class="assess-dim-label">' + esc(d.label || d.key) + "</span>" +
      '<span class="assess-dim-badge ' + (LEVEL_CLASS[lvl] || "") + '">' + esc(d.level_label || lvl) + "</span></div>" +
      '<div class="assess-dim-bar"><div class="assess-dim-fill ' + (LEVEL_CLASS[lvl] || "") + '" style="width:' +
      (d.score == null ? 0 : d.score) + '%"></div></div>' +
      '<div class="assess-dim-sub">' + (d.correct != null ? esc(d.correct) + "/" + esc(d.total) + " 정답 · " : "") +
      esc(score) + "점</div>" +
      "</div>"
    );
  }

  function renderResult(r) {
    const dims = (r.dimension_scores || []).slice();
    // 약한 것부터
    dims.sort((a, b) => (a.score == null ? 999 : a.score) - (b.score == null ? 999 : b.score));
    const strong = (r.strengths || []);
    const weak = (r.weaknesses || []);
    const mods = (r.recommended_modules || []);
    bodyEl.innerHTML =
      '<div class="assess-result-top">' +
      '<div class="assess-result-score"><span>' + esc(r.score != null ? r.score : 0) + '</span><small>점</small></div>' +
      "<div><h3>" + esc(TYPE_LABELS[r.assessment_type] || "진단") + " 완료</h3>" +
      '<p class="assess-result-tag">' + esc(r.correct_count != null ? (r.correct_count + "/" + r.total_questions + " 정답") : "") +
      " · 높을수록 방어 역량이 강해요.</p></div></div>" +
      (strong.length ? '<div class="assess-res-block"><h4>💪 강한 영역</h4><div class="chip-row">' +
        strong.map((s) => '<span class="chip good">' + esc(s) + "</span>").join("") + "</div></div>" : "") +
      (weak.length ? '<div class="assess-res-block"><h4>🎯 보완할 영역</h4><div class="chip-row">' +
        weak.map((s) => '<span class="chip warn">' + esc(s) + "</span>").join("") + "</div></div>" : "") +
      '<div class="assess-res-block"><h4>📊 위험 차원별 점수</h4>' + dims.map(dimRow).join("") + "</div>" +
      (mods.length ? '<div class="assess-res-block"><h4>🧭 추천 훈련</h4><ul class="assess-mods">' +
        mods.map((m) => "<li>" + esc(m) + "</li>").join("") + "</ul></div>" : "") +
      '<p class="platform-disclaimer2">' + esc(r.disclaimer || "훈련용 데모 지표예요.") + "</p>" +
      '<button class="btn-primary" id="assess-done-close">내 리포트에서 자세히 보기</button>';
    document.getElementById("assess-done-close").addEventListener("click", () => {
      closeRunner();
      if (global.SafeDealPlatform) SafeDealPlatform.switchTab("report");
    });
  }

  function closeRunner() {
    overlay.classList.add("hidden");
    state = null;
  }

  const CAT_LABELS = (global.SafeDealPlatform && SafeDealPlatform.CATEGORY_LABELS) || {
    used_marketplace: "중고거래", voice_phishing: "보이스피싱", romance_scam: "로맨스스캠",
    side_job_scam: "부업사기", job_scam: "취업사기", investment_scam: "투자사기",
    account_takeover: "계정탈취", private_contact_boundary: "사적연락 경계",
    seller_refund_conflict: "환불분쟁", delivery_trade_safety: "택배거래",
  };
  function catLabel(c) {
    if (global.SafeDealPlatform && SafeDealPlatform.catLabel) return SafeDealPlatform.catLabel(c);
    return CAT_LABELS[c] || c || "기타";
  }

  document.getElementById("assess-close").addEventListener("click", () => {
    if (state && confirm("진단을 중단할까요? 지금까지의 답변은 저장돼 있어요.")) closeRunner();
    else if (!state) closeRunner();
  });

  global.SafeDealAssessment = { renderPanel, startAssessment };
})(window);
