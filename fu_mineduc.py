"""Formulario Único de Evaluación de Salud (Mineduc, Decreto 170) en formato texto.
Toma los datos de una evaluación de Medicina Familiar y los escribe como texto
corrido sobre el formulario oficial, sin casillas."""
import io, os, re
from datetime import date, datetime
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import simpleSplit, ImageReader
from PyPDF2 import PdfReader, PdfWriter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FU_BASE = os.path.join(BASE_DIR, 'static', 'fu', 'FU_EVALUACION_SALUD_2024.pdf')
PH = 841.92  # alto A4

# Datos del profesional por doctora_id
PROFESIONALES = {
    'f6ac8f25-019d-4df6-aa6a-f38a8419ca5e': {
        'nombre': 'Marlene Ximena Yáñez Negrón', 'rut': '13.157.574-2', 'registro': '6420',
        'especialidad': 'Medicina Familiar', 'contacto': 'contacto@cardiohome.cl',
        'timbre': 'timbre_f6ac8f25.png', 'firma': 'firma_f6ac8f25.png',
    },
}

def _si(v):
    return v is True or (isinstance(v, str) and v.strip().lower() in ('x', 'on', 'true', '1', 'si', 'sí')) or v == 1

def _txt(v):
    s = '' if v is None else str(v).strip()
    return '' if s.lower() in ('none', 'null') else s

def _fecha(v):
    s = _txt(v)
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try: return datetime.strptime(s[:10], fmt).strftime('%d/%m/%Y')
        except Exception: pass
    return s

def _edad(fnac, feval):
    try:
        n = datetime.strptime(_txt(fnac)[:10], '%Y-%m-%d').date()
        e = datetime.strptime(_txt(feval)[:10], '%Y-%m-%d').date() if _txt(feval) else date.today()
        meses = (e.year - n.year) * 12 + e.month - n.month - (1 if e.day < n.day else 0)
        return f"{meses // 12} años {meses % 12} meses"
    except Exception:
        return ''

def _lista(est, pares):
    return [t for k, t in pares if _si(est.get(k))]

def _frase(titulo, items, obs=''):
    partes = ', '.join(items)
    obs = _txt(obs)
    obs = obs.strip().rstrip('.').strip()
    if obs and obs.upper() != 'NO INFORMADO':
        partes = f"{partes}. {obs}" if partes else obs
    elif obs.upper() == 'NO INFORMADO' and not partes:
        partes = 'no informado'
    return f"{titulo}: {partes}." if partes else ''

def texto_examen(est):
    l = []
    l.append(_frase('Antecedentes perinatales',
        _lista(est, [('check_vaginal','parto vaginal'),('check_cesarea','parto por cesárea'),('check_atermino','recién nacido a término'),('check_prematuro','prematuro')]), est.get('observacion_1')))
    l.append(_frase('Desarrollo psicomotor',
        _lista(est, [('check_acorde','logrado acorde a la edad'),('check_retraso','retraso del lenguaje'),('check_retrasogeneralizado','retraso generalizado del desarrollo')]), est.get('observacion_2')))
    l.append(_frase('Vacunas', _lista(est, [('check_esquemac','esquema completo'),('check_esquemai','esquema incompleto')])))
    l.append(_frase('Alergias', _lista(est, [('check_alergiano','no refiere'),('check_alergiasi','sí')]), est.get('observacion_3')))
    ap = ' '.join(x for x in (_txt(est.get('observacion_4')), _txt(est.get('observacion_5'))) if x)
    if ap: l.append(f"Antecedentes personales: {ap.rstrip('.')}.")
    l.append(_frase('Hospitalizaciones/cirugías', _lista(est, [('check_cirugiano','no refiere'),('check_cirugiasi','sí')]), est.get('observacion_6')))
    l.append(_frase('Visión', _lista(est, [('check_visionsinalteracion','sin alteración'),('check_visionrefraccion','vicios de refracción')]), est.get('observacion_7')))
    l.append(_frase('Audición', _lista(est, [('check_audicionnormal','normal'),('check_tapondecerumen','tapón de cerumen'),('check_hipoacusia','hipoacusia')])))
    l.append(_frase('Salud bucodental', _lista(est, [('check_sinhallazgos','sin hallazgos'),('check_caries','caries'),('check_apinamientodental','apiñamiento dental'),('check_retenciondental','retención dental'),('check_frenillolingual','frenillo lingual'),('check_hipertrofia','hipertrofia amigdalina')])))
    antro = []
    if _txt(est.get('altura')): antro.append(f"talla {_txt(est.get('altura'))} cm")
    if _txt(est.get('peso')): antro.append(f"peso {_txt(est.get('peso'))} kg")
    if _txt(est.get('imc')): antro.append(f"IMC {_txt(est.get('imc'))}")
    clas = _txt(est.get('clasificacion_imc')) or _txt(est.get('clasificacion'))
    if clas: antro.append(f"clasificación nutricional: {clas}")
    if antro: l.append('Antropometría: ' + ', '.join(antro) + '.')
    return '\n'.join(x for x in l if x)

