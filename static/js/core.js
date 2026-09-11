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
const _FMT_DATE=new Intl.DateTimeFormat("ar-EG",{day:"numeric",month:"short",year:"numeric"});
const _FMT_WEEKDAY=new Intl.DateTimeFormat("ar-EG",{weekday:"long"});
const _fmtCache=new Map(), _wdCache=new Map();
const fmt=d=>{
  if(!d) return "-";
  let v=_fmtCache.get(d);
  if(v===undefined){ v=_FMT_DATE.format(new Date(d+"T00:00:00")); _fmtCache.set(d,v) }
  return v;
};
const iso=d=>{const t=new Date(d);t.setHours(12);return t.toISOString().slice(0,10)};
const addDays=(s,n)=>{const d=new Date(s+"T12:00:00");d.setDate(d.getDate()+n);return iso(d)};
const dayName=s=>{
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
const MEDICAL_BADGE=()=>META.medical_badge||"ضابط العيادة الطبية";
const KIND_CLS={"خارجية":"w","داخلية":"h","حراسات":"m","طبية":"on","بحث":"soon"};

/* ---------- الشبكة ---------- */
function showToast(msg,bad){
  const t=$("#toast"); t.textContent=msg; t.classList.toggle("bad",!!bad); t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"),2800);
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
  if(!r.ok){showToast(out.error||"حدث خطأ",true); return null}
  return out;
}
const jsonReq=(method,body)=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

/** بيحمّل شريحة الصفحة الحالية بس — مش الداتا كلها. */
async function bootstrap(){
  const d=await api(`/api/bootstrap/${PAGE}`);
  if(!d) return null;
  META=d.meta||{}; COUNTS=d.counts||{};
  $("#today").textContent=new Date(curDate()+"T00:00:00")
    .toLocaleDateString("ar-EG",{weekday:"long",year:"numeric",month:"long",day:"numeric"});
  paintNavCounts(d);
  return d;
}
function paintNavCounts(d){
  const c = d.counts || COUNTS || {};
  const n = {
    navOfficers: (d.officers && d.officers.active) ? d.officers.active.length : c.officers,
    navPersonnel: (d.personnel && d.personnel.active) ? d.personnel.active.length : (Array.isArray(d.personnel) ? d.personnel.length : c.personnel),
    navLeaves: d.leaves ? d.leaves.length : c.leaves,
    navDuty: d.services ? d.services.length : c.services,
    navCourses: c.courses,
  };
  for (const [id, v] of Object.entries(n)){
    const el = $("#" + id);
    if (el && v != null && v !== undefined) el.textContent = v;
  }
  const alerts = (d.alerts || []).length;
  $("#navAlerts")?.classList.toggle("hidden", !alerts);
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

function openModal(id){$("#"+id)?.classList.remove("hidden")}
function closeModal(id){$("#"+id)?.classList.add("hidden")}

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
function renderAlerts(alerts){
  const box=$("#alerts"); if(!box) return;
  if(!alerts||!alerts.length){box.innerHTML="";return}
  box.innerHTML=`<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">⚠</span>
      <strong>تنبيه تقصيرة</strong>
      <span class="muted">اليوم السابق للراحة — ${alerts.length} ضابط</span></div>
    <ul class="alert-list">${alerts.map(a=>`<li>
      <span class="a-name">${esc(a.role)} / ${esc(a.name)}</span>
      <span class="a-mid">تقصيرة يوم <b>${dayName(a.taqseera_date)} ${fmt(a.taqseera_date)}</b>${a.taqseera_date===curDate()?' <span class="chip taq">النهاردة</span>':""}</span>
      <span class="a-rest">الراحة ${esc(a.type)} تبدأ ${dayName(a.rest_start)} ${fmt(a.rest_start)}</span>
    </li>`).join("")}</ul></div>`;
}

/* ---------- منتقي التاريخ العربي ----------
   الحقول الأصلية (type=date/month) كانت بتترندر بالفورمات واللغة اللي
   المتصفح نفسه مظبوط عليها (mm/dd/yyyy إنجليزي غالبًا) — مش حاجة CSS
   بسيطة تغيّرها لأنها تحكّم متصفح مش صفحة. الحل: نحوّل الحقل لـtext
   للعرض بس، ونعيد تعريف value بـObject.defineProperty عشان كل كود
   قديم (leave-form.js, force.js, duty.js...) يفضل يقرا/يكتب ISO زي ما
   هو من غير أي تعديل فيه — الفرق الوحيد اللي المستخدم شايفه هو النص. */
const AR_MONTHS=Array.from({length:12},(_,i)=>
  new Date(2000,i,1).toLocaleDateString("ar-EG",{month:"long"}));
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
  return new Date(y,m-1,1).toLocaleDateString("ar-EG",{month:"long",year:"numeric"});
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
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="-1">‹</button>
      <b>${new Date(y,m,1).toLocaleDateString("ar-EG",{month:"long",year:"numeric"})}</b>
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="1">›</button>
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
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="-1">‹</button>
      <b>${y.toLocaleString("ar-EG",{useGrouping:false})}</b>
      <button type="button" class="dp-nav" data-action="_dpNav" data-id="1">›</button>
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
document.addEventListener("click",e=>{
  if(_dpInput && !datePopover.contains(e.target) && e.target!==_dpInput) _dpClose();
});

/** بتحوّل أي input[type=date]/input[type=month] لسه ما اترقّاش. بتتنادى
 * مرة تلقائي على كل الصفحة، وبرضو من أي صفحة بتولّد حقول تاريخ ديناميكيًا
 * بعد التحميل الأول (زي جدول كشف الراحات الشهرية). */
function upgradeDateInputs(root){
  (root||document).querySelectorAll('input[type="date"],input[type="month"]').forEach(input=>{
    if(input.dataset.picker) return;
    const mode=input.type, initial=input.value;
    input.dataset.picker=mode;
    input.type="text";
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

/* ---------- ربط عام ---------- */
$("#burgerBtn").onclick=()=>$("#sidebar").classList.toggle("open");
$$("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
$$(".modal").forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.add("hidden")});
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ $$(".modal").forEach(m=>m.classList.add("hidden")); _dpClose() }
});

/* اسم من قام بالتعديل — بيتحفظ محليًا وبيتبعت مع أي طلب تعديل كـheader،
   عشان يتسجل في سجل التدقيق من غير أي نظام حسابات أو تسجيل دخول. */
const editedByEl=$("#editedBy");
if(editedByEl){
  editedByEl.value=localStorage.getItem("editedBy")||"";
  editedByEl.addEventListener("input",()=>localStorage.setItem("editedBy",editedByEl.value.trim()));
}
