/* ==========================================================================
   إدارة الحسابات — إنشاء حسابات الضباط والأفراد والمجندين وإدارتها
   ========================================================================== */

let USERS = [];
let SEARCH_TIMER = null;

const ERROR_MESSAGES = {
  username_taken: "اسم المستخدم مستخدم بالفعل، يرجى اختيار اسم آخر",
  invalid_username: "اسم المستخدم غير صالح (٣-٣٢ حرفًا إنجليزيًا وأرقام ورموز ._- فقط)",
  weak_password: "كلمة المرور ضعيفة (يجب ألا تقل عن ٨ أحرف)",
  invalid_role: "نوع الحساب المختار غير صالح",
  last_admin: "لا يمكن تعديل أو إيقاف آخر مدير نشط في النظام",
  cannot_disable_self: "لا يمكنك إيقاف حسابك الحالي الذي تستخدمه الآن",
  user_not_found: "الحساب غير موجود",
};

function getErrorMessage(code, fallback) {
  return ERROR_MESSAGES[code] || fallback || "حدث خطأ أثناء معالجة الطلب";
}

function showModalError(boxId, msg) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.textContent = msg;
  box.classList.remove("hidden");
}

function clearModalError(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.textContent = "";
  box.classList.add("hidden");
}

function formatUserRole(role, label) {
  return `<span class="role-badge role-${esc(role)}">${esc(label || role)}</span>`;
}

function formatUserStatus(active) {
  return active
    ? '<span class="chip on">نشط</span>'
    : '<span class="chip err">موقوف</span>';
}

function formatLastLogin(ts) {
  if (!ts) return "<span class='muted'>لم يدخل بعد</span>";
  const [d, t] = String(ts).split("T");
  return `${fmt(d)} <span class="sub muted" dir="ltr">${(t || "").slice(0, 5)}</span>`;
}

function formatCreatedBy(u) {
  const by = esc(u.created_by || "—");
  const dateStr = u.created_at ? `<div class="sub muted">${fmt(String(u.created_at).slice(0, 10))}</div>` : "";
  return `${by}${dateStr}`;
}

function userRow(u) {
  const toggleLabel = u.active ? "إيقاف" : "تفعيل";
  const toggleDanger = u.active ? "danger" : "";

  return `<tr>
    <td class="font-mono" dir="ltr"><strong>${esc(u.username)}</strong></td>
    <td>${esc(u.display_name)}</td>
    <td>${formatUserRole(u.role, u.role_label)}</td>
    <td>${formatUserStatus(u.active)}</td>
    <td>${formatLastLogin(u.last_login)}</td>
    <td>${formatCreatedBy(u)}</td>
    <td class="wrap">
      <div class="actions">
        <button type="button" class="mini" data-action="editUser" data-id="${esc(u.id)}" title="تعديل الاسم والصلاحية">تعديل</button>
        <button type="button" class="mini ${toggleDanger}" data-action="toggleUser" data-id="${esc(u.id)}" title="${toggleLabel} الحساب">${toggleLabel}</button>
        <button type="button" class="mini" data-action="resetUserPassword" data-id="${esc(u.id)}" title="إعادة تعيين كلمة المرور">كلمة المرور</button>
      </div>
    </td>
  </tr>`;
}

function filteredUsers() {
  const q = ($("#userSearch")?.value || "").trim().toLowerCase();
  const role = $("#userRoleFilter")?.value || "";
  const status = $("#userStatusFilter")?.value || "";

  return USERS.filter(u => {
    if (role && u.role !== role) return false;
    if (status === "active" && !u.active) return false;
    if (status === "disabled" && u.active) return false;
    if (q) {
      const matchName = (u.display_name || "").toLowerCase().includes(q);
      const matchUser = (u.username || "").toLowerCase().includes(q);
      if (!matchName && !matchUser) return false;
    }
    return true;
  });
}