def texto_diagnostico(est):
    d = _txt(est.get('diagnostico_1')) or _txt(est.get('diagnostico_2'))
    c = _txt(est.get('diagnostico_complementario'))
    out = []
    if d: out.append(d.rstrip('.') + '.')
    if c: out.append(f"Diagnóstico complementario: {c.rstrip('.')}.")
    return '\n'.join(out)

def texto_indicaciones(est):
    out = []
    i = _txt(est.get('indicaciones')); dv = _txt(est.get('derivaciones'))
    if i: out.append(i)
    if dv: out.append(f"Derivaciones: {dv}")
    return '\n'.join(out)

def _escribe(c, valor, x0, ytop, x1, ybot, fs=9, fs_min=6.5, font='Helvetica'):
    """Escribe texto con salto de línea dentro de un cuadro (coordenadas desde arriba)."""
    valor = _txt(valor)
    if not valor: return
    w = x1 - x0 - 6; h = ybot - ytop - 4
    def partir(f):
        ls = []
        for par in valor.splitlines():
            ls.extend(simpleSplit(par, font, f, w) or [''])
        return ls
    lines = partir(fs)
    while len(lines) * fs * 1.3 > h and fs > fs_min:
        fs -= 0.25; lines = partir(fs)
    c.setFont(font, fs)
    y = PH - ytop - fs - 2
    for ln in lines:
        if y < PH - ybot: break
        c.drawString(x0 + 3, y, ln); y -= fs * 1.3

def _campo(c, valor, x0, ytop, x1, ybot, fs=9):
    valor = _txt(valor)
    if not valor: return
    while fs > 6 and c.stringWidth(valor, 'Helvetica', fs) > (x1 - x0 - 4): fs -= 0.25
    c.setFont('Helvetica', fs)
    c.drawString(x0 + 2, PH - ybot + 2.5, valor)

def _x(c, x, ytop):
    c.setFont('Helvetica-Bold', 9); c.drawString(x, PH - ytop - 8, 'X')

def crear_base_fu(doctora_id, salida):
    """Crea el PDF base: formulario Mineduc con los datos fijos, firma y timbre de la doctora."""
    prof = PROFESIONALES[doctora_id]
    buf = io.BytesIO(); c = rl_canvas.Canvas(buf, pagesize=(595.2, PH))
    _x(c, 51.3, 171.5)  # Motivo: examen general de salud
    _campo(c, prof['nombre'], 47, 194, 368, 208)
    _campo(c, prof['rut'], 371, 194, 473, 208)
    _campo(c, prof['registro'], 476, 194, 548, 208)
    _campo(c, prof['especialidad'], 47, 218, 236, 232)
    _x(c, 354.6, 229.4)  # Procedencia: Escuela
    _campo(c, prof['contacto'], 47, 245, 198, 259)
    d = os.path.join(BASE_DIR, 'static', 'fu')
    c.drawImage(ImageReader(os.path.join(d, prof['timbre'])), 392, PH - 782, width=105, height=41, mask='auto')
    c.drawImage(ImageReader(os.path.join(d, prof['firma'])), 480, PH - 785, width=52, height=92, mask='auto')
    c.setTitle('FORMULARIO UNICO EVALUACION DE SALUD')
    c.save(); buf.seek(0)
    pg = PdfReader(FU_BASE).pages[0]; pg.merge_page(PdfReader(buf).pages[0])
    w = PdfWriter(); w.add_page(pg)
    w.add_metadata({'/Title': 'FORMULARIO UNICO EVALUACION DE SALUD'})
    with open(salida, 'wb') as f: w.write(f)

