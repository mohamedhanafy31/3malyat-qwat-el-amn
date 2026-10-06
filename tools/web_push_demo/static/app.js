const button = document.getElementById("subscribe");
const statusBox = document.getElementById("status");
const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
const isStandalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;

if (isIos && !isStandalone) document.getElementById("iosHelp").style.display = "block";

function setStatus(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`;
}

function decodeKey(value) {
  const padded = value + "=".repeat((4 - value.length % 4) % 4);
  const bytes = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(bytes, char => char.charCodeAt(0));
}

async function subscribe() {
  button.disabled = true;
  try {
    if (!window.isSecureContext) {
      throw new Error("يجب فتح رابط HTTPS الآمن لتشغيل الإشعارات.");
    }
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      throw new Error("هذا المتصفح لا يدعم Web Push.");
    }
    if (Notification.permission === "denied") {
      throw new Error("الإشعارات محظورة هنا. افتح الرابط في Chrome أو Safari الخارجي واسمح بالإشعارات من إعدادات الموقع.");
    }
    if (isIos && !isStandalone) {
      throw new Error("أضف الصفحة إلى الشاشة الرئيسية وافتحها من الأيقونة أولًا.");
    }
    setStatus("جاري تجهيز خدمة الإشعارات…");
    const registration = await navigator.serviceWorker.register("/sw.js", {scope: "/"});
    await navigator.serviceWorker.ready;
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("لم يتم السماح بالإشعارات.");
    const keyResponse = await fetch("/api/public-key", {credentials: "same-origin"});
    if (!keyResponse.ok) throw new Error("انتهت صلاحية رابط الاختبار. افتحه من جديد.");
    const {public_key: publicKey} = await keyResponse.json();
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeKey(publicKey),
      });
    }
    const response = await fetch("/api/subscribe", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(subscription),
    });
    if (!response.ok) throw new Error("تعذّر حفظ الاشتراك على الكمبيوتر.");
    setStatus("تم الاشتراك بنجاح. الهاتف جاهز لاستقبال رسالة الاختبار.", "ok");
    button.textContent = "إعادة تسجيل هذا الهاتف";
  } catch (error) {
    setStatus(error.message || "تعذّر تشغيل الإشعارات.", "bad");
  } finally {
    button.disabled = false;
  }
}

button.addEventListener("click", subscribe);
