from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response, jsonify
import os
import requests
import base64
from werkzeug.utils import secure_filename
from datetime import datetime, date
from openpyxl import load_workbook
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject, NumberObject, DictionaryObject
import mimetypes
import io
import uuid
import json
import pandas as pd
import unicodedata
import zipfile

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}

PDF_BASE_NEUROLOGIA = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_BASE_FAMILIAR = 'formulario_familiar.pdf' 
PDF_BASES_NEUROLOGIA_DIR = 'pdf_bases_doctoras_neurologia'

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IlNJUDU4IiwicmVmIjoiYnhzbnFmZml4d2pkcWl2eGJrZXkiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzE5Mjg3MzI1LCJleHAiOjE3NTA4MjMzMjV9.qNlSg_p4_u1O5xQ9s6bN0K2Z0f0v_N9s8k0k0k0k0k")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json" 
}
SUPABASE_SERVICE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json" 
}

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = os.getenv("SENDGRID_FROM_EMAIL", 'your_sendgrid_email@example.com')
SENDGRID_TO = os.getenv("SENDGRID_ADMIN_EMAIL", 'destination_admin_email@example.com')

def format_rut_python(rut):
    if not rut:
        return ""
    rut = str(rut).replace('.', '').replace('-', '').strip().upper() 
    if not rut:
        return ""
    body = rut[:-1]
    dv = rut[-1]
    formatted_body = ""
    for i, digit in enumerate(reversed(body)):
        if i > 0 and i % 3 == 0:
            formatted_body = "." + formatted_body
        formatted_body = digit + formatted_body
    return f"{formatted_body}-{dv}"

def permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_age(birth_date):
    today = date.today()
    years = today.year - birth_date.year
    months = today.month - birth_date.month
    if months < 0:
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    name_lower = name.lower().strip()
    first_word = name_lower.split(' ')[0]
    nombres_masculinos = ["juan", "pedro", "luis", "carlos", "jose", "manuel", "alejandro", "ignacio", "felipe", "vicente", "emilio", "cristobal", "mauricio", "diego", "jean", "agustin", "joaquin", "thomas", "martin", "angel", "alonso"]
    nombres_femeninos = ["maria", "ana", "sofia", "laura", "paula", "trinidad", "mariana", "lizeth", "alexandra", "lisset"] 
    if first_word in nombres_masculinos:
        return 'M'
    elif first_word in nombres_femeninos:
        return 'F'
    return None

def normalizar(texto):
    if not isinstance(texto, str):
        return ""
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = texto.replace(" ", "_")
    return texto

def enviar_correo_sendgrid(asunto, cuerpo, adjuntos=None):
    if not SENDGRID_API_KEY:
        print("Falta SENDGRID_API_KEY en variables de entorno. No se enviará correo.")
        return
    data = {
        "personalizations": [{"to": [{"email": SENDGRID_TO}]}],
        "from": {"email": SENDGRID_FROM},
        "subject": asunto,
        "content": [{"type": "text/plain", "value": cuerpo}]
    }
    if adjuntos:
        data["attachments"] = [
            {
                "content": adj["content"],
                "filename": adj["filename"],
                "type": "application/octet-stream", 
                "disposition": "attachment"
            } for adj in adjuntos
        ]
    try:
        response = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json"
            },
            json=data
        )
        print(f"Correo enviado, status: {response.status_code}")
        if response.status_code >= 400:
            print(f"Error SendGrid Response: {response.text}")
    except Exception as e:
        print(f"Error al enviar correo con SendGrid: {e}")

def get_form_field_value(field_name, form_data, return_none_if_empty=False):
    value = form_data.get(field_name)
    if value is None:
        return None
    stripped_value = value.strip()
    if not stripped_value:
        return None if return_none_if_empty else ''
    return stripped_value

def get_doctor_specific_neurologia_pdf(doctora_id):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)
    specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{doctora_id}.pdf"
    specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)
    if os.path.exists(specific_pdf_path):
        return specific_pdf_path
    else:
        default_pdf_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
        return default_pdf_path

