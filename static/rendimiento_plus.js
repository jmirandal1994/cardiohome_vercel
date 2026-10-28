/* ═══ Rendimiento en Vivo ampliado ═══
   Equipo conectado, actividad en vivo, correcciones, evaluaciones por doctora,
   calendario de actividad y ausencias. Lee /api/coordinadora/actividad y se
   actualiza solo cada minuto mientras el panel está a la vista. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (n) => (n == null ? "—" : Number(n).toLocaleString("es-CL"));
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const PALETA = ["#1c67a3", "#0f766e", "#7c3aed", "#db2777", "#d97706", "#0891b2", "#4f46e5", "#15803d", "#be123c", "#0e7490"];
  const colorDe = (s) => { let h = 0; for (const ch of String(s || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return PALETA[h % PALETA.length]; };
  const ini = (n) => String(n || "?").replace(/^(dra?\.?|dr\.?)\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  const avatar = (nombre, clase = "") => `<span class="${clase}" style="background:linear-gradient(135deg,${colorDe(nombre)},#0f3460)">${esc(ini(nombre))}</span>`;
  function hace(fechaIso, hoyIso) {
    if (!fechaIso) return "";
    const d = Math.round((new Date(hoyIso) - new Date(fechaIso.slice(0, 10))) / 86400000);
    if (d <= 0) return "hoy";
    if (d === 1) return "ayer";
    if (d < 7) return `hace ${d} días`;
    const [y, m, dd] = fechaIso.slice(0, 10).split("-");
    return `${+dd} ${MESES[+m - 1]}${y !== hoyIso.slice(0, 4) ? " " + y : ""}`;
  }

  let datos = null, filtro = "todo", periodo = "total", vistos = null, chartDoc = null, timer = null;

  async function cargar() {
    if (!$("rp-root")) return;
    try {
      const r = await fetch("/api/coordinadora/actividad", { credentials: "same-origin" });
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.message || "Error");
      datos = j;
      pintar();
      revisarPeriodoVacio();
    } catch (e) {
      ["rp-team", "rp-feed", "rp-corr", "rp-doc-list", "rp-heat", "rp-aus"].forEach((id) => {
        const el = $(id); if (el && !datos) el.innerHTML = `<div class="rp-load" style="color:#b91c1c"><i class="fa-solid fa-triangle-exclamation"></i> No se pudo cargar. Se reintentará en un minuto.</div>`;
      });
    }
  }

  function pintar() { equipo(); feed(); correcciones(); porDoctora(); calendario(); ausencias(); }

  const ILUSTRACION = `<svg width="86" height="70" viewBox="0 0 86 70" aria-hidden="true"><rect x="8" y="14" width="44" height="50" rx="7" fill="#e0ecff"/><rect x="20" y="8" width="20" height="10" rx="4" fill="#1c67a3"/><path d="M18 32h24M18 42h24M18 52h14" stroke="#1c67a3" stroke-width="3" stroke-linecap="round" opacity=".55"/><circle cx="64" cy="40" r="16" fill="#dcfce7"/><path d="M64 32v16M56 40h16" stroke="#16a34a" stroke-width="4" stroke-linecap="round"/></svg>`;

  function equipo() {
    const el = $("rp-team"), c = datos.conectadas || [];
    if (!c.length) {
      const u = datos.ultima_actividad ? new Date(datos.ultima_actividad) : null;
      el.innerHTML = `<div class="rp-empty">${ILUSTRACION}<div><b style="color:#13263a">No hay doctoras conectadas en este momento.</b><br>
        ${u ? `Última actividad registrada: ${u.toLocaleDateString("es-CL", { day: "numeric", month: "long" })} a las ${u.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" })}.` : "Cuando una doctora abra una nómina aparecerá aquí."}</div></div>`;
      return;
    }
    el.innerHTML = `<div class="rp-team">${c.map((p, i) => `<div class="rp-person" style="animation-delay:${i * 60}ms">
      ${avatar(p.doctora, "rp-ava on")}<b>${esc(p.doctora)}</b><small>${esc(p.establecimiento || "—")}</small>
      <small style="color:#15803d;font-weight:700;margin-top:3px">${p.hace_min <= 1 ? "activa ahora" : `hace ${p.hace_min} min`}</small></div>`).join("")}</div>`;
  }

  function feed() {
    const el = $("rp-feed");
    const evs = (datos.eventos || []).filter((e) => filtro === "todo" || e.tipo === filtro);
    const clave = (e) => `${e.tipo}|${e.fecha}|${e.estudiante}|${e.estado || ""}`;
    const previos = vistos;
    vistos = new Set((datos.eventos || []).map(clave));
    if (!evs.length) { el.innerHTML = `<div class="rp-empty">${ILUSTRACION}<div>Aún no hay actividad registrada.</div></div>`; return; }
    el.innerHTML = evs.map((e, i) => {
      const nuevo = previos && !previos.has(clave(e)) ? " nuevo" : "";
      let ic, t, s;
      if (e.tipo === "evaluacion") {
        const neuro = e.especialidad === "Neurología";
        ic = `<span class="rp-ic" style="background:${neuro ? "#ede9fe" : "#e0ecff"};color:${neuro ? "#6d28d9" : "#1c67a3"}"><i class="fa-solid ${neuro ? "fa-brain" : "fa-stethoscope"}"></i></span>`;
        t = `Evaluación cerrada · ${esc(e.estudiante || "Estudiante")}`;
        s = `${esc(e.colegio || "—")} · ${esc(e.doctora || "")}`;
      } else {
        const ok = e.estado === "Aprobada", pend = e.estado === "Pendiente";
        ic = `<span class="rp-ic" style="background:${ok ? "#dcfce7" : pend ? "#fef3c7" : "#fee2e2"};color:${ok ? "#15803d" : pend ? "#b45309" : "#b91c1c"}"><i class="fa-solid ${ok ? "fa-circle-check" : pend ? "fa-hourglass-half" : "fa-circle-xmark"}"></i></span>`;
        t = `Corrección ${ok ? "aprobada" : pend ? "pendiente" : "rechazada"} · ${esc(e.estudiante || "Estudiante")}`;
        s = `${esc(e.colegio || "—")}${e.detalle ? " · " + esc(e.detalle) : ""}`;
      }
      return `<div class="rp-ev${nuevo}" style="animation-delay:${Math.min(i, 8) * 40}ms">${ic}<div style="min-width:0;flex:1"><div class="t">${t}</div><div class="s">${s}</div></div><span class="w">${hace(e.fecha, datos.hoy)}</span></div>`;
    }).join("");
  }

  function correcciones() {
    const c = datos.correcciones || {}, pe = c.por_estado || {}, el = $("rp-corr");
    const ap = pe.Aprobada || 0, re = pe.Rechazada || 0, pen = pe.Pendiente || 0, tot = c.total || 0;
    const pct = (n) => (tot ? Math.round((100 * n) / tot) : 0);
    el.innerHTML = `<div class="rp-mini">
        <div><small>Aprobadas</small><b style="color:#15803d">${fmtN(ap)}</b></div>
        <div><small>Rechazadas</small><b style="color:#b91c1c">${fmtN(re)}</b></div>
        <div><small>Pendientes</small><b style="color:#b45309">${fmtN(pen)}</b></div></div>
      <div style="display:flex;height:12px;border-radius:99px;overflow:hidden;background:#eef2f6;margin-bottom:6px">
        <span style="width:${pct(ap)}%;background:#16a34a;transition:width 1s"></span><span style="width:${pct(re)}%;background:#dc2626"></span><span style="width:${pct(pen)}%;background:#f59e0b"></span></div>
      <p style="font-size:.78rem;color:#5b6b7a;margin:0 0 14px">${fmtN(tot)} solicitudes${c.tasa != null ? ` · <b>${String(c.tasa).replace(".", ",")}%</b> de las evaluaciones pidió corrección` : ""}</p>
      <div style="font-size:.78rem;font-weight:800;color:#0f3460;margin-bottom:8px">Colegios con más correcciones</div>
      <div class="rp-list">${(c.por_colegio || []).map((x) => `<div><div class="row"><span>${esc(x.colegio)}</span><b>${fmtN(x.n)}</b></div>
        <div style="height:6px;border-radius:99px;background:#eef2f6;overflow:hidden;margin-top:4px"><span style="display:block;height:100%;width:${Math.round((100 * x.n) / Math.max(1, c.por_colegio[0].n))}%;background:#7c3aed;border-radius:99px"></span></div></div>`).join("") || `<span style="font-size:.82rem;color:#5b6b7a">Sin correcciones.</span>`}</div>`;
  }

  function porDoctora() {
    const docs = (datos.doctoras || []).slice().sort((a, b) => b[periodo] - a[periodo]).filter((d) => d[periodo] > 0);
    $("rp-doc-sub").textContent = `${docs.length} profesionales · ${fmtN(docs.reduce((s, d) => s + d[periodo], 0))} formularios cerrados${periodo === "total" ? "" : periodo === "d30" ? " en los últimos 30 días" : " en los últimos 7 días"}`;
    const top = docs.slice(0, 12), max = Math.max(1, ...docs.map((d) => d[periodo]));
    $("rp-doc-list").innerHTML = docs.length ? docs.map((d, i) => `<div class="rp-doc">
      <span style="width:22px;font-weight:800;color:#94a3b8;font-size:.78rem">${i + 1}</span>${avatar(d.nombre, "ava")}
      <div style="flex:1;min-width:0"><div style="display:flex;justify-content:space-between;gap:8px;font-size:.84rem"><b style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(d.nombre)}</b><b>${fmtN(d[periodo])}</b></div>
      <div style="font-size:.72rem;color:#5b6b7a">${esc(d.especialidad)} · ${d.colegios} colegio${d.colegios === 1 ? "" : "s"}</div>
      <div class="bar"><span style="width:${Math.round((100 * d[periodo]) / max)}%;background:${colorDe(d.nombre)}"></span></div></div></div>`).join("")
      : `<div class="rp-empty">${ILUSTRACION}<div>No hay evaluaciones en este periodo.</div></div>`;
    if (!window.Chart) return;
    if (chartDoc) chartDoc.destroy();
    chartDoc = new Chart($("rp-doc-chart").getContext("2d"), {
      type: "bar",
      data: { labels: top.map((d) => d.nombre.length > 22 ? d.nombre.slice(0, 20) + "…" : d.nombre),
        datasets: [{ data: top.map((d) => d[periodo]), backgroundColor: top.map((d) => colorDe(d.nombre)), borderRadius: 7, maxBarThickness: 26 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: { duration: 900, easing: "easeOutCubic" },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${fmtN(c.parsed.x)} evaluaciones` } } },
        scales: { x: { grid: { color: "#eef2f6" }, ticks: { precision: 0 } }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } } },
    });
  }

  function calendario() {
    const cal = datos.calor || [], max = Math.max(1, ...cal.map((d) => d.n));
    const tono = (n) => (n === 0 ? "#eef2f6" : n < max * 0.15 ? "#bbf7d0" : n < max * 0.35 ? "#4ade80" : n < max * 0.65 ? "#16a34a" : "#14532d");
    const total = cal.reduce((s, d) => s + d.n, 0), activos = cal.filter((d) => d.n > 0).length;
    const mejor = cal.reduce((a, b) => (b.n > a.n ? b : a), { n: 0 });
    $("rp-heat").innerHTML = `<div class="rp-mini">
        <div><small>Evaluaciones</small><b>${fmtN(total)}</b></div><div><small>Días con actividad</small><b>${fmtN(activos)}</b></div>
        <div><small>Mejor día</small><b>${fmtN(mejor.n)}</b><small>${mejor.fecha ? new Date(mejor.fecha + "T12:00").toLocaleDateString("es-CL", { day: "numeric", month: "short" }) : ""}</small></div></div>
      <div class="rp-heat">${cal.map((d, i) => `<span title="${new Date(d.fecha + "T12:00").toLocaleDateString("es-CL", { weekday: "short", day: "numeric", month: "short" })}: ${d.n} evaluaciones" style="background:${tono(d.n)};animation-delay:${Math.floor(i / 7) * 12}ms"></span>`).join("")}</div>
      <div class="rp-heat-leg">Menos <i style="background:#eef2f6"></i><i style="background:#bbf7d0"></i><i style="background:#4ade80"></i><i style="background:#16a34a"></i><i style="background:#14532d"></i> Más</div>`;
    const h = $("rp-heat").querySelector(".rp-heat");
    if (h) h.scrollLeft = h.scrollWidth;  // mostrar primero las semanas más recientes
  }

  function ausencias() {
    const a = datos.ausencias || {};
    $("rp-aus").innerHTML = `<div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
        <div style="width:64px;height:64px;border-radius:18px;background:#fee2e2;color:#b91c1c;display:flex;align-items:center;justify-content:center;font-size:1.5rem"><i class="fa-solid fa-user-slash"></i></div>
        <div><b style="font-size:1.9rem;color:#b91c1c;line-height:1">${fmtN(a.total)}</b><div style="font-size:.8rem;color:#5b6b7a">estudiantes marcados como "no asiste"</div></div></div>
      <div style="font-size:.78rem;font-weight:800;color:#0f3460;margin-bottom:8px">Motivos más frecuentes</div>
      <div class="rp-list">${(a.motivos || []).map((m) => `<div class="row"><span>${esc(m.motivo)}</span><b>${fmtN(m.n)}</b></div>`).join("") || `<span style="font-size:.82rem;color:#5b6b7a">Sin ausencias registradas.</span>`}</div>`;
  }

  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest("#rp-root .rp-filtros button, #rp-feed-card .rp-filtros button");
    if (!b || !datos) return;
    b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    if (b.dataset.f) { filtro = b.dataset.f; feed(); }
    if (b.dataset.p) { periodo = b.dataset.p; porDoctora(); }
  });

  // Gráfico "Evaluaciones por período": si no hay evaluaciones en el rango, mostrar un aviso en vez de ejes vacíos
  function revisarPeriodoVacio() {
    const cv = $("coordLineChart"), av = $("coord-periodo-vacio");
    if (!cv || !av || !window.Chart || !Chart.getChart) return;
    const ch = Chart.getChart(cv);
    if (!ch) return;
    const total = ch.data.datasets.reduce((s, d) => s + (d.data || []).reduce((a, v) => a + (+v || 0), 0), 0);
    if (total > 0) { av.style.display = "none"; return; }
    const evs = (datos && datos.eventos || []).filter((e) => e.tipo === "evaluacion");
    const ult = evs.length ? evs[0].fecha : null;
    av.innerHTML = `<div><i class="fa-solid fa-mug-hot"></i><b>Sin evaluaciones en este período</b>
      <span>${ult ? `La última evaluación cerrada fue el ${new Date(ult + "T12:00").toLocaleDateString("es-CL", { day: "numeric", month: "long", year: "numeric" })}.` : "Cuando se cierren evaluaciones aparecerán aquí."} Revisa el calendario de actividad más abajo.</span></div>`;
    av.style.display = "flex";
  }
  let revisiones = 0;
  const vigilante = setInterval(() => { revisarPeriodoVacio(); if (++revisiones > 30) clearInterval(vigilante); }, 1000);
  document.addEventListener("click", (ev) => { if (ev.target.closest && ev.target.closest("#btn-periodo-dia, #btn-periodo-semana")) setTimeout(revisarPeriodoVacio, 400); });

  // ── Avance por establecimiento (datos de /api/coordinadora/stats que ya cargó el panel) ──
  let estUltimo = null, estFiltro = "todos";
  const estColor = (p) => (p >= 100 ? "#16a34a" : p >= 80 ? "#22c55e" : p >= 50 ? "#f59e0b" : p > 0 ? "#ef4444" : "#94a3b8");
  function datosCoord() { try { return typeof _coordData !== "undefined" ? _coordData : null; } catch (e) { return null; } }
  function pintarEst() {
    const d = datosCoord(), lista = $("rp-est-lista");
    if (!lista || !d || !Array.isArray(d.establecimientos)) return;
    const est = d.establecimientos.map((e) => ({ ...e, pend: Math.max(0, (e.total || 0) - (e.completed || 0)) }));
    const completos = est.filter((e) => e.total > 0 && e.completed >= e.total).length;
    const sinIniciar = est.filter((e) => !e.completed).length;
    const enCurso = est.length - completos - sinIniciar;
    const chip = (k, lab, n, col) => `<button type="button" class="rp-chip${estFiltro === k ? " on" : ""}" data-est="${k}">${col ? `<i style="background:${col}"></i>` : ""}${lab} <b>${fmtN(n)}</b></button>`;
    $("rp-est-resumen").innerHTML = chip("todos", "Todos", est.length) + chip("curso", "En curso", enCurso, "#f59e0b") + chip("completos", "Completos", completos, "#16a34a") + chip("sin", "Sin iniciar", sinIniciar, "#94a3b8");
    const q = ($("rp-est-q").value || "").trim().toLowerCase();
    let vis = est.filter((e) => (!q || (e.nombre || "").toLowerCase().includes(q)) &&
      (estFiltro === "todos" || (estFiltro === "completos" && e.total > 0 && e.completed >= e.total) || (estFiltro === "sin" && !e.completed) ||
       (estFiltro === "curso" && e.completed > 0 && e.completed < e.total)));
    const orden = $("rp-est-orden").value;
    vis.sort((a, b) => orden === "mayor" ? b.percent - a.percent : orden === "pend" ? b.pend - a.pend : orden === "az" ? (a.nombre || "").localeCompare(b.nombre || "", "es") : a.percent - b.percent);
    $("rp-est-sub").textContent = `${fmtN(est.length)} establecimientos · ${fmtN(est.reduce((s, e) => s + e.pend, 0))} evaluaciones pendientes en total`;
    if (!vis.length) { lista.innerHTML = `<div class="rp-load" style="grid-column:1/-1">No hay establecimientos con este filtro.</div>`; return; }
    lista.innerHTML = vis.map((e, i) => {
      const c = estColor(e.percent);
      return `<div class="rp-est" style="animation-delay:${Math.min(i, 20) * 25}ms">
        <span class="logo" style="background:linear-gradient(135deg,${colorDe(e.nombre)},#0f3460)">${esc(ini(e.nombre))}</span>
        <div style="flex:1;min-width:0"><div class="nom" title="${esc(e.nombre)}">${esc(e.nombre)}</div>
          <div class="det">${fmtN(e.completed)} de ${fmtN(e.total)} evaluados · ${e.pend ? `<b style="color:#b45309">${fmtN(e.pend)} pendientes</b>` : `<b style="color:#15803d">completo</b>`}</div>
          <div class="bar"><span style="width:${Math.min(100, e.percent)}%;background:${c}"></span></div></div>
        <span class="pct" style="color:${c}">${String(e.percent).replace(".", ",")}%</span></div>`;
    }).join("");
  }
  setInterval(() => { const d = datosCoord(); if (d && d !== estUltimo) { estUltimo = d; pintarEst(); } }, 700);
  document.addEventListener("input", (ev) => { if (ev.target && ev.target.id === "rp-est-q") pintarEst(); });
  document.addEventListener("change", (ev) => { if (ev.target && ev.target.id === "rp-est-orden") pintarEst(); });
  document.addEventListener("click", (ev) => { const c = ev.target.closest && ev.target.closest("#rp-est-resumen .rp-chip"); if (c) { estFiltro = c.dataset.est; pintarEst(); } });

  function visible() { const r = $("rp-root"); return r && r.offsetParent !== null; }
  function iniciar() {
    if (!$("rp-root")) return;
    cargar();
    clearInterval(timer);
    timer = setInterval(() => { if (visible() && !document.hidden) cargar(); }, 60000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
  window.RP = { recargar: cargar };
})();
