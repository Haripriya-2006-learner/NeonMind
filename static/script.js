/* NeonMind front-end behaviour (vanilla JS, no libraries) */
document.addEventListener("DOMContentLoaded", () => {
  initMenu();
  initParticles();
  initFlash();
  initConfirm();
  initProgress();
  initCounters();
  initCharts();
  initTaskDialog();
  initDiary();
  initAppearancePreview();
  initPasswordMatch();
});

/* Responsive sidebar: hamburger opens it, overlay / link / Esc closes it */
function initMenu() {
  const btn = document.getElementById("menuBtn");
  const overlay = document.getElementById("overlay");
  if (!btn) return;
  const set = (open) => {
    document.body.classList.toggle("menu-open", open);
    btn.setAttribute("aria-expanded", String(open));
  };
  btn.addEventListener("click", () => set(!document.body.classList.contains("menu-open")));
  overlay.addEventListener("click", () => set(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
  document.querySelectorAll("#sidebar .nav a").forEach((a) => a.addEventListener("click", () => set(false)));
  window.matchMedia("(min-width: 992px)").addEventListener("change", (m) => { if (m.matches) set(false); });
}

/* Floating neon particles on a canvas (skipped if the user prefers less motion) */
function initParticles() {
  const canvas = document.getElementById("particles");
  if (!canvas || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const ctx = canvas.getContext("2d");
  let w, h, dots = [], raf;

  const accent = () => getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim() || "182,255,0";
  function resize() {
    const ratio = window.devicePixelRatio || 1;
    w = canvas.width = innerWidth * ratio;
    h = canvas.height = innerHeight * ratio;
    const count = Math.min(48, Math.floor(innerWidth / 30));
    dots = Array.from({ length: count }, () => ({
      x: Math.random() * w, y: Math.random() * h, r: (Math.random() * 1.6 + 0.6) * ratio,
      vx: (Math.random() - 0.5) * 0.25 * ratio, vy: (Math.random() - 0.5) * 0.25 * ratio,
    }));
  }
  function draw() {
    ctx.clearRect(0, 0, w, h);
    const rgb = accent();
    const reach = 120 * (window.devicePixelRatio || 1);
    dots.forEach((d, i) => {
      d.x += d.vx; d.y += d.vy;
      if (d.x < 0 || d.x > w) d.vx *= -1;
      if (d.y < 0 || d.y > h) d.vy *= -1;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${rgb},0.55)`;
      ctx.fill();
      for (let j = i + 1; j < dots.length; j++) {          // faint lines between close dots
        const dx = d.x - dots[j].x, dy = d.y - dots[j].y, dist = Math.hypot(dx, dy);
        if (dist < reach) {
          ctx.strokeStyle = `rgba(${rgb},${0.12 * (1 - dist / reach)})`;
          ctx.beginPath(); ctx.moveTo(d.x, d.y); ctx.lineTo(dots[j].x, dots[j].y); ctx.stroke();
        }
      }
    });
    raf = requestAnimationFrame(draw);
  }
  resize(); draw();
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", () => {      // pause when tab is hidden
    cancelAnimationFrame(raf);
    if (!document.hidden) draw();
  });
}

/* Auto-hide flash messages */
function initFlash() {
  document.querySelectorAll(".flash").forEach((el, i) => {
    setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 450); }, 4200 + i * 400);
  });
}

/* Any form with data-confirm asks before submitting */
function initConfirm() {
  document.querySelectorAll("form[data-confirm]").forEach((f) => {
    f.addEventListener("submit", (e) => { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });
}

/* Animate progress bars from 0 to their data-progress value */
function initProgress() {
  const bars = document.querySelectorAll("[data-progress]");
  requestAnimationFrame(() => setTimeout(() => {
    bars.forEach((b) => { b.style.width = Math.min(100, Number(b.dataset.progress) || 0) + "%"; });
  }, 120));
}

/* Count numbers up from 0 */
function initCounters() {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll(".count").forEach((el) => {
    const target = Number(el.dataset.target) || 0;
    if (reduce || target === 0) { el.textContent = target; return; }
    const start = performance.now(), dur = 900;
    (function tick(now) {
      const t = Math.min(1, (now - start) / dur);
      el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick);
    })(start);
  });
}

/* Charts are built from JSON in data-points using plain divs + CSS */
function initCharts() {
  const week = document.getElementById("weekChart");
  if (week) {
    const points = JSON.parse(week.dataset.points);
    const max = Math.max(1, ...points.flatMap((p) => [p.added, p.completed]));
    week.innerHTML = "";
    points.forEach((p) => {
      const col = document.createElement("div");
      col.className = "chart-col";
      col.innerHTML = `<div class="chart-bars">
          <div class="chart-bar added" data-h="${p.added / max * 88}" title="${p.added} added"><span>${p.added || ""}</span></div>
          <div class="chart-bar done" data-h="${p.completed / max * 88}" title="${p.completed} completed"><span>${p.completed || ""}</span></div>
        </div><div class="chart-label">${p.label}</div>`;
      week.appendChild(col);
    });
    growBars(week);
  }
  const mood = document.getElementById("moodChart");
  if (mood) {
    const points = JSON.parse(mood.dataset.points);
    mood.innerHTML = "";
    points.forEach((p) => {
      const col = document.createElement("div");
      col.className = "chart-col";
      col.innerHTML = `<div class="chart-bars">
          <div class="chart-bar" data-h="${p.score / 5 * 80}" title="${p.name}"><span class="chart-emoji">${p.emoji}</span></div>
        </div><div class="chart-label">${p.label}</div>`;
      mood.appendChild(col);
    });
    growBars(mood);
  }
}
function growBars(root) {
  requestAnimationFrame(() => setTimeout(() => {
    root.querySelectorAll(".chart-bar").forEach((b) => { b.style.height = Math.max(Number(b.dataset.h), 2) + "%"; });
  }, 150));
}

/* Task edit dialog */
function initTaskDialog() {
  const dlg = document.getElementById("editDialog");
  if (!dlg) return;
  document.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("editId").value = btn.dataset.id;
      document.getElementById("editTitle").value = btn.dataset.title;
      document.getElementById("editPriority").value = btn.dataset.priority;
      document.getElementById("editDue").value = btn.dataset.due;
      dlg.showModal();
      document.getElementById("editTitle").focus();
    });
  });
  document.getElementById("editCancel").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // click backdrop to close
}

/* Diary: character counter + "Read more" only on long entries */
function initDiary() {
  const area = document.querySelector("textarea[data-count]");
  if (area) {
    const out = document.querySelector(area.dataset.count);
    const update = () => { out.textContent = area.value.length; };
    area.addEventListener("input", update); update();
  }
  document.querySelectorAll(".diary-card").forEach((card) => {
    const text = card.querySelector(".diary-text");
    const btn = card.querySelector(".toggle-read");
    if (text.scrollHeight > text.clientHeight + 2) btn.hidden = false;
    btn.addEventListener("click", () => {
      const open = card.classList.toggle("expanded");
      btn.textContent = open ? "Show less" : "Read more";
    });
  });
}

/* Settings: preview theme / mode instantly before saving */
function initAppearancePreview() {
  const form = document.getElementById("appearanceForm");
  if (!form) return;
  form.addEventListener("change", (e) => {
    if (e.target.name === "theme") document.documentElement.dataset.theme = e.target.value;
    if (e.target.name === "mode") document.documentElement.dataset.mode = e.target.value;
  });
}

/* Check "confirm" matches the password field before submitting */
function initPasswordMatch() {
  document.querySelectorAll("form.js-match").forEach((form) => {
    const confirm = form.querySelector('input[name="confirm"]');
    const pw = form.querySelector('input[name="password"], input[name="new"]');
    const check = () => confirm.setCustomValidity(confirm.value && confirm.value !== pw.value ? "Passwords do not match." : "");
    confirm.addEventListener("input", check); pw.addEventListener("input", check);
  });
}