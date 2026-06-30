/* ============================================================
   avatar.js — 도트 캐릭터 렌더링 + 커스터마이즈 옵션
   이미지 에셋 없이 캔버스 프리미티브로만 그린다 (가볍게 유지).
   플레이어(게임/셋업 미리보기)와 NPC 가 같은 그리기 로직을 공유한다.
   ============================================================ */
(function (global) {
  "use strict";

  /* ---------- 색 팔레트 (키 → 색) ---------- */
  const SKIN = {
    light: "#f3d2a8", tan: "#e6b98c", brown: "#bd8b60", deep: "#8a5e3c",
  };
  const SHIRT = {
    terracotta: "#d9744f", sage: "#7a9b6e", sky: "#6aa6c7", gold: "#e0a93c",
    berry: "#c0567a", plum: "#8d6aa6", mint: "#67b79e", charcoal: "#4f4636",
  };
  const PANTS = {
    denim: "#3f6fb0", khaki: "#b6a06a", charcoal: "#45413a",
    brown: "#6f4524", olive: "#6f7a3c",
  };
  const HAIR = "#2a2018";

  /* ---------- 커스터마이즈 선택지 (셋업 화면이 이걸 읽어 스와치를 그림) ---------- */
  const OPTIONS = {
    skin: [
      { key: "light", label: "밝은" }, { key: "tan", label: "건강한" },
      { key: "brown", label: "갈색" }, { key: "deep", label: "진한" },
    ],
    shirt: [
      { key: "terracotta", label: "테라코타" }, { key: "sage", label: "세이지" },
      { key: "sky", label: "하늘" }, { key: "gold", label: "골드" },
      { key: "berry", label: "베리" }, { key: "plum", label: "자두" },
      { key: "mint", label: "민트" }, { key: "charcoal", label: "차콜" },
    ],
    pants: [
      { key: "denim", label: "데님" }, { key: "khaki", label: "카키" },
      { key: "charcoal", label: "차콜" }, { key: "brown", label: "브라운" },
      { key: "olive", label: "올리브" },
    ],
    hat: [
      { key: "none", label: "없음" }, { key: "cap", label: "캡모자" },
      { key: "beanie", label: "비니" }, { key: "straw", label: "밀짚" },
      { key: "band", label: "머리띠" },
    ],
    accessory: [
      { key: "none", label: "없음" }, { key: "glasses", label: "안경" },
      { key: "bag", label: "가방" }, { key: "scarf", label: "스카프" },
      { key: "earring", label: "귀걸이" },
    ],
  };

  const DEFAULT_AVATAR = {
    skin: "light", hat: "none", shirt: "terracotta",
    pants: "denim", accessory: "none",
  };

  function colorOf(map, key, fallback) {
    return map[key] || fallback;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /* ---------- 캐릭터 그리기 ----------
     opts: { scale=1, bob=0, facing="down", shirtColor (override) } */
  function draw(ctx, cx, cy, avatar, opts) {
    avatar = avatar || DEFAULT_AVATAR;
    opts = opts || {};
    const s = opts.scale || 1;
    const bob = opts.bob || 0;
    const skin = colorOf(SKIN, avatar.skin, SKIN.light);
    const shirt = opts.shirtColor || colorOf(SHIRT, avatar.shirt, SHIRT.terracotta);
    const pants = colorOf(PANTS, avatar.pants, PANTS.denim);

    ctx.save();
    ctx.translate(cx, cy + bob);
    ctx.scale(s, s);

    // 그림자
    ctx.fillStyle = "rgba(0,0,0,.18)";
    ctx.beginPath();
    ctx.ellipse(0, 16, 13, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // 다리/바지
    ctx.fillStyle = pants;
    ctx.fillRect(-8, 10, 6, 9);
    ctx.fillRect(2, 10, 6, 9);
    // 신발
    ctx.fillStyle = "#3a2f25";
    ctx.fillRect(-9, 18, 7, 3);
    ctx.fillRect(2, 18, 7, 3);

    // 몸통 (셔츠)
    ctx.fillStyle = shirt;
    roundRect(ctx, -11, -3, 22, 16, 5);
    ctx.fill();
    // 셔츠 음영
    ctx.fillStyle = "rgba(0,0,0,.10)";
    roundRect(ctx, -11, 7, 22, 6, 4);
    ctx.fill();

    // 액세서리: 가방끈 / 스카프
    if (avatar.accessory === "bag") {
      ctx.fillStyle = "#6f4524";
      ctx.fillRect(-3, -3, 6, 16);
    } else if (avatar.accessory === "scarf") {
      ctx.fillStyle = "#c0567a";
      ctx.fillRect(-9, -2, 18, 4);
    }

    // 머리
    ctx.fillStyle = skin;
    ctx.beginPath();
    ctx.arc(0, -10, 9, 0, Math.PI * 2);
    ctx.fill();

    // 머리카락 (모자 없을 때 더 보이게)
    ctx.fillStyle = HAIR;
    ctx.beginPath();
    ctx.arc(0, -12, 9, Math.PI, Math.PI * 2);
    ctx.fill();
    if (avatar.hat === "none" || avatar.hat === "band" || avatar.hat === "earring") {
      ctx.fillRect(-9, -12, 3, 6);
      ctx.fillRect(6, -12, 3, 6);
    }

    // 눈 (바라보는 방향)
    let ex = 0, ey = 0;
    if (opts.facing === "left") ex = -3;
    else if (opts.facing === "right") ex = 3;
    else if (opts.facing === "up") ey = -2;
    else ey = 1;
    ctx.fillStyle = "#2a2018";
    ctx.beginPath();
    ctx.arc(-3 + ex, -10 + ey, 1.6, 0, Math.PI * 2);
    ctx.arc(3 + ex, -10 + ey, 1.6, 0, Math.PI * 2);
    ctx.fill();

    // 안경
    if (avatar.accessory === "glasses") {
      ctx.strokeStyle = "#2a2018";
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.arc(-3, -10, 3, 0, Math.PI * 2);
      ctx.arc(4, -10, 3, 0, Math.PI * 2);
      ctx.moveTo(0, -10);
      ctx.lineTo(1, -10);
      ctx.stroke();
    }
    // 귀걸이
    if (avatar.accessory === "earring") {
      ctx.fillStyle = "#e0a93c";
      ctx.beginPath();
      ctx.arc(-9, -8, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
    // 탐정 선글라스 (보상 코스튬)
    if (avatar.accessory === "sunglasses") {
      ctx.fillStyle = "#1c1c22";
      roundRect(ctx, -7, -12, 6, 5, 1.6); ctx.fill();
      roundRect(ctx, 1, -12, 6, 5, 1.6); ctx.fill();
      ctx.strokeStyle = "#1c1c22"; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(-1, -10); ctx.lineTo(1, -10); ctx.stroke();
    }

    // 모자
    drawHat(ctx, avatar.hat, shirt);

    ctx.restore();
  }

  function drawHat(ctx, hat, accentColor) {
    if (!hat || hat === "none" || hat === "earring") return;
    if (hat === "cap") {
      ctx.fillStyle = accentColor;
      roundRect(ctx, -10, -22, 20, 9, 4);
      ctx.fill();
      ctx.fillStyle = "rgba(0,0,0,.25)";
      ctx.fillRect(-2, -14, 14, 3); // 챙
    } else if (hat === "beanie") {
      ctx.fillStyle = "#7a9b6e";
      roundRect(ctx, -10, -23, 20, 11, 6);
      ctx.fill();
      ctx.fillStyle = "#5f7e55";
      ctx.fillRect(-10, -14, 20, 3);
    } else if (hat === "straw") {
      ctx.fillStyle = "#e0c07a";
      ctx.beginPath();
      ctx.ellipse(0, -13, 15, 5, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#cda85a";
      roundRect(ctx, -8, -22, 16, 9, 5);
      ctx.fill();
    } else if (hat === "band") {
      ctx.fillStyle = "#d9744f";
      ctx.fillRect(-10, -16, 20, 3);
    } else if (hat === "hood") {
      // 베테랑 후드 (머리 위로 덮은 후드)
      ctx.fillStyle = accentColor;
      ctx.beginPath();
      ctx.arc(0, -10, 13, Math.PI, 0);
      ctx.lineTo(13, -7); ctx.lineTo(-13, -7); ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "rgba(0,0,0,.15)";
      ctx.beginPath(); ctx.arc(0, -10, 9, Math.PI, 0); ctx.fill();
    } else if (hat === "detective") {
      // 장터 고수 모자 (디어스토커 느낌)
      ctx.fillStyle = "#8a5a33";
      ctx.fillRect(-13, -13, 26, 3);            // 챙
      ctx.fillStyle = "#9b6a3c";
      roundRect(ctx, -11, -22, 22, 10, 5); ctx.fill();  // 크라운
      ctx.fillStyle = "#7a4d2a";
      roundRect(ctx, -4, -25, 8, 5, 2); ctx.fill();     // 꼭지
    }
  }

  global.SafeDealAvatar = {
    draw,
    OPTIONS,
    DEFAULT_AVATAR,
    SKIN, SHIRT, PANTS,
    colorOf,
  };
})(window);