@app.route('/relleno_formularios/<nomina_id>', methods=['GET'])
def relleno_formularios(nomina_id):
    if 'usuario' not in session:
        return redirect(url_for('index'))
    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {session.get('usuario_id')}")
    nomina_data = None
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina,form_type,doctora_id_para_formulario"
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        if not nomina_data:
            flash("❌ Nómina no encontrada.", 'error')
            return redirect(url_for('dashboard'))
        nomina = nomina_data[0]
        session['establecimiento'] = f"{nomina['nombre_nomina']} ({nomina['tipo_nomina'].replace('_', ' ').title()})"
        session['current_nomina_id'] = nomina_id
        session['establecimiento_nombre'] = nomina['nombre_nomina']
        session['current_form_type'] = nomina.get('form_type', 'neurologia') 
        session['doctora_id_para_formulario'] = nomina.get('doctora_id_para_formulario')
    except requests.exceptions.RequestException as e:
        flash('Error al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash('Error inesperado al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))
    estudiantes = []
    total_forms_completed_for_nomina = 0
    try:
        url_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_SERVICE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        for est in estudiantes_raw:
            if 'fecha_nacimiento' in est and isinstance(est['fecha_nacimiento'], str) and est['fecha_nacimiento'].strip():
                try:
                    fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                    est['edad'] = calculate_age(fecha_nac_obj)
                    est['fecha_nacimiento_formato'] = fecha_nac_obj.strftime("%d/%m/%Y")
                except ValueError:
                    est['fecha_nacimiento_formato'] = 'N/A'
                    est['edad'] = 'N/A'
            else:
                est['fecha_nacimiento_formato'] = 'N/A'
                est['edad'] = 'N/A'
            est['estado_general'] = est.get('estado_general') or ''
            est['diagnostico'] = est.get('diagnostico') or ''
            est['derivaciones'] = est.get('derivaciones') or ''
            est['fecha_evaluacion'] = est.get('fecha_evaluacion') or ''
            est['fecha_reevaluacion'] = est.get('fecha_reevaluacion') or ''
            if est.get('fecha_relleno') is not None:
                total_forms_completed_for_nomina += 0
            estudiantes.append(est)
    except requests.exceptions.RequestException as e:
        flash('Error al cargar la lista de estudiantes.', 'error')
        estudiantes = []
    except Exception as e:
        flash('Error inesperado al cargar la lista de estudiantes.', 'error')
        estudiantes = []
    template_name = 'formulario_relleno.html'
    if session.get('current_form_type') == 'medicina_familiar':
        template_name = 'formulario_medicina_familiar.html'
    return render_template(template_name, 
                           estudiantes=estudiantes, 
                           total_forms_completed_for_nomina=total_forms_completed_for_nomina,
                           establecimiento_nombre=nomina['nombre_nomina'])

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        flash('Debes iniciar sesión para acceder a esta página.', 'danger')
        return redirect(url_for('index'))
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    form_type = session.get('current_form_type', 'neurologia') 
    doctora_id_para_formulario = session.get('doctora_id_para_formulario')
    if not all([estudiante_id, nomina_id]):
        flash("❌ Faltan datos esenciales del formulario para generar PDF.", 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))
    nombre = get_form_field_value('nombre', request.form)
    rut = format_rut_python(get_form_field_value('rut', request.form))
    fecha_nac_formato = ''
    fecha_nac_original_str = get_form_field_value('fecha_nacimiento_original', request.form)
    if fecha_nac_original_str:
        try:
            fecha_nac_formato = datetime.strptime(fecha_nac_original_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass 
    edad = get_form_field_value('edad', request.form)
    nacionalidad = get_form_field_value('nacionalidad', request.form)
    sexo_f_pdf = ""
    sexo_m_pdf = ""
    sexo_form_value = get_form_field_value('sexo', request.form)
    if form_type == 'neurologia':
        sexo_f_pdf = "X" if sexo_form_value == "F" else ""
        sexo_m_pdf = "X" if sexo_form_value == "M" else ""
    elif form_type == 'medicina_familiar':
        sexo_f_pdf = "X" if get_form_field_value('genero_f', request.form) == 'Femenino' else ""
        sexo_m_pdf = "X" if get_form_field_value('genero_m', request.form) == 'Masculino' else ""
    fecha_evaluacion_form_value = get_form_field_value('fecha_evaluacion', request.form)
    fecha_evaluacion_formatted = ''
    if fecha_evaluacion_form_value:
        try:
            fecha_evaluacion_formatted = datetime.strptime(fecha_evaluacion_form_value, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass
    fecha_reevaluacion_form_value = get_form_field_value('fecha_reevaluacion', request.form)
    fecha_reeval_pdf = ''
    if fecha_reevaluacion_form_value:
        try:
            fecha_reeval_pdf = datetime.strptime(fecha_reevaluacion_form_value, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass
    pdf_base_path = ''
    if form_type == 'neurologia':
        if doctora_id_para_formulario:
            pdf_base_path = get_doctor_specific_neurologia_pdf(doctora_id_para_formulario)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
    elif form_type == 'medicina_familiar':
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
    else:
        flash("❌ Tipo de formulario no reconocido para generar PDF.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))
    if not os.path.exists(pdf_base_path):
        flash(f"❌ Error: El archivo '{pdf_base_path}' no se encontró en la carpeta del servidor. Verifique la ruta y el nombre del archivo.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))
    try:
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        campos = {}
        if form_type == 'neurologia':
            campos = {
                "nombre": nombre,
                "rut": rut,
                "fecha_nacimiento": fecha_nac_formato, 
                "nacionalidad": nacionalidad,
                "edad": edad,
                "diagnostico_1": get_form_field_value('diagnostico', request.form),
                "diagnostico_2": get_form_field_value('diagnostico', request.form),
                "estado_general": get_form_field_value('estado', request.form),
                "fecha_evaluacion": fecha_evaluacion_formatted, 
                "fecha_reevaluacion": fecha_reeval_pdf,
                "derivaciones": get_form_field_value('derivaciones', request.form),
                "sexo_f": sexo_f_pdf,
                "sexo_m": sexo_m_pdf,
            }
        elif form_type == 'medicina_familiar':
            campos = {
                "nombre": nombre,
                "rut": rut,
                "fecha_nacimiento": fecha_nac_formato,
                "edad": edad,
                "nacionalidad": nacionalidad,
                "sexo_f": sexo_f_pdf,
                "sexo_m": sexo_m_pdf,
                "diagnostico_1": get_form_field_value('diagnostico_1', request.form),
                "diagnostico_2": get_form_field_value('diagnostico_2', request.form),
                "diagnostico_complementario": get_form_field_value('diagnostico_complementario', request.form),
                "clasificación": get_form_field_value('clasificacion_imc', request.form),
                "derivaciones": get_form_field_value('derivaciones', request.form),
                "fecha_evaluacion": fecha_evaluacion_formatted,
                "fecha_reevaluacion": fecha_reeval_pdf,
                "observacion_1": get_form_field_value('observacion_1', request.form),
                "observacion_2": get_form_field_value('observacion_2', request.form),
                "observacion_3": get_form_field_value('observacion_3', request.form),
                "observacion_4": get_form_field_value('observacion_4', request.form),
                "observacion_5": get_form_field_value('observacion_5', request.form),
                "observacion_6": get_form_field_value('observacion_6', request.form),
                "observacion_7": get_form_field_value('observacion_7', request.form),
                "check_cesarea": "/Yes" if get_form_field_value('check_cesarea', request.form) == 'CESAREA' else "",
                "check_atermino": "/Yes" if get_form_field_value('check_atermino', request.form) == 'A_TERMINO' else "",
                "check_vaginal": "/Yes" if get_form_field_value('check_vaginal', request.form) == 'VAGINAL' else "",
                "check_prematuro": "/Yes" if get_form_field_value('check_prematuro', request.form) == 'PREMATURO' else "",
                "LOGRADO ACORDE A LA EDAD": "/Yes" if get_form_field_value('check_acorde', request.form) == 'LOGRADO_ACORDE_A_LA_EDAD' else "",
                "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if get_form_field_value('check_retrasogeneralizado', request.form) == 'RETRASO_GENERALIZADO_DEL_DESARROLLO' else "",
                "ESQUEMA COMPLETO": "/Yes" if get_form_field_value('check_esquemac', request.form) == 'ESQUEMA_COMPLETO' else "",
                "ESQUEMA INCOMPLETO": "/Yes" if get_form_field_value('check_esquemai', request.form) == 'ESQUEMA_INCOMPLETO' else "",
                "NO": "/Yes" if get_form_field_value('check_alergiano', request.form) == 'NO_ALERGIAS' else "",
                "SI": "/Yes" if get_form_field_value('check_alergiasi', request.form) == 'SI_ALERGIAS' else "",
                "NO_2": "/Yes" if get_form_field_value('check_cirugiano', request.form) == 'NO_CIRUGIAS' else "",
                "SI_2": "/Yes" if get_form_field_value('si_2', request.form) == 'SI_2' else "",
                "SIN ALTERACIÓN": "/Yes" if get_form_field_value('check_visionsinalteracion', request.form) == 'SIN_ALTERACION_VISION' else "",
                "VICIOS DE REFRACCION": "/Yes" if get_form_field_value('check_visionrefraccion', request.form) == 'VICIOS_DE_REFRACCION' else "",
                "NORMAL": "/Yes" if get_form_field_value('check_audicionnormal', request.form) == 'NORMAL_AUDICION' else "",
                "HIPOACUSIA": "/Yes" if get_form_field_value('check_hipoacusia', request.form) == 'HIPOACUSIA' else "",
                "TAPÓN DE CERUMEN": "/Yes" if get_form_field_value('check_tapondecerumen', request.form) == 'TAPON_DE_CERUMEN' else "",
                "SIN HALLAZGOS": "/Yes" if get_form_field_value('check_sinhallazgos', request.form) == 'SIN_HALLAZGOS' else "",
                "CARIES": "/Yes" if get_form_field_value('caries', request.form) == 'CARIES' else "",
                "APIÑAMIENTO DENTAL": "/Yes" if get_form_field_value('check_apinamientodental', request.form) == 'APINAMIENTO_DENTAL' else "",
                "RETENCIÓN DENTAL": "/Yes" if get_form_field_value('check_retenciondental', request.form) == 'RETENCION_DENTAL' else "",
                "FRENILLO LINGUAL": "/Yes" if get_form_field_value('check_frenillolingual', request.form) == 'FRENILLO_LINGUAL' else "",
                "HIPERTROFIA AMIGDALINA": "/Yes" if get_form_field_value('check_hipertrofia', request.form) == 'HIPERTROFIA_AMIGDALINA' else "",
                "Altura": get_form_field_value('altura', request.form),
                "Peso": get_form_field_value('peso', request.form),
                "I.M.C": get_form_field_value('imc', request.form),
                "Clasificación_IMC": get_form_field_value('clasificacion_imc', request.form),
            }
        writer.update_page_form_field_values(writer.pages[0], campos)
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        nombre_archivo_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario_{form_type}.pdf"
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')
    except Exception as e:
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

@app.route('/marcar_evaluado', methods=['POST'])
def marcar_evaluado():
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    doctora_id = session.get('usuario_id')
    form_type = session.get('current_form_type', 'neurologia') 
    nombre = get_form_field_value('nombre', request.form)
    rut = get_form_field_value('rut', request.form)
    if not all([estudiante_id, nomina_id, doctora_id]):
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400
    update_data = {
        'fecha_relleno': str(date.today()),
        'doctora_evaluadora_id': doctora_id, 
        'nombre': get_form_field_value('nombre', request.form),
        'rut': get_form_field_value('rut', request.form),
        'fecha_nacimiento': get_form_field_value('fecha_nacimiento_original', request.form, return_none_if_empty=True), 
        'fecha_evaluacion': get_form_field_value('fecha_evaluacion', request.form, return_none_if_empty=True),
        'fecha_reevaluacion': get_form_field_value('fecha_reevaluacion', request.form, return_none_if_empty=True),
        'edad': get_form_field_value('edad', request.form),
        'nacionalidad': get_form_field_value('nacionalidad', request.form),
    }
    if form_type == 'neurologia':
        update_data.update({
            'sexo': get_form_field_value('sexo', request.form),
            'estado_general': get_form_field_value('estado', request.form),
            'diagnostico': get_form_field_value('diagnostico', request.form), 
            'derivaciones': get_form_field_value('derivaciones', request.form),
        })
    elif form_type == 'medicina_familiar':
        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac_formato,
            "edad": edad,
            "nacionalidad": nacionalidad,
            "sexo_f": sexo_f_pdf,
            "sexo_m": sexo_m_pdf,
            "diagnostico_1": get_form_field_value('diagnostico_1', request.form),
            "diagnostico_2": get_form_field_value('diagnostico_2', request.form),
            "diagnostico_complementario": get_form_field_value('diagnostico_complementario', request.form),
            "clasificación": get_form_field_value('clasificacion_imc', request.form),
            "derivaciones": get_form_field_value('derivaciones', request.form),
            "fecha_evaluacion": fecha_evaluacion_formatted,
            "fecha_reevaluacion": fecha_reeval_pdf,
            "observacion_1": get_form_field_value('observacion_1', request.form),
            "observacion_2": get_form_field_value('observacion_2', request.form),
            "observacion_3": get_form_field_value('observacion_3', request.form),
            "observacion_4": get_form_field_value('observacion_4', request.form),
            "observacion_5": get_form_field_value('observacion_5', request.form),
            "observacion_6": get_form_field_value('observacion_6', request.form),
            "observacion_7": get_form_field_value('observacion_7', request.form),
            "check_cesarea": "/Yes" if get_form_field_value('check_cesarea', request.form) == 'CESAREA' else "",
            "check_atermino": "/Yes" if get_form_field_value('check_atermino', request.form) == 'A_TERMINO' else "",
            "check_vaginal": "/Yes" if get_form_field_value('check_vaginal', request.form) == 'VAGINAL' else "",
            "check_prematuro": "/Yes" if get_form_field_value('check_prematuro', request.form) == 'PREMATURO' else "",
            "LOGRADO ACORDE A LA EDAD": "/Yes" if get_form_field_value('check_acorde', request.form) == 'LOGRADO_ACORDE_A_LA_EDAD' else "",
            "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if get_form_field_value('check_retrasogeneralizado', request.form) == 'RETRASO_GENERALIZADO_DEL_DESARROLLO' else "",
            "ESQUEMA COMPLETO": "/Yes" if get_form_field_value('check_esquemac', request.form) == 'ESQUEMA_COMPLETO' else "",
            "ESQUEMA INCOMPLETO": "/Yes" if get_form_field_value('check_esquemai', request.form) == 'ESQUEMA_INCOMPLETO' else "",
            "NO": "/Yes" if get_form_field_value('check_alergiano', request.form) == 'NO_ALERGIAS' else "",
            "SI": "/Yes" if get_form_field_value('check_alergiasi', request.form) == 'SI_ALERGIAS' else "",
            "NO_2": "/Yes" if get_form_field_value('check_cirugiano', request.form) == 'NO_CIRUGIAS' else "",
            "SI_2": "/Yes" if get_form_field_value('si_2', request.form) == 'SI_2' else "",
            "SIN ALTERACIÓN": "/Yes" if get_form_field_value('check_visionsinalteracion', request.form) == 'SIN_ALTERACION_VISION' else "",
            "VICIOS DE REFRACCION": "/Yes" if get_form_field_value('check_visionrefraccion', request.form) == 'VICIOS_DE_REFRACCION' else "",
            "NORMAL": "/Yes" if get_form_field_value('check_audicionnormal', request.form) == 'NORMAL_AUDICION' else "",
            "HIPOACUSIA": "/Yes" if get_form_field_value('check_hipoacusia', request.form) == 'HIPOACUSIA' else "",
            "TAPÓN DE CERUMEN": "/Yes" if get_form_field_value('check_tapondecerumen', request.form) == 'TAPON_DE_CERUMEN' else "",
            "SIN HALLAZGOS": "/Yes" if get_form_field_value('check_sinhallazgos', request.form) == 'SIN_HALLAZGOS' else "",
            "CARIES": "/Yes" if get_form_field_value('caries', request.form) == 'CARIES' else "",
            "APIÑAMIENTO DENTAL": "/Yes" if get_form_field_value('check_apinamientodental', request.form) == 'APINAMIENTO_DENTAL' else "",
            "RETENCIÓN DENTAL": "/Yes" if get_form_field_value('check_retenciondental', request.form) == 'RETENCION_DENTAL' else "",
            "FRENILLO LINGUAL": "/Yes" if get_form_field_value('check_frenillolingual', request.form) == 'FRENILLO_LINGUAL' else "",
            "HIPERTROFIA AMIGDALINA": "/Yes" if get_form_field_value('check_hipertrofia', request.form) == 'HIPERTROFIA_AMIGDALINA' else "",
            "Altura": get_form_field_value('altura', request.form),
            "Peso": get_form_field_value('peso', request.form),
            "I.M.C": get_form_field_value('imc', request.form),
            "Clasificación_IMC": get_form_field_value('clasificacion_imc', request.form),
        }
    try:
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=update_data
        )
        if response.status_code >= 400: 
            return jsonify({"success": False, "message": f"Error al actualizar estudiante: {response.text}"}), response.status_code
        return jsonify({"success": True, "message": "Estudiante marcado como evaluado y datos guardados."})
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión con Supabase: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario = request.form['username']
    clave = request.form['password']
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario}&password=eq.{clave}&select=id,rol"
    try:
        res = requests.get(url, headers=SUPABASE_SERVICE_HEADERS) 
        res.raise_for_status()
        data = res.json()
        if data:
            session['usuario'] = data[0]['rol']
            session['usuario_id'] = data[0]['id']
            flash(f'¡Bienvenido, {usuario}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrecta.', 'error')
        return redirect(url_for('index'))
    except requests.exceptions.RequestException as e:
        flash('Error de conexión al intentar iniciar sesión. Intente de nuevo.', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario_rol = session['usuario']
    usuario_id = session.get('usuario_id')
    
    doctoras = []
    establecimientos_admin_list = []
    admin_nominas_cargadas = []
    conteo = {}
    
    doctor_performance_data = {}
    doctor_performance_data_single_doctor = {'completed': 0, 'pending': 0, 'total': 0}

    campos_establecimientos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo,doctora_id"
    eventos = []
    try:
        if usuario_rol == 'doctora':
            url_eventos = (
                f"{SUPABASE_URL}/rest/v1/establecimientos"
                f"?doctora_id=eq.{usuario_id}"
                f"&select={campos_establecimientos}"
            )
        else:
            url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos_establecimientos}"
        res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
        res_eventos.raise_for_status()
        eventos = res_eventos.json()
        if isinstance(eventos, list):
            eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0] if e.get('horario') else '')
    except requests.exceptions.RequestException as e:
        flash('Error al cargar el calendario de visitas.', 'error')

    formularios = []
    try:
        url_formularios_subidos = f"{SUPABASE_URL}/rest/v1/formularios_subidos"
        res_formularios = requests.get(url_formularios_subidos, headers=SUPABASE_HEADERS)
        res_formularios.raise_for_status()
        formularios = res_formularios.json()
    except requests.exceptions.RequestException as e:
        flash('Error al cargar los formularios subidos.', 'error')

    assigned_nominations = []
    if usuario_rol == 'doctora':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}"
                f"&select=id,nombre_nomina,tipo_nomina,form_type,doctora_id_para_formulario"
            )
            res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_SERVICE_HEADERS)
            res_nominas_asignadas.raise_for_status()
            raw_nominas = res_nominas_asignadas.json()
            for nom in raw_nominas:
                display_name = nom['tipo_nomina'].replace('_', ' ').title()
                assigned_nominations.append({
                    'id': nom['id'],
                    'nombre_establecimiento': nom['nombre_nomina'],
                    'tipo_nomina_display': display_name,
                    'form_type': nom.get('form_type'),
                    'doctora_id_para_formulario': nom.get('doctora_id_para_formulario')
                })
            nomina_ids_for_doctor = [n['id'] for n in raw_nominas]
            total_students_in_assigned_nominas = 0
            if nomina_ids_for_doctor:
                nomina_ids_str = ",".join(nomina_ids_for_doctor)
                url_total_students_assigned_to_doctor_nominations = (
                    f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                    f"?nomina_id=in.({nomina_ids_str})"
                    f"&select=count"
                )
                res_total_students = requests.get(url_total_students_assigned_to_doctor_nominations, headers=SUPABASE_SERVICE_HEADERS)
                res_total_students.raise_for_status()
                total_students_count_range = res_total_students.headers.get('Content-Range')
                if total_students_count_range:
                    try:
                        total_students_in_assigned_nominas = int(total_students_count_range.split('/')[-1])
                    except ValueError:
                        pass
            url_completed_by_this_doctor = (
                f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                f"?doctora_evaluadora_id=eq.{usuario_id}"
                f"&fecha_relleno.not.is.null"
                f"&select=count"
            )
            res_completed_by_this_doctor = requests.get(url_completed_by_this_doctor, headers=SUPABASE_SERVICE_HEADERS)
            res_completed_by_this_doctor.raise_for_status()
            completed_forms_count_range = res_completed_by_this_doctor.headers.get('Content-Range')
            completed_count_by_doctor = 0
            if completed_forms_count_range:
                try:
                    completed_count_by_doctor = int(completed_forms_count_range.split('/')[-1])
                except ValueError:
                    pass
            doctor_performance_data_single_doctor = {
                'completed': completed_count_by_doctor,
                'total': total_students_in_assigned_nominas,
                'pending': total_students_in_assigned_nominas - completed_count_by_doctor if total_students_in_assigned_nominas >= completed_count_by_doctor else 0
            }
        except requests.exceptions.RequestException as e:
            flash('Error al cargar sus nóminas asignadas o conteo de evaluaciones.', 'error')

    if usuario_rol == 'admin':
        try:
            url_doctoras = f"{SUPABASE_URL}/rest/v1/doctoras"
            res_doctoras = requests.get(url_doctoras, headers=SUPABASE_SERVICE_HEADERS) 
            res_doctoras.raise_for_status()
            doctoras_raw = res_doctoras.json()
            doctoras = []
            for doc in doctoras_raw:
                doctoras.append({'id': doc['id'], 'usuario': doc['usuario']})
        except requests.exceptions.RequestException as e:
            flash('Error crítico al cargar doctoras en el panel de administrador. Verifique su SUPABASE_SERVICE_KEY.', 'error')
            doctoras = [] 
        try:
            url_establecimientos_admin = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre"
            res_establecimientos = requests.get(url_establecimientos_admin, headers=SUPABASE_SERVICE_HEADERS) 
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
        except requests.exceptions.RequestException as e:
            flash('Error crítico al cargar establecimientos en el panel de administrador. Verifique su SUPABASE_SERVICE_KEY.', 'error')
            establecimientos_admin_list = [] 
        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1
        try:
            url_admin_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina,tipo_nomina,doctora_id,url_excel_original,nombre_excel_original,form_type,doctora_id_para_formulario"
            res_admin_nominas = requests.get(url_admin_nominas, headers=SUPABASE_SERVICE_HEADERS) 
            res_admin_nominas.raise_for_status()
            admin_nominas_cargadas = res_admin_nominas.json()
        except requests.exceptions.RequestException as e:
            flash('Error al cargar la lista de nóminas en la vista de administrador.', 'error')
        if doctoras_raw: 
            for doc in doctoras_raw:
                doctor_id = doc['id']
                doctor_name = doc['usuario']
                try:
                    url_doctor_forms_count = (
                        f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                        f"?doctora_evaluadora_id=eq.{doctor_id}" 
                        f"&fecha_relleno.not.is.null" 
                        f"&select=count" 
                    )
                    res_doctor_forms = requests.get(url_doctor_forms_count, headers=SUPABASE_SERVICE_HEADERS) 
                    res_doctor_forms.raise_for_status()
                    count_range = res_doctor_forms.headers.get('Content-Range')
                    completed_forms_count = 0
                    if count_range:
                        try:
                            completed_forms_count = int(count_range.split('/')[-1])
                        except ValueError:
                            pass
                    doctor_performance_data[doctor_name] = completed_forms_count
                except requests.exceptions.RequestException as e:
                    doctor_performance_data[doctor_name] = 0 
                except Exception as e:
                    doctor_performance_data[doctor_name] = 0

    return render_template(
        'dashboard.html',
        usuario=usuario_rol,
        eventos=eventos,
        doctoras=doctoras,
        establecimientos=establecimientos_admin_list,
        formularios=formularios,
        conteo=conteo,
        assigned_nominations=assigned_nominations,
        admin_nominas_cargadas=admin_nominas_cargadas,
        doctor_performance_data=doctor_performance_data, 
        doctor_performance_data_single_doctor=doctor_performance_data_single_doctor 
    )

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/agregar', methods=['POST'])
def admin_agregar():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    nombre = request.form.get('nombre')
    fecha = request.form.get('fecha')
    horario = request.form.get('horario')
    obs = request.form.get('obs')
    doctora_id_from_form = request.form.get('doctora', '').strip()
    cantidad_alumnos = request.form.get('alumnos')
    if not all([nombre, fecha, horario, doctora_id_from_form]):
        flash("❌ Faltan campos obligatorios para el establecimiento.", 'error')
        return redirect(url_for('dashboard'))
    nuevo_id = str(uuid.uuid4())
    data_establecimiento = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha": fecha,
        "horario": horario,
        "observaciones": obs,
        "doctora_id": doctora_id_from_form,
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None,
        "url_archivo": None,
        "nombre_archivo": None
    }
    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_establecimiento
        )
        response_db.raise_for_status()
        flash("✅ Establecimiento agregado correctamente.", 'success')
    except requests.exceptions.RequestException as e:
        flash("❌ Error al guardar el establecimiento en la base de datos.", 'error')
    except Exception as e:
        flash("❌ Error inesperado al guardar el establecimiento.", 'error')
    return redirect(url_for('dashboard'))

