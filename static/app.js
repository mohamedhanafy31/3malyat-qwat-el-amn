let DATA={officers:{active:[],archive:[]},personnel:{active:[],archive:[]},leaves:[],meta:{}};
let SECTION="dashboard";     // dashboard | officers | personnel | duty | leaves
let BUCKET="active";         // active | archive
let LEAVE_TAB="all";         // all | current | upcoming

const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
// بيانات حرة (اسم/ملاحظة/وسم) بتتحط جوه data-* attribute بدل onclick="fn('...')" —
// المتصفح بيفك تشفير HTML بتاع الـ attribute قبل ما يجمّع أي onclick كـ JS، وده كان بيلغي
// تأثير esc() ويسمح بحقن سكريبت من أي حقل حر (اسم خدمة فيه علامة اقتباس كان كفاية يكسر الصفحة).
// dataAttr() بتتقرأ في الدالة المستمعة بس كـ JSON.parse — مفيش تنفيذ كود خالص.
const dataAttr=obj=>esc(JSON.stringify(obj));
const fmt=d=>d?new Date(d+"T00:00:00").toLocaleDateString("ar-EG",{day:"numeric",month:"short",year:"numeric"}):"-";
const curDate=()=>DATA.meta.today||new Date().toISOString().slice(0,10);
const days=(a,b)=>Math.round((new Date(b)-new Date(a))/864e5)+1;

const REST_SYSTEMS=()=>DATA.meta.rest_systems||["أسبوعية","نصف شهرية","شهرية","—"];
const WEEKDAYS=()=>DATA.meta.weekdays||[];
const LEAVE_TYPES=()=>DATA.meta.leave_types||[];
const DURATIONS=()=>DATA.meta.rest_durations||{"شهرية":7,"نصف شهرية":3,"أسبوعية":1};
const KINDS=()=>DATA.meta.service_kinds||["خارجية","داخلية","حراسات","طبية","بحث"];
const SHIFTS=()=>DATA.meta.shifts||["صباحية","ليلية"];
const NOTICE=()=>DATA.meta.taqseera_notice_days??1;

/* تحويل التواريخ */
const iso=d=>{const t=new Date(d);t.setHours(12);return t.toISOString().slice(0,10)};
const addDays=(s,n)=>{const d=new Date(s+"T12:00:00");d.setDate(d.getDate()+n);return iso(d)};
const dayName=s=>new Date(s+"T12:00:00").toLocaleDateString("ar-EG",{weekday:"long"});
/* WEEKDAYS يبدأ بالسبت، وgetDay يبدأ بالأحد */
const weekdayIndex=name=>{const i=WEEKDAYS().indexOf(name);return i<0?-1:(i+6)%7};

/* أول ظهور ليوم الراحة الأسبوعية بعد تاريخ معيّن */
function nextWeekday(name,from){
  const target=weekdayIndex(name); if(target<0) return null;
  const d=new Date(from+"T12:00:00");
  let diff=(target-d.getDay()+7)%7;
  if(diff===0) diff=7;                       // الراحة الجاية مش النهاردة
  d.setDate(d.getDate()+diff); return iso(d);
}

const OFFICER_ROLES=["ملازم","ملازم أول","نقيب","رائد","مقدم","عقيد","عميد","لواء","أخرى"];
const RANK_ORDER=["لواء","عميد","عقيد","مقدم","رائد","نقيب","ملازم أول","ملازم"];
const rankIndex=role=>{const i=RANK_ORDER.indexOf(role); return i<0?RANK_ORDER.length:i};
// أسبوعية/نصف شهرية/شهرية أولاً بالترتيب ده، والباقي بعدهم بأي ترتيب ثابت
// (مش مهم أيّهم قبل التاني، المهم إن كل نوع يتجمّع لوحده مش يتوزّع بين الرتب)
const leaveTypeIndex=t=>{
  const order=DATA.meta.leave_types||["أسبوعية","نصف شهرية","شهرية"];
  const i=order.indexOf(t); return i<0?order.length:i;
};
const PERSONNEL_ROLES=[
  "أمين شرطة ممتاز أول","أمين شرطة ممتاز ثان","أمين شرطة ممتاز ثالث","أمين شرطة ممتاز",
  "أمين شرطة أول","أمين شرطة ثان","أمين شرطة ثالث","أمين شرطة",
  "مساعد شرطة أول","مساعد شرطة ثان","مساعد شرطة ثالث","مساعد شرطة",
  "معاون شرطة ثان","معاون شرطة ثالث","معاون شرطة",
  "رقيب شرطة أول","رقيب شرطة","مراقب شرطة ثالث","مندوب شرطة","عريف شرطة","شرطي"
];

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
const listOf=(sec,bucket)=>(DATA[sec]&&DATA[sec][bucket])||[];
const personById=id=>["officers","personnel"].flatMap(c=>[...DATA[c].active,...DATA[c].archive]).find(p=>p.id===id);

/* ---------- الراحة الحالية ---------- */
function leavesFor(id){return DATA.leaves.filter(l=>l.person_id===id)}
function currentLeave(id){const t=curDate(); return leavesFor(id).find(l=>l.start<=t&&t<=l.end)}

/* أقرب راحة قادمة: من السجلات أو من يوم الراحة الأسبوعية الثابت */
function nextRestStart(p){
  const t=curDate();
  const rec=leavesFor(p.id).filter(l=>l.start>t).map(l=>({start:l.start,type:l.type}));
  if(p.rest_system==="أسبوعية"&&p.rest_day){
    const w=nextWeekday(p.rest_day,t);
    if(w) rec.push({start:w,type:"أسبوعية",weekly:true});
  }
  rec.sort((a,b)=>a.start<b.start?-1:1);
  return rec[0]||null;
}
/* اليوم السابق للراحة = تقصيرة، والتنبيه يبدأ قبله بيوم */
function taqseera(p){
  if(currentLeave(p.id)) return null;          // في راحة بالفعل
  const nx=nextRestStart(p); if(!nx) return null;
  const day=addDays(nx.start,-1);
  if(day<curDate()) return null;                  // فات (واليوم نفسه لسه صالح)
  return {date:day,restStart:nx.start,type:nx.type,weekly:!!nx.weekly};
}
function taqseeraDue(p){                        // مستحق التنبيه دلوقتي؟
  const q=taqseera(p); if(!q) return null;
  return q.date<=addDays(curDate(),NOTICE())?q:null;
}

function restLabel(p){
  const sys=p.rest_system||"—";
  if(sys==="—"||!sys) return `<span class="muted">—</span>`;
  const day=p.rest_day?` <span class="chip-day">${esc(p.rest_day)}</span>`:"";
  const cls=sys==="شهرية"?"m":sys==="نصف شهرية"?"h":"w";
  return `<span class="chip ${cls}">${esc(sys)}</span>${day}`;
}
function statusCell(p){
  const cur=currentLeave(p.id);
  if(cur) return `<span class="chip rest">في راحة</span><div class="sub">حتى ${fmt(cur.end)}</div>`;
  const q=taqseeraDue(p);
  if(q) return `<span class="chip taq">تقصيرة ${q.date===curDate()?"النهاردة":"يوم "+dayName(q.date)}</span>`+
               `<div class="sub">الراحة ${fmt(q.restStart)}</div>`;
  const nx=nextRestStart(p);
  if(nx) return `<span class="chip soon">راحة قادمة</span><div class="sub">${fmt(nx.start)}</div>`;
  return `<span class="chip on">بالعمل</span>`;
}

