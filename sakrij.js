/*
 * Rules the Android app applies on top of the Claude page that hosts Dnevnik goriva.
 * The app downloads this file on every start, so the rules can change without a new APK.
 * It hides:
 *   1. Claude's top bar (title, "Content is user-generated and unverified", Sign in)
 *   2. the floating "Sign in to see this artifact's data" pop-up
 * Signing in stays possible from the app's own Settings tab.
 * Everything is found by its text; if Claude changes the wording, the bar simply shows again.
 */
(function () {
  if (window.__dgRules) return;
  window.__dgRules = true;

  var TOAST = ["sign in to see this artifact", "prijavi se da vidi"];
  var BAR = ["content is user-generated", "user-generated and unverified"];

  function has(text, list) {
    text = (text || "").toLowerCase();
    for (var i = 0; i < list.length; i++) if (text.indexOf(list[i]) >= 0) return true;
    return false;
  }
  function hideEl(el) {
    el.style.setProperty("display", "none", "important");
    el.dataset.dgHidden = "1";
  }
  /* Smallest element whose own text matches. */
  function findSmallest(list) {
    var found = [];
    var all = document.body ? document.body.querySelectorAll("div,span,p,section,header,aside,[role=status],[role=dialog],[role=alert]") : [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el.dataset.dgHidden || el.textContent.length > 300 || !has(el.textContent, list)) continue;
      var child = false;
      for (var j = 0; j < el.children.length; j++) if (has(el.children[j].textContent, list)) { child = true; break; }
      if (!child) found.push(el);
    }
    return found;
  }

  function hideToast() {
    findSmallest(TOAST).forEach(function (el) {
      var box = el, n = 0;
      while (box && box !== document.body && n < 8) {
        var pos = getComputedStyle(box).position;
        if (pos === "fixed" || pos === "sticky" || pos === "absolute") break;
        box = box.parentElement; n++;
      }
      if (!box || box === document.body || box.textContent.length > 300 || box.querySelector("iframe")) box = el;
      hideEl(box);
    });
  }

  /* The top bar: climb from its caption to the last ancestor that does not also hold the app frame. */
  function hideBar() {
    if (!document.querySelector("iframe")) return;
    findSmallest(BAR).forEach(function (el) {
      var box = el;
      while (box.parentElement && box.parentElement !== document.body && !box.parentElement.querySelector("iframe")) box = box.parentElement;
      if (box.querySelector("iframe")) return;
      hideEl(box);
    });
  }

  function run() { try { hideBar(); hideToast(); } catch (e) {} }
  run();
  new MutationObserver(run).observe(document.documentElement, { childList: true, subtree: true });
})();
