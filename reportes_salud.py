# -*- coding: utf-8 -*-
"""Reportes en Excel del módulo Salud de estudiantes (alertas, nutrición, derivaciones y diagnósticos PIE)."""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "0F3460"
GRIS = "F3F6F9"
LINEA = Side(style="thin", color="DDE3EA")
BORDE = Border(left=LINEA, right=LINEA, top=LINEA, bottom=LINEA)

ESTADOS = {
    "vencida": ("Vencida", "FEE2E2", "B91C1C"),
    "urgente": ("Próximos 30 días", "FFEDD5", "C2410C"),
    "proxima": ("En 31 a 90 días", "FEF3C7", "B45309"),
    "este_anio": ("Dentro de 12 meses", "E0ECFF", "1D4ED8"),
    "en_plazo": ("Al día", "DCFCE7", "15803D"),
    "fecha_a_revisar": ("Fecha a revisar", "EDE9FE", "6D28D9"),
    "sin_fecha": ("Sin fecha", "EEF2F6", "475569"),
}
CLASES = ["Normal", "Sobrepeso", "Obesidad", "Bajo peso"]
ALCANCE = "Medicina Familiar"  # nutrición, derivaciones y diagnósticos consideran solo estas nóminas
CORTO = {"Otorrinolaringología": "Otorrino"}
# Misma escala y umbrales que la matriz de la pantalla (static/salud_estudiantes.js)
RAMPA_MATRIZ = ["EEF4FB", "CDE2FB", "B7D3F6", "9EC5F4", "86B6EF", "6DA7EC", "5598E7", "3987E5", "2A78D6", "256ABF", "1C5CAB", "184F95", "104281"]
TOPE_MATRIZ, MIN_EVALUADOS = 60, 10


def _color_matriz(p):
    k = 0 if p <= 0 else min(len(RAMPA_MATRIZ) - 1, 1 + int(p // (TOPE_MATRIZ / (len(RAMPA_MATRIZ) - 1))))
    return RAMPA_MATRIZ[k], ("FFFFFF" if k >= 8 else "0F172A")


def _f(iso):
    if not iso:
        return None
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _rut(r):
    n = "".join(ch for ch in str(r or "").upper() if ch.isdigit() or ch == "K")
    if len(n) < 2:
        return r or ""
    c = f"{int(n[:-1]):,}".replace(",", ".") if n[:-1].isdigit() else n[:-1]
    return f"{c}-{n[-1]}"


def _titulo(ws, texto, sub, ancho):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ancho)
    ws.cell(1, 1, texto).font = Font(bold=True, size=15, color=AZUL)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ancho)
    ws.cell(2, 1, sub).font = Font(size=10, color="5B6B7A")
    ws.row_dimensions[1].height = 24