/* شريط تنبيهات التقصيرة */
function renderAlerts(){
  const box=$("#alerts"); if(!box) return;
  const due=DATA.officers.active.map(p=>({p,q:taqseeraDue(p)})).filter(x=>x.q)
    .sort((a,b)=>a.q.date<b.q.date?-1:1);
  $("#navAlerts").classList.toggle("hidden",!due.length);
  if(!due.length){box.innerHTML="";return}
  box.innerHTML=`<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">⚠</span>
      <strong>تنبيه تقصيرة</strong>
      <span class="muted">اليوم السابق للراحة — ${due.length} ضابط</span></div>
    <ul class="alert-list">${due.map(({p,q})=>`<li>
      <span class="a-name">${esc(p.role)} / ${esc(p.name)}</span>
      <span class="a-mid">تقصيرة يوم <b>${dayName(q.date)} ${fmt(q.date)}</b>${q.date===curDate()?' <span class="chip taq">النهاردة</span>':""}</span>
      <span class="a-rest">الراحة ${esc(q.type)} تبدأ ${dayName(q.restStart)} ${fmt(q.restStart)}</span>
    </li>`).join("")}</ul></div>`;
}

/* ---------- عرض جدول عام: نفس الغلاف (تمرير أفقي + سطر العدد) لكل قوائم السجلات ---------- */
function tableBlock(head,rows,countText,emptyText){
  if(!rows.length&&emptyText) return `<div class="empty">${emptyText}</div>`;
  return `<div class="table-scroll">${mtable(head,rows)}</div><div class="count">${countText}</div>`;
}

/* ---------- عرض القوة ---------- */
function renderStats(){
  const o=DATA.officers, p=DATA.personnel, t=curDate();
  $("#navOfficers").textContent=o.active.length;
  $("#navPersonnel").textContent=p.active.length;
  $("#navLeaves").textContent=DATA.leaves.length;
  $("#today").textContent=new Date(t+"T00:00:00").toLocaleDateString("ar-EG",{weekday:"long",year:"numeric",month:"long",day:"numeric"});

  if(SECTION==="officers"||SECTION==="personnel"){
    const src=SECTION==="officers"?o:p;
    const onRest=src.active.filter(x=>currentLeave(x.id)).length;
    $("#forceStats").innerHTML=`
      <div class="stat"><span>على القوة</span><strong>${src.active.length}</strong></div>
      <div class="stat"><span>في الأرشيف</span><strong>${src.archive.length}</strong></div>
      <div class="stat"><span>في راحة اليوم</span><strong>${onRest}</strong></div>
      <div class="stat"><span>الإجمالي (قوة + أرشيف)</span><strong>${src.active.length+src.archive.length}</strong></div>`;
  }else if(SECTION==="leaves"){
    const cur=DATA.leaves.filter(l=>l.start<=t&&t<=l.end).length;
    const up=DATA.leaves.filter(l=>l.start>t).length;
    $("#leaveStats").innerHTML=`
      <div class="stat"><span>جارية الآن</span><strong>${cur}</strong></div>
      <div class="stat"><span>قادمة</span><strong>${up}</strong></div>
      <div class="stat"><span>منتهية</span><strong>${DATA.leaves.length-cur-up}</strong></div>
      <div class="stat"><span>إجمالي السجلات</span><strong>${DATA.leaves.length}</strong></div>`;
  }
}

/* ---------- قيادة الإدارة (الهيكل التنظيمي) ---------- */
const COMMAND_ROLES=()=>DATA.meta.command_roles||[];
const commandOf=id=>COMMAND_ROLES().find(r=>(DATA.command||{})[r]===id);

function renderCommand(){
  const box=$("#commandBar"); if(!box) return;
  box.classList.toggle("hidden",SECTION!=="officers");
  if(SECTION!=="officers") return;
  const officers=DATA.officers.active;
  box.innerHTML=`
    <div class="cmd-head">قيادة الإدارة
      <span class="muted">تشغيلهم ثابت يوميًا (إلا أيام الراحة) — غيّرهم مع حركة الضباط</span>
    </div>
    <div class="cmd-slots">${COMMAND_ROLES().map(role=>{
      const held=(DATA.command||{})[role];
      const p=held?personById(held):null;
      return `<label class="cmd-slot"><span class="cmd-role">${esc(role)}</span>
        <select data-cmd-role="${esc(role)}">
          <option value="">— غير محدد —</option>
          ${officers.map(o=>`<option value="${esc(o.id)}" ${o.id===held?"selected":""}>${esc(o.role)} / ${esc(o.name)}</option>`).join("")}
        </select>
        ${p?`<span class="cmd-now">${esc(p.role)} / ${esc(p.name)}</span>`
           :`<span class="cmd-now empty">مفيش ضابط محدد للمنصب ده</span>`}</label>`;
    }).join("")}</div>`;
  box.querySelectorAll("[data-cmd-role]").forEach(sel=>sel.onchange=async()=>{
    const out=await api("/api/command",{method:"PATCH",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({[sel.dataset.cmdRole]:sel.value||null})});
    if(!out){renderCommand(); return}   // رجّع الاختيار القديم لو الطلب اترفض
    showToast("تم تحديث القيادة"); load();
  });
}

function filterRows(rows){
  const q=$("#search").value.trim().toLowerCase();
  const rf=$("#restFilter").value;
  if(q) rows=rows.filter(p=>[p.name,p.code,p.phone,p.role,p.post,p.address].some(v=>String(v||"").toLowerCase().includes(q)));
  if(rf&&SECTION==="officers") rows=rf==="__rest_now"?rows.filter(p=>currentLeave(p.id)):rows.filter(p=>(p.rest_system||"—")===rf);
  return rows;
}

/* شارة المنصب القيادي جنب اسم الضابط في الجدول */
function cmdBadge(p){
  const role=commandOf(p.id);
  return role?` <span class="chip cmd">${esc(role)}</span>`:"";
}

function renderForce(){
  $("#forceTitle").textContent=SECTION==="officers"?"الضباط":"الأفراد";
  $("#forceSub").textContent=SECTION==="officers"?"سجل الضباط والأرشيف":"سجل الأفراد والأرشيف";
  $("#addBtn").textContent=SECTION==="officers"?"＋ إضافة ضابط":"＋ إضافة فرد";
  $("#restFilter").classList.toggle("hidden",SECTION!=="officers");

  const rows=filterRows(listOf(SECTION,BUCKET));
  const isOff=SECTION==="officers", isArch=BUCKET==="archive";
  const head=isOff
    ? (isArch?["الاسم","الرتبة","الأقدمية","الهاتف","العمل المسند","من","إلى","السبب","الإجراء"]
             :["الاسم","الرتبة","الأقدمية","الهاتف","العمل المسند","نظام الراحة","حالة اليوم","من","الإجراء"])
    : (isArch?["الاسم","الدرجة","الكود","الهاتف","العمل","العنوان","من","إلى","السبب","الإجراء"]
             :["الاسم","الدرجة","الكود","الهاتف","العمل","العنوان","من","الإجراء"]);

  const bodyRows=rows.map(p=>{
    const acts=isArch
      ? `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
         <button class="mini ok" data-action="restorePerson" data-id="${esc(p.id)}">استرجاع</button>
         <button class="mini bad" data-action="deleteRecord" data-id="${esc(p.id)}" data-extra="${dataAttr({name:p.name})}">حذف</button>`
      : `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
         ${isOff?`<button class="mini ok" data-action="openLeaveFor" data-id="${esc(p.id)}">راحة</button>`:""}
         <button class="mini bad" data-action="openRemove" data-id="${esc(p.id)}" data-extra="${dataAttr({name:p.name})}">إخراج</button>`;
    const cells=isOff
      ? (isArch?[`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)||"<span class='muted'>—</span>"}</td>`,`<td class="wrap">${esc(p.post)||"-"}</td>`,`<td>${fmt(p.join_date)}</td>`,`<td>${fmt(p.leave_date)}</td>`,`<td class="wrap">${esc(p.leave_reason)||"<span class='muted'>—</span>"}</td>`]
                :[`<td class="name">${esc(p.name)}${cmdBadge(p)}</td>`,`<td><span class="badge">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)||"<span class='muted'>—</span>"}</td>`,`<td class="wrap">${esc(p.post)||"-"}</td>`,`<td>${restLabel(p)}</td>`,`<td>${statusCell(p)}</td>`,`<td>${fmt(p.join_date)}</td>`])
      : (isArch?[`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge person">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)}</td>`,`<td>${esc(p.post)||"-"}</td>`,`<td class="wrap">${esc(p.address)||"-"}</td>`,`<td>${fmt(p.join_date)}</td>`,`<td>${fmt(p.leave_date)}</td>`,`<td class="wrap">${esc(p.leave_reason)||"<span class='muted'>—</span>"}</td>`]
                :[`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge person">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)}</td>`,`<td>${esc(p.post)||"-"}</td>`,`<td class="wrap">${esc(p.address)||"-"}</td>`,`<td>${fmt(p.join_date)}</td>`]);
    return `<tr>${cells.join("")}<td><div class="actions">${acts}</div></td></tr>`;
  });

  $("#tableWrap").innerHTML=tableBlock(head,bodyRows,`عدد النتائج: ${rows.length}`,"لا توجد بيانات لعرضها.");
}

