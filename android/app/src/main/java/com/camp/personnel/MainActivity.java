package com.camp.personnel;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * غلاف أندرويد لسيستم مكتب العمليات: البيانات كلها على الكمبيوتر الرئيسي،
 * والتطبيق بيفتح نفس السيستم بملء الشاشة — فالكمبيوتر والموبايل شايفين نفس البيانات دايمًا.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "settings";
    private static final String KEY_SERVER = "server_url";
    private static final int REQ_FILE = 1;
    private static final int REQ_STORAGE = 2;

    private WebView web;
    private ProgressBar progress;
    private ValueCallback<Uri[]> fileCallback;
    private boolean showingError;
    private PendingDownload pendingDownload;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        root.addView(progress, new FrameLayout.LayoutParams(-1, dp(3), Gravity.TOP));
        setContentView(root);

        // أندرويد 15 بيرسم التطبيق تحت شريط الحالة والكيبورد إجباريًا — نسيب مكانهم
        // بلون السيستم بدل ما رأس الصفحة وحقول الإدخال يستخبّوا تحتهم.
        root.setBackgroundColor(getColor(R.color.navy_900));
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top, bottom, left, right;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                top = bars.top; bottom = bars.bottom; left = bars.left; right = bars.right;
            } else {
                top = insets.getSystemWindowInsetTop(); bottom = insets.getSystemWindowInsetBottom();
                left = insets.getSystemWindowInsetLeft(); right = insets.getSystemWindowInsetRight();
            }
            v.setPadding(left, top, right, bottom);
            return insets;
        });

        configureWebView();

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else if (serverUrl().isEmpty()) {
            askServerUrl(false);
        } else {
            loadHome();
        }
    }

    private void configureWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setTextZoom(100);
        s.setUserAgentString(s.getUserAgentString() + " PersonnelApp/1.0");

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, false);

        web.addJavascriptInterface(new Bridge(), "Android");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isOwnServer(uri)) return false;
                // أي رابط خارجي يفتح في المتصفح بدل ما يطلّع المستخدم برّه السيستم
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progress.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showOffline();
            }

            // الكمبيوتر شغّال وTailscale شغّال بس السيستم نفسه مقفول → Tailscale
            // بيرجّع 502 فاضية، وأندرويد كان بيعرض صفحة خطأ إنجليزي من غير «إعادة المحاولة»
            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                int code = response.getStatusCode();
                if (request.isForMainFrame() && (code == 502 || code == 504)) showOffline();
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progress.setProgress(newProgress);
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), REQ_FILE);
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    toast("لا يوجد تطبيق لاختيار الملفات.");
                    return false;
                }
                return true;
            }
        });

        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) ->
                startDownload(new PendingDownload(url, userAgent, contentDisposition, mimeType)));
    }

    // ───────────── عنوان الخادم ─────────────

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private String serverUrl() {
        return prefs().getString(KEY_SERVER, "");
    }

    private static String normalize(String raw) {
        String url = raw.trim();
        if (url.isEmpty()) return "";
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://" + url;
        while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
        return url;
    }

    private boolean isOwnServer(Uri uri) {
        Uri server = Uri.parse(serverUrl());
        return server.getHost() != null && server.getHost().equalsIgnoreCase(uri.getHost())
                && server.getPort() == uri.getPort();
    }

    private void askServerUrl(boolean cancelable) {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setHint("https://pc-name.tailnet.ts.net");
        input.setText(serverUrl());
        input.setTextDirection(View.TEXT_DIRECTION_LTR);
        FrameLayout box = new FrameLayout(this);
        box.setPadding(dp(20), dp(8), dp(20), 0);
        box.addView(input);

        AlertDialog.Builder b = new AlertDialog.Builder(this)
                .setTitle("عنوان الخادم")
                .setMessage("اكتب عنوان السيستم على الكمبيوتر الرئيسي (من Tailscale).")
                .setView(box)
                .setCancelable(cancelable)
                .setPositiveButton("حفظ", (d, w) -> {
                    String url = normalize(input.getText().toString());
                    if (url.isEmpty()) {
                        askServerUrl(cancelable);
                        return;
                    }
                    prefs().edit().putString(KEY_SERVER, url).apply();
                    loadHome();
                });
        if (cancelable) b.setNegativeButton("إلغاء", null);
        b.show();
    }

    private void loadHome() {
        if (serverUrl().isEmpty()) {
            askServerUrl(false);
            return;
        }
        showingError = false;
        web.clearHistory();
        web.loadUrl(serverUrl() + "/");
    }

    private void showOffline() {
        showingError = true;
        progress.setVisibility(View.GONE);
        web.loadDataWithBaseURL(null, readAsset("offline.html"), "text/html", "utf-8", null);
    }

    // ───────────── التنزيلات (تصدير Word) ─────────────

    private static class PendingDownload {
        final String url, userAgent, contentDisposition, mimeType;

        PendingDownload(String url, String userAgent, String contentDisposition, String mimeType) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
        }
    }

    private void startDownload(PendingDownload d) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = d;
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            return;
        }
        // التنزيل من جوّه التطبيق نفسه: DownloadManager بتاع أندرويد بيفتح اتصال
        // منفصل من عملية تانية، وفي التجربة فضل «جارٍ إعادة المحاولة» عند 0% للأبد.
        String name = fileName(d);
        String cookie = CookieManager.getInstance().getCookie(d.url);
        toast("جارٍ تنزيل الملف…");
        new Thread(() -> {
            Uri saved = null;
            String error = null;
            HttpURLConnection conn = null;
            try {
                conn = (HttpURLConnection) new URL(d.url).openConnection();
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(60000);
                if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                conn.setRequestProperty("User-Agent", d.userAgent);
                int code = conn.getResponseCode();
                if (code != 200) {
                    error = code == 401 ? "انتهت الجلسة — سجّل الدخول وحاول مرة أخرى." : "تعذّر التنزيل (" + code + ").";
                } else {
                    try (InputStream in = conn.getInputStream()) {
                        saved = saveToDownloads(name, d.mimeType, in);
                    }
                }
            } catch (IOException e) {
                error = "تعذّر الاتصال بالخادم أثناء التنزيل.";
            } finally {
                if (conn != null) conn.disconnect();
            }
            Uri result = saved;
            String message = error;
            runOnUiThread(() -> downloadFinished(name, d.mimeType, result, message));
        }).start();
    }

    private Uri saveToDownloads(String name, String mimeType, InputStream in) throws IOException {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, name);
            values.put(MediaStore.Downloads.MIME_TYPE, mimeType);
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (uri == null) throw new IOException("insert failed");
            try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                copy(in, out);
            } catch (IOException e) {
                getContentResolver().delete(uri, null, null);
                throw e;
            }
            values.clear();
            values.put(MediaStore.Downloads.IS_PENDING, 0);
            getContentResolver().update(uri, values, null, null);
            return uri;
        }
        File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        if (!dir.exists() && !dir.mkdirs()) throw new IOException("no downloads dir");
        File file = new File(dir, name);
        try (OutputStream out = new FileOutputStream(file)) {
            copy(in, out);
        }
        return null;  // قبل أندرويد 10 الفتح محتاج FileProvider — الملف موجود في Downloads
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    // اسم الملف (عربي + تاريخ + .docx) بيتلخبط اتجاهه جوّه جملة عربي في نوافذ أندرويد
    // حتى مع علامات عزل الاتجاه — فالرسالة مش بتذكره؛ الاسم الصح ظاهر في تطبيق الملفات.
    private void downloadFinished(String name, String mimeType, Uri uri, String error) {
        if (error != null) {
            toast(error);
            return;
        }
        String saved = "تم حفظ الملف في مجلد التنزيلات (Downloads).";
        if (uri == null) {
            toast(saved);
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("تم التنزيل")
                .setMessage(saved)
                .setPositiveButton("فتح", (dlg, w) -> {
                    Intent view = new Intent(Intent.ACTION_VIEW)
                            .setDataAndType(uri, mimeType)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    try {
                        startActivity(view);
                    } catch (ActivityNotFoundException e) {
                        toast("لا يوجد تطبيق لفتح ملفات Word — ثبّت Microsoft Word أو WPS.");
                    }
                })
                .setNegativeButton("إغلاق", null)
                .show();
    }

    /** يقرأ filename*=UTF-8''… أولًا عشان الأسماء العربية، وإلا يرجع لتخمين أندرويد. */
    private static String fileName(PendingDownload d) {
        if (d.contentDisposition != null) {
            Matcher m = Pattern.compile("filename\\*=UTF-8''([^;]+)", Pattern.CASE_INSENSITIVE)
                    .matcher(d.contentDisposition);
            if (m.find()) {
                try {
                    return URLDecoder.decode(m.group(1), "UTF-8").replaceAll("[/\\\\]", "_");
                } catch (Exception ignored) {
                }
            }
        }
        return URLUtil.guessFileName(d.url, d.contentDisposition, d.mimeType);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code == REQ_STORAGE && pendingDownload != null) {
            PendingDownload d = pendingDownload;
            pendingDownload = null;
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
                startDownload(d);
            } else {
                toast("لازم صلاحية التخزين لتنزيل الملفات.");
            }
        }
    }

    // ───────────── رفع الملفات ─────────────

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    // ───────────── زر الرجوع ─────────────

    @Override
    public void onBackPressed() {
        if (!showingError && web.canGoBack()) {
            web.goBack();
            return;
        }
        new AlertDialog.Builder(this)
                .setItems(new CharSequence[]{"إعادة تحميل", "تغيير عنوان الخادم", "خروج"}, (d, which) -> {
                    if (which == 0) loadHome();
                    else if (which == 1) askServerUrl(true);
                    else finish();
                })
                .show();
    }

    // ───────────── دورة الحياة ─────────────

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    /** واجهة صفحة «تعذّر الوصول» المحلية. */
    private class Bridge {
        @JavascriptInterface
        public void retry() {
            runOnUiThread(MainActivity.this::loadHome);
        }

        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(() -> askServerUrl(true));
        }

        @JavascriptInterface
        public String serverUrl() {
            return MainActivity.this.serverUrl();
        }
    }

    // ───────────── أدوات ─────────────

    private String readAsset(String name) {
        try (InputStream in = getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        } catch (IOException e) {
            return "<h1>تعذّر الوصول إلى الخادم</h1>";
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
