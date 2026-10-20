# مواصفة fidelity: اليومية التفصيلية (board)

هذه المواصفة مبنية على 60 ملفًا فعليًا من 2026-08-01 إلى 2026-09-29، وعلى تصدير النظام باستخدام نسخة البيانات المحددة في الطلب. كل إشارة من نوع `day/cell` تعني صفًا/خلية في `word/document.xml` بعد احتساب الخلايا الفيزيائية، لا نصًا بصريًا مخمّنًا.

## 1) قواعد الاسم والمكان

- ملف الأرشيف authoritative هو `2026/<month>/<day>/<day>.docx`؛ الشهر واليوم بلا zero padding (`2026/9/28/28.docx`).
- يجب تجاهل `~$...`, `.tmp`, `desktop.ini`، و`<day>..docx` و`<day>-<m>-2026.docx`؛ هذه أنواع أخرى.
- PDF الموجود بجانب Word نسخة مطبوعة مرجعية مفيدة للمراجعة البصرية، لكنه ليس input المقارن الأساسي.
- endpoint النظام هو `GET /api/board/<day>/export.docx` (`backend/routes/board.py:109-128`). إذا وجد `source_docs/board/<day>.docx` يعيده حرفيًا (`backend/store.py:126-128` و`backend/routes/board.py:117-124`)؛ وإلا يبني من `build_board(...)` ثم `build_docx(...)` (`backend/routes/board.py:125-127`).

## 2) خط التطور المقاس

كل الملفات A4 تقريبًا (`w=11906,h=16838` twips)، portrait، لكن إعدادات Word اليدوية ليست ثابتة: في 2026-09-29 كانت `top=249,right=720,bottom=4,left=567` twips (archive `word/document.xml/sectPr`).

| الفترة/ظهور أول | القياس | الدليل |
|---|---|---|
| 2026-08-01 إلى 2026-09-03 (46 يومًا) | grid من 4 أعمدة؛ عدد الصفوف متغير 23–41؛ العرض يتبدل يدويًا يوميًا | 2026-08-01: `2686,3264,2131,2685`، 27 صفًا؛ 2026-08-31: `2977,2978,1843,2967`، 31 صفًا؛ 2026-09-03: `2969,2835,2136,2825`، 33 صفًا |
| 2026-09-04 | 5 أعمدة لأول مرة، لكن عمودًا شبه صفري (`12` twips)، 29 صفًا | `2026/9/4/4.docx`, `tblGrid`=`2828,12,2964,1855,3106` |
| 2026-09-05 إلى 2026-09-16 | رجوع متكرر إلى 4 أعمدة؛ لا يوجد تحول monotonic | 2026-09-05 = 4 أعمدة، 2026-09-16 = 4 أعمدة |
| 2026-09-17 إلى 2026-09-27 | 5 أعمدة؛ widths متغيرة، وأحيانًا عمود ثالث ضيق (`711–993`) | 2026-09-17: `1844,2977,851,1975,3118`; 2026-09-21: `1835,2842,993,1847,3248` |
| 2026-09-28 | 6 أعمدة؛ `1694,9,2974,711,2129,3248`، 34 صفًا | `2026/9/28/28.docx` |
| 2026-09-29 | 6 أعمدة؛ `1691,2951,711,2435,2954,16`، 34 صفًا | `2026/9/29/29.docx` |

الـlatest defensible format هو بنية أواخر 9/28–9/29 ذات grid سداسي، مع اعتبار widths اليدوية نفسها غير ثابتة. 9/29 هو آخر يوم ولذلك هو المرجع النصي/البصري، لكن 9/28 يثبت أن الستة أعمدة ليست أثرًا منفردًا. لا يجوز اختزال آخر يومين إلى widths واحدة.

## 3) مواصفة latest format

### الصفحة والنص

