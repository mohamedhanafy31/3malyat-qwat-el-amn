# التشغيل على جهاز معزول عن الإنترنت (ويندوز 10)

## تشغيل إنتاجي على Linux

لا تستخدم `flask run` أو `python app.py` في التشغيل المستمر. استخدم خادم
WSGI المرفق:

```bash
./run_production.sh
```

يستمع افتراضيًا على `127.0.0.1:5000`، ويكتب السجل إلى `logs/server.log`
مع تدوير تلقائي. يمكن تغيير الإعدادات دون تعديل الملفات:

```bash
HOST=127.0.0.1 PORT=5050 WAITRESS_THREADS=12 ./run_production.sh
```

للتشغيل كخدمة systemd انسخ `personnel-system.service.example` إلى
`/etc/systemd/system/personnel-system.service` وعدّل مسار التثبيت، ثم نفّذ:

```bash
sudo systemctl enable --now personnel-system
```

لا تجعل `HOST=0.0.0.0` إلا إذا كان الوصول من شبكة داخلية مقصودًا ومُحميًا
بجدار ناري؛ الوضع الافتراضي محلي وآمن للعمل دون إنترنت.

السيستم بيشتغل **محليًا بالكامل**. مفيش أي اتصال بالإنترنت في التشغيل اليومي،
ولا أي خدمة خارجية، ولا أي مكتبة بتتحمّل من الشبكة.

---

## الملفات الثلاثة

| الملف | امتى | إنترنت؟ |
|---|---|---|
| `PREPARE_ONLINE.bat` | مرة واحدة عند تنزيل Source code من GitHub | **أيوه** — ده الوحيد |
| `SETUP_OFFLINE.bat` | اختياري للتشخيص؛ `START_SYSTEM.bat` يشغله تلقائيًا أول مرة | لأ |
| `START_SYSTEM.bat` | أول تشغيل والإعداد، ثم كل يوم | لأ |
| `STOP_SYSTEM.bat` | لإيقاف السيستم (مثلًا قبل الاستعادة) | لأ |
| `SETUP_PHONE_ACCESS.bat` | اختياري — تطبيق الموبايل، شوف `MOBILE_APP.md` | **أيوه** |

---

## طريقتا التثبيت

