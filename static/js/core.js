/* أدوات مشتركة بين كل الصفحات — بتتحمّل مرة واحدة في base.html.
   كل صفحة بعدها بتحمّل ملفها هي بس، مش منطق النظام كله. */

const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const PAGE=document.body.dataset.page;

const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
// بيانات حرة (اسم/ملاحظة/وسم) بتتحط جوه data-* attribute بدل onclick="fn('...')" —
// المتصفح بيفك تشفير HTML بتاع الـattribute قبل ما يجمّع أي onclick كـJS، وده كان
// بيلغي تأثير esc() ويسمح بحقن سكريبت من أي حقل حر. القيم هنا بتتقرأ JSON.parse بس.
const dataAttr=obj=>esc(JSON.stringify(obj));
function icon(name,opts={}){
  const extra=typeof opts==="string"?opts:(opts.className||"");
  const cls=`ico${extra?` ${extra}`:""}`;
  return `<svg class="${esc(cls)}" aria-hidden="true" focusable="false"><use href="#i-${esc(name)}"></use></svg>`;
}

/* ---------- تطبيع النص العربي ----------
   نسخة مطابقة لـ backend/text.py norm() — الحرف الواحد بيتكتب بأكتر من صورة
   (أحمد/احمد، عيسى/عيسي، فاطمة/فاطمه)، والبحث بالمطابقة الحرفية كان بيدّي
   نتايج مختلفة تمامًا حسب اللي المستخدم كتبه: «أحمد» كانت بتجيب 43 نتيجة
   و«احمد» بتجيب 86، و«عيسى» ما بتجيبش حاجة. للمطابقة بس مش للعرض. */
const _AR_DIACRITICS = /[ؐ-ًؚ-ٰٟۖ-ۭـ]/g;
const _AR_FOLD = [[/[أإآٱ]/g, "ا"], [/ى/g, "ي"], [/ة/g, "ه"], [/ؤ/g, "و"], [/ئ/g, "ي"]];
function normAr(s) {
  let t = String(s ?? "").replace(_AR_DIACRITICS, "");
  for (const [re, to] of _AR_FOLD) t = t.replace(re, to);
  return t.replace(/\s+/g, " ").trim().toLowerCase();
}
/** هل النص ده بيحتوي على البحث ده، بغض النظر عن صورة الحروف؟ */
const arIncludes = (haystack, needle) => normAr(haystack).includes(normAr(needle));

/* ---------- التواريخ ----------
   `toLocaleDateString` بيبني كائن Intl.DateTimeFormat جديد في **كل نداء**،
   وده أغلى بكتير من التنسيق نفسه. جدول الراحات بينادي fmt/dayName حوالي 6
   مرات للصف الواحد، فـ280 صف = ~1700 نداء وكل واحد بيعمل كائن جديد: 85
   مللي من أصل 99 مللي بتاعة رسم الجدول كانت بناء منسّقات مش عرض بيانات.

   المنسّق بيتبني مرة واحدة، والنتيجة بتتخزّن على نص التاريخ نفسه (التواريخ
   بتتكرر كتير — 90 تاريخ مختلف بس في 280 راحة). النتيجة حرفيًا نفسها.

   Intl جزء من المتصفح نفسه (ECMA-402) — مفيش أي طلب شبكة ولا مكتبة خارجية،
   ونفس اللي `toLocaleDateString` كان بيستخدمه أصلًا. */
const _FMT_DATE=new Intl.DateTimeFormat("ar-EG-u-nu-latn",{day:"numeric",month:"short",year:"numeric"});
const _FMT_WEEKDAY=new Intl.DateTimeFormat("ar-EG-u-nu-latn",{weekday:"long"});
const _fmtCache=new Map(), _wdCache=new Map();
const fmt=d=>{
  if(!d) return "-";
  let v=_fmtCache.get(d);
  if(v===undefined){ v=_FMT_DATE.format(new Date(d+"T00:00:00")); _fmtCache.set(d,v) }
  return v;
};
const fmtShort=d=>{
  if(!d) return "-";
  const parts=d.split("-");
  return `${Number(parts[2])}/${Number(parts[1])}`;
};
const humanizeDates=text=>String(text??"").replace(/\b\d{4}-\d{2}-\d{2}\b/g,fmt);
const iso=d=>{const t=new Date(d);t.setHours(12);return t.toISOString().slice(0,10)};
const addDays=(s,n)=>{const d=new Date(s+"T12:00:00");d.setDate(d.getDate()+n);return iso(d)};
const dayName=s=>{
  // كانت بتفضل من غير حراسة زي fmt() جنبها — أي نداء بتاريخ فاضي كان بيرمي
  // "Invalid time value" ويوقف الدالة اللي نادتها في نص تنفيذها. ده كان
  // بيكسر نافذة تفاصيل الالتحاق بصمت لأي التحاق من غير تاريخ بداية/نهاية
  // مسجّل (أغلب فرق الأرشيف)، لأن الزرار بيحدّث العنوان الأول قبل ما يوصل
  // لنداء dayName ويقف من غير ما المستخدم يشوف أي رسالة خطأ.
  if(!s) return "-";
  let v=_wdCache.get(s);
  if(v===undefined){ v=_FMT_WEEKDAY.format(new Date(s+"T12:00:00")); _wdCache.set(s,v) }
  return v;
};
const days=(a,b)=>Math.round((new Date(b)-new Date(a))/864e5)+1;

/** يؤجّل نداء متكرر لحد ما المستخدم يهدى — للكتابة في خانات البحث.
    كل ضغطة زرار كانت بتعيد رسم الجدول كامل. */
function debounce(fn,ms=120){
  let t;
  return (...args)=>{ clearTimeout(t); t=setTimeout(()=>fn(...args),ms) };
}

/* ---------- الرتب ---------- */
const OFFICER_ROLES=["ملازم","ملازم أول","نقيب","رائد","مقدم","عقيد","عميد","لواء","أخرى"];
const RANK_ORDER=["لواء","عميد","عقيد","مقدم","رائد","نقيب","ملازم أول","ملازم"];
const rankIndex=role=>{const i=RANK_ORDER.indexOf(role); return i<0?RANK_ORDER.length:i};
const PERSONNEL_ROLES=[
  "أمين شرطة ممتاز أول","أمين شرطة ممتاز ثان","أمين شرطة ممتاز ثالث","أمين شرطة ممتاز",
  "أمين شرطة أول","أمين شرطة ثان","أمين شرطة ثالث","أمين شرطة",
  "مساعد شرطة أول","مساعد شرطة ثان","مساعد شرطة ثالث","مساعد شرطة",
  "معاون شرطة ثان","معاون شرطة ثالث","معاون شرطة",
  "رقيب شرطة أول","رقيب شرطة","مراقب شرطة ثالث","مندوب شرطة","عريف شرطة","شرطي"
];

/* ---------- الحالة المشتركة ---------- */
let META={}, COUNTS={};
const curDate=()=>META.today||new Date().toISOString().slice(0,10);
const REST_SYSTEMS=()=>META.rest_systems||["أسبوعية","نصف شهرية","شهرية","—"];
const WEEKDAYS=()=>META.weekdays||[];
const LEAVE_TYPES=()=>META.leave_types||[];
const DURATIONS=()=>META.rest_durations||{"شهرية":7,"نصف شهرية":3,"أسبوعية":1};
const KINDS=()=>META.service_kinds||["خارجية","داخلية","حراسات","طبية"];
const SHIFTS=()=>META.shifts||["صباحية","ليلية"];
const COMMAND_ROLES=()=>META.command_roles||[];
const GROUP_ROLES=()=>META.group_roles||[];
const KIND_CLS={"خارجية":"w","داخلية":"h","حراسات":"m","طبية":"on","بحث":"soon"};