/* ---------- عرض الراحات ---------- */
function renderLeaves(){
  const t=curDate();
  let rows=[...DATA.leaves];
  if(LEAVE_TAB==="current") rows=rows.filter(l=>l.start<=t&&t<=l.end);
  if(LEAVE_TAB==="upcoming") rows=rows.filter(l=>l.start>t);
  const q=$("#leaveSearch").value.trim().toLowerCase();
  if(q) rows=rows.filter(l=>String(l.name||"").toLowerCase().includes(q));
  const tf=$("#leaveTypeFilter").value;
  if(tf) rows=rows.filter(l=>l.type===tf);

  // ترتيب: النوع (أسبوعية، نصف شهرية، شهرية، ثم الباقي)، وجوّه كل نوع بالرتبة
  rows.sort((a,b)=>{
    const ta=leaveTypeIndex(a.type), tb=leaveTypeIndex(b.type);
    if(ta!==tb) return ta-tb;
    const pa=personById(a.person_id), pb=personById(b.person_id);
    const ra=rankIndex(pa?.role), rb=rankIndex(pb?.role);
    if(ra!==rb) return ra-rb;
    return (pa?.name||a.name).localeCompare(pb?.name||b.name,'ar');
  });

  let lastType=null;
  const bodyRows=rows.map(l=>{
    const divider=l.type!==lastType
      ?`<tr class="grouprow"><td colspan="9">${esc(l.type)}</td></tr>`:"";
    lastType=l.type;
    return divider+leaveRow(l,t);
  });
  $("#leaveWrap").innerHTML=tableBlock(
    ["الاسم","النوع","من","إلى","العودة","الأيام","الحالة","ملاحظات","الإجراء"],
    bodyRows,`عدد النتائج: ${rows.length}`,"لا توجد راحات مسجلة.");
}
function leaveRow(l,t){
    const live=l.start<=t&&t<=l.end, up=l.start>t;
    const state=live?`<span class="chip rest">جارية</span>`:up?`<span class="chip soon">قادمة</span>`:`<span class="chip done">منتهية</span>`;
    const p=personById(l.person_id);
    const isOff=DATA.officers.active.concat(DATA.officers.archive).some(x=>x.id===l.person_id);
    const who=p?`<span class="badge ${isOff?"":"person"}">${esc(p.role)}</span>`:'<span class="muted">(محذوف)</span>';
    return `<tr>
      <td class="name">${esc(l.name)}<div class="sub">${who}</div></td>
      <td><span class="chip ${l.type==="شهرية"?"m":l.type==="نصف شهرية"?"h":"w"}">${esc(l.type)}</span></td>
      <td>${fmt(l.start)}<div class="sub">تقصيرة ${dayName(addDays(l.start,-1))}</div></td><td>${fmt(l.end)}</td>
      <td>${fmt(l.return_date)}</td>
      <td class="num">${days(l.start,l.end)}</td>
      <td>${state}</td>
      <td class="wrap">${esc(l.note)||"<span class='muted'>—</span>"}</td>
      <td><div class="actions">
        <button class="mini" data-action="openLeaveEdit" data-id="${esc(l.id)}">تعديل</button>
        <button class="mini bad" data-action="deleteLeave" data-id="${esc(l.id)}" data-extra="${dataAttr({name:l.name})}">حذف</button>
      </div></td></tr>`;
}

/* ---------- التشغيل اليومي ---------- */
let DUTY=null, DUTY_TAB="board";
const KIND_CLS={"خارجية":"w","داخلية":"h","حراسات":"m","طبية":"on","بحث":"soon"};
const CATEGORY_OCCASIONAL="الخدمات الطارئة";
const CATEGORY_TARGETS="الأهداف";        // هدف ثابت طول اليوم — مالوش صباحية/ليلية
function toggleEnShift(){
  const noShift=$("#enCategory").value.trim()===CATEGORY_TARGETS;
  $("#enShiftWrap").classList.toggle("hidden",noShift);
  if(noShift) $("#enShift").value="";
}

