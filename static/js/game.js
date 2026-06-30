/* ============================================================
   game.js — 마을 캔버스 엔진
   - 맵은 백엔드가 만들고(world_map.js 가 그림), NPC 는 스폰 매니저가 관리.
   - 방향키/WASD 이동 + 충돌(world_map)
   - 커스텀 아바타 플레이어(avatar.js), 카테고리별 NPC(sprites.js)
   - NPC 근처에서 E/Space → 대화 (chat.js 에 위임), 스폰 인스턴스 단위로 시작
   ============================================================ */
(function (global) {
  "use strict";

  const canvas = document.getElementById("game-canvas");
  const ctx = canvas.getContext("2d");
  const hintEl = document.getElementById("interact-hint");
  const bannerEl = document.getElementById("objective-banner");
  const townNameEl = document.getElementById("town-name");
  const townNameTextEl = document.getElementById("town-name-text");

  let player = null;
  let nearby = null;       // 가장 가까운 상호작용 가능한 스폰
  let hintForId = null;    // interact-hint 가 현재 가리키는 스폰 (매 프레임 DOM 갱신 방지)
  let paused = true;
  let started = false;
  let gameRole = "buyer";
  let equippedEffects = [];  // 장착된 거래 도구 효과키 (체크리스트/답변칩에 사용)
  let sellerTheme = "general_booth";  // 판매자 모드 부스 소품 테마 (내 카테고리 기반)
  const inquiryAlertEl = document.getElementById("inquiry-alert");
  let inquiryAlertCount = -1;  // 현재 표시된 대기 문의 수 (DOM 갱신 최소화)
  if (inquiryAlertEl) {
    inquiryAlertEl.addEventListener("click", () => openNearestWaiting());
  }

  const keys = Object.create(null);
  const MOVE_KEYS = {
    ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    KeyW: "up", KeyS: "down", KeyA: "left", KeyD: "right",
  };

  window.addEventListener("keydown", (e) => {
    if (paused) return;
    if (e.code in MOVE_KEYS) {
      keys[MOVE_KEYS[e.code]] = true;
      e.preventDefault();
    } else if (e.code === "KeyE" || e.code === "Space") {
      e.preventDefault();
      tryInteract();
    }
  });
  window.addEventListener("keyup", (e) => {
    if (e.code in MOVE_KEYS) {
      keys[MOVE_KEYS[e.code]] = false;
      e.preventDefault();
    }
  });
  window.addEventListener("blur", () => {
    for (const k in keys) keys[k] = false;
  });

  /* ---------- 충돌 (플레이어 박스 네 모서리) ---------- */
  const SPEED = 1.5;
  const HALF = 11;
  function boxHits(px, py) {
    return (
      SafeDealWorldMap.isSolidPx(px - HALF, py - HALF) ||
      SafeDealWorldMap.isSolidPx(px + HALF, py - HALF) ||
      SafeDealWorldMap.isSolidPx(px - HALF, py + HALF) ||
      SafeDealWorldMap.isSolidPx(px + HALF, py + HALF)
    );
  }

  /* ---------- NPC 로밍(배회) + 판매자 모드 접근 ---------- */
  const NPC_SPEED = 0.55;          // 플레이어보다 느긋하게
  const NPC_APPROACH_SPEED = 0.7;  // 플레이어를 향해 다가올 땐 조금 더 목적성 있게
  const NPC_HALF = 9;
  const NPC_WANDER_TILES = 2.4;    // 집(자리)에서 벗어나는 최대 반경
  const APPROACH_INTEREST_MIN = 0.4;

  function npcBoxHits(px, py) {
    return (
      SafeDealWorldMap.isSolidPx(px - NPC_HALF, py - NPC_HALF) ||
      SafeDealWorldMap.isSolidPx(px + NPC_HALF, py - NPC_HALF) ||
      SafeDealWorldMap.isSolidPx(px - NPC_HALF, py + NPC_HALF) ||
      SafeDealWorldMap.isSolidPx(px + NPC_HALF, py + NPC_HALF)
    );
  }

  function pickNpcTarget(s, TILE) {
    // 집 주변의 걸어갈 수 있는 한 점을 고른다 (막힌 곳이면 몇 번 다시 시도).
    for (let i = 0; i < 6; i++) {
      const ang = Math.random() * Math.PI * 2;
      const r = Math.random() * NPC_WANDER_TILES * TILE;
      const tx = s.homePx + Math.cos(ang) * r;
      const ty = s.homePy + Math.sin(ang) * r;
      if (!npcBoxHits(tx, ty)) { s.tx = tx; s.ty = ty; return; }
    }
    s.tx = s.homePx; s.ty = s.homePy;
  }

  // 한 점을 향해 충돌을 피하며 한 걸음. 반환: 남은 거리.
  function stepToward(s, tx, ty, speed) {
    const dx = tx - s.px, dy = ty - s.py;
    const dist = Math.hypot(dx, dy);
    if (dist <= 1.5) { s.moving = false; return dist; }
    const vx = (dx / dist) * speed, vy = (dy / dist) * speed;
    let moved = false;
    if (!npcBoxHits(s.px + vx, s.py)) { s.px += vx; moved = true; }
    if (!npcBoxHits(s.px, s.py + vy)) { s.py += vy; moved = true; }
    if (moved) {
      if (Math.abs(dx) > Math.abs(dy)) s.facing = dx < 0 ? "left" : "right";
      else s.facing = dy < 0 ? "up" : "down";
      s.walkPhase += 0.25;
      s.moving = true;
    } else {
      s.moving = false;
    }
    return dist;
  }

  function roamStep(s, now, TILE) {
    if (!s.repathAt || now >= s.repathAt) {
      pickNpcTarget(s, TILE);
      s.repathAt = now + 1500 + Math.random() * 2600; // 잠깐 멈췄다 다시 이동
    }
    const moved = stepToward(s, s.tx, s.ty, NPC_SPEED);
    // 양쪽 다 막혀 제자리면 다음 프레임에 곧바로 새 목적지를 고르게 한다.
    if (moved > 1.5 && !s.moving) s.repathAt = 0;
  }

  function approachReady(s, nowMs) {
    const delay = s.approach_delay_seconds;
    if (delay == null) return false;                         // 이번엔 둘러보기만
    if ((s.interest_level || 0) < APPROACH_INTEREST_MIN) return false;
    return (nowMs - s.bornAt) / 1000 >= delay;
  }

  // 판매자 모드 구매자 NPC 의 접근 상태머신: roaming→interested→approaching→waiting
  function updateSellerBuyer(s, now, nowMs, TILE) {
    const st = s.approachState || "roaming";
    if (st === "roaming") {
      if (approachReady(s, nowMs)) {
        s.approachState = "interested";
        s.stateAt = nowMs;
        s.moving = false;
      } else {
        roamStep(s, now, TILE);
      }
      return;
    }
    if (st === "interested") {
      s.moving = false;                                       // 잠깐 멈춰 '관심'(생각 말풍선)
      if (nowMs - (s.stateAt || nowMs) > 1400) {
        s.approachState = "approaching";
        s.stateAt = nowMs;
      }
      return;
    }
    // approaching / waiting → 플레이어 옆으로
    if (!player) return;
    const standoff = TILE * 1.05;
    const ang = Math.atan2(s.py - player.py, s.px - player.px);
    const tx = player.px + Math.cos(ang) * standoff;
    const ty = player.py + Math.sin(ang) * standoff;
    stepToward(s, tx, ty, NPC_APPROACH_SPEED);
    const dp = Math.hypot(player.px - s.px, player.py - s.py);
    if (st === "approaching") {
      if (dp <= TILE * 1.25) {
        s.approachState = "waiting";
        s.stateAt = nowMs;
        if (!s.inquiryNotified) {
          s.inquiryNotified = true;
          if (global.SafeDeal && SafeDeal.toast) {
            SafeDeal.toast("🔔 구매자가 문의를 보냈습니다 — 가까이서 E/Space 로 응대하세요");
          }
        }
      }
    } else { // waiting: 플레이어 바라보며 대기, 멀어지면 다시 따라감
      s.facing = Math.abs(player.px - s.px) > Math.abs(player.py - s.py)
        ? (player.px < s.px ? "left" : "right")
        : (player.py < s.py ? "up" : "down");
      if (dp > TILE * 2.6) s.approachState = "approaching";
    }
  }

  function updateNpcs(now, TILE) {
    const nowMs = Date.now();
    SafeDealSpawns.list().forEach((s) => {
      if (gameRole === "seller" && s.npc_kind === "buyer") {
        updateSellerBuyer(s, now, nowMs, TILE);
      } else {
        roamStep(s, now, TILE);
      }
    });
  }

  // 가장 가까운 '대기 중(waiting)' 구매자를 응대 (알림 클릭/HUD 버튼용)
  function openNearestWaiting() {
    if (paused || !player) return;
    let best = null, bd = Infinity;
    SafeDealSpawns.list().forEach((s) => {
      if (s.npc_kind !== "buyer") return;
      if (s.approachState !== "waiting" && s.approachState !== "approaching") return;
      const d = Math.hypot(s.px - player.px, s.py - player.py);
      if (d < bd) { bd = d; best = s; }
    });
    if (best && global.SafeDealChat && SafeDealChat.openCard) SafeDealChat.openCard(best);
  }

  function waitingCount() {
    let n = 0;
    SafeDealSpawns.list().forEach((s) => {
      if (s.npc_kind === "buyer" && s.approachState === "waiting") n++;
    });
    return n;
  }

  /* ---------- 업데이트 ---------- */
  function update() {
    if (!player) return;
    const { TILE } = SafeDealWorldMap.dims();
    let dx = 0, dy = 0;
    if (keys.up) dy -= 1;
    if (keys.down) dy += 1;
    if (keys.left) dx -= 1;
    if (keys.right) dx += 1;

    if (dx !== 0 || dy !== 0) {
      const len = Math.hypot(dx, dy) || 1;
      const vx = (dx / len) * SPEED;
      const vy = (dy / len) * SPEED;
      const nx = player.px + vx;
      if (!boxHits(nx, player.py)) player.px = nx;
      const ny = player.py + vy;
      if (!boxHits(player.px, ny)) player.py = ny;
      if (dx < 0) player.facing = "left";
      else if (dx > 0) player.facing = "right";
      else if (dy < 0) player.facing = "up";
      else if (dy > 0) player.facing = "down";
      player.moving = true;
      player.walkPhase += 0.3;
    } else {
      player.moving = false;
    }

    // NPC 들을 배회시키고(roaming), 그 '현재 위치' 기준으로 가장 가까운 NPC 를 찾는다.
    updateNpcs(performance.now(), TILE);
    let best = null, bestDist = Infinity;
    SafeDealSpawns.list().forEach((s) => {
      const d = Math.hypot(s.px - player.px, s.py - player.py);
      if (d < bestDist) { bestDist = d; best = s; }
    });
    nearby = bestDist <= TILE * 1.5 ? best : null;
    hintEl.classList.toggle("hidden", !nearby);
    // 가리키는 NPC 가 바뀔 때만 DOM 을 갱신한다 (매 프레임 innerHTML 재생성 방지).
    const nid = nearby ? nearby.spawn_instance_id : null;
    if (nid !== hintForId) {
      hintForId = nid;
      if (nearby) {
        hintEl.innerHTML =
          '<span class="key">E</span> 또는 <span class="key">Space</span> — ' +
          "<b>" + escapeHtml(nearby.name) + "</b> 와 대화하기";
      }
    }

    updateInquiryAlert();
  }

  // 판매자 모드: 대기 중인 구매자 문의 알림(클릭하면 응대). 구매자 모드/0건이면 숨긴다.
  function updateInquiryAlert() {
    if (!inquiryAlertEl) return;
    const n = gameRole === "seller" ? waitingCount() : 0;
    if (n === inquiryAlertCount) return;
    inquiryAlertCount = n;
    if (n > 0) {
      inquiryAlertEl.textContent = "🔔 구매자 문의 " + n + "건 — 클릭해 응대";
      inquiryAlertEl.classList.remove("hidden");
    } else {
      inquiryAlertEl.classList.add("hidden");
    }
  }

  function tryInteract() {
    if (paused || !nearby) return;
    // 대화 전에 먼저 프로필/매물 카드를 보여준다 (없으면 바로 대화).
    if (global.SafeDealChat && SafeDealChat.openCard) {
      SafeDealChat.openCard(nearby);
    } else if (global.SafeDealChat && SafeDealChat.openChat) {
      SafeDealChat.openChat(nearby);
    }
  }

  /* ---------- NPC 렌더 ---------- */
  function npcAvatarOf(s) {
    // sprite_color 를 셔츠색으로 쓰고, 스폰 id 해시로 피부/모자에 변주를 준다
    // (npc_id 는 정답지라 클라이언트에 없으므로 spawn_instance_id 를 시드로 사용)
    const seed = s.spawn_instance_id || "";
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) & 0xffff;
    const skins = ["light", "tan", "brown", "deep"];
    const hats = ["none", "none", "cap", "beanie", "straw"];
    return {
      skin: skins[h % skins.length],
      hat: hats[(h >> 2) % hats.length],
      pants: "charcoal",
      accessory: "none",
    };
  }

  // 말풍선 문구: 인물의 한마디(tagline, 무엇을 팔/사는지 + 성격). 없으면 물건명으로 폴백.
  // 판매자 모드 구매자는 접근 상태에 따라 '관심(👀)→문의 미리보기'로 바뀐다 (유형은 비노출).
  function balloonText(s) {
    if (s.npc_kind === "buyer" && gameRole === "seller") {
      const st = s.approachState || "roaming";
      if (st === "interested") return "👀";
      if (st === "approaching" || st === "waiting") {
        const q = String(s.inquiry_preview || s.tagline || "이거 아직 있나요?").trim();
        return q.length > 24 ? q.slice(0, 24) + "…" : q;
      }
    }
    const line = String(s.tagline || "").trim();
    if (line) return line.length > 24 ? line.slice(0, 24) + "…" : line;
    const item = String(s.item_name || "").trim();
    if (!item) return "";
    const short = item.length > 11 ? item.slice(0, 11) + "…" : item;
    return short + (s.npc_kind === "seller" ? " 팝니다" : " 삽니다");
  }

  function drawBalloon(cx, baseY, text) {
    if (!text) return;
    ctx.font = "11px 'Jua', sans-serif";
    const padX = 7;
    const tw = Math.min(ctx.measureText(text).width, 200);
    const w = tw + padX * 2;
    const h = 17;
    const x = cx - w / 2;
    const y = baseY - h; // baseY = 풍선 아래(꼬리) 위치
    rr(x, y, w, h, 7);
    ctx.fillStyle = "rgba(255,252,245,.96)";
    ctx.fill();
    ctx.strokeStyle = "rgba(58,50,38,.5)";
    ctx.lineWidth = 1.1;
    ctx.stroke();
    // 꼬리
    ctx.beginPath();
    ctx.moveTo(cx - 4, y + h - 0.5);
    ctx.lineTo(cx, y + h + 5);
    ctx.lineTo(cx + 4, y + h - 0.5);
    ctx.closePath();
    ctx.fillStyle = "rgba(255,252,245,.96)";
    ctx.fill();
    // 글자
    ctx.fillStyle = "#3a3226";
    ctx.textAlign = "center";
    ctx.fillText(text, cx, y + 12, tw);
    ctx.textAlign = "left";
  }

  function drawNpc(ctx, s, t) {
    // 가판대 소품은 '자리(home)'에 고정 — 캐릭터만 그 주변을 배회한다.
    if (s.npc_kind === "seller") {
      SafeDealSprites.drawBoothProps(ctx, s.homePx, s.homePy, s.visual_theme);
    } else {
      SafeDealSprites.drawBuyerProp(ctx, s.homePx, s.homePy, s.visual_theme);
    }

    const cx = s.px, cy = s.py;
    const bob = s.moving ? Math.abs(Math.sin(s.walkPhase)) * 2.2
                         : Math.sin(t / 320 + (s.phase || 0)) * 1.4;

    // 상호작용 가능 표시 (반짝이는 링 + 별)
    if (nearby && nearby.spawn_instance_id === s.spawn_instance_id) {
      ctx.strokeStyle = "rgba(224,169,60,.95)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(cx, cy + 2, 22, 0, Math.PI * 2);
      ctx.stroke();
      const sp = (Math.sin(t / 160) + 1) / 2;
      ctx.fillStyle = "rgba(255,236,170," + (0.5 + sp * 0.5) + ")";
      drawStar(ctx, cx + 16, cy - 18, 5, 5, 2.4);
    }

    // 캐릭터 (걷는 방향을 바라봄)
    SafeDealAvatar.draw(ctx, cx, cy, npcAvatarOf(s), {
      bob, facing: s.facing || "down", shirtColor: s.sprite_color,
    });

    // 이름표
    ctx.font = "12px 'Jua', sans-serif";
    ctx.textAlign = "center";
    const name = s.name;
    const nw = ctx.measureText(name).width + 12;
    rr(cx - nw / 2, cy + 20, nw, 16, 6);
    ctx.fillStyle = "rgba(58,50,38,.85)";
    ctx.fill();
    ctx.fillStyle = "#fbf3e3";
    ctx.fillText(name, cx, cy + 32);
    ctx.textAlign = "left";

    // 머리 위 말풍선 (무엇을 팔/사는지)
    drawBalloon(cx, cy - 22 + bob * 0.4, balloonText(s));

    // 남은 수명 바 (사라지기 직전 표시) — 이름표 아래
    const rem = SafeDealSpawns.remainingSeconds(s);
    if (rem <= 20) {
      const w = 26;
      ctx.fillStyle = "rgba(0,0,0,.25)";
      ctx.fillRect(cx - w / 2, cy + 36, w, 4);
      ctx.fillStyle = rem <= 8 ? "#c0392b" : "#e0a93c";
      ctx.fillRect(cx - w / 2, cy + 36, (w * rem) / 20, 4);
    }
  }

  function drawStar(ctx, cx, cy, spikes, outer, inner) {
    let rot = -Math.PI / 2;
    const step = Math.PI / spikes;
    ctx.beginPath();
    ctx.moveTo(cx, cy - outer);
    for (let i = 0; i < spikes; i++) {
      ctx.lineTo(cx + Math.cos(rot) * outer, cy + Math.sin(rot) * outer); rot += step;
      ctx.lineTo(cx + Math.cos(rot) * inner, cy + Math.sin(rot) * inner); rot += step;
    }
    ctx.closePath();
    ctx.fill();
  }

  function drawPlayer(ctx, t) {
    const bob = player.moving ? Math.sin(player.walkPhase) * 2 : 0;
    SafeDealAvatar.draw(ctx, player.px, player.py, player.avatar, {
      bob, facing: player.facing,
    });
  }

  /* ---------- 렌더 ---------- */
  function render(t) {
    if (!SafeDealWorldMap.ready()) return;
    const dims = SafeDealWorldMap.dims();
    const vw = canvas.width, vh = canvas.height;
    // 카메라: 플레이어를 화면 중앙에 두되, 월드 경계 밖으로 나가지 않게 클램프.
    // 월드가 화면보다 크므로 움직이면 스크롤되며 새 구역이 드러난다.
    let camX = (player ? player.px : dims.W / 2) - vw / 2;
    let camY = (player ? player.py : dims.H / 2) - vh / 2;
    camX = Math.round(Math.max(0, Math.min(camX, Math.max(0, dims.W - vw))));
    camY = Math.round(Math.max(0, Math.min(camY, Math.max(0, dims.H - vh))));

    ctx.clearRect(0, 0, vw, vh);
    ctx.save();
    ctx.translate(-camX, -camY);
    SafeDealWorldMap.draw(ctx, t, camX, camY, vw, vh);

    // 판매자 모드: 플레이어 자리에 좌판/돗자리(플레이어보다 먼저 그려 뒤에 깔린다)
    if (player && gameRole === "seller") {
      SafeDealSprites.drawSellerBooth(ctx, player.px, player.py, sellerTheme, "내 좌판");
    }

    // 액터(NPC/플레이어)를 y 순으로 그려 앞뒤 겹침 자연스럽게
    const actors = SafeDealSpawns.list().map((s) => ({
      kind: "npc", y: s.py, ref: s,
    }));
    actors.push({ kind: "player", y: player ? player.py : 0 });
    actors.sort((a, b) => a.y - b.y);
    actors.forEach((a) => {
      if (a.kind === "npc") drawNpc(ctx, a.ref, t);
      else if (player) drawPlayer(ctx, t);
    });
    ctx.restore();
  }

  /* ---------- 루프 ---------- */
  function loop(ts) {
    if (!paused) update();
    render(ts);
    requestAnimationFrame(loop);
  }

  /* ---------- 헬퍼 ---------- */
  function rr(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // 판매자 카테고리(표준) → 부스 소품 테마. 모르면 general_booth.
  function _boothTheme(cat) {
    const ok = { electronics: 1, camping: 1, beauty: 1, home: 1, fashion: 1, books: 1, general: 1 };
    const c = ok[cat] ? cat : "general";
    return c + "_booth";
  }

  function applyBanner() {
    if (!bannerEl) return;
    if (gameRole === "seller") {
      bannerEl.innerHTML =
        "🎯 당신은 <b>판매자</b>입니다. 찾아오는 구매자 중 <b>진상·위험 구매자</b>에게 침착하고 안전하게 대응하세요.";
    } else {
      bannerEl.innerHTML =
        "🎯 마을을 돌아다니며 판매자와 대화해 보세요. 누가 <b>사기꾼</b>이고 누가 <b>정상 판매자</b>일까요?";
    }
  }

  /* ---------- 공개 API ---------- */
  function applyTownName(map) {
    const name = (map && map.town_name) || "";
    if (townNameTextEl) townNameTextEl.textContent = name;
    if (townNameEl) townNameEl.classList.toggle("hidden", !name);
    // town_name 에 이미 "중고타운" 이 들어있으므로 접미사를 또 붙이지 않는다.
    document.title = name ? name + " — 사기꾼은 누구?" : "중고타운 — 사기꾼은 누구?";
  }

  async function loadWorld() {
    const world = await API.game.world();
    gameRole = (world.player && world.player.game_role) || "buyer";
    SafeDealWorldMap.set(world.map);
    applyTownName(world.map);
    SafeDealSpawns.init(world.spawns || []);
    SafeDealSpawns.startPolling();
    const sp = SafeDealWorldMap.playerSpawnPx();
    player = {
      px: sp.px, py: sp.py, facing: "down", moving: false, walkPhase: 0,
      avatar: (world.player && world.player.avatar) || SafeDealAvatar.DEFAULT_AVATAR,
    };
    equippedEffects = (world.player && world.player.equipped_effects) || [];
    sellerTheme = _boothTheme((world.player && world.player.seller_category) || "general");
    inquiryAlertCount = -1;  // 알림 표시 강제 재계산
    applyBanner();
    if (global.SafeDeal && SafeDeal.updateHud) SafeDeal.updateHud(world.player);
    if (global.SafeDeal && SafeDeal.setRoleHud) SafeDeal.setRoleHud(gameRole);
    return world;
  }

  // 거래 후 / 장착 변경 후 스폰·HUD·아바타 갱신
  async function refreshWorld() {
    try {
      const world = await API.game.world();
      SafeDealSpawns.init(world.spawns || []);
      if (player && world.player && world.player.avatar) player.avatar = world.player.avatar;
      equippedEffects = (world.player && world.player.equipped_effects) || [];
      if (global.SafeDeal && SafeDeal.updateHud) SafeDeal.updateHud(world.player);
    } catch (_) { /* 무시 */ }
  }

  function start() {
    paused = false;
    if (!started) {
      started = true;
      requestAnimationFrame(loop);
    }
  }
  function setPaused(p) {
    paused = p;
    if (p) {
      for (const k in keys) keys[k] = false;
      hintEl.classList.add("hidden");
    }
  }
  function reset() {
    paused = true;
    player = null;
    nearby = null;
    SafeDealSpawns.reset();
    for (const k in keys) keys[k] = false;
    hintEl.classList.add("hidden");
    if (inquiryAlertEl) inquiryAlertEl.classList.add("hidden");
    inquiryAlertCount = -1;
  }

  global.SafeDealGame = {
    loadWorld, refreshWorld, start, setPaused, reset,
    openNearestWaiting,
    effects: () => equippedEffects.slice(),
    role: () => gameRole,
  };
})(window);