### الطريقة A: لو نزّلت Source code من GitHub على جهاز Windows فيه إنترنت
```
PREPARE_ONLINE.bat
```
ينزّل المكونات، يجهّز **نفس مجلد المشروع** ويشغّل فحص الإعداد تلقائيًا. بعد
ظهور رسالة الجاهزية شغّل `START_SYSTEM.bat`؛ التشغيلات التالية لا تحتاج
إنترنت. ويجهّز جوّه المشروع:
- `runtime\` — نسخة بايثون محمولة (فيها بايثون كامل، الجهاز المعزول مش هيحتاج يثبّت حاجة)
- `wheels\` — كل الحزم، بما فيها Flask وWord وExcel وOpenCV، كملفات جاهزة
- `tools\offline_installers\` — محرك Tesseract وبيانات اللغة العربية
- `OFFLINE_ASSETS.sha256` — بصمات كل مكونات التشغيل قبل النقل

المتطلبات قبل التشغيل: Windows 10+ x64، وPython 3.9 أو أحدث مع `pip`
(يفضّل تثبيته من python.org بدل اختصار Microsoft Store)، و1.5 GB مساحة خالية،
ومجلد قابل للكتابة. الفحص المبدئي يرفض التشغيل برسالة واضحة لو المعمارية خطأ،
المساحة أو الصلاحيات غير كافية، رقم `PORT` غير صالح، أو نسخة من السيستم ما زالت
شغالة. قبل `git pull` أو إعادة التحضير شغّل `STOP_SYSTEM.bat` وخذ نسخة احتياطية.

لإنشاء ZIP نهائي للنشر كمشرف إصدار، شغّل:
```
python tools\prepare_offline_bundle.py --archive
```

ميزة قراءة صورة «يومية الأفراد» تحتاج **محرك Tesseract نفسه** مع لغة العربية
`ara`؛ لذلك الحزمة النهائية تحمل المثبّت وملف اللغة، و`SETUP_OFFLINE.bat`
يثبتهما من غير إنترنت في مسار Tesseract القياسي ويضيف ملف العربية. قد يظهر
طلب صلاحية Windows مرة واحدة أثناء هذه الخطوة. لو فشل تثبيته يظهر تحذير فقط:
باقي النظام يعمل طبيعيًا، ويمكن تثبيته لاحقًا أو ضبط `TESSERACT_CMD` ثم إعادة
تشغيل `SETUP_OFFLINE.bat`.
ويمكن بدلًا منه تشغيل PaddleOCR من بيئة مستقلة وضبط متغير `PADDLE_PYTHON`
لمسار Python الخاص بها.

### الطريقة B: نزّل ملف Offline Release من GitHub
من صفحة **Releases** على GitHub نزّل الملف المسمى
`personnel-system-offline-<date>.zip`، وليس زر **Source code (zip)**، ثم فكّه
على الجهاز. ملف Source code لا يحتوي مكونات التشغيل الكبيرة التي لا يسمح Git
بوضعها داخل المستودع. الحزمة تتعمّد عدم
إدراج `data\users.json` و`data\secret_key`، لذلك أول تشغيل يطلب إنشاء مدير
جديد. وهي لا تحمل أرشيفات المصادر الكبيرة أو ملفات الاستيراد المؤقتة، لكنها
تحمل `data\core.json` و`data\days\` وملفات الرفع التشغيلية الحالية.

> **مهم — مكان المجلد على جهاز التشغيل:**
> حطّه في مكان **المستخدم بيقدر يكتب فيه**، زي:
> ```
> C:\SIGIL\           أو    D:\SIGIL\           أو    %USERPROFILE%\Desktop\SIGIL\
> ```
> **ماتحطهوش في `C:\Program Files\` ولا `C:\Program Files (x86)\`** — ويندوز
> بيمنع الكتابة هناك، والسيستم محتاج يكتب `data\` و`backups\` و`logs\`.
> لو اتحط هناك هيطلع خطأ صلاحيات عند التشغيل (`PermissionError ... logs`).
>
> المسار ينفع يبقى فيه مسافات وحروف عربية عادي — ده متجرَّب.

### بعد تنزيل Offline Release: فك الضغط وشغّل
```
START_SYSTEM.bat
```
في أول مرة يشغّل الإعداد المحلي تلقائيًا من الملفات الموجودة داخل الحزمة، من
غير إنترنت، ثم يكمل التشغيل. بعد ذلك يتحقق من البيئة وقاعدة البيانات، يشغّل
Waitress في نافذة خادم مستقلة، ينتظر
فحص جاهزية خاص بالنظام (وليس مجرد صفحة HTTP)، ثم يفتح المتصفح على
`http://127.0.0.1:5000`. إغلاق نافذة
المشغّل لا يوقف الخادم؛ لإيقافه استخدم نافذة الخادم أو أنهِ عملية Python الخاصة
بالمشروع.

من اللحظة دي الجهاز ممكن يتفصل عن الشبكة نهائيًا.

---

## النسخ الاحتياطية

```
BACKUPS.bat
```
عرض / فحص / استعادة. النسخ مضغوطة (`.json.gz`) وبتتاخد أوتوماتيك قبل أي حفظ،
وبيتحفظ آخر 20 نسخة.

الاستعادة بتتأكد إن النسخة سليمة **قبل** ما تلمس البيانات، وبتاخد لقطة من
الوضع الحالي الأول — فحتى الاستعادة ليها تراجع.

**اقفل شاشة التشغيل قبل الاستعادة، وشغّلها تاني بعدها.**

---

## لو حصلت مشكلة

**فشل الإعداد التلقائي** → النافذة ستظل مفتوحة وتعرض مسار السجل. يمكن تشغيل
`SETUP_OFFLINE.bat` يدويًا للتشخيص ثم إعادة تشغيل `START_SYSTEM.bat`.

**`CERTIFICATE_VERIFY_FAILED` أثناء `PREPARE_ONLINE.bat`** → النسخة الحديثة
تعيد المحاولة تلقائيًا باستخدام مخزن شهادات Windows عبر `curl.exe` ثم
PowerShell، مع بقاء التحقق الآمن من شهادة HTTPS مفعّلًا.

