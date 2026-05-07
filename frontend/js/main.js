import "../css/main.css";

// ── Theme preference sync ─────────────────────────────────
(function () {
  function applyTheme(theme) {
    var resolved = theme === "system"
      ? (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : theme;
    var root = document.documentElement;
    root.dataset.theme = theme;
    root.classList.toggle("theme-dark", resolved === "dark");
    root.classList.toggle("theme-light", resolved !== "dark");
  }

  var root = document.documentElement;
  var select = document.querySelector("select[name='theme_preference']");
  var storedTheme = localStorage.getItem("feedee-theme");
  var initialTheme = storedTheme || root.dataset.theme || (select ? select.value : "system");

  applyTheme(initialTheme);

  if (window.matchMedia) {
    var mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener("change", function () {
      if ((root.dataset.theme || "system") === "system") {
        applyTheme("system");
      }
    });
  }

  if (!select) return;

  select.value = initialTheme;

  select.addEventListener("change", function () {
    localStorage.setItem("feedee-theme", select.value);
    applyTheme(select.value);
  });
})();

// ── Sidebar toggle (mobile) ──────────────────────────────
(function () {
  var panel = document.getElementById("sidebar-panel");
  var overlay = document.getElementById("sidebar-overlay");
  var closeBtn = document.getElementById("sidebar-close-btn");
  if (!panel || !overlay || !closeBtn) return;

  function open() {
    panel.classList.add("open");
    overlay.classList.add("open");
  }
  function close() {
    panel.classList.remove("open");
    overlay.classList.remove("open");
  }

  // Mobile menu button (hamburger)
  var mobileMenuBtn = document.createElement("button");
  mobileMenuBtn.id = "mobile-menu-btn";
  mobileMenuBtn.className = "md:hidden fixed left-4 top-4 z-50 p-1.5 rounded-lg hover:bg-gray-100 text-gray-600";
  mobileMenuBtn.setAttribute("aria-label", "Toggle sidebar");
  mobileMenuBtn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" d="M4 6h16M4 12h16M4 18h16"/></svg>';
  document.body.insertBefore(mobileMenuBtn, document.body.firstChild);

  mobileMenuBtn.addEventListener("click", function () {
    panel.classList.contains("open") ? close() : open();
  });

  closeBtn.addEventListener("click", close);
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
  // Removed - mobile search bar is now in sidebar
})();

// ── Inline article state toggle (fetch API) ─────────────
(function () {
  var csrf =
    document.querySelector("meta[name='csrf-token']") ||
    document.querySelector("input[name='csrfmiddlewaretoken']");
  var csrfToken = csrf
    ? csrf.content || csrf.value
    : "";

  function currentStateFilter() {
    var params = new URLSearchParams(window.location.search);
    return params.get("state") || "all";
  }

  function removeArticleCardRealtime(card) {
    if (!card) return;
    var listContainer = card.parentElement;

    card.style.transition = "opacity 150ms ease, transform 150ms ease";
    card.style.opacity = "0";
    card.style.transform = "scale(0.98)";

    window.setTimeout(function () {
      card.remove();
      if (!listContainer) return;

      if (!listContainer.querySelector(".article-card") && !document.getElementById("unread-empty-state")) {
        var empty = document.createElement("div");
        empty.id = "unread-empty-state";
        empty.className = "rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700";
        empty.textContent = "All visible unread articles are now read.";
        listContainer.parentNode.insertBefore(empty, listContainer.nextSibling);
      }
    }, 170);
  }

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

            if (data[field] && currentStateFilter() === "unread") {
              removeArticleCardRealtime(card);
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

// ── Save article to bookmarks (one-click) ───────────────
(function () {
  var csrf =
    document.querySelector("meta[name='csrf-token']") ||
    document.querySelector("input[name='csrfmiddlewaretoken']");
  var csrfToken = csrf ? csrf.content || csrf.value : "";

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".save-to-bookmark");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();

    var saveUrl = btn.dataset.saveUrl;
    if (!saveUrl) return;

    var alreadySaved = btn.dataset.saved === "true";
    if (alreadySaved) {
      // Already saved — navigate to bookmarks
      window.location.href = "/bookmarks/";
      return;
    }

    btn.disabled = true;

    fetch(saveUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Failed");
        return res.json();
      })
      .then(function (data) {
        if (data.ok) {
          btn.dataset.saved = "true";
          btn.classList.remove("text-gray-400", "hover:text-violet-500", "opacity-0", "group-hover:opacity-100");
          btn.classList.add("text-violet-500");
          btn.title = "Already saved to bookmarks";
          var svg = btn.querySelector("svg");
          if (svg) svg.setAttribute("fill", "currentColor");
        }
        btn.disabled = false;
      })
      .catch(function () {
        btn.disabled = false;
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

// ── App Switcher (Catalyst-style) ──────────────────────
(function () {
  var btn = document.getElementById("app-switcher-btn");
  var dropdown = document.getElementById("app-switcher-dropdown");
  var badge = document.getElementById("app-switcher-badge");
  if (!btn || !dropdown) return;

  function detectCurrentApp() {
    var explicitApp = document.body ? document.body.dataset.currentApp : "";
    if (explicitApp === "rss" || explicitApp === "bookmark") return explicitApp;

    var path = window.location.pathname;
    if (path.includes("/bookmarks")) return "bookmark";
    if (path.includes("/feeds") || path.includes("/articles") || path.includes("/overview") || path.includes("/read-later") || path.includes("/favorites")) return "rss";
    return "";
  }

  function updateAppIndicators(activeApp) {
    var rssIndicator = document.getElementById("app-indicator-rss");
    var bookmarkIndicator = document.getElementById("app-indicator-bookmark");
    if (rssIndicator) rssIndicator.classList.toggle("hidden", activeApp !== "rss");
    if (bookmarkIndicator) bookmarkIndicator.classList.toggle("hidden", activeApp !== "bookmark");
    if (badge) badge.textContent = activeApp === "bookmark" ? "Bookmark" : "Feed";
  }

  // Initialize from the current page. Only fall back to stored state when the page is app-agnostic.
  var currentApp = detectCurrentApp();
  var storedApp = localStorage.getItem("feedee-active-app");
  if (!currentApp && storedApp && (storedApp === "rss" || storedApp === "bookmark")) {
    currentApp = storedApp;
  }
  if (!currentApp) currentApp = "rss";
  localStorage.setItem("feedee-active-app", currentApp);
  updateAppIndicators(currentApp);

  // Dropdown toggle
  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    dropdown.classList.toggle("hidden");
  });

  // Close dropdown on outside click
  document.addEventListener("click", function (e) {
    if (!dropdown.classList.contains("hidden") && !dropdown.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
      dropdown.classList.add("hidden");
    }
  });

  // App option links
  var appOptions = dropdown.querySelectorAll(".data-app-option");
  appOptions.forEach(function (option) {
    option.addEventListener("click", function (e) {
      e.preventDefault();
      var app = option.dataset.app;
      localStorage.setItem("feedee-active-app", app);
      updateAppIndicators(app);
      dropdown.classList.add("hidden");
      window.location.href = option.href;
    });
  });
})();

// ── Sidebar mode switcher (Phase 2) ────────────────────────
(function () {
  var rssSidebar = document.getElementById("sidebar-rss");
  var bookmarkSidebar = document.getElementById("sidebar-bookmark");

  if (!rssSidebar || !bookmarkSidebar) return;

  /**
   * Switch between RSS and Bookmark sidebar modes
   * @param {string} mode - 'rss' or 'bookmark'
   */
  function switchSidebarMode(mode) {
    if (mode === "rss") {
      rssSidebar.classList.remove("hidden");
      bookmarkSidebar.classList.add("hidden");
    } else if (mode === "bookmark") {
      rssSidebar.classList.add("hidden");
      bookmarkSidebar.classList.remove("hidden");
    }
  }

  // Listen to app switcher clicks
  var appOptions = document.querySelectorAll(".data-app-option");
  appOptions.forEach(function (option) {
    option.addEventListener("click", function (e) {
      var targetApp = e.currentTarget.dataset.app;
      // Switch sidebar immediately before navigation
      switchSidebarMode(targetApp);
    });
  });

  // Initialize on page load based on body data-current-app
  var initialApp = document.body.dataset.currentApp || "rss";
  switchSidebarMode(initialApp);
})();
