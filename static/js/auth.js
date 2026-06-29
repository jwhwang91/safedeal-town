/* ============================================================
   auth.js — 로그인 / 회원가입 화면
   탭 전환, 폼 제출, 성공 시 게임 화면으로 넘기는 역할.
   실제 화면 전환은 main.js 의 SafeDeal.enterGame() 에 위임한다.
   ============================================================ */
(function (global) {
  "use strict";

  const tabs = document.querySelectorAll(".auth-tab");
  const forms = {
    login: document.getElementById("login-form"),
    register: document.getElementById("register-form"),
  };
  const msgs = {
    login: document.getElementById("login-msg"),
    register: document.getElementById("register-msg"),
  };

  function showTab(name) {
    tabs.forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === name)
    );
    Object.entries(forms).forEach(([key, form]) =>
      form.classList.toggle("active", key === name)
    );
    msgs.login.textContent = "";
    msgs.register.textContent = "";
  }

  tabs.forEach((tab) =>
    tab.addEventListener("click", () => showTab(tab.dataset.tab))
  );

  function setMsg(which, text, kind) {
    const el = msgs[which];
    el.textContent = text || "";
    el.classList.remove("error", "success");
    if (kind) el.classList.add(kind);
  }

  function lockForm(form, locked) {
    form
      .querySelectorAll("input, button")
      .forEach((el) => (el.disabled = locked));
  }

  /* ---------- 로그인 ---------- */
  forms.login.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(forms.login);
    const username = (fd.get("username") || "").trim();
    const password = fd.get("password") || "";
    if (!username || !password) {
      setMsg("login", "아이디와 비밀번호를 입력해 주세요.", "error");
      return;
    }
    lockForm(forms.login, true);
    setMsg("login", "마을 문을 여는 중...", null);
    try {
      await API.auth.login(username, password);
      setMsg("login", "환영합니다! 잠시만요...", "success");
      await SafeDeal.enterGame();
    } catch (err) {
      setMsg("login", err.message, "error");
      lockForm(forms.login, false);
    }
  });

  /* ---------- 회원가입 ---------- */
  forms.register.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(forms.register);
    const payload = {
      username: (fd.get("username") || "").trim(),
      display_name: (fd.get("display_name") || "").trim(),
      password: fd.get("password") || "",
    };
    const email = (fd.get("email") || "").trim();
    if (email) payload.email = email;

    if (payload.username.length < 3) {
      setMsg("register", "아이디는 영문/숫자 3자 이상이어야 해요.", "error");
      return;
    }
    if (payload.password.length < 6) {
      setMsg("register", "비밀번호는 6자 이상이어야 해요.", "error");
      return;
    }
    if (!payload.display_name) {
      setMsg("register", "마을에서 쓸 닉네임을 정해 주세요.", "error");
      return;
    }

    lockForm(forms.register, true);
    setMsg("register", "계정을 만드는 중...", null);
    try {
      await API.auth.register(payload);
      setMsg("register", "가입 완료! 마을로 들어갑니다...", "success");
      await SafeDeal.enterGame();
    } catch (err) {
      setMsg("register", err.message, "error");
      lockForm(forms.register, false);
    }
  });

  /* 로그아웃 등으로 인증 화면에 돌아왔을 때 폼을 깨끗이 되돌리는 헬퍼 */
  function resetAuthForms() {
    forms.login.reset();
    forms.register.reset();
    lockForm(forms.login, false);
    lockForm(forms.register, false);
    setMsg("login", "", null);
    setMsg("register", "", null);
    showTab("login");
  }

  global.SafeDealAuth = { resetAuthForms };
})(window);