@app.route('/admin/cargar_nomina', methods=['POST'])
def admin_cargar_nomina():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    tipo_nomina_raw = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id_from_form = request.form.get('doctora', '').strip()
    excel_file = request.files.get('excel')
    doctora_id_para_formulario = request.form.get('doctora_id_para_formulario', '').strip()
    tipo_nomina_normalized = tipo_nomina_raw.strip().lower() if tipo_nomina_raw else ''
    form_type = None
    if 'neurologia' in tipo_nomina_normalized: 
        form_type = 'neurologia'
    elif 'familiar' in tipo_nomina_normalized: 
        form_type = 'medicina_familiar'
    if not all([tipo_nomina_raw, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Falta uno o más campos obligatorios para cargar la nómina (tipo, nombre, doctora, archivo).', 'error')
        return redirect(url_for('dashboard'))
    if form_type is None: 
        flash(f'❌ El tipo de nómina "{tipo_nomina_raw}" no se pudo mapear a un tipo de formulario conocido. Por favor, verifique el tipo de nómina.', 'error')
        return redirect(url_for('dashboard'))
    if form_type == 'neurologia' and not doctora_id_para_formulario:
        flash('❌ Para nóminas de tipo "Neurología", debe seleccionar la Doctora para el formulario.', 'error')
        return redirect(url_for('dashboard'))
    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))
    nomina_id = str(uuid.uuid4())
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read()
    mime_type = mimetypes.guess_type(excel_filename)[0] or 'application/octet-stream'
    try:
        upload_path = f"nominas-medicas/{nomina_id}/{excel_filename}" 
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" 
    except requests.exceptions.RequestException as e:
        error_detail = res_upload.text if 'res_upload' in locals() else 'No response from Supabase Storage.'
        flash(f"❌ Error al subir el archivo de la nómina a Supabase Storage: {error_detail}", 'error')
        return redirect(url_for('dashboard'))
    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina_raw,
        "doctora_id": doctora_id_from_form,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename,
        "form_type": form_type,
        "doctora_id_para_formulario": doctora_id_para_formulario if form_type == 'neurologia' else None
    }
    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
    except requests.exceptions.RequestException as e:
        error_detail = res_insert_nomina.text if 'res_insert_nomina' in locals() else 'No response from Supabase.'
        flash(f"❌ Error al guardar los datos de la nómina en la base de datos: {error_detail}", 'error')
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
        except Exception as cleanup_e:
            pass
        return redirect(url_for('dashboard'))
    excel_data_stream = io.BytesIO(excel_file_data)
    if excel_filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(excel_data_stream)
    elif excel_filename.endswith('.csv'):
        df = pd.read_csv(excel_data_stream, encoding='utf-8')
    else:
        flash('❌ Formato de archivo no soportado para la nómina.', 'error')
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
        except Exception as rollback_e:
            pass
        return redirect(url_for('dashboard'))
    estudiantes_a_insertar = []
    df.columns = [normalizar(col) for col in df.columns]
    column_mapping = {
        'nombre_completo': ['nombre_completo', 'nombre_del_estudiante', 'nombre'],
        'rut': ['rut'],
        'fecha_nacimiento': ['fecha_nacimiento', 'fecha_de_nacimiento'],
        'nacionalidad': ['nacionalidad'],
    }
    col_map = {}
    for key, possible_names in column_mapping.items():
        for name in possible_names:
            if name in df.columns:
                col_map[key] = name
                break
    required_columns_excel = ['nombre_completo', 'rut', 'fecha_nacimiento']
    if not all(k in col_map for k in required_columns_excel):
        missing_cols = [col for col in required_columns_excel if col not in col_map]
        flash(f"❌ El archivo no contiene las columnas necesarias: {', '.join(missing_cols)}. Verifique que los encabezados sean 'Nombre Completo', 'rut', y 'fecha nacimiento' exactamente.", 'error')
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
        except Exception as rollback_e:
            pass
        return redirect(url_for('dashboard'))
    for index, row in df.iterrows():
        try:
            nombre_completo_raw = row.get(col_map.get('nombre_completo'))
            rut_raw = row.get(col_map.get('rut'))
            fecha_nacimiento_raw = row.get(col_map.get('fecha_nacimiento'))
            nacionalidad_raw = row.get(col_map.get('nacionalidad'))
            if pd.isna(nombre_completo_raw) or pd.isna(rut_raw) or pd.isna(fecha_nacimiento_raw):
                continue
            rut_limpio = str(rut_raw).replace('.', '').replace('-', '').strip()
            fecha_nac_str = None
            if isinstance(fecha_nacimiento_raw, datetime):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            elif isinstance(fecha_nacimiento_raw, date):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            else:
                try:
                    parsed_date = pd.to_datetime(fecha_nacimiento_raw, errors='coerce')
                    if pd.notna(parsed_date):
                        fecha_nac_str = parsed_date.strftime('%Y-%m-%d')
                    else:
                        raise ValueError("Formato de fecha no reconocido o inválido.")
                except Exception as date_e:
                    fecha_nac_str = None
            if fecha_nac_str is None:
                continue
            sexo_adivinado = guess_gender(str(nombre_completo_raw))
            nacionalidad_valor = str(nacionalidad_raw).strip() if pd.notna(nacionalidad_raw) else 'Chilena'
            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, 
                "nacionalidad": nacionalidad_valor,
                "sexo": sexo_adivinado,
                "estado_general": None, 
                "diagnostico": None,
                "fecha_reevaluacion": None,
                "derivaciones": None,
                "fecha_relleno": None
            }
            estudiantes_a_insertar.append(estudiante)
        except Exception as e:
            flash(f"Error al procesar la fila {index+2} del archivo. Verifique el formato de los datos. ({e})", 'error')
            try:
                requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
                requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
            except Exception as rollback_e:
                pass
            return redirect(url_for('dashboard'))
    if not estudiantes_a_insertar:
        flash("⚠️ El archivo Excel/CSV no contiene datos válidos para estudiantes. La nómina fue cargada, pero sin estudiantes.", 'warning')
        return redirect(url_for('dashboard'))
    try:
        res_insert_estudiantes = requests.post(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=estudiantes_a_insertar
        )
        res_insert_estudiantes.raise_for_status()
        flash(f"✅ Nómina '{nombre_especifico}' cargada con éxito. Se agregaron {len(estudiantes_a_insertar)} estudiantes.", 'success')
        return redirect(url_for('dashboard'))
    except requests.exceptions.RequestException as e:
        error_detail = res_insert_estudiantes.text if 'res_insert_estudiantes' in locals() else 'No response from Supabase.'
        flash(f"❌ Error al guardar los estudiantes en la base de datos. La nómina fue creada, pero no se agregaron los estudiantes. ({e}). Detalles: {error_detail}", 'error')
        return redirect(url_for('dashboard'))

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))
    archivos = request.files.getlist('archivo')
    if not archivos or archivos[0].filename == '':
        flash('No se seleccionó ningún archivo para subir.', 'error')
        return redirect(url_for('dashboard'))
    usuario_id = session['usuario_id']
    mensajes = []
    for archivo in archivos:
        if permitido(archivo.filename):
            filename = secure_filename(archivo.filename)
            file_data = archivo.read()
            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            unique_file_id = str(uuid.uuid4())
            upload_path = f"formularios_completados/{establecimiento}/{unique_file_id}/{filename}"
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
            try:
                res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
                res_upload.raise_for_status()
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" 
                data = {
                    "doctoras_id": usuario_id,
                    "establecimientos_id": establecimiento,
                    "nombre_archivo": filename,
                    "url_archivo": url_publica
                }
                res_insert = requests.post(
                    f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                    headers=SUPABASE_SERVICE_HEADERS, 
                    json=data
                )
                res_insert.raise_for_status()
                mensajes.append(f"✅ Archivo '{filename}' subido y registrado correctamente.")
            except requests.exceptions.RequestException as e:
                error_msg = f"❌ Error al subir o registrar '{filename}': {e} - {res_upload.text if 'res_upload' in locals() else res_insert.text if 'res_insert' in locals() else 'No response'}"
                mensajes.append(error_msg)
            except Exception as e:
                error_msg = f"❌ Error inesperado al procesar '{filename}': {e}"
                mensajes.append(error_msg)
        else:
            mensajes.append(f"⚠️ Archivo '{archivo.filename}' no permitido.")
    for msg in mensajes:
        flash(msg, 'success' if '✅' in msg else 'error' if '❌' in msg else 'warning')
    return redirect(url_for('dashboard'))

