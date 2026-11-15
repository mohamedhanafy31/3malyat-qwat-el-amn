/* بحث داخل اليوميات (التفصيلية، الضباط، الأفراد، الحملة، اعداد الخدمات).
   - بيدوّر في كل صف: اسم + خدمة + محتوى التشغيل + قيم الحقول المختارة.
   - الكلمات المتعددة لازم كلها تتلاقي في نفس الصف؛ الهمزات والتشكيل والأرقام العربية بتتوحّد.
   - النتيجة: الصف بيتلوّن (مش بيعتمد على ألوان الصفحة)، والكلمة جوّاه بتتظلل من غير تعديل
     الـDOM (CSS Custom Highlight)، وقايمة نتايج بالقسم والمقتطف بتنقلك للصف، وخيار «المطابق فقط».
   - الشريط بيلزق تحت الترويسة لما تنزل بالصفحة، و«/» بتفتحه من أي مكان. */
(() => {
  const HL = "page-search", HL_CUR = "page-search-current";
  const SKIP = "script,style,button,svg,.sr-only,.page-search";
  const MAX_LIST = 40;

  const DIGITS = {"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"};
  const FOLD = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"};
  const DROP = /[\u064B-\u065F\u0670\u0640\u200E\u200F]/;   // تشكيل، تطويل، علامات اتجاه

  /* النص موحّدًا + خريطة من موضع الحرف الموحّد لموضعه في الأصل */
  function fold(text) {
    let out = "";
    const map = [];
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (DROP.test(ch)) continue;
      out += (DIGITS[ch] ?? FOLD[ch] ?? ch).toLowerCase();
      map.push(i);
    }
    return {text: out, map};
  }
  const plain = text => fold(text).text.replace(/\s+/g, " ").trim();
  const squash = text => text.replace(/\s+/g, " ").trim();

  /* النص الخام للصف (للمقتطف) — نفس ترتيب القراءة، مع قيم الحقول المختارة */
  function rowRaw(tr) {
    const parts = [];
    const walker = document.createTreeWalker(tr, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === 1 && node.matches(SKIP)) return NodeFilter.FILTER_REJECT;
        if (node.nodeType === 1 && node.matches("select,textarea")) return NodeFilter.FILTER_ACCEPT;
        return NodeFilter.FILTER_ACCEPT;
      }});
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === 3) parts.push(node.nodeValue);
      else if (node.matches("input:not([type=checkbox]):not([type=radio]):not([type=hidden])")) parts.push(node.value);
      else if (node.matches("select")) parts.push([...node.selectedOptions].map(o => o.textContent).join(" "));
      else if (node.matches("textarea")) parts.push(node.value);
    }
    return squash(parts.join(" "));
  }

  function sectionOf(tr) {
    const card = tr.closest(".mcard, .panel");
    const head = card && card.querySelector(":scope > h3, :scope > .panel-head h2, :scope > h2");
    return head ? squash(head.textContent).replace(/\s*\d+\s*$/, "") : "";
  }

  function init(box) {
    const root = document.querySelector(box.dataset.searchRoot);
    const input = box.querySelector(".page-search-input");
    const count = box.querySelector(".page-search-count");
    const prev = box.querySelector(".page-search-prev");
    const next = box.querySelector(".page-search-next");
    const filterLabel = box.querySelector(".page-search-filter");
    const filter = filterLabel.querySelector("input");
    const list = box.querySelector(".page-search-list");
    if (!root || !input) return;
    const canRanges = "highlights" in CSS && typeof Highlight === "function";
    let hits = [], current = -1, timer = 0, jump = false, filtering = false;

    /* مرساة صفرية الحجم: لما تطلع برّه الشاشة الشريط يتحوّل للصق تحت الترويسة */
    const anchor = document.createElement("span");
    anchor.className = "page-search-anchor";
    box.before(anchor);
    const topbar = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 60;
    const bar = box.querySelector(".page-search-box");
    function syncFloat() {
      const floating = anchor.getBoundingClientRect().top < topbar;
      if (floating && !bar.classList.contains("is-floating")) {
        const rect = bar.getBoundingClientRect();   // الغلاف يحتفظ بمكانه عشان الأدوات ما تتحركش
        box.style.minWidth = rect.width + "px";
      }
      bar.classList.toggle("is-floating", floating);
    }
    window.addEventListener("scroll", syncFloat, {passive: true});
    window.addEventListener("resize", syncFloat);
    syncFloat();

    const rows = () => [...root.querySelectorAll("tr")].filter(tr => tr.querySelector("td"));

    function clear() {
      root.querySelectorAll("tr.search-hit,tr.search-miss").forEach(tr => tr.classList.remove("search-hit", "search-current", "search-miss"));
      root.querySelectorAll(".search-card-empty").forEach(card => card.classList.remove("search-card-empty"));
      if (canRanges) { CSS.highlights.delete(HL); CSS.highlights.delete(HL_CUR); }
    }

    function ranges(tr, terms) {
      const found = [];
      const walker = document.createTreeWalker(tr, NodeFilter.SHOW_TEXT, {
        acceptNode: node => node.parentElement && node.parentElement.closest(SKIP)
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const {text, map} = fold(node.nodeValue);
        for (const term of terms) {
          for (let at = text.indexOf(term); at !== -1; at = text.indexOf(term, at + term.length)) {
            const range = new Range();
            range.setStart(node, map[at]);
            range.setEnd(node, map[at + term.length - 1] + 1);
            found.push(range);
          }
        }
      }
      return found;
    }

    /* مقتطف ~60 حرف حوالين أول تطابق، مع تظليل الكلمات */
    function snippet(raw, terms) {
      const {text, map} = fold(raw);
      let at = -1;
      for (const term of terms) { const i = text.indexOf(term); if (i !== -1 && (at === -1 || i < at)) at = i; }
      if (at === -1) return esc(raw.slice(0, 70));
      const from = Math.max(0, map[at] - 24);
      const slice = raw.slice(from, from + 80);
      const folded = fold(slice);
      const marks = [];
      for (const term of terms) {
        for (let i = folded.text.indexOf(term); i !== -1; i = folded.text.indexOf(term, i + term.length)) {
          marks.push([folded.map[i], folded.map[i + term.length - 1] + 1]);
        }
      }
      marks.sort((a, b) => a[0] - b[0]);
      let out = "", pos = 0;
      for (const [s, e] of marks) {
        if (s < pos) continue;
        out += esc(slice.slice(pos, s)) + `<mark>${esc(slice.slice(s, e))}</mark>`;
        pos = e;
      }
      return (from ? "… " : "") + out + esc(slice.slice(pos)) + (from + 80 < raw.length ? " …" : "");
    }
    const esc = text => text.replace(/[&<>"]/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[ch]));

    function renderList(terms) {
      if (!hits.length) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
      const items = hits.slice(0, MAX_LIST).map((tr, i) => {
        const cells = [...tr.children];
        const name = squash(cells.find(c => squash(c.textContent))?.textContent || "").slice(0, 48);
        return `<button type="button" role="option" class="page-search-item${i === current ? " is-current" : ""}" data-i="${i}">
          <span class="psi-head"><b>${esc(name || "—")}</b>${sectionOf(tr) ? `<small>${esc(sectionOf(tr))}</small>` : ""}</span>
          <span class="psi-text">${snippet(rowRaw(tr), terms)}</span></button>`;
      });
      if (hits.length > MAX_LIST) items.push(`<div class="page-search-more">و${hits.length - MAX_LIST} نتيجة أخرى — استخدم Enter للتنقل</div>`);
      list.innerHTML = items.join("");
      list.hidden = document.activeElement !== input && !list.matches(":hover");
      input.setAttribute("aria-expanded", String(!list.hidden));
    }

    function paint() {
      const query = plain(input.value);
      const terms = query ? query.split(" ") : [];
      clear();
      hits = [];
      if (terms.length) {
        const all = rows();
        for (const tr of all) {
          const text = plain(rowRaw(tr));
          if (terms.every(term => text.includes(term))) { hits.push(tr); tr.classList.add("search-hit"); }
          else if (filtering) tr.classList.add("search-miss");
        }
        if (filtering) {
          root.querySelectorAll(".mcard").forEach(card => {
            if (!card.querySelector("tr.search-hit")) card.classList.add("search-card-empty");
          });
        }
      }
      if (canRanges && hits.length) {
        const all = new Highlight();
        hits.forEach(tr => ranges(tr, terms).forEach(range => all.add(range)));
        CSS.highlights.set(HL, all);
      }
      if (current >= hits.length) current = hits.length - 1;
      if (current < 0 && hits.length) current = 0;
      const on = !!terms.length;
      count.hidden = !on;
      filterLabel.hidden = !on;
      prev.hidden = next.hidden = !(on && hits.length > 1);
      count.classList.toggle("is-empty", on && !hits.length);
      renderList(terms);
      mark(jump);
      jump = false;
    }

    function mark(scroll) {
      hits.forEach((tr, i) => tr.classList.toggle("search-current", i === current));
      const terms = plain(input.value).split(" ").filter(Boolean);
      if (canRanges) {
        CSS.highlights.delete(HL_CUR);
        const tr = hits[current];
        if (tr && terms.length) {
          const cur = new Highlight();
          ranges(tr, terms).forEach(range => cur.add(range));
          CSS.highlights.set(HL_CUR, cur);
        }
      }
      list.querySelectorAll(".page-search-item").forEach(item =>
        item.classList.toggle("is-current", Number(item.dataset.i) === current));
      list.querySelector(".is-current")?.scrollIntoView({block: "nearest"});
      count.textContent = !terms.length ? "" : hits.length ? `${current + 1} من ${hits.length}` : "لا توجد نتائج";
      if (scroll && hits[current]) {
        hits[current].scrollIntoView({block: "center", behavior:
          matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
      }
    }

    function step(delta) {
      if (!hits.length) return;
      current = (current + delta + hits.length) % hits.length;
      mark(true);
    }

    const schedule = () => { clearTimeout(timer); timer = setTimeout(paint, 120); };
    input.addEventListener("input", () => { current = -1; jump = true; schedule(); });
    input.addEventListener("focus", () => { if (hits.length) { list.hidden = false; input.setAttribute("aria-expanded", "true"); } });
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") { event.preventDefault(); if (hits.length) step(event.shiftKey ? -1 : 1); else paint(); }
      else if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); step(event.key === "ArrowDown" ? 1 : -1); }
      else if (event.key === "Escape") {
        if (!list.hidden) { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
        else { input.value = ""; current = -1; jump = false; paint(); input.blur(); }
      }
    });
    document.addEventListener("click", event => { if (!box.contains(event.target)) list.hidden = true; });
    list.addEventListener("click", event => {
      const item = event.target.closest(".page-search-item");
      if (!item) return;
      current = Number(item.dataset.i);
      mark(true);
      list.hidden = true;
    });
    prev.addEventListener("click", () => step(-1));
    next.addEventListener("click", () => step(1));
    filter.addEventListener("change", () => { filtering = filter.checked; paint(); });
    document.addEventListener("keydown", event => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.target.closest && event.target.closest("input,textarea,select,[contenteditable=true]")) return;
      if (document.querySelector(".modal:not(.hidden)")) return;
      event.preventDefault();
      input.focus({preventScroll: true}); input.select();
    });

    /* الصفحة بتعيد رسم الجداول بعد كل حفظ/تحميل — نعيد التلوين من غير ما نقفز لنتيجة */
    new MutationObserver(() => { if (input.value.trim()) schedule(); })
      .observe(root, {childList: true, subtree: true});
  }

  document.querySelectorAll("[data-page-search]").forEach(init);
})();