/* ---------- الشبكة ---------- */
function showToast(msg,bad){
  const stack=$("#toast");
  if(!stack) return;
  const item=document.createElement("div");
  item.className=`toast-item${bad?" bad":""}`;
  item.setAttribute("role",bad?"alert":"status");
  item.setAttribute("aria-live",bad?"assertive":"polite");
  const message=document.createElement("span");
  message.className="toast-message";
  message.textContent=humanizeDates(msg);
  item.appendChild(message);
  if(bad){
    const close=document.createElement("button");
    close.type="button"; close.className="toast-close";
    close.setAttribute("aria-label","إغلاق التنبيه"); close.textContent="×";
    close.onclick=()=>item.remove();
    item.appendChild(close);
  }else item.tabIndex=0;
  stack.appendChild(item);
  while(stack.children.length>3) stack.firstElementChild.remove();
  if(bad) return;

  let remaining=4000, started=performance.now(), timer;
  const dismiss=()=>item.remove();
  const resume=()=>{
    if(!item.isConnected||timer) return;
    started=performance.now(); timer=setTimeout(dismiss,remaining);
  };
  const pause=()=>{
    if(!timer) return;
    clearTimeout(timer); timer=null;
    remaining=Math.max(0,remaining-(performance.now()-started));
  };
  item.addEventListener("mouseenter",pause);
  item.addEventListener("mouseleave",resume);
  item.addEventListener("focusin",pause);
  item.addEventListener("focusout",resume);
  resume();
}
async function api(url,opts){
  opts=opts||{};
  const editedBy=($("#editedBy")?.value||"").trim();
  if(editedBy && opts.method && opts.method!=="GET"){
    // ترويسة HTTP لازم تبقى ISO-8859-1 بس — تشفير عشان الاسم غالبًا عربي
    opts.headers={...(opts.headers||{}),"X-Edited-By":encodeURIComponent(editedBy)};
  }
  let r;
  try{ r=await fetch(url,opts) }
  catch(e){ showToast("تعذر الاتصال بالخادم",true); return null }
  let out={}; try{out=await r.json()}catch(e){}
  if(!r.ok){
    // التعديل بيمس يوم/أيام مقفولة (راحة أو فرقة بتاريخ فات مثلًا) —
    // مسموح بس محتاج سبب مكتوب (backend/retro.py). بنسأل هنا مرة واحدة
    // في مكان واحد عشان كل نداء `api()` في السيستم يستفيد من غير ما كل
    // صفحة تتعامل مع الحالة دي لوحدها.
    if(out && out.needs_reason && !opts.__retro){
      const closedDays=(out.closed_days||[]).map(fmt);
      const closedScope=closedDays.length===1?`اليوم المغلق ${closedDays[0]}`
        :closedDays.length?`الأيام المغلقة: ${closedDays.join("، ")}`:"يومًا مغلقًا";
      const reason=await reasonDialog({
        title:"سبب التعديل على يوم مغلق",
        body:`يمس هذا التعديل ${closedScope}. سيُسجَّل السبب في سجل التغييرات.`,
        label:"سبب التعديل",
        confirmLabel:"متابعة التعديل",
      });
      if(reason){
        return api(url,{...opts,__retro:true,
          headers:{...(opts.headers||{}),"X-Retro-Reason":encodeURIComponent(reason)}});
      }
      return null;      // المستخدم لغى — مفيش توست، هو اللي قرر يوقف
    }
    // opts.onError(out, status) بتاخد فرصة تتصرّف في خطأ معيّن (409
    // محتاج تأكيد إضافي مثلًا) — لو رجّعت true بتتلغى التوست الافتراضي
    // لأن المتصل هيتصرّف هو بنفسه.
    if(opts.onError && opts.onError(out,r.status)) return null;
    showToast(out.error||"حدث خطأ",true); return null;
  }
  return out;
}
const jsonReq=(method,body)=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

/** بيحمّل شريحة الصفحة الحالية بس — مش الداتا كلها. */
async function bootstrap(){
  const d=await api(`/api/bootstrap/${PAGE}`);
  if(!d) return null;
  META=d.meta||{}; COUNTS=d.counts||{};
  $("#today").textContent=new Date(curDate()+"T00:00:00")
    .toLocaleDateString("ar-EG-u-nu-latn",{weekday:"long",year:"numeric",month:"long",day:"numeric"});
  paintNavCounts(d);
  return d;
}
function paintNavCounts(d){
  const c = d.counts || COUNTS || {};
  const n = {
    navOfficers: (d.officers && d.officers.active) ? d.officers.active.length : c.officers,
    navPersonnel: (d.personnel && d.personnel.active) ? d.personnel.active.length : (Array.isArray(d.personnel) ? d.personnel.length : c.personnel),
    navLeaves: d.leaves ? d.leaves.length : c.leaves,
    navCourses: c.courses,
  };
  for (const [id, v] of Object.entries(n)){
    const el = $("#" + id);
    if (el && v != null && v !== undefined) el.textContent = v;
  }
  const alerts = (d.alerts || []).length;
  $("#navAlerts")?.classList.toggle("hidden", !alerts);
  // أمر وقف راحات ساري — بيبان في القايمة من أي صفحة
  $("#navSuspension")?.classList.toggle("hidden", !(META.rest_suspension?.active || []).length);
}

/* ---------- شريط وقف الراحات (اليومية التفصيلية + يومية الضباط) ----------
   مكان التسكين نفسه لازم يقول: الأنواع الموقوفة في اليوم ده، ومين رجع من
   إيقاف راحته فيه — دول الضباط اللي محتاجين يتسكّنوا. */
async function renderRestStrip(el, day){
  if(!el || !day) return;
  el.dataset.day = day;
  const r = await api(`/api/rest-suspensions/day/${encodeURIComponent(day)}`);
  if(el.dataset.day !== day) return;          // اتغيّر اليوم قبل ما الرد يوصل
  if(!r || (!r.types.length && !r.returned.length)){ el.innerHTML = ""; return }
  const returned = r.returned.map(o => `<span class="chip on"
      title="${esc(o.stop_reason)} — كانت لحد ${esc(fmt(o.original_end))}">${esc(o.role)}/ ${esc(o.name)}
      <i>${esc(o.type)}</i></span>`).join("");
  el.innerHTML = `<div class="alert-card susp-banner rest-strip"><div class="alert-head">
      <span class="alert-ico">${icon("block","ico-lg")}</span>
      <strong>${r.types.length ? `الراحات موقوفة: ${r.types.map(esc).join("، ")}` : "إيقاف راحات"}</strong>
      <a class="mini" href="/leaves/suspension">إدارة الوقف</a></div>
    ${r.returned.length ? `<div class="sub">رجعوا للعمل في اليوم ده بإيقاف راحتهم — محتاجين تسكين:</div>
      <div class="returned">${returned}</div>` : ""}
  </div>`;
}

