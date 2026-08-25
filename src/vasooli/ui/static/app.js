// Tooltip layer for SVG marks, and the theme toggle.
// Deliberately tiny and dependency-free: the dashboard must render with no
// network access at all.

(function () {
  const tip = document.createElement("div");
  tip.id = "tip";
  document.body.appendChild(tip);

  document.addEventListener("mouseover", (e) => {
    const g = e.target.closest("[data-tip]");
    if (!g) return;
    tip.textContent = g.getAttribute("data-tip");
    tip.classList.add("on");
  });
  document.addEventListener("mousemove", (e) => {
    if (!tip.classList.contains("on")) return;
    const pad = 14;
    let x = e.clientX + pad;
    let y = e.clientY + pad;
    const r = tip.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest("[data-tip]")) tip.classList.remove("on");
  });

  const btn = document.getElementById("theme");
  if (btn) {
    const stored = (() => {
      try { return localStorage.getItem("vasooli-theme"); } catch { return null; }
    })();
    if (stored) document.documentElement.setAttribute("data-theme", stored);
    btn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme");
      const dark = cur
        ? cur === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("vasooli-theme", next); } catch { /* private mode */ }
    });
  }
})();
