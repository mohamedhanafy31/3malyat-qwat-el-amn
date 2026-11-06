"""الوضع الداكن: كل رمز لوني له نسخة داكنة، والأسطح المصمتة ما بتعتمدش على درجات النص،
والتبديل بيتحدد قبل أول رسم، والطباعة ما بتتأثرش."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css"
TOKENS = (CSS / "tokens.css").read_text(encoding="utf-8")

# ألوان ثابتة في الوضعين عن قصد: نص فوق الأسطح المصمتة الغامقة (الترويسة، الأزرار)
# وذهبي الحدود الفاتح فوقها. الباقي لازم يتعرّف في الداكن.
SAME_IN_BOTH_MODES = {
    "--on-dark", "--on-dark-muted", "--on-dark-soft", "--on-dark-placeholder",
    "--on-dark-wash", "--on-dark-muted-wash", "--border-on-dark", "--gold-300",
}


def _declarations(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def _light_and_dark():
    light = re.search(r":root\{(.*?)\n\}", TOKENS, re.S).group(1)
    dark = re.search(r':root\[data-theme="dark"\]\{(.*?)\n\}', TOKENS, re.S).group(1)
    return _declarations(light), _declarations(dark)


def test_every_literal_color_token_has_a_dark_version():
    light, dark = _light_and_dark()
    literal = {name for name, value in light.items() if re.match(r"\s*(#|rgba?\()", value)}

    missing = sorted(literal - set(dark) - SAME_IN_BOTH_MODES)

    assert not missing, ("رموز لونية في :root من غير نسخة داكنة في tokens.css: " + ", ".join(missing))


def test_dark_block_only_overrides_tokens_that_exist_in_light_mode():
    light, dark = _light_and_dark()

    assert sorted(set(dark) - set(light) - {"color-scheme"}) == []


def test_dark_theme_is_screen_only_so_printing_stays_light():
    start = TOKENS.index(':root[data-theme="dark"]')
    assert TOKENS[:start].rstrip().endswith("@media screen{")
    assert "color-scheme:dark" in TOKENS[start:start + 200]


def test_solid_navy_backgrounds_use_fill_tokens_not_text_tokens():
    """--navy-* بتنعكس (فاتحة) في الداكن لأنها لون نص؛ الخلفيات الغامقة لازم --fill-*."""
    offenders = []
    for name in ("base", "layout", "components", "pages", "modules", "responsive"):
        text = (CSS / f"{name}.css").read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"background(?:-color)?\s*:\s*var\(--navy-(950|900|800|700|600|500)\)", line):
                offenders.append(f"{name}.css:{number}")

    assert not offenders, "background بدرجة كحلي غامقة (استخدم --fill-N): " + ", ".join(offenders)


def test_page_head_decides_the_theme_before_any_stylesheet():
    html = (ROOT / "templates" / "partials" / "styles.html").read_text(encoding="utf-8")

    assert html.index("data-theme") < html.index("stylesheet")
    assert 'localStorage.getItem("theme")' in html
    assert "prefers-color-scheme: dark" in html


def test_every_standalone_page_loads_the_theme_boot_script():
    for template in ("base.html", "login.html", "setup.html"):
        source = (ROOT / "templates" / template).read_text(encoding="utf-8")
        assert 'partials/styles.html' in source, template


def test_topbar_has_an_accessible_theme_toggle(client):
    html = client.get("/officers").get_data(as_text=True)

    assert 'id="themeToggle"' in html
    assert 'aria-pressed="false"' in html
    assert "js/theme.js" in html
    assert "#i-moon" in html and "#i-sun" in html


def test_theme_script_persists_only_an_explicit_choice_and_follows_the_system():
    source = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")

    assert 'const KEY = "theme"' in source
    assert "localStorage.setItem(KEY, theme)" in source
    assert "if (!stored()) apply(systemTheme(), false)" in source  # اختيار صريح يغلب النظام
    assert "themechange" in source
    assert "visibilitychange" in source  # حدث النظام بيضيع لو التبويب مخفي


def test_stats_charts_reload_on_theme_change_because_colors_are_read_once():
    source = (ROOT / "static" / "js" / "charts.js").read_text(encoding="utf-8")

    assert '"themechange"' in source and "location.reload()" in source