/* ---------- عناصر عامة ---------- */
function fillSelect(el,pairs,keep){
  if(!el) return;
  const old=keep?el.value:null;
  el.innerHTML=pairs.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join("");
  if(old!==null&&pairs.some(([v])=>v===old)) el.value=old;
}
function mtable(head,rows){
  return `<table class="table mtable"><thead><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}
function tableBlock(head,rows,countText,emptyText){
  if(!rows.length&&emptyText) return `<div class="empty">${emptyText}</div>`;
  return `<div class="table-scroll">${mtable(head,rows)}</div><div class="count">${countText}</div>`;
}

/* ---------- توزيع النقرات (بديل onclick المضمّن) ----------
   كل زرار متولّد بيحمل data-action (+ data-id/data-extra). النقر بيتلقط مرة
   واحدة هنا، والقيم بتتقرأ من الـdataset كنص عادي — مش بيتجمّع كـJS أبدًا،
   فأي قيمة حرة مهما كان محتواها ما تقدرش تكسر الصفحة أو تنفّذ كود.
   لازم تتعرّف هنا قبل قسم Sortable Table تحت، لأنه بيسجّل ACTIONS._thSort
   فورًا وقت التحميل — مش جوه دالة بتتأجل استدعاءها. */
const ACTIONS={};
document.addEventListener("click",e=>{
  const el=e.target.closest("[data-action]");
  if(!el) return;
  const fn=ACTIONS[el.dataset.action];
  if(!fn) return;
  let extra={};
  if(el.dataset.extra){ try{extra=JSON.parse(el.dataset.extra)}catch(err){} }
  fn(el.dataset.id,extra,el);
});

/* ═══════════════════════════════════════════════════════════════════
   Sortable Table — يُستخدم في الصفحات التي تحتاج ترتيب الأعمدة.
   الاستخدام:
     const COLS = { key: { label:"العمود", fn: row=>row.field, type:"text"|"num"|"date"|"rank" } }
     sortableTableBlock(containerId, COLS, rows, rowHtml, countText, emptyText, defaultKey)
   ═══════════════════════════════════════════════════════════════════ */
const _sortStates = {};   // { containerId: { col, dir } }

function _sortState(cid) {
  return _sortStates[cid] || (_sortStates[cid] = { col: null, dir: 0 });
}

/**
 * يرتّب مصفوفة rows بناءً على accessor fn وaتجاه dir (+1 تصاعدي, -1 تنازلي).
 * type: 'text' | 'num' | 'date' | 'rank'
 */
function applySort(rows, fn, dir, type) {
  if (!dir) return rows;
  return [...rows].sort((a, b) => {
    const va = fn(a), vb = fn(b);
    // الرتبة ترتيبها عسكري مش أبجدي — «عقيد» فوق «نقيب» مهما كان ترتيب
    // الحروف. النوع ده كان موصوف في التوثيق بس من غير تنفيذ، فكان بيقع
    // على المقارنة النصية تحت ويطلع ترتيب أبجدي غلط.
    if (type === "rank") return dir * (rankIndex(va) - rankIndex(vb));
    if (type === "date") {
      // التواريخ ISO بتترتب صح كنص، فمفيش داعي لتحويلها لأرقام
      return dir * String(va ?? "").localeCompare(String(vb ?? ""), "en");
    }
    if (type === "num") {
      // Number() على طول — الاستبدال القديم للشرطة كان بيقلب الأرقام السالبة
      return dir * ((Number(va) || 0) - (Number(vb) || 0));
    }
    return dir * String(va ?? "").localeCompare(String(vb ?? ""), "ar");
  });
}

/**
 * يبني `<th>` قابل للضغط يحوّل بين ▲ ▼ وبلا ترتيب.
 * onSort(col, dir) يُستدعى بعد كل تغيير.
 */
function _sortTh(label, key, cid, onSort) {
  const st = _sortState(cid);
  const isCur = st.col === key;
  const dir = isCur ? st.dir : 0;
  const cls = isCur && dir === 1 ? " asc" : isCur && dir === -1 ? " desc" : "";
  return `<th class="th-sort${cls}" data-action="_thSort"
    data-extra="${dataAttr({cid, key})}">${esc(label)}</th>`;
}

// يلتقط الضغط على أي th-sort ويحدّث الـ state ويعيد الرسم
ACTIONS._thSort = (_id, extra) => {
  const { cid, key } = extra;
  const st = _sortState(cid);
  if (st.col !== key) { st.col = key; st.dir = 1; }
  else if (st.dir === 1) { st.dir = -1; }
  else { st.col = null; st.dir = 0; }
  // استدعاء render المخزن للصفحة الحالية
  if (typeof _sortRenders[cid] === "function") _sortRenders[cid]();
};
const _sortRenders = {};   // { cid: renderFn }

/**
 * الدالة الرئيسية — تحلّ محلّ tableBlock في الصفحات التي تريد sorting.
 *
 * @param {string}   cid         id العنصر الحاوي (يُستخدم كمفتاح للـstate)
 * @param {object}   cols        { key: { label, fn, type } } — الأعمدة القابلة للترتيب
 * @param {Array}    rows        البيانات الخام (objects)
 * @param {function} rowHtml     fn(row) → HTML string للصف
 * @param {string[]} extraHeads  أعمدة ثابتة (لا تُرتّب) تُلحق بعد الأعمدة القابلة
 * @param {string}   countText
 * @param {string}   emptyText
 * @param {function} [renderFn]  دالة إعادة الرسم لهذه الصفحة
 */
function sortableTableBlock(cid, cols, rows, rowHtml, extraHeads, countText, emptyText, renderFn) {
  if (renderFn) _sortRenders[cid] = renderFn;
  const st = _sortState(cid);
  // ترتيب
  let sorted = rows;
  if (st.col && cols[st.col]) {
    const { fn, type } = cols[st.col];
    sorted = applySort(rows, fn, st.dir, type);
  }
  if (!sorted.length && emptyText) return `<div class="empty">${emptyText}</div>`;
  const heads = [
    ...Object.entries(cols).map(([k, c]) => _sortTh(c.label, k, cid, null)),
    ...(extraHeads || []).map(h => `<th>${esc(h)}</th>`)
  ];
  const tableHtml = `<table class="table mtable"><thead><tr>${heads.join("")}</tr></thead>
    <tbody>${sorted.map(rowHtml).join("")}</tbody></table>`;
  return `<div class="table-scroll">${tableHtml}</div><div class="count">${countText}</div>`;
}

const _modalStack=[];
const _sharedDialog=document.createElement("div");
_sharedDialog.id="sharedDialog";
_sharedDialog.className="modal hidden";
_sharedDialog.innerHTML=`<div class="modal-card small shared-dialog" role="dialog" aria-modal="true" aria-labelledby="sharedDialogTitle">
  <button type="button" class="close" data-close="sharedDialog" aria-label="إغلاق">×</button>
  <h2 id="sharedDialogTitle"></h2>
  <p class="dialog-body" id="sharedDialogBody"></p>
  <form id="sharedDialogForm" novalidate>
    <div id="sharedDialogField"></div>
    <p class="dialog-error hidden" id="sharedDialogError" role="alert"></p>
    <div class="dialog-actions">
      <button type="button" class="btn" id="sharedDialogCancel">إلغاء</button>
      <button type="submit" class="primary" id="sharedDialogConfirm"></button>
    </div>
  </form>
</div>`;
document.body.appendChild(_sharedDialog);
let _dialogPending=null;
const _modalFocusableSelector=[
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])", "textarea:not([disabled])", "[tabindex]", '[contenteditable="true"]',
].join(",");

const _modalTop=()=>_modalStack[_modalStack.length-1]||null;
const _modalVisible=el=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
function _modalFocusable(root){
  return [...root.querySelectorAll(_modalFocusableSelector)].filter(el=>
    el.tabIndex>=0 && !el.closest("[inert]") && _modalVisible(el));
}
function _syncModalState(){
  const top=_modalTop()?.modal||null;
  $$(".topbar,.shell").forEach(el=>el.toggleAttribute("inert",!!top));
  $$(".modal").forEach(modal=>modal.toggleAttribute("inert",!!top&&!modal.classList.contains("hidden")&&modal!==top));
  document.body.classList.toggle("modal-open",!!top);
}
function _focusModal(modal){
  const card=modal.querySelector(".modal-card");
  if(!card) return;
  const autofocus=[...card.querySelectorAll("[autofocus]")].find(el=>
    !el.disabled&&!el.classList.contains("close")&&_modalVisible(el));
  const field=[...card.querySelectorAll("input:not([type=hidden]),select,textarea,button:not(.close)")].find(el=>
    !el.disabled&&el.tabIndex>=0&&_modalVisible(el));
  const target=autofocus||field||card;
  if(target===card&&!card.hasAttribute("tabindex")) card.setAttribute("tabindex","-1");
  target.focus({preventScroll:true});
}
function openModal(id){
  const modal=$("#"+id);
  if(!modal) return;
  const current=_modalStack.find(entry=>entry.modal===modal);
  if(current){
    if(_modalTop()===current) _focusModal(modal);
    return;
  }
  const opener=document.activeElement instanceof HTMLElement?document.activeElement:null;
  modal.classList.remove("hidden");
  const entry={modal,opener};
  _modalStack.push(entry);
  _syncModalState();
  _focusModal(modal);
}
function closeModal(id){
  const modal=$("#"+id);
  if(!modal) return;
  if(id==="sharedDialog"&&_dialogPending){ _dialogFinish(_dialogPending.cancelValue); return }
  const index=_modalStack.findIndex(entry=>entry.modal===modal);
  const entry=index<0?null:_modalStack[index];
  const wasTop=index===_modalStack.length-1;
  modal.classList.add("hidden");
  modal.removeAttribute("inert");
  if(index>=0) _modalStack.splice(index,1);
  if(_cbSel&&modal.contains(_cbSel)) _cbClose();
  if(_dpInput&&modal.contains(_dpInput)) _dpClose();
  _syncModalState();
  if(!wasTop) return;
  if(entry?.opener?.isConnected&&!entry.opener.closest("[inert]")) entry.opener.focus({preventScroll:true});
  else if(_modalTop()) _focusModal(_modalTop().modal);
}

function _dialogFinish(value){
  const pending=_dialogPending;
  if(!pending) return;
  _dialogPending=null;
  closeModal("sharedDialog");
  pending.resolve(value);
}
function _dialogStart(options,renderField,onConfirm,cancelValue){
  if(_dialogPending) _dialogFinish(_dialogPending.cancelValue);
  $("#sharedDialogTitle").textContent=options.title;
  $("#sharedDialogBody").textContent=humanizeDates(options.body||"");
  $("#sharedDialogField").replaceChildren();
  $("#sharedDialogError").classList.add("hidden");
  const confirm=$("#sharedDialogConfirm"), cancel=$("#sharedDialogCancel");
  confirm.textContent=options.confirmLabel;
  confirm.className=options.danger?"danger":"primary";
  confirm.disabled=false;
  cancel.textContent=options.cancelLabel||"إلغاء";
  confirm.removeAttribute("autofocus"); cancel.removeAttribute("autofocus");
  (options.danger?cancel:confirm).setAttribute("autofocus","");
  renderField?.();
  return new Promise(resolve=>{
    _dialogPending={resolve,cancelValue,onConfirm};
    openModal("sharedDialog");
  });
}
function confirmDialog({title,body,confirmLabel,cancelLabel="إلغاء",danger=false}){
  return _dialogStart({title,body,confirmLabel,cancelLabel,danger},null,()=>true,false);
}
function reasonDialog({title,body,label,confirmLabel,required=true,maxLength=300}){
  return _dialogStart({title,body,confirmLabel},()=>{
    const field=document.createElement("label");
    field.textContent=label;
    const textarea=document.createElement("textarea");
    textarea.id="sharedDialogReason"; textarea.rows=4; textarea.maxLength=maxLength;
    field.appendChild(textarea); $("#sharedDialogField").appendChild(field);
    const confirm=$("#sharedDialogConfirm");
    const sync=()=>{ confirm.disabled=required&&!textarea.value.trim() };
    textarea.addEventListener("input",sync); sync();
  },()=>{
    const value=$("#sharedDialogReason").value.trim();
    return value||(!required?"":null);
  },null);
}
function dateDialog({title,body,label,value,confirmLabel,min,max}){
  return _dialogStart({title,body,confirmLabel},()=>{
    const field=document.createElement("label");
    field.textContent=label;
    const input=document.createElement("input");
    input.id="sharedDialogDate"; input.type="date"; input.value=value||"";
    if(min) input.min=min;
    if(max) input.max=max;
    field.appendChild(input); $("#sharedDialogField").appendChild(field);
    upgradeDateInputs($("#sharedDialogField"));
  },()=>{
    const input=$("#sharedDialogDate"), value=input.value;
    const error=$("#sharedDialogError");
    let message="";
    const parts=/^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    const date=parts?new Date(Date.UTC(Number(parts[1]),Number(parts[2])-1,Number(parts[3]))):null;
    const valid=date&&date.getUTCFullYear()===Number(parts[1])
      &&date.getUTCMonth()===Number(parts[2])-1&&date.getUTCDate()===Number(parts[3]);
    if(!valid) message="اختر تاريخًا صحيحًا.";
    else if(input.min&&value<input.min) message=`يجب ألا يسبق التاريخ ${fmt(input.min)}.`;
    else if(input.max&&value>input.max) message=`يجب ألا يتجاوز التاريخ ${fmt(input.max)}.`;
    error.textContent=message; error.classList.toggle("hidden",!message);
    if(message){ input.focus(); return undefined }
    return value;
  },null);
}

$("#sharedDialogCancel").onclick=()=>_dialogFinish(_dialogPending?.cancelValue);
$("#sharedDialogForm").onsubmit=e=>{
  e.preventDefault();
  if(!_dialogPending||$("#sharedDialogConfirm").disabled) return;
  const value=_dialogPending.onConfirm();
  if(value!==undefined) _dialogFinish(value);
};

/* ---------- شارات الحالة (الحالة نفسها محسوبة في الباك إند) ---------- */
function restLabel(p){
  const sys=p.rest_system||"—";
  if(sys==="—"||!sys) return `<span class="muted">—</span>`;
  const day=p.rest_day?` <span class="chip-day">${esc(p.rest_day)}</span>`:"";
  const cls=sys==="شهرية"?"m":sys==="نصف شهرية"?"h":"w";
  return `<span class="chip ${cls}">${esc(sys)}</span>${day}`;
}
function statusCell(p){
  const st=p.status_today||{};
  if(st.state==="resting")
    return `<span class="chip rest">في راحة</span><div class="sub">حتى ${fmt(st.leave?.end)}</div>`;
  if(st.state==="taqseera")
    return `<span class="chip taq">تقصيرة ${st.taqseera_date===curDate()?"النهاردة":"يوم "+dayName(st.taqseera_date)}</span>`+
           `<div class="sub">الراحة ${fmt(st.rest_start)}</div>`;
  if(st.state==="upcoming")
    return `<span class="chip soon">راحة قادمة</span><div class="sub">${fmt(st.rest_start)}</div>`;
  return `<span class="chip on">بالعمل</span>`;
}
/* التنبيه كان بيترسم قائمة عمودية صف كامل لكل ضابط فوق عنوان الصفحة — عشر
   ضباط يعني ~30 سطر بيدفعوا كل محتوى الصفحة تحت حافة الشاشة. بقى شبكة
   مضغوطة قابلة للطي، وضباط النهاردة متقدمين على اللي بعدهم لأنهم الأعجل. */
function renderAlerts(alerts){
  const box=$("#alerts"); if(!box) return;
  if(!alerts||!alerts.length){box.innerHTML="";return}
  const today=curDate();
  const sorted=[...alerts].sort((a,b)=>String(a.taqseera_date).localeCompare(String(b.taqseera_date)));
  const todayCount=sorted.filter(a=>a.taqseera_date===today).length;
  const lede=todayCount
    ? `${todayCount} تقصيرة النهاردة · ${sorted.length - todayCount} خلال الأيام الجاية`
    : `${sorted.length} ضابط خلال الأيام الجاية`;
  /* على الرئيسية التنبيه هو الخبر نفسه فبيفضل مفتوح. على صفحة الضباط الجدول
     هو المقصود، والمعلومة نفسها موجودة في عمود «حالة اليوم» — فبيبدأ مطوي
     وسطر الملخص لسه بيقول العدد. واللي المستخدم يختاره بيتحفظ له. */
  const saved=localStorage.getItem("alertsOpen");
  const open=saved===null?PAGE==="dashboard":saved==="1";
  box.innerHTML=`<div class="alert-card"><details class="alert-fold" ${open?"open":""}>
    <summary>
      <span class="alert-head"><span class="alert-ico">${icon("alert","ico-lg")}</span>
        <strong>تنبيه تقصيرة</strong>
        <span class="muted">${esc(lede)}</span></span>
      <span class="alert-toggle">التفاصيل</span>
    </summary>
    <ul class="alert-list">${sorted.map(a=>{
      const isToday=a.taqseera_date===today;
      const when=isToday?"<b>النهاردة</b>":`${dayName(a.taqseera_date)} ${fmt(a.taqseera_date)}`;
      return `<li class="${isToday?"is-today":""}">
        <span class="a-name">${esc(a.role)} / ${esc(a.name)}</span>
        <span class="a-meta"><span class="a-mid">تقصيرة ${when}</span>
          <span class="a-rest">راحة ${esc(a.type)} ${fmt(a.rest_start)}</span></span>
      </li>`;
    }).join("")}</ul>
  </details></div>`;
  /* الحفظ لازم يكون على نقرة المستخدم بس. حدث `toggle` بيتطلق كمان لما
     المتصفح يركّب <details open> لأول مرة، فالرئيسية (اللي بتفتحه
     افتراضيًا) كانت بتكتب "1" وتخلّيه مفتوح في كل الصفحات التانية. */
  const fold=box.querySelector(".alert-fold");
  fold.querySelector("summary").addEventListener("click",()=>
    setTimeout(()=>localStorage.setItem("alertsOpen",fold.open?"1":"0"),0));
}

/* ---------- منتقي التاريخ العربي ----------
   الحقول الأصلية (type=date/month) كانت بتترندر بالفورمات واللغة اللي
   المتصفح نفسه مظبوط عليها (mm/dd/yyyy إنجليزي غالبًا) — مش حاجة CSS
   بسيطة تغيّرها لأنها تحكّم متصفح مش صفحة. الحل: نحوّل الحقل لـtext
   للعرض بس، ونعيد تعريف value بـObject.defineProperty عشان كل كود
   قديم (leave-form.js, force.js, duty.js...) يفضل يقرا/يكتب ISO زي ما
   هو من غير أي تعديل فيه — الفرق الوحيد اللي المستخدم شايفه هو النص. */
const AR_MONTHS=Array.from({length:12},(_,i)=>
  new Date(2000,i,1).toLocaleDateString("ar-EG-u-nu-latn",{month:"long"}));
const WD_SHORT=["س","ح","ن","ث","ر","خ","ج"];   // بادئة بالسبت زي WEEKDAYS
const _dateValueDesc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value");

const datePopover=document.createElement("div");
datePopover.className="date-popover hidden";
document.body.appendChild(datePopover);
let _dpInput=null, _dpView=null;

function _dpClose(){ datePopover.classList.add("hidden"); _dpInput=null }
function _dpFireChange(input){
  input.dispatchEvent(new Event("input",{bubbles:true}));
  input.dispatchEvent(new Event("change",{bubbles:true}));
}
function _dpPick(iso){
  const input=_dpInput; _dpClose();
  input.value=iso; _dpFireChange(input); input.focus();
}
function _dpClear(){
  const input=_dpInput; _dpClose();
  input.value=""; _dpFireChange(input); input.focus();
}
function _dpMonthLabel(iso){
  const [y,m]=iso.split("-").map(Number);
  return new Date(y,m-1,1).toLocaleDateString("ar-EG-u-nu-latn",{month:"long",year:"numeric"});
}
function _dpDayGrid(y,m){
  const first=new Date(y,m,1);
  const startIdx=(first.getDay()+1)%7;            // الأحد=0 في JS، والأسبوع هنا بادئ بالسبت
  const daysInMonth=new Date(y,m+1,0).getDate();
  const todayIso=curDate(), selIso=_dpInput.value||"";
  const cells=[];
  for(let i=0;i<startIdx;i++) cells.push("<span></span>");
  for(let d=1;d<=daysInMonth;d++){
    const iso=`${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    const cls=[iso===todayIso?"today":"",iso===selIso?"sel":""].filter(Boolean).join(" ");
    cells.push(`<button type="button" class="${cls}" data-action="_dpPickDay" data-id="${iso}">${d}</button>`);
  }
  const heads=WD_SHORT.map(h=>`<span class="dp-wd">${h}</span>`).join("");
  return `<div class="dp-head">
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="-1" aria-label="الشهر السابق">${icon("chevron-prev")}</button>
      <b>${new Date(y,m,1).toLocaleDateString("ar-EG-u-nu-latn",{month:"long",year:"numeric"})}</b>
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="1" aria-label="الشهر التالي">${icon("chevron-next")}</button>
    </div>
    <div class="dp-grid dp-grid-day">${heads}${cells.join("")}</div>`;
}
function _dpMonthGrid(y){
  const v=_dpInput.value||"";
  const [selY,selM]=v?v.split("-").map(Number):[null,null];
  const btns=AR_MONTHS.map((name,i)=>{
    const iso=`${y}-${String(i+1).padStart(2,"0")}`;
    const cls=(y===selY&&i+1===selM)?"sel":"";
    return `<button type="button" class="${cls}" data-action="_dpPickMonth" data-id="${iso}">${name}</button>`;
  }).join("");
  return `<div class="dp-head">
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="-1" aria-label="الشهر السابق">${icon("chevron-prev")}</button>
      <b>${y.toLocaleString("ar-EG-u-nu-latn",{useGrouping:false})}</b>
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="1" aria-label="الشهر التالي">${icon("chevron-next")}</button>
    </div>
    <div class="dp-grid dp-grid-month">${btns}</div>`;
}
function _dpRender(){
  const isMonth=_dpInput.dataset.picker==="month";
  const body=isMonth?_dpMonthGrid(_dpView.y):_dpDayGrid(_dpView.y,_dpView.m);
  const clearBtn=_dpInput.required?"":`<button type="button" class="dp-clear" data-action="_dpClearBtn">مسح</button>`;
  datePopover.innerHTML=body+clearBtn;
}
function _dpPosition(input){
  const r=input.getBoundingClientRect();
  const top=Math.min(r.bottom+6,window.innerHeight-320);
  const left=Math.min(Math.max(8,r.left),window.innerWidth-260);
  datePopover.style.top=`${top}px`;
  datePopover.style.left=`${left}px`;
}
function _dpOpen(input){
  _dpInput=input;
  const isMonth=input.dataset.picker==="month";
  const fallback=isMonth?curDate().slice(0,7):curDate();
  const [y,m]=(input.value||fallback).split("-").map(Number);
  _dpView={y, m:m-1};
  _dpRender();
  _dpPosition(input);
  datePopover.classList.remove("hidden");
}
ACTIONS._dpPickDay=id=>_dpPick(id);
ACTIONS._dpPickMonth=id=>_dpPick(id);
ACTIONS._dpClearBtn=()=>_dpClear();
ACTIONS._dpNav=id=>{
  const dir=Number(id);
  if(_dpInput.dataset.picker==="month"){ _dpView.y+=dir }
  else{
    _dpView.m+=dir;
    if(_dpView.m<0){ _dpView.m=11; _dpView.y-- }
    else if(_dpView.m>11){ _dpView.m=0; _dpView.y++ }
  }
  _dpRender();
};
/* `_dpNav` (فوق) بينادي `_dpRender()` اللي بيستبدل innerHTML بتاع
   التقويم — يعني زر التنقل اللي المستخدم دوس عليه بيتشال من الـDOM
   **قبل** ما الحدث ده يوصل لمعالج الإغلاق هنا (الاتنين مسجّلين على
   `document` بنفس مرحلة الفقاعة، وده مسجّل بعد معالج data-action). ساعتها
   `datePopover.contains(e.target)` بترجع false — العنصر اتشال فعلًا —
   فالتقويم كان بيتقفل لوحده أول ما حد يضغط على زرار تنقّل الشهر بالظبط،
   بدل ما يتنقل. `composedPath()` بترجع سلسلة الأجداد وقت إطلاق الحدث
   **قبل** أي تعديل في الـDOM، فبتفضل شايفة التقويم كجدّ للزرار حتى بعد
   ما الزرار نفسه يتشال. */
