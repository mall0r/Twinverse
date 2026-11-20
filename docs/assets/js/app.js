(function () {
  "use strict";

  var html = document.documentElement;
  var STORAGE_LANG = "twinverse_docs_lang";
  var STORAGE_THEME = "twinverse_docs_theme";

  var UI_STRINGS = {
    en: {
      title: "Twinverse Documentation — Multi-Instance Steam Splitscreen & Multi-Monitor Guide",
      description:
        "Complete step-by-step documentation for Twinverse: run up to 8 isolated Steam instances on Linux & SteamOS in splitscreen or multi-monitor setups.",
      searchPlaceholder: "Search guides, features, shortcuts, CLI flags…",
      searchTrigger: "Search docs…",
      searchEmpty: "No matching sections found. Try another keyword.",
      copy: "Copy",
      copied: "Copied!",
      zoomHint: "Click to zoom",
      langBtn: "PT-BR",
      langAria: "Switch documentation language to Portuguese (Brazil)",
      themeAria: "Toggle light / dark theme",
      tocTitle: "On this page",
    },
    pt: {
      title: "Documentação do Twinverse — Guia Completo de Tela Dividida e Múltiplos Monitores no Linux",
      description:
        "Documentação passo a passo completa do Twinverse: execute até 8 instâncias isoladas do Steam no Linux e SteamOS em tela dividida ou múltiplos monitores.",
      searchPlaceholder: "Buscar guias, funcionalidades, atalhos, flags CLI…",
      searchTrigger: "Buscar na docs…",
      searchEmpty: "Nenhuma seção encontrada. Tente outro termo.",
      copy: "Copiar",
      copied: "Copiado!",
      zoomHint: "Clique para ampliar",
      langBtn: "EN",
      langAria: "Mudar idioma da documentação para Inglês",
      themeAria: "Alternar tema claro / escuro",
      tocTitle: "Nesta página",
    },
  };

  function detectInitialLang() {
    var params = new URLSearchParams(window.location.search);
    var q = (params.get("lang") || "").toLowerCase();
    if (q === "pt" || q === "pt-br") return "pt";
    if (q === "en" || q === "en-us") return "en";
    var saved = localStorage.getItem(STORAGE_LANG);
    if (saved === "pt" || saved === "en") return saved;
    var nav = (navigator.language || "").toLowerCase();
    return nav.startsWith("pt") ? "pt" : "en";
  }

  function detectInitialTheme() {
    var saved = localStorage.getItem(STORAGE_THEME);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }

  function applyLang(lang, persist) {
    html.setAttribute("data-lang", lang);
    html.setAttribute("lang", lang === "pt" ? "pt-BR" : "en");
    if (persist) {
      localStorage.setItem(STORAGE_LANG, lang);
    }
    var s = UI_STRINGS[lang] || UI_STRINGS.en;
    document.title = s.title;
    var metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) metaDesc.setAttribute("content", s.description);

    var langBtn = document.getElementById("lang-toggle");
    if (langBtn) {
      langBtn.textContent = s.langBtn;
      langBtn.setAttribute("aria-label", s.langAria);
    }
    var searchLabel = document.getElementById("search-trigger-label");
    if (searchLabel) searchLabel.textContent = s.searchTrigger;
    var searchInput = document.getElementById("search-input");
    if (searchInput) searchInput.setAttribute("placeholder", s.searchPlaceholder);
    var tocTitle = document.getElementById("toc-title");
    if (tocTitle) tocTitle.textContent = s.tocTitle;

    document.querySelectorAll(".copy-btn").forEach(function (btn) {
      if (!btn.classList.contains("copied")) {
        btn.textContent = s.copy;
      }
    });
    document.querySelectorAll(".figure-zoom-hint").forEach(function (hint) {
      hint.textContent = s.zoomHint;
    });

    rebuildToc();
    if (searchModal && searchModal.classList.contains("open")) {
      runSearch(searchInput ? searchInput.value : "");
    }
  }

  function applyTheme(theme, persist) {
    html.setAttribute("data-theme", theme);
    if (persist) {
      localStorage.setItem(STORAGE_THEME, theme);
    }
    var sun = document.getElementById("icon-sun");
    var moon = document.getElementById("icon-moon");
    if (sun && moon) {
      sun.style.display = theme === "dark" ? "block" : "none";
      moon.style.display = theme === "light" ? "block" : "none";
    }
  }

  // Dynamic On-This-Page TOC
  function rebuildToc() {
    var tocList = document.getElementById("toc-list");
    if (!tocList) return;
    var lang = html.getAttribute("data-lang") || "en";
    tocList.innerHTML = "";
    var sections = document.querySelectorAll("main .doc-section[id]");
    sections.forEach(function (sec) {
      var h2 = sec.querySelector("h2 [data-lang-block='" + lang + "']") || sec.querySelector("h2");
      if (!h2) return;
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#" + sec.id;
      a.textContent = h2.textContent.trim();
      li.appendChild(a);
      tocList.appendChild(li);

      sec.querySelectorAll("[data-toc-sub][id]").forEach(function (sub) {
        var subTitle = sub.querySelector("h3 [data-lang-block='" + lang + "']") || sub.querySelector("h3");
        if (!subTitle) return;
        var sli = document.createElement("li");
        var sa = document.createElement("a");
        sa.href = "#" + sub.id;
        sa.className = "toc-sub";
        sa.textContent = subTitle.textContent.trim();
        sli.appendChild(sa);
        tocList.appendChild(sli);
      });
    });
    updateActiveNav();
  }

  // Scroll-spy for Sidebar & Right TOC
  function updateActiveNav() {
    var anchors = Array.prototype.slice.call(
      document.querySelectorAll("main .doc-section[id], main [data-toc-sub][id]")
    );
    var scrollPos = window.scrollY + 120;
    var currentId = anchors.length ? anchors[0].id : "";
    for (var i = 0; i < anchors.length; i++) {
      if (anchors[i].offsetTop <= scrollPos) {
        currentId = anchors[i].id;
      }
    }
    var sectionEl = document.getElementById(currentId);
    var parentSectionId =
      sectionEl && sectionEl.closest(".doc-section[id]")
        ? sectionEl.closest(".doc-section[id]").id
        : currentId;

    document.querySelectorAll(".sidebar a").forEach(function (a) {
      var href = a.getAttribute("href");
      a.classList.toggle("active", href === "#" + currentId || href === "#" + parentSectionId);
    });
    document.querySelectorAll("#toc-list a").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("href") === "#" + currentId);
    });
  }

  // Copy Buttons
  function initCodeCopy() {
    var lang = html.getAttribute("data-lang") || "en";
    document.querySelectorAll("pre").forEach(function (pre) {
      if (pre.parentElement && pre.parentElement.classList.contains("code-wrap")) return;
      var wrap = document.createElement("div");
      wrap.className = "code-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = (UI_STRINGS[lang] || UI_STRINGS.en).copy;
      btn.addEventListener("click", function () {
        var code = pre.querySelector("code");
        var text = code ? code.innerText : pre.innerText;
        var curLang = html.getAttribute("data-lang") || "en";
        var s = UI_STRINGS[curLang] || UI_STRINGS.en;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            btn.textContent = s.copied;
            btn.classList.add("copied");
            setTimeout(function () {
              btn.textContent = (UI_STRINGS[html.getAttribute("data-lang") || "en"] || UI_STRINGS.en).copy;
              btn.classList.remove("copied");
            }, 1600);
          });
        }
      });
      wrap.appendChild(btn);
    });
  }

  // Interactive Tabs
  function initTabs() {
    document.querySelectorAll(".tabs").forEach(function (group) {
      var buttons = group.querySelectorAll(".tab-btn");
      var panels = group.querySelectorAll(".tab-panel");
      buttons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          var target = btn.getAttribute("data-tab");
          buttons.forEach(function (b) {
            b.setAttribute("aria-selected", b === btn ? "true" : "false");
          });
          panels.forEach(function (p) {
            p.hidden = p.getAttribute("data-panel") !== target;
          });
        });
      });
    });
  }

  // Image Lightbox
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = document.getElementById("lightbox-img");
  var lightboxCap = document.getElementById("lightbox-caption");

  function openLightbox(src, alt, caption) {
    if (!lightbox || !lightboxImg) return;
    lightboxImg.src = src;
    lightboxImg.alt = alt || "";
    if (lightboxCap) lightboxCap.textContent = caption || alt || "";
    lightbox.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.classList.remove("open");
    document.body.style.overflow = "";
  }

  function initLightbox() {
    document.querySelectorAll(".figure-img-wrap").forEach(function (wrap) {
      var img = wrap.querySelector("img");
      if (!img) return;
      var hint = document.createElement("span");
      hint.className = "figure-zoom-hint";
      hint.textContent = UI_STRINGS[html.getAttribute("data-lang") || "en"].zoomHint;
      wrap.appendChild(hint);

      wrap.addEventListener("click", function () {
        var fig = wrap.closest("figure");
        var lang = html.getAttribute("data-lang") || "en";
        var capEl = fig
          ? fig.querySelector("figcaption [data-lang-block='" + lang + "']") || fig.querySelector("figcaption")
          : null;
        openLightbox(img.src, img.alt, capEl ? capEl.textContent.trim() : img.alt);
      });
    });

    var closeBtn = document.getElementById("lightbox-close");
    if (closeBtn) closeBtn.addEventListener("click", closeLightbox);
    if (lightbox) {
      lightbox.addEventListener("click", function (e) {
        if (e.target === lightbox) closeLightbox();
      });
    }
  }

  // Full-Text Search
  var searchModal = document.getElementById("search-modal");
  var searchInput = document.getElementById("search-input");
  var searchResults = document.getElementById("search-results");

  function getVisibleText(el, lang) {
    var clone = el.cloneNode(true);
    clone.querySelectorAll("[data-lang-block='" + (lang === "en" ? "pt" : "en") + "']").forEach(function (n) {
      n.remove();
    });
    return (clone.textContent || "").replace(/\s+/g, " ").trim();
  }

  function runSearch(query) {
    if (!searchResults) return;
    var lang = html.getAttribute("data-lang") || "en";
    var q = (query || "").trim().toLowerCase();
    var targets = document.querySelectorAll("main .doc-section[id], main [data-toc-sub][id]");
    var matches = [];

    targets.forEach(function (el) {
      var heading =
        el.querySelector("h2 [data-lang-block='" + lang + "'], h3 [data-lang-block='" + lang + "']") ||
        el.querySelector("h2, h3");
      if (!heading) return;
      var title = heading.textContent.trim();
      var body = getVisibleText(el, lang);
      var hay = (title + " " + body).toLowerCase();
      if (!q || hay.indexOf(q) !== -1) {
        var snippet = body.slice(0, 140);
        if (q) {
          var pos = body.toLowerCase().indexOf(q);
          if (pos > 30) {
            snippet = "…" + body.slice(Math.max(0, pos - 40), pos + 100) + "…";
          } else {
            snippet = body.slice(0, 140) + (body.length > 140 ? "…" : "");
          }
        }
        matches.push({ id: el.id, title: title, snippet: snippet });
      }
    });

    searchResults.innerHTML = "";
    if (!matches.length) {
      var empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = (UI_STRINGS[lang] || UI_STRINGS.en).searchEmpty;
      searchResults.appendChild(empty);
      return;
    }

    matches.slice(0, 14).forEach(function (m) {
      var a = document.createElement("a");
      a.className = "search-result-item";
      a.href = "#" + m.id;
      var t = document.createElement("div");
      t.className = "search-result-title";
      t.textContent = m.title;
      var sn = document.createElement("div");
      sn.className = "search-result-snippet";
      sn.textContent = m.snippet;
      a.appendChild(t);
      a.appendChild(sn);
      a.addEventListener("click", function () {
        closeSearch();
      });
      searchResults.appendChild(a);
    });
  }

  function openSearch() {
    if (!searchModal) return;
    searchModal.classList.add("open");
    runSearch(searchInput ? searchInput.value : "");
    if (searchInput) {
      searchInput.focus();
      searchInput.select();
    }
  }

  function closeSearch() {
    if (!searchModal) return;
    searchModal.classList.remove("open");
  }

  // Mobile Drawer
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.getElementById("sidebar-backdrop");
  var menuBtn = document.getElementById("mobile-menu-btn");

  function closeDrawer() {
    if (sidebar) sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("open");
  }

  function initEvents() {
    var langBtn = document.getElementById("lang-toggle");
    if (langBtn) {
      langBtn.addEventListener("click", function () {
        var next = html.getAttribute("data-lang") === "pt" ? "en" : "pt";
        applyLang(next, true);
      });
    }

    var themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
        applyTheme(next, true);
      });
    }

    var searchTrigger = document.getElementById("search-trigger");
    if (searchTrigger) searchTrigger.addEventListener("click", openSearch);
    if (searchModal) {
      searchModal.addEventListener("click", function (e) {
        if (e.target === searchModal) closeSearch();
      });
    }
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        runSearch(searchInput.value);
      });
    }

    if (menuBtn) {
      menuBtn.addEventListener("click", function () {
        if (sidebar) sidebar.classList.toggle("open");
        if (backdrop) backdrop.classList.toggle("open");
      });
    }
    if (backdrop) backdrop.addEventListener("click", closeDrawer);
    if (sidebar) {
      sidebar.querySelectorAll("a").forEach(function (link) {
        link.addEventListener("click", closeDrawer);
      });
    }

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openSearch();
      } else if (
        e.key === "/" &&
        document.activeElement &&
        !/input|textarea|select/i.test(document.activeElement.tagName)
      ) {
        e.preventDefault();
        openSearch();
      } else if (e.key === "Escape") {
        closeSearch();
        closeLightbox();
        closeDrawer();
      }
    });

    var ticking = false;
    window.addEventListener(
      "scroll",
      function () {
        if (!ticking) {
          window.requestAnimationFrame(function () {
            updateActiveNav();
            ticking = false;
          });
          ticking = true;
        }
      },
      { passive: true }
    );
  }

  // Bootstrap
  applyTheme(detectInitialTheme(), false);
  initCodeCopy();
  initTabs();
  initLightbox();
  initEvents();
  applyLang(detectInitialLang(), false);
})();
