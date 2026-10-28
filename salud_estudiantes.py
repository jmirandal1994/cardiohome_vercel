# -*- coding: utf-8 -*-
"""
Módulo "Salud de estudiantes": historial por estudiante, estadísticas de
peso/talla/IMC y alertas de reevaluación.

Todo es de SOLO LECTURA: no escribe nada en la base de datos ni modifica
rutas existentes. Se registra desde app.py con:

    from salud_estudiantes import crear_blueprint_salud
    app.register_blueprint(crear_blueprint_salud(SUPABASE_URL, SUPABASE_SERVICE_HEADERS))

Permisos por rol (session['usuario']):
    admin          -> todas las nóminas
    coordinadora   -> nóminas donde coord_general_id = su id
    doctora        -> nóminas donde es doctora_id, _2, _3 o _4
    otros          -> sin acceso
"""
import re
import time
import threading
from collections import Counter, defaultdict
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Blueprint, Response, jsonify, request, session

ROLES_PERMITIDOS = ("admin", "coordinadora", "doctora")
CACHE_TTL = 300          # segundos
PAGE = 1000              # filas por página (límite típico de PostgREST)

COLS_LIGERAS = ("id,nomina_id,nombre,rut,fecha_nacimiento,sexo,fecha_relleno,"
                "altura,peso,imc,clasificacion_imc,fecha_reevaluacion,estado_asistencia")
COLS_HISTORIAL = ("id,nomina_id,nombre,rut,fecha_nacimiento,edad,sexo,fecha_relleno,altura,peso,imc,"
                  "clasificacion_imc,fecha_reevaluacion,diagnostico,diagnostico_1,diagnostico_2,"
                  "diagnostico_complementario,diagnostico_sospecha,diagnostico_definitivo,derivaciones,"
                  "indicaciones,doctor_nombre,doctor_especialidad,estado_asistencia")
COLS_NOMINA = ("id,nombre_nomina,nombre_colegio,form_type,tipo_nomina,proyecto_id,coord_general_id,"
               "doctora_id,doctora_id_2,doctora_id_3,doctora_id_4")

CLASES = ["Bajo peso", "Normal", "Sobrepeso", "Obesidad"]


# ───────────────────────── utilidades ─────────────────────────
def normalizar_rut(rut):
    """'12.345.678-k' -> '12345678K'"""
    return re.sub(r"[^0-9K]", "", str(rut or "").upper())


def variantes_rut(rut):
    """Formas en que el mismo RUT puede estar escrito en la base."""
    n = normalizar_rut(rut)
    if len(n) < 2:
        return []
    cuerpo, dv = n[:-1], n[-1]
    con_puntos = f"{int(cuerpo):,}".replace(",", ".") if cuerpo.isdigit() else cuerpo
    vs = {n, n.lower(), f"{cuerpo}-{dv}", f"{cuerpo}-{dv.lower()}",
          f"{con_puntos}-{dv}", f"{con_puntos}-{dv.lower()}"}
    return sorted(vs)


def normalizar_clasificacion(texto, imc=None):
    t = (texto or "").strip().lower()
    if not t:
        return "Sin clasificar" if imc not in (None, "") else None
    if "bajo" in t or "desnutr" in t:
        return "Bajo peso"
    if "obes" in t:
        return "Obesidad"
    if "sobre" in t:
        return "Sobrepeso"
    if "normal" in t or "eutrof" in t:
        return "Normal"
    if "curva" in t or "< 2" in t:
        return "Menor de 2 años"
    return "Sin clasificar"


