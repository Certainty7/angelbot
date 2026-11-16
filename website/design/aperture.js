/* ANGEL — hero reference behaviour. No framework, ~1 KB, CSP-safe (external file).
   The page reaches its final state without this file; this only adds the theme
   switch and the sticky-header hairline. */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    var night = function () {
      var t = root.getAttribute("data-theme");
      return t === "rose-night" || t === "dark";
    };
    var sync = function () {
      var isNight = night();
      toggle.setAttribute("aria-pressed", String(isNight));
      toggle.setAttribute(
        "aria-label",
        isNight ? "التبديل إلى المظهر الفاتح" : "التبديل إلى المظهر الداكن"
      );
    };
    sync();
    toggle.addEventListener("click", function () {
      var next = night() ? "light" : "rose-night";
      var apply = function () {
        root.setAttribute("data-theme", next);
        sync();
      };
      try {
        localStorage.setItem("angel-theme", next);
      } catch (e) {
        /* storage blocked: the choice still holds for this document */
      }
      if (document.startViewTransition && !reduce) {
        document.startViewTransition(apply);
      } else {
        apply();
      }
    });
  }

  var head = document.querySelector("[data-head]");
  if (head) {
    var onScroll = function () {
      head.classList.toggle("is-stuck", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }
})();
