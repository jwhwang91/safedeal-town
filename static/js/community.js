/* ============================================================
   community.js — 피해 사례 공유 MVP
   사례 목록 / 상세(댓글·공감) / 작성(비식별 안내) / 사례→시나리오 변환.
   저장 전 서버가 자동 비식별(redaction)하므로, 화면에 뜨는 본문은 이미 가려진 상태.
   ============================================================ */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function toast(m) { if (global.SafeDeal) SafeDeal.toast(m); }

  const CATEGORIES = [
    "used_marketplace", "voice_phishing", "romance_scam", "side_job_scam", "job_scam",
    "investment_scam", "account_takeover", "private_contact_boundary",
    "seller_refund_conflict", "delivery_trade_safety",
  ];
  const CAT_LABELS = {
    used_marketplace: "중고거래", voice_phishing: "보이스피싱", romance_scam: "로맨스스캠",
    side_job_scam: "부업사기", job_scam: "취업사기", investment_scam: "투자사기",
    account_takeover: "계정탈취", private_contact_boundary: "사적연락 경계",
    seller_refund_conflict: "환불분쟁", delivery_trade_safety: "택배거래",
  };
  const LOSS_RANGES = [
    ["none", "피해 없음"], ["under_100k", "10만원 미만"], ["100k_500k", "10~50만원"],
    ["500k_1m", "50~100만원"], ["over_1m", "100만원 이상"], ["undisclosed", "비공개"],
  ];
  const LOSS_LABEL = Object.fromEntries(LOSS_RANGES);
  function catLabel(c) { return CAT_LABELS[c] || c || "기타"; }

  const detailOverlay = document.getElementById("case-detail-overlay");
  const detailBody = document.getElementById("case-detail-body");
  const detailTitle = document.getElementById("case-detail-title");
  const submitOverlay = document.getElementById("case-submit-overlay");
  const submitBody = document.getElementById("case-submit-body");

  let filterCategory = "";

  /* ---------- 목록 패널 ---------- */
  async function renderPanel(el) {
    el.innerHTML = '<div class="platform-loading">사례를 불러오는 중…</div>';
    let data;
    try {
      data = await API.community.listCases(filterCategory || null);
    } catch (err) {
      if (err.status === 404) {
        el.innerHTML = '<div class="platform-empty">커뮤니티 기능이 비활성화되어 있어요. (COMMUNITY_CASES_ENABLED)</div>';
      } else {
        el.innerHTML = '<div class="platform-empty">' + esc(err.message || "불러오기 실패") + "</div>";
      }
      return;
    }
    const cases = (data && data.cases) || data || [];
    const catOptions = '<option value="">전체 유형</option>' +
      CATEGORIES.map((c) => '<option value="' + c + '"' + (c === filterCategory ? " selected" : "") + ">" +
        esc(catLabel(c)) + "</option>").join("");

    el.innerHTML =
      '<div class="platform-section-head"><h3>🗣️ 피해 사례 공유</h3>' +
      '<p class="platform-note">비슷한 경험을 나누고, 위험 신호를 함께 배워요. 올린 글은 자동 비식별 처리돼요.</p></div>' +
      '<div class="comm-toolbar">' +
      '<select id="comm-filter">' + catOptions + "</select>" +
      '<button class="btn-mini primary" id="comm-new">✍️ 사례 나누기</button>' +
      "</div>" +
      '<div class="comm-list" id="comm-list">' +
      (cases.length ? cases.map(caseCardHtml).join("") : '<div class="platform-empty">아직 등록된 사례가 없어요. 첫 사례를 나눠 주세요.</div>') +
      "</div>";

    el.querySelector("#comm-filter").addEventListener("change", (e) => {
      filterCategory = e.target.value;
      renderPanel(el);
    });
    el.querySelector("#comm-new").addEventListener("click", () => openSubmit(el));
    el.querySelectorAll(".comm-card").forEach((c) => {
      c.addEventListener("click", () => openDetail(c.dataset.id));
    });
  }

  function caseCardHtml(c) {
    const signals = (c.risk_signals || []).slice(0, 3)
      .map((s) => '<span class="comm-signal">' + esc(signalLabel(s)) + "</span>").join("");
    return (
      '<div class="comm-card" data-id="' + esc(c.id) + '">' +
      '<div class="comm-card-head"><span class="comm-tag">' + esc(catLabel(c.category)) + "</span>" +
      (c.loss_amount_range ? '<span class="comm-loss">' + esc(LOSS_LABEL[c.loss_amount_range] || c.loss_amount_range) + "</span>" : "") +
      (c.status && c.status !== "approved" ? '<span class="comm-status">검토중</span>' : "") + "</div>" +
      "<h4>" + esc(c.title) + "</h4>" +
      '<p class="comm-preview">' + esc(truncate(c.body, 90)) + "</p>" +
      (signals ? '<div class="comm-signals">' + signals + "</div>" : "") +
      '<div class="comm-card-foot"><span>👍 ' + esc(c.reaction_count || 0) + "</span>" +
      "<span>💬 " + esc(c.comment_count || 0) + "</span></div>" +
      "</div>"
    );
  }

  function truncate(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n) + "…" : s;
  }
  const SIGNAL_LABELS = {
    private_contact: "사적 연락 유도", external_link: "외부 링크", account_transfer: "계좌 이체",
    off_platform_contact: "플랫폼 밖 연락", identity_exposure: "신원 노출", credential_exposure: "인증정보 노출",
  };
  function signalLabel(s) { return SIGNAL_LABELS[s] || s; }

  /* ---------- 상세 ---------- */
  async function openDetail(caseId) {
    detailOverlay.classList.remove("hidden");
    detailBody.innerHTML = '<div class="platform-loading">불러오는 중…</div>';
    let data;
    try {
      data = await API.community.getCase(caseId);
    } catch (err) {
      detailBody.innerHTML = '<div class="platform-empty">' + esc(err.message || "불러오기 실패") + "</div>";
      return;
    }
    const c = (data && data.case) || data || {};
    detailTitle.textContent = c.title || "피해 사례";
    const comments = (data.comments || c.comments || []);
    const reacted = data.reacted || c.reacted;
    const signals = (c.risk_signals || []).map((s) => '<span class="comm-signal">' + esc(signalLabel(s)) + "</span>").join("");

    detailBody.innerHTML =
      '<div class="comm-detail-meta"><span class="comm-tag">' + esc(catLabel(c.category)) + "</span>" +
      (c.platform ? '<span class="comm-plat">' + esc(c.platform) + "</span>" : "") +
      (c.loss_amount_range ? '<span class="comm-loss">' + esc(LOSS_LABEL[c.loss_amount_range] || c.loss_amount_range) + "</span>" : "") +
      "</div>" +
      (signals ? '<div class="comm-signals">' + signals + "</div>" : "") +
      '<div class="comm-detail-body">' + esc(c.body || "").replace(/\n/g, "<br>") + "</div>" +
      '<div class="comm-detail-actions">' +
      '<button class="btn-mini ' + (reacted ? "alt" : "primary") + '" id="comm-react">👍 나도 비슷했어요 (' + esc(c.reaction_count || 0) + ")</button>" +
      '<button class="btn-mini" id="comm-to-scn">🎬 방어 시나리오로 변환</button>' +
      '<button class="btn-mini danger" id="comm-report">🚩 신고</button>' +
      "</div>" +
      '<div class="comm-comments"><h4>💬 댓글</h4><div id="comm-comment-list">' +
      (comments.length ? comments.map(commentHtml).join("") : '<p class="report-muted">첫 댓글을 남겨보세요.</p>') +
      "</div>" +
      '<div class="comm-comment-form"><input type="text" id="comm-comment-input" maxlength="400" placeholder="따뜻한 조언·경험을 남겨주세요 (자동 비식별)" />' +
      '<button class="btn-mini primary" id="comm-comment-send">등록</button></div></div>';

    document.getElementById("comm-react").addEventListener("click", async () => {
      try {
        const r = await API.community.react(caseId, "me_too");
        const cnt = r.reaction_count != null ? r.reaction_count : (c.reaction_count || 0);
        document.getElementById("comm-react").textContent = "👍 나도 비슷했어요 (" + cnt + ")";
      } catch (e) { toast(e.message || "실패"); }
    });
    document.getElementById("comm-to-scn").addEventListener("click", () => convertToScenario(caseId));
    document.getElementById("comm-report").addEventListener("click", async () => {
      const reason = prompt("신고 사유를 적어주세요 (예: 개인정보 노출, 부적절한 내용)");
      if (!reason) return;
      try { await API.community.report(caseId, reason); toast("신고가 접수됐어요."); }
      catch (e) { toast(e.message || "신고 실패"); }
    });
    document.getElementById("comm-comment-send").addEventListener("click", () => sendComment(caseId));
    document.getElementById("comm-comment-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendComment(caseId);
    });
  }

  function commentHtml(cm) {
    return '<div class="comm-comment' + (cm.status === "hidden" ? " hidden-c" : "") + '">' +
      (cm.status === "hidden" ? "⚠️ 검토 대기 중인 댓글" : esc(cm.redacted_comment || cm.comment || "")) + "</div>";
  }

  async function sendComment(caseId) {
    const input = document.getElementById("comm-comment-input");
    const text = (input.value || "").trim();
    if (!text) return;
    input.disabled = true;
    try {
      await API.community.comment(caseId, text);
      openDetail(caseId); // 새로고침
    } catch (e) {
      toast(e.message || "댓글 등록 실패");
      input.disabled = false;
    }
  }

  async function convertToScenario(caseId) {
    toast("사례를 방어 시나리오로 변환하는 중…");
    try {
      const r = await API.scenarios.fromCase(caseId);
      const scn = (r && r.scenario) || r || {};
      const review = r && (r.requires_review || (scn.status && scn.status !== "approved"));
      detailBody.insertAdjacentHTML("afterbegin",
        '<div class="comm-scn-made">✅ 방어 시나리오가 생성됐어요: <b>' + esc(scn.title || "새 시나리오") + "</b>" +
        (review ? " <span class=\"comm-status\">검토 후 훈련에 반영</span>" : "") +
        ' <span class="report-muted">(원문은 복제되지 않고 위험 패턴만 추출·픽션화돼요)</span></div>');
    } catch (e) {
      toast(e.message || "변환 실패");
    }
  }

  /* ---------- 작성 ---------- */
  function openSubmit(panelEl) {
    submitOverlay.classList.remove("hidden");
    const catOpts = CATEGORIES.map((c) => '<option value="' + c + '">' + esc(catLabel(c)) + "</option>").join("");
    const lossOpts = LOSS_RANGES.map(([v, l]) => '<option value="' + v + '">' + esc(l) + "</option>").join("");
    submitBody.innerHTML =
      '<div class="case-warn">🔒 개인정보는 자동으로 가려지지만, 실명·계좌번호·연락처는 직접 적지 않는 것을 권장합니다.</div>' +
      '<label>제목<input type="text" id="cs-title" maxlength="80" placeholder="예: 택배거래 중 외부 링크로 결제를 유도당함" /></label>' +
      '<div class="case-form-row"><label>사기 유형<select id="cs-category">' + catOpts + "</select></label>" +
      '<label>피해 규모<select id="cs-loss">' + lossOpts + "</select></label></div>" +
      '<label>플랫폼 <span class="hint">선택</span><input type="text" id="cs-platform" maxlength="30" placeholder="예: 중고거래앱, 문자, SNS" /></label>' +
      '<label>무슨 일이 있었나요?<textarea id="cs-happened" maxlength="2000" rows="4" placeholder="상황을 시간 순서로 적어주세요 (연락처·계좌·링크는 자동으로 가려져요)"></textarea></label>' +
      '<label>나중에 수상했던 점 <span class="hint">선택</span><textarea id="cs-suspicious" maxlength="800" rows="2"></textarea></label>' +
      '<label>이렇게 했더라면 <span class="hint">선택</span><textarea id="cs-wish" maxlength="800" rows="2"></textarea></label>' +
      '<button class="btn-primary" id="cs-submit">비식별 처리 후 공유하기</button>' +
      '<p class="case-submit-msg" id="cs-msg"></p>';

    document.getElementById("cs-submit").addEventListener("click", async () => {
      const payload = {
        title: (document.getElementById("cs-title").value || "").trim(),
        category: document.getElementById("cs-category").value,
        platform: (document.getElementById("cs-platform").value || "").trim(),
        loss_amount_range: document.getElementById("cs-loss").value,
        what_happened: (document.getElementById("cs-happened").value || "").trim(),
        what_felt_suspicious: (document.getElementById("cs-suspicious").value || "").trim(),
        what_wish_done: (document.getElementById("cs-wish").value || "").trim(),
      };
      const msg = document.getElementById("cs-msg");
      if (!payload.title || !payload.what_happened) {
        msg.textContent = "제목과 '무슨 일이 있었나요?'는 필수예요.";
        return;
      }
      document.getElementById("cs-submit").disabled = true;
      msg.textContent = "비식별 처리 중…";
      try {
        const r = await API.community.submitCase(payload);
        const status = (r && (r.status || (r.case && r.case.status))) || "approved";
        submitOverlay.classList.add("hidden");
        toast(status === "approved" ? "사례를 공유했어요. 고마워요!" : "사례가 접수됐어요 (검토 후 공개).");
        if (panelEl) renderPanel(panelEl);
      } catch (e) {
        document.getElementById("cs-submit").disabled = false;
        msg.textContent = e.message || "등록 실패";
      }
    });
  }

  document.getElementById("case-detail-close").addEventListener("click", () => detailOverlay.classList.add("hidden"));
  document.getElementById("case-submit-close").addEventListener("click", () => submitOverlay.classList.add("hidden"));
  [detailOverlay, submitOverlay].forEach((ov) => {
    ov.addEventListener("click", (e) => { if (e.target === ov) ov.classList.add("hidden"); });
  });

  global.SafeDealCommunity = { renderPanel, openDetail };
})(window);