document.addEventListener("click",e=>{
  if(_dpInput && !e.composedPath().includes(datePopover) && e.target!==_dpInput) _dpClose();
});
/* التقويم `position:fixed` وموضعه بيتحسب مرة واحدة وقت الفتح (`_dpPosition`)
   نسبة لمكان الحقل وقتها. لو المستخدم بعد كده عمل اسكرول (الصفحة نفسها،
   أو أي حاوية بتتمرّر جواها الحقل زي شريط فلترة طويل) الحقل بيتحرك
   والتقويم بيفضل ثابت في نفس بكسلات الشاشة — يعني بيبان طاير في مكان غلط
   عن الحقل. الاسكرول مالوش bubble للـdocument زي الكليك، فلازم نلقطه في
   مرحلة الالتقاط (capture) من أي حاوية بتتمرّر. بنحرّك التقويم بدل ما
   نقفله عشان نفس مشكلة `composedPath` فوق: أي حدث `scroll` بيتطلق أثناء
   `_dpRender()` (تغيير الفوكس بعد شيل الزرار القديم من الـDOM ممكن
   يسبّبه في بعض المتصفحات) كان بيقفل التقويم لوحده. */
document.addEventListener("scroll",e=>{
  if(_dpInput && !datePopover.contains(e.target)) _dpPosition(_dpInput);
},true);

