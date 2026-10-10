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
    loginForm.addEventListener("submit", async e => {
      e.preventDefault();
      const errBox = document.getElementById("loginError");
      const submitBtn = document.getElementById("loginSubmit");
      clearError(errBox);

      const username = (document.getElementById("loginUsername")?.value || "").trim();
      const password = document.getElementById("loginPassword")?.value || "";
      const nextVal = document.getElementById("loginNext")?.value || "";

      if (!username || !password) {
        showError(errBox, "يرجى إدخال اسم المستخدم وكلمة المرور");
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
            username,
            password,
            next: nextVal || "/"
          })
        });

        let data = {};
        try { data = await res.json(); } catch (_) {}

        if (res.ok) {
          location.href = data.next || "/";
          return;
        }

        // 401, 429, or other error
        showError(errBox, data.error || "بيانات الدخول غير صحيحة");
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

  // ── تغيير كلمة المرور (/change-password) ──
  const changePasswordForm = document.getElementById("changePasswordForm");
  if (changePasswordForm) {
    changePasswordForm.addEventListener("submit", async e => {
      e.preventDefault();
      const errBox = document.getElementById("changePasswordError");
      const submitBtn = document.getElementById("changePasswordSubmit");
      clearError(errBox);

      const currentPassword = document.getElementById("currentPassword")?.value || "";
      const newPassword = document.getElementById("newPassword")?.value || "";
      const confirmPassword = document.getElementById("confirmPassword")?.value || "";

      if (!currentPassword || !newPassword) {
        showError(errBox, "يرجى إدخال كلمة المرور الحالية والجديدة");
        return;
      }
      if (newPassword.length < 8) {
        showError(errBox, "يجب ألا تقل كلمة المرور الجديدة عن ٨ أحرف");
        return;
      }
      if (newPassword !== confirmPassword) {
        showError(errBox, "كلمتا المرور الجديدتان غير متطابقتين");
        return;
      }

      const origText = submitBtn.innerHTML;
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> جاري الحفظ…';

      try {
        const res = await fetch("/api/auth/password", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "fetch"
          },
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword
          })
        });

        let data = {};
        try { data = await res.json(); } catch (_) {}

        if (res.ok) {
          location.href = "/";
          return;
        }

        showError(errBox, data.error || "تعذر تغيير كلمة المرور");
      } catch (_) {
        showError(errBox, "تعذر الاتصال بالخادم، يرجى المحاولة لاحقًا");
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origText;
      }
    });
  }

  // ── تسجيل الخروج من صفحة تغيير كلمة المرور ──
  const logoutBtn = document.getElementById("authLogoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async e => {
      e.preventDefault();
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "fetch"
          }
        });
      } catch (_) {}
      location.href = "/login";
    });
  }
});
