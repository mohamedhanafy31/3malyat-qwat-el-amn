مجلد الحزم الجاهزة للتثبيت بدون إنترنت.

بيتملى مرة واحدة على جهاز فيه إنترنت بتشغيل: PREPARE_ONLINE.bat
وبيستخدمه SETUP_OFFLINE.bat داخل نفس مجلد المشروع. PREPARE_ONLINE.bat لا ينشئ
ZIP تلقائيًا؛ إنشاء حزمة Release منفصلة مسؤولية مشرف الإصدار.

الحزمة المستهدفة هي Windows 64-bit / Python 3.11، وتشمل Flask وWaitress
وتصدير Word وExcel ومعالجة الصور وواجهة Tesseract وكل الاعتماديات الفرعية.

ملفات wheel المبنية وruntime الكبير غير متتبعين في Git؛ أعد تشغيل
PREPARE_ONLINE.bat عند تجهيز إصدار أوفلاين جديد.
