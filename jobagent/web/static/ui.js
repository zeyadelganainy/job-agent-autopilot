// Lightweight UI helpers: toast notifications + a styled confirm dialog that replaces
// the browser's native confirm() ("localhost says…"). No dependencies.
(function () {
  "use strict";

  // ---- toasts ---------------------------------------------------------------
  function toastWrap() {
    var w = document.getElementById("toast-wrap");
    if (!w) {
      w = document.createElement("div");
      w.id = "toast-wrap";
      w.className = "toast-wrap";
      document.body.appendChild(w);
    }
    return w;
  }

  function toast(message, type, timeout) {
    if (!message) return;
    var el = document.createElement("div");
    el.className = "toast toast-" + (type || "info");
    el.setAttribute("role", "status");
    var span = document.createElement("span");
    span.className = "toast-msg";
    span.textContent = message;
    var x = document.createElement("button");
    x.className = "toast-x";
    x.setAttribute("aria-label", "Dismiss");
    x.innerHTML = "&times;";
    el.appendChild(span);
    el.appendChild(x);
    toastWrap().appendChild(el);
    // animate in
    requestAnimationFrame(function () { el.classList.add("in"); });

    var t = setTimeout(close, timeout || 5200);
    function close() {
      clearTimeout(t);
      el.classList.remove("in");
      el.classList.add("out");
      setTimeout(function () { el.remove(); }, 260);
    }
    x.addEventListener("click", close);
    return close;
  }
  window.toast = toast;

  // Turn a server-rendered notice banner into a toast (progressive enhancement:
  // no-JS users still see the inline banner).
  function classify(text) {
    var t = (text || "").toLowerCase();
    if (/complete|ready|prepared|saved|imported|added|recorded|done/.test(t)) return "success";
    if (/can't|cannot|read-only|fail|error|attention/.test(t)) return "warn";
    return "info";
  }
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("notice-banner");
    if (b) {
      var msg = b.textContent.trim();
      b.remove();
      toast(msg, classify(msg), 6500);
      // strip ?notice= from the URL so a refresh doesn't repeat it
      try {
        var u = new URL(window.location);
        if (u.searchParams.has("notice")) {
          u.searchParams.delete("notice");
          history.replaceState(null, "", u.toString());
        }
      } catch (e) {}
    }
  });

  // ---- theme toggle ---------------------------------------------------------
  // The <head> inline script already applied the saved theme before paint; here we
  // just wire the toggle button and persist the choice.
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".theme-toggle")) return;
    var light = document.documentElement.getAttribute("data-theme") === "light";
    if (light) document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", "light");
    try { localStorage.setItem("jp-theme", light ? "dark" : "light"); } catch (err) {}
    // let theme-aware widgets (e.g. the Insights charts) restyle without a reload
    window.dispatchEvent(new CustomEvent("jp:themechange", { detail: { light: !light } }));
  });

  // ---- mobile nav drawer ----------------------------------------------------
  // The sidebar is a left-anchored off-canvas drawer on phones; the hamburger in
  // the app bar opens it. Scrim tap / Esc / picking a destination all close it.
  (function () {
    var app = document.querySelector(".app");
    var burger = document.getElementById("nav-toggle");
    if (!app || !burger) return;
    var scrim = document.getElementById("nav-scrim");
    var closeBtn = document.getElementById("nav-close");

    function isOpen() { return app.classList.contains("nav-open"); }
    function open() {
      app.classList.add("nav-open");
      burger.setAttribute("aria-expanded", "true");
      document.body.style.overflow = "hidden";   // lock the page behind the drawer
    }
    function close() {
      app.classList.remove("nav-open");
      burger.setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
    }
    burger.addEventListener("click", function () { isOpen() ? close() : open(); });
    if (scrim) scrim.addEventListener("click", close);
    if (closeBtn) closeBtn.addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) close(); });
    var nav = app.querySelector(".sidebar nav");
    if (nav) nav.addEventListener("click", function (e) { if (e.target.closest("a")) close(); });
    // if the viewport grows back to desktop, drop any open state + scroll lock
    window.addEventListener("resize", function () {
      if (window.innerWidth > 820 && isOpen()) close();
    });
  })();

  // ---- confirm dialog -------------------------------------------------------
  function confirmDialog(message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML =
        '<div class="modal-card" role="dialog" aria-modal="true">' +
        '  <div class="modal-msg"></div>' +
        '  <div class="modal-actions">' +
        '    <button type="button" class="btn modal-cancel"></button>' +
        '    <button type="button" class="btn btn-danger modal-ok"></button>' +
        '  </div>' +
        '</div>';
      overlay.querySelector(".modal-msg").textContent = message || "Are you sure?";
      var okBtn = overlay.querySelector(".modal-ok");
      var cancelBtn = overlay.querySelector(".modal-cancel");
      okBtn.textContent = opts.confirmText || "Confirm";
      cancelBtn.textContent = opts.cancelText || "Cancel";
      document.body.appendChild(overlay);
      requestAnimationFrame(function () { overlay.classList.add("in"); });
      okBtn.focus();

      function done(val) {
        overlay.classList.remove("in");
        setTimeout(function () { overlay.remove(); }, 200);
        document.removeEventListener("keydown", onKey);
        resolve(val);
      }
      function onKey(e) {
        if (e.key === "Escape") done(false);
        else if (e.key === "Enter") done(true);
      }
      okBtn.addEventListener("click", function () { done(true); });
      cancelBtn.addEventListener("click", function () { done(false); });
      overlay.addEventListener("click", function (e) { if (e.target === overlay) done(false); });
      document.addEventListener("keydown", onKey);
    });
  }
  window.confirmDialog = confirmDialog;

  // Intercept clicks on anything with [data-confirm]; ask in a styled dialog, then
  // re-dispatch the original action (form submit / link nav) once confirmed.
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-confirm]");
    if (!el) return;
    if (el.dataset.confirmed === "1") { el.dataset.confirmed = ""; return; }  // pass through
    e.preventDefault();
    confirmDialog(el.getAttribute("data-confirm"), {
      confirmText: el.getAttribute("data-confirm-ok") || "Confirm"
    }).then(function (ok) {
      if (!ok) return;
      el.dataset.confirmed = "1";
      if (el.tagName === "BUTTON" || el.tagName === "A") {
        el.click();
      } else {
        var f = el.closest("form");
        if (f) f.submit();
      }
    });
  }, true);
})();