async function loadDuty(day){
  const d=await api(`/api/duty/${day}`); if(!d) return;
  DUTY=d; render();
}
function renderSummary(s){
  const cell=(v,warn)=>`<td class="${warn&&!v?'zero':''}">${v}</td>`;
  const x=s["خارجية"],dl=s["داخلية"],tb=s["طبية"],kh=s["خوارج"];
  $("#balanceTag").innerHTML=s.balanced
    ? `<span class="chip on">متوازن ${s.counted}/${s["أصل القوة"]}</span>`
    : `<span class="chip rest">غير متوازن ${s.counted}/${s["أصل القوة"]}</span>`;
  $("#dutySummary").innerHTML=`<div class="table-scroll"><table class="table sum">
   <thead>
    <tr><th rowspan="2">أصل القوة</th><th colspan="3">الخدمات الخارجية</th><th colspan="2">الخدمات الداخلية</th>
        <th colspan="2">الخدمات الطبية</th><th colspan="7">الخوارج</th>
        <th rowspan="2">الحراسات المشددة</th><th rowspan="2">الصافي (${s["صافي"]})</th></tr>
    <tr><th>صباحية</th><th>ليلية</th><th>بحث</th><th>صباحية</th><th>ليلية</th>
        <th>موجود</th><th>راحة</th>
        <th>تقصيرة</th><th>راحة</th><th>طارئة</th><th>غياب</th><th>مرضي</th><th>فرقة</th><th>انتداب</th></tr>
   </thead>
   <tbody><tr class="sumrow">
     <td><b>${s["أصل القوة"]}</b></td>
     ${cell(x["صباحية"])}${cell(x["ليلية"])}${cell(x["بحث"])}
     ${cell(dl["صباحية"])}${cell(dl["ليلية"])}
     ${cell(tb["موجود"])}${cell(tb["راحة"])}
     ${cell(kh["تقصيرة"])}${cell(kh["راحة"])}${cell(kh["طارئة"])}${cell(kh["غياب"])}${cell(kh["مرضي"])}${cell(kh["فرقة"])}${cell(kh["انتداب"])}
     ${cell(s["حراسات"])}
     <td class="wrap">${s.net_names.map(esc).join("<br>")||"—"}</td>
   </tr></tbody></table></div>`;
}
function renderBoard(rows){
  const bodyRows=rows.map(r=>{
    const svc=r.services.length
      ? r.services.map(s=>`<span class="chip ${KIND_CLS[s.kind]||"w"}">${esc(s.name)}<i>${esc(s.shift)}</i></span>`).join(" ")
      : `<span class="muted">—</span>`;
    const grp=r.leave?`<span class="chip rest">${esc(r.leave.type)}</span><div class="sub">حتى ${fmt(r.leave.end)}</div>`
      : r.group==="صافي"?`<span class="chip on">صافي</span>`
      : `<span class="chip ${KIND_CLS[r.group]||"done"}">${esc(r.group)}${r.bucket?" · "+esc(r.bucket):""}</span>`;
    const gone=r.later_left?`<span class="chip done" title="خرج من القوة يوم ${fmt(r.later_left)}">خرج ${fmt(r.later_left)}</span>`:"";
    return `<tr class="${r.later_left?"was":""}">
      <td class="name">${esc(r.name)}<div class="sub">${esc(r.role)} ${gone}</div></td>
      <td>${svc}${r.taqseera?' <span class="chip taq">تقصيرة</span>':""}</td>
      <td>${grp}</td>
      <td class="wrap">${esc(r.note)||"<span class='muted'>—</span>"}</td>
      <td><button class="mini" ${r.leave?"disabled title='الضابط في راحة'":""} data-action="openAssign" data-id="${esc(r.id)}">تكليف</button></td>
    </tr>`;});
  const gone=rows.filter(r=>r.later_left).length;
  const countText=`قوة اليوم: ${rows.length} ضابط${gone?` — منهم ${gone} خرجوا من القوة بعد كده`:""}`;
  $("#dutyBoard").innerHTML=tableBlock(
    ["الضابط","الخدمات","الخانة في الإجمالي","نص التشغيل","الإجراء"],bodyRows,countText);
}
function renderCatalog(){
  const q=$("#svcSearch").value.trim().toLowerCase(), k=$("#svcKindFilter").value;
  let rows=DATA.services||[];
  if(q) rows=rows.filter(s=>s.name.toLowerCase().includes(q));
  if(k) rows=rows.filter(s=>s.kind===k);
  const bodyRows=rows.map(s=>`<tr>
      <td class="name">${esc(s.name)}</td>
      <td><span class="chip ${KIND_CLS[s.kind]||"w"}">${esc(s.kind)}</span></td>
      <td><div class="actions">
        <button class="mini" data-action="openSvc" data-id="${esc(s.id)}">تعديل</button>
        <button class="mini bad" data-action="deleteSvc" data-id="${esc(s.id)}" data-extra="${dataAttr({name:s.name})}">حذف</button>
      </div></td></tr>`);
  $("#catalogWrap").innerHTML=tableBlock(
    ["الخدمة","التصنيف","الإجراء"],bodyRows,`عدد الخدمات: ${rows.length}`,"لا توجد خدمات.");
}
/* ---------- لوحة التشغيل المختصرة (صفحة المطابقة، قابلة للتعديل الحر) ---------- */
let MATCH=null, MATCH_DAY=null;
async function loadMatch(day,force){
  if(!force && MATCH_DAY===day && MATCH) return renderMatch();
  const b=await api(`/api/board/${day}`); if(!b) return;
  MATCH=b; MATCH_DAY=day; renderMatch();
}
function mtable(head,rows){
  return `<table class="table mtable"><thead><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}
function reqBadges(reqs){
  if(!reqs||!reqs.length) return "";
  return reqs.map(r=>`<span class="chip w">${esc(r.label)}${r.count?" ×"+r.count:""}${r.note?" ("+esc(r.note)+")":""}</span>`).join(" ");
}
function tagBadges(tags){
  if(!tags||!tags.length) return "";
  return tags.map(t=>`<span class="chip soon">#${esc(t)}</span>`).join(" ");
}
function entryRow(cat,e,extraTags){
  const reqCell=reqBadges(e.requirements)+(extraTags&&extraTags.length?" "+tagBadges(extraTags):"");
  return `<tr>
    <td class="name">${esc(e.service)}${e.shift?`<div class="sub">${esc(e.shift)}</div>`:""}</td>
    <td>${e.officer_name?esc(e.officer_name):"<span class='muted'>—</span>"}</td>
    <td class="wrap">${reqCell}</td>
    <td class="wrap">${esc(e.note)||"<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openEntry" data-id="${esc(e.id)}" data-extra="${dataAttr({category:cat})}">تعديل</button>
      <button class="mini bad" data-action="deleteEntry" data-id="${esc(e.id)}" data-extra="${dataAttr({name:e.service})}">حذف</button>
    </div></td></tr>`;
}
function entryCard(cat){
  const rows=cat.entries.map(e=>entryRow(cat.name,e));
  const table=cat.entries.length
    ? mtable(["الخدمة","الضابط / المسؤول","الاحتياجات","ملاحظات","الإجراء"],rows)
    : `<div class="mempty">لا توجد خدمات — اضغط «إضافة» فوق</div>`;
  return `<div class="mcard">
    <h3>${esc(cat.name)}<span class="mcount">${cat.entries.length}</span>
      <button class="mini ok" data-action="openEntry" data-extra="${dataAttr({category:cat.name})}">＋ إضافة</button></h3>
    ${table}</div>`;
}
function specialCard(group){
  const rows=group.entries.map(e=>entryRow(e.category,e,e.tags.filter(t=>t!==group.tag)));
  const table=mtable(["الخدمة","الضابط / المسؤول","الاحتياجات","ملاحظات","الإجراء"],rows);
  return `<div class="mcard special">
    <h3>#${esc(group.tag)}<span class="mcount">${group.entries.length}</span>
      <span class="of-cat">ضمن «${esc(group.of_category)}»</span>
      <button class="mini ok" data-action="openSpecialEntry" data-extra="${dataAttr({tag:group.tag,category:group.of_category})}">＋ إضافة</button></h3>
    ${table}</div>`;
}
function renderMatch(){
  const wrap=$("#matchBoard");
  if(!MATCH){wrap.innerHTML=`<div class="empty">جارٍ التحميل...</div>`;return}
  const b=MATCH;

  const restRows=b.rests.map(x=>`<tr><td class="name">${esc(x.name)}</td>
    <td><span class="chip ${x.type==='شهرية'?'m':x.type==='نصف شهرية'?'h':'w'}">${esc(x.type)}</span></td>
    <td>${x.start?fmt(x.start):"-"}</td><td>${x.end?fmt(x.end):"-"}</td>
    <td>${x.return_date?fmt(x.return_date):"-"}</td></tr>`);
  const restHtml=mtable(["الضابط","النوع","من يوم","إلى يوم","العودة"],restRows);

  const taqRows=b.taqseeras.map(x=>`<tr><td class="name">${esc(x.name)}</td><td class="wrap">${esc(x.note)}</td></tr>`);
  const taqHtml=mtable(["الضابط","العمل قبل التقصيرة"],taqRows);

  const outRows=b.outsiders.map(x=>`<tr><td class="name">${esc(x.name)}</td>
    <td><span class="chip taq">${esc(x.reason)}</span></td><td class="wrap">${esc(x.note)}</td></tr>`);
  const outHtml=mtable(["الضابط","السبب","التفاصيل"],outRows);

  const netRows=b.net.map(x=>`<tr><td class="name">${esc(x.name)}</td><td class="wrap">${esc(x.post)||"<span class='muted'>—</span>"}</td></tr>`);
  const netHtml=mtable(["الضابط","العمل بالإدارة"],netRows);

  const statusCards=[
    ["الراحات",b.rests.length,restHtml],["التقصيرات",b.taqseeras.length,taqHtml],
    ["الخوارج",b.outsiders.length,outHtml],["عمل بالإدارة (الصافي)",b.net.length,netHtml],
  ].map(([t,n,h])=>`<div class="mcard"><h3>${t}<span class="mcount">${n}</span></h3>${n?h:'<div class="mempty">لا يوجد</div>'}</div>`);

  const specialHtml=`
    <div class="special-head">
      <div><h3>الخدمات الخاصة</h3>
      <p class="hint" style="margin:0">خدمات مرتبطة بحدث معيّن (مباراة، خطة انتشار...) — منفصلة هنا للمتابعة،
        لكنها تفضل منطقيًا ضمن تصنيفها الأصلي (غالبًا الخدمات الطارئة).</p></div>
      <button class="mini ok" data-action="openSpecialEntry" data-extra="${dataAttr({tag:"",category:CATEGORY_OCCASIONAL})}">＋ حدث خاص جديد</button>
    </div>
    ${b.special.length?`<div class="match-grid special-grid">${b.special.map(specialCard).join("")}</div>`
      :`<div class="mempty" style="margin:0 18px 20px">لا توجد خدمات خاصة اليوم.</div>`}`;

  wrap.innerHTML=`
    <div class="match-head">
      <span class="muted">لوحة التشغيل المختصرة — ${dayName(b.date)} ${fmt(b.date)}</span>
    </div>
    <div class="match-grid">
      ${b.categories.map(entryCard).join("")}
      ${statusCards.join("")}
    </div>
    ${specialHtml}`;
}

