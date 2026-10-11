// Run before CSS and body rendering so saved light mode also avoids a flash.
(() => {
  let theme = "dark";
  try {
    const saved = localStorage.getItem("tally-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch {}
  document.documentElement.dataset.theme = theme;
})();
