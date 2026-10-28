/* ═══ Monitor de Doctoras: evaluaciones de hoy por doctora + bitácora de actividad ═══
   Lee /api/presencia/hoy y /api/bitacora. Se engancha a cargarPresencia() mediante
   window.presTrasCargar, que el monitor llama después de cada actualización. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (n) => Number(n || 0).toLocaleString("es-CL");
  const datos = () => { try { return typeof _presDatos !== "undefined" ? _presDatos : []; } catch (e) { return []; } };
  const fechaHora = (iso) => (typeof presFechaHora === "function" ? presFechaHora(iso) : new Date(iso).toLocaleString("es-CL"));
  const hora = (iso) => new Date(iso).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  function diaLargo(iso) {
    const d = new Date(String(iso).length <= 10 ? iso + "T12:00:00" : iso);
    const hoy = new Date(), ayer = new Date(); ayer.setDate(hoy.getDate() - 1);
    if (d.toDateString() === hoy.toDateString()) return "Hoy";
    if (d.toDateString() === ayer.toDateString()) return "Ayer";
    const t = d.toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long", year: d.getFullYear() !== hoy.getFullYear() ? "numeric" : undefined });
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  const ICONOS = {
    inicio_sesion: ["fa-right-to-bracket", "#dcfce7", "#15803d"],
    cierre_sesion: ["fa-right-from-bracket", "#eef2f6", "#475569"],
    inicio_fallido: ["fa-triangle-exclamation", "#fee2e2", "#b91c1c"],
    abrir_nomina: ["fa-folder-open", "#e0ecff", "#1c67a3"],
    evaluacion_cerrada: ["fa-circle-check", "#dcfce7", "#16a34a"],
    pdf_generado: ["fa-file-pdf", "#fee2e2", "#dc2626"],
    evaluacion_editada: ["fa-pen", "#fef3c7", "#b45309"],
    asistencia_cambiada: ["fa-user-slash", "#fce7f3", "#be185d"],
    correccion_solicitada: ["fa-pen-to-square", "#ede9fe", "#6d28d9"],
    correccion_resuelta: ["fa-check-double", "#ede9fe", "#6d28d9"],
    descarga: ["fa-download", "#e0f2fe", "#0369a1"],
  };
  const nombreDoc = (e) => {
    const d = datos().find((x) => String(x.doctora_id) === String(e.usuario_id));
    return (d && d.nombre) || e.nombre || "Usuario";
  };
  const subtitulo = (e) => [e.estudiante, e.colegio, e.detalle && e.detalle.archivo, e.detalle && e.detalle.estado].filter(Boolean).map(esc).join(" · ");

  // ── Evaluaciones de hoy en cada tarjeta ──
  let ultimaHoy = 0;
  async function avanceHoy() {
    try {
      const r = await fetch("/api/presencia/hoy", { credentials: "same-origin" });
      const j = await r.json();
      if (!r.ok || !j.success) return;
      const docs = j.doctoras || {};
      ultimoHoy = j;
      aplicarHoy(docs);
    } catch (e) { /* el monitor sigue funcionando sin este dato */ }
  }
  let ultimoHoy = null;
  function aplicarHoy(docs) {
    {
      datos().forEach((d) => {
        const x = docs[String(d.doctora_id)];
        d.hoy_eval = x ? x.hoy : 0;
        d.hoy_colegios = x ? x.colegios : [];
      });
      window._presHoyTotal = (ultimoHoy && ultimoHoy.total) || 0;
      if (typeof presRenderGrid === "function") presRenderGrid();
      const el = $("pres-hoy-eval");
      if (el) el.textContent = fmtN(window._presHoyTotal);
    }
  }

  // ── Actividad reciente del monitor con hora exacta, desde la bitácora ──
  async function feedHoy() {
    try {
      const r = await fetch("/api/bitacora?dias=2&limit=30", { credentials: "same-origin" });
      const j = await r.json();
      if (!r.ok || !j.success || !j.disponible || !(j.eventos || []).length) return;
      if (typeof _presFeedLog === "undefined") return;
      const evs = j.eventos.filter((e) => e.accion !== "descarga" || e.rol === "doctora").slice(0, 8).map((e) => {
        const ic = ICONOS[e.accion] || ICONOS.descarga;
        return { _bit: true, color: ic[2], texto: `<strong>${esc(nombreDoc(e))}</strong> ${esc((e.texto || "").toLowerCase())}${e.colegio ? " · " + esc(e.colegio) : ""}`, tiempo: fechaHora(e.creado_en) };
      });
      ultimosEvs = evs;
      aplicarFeed();
    } catch (e) { /* se mantiene el feed básico */ }
  }
  let ultimosEvs = null;
  function aplicarFeed() {
    if (!ultimosEvs || typeof _presFeedLog === "undefined") return;
    _presFeedLog = _presFeedLog.filter((x) => x.color !== "#94a3b8" && !x._bit).concat(ultimosEvs);
    if (typeof presRenderFeed === "function") presRenderFeed();
  }

  // ── Tarjeta de bitácora ──
  let cargandoBit = false, ultimaBit = 0;
  function llenarDoctoras() {
    const sel = $("bit-doc");
    if (!sel) return;
    const actual = sel.value;
    const lista = datos().slice().sort((a, b) => String(a.nombre).localeCompare(String(b.nombre), "es"));
    if (sel.options.length - 1 === lista.length) return;
    sel.innerHTML = `<option value="">Todas las doctoras</option>` + lista.map((d) => `<option value="${esc(d.doctora_id)}">${esc(d.nombre)}</option>`).join("");
    sel.value = actual;
  }

  async function cargarBitacora() {
    const lista = $("bit-lista");
    if (!lista || cargandoBit) return;
    cargandoBit = true; ultimaBit = Date.now();
    const doc = $("bit-doc").value, dias = $("bit-dias").value, acc = $("bit-accion").value;
    const qs = new URLSearchParams({ dias, limit: "400" });
    if (doc) qs.set("usuario_id", doc);
    if (acc) qs.set("accion", acc);
    try {
      const r = await fetch("/api/bitacora?" + qs.toString(), { credentials: "same-origin" });
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.message || "Error");
      const aviso = $("bit-aviso");
      if (!j.disponible) {
        aviso.style.display = "block";
        aviso.innerHTML = `<i class="fa-solid fa-circle-info"></i> El registro detallado (inicios de sesión, nóminas abiertas, descargas) empezará a guardarse cuando se active la tabla de bitácora en la base de datos. Mientras tanto se muestran las evaluaciones por día.`;
      } else aviso.style.display = "none";

      // Evaluaciones por día (solo con una doctora elegida)
      const box = $("bit-dias-box");
      if (doc) {
        box.style.display = "block";
        const pd = j.evaluaciones_por_dia || [];
        $("bit-por-dia").innerHTML = pd.length ? pd.map((d) => `<div class="bit-pd"><div class="f"><span>${esc(diaLargo(d.fecha))}</span><b>${fmtN(d.total)} ${d.total === 1 ? "evaluación" : "evaluaciones"}</b></div>
          <div class="c">${d.colegios.map((c) => `${esc(c.colegio)} (${fmtN(c.n)})`).join(" · ")}</div></div>`).join("")
          : `<div class="bit-vacio">Sin evaluaciones cerradas en este período.</div>`;
      } else box.style.display = "none";

      // Línea de tiempo
      const evs = j.eventos || [];
      if (!evs.length) {
        lista.innerHTML = `<div class="bit-vacio">${j.disponible ? "Sin actividad registrada en este período." : "Aún no hay registros en la bitácora."}</div>`;
      } else {
        let html = "", diaPrev = "";
        evs.forEach((e) => {
          const dia = new Date(e.creado_en).toDateString();
          if (dia !== diaPrev) { html += `<div class="bit-dia">${esc(diaLargo(e.creado_en))}</div>`; diaPrev = dia; }
          const ic = ICONOS[e.accion] || ICONOS.descarga, sub = subtitulo(e);
          html += `<div class="bit-ev"><span class="bit-ic" style="background:${ic[1]};color:${ic[2]}"><i class="fa-solid ${ic[0]}"></i></span>
            <div style="min-width:0;flex:1"><div class="t">${doc ? "" : esc(nombreDoc(e)) + " · "}${esc(e.texto)}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>
            <span class="h">${hora(e.creado_en)}</span></div>`;
        });
        lista.innerHTML = html;
      }
    } catch (e) {
      lista.innerHTML = `<div class="bit-vacio" style="color:#b91c1c"><i class="fa-solid fa-triangle-exclamation"></i> No se pudo cargar la bitácora.</div>`;
    } finally { cargandoBit = false; }
  }

  window.presAbrirBitacora = function (docId) {
    llenarDoctoras();
    const sel = $("bit-doc");
    if (!sel) return;
    sel.value = docId || "";
    cargarBitacora();
    const card = $("bit-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  window.presTrasCargar = function () {
    llenarDoctoras();
    if (ultimoHoy) aplicarHoy(ultimoHoy.doctoras || {});
    aplicarFeed();
    if (Date.now() - ultimaHoy > 25000) { ultimaHoy = Date.now(); avanceHoy(); feedHoy(); }
    if (Date.now() - ultimaBit > 60000) cargarBitacora();
  };

  ["bit-doc", "bit-dias", "bit-accion"].forEach((id) => { const el = $(id); if (el) el.addEventListener("change", cargarBitacora); });
})();