/* ---------- إضافة/تعديل خانة في اللوحة ---------- */
function reqRow(r){
  return `<div class="req-row">
    <input class="req-label" placeholder="النوع (ضابط/فرد/مج/وحدة...)" value="${esc(r.label||"")}">
    <input class="req-count" type="number" min="0" placeholder="العدد" value="${r.count||""}">
    <input class="req-note" placeholder="ملاحظة (قتالية/فض/رياضي...)" value="${esc(r.note||"")}">
    <button type="button" class="mini bad" data-action="removeReqRow">حذف</button>
  </div>`;
}
$("#addReqRow").onclick=()=>$("#reqRows").insertAdjacentHTML("beforeend",reqRow({}));
$("#enCategory").addEventListener("input",toggleEnShift);

let ENTRY_TAGS=[];
function renderTagChips(){
  $("#tagChips").innerHTML=ENTRY_TAGS.map((t,i)=>
    `<span class="chip soon">#${esc(t)} <a data-action="removeTag" data-id="${i}">×</a></span>`).join(" ");
}
$("#enTags").addEventListener("keydown",e=>{
  if(e.key!=="Enter") return;
  e.preventDefault();
  const v=$("#enTags").value.trim();
  if(v && !ENTRY_TAGS.includes(v)){ENTRY_TAGS.push(v); renderTagChips()}
  $("#enTags").value="";
});

