# -*- coding: utf-8 -*-
"""
Bitácora de actividad y avance del día por doctora.

1) Registro automático (best-effort): después de cada petición a las rutas de la
   lista RUTAS se inserta una fila en la tabla `bitacora_actividad`. Nunca
   interrumpe la petición original: cualquier error se ignora y, si la tabla aún
   no existe, el registro se pausa 10 minutos.

2) Lectura:
   GET /api/bitacora          (admin / coordinadora) eventos de la bitácora y,
                              para una doctora, sus evaluaciones día a día.
   GET /api/presencia/hoy     (admin / coordinadora) evaluaciones cerradas hoy
                              por cada doctora y en qué colegios.
"""
import time
from collections import Counter, defaultdict
from datetime import date, timedelta

import requests
from flask import Blueprint, g, jsonify, request, session

TABLA = "bitacora_actividad"

# regla de la ruta → (acción, método)
RUTAS = {
    "/login": ("inicio_sesion", "POST"),
    "/logout": ("cierre_sesion", "GET"),
    "/relleno_formulario/<string:nomina_id>": ("abrir_nomina", "GET"),
    "/marcar_evaluado": ("evaluacion_cerrada", "POST"),
    "/generar_pdf": ("pdf_generado", "POST"),
    "/guardar_evaluacion": ("evaluacion_editada", "POST"),
    "/api/estudiante/estado_ausencia": ("asistencia_cambiada", "POST"),
    "/api/correccion/solicitar": ("correccion_solicitada", "POST"),
    "/api/correcciones/actualizar_estado": ("correccion_resuelta", "POST"),
    "/descargar_pdf_alumno/<alumno_id>": ("descarga", "GET"),
    "/descargar_excel_evaluados/<nomina_id>": ("descarga", "GET"),
    "/generar_zip_pdfs_evaluados": ("descarga", "POST"),
    "/generar_pdfs_visibles": ("descarga", "POST"),
    "/api/admin/listado_alumnos_excel": ("descarga", "POST"),
    "/api/admin/listado_alumnos_pdf": ("descarga", "POST"),
    "/api/coordinador_escuela/excel/<path:school_id>": ("descarga", "GET"),
    "/api/coordinadora/export_listado": ("descarga", "GET"),
    "/api/coordinadora/export_pdf": ("descarga", "GET"),
    "/api/salud/reporte": ("descarga", "GET"),
}

ETIQUETAS = {
    "inicio_sesion": "Inició sesión",
    "inicio_fallido": "Intento de inicio de sesión fallido",
    "cierre_sesion": "Cerró sesión",
    "abrir_nomina": "Abrió la nómina",
    "evaluacion_cerrada": "Cerró una evaluación",
    "pdf_generado": "Generó el informe PDF",
    "evaluacion_editada": "Editó una evaluación",
    "asistencia_cambiada": "Cambió la asistencia",
    "correccion_solicitada": "Solicitó una corrección",
    "correccion_resuelta": "Resolvió una corrección",
    "descarga": "Descargó un archivo",
}


def _txt(v, n=120):
    return None if v in (None, "") else str(v)[:n]


