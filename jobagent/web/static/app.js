// Poll a background task (agent run / manual generate) and narrate progress, then refresh.
(function () {
  var tid = window.JOB_TASK;
  if (!tid) return;
  var EXPECT = 150; // seconds before we say "taking longer than usual"

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
        var msg = d.kind === "agent" ? "Running agent — scanning, scoring & preparing documents…"
                                     : "Generating documents…";
        if (d.kind === "agent") {
          msg += slow ? " Taking longer than usual — a full run can take a few minutes."
                      : " This usually takes 1–3 minutes.";
        }
        setBanner(slow ? "banner banner-warn" : "banner", '<span class="spin"></span> ' + msg);
        setTimeout(poll, 2000);
        return;
      }
      if (d.status === "error") {
        var what = d.kind === "agent" ? "Agent run failed" : "Generation failed";
        setBanner("banner banner-error", what + " — " + (d.error || "unknown error"));
        return;
      }
      if (d.kind === "agent") {
        var r = d.result || {};
        var prepared = r.generated || 0, att = r.attention || 0;
        var note = "Agent finished — prepared " + prepared + " document set" + (prepared === 1 ? "" : "s");
        if (att) note += ", " + att + " need attention";
        if (r.error) note += " (stopped early: " + r.error + ")";
        setBanner(att || r.error ? "banner banner-warn" : "banner banner-done", note + ". Refreshing…");
      } else {
        setBanner("banner banner-done", "Documents ready. Refreshing…");
      }
      setTimeout(reloadClean, 2400);
    }).catch(function () { setTimeout(poll, 3000); });
  }
  poll();
})();