function findEntry(entryId){
  for(const c of MATCH.categories){const e=c.entries.find(x=>x.id===entryId); if(e) return e}
  for(const g of MATCH.special){const e=g.entries.find(x=>x.id===entryId); if(e) return e}
  return null;
}
function openEntry(category,entryId,presetTags){
  const e=entryId?findEntry(entryId):null;
  $("#enId").value=entryId||"";
  $("#entryTitle").textContent=e?"تعديل خانة":`إضافة إلى «${category}»`;
  $("#categoryList").innerHTML=(DATA.meta.board_categories||[]).map(x=>`<option value="${esc(x)}">`).join("");
  $("#officerList").innerHTML=DATA.officers.active.map(o=>`<option value="${esc(o.name)}">`).join("");
  $("#tagList").innerHTML=(DATA.meta.service_tags||[]).map(x=>`<option value="${esc(x)}">`).join("");
  fillSelect($("#enShift"),[["","— بدون —"],...SHIFTS().map(x=>[x,x])]);

  $("#enCategory").value=e?e.category:category;
  $("#enService").value=e?e.service:"";
  $("#enShift").value=e?e.shift:"";
  $("#enOfficer").value=e?(e.officer_name||""):"";
  $("#enOfficer").dataset.officerId=e?(e.officer_id||""):"";
  $("#enNote").value=e?e.note:"";
  toggleEnShift();
  $("#reqRows").innerHTML=(e&&e.requirements||[]).map(reqRow).join("");
  ENTRY_TAGS=[...(e?e.tags:presetTags)||[]]; renderTagChips();
  openModal("entryModal");
}
function openSpecialEntry(tag,ofCategory){openEntry(ofCategory,null,tag?[tag]:[])}
$("#enOfficer").addEventListener("input",()=>{
  const o=DATA.officers.active.find(o=>o.name===$("#enOfficer").value);
  $("#enOfficer").dataset.officerId=o?o.id:"";
});
$("#entryForm").onsubmit=async e=>{
  e.preventDefault();
  const requirements=$$("#reqRows .req-row").map(r=>({
    label:r.querySelector(".req-label").value.trim(),
    count:parseInt(r.querySelector(".req-count").value)||0,
    note:r.querySelector(".req-note").value.trim(),
  })).filter(r=>r.label);
  const body={
    category:$("#enCategory").value.trim(), service:$("#enService").value.trim(),
    shift:$("#enShift").value, officer_id:$("#enOfficer").dataset.officerId||"",
    officer_name:$("#enOfficer").value.trim(), requirements, tags:ENTRY_TAGS,
    note:$("#enNote").value.trim(),
  };
  const id=$("#enId").value;
  const out=id
    ? await api(`/api/board/${MATCH_DAY}/entries/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
    : await api(`/api/board/${MATCH_DAY}/entries`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!out) return;
  closeModal("entryModal"); showToast(id?"تم حفظ التعديلات":"تمت الإضافة");
  await load(); await loadMatch(MATCH_DAY,true);
};
async function deleteEntry(id,name){
  if(!confirm(`حذف «${name}» من اليومية؟`)) return;
  const out=await api(`/api/board/${MATCH_DAY}/entries/${encodeURIComponent(id)}`,{method:"DELETE"});
  if(out){showToast("تم الحذف"); loadMatch(MATCH_DAY,true)}
}

function renderDuty(){
  const dateView=DUTY_TAB==="board"||DUTY_TAB==="match";
  $("#dutyBar").classList.toggle("hidden",!dateView);
  $("#dutySummary").classList.toggle("hidden",DUTY_TAB!=="board");
  $("#dutyBoard").classList.toggle("hidden",DUTY_TAB!=="board");
  $("#matchBoard").classList.toggle("hidden",DUTY_TAB!=="match");
  $("#catalogPanel").classList.toggle("hidden",DUTY_TAB!=="catalog");
  if(DUTY_TAB==="board"){
    if(DUTY){renderSummary(DUTY.summary);renderBoard(DUTY.rows)}
    else{$("#dutySummary").innerHTML="";$("#dutyBoard").innerHTML=`<div class="empty">جارٍ التحميل...</div>`}
  }
  else if(DUTY_TAB==="match"){ loadMatch($("#dutyDate").value||curDate()) }
  else renderCatalog();
}

function renderDashboard(){
  const o=DATA.officers, p=DATA.personnel;
  const onRest=o.active.filter(x=>currentLeave(x.id)).length;
  const dueCount=o.active.filter(x=>taqseeraDue(x)).length;
  $("#dashStats").innerHTML=`
    <div class="stat"><span>الضباط على القوة</span><strong>${o.active.length}</strong></div>
    <div class="stat"><span>الأفراد على القوة</span><strong>${p.active.length}</strong></div>
    <div class="stat"><span>في راحة اليوم</span><strong>${onRest}</strong></div>
    <div class="stat"><span>تنبيهات تقصيرة</span><strong>${dueCount}</strong></div>`;
  $("#qlOfficers").textContent=o.active.length;
  $("#qlPersonnel").textContent=p.active.length;
  $("#qlLeaves").textContent=DATA.leaves.length;

  const day=curDate();
  $("#dashToday").innerHTML=`<p class="hint" style="margin:0">
    ${dayName(day)} ${fmt(day)} — لمتابعة تفاصيل تشغيل اليوم افتح
    «يومية التشغيل» أو «لوحة التشغيل المختصرة» من القائمة.</p>`;
}

function render(){
  renderStats();
  renderAlerts();
  $("#alerts").classList.toggle("hidden",!(SECTION==="dashboard"||SECTION==="officers"));
  $("#dashboardSection").classList.toggle("hidden",SECTION!=="dashboard");
  $("#forceSection").classList.toggle("hidden",!(SECTION==="officers"||SECTION==="personnel"));
  $("#leavesSection").classList.toggle("hidden",SECTION!=="leaves");
  $("#dutySection").classList.toggle("hidden",SECTION!=="duty");
  renderCommand();
  if(SECTION==="dashboard") renderDashboard();
  else if(SECTION==="leaves") renderLeaves();
  else if(SECTION==="duty") renderDuty();
  else renderForce();
}

async function load(){
  const d=await api("/api/data"); if(!d) return;
  DATA=d;
  fillSelect($("#restFilter"),[["","كل أنظمة الراحة"],["__rest_now","في راحة اليوم"],...REST_SYSTEMS().map(x=>[x,x])],true);
  fillSelect($("#leaveTypeFilter"),[["","كل الأنواع"],...LEAVE_TYPES().map(x=>[x,x])],true);
  fillSelect($("#svcKindFilter"),[["","كل التصنيفات"],...KINDS().map(x=>[x,x])],true);
  $("#navDuty").textContent=(DATA.services||[]).length;
  if(!$("#dutyDate").value){
    const days=DATA.duty_days||[];
    $("#dutyDate").value=days.includes(curDate())?curDate():(days[days.length-1]||curDate());
  }
  render();
}
function fillSelect(el,pairs,keep){
  const old=keep?el.value:null;
  el.innerHTML=pairs.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join("");
  if(old!==null&&pairs.some(([v])=>v===old)) el.value=old;
}

/* ---------- نماذج القوة ---------- */
function updateRoles(){
  const isOff=$("#type").value==="officer";
  fillSelect($("#role"),(isOff?OFFICER_ROLES:PERSONNEL_ROLES).map(x=>[x,x]),true);
  $("#restSysWrap").classList.toggle("hidden",!isOff);
  $("#restDayWrap").classList.toggle("hidden",!isOff);
  $("#addressWrap").classList.toggle("hidden",isOff);
  toggleRestDay();
}
function toggleRestDay(){
  $("#restDayWrap").style.display=($("#fRestSystem").value==="أسبوعية"&&$("#type").value==="officer")?"":"none";
}
function openModal(id){$("#"+id).classList.remove("hidden")}
function closeModal(id){$("#"+id).classList.add("hidden")}

function openPerson(id){
  const p=id?personById(id):null;
  $("#personId").value=id||"";
  $("#personModalTitle").textContent=p?"تعديل البيانات":"إضافة إلى القوة";
  $("#personSubmit").textContent=p?"حفظ التعديلات":"حفظ وإضافة للقوة";
  fillSelect($("#fRestSystem"),REST_SYSTEMS().map(x=>[x,x]));
  fillSelect($("#fRestDay"),[["","— بدون —"],...WEEKDAYS().map(x=>[x,x])]);

  const isOff=p?DATA.officers.active.concat(DATA.officers.archive).some(x=>x.id===id):SECTION!=="personnel";
  $("#type").value=isOff?"officer":"personnel";
  $("#type").disabled=!!p;
  updateRoles();

  $("#fName").value=p?p.name||"":"";
  $("#fCode").value=p?p.code||"":"";
  $("#fPhone").value=p?p.phone||"":"";
  $("#fJoin").value=p?p.join_date||"":curDate();
  $("#fPost").value=p?p.post||"":"";
  $("#fAddress").value=p?p.address||"":"";
  if(p&&p.role) fillSelect($("#role"),[[p.role,p.role],...(isOff?OFFICER_ROLES:PERSONNEL_ROLES).filter(x=>x!==p.role).map(x=>[x,x])]);
  $("#fRestSystem").value=(p&&p.rest_system)||"—";
  $("#fRestDay").value=(p&&p.rest_day)||"";
  toggleRestDay();

  const archived=!!(p&&p.status==="archived");
  $("#archiveFields").classList.toggle("hidden",!archived);
  if(archived){$("#fLeaveDate").value=p.leave_date||"";$("#fLeaveReason").value=p.leave_reason||""}
  openModal("personModal");
}

$("#personForm").onsubmit=async e=>{
  e.preventDefault();
  const id=$("#personId").value;
  const isOff=$("#type").value==="officer";
  const body={name:$("#fName").value,role:$("#role").value,code:$("#fCode").value,
    phone:$("#fPhone").value,join_date:$("#fJoin").value,post:$("#fPost").value};
  if(isOff){body.rest_system=$("#fRestSystem").value;body.rest_day=$("#fRestSystem").value==="أسبوعية"?$("#fRestDay").value:""}
  else body.address=$("#fAddress").value;
  if(!$("#archiveFields").classList.contains("hidden")){
    body.leave_date=$("#fLeaveDate").value; body.leave_reason=$("#fLeaveReason").value;
  }
  let out;
  if(id) out=await api(`/api/person/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  else out=await api("/api/person",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...body,type:$("#type").value})});
  if(!out) return;
  closeModal("personModal"); showToast(id?"تم حفظ التعديلات":"تمت الإضافة إلى القوة"); load();
};

function openRemove(id,name){
  $("#removeId").value=id; $("#removeName").textContent=`سيتم إخراج: ${name}`;
  $("#leaveDate").value=curDate(); $("#reason").value=""; openModal("removeModal");
}
$("#removeForm").onsubmit=async e=>{
  e.preventDefault();
  const out=await api(`/api/person/${encodeURIComponent($("#removeId").value)}/remove`,
    {method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify({leave_date:$("#leaveDate").value,reason:$("#reason").value})});
  if(!out) return;
  closeModal("removeModal"); showToast("تم الإخراج وحفظ السجل في الأرشيف"); load();
};
async function restorePerson(id){
  if(!confirm("استرجاع هذا السجل إلى القوة؟")) return;
  const out=await api(`/api/person/${encodeURIComponent(id)}/restore`,{method:"POST"});
  if(out){showToast("تم الاسترجاع إلى القوة"); load()}
}
async function deleteRecord(id,name){
  if(!confirm(`حذف سجل «${name}» نهائيًا من الأرشيف؟ لا يمكن التراجع.`)) return;
  const out=await api(`/api/person/${encodeURIComponent(id)}`,{method:"DELETE"});
  if(out){showToast("تم حذف السجل"); load()}
}

