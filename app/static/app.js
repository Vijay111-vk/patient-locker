// Live updates without a page framework: watch a status URL and reload when something changes.
(function () {
  const watched = document.querySelector("[data-watch]");
  if (watched) {
    const url = watched.getAttribute("data-watch");
    let first = null;
    const tick = async () => {
      try {
        const r = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
        if (!r.ok) return;
        const data = await r.json();
        const sig = JSON.stringify(data);
        if (first === null) first = sig;
        else if (sig !== first || data.running === false) { location.reload(); return; }
      } catch (e) { /* network blip; try again */ }
      setTimeout(tick, 1500);
    };
    setTimeout(tick, 800);
  }
  const poll = document.querySelector("[data-poll]");
  if (poll) setTimeout(() => location.reload(), 4000);

  document.querySelectorAll("form[data-confirm]").forEach((f) =>
    f.addEventListener("submit", (e) => { if (!confirm(f.getAttribute("data-confirm"))) e.preventDefault(); }));
  document.querySelectorAll("select[data-autosubmit]").forEach((s) =>
    s.addEventListener("change", () => s.form.submit()));
  document.querySelectorAll("form").forEach((f) =>
    f.addEventListener("submit", () => {
      const b = f.querySelector("button[type=submit], button:not([type])");
      if (b && !f.hasAttribute("data-confirm")) setTimeout(() => { b.disabled = true; }, 0);
    }));
})();