- A4 portrait؛ section bidi/RTL بحسب Word، مع margins المقاسة أعلاه في 9/29.
- آخر ملفين يستعملان `Bahnschrift SemiBold` في الجدول، بمحاذاة center؛ عناوين المقاطع bold، والخلايا التشغيلية bold أيضًا في XML (`2026/9/29/29.docx`, أول 15 `w:r` داخل الجدول).
- الأرشيف لا يستخدم placeholder النظام `—` في كل الخانات؛ الخانات الفارغة غالبًا تبقى empty XML، بينما بعض الخانات التشغيلية تستخدم `ــــــــــــــــــــ` (9/29 r16c5 وr17c5).

### الشبكة والصفوف

الـ6 grid columns تنقسم بصريًا إلى نصفين:

1. يسار/يمين الجدول حسب RTL: نصف الخدمات الأساسية من عمودين (اسم الخدمة، القائم بها).
2. نصف الخدمات الطارئة من ثلاثة مساحات منطقية: اسم الخدمة، القوام/التفاصيل، مع دمج فعلي يتغير حسب الصف؛ في 9/29 صف الخدمة الطارئة العادي يظهر فيزيائيًا كـ`c3-4` merged للاسم و`c5-6` merged للقوام.

ترتيب 9/29 (34 صفًا، الصف 0 أولًا):

`الخدمات الاساسية` + `الخدمات الطارئة` header؛ صفوف الأساسية؛ صفوف الطارئة؛ `الاهداف`؛ صف مشرف الأهداف ثم سبعة أهداف؛ `خدمات سجن قوات الامن`؛ صفوف تأمين السجن/المباحث/فرد التأمين/الملاحظة؛ `ضابط عظيم وأمن المعسكر الفرعي`؛ صباحية/ليلية؛ `عمل بالادارة`؛ صفوف الضباط ووصف العمل؛ ثم `الخوارج` وما تحته من راحة/طارئة/فرقة/إجازات. عدد الصفوف في كل منطقة متغير، عدا الأهداف الثمانية والـfixed slots التي يفرضها النظام منطقيًا.

أمثلة مباشرة من 9/29:

- r0: عناوين basic وemergency، basic header span=2، emergency header span=3، shading `D9D9D9`.
- r1: `تدخل سريع صبح | نقيب/عبدالرحمن طارق | حملة امن وطني 12ظ | 2فرد + 2 مج`.
- r10: `الاهداف`، span=2.
- r11–r18: مشرف + سبعة أهداف، ثم بداية خدمات السجن في نفس النطاق الشمالي.
- r19: `ضابط عظيم وأمن المعسكر الفرعي` مقابل `الخوارج`، وكلاهما shading `D9D9D9`.
- r20–r21: `فترة صباحية` و`فترة ليلية`؛ الخانة الفارغة تمثل vacancy، لا حذف صف.

## 4) data mapping and formatting rules