/** بتحوّل أي input[type=date]/input[type=month] لسه ما اترقّاش. بتتنادى
 * مرة تلقائي على كل الصفحة، وبرضو من أي صفحة بتولّد حقول تاريخ ديناميكيًا
 * بعد التحميل الأول (زي جدول كشف الراحات الشهرية). */
function upgradeDateInputs(root){
  (root||document).querySelectorAll('input[type="date"],input[type="month"]').forEach(input=>{
    if(input.dataset.picker) return;
    const mode=input.type, initial=input.value;
    input.dataset.picker=mode;
    input.type="text";
    // حقل النص عرضه الطبيعي ~٢٠ حرف، والتاريخ العربي «١٥ سبتمبر ٢٠٢٦» أقصر
    // من كده بكتير — من غير الضبط ده الحقل بيطلع ضعف اللي محتاجه في الأشرطة.
    input.size=14;
    input.readOnly=true;
    input.classList.add("date-input-display");
    let iso=initial||"";
    Object.defineProperty(input,"value",{
      configurable:true,
      get(){ return iso },
      set(v){
        iso=v||"";
        _dateValueDesc.set.call(input, iso?(mode==="month"?_dpMonthLabel(iso+"-01"):fmt(iso)):"");
      },
    });
    if(initial) _dateValueDesc.set.call(input, mode==="month"?_dpMonthLabel(initial+"-01"):fmt(initial));
    input.addEventListener("click",()=>_dpOpen(input));
    input.addEventListener("keydown",e=>{
      if(e.key==="Enter"||e.key===" "){ e.preventDefault(); _dpOpen(input) }
    });
  });
}
upgradeDateInputs();