function render() {
  const list = filteredUsers();
  const wrap = $("#usersWrap");

  if (!list.length) {
    const hasFilter = ($("#userSearch")?.value || "").trim() ||
      $("#userRoleFilter")?.value ||
      $("#userStatusFilter")?.value;

    wrap.innerHTML = emptyState({
      icon: hasFilter ? "search" : "users",
      title: hasFilter ? "لا توجد نتائج مطابقة" : "لا توجد حسابات مسجلة",
      hint: hasFilter ? "جرّب تغيير كلمات البحث أو خيارات التصفية." : "يمكنك إضافة أول حساب بالضغط على «إضافة حساب» أعلاه."
    });
    return;
  }

  const heads = ["اسم المستخدم", "الاسم الظاهر", "الصلاحية", "الحالة", "آخر دخول", "أنشأه", "إجراءات"];
  wrap.innerHTML = `
    <div class="table-scroll">
      ${mtable(heads, list.map(userRow))}
    </div>
    <div class="count">عدد الحسابات: ${list.length} ${list.length !== USERS.length ? `(من إجمالي ${USERS.length})` : ""}</div>
  `;
}

async function loadUsers() {
  const wrap = $("#usersWrap");
  wrap.innerHTML = skeleton("rows", 6);

  const res = await api("/api/users");
  if (!res) {
    wrap.innerHTML = emptyState({
      icon: "alert",
      title: "تعذر تحميل قائمة الحسابات",
      hint: "حدث خطأ أثناء جلب الحسابات من الخادم.",
      action: '<button type="button" class="btn" id="retryUsersBtn">إعادة المحاولة</button>'
    });
    $("#retryUsersBtn")?.addEventListener("click", loadUsers);
    return;
  }

  USERS = res.users || [];
  render();
}

// ── فتح نافذة إضافة حساب ──
$("#btnAddUser").onclick = () => {
  clearModalError("userCreateError");
  const form = $("#userCreateForm");
  form.reset();
  $("#createMustChange").checked = true;
  openModal("userCreateModal");
};

// ── حفظ حساب جديد ──
$("#userCreateForm").onsubmit = async e => {
  e.preventDefault();
  clearModalError("userCreateError");

  const username = ($("#createUsername")?.value || "").trim();
  const displayName = ($("#createDisplayName")?.value || "").trim();
  const role = $("#createRole")?.value || "";
  const password = $("#createPassword")?.value || "";
  const mustChange = $("#createMustChange")?.checked ?? true;

  if (!username || !displayName || !role || !password) {
    showModalError("userCreateError", "يرجى استيفاء جميع الحقول المطلوبة");
    return;
  }
  if (password.length < 8) {
    showModalError("userCreateError", "يجب ألا تقل كلمة المرور عن ٨ أحرف");
    return;
  }

  const submitBtn = $("#createSubmitBtn");
  submitBtn.disabled = true;

  let errorCode = null;
  const res = await api("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      display_name: displayName,
      role,
      password,
      must_change_password: mustChange
    }),
    onError: (out, status) => {
      errorCode = out?.code;
      const msg = getErrorMessage(out?.code, out?.error);
      showModalError("userCreateError", msg);
      return true; // منع التوست الافتراضي
    }
  });

  submitBtn.disabled = false;

  if (res && res.user) {
    markModalSaved("userCreateModal");
    closeModal("userCreateModal", true);
    showToast("تم إنشاء الحساب بنجاح");
    await loadUsers();
  }
};

// ── إجراء تعديل حساب ──
function openEditModal(userId) {
  const u = USERS.find(x => String(x.id) === String(userId));
  if (!u) return;

  clearModalError("userEditError");
  $("#editUserId").value = u.id;
  $("#editUsernameDisplay").value = u.username;
  $("#editDisplayName").value = u.display_name || "";
  $("#editRole").value = u.role || "officer";

  openModal("userEditModal");
}