def _fecha(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")[:19]).date() \
            if "T" in str(v) or " " in str(v) else date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _edad_anios(nac, ref):
    if not nac or not ref:
        return None
    a = ref.year - nac.year - ((ref.month, ref.day) < (nac.month, nac.day))
    return a if 0 <= a <= 25 else None


def _especialidad(nom):
    ft = (nom or {}).get("form_type") or ""
    tipo = ((nom or {}).get("tipo_nomina") or "").lower()
    if ft in ("neurologia", "informe_neurologico") or "neuro" in tipo:
        return "Neurología"
    if ft == "medicina_familiar" or "familiar" in tipo or "medicina" in tipo:
        return "Medicina familiar"
    return "Otra"


def estado_reevaluacion(fecha_reev, hoy=None):
    """Semáforo según los días que faltan. Se recalcula cada día."""
    hoy = hoy or date.today()
    if not fecha_reev:
        return "sin_fecha", None
    if fecha_reev.year < 2020 or (fecha_reev - hoy).days > 365 * 8:
        return "fecha_a_revisar", None
    dias = (fecha_reev - hoy).days
    if dias < 0:
        return "vencida", dias
    if dias <= 30:
        return "urgente", dias
    if dias <= 90:
        return "proxima", dias
    if dias <= 365:
        return "este_anio", dias
    return "en_plazo", dias


def calidad_antropometria(altura, peso, imc):
    """Devuelve lista de problemas detectados (vacía si todo es plausible)."""
    p = []
    if altura is not None:
        if altura < 3:
            p.append("Talla parece estar en metros")
        elif altura < 45 or altura > 210:
            p.append("Talla fuera de rango")
    if peso is not None and (peso < 5 or peso > 160):
        p.append("Peso fuera de rango")
    if imc is not None and (imc < 9 or imc > 50):
        p.append("IMC improbable")
    return p


# Especialidades a las que se deriva. Se reconocen por palabras clave porque el
# texto viene libre (medicina familiar usa "DENTISTA - OFTALMÓLOGO", neurología
# escribe recomendaciones completas).
ESPECIALIDADES_DERIVACION = [
    ("Oftalmología", r"oftalm|[oó]ptic"),
    ("Dental", r"dentist|odontol|dental"),
    ("Nutrición", r"nutri"),
    ("Otorrinolaringología", r"otorrin|lavado de o[ií]do"),
    ("Neurología", r"neur[oó]log"),
    ("Pediatría", r"pediatr"),
    ("Fonoaudiología", r"fonoaud"),
    ("Psicología", r"psic[oó]log"),
    ("Terapia ocupacional", r"terap\w* ocupacional"),
    ("Psicopedagogía / Ed. diferencial", r"psicopedag|educador\w* diferencial"),
    ("Psiquiatría", r"psiquiatr"),
    ("Endocrinología", r"endocrin"),
    ("Broncopulmonar", r"broncopulm"),
    ("Dermatología", r"dermat"),
    ("Traumatología", r"traumat"),
    ("Kinesiología", r"kinesi"),
    ("Cardiología", r"cardi[oó]log"),
]
_RX_DERIV = [(n, re.compile(p, re.I)) for n, p in ESPECIALIDADES_DERIVACION]


def especialidades_derivadas(texto):
    if not texto or not str(texto).strip():
        return []
    t = str(texto)
    return [n for n, rx in _RX_DERIV if rx.search(t)]


# ───────────────────────── blueprint ─────────────────────────
def crear_blueprint_salud(supabase_url, headers):
    bp = Blueprint("salud_estudiantes", __name__)
    _cache = {}
    _lock = threading.Lock()

    def _get(path, extra_headers=None):
        h = dict(headers)
        if extra_headers:
            h.update(extra_headers)
        r = requests.get(f"{supabase_url}/rest/v1/{path}", headers=h, timeout=25)
        r.raise_for_status()
        return r

    def _cacheado(clave, fn):
        ahora = time.time()
        with _lock:
            hit = _cache.get(clave)
            if hit and ahora - hit[0] < CACHE_TTL:
                return hit[1]
        val = fn()
        with _lock:
            _cache[clave] = (ahora, val)
        return val

    def _todas_paginas(path_base):
        """Trae todas las filas de una consulta, en paralelo por páginas."""
        r = _get(path_base, {"Prefer": "count=exact", "Range": "0-0"})
        try:
            total = int(r.headers.get("Content-Range", "0/0").split("/")[-1])
        except ValueError:
            total = 0
        if total == 0:
            return []
        rangos = [(i, min(i + PAGE, total) - 1) for i in range(0, total, PAGE)]

        def pedir(rg):
            return _get(path_base, {"Range": f"{rg[0]}-{rg[1]}", "Prefer": "count=none"}).json()

        filas = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            for bloque in ex.map(pedir, rangos):
                filas.extend(bloque)
        return filas

    def _nominas():
        return _cacheado("nominas", lambda: {
            n["id"]: n for n in _todas_paginas(f"nominas_medicas?select={COLS_NOMINA}&order=id.asc")})

    def _proyectos():
        return _cacheado("proyectos", lambda: {
            p["id"]: p.get("nombre_proyecto") for p in
            _get("proyectos?select=id,nombre_proyecto").json()})

    def _nominas_permitidas():
        rol, uid = session.get("usuario"), str(session.get("usuario_id") or "")
        noms = _nominas()
        if rol == "admin":
            return set(noms.keys())
        if rol == "coordinadora":
            return {k for k, n in noms.items() if str(n.get("coord_general_id") or "") == uid}
        if rol == "doctora":
            return {k for k, n in noms.items()
                    if uid in {str(n.get(c) or "") for c in ("doctora_id", "doctora_id_2", "doctora_id_3", "doctora_id_4")}}
        return set()

    def _evaluaciones_ligeras():
        """Todas las evaluaciones realizadas (cache compartida); se filtran por rol después."""
        return _cacheado("evals", lambda: _todas_paginas(
            f"estudiantes_nomina?select={COLS_LIGERAS}&fecha_relleno=not.is.null&order=id.asc"))

    def _autorizado():
        return "usuario" in session and session.get("usuario") in ROLES_PERMITIDOS

    def _filtrar(filas, permitidas):
        proyecto = request.args.get("proyecto_id") or ""
        colegio = (request.args.get("colegio") or "").strip().lower()
        noms = _nominas()
        out = []
        for f in filas:
            nid = f.get("nomina_id")
            if nid not in permitidas:
                continue
            n = noms.get(nid) or {}
            if proyecto and str(n.get("proyecto_id") or "") != proyecto:
                continue
            if colegio and (n.get("nombre_colegio") or "").strip().lower() != colegio:
                continue
            out.append(f)
        return out

    # ───────────── filtros disponibles ─────────────
    @bp.route("/api/salud/filtros", methods=["GET"])
    def api_salud_filtros():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            permitidas = _nominas_permitidas()
            noms, proys = _nominas(), _proyectos()
            proyectos, colegios = {}, set()
            for nid in permitidas:
                n = noms[nid]
                if n.get("proyecto_id"):
                    proyectos[n["proyecto_id"]] = proys.get(n["proyecto_id"]) or "Proyecto"
                if n.get("nombre_colegio"):
                    colegios.add(n["nombre_colegio"].strip())
            return jsonify({"success": True,
                            "proyectos": sorted([{"id": k, "nombre": v} for k, v in proyectos.items()], key=lambda x: x["nombre"]),
                            "colegios": sorted(colegios),
                            "rol": session.get("usuario")})
        except Exception as e:
            print(f"ERROR api_salud_filtros: {e}")
            return jsonify({"success": False, "message": "Error al cargar filtros"}), 500

    # ───────────── historial de un estudiante ─────────────
    @bp.route("/api/salud/buscar", methods=["GET"])
    def api_salud_buscar():
        """Busca estudiantes por RUT o nombre dentro del alcance del usuario."""
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        q = (request.args.get("q") or "").strip()
        if len(q) < 3:
            return jsonify({"success": True, "resultados": []})
        try:
            permitidas = _nominas_permitidas()
            noms = _nominas()
            n = normalizar_rut(q)
            if len(n) >= 7 and n[:-1].isdigit():
                rows = _get(f"estudiantes_nomina?select=id,nomina_id,nombre,rut,fecha_relleno"
                            f"&rut=in.({','.join(variantes_rut(q))})&limit=200").json()
            else:
                termino = re.sub(r"[%*,()]", " ", q)
                rows = _get(f"estudiantes_nomina?select=id,nomina_id,nombre,rut,fecha_relleno"
                            f"&nombre=ilike.*{requests.utils.quote(termino)}*&limit=400").json()
            agrupado = {}
            for r in rows:
                if r.get("nomina_id") not in permitidas:
                    continue
                clave = normalizar_rut(r.get("rut")) or r["id"]
                g = agrupado.setdefault(clave, {"rut": r.get("rut"), "nombre": r.get("nombre"),
                                                "evaluaciones": 0, "colegios": set()})
                if r.get("fecha_relleno"):
                    g["evaluaciones"] += 1
                col = (noms.get(r["nomina_id"]) or {}).get("nombre_colegio")
                if col:
                    g["colegios"].add(col.strip())
            res = [{**v, "colegios": sorted(v["colegios"])} for v in agrupado.values()]
            res.sort(key=lambda x: (x["nombre"] or ""))
            return jsonify({"success": True, "resultados": res[:30]})
        except Exception as e:
            print(f"ERROR api_salud_buscar: {e}")
            return jsonify({"success": False, "message": "Error en la búsqueda"}), 500

    @bp.route("/api/salud/historial", methods=["GET"])
    def api_salud_historial():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        rut = request.args.get("rut") or ""
        vs = variantes_rut(rut)
        if not vs:
            return jsonify({"success": False, "message": "RUT inválido"}), 400
        try:
            permitidas = _nominas_permitidas()
            noms = _nominas()
            rows = _get(f"estudiantes_nomina?select={COLS_HISTORIAL}&rut=in.({','.join(vs)})").json()
            # La doctora solo puede ver el historial de estudiantes que estén en alguna de sus nóminas
            if not any(r.get("nomina_id") in permitidas for r in rows):
                return jsonify({"success": False, "message": "Este estudiante no está en tus nóminas"}), 403
            # Admin y coordinadora ven solo sus nóminas; la doctora ve el historial completo del estudiante
            # (es su paciente) para poder comparar con evaluaciones anteriores.
            if session.get("usuario") != "doctora":
                rows = [r for r in rows if r.get("nomina_id") in permitidas]
            hoy = date.today()
            evals = []
            for r in rows:
                n = noms.get(r.get("nomina_id")) or {}
                fr = _fecha(r.get("fecha_relleno"))
                nac = _fecha(r.get("fecha_nacimiento"))
                altura, peso, imc = _num(r.get("altura")), _num(r.get("peso")), _num(r.get("imc"))
                freev = _fecha(r.get("fecha_reevaluacion"))
                est, dias = estado_reevaluacion(freev, hoy)
                diags = [r.get(k) for k in ("diagnostico_definitivo", "diagnostico_1", "diagnostico_2",
                                            "diagnostico", "diagnostico_sospecha", "diagnostico_complementario")]
                diags = list(dict.fromkeys([d.strip() for d in diags if d and str(d).strip()]))
                evals.append({
                    "id": r["id"],
                    "fecha": fr.isoformat() if fr else None,
                    "anio": fr.year if fr else None,
                    "evaluado": bool(fr),
                    "especialidad": _especialidad(n),
                    "colegio": (n.get("nombre_colegio") or "").strip() or None,
                    "nomina": n.get("nombre_nomina"),
                    "profesional": r.get("doctor_nombre"),
                    "edad": r.get("edad") or (f"{_edad_anios(nac, fr)} años" if _edad_anios(nac, fr) is not None else None),
                    "edad_anios": _edad_anios(nac, fr or hoy),
                    "altura": altura, "peso": peso, "imc": imc,
                    "clasificacion": normalizar_clasificacion(r.get("clasificacion_imc"), imc),
                    "alertas_datos": calidad_antropometria(altura, peso, imc),
                    "diagnosticos": diags,
                    "derivaciones": r.get("derivaciones"),
                    "indicaciones": r.get("indicaciones"),
                    "fecha_reevaluacion": freev.isoformat() if freev else None,
                    "estado_reevaluacion": est,
                    "dias_para_reevaluar": dias,
                    "progreso_reevaluacion": (
                        max(0, min(100, round(100 * (hoy - fr).days / max(1, (freev - fr).days))))
                        if fr and freev and freev > fr and est != "fecha_a_revisar" else None),
                })
            evals.sort(key=lambda e: (e["fecha"] or "9999", e["especialidad"]))
            # Solo la evaluación más reciente de cada especialidad tiene una reevaluación pendiente;
            # las anteriores ya se cumplieron con la evaluación siguiente.
            vista = set()
            for e in reversed(evals):
                if not e["evaluado"]:
                    continue
                if e["especialidad"] in vista:
                    e["estado_reevaluacion"], e["dias_para_reevaluar"], e["progreso_reevaluacion"] = "cumplida", None, 100
                vista.add(e["especialidad"])
            base = rows[0] if rows else {}
            return jsonify({"success": True, "estudiante": {
                "nombre": base.get("nombre"), "rut": base.get("rut"), "sexo": base.get("sexo"),
                "fecha_nacimiento": base.get("fecha_nacimiento"),
            }, "evaluaciones": evals, "hoy": hoy.isoformat()})
        except Exception as e:
            print(f"ERROR api_salud_historial: {e}")
            return jsonify({"success": False, "message": "Error al cargar el historial"}), 500

    # ───────────── cálculos (compartidos por la pantalla y los reportes) ─────────────
    def _calc_nutricion(filas, anio_param=None):
        noms = _nominas()
        anios = sorted({fr.year for fr in (_fecha(f.get("fecha_relleno")) for f in filas) if fr})
        try:
            anio_sel = int(anio_param or (anios[-1] if anios else date.today().year))
        except ValueError:
            anio_sel = anios[-1] if anios else date.today().year
        dist = {c: 0 for c in CLASES}
        vistos_anio = set()
        otros = {"Sin clasificar": 0, "Menor de 2 años": 0}
        por_colegio, por_edad, por_anio = {}, {}, {}
        revisar, con_medidas = [], 0
        for f in filas:
            altura, peso, imc = _num(f.get("altura")), _num(f.get("peso")), _num(f.get("imc"))
            if altura is None and peso is None and imc is None:
                continue
            con_medidas += 1
            problemas = calidad_antropometria(altura, peso, imc)
            n = noms.get(f.get("nomina_id")) or {}
            col = (n.get("nombre_colegio") or "Sin colegio").strip()
            if problemas:
                revisar.append({"nombre": f.get("nombre"), "rut": f.get("rut"), "colegio": col,
                                "altura": altura, "peso": peso, "imc": imc, "problemas": problemas})
                continue
            c = normalizar_clasificacion(f.get("clasificacion_imc"), imc)
            fr, nac = _fecha(f.get("fecha_relleno")), _fecha(f.get("fecha_nacimiento"))
            if fr:
                pa = por_anio.setdefault(fr.year, {"anio": fr.year, "total": 0, **{k: 0 for k in CLASES}})
                pa["total"] += 1
                if c in CLASES:
                    pa[c] += 1
            # Lo que sigue describe solo el año elegido y una medición por estudiante
            if not fr or fr.year != anio_sel:
                continue
            clave_est = normalizar_rut(f.get("rut")) or f["id"]
            if clave_est in vistos_anio:
                continue
            vistos_anio.add(clave_est)
            if c in dist:
                dist[c] += 1
            elif c in otros:
                otros[c] += 1
            pc = por_colegio.setdefault(col, {"colegio": col, "total": 0, **{k: 0 for k in CLASES}})
            pc["total"] += 1
            if c in CLASES:
                pc[c] += 1
            ed = _edad_anios(nac, fr)
            sexo = (f.get("sexo") or "").strip().upper()[:1]  # "F"/"M"; otros valores no se grafican
            if ed is not None and imc is not None and 2 <= ed <= 18:
                pe = por_edad.setdefault(ed, {"edad": ed, "F": [], "M": [], "talla_F": [], "talla_M": [],
                                               "peso_F": [], "peso_M": []})
                if sexo in ("F", "M"):
                    pe[sexo].append(imc)
                    if altura:
                        pe["talla_" + sexo].append(altura)
                    if peso:
                        pe["peso_" + sexo].append(peso)

        def prom(xs):
            return round(sum(xs) / len(xs), 1) if xs else None

        edades = [{"edad": e["edad"],
                   "imc_F": prom(e["F"]), "imc_M": prom(e["M"]),
                   "talla_F": prom(e["talla_F"]), "talla_M": prom(e["talla_M"]),
                   "peso_F": prom(e["peso_F"]), "peso_M": prom(e["peso_M"]),
                   "n": len(e["F"]) + len(e["M"])} for e in sorted(por_edad.values(), key=lambda x: x["edad"])]
        colegios = []
        for pc in por_colegio.values():
            clas = sum(pc[k] for k in CLASES)
            pc["exceso_pct"] = round(100 * (pc["Sobrepeso"] + pc["Obesidad"]) / clas, 1) if clas else None
            pc["bajo_pct"] = round(100 * pc["Bajo peso"] / clas, 1) if clas else None
            colegios.append(pc)
        colegios.sort(key=lambda x: -(x["exceso_pct"] or 0))
        clasificados = sum(dist.values())
        return {
            "anio": anio_sel, "anios": anios,
            "evaluados": len(filas), "con_medidas": con_medidas, "clasificados": clasificados,
            "distribucion": dist, "otros": otros,
            "exceso_pct": round(100 * (dist["Sobrepeso"] + dist["Obesidad"]) / clasificados, 1) if clasificados else None,
            "colegios": colegios, "por_edad": edades,
            "por_anio": sorted(por_anio.values(), key=lambda x: x["anio"]),
            "a_revisar": revisar, "a_revisar_total": len(revisar),
        }

    def _calc_reev(filas, incluir_al_dia=False):
        noms = _nominas()
        hoy = date.today()
        # Una alerta por estudiante y especialidad: la evaluación más reciente manda.
        ultima = {}
        for f in filas:
            n = noms.get(f.get("nomina_id")) or {}
            esp = _especialidad(n)
            clave = (normalizar_rut(f.get("rut")) or f["id"], esp)
            fr = _fecha(f.get("fecha_relleno"))
            prev = ultima.get(clave)
            if not prev or (fr and (prev["_fr"] is None or fr > prev["_fr"])):
                ultima[clave] = {**f, "_fr": fr, "_esp": esp, "_col": (n.get("nombre_colegio") or "").strip()}
        conteo = {k: 0 for k in ("vencida", "urgente", "proxima", "este_anio", "en_plazo", "fecha_a_revisar", "sin_fecha")}
        por_mes, lista = {}, []
        for f in ultima.values():
            freev = _fecha(f.get("fecha_reevaluacion"))
            est, dias = estado_reevaluacion(freev, hoy)
            conteo[est] += 1
            if freev and est not in ("fecha_a_revisar", "sin_fecha"):
                k = freev.strftime("%Y-%m")
                por_mes[k] = por_mes.get(k, 0) + 1
            if incluir_al_dia or est in ("vencida", "urgente", "proxima", "este_anio", "fecha_a_revisar"):
                fr = f["_fr"]
                lista.append({
                    "nombre": f.get("nombre"), "rut": f.get("rut"), "colegio": f["_col"] or None,
                    "especialidad": f["_esp"], "fecha_evaluacion": fr.isoformat() if fr else None,
                    "fecha_reevaluacion": freev.isoformat() if freev else None,
                    "estado": est, "dias": dias,
                    "progreso": (max(0, min(100, round(100 * (hoy - fr).days / max(1, (freev - fr).days))))
                                 if fr and freev and freev > fr and est != "fecha_a_revisar" else None),
                })
        orden = {"vencida": 0, "urgente": 1, "proxima": 2, "este_anio": 3, "fecha_a_revisar": 4, "en_plazo": 5, "sin_fecha": 6}
        lista.sort(key=lambda x: (orden[x["estado"]], x["dias"] if x["dias"] is not None else 99999))
        return {"hoy": hoy.isoformat(), "total_estudiantes": len(ultima), "conteo": conteo,
                "por_mes": [{"mes": k, "n": v} for k, v in sorted(por_mes.items())],
                "lista": lista, "lista_total": len(lista)}

    def _calc_reev_establecimientos(filas, con_estudiantes=True):
        """Reevaluaciones agrupadas por proyecto y establecimiento: cuántas vencen, cuáles son,
        y el historial de cada colegio (cuándo se evaluó y quiénes ya fueron reevaluados)."""
        noms, proys = _nominas(), _proyectos()
        hoy = date.today()
        hoy_ym = hoy.strftime("%Y-%m")
        lim_ym = (date(hoy.year + 1, hoy.month, 1)).strftime("%Y-%m")
        # Evaluaciones de cada estudiante y especialidad, ordenadas en el tiempo
        grupos = defaultdict(list)
        for f in filas:
            n = noms.get(f.get("nomina_id")) or {}
            esp = _especialidad(n)
            grupos[(normalizar_rut(f.get("rut")) or f["id"], esp)].append((_fecha(f.get("fecha_relleno")), f, n))
        ALERTA = ("vencida", "urgente", "proxima")
        cols = {}

        def colegio(n):
            pid = n.get("proyecto_id")
            nombre = (n.get("nombre_colegio") or n.get("nombre_nomina") or "Sin colegio").strip()
            k = (str(pid or ""), nombre.upper())
            if k not in cols:
                cols[k] = {"proyecto_id": pid, "proyecto": proys.get(pid) or "Sin proyecto", "colegio": nombre,
                           "total": 0, "reevaluados": 0, "conteo": Counter(), "campanas": Counter(),
                           "calendario": Counter(), "proxima_fecha": None, "estudiantes": []}
            return cols[k]

        for evs in grupos.values():
            evs.sort(key=lambda x: (x[0] or date.min))
            fr, f, n = evs[-1]
            c = colegio(n)
            c["total"] += 1
            for fr_i, _f_i, n_i in evs:  # campañas: cuándo se evaluó en cada colegio
                if fr_i:
                    colegio(n_i)["campanas"][fr_i.strftime("%Y-%m")] += 1
            if len(evs) > 1:
                c["reevaluados"] += 1
            freev = _fecha(f.get("fecha_reevaluacion"))
            est, dias = estado_reevaluacion(freev, hoy)
            c["conteo"][est] += 1
            if freev and est not in ("fecha_a_revisar", "sin_fecha"):
                ym = freev.strftime("%Y-%m")
                if est == "vencida":
                    c["calendario"]["vencidas"] += 1
                elif ym <= lim_ym:
                    c["calendario"][ym] += 1
                if est != "vencida" and (c["proxima_fecha"] is None or freev.isoformat() < c["proxima_fecha"]):
                    c["proxima_fecha"] = freev.isoformat()
            if con_estudiantes and est in ALERTA + ("este_anio", "fecha_a_revisar"):
                c["estudiantes"].append({"nombre": f.get("nombre"), "rut": f.get("rut"), "especialidad": _especialidad(n),
                                         "fecha_evaluacion": fr.isoformat() if fr else None,
                                         "fecha_reevaluacion": freev.isoformat() if freev else None,
                                         "estado": est, "dias": dias, "veces": len(evs)})

        orden = {"vencida": 0, "urgente": 1, "proxima": 2, "este_anio": 3, "fecha_a_revisar": 4}
        salida, por_proy = [], {}
        for c in cols.values():
            c["alerta"] = sum(c["conteo"].get(k, 0) for k in ALERTA)
            c["estudiantes"].sort(key=lambda x: (orden[x["estado"]], x["dias"] if x["dias"] is not None else 99999, x["nombre"] or ""))
            c["conteo"] = {k: c["conteo"].get(k, 0) for k in ("vencida", "urgente", "proxima", "este_anio", "en_plazo", "fecha_a_revisar", "sin_fecha")}
            c["campanas"] = [{"mes": k, "n": v} for k, v in sorted(c["campanas"].items())]
            cal = c["calendario"]
            c["calendario"] = {"vencidas": cal.pop("vencidas", 0),
                               "meses": [{"mes": k, "n": v} for k, v in sorted(cal.items()) if k >= hoy_ym]}
            if not con_estudiantes:
                c.pop("estudiantes")
            salida.append(c)
            pk = str(c["proyecto_id"] or "")
            p = por_proy.setdefault(pk, {"id": c["proyecto_id"], "nombre": c["proyecto"], "colegios": 0, "colegios_alerta": 0,
                                         "total": 0, "conteo": Counter()})
            p["colegios"] += 1
            p["colegios_alerta"] += 1 if c["alerta"] else 0
            p["total"] += c["total"]
            p["conteo"].update(c["conteo"])
        for p in por_proy.values():
            p["conteo"] = dict(p["conteo"])
            p["alerta"] = sum(p["conteo"].get(k, 0) for k in ALERTA)
        salida.sort(key=lambda c: (-c["conteo"]["vencida"], -c["conteo"]["urgente"], -c["conteo"]["proxima"],
                                   c["proyecto"], c["colegio"]))
        tot = Counter()
        for c in salida:
            tot.update(c["conteo"])
        return {"hoy": hoy.isoformat(),
                "resumen": {"conteo": dict(tot), "alerta": sum(tot.get(k, 0) for k in ALERTA),
                            "colegios": len(salida), "colegios_alerta": sum(1 for c in salida if c["alerta"])},
                "proyectos": sorted(por_proy.values(), key=lambda p: (-p["alerta"], p["nombre"] or "")),
                "colegios": salida}

    def _calc_derivaciones(filas):
        """Derivaciones por especialidad. Cuenta estudiantes (no textos): un estudiante con
        'DENTISTA - OFTALMÓLOGO' suma 1 en Dental y 1 en Oftalmología."""
        noms = _nominas()
        evaluados = set()
        por_esp, por_colegio, por_origen, por_anio = {}, {}, {}, {}
        derivados, lista = set(), []
        for f in filas:
            clave = normalizar_rut(f.get("rut")) or f["id"]
            evaluados.add(clave)
            esps = especialidades_derivadas(f.get("derivaciones"))
            if not esps:
                continue
            derivados.add(clave)
            n = noms.get(f.get("nomina_id")) or {}
            col = (n.get("nombre_colegio") or "Sin colegio").strip()
            origen = _especialidad(n)
            fr = _fecha(f.get("fecha_relleno"))
            for e in esps:
                por_esp.setdefault(e, set()).add(clave)
                pc = por_colegio.setdefault(col, {"colegio": col, "derivados": set(), **{}})
                pc.setdefault(e, set()).add(clave)
                pc["derivados"].add(clave)
                por_origen.setdefault(origen, {}).setdefault(e, set()).add(clave)
                if fr:
                    por_anio.setdefault(fr.year, {}).setdefault(e, set()).add(clave)
            lista.append({"nombre": f.get("nombre"), "rut": f.get("rut"), "colegio": col, "origen": origen,
                          "fecha": fr.isoformat() if fr else None, "especialidades": esps})
        ranking = sorted(((e, len(v)) for e, v in por_esp.items()), key=lambda x: -x[1])
        orden_esp = [e for e, _ in ranking]
        tot_eval = len(evaluados)
        colegios = []
        for pc in por_colegio.values():
            fila = {"colegio": pc["colegio"], "derivados": len(pc["derivados"])}
            for e in orden_esp:
                fila[e] = len(pc.get(e, ()))
            colegios.append(fila)
        colegios.sort(key=lambda x: -x["derivados"])
        lista.sort(key=lambda x: (x["colegio"] or "", x["nombre"] or ""))
        return {
            "evaluados": tot_eval, "derivados": len(derivados),
            "derivados_pct": round(100 * len(derivados) / tot_eval, 1) if tot_eval else None,
            "especialidades": [{"especialidad": e, "estudiantes": n,
                                "pct": round(100 * n / tot_eval, 1) if tot_eval else None} for e, n in ranking],
            "colegios": colegios,
            "por_origen": {o: {e: len(v) for e, v in d.items()} for o, d in por_origen.items()},
            "por_anio": [{"anio": a, **{e: len(v) for e, v in d.items()}} for a, d in sorted(por_anio.items())],
            "lista": lista,
        }

    def _evaluaciones_derivaciones():
        return _cacheado("deriv", lambda: _todas_paginas(
            "estudiantes_nomina?select=id,nomina_id,nombre,rut,fecha_relleno,derivaciones"
            "&fecha_relleno=not.is.null&derivaciones=not.is.null&order=id.asc"))

    def _evaluados_para_derivaciones():
        """Evaluaciones (con y sin derivación) para calcular porcentajes."""
        ligeras = _filtrar(_evaluaciones_ligeras(), _nominas_permitidas())
        con_texto = {f["id"]: f.get("derivaciones") for f in _filtrar(_evaluaciones_derivaciones(), _nominas_permitidas())}
        return [{**f, "derivaciones": con_texto.get(f["id"])} for f in ligeras]

    # ───────────── rutas de la pantalla ─────────────
    @bp.route("/api/salud/nutricion", methods=["GET"])
    def api_salud_nutricion():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            r = _calc_nutricion(_filtrar(_evaluaciones_ligeras(), _nominas_permitidas()), request.args.get("anio"))
            r["a_revisar"] = r["a_revisar"][:300]
            return jsonify({"success": True, **r})
        except Exception as e:
            print(f"ERROR api_salud_nutricion: {e}")
            return jsonify({"success": False, "message": "Error al calcular estadísticas"}), 500

    @bp.route("/api/salud/reevaluaciones", methods=["GET"])
    def api_salud_reevaluaciones():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            r = _calc_reev(_filtrar(_evaluaciones_ligeras(), _nominas_permitidas()))
            r["lista"] = r["lista"][:2000]
            return jsonify({"success": True, **r})
        except Exception as e:
            print(f"ERROR api_salud_reevaluaciones: {e}")
            return jsonify({"success": False, "message": "Error al calcular reevaluaciones"}), 500

    @bp.route("/api/salud/reevaluaciones/establecimientos", methods=["GET"])
    def api_salud_reev_establecimientos():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            resumen = request.args.get("resumen") == "1"
            r = _calc_reev_establecimientos(_filtrar(_evaluaciones_ligeras(), _nominas_permitidas()),
                                            con_estudiantes=not resumen)
            if resumen:  # solo para la alerta del inicio: los colegios con más urgencias
                r["colegios"] = [c for c in r["colegios"] if c["alerta"]][:8]
            return jsonify({"success": True, **r})
        except Exception as e:
            print(f"ERROR api_salud_reev_establecimientos: {e}")
            return jsonify({"success": False, "message": "Error al calcular reevaluaciones por establecimiento"}), 500

    @bp.route("/api/salud/derivaciones", methods=["GET"])
    def api_salud_derivaciones():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            r = _calc_derivaciones(_evaluados_para_derivaciones())
            r["colegios"] = r["colegios"][:60]
            r.pop("lista", None)
            return jsonify({"success": True, **r})
        except Exception as e:
            print(f"ERROR api_salud_derivaciones: {e}")
            return jsonify({"success": False, "message": "Error al calcular derivaciones"}), 500

    # ───────────── reportes descargables (Excel) ─────────────
    @bp.route("/api/salud/reporte", methods=["GET"])
    def api_salud_reporte():
        if not _autorizado():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        tipo = request.args.get("tipo", "completo")
        if tipo not in ("completo", "reevaluaciones", "nutricion", "derivaciones"):
            return jsonify({"success": False, "message": "Tipo de reporte no válido"}), 400
        try:
            from reportes_salud import armar_excel
            filas = _filtrar(_evaluaciones_ligeras(), _nominas_permitidas())
            datos = {}
            if tipo in ("completo", "reevaluaciones"):
                datos["reev"] = _calc_reev(filas, incluir_al_dia=True)
                datos["reev_est"] = _calc_reev_establecimientos(filas)
            if tipo in ("completo", "nutricion"):
                datos["nutri"] = _calc_nutricion(filas, request.args.get("anio"))
            if tipo in ("completo", "derivaciones"):
                datos["deriv"] = _calc_derivaciones(_evaluados_para_derivaciones())
            proys = _proyectos()
            filtros = {
                "Generado por": session.get("nombre") or session.get("usuario"),
                "Perfil": {"admin": "Administrador", "coordinadora": "Coordinadora general", "doctora": "Doctora"}.get(session.get("usuario"), ""),
                "Proyecto": proys.get(request.args.get("proyecto_id")) or "Todos",
                "Colegio": request.args.get("colegio") or "Todos",
            }
            contenido = armar_excel(tipo, datos, filtros)
            nombre = f"Reporte_salud_{tipo}_{date.today().isoformat()}.xlsx"
            return Response(contenido,
                            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
        except Exception as e:
            print(f"ERROR api_salud_reporte: {e}")
            return jsonify({"success": False, "message": "No se pudo generar el reporte"}), 500

    return bp