/* ---------- نموذج الراحة ---------- */
function openLeave(leaveId,personId){
  const lv=leaveId?DATA.leaves.find(x=>x.id===leaveId):null;
  $("#leaveId").value=leaveId||"";
  $("#leaveModalTitle").textContent=lv?"تعديل الراحة":"تسجيل راحة";
  const people=[...DATA.officers.active,...DATA.personnel.active];
  fillSelect($("#lvPerson"),people.map(p=>[p.id,`${p.name} — ${p.role}`]));
  fillSelect($("#lvType"),LEAVE_TYPES().map(x=>[x,x]));
  const pid=lv?lv.person_id:personId;
  if(pid) $("#lvPerson").value=pid;
  const p=personById(pid);
  $("#lvNote").value=lv?(lv.note||""):"";
  $("#lvType").value=lv?lv.type:(p&&p.rest_system&&p.rest_system!=="—"?p.rest_system:"راحة");
  if(lv){
    $("#lvStart").value=lv.start; $("#lvEnd").value=lv.end;
  }else{
    // للراحة الأسبوعية ابدأ من أقرب يوم راحة، وطبّق المدة القياسية
    const w=(p&&p.rest_system==="أسبوعية"&&p.rest_day)?nextWeekday(p.rest_day,curDate()):null;
    $("#lvStart").value=w||curDate();
    $("#lvEnd").value=$("#lvStart").value;
    applyDuration();
  }
  updateHint(); openModal("leaveModal");
}
function openLeaveFor(personId){openLeave(null,personId)}
function openLeaveEdit(leaveId){openLeave(leaveId)}
/* المدة القياسية: شهرية 7 أيام، نصف شهرية 3، أسبوعية يوم واحد */
function applyDuration(){
  const n=DURATIONS()[$("#lvType").value], s=$("#lvStart").value;
  if(!n||!s) return false;
  $("#lvEnd").value=addDays(s,n-1);
  return true;
}
function updateHint(){
  const s=$("#lvStart").value,e=$("#lvEnd").value,t=$("#lvType").value;
  if(!s||!e||e<s){$("#lvHint").textContent="";return}
  const std=DURATIONS()[t];
  const n=days(s,e);
  let msg=`المدة ${n} يوم — العودة يوم ${dayName(addDays(e,1))} ${fmt(addDays(e,1))}`;
  msg+=` • التقصيرة يوم ${dayName(addDays(s,-1))} ${fmt(addDays(s,-1))}`;
  if(std&&n!==std) msg+=` ⚠ المدة القياسية لـ«${t}» ${std} أيام`;
  $("#lvHint").textContent=msg;
}
$("#lvStart").oninput=()=>{
  if(!applyDuration()&&$("#lvEnd").value<$("#lvStart").value) $("#lvEnd").value=$("#lvStart").value;
  updateHint();
};
$("#lvEnd").oninput=updateHint;
$("#lvType").onchange=()=>{applyDuration();updateHint()};
$("#lvPerson").onchange=()=>{
  const p=personById($("#lvPerson").value);
  if(p&&p.rest_system&&p.rest_system!=="—"&&!$("#leaveId").value){
    $("#lvType").value=p.rest_system;
    if(p.rest_system==="أسبوعية"&&p.rest_day){
      const w=nextWeekday(p.rest_day,curDate());
      if(w) $("#lvStart").value=w;
    }
    applyDuration(); updateHint();
  }
};
$("#leaveForm").onsubmit=async e=>{
  e.preventDefault();
  const id=$("#leaveId").value;
  const body={person_id:$("#lvPerson").value,type:$("#lvType").value,
    start:$("#lvStart").value,end:$("#lvEnd").value,note:$("#lvNote").value};
  const out=id
    ? await api(`/api/leaves/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
    : await api("/api/leaves",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!out) return;
  closeModal("leaveModal"); showToast(id?"تم تعديل الراحة":"تم تسجيل الراحة"); load();
};
async function deleteLeave(id,name){
  if(!confirm(`حذف سجل راحة «${name}»؟`)) return;
  const out=await api(`/api/leaves/${encodeURIComponent(id)}`,{method:"DELETE"});
  if(out){showToast("تم حذف الراحة"); load()}
}

/* ---------- تكليف ضابط ---------- */
function openAssign(id){
  const row=DUTY.rows.find(r=>r.id===id); if(!row) return;
  $("#assignPerson").value=id;
  $("#assignTitle").textContent=`تكليف: ${row.name}`;
  $("#assignHint").textContent=`يوم ${dayName(DUTY.date)} ${fmt(DUTY.date)} — الضابط بدون خدمة بيتحسب في الصافي.`;
  const chosen=new Map(row.services.map(s=>[s.id,s.shift]));
  $("#assignServices").innerHTML=(DATA.services||[]).map(s=>`
    <label class="svc-item ${chosen.has(s.id)?"on":""}">
      <input type="checkbox" value="${s.id}" ${chosen.has(s.id)?"checked":""}>
      <span class="chip ${KIND_CLS[s.kind]||"w"}">${esc(s.kind)}</span>
      <span class="svc-name">${esc(s.name)}</span>
      <select class="svc-shift">${SHIFTS().map(x=>`<option ${chosen.get(s.id)===x?"selected":""}>${x}</option>`).join("")}</select>
    </label>`).join("");
  $$("#assignServices input").forEach(cb=>cb.onchange=()=>cb.closest(".svc-item").classList.toggle("on",cb.checked));
  $("#assignTaq").checked=!!row.taqseera;
  $("#assignStatus").value=row.group==="خوارج"&&["انتداب","غياب"].includes(row.bucket)?row.bucket:"";
  $("#assignNote").value=row.note||"";
  openModal("assignModal");
}
$("#assignForm").onsubmit=async e=>{
  e.preventDefault();
  const items=$$("#assignServices .svc-item").filter(l=>l.querySelector("input").checked)
    .map(l=>({service_id:l.querySelector("input").value,shift:l.querySelector(".svc-shift").value}));
  const out=await api(`/api/duty/${DUTY.date}/${encodeURIComponent($("#assignPerson").value)}`,
    {method:"PUT",headers:{"Content-Type":"application/json"},
     body:JSON.stringify({items,taqseera:$("#assignTaq").checked,
       status:$("#assignStatus").value,note:$("#assignNote").value})});
  if(!out) return;
  DUTY=out; closeModal("assignModal"); showToast("تم حفظ التكليف"); renderDuty();
};

/* ---------- كتالوج الخدمات ---------- */
function openSvc(id){
  const s=id?(DATA.services||[]).find(x=>x.id===id):null;
  $("#svcId").value=id||"";
  $("#svcTitle").textContent=s?"تعديل خدمة":"خدمة جديدة";
  $("#svcName").value=s?s.name:"";
  fillSelect($("#svcKind"),KINDS().map(x=>[x,x]));
  if(s) $("#svcKind").value=s.kind;
  openModal("svcModal");
}
$("#svcForm").onsubmit=async e=>{
  e.preventDefault();
  const id=$("#svcId").value, body={name:$("#svcName").value,kind:$("#svcKind").value};
  const out=id
    ? await api(`/api/services/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
    : await api("/api/services",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!out) return;
  closeModal("svcModal"); showToast(id?"تم تعديل الخدمة":"تمت إضافة الخدمة");
  await load(); if(DUTY) await loadDuty(DUTY.date);
};
async function deleteSvc(id,name){
  if(!confirm(`حذف خدمة «${name}» من الكتالوج؟`)) return;
  const out=await api(`/api/services/${encodeURIComponent(id)}`,{method:"DELETE"});
  if(out){showToast("تم حذف الخدمة"); load()}
}

/* ---------- توزيع النقرات على الأزرار المُنشأة ديناميكيًا (بديل onclick المضمّن) ----------
   كل زرار متولّد من قالب نص بيحمل data-action (+ data-id/data-extra عند اللزوم) بدل ما
   يحمل onclick="fn('${قيمة حرة}')" مباشر. النقر بيتلقط هنا مرة واحدة على مستوى الصفحة،
   والقيم بتتقرأ من الـ dataset (نص عادي، لا يتجمّع كـ JS أبدًا) — فمفيش أي طريقة لقيمة
   حرة (اسم/خدمة/وسم) إنها تكسر الصفحة أو تنفّذ كود مهما كان محتواها. */
const ACTIONS={
  openPerson:id=>openPerson(id),
  restorePerson:id=>restorePerson(id),
  deleteRecord:(id,extra)=>deleteRecord(id,extra.name),
  openLeaveFor:id=>openLeaveFor(id),
  openRemove:(id,extra)=>openRemove(id,extra.name),
  openLeaveEdit:id=>openLeaveEdit(id),
  deleteLeave:(id,extra)=>deleteLeave(id,extra.name),
  openAssign:id=>openAssign(id),
  openSvc:id=>openSvc(id),
  deleteSvc:(id,extra)=>deleteSvc(id,extra.name),
  openEntry:(id,extra)=>openEntry(extra.category,id||null),
  deleteEntry:(id,extra)=>deleteEntry(id,extra.name),
  openSpecialEntry:(id,extra)=>openSpecialEntry(extra.tag,extra.category),
  removeTag:id=>{ENTRY_TAGS.splice(Number(id),1); renderTagChips()},
  removeReqRow:(id,extra,el)=>el.closest(".req-row").remove(),
};
document.addEventListener("click",e=>{
  const el=e.target.closest("[data-action]");
  if(!el) return;
  const action=ACTIONS[el.dataset.action];
  if(!action) return;
  let extra={};
  if(el.dataset.extra){ try{extra=JSON.parse(el.dataset.extra)}catch(err){} }
  action(el.dataset.id,extra,el);
});

/* ---------- ربط الأحداث ---------- */
const shiftDay=n=>{const d=addDays($("#dutyDate").value||curDate(),n);$("#dutyDate").value=d;loadDuty(d)};
$("#dayPrev").onclick=()=>shiftDay(-1);
$("#dayNext").onclick=()=>shiftDay(1);
$("#dayToday").onclick=()=>{$("#dutyDate").value=curDate();loadDuty(curDate())};
$("#dayTomorrow").onclick=async()=>{
  const tmr=addDays(curDate(),1);
  $("#dutyDate").value=tmr;
  goToSection("duty","match");
  await loadMatch(tmr,true);
  await showTomorrowHandover(tmr);
};

/* تنبيه تسليم واستلام: مين هيبدأ راحته بكرة (تقصيرته النهاردة) وكان بيشتغل إيه،
   عشان يتكلّف بديل — من غير ما ننسخ التكليفات تلقائي (خدمات كتير بتتغير يوميًا). */
async function showTomorrowHandover(tmr){
  const today=curDate();
  if(tmr!==addDays(today,1)) return;
  const leaving=DATA.officers.active.filter(p=>{const q=taqseera(p); return q&&q.date===today});
  if(!leaving.length) return;
  const todayBoard=await api(`/api/board/${today}`);
  const rows=leaving.map(p=>{
    let service="بدون خدمة مسجلة النهاردة";
    if(todayBoard) for(const cat of todayBoard.categories){
      const e=cat.entries.find(x=>x.officer_id===p.id);
      if(e){service=`${e.service}${e.shift?" ("+e.shift+")":""}`;break}
    }
    return `<li><span class="a-name">${esc(p.role)} / ${esc(p.name)}</span>
      <span class="a-mid">في راحة (${esc(p.rest_system)}) بداية من بكرة</span>
      <span class="a-rest">كان بيشتغل: ${esc(service)}</span></li>`;
  });
  $("#matchBoard").insertAdjacentHTML("afterbegin",`<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">↷</span><strong>تسليم واستلام بكرة</strong>
      <span class="muted">${leaving.length} ضابط هيبدأ راحته بكرة — محتاجين تكليف بديل على خدمتهم</span></div>
    <ul class="alert-list">${rows.join("")}</ul></div>`);
}
$("#dutyDate").onchange=()=>loadDuty($("#dutyDate").value);
$("#svcSearch").oninput=renderCatalog;
$("#svcKindFilter").onchange=renderCatalog;
$("#addSvcBtn").onclick=()=>openSvc(null);

const DUTY_PAGE_META={
  board:["يومية التشغيل","تشغيل الضباط اليومي وجدول الإجمالي"],
  match:["لوحة التشغيل المختصرة","مطابقة الخدمات اليومية — قابلة للتعديل الحر"],
  catalog:["كتالوج الخدمات","تصنيف الخدمات المستخدمة في جدول الإجمالي"],
};
function goToSection(section,dutyTab){
  SECTION=section;
  if(section==="duty" && dutyTab) DUTY_TAB=dutyTab;
  $$(".navbtn").forEach(x=>{
    const match=x.dataset.section==="duty"
      ? (section==="duty" && x.dataset.duty===DUTY_TAB)
      : x.dataset.section===section;
    x.classList.toggle("active",match);
  });
  if(section==="duty"){
    const[title,sub]=DUTY_PAGE_META[DUTY_TAB]||DUTY_PAGE_META.board;
    $("#dutyPageTitle").textContent=title; $("#dutyPageSub").textContent=sub;
  }
  BUCKET="active";
  $$("[data-bucket]").forEach(x=>x.classList.toggle("active",x.dataset.bucket==="active"));
  $("#search").value=""; $("#restFilter").value="";
  $("#sidebar").classList.remove("open");
  render();
  if(section==="duty" && DUTY_TAB==="board" && !DUTY) loadDuty($("#dutyDate").value||curDate());
}
$$(".navbtn, .quick-links button").forEach(b=>b.onclick=()=>goToSection(b.dataset.section,b.dataset.duty));
$("#burgerBtn").onclick=()=>$("#sidebar").classList.toggle("open");
$$("[data-bucket]").forEach(b=>b.onclick=()=>{
  $$("[data-bucket]").forEach(x=>x.classList.remove("active")); b.classList.add("active");
  BUCKET=b.dataset.bucket; $("#search").value=""; render();
});
$$("[data-lv]").forEach(b=>b.onclick=()=>{
  $$("[data-lv]").forEach(x=>x.classList.remove("active")); b.classList.add("active");
  LEAVE_TAB=b.dataset.lv; render();
});
$$("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
$$(".modal").forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.add("hidden")});
document.onkeydown=e=>{if(e.key==="Escape")$$(".modal").forEach(m=>m.classList.add("hidden"))};

$("#search").oninput=render;
$("#restFilter").onchange=render;
$("#leaveSearch").oninput=render;
$("#leaveTypeFilter").onchange=render;
$("#addBtn").onclick=()=>openPerson(null);
$("#addLeaveBtn").onclick=()=>openLeave(null);
$("#type").onchange=updateRoles;
$("#fRestSystem").onchange=toggleRestDay;

/* اسم من قام بالتعديل — حقل اختياري بيتحفظ محليًا وبيتبعت مع أي طلب تعديل
   (POST/PUT/PATCH/DELETE) كـ header، عشان يتسجل في سجل التدقيق (logs/audit.log)
   من غير أي نظام حسابات أو تسجيل دخول. */
const editedByEl=$("#editedBy");
if(editedByEl){
  editedByEl.value=localStorage.getItem("editedBy")||"";
  editedByEl.addEventListener("input",()=>localStorage.setItem("editedBy",editedByEl.value.trim()));
}

load();
