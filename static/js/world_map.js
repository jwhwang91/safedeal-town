/* ============================================================
   world_map.js — 백엔드가 생성한 동네 맵을 그리고 충돌을 제공한다.
   맵 생성 로직은 전부 서버(worldgen.py). 여기선 받은 대로만 그린다.
   바닥 타일 → 건물 → 랜드마크 순으로 정적 레이어를 그린다.
   ============================================================ */
(function (global) {
  "use strict";

  // 타일 코드 (worldgen.py 와 공유)
  const T_GRASS = 0, T_ROAD = 1, T_SIDEWALK = 2, T_PLAZA = 3, T_PARK = 4, T_WATER = 5;

  let map = null;
  let TILE = 40, COLS = 24, ROWS = 16;

  function set(mapData) {
    map = mapData || null;
    if (map) {
      TILE = map.tile || 40;
      COLS = map.cols || 24;
      ROWS = map.rows || 16;
    }
  }
  function ready() { return !!map; }
  function dims() { return { TILE, COLS, ROWS, W: COLS * TILE, H: ROWS * TILE }; }
  function playerSpawnPx() {
    const ps = (map && map.player_spawn) || { x: Math.floor(COLS / 2), y: Math.floor(ROWS / 2) };
    return { px: ps.x * TILE + TILE / 2, py: ps.y * TILE + TILE / 2 };
  }

  /* ---------- 충돌 ---------- */
  function isSolidPx(px, py) {
    if (!map) return false;
    const tx = Math.floor(px / TILE);
    const ty = Math.floor(py / TILE);
    if (tx < 0 || ty < 0 || tx >= COLS || ty >= ROWS) return true;
    return !!(map.solid && map.solid[ty] && map.solid[ty][tx]);
  }

  /* ---------- 바닥 타일 ---------- */
  function drawTile(ctx, x, y, type) {
    const px = x * TILE, py = y * TILE;
    if (type === T_GRASS) {
      const h = (x * 928371 + y * 1299721) % 5;
      ctx.fillStyle = h < 2 ? "#a9c98a" : h < 4 ? "#a3c483" : "#9dbf7c";
      ctx.fillRect(px, py, TILE, TILE);
      if (h === 0) {
        ctx.fillStyle = "#90b56e";
        ctx.fillRect(px + 8, py + 22, 4, 4);
        ctx.fillRect(px + 24, py + 10, 4, 4);
      }
    } else if (type === T_ROAD) {
      ctx.fillStyle = "#b9ad97";
      ctx.fillRect(px, py, TILE, TILE);
      ctx.fillStyle = "#ad9f86";
      ctx.fillRect(px, py, TILE, 3);
      ctx.fillRect(px, py, 3, TILE);
      // 중앙선 점선 느낌
      ctx.fillStyle = "#e8dcc0";
      ctx.fillRect(px + TILE / 2 - 2, py + 14, 4, 10);
    } else if (type === T_SIDEWALK) {
      ctx.fillStyle = "#ded2b6";
      ctx.fillRect(px, py, TILE, TILE);
      ctx.strokeStyle = "rgba(150,135,105,.35)";
      ctx.lineWidth = 1;
      ctx.strokeRect(px + 4, py + 4, TILE - 8, TILE - 8);
    } else if (type === T_PLAZA) {
      ctx.fillStyle = "#e6d3ab";
      ctx.fillRect(px, py, TILE, TILE);
      ctx.fillStyle = "#dcc79a";
      ctx.fillRect(px + 6, py + 6, 8, 8);
      ctx.fillRect(px + 24, py + 24, 8, 8);
    } else if (type === T_PARK) {
      ctx.fillStyle = "#8fbf73";
      ctx.fillRect(px, py, TILE, TILE);
      ctx.fillStyle = "#7fb066";
      ctx.fillRect(px + 10, py + 12, 5, 5);
      ctx.fillRect(px + 26, py + 26, 4, 4);
    } else if (type === T_WATER) {
      ctx.fillStyle = "#8fb8cf";
      ctx.fillRect(px, py, TILE, TILE);
      ctx.fillStyle = "#a6cadd";
      ctx.fillRect(px + 6, py + 10, 12, 3);
    } else {
      ctx.fillStyle = "#a3c483";
      ctx.fillRect(px, py, TILE, TILE);
    }
  }

  /* 바깥 울타리 (solid 인 테두리) */
  function drawFence(ctx, x, y) {
    const px = x * TILE, py = y * TILE;
    ctx.fillStyle = "#5f7e4f";
    ctx.fillRect(px, py, TILE, TILE);
    ctx.fillStyle = "#6f9159";
    ctx.fillRect(px + 3, py + 3, TILE - 6, TILE - 10);
    ctx.fillStyle = "#547046";
    ctx.fillRect(px + 6, py + 20, 6, 6);
    ctx.fillRect(px + 22, py + 12, 6, 6);
  }

  function isBorder(x, y) {
    return x === 0 || y === 0 || x === COLS - 1 || y === ROWS - 1;
  }

  /* ---------- 정적 레이어 그리기 ----------
     카메라(camX,camY)와 뷰포트(vw,vh)를 받아 '보이는 타일'만 그린다(컬링).
     ctx 는 이미 카메라만큼 translate 된 상태(월드 좌표계)로 들어온다. */
  function draw(ctx, t, camX, camY, vw, vh) {
    if (!map) return;
    camX = camX || 0; camY = camY || 0;
    vw = vw || COLS * TILE; vh = vh || ROWS * TILE;
    const x0 = Math.max(0, Math.floor(camX / TILE));
    const y0 = Math.max(0, Math.floor(camY / TILE));
    const x1 = Math.min(COLS - 1, Math.floor((camX + vw) / TILE));
    const y1 = Math.min(ROWS - 1, Math.floor((camY + vh) / TILE));
    // 바닥 (보이는 범위만)
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        if (isBorder(x, y) && map.solid[y][x]) drawFence(ctx, x, y);
        else drawTile(ctx, x, y, map.tiles[y][x]);
      }
    }
    // 건물 (보이는 것만)
    (map.buildings || []).forEach((b) => {
      if (b.x + b.w >= x0 && b.x <= x1 + 1 && b.y + b.h >= y0 && b.y <= y1 + 1) {
        SafeDealSprites.drawBuilding(ctx, b, TILE);
      }
    });
    // 랜드마크 (보이는 것만)
    (map.landmarks || []).forEach((lm) => {
      if (lm.x >= x0 - 1 && lm.x <= x1 + 1 && lm.y >= y0 - 1 && lm.y <= y1 + 1) {
        SafeDealSprites.drawLandmark(ctx, lm, TILE, t);
      }
    });
  }

  global.SafeDealWorldMap = { set, ready, dims, draw, isSolidPx, playerSpawnPx };
})(window);
