package rs.dnevnikgoriva;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** Opens the published "Dnevnik goriva" page full screen, without browser bars. */
public class MainActivity extends Activity {

    private static final String APP_URL = "https://claude.ai/artifact/XxHYWb119SLFVgDeR756k7";

    /*
     * Hides the floating "Sign in to see this artifact's data" pop-up that Claude shows to visitors who are not
     * signed in. The "Sign in" button in the top bar stays, so signing in is still possible.
     * It looks for the pop-up by its text, so if Claude changes the wording the pop-up simply shows again.
     */
    private static final String HIDE_SIGNIN_TOAST =
            "(function(){"
          + " if (window.__dgHide) return; window.__dgHide = true;"
          + " var PHRASES = ['sign in to see this artifact', 'prijavi se da vidi'];"
          + " function matches(t){ t = (t || '').toLowerCase(); for (var i = 0; i < PHRASES.length; i++) if (t.indexOf(PHRASES[i]) >= 0) return true; return false; }"
          + " function hide(){"
          + "  var all = document.body ? document.body.querySelectorAll('div,section,aside,[role=status],[role=dialog],[role=alert]') : [];"
          + "  for (var i = 0; i < all.length; i++){"
          + "   var el = all[i];"
          + "   if (el.dataset.dgHidden || !matches(el.textContent) || el.textContent.length > 200) continue;"
          + "   var box = el, n = 0;"
          + "   while (box && box !== document.body && n < 8){"
          + "    var pos = getComputedStyle(box).position;"
          + "    if (pos === 'fixed' || pos === 'sticky' || pos === 'absolute') break;"
          + "    box = box.parentElement; n++;"
          + "   }"
          + "   if (!box || box === document.body || box.textContent.length > 200) box = el;"
          + "   box.style.setProperty('display', 'none', 'important');"
          + "   box.dataset.dgHidden = '1'; el.dataset.dgHidden = '1';"
          + "  }"
          + " }"
          + " hide();"
          + " new MutationObserver(hide).observe(document.documentElement, {childList: true, subtree: true});"
          + "})();";

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0F1214"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // lets the page keep the tank size and fill-ups on the phone
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
                view.evaluateJavascript(HIDE_SIGNIN_TOAST, null);
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
