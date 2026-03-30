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

// ── Mobile search toggle ────────────────────────────────
(function () {
  var btn = document.getElementById("mobile-search-toggle");
  var bar = document.getElementById("mobile-search-bar");
  if (!btn || !bar) return;

  btn.addEventListener("click", function () {
    var visible = bar.style.display === "block";
    bar.style.display = visible ? "none" : "block";
    if (!visible) {
      var input = bar.querySelector("input[name='q']");
      if (input) input.focus();
    }
  });
})();

// ── Inline article state toggle (fetch API) ─────────────
(function () {
  var csrf =
    document.querySelector("meta[name='csrf-token']") ||
    document.querySelector("input[name='csrfmiddlewaretoken']");
  var csrfToken = csrf
    ? csrf.content || csrf.value
    : "";

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".state-toggle");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();

    var articleId = btn.dataset.articleId;
    var field = btn.dataset.field;
    var isActive = btn.dataset.active === "true";

    var body = {};
    body[field] = !isActive;

    fetch("/api/articles/" + articleId + "/state/", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Failed");
        return res.json();
      })
      .then(function (data) {
        btn.dataset.active = String(data[field]);
        var svg = btn.querySelector("svg");

        // Update button styling
        var styles = {
          is_favorite: {
            active: "text-amber-500",
            inactive: "text-gray-400 hover:text-amber-500",
          },
          is_read_later: {
            active: "text-sky-500",
            inactive: "text-gray-400 hover:text-sky-500",
          },
          is_read: {
            active: "text-emerald-500",
            inactive: "text-gray-400 hover:text-emerald-500",
          },
        };
        var s = styles[field];
        var allClasses = (s.active + " " + s.inactive + " opacity-0 group-hover:opacity-100").split(" ");
        allClasses.forEach(function (c) { if (c) btn.classList.remove(c); });

        if (data[field]) {
          s.active.split(" ").forEach(function (c) { btn.classList.add(c); });
          if (svg && field !== "is_read") svg.setAttribute("fill", "currentColor");
        } else {
          s.inactive.split(" ").forEach(function (c) { btn.classList.add(c); });
          btn.classList.add("opacity-0", "group-hover:opacity-100");
          if (svg && field !== "is_read") svg.setAttribute("fill", "none");
        }

        // Update card styling for read state
        if (field === "is_read") {
          var card = btn.closest(".article-card");
          if (card) {
            card.classList.toggle("is-read", data[field]);
            var title = card.querySelector("h2");
            if (title) {
              title.classList.toggle("text-gray-500", data[field]);
              title.classList.toggle("text-gray-900", !data[field]);
            }
          }
        }
      })
      .catch(function () {
        // Fallback: reload on error
        window.location.reload();
      });
  });
})();

// ── Sidebar category collapse ───────────────────────────
(function () {
  var toggles = document.querySelectorAll(".category-toggle");
  toggles.forEach(function (btn) {
    var container = btn.closest(".sidebar-category");
    var feeds = container ? container.querySelector(".category-feeds") : null;
    var chevron = btn.querySelector(".category-chevron");
    if (!feeds) return;

    // Restore from localStorage
    var key = "sidebar-cat-" + (btn.textContent || "").trim();
    if (localStorage.getItem(key) === "collapsed") {
      feeds.style.display = "none";
      if (chevron) chevron.style.transform = "rotate(-90deg)";
    }

    btn.addEventListener("click", function () {
      var collapsed = feeds.style.display === "none";
      feeds.style.display = collapsed ? "" : "none";
      if (chevron) chevron.style.transform = collapsed ? "" : "rotate(-90deg)";
      localStorage.setItem(key, collapsed ? "expanded" : "collapsed");
    });
  });
})();

// ── Keyboard shortcut help (? key) ──────────────────────
(function () {
  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    var help = document.getElementById("shortcut-help");
    if (!help) return;
    if (e.key === "?" || (e.shiftKey && e.key === "/")) {
      e.preventDefault();
      help.style.display = help.style.display === "flex" ? "none" : "flex";
    }
    if (e.key === "Escape" && help.style.display === "flex") {
      help.style.display = "none";
    }
  });
  // Close on overlay click
  var help = document.getElementById("shortcut-help");
  if (help) {
    help.addEventListener("click", function (e) {
      if (e.target === help) help.style.display = "none";
    });
  }
})();

// ── Custom confirm dialog ───────────────────────────────
(function () {
  var dialog = document.getElementById("confirm-dialog");
  var message = document.getElementById("confirm-message");
  var okBtn = document.getElementById("confirm-ok");
  var cancelBtn = document.getElementById("confirm-cancel");
  if (!dialog) return;

  var pendingForm = null;

  function show(text, variant) {
    message.textContent = text;
    // Style the confirm button based on action type
    okBtn.className = variant === "danger"
      ? "rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm font-medium transition-colors shadow-sm"
      : "rounded-lg bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 text-sm font-medium transition-colors shadow-sm";
    dialog.style.display = "flex";
    okBtn.focus();
  }

  function hide() {
    dialog.style.display = "none";
    pendingForm = null;
  }

  okBtn.addEventListener("click", function () {
    if (pendingForm) {
      var form = pendingForm;
      hide();
      form.submit();
    }
  });

  cancelBtn.addEventListener("click", hide);

  dialog.addEventListener("click", function (e) {
    if (e.target === dialog) hide();
  });

  document.addEventListener("keydown", function (e) {
    if (dialog.style.display !== "flex") return;
    if (e.key === "Escape") hide();
  });

  // Intercept form submissions with data-confirm
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-confirm]");
    if (!form) return;
    if (pendingForm === form) return; // already confirmed
    e.preventDefault();
    pendingForm = form;
    var variant = form.hasAttribute("data-confirm-danger") ? "danger" : "default";
    show(form.dataset.confirm, variant);
  });
})();