/* ═══════════════════════════════════════════════════════════════════
   قائمة منسدلة قابلة للبحث (Combobox)
   ───────────────────────────────────────────────────────────────────
   القوايم هنا فيها أحيانًا مئات الخيارات (قايمة الأشخاص في نموذج الراحة
   فيها ~500 اسم، والضباط 34)، والـ<select> الأصلي مالوش بحث — يعني تدوّر
   بعينك أو تعتمد على كتابة أول حرفين اللي المتصفح بيعملها بالمطابقة
   الحرفية بس.

   الحل: حقل كتابة + قايمة مفلترة فوقه، بس **الـ<select> الأصلي بيفضل في
   الصفحة زي ما هو** وهو مصدر الحقيقة. ده مقصود: في ١٩ نداء لـfillSelect
   وعشرات القراءات `$("#x").value` في كل الصفحات — كلها بتفضل شغالة من
   غير ما تتلمس. الحقل الجديد مجرد واجهة بتكتب في الـselect وبتقرا منه.

   البحث بيستخدم normAr نفسها اللي فوق، فـ«احمد» بتلاقي «أحمد» و«فاطمه»
   بتلاقي «فاطمة» — نفس سلوك البحث في باقي النظام.
   ═══════════════════════════════════════════════════════════════════ */
const _selValueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");

const comboPop = document.createElement("div");
comboPop.className = "combo-pop hidden";
document.body.appendChild(comboPop);

/* الضغط على خيار لازم ما يسحبش التركيز من حقل البحث.
   من غير الـpreventDefault دي: mousedown على الخيار بيعمل blur للحقل →
   معالج الـblur بيقفل القايمة في setTimeout(0) → الـtimer ده بيشتغل **قبل**
   حدث click → لما _cbPick يتنادى تكون _cbOpts اتفضّت و_cbSel بقى null،
   فالاختيار ما بيحصلش خالص. الأحداث الصناعية في الاختبار كانت بتتبعت كلها
   في نفس المهمة فالـtimer ماكانش بيلحق يشتغل، وده اللي خفى العيب. */
comboPop.addEventListener("mousedown", e => e.preventDefault());

let _cbSel = null, _cbInput = null, _cbOpts = [], _cbIdx = -1, _cbMulti = false;

const _cbLabel = sel => sel.options[sel.selectedIndex]?.textContent ?? "";

/* ---------- الاختيار المتعدد ----------
   `<select multiple size=4>` كان صندوق تمرير بأربع أسطر جوه 49 اسم، والاختيار
   المتعدد فيه لازم Ctrl+نقر — أي نقرة عادية بتمسح كل اللي قبلها. بقى صندوق
   وسوم: المختارين ظاهرين كلهم كشارات تتشال بنقرة، والبحث جنبهم.
   الـ<select> نفسه بيفضل مصدر الحقيقة — readMulti() بتقرا selectedOptions
   زي ما هي، و fillMulti() بتكتب innerHTML والمراقب بيعيد رسم الشارات. */
function _msSync(sel) {
  const box = sel._comboBox, inp = sel._comboInput;
  if (!box) return;
  box.querySelectorAll(".multi-chip").forEach(n => n.remove());
  const chosen = [...sel.options].filter(o => o.selected);
  for (const o of chosen) {
    const chip = document.createElement("span");
    chip.className = "multi-chip";
    chip.innerHTML = `${esc(o.textContent)}<button type="button" class="multi-x"
      data-action="_msRemove" data-extra="${dataAttr({v: o.value})}"
      aria-label="شيل ${esc(o.textContent)}">×</button>`;
    box.insertBefore(chip, inp);
  }
  inp.placeholder = chosen.length ? "زوّد كمان…" : "دوّر واختار…";
  box.classList.toggle("has-items", chosen.length > 0);
}

ACTIONS._msRemove = (_id, extra, el) => {
  const sel = el.closest(".multi")?._sel;
  if (!sel) return;
  const o = [...sel.options].find(x => x.value === extra.v);
  if (!o) return;
  o.selected = false;
  _msSync(sel);
  if (_cbSel === sel) _cbRender(_cbInput.value);
  sel.dispatchEvent(new Event("change", {bubbles: true}));
};

/** يرجّع نص الحقل للقيمة المختارة فعلًا في الـselect. */
function _cbSync(sel) {
  const inp = sel._comboInput;
  if (!inp) return;
  inp.value = sel._comboCustomDraft ?? _cbLabel(sel);
  inp.disabled = sel.disabled;
}

function _cbRender(q) {
  if (!_cbSel) return;
  const opts = [..._cbSel.options];
  const all = opts.map((o, i) => ({i, text: o.textContent, value: o.value}));
  const typed = String(q || "").trim();
  const allowCustom = !_cbMulti && _cbSel.hasAttribute("data-combo-custom");
  const exact = typed && all.some(o => o.value.trim() === typed || o.text.trim() === typed);
  const custom = allowCustom && typed && !exact
    ? [{custom: true, text: typed, value: typed}] : [];
  _cbOpts = [...custom, ...(q ? all.filter(o => arIncludes(o.text, q)) : all)];
  if (!_cbOpts.length) {
    comboPop.innerHTML = `<div class="combo-empty">مفيش خيار مطابق لـ«${esc(q)}»</div>`;
    return;
  }
  if (custom.length) _cbIdx = 0;
  if (_cbIdx >= _cbOpts.length) _cbIdx = _cbOpts.length - 1;
  const cur = _selValueDesc.get.call(_cbSel);
  const chosen = o => !o.custom && (_cbMulti ? opts[o.i].selected : o.value === cur);
  comboPop.innerHTML = `<ul class="combo-list" role="listbox"
    ${_cbMulti ? 'aria-multiselectable="true"' : ""}>${_cbOpts.map((o, n) => {
    const on = chosen(o);
    return `<li role="option" aria-selected="${on}" data-action="_cbPick" data-id="${n}"
      class="combo-opt${o.custom ? " custom" : ""}${on ? " sel" : ""}${n === _cbIdx ? " active" : ""}"
      >${_cbMulti ? `<span class="combo-tick" aria-hidden="true">${on ? icon("check") : ""}</span>` : ""}${o.custom
        ? `${icon("plus")} قسم جديد: «${esc(o.text)}»` : esc(o.text)}</li>`;
  }).join("")}</ul>`;
}