بيانات OCR العربية تُحفظ داخل `tools\tesseract\tessdata` في مجلد المشروع؛
لا يحتاج الإعداد للكتابة داخل `Program Files` بعد تثبيت محرك Tesseract.

**«مجلد wheels فاضي»** → `PREPARE_ONLINE.bat` ما اتشغّلش على الجهاز اللي فيه نت.

**البيانات باظت / ملف تالف** → السيستم بيرفض يشتغل بصوت عالي بدل ما يشتغل
على بيانات فاضية. شغّل `BACKUPS.bat` واختار «استعادة أحدث نسخة سليمة».

**البورت 5000 مشغول** → من نافذة CMD داخل المجلد شغّل:
```
set PORT=5050
START_SYSTEM.bat
```
المشغّل يتأكد أن الرد صادر من هذا النظام تحديدًا؛ صفحة دخول أو برنامج آخر على
نفس المنفذ لن تُعتبر نجاحًا. و`STOP_SYSTEM.bat` يرفض قتل عملية غير مؤكدة.

**Python غير صالح أثناء التحضير** → ثبّت Python 3.9+ مع pip من python.org.
اختبره بـ`py -3 -m pip --version`. عند استخدام مسار venv الاحتياطي بدل runtime
المحمول، يلزم CPython 3.11 x64 ليتوافق مع عجلات Windows الجاهزة.

**فشل checksum أو ملف ناقص** → لا تكمل يدويًا ولا تنسخ أجزاء منفردة؛ أعد تشغيل
`PREPARE_ONLINE.bat`. التفعيل يتم في مجلدات مؤقتة ويسترجع المكونات السابقة لو
فشل التحقق قبل اكتمال التحضير.

---

## ملاحظات فنية

- ملفات `data\` بتفضل JSON عادي مقروء — الضغط على النسخ الاحتياطية بس.
- السيرفر بيسمع على `127.0.0.1` بس، يعني مش متاح لأي جهاز تاني على الشبكة.
- Chart.js متخزّنة محليًا في `static\js\vendor\` — مفيش CDN.
- للتأكد في أي وقت إن البيئة سليمة:
  ```
  runtime\python.exe tools\offline_env.py verify --strict
  ```
  (`--strict` بيمنع أي اتصال شبكة أثناء الفحص، فلو فيه أي محاولة هتفشل بصوت عالي)
# Recovery and performance notes

Writes use a transaction journal (`.transaction-journal.json`) in the data
directory. It is fsynced before replacements; startup rolls an incomplete
journal forward idempotently. The `.lock` file is held with `fcntl` on Linux
and `msvcrt` on Windows, so the operating system releases it after a crash.

Automatic backups are throttled to one per 120 seconds and stored as ZIP
archives containing `data.json` and `uploads/`. Legacy `.json` and `.json.gz`
archives remain readable. Keep the original archive when testing recovery.

Run the isolated storage benchmark with:

    python tools/benchmark_storage.py --days 1097 --runs 30

The final release gates are cold start <=8s, API/page p95 <=1.5s, save p95
<=750ms, RSS <=750MiB, and growth <=100MiB over eight hours. Windows forced
power-loss and target HDD measurements still require the target VM/machine.

---

## الحسابات وأول تشغيل (طبقة الدخول)

- أول مرة: افتح `http://127.0.0.1:5000` **من نفس الجهاز** وأنشئ أول مدير من صفحة
  الإعداد، أو شغّل `python tools/create_admin.py --username admin` (بيسأل عن كلمة المرور).
- الحسابات في `data/users.json` ومفتاح الجلسة في `data/secret_key`. الملفان
  **مش** في النسخ الاحتياطية ولا في git — انسخهم يدويًا مع أي نقل للنظام، وإلا
  هيطلب إنشاء أول مدير من جديد وتتسجّل خروج كل الجلسات.
- لو `HOST=0.0.0.0`: الاتصال HTTP من غير تشفير؛ استخدم شبكة داخلية خلف جدار ناري.
