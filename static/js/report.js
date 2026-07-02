/* ============================================================
   report.js — 내 사기 방어 리포트 (개인 리포트 + before/after)
   투명성 원칙: 점수의 '근거'를 함께 보여주고, 훈련용 데모임을 명시한다.
   ============================================================ */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  const LEVEL_CLASS = { weak: "lv-weak", moderate: "lv-moderate", strong: "lv-strong", unknown: "lv-unknown" };
  const CONF_LABEL = {
    demo_low: "데모·낮음", demo_medium: "데모·보통", demo_high: "데모·높음",
    low: "낮음", medium: "보통", high: "높음",
  };

  function pick(obj, keys, dflt) {
    for (const k of keys) if (obj && obj[k] != null) return obj[k];
    return dflt;
  }

  /* 미션 추천(객체) + 일반 행동(문자열)을 표시용 문자열 배열로 합친다 */
  function normalizeActions(missions, actions) {
    const out = [];
    (missions || []).forEach((m) => {
      if (typeof m === "string") out.push(m);
      else if (m && (m.title || m.dimension_label)) {
        out.push("🎯 미션: " + (m.title || "") + (m.dimension_label ? " — " + m.dimension_label : ""));
      }
    });
    (actions || []).forEach((a) => { if (typeof a === "string") out.push(a); });
    return out;
  }

  async function renderPanel(el) {
    el.innerHTML = '<div class="platform-loading">리포트를 만드는 중…</div>';
    let personal = null, ba = null;
    try { personal = await API.report.personal(); } catch (e) { personal = { _error: e.message }; }
    try { ba = await API.report.beforeAfter(); } catch (_) { ba = null; }

    if (!personal || personal._error) {
      el.innerHTML = '<div class="platform-empty">리포트를 불러오지 못했어요.' +
        (personal && personal._error ? " (" + esc(personal._error) + ")" : "") + "</div>";
      return;
    }

    const rp = personal.risk_profile || {};
    const score = pick(personal, ["current_training_score", "overall_risk_score", "training_score", "score"],
      pick(rp, ["overall_risk_score"], 0));
    const conf = pick(personal, ["confidence"], pick(rp, ["confidence"], "demo_low"));
    const dims = pick(personal, ["risk_dimensions", "dimensions"], null) || rp.risk_dimensions || [];
    const strengths = pick(personal, ["strongest_skills", "strengths"], []);
    const weaknesses = pick(personal, ["weakest_skills", "weaknesses"], []);
    // 추천 다음 행동: 미션 추천(객체) + 일반 행동(문자열)을 하나의 문자열 배열로 정규화
    const actions = normalizeActions(
      pick(personal, ["recommended_next_missions"], []),
      pick(personal, ["recommended_next_actions"], [])
    );
    const explain = pick(personal, ["score_explanation", "explanation"], []);
    const disclaimer = pick(personal, ["disclaimer"], "이 점수는 방어 훈련용 데모 지표예요.");

    let html =
      '<div class="platform-section-head"><h3>📊 내 사기 방어 리포트</h3></div>' +
      '<div class="report-hero">' +
      '<div class="report-score-ring"><span class="report-score-num">' + esc(score) + '</span><span class="report-score-lbl">방어 점수</span></div>' +
      '<div class="report-hero-meta">' +
      '<span class="report-conf">신뢰도: ' + esc(CONF_LABEL[conf] || conf) + "</span>" +
      "<p>훈련 기록(진단·거래·미션)을 합쳐 계산한 <b>훈련 점수</b>예요. 높을수록 방어 역량이 강해요.</p>" +
      "</div></div>";

    // 강점/보완점
    html += '<div class="report-two-col">';
    html += '<div class="report-block"><h4>💪 강점</h4>' +
      (strengths.length ? '<ul class="report-ul good">' + strengths.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>"
        : '<p class="report-muted">아직 두드러진 강점 데이터가 부족해요.</p>') + "</div>";
    html += '<div class="report-block"><h4>🎯 보완점</h4>' +
      (weaknesses.length ? '<ul class="report-ul warn">' + weaknesses.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>"
        : '<p class="report-muted">보완점을 찾으려면 진단과 거래를 더 진행해 보세요.</p>') + "</div>";
    html += "</div>";

    // 위험 차원 레이더(막대 리스트) + 근거
    if (dims.length) {
      html += '<div class="report-block"><h4>🧭 위험 차원별 방어력 <span class="report-note">— 점수 근거를 함께 보여줘요</span></h4>';
      const sorted = dims.slice().sort((a, b) =>
        (a.score == null ? 999 : a.score) - (b.score == null ? 999 : b.score));
      html += sorted.map(dimRow).join("");
      html += "</div>";
    }

    // 왜 이 점수인가 (score explanation)
    if (explain && explain.length) {
      html += '<div class="report-block report-why"><h4>❓ 왜 ' + esc(score) + '점인가요?</h4><ul class="report-why-ul">' +
        explain.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>";
    }

    // 추천 다음 행동
    if (actions && actions.length) {
      html += '<div class="report-block"><h4>➡️ 추천 다음 행동</h4><ul class="report-actions">' +
        actions.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>";
    }

    // before/after
    html += '<div class="report-block" id="report-ba">' + renderBeforeAfter(ba) + "</div>";

    html += '<p class="platform-disclaimer2">' + esc(disclaimer) + "</p>";
    el.innerHTML = html;
  }

  function dimRow(d) {
    const lvl = d.level || "unknown";
    const cls = LEVEL_CLASS[lvl] || "";
    const ev = (d.evidence || []).map((e) => "<li>" + esc(e) + "</li>").join("");
    const rec = d.recommended_training ? '<div class="report-dim-rec">🧩 ' + esc(d.recommended_training) + "</div>" : "";
    return (
      '<div class="report-dim">' +
      '<div class="report-dim-head"><span class="report-dim-label">' + esc(d.label || d.key) + "</span>" +
      '<span class="report-dim-badge ' + cls + '">' + esc(d.level_label || lvl) + " · " +
      (d.score == null ? "—" : esc(d.score)) + "</span></div>" +
      '<div class="report-dim-bar"><div class="report-dim-fill ' + cls + '" style="width:' +
      (d.score == null ? 0 : d.score) + '%"></div></div>' +
      (ev ? '<ul class="report-dim-ev">' + ev + "</ul>" : "") +
      rec +
      "</div>"
    );
  }

  function renderBeforeAfter(ba) {
    if (!ba || ba.available === false || !ba.available) {
      const msg = (ba && ba.message) || "사전 진단과 훈련 후 진단을 모두 완료하면 개선도를 볼 수 있어요.";
      return "<h4>📈 훈련 전/후 개선도</h4><p class=\"report-muted\">" + esc(msg) + "</p>";
    }
    const base = ba.baseline_score, post = ba.post_score;
    const imp = ba.improvement != null ? ba.improvement : (post - base);
    const impCls = imp > 0 ? "good" : (imp < 0 ? "warn" : "");
    const dims = (ba.dimension_improvements || []).filter((d) => (d.delta || 0) !== 0);
    let html = "<h4>📈 훈련 전/후 개선도</h4>" +
      '<div class="ba-row">' +
      '<div class="ba-cell"><small>사전</small><b>' + esc(base) + "</b></div>" +
      '<div class="ba-arrow">→</div>' +
      '<div class="ba-cell"><small>훈련 후</small><b>' + esc(post) + "</b></div>" +
      '<div class="ba-delta ' + impCls + '">' + (imp > 0 ? "+" : "") + esc(imp) + "</div>" +
      "</div>";
    if (dims.length) {
      html += '<div class="ba-dims">' + dims.map((d) => {
        const dv = d.delta || 0;
        return '<div class="ba-dim"><span>' + esc(d.label || d.key) + "</span>" +
          '<span class="ba-dim-delta ' + (dv > 0 ? "good" : "warn") + '">' +
          esc(d.baseline_score) + " → " + esc(d.post_score) + " (" + (dv > 0 ? "+" : "") + esc(dv) + ")</span></div>";
      }).join("") + "</div>";
    }
    if (ba.recommended_next_step) {
      html += '<p class="report-actions-single">➡️ ' + esc(ba.recommended_next_step) + "</p>";
    }
    return html;
  }

  global.SafeDealReport = { renderPanel };
})(window);
