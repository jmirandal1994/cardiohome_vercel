/* ══════════════════════════════════════════════════════════════════
   Formulario Medicina Familiar · vista compacta (solo diseño)
   Reagrupa visualmente los campos existentes de cada <form> en
   tarjetas por sección. No crea, renombra ni elimina campos: solo
   los mueve dentro del mismo <form>, así que el guardado, el PDF y
   la vista previa siguen funcionando igual.
   ══════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  var SECCIONES = {
    "identificación del estudiante": { ico: "fa-id-card", corto: "Identificación", tema: "slate" },
    "antecedentes perinatales": { ico: "fa-baby", corto: "Perinatales", half: true, tema: "green" },
    "dsm": { ico: "fa-child", corto: "DSM", half: true, tema: "green" },
    "antecedentes personales": { ico: "fa-notes-medical", corto: "Personales", tema: "orange" },
    "visión y audición": { ico: "fa-eye", corto: "Visión y audición", half: true, tema: "violet" },
    "salud bucodental": { ico: "fa-tooth", corto: "Bucodental", half: true, tema: "rose" },
    "examen físico y clasificación": { ico: "fa-stethoscope", corto: "Examen físico", tema: "blue" }
  };

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // Ancho de cada campo en la grilla de 12 columnas
  function anchoCampo(f) {
    var ta = f.querySelector("textarea");
    var nombre = (f.querySelector("[name]:not([type=hidden])") || {}).name || "";
    if (/^(nombre|diagnostico_unificado)$/.test(nombre)) return "s8";
    if (/^(altura|peso|imc|clasificacion_imc)$/.test(nombre)) return "s3";
    if (f.querySelector(".indicaciones-quick-bar, .deriv-chips-bar")) return "full";
    if (ta) {
      var max = parseInt(ta.getAttribute("maxlength") || "0", 10);
      if (max && max <= 32) return "s4";
      if (max && max <= 70) return "s6";
      return "full";
    }
    var cg = f.querySelector(".checkbox-group");
    if (cg) {
      var n = cg.querySelectorAll(".checkbox-item").length;
      return n <= 2 ? "s4" : n <= 3 ? "s6" : "full";
    }
    return "";
  }

  function controles(f) {
    return Array.prototype.filter.call(
      f.querySelectorAll("input, select, textarea"),
      function (c) { return c.type !== "hidden" && !c.readOnly && !c.disabled; }
    );
  }

  function campoLleno(f) {
    var cs = controles(f);
    if (!cs.length) return null; // campo solo informativo (calculado)
    for (var i = 0; i < cs.length; i++) {
      var c = cs[i];
      if (c.type === "checkbox") { if (c.checked) return true; }
      else if (String(c.value || "").trim() !== "") return true;
    }
    return false;
  }

  function compactar(form) {
    if (form.classList.contains("fm-on")) return;
    var hijos = Array.prototype.slice.call(form.children);
    if (!hijos.some(function (h) { return h.matches("h3.section-title"); })) return;

    var grid = el("div", "fm-grid");
    var nav = el("div", "fm-nav");
    var secciones = [];
    var actual = null, campo = null;

    function nuevoCampo() {
      campo = el("div", "fm-f");
      actual.body.appendChild(campo);
      actual.campos.push(campo);
    }

    hijos.forEach(function (h) {
      if (h.matches("h3.section-title")) {
        var titulo = h.textContent.trim();
        var cfg = SECCIONES[titulo.toLowerCase()] || { ico: "fa-file-medical", corto: titulo };
        var sec = el("section", "fm-sec" + (cfg.half ? " fm-half" : ""));
        sec.style.animationDelay = (secciones.length * 40) + "ms";
        sec.setAttribute("data-tema", cfg.tema || "slate");
        var head = el("div", "fm-head");
        head.appendChild(el("span", "fm-ico", '<i class="fas ' + cfg.ico + '"></i>'));
        head.appendChild(h);
        var cnt = el("span", "fm-count", "0/0");
        head.appendChild(cnt);
        head.appendChild(el("i", "fas fa-chevron-down fm-caret"));
        var wrap = el("div", "fm-wrap");
        var body = el("div", "fm-body");
        wrap.appendChild(body);
        sec.appendChild(head); sec.appendChild(wrap);
        grid.appendChild(sec);
        actual = { sec: sec, body: body, campos: [], cnt: cnt, cfg: cfg };
        secciones.push(actual);
        campo = null;
        head.addEventListener("click", function () { sec.classList.toggle("closed"); });
        return;
      }
      if (h.matches(".button-group")) { return; } // queda al final, fijo
      if (!actual) { return; } // avisos e inputs ocultos previos quedan donde están
      if (h.matches("input[type=hidden]")) { (campo || actual.body).appendChild(h); return; }
      if (h.matches("label:not(.checkbox-item)") || !campo) nuevoCampo();
      campo.appendChild(h);
    });

    var botones = form.querySelector(":scope > .button-group");
    if (botones) form.insertBefore(grid, botones); else form.appendChild(grid);
    form.insertBefore(nav, form.firstChild);

    secciones.forEach(function (s) {
      s.campos.forEach(function (f) {
        var w = anchoCampo(f); if (w) f.classList.add(w);
        var ta = f.querySelector("textarea[maxlength]");
        if (ta) {
          var len = el("small", "fm-len");
          f.appendChild(len);
          var upd = function () {
            var n = ta.value.length, m = parseInt(ta.getAttribute("maxlength"), 10);
            len.textContent = n + "/" + m;
            len.classList.toggle("warn", n >= m);
          };
          ta.addEventListener("input", upd); upd();
          s.lens = (s.lens || []).concat(upd);
        }
      });
      var chip = el("button", "fm-chip", '<span class="fm-ring"><i></i></span>' + s.cfg.corto);
      chip.type = "button";
      chip.setAttribute("data-tema", s.cfg.tema || "slate");
      chip.addEventListener("click", function () {
        s.sec.classList.remove("closed");
        s.sec.scrollIntoView({ behavior: "smooth", block: "start" });
        s.sec.classList.remove("flash"); void s.sec.offsetWidth; s.sec.classList.add("flash");
      });
      nav.appendChild(chip);
      s.chip = chip;
    });

    var tools = el("div", "fm-nav-tools");
    var total = el("span", "fm-total");
    var toggle = el("button", "fm-tool", '<i class="fas fa-compress"></i> Contraer');
    toggle.type = "button";
    toggle.addEventListener("click", function () {
      var cerrar = secciones.some(function (s) { return !s.sec.classList.contains("closed"); });
      secciones.forEach(function (s) { s.sec.classList.toggle("closed", cerrar); });
      toggle.innerHTML = cerrar ? '<i class="fas fa-expand"></i> Expandir' : '<i class="fas fa-compress"></i> Contraer';
    });
    tools.appendChild(total); tools.appendChild(toggle);
    nav.appendChild(tools);

    function progreso() {
      var llenos = 0, totales = 0;
      secciones.forEach(function (s) {
        var ok = 0, n = 0;
        s.campos.forEach(function (f) {
          var r = campoLleno(f);
          f.classList.toggle("filled", r === true);
          if (r === null) return;
          n++; if (r) ok++;
        });
        llenos += ok; totales += n;
        var pct = n ? Math.round(ok * 100 / n) : 0;
        s.cnt.textContent = ok + "/" + n;
        s.chip.querySelector(".fm-ring").style.setProperty("--p", pct);
        s.chip.querySelector(".fm-ring i").innerHTML = pct === 100 ? '<i class="fas fa-check" style="font-size:.5rem"></i>' : "";
        s.chip.classList.toggle("done", pct === 100);
        s.sec.classList.toggle("done", pct === 100);
        (s.lens || []).forEach(function (u) { u(); });
      });
      total.innerHTML = "<b>" + llenos + "</b> de " + totales;
    }
    var pend = false;
    function programar() { if (pend) return; pend = true; setTimeout(function () { pend = false; progreso(); }, 60); }
    form.addEventListener("input", programar);
    form.addEventListener("change", programar);
    form.addEventListener("click", programar);
    progreso();

    // Resalta en la barra la sección visible
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          var s = secciones.filter(function (x) { return x.sec === en.target; })[0];
          if (s && en.isIntersecting) {
            secciones.forEach(function (x) { x.chip.classList.toggle("current", x === s); });
          }
        });
      }, { rootMargin: "-140px 0px -55% 0px" });
      secciones.forEach(function (s) { io.observe(s.sec); });
    }

    form.classList.add("fm-on");
  }

  // La barra de secciones queda justo bajo el encabezado fijo de la página
  function altoEncabezado() {
    var h = document.querySelector("body > header");
    var alto = h && getComputedStyle(h).position === "sticky" ? h.offsetHeight : 0;
    document.documentElement.style.setProperty("--fm-top", alto + "px");
  }

  function iniciar() {
    altoEncabezado();
    window.addEventListener("resize", altoEncabezado);
    document.querySelectorAll(".formulario form").forEach(compactar);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