@app.route('/colegios')
def colegios():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('colegios.html')

@app.route('/mis_nominas')
def mis_nominas():
    if 'usuario' not in session:
        return redirect(url_for('index'))
    usuario_id = session.get('usuario_id')
    assigned_nominations = []
    if not usuario_id:
        flash("No se pudo obtener el ID de usuario.", "error")
        return redirect(url_for('dashboard'))
    try:
        url_nominas_asignadas = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?doctora_id=eq.{usuario_id}"
            f"&select=id,nombre_nomina,tipo_nomina,form_type,doctora_id_para_formulario"
        )
        res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
        res_nominas_asignadas.raise_for_status()
        raw_nominas = res_nominas_asignadas.json()
        for nom in raw_nominas:
            display_name = nom['tipo_nomina'].replace('_', ' ').title()
            assigned_nominations.append({
                'id': nom['id'],
                'nombre_establecimiento': nom['nombre_nomina'],
                'tipo_nomina_display': display_name,
                'form_type': nom.get('form_type'),
                'doctora_id_para_formulario': nom.get('doctora_id_para_formulario')
            })
    except requests.exceptions.RequestException as e:
        flash('Error al cargar sus nóminas asignadas.', 'error')
    except Exception as e:
        flash('Error inesperado al cargar sus nóminas asignadas.', 'error')
    return render_template('mis_nominas.html', assigned_nominations=assigned_nominations)