function _cbScrollActive() {
  comboPop.querySelector(".combo-opt.active")?.scrollIntoView({block: "nearest"});
}

function _cbPosition() {
  const r = _cbInput.getBoundingClientRect();
  const width = Math.min(Math.max(r.width, 260), window.innerWidth - 16);
  const left = Math.min(Math.max(8, r.right - width), window.innerWidth - width - 8);
  comboPop.style.width = `${width}px`;
  comboPop.style.left = `${left}px`;
  // لو مفيش مكان تحت الحقل، القايمة بتطلع فوقه بدل ما تتقص
  const below = window.innerHeight - r.bottom;
  comboPop.style.maxHeight = `${Math.max(150, Math.min(280, below - 12))}px`;
  if (below < 170 && r.top > below) {
    comboPop.style.top = "auto";
    comboPop.style.bottom = `${window.innerHeight - r.top + 4}px`;
    comboPop.style.maxHeight = `${Math.min(280, r.top - 12)}px`;
  } else {
    comboPop.style.bottom = "auto";
    comboPop.style.top = `${r.bottom + 4}px`;
  }
}

function _cbOpen(sel, query = "") {
  if (sel.disabled) return;
  _cbSel = sel; _cbInput = sel._comboInput; _cbMulti = !!sel.multiple;
  _cbIdx = _cbMulti ? 0 : Math.max(0, sel.selectedIndex);
  if (!_cbMulti) {
    // الحقل بيتفضّى عشان الكتابة تبدأ بحث جديد، والمختار حاليًا باين كـplaceholder
    _cbInput.placeholder = (sel._comboCustomDraft ?? _cbLabel(sel)) || "اختار...";
    _cbInput.value = query;
  }
  _cbRender(query);
  comboPop.classList.remove("hidden");
  comboPop.classList.toggle("is-multi", _cbMulti);
  _cbPosition();
  _cbInput.setAttribute("aria-expanded", "true");
  _cbScrollActive();
}

function _cbClose() {
  if (_cbInput) {
    _cbInput.setAttribute("aria-expanded", "false");
    if (_cbMulti) { _cbInput.value = ""; _msSync(_cbSel) }
    else { _cbInput.placeholder = ""; _cbSync(_cbSel) }
  }
  comboPop.classList.add("hidden");
  _cbSel = null; _cbInput = null; _cbOpts = []; _cbIdx = -1;
  _cbMulti = false;
}

function _cbPick(n) {
  const o = _cbOpts[n];
  if (!o) return;
  const sel = _cbSel, inp = _cbInput;

  if (o.custom) {
    sel._comboCustomDraft = o.value;
    _cbClose();
    sel.dispatchEvent(new Event("input", {bubbles: true}));
    sel.dispatchEvent(new Event("change", {bubbles: true}));
    inp?.focus();
    return;
  }

  if (_cbMulti) {
    // الاختيار المتعدد: القايمة بتفضل مفتوحة عشان تكمّل اختيار من غير ما تعيد فتحها
    const opt = sel.options[o.i];
    opt.selected = !opt.selected;
    _msSync(sel);
    _cbIdx = n;
    _cbRender(inp.value);
    _cbPosition();
    sel.dispatchEvent(new Event("change", {bubbles: true}));
    inp.focus();
    return;
  }

  _cbClose();
  sel._comboCustomDraft = null;
  sel.value = o.value;                       // بيعدي على الـsetter المعدّل فيسيّنك الحقل
  sel.dispatchEvent(new Event("input", {bubbles: true}));
  sel.dispatchEvent(new Event("change", {bubbles: true}));
  inp?.focus();
}
ACTIONS._cbPick = id => _cbPick(Number(id));

function _cbMove(step) {
  if (!_cbOpts.length) return;
  _cbIdx = (_cbIdx + step + _cbOpts.length) % _cbOpts.length;
  comboPop.querySelectorAll(".combo-opt").forEach((el, i) =>
    el.classList.toggle("active", i === _cbIdx));
  _cbScrollActive();
}

/** صندوق الوسوم للاختيار المتعدد — شارة لكل مختار + حقل بحث جنبهم. */
function _upgradeMulti(sel) {
  const box = document.createElement("div");
  box.className = "multi";
  const inp = document.createElement("input");
  inp.type = "text"; inp.size = 1; inp.autocomplete = "off";
  inp.className = "multi-input";
  inp.setAttribute("role", "combobox");
  inp.setAttribute("aria-expanded", "false");
  inp.setAttribute("aria-autocomplete", "list");
  const lab = sel.closest("label");
  if (lab) inp.setAttribute("aria-label", lab.textContent.replace(/\s+/g, " ").trim());
  box.appendChild(inp);

  box._sel = sel; sel._comboBox = box; sel._comboInput = inp;
  sel.parentNode.insertBefore(box, sel);
  sel.classList.add("combo-native");
  sel.setAttribute("tabindex", "-1");
  sel.setAttribute("aria-hidden", "true");
  _msSync(sel);

  box.addEventListener("mousedown", e => {
    if (e.target.closest(".multi-x")) return;      // زرار شيل الشارة له تصرفه
    e.preventDefault();
    inp.focus();
    if (_cbSel !== sel) _cbOpen(sel);
  });
  inp.addEventListener("input", () => {
    if (_cbSel !== sel) _cbOpen(sel);
    _cbIdx = 0; _cbRender(inp.value); _cbPosition();
  });
  inp.addEventListener("keydown", e => {
    const open = _cbSel === sel;
    if (e.key === "ArrowDown") { e.preventDefault(); open ? _cbMove(1) : _cbOpen(sel) }
    else if (e.key === "ArrowUp") { e.preventDefault(); open ? _cbMove(-1) : _cbOpen(sel) }
    else if (e.key === "Enter" && open) { e.preventDefault(); _cbPick(_cbIdx) }
    else if (e.key === "Escape" && open) { e.stopPropagation(); _cbClose() }
    else if (e.key === "Tab" && open) { _cbClose() }
    // Backspace على حقل فاضي بيشيل آخر شارة — اختصار متوقع في صناديق الوسوم
    else if (e.key === "Backspace" && !inp.value) {
      const last = [...sel.options].filter(o => o.selected).pop();
      if (last) {
        last.selected = false; _msSync(sel);
        if (open) _cbRender(inp.value);
        sel.dispatchEvent(new Event("change", {bubbles: true}));
      }
    }
  });
  /* النقر على خيار بيعمل blur للحقل ثم بنرجّع الفوكس له — فلازم نستثني
     الحالة دي، وإلا القايمة بتتقفل بعد كل اختيار والمفروض تفضل مفتوحة. */
  inp.addEventListener("blur", () => setTimeout(() => {
    if (_cbSel === sel && document.activeElement !== inp
        && !comboPop.contains(document.activeElement)) _cbClose();
  }, 0));

  // fillMulti() بتستبدل الـinnerHTML بالكامل ومعاه الـselected
  new MutationObserver(() => {
    _msSync(sel);
    if (_cbSel === sel) _cbRender(_cbInput.value);
  }).observe(sel, {childList: true, attributes: true, attributeFilter: ["disabled"]});
}

/** بتحوّل أي <select> مفرد لحقل بحث. بتتنادى مرة على الصفحة كلها، وكمان
 *  من أي كود بيولّد <select> بعد التحميل (زي كروت قيادة الإدارة). */