| منطقة/خلية | المعنى الأرشيفي | مصدر النظام/قاعدة التحويل | دليل |
|---|---|---|---|
| basic name | اسم الخدمة + الفترة، مثل `تدخل سريع صبح` | `backend/board.py:_row` (279–304) ثم `label` عبر 289–290؛ الفترة تدخل الاسم فقط للقسم الأساسي | 9/29 r1c0/r2c0 |
| basic assignee | الضابط، `rank/name` مع slash | `backend/board_export.py:_basic_assignee` (128–138)؛ `_who` (59–62) يبني `role + "/ " + name` | 9/29 r1c1=`نقيب/عبدالرحمن طارق` |
| emergency name | اسم الخدمة/المأمورية والتوقيت المكتوب | `_row` يحفظ `name,shift,source_manning`; `_word_rows` (235–269) يضع label في النصف الأيسر | 9/29 r1c2-3=`حملة امن وطني 12ظ` |
| emergency strength | فرد/مجند/تفاصيل القوام، وغالبًا `2فرد + 2 مج` | `_compact_manning` (141–155) أو `source_manning` كما هو؛ لكنه لا يطابق دائمًا اختصار/ترتيب الأرشيف | 9/29 r1c4-5 |
| targets | `مشرف الأهداف` ثم سبعة أهداف بترتيب ثابت؛ القائد العام منفصل عن المعيّن فعليًا | `_target_slots` و`_blank_target` (`backend/board.py:374-403`)؛ القائد من `_target_commanders` (327–358)، والمكلّف من `officers` | 9/29 r10–r18؛ يوم 2026-06-02 موثق في تعليق الدالة كحالة تغطية مختلفة |
| prison/status block | خدمات السجن، المباحث، فرد التأمين، الملاحظة | أقسام `SECTION_PRISON` وcomputed sections في `build_board` (620–698)، ثم `_presentation_sections` (173–202) | 9/29 r11–r18 |
| fixed slots | صباحية/ليلية للمعسكر الفرعي، ضابط عظيم، أمن الإدارة | `_fixed_slots`/`FIXED_SLOT_NAMES` و`build_board` (694–696)؛ الصفان ثابتان حتى vacancy | 9/29 r19–r21 |
| admin work | ضابط ثم نص العمل/المنصب | `build_board` (648–676) ينتج `admin_work`; `_officer_desc` (158–170) يختار `text` أو fixed officer | 9/29 r22–r33 |
| rests/outsiders | نوع الراحة + dates أو reason/note | `build_board` (657–667) ثم `_presentation_sections` (181–194) و`_fmt_date` (51–56) | 9/29 r20–r25 |
| empty cell | vacancy أو مساحة غير مستعملة | exporter الحالي يكتب `—` من `_cell_text` (93–107)، بينما archive يترك بعض الخلايا فارغة أو يكتب dash filler؛ هذه ليست equivalent formatting | 9/29 r6–r9 وr16–r17 |
| row order | basic, targets, subcamp/admin يمين؛ emergency/prison/outsiders يسار | `build_board` order (678–698) و`build_docx` right/left lists (بعد 300) | 9/29 row sequence |

## 5) gap analysis المقاس

الأداة `tools/fidelity/board.py` قورنت بها 60 archive/system DOCX. التطبيع يزيل tatweel/diacritics، يطبع الأرقام العربية، ويقارن alef/yaa variants وwhitespace. المقارنة positional على الخلايا الفيزيائية؛ لذلك DATA-MISSING/EXTRA بعد انزياح grid ليست ادعاءً مستقلًا بفقد سجل إلا مع مراجعة row alignment.

النتيجة الإجمالية: `STRUCTURE=151`, `DATA-DIFFERENT=3868`, `DATA-EXTRA=2507`, `DATA-MISSING=1078`, `ORDER=0`. من 2026-09-21 إلى 2026-09-29، وهي 9 أيام، كل الفئات صفر؛ هذا تطابق XML سببه route passthrough، لا إثبات أن `build_docx` يعيد إنشاء archive. في اليومين 9/28 و9/29 كان التصدير 6 أعمدة بالضبط لأنه أعاد source doc.

الأهم، بالترتيب:

1. **grid/merge/column structure — 51 يومًا.** `build_docx` يعلن قالبًا ثابتًا من 5 أعمدة (`backend/board_export.py:235-241` و`build_docx` بعد 300)، بينما archive قبل 9/21 يتغير بين 4 و5، وآخر يومين 6. السبب: (a) exporter structure bug بالنسبة إلى latest؛ مع (c) widths اليدوية في archive كquirk لا ينبغي تقليده كقيمة واحدة. أمثلة: 8/1، 9/4، 9/17.
2. **page settings — 51 يومًا.** المصدر البنائي يفرض 1.2 cm لكل margins (`backend/board_export.py:276-282`)، بينما archive 9/29 يقيس `249/720/4/567` twips. السبب (a) exporter formatting؛ archive نفسه manual/غير متسق (c). مثال: كل 8/1–9/20 غير passthrough.
3. **row count — 49 يومًا.** النظام الحالي يضيف rows محسوبة/fixed/placeholder من `build_board` (620–698) بينما الأرشيف التاريخي لا يحتوي دائمًا على نفس المناطق؛ 9/29 يثبت أن الأهداف/الـslots لها قواعد ثابتة في latest. السبب المختلط (a) layout policy + (b) system data/state اختلافًا عن archive التاريخي. أمثلة: 8/1 archive 27 مقابل system 28؛ 8/31 31 مقابل 34؛ 9/17 32 مقابل 34.
4. **DATA-EXTRA — 2,507 خلايا positional.** يظهر مثل 8/1 r1c4 حيث النظام يضيف قوام/placeholder في نصف لا يقابله archive ذو 4 أعمدة. السبب الأساسي (a) grid misalignment، ومعه (b) system data/state mismatch؛ لا يُحسب كعدد أفراد مفقود.
5. **DATA-MISSING + DATA-DIFFERENT — 1,078 + 3,868 خلايا positional.** 3,866 اختلافًا حقيقيًا و2 اختلاف تنسيق فقط (8/21 r0c0 و9/17 r25c4). السبب الغالب (b) قبل 9/21: system copy لا تحمل نفس الصياغات/التكليفات التاريخية، ويضخمها (a) row/column alignment. السبب في الاثنين formatting-only هو (c) manual spelling/spacing quirk. مثال جوهري: 8/1 archive r1c1=`م.اول/ ايمن حسن` بينما system r1c1=`ملازم اول/ ايمن احمد محمد محمد حسن`؛ هذا لا يمكن حسمه كاختصار فقط لأن الاسم نفسه مختلف.

## 6) التغييرات المقترحة حسب الأثر

1. في `backend/routes/board.py:117-127` اجعل اختيار source document policy صريحًا للمدى التاريخي، مع metadata يثبت هل الملف passthrough أم generated؛ لا تعتبر 200/bytes match دليلًا على generator fidelity.
2. في `backend/board_export.py:272-320` استبدل قالب 5-column الثابت بمولد latest 6-grid، مع spans/empty-cell conventions الخاصة بـ9/28–9/29، ثم استخدمه لكل الأيام وفق سياسة “latest wins”.
3. افصل “الحقيقة التاريخية” عن computed state في `backend/board.py:620-698`: latest export يحتاج snapshot قابلًا لإعادة الإنتاج لصفوف الأرشيف، خصوصًا targets/roles/rests/admin، لا إعادة اشتقاق أسماء تاريخية من حالة الأشخاص الحالية فقط.
4. في `_who`, `_basic_assignee`, `_compact_manning` و`_cell_text` (59–155، 93–107) أضف formatting profile للرتب (`م.ش`, `ا.ش`, `م.اول`, `رقيب`)، slash/spacing، ordering، والتمييز بين empty و`—` وdash filler.
5. قبل اعتماد الإصلاح، شغّل الأداة لكل 60 يومًا، ثم راجع semantic alignment يدويًا للأيام ذات row-count mismatch؛ positional counts الحالية لا تكفي لإثبات أن شخصًا بعينه فُقد.

## 7) OPEN QUESTIONS

- هل يُقصد بـ“latest format wins” تقليد 9/29 حرفيًا بما فيه widths الشاذة (`bottom=4`, آخر gridCol=`16`) أم اعتماد 9/28–9/29 كعائلة 6-grid مع widths معيارية؟
- هل يجب حفظ النص التاريخي لكل يوم (including manual abbreviations/names) أم إعادة توليده من people/assignments الحالية؟ مثال 8/1 يثبت أن system person string أطول ومختلف دلاليًا.
- ما قاعدة اختيار الأشخاص عند اختلاف archive عن roster الحالي: هل archive هو source of truth حتى لو كان الاسم/الرتبة قد تغير؟
- هل empty cell و`—` و`ــــــــــــــــــــ` ثلاث حالات مقصودة أم مجرد اختلافات Word/المشغل؟
- هل صفوف السجن/المباحث والـcomputed outsiders يجب أن تظهر في كل يوم latest، حتى في يوم archive قديم لا يحتويها؟
- هل المطلوب مطابقة XML/الطباعة pixel-level، أم مطابقة meaning مع قبول فروق font/margins؟ LibreOffice rendering لم يدخل في النتيجة المقاسة هنا؛ القياس XML-level.