@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))
    alumnos_evaluados = request.form.get('alumnos')
    data_update = {
        "cantidad_alumnos_evaluados": int(alumnos_evaluados) if alumnos_evaluados else 0
    }
    try:
        response_db = requests.patch(
            f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento}",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_update
        )
        response_db.raise_for_status()
        flash("✅ Cantidad de alumnos evaluados registrada correctamente.", 'success')
    except requests.exceptions.RequestException as e:
        flash("❌ Error al registrar la cantidad de alumnos evaluados.", 'error')
    except Exception as e:
        flash("❌ Error inesperado al registrar la cantidad de alumnos evaluados.", 'error')
    return redirect(url_for('dashboard'))

@app.route('/doctor_performance/<doctor_id>')
def doctor_performance_detail(doctor_id):
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    doctor_name = "Doctora Desconocida"
    evaluated_students = []
    try:
        url_doctora = f"{SUPABASE_URL}/rest/v1/doctoras?id=eq.{doctor_id}&select=usuario"
        res_doctora = requests.get(url_doctora, headers=SUPABASE_SERVICE_HEADERS)
        res_doctora.raise_for_status()
        doctor_data = res_doctora.json()
        if doctor_data:
            doctor_name = doctor_data[0]['usuario']
        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?doctora_evaluadora_id=eq.{doctor_id}" 
            f"&fecha_relleno.not.is.null" 
            f"&select=nombre,rut,fecha_nacimiento,fecha_relleno,nomina_id,nominas_medicas(nombre_nomina)" 
            f"&order=nombre.asc" 
        )
        res_students = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS)
        res_students.raise_for_status()
        students_raw = res_students.json()
        for student in students_raw:
            formatted_date = student.get('fecha_relleno')
            if formatted_date and isinstance(formatted_date, str):
                try:
                    formatted_date = datetime.strptime(formatted_date, '%Y-%m-%d').strftime('%d-%m-%Y')
                except ValueError:
                    pass 
            nomina_nombre = "Nómina Desconocida"
            if student.get('nominas_medicas') and student['nominas_medicas']:
                if isinstance(student['nominas_medicas'], list) and student['nominas_medicas']:
                    nomina_nombre = student['nominas_medicas'][0].get('nombre_nomina', nomina_nombre)
                elif isinstance(student['nominas_medicas'], dict):
                    nomina_nombre = student['nominas_medicas'].get('nombre_nomina', nomina_nombre)
            evaluated_students.append({
                'nombre': student.get('nombre'),
                'rut': format_rut_python(student.get('rut')),
                'fecha_relleno': formatted_date,
                'nomina_nombre': nomina_nombre 
            })
    except requests.exceptions.RequestException as e:
        flash('Error al cargar el detalle de rendimiento de la doctora.', 'error')
    except Exception as e:
        flash('Error inesperado al cargar el detalle de rendimiento de la doctora.', 'error')
    return render_template('doctor_performance.html', 
                           doctor_name=doctor_name, 
                           evaluated_students=evaluated_students)