function upgradeSelects(root) {
  (root || document).querySelectorAll("select:not([data-combo])").forEach(sel => {
    sel.dataset.combo = "1";
    if (sel.multiple) { _upgradeMulti(sel); return }
    const allowCustom = sel.hasAttribute("data-combo-custom");

    const inp = document.createElement("input");
    inp.type = "text";
    inp.autocomplete = "off";
    // <input> عرضه الطبيعي ~٢٠ حرف، والـ<select> عرضه بقد أطول خيار. من غير
    // ده الحقول بتطلع أعرض من القوايم اللي حلّت محلها وبتزحلق أزرار الشريط لسطر تاني.
    inp.size = 1;
    inp.className = `${sel.className} combo-input`.trim();
    inp.setAttribute("role", "combobox");
    inp.setAttribute("aria-expanded", "false");
    inp.setAttribute("aria-autocomplete", "list");
    // الاسم المقروء: من aria-label أو من الـ<label> المرتبط (صريح أو محيط)
    const lab = sel.closest("label")
      || (sel.id && document.querySelector(`label[for="${CSS.escape(sel.id)}"]`));
    const name = sel.getAttribute("aria-label")
      || (lab ? lab.textContent.replace(/\s+/g, " ").trim() : "");
    if (name) inp.setAttribute("aria-label", name);

    /* التحقق المطلوب (required) بينتقل للحقل الظاهر: المتصفح مايقدرش يوقف
       عند عنصر مخفي، وكان هيرمي "not focusable" ويمنع الحفظ. القوايم
       الثلاثة اللي عليها required مفيهاش خيار فاضي — بتتملّي بقيم حقيقية
       وبتختار أول واحدة — فالمعنى واحد، بس الرسالة بقت على حقل مرئي. */
    if (sel.required) { inp.required = true; sel.removeAttribute("required") }

    sel._comboInput = inp;
    sel._comboCustomDraft = null;
    sel.classList.add("combo-native");
    sel.setAttribute("tabindex", "-1");
    sel.setAttribute("aria-hidden", "true");
    sel.parentNode.insertBefore(inp, sel);
    _cbSync(sel);

    inp.addEventListener("mousedown", e => {
      e.preventDefault();                       // من غير كده الفوكس بيسبق الفتح
      _cbSel === sel ? _cbClose() : _cbOpen(sel);
      inp.focus();
    });
    // الحقل الحر محتاج نفس سلوك النقر مع التنقّل بالكيبورد: أول ما ياخد
    // focus يعرض كل الأقسام بدل ما النص الحالي يفلتر القايمة قبل الكتابة.
    if (allowCustom) inp.addEventListener("focus", () => {
      if (_cbSel !== sel) _cbOpen(sel);
    });
    inp.addEventListener("input", () => {
      const query = inp.value;
      if (allowCustom) sel._comboCustomDraft = query;
      if (_cbSel !== sel) _cbOpen(sel, query);
      _cbIdx = 0;
      _cbRender(query);
      _cbPosition();
      if (allowCustom) sel.dispatchEvent(new Event("input", {bubbles: true}));
    });
    inp.addEventListener("keydown", e => {
      const open = _cbSel === sel;
      if (e.key === "ArrowDown") { e.preventDefault(); open ? _cbMove(1) : _cbOpen(sel) }
      else if (e.key === "ArrowUp") { e.preventDefault(); open ? _cbMove(-1) : _cbOpen(sel) }
      else if (e.key === "Home" && open) { e.preventDefault(); _cbIdx = 0; _cbMove(0) }
      else if (e.key === "End" && open) { e.preventDefault(); _cbIdx = _cbOpts.length - 1; _cbMove(0) }
      else if (e.key === "Enter") {
        if (open) {
          e.preventDefault();
          if (_cbOpts.length) _cbPick(_cbIdx);
          else if (allowCustom) { _cbClose(); sel.dispatchEvent(new Event("change", {bubbles: true})) }
        }
      }
      else if (e.key === "Escape") { if (open) { e.stopPropagation(); _cbClose() } }
      else if (e.key === "Tab") { if (open) _cbClose() }
    });
    inp.addEventListener("blur", () => { if (_cbSel === sel) setTimeout(() => {
      if (_cbSel === sel && !comboPop.contains(document.activeElement)) _cbClose();
    }, 0) });

    /* الكود القديم بيكتب `sel.value = x` مباشرة في مليون مكان، وde مش
       بيولّد أي حدث — فبنلفّ الخاصية نفسها عشان الحقل يفضل متطابق.
       نفس الأسلوب المستخدم فوق مع حقول التاريخ. */
    Object.defineProperty(sel, "value", {
      configurable: true,
      get() {
        return allowCustom && sel._comboCustomDraft !== null
          ? sel._comboCustomDraft : _selValueDesc.get.call(sel)
      },
      set(v) {
        const raw = String(v ?? "");
        sel._comboCustomDraft = null;
        _selValueDesc.set.call(sel, raw);
        if (allowCustom && raw && _selValueDesc.get.call(sel) !== raw) {
          sel._comboCustomDraft = raw;
        }
        _cbSync(sel);
      },
    });

    // fillSelect() بيستبدل الـinnerHTML كله — الحقل لازم يتحدّث بعدها
    new MutationObserver(() => {
      _cbSync(sel);
      if (_cbSel === sel) _cbRender(_cbInput.value);
    }).observe(sel, {childList: true, attributes: true, attributeFilter: ["disabled"]});
  });
}
upgradeSelects();

/* لازم mousedown مش click: اختيار عنصر من قايمة متعددة بيعيد رسم الـinnerHTML
   جوه معالج الـclick، فالعنصر اللي اتضغط بيبقى مفصول عن الـDOM وقت ما الحدث
   يوصل هنا — و`contains()` بترجع false فالقايمة كانت بتتقفل بعد كل اختيار. */
document.addEventListener("mousedown", e => {
  if (_cbSel && !comboPop.contains(e.target) && e.target !== _cbInput
      && !e.target.closest(".multi")) _cbClose();
});
window.addEventListener("resize", () => { if (_cbSel) _cbPosition() });

/* ---------- ربط عام ---------- */
/* القائمة الجانبية على الشاشة الصغيرة: كانت بتتفتح وخلاص — من غير حجاب ولا
   طريقة تقفلها غير إنك تضغط الزرار تاني بالظبط. دلوقتي الضغط برّه أو Esc
   أو اختيار قسم بيقفلها، والزرار بيقول حالته لقارئ الشاشة. */
const sidebarEl=$("#sidebar"), scrimEl=$("#scrim"), burgerEl=$("#burgerBtn");
function setSidebar(open){
  sidebarEl.classList.toggle("open",open);
  scrimEl.classList.toggle("open",open);
  burgerEl.setAttribute("aria-expanded",String(open));
  burgerEl.setAttribute("aria-label",open?"إغلاق القائمة":"فتح القائمة");
}
burgerEl.onclick=()=>setSidebar(!sidebarEl.classList.contains("open"));
scrimEl.onclick=()=>setSidebar(false);
sidebarEl.addEventListener("click",e=>{ if(e.target.closest(".navbtn")) setSidebar(false) });

$$("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
$$(".modal").forEach(m=>m.onclick=e=>{
  if(e.target===m&&_modalTop()?.modal===m) closeModal(m.id);
});
document.addEventListener("keydown",e=>{
  if(e.key==="Tab"&&_modalTop()){
    const card=_modalTop().modal.querySelector(".modal-card");
    const active=document.activeElement;
    const popup=(!_cbSel||comboPop.classList.contains("hidden")||!comboPop.contains(active))
      ? (!_dpInput||datePopover.classList.contains("hidden")||!datePopover.contains(active)?null:datePopover)
      : comboPop;
    const focusable=[..._modalFocusable(card),...(popup?_modalFocusable(popup):[])];
    if(!focusable.length){ e.preventDefault(); card.focus({preventScroll:true}); return }
    const index=focusable.indexOf(active);
    if(index<0||(e.shiftKey&&index===0)||(!e.shiftKey&&index===focusable.length-1)){
      e.preventDefault();
      focusable[e.shiftKey?focusable.length-1:0].focus();
    }
    return;
  }
  if(e.key!=="Escape") return;
  // Esc وقت القايمة مفتوحة بيقفل القايمة بس — مش النافذة اللي هي جواها
  if(_cbSel){ _cbClose(); return }
  if(_dpInput){ const input=_dpInput; _dpClose(); input.focus(); return }
  if(_modalTop()){ closeModal(_modalTop().modal.id); return }
  setSidebar(false);
});

/* اسم من قام بالتعديل — بيتحفظ محليًا وبيتبعت مع أي طلب تعديل كـheader،
   عشان يتسجل في سجل التدقيق من غير أي نظام حسابات أو تسجيل دخول. */
const editedByEl=$("#editedBy");
if(editedByEl){
  editedByEl.value=localStorage.getItem("editedBy")||"";
  editedByEl.addEventListener("input",()=>localStorage.setItem("editedBy",editedByEl.value.trim()));
}
