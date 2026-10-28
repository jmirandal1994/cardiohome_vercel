# -*- coding: utf-8 -*-
"""
Lecturas masivas de estudiantes_nomina para los paneles de rendimiento.

Antes, cada panel hacía varias consultas por nómina, una detrás de otra
(una coordinadora con 40 nóminas generaba ~280 llamadas a Supabase).
Aquí se traen las filas de muchas nóminas a la vez, en bloques y en paralelo,
y los conteos se hacen en memoria. Los resultados son los mismos.
"""
from concurrent.futures import ThreadPoolExecutor

import requests

IDS_POR_BLOQUE = 80      # nóminas por consulta (mantiene la URL corta)
FILAS_POR_PAGINA = 1000  # límite típico de PostgREST
HILOS = 8


def cargar_filas_nominas(supabase_url, headers, nomina_ids, select, filtro="", order="id.asc"):
    """Devuelve todas las filas de estudiantes_nomina de esas nóminas.

    filtro: condiciones PostgREST adicionales, p. ej. "estado_asistencia=in.(activo,extra)".
    """
    ids = [str(i) for i in dict.fromkeys(nomina_ids) if i]
    if not ids:
        return []
    bloques = [ids[i:i + IDS_POR_BLOQUE] for i in range(0, len(ids), IDS_POR_BLOQUE)]
    base_h = {k: v for k, v in headers.items() if k.lower() != "prefer"}

    def url_de(bloque):
        u = f"{supabase_url}/rest/v1/estudiantes_nomina?select={select}&nomina_id=in.({','.join(bloque)})"
        if filtro:
            u += "&" + filtro.lstrip("&")
        if order:
            u += f"&order={order}"
        return u

    def total_de(bloque):
        r = requests.get(url_de(bloque), headers={**base_h, "Prefer": "count=exact", "Range": "0-0"}, timeout=30)
        r.raise_for_status()
        try:
            return int(r.headers.get("Content-Range", "0/0").split("/")[-1])
        except ValueError:
            return 0

    def pagina(tarea):
        bloque, ini, fin = tarea
        r = requests.get(url_de(bloque), headers={**base_h, "Range": f"{ini}-{fin}"}, timeout=30)
        r.raise_for_status()
        return r.json()

    with ThreadPoolExecutor(max_workers=HILOS) as ex:
        totales = list(ex.map(total_de, bloques))
        tareas = [(b, ini, min(ini + FILAS_POR_PAGINA, t) - 1)
                  for b, t in zip(bloques, totales) for ini in range(0, t, FILAS_POR_PAGINA)]
        filas = []
        for parte in ex.map(pagina, tareas):  # map conserva el orden de las tareas
            filas.extend(parte)
    return filas
