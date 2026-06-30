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

  /* 한 줄 제목 → 카테고리 추론 (백엔드 category_infer.py 의 가벼운 미러).
     라이브 UX 용이며, 최종 권위는 서버다. 더 구체적인 것부터 검사한다. */
  const _INFER_RULES = [
    ["laptop", ["맥북", "macbook", "노트북", "랩탑", "그램", "gram", "갤럭시북", "갤북", "씽크패드"]],
    ["gaming", ["닌텐도", "스위치", "switch", "ps5", "ps4", "플스", "플레이스테이션", "xbox", "엑스박스", "스팀덱", "게임기", "조이콘", "rtx", "게이밍"]],
    ["camera", ["카메라", "dslr", "미러리스", "캐논", "canon", "니콘", "nikon", "고프로", "gopro", "짐벌", "액션캠"]],
    ["electronics", ["아이패드", "ipad", "갤럭시탭", "갤탭", "태블릿", "에어팟", "airpods", "버즈", "갤럭시워치", "애플워치", "스마트워치", "워치", "이어폰", "헤드폰", "스피커", "키보드", "마우스", "모니터", "ssd"]],
    ["smartphone", ["아이폰", "iphone", "갤럭시", "galaxy", "z플립", "z폴드", "폴드", "플립", "픽셀", "pixel", "스마트폰", "핸드폰", "휴대폰", "공기계", "자급제"]],
    ["camping", ["텐트", "캠핑", "랜턴", "코펠", "버너", "화로대", "타프", "침낭", "아이스박스", "아웃도어"]],
    ["beauty", ["화장품", "에어랩", "고데기", "드라이기", "향수", "립스틱", "파운데이션", "뷰티", "쿠션", "세럼"]],
    ["books", ["도서", "교재", "문제집", "참고서", "전공책", "전공서적", "만화책", "소설", "수험서", "원서"]],
    ["fashion", ["패딩", "코트", "자켓", "재킷", "신발", "운동화", "스니커즈", "나이키", "nike", "아디다스", "adidas", "구두", "백팩", "핸드백", "지갑", "명품", "원피스", "청바지", "후드티", "맨투맨", "패션", "의류", "가방"]],
    ["furniture", ["책상", "소파", "쇼파", "침대", "옷장", "서랍", "행거", "식탁", "책장", "매트리스", "화장대", "수납장", "가구"]],
    ["sports", ["자전거", "헬스", "덤벨", "아령", "골프", "테니스", "라켓", "스키", "킥보드", "런닝머신", "요가매트", "축구", "농구"]],
    ["kids", ["유아", "아기", "기저귀", "분유", "유모차", "카시트", "아기띠", "아동", "어린이", "보행기"]],
    ["hobby", ["일렉기타", "통기타", "피아노", "드론", "레고", "프라모델", "피규어", "보드게임", "낚시", "악기"]],
    ["home", ["청소기", "냉장고", "세탁기", "에어컨", "전자레인지", "밥솥", "가습기", "공기청정기", "식기세척기", "인덕션", "티비", "로봇청소기", "정수기", "선풍기", "가전"]],
    ["books", ["책"]],
    ["furniture", ["의자"]],
  ];

  function inferCategoryFromTitle(title) {
    const raw = String(title || "").toLowerCase();
    const squashed = raw.replace(/\s+/g, "");
    for (const [cat, kws] of _INFER_RULES) {
      for (const kw of kws) {
        if (raw.indexOf(kw) >= 0 || squashed.indexOf(kw) >= 0) return cat;
      }
    }
    return "random";
  }

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
      sRefundInput = null, sProofGroup = null, sDefectWrap = null, sAccWrap = null,
      sCatHint = null, userPickedCategory = false;

  function _catLabelOf(key) {
    if (!sCatSel) return key;
    const o = Array.from(sCatSel.options).find((x) => x.value === key);
    return o ? o.textContent : key;
  }

  function updateInferHint() {
    if (!sCatHint || !sNameInput) return;
    const title = sNameInput.value.trim();
    if (!title) { sCatHint.textContent = ""; return; }
    const inferred = inferCategoryFromTitle(title);
    if (inferred === "random") {
      sCatHint.textContent = "제목에서 카테고리를 추론하지 못했어요. 직접 골라주세요.";
    } else if (userPickedCategory && sCatSel && sCatSel.value !== inferred) {
      sCatHint.textContent = "제목 추론은 ‘" + _catLabelOf(inferred) + "’ 지만, 직접 고른 카테고리를 유지해요.";
    } else {
      sCatHint.textContent = "💡 제목에서 추론한 카테고리: " + _catLabelOf(inferred);
    }
  }

  // 제목 입력 → 카테고리 라이브 추론 (사용자가 카테고리를 직접 바꾸기 전까지만 자동 반영)
  function liveInferCategory() {
    if (!sNameInput || !sCatSel) return;
    const inferred = inferCategoryFromTitle(sNameInput.value);
    if (inferred !== "random" && !userPickedCategory && sCatSel.value !== inferred) {
      if (Array.from(sCatSel.options).some((o) => o.value === inferred)) {
        sCatSel.value = inferred;
        refreshNameDatalist(inferred);
        rebuildSuggestionChips(inferred, sNameInput.value);
      }
    }
    updateInferHint();
  }

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

    // 한 줄 판매글 제목(=상품명) + datalist — '가장 중요한 필드'. 여기서 카테고리를 추론한다.
    sNameInput = el("input", "field-input");
    sNameInput.type = "text";
    sNameInput.maxLength = 60;
    sNameInput.placeholder = "예: 아이폰 14 Pro 128GB 팔아요 / 맥북 에어 M1 급처";
    sNameInput.setAttribute("list", "seller-name-options");
    sNameInput.value = pf.product_name || "";
    let dl = document.getElementById("seller-name-options");
    if (!dl) { dl = el("datalist"); dl.id = "seller-name-options"; container.appendChild(dl); }
    container.appendChild(labeledRow("판매글 제목 (상품명)", sNameInput));

    // 카테고리 select — 제목에서 자동 추론되며, 직접 고르면 그 선택을 유지(수동 우선).
    sCatSel = el("select", "field-input");
    META.categories.forEach((c) => {
      if (c.key === "random") return; // 판매글은 구체 카테고리만
      const o = el("option", null, c.label); o.value = c.key; sCatSel.appendChild(o);
    });
    // 기존 판매글을 수정하는 경우(pf.category 존재) → 사용자가 고른 값으로 간주해 유지.
    userPickedCategory = !!pf.category;
    sCatSel.value = pf.category || (sNameInput.value ? inferCategoryFromTitle(sNameInput.value) : "electronics");
    if (sCatSel.value === "random" || !sCatSel.value) sCatSel.value = "electronics";
    container.appendChild(labeledRow("카테고리", sCatSel));
    sCatHint = el("p", "setup-hint infer-hint");
    container.appendChild(sCatHint);

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

    // 이벤트: 카테고리/상품 변경 → 자동완성 + 라이브 추론
    sCatSel.addEventListener("change", () => {
      userPickedCategory = true;           // 직접 골랐으니 이제 추론이 덮어쓰지 않는다
      refreshNameDatalist(sCatSel.value);
      sMarketInput.dataset.auto = "1";
      rebuildSuggestionChips(sCatSel.value, sNameInput.value);
      updateInferHint();
    });
    // 제목을 칠 때마다 카테고리 라이브 추론 (사용자가 직접 고르기 전까지)
    sNameInput.addEventListener("input", liveInferCategory);
    sNameInput.addEventListener("change", () => applyProductAutofill(sCatSel.value, sNameInput.value));
    sNameInput.addEventListener("blur", () => applyProductAutofill(sCatSel.value, sNameInput.value));

    refreshNameDatalist(sCatSel.value);
    if (sNameInput.value) applyProductAutofill(sCatSel.value, sNameInput.value);
    updateInferHint();
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