def crear_blueprint_bitacora(supabase_url, headers):
    bp = Blueprint("bitacora", __name__)
    h = {k: v for k, v in headers.items() if k.lower() != "prefer"}
    http = requests.Session()
    estado = {"pausa_hasta": 0.0}

    # ───────────────────────── registro ─────────────────────────
    def registrar(fila):
        if time.time() < estado["pausa_hasta"]:
            return
        try:
            r = http.post(f"{supabase_url}/rest/v1/{TABLA}", json=fila,
                          headers={**h, "Prefer": "return=minimal"}, timeout=(1.5, 2.5))
            if r.status_code in (404, 400) and ("PGRST205" in r.text or "does not exist" in r.text or "Could not find" in r.text):
                estado["pausa_hasta"] = time.time() + 600
        except Exception:
            estado["pausa_hasta"] = time.time() + 60

    @bp.before_app_request
    def _antes():
        g._bit_quien = (session.get("usuario_id"), session.get("usuario"), session.get("nombre"))

    @bp.after_app_request
    def _despues(resp):
        try:
            regla = request.url_rule.rule if request.url_rule else None
            conf = RUTAS.get(regla)
            if not conf or request.method != conf[1]:
                return resp
            accion = conf[0]
            if accion == "cierre_sesion":
                uid, rol, nombre = getattr(g, "_bit_quien", (None, None, None))
            else:
                uid, rol, nombre = session.get("usuario_id"), session.get("usuario"), session.get("nombre")

            if accion == "inicio_sesion":
                ok = resp.status_code in (301, 302, 303) and uid and "dashboard" in (resp.headers.get("Location") or "")
                if not ok:
                    accion = "inicio_fallido"
                    uid, rol = None, None
                    nombre = _txt(request.form.get("username"), 80)  # nunca se guarda la contraseña
            elif resp.status_code >= 400:
                return resp
            elif resp.mimetype == "application/json":
                j = resp.get_json(silent=True)
                if isinstance(j, dict) and j.get("success") is False:
                    return resp
            if not uid and accion != "inicio_fallido":
                return resp

            js = request.get_json(silent=True) if request.is_json else None
            js = js if isinstance(js, dict) else {}
            frm = request.form if request.method == "POST" else {}
            va = request.view_args or {}
            nomina_id = va.get("nomina_id") or frm.get("nomina_id") or js.get("nomina_id")
            if not nomina_id and accion in ("abrir_nomina", "evaluacion_cerrada", "pdf_generado", "evaluacion_editada"):
                nomina_id = session.get("current_nomina_id")
            est_id = frm.get("estudiante_id") or js.get("estudiante_id") or js.get("alumno_id") or va.get("alumno_id")
            detalle = {}
            if accion == "descarga":
                detalle["archivo"] = regla.split("/<")[0].strip("/").replace("api/", "")
                if request.args.get("tipo"):
                    detalle["tipo"] = _txt(request.args.get("tipo"), 40)
            if accion == "asistencia_cambiada":
                detalle["estado"] = _txt(js.get("estado_asistencia"), 40)
            if accion == "correccion_resuelta":
                detalle["estado"] = _txt(js.get("estado") or js.get("nuevo_estado"), 40)
            if va.get("school_id"):
                detalle["colegio"] = _txt(va.get("school_id"))

            registrar({
                "usuario_id": _txt(uid, 64), "rol": _txt(rol, 30), "nombre": _txt(nombre, 120),
                "accion": accion, "nomina_id": _txt(nomina_id, 64), "estudiante_id": _txt(est_id, 64),
                "detalle": detalle or None,
                "ip": _txt((request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip(), 60),
            })
        except Exception:
            pass
        return resp

    # ───────────────────────── lectura ─────────────────────────
    def _get(path, rango=None):
        hh = {**h, "Range": rango} if rango else h
        r = http.get(f"{supabase_url}/rest/v1/{path}", headers=hh, timeout=20)
        r.raise_for_status()
        return r.json()

    def _get_todo(path, maximo=20000):
        filas, ini = [], 0
        while ini < maximo:
            parte = _get(path, f"{ini}-{ini + 999}")
            filas.extend(parte)
            if len(parte) < 1000:
                break
            ini += 1000
        return filas

    def _nombres_nominas(ids):
        ids = [i for i in {str(x) for x in ids if x} if len(i) < 64]
        out = {}
        for k in range(0, len(ids), 80):
            lote = ",".join(ids[k:k + 80])
            try:
                for n in _get(f"nominas_medicas?id=in.({lote})&select=id,nombre_colegio,nombre_nomina,form_type"):
                    out[str(n["id"])] = n
            except Exception:
                pass
        return out

    def _nombres_estudiantes(ids):
        ids = [i for i in {str(x) for x in ids if x} if len(i) < 64]
        out = {}
        for k in range(0, len(ids), 80):
            lote = ",".join(ids[k:k + 80])
            try:
                for e in _get(f"estudiantes_nomina?id=in.({lote})&select=id,nombre"):
                    out[str(e["id"])] = e.get("nombre")
            except Exception:
                pass
        return out

    def _alcance_coordinadora(uid):
        """Doctoras y nóminas que puede ver una coordinadora general."""
        noms = _get(f"nominas_medicas?coord_general_id=eq.{uid}&select=id,doctora_id,doctora_id_2,doctora_id_3,doctora_id_4")
        docs = {str(n.get(c)) for n in noms for c in ("doctora_id", "doctora_id_2", "doctora_id_3", "doctora_id_4") if n.get(c)}
        return docs, {str(n["id"]) for n in noms}

    def _permitido():
        return session.get("usuario") in ("admin", "coordinadora")

    @bp.route("/api/presencia/hoy", methods=["GET"])
    def api_presencia_hoy():
        if not _permitido():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            # fecha_relleno se guarda con date.today() del servidor: se usa la misma referencia
            hoy = date.today().isoformat()
            filas = _get_todo(f"estudiantes_nomina?fecha_relleno=eq.{hoy}&doctora_evaluadora_id=not.is.null"
                              f"&select=doctora_evaluadora_id,nomina_id")
            noms = _nombres_nominas(f.get("nomina_id") for f in filas)
            por_doc = defaultdict(lambda: {"hoy": 0, "colegios": Counter()})
            for f in filas:
                d = por_doc[str(f["doctora_evaluadora_id"])]
                d["hoy"] += 1
                n = noms.get(str(f.get("nomina_id"))) or {}
                d["colegios"][(n.get("nombre_colegio") or n.get("nombre_nomina") or "Sin colegio").strip()] += 1

            # última evaluación con hora, desde la bitácora (si existe)
            ultima = {}
            try:
                for b in _get(f"{TABLA}?accion=eq.evaluacion_cerrada&creado_en=gte.{hoy}T00:00:00"
                              f"&select=usuario_id,creado_en&order=creado_en.desc&limit=500"):
                    ultima.setdefault(str(b.get("usuario_id")), b.get("creado_en"))
            except Exception:
                pass

            return jsonify({"success": True, "fecha": hoy, "total": len(filas),
                            "doctoras": {k: {"hoy": v["hoy"], "ultima_eval": ultima.get(k),
                                             "colegios": [{"colegio": c, "n": n} for c, n in v["colegios"].most_common()]}
                                         for k, v in por_doc.items()}})
        except Exception as e:
            print(f"ERROR api_presencia_hoy: {e}")
            return jsonify({"success": False, "message": "No se pudo calcular el avance de hoy"}), 500

    @bp.route("/api/bitacora", methods=["GET"])
    def api_bitacora():
        if not _permitido():
            return jsonify({"success": False, "message": "No autorizado"}), 403
        try:
            rol, uid_sesion = session.get("usuario"), session.get("usuario_id")
            doc = (request.args.get("usuario_id") or "").strip()
            accion = (request.args.get("accion") or "").strip()
            try:
                dias = max(1, min(90, int(request.args.get("dias", 7))))
            except ValueError:
                dias = 7
            try:
                limite = max(10, min(1000, int(request.args.get("limit", 300))))
            except ValueError:
                limite = 300
            if doc and (len(doc) > 64 or not all(c.isalnum() or c == "-" for c in doc)):
                return jsonify({"success": False, "message": "Doctora inválida"}), 400
            if accion and accion not in ETIQUETAS:
                return jsonify({"success": False, "message": "Acción inválida"}), 400
            desde = date.today() - timedelta(days=dias - 1)

            docs_ok = None
            if rol == "coordinadora":
                docs_ok, _ = _alcance_coordinadora(uid_sesion)
                docs_ok.add(str(uid_sesion))
                if doc and doc not in docs_ok:
                    return jsonify({"success": False, "message": "No autorizado"}), 403

            # Eventos de la bitácora
            disponible, eventos = True, []
            q = f"{TABLA}?creado_en=gte.{desde.isoformat()}T00:00:00&order=creado_en.desc&limit={limite}" \
                f"&select=id,creado_en,usuario_id,rol,nombre,accion,nomina_id,estudiante_id,detalle"
            if doc:
                q += f"&usuario_id=eq.{doc}"
            if accion:
                q += f"&accion=eq.{accion}"
            try:
                eventos = _get(q)
            except requests.HTTPError:
                disponible = False
            if docs_ok is not None:
                eventos = [e for e in eventos if str(e.get("usuario_id")) in docs_ok]

            # Evaluaciones día a día de la doctora (existe aunque la bitácora sea nueva)
            por_dia = []
            if doc:
                filas = _get_todo(f"estudiantes_nomina?doctora_evaluadora_id=eq.{doc}"
                                  f"&fecha_relleno=gte.{desde.isoformat()}&select=fecha_relleno,nomina_id")
                noms_f = _nombres_nominas(f.get("nomina_id") for f in filas)
                agg = defaultdict(Counter)
                for f in filas:
                    n = noms_f.get(str(f.get("nomina_id"))) or {}
                    agg[str(f.get("fecha_relleno"))[:10]][(n.get("nombre_colegio") or n.get("nombre_nomina") or "Sin colegio").strip()] += 1
                por_dia = [{"fecha": d, "total": sum(c.values()), "colegios": [{"colegio": k, "n": v} for k, v in c.most_common()]}
                           for d, c in sorted(agg.items(), reverse=True)]

            noms = _nombres_nominas(e.get("nomina_id") for e in eventos)
            ests = _nombres_estudiantes(e.get("estudiante_id") for e in eventos)
            for e in eventos:
                n = noms.get(str(e.get("nomina_id"))) or {}
                e["colegio"] = (n.get("nombre_colegio") or n.get("nombre_nomina") or "").strip() or None
                e["estudiante"] = ests.get(str(e.get("estudiante_id")))
                e["texto"] = ETIQUETAS.get(e.get("accion"), e.get("accion"))

            return jsonify({"success": True, "disponible": disponible, "desde": desde.isoformat(),
                            "eventos": eventos, "evaluaciones_por_dia": por_dia})
        except Exception as e:
            print(f"ERROR api_bitacora: {e}")
            return jsonify({"success": False, "message": "No se pudo cargar la bitácora"}), 500

    return bp
