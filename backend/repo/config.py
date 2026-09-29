"""الإعدادات وسجل التغييرات — المفاتيح المفردة اللي مش قوايم كيانات.

`command` و`service_tags` و`counts_template` كلها إعدادات على مستوى
النظام. مجمّعين هنا بدل ما كل واحد يتلمس من مكان مختلف.
"""
from ..constants import COMMAND_ROLES, GROUP_ROLES
from ..models import MAX_ENTRIES, ChangeEntry, CountEntry
from .base import Repo


class ConfigRepo:
    def __init__(self, data):
        self.data = data

    # ---------- قيادة الإدارة — مناصب فردية (مدير/وكيل الإدارة) ----------

    def command(self):
        holder = self.data.setdefault("command", {})
        for role in COMMAND_ROLES:
            holder.setdefault(role, None)
        return holder

    def holder_of(self, role):
        return self.command().get(role)

    def role_of(self, officer_id):
        """المنصب القيادي الفردي اللي الضابط شايله — أو None."""
        return next((r for r, oid in self.command().items() if oid == officer_id), None)

    def assign_command(self, role, officer_id):
        self.command()[role] = officer_id or None

    def clear_command(self, officer_id):
        """يفضّي أي منصب قيادي فردي الضابط ده شايله."""
        for role, holder in self.command().items():
            if holder == officer_id:
                self.data["command"][role] = None

    # ---------- قيادة الإدارة — مناصب جماعية (طبي/بحث) ----------

    def groups(self):
        groups = self.data.setdefault("command_groups", {})
        for role in GROUP_ROLES:
            groups.setdefault(role, [])
        return groups

    def group(self, role):
        return self.groups().get(role, [])

    def group_roles_of(self, officer_id):
        """كل المناصب الجماعية اللي الضابط ده عضو فيها."""
        return [role for role, ids in self.groups().items() if officer_id in ids]

    def assign_group(self, role, officer_ids):
        """بيستبدل أعضاء المنصب الجماعي بالكامل — مكرّرات بتتشال، والترتيب
        بيفضل زي ما اتبعت (نفس ترتيب الاختيار في الواجهة)."""
        self.groups()[role] = list(dict.fromkeys(officer_ids))

    def remove_from_groups(self, officer_id):
        """يشيل الضابط ده من أي منصب جماعي عضو فيه — بيتنادى لما يخرج من
        القوة أو يتحذف نهائيًا، زي `clear_command` بالظبط للمناصب الفردية.
        بترجّع عدد المناصب اللي اتشال منها — للاستخدام في تقرير الحذف."""
        removed = 0
        for role, ids in self.groups().items():
            if officer_id in ids:
                self.data["command_groups"][role] = [i for i in ids if i != officer_id]
                removed += 1
        return removed

    # ---------- وسوم الخدمات ----------

    def tags(self):
        return self.data.setdefault("service_tags", [])

    def add_tags(self, tags):
        known = self.tags()
        for tag in tags:
            if tag and tag not in known:
                known.append(tag)

    # ---------- قالب اعداد الخدمات ----------

    def template(self):
        return [CountEntry.from_dict(e) for e in self.template_rows()]

    def template_rows(self):
        """القايمة المخزّنة نفسها — بتتعمل لو مش موجودة."""
        return self.data.setdefault("counts_template", {}).setdefault("entries", [])

    def peek_template(self):
        """للقراءة المجردة — من غير ما تعمل مدخل في ملف لسه مافيهوش القالب."""
        return (self.data.get("counts_template") or {}).get("entries", [])

    def save_template(self, entries):
        self.data.setdefault("counts_template", {})["entries"] = [
            e.as_dict() for e in entries]


class ChangeRepo(Repo):
    """سجل التغييرات — إلحاقي ومسقوف.

    مسقوف بعدد ثابت زي `store.BACKUP_KEEP` بالظبط عشان الملف ما يكبرش من
    غير حد؛ أقدم سجل بيتشال لما العدد يعدّي السقف.
    """
    KEY = "change_log"
    MODEL = ChangeEntry

    def record(self, entity, entity_id, action, before=None, after=None,
               reason="", day=None, text="", ts=None):
        """بيسجّل تغيير واحد ويرجّعه.

        `ts` بيتحدد من برّه لما كذا تغيير يتسجّلوا كوحدة واحدة (تأكيد
        اليومية مثلًا) — كلهم لازم يحملوا **نفس** اللحظة.
        """
        from datetime import datetime

        entry = ChangeEntry(
            id=self.new_id(),
            ts=ts or datetime.now().isoformat(timespec="seconds"),
            entity=entity, entity_id=entity_id, action=action,
            day=day, text=text, before=before, after=after, reason=reason,
            edited_by=_edited_by() or None)
        rows = self.rows()
        rows.append(entry.as_dict())
        if len(rows) > MAX_ENTRIES:
            del rows[:len(rows) - MAX_ENTRIES]
        self._invalidate()
        return entry

    def recent(self, limit=200, entity=None, entity_id=None, day=None):
        """أحدث التغييرات أولًا، قابلة للتصفية."""
        out = self.rows()
        if entity:
            out = [e for e in out if e.get("entity") == entity]
        if entity_id:
            out = [e for e in out if e.get("entity_id") == entity_id]
        if day:
            out = [e for e in out if e.get("day") == day]
        return list(reversed(out))[:limit]


def _edited_by():
    """اسم المشغّل من ترويسة X-Edited-By. الفرونت بيبعته مشفّر
    (`encodeURIComponent`) لأن ترويسة HTTP لازم تبقى ISO-8859-1 بس،
    والاسم هنا غالبًا عربي."""
    from urllib.parse import unquote
    try:
        from flask import request
        return unquote(request.headers.get("X-Edited-By", "")).strip()
    except RuntimeError:
        return ""          # نداء بره سياق طلب HTTP
