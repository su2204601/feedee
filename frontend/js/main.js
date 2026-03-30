import "../css/main.css";

// ── Sidebar toggle (mobile) ──────────────────────────────
(function () {
  var toggle = document.getElementById("sidebar-toggle");
  var panel = document.getElementById("sidebar-panel");
  var overlay = document.getElementById("sidebar-overlay");
  if (!toggle) return;
  function open() {
    panel.classList.add("open");
    overlay.classList.add("open");
  }
  function close() {
    panel.classList.remove("open");
    overlay.classList.remove("open");
  }
  toggle.addEventListener("click", function () {
    panel.classList.contains("open") ? close() : open();
  });
  overlay.addEventListener("click", close);
})();

// ── User menu dropdown ──────────────────────────────────
(function () {
  var btn = document.getElementById("user-menu-btn");
  var dropdown = document.getElementById("user-menu-dropdown");
  if (!btn || !dropdown) return;

  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    dropdown.classList.toggle("hidden");
  });

  document.addEventListener("click", function (e) {
    if (!dropdown.classList.contains("hidden") && !dropdown.contains(e.target)) {
      dropdown.classList.add("hidden");
    }
  });
})();