$("#userEditForm").onsubmit = async e => {
  e.preventDefault();
  clearModalError("userEditError");

  const userId = $("#editUserId").value;
  const displayName = ($("#editDisplayName")?.value || "").trim();
  const role = $("#editRole")?.value || "";

  if (!displayName || !role) {
    showModalError("userEditError", "يرجى ملء جميع الحقول المطلوبة");
    return;
  }

  const submitBtn = $("#editSubmitBtn");
  submitBtn.disabled = true;

  const res = await api(`/api/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      display_name: displayName,
      role
    }),
    onError: (out, status) => {
      const msg = getErrorMessage(out?.code, out?.error);
      showModalError("userEditError", msg);
      return true;
    }
  });

  submitBtn.disabled = false;

  if (res && res.user) {
    markModalSaved("userEditModal");
    closeModal("userEditModal", true);
    showToast("تم حفظ تعديلات الحساب بنجاح");
    await loadUsers();
  }
};

// ── إجراء إيقاف / تفعيل الحساب ──
async function toggleUserActive(userId) {
  const u = USERS.find(x => String(x.id) === String(userId));
  if (!u) return;

  const willActive = !u.active;
  const actionText = willActive ? "تفعيل" : "إيقاف";

  const confirmed = await confirmDialog({
    title: `${actionText} حساب ${u.display_name}`,
    body: willActive
      ? `هل تريد تفعيل حساب «${u.display_name}» (@${u.username})؟ سيتمكن صاحب الحساب من تسجيل الدخول فورًا.`
      : `هل تريد إيقاف حساب «${u.display_name}» (@${u.username})؟ لن يتمكن صاحب الحساب من الدخول حتى يُعاد تفعيله.`,
    confirmLabel: `${actionText} الحساب`,
    danger: !willActive
  });

  if (!confirmed) return;

  const res = await api(`/api/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active: willActive }),
    onError: (out, status) => {
      if (out?.code === "last_admin" || out?.code === "cannot_disable_self") {
        showToast(getErrorMessage(out.code, out.error), true);
        return true;
      }
      return false;
    }
  });

  if (res && res.user) {
    showToast(`تم ${actionText} الحساب بنجاح`);
    await loadUsers();
  }
}

// ── إجراء إعادة تعيين كلمة المرور ──
function openResetModal(userId) {
  const u = USERS.find(x => String(x.id) === String(userId));
  if (!u) return;

  clearModalError("userResetError");
  $("#resetUserId").value = u.id;
  $("#resetUserInfo").innerHTML = `إعادة تعيين كلمة المرور لحساب <strong>${esc(u.display_name)}</strong> (@${esc(u.username)})`;
  $("#resetNewPassword").value = "";
  $("#resetMustChange").checked = true;

  openModal("userResetPasswordModal");
}

$("#userResetPasswordForm").onsubmit = async e => {
  e.preventDefault();
  clearModalError("userResetError");

  const userId = $("#resetUserId").value;
  const password = $("#resetNewPassword")?.value || "";
  const mustChange = $("#resetMustChange")?.checked ?? true;

  if (!password) {
    showModalError("userResetError", "يرجى إدخال كلمة المرور الجديدة");
    return;
  }
  if (password.length < 8) {
    showModalError("userResetError", "يجب ألا تقل كلمة المرور عن ٨ أحرف");
    return;
  }

  const submitBtn = $("#resetSubmitBtn");
  submitBtn.disabled = true;

  const res = await api(`/api/users/${encodeURIComponent(userId)}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      password,
      must_change_password: mustChange
    }),
    onError: (out, status) => {
      const msg = getErrorMessage(out?.code, out?.error);
      showModalError("userResetError", msg);
      return true;
    }
  });

  submitBtn.disabled = false;

  if (res && res.ok) {
    markModalSaved("userResetPasswordModal");
    closeModal("userResetPasswordModal", true);
    showToast("تمت إعادة تعيين كلمة المرور بنجاح");
  }
};

// ── تسجيل الإجراءات في ACTIONS ──
ACTIONS.editUser = id => openEditModal(id);
ACTIONS.toggleUser = id => toggleUserActive(id);
ACTIONS.resetUserPassword = id => openResetModal(id);

// ── أحداث التصفية والبحث ──
$("#userRoleFilter").onchange = render;
$("#userStatusFilter").onchange = render;

$("#userSearch").addEventListener("input", () => {
  clearTimeout(SEARCH_TIMER);
  SEARCH_TIMER = setTimeout(render, 200);
});

loadUsers();
