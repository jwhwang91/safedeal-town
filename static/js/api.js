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
    spawns() {
      return request("/api/game/spawns");
    },
    refreshSpawns() {
      return request("/api/game/spawns/refresh", { method: "POST" });
    },
    profile() {
      return request("/api/game/profile");
    },
    leaderboard() {
      return request("/api/game/leaderboard");
    },
  };

  /* ---------- 채팅(거래) ---------- */
  const chat = {
    // 정답지 보호: 클라이언트는 spawn_instance_id 만 안다. 서버가 npc_id 로 매핑한다.
    start(spawnInstanceId) {
      return request("/api/chat/start", {
        method: "POST",
        body: { spawn_instance_id: spawnInstanceId || null },
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
    resolve(sessionId, decision) {
      return request("/api/chat/resolve", {
        method: "POST",
        body: { session_id: sessionId, decision },
      });
    },
  };

  global.API = {
    auth,
    game,
    chat,
    getToken,
    clearToken,
    hasToken: () => !!getToken(),
  };
})(window);
