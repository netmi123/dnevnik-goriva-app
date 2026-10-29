package rs.dnevnikgoriva;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Opens the published "Dnevnik goriva" page full screen, without browser bars. */
public class MainActivity extends Activity {

    private static final String APP_URL = "https://claude.ai/artifact/XxHYWb119SLFVgDeR756k7";

    /*
     * Rules that hide Claude's top bar and sign-in pop-up. They are downloaded from the GitHub repository on every
     * start, so they can be adjusted without a new APK. A copy ships inside the app, and the last downloaded version
     * is kept, so the app also works offline.
     */
    private static final String RULES_URL = "https://raw.githubusercontent.com/netmi123/dnevnik-goriva-app/main/sakrij.js";
    private static final String PREFS = "pravila";

    private WebView web;
    private volatile String rules;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        rules = loadRules();
        refreshRulesInBackground();

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0F1214"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // lets the page keep the cars, settings and fill-ups on the phone
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, true);   // the app runs in an embedded frame

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                applyRules();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                Uri uri = request.getUrl();
                String host = uri.getHost() == null ? "" : uri.getHost();
                boolean inside = host.equals("claude.ai") || host.endsWith(".claude.ai")
                        || host.endsWith("anthropic.com") || host.endsWith("claudeusercontent.com");
                if (inside) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (Exception ignored) { }
                return true;
            }
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(APP_URL);
    }

    private void applyRules() {
        String r = rules;
        if (web != null && r != null && !r.isEmpty()) web.evaluateJavascript(r, null);
    }

    private String loadRules() {
        String cached = getSharedPreferences(PREFS, MODE_PRIVATE).getString("js", null);
        if (cached != null && !cached.isEmpty()) return cached;
        try (InputStream in = getAssets().open("sakrij.js")) {
            return readAll(in);
        } catch (Exception e) {
            return "";
        }
    }

    private void refreshRulesInBackground() {
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(RULES_URL).openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(8000);
                c.setUseCaches(false);
                if (c.getResponseCode() != 200) return;
                String js;
                try (InputStream in = c.getInputStream()) { js = readAll(in); }
                if (js.length() < 50 || js.length() > 100000) return;
                SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
                p.edit().putString("js", js).apply();
                rules = js;
                runOnUiThread(this::applyRules);
            } catch (Exception ignored) {
            } finally {
                if (c != null) c.disconnect();
            }
        }).start();
    }

    private static String readAll(InputStream in) throws java.io.IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

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

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
