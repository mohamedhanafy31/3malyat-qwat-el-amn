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

/* ---------- التواريخ ---------- */
const fmt=d=>d?new Date(d+"T00:00:00").toLocaleDateString("ar-EG",{day:"numeric",month:"short",year:"numeric"}):"-";
const iso=d=>{const t=new Date(d);t.setHours(12);return t.toISOString().slice(0,10)};
const addDays=(s,n)=>{const d=new Date(s+"T12:00:00");d.setDate(d.getDate()+n);return iso(d)};
const dayName=s=>new Date(s+"T12:00:00").toLocaleDateString("ar-EG",{weekday:"long"});
const days=(a,b)=>Math.round((new Date(b)-new Date(a))/864e5)+1;

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
const KINDS=()=>META.service_kinds||["خارجية","داخلية","حراسات","طبية","بحث"];
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
  const n={
    navOfficers: d.officers?d.officers.active.length:COUNTS.officers,
    navPersonnel: d.personnel?d.personnel.active.length:COUNTS.personnel,
    navLeaves: d.leaves?d.leaves.length:COUNTS.leaves,
    navDuty: d.services?d.services.length:COUNTS.services,
  };
  for(const [id,v] of Object.entries(n)){
    const el=$("#"+id); if(el && v!=null) el.textContent=v;
  }
  const alerts=(d.alerts||[]).length;
  $("#navAlerts")?.classList.toggle("hidden",!alerts);
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

/* ---------- توزيع النقرات (بديل onclick المضمّن) ----------
   كل زرار متولّد بيحمل data-action (+ data-id/data-extra). النقر بيتلقط مرة
   واحدة هنا، والقيم بتتقرأ من الـdataset كنص عادي — مش بيتجمّع كـJS أبدًا،
   فأي قيمة حرة مهما كان محتواها ما تقدرش تكسر الصفحة أو تنفّذ كود. */
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

/* ---------- ربط عام ---------- */
$("#burgerBtn").onclick=()=>$("#sidebar").classList.toggle("open");
$$("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
$$(".modal").forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.add("hidden")});
document.addEventListener("keydown",e=>{
  if(e.key==="Escape")$$(".modal").forEach(m=>m.classList.add("hidden"));
});

/* اسم من قام بالتعديل — بيتحفظ محليًا وبيتبعت مع أي طلب تعديل كـheader،
   عشان يتسجل في سجل التدقيق من غير أي نظام حسابات أو تسجيل دخول. */
const editedByEl=$("#editedBy");
if(editedByEl){
  editedByEl.value=localStorage.getItem("editedBy")||"";
  editedByEl.addEventListener("input",()=>localStorage.setItem("editedBy",editedByEl.value.trim()));
}
