// Poll a background task (scan/pick) and narrate progress, then refresh.
(function () {
  var tid = window.JOB_TASK;
  if (!tid) return;
  var EXPECT = 120; // seconds before we say "taking longer than usual"

  function setBanner(cls, html) {
    var b = document.getElementById("task-banner");
    if (b) { b.className = cls; b.innerHTML = html; }
  }
  function reloadClean() {
    var u = new URL(window.location);
    u.searchParams.delete("task");
    window.location = u.toString();
  }
  function poll() {
    fetch("/tasks/" + tid).then(function (r) { return r.json(); }).then(function (d) {
      if (d.status === "running") {
        var slow = (d.elapsed || 0) > EXPECT;
        var msg = d.kind === "scan" ? "Scanning for new roles…" : "Generating documents…";
        if (d.kind === "scan") {
          msg += slow ? " Taking longer than usual — larger scans can run a few minutes."
                      : " This usually takes 1–2 minutes.";
        }
        setBanner(slow ? "banner banner-warn" : "banner", '<span class="spin"></span> ' + msg);
        setTimeout(poll, 2000);
        return;
      }
      if (d.status === "error") {
        var what = d.kind === "scan" ? "Scan failed" : "Generation failed";
        setBanner("banner banner-error", what + " — " + (d.error || "unknown error"));
        return;
      }
      if (d.kind === "scan") {
        var n = d.result;
        setBanner("banner banner-done",
          "Scan complete — " + n + " new job" + (n === 1 ? "" : "s") + " added. Refreshing…");
      } else {
        setBanner("banner banner-done", "Documents ready. Refreshing…");
      }
      setTimeout(reloadClean, 2200);
    }).catch(function () { setTimeout(poll, 3000); });
  }
  poll();
})();
