"""الأدوار والصلاحيات الثابتة لطبقة الدخول."""

ROLE_LABELS = {
    "admin": "ادمن",
    "officer": "ضابط",
    "individual": "فرد",
    "conscript": "مجند",
}

ROLE_CAPABILITIES = {
    "admin": {"view_logs", "manage_users"},
    "officer": {"view_logs"},
    "individual": set(),
    "conscript": set(),
}


def capabilities(role):
    return sorted(ROLE_CAPABILITIES.get(role, ()))


def can(role, capability):
    return capability in ROLE_CAPABILITIES.get(role, ())
