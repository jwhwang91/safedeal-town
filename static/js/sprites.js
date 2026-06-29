/* ============================================================
   sprites.js — 건물 / 랜드마크 / 카테고리별 부스 소품 / NPC 그리기
   전부 캔버스 프리미티브. 도트/픽셀 느낌 + 따뜻한 색감 유지.
   ============================================================ */
(function (global) {
  "use strict";

  function rr(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function shade(ctx, x, y, w, h, a) {
    ctx.fillStyle = "rgba(0,0,0," + a + ")";
    ctx.fillRect(x, y, w, h);
  }

  /* ---------- 건물 ---------- */
  function drawBuilding(ctx, b, TILE) {
    const x = b.x * TILE;
    const y = b.y * TILE;
    const w = b.w * TILE;
    const h = b.h * TILE;
    const wall = b.color || "#b0a080";

    // 바닥 그림자
    ctx.fillStyle = "rgba(58,50,38,.18)";
    ctx.fillRect(x + 4, y + h - 3, w, 6);

    // 벽
    ctx.fillStyle = wall;
    rr(ctx, x + 3, y + 10, w - 6, h - 12, 5);
    ctx.fill();
    shade(ctx, x + 3, y + h - 12, w - 6, 10, 0.12);

    // 지붕
    ctx.fillStyle = "#9a4f3a";
    ctx.beginPath();
    ctx.moveTo(x, y + 12);
    ctx.lineTo(x + w / 2, y - 2);
    ctx.lineTo(x + w, y + 12);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(0,0,0,.12)";
    ctx.fillRect(x, y + 10, w, 3);

    // 문
    const dw = 12, dh = 16;
    const dx = x + w / 2 - dw / 2;
    const dy = y + h - dh - 2;
    ctx.fillStyle = "#6f4524";
    rr(ctx, dx, dy, dw, dh, 3);
    ctx.fill();
    ctx.fillStyle = "#e0a93c";
    ctx.beginPath();
    ctx.arc(dx + dw - 3, dy + dh / 2, 1.4, 0, Math.PI * 2);
    ctx.fill();

    // 창문 (벽 너비에 따라 1~2개)
    ctx.fillStyle = "#cfe8f0";
    const winY = y + 16;
    if (w >= 100) {
      ctx.fillRect(x + 10, winY, 12, 12);
      ctx.fillRect(x + w - 22, winY, 12, 12);
      ctx.strokeStyle = "rgba(58,50,38,.5)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 10, winY, 12, 12);
      ctx.strokeRect(x + w - 22, winY, 12, 12);
    } else {
      ctx.fillRect(x + 8, winY, 10, 10);
      ctx.strokeStyle = "rgba(58,50,38,.5)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 8, winY, 10, 10);
    }

    // 간판
    const label = b.name || "";
    if (label) {
      ctx.font = "11px 'Jua', sans-serif";
      const tw = ctx.measureText(label).width + 12;
      const sx = x + w / 2 - tw / 2;
      const sy = y + 6;
      rr(ctx, sx, sy, tw, 14, 4);
      ctx.fillStyle = "#fffaf0";
      ctx.fill();
      ctx.strokeStyle = "#3a3226";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.fillStyle = "#3a3226";
      ctx.textAlign = "center";
      ctx.fillText(label, x + w / 2, sy + 11);
      ctx.textAlign = "left";
    }
  }

  /* ---------- 랜드마크 ---------- */
  function drawLandmark(ctx, lm, TILE, t) {
    const cx = lm.x * TILE + TILE / 2;
    const cy = lm.y * TILE + TILE / 2;
    if (lm.type === "fountain") {
      ctx.fillStyle = "#9bb0bd";
      ctx.beginPath();
      ctx.ellipse(cx, cy + 4, 16, 9, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#cfe8f0";
      ctx.beginPath();
      ctx.ellipse(cx, cy + 3, 12, 6, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#aebfca";
      ctx.fillRect(cx - 2, cy - 8, 4, 12);
      // 물줄기 반짝
      const j = Math.sin((t || 0) / 200) * 1.5;
      ctx.fillStyle = "#eaf6fb";
      ctx.beginPath();
      ctx.arc(cx, cy - 9 + j, 2.5, 0, Math.PI * 2);
      ctx.fill();
    } else if (lm.type === "tree") {
      ctx.fillStyle = "#6f4524";
      ctx.fillRect(cx - 2, cy, 4, 10);
      ctx.fillStyle = "#5f8e4f";
      ctx.beginPath();
      ctx.arc(cx, cy - 4, 11, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#6fa15c";
      ctx.beginPath();
      ctx.arc(cx - 4, cy - 7, 6, 0, Math.PI * 2);
      ctx.arc(cx + 5, cy - 3, 5, 0, Math.PI * 2);
      ctx.fill();
    } else if (lm.type === "bench") {
      ctx.fillStyle = "#8a5a33";
      ctx.fillRect(cx - 11, cy, 22, 5);
      ctx.fillRect(cx - 11, cy - 6, 22, 3);
      ctx.fillStyle = "#6f4524";
      ctx.fillRect(cx - 10, cy + 5, 3, 5);
      ctx.fillRect(cx + 7, cy + 5, 3, 5);
    } else if (lm.type === "pond") {
      // 연못 위 수련잎 + 반짝임 (물 타일은 world_map 이 이미 그린다)
      ctx.fillStyle = "#6fae7a";
      ctx.beginPath(); ctx.ellipse(cx + 6, cy + 6, 6, 4, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#5f9e6a";
      ctx.beginPath(); ctx.ellipse(cx - 6, cy + 12, 5, 3, 0, 0, Math.PI * 2); ctx.fill();
      const g = (Math.sin((t || 0) / 260) + 1) / 2;
      ctx.fillStyle = "rgba(234,246,251," + (0.4 + g * 0.5) + ")";
      ctx.fillRect(cx + 2, cy + 2, 3, 2);
    } else if (lm.type === "lamp") {
      ctx.fillStyle = "#4f4636";
      ctx.fillRect(cx - 1.5, cy - 10, 3, 18);
      ctx.fillStyle = "#e0a93c";
      ctx.beginPath();
      ctx.arc(cx, cy - 12, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(224,169,60,.25)";
      ctx.beginPath();
      ctx.arc(cx, cy - 12, 8, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* ---------- 카테고리별 부스 소품 (판매자 NPC) ---------- */
  function drawBoothProps(ctx, cx, cy, theme) {
    ctx.save();
    ctx.translate(cx, cy);
    const tableY = 14;
    // 작은 좌판
    ctx.fillStyle = "#8a5a33";
    rr(ctx, -20, tableY, 40, 8, 2);
    ctx.fill();
    ctx.fillStyle = "#7a4d2a";
    ctx.fillRect(-18, tableY + 8, 3, 6);
    ctx.fillRect(15, tableY + 8, 3, 6);

    const onTop = tableY - 8;
    if (theme === "electronics_booth") {
      ctx.fillStyle = "#cdd6e0"; ctx.fillRect(-16, onTop, 12, 8);   // 노트북
      ctx.fillStyle = "#3a4654"; ctx.fillRect(-16, onTop - 6, 12, 7);
      ctx.fillStyle = "#2a2f36"; ctx.fillRect(2, onTop - 4, 6, 12); // 폰
      ctx.fillStyle = "#d9a05a"; ctx.fillRect(10, onTop, 8, 8);     // 박스
    } else if (theme === "beauty_booth") {
      ctx.fillStyle = "#e7b7d2"; ctx.fillRect(-14, onTop - 2, 5, 10);
      ctx.fillStyle = "#c97aa5"; ctx.fillRect(-6, onTop, 4, 8);
      ctx.fillStyle = "#f0e0e8"; ctx.beginPath(); ctx.arc(8, onTop + 3, 6, 0, Math.PI * 2); ctx.fill(); // 거울
      ctx.strokeStyle = "#b58aa0"; ctx.lineWidth = 1.5; ctx.stroke();
    } else if (theme === "camping_booth") {
      ctx.fillStyle = "#6aae8a"; // 텐트
      ctx.beginPath(); ctx.moveTo(-16, onTop + 8); ctx.lineTo(-6, onTop - 6); ctx.lineTo(4, onTop + 8); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#4f8e6a"; ctx.fillRect(-7, onTop + 2, 3, 6);
      ctx.fillStyle = "#c98a5a"; ctx.fillRect(8, onTop, 9, 8); // 의자 박스
    } else if (theme === "home_booth") {
      ctx.fillStyle = "#e0c07a"; ctx.fillRect(-14, onTop - 4, 8, 12); // 램프
      ctx.fillStyle = "#caa06a"; ctx.fillRect(-12, onTop + 4, 4, 4);
      ctx.fillStyle = "#b08a5a"; ctx.fillRect(4, onTop, 12, 8);
    } else if (theme === "fashion_booth") {
      ctx.strokeStyle = "#8a5a33"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-14, onTop - 6); ctx.lineTo(14, onTop - 6); ctx.stroke();
      ctx.fillStyle = "#d98aa8"; ctx.fillRect(-12, onTop - 6, 8, 12);
      ctx.fillStyle = "#7aa6c7"; ctx.fillRect(0, onTop - 6, 8, 12);
    } else if (theme === "books_booth") {
      ctx.fillStyle = "#9a5f4f"; ctx.fillRect(-14, onTop, 7, 8);
      ctx.fillStyle = "#5f7e9b"; ctx.fillRect(-6, onTop - 2, 7, 10);
      ctx.fillStyle = "#7a9b6e"; ctx.fillRect(3, onTop, 7, 8);
    } else { // general
      ctx.fillStyle = "#caa06a"; ctx.fillRect(-14, onTop, 9, 8);
      ctx.fillStyle = "#b58a5a"; ctx.fillRect(0, onTop - 2, 9, 10);
    }
    ctx.restore();
  }

  /* ---------- 구매자 소품 (판매자 모드 NPC) ---------- */
  function drawBuyerProp(ctx, cx, cy, theme) {
    ctx.save();
    ctx.translate(cx, cy);
    if (theme === "buyer_friendly") {
      ctx.fillStyle = "#c98a5a"; // 에코백
      ctx.fillRect(13, 2, 9, 11);
      ctx.strokeStyle = "#8a5a33"; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(17, 2, 4, Math.PI, 0); ctx.stroke();
    } else if (theme === "buyer_shifty") {
      ctx.fillStyle = "#7d5ba6"; // 물음표 말풍선
      rr(ctx, 12, -22, 14, 12, 4); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "10px 'Jua', sans-serif"; ctx.textAlign = "center";
      ctx.fillText("?", 19, -13); ctx.textAlign = "left";
    } else if (theme === "buyer_pushy") {
      ctx.fillStyle = "#d36ea0"; // 느낌표 말풍선
      rr(ctx, 12, -22, 14, 12, 4); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "10px 'Jua', sans-serif"; ctx.textAlign = "center";
      ctx.fillText("!", 19, -13); ctx.textAlign = "left";
    }
    ctx.restore();
  }

  global.SafeDealSprites = { drawBuilding, drawLandmark, drawBoothProps, drawBuyerProp };
})(window);
