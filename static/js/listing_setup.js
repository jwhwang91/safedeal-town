/* ============================================================
   listing_setup.js — 입장 전 '오늘 찾는 물건'(구매) / '내 판매글'(판매) 빌더
   - 구매자: 카테고리 + 가격 민감도 + 선호 거래방식
   - 판매자: 카테고리/상품/상태/가격/구성품/하자/거래방식/환불원칙/증거
   카탈로그 메타(/api/game/catalog)로 상품 자동완성·시세 추천을 돕는다.
   setup.js 가 이 모듈을 불러 두 패널을 그리고, 저장 시 값을 읽어 API 로 보낸다.
   ============================================================ */
(function (global) {
  "use strict";

  let META = null; // 카탈로그 메타 (categories/conditions/products/...)

  /* ---------- 작은 DOM 헬퍼 ---------- */
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function won(n) { return "₩" + Number(n || 0).toLocaleString("ko-KR"); }

  /* 단일/다중 선택 칩 그룹.
     opts: [{key,label}], selected: 단일이면 key, 다중이면 [keys]
     반환: { node, get() } */
  function chipGroup(opts, selected, multi) {
    const wrap = el("div", "chip-group");
    const state = multi ? new Set(selected || []) : { key: selected };
    opts.forEach((o) => {
      const b = el("button", "chip-toggle", o.label);
      b.type = "button";
      b.dataset.key = o.key;
      const isOn = multi ? state.has(o.key) : state.key === o.key;
      if (isOn) b.classList.add("on");
      b.addEventListener("click", () => {
        if (multi) {
          if (state.has(o.key)) { state.delete(o.key); b.classList.remove("on"); }
          else { state.add(o.key); b.classList.add("on"); }
        } else {
          state.key = o.key;
          wrap.querySelectorAll(".chip-toggle").forEach((x) => x.classList.remove("on"));
          b.classList.add("on");
          if (typeof wrap._onpick === "function") wrap._onpick(o.key);
        }
      });
      wrap.appendChild(b);
    });
    wrap._get = () => (multi ? Array.from(state) : state.key);
    return wrap;
  }

  function labeledRow(labelText, node) {
    const row = el("div", "field");
    row.appendChild(el("label", "field-label", labelText));
    row.appendChild(node);
    return row;
  }

  /* ============================================================
     구매자 위시리스트
     ============================================================ */
  let buyerCatGroup = null, buyerPriceGroup = null, buyerTradeGroup = null;

  function buildBuyer(container, prefill) {
    clear(container);
    const pf = prefill || {};
    container.appendChild(el("p", "setup-hint",
      "찾는 물건을 정하면, 마을에 그 카테고리의 다양한 매물이 등장해요."));

    buyerCatGroup = chipGroup(META.categories, pf.buyer_category || "random", false);
    container.appendChild(labeledRow("카테고리", buyerCatGroup));

    buyerPriceGroup = chipGroup(META.price_preferences, pf.buyer_price_preference || "fair", false);
    container.appendChild(labeledRow("가격 민감도", buyerPriceGroup));

    buyerTradeGroup = chipGroup(META.trade_preferences, pf.buyer_trade_preference || "any", false);
    container.appendChild(labeledRow("선호 거래방식", buyerTradeGroup));
  }

  function getBuyer() {
    return {
      buyer_category: (buyerCatGroup && buyerCatGroup._get()) || "random",
      buyer_price_preference: (buyerPriceGroup && buyerPriceGroup._get()) || "fair",
      buyer_trade_preference: (buyerTradeGroup && buyerTradeGroup._get()) || "any",
    };
  }

  /* ============================================================
     판매자 판매글
     ============================================================ */
  let sCatSel = null, sNameInput = null, sCondSel = null,
      sPriceInput = null, sMarketInput = null,
      sDefectGroup = null, sAccGroup = null, sTradeGroup = null,
      sRefundInput = null, sProofGroup = null, sDefectWrap = null, sAccWrap = null;

  function productsFor(cat) {
    return (META.products && META.products[cat]) || [];
  }
  function findProduct(cat, name) {
    return productsFor(cat).find((p) => p.name === name) || null;
  }

  function rebuildSuggestionChips(cat, name) {
    // 상품을 고르면 흔한 하자/구성품을 칩 후보로 깔아준다 (자동완성).
    const prod = findProduct(cat, name);
    const defectSel = sDefectGroup ? sDefectGroup._get() : [];
    const accSel = sAccGroup ? sAccGroup._get() : [];
    const defectOpts = (prod ? prod.common_defects : []).map((d) => ({ key: d, label: d }));
    const accOpts = (prod ? prod.typical_accessories : []).map((a) => ({ key: a, label: a }));
    clear(sDefectWrap);
    sDefectGroup = chipGroup(defectOpts, defectSel, true);
    sDefectWrap.appendChild(sDefectGroup);
    clear(sAccWrap);
    sAccGroup = chipGroup(accOpts, accSel, true);
    sAccWrap.appendChild(sAccGroup);
  }

  function applyProductAutofill(cat, name) {
    const prod = findProduct(cat, name);
    if (prod) {
      if (!sMarketInput.value || sMarketInput.dataset.auto === "1") {
        sMarketInput.value = prod.market_price;
        sMarketInput.dataset.auto = "1";
      }
      if (!sPriceInput.value) {
        // 적정가 추천: 시세의 약 85%
        sPriceInput.value = Math.round(prod.market_price * 0.85 / 1000) * 1000;
      }
    }
    rebuildSuggestionChips(cat, name);
  }

  function refreshNameDatalist(cat) {
    const dl = document.getElementById("seller-name-options");
    if (!dl) return;
    clear(dl);
    productsFor(cat).forEach((p) => {
      const o = document.createElement("option");
      o.value = p.name;
      dl.appendChild(o);
    });
  }

  function buildSeller(container, prefill) {
    clear(container);
    const pf = prefill || {};
    container.appendChild(el("p", "setup-hint",
      "내가 파는 물건을 정해두면, 찾아오는 구매자 NPC 가 이 물건을 보고 반응해요."));

    // 카테고리 select
    sCatSel = el("select", "field-input");
    META.categories.forEach((c) => {
      if (c.key === "random") return; // 판매글은 구체 카테고리만
      const o = el("option", null, c.label); o.value = c.key; sCatSel.appendChild(o);
    });
    sCatSel.value = pf.category || "electronics";
    container.appendChild(labeledRow("카테고리", sCatSel));

    // 상품명 + datalist
    sNameInput = el("input", "field-input");
    sNameInput.type = "text";
    sNameInput.maxLength = 60;
    sNameInput.placeholder = "예: MacBook Air M1";
    sNameInput.setAttribute("list", "seller-name-options");
    sNameInput.value = pf.product_name || "";
    let dl = document.getElementById("seller-name-options");
    if (!dl) { dl = el("datalist"); dl.id = "seller-name-options"; container.appendChild(dl); }
    container.appendChild(labeledRow("상품명", sNameInput));

    // 상태 select
    sCondSel = el("select", "field-input");
    META.conditions.forEach((c) => {
      const o = el("option", null, c.label); o.value = c.key; sCondSel.appendChild(o);
    });
    sCondSel.value = pf.condition || "lightly_used";
    container.appendChild(labeledRow("상태", sCondSel));

    // 가격 / 시세 (한 줄)
    const priceRow = el("div", "field-grid2");
    sPriceInput = el("input", "field-input");
    sPriceInput.type = "number"; sPriceInput.min = "0"; sPriceInput.placeholder = "판매가";
    if (pf.listing_price) sPriceInput.value = pf.listing_price;
    sMarketInput = el("input", "field-input");
    sMarketInput.type = "number"; sMarketInput.min = "0"; sMarketInput.placeholder = "시세(자동)";
    if (pf.market_price) sMarketInput.value = pf.market_price;
    sMarketInput.addEventListener("input", () => { sMarketInput.dataset.auto = "0"; });
    priceRow.appendChild(labeledRow("판매가(원)", sPriceInput));
    priceRow.appendChild(labeledRow("시세(원)", sMarketInput));
    container.appendChild(priceRow);

    // 하자 / 구성품 (자동완성 칩)
    sDefectWrap = el("div");
    container.appendChild(labeledRow("고지할 하자", sDefectWrap));
    sAccWrap = el("div");
    container.appendChild(labeledRow("구성품", sAccWrap));
    sDefectGroup = chipGroup([], pf.disclosed_defects || [], true);
    sAccGroup = chipGroup([], pf.accessories || [], true);
    sDefectWrap.appendChild(sDefectGroup);
    sAccWrap.appendChild(sAccGroup);

    // 거래방식
    sTradeGroup = chipGroup(
      META.trade_methods.map((m) => ({ key: m, label: m })),
      pf.trade_methods || ["직거래", "안전결제"], true
    );
    container.appendChild(labeledRow("거래방식", sTradeGroup));

    // 준비한 증거
    sProofGroup = chipGroup(META.proof_options, pf.proof_prepared || [], true);
    container.appendChild(labeledRow("준비한 증거", sProofGroup));

    // 환불 원칙
    sRefundInput = el("input", "field-input");
    sRefundInput.type = "text"; sRefundInput.maxLength = 200;
    sRefundInput.placeholder = "예: 단순 변심 환불은 어렵고, 하자는 사진 확인 후 협의";
    sRefundInput.value = pf.refund_policy || "";
    container.appendChild(labeledRow("환불 원칙", sRefundInput));

    // 이벤트: 카테고리/상품 변경 → 자동완성
    sCatSel.addEventListener("change", () => {
      refreshNameDatalist(sCatSel.value);
      sMarketInput.dataset.auto = "1";
      rebuildSuggestionChips(sCatSel.value, sNameInput.value);
    });
    sNameInput.addEventListener("change", () => applyProductAutofill(sCatSel.value, sNameInput.value));
    sNameInput.addEventListener("blur", () => applyProductAutofill(sCatSel.value, sNameInput.value));

    refreshNameDatalist(sCatSel.value);
    if (sNameInput.value) applyProductAutofill(sCatSel.value, sNameInput.value);
  }

  function getSeller() {
    return {
      category: sCatSel ? sCatSel.value : "electronics",
      product_name: (sNameInput ? sNameInput.value.trim() : "") || "중고 물품",
      condition: sCondSel ? sCondSel.value : "lightly_used",
      listing_price: parseInt(sPriceInput && sPriceInput.value, 10) || 0,
      market_price: parseInt(sMarketInput && sMarketInput.value, 10) || 0,
      disclosed_defects: sDefectGroup ? sDefectGroup._get() : [],
      accessories: sAccGroup ? sAccGroup._get() : [],
      trade_methods: sTradeGroup ? sTradeGroup._get() : [],
      refund_policy: sRefundInput ? sRefundInput.value.trim() : "",
      proof_prepared: sProofGroup ? sProofGroup._get() : [],
    };
  }

  global.SafeDealListingSetup = {
    setCatalog(meta) { META = meta; },
    hasCatalog() { return !!META; },
    buildBuyer, getBuyer,
    buildSeller, getSeller,
  };
})(window);
