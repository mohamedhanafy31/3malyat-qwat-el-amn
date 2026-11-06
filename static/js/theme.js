/* الوضع الداكن — الاختيار المحفوظ (light/dark) أو تفضيل النظام لو ما اختارش.
   data-theme على <html> بيتحدد قبل أول رسم من السكريبت الصغير في partials/styles.html؛
   الملف ده بس بيشغّل الزرار ويحفظ الاختيار ويتابع تغيير تفضيل النظام. */
(function () {
  "use strict";
  const KEY = "theme";
  const root = document.documentElement;
  const query = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  const stored = () => {
    try { const v = localStorage.getItem(KEY); return v === "dark" || v === "light" ? v : null; }
    catch (err) { return null; }
  };
  const systemTheme = () => (query && query.matches ? "dark" : "light");
  const current = () => (root.getAttribute("data-theme") === "dark" ? "dark" : "light");

  function paintButton() {
    const button = document.getElementById("themeToggle");
    if (button) button.setAttribute("aria-pressed", String(current() === "dark"));
  }

  function apply(theme, persist) {
    root.setAttribute("data-theme", theme);
    if (persist) { try { localStorage.setItem(KEY, theme); } catch (err) { /* التخزين ممنوع: الاختيار بيفضل للصفحة دي بس */ } }
    paintButton();
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  document.addEventListener("click", event => {
    if (event.target.closest("#themeToggle")) apply(current() === "dark" ? "light" : "dark", true);
  });
  // لو المستخدم ما اختارش بنفسه، الصفحة بتتبع تفضيل النظام لحظيًا
  if (query) query.addEventListener("change", () => { if (!stored()) apply(systemTheme(), false); });
  // المتصفح مابيبعتش حدث التغيير للتبويب المخفي: لو النظام بدّل أثناء ما الصفحة في
  // الخلفية، بنلحق عند رجوعها للواجهة (لو ما فيش اختيار محفوظ).
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !stored() && current() !== systemTheme()) apply(systemTheme(), false);
  });
  // تبويب تاني غيّر الاختيار
  window.addEventListener("storage", event => {
    if (event.key === KEY) apply(stored() || systemTheme(), false);
  });
  paintButton();
})();
