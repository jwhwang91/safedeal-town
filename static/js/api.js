/* ============================================================
   api.js — 서버 통신 계층
   모든 /api 호출을 여기서 감싼다. 토큰은 localStorage 에 보관하고,
   요청마다 Authorization 헤더를 자동으로 붙인다.
   ============================================================ */
(function (global) {
  "use strict";

  const TOKEN_KEY = "safedeal_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }
  function setToken(token) {
    if (token) localStorage.setItem(TOKEN_KEY, token);
  }
  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  /* 공통 요청 함수: JSON 보내고 JSON 받기.
     서버가 에러를 주면 detail 메시지를 담은 Error 를 던진다. */
  async function request(path, { method = "GET", body = null, auth = true } = {}) {
    const headers = {};
    if (body !== null) headers["Content-Type"] = "application/json";
    if (auth) {
      const t = getToken();
      if (t) headers["Authorization"] = "Bearer " + t;
    }

    let res;
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : undefined,
      });
    } catch (networkErr) {
      throw new Error("서버에 연결할 수 없어요. 서버가 켜져 있는지 확인해 주세요.");
    }

    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_) {
        data = null;
      }
    }

    if (!res.ok) {
      const detail =
        (data && (data.detail || data.message)) ||
        "요청 처리 중 문제가 생겼어요. (" + res.status + ")";
      const err = new Error(
        typeof detail === "string" ? detail : "요청을 처리하지 못했어요."
      );
      err.status = res.status;
      throw err;
    }
    return data;
  }

  /* ---------- 인증 ---------- */
  const auth = {
    async register(payload) {
      const data = await request("/api/auth/register", {
        method: "POST",
        body: payload,
        auth: false,
      });
      setToken(data.access_token);
      return data;
    },
    async login(username, password) {
      const data = await request("/api/auth/login", {
        method: "POST",
        body: { username, password },
        auth: false,
      });
      setToken(data.access_token);
      return data;
    },
    async me() {
      return request("/api/auth/me");
    },
    logout() {
      clearToken();
    },
  };

  /* ---------- 게임 ---------- */
  const game = {
    world() {
      return request("/api/game/world");
    },
    getSetup() {
      return request("/api/game/setup");
    },
    saveSetup(payload) {
      return request("/api/game/setup", { method: "POST", body: payload });
    },
    updateAvatar(avatar) {
      return request("/api/game/avatar", { method: "POST", body: { avatar } });
    },
    setLocation(payload) {
      return request("/api/game/location", { method: "POST", body: payload });
    },
    setRole(gameRole) {
      return request("/api/game/role", { method: "POST", body: { game_role: gameRole } });
    },
    catalog() {
      return request("/api/game/catalog");
    },
    getPreferences() {
      return request("/api/game/preferences");
    },
    savePreferences(payload) {
      return request("/api/game/preferences", { method: "POST", body: payload });
    },
    getListing() {
      return request("/api/game/listing");
    },
    saveListing(listing) {
      return request("/api/game/listing", { method: "POST", body: listing });
    },
    spawns() {
      return request("/api/game/spawns");
    },
    refreshSpawns() {
      return request("/api/game/spawns/refresh", { method: "POST" });
    },
    // 판매자 모드: 현재 대기 중인 인바운드 문의 목록
    getInquiries() {
      return request("/api/game/inquiries");
    },
    // 판매자 모드: 문의 수락 → 거래(채팅) 시작 (chat.start 와 동일 응답)
    acceptInquiry(inquiryId) {
      return request(
        "/api/game/inquiries/" + encodeURIComponent(inquiryId) + "/accept",
        { method: "POST" }
      );
    },
    profile() {
      return request("/api/game/profile");
    },
    leaderboard() {
      return request("/api/game/leaderboard");
    },
    inventory() {
      return request("/api/game/inventory");
    },
    equip(itemId, slot) {
      return request("/api/game/equip", { method: "POST", body: { item_id: itemId, slot: slot || null } });
    },
    unequip(slot) {
      return request("/api/game/unequip", { method: "POST", body: { slot } });
    },
    rewardsCatalog() {
      return request("/api/game/rewards/catalog");
    },
    habitReport() {
      return request("/api/game/habit-report");
    },
    trainingProfile() {
      return request("/api/game/training-profile");
    },
    resetTrainingProfile() {
      return request("/api/game/training-profile/reset", { method: "POST" });
    },
    // ---------- 미션(퀘스트) ----------
    getMissions() {
      return request("/api/game/missions/available");
    },
    acceptMission(missionKey, sessionId) {
      return request("/api/game/missions/accept", {
        method: "POST",
        body: { mission_key: missionKey, session_id: sessionId || null },
      });
    },
    skipMission(missionId) {
      return request("/api/game/missions/skip", {
        method: "POST",
        body: { mission_id: missionId },
      });
    },
    getActiveMission(sessionId) {
      const qs = sessionId ? "?session_id=" + encodeURIComponent(sessionId) : "";
      return request("/api/game/missions/active" + qs);
    },
    clearCurrentMission() {
      return request("/api/game/missions/clear-current", { method: "POST" });
    },
  };

  /* ---------- 채팅(거래) ---------- */
  const chat = {
    // 정답지 보호: 클라이언트는 spawn_instance_id 만 안다. 서버가 npc_id 로 매핑한다.
    card(spawnInstanceId) {
      return request("/api/chat/card", {
        method: "POST",
        body: { spawn_instance_id: spawnInstanceId || null },
      });
    },
    start(spawnInstanceId, inquiryId) {
      return request("/api/chat/start", {
        method: "POST",
        body: {
          spawn_instance_id: spawnInstanceId || null,
          inquiry_id: inquiryId || null,
        },
      });
    },
    message(sessionId, message) {
      return request("/api/chat/message", {
        method: "POST",
        body: { session_id: sessionId, message },
      });
    },
    flag(sessionId, messageId, flagged) {
      return request("/api/chat/flag", {
        method: "POST",
        body: { session_id: sessionId, message_id: messageId, flagged },
      });
    },
    resolve(sessionId, decision, checklist) {
      return request("/api/chat/resolve", {
        method: "POST",
        body: { session_id: sessionId, decision, checklist: checklist || [] },
      });
    },
  };

  /* ---------- 사기 취약도 진단 (assessment) ---------- */
  const assessment = {
    start(assessmentType) {
      return request("/api/assessment/start", {
        method: "POST",
        body: { assessment_type: assessmentType || "baseline" },
      });
    },
    answer(sessionId, questionId, answer) {
      return request("/api/assessment/answer", {
        method: "POST",
        body: { session_id: sessionId, question_id: questionId, answer },
      });
    },
    complete(sessionId) {
      return request("/api/assessment/complete", {
        method: "POST",
        body: { session_id: sessionId },
      });
    },
    latest(assessmentType) {
      const qs = assessmentType ? "?assessment_type=" + encodeURIComponent(assessmentType) : "";
      return request("/api/assessment/latest" + qs);
    },
    history() {
      return request("/api/assessment/history");
    },
  };

  /* ---------- 개인 방어 리포트 (report) ---------- */
  const report = {
    personal() {
      return request("/api/report/personal");
    },
    beforeAfter() {
      return request("/api/report/before-after");
    },
    evidence() {
      return request("/api/report/evidence");
    },
  };

  /* ---------- 커뮤니티 피해 사례 (community) ---------- */
  const community = {
    listCases(category, status) {
      const p = new URLSearchParams();
      if (category) p.set("category", category);
      if (status) p.set("status", status);
      const qs = p.toString();
      return request("/api/community/cases" + (qs ? "?" + qs : ""));
    },
    getCase(caseId) {
      return request("/api/community/cases/" + encodeURIComponent(caseId));
    },
    submitCase(payload) {
      return request("/api/community/cases", { method: "POST", body: payload });
    },
    comment(caseId, comment) {
      return request("/api/community/cases/" + encodeURIComponent(caseId) + "/comment", {
        method: "POST",
        body: { comment },
      });
    },
    react(caseId, reactionType) {
      return request("/api/community/cases/" + encodeURIComponent(caseId) + "/react", {
        method: "POST",
        body: { reaction_type: reactionType || "me_too" },
      });
    },
    report(caseId, reason) {
      return request("/api/community/cases/" + encodeURIComponent(caseId) + "/report", {
        method: "POST",
        body: { reason },
      });
    },
  };

  /* ---------- 방어 시나리오 뱅크 (scenarios) ---------- */
  const scenarios = {
    search(q, category, riskFamily) {
      const p = new URLSearchParams();
      if (q) p.set("q", q);
      if (category) p.set("category", category);
      if (riskFamily) p.set("risk_family", riskFamily);
      const qs = p.toString();
      return request("/api/scenarios/search" + (qs ? "?" + qs : ""));
    },
    fromCase(caseId) {
      return request("/api/scenarios/from-case/" + encodeURIComponent(caseId), {
        method: "POST",
      });
    },
    recommend(missionKey) {
      const qs = missionKey ? "?mission_key=" + encodeURIComponent(missionKey) : "";
      return request("/api/scenarios/recommend" + qs);
    },
  };

  /* ---------- 기관 / 코호트 데모 대시보드 (orgs) ---------- */
  const orgs = {
    createDemo(name, orgType) {
      return request("/api/orgs/demo/create", {
        method: "POST",
        body: { name, org_type: orgType || "school" },
      });
    },
    addCurrentUser(cohortId) {
      return request("/api/orgs/demo/cohort/add-current-user", {
        method: "POST",
        body: { cohort_id: cohortId || null },
      });
    },
    dashboard(cohortId) {
      const qs = cohortId ? "?cohort_id=" + encodeURIComponent(cohortId) : "";
      return request("/api/orgs/demo/dashboard" + qs);
    },
    list() {
      return request("/api/orgs/demo/list");
    },
  };

  global.API = {
    auth,
    game,
    chat,
    assessment,
    report,
    community,
    scenarios,
    orgs,
    getToken,
    clearToken,
    hasToken: () => !!getToken(),
  };
})(window);