@app.route('/admin/crear_proyecto', methods=['POST'])
def crear_proyecto():
    if request.method == 'POST':
        nombre_proyecto_form = request.form.get('nombre_proyecto')
        descripcion_proyecto_form = request.form.get('descripcion_proyecto')
        payload = {
            "nombre_proyecto": nombre_proyecto_form,
            "descripcion_proyecto": descripcion_proyecto_form,
            "fecha_creacion": datetime.now().isoformat()
        }
        proyectos_url = f"{SUPABASE_URL}/rest/v1/proyectos"
        try:
            response = requests.post(proyectos_url, json=payload, headers=SUPABASE_SERVICE_HEADERS)
            if response.status_code != 201:
                pass
            response.raise_for_status()
            data = response.json()
            flash('Proyecto creado exitosamente!', 'success')
            return redirect(url_for('dashboard', _external=True, _scheme='https', section='gestionar_proyectos'))
        except requests.exceptions.HTTPError as errh:
            flash(f"Error al crear el proyecto (HTTP): {errh}", 'danger')
        except requests.exceptions.ConnectionError as errc:
            flash(f"Error al crear el proyecto (Conexión): {errc}", 'danger')
        except requests.exceptions.Timeout as errt:
            flash(f"Error al crear el proyecto (Timeout): {errt}", 'danger')
        except requests.exceptions.RequestException as err:
            flash(f"Error en el servidor al crear el proyecto: {err}", 'danger')
        except Exception as e:
            flash(f"Error inesperado al crear el proyecto: {e}", 'danger')
    return redirect(url_for('dashboard', _external=True, _scheme='https'))
    