def es_base_fu(pdf_base_path):
    """True si el PDF base es el Formulario Único Mineduc (A4) y no el formulario de casillas (carta)."""
    try:
        r = PdfReader(pdf_base_path)
        if '/Title' in (r.metadata or {}) and 'FORMULARIO UNICO' in str(r.metadata.get('/Title', '')).upper():
            return True
        return float(r.pages[0].mediabox.width) < 600
    except Exception:
        return False

def generar_fu_desde_campos(pdf_base_path, campos):
    """Recibe el mismo diccionario 'campos' que generar_pdf_familiar_overlay y devuelve el PDF en formato texto."""
    est = dict(campos)
    est['sexo'] = 'F' if _si(campos.get('sexo_f')) else ('M' if _si(campos.get('sexo_m')) else '')
    est['clasificacion_imc'] = campos.get('clasificacion', '')
    buf = io.BytesIO(); c = rl_canvas.Canvas(buf, pagesize=(595.2, PH))
    c.setFillColorRGB(0, 0, 0)
    _campo(c, est.get('nombre'), 47, 104, 368, 118)
    if est['sexo'] == 'F': _x(c, 380.2, 105.5)
    if est['sexo'] == 'M': _x(c, 417.2, 105.5)
    _campo(c, est.get('rut'), 438, 104, 548, 118)
    _campo(c, _fecha(est.get('fecha_nacimiento')), 47, 127, 152, 141)
    edad = _txt(est.get('edad'))
    if edad.isdigit(): edad = f"{edad} años"
    _campo(c, edad, 152, 127, 243, 141)
    _campo(c, _txt(est.get('nacionalidad')) or 'Chilena', 244, 127, 333, 141)
    _campo(c, 'Español', 335, 127, 440, 141)
    _campo(c, 'Español', 443, 127, 548, 141)
    _campo(c, _fecha(est.get('fecha_evaluacion')), 200, 245, 368, 259)
    _campo(c, _fecha(est.get('fecha_reevaluacion')), 371, 245, 548, 259)
    # Diagnóstico de discapacidad o déficit (mismo texto del diagnóstico)
    diag = (_txt(est.get('diagnostico_1')) or _txt(est.get('diagnostico_2'))).rstrip('.')
    ancho = 548 - 413 - 4
    if diag and c.stringWidth(diag, 'Helvetica', 6.5) > ancho:
        corto = re.split(r'[,;.]', diag)[0].strip()
        while corto and c.stringWidth(corto + '…', 'Helvetica', 6.5) > ancho:
            corto = corto[:-1].rstrip()
        diag = corto if corto == re.split(r'[,;.]', diag)[0].strip() else corto + '…'
    _campo(c, diag, 413, 169, 548, 182, fs=8)
    _escribe(c, texto_examen(est), 47, 321, 548, 441, fs=8.5)
    _escribe(c, texto_diagnostico(est), 47, 478, 548, 542, fs=9)
    _escribe(c, texto_indicaciones(est), 47, 581, 548, 707, fs=8.5)
    c.save(); buf.seek(0)
    pg = PdfReader(pdf_base_path).pages[0]; pg.merge_page(PdfReader(buf).pages[0])
    w = PdfWriter(); w.add_page(pg); out = io.BytesIO(); w.write(out)
    return out.getvalue()
