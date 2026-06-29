/* ============================================================
   spawn_manager.js — NPC 등장/소멸 관리 (프론트)
   백엔드 /api/game/spawns 를 주기적으로 폴링해서, 마을에 떠 있는
   NPC 목록을 최신으로 유지한다. 각 NPC 는 남은 수명이 있고,
   시간이 지나면 사라지고 다른 NPC 가 다른 자리에 나타난다.
   ============================================================ */
(function (global) {
  "use strict";

  const POLL_MS = 6000;

  let spawns = []; // { ...serverFields, expiresAt(ms), phase }
  let timer = null;
  let generation = 0; // 월드가 새로 깔릴 때마다 증가 → 옛 역할의 폴링 응답을 버리는 기준

  function _hashPhase(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 100000;
    return (h % 1000) / 1000 * Math.PI * 2;
  }

  function _adopt(serverList) {
    const now = Date.now();
    const TILE = (SafeDealWorldMap.dims && SafeDealWorldMap.dims().TILE) || 40;
    const prev = {};
    spawns.forEach((s) => (prev[s.spawn_instance_id] = s));
    spawns = (serverList || []).map((s) => {
      const old = prev[s.spawn_instance_id];
      // 자리(스폰 칸)는 '집(home)'. NPC 는 이 집 주변을 돌아다닌다(roaming).
      const homePx = s.x * TILE + TILE / 2;
      const homePy = s.y * TILE + TILE / 2;
      return Object.assign({}, s, {
        expiresAt: now + (s.remaining_seconds || 0) * 1000,
        phase: old ? old.phase : _hashPhase(s.spawn_instance_id),
        bornAt: old ? old.bornAt : now,
        // 로밍 상태 (재폴링 시 이어받아 끊김 없이 움직이게)
        homePx, homePy,
        px: old ? old.px : homePx,
        py: old ? old.py : homePy,
        tx: old ? old.tx : homePx,
        ty: old ? old.ty : homePy,
        facing: old ? old.facing : "down",
        walkPhase: old ? old.walkPhase : 0,
        moving: false,
        repathAt: old ? old.repathAt : 0,
      });
    });
  }

  function init(serverList) {
    generation++; // 역할 전환 등으로 월드를 새로 깔았음 → 이전 폴링 응답은 무효화
    _adopt(serverList);
  }

  async function poll() {
    const gen = generation;
    try {
      const data = await API.game.spawns();
      // 폴링 도중 init()(예: 역할 전환)이 일어났으면 이 응답은 옛 역할 것이므로 버린다.
      if (gen !== generation) return;
      _adopt(data.spawns || []);
    } catch (_) {
      /* 조용히 무시 — 다음 폴링에서 다시 시도 */
    }
  }

  function startPolling() {
    stopPolling();
    timer = setInterval(poll, POLL_MS);
  }
  function stopPolling() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  // 아직 살아있는(수명 남은) 스폰만 반환
  function list() {
    const now = Date.now();
    return spawns.filter((s) => s.expiresAt > now);
  }

  function remainingSeconds(s) {
    return Math.max(0, Math.round((s.expiresAt - Date.now()) / 1000));
  }

  // 갓 등장한 NPC 인지 (등장 연출용, 0.6초)
  function justSpawned(s) {
    return Date.now() - s.bornAt < 600;
  }

  function reset() {
    stopPolling();
    spawns = [];
  }

  global.SafeDealSpawns = {
    init, poll, startPolling, stopPolling, list,
    remainingSeconds, justSpawned, reset,
  };
})(window);
