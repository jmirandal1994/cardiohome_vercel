# -*- coding: utf-8 -*-
"""
Rendimiento en Vivo ampliado (coordinadora general y admin). Solo lectura.

GET /api/coordinadora/actividad devuelve, para las nóminas del usuario:
  - quién está conectado ahora (presencia_doctoras)
  - actividad reciente: evaluaciones cerradas y correcciones resueltas
  - evaluaciones por doctora (total, últimos 7 y 30 días)
  - actividad diaria de las últimas 12 semanas (mapa de calor)
  - correcciones (aprobadas, rechazadas, pendientes) y ausencias
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, session

from consultas_rapidas import cargar_filas_nominas

MIN_CONECTADA = 30  # minutos sin actividad para dejar de mostrarla como conectada


def _fecha(v):
    if not v:
        return None
    s = str(v)
    try:
        if "T" in s or " " in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")[:19]).date()
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _momento(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _especialidad(n):
    ft = (n or {}).get("form_type") or ""
    tipo = ((n or {}).get("tipo_nomina") or "").lower()
    if ft in ("neurologia", "informe_neurologico") or "neuro" in tipo:
        return "Neurología"
    if ft == "medicina_familiar" or "familiar" in tipo or "medicina" in tipo:
        return "Medicina familiar"
    return "Otra"


def _estado_correccion(e):
    t = (e or "").strip().lower()
    if t.startswith("aprob"):
        return "Aprobada"
    if t.startswith("rechaz"):
        return "Rechazada"
    return "Pendiente"


def crear_blueprint_actividad(supabase_url, headers):
    bp = Blueprint("actividad_coordinacion", __name__)
    h_simple = {k: v for k, v in headers.items() if k.lower() != "prefer"}

    def _get(path):
        r = requests.get(f"{supabase_url}/rest/v1/{path}", headers=h_simple, timeout=25)
        r.raise_for_status()
        return r.json()

    def _get_todo(path, pagina=1000):
        """Todas las filas de una consulta, por páginas (hay ~2.000 solicitudes de corrección)."""
        filas, ini = [], 0
        while True:
            r = requests.get(f"{supabase_url}/rest/v1/{path}", headers={**h_simple, "Range": f"{ini}-{ini + pagina - 1}"}, timeout=25)
            r.raise_for_status()
            parte = r.json()
            filas.extend(parte)
            if len(parte) < pagina:
                return filas
            ini += pagina

    @bp.route("/api/coordinadora/actividad", methods=["GET"])
    def api_coordinadora_actividad():
        rol, uid = session.get("usuario"), session.get("usuario_id")
        if rol not in ("coordinadora", "admin"):
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            sel_nom = "id,nombre_colegio,nombre_nomina,form_type,tipo_nomina,doctora_id,doctora_id_2,doctora_id_3,doctora_id_4"
            nominas = _get(f"nominas_medicas?select={sel_nom}" + (f"&coord_general_id=eq.{uid}" if rol == "coordinadora" else ""))
            noms = {n["id"]: n for n in nominas}
            docs = {d["id"]: (d.get("nombre") or d.get("usuario") or "Doctora") for d in _get("doctoras?select=id,nombre,usuario")}
            filas = cargar_filas_nominas(
                supabase_url, headers, list(noms.keys()),
                select="id,nomina_id,nombre,fecha_relleno,doctora_evaluadora_id,doctor_nombre,estado_asistencia,motivo_ausencia,evaluado_flag")
            hoy = date.today()
            ahora = datetime.now(timezone.utc)

            # ── Conectadas ahora ──
            doctoras_scope = {n.get(c) for n in nominas for c in ("doctora_id", "doctora_id_2", "doctora_id_3", "doctora_id_4") if n.get(c)}
            conectadas, ultima_vez = [], None
            for p in _get("presencia_doctoras?select=doctora_id,nomina_id,establecimiento,ultima_actividad,estado"):
                if rol == "coordinadora" and p.get("nomina_id") not in noms and p.get("doctora_id") not in doctoras_scope:
                    continue
                m = _momento(p.get("ultima_actividad"))
                if not m:
                    continue
                if ultima_vez is None or m > ultima_vez:
                    ultima_vez = m
                minutos = int((ahora - m).total_seconds() // 60)
                if minutos <= MIN_CONECTADA and (p.get("estado") or "") != "desconectada":
                    n = noms.get(p.get("nomina_id")) or {}
                    conectadas.append({"doctora": docs.get(p.get("doctora_id"), "Doctora"),
                                       "establecimiento": p.get("establecimiento") or n.get("nombre_colegio") or "",
                                       "especialidad": _especialidad(n) if n else "", "hace_min": max(0, minutos)})
            conectadas.sort(key=lambda x: x["hace_min"])

            # ── Evaluaciones por doctora y por día ──
            por_doc = defaultdict(lambda: {"total": 0, "d7": 0, "d30": 0, "colegios": set(), "esp": Counter()})
            por_dia = Counter()
            evaluadas, ausencias, motivos = [], 0, Counter()
            ids_scope = {}
            for f in filas:
                ids_scope[f["id"]] = f
                n = noms.get(f.get("nomina_id")) or {}
                est = f.get("estado_asistencia")
                if est in ("no_asiste_reemplazado", "no_asiste_sin_reemplazo"):
                    ausencias += 1
                    motivos[(f.get("motivo_ausencia") or "Sin motivo indicado").strip()[:60]] += 1
                    continue
                fr = _fecha(f.get("fecha_relleno"))
                if not fr:
                    continue
                did = f.get("doctora_evaluadora_id")
                nombre_doc = docs.get(did) or f.get("doctor_nombre") or "Sin doctora"
                d = por_doc[nombre_doc]
                d["total"] += 1
                dias = (hoy - fr).days
                if 0 <= dias < 7:
                    d["d7"] += 1
                if 0 <= dias < 30:
                    d["d30"] += 1
                if n.get("nombre_colegio"):
                    d["colegios"].add(n["nombre_colegio"].strip())
                d["esp"][_especialidad(n)] += 1
                if 0 <= dias < 7 * 53:
                    por_dia[fr.isoformat()] += 1
                evaluadas.append((fr, f, n, nombre_doc))

            doctoras = sorted(({"nombre": k, "total": v["total"], "d7": v["d7"], "d30": v["d30"],
                                "colegios": len(v["colegios"]),
                                "especialidad": v["esp"].most_common(1)[0][0] if v["esp"] else ""}
                               for k, v in por_doc.items()), key=lambda x: -x["total"])

            # Mapa de calor: 53 semanas hacia atrás, de lunes a domingo
            inicio = hoy - timedelta(days=hoy.weekday()) - timedelta(weeks=52)
            calor = [{"fecha": (inicio + timedelta(days=i)).isoformat(),
                      "n": por_dia.get((inicio + timedelta(days=i)).isoformat(), 0)}
                     for i in range((hoy - inicio).days + 1)]

            # ── Correcciones ──
            corr = [c for c in _get_todo("solicitudes_correccion?select=id,alumno_id,estado,fecha_resolucion,detalles_correccion&order=id.desc")
                    if c.get("alumno_id") in ids_scope]
            corr_estado = Counter(_estado_correccion(c.get("estado")) for c in corr)
            corr_colegio = Counter()
            for c in corr:
                f = ids_scope.get(c.get("alumno_id")) or {}
                col = ((noms.get(f.get("nomina_id")) or {}).get("nombre_colegio") or "Sin colegio").strip()
                corr_colegio[col] += 1

            # ── Actividad reciente (evaluaciones y correcciones) ──
            evaluadas.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
            eventos = [{"tipo": "evaluacion", "fecha": fr.isoformat(), "estudiante": f.get("nombre"),
                        "doctora": nd, "colegio": (n.get("nombre_colegio") or "").strip(), "especialidad": _especialidad(n)}
                       for fr, f, n, nd in evaluadas[:30]]
            for c in sorted(corr, key=lambda c: (str(c.get("fecha_resolucion") or ""), c.get("id") or 0), reverse=True)[:15]:
                f = ids_scope.get(c.get("alumno_id")) or {}
                eventos.append({"tipo": "correccion", "estado": _estado_correccion(c.get("estado")),
                                "fecha": str(c.get("fecha_resolucion") or "")[:10] or None,
                                "estudiante": f.get("nombre"),
                                "colegio": ((noms.get(f.get("nomina_id")) or {}).get("nombre_colegio") or "").strip(),
                                "detalle": (c.get("detalles_correccion") or "")[:120]})
            eventos.sort(key=lambda e: e["fecha"] or "", reverse=True)

            total_eval = sum(d["total"] for d in doctoras)
            return jsonify({
                "success": True, "hoy": hoy.isoformat(),
                "conectadas": conectadas,
                "ultima_actividad": ultima_vez.isoformat() if ultima_vez else None,
                "eventos": eventos[:40],
                "doctoras": doctoras,
                "calor": calor,
                "correcciones": {"total": len(corr), "por_estado": dict(corr_estado),
                                 "tasa": round(100 * len(corr) / total_eval, 1) if total_eval else None,
                                 "por_colegio": [{"colegio": k, "n": v} for k, v in corr_colegio.most_common(8)]},
                "ausencias": {"total": ausencias, "motivos": [{"motivo": k, "n": v} for k, v in motivos.most_common(5)]},
            })
        except Exception as e:
            print(f"ERROR api_coordinadora_actividad: {e}")
            return jsonify({"success": False, "message": "No se pudo cargar la actividad"}), 500

    return bp
