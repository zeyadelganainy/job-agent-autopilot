// Live "Next scan in 1hr 5min 2sec" countdown in the sidebar.
(function () {
  var el = document.getElementById("next-scan");
  if (!el) return;
  var ts = parseInt(el.getAttribute("data-next") || "", 10);
  if (!ts) { el.textContent = "off"; return; }
  function tick() {
    var s = Math.floor((ts - Date.now()) / 1000);
    if (s <= 0) { el.textContent = "due now"; return; }
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    var parts = [];
    if (h) parts.push(h + "hr");
    if (h || m) parts.push(m + "min");
    parts.push(sec + "sec");
    el.textContent = "in " + parts.join(" ");
    setTimeout(tick, 1000);
  }
  tick();
})();
