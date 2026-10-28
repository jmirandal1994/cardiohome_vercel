/* ═══ Capa visual con movimiento para toda la plataforma ═══
   - Barra de carga superior mientras hay consultas en curso (no cambia las consultas).
   - Entrada en cascada de los bloques cuando se abre una sección.
   - Conteo animado en los números grandes de las tarjetas KPI (.kpi-g-val). */
(function () {
  "use strict";
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ── Barra de carga ──
  const bar = document.createElement("div");
  bar.id = "uim-progreso";
  let activas = 0, timer = null, ancho = 0;
  function avanzar() { ancho = Math.min(90, ancho + (90 - ancho) * 0.12); bar.style.width = ancho + "%"; }
  function inicio() {
    if (!bar.isConnected && document.body) document.body.appendChild(bar);
    if (activas++ === 0) { ancho = 8; bar.style.width = "8%"; bar.classList.add("on"); clearInterval(timer); timer = setInterval(avanzar, 250); }
  }
  function fin() {
    activas = Math.max(0, activas - 1);
    if (activas === 0) {
      clearInterval(timer); bar.style.width = "100%";
      setTimeout(() => { if (activas === 0) { bar.classList.remove("on"); setTimeout(() => { if (activas === 0) bar.style.width = "0"; }, 300); } }, 250);
    }
  }
  if (window.fetch && !window.fetch.__uim) {
    const original = window.fetch;
    const envuelto = function () {
      inicio();
      let p;
      try { p = original.apply(this, arguments); } catch (e) { fin(); throw e; }
      return p.finally ? p.finally(fin) : p.then((r) => { fin(); return r; }, (e) => { fin(); throw e; });
    };
    envuelto.__uim = true;
    window.fetch = envuelto;
  }

  if (reduce) return;

  // ── Entrada en cascada al abrir una sección ──
  function cascada(sec) {
    Array.from(sec.children).slice(0, 14).forEach((el, i) => {
      el.classList.remove("uim-entra"); void el.offsetWidth;
      el.style.animationDelay = i * 55 + "ms";
      el.classList.add("uim-entra");
    });
  }
  const obsSecciones = new MutationObserver((ms) => {
    ms.forEach((m) => {
      const el = m.target;
      if (m.attributeName === "class" && el.classList.contains("content-section") && el.classList.contains("active") &&
          !(m.oldValue || "").split(/\s+/).includes("active")) cascada(el);
    });
  });

  // ── Conteo animado en KPIs ──
  const parse = (t) => {
    const m = String(t).trim().match(/^([\d.]+)(,\d+)?(%?)$/);
    if (!m) return null;
    const v = parseFloat(m[1].replace(/\./g, "") + (m[2] ? "." + m[2].slice(1) : ""));
    return isFinite(v) ? { v, dec: m[2] ? m[2].length - 1 : 0, suf: m[3] } : null;
  };
  const fmt = (n, d) => n.toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
  const animando = new WeakSet();
  function contar(el, desde, hasta) {
    animando.add(el);
    const t0 = performance.now(), dur = 800, final = el.textContent;
    const paso = (t) => {
      if (el.textContent !== el.__uimUltimo && el.__uimUltimo !== undefined) { animando.delete(el); return; } // otro código cambió el valor
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      const txt = k < 1 ? fmt(desde + (hasta.v - desde) * e, hasta.dec) + hasta.suf : final;
      el.textContent = txt; el.__uimUltimo = txt;
      if (k < 1) requestAnimationFrame(paso); else animando.delete(el);
    };
    el.__uimUltimo = undefined;
    requestAnimationFrame(paso);
  }
  const previo = new WeakMap();
  const obsKpi = new MutationObserver((ms) => {
    const vistos = new Set();
    ms.forEach((m) => {
      const el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
      if (!el || !el.classList || !el.classList.contains("kpi-g-val") || vistos.has(el)) return;
      vistos.add(el);
      if (animando.has(el)) return;
      const nuevo = parse(el.textContent);
      const antes = previo.get(el);
      previo.set(el, nuevo);
      if (!nuevo || el.children.length) return;
      const desde = antes ? antes.v : 0;
      if (antes && antes.v === nuevo.v) return;
      contar(el, desde, nuevo);
    });
  });

  function arrancar() {
    document.querySelectorAll(".content-section").forEach((s) => obsSecciones.observe(s, { attributes: true, attributeFilter: ["class"], attributeOldValue: true }));
    const main = document.getElementById("mainContent") || document.body;
    obsKpi.observe(main, { childList: true, characterData: true, subtree: true });
    const activa = document.querySelector(".content-section.active");
    if (activa) cascada(activa);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar); else arrancar();
})();
