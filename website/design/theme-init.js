/* Runs before first paint: restores the visitor's theme, so there is no flash.
   The only blocking script on the site, and it is 340 bytes of localStorage. */
(function () {
  try {
    var saved = localStorage.getItem("angel-theme");
    if (saved === "rose-night" || saved === "dark" || saved === "light") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) {
    /* private mode: the Pearl Light default stands */
  }
})();
