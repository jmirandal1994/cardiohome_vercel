/* ═══ Módulo Salud de estudiantes · historial, nutrición y reevaluaciones ═══
   Todo es de solo lectura. Usa las rutas /api/salud/*.
   Se usa en dos lugares:
     1) Sección "Salud y Reevaluaciones" del panel (admin, coordinadora, doctora): SE.init()
     2) Botón "Historial" en los formularios de la doctora: SE.abrirHistorialModal(rut, nombre)
*/
(function () {
  "use strict";
  const SE = {};
  window.SE = SE;

  // ───────── utilidades ─────────
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (n, d = 0) => (n == null || isNaN(n) ? "—" : Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const fmtF = (iso) => { if (!iso) return "—"; const [y, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${y}`; };
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const fmtMes = (ym) => { const [y, m] = ym.split("-"); return `${MESES[+m - 1]} ${y.slice(2)}`; };
  const fmtRut = (r) => {
    const n = String(r || "").toUpperCase().replace(/[^0-9K]/g, "");
    if (n.length < 2) return r || "—";
    const c = n.slice(0, -1).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return `${c}-${n.slice(-1)}`;
  };
  const iniciales = (n) => (n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  async function api(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    let j = {};
    try { j = await r.json(); } catch (e) { /* respuesta no JSON */ }
    if (!r.ok || j.success === false) throw new Error(j.message || `Error ${r.status}`);
    return j;
  }
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Cuenta de 0 al valor final en los números grandes (.val) y hace aparecer las tarjetas en cascada
  function animar(cont) {
    if (!cont) return;
    cont.querySelectorAll(".se-card, .se-help").forEach((el, i) => { el.classList.add("se-in"); el.style.animationDelay = `${Math.min(i, 14) * 45}ms`; });
    if (reduceMotion) return;
    cont.querySelectorAll(".val").forEach((el) => {
      const txt = el.textContent.trim();
      const m = txt.match(/^([\d.]+)(,\d+)?(%?)$/);
      if (!m) return;
      const fin = parseFloat(m[1].replace(/\./g, "") + (m[2] ? "." + m[2].slice(1) : ""));
      const dec = m[2] ? m[2].length - 1 : 0, suf = m[3] || "";
      if (!isFinite(fin) || fin === 0) return;
      const t0 = performance.now(), dur = 900;
      const paso = (t) => {
        const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        el.textContent = fmtN(fin * e, dec) + suf;
        if (k < 1) requestAnimationFrame(paso); else el.textContent = txt;
      };
      requestAnimationFrame(paso);
    });
  }
  const loading = (txt = "Cargando…") => `<div class="se-load"><span class="se-spin"></span>${esc(txt)}</div>`;
  const empty = (txt, icon = "fa-circle-info") => `<div class="se-empty"><i class="fa-solid ${icon}"></i>${txt}</div>`;
  function ensureChart() {
    if (window.Chart) return Promise.resolve();
    return new Promise((ok, ko) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js";
      s.onload = ok; s.onerror = ko; document.head.appendChild(s);
    });
  }
  const charts = {};
  function chart(id, cfg) {
    const el = document.getElementById(id);
    if (!el || !window.Chart) return;
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(el.getContext("2d"), cfg);
  }

  // Colores de clasificación nutricional y de estado de reevaluación
  const CLAS = {
    "Bajo peso": { fg: "#2563eb", bg: "#e0ecff" },
    "Normal": { fg: "#16a34a", bg: "#dcfce7" },
    "Sobrepeso": { fg: "#d97706", bg: "#fef3c7" },
    "Obesidad": { fg: "#dc2626", bg: "#fee2e2" },
    "Sin clasificar": { fg: "#64748b", bg: "#eef2f6" },
    "Menor de 2 años": { fg: "#7c3aed", bg: "#ede9fe" },
  };
  const EST = {
    vencida: { lab: "Vencida", fg: "#dc2626", bg: "#fee2e2", icon: "fa-triangle-exclamation", hint: "ya pasó la fecha" },
    urgente: { lab: "Próximos 30 días", fg: "#ea580c", bg: "#ffedd5", icon: "fa-bell", hint: "agendar ya" },
    proxima: { lab: "En 31 a 90 días", fg: "#d97706", bg: "#fef3c7", icon: "fa-clock", hint: "planificar operativo" },
    este_anio: { lab: "Dentro de 12 meses", fg: "#1c67a3", bg: "#e0ecff", icon: "fa-calendar", hint: "presupuestar" },
    en_plazo: { lab: "Al día", fg: "#16a34a", bg: "#dcfce7", icon: "fa-circle-check", hint: "más de 12 meses" },
    fecha_a_revisar: { lab: "Fecha a revisar", fg: "#7c3aed", bg: "#ede9fe", icon: "fa-pen-to-square", hint: "fecha mal escrita" },
    sin_fecha: { lab: "Sin fecha", fg: "#64748b", bg: "#eef2f6", icon: "fa-calendar-xmark", hint: "no se indicó" },
    cumplida: { lab: "Cumplida", fg: "#64748b", bg: "#eef2f6", icon: "fa-check", hint: "se reevaluó después" },
  };
  const chipClas = (c) => (c ? `<span class="se-chip dot" style="--fg:${(CLAS[c] || CLAS["Sin clasificar"]).fg};--bg:${(CLAS[c] || CLAS["Sin clasificar"]).bg}">${esc(c)}</span>` : "");
  const chipEst = (e) => { const s = EST[e] || EST.sin_fecha; return `<span class="se-chip" style="--fg:${s.fg};--bg:${s.bg}"><i class="fa-solid ${s.icon}"></i>${s.lab}</span>`; };
  function textoDias(d, est) {
    if (est === "cumplida") return "Reevaluación ya realizada";
    if (est === "fecha_a_revisar") return "La fecha ingresada no es válida";
    if (d == null) return "Sin fecha de reevaluación";
    if (d < 0) return `Venció hace ${fmtN(-d)} día${-d === 1 ? "" : "s"}`;
    if (d === 0) return "Vence hoy";
    if (d < 60) return `Faltan ${d} día${d === 1 ? "" : "s"}`;
    const m = Math.round(d / 30.4);
    return `Faltan ${fmtN(d)} días (≈ ${m} ${m === 1 ? "mes" : "meses"})`;
  }
  const barra = (pct, est) => (pct == null ? "" : `<div class="se-bar" title="${pct}% del plazo transcurrido"><span style="width:${pct}%;--fg:${(EST[est] || EST.en_plazo).fg}"></span></div>`);

  // ───────── HISTORIAL (compartido entre panel y modal) ─────────
  function htmlHistorial(j, prefijo) {
    const est = j.estudiante || {};
    const evs = j.evaluaciones || [];
    const hechas = evs.filter((e) => e.evaluado);
    const conMedidas = hechas.filter((e) => e.peso != null || e.altura != null || e.imc != null);
    const pendientes = hechas.filter((e) => e.estado_reevaluacion !== "cumplida");
    const prox = pendientes.filter((e) => e.fecha_reevaluacion && e.dias_para_reevaluar != null).sort((a, b) => a.dias_para_reevaluar - b.dias_para_reevaluar)[0];
    const ultima = conMedidas[conMedidas.length - 1];
    const sexo = (est.sexo || "").toUpperCase().startsWith("F") ? "Femenino" : (est.sexo || "").toUpperCase().startsWith("M") ? "Masculino" : "—";
    const edadAct = ultima && ultima.edad_anios != null ? `${ultima.edad_anios} años` : (hechas.length && hechas[hechas.length - 1].edad) || "—";
    const anios = [...new Set(hechas.map((e) => e.anio).filter(Boolean))];

    let h = `<div class="se-card se-ficha" style="margin-bottom:12px">
      <div class="who"><div class="se-avatar">${esc(iniciales(est.nombre))}</div>
        <div><div class="nm">${esc(est.nombre || "Estudiante")}</div>
        <div class="meta">RUT ${esc(fmtRut(est.rut))} · ${esc(sexo)} · ${esc(edadAct)} · ${hechas.length} evaluación${hechas.length === 1 ? "" : "es"} ${anios.length ? `(${anios.join(", ")})` : ""}</div></div></div>
      <div class="se-countdown">${prox ? `<div class="t"><span>Próxima reevaluación · ${esc(prox.especialidad)}</span><span style="color:${EST[prox.estado_reevaluacion].fg}">${fmtF(prox.fecha_reevaluacion)}</span></div>
        ${barra(prox.progreso_reevaluacion, prox.estado_reevaluacion)}
        <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:.78rem"><span>${chipEst(prox.estado_reevaluacion)}</span><b style="color:${EST[prox.estado_reevaluacion].fg}">${textoDias(prox.dias_para_reevaluar, prox.estado_reevaluacion)}</b></div>`
        : `<div class="t"><span>Próxima reevaluación</span></div><div style="font-size:.82rem;color:#5b6b7a">No hay una fecha de reevaluación registrada.</div>`}</div>
    </div>`;

    if (conMedidas.length) {
      h += `<div class="se-grid se-g3" style="margin-bottom:12px">
        <div class="se-card"><h4>Peso</h4><p class="se-cap">kilogramos por evaluación</p><div class="se-chart sm"><canvas id="${prefijo}-peso"></canvas></div></div>
        <div class="se-card"><h4>Talla</h4><p class="se-cap">centímetros por evaluación</p><div class="se-chart sm"><canvas id="${prefijo}-talla"></canvas></div></div>
        <div class="se-card"><h4>IMC</h4><p class="se-cap">kg/m² · el color indica la clasificación</p><div class="se-chart sm"><canvas id="${prefijo}-imc"></canvas></div></div>
      </div>`;
      if (conMedidas.length === 1) {
        h += `<div class="se-help"><i class="fa-solid fa-seedling"></i><div>Por ahora hay <b>una sola medición</b> de peso y talla. Desde la próxima evaluación verás aquí cómo cambia su crecimiento año tras año.</div></div>`;
      }
    } else if (hechas.length) {
      h += `<div class="se-help"><i class="fa-solid fa-circle-info"></i><div>Las evaluaciones de este estudiante no tienen peso ni talla registrados (por ejemplo, neurología no los mide).</div></div>`;
    }

    if (!hechas.length) {
      h += empty("Este estudiante aún no tiene evaluaciones realizadas.", "fa-user-clock");
      return h;
    }
    h += `<div class="se-card"><h4>Línea de tiempo</h4><p class="se-cap">De la más reciente a la más antigua. Cada tarjeta es una evaluación.</p><div class="se-timeline">`;
    const ordenadas = [...hechas].reverse();
    ordenadas.forEach((e, i) => {
      const prev = ordenadas.slice(i + 1).find((p) => p.especialidad === e.especialidad && (p.peso != null || p.altura != null));
      const delta = (a, b, u, d = 1) => {
        if (a == null || b == null) return "";
        const x = a - b;
        if (Math.abs(x) < 0.05) return `<span class="se-delta" style="color:#64748b">=</span>`;
        return `<span class="se-delta" style="color:${x > 0 ? "#0f766e" : "#b45309"}">${x > 0 ? "▲" : "▼"} ${fmtN(Math.abs(x), d)}${u}</span>`;
      };
      const color = (CLAS[e.clasificacion] || {}).fg || "#1c67a3";
      h += `<div class="se-ev" style="--fg:${color}"><div class="se-card">
        <div class="hd"><div><span class="fecha">${fmtF(e.fecha)}</span> · <span class="se-chip" style="--bg:${e.especialidad === "Neurología" ? "#ede9fe" : "#e0ecff"};--fg:${e.especialidad === "Neurología" ? "#6d28d9" : "#1c67a3"}">${esc(e.especialidad)}</span></div>
          <div style="font-size:.8rem;color:#5b6b7a">${esc(e.colegio || "")}${e.profesional ? " · " + esc(e.profesional) : ""}</div></div>
        ${e.peso != null || e.altura != null || e.imc != null ? `<div class="med">
          <div class="se-med">Peso<b>${fmtN(e.peso, 1)} kg${delta(e.peso, prev && prev.peso, " kg")}</b></div>
          <div class="se-med">Talla<b>${fmtN(e.altura, 1)} cm${delta(e.altura, prev && prev.altura, " cm")}</b></div>
          <div class="se-med">IMC<b>${fmtN(e.imc, 1)}${delta(e.imc, prev && prev.imc, "")}</b></div>
          <div class="se-med">Clasificación<b style="font-size:.85rem;margin-top:3px">${chipClas(e.clasificacion) || "—"}</b></div>
          ${e.edad ? `<div class="se-med">Edad<b>${esc(e.edad)}</b></div>` : ""}
        </div>` : ""}
        ${(e.alertas_datos || []).length ? `<div class="se-warn"><i class="fa-solid fa-triangle-exclamation"></i> Revisar: ${esc(e.alertas_datos.join(", "))}</div>` : ""}
        ${e.diagnosticos && e.diagnosticos.length ? `<div class="se-kv"><span>Diagnóstico:</span> ${esc(e.diagnosticos.join(" · "))}</div>` : ""}
        ${e.derivaciones ? `<div class="se-kv"><span>Derivaciones:</span> ${esc(e.derivaciones)}</div>` : ""}
        ${e.indicaciones ? `<div class="se-kv"><span>Indicaciones:</span> ${esc(e.indicaciones)}</div>` : ""}
        <div class="se-kv" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px"><span>Reevaluación:</span> <b>${fmtF(e.fecha_reevaluacion)}</b> ${chipEst(e.estado_reevaluacion)}
          <span style="font-size:.78rem;color:${(EST[e.estado_reevaluacion] || EST.sin_fecha).fg};font-weight:700">${textoDias(e.dias_para_reevaluar, e.estado_reevaluacion)}</span></div>
      </div></div>`;
    });
    h += `</div></div>`;
    return h;
  }

  function graficosHistorial(j, prefijo) {
    const pts = (j.evaluaciones || []).filter((e) => e.evaluado && (e.peso != null || e.altura != null || e.imc != null));
    if (!pts.length) return;
    const labels = pts.map((e) => fmtF(e.fecha));
    const base = (data, color, unidad) => ({
      type: "line",
      data: { labels, datasets: [{ data, borderColor: color, backgroundColor: color, pointRadius: 5, pointHoverRadius: 7, tension: 0.25, spanGaps: true, borderWidth: 2.5 }] },
      options: {
        responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${fmtN(c.parsed.y, 1)} ${unidad}` } } },
        scales: { x: { grid: { display: false }, ticks: { font: { size: 10 } } }, y: { grid: { color: "#eef2f6" }, ticks: { font: { size: 10 } }, grace: "15%" } },
      },
    });
    ensureChart().then(() => {
      chart(`${prefijo}-peso`, base(pts.map((e) => e.peso), "#1c67a3", "kg"));
      chart(`${prefijo}-talla`, base(pts.map((e) => e.altura), "#0f766e", "cm"));
      const cfg = base(pts.map((e) => e.imc), "#0f3460", "kg/m²");
      cfg.data.datasets[0].pointBackgroundColor = pts.map((e) => (CLAS[e.clasificacion] || CLAS["Sin clasificar"]).fg);
      cfg.data.datasets[0].pointBorderColor = cfg.data.datasets[0].pointBackgroundColor;
      cfg.options.plugins.tooltip.callbacks.afterLabel = (c) => pts[c.dataIndex].clasificacion || "";
      chart(`${prefijo}-imc`, cfg);
    }).catch(() => {});
  }

  async function cargarHistorial(rut, cont, prefijo) {
    cont.innerHTML = loading("Cargando historial…");
    try {
      const j = await api(`/api/salud/historial?rut=${encodeURIComponent(rut)}`);
      cont.innerHTML = htmlHistorial(j, prefijo);
      animar(cont);
      graficosHistorial(j, prefijo);
    } catch (e) {
      cont.innerHTML = empty(esc(e.message), "fa-lock");
    }
  }

  // Modal para la doctora (formularios)
  SE.abrirHistorialModal = function (rut, nombre) {
    let bg = document.getElementById("se-modal-bg");
    if (!bg) {
      bg = document.createElement("div");
      bg.id = "se-modal-bg";
      bg.className = "se-modal-bg se-wrap";
      bg.innerHTML = `<div class="se-modal" role="dialog" aria-modal="true"><div class="top"><h3><i class="fa-solid fa-clock-rotate-left"></i> <span id="se-modal-tit">Historial</span></h3>
        <button type="button" class="se-x" aria-label="Cerrar" onclick="SE.cerrarModal()"><i class="fa-solid fa-xmark"></i></button></div><div id="se-modal-body"></div></div>`;
      bg.addEventListener("click", (ev) => { if (ev.target === bg) SE.cerrarModal(); });
      document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") SE.cerrarModal(); });
      document.body.appendChild(bg);
    }
    document.getElementById("se-modal-tit").textContent = `Historial de ${nombre || "estudiante"}`;
    bg.classList.add("on");
    document.body.style.overflow = "hidden";
    cargarHistorial(rut, document.getElementById("se-modal-body"), "se-m");
  };
  SE.cerrarModal = function () {
    const bg = document.getElementById("se-modal-bg");
    if (bg) bg.classList.remove("on");
    document.body.style.overflow = "";
  };
  SE.histBtn = function (btn) { SE.abrirHistorialModal(btn.dataset.rut, btn.dataset.nombre); };

  // ───────── SECCIÓN DEL PANEL ─────────
  let iniciado = false;
  const estado = { tab: "reev", filtroEst: null, buscaReev: "", pag: 0, reev: null, nutri: null, deriv: null };
  const $ = (id) => document.getElementById(id);
  const qsFiltros = () => {
    const p = new URLSearchParams();
    if ($("se-f-proy") && $("se-f-proy").value) p.set("proyecto_id", $("se-f-proy").value);
    if ($("se-f-col") && $("se-f-col").value) p.set("colegio", $("se-f-col").value);
    return p;
  };

  SE.init = async function () {
    const raiz = $("se-root");
    if (!raiz) return;
    if (!iniciado) {
      iniciado = true;
      raiz.querySelectorAll(".se-tab").forEach((b) => b.addEventListener("click", () => SE.tab(b.dataset.tab)));
      $("se-buscar").addEventListener("input", debounce(buscar, 350));
      ["se-f-proy", "se-f-col"].forEach((id) => $(id).addEventListener("change", () => { estado.reev = null; estado.nutri = null; estado.deriv = null; SE.tab(estado.tab); }));
      $("se-f-anio").addEventListener("change", () => { estado.nutri = null; SE.tab("nutri"); });
      try {
        const f = await api("/api/salud/filtros");
        $("se-f-proy").innerHTML = `<option value="">Todos los proyectos</option>` + f.proyectos.map((p) => `<option value="${esc(p.id)}">${esc(p.nombre)}</option>`).join("");
        $("se-f-col").innerHTML = `<option value="">Todos los colegios</option>` + f.colegios.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
      } catch (e) { /* los filtros son opcionales */ }
    }
    SE.tab(estado.tab);
  };

  SE.tab = function (t) {
    estado.tab = t;
    document.querySelectorAll("#se-root .se-tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
    document.querySelectorAll("#se-root .se-panel").forEach((p) => p.classList.toggle("on", p.id === `se-p-${t}`));
    $("se-f-anio").style.display = t === "nutri" ? "" : "none";
    if (t === "reev") cargarReev();
    if (t === "nutri") cargarNutri();
    if (t === "deriv") cargarDeriv();
  };

  // ── Descarga de reportes ──
  SE.descargar = function (tipo) {
    const p = qsFiltros();
    p.set("tipo", tipo);
    if ($("se-f-anio") && $("se-f-anio").value) p.set("anio", $("se-f-anio").value);
    const btn = $("se-dl-btn");
    const txt = btn ? btn.innerHTML : "";
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="se-spin" style="width:14px;height:14px;border-width:2px"></span> Generando…'; }
    fetch(`/api/salud/reporte?${p}`, { credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) { let m = "No se pudo generar el reporte"; try { m = (await r.json()).message || m; } catch (e) { /* */ } throw new Error(m); }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const nombre = (cd.match(/filename="([^"]+)"/) || [])[1] || `Reporte_salud_${tipo}.xlsx`;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = nombre; document.body.appendChild(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
      })
      .catch((e) => alertaSuave(e.message))
      .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = txt; } SE.menuDescarga(false); });
  };
  SE.menuDescarga = function (abrir) {
    const m = $("se-dl-menu");
    if (!m) return;
    m.classList.toggle("on", abrir === undefined ? !m.classList.contains("on") : abrir);
  };
  SE.imprimir = function () { SE.menuDescarga(false); document.body.classList.add("se-print"); setTimeout(() => { window.print(); document.body.classList.remove("se-print"); }, 120); };
  function alertaSuave(msg) {
    let t = $("se-toast");
    if (!t) { t = document.createElement("div"); t.id = "se-toast"; t.className = "se-toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 4000);
  }
  document.addEventListener("click", (ev) => { if (!ev.target.closest || !ev.target.closest(".se-dl")) SE.menuDescarga(false); });

  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  async function buscar() {
    const q = $("se-buscar").value.trim();
    const out = $("se-resultados");
    if (q.length < 3) { out.innerHTML = ""; return; }
    out.innerHTML = loading("Buscando…");
    try {
      const j = await api(`/api/salud/buscar?q=${encodeURIComponent(q)}`);
      if (!j.resultados.length) { out.innerHTML = empty("No encontramos estudiantes con ese RUT o nombre en tus nóminas.", "fa-magnifying-glass"); return; }
      out.innerHTML = `<div class="se-res">${j.resultados.map((r) => `<div class="se-res-it" data-rut="${esc(r.rut)}">
        <div><div class="n">${esc(r.nombre)}</div><div class="m">RUT ${esc(fmtRut(r.rut))} · ${esc(r.colegios.join(", ") || "—")}</div></div>
        <span class="se-chip">${r.evaluaciones} evaluación${r.evaluaciones === 1 ? "" : "es"}</span></div>`).join("")}</div>`;
      out.querySelectorAll(".se-res-it").forEach((el) => el.addEventListener("click", () => SE.verEstudiante(el.dataset.rut)));
    } catch (e) { out.innerHTML = empty(esc(e.message), "fa-circle-exclamation"); }
  }

  SE.verEstudiante = function (rut) {
    SE.tab("hist");
    $("se-resultados").innerHTML = `<button type="button" class="se-btn" onclick="SE.volverBusqueda()"><i class="fa-solid fa-arrow-left"></i> Volver a la búsqueda</button>`;
    cargarHistorial(rut, $("se-ficha"), "se-h");
    $("se-ficha").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  SE.volverBusqueda = function () { $("se-ficha").innerHTML = ""; buscar(); };

  // ── Reevaluaciones ──
  async function cargarReev() {
    const box = $("se-p-reev-body");
    if (estado.reev) return pintarReev();
    box.innerHTML = loading("Calculando fechas de reevaluación…");
    try {
      estado.reev = await api(`/api/salud/reevaluaciones?${qsFiltros()}`);
      estado.pag = 0;
      pintarReev();
    } catch (e) { box.innerHTML = empty(esc(e.message), "fa-circle-exclamation"); }
  }

  function pintarReev() {
    const j = estado.reev, c = j.conteo, box = $("se-p-reev-body");
    const orden = ["vencida", "urgente", "proxima", "este_anio", "en_plazo", "fecha_a_revisar"];
    let h = `<div class="se-help"><i class="fa-solid fa-calendar-check"></i><div>Cada estudiante tiene la <b>fecha de reevaluación que indicó su especialista</b>. El sistema cuenta los días que faltan <b>cada día de forma automática</b> (hoy es ${fmtF(j.hoy)}) y cambia el color del semáforo a medida que se acerca la fecha. Si un estudiante tiene varias evaluaciones, manda la más reciente de cada especialidad.</div></div>
      <div class="se-grid se-g6" style="margin-bottom:12px">${orden.map((k) => `<div class="se-card se-kpi click ${estado.filtroEst === k ? "sel" : ""}" style="--c:${EST[k].fg}" data-est="${k}">
        <div class="lab">${EST[k].lab}</div><div class="val" style="color:${EST[k].fg}">${fmtN(c[k])}</div><div class="hint">${EST[k].hint}</div></div>`).join("")}</div>
      <div class="se-grid se-g2" style="margin-bottom:12px">
        <div class="se-card"><h4>Reevaluaciones por mes</h4><p class="se-cap">cuántos estudiantes deben reevaluarse cada mes (próximos 36 meses)</p><div class="se-chart"><canvas id="se-c-meses"></canvas></div>
          <details class="se-que"><summary>¿Para qué sirve?</summary><p>Muestra en qué meses se concentran las reevaluaciones, para programar operativos y presupuesto con anticipación. Las barras rojas son meses que ya pasaron.</p></details></div>
        <div class="se-card"><h4>Estado general</h4><p class="se-cap">${fmtN(j.total_estudiantes)} estudiantes con evaluación (por especialidad)</p><div class="se-chart"><canvas id="se-c-estados"></canvas></div>
          <details class="se-que"><summary>¿Qué significa cada color?</summary><p><b>Rojo:</b> la fecha ya pasó. <b>Naranjo:</b> vence en 30 días o menos. <b>Amarillo:</b> entre 31 y 90 días. <b>Azul:</b> dentro de 12 meses. <b>Verde:</b> falta más de un año. <b>Morado:</b> la fecha está mal escrita (por ejemplo, año 0011) y debe corregirse.</p></details></div>
      </div>
      <div class="se-card"><div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px">
        <div><h4>Estudiantes que requieren atención</h4><p class="se-cap" style="margin:0">${estado.filtroEst ? `Filtrado: ${EST[estado.filtroEst].lab} · <a href="#" onclick="SE.filtroEst(null);return false">ver todos</a>` : "vencidas, próximas y fechas a revisar · haz clic en una tarjeta de arriba para filtrar"}</p></div>
        <input class="se-input" id="se-reev-q" placeholder="Filtrar por nombre, RUT o colegio" value="${esc(estado.buscaReev)}"></div>
        <div id="se-reev-tabla"></div></div>`;
    box.innerHTML = h;
    animar(box);
    box.querySelectorAll("[data-est]").forEach((el) => el.addEventListener("click", () => SE.filtroEst(el.dataset.est === estado.filtroEst ? null : el.dataset.est)));
    $("se-reev-q").addEventListener("input", debounce(() => { estado.buscaReev = $("se-reev-q").value; estado.pag = 0; tablaReev(); }, 250));
    tablaReev();
    ensureChart().then(() => {
      const hoyYM = j.hoy.slice(0, 7);
      const meses = j.por_mes.filter((m) => m.mes >= addMes(hoyYM, -6) && m.mes <= addMes(hoyYM, 36));
      chart("se-c-meses", { type: "bar", data: { labels: meses.map((m) => fmtMes(m.mes)), datasets: [{ data: meses.map((m) => m.n),
        backgroundColor: meses.map((m) => (m.mes < hoyYM ? "#dc2626" : m.mes <= addMes(hoyYM, 3) ? "#ea580c" : m.mes <= addMes(hoyYM, 12) ? "#1c67a3" : "#86b7a0")), borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 60 } }, y: { grid: { color: "#eef2f6" }, ticks: { precision: 0 } } } } });
      const ks = ["vencida", "urgente", "proxima", "este_anio", "en_plazo", "fecha_a_revisar", "sin_fecha"].filter((k) => c[k]);
      chart("se-c-estados", { type: "doughnut", data: { labels: ks.map((k) => EST[k].lab), datasets: [{ data: ks.map((k) => c[k]), backgroundColor: ks.map((k) => EST[k].fg), borderWidth: 2, borderColor: "#fff" }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } } } } });
    }).catch(() => {});
  }
  function addMes(ym, n) { let [y, m] = ym.split("-").map(Number); m += n; y += Math.floor((m - 1) / 12); m = ((m - 1) % 12 + 12) % 12 + 1; return `${y}-${String(m).padStart(2, "0")}`; }
  SE.filtroEst = function (k) { estado.filtroEst = k; estado.pag = 0; pintarReev(); };

  function tablaReev() {
    const j = estado.reev, q = estado.buscaReev.trim().toLowerCase(), qr = q.replace(/[^0-9k]/g, "");
    let rows = j.lista.filter((r) => !estado.filtroEst || r.estado === estado.filtroEst);
    if (q) rows = rows.filter((r) => (r.nombre || "").toLowerCase().includes(q) || (r.colegio || "").toLowerCase().includes(q) || (qr && String(r.rut || "").toLowerCase().replace(/[^0-9k]/g, "").includes(qr)));
    const t = $("se-reev-tabla");
    if (estado.filtroEst === "en_plazo") { t.innerHTML = empty(`Hay ${fmtN(j.conteo.en_plazo)} estudiantes al día (falta más de un año). No requieren acción por ahora.`, "fa-circle-check"); return; }
    if (!rows.length) { t.innerHTML = empty("No hay estudiantes en esta categoría. ¡Todo en orden!", "fa-circle-check"); return; }
    const P = 50, pags = Math.ceil(rows.length / P), pg = Math.min(estado.pag, pags - 1), vis = rows.slice(pg * P, pg * P + P);
    t.innerHTML = `<div class="se-tw"><table class="se-table"><thead><tr><th>Estudiante</th><th>Colegio</th><th>Especialidad</th><th>Evaluado</th><th>Reevaluar</th><th>Estado</th><th>Plazo</th></tr></thead><tbody>
      ${vis.map((r) => `<tr class="link" data-rut="${esc(r.rut)}"><td><b>${esc(r.nombre)}</b><div style="font-size:.74rem;color:#5b6b7a">${esc(fmtRut(r.rut))}</div></td>
        <td>${esc(r.colegio || "—")}</td><td>${esc(r.especialidad)}</td><td>${fmtF(r.fecha_evaluacion)}</td><td><b>${fmtF(r.fecha_reevaluacion)}</b></td>
        <td>${chipEst(r.estado)}<div style="font-size:.74rem;font-weight:700;margin-top:3px;color:${EST[r.estado].fg}">${textoDias(r.dias, r.estado)}</div></td><td>${barra(r.progreso, r.estado)}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="se-pag">${fmtN(rows.length)} estudiantes${j.lista_total > j.lista.length ? ` (se muestran los primeros ${fmtN(j.lista.length)})` : ""} · página ${pg + 1} de ${pags}
        <button class="se-btn" ${pg === 0 ? "disabled" : ""} onclick="SE.pagina(-1)">‹</button><button class="se-btn" ${pg >= pags - 1 ? "disabled" : ""} onclick="SE.pagina(1)">›</button></div>`;
    t.querySelectorAll("tr.link").forEach((tr) => tr.addEventListener("click", () => SE.verEstudiante(tr.dataset.rut)));
  }
  SE.pagina = function (d) { estado.pag = Math.max(0, estado.pag + d); tablaReev(); };

  // ── Nutrición ──
  async function cargarNutri() {
    const box = $("se-p-nutri-body");
    if (estado.nutri) return pintarNutri();
    box.innerHTML = loading("Calculando estadísticas de peso, talla e IMC…");
    try {
      const p = qsFiltros();
      if ($("se-f-anio").value) p.set("anio", $("se-f-anio").value);
      estado.nutri = await api(`/api/salud/nutricion?${p}`);
      const sel = $("se-f-anio");
      const actual = String(estado.nutri.anio);
      sel.innerHTML = (estado.nutri.anios || []).map((a) => `<option value="${a}" ${String(a) === actual ? "selected" : ""}>Año ${a}</option>`).join("") || `<option value="">Año</option>`;
      pintarNutri();
    } catch (e) { box.innerHTML = empty(esc(e.message), "fa-circle-exclamation"); }
  }

  function pintarNutri() {
    const j = estado.nutri, d = j.distribucion, tot = j.clasificados || 0, box = $("se-p-nutri-body");
    const pct = (n) => (tot ? Math.round((100 * n) / tot) : 0);
    if (!tot) { box.innerHTML = empty(`No hay mediciones de peso y talla para ${j.anio}.`, "fa-weight-scale"); return; }
    let h = `<div class="se-help"><i class="fa-solid fa-child-reaching"></i><div>Resumen de <b>${fmtN(tot)} estudiantes medidos en ${j.anio}</b> (una medición por estudiante). La clasificación es la que registró la doctora en el formulario, según las curvas de IMC para la edad y el sexo.</div></div>
      <div class="se-grid se-g4" style="margin-bottom:12px">
        <div class="se-card se-kpi" style="--c:#16a34a"><div class="lab">Peso normal</div><div class="val" style="color:#16a34a">${pct(d.Normal)}%</div><div class="hint">${fmtN(d.Normal)} estudiantes</div></div>
        <div class="se-card se-kpi" style="--c:#d97706"><div class="lab">Sobrepeso</div><div class="val" style="color:#d97706">${pct(d.Sobrepeso)}%</div><div class="hint">${fmtN(d.Sobrepeso)} estudiantes</div></div>
        <div class="se-card se-kpi" style="--c:#dc2626"><div class="lab">Obesidad</div><div class="val" style="color:#dc2626">${pct(d.Obesidad)}%</div><div class="hint">${fmtN(d.Obesidad)} estudiantes</div></div>
        <div class="se-card se-kpi" style="--c:#2563eb"><div class="lab">Bajo peso</div><div class="val" style="color:#2563eb">${pct(d["Bajo peso"])}%</div><div class="hint">${fmtN(d["Bajo peso"])} estudiantes</div></div>
      </div>
      <div class="se-grid se-g2" style="margin-bottom:12px">
        <div class="se-card"><h4>Estado nutricional</h4><p class="se-cap">${j.exceso_pct != null ? `<b style="color:#dc2626">${fmtN(j.exceso_pct, 1)}%</b> tiene exceso de peso (sobrepeso + obesidad)` : ""}</p><div class="se-chart"><canvas id="se-c-dist"></canvas></div>
          <details class="se-que"><summary>¿Qué es el IMC?</summary><p>El Índice de Masa Corporal es el peso (kg) dividido por la talla (m) al cuadrado. En niños y adolescentes no se usa un número fijo: se compara con otros niños de su misma edad y sexo (percentiles). Por eso un mismo IMC puede ser normal a los 15 años y sobrepeso a los 8.</p></details></div>
        <div class="se-card"><h4>IMC promedio por edad</h4><p class="se-cap">niñas y niños por separado</p><div class="se-chart"><canvas id="se-c-edad"></canvas></div>
          <details class="se-que"><summary>¿Cómo leerlo?</summary><p>Es normal que el IMC promedio suba con la edad. Lo que conviene mirar es si en alguna edad el promedio sube más de lo esperado, porque ahí se concentra el exceso de peso.</p></details></div>
      </div>
      <div class="se-grid se-g2" style="margin-bottom:12px">
        <div class="se-card"><h4>Talla promedio por edad</h4><p class="se-cap">centímetros</p><div class="se-chart sm"><canvas id="se-c-talla"></canvas></div></div>
        <div class="se-card"><h4>Peso promedio por edad</h4><p class="se-cap">kilogramos</p><div class="se-chart sm"><canvas id="se-c-pesoedad"></canvas></div></div>
      </div>
      <div class="se-card" style="margin-bottom:12px"><h4>Colegios con más exceso de peso</h4><p class="se-cap">% de estudiantes con sobrepeso u obesidad · colegios con 10 o más medidos</p><div class="se-chart" style="height:${Math.max(220, Math.min(15, j.colegios.filter((x) => x.total >= 10).length) * 26 + 40)}px"><canvas id="se-c-col"></canvas></div></div>`;
    if ((j.por_anio || []).length > 1) {
      h += `<div class="se-card" style="margin-bottom:12px"><h4>Evolución año a año</h4><p class="se-cap">% de cada clasificación por año de evaluación</p><div class="se-chart sm"><canvas id="se-c-anios"></canvas></div></div>`;
    } else {
      h += `<div class="se-help"><i class="fa-solid fa-chart-line"></i><div>La <b>comparación año a año</b> aparecerá automáticamente cuando haya evaluaciones de más de un año.</div></div>`;
    }
    h += `<div class="se-card"><h4><i class="fa-solid fa-triangle-exclamation" style="color:#ea580c"></i> Datos a revisar (${fmtN(j.a_revisar_total)})</h4><p class="se-cap">mediciones que parecen mal escritas; no se cuentan en los gráficos. Se pueden corregir con el editor de corrección.</p>
      ${j.a_revisar.length ? `<div class="se-tw"><table class="se-table"><thead><tr><th>Estudiante</th><th>Colegio</th><th>Talla</th><th>Peso</th><th>IMC</th><th>Problema</th></tr></thead><tbody>
      ${j.a_revisar.slice(0, estado.verRevisar ? 300 : 15).map((r) => `<tr class="link" data-rut="${esc(r.rut)}"><td><b>${esc(r.nombre)}</b><div style="font-size:.74rem;color:#5b6b7a">${esc(fmtRut(r.rut))}</div></td><td>${esc(r.colegio)}</td><td>${fmtN(r.altura, 2)}</td><td>${fmtN(r.peso, 1)}</td><td>${fmtN(r.imc, 1)}</td><td class="se-warn">${esc(r.problemas.join(", "))}</td></tr>`).join("")}
      </tbody></table></div>${j.a_revisar.length > 15 ? `<div class="se-pag"><button class="se-btn" onclick="SE.toggleRevisar()">${estado.verRevisar ? "Ver menos" : `Ver los ${fmtN(j.a_revisar.length)}`}</button></div>` : ""}` : empty("No encontramos mediciones sospechosas.", "fa-circle-check")}</div>`;
    box.innerHTML = h;
    animar(box);
    box.querySelectorAll("tr.link").forEach((tr) => tr.addEventListener("click", () => SE.verEstudiante(tr.dataset.rut)));
    ensureChart().then(() => {
      const ks = ["Normal", "Sobrepeso", "Obesidad", "Bajo peso"];
      chart("se-c-dist", { type: "doughnut", data: { labels: ks, datasets: [{ data: ks.map((k) => d[k]), backgroundColor: ks.map((k) => CLAS[k].fg), borderWidth: 2, borderColor: "#fff" }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: "60%", plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (c) => `${c.label}: ${fmtN(c.parsed)} (${pct(c.parsed)}%)` } } } } });
      const ed = j.por_edad.filter((e) => e.n >= 5);
      const lineas = (campo, unidad) => ({ type: "line", data: { labels: ed.map((e) => `${e.edad} a`), datasets: [
        { label: "Niñas", data: ed.map((e) => e[campo + "_F"]), borderColor: "#db2777", backgroundColor: "#db2777", tension: 0.3, pointRadius: 3, spanGaps: true },
        { label: "Niños", data: ed.map((e) => e[campo + "_M"]), borderColor: "#1c67a3", backgroundColor: "#1c67a3", tension: 0.3, pointRadius: 3, spanGaps: true }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtN(c.parsed.y, 1)} ${unidad}` } } },
          scales: { x: { grid: { display: false } }, y: { grid: { color: "#eef2f6" } } } } });
      chart("se-c-edad", lineas("imc", "kg/m²"));
      chart("se-c-talla", lineas("talla", "cm"));
      chart("se-c-pesoedad", lineas("peso", "kg"));
      const cols = j.colegios.filter((x) => x.total >= 10).slice(0, 15);
      chart("se-c-col", { type: "bar", data: { labels: cols.map((x) => x.colegio.length > 38 ? x.colegio.slice(0, 36) + "…" : x.colegio), datasets: [
        { label: "Sobrepeso", data: cols.map((x) => +(100 * x.Sobrepeso / Math.max(1, x.total)).toFixed(1)), backgroundColor: CLAS.Sobrepeso.fg },
        { label: "Obesidad", data: cols.map((x) => +(100 * x.Obesidad / Math.max(1, x.total)).toFixed(1)), backgroundColor: CLAS.Obesidad.fg }] },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.x}%` } } },
          scales: { x: { stacked: true, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: "#eef2f6" } }, y: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 } } } } } });
      if ((j.por_anio || []).length > 1) {
        const pa = j.por_anio;
        chart("se-c-anios", { type: "bar", data: { labels: pa.map((a) => String(a.anio)), datasets: ks.map((k) => ({ label: k, data: pa.map((a) => +(100 * a[k] / Math.max(1, a.total)).toFixed(1)), backgroundColor: CLAS[k].fg })) },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } }, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, max: 100, ticks: { callback: (v) => v + "%" } } } } });
      }
    }).catch(() => {});
  }

  SE.toggleRevisar = function () { estado.verRevisar = !estado.verRevisar; pintarNutri(); };

  // ── Derivaciones por especialidad ──
  const COL_ESP = ["#1c67a3", "#0f766e", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#ea580c", "#4f46e5", "#be123c", "#0d9488", "#a16207", "#6d28d9", "#15803d", "#9333ea", "#b91c1c", "#475569"];
  async function cargarDeriv() {
    const box = $("se-p-deriv-body");
    if (estado.deriv) return pintarDeriv();
    box.innerHTML = loading("Contando derivaciones por especialidad…");
    try { estado.deriv = await api(`/api/salud/derivaciones?${qsFiltros()}`); pintarDeriv(); }
    catch (e) { box.innerHTML = empty(esc(e.message), "fa-circle-exclamation"); }
  }
  function pintarDeriv() {
    const j = estado.deriv, box = $("se-p-deriv-body");
    if (!j.derivados) { box.innerHTML = empty("No hay derivaciones registradas con estos filtros.", "fa-share-from-square"); return; }
    const esps = j.especialidades, top = esps.slice(0, 4);
    const colEsp = {}; esps.forEach((e, i) => { colEsp[e.especialidad] = COL_ESP[i % COL_ESP.length]; });
    let h = `<div class="se-help"><i class="fa-solid fa-share-from-square"></i><div>De <b>${fmtN(j.evaluados)} estudiantes evaluados</b>, <b>${fmtN(j.derivados)} (${fmtN(j.derivados_pct, 1)}%)</b> fueron derivados a al menos una especialidad. Un estudiante derivado a dentista y oftalmólogo cuenta en ambas.</div></div>
      <div class="se-grid se-g4" style="margin-bottom:12px">${top.map((e) => `<div class="se-card se-kpi" style="--c:${colEsp[e.especialidad]}"><div class="lab">${esc(e.especialidad)}</div><div class="val" style="color:${colEsp[e.especialidad]}">${fmtN(e.estudiantes)}</div><div class="hint">${fmtN(e.pct, 1)}% de los evaluados</div></div>`).join("")}</div>
      <div class="se-grid se-g2" style="margin-bottom:12px">
        <div class="se-card"><h4>Estudiantes derivados por especialidad</h4><p class="se-cap">cantidad de estudiantes</p><div class="se-chart" style="height:${Math.max(250, esps.length * 26 + 40)}px"><canvas id="se-c-deriv"></canvas></div>
          <details class="se-que"><summary>¿Para qué sirve?</summary><p>Muestra qué especialistas se necesitan más. Sirve para coordinar operativos (por ejemplo, oftalmología o dental) y para gestionar horas con la red de salud.</p></details></div>
        <div class="se-card"><h4>Según quién derivó</h4><p class="se-cap">medicina familiar y neurología</p><div class="se-chart" style="height:${Math.max(250, esps.length * 26 + 40)}px"><canvas id="se-c-origen"></canvas></div>
          <details class="se-que"><summary>¿Cómo leerlo?</summary><p>Medicina familiar deriva sobre todo a oftalmología, dental, nutrición y otorrino. Neurología suele recomendar apoyos como fonoaudiología, psicología o terapia ocupacional.</p></details></div>
      </div>
      <div class="se-card"><h4>Derivaciones por colegio</h4><p class="se-cap">estudiantes derivados a cada especialidad · ordenado por total</p>
        <div class="se-tw"><table class="se-table"><thead><tr><th>Colegio</th><th>Derivados</th>${esps.slice(0, 8).map((e) => `<th>${esc(e.especialidad)}</th>`).join("")}</tr></thead><tbody>
        ${j.colegios.slice(0, 25).map((c) => `<tr><td><b>${esc(c.colegio)}</b></td><td><b>${fmtN(c.derivados)}</b></td>${esps.slice(0, 8).map((e) => { const v = c[e.especialidad] || 0, mx = Math.max(1, c.derivados); return `<td><div style="display:flex;align-items:center;gap:6px"><span style="min-width:28px">${fmtN(v)}</span><div class="se-bar" style="min-width:50px;flex:1"><span style="width:${Math.round(100 * v / mx)}%;--fg:${colEsp[e.especialidad]}"></span></div></div></td>`; }).join("")}</tr>`).join("")}
        </tbody></table></div>${j.colegios.length > 25 ? `<div class="se-pag">Se muestran 25 de ${fmtN(j.colegios.length)} colegios. Descarga el reporte para ver todos.</div>` : ""}</div>`;
    box.innerHTML = h;
    animar(box);
    ensureChart().then(() => {
      chart("se-c-deriv", { type: "bar", data: { labels: esps.map((e) => e.especialidad), datasets: [{ data: esps.map((e) => e.estudiantes), backgroundColor: esps.map((e) => colEsp[e.especialidad]), borderRadius: 5 }] },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${fmtN(c.parsed.x)} estudiantes (${fmtN(esps[c.dataIndex].pct, 1)}%)` } } },
          scales: { x: { grid: { color: "#eef2f6" } }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } } } });
      const origenes = Object.keys(j.por_origen || {});
      const colO = { "Medicina familiar": "#1c67a3", "Neurología": "#7c3aed", "Otra": "#94a3b8" };
      chart("se-c-origen", { type: "bar", data: { labels: esps.map((e) => e.especialidad), datasets: origenes.map((o) => ({ label: o, data: esps.map((e) => (j.por_origen[o] || {})[e.especialidad] || 0), backgroundColor: colO[o] || "#94a3b8", borderRadius: 4 })) },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
          scales: { x: { stacked: true, grid: { color: "#eef2f6" } }, y: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } } } } });
    }).catch(() => {});
  }

  // Iniciar cuando se abre la sección desde el menú
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest && ev.target.closest('a[data-section="salud-estudiantes"]');
    if (a) setTimeout(SE.init, 60);
  });
})();
