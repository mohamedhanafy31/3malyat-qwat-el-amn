/* ==========================================================================
   منظومة المصادقة — صفحات الدخول، الإعداد، وتغيير كلمة المرور
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  // ── إظهار / إخفاء كلمة المرور ──
  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-toggle-password]");
    if (!btn) return;
    const targetId = btn.getAttribute("data-toggle-password");
    const input = document.getElementById(targetId);
    if (!input) return;
    const isPassword = input.type === "password";
    input.type = isPassword ? "text" : "password";
    btn.setAttribute("aria-pressed", isPassword ? "true" : "false");
    btn.setAttribute("aria-label", isPassword ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
    const iconEye = btn.querySelector(".icon-eye");
    const iconEyeOff = btn.querySelector(".icon-eye-off");
    if (iconEye && iconEyeOff) {
      iconEye.classList.toggle("hidden", isPassword);
      iconEyeOff.classList.toggle("hidden", !isPassword);
    }
  });

  // ── دالة مساعدة لعرض الخطأ ──
  function showError(box, msg) {
    if (!box) return;
    box.textContent = msg;
    box.classList.remove("hidden");
    box.focus?.();
  }
  function clearError(box) {
    if (!box) return;
    box.textContent = "";
    box.classList.add("hidden");
  }

  // ── تسجيل الدخول (/login) ──
  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    const VALID_ROLES = ["admin", "officer", "individual", "conscript"];

    // استرجاع نوع المستخدم المحفوظ سابقًا من localStorage إن وُجد وكان صالحًا
    try {
      const savedRole = localStorage.getItem("loginRole");
      if (savedRole && VALID_ROLES.includes(savedRole)) {
        const radio = document.querySelector(`input[name="loginRole"][value="${savedRole}"]`);
        if (radio) {
          radio.checked = true;
        }
      }
    } catch (_) {}

    // حفظ نوع المستخدم في localStorage عند الاختيار
    document.querySelectorAll('input[name="loginRole"]').forEach(radio => {
      radio.addEventListener("change", () => {
        try {
          localStorage.setItem("loginRole", radio.value);
        } catch (_) {}
      });
    });

    loginForm.addEventListener("submit", async e => {
      e.preventDefault();
      const errBox = document.getElementById("loginError");
      const submitBtn = document.getElementById("loginSubmit");
      clearError(errBox);

      const roleRadio = document.querySelector('input[name="loginRole"]:checked');
      const role = roleRadio?.value || "";

      if (!role) {
        showError(errBox, "اختر نوع المستخدم");
        const firstRadio = document.querySelector('input[name="loginRole"]');
        firstRadio?.focus();
        return;
      }

      const username = (document.getElementById("loginUsername")?.value || "").trim();
      const password = document.getElementById("loginPassword")?.value || "";
      const nextVal = document.getElementById("loginNext")?.value || "";

      if (!username || !password) {
        showError(errBox, "يرجى إدخال اسم المستخدم وكلمة المرور");
        if (!username) {
          document.getElementById("loginUsername")?.focus();
        } else {
          document.getElementById("loginPassword")?.focus();
        }
        return;
      }

      const origText = submitBtn.innerHTML;
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> جاري الدخول…';

      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "fetch"
          },
          body: JSON.stringify({
            role,
            username,
            password,
            next: nextVal || "/"
          })
        });

        let data = {};
        try { data = await res.json(); } catch (_) {}

        if (res.ok) {
          try {
            localStorage.setItem("loginRole", role);
          } catch (_) {}
          location.href = data.next || "/";
          return;
        }

        // On 401, 400 role_required, or other error
        const serverError = data.error || "بيانات الدخول غير صحيحة";
        showError(errBox, serverError);
        if (data.code === "role_required" || res.status === 400) {
          const firstRadio = document.querySelector('input[name="loginRole"]');
          firstRadio?.focus();
        }
      } catch (_) {
        showError(errBox, "تعذر الاتصال بالخادم، يرجى المحاولة لاحقًا");
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origText;
      }
    });
  }

  // ── إعداد أول مدير للنظام (/setup) ──
  const setupForm = document.getElementById("setupForm");
  if (setupForm) {
    setupForm.addEventListener("submit", async e => {
      e.preventDefault();
      const errBox = document.getElementById("setupError");
      const submitBtn = document.getElementById("setupSubmit");
      clearError(errBox);

      const username = (document.getElementById("setupUsername")?.value || "").trim();
      const displayName = (document.getElementById("setupDisplayName")?.value || "").trim();
      const password = document.getElementById("setupPassword")?.value || "";
      const confirmPassword = document.getElementById("setupConfirmPassword")?.value || "";

      if (!username || !displayName || !password) {
        showError(errBox, "يرجى استيفاء جميع الحقول المطلوبة");
        return;
      }
      if (password.length < 8) {
        showError(errBox, "يجب ألا تقل كلمة المرور عن ٨ أحرف");
        return;
      }
      if (password !== confirmPassword) {
        showError(errBox, "كلمتا المرور غير متطابقتين");
        return;
      }

      const origText = submitBtn.innerHTML;
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> جاري الإنشاء…';

      try {
        const res = await fetch("/api/auth/setup", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "fetch"
          },
          body: JSON.stringify({
            username,
            display_name: displayName,
            password
          })
        });

        let data = {};
        try { data = await res.json(); } catch (_) {}

        if (res.ok) {
          location.href = "/";
          return;
        }

        showError(errBox, data.error || "تعذر إنشاء الحساب");
      } catch (_) {
        showError(errBox, "تعذر الاتصال بالخادم، يرجى المحاولة لاحقًا");
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origText;
      }
    });
  }
});