@app.route('/descargar_excel_evaluados/<nomina_id>', methods=['GET'])
def descargar_excel_evaluados(nomina_id):
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    try:
        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?nomina_id=eq.{nomina_id}"
            f"&fecha_relleno.not.is.null" 
            f"&select=nombre,rut,fecha_nacimiento,fecha_relleno" 
            f"&order=nombre.asc" 
        )
        res_students = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS)
        res_students.raise_for_status()
        evaluated_students_data = res_students.json()
        if not evaluated_students_data:
            return jsonify({"success": False, "message": "No hay formularios evaluados para esta nómina."}), 404
        df = pd.DataFrame(evaluated_students_data)
        df.rename(columns={
            'nombre': 'Nombre Completo',
            'rut': 'RUT',
            'fecha_nacimiento': 'Fecha de Nacimiento',
            'fecha_relleno': 'Fecha de Evaluación'
        }, inplace=True)
        df['RUT'] = df['RUT'].apply(format_rut_python)
        for col in ['Fecha de Nacimiento', 'Fecha de Evaluación']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
        df['Estado de Evaluación'] = df['Fecha de Evaluación'].apply(lambda x: 'Evaluado' if pd.notnull(x) and x != '' else 'Pendiente')
        df = df[['Nombre Completo', 'RUT', 'Fecha de Nacimiento', 'Estado de Evaluación']]
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        df.to_excel(writer, index=False, sheet_name='Formularios Evaluados')
        writer.close() 
        output.seek(0)
        establecimiento_nombre = session.get('establecimiento_nombre', 'Nomina_Desconocida').replace(' ', '_')
        excel_filename = f"Formularios_Evaluados_{establecimiento_nombre}_{date.today().strftime('%Y%m%d')}.xlsx"
        return send_file(output, as_attachment=True, download_name=excel_filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión con Supabase: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error interno del servidor al generar el Excel: {str(e)}"}), 500

@app.route('/generar_zip_pdfs_evaluados', methods=['POST'])
def generar_zip_pdfs_evaluados():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Acceso denegado."}), 403
    data = request.get_json()
    nomina_id = data.get('nomina_id')
    student_ids = data.get('student_ids', [])
    if not nomina_id or not student_ids:
        return jsonify({"success": False, "message": "IDs de nómina o estudiantes faltantes."}), 400
    merged_pdf_writer = PdfWriter()
    form_type = session.get('current_form_type', 'neurologia') 
    doctora_id_para_formulario = session.get('doctora_id_para_formulario')
    pdf_base_path = None
    if form_type == 'neurologia':
        pdf_base_path = PDF_BASE_NEUROLOGIA 
        if not doctora_id_para_formulario:
            return jsonify({"success": False, "message": "No se especificó la doctora para el formulario de neurología."}), 400
    elif form_type == 'medicina_familiar':
        pdf_base_path = PDF_BASE_FAMILIAR
    else:
        return jsonify({"success": False, "message": "Tipo de formulario no soportado."}), 400
    if not os.path.exists(pdf_base_path):
        return jsonify({"success": False, "message": f"Archivo PDF base no encontrado: {pdf_base_path}"}), 500
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for student_id in student_ids:
                res_estudiante = requests.get(
                    f"{SUPABASE_URL}/rest/v1/estudiantes?id=eq.{student_id}&select=*",
                    headers=SUPABASE_SERVICE_HEADERS
                )
                res_estudiante.raise_for_status()
                estudiante_data = res_estudiante.json()
                if not estudiante_data:
                    continue
                estudiante = estudiante_data[0]
                temp_pdf_buffer = io.BytesIO()
                with open(pdf_base_path, 'rb') as file:
                    reader = PdfReader(file)
                    writer = PdfWriter()
                    for page in reader.pages:
                        writer.add_page(page)
                    field_mapping = {
                        "Nombre": estudiante.get('nombre', ''),
                        "RUT": estudiante.get('rut', ''),
                        "Fecha_Nacimiento": datetime.strptime(estudiante['fecha_nacimiento'], '%Y-%m-%d').strftime('%d/%m/%Y') if estudiante.get('fecha_nacimiento') else '',
                        "Edad": str(estudiante.get('edad', '')),
                        "Nacionalidad": estudiante.get('nacionalidad', ''),
                        "Sexo": 'MASCULINO' if estudiante.get('sexo') == 'M' else 'FEMENINO' if estudiante.get('sexo') == 'F' else '',
                        "Fecha_Evaluacion": datetime.strptime(estudiante['fecha_evaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y') if estudiante.get('fecha_evaluacion') else '',
                        "Estado_General": estudiante.get('estado_general', ''),
                        "Diagnostico": estudiante.get('diagnostico', ''),
                        "Plazo_Reevaluacion": estudiante.get('plazo', ''),
                        "Fecha_Reevaluacion": datetime.strptime(estudiante['fecha_reevaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y') if estudiante.get('fecha_reevaluacion') else '',
                        "Derivaciones": estudiante.get('derivaciones', '')
                    }
                    writer.update_page_form_field_values(writer.pages[0], field_mapping)
                    writer.write(temp_pdf_buffer)
                temp_pdf_buffer.seek(0)
                pdf_filename = f"Evaluacion_{estudiante.get('nombre', 'Estudiante').replace(' ', '_')}_{estudiante.get('rut', '')}.pdf"
                zf.writestr(pdf_filename, temp_pdf_buffer.getvalue())
        zip_buffer.seek(0)
        zip_filename = f"Evaluaciones_ZIP_{nomina_nombre.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión al generar ZIP de PDFs: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error inesperado al generar ZIP de PDFs: {str(e)}"}), 500

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

@app.route('/generar_pdfs_visibles', methods=['POST'])
def generar_pdfs_visibles():
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    data = request.get_json()
    nomina_id = data.get('nomina_id')
    student_ids = data.get('student_ids')
    if not nomina_id or not student_ids or not isinstance(student_ids, list):
        return jsonify({"success": False, "message": "Datos de entrada inválidos para la generación de PDFs."}), 400
    merged_pdf_writer = PdfWriter()
    form_type = session.get('current_form_type', 'neurologia') 
    doctora_id_para_formulario = session.get('doctora_id_para_formulario')
    pdf_base_path = ''
    if form_type == 'neurologia':
        if doctora_id_para_formulario:
            pdf_base_path = get_doctor_specific_neurologia_pdf(doctora_id_para_formulario)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
    elif form_type == 'medicina_familiar':
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
    else:
        return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400
    if not os.path.exists(pdf_base_path):
        return jsonify({"success": False, "message": f"Error interno: Archivo base del formulario '{pdf_base_path}' no encontrado en el servidor."}), 500
    try:
        for student_id in student_ids:
            url_student_data = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{student_id}&select=*"
            res_student = requests.get(url_student_data, headers=SUPABASE_SERVICE_HEADERS)
            res_student.raise_for_status()
            student_data = res_student.json()
            if not student_data:
                continue
            est = student_data[0] 
            nombre = est.get('nombre', '')
            rut = format_rut_python(est.get('rut', ''))
            fecha_nac_formato = ''
            if est.get('fecha_nacimiento'):
                try:
                    fecha_nac_formato = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass 
            edad = est.get('edad', '')
            nacionalidad = est.get('nacionalidad', '')
            sexo_f_pdf = ""
            sexo_m_pdf = ""
            if form_type == 'neurologia':
                sexo_f_pdf = "X" if est.get('sexo') == "F" else ""
                sexo_m_pdf = "X" if est.get('sexo') == "M" else ""
            elif form_type == 'medicina_familiar':
                sexo_f_pdf = "X" if est.get('genero_f') else ""
                sexo_m_pdf = "X" if est.get('genero_m') else ""
            fecha_evaluacion_from_db_formatted = ''
            if est.get('fecha_evaluacion'):
                try:
                    fecha_evaluacion_from_db_formatted = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass
            fecha_reeval_pdf = ''
            if est.get('fecha_reevaluacion'):
                try:
                    fecha_reeval_pdf = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass
            reader = PdfReader(pdf_base_path)
            writer_single_pdf = PdfWriter()
            writer_single_pdf.add_page(reader.pages[0])
            campos = {}
            if form_type == 'neurologia':
                campos = {
                    "nombre": nombre,
                    "rut": rut,
                    "fecha_nacimiento": fecha_nac_formato, 
                    "nacionalidad": nacionalidad,
                    "edad": edad,
                    "diagnostico_1": est.get('diagnostico', ''),
                    "diagnostico_2": est.get('diagnostico', ''), 
                    "estado_general": est.get('estado_general', ''),
                    "fecha_evaluacion": fecha_evaluacion_from_db_formatted, 
                    "fecha_reevaluacion": fecha_reeval_pdf,
                    "derivaciones": est.get('derivaciones', ''),
                    "sexo_f": sexo_f_pdf,
                    "sexo_m": sexo_m_pdf,
                }
            elif form_type == 'medicina_familiar':
                campos = {
                    "Nombres y Apellidos": nombre,
                    "RUN": rut,
                    "Fecha nacimiento (dd/mm/aaaa)": fecha_nac_formato,
                    "Edad (en años y meses)": edad,
                    "Nacionalidad": nacionalidad,
                    "F": sexo_f_pdf,
                    "M": sexo_m_pdf,
                    "DIAGNOSTICO": est.get('diagnostico_1', ''),
                    "DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', ''),
                    "Clasificación": est.get('clasificacion', ''),
                    "INDICACIONES": est.get('derivaciones', ''),
                    "Fecha evaluación": fecha_evaluacion_from_db_formatted, 
                    "Fecha reevaluación": fecha_reeval_pdf,
                    "OBS1": est.get('observacion_1', ''),
                    "OBS2": est.get('observacion_2', ''),
                    "OBS3": est.get('observacion_3', ''),
                    "OBS4": est.get('observacion_4', ''),
                    "OBS5": est.get('observacion_5', ''),
                    "OBS6": est.get('observacion_6', ''),
                    "OBS7": est.get('observacion_7', ''),
                    "CESAREA": "/Yes" if est.get('check_cesarea') else "",
                    "A TÉRMINO": "/Yes" if est.get('check_atermino') else "",
                    "VAGINAL": "/Yes" if est.get('check_vaginal') else "",
                    "PREMATURO": "/Yes" if est.get('check_prematuro') else "",
                    "LOGRADO ACORDE A LA EDAD": "/Yes" if est.get('check_acorde') else "",
                    "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if est.get('check_retrasogeneralizado') else "",
                    "ESQUEMA COMPLETO": "/Yes" if est.get('check_esquemac') else "",
                    "ESQUEMA INCOMPLETO": "/Yes" if est.get('check_esquemai') else "",
                    "NO": "/Yes" if est.get('check_alergiano') else "",
                    "SI": "/Yes" if est.get('check_alergiasi') else "",
                    "NO_2": "/Yes" if est.get('check_cirugiano') else "",
                    "SI_2": "/Yes" if est.get('si_2') else "",
                    "SIN ALTERACIÓN": "/Yes" if est.get('check_visionsinalteracion') else "",
                    "VICIOS DE REFRACCION": "/Yes" if est.get('check_visionrefraccion') else "",
                    "NORMAL": "/Yes" if est.get('check_audicionnormal') else "",
                    "HIPOACUSIA": "/Yes" if est.get('check_hipoacusia') else "",
                    "TAPÓN DE CERUMEN": "/Yes" if est.get('check_tapondecerumen') else "",
                    "SIN HALLAZGOS": "/Yes" if est.get('check_sinhallazgos') else "",
                    "CARIES": "/Yes" if est.get('caries') else "",
                    "APIÑAMIENTO DENTAL": "/Yes" if est.get('check_apinamientodental') else "",
                    "RETENCIÓN DENTAL": "/Yes" if est.get('check_retenciondental') else "",
                    "FRENILLO LINGUAL": "/Yes" if est.get('check_frenillolingual') else "",
                    "HIPERTROFIA AMIGDALINA": "/Yes" if est.get('check_hipertrofia') else "",
                    "Altura": est.get('altura', ''),
                    "Peso": est.get('peso', ''),
                    "I.M.C": est.get('imc', ''),
                    "Clasificación_IMC": est.get('clasificacion_imc', ''),
                    "Nombres y Apellidos_Doctor": est.get('doctor_nombre', ''), 
                    "Rut_Doctor": est.get('doctor_rut', ''),
                    "Nº Registro Profesional": est.get('doctor_registro', ''),
                    "Especialidad": est.get('doctor_especialidad', ''),
                    "Fono/E-Mail Contacto": est.get('doctor_email', ''),
                    "Salud pública": "/Yes" if est.get('procedencia_salud_publica') else "",
                    "Particular": "/Yes" if est.get('procedencia_particular') else "",
                    "Escuela": "/Yes" if est.get('procedencia_escuela') else "",
                    "Otro": "/Yes" if est.get('procedencia_otro') else "",
                }
            if "/AcroForm" not in writer_single_pdf._root_object:
                writer_single_pdf._root_object.update({
                    NameObject("/AcroForm"): DictionaryObject()
                })
            writer_single_pdf.update_page_form_field_values(writer_single_pdf.pages[0], campos)
            writer_single_pdf._root_object["/AcroForm"].update({
                NameObject("/NeedAppearances"): BooleanObject(True)
            })
            temp_output = io.BytesIO()
            writer_single_pdf.write(temp_output)
            temp_output.seek(0)
            temp_reader = PdfReader(temp_output)
            for page_num in range(len(temp_reader.pages)):
                merged_pdf_writer.add_page(temp_reader.pages[page_num])
        final_output_pdf = io.BytesIO()
        merged_pdf_writer.write(final_output_pdf)
        final_output_pdf.seek(0)
        establecimiento_nombre = session.get('establecimiento_nombre', 'Nomina_Desconocida').replace(' ', '_')
        pdf_filename = f"Formularios_Visibles_{establecimiento_nombre}_{date.today().strftime('%Y%m%d')}.pdf"
        return send_file(final_output_pdf, as_attachment=False, download_name=pdf_filename, mimetype='application/pdf')
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión con Supabase al generar PDF: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error inesperado al generar PDFs: {str(e)}"}), 500

@app.route('/admin/eliminar_establecimiento/<establecimiento_id>', methods=['DELETE'])
def eliminar_establecimiento(establecimiento_id):
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado. Solo administradores pueden eliminar."}), 403
    try:
        res_delete_est = requests.delete(
            f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_est.raise_for_status()
        if res_delete_est.status_code == 204:
            return jsonify({"success": True, "message": "Colegio eliminado correctamente."})
        else:
            return jsonify({"success": False, "message": f"Error al eliminar el colegio: {res_delete_est.text}"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión al eliminar colegio: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error interno del servidor al eliminar colegio: {str(e)}"}), 500

@app.route('/admin/eliminar_nomina/<nomina_id>', methods=['DELETE'])
def eliminar_nomina(nomina_id):
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado. Solo administradores pueden eliminar."}), 403
    try:
        res_delete_students = requests.delete(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_students.raise_for_status()
        res_delete_nomina = requests.delete(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_nomina.raise_for_status()
        if res_delete_nomina.status_code == 204:
            return jsonify({"success": True, "message": "Nómina y sus estudiantes eliminados correctamente."})
        else:
            return jsonify({"success": False, "message": f"Error al eliminar la nómina: {res_delete_nomina.text}"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Error de conexión al eliminar nómina: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error inesperado al eliminar nómina: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