def _tabla(ws, fila, encabezados, filas, anchos=None):
    for j, h in enumerate(encabezados, 1):
        c = ws.cell(fila, j, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(vertical="center", wrap_text=True)
        c.border = BORDE
    ws.row_dimensions[fila].height = 30
    for i, r in enumerate(filas, fila + 1):
        for j, v in enumerate(r, 1):
            c = ws.cell(i, j, v)
            c.border = BORDE
            c.alignment = Alignment(vertical="center", wrap_text=isinstance(v, str) and len(v) > 40)
            if (i - fila) % 2 == 0:
                c.fill = PatternFill("solid", fgColor=GRIS)
            if isinstance(v, date):
                c.number_format = "DD/MM/YYYY"
    if anchos:
        for j, w in enumerate(anchos, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.auto_filter.ref = f"A{fila}:{get_column_letter(len(encabezados))}{fila + max(1, len(filas))}"
    ws.freeze_panes = ws.cell(fila + 1, 1)
    return fila + len(filas) + 1


def _hoja_resumen(wb, datos, filtros):
    ws = wb.active
    ws.title = "Resumen"
    _titulo(ws, "Reporte de salud de estudiantes · Cardiohome",
            f"Generado el {date.today().strftime('%d/%m/%Y')}", 4)
    fila = 4
    for k, v in filtros.items():
        ws.cell(fila, 1, k).font = Font(bold=True, color="5B6B7A")
        ws.cell(fila, 2, v)
        fila += 1
    fila += 1
    if "reev" in datos:
        r = datos["reev"]
        ws.cell(fila, 1, "Alertas de reevaluación").font = Font(bold=True, size=12, color=AZUL)
        fila += 1
        for k in ("vencida", "urgente", "proxima", "este_anio", "en_plazo", "fecha_a_revisar", "sin_fecha"):
            lab, bg, fg = ESTADOS[k]
            a = ws.cell(fila, 1, lab)
            a.fill = PatternFill("solid", fgColor=bg)
            a.font = Font(bold=True, color=fg)
            ws.cell(fila, 2, r["conteo"].get(k, 0))
            fila += 1
        ws.cell(fila, 1, "Total estudiantes (por especialidad)").font = Font(bold=True)
        ws.cell(fila, 2, r["total_estudiantes"])
        fila += 2
    if "nutri" in datos:
        n = datos["nutri"]
        ws.cell(fila, 1, f"Estado nutricional {n['anio']} · {ALCANCE}").font = Font(bold=True, size=12, color=AZUL)
        fila += 1
        tot = n["clasificados"] or 1
        for k in CLASES:
            ws.cell(fila, 1, k)
            ws.cell(fila, 2, n["distribucion"][k])
            c = ws.cell(fila, 3, n["distribucion"][k] / tot)
            c.number_format = "0.0%"
            fila += 1
        ws.cell(fila, 1, "Estudiantes medidos").font = Font(bold=True)
        ws.cell(fila, 2, n["clasificados"])
        fila += 1
        ws.cell(fila, 1, "Malnutrición por exceso").font = Font(bold=True)
        ws.cell(fila, 2, n["distribucion"]["Sobrepeso"] + n["distribucion"]["Obesidad"])
        c = ws.cell(fila, 3, (n["exceso_pct"] or 0) / 100)
        c.number_format = "0.0%"
        fila += 1
        if n.get("derivados_nutricion") is not None:
            ws.cell(fila, 1, "Derivados a nutricionista").font = Font(bold=True)
            ws.cell(fila, 2, n["derivados_nutricion"])
            c = ws.cell(fila, 3, n["derivados_nutricion"] / tot)
            c.number_format = "0.0%"
            fila += 1
        fila += 1
    if "deriv" in datos:
        d = datos["deriv"]
        ws.cell(fila, 1, f"Derivaciones por especialidad · {ALCANCE}").font = Font(bold=True, size=12, color=AZUL)
        fila += 1
        for e in d["especialidades"]:
            ws.cell(fila, 1, e["especialidad"])
            ws.cell(fila, 2, e["estudiantes"])
            c = ws.cell(fila, 3, (e["pct"] or 0) / 100)
            c.number_format = "0.0%"
            fila += 1
        ws.cell(fila, 1, "Estudiantes con al menos una derivación").font = Font(bold=True)
        ws.cell(fila, 2, d["derivados"])
        c = ws.cell(fila, 3, (d["derivados_pct"] or 0) / 100)
        c.number_format = "0.0%"
        fila += 1
        ws.cell(fila, 1, "Estudiantes evaluados").font = Font(bold=True)
        ws.cell(fila, 2, d["evaluados"])
        fila += 2
    if "diag" in datos:
        g = datos["diag"]
        ws.cell(fila, 1, f"Diagnósticos PIE · {ALCANCE}").font = Font(bold=True, size=12, color=AZUL)
        fila += 1
        for x in g["grupos"]:
            ws.cell(fila, 1, x["grupo"])
            ws.cell(fila, 2, x["estudiantes"])
            c = ws.cell(fila, 3, (x["pct"] or 0) / 100)
            c.number_format = "0.0%"
            fila += 1
        ws.cell(fila, 1, "Estudiantes con diagnóstico").font = Font(bold=True)
        ws.cell(fila, 2, g["con_diagnostico"])
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 12


def _hoja_reev(wb, r):
    ws = wb.create_sheet("Reevaluaciones")
    _titulo(ws, "Reevaluaciones por estudiante",
            f"Días calculados al {date.fromisoformat(r['hoy']).strftime('%d/%m/%Y')}. Una fila por estudiante y especialidad (la evaluación más reciente).", 8)
    filas = []
    for x in r["lista"]:
        lab = ESTADOS[x["estado"]][0]
        filas.append([x["nombre"], _rut(x["rut"]), x["colegio"], x["especialidad"], _f(x["fecha_evaluacion"]),
                      _f(x["fecha_reevaluacion"]), lab, x["dias"]])
    fin = _tabla(ws, 4, ["Estudiante", "RUT", "Colegio", "Especialidad", "Evaluado", "Reevaluar antes de", "Estado", "Días que faltan"],
                 filas, [32, 14, 34, 18, 12, 16, 20, 14])
    for i in range(5, fin):
        est = ws.cell(i, 7).value
        for k, (lab, bg, fg) in ESTADOS.items():
            if lab == est:
                ws.cell(i, 7).fill = PatternFill("solid", fgColor=bg)
                ws.cell(i, 7).font = Font(bold=True, color=fg)
                break
    ws2 = wb.create_sheet("Reevaluaciones por mes")
    _titulo(ws2, "Reevaluaciones por mes", "Cantidad de estudiantes que deben reevaluarse en cada mes", 2)
    _tabla(ws2, 4, ["Mes", "Estudiantes"], [[m["mes"], m["n"]] for m in r["por_mes"]], [12, 14])
    if r["por_mes"]:
        ch = BarChart()
        ch.title, ch.height, ch.width, ch.legend = "Reevaluaciones por mes", 8, 22, None
        ch.add_data(Reference(ws2, min_col=2, min_row=4, max_row=4 + len(r["por_mes"])), titles_from_data=True)
        ch.set_categories(Reference(ws2, min_col=1, min_row=5, max_row=4 + len(r["por_mes"])))
        ws2.add_chart(ch, "D4")


def _hoja_reev_est(wb, r):
    ws = wb.create_sheet("Reev. por establecimiento")
    _titulo(ws, "Reevaluaciones por establecimiento",
            f"Días calculados al {date.fromisoformat(r['hoy']).strftime('%d/%m/%Y')}. Ordenado por urgencia.", 12)
    filas = [[c["proyecto"], c["colegio"], c["total"], c["conteo"]["vencida"], c["conteo"]["urgente"], c["conteo"]["proxima"],
              c["conteo"]["este_anio"], c["conteo"]["en_plazo"], c["conteo"]["fecha_a_revisar"], c["conteo"]["sin_fecha"],
              c["reevaluados"], _f(c["proxima_fecha"])] for c in r["colegios"]]
    fin = _tabla(ws, 4, ["Proyecto", "Establecimiento", "Estudiantes", "Vencidas", "Próximos 30 días", "En 31 a 90 días",
                         "Dentro de 12 meses", "Al día", "Fecha a revisar", "Sin fecha", "Ya reevaluados", "Próxima fecha"],
                 filas, [20, 38, 12, 10, 12, 12, 12, 9, 11, 10, 12, 13])
    for col, k in ((4, "vencida"), (5, "urgente"), (6, "proxima")):
        lab, bg, fg = ESTADOS[k]
        for i in range(5, fin):
            if ws.cell(i, col).value:
                ws.cell(i, col).fill = PatternFill("solid", fgColor=bg)
                ws.cell(i, col).font = Font(bold=True, color=fg)

    ws2 = wb.create_sheet("Alertas por establecimiento")
    _titulo(ws2, "Estudiantes a reevaluar, separados por establecimiento",
            "Vencidas, próximas y fechas a revisar. Una fila por estudiante y especialidad.", 9)
    filas2 = []
    for c in r["colegios"]:
        for x in c.get("estudiantes", []):
            filas2.append([c["proyecto"], c["colegio"], x["nombre"], _rut(x["rut"]), x["especialidad"],
                           _f(x["fecha_evaluacion"]), _f(x["fecha_reevaluacion"]), ESTADOS[x["estado"]][0], x["dias"]])
    fin2 = _tabla(ws2, 4, ["Proyecto", "Establecimiento", "Estudiante", "RUT", "Especialidad", "Evaluado",
                           "Reevaluar antes de", "Estado", "Días que faltan"],
                  filas2, [20, 36, 32, 14, 18, 12, 16, 20, 14])
    for i in range(5, fin2):
        est = ws2.cell(i, 8).value
        for lab, bg, fg in ESTADOS.values():
            if lab == est:
                ws2.cell(i, 8).fill = PatternFill("solid", fgColor=bg)
                ws2.cell(i, 8).font = Font(bold=True, color=fg)
                break


def _hoja_nutri(wb, n):
    ws = wb.create_sheet("Nutrición por colegio")
    _titulo(ws, f"Estado nutricional por colegio · {n['anio']} · {ALCANCE}",
            f"Una medición por estudiante. Clasificación registrada por la doctora. Promedio de exceso de peso: {n['exceso_pct'] or 0:.0f}%.", 8)
    filas = [[c["colegio"], c["total"], c["Normal"], c["Sobrepeso"], c["Obesidad"], c["Bajo peso"],
              (c["exceso_pct"] or 0) / 100, (c["bajo_pct"] or 0) / 100] for c in n["colegios"]]
    fin = _tabla(ws, 4, ["Colegio", "Medidos", "Normal", "Sobrepeso", "Obesidad", "Bajo peso", "% exceso de peso", "% bajo peso"],
                 filas, [40, 11, 10, 12, 11, 11, 16, 12])
    for i in range(5, fin):
        ws.cell(i, 7).number_format = "0.0%"
        ws.cell(i, 8).number_format = "0.0%"
    ws.cell(fin + 1, 1, "Distribución").font = Font(bold=True, color=AZUL)
    for k_i, k in enumerate(CLASES):
        ws.cell(fin + 2 + k_i, 1, k)
        ws.cell(fin + 2 + k_i, 2, n["distribucion"][k])
    ch = DoughnutChart()
    ch.title, ch.height, ch.width = "Estado nutricional", 8, 12
    ch.add_data(Reference(ws, min_col=2, min_row=fin + 2, max_row=fin + 5))
    ch.set_categories(Reference(ws, min_col=1, min_row=fin + 2, max_row=fin + 5))
    ws.add_chart(ch, f"J4")

    ws2 = wb.create_sheet("Estado por edad")
    _titulo(ws2, f"Estado nutricional por edad · {n['anio']} · {ALCANCE}", "% de cada clasificación en cada rango de edad. Una medición por estudiante.", 7)
    rangos = [r for r in n.get("por_rango", []) if r["rango"] != "Sin edad válida" and r["total"] >= 5]
    filas2 = [[f"{r['rango']} años", r["total"], r["Bajo peso"] / r["total"], r["Normal"] / r["total"], r["Sobrepeso"] / r["total"],
               r["Obesidad"] / r["total"], (r["Sobrepeso"] + r["Obesidad"]) / r["total"]] for r in rangos]
    fin2 = _tabla(ws2, 4, ["Rango de edad", "Estudiantes", "Bajo peso", "Normal", "Sobrepeso", "Obesidad", "Exceso de peso"],
                  filas2, [16, 12, 11, 11, 12, 11, 15])
    for i in range(5, fin2):
        for j in range(3, 8):
            ws2.cell(i, j).number_format = "0%"
    sin_edad = next((r for r in n.get("por_rango", []) if r["rango"] == "Sin edad válida"), None)
    if sin_edad:
        ws2.cell(fin2 + 1, 1, f"{sin_edad['total']} estudiantes sin fecha de nacimiento válida no se incluyen en esta tabla.").font = Font(italic=True, color="5B6B7A")
    if filas2:
        ch2 = BarChart()
        ch2.type, ch2.grouping, ch2.overlap = "col", "percentStacked", 100
        ch2.title, ch2.height, ch2.width = "Estado nutricional por edad", 9, 16
        ch2.add_data(Reference(ws2, min_col=3, max_col=6, min_row=4, max_row=fin2 - 1), titles_from_data=True)
        ch2.set_categories(Reference(ws2, min_col=1, min_row=5, max_row=fin2 - 1))
        for serie, color in zip(ch2.series, ("2563EB", "16A34A", "D97706", "DC2626")):
            serie.graphicalProperties.solidFill = color
        ws2.add_chart(ch2, "I4")

    ws3 = wb.create_sheet("Datos a revisar")
    _titulo(ws3, f"Mediciones a revisar · {ALCANCE}", "Valores que parecen mal escritos (no se cuentan en las estadísticas)", 6)
    _tabla(ws3, 4, ["Estudiante", "RUT", "Colegio", "Talla", "Peso", "IMC", "Problema"],
           [[r["nombre"], _rut(r["rut"]), r["colegio"], r["altura"], r["peso"], r["imc"], ", ".join(r["problemas"])] for r in n["a_revisar"]],
           [32, 14, 34, 9, 9, 9, 34])


def _hoja_deriv(wb, d):
    ws = wb.create_sheet("Derivaciones")
    _titulo(ws, f"Derivaciones por especialidad · {ALCANCE}",
            f"{d['derivados']} de {d['evaluados']} estudiantes evaluados en {ALCANCE} tienen al menos una derivación", 3)
    filas = [[e["especialidad"], e["estudiantes"], (e["pct"] or 0) / 100] for e in d["especialidades"]]
    fin = _tabla(ws, 4, ["Especialidad", "Estudiantes derivados", "% de evaluados"], filas, [34, 20, 16])
    for i in range(5, fin):
        ws.cell(i, 3).number_format = "0.0%"
    if filas:
        ch = BarChart()
        ch.type, ch.title, ch.height, ch.width, ch.legend = "bar", "Estudiantes derivados", 9, 18, None
        ch.add_data(Reference(ws, min_col=2, min_row=4, max_row=fin - 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=fin - 1))
        ch.y_axis.majorGridlines = None
        ws.add_chart(ch, "E4")

    _hoja_matriz_deriv(wb, d)

    esps = [e["especialidad"] for e in d["especialidades"]]
    ws2 = wb.create_sheet("Conteo por colegio")
    _titulo(ws2, f"Conteo de derivaciones por colegio · {ALCANCE}", "Cantidad de estudiantes derivados, con todas las especialidades", len(esps) + 3)
    _tabla(ws2, 4, ["Colegio", "Evaluados", "Derivados"] + esps,
           [[c["colegio"], c["evaluados"], c["derivados"]] + [c.get(e, 0) for e in esps] for c in d["colegios"]],
           [40, 11, 11] + [14] * len(esps))

    ws3 = wb.create_sheet("Estudiantes derivados")
    _titulo(ws3, f"Listado de estudiantes derivados · {ALCANCE}", "Una fila por evaluación con derivación", 6)
    _tabla(ws3, 4, ["Estudiante", "RUT", "Colegio", "Evaluado por", "Fecha", "Derivado a"],
           [[x["nombre"], _rut(x["rut"]), x["colegio"], x["origen"], _f(x["fecha"]), ", ".join(x["especialidades"])] for x in d["lista"]],
           [32, 14, 34, 18, 12, 46])


def _hoja_matriz_deriv(wb, d):
    """Misma matriz de la pantalla: % de los evaluados de cada colegio, con la misma escala de color."""
    esps = list(d["principales"]) + ["Otras"]
    ws = wb.create_sheet("Derivaciones por colegio")
    _titulo(ws, f"Derivaciones por colegio · {ALCANCE}",
            f"% de los evaluados de cada colegio derivados a cada especialidad. Color más oscuro = mayor %. Colegios con menos de {MIN_EVALUADOS} evaluados al final y en gris.", len(esps) + 4)

    def pct(n, total):
        return (n or 0) / total if total else 0

    orden = lambda c: (-pct(c["derivados"], c["evaluados"]), -c["evaluados"])
    grandes = sorted((c for c in d["colegios"] if c["evaluados"] >= MIN_EVALUADOS), key=orden)
    chicos = sorted((c for c in d["colegios"] if c["evaluados"] < MIN_EVALUADOS), key=orden)
    promedio = {"colegio": "Promedio", "evaluados": d["evaluados"], "derivados": d["derivados"], "Otras": d["otras"],
                **{e["especialidad"]: e["estudiantes"] for e in d["especialidades"]}}
    lista = [promedio] + grandes + chicos
    filas = [[c["colegio"], c["evaluados"], c["derivados"], pct(c["derivados"], c["evaluados"])] +
             [pct(c.get(e), c["evaluados"]) for e in esps] for c in lista]
    fin = _tabla(ws, 4, ["Colegio", "Evaluados", "Derivados", "% derivados"] + [CORTO.get(e, e) for e in esps],
                 filas, [44, 11, 11, 12] + [14] * len(esps))
    for i, c in zip(range(5, fin), lista):
        gris = c["evaluados"] < MIN_EVALUADOS and c is not promedio
        ws.cell(i, 4).number_format = "0%"
        for j in range(5, 5 + len(esps)):
            celda = ws.cell(i, j)
            celda.number_format = "0%"
            celda.alignment = Alignment(horizontal="center", vertical="center")
            if gris:
                celda.fill = PatternFill(fill_type=None)
                celda.font = Font(color="94A3B8")
            else:
                color, tinta = _color_matriz(celda.value * 100)
                celda.fill = PatternFill("solid", fgColor=color)
                celda.font = Font(bold=True, color=tinta)
        if gris:
            for j in range(1, 5):
                ws.cell(i, j).font = Font(color="94A3B8")
                ws.cell(i, j).fill = PatternFill(fill_type=None)
    for j in range(1, 5):
        ws.cell(5, j).font = Font(bold=True)
    ws.freeze_panes = ws.cell(6, 2)  # encabezado, promedio y nombres fijos
    ws.auto_filter.ref = None


def _hoja_diag(wb, g):
    ws = wb.create_sheet("Diagnósticos PIE")
    _titulo(ws, f"Diagnósticos PIE · {ALCANCE}",
            f"{g['con_diagnostico']} de {g['evaluados']} estudiantes evaluados tienen diagnóstico registrado, agrupado en las categorías del Decreto 170.", 3)
    filas = [[x["grupo"], x["estudiantes"], (x["pct"] or 0) / 100] for x in g["grupos"]]
    fin = _tabla(ws, 4, ["Diagnóstico", "Estudiantes", "% de los diagnósticos"], filas, [52, 13, 16])
    for i in range(5, fin):
        ws.cell(i, 3).number_format = "0.0%"
    extra = []
    if g["sin_diagnostico"]:
        extra.append(f"{g['sin_diagnostico']} sin diagnóstico o pendientes")
    if g["otro"]:
        extra.append(f"{g['otro']} con un texto que no calza con ningún grupo")
    if extra:
        ws.cell(fin + 1, 1, "Además: " + " y ".join(extra) + " (no están en la tabla).").font = Font(italic=True, color="5B6B7A")
    if filas:
        ch = BarChart()
        ch.type, ch.title, ch.height, ch.width, ch.legend = "bar", "Estudiantes por diagnóstico", 10, 20, None
        ch.add_data(Reference(ws, min_col=2, min_row=4, max_row=fin - 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=fin - 1))
        ch.y_axis.majorGridlines = None
        ws.add_chart(ch, "E4")

    ws2 = wb.create_sheet("Diagnósticos por colegio")
    _titulo(ws2, f"Diagnósticos por colegio · {ALCANCE}", "Estudiantes con diagnóstico y el diagnóstico más frecuente de cada colegio", 5)
    fin2 = _tabla(ws2, 4, ["Colegio", "Con diagnóstico", "Diagnóstico principal", "Estudiantes", "% del colegio"],
                  [[c["colegio"], c["con_diagnostico"], c["principal"] or "—", c["principal_n"], (c["principal_pct"] or 0) / 100] for c in g["colegios"]],
                  [44, 14, 52, 12, 12])
    for i in range(5, fin2):
        ws2.cell(i, 5).number_format = "0%"


def armar_excel(tipo, datos, filtros):
    wb = Workbook()
    _hoja_resumen(wb, datos, filtros)
    if "reev" in datos:
        _hoja_reev(wb, datos["reev"])
    if "reev_est" in datos:
        _hoja_reev_est(wb, datos["reev_est"])
    if "nutri" in datos:
        _hoja_nutri(wb, datos["nutri"])
    if "deriv" in datos:
        _hoja_deriv(wb, datos["deriv"])
    if "diag" in datos:
        _hoja_diag(wb, datos["diag"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
