from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response, jsonify
import os
import requests
import base64
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from openpyxl import load_workbook
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject, NumberObject, DictionaryObject
import mimetypes
import io
import uuid
import json
import pandas as pd
import unicodedata

# Importaciones específicas para Google Drive API
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}

# Define los PDFs base para cada tipo de formulario
# Asegúrate de que estos archivos PDF existan en la misma carpeta que app.py
PDF_BASE_NEUROLOGIA = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_BASE_FAMILIAR = 'formulario_familiar.pdf' 

# -------------------- Supabase Configuration --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IlNJUDU4IiwicmVmIjoiYnhzbnFmZml4d2pkcWl2eGJrZXkiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzE5Mjg3MzI1LCJleHAiOjE3NTA4MjMzMjV9.qNl_p4_u1O5xQ9s6bN0K2Z0f0v_N9s8k0k0k0k0k") # ASEGÚRATE DE USAR TU SERVICE_KEY REAL

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

# Configuración de SendGrid
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = os.getenv("SENDGRID_FROM_EMAIL", 'your_sendgrid_email@example.com')
SENDGRID_TO = os.getenv("SENDGRID_ADMIN_EMAIL", 'destination_admin_email@example.com')

# -------------------- Google Drive API Configuration (Empresa) --------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID") 
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET")
GOOGLE_DRIVE_REFRESH_TOKEN = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", None)
GOOGLE_DRIVE_PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", None)

SCOPES = ['https://www.googleapis.com/auth/drive.file'] 


# -------------------- Utilidades --------------------
def permitido(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_age(birth_date):
    """Calcula la edad en años y meses a partir de una fecha de nacimiento."""
    today = date.today()
    years = today.year - birth_date.year
    months = today.month - birth_date.month
    if months < 0:
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    """
    Intenta adivinar el género basado en el nombre (heurística simple).
    Retorna 'M', 'F' o None si no puede adivinar.
    """
    name_lower = name.lower().strip()
    first_word = name_lower.split(' ')[0]

    nombres_masculinos = ["juan", "pedro", "luis", "carlos", "jose", "manuel", "alejandro", "ignacio", "felipe", "vicente", "emilio", "cristobal", "mauricio", "diego", "jean", "agustin", "joaquin", "thomas", "martin", "angel", "alonso"]
    nombres_femeninos = ["maria", "ana", "sofia", "laura", "paula", "trinidad", "mariana", "lizeth", "alexandra", "lisset"] 

    if first_word in nombres_masculinos:
        return 'M'
    elif first_word in nombres_femeninos:
        return 'F'
    
    return None # Retorna None si no puede adivinar con certeza

def normalizar(texto):
    """Normaliza texto: quita espacios, minúsculas, tildes y reemplaza espacios por guiones bajos."""
    if not isinstance(texto, str):
        return ""
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = texto.replace(" ", "_")
    return texto

def enviar_correo_sendgrid(asunto, cuerpo, adjuntos=None):
    """Envía un correo electrónico usando la API de SendGrid."""
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

# -------------------- Google Drive API Functions (Empresa) --------------------

_COMPANY_DRIVE_CREDS = None # Variable global para almacenar las credenciales de la empresa

def get_company_google_credentials():
    """
    Obtiene y refresca las credenciales de Google para la cuenta de la empresa.
    Utiliza el refresh token almacenado en las variables de entorno.
    Almacena las credenciales en una variable global para reutilización.
    """
    global _COMPANY_DRIVE_CREDS

    if _COMPANY_DRIVE_CREDS and _COMPANY_DRIVE_CREDS.valid:
        print("DEBUG: Credenciales de Google Drive de empresa válidas y en caché.")
        return _COMPANY_DRIVE_CREDS

    if not GOOGLE_DRIVE_REFRESH_TOKEN:
        print("ERROR: GOOGLE_DRIVE_REFRESH_TOKEN no está configurado en las variables de entorno.")
        return None
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print("ERROR: GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET no están configurados.")
        return None

    creds = Credentials(
        None, 
        refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )
    
    try:
        print("DEBUG: Intentando refrescar token de Google Drive de empresa...")
        creds.refresh(Request())
        _COMPANY_DRIVE_CREDS = creds 
        print("DEBUG: Token de acceso de Google Drive de empresa refrescado y credenciales obtenidas.")
        return creds
    except Exception as e:
        print(f"ERROR: No se pudo refrescar el token de Google Drive de empresa: {e}")
        return None

def find_or_create_drive_folder(service, folder_name, parent_folder_id=None):
    """
    Busca una carpeta por nombre. Si no existe, la crea.
    """
    try:
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'"
        if parent_folder_id:
            query += f" and '{parent_folder_id}' in parents"
        
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])

        if items:
            print(f"DEBUG: Carpeta '{folder_name}' encontrada con ID: {items[0]['id']}")
            return items[0]['id']
        else:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]
            
            folder = service.files().create(body=file_metadata, fields='id').execute()
            print(f"DEBUG: Carpeta '{folder_name}' creada con ID: {folder.get('id')}")
            return folder.get('id')
    except HttpError as error:
        print(f"ERROR: Error al buscar o crear carpeta en Google Drive: {error}")
        return None
    except Exception as e:
        print(f"ERROR: Error inesperado en find_or_create_drive_folder: {e}")
        return None

def upload_pdf_to_google_drive(creds, file_content_io, file_name, folder_id=None):
    """
    Sube un archivo PDF a Google Drive.
    """
    try:
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': file_name, 'mimeType': 'application/pdf'}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        file_content_io.seek(0)

        file = service.files().create(
            body=file_metadata,
            media_body=file_content_io,
            media_mime_type='application/pdf', 
            fields='id'
        ).execute()

        print(f"DEBUG: Archivo subido a Google Drive. ID: {file.get('id')}")
        return file.get('id')

    except HttpError as error:
        print(f"ERROR: Ocurrió un error al subir a Google Drive: {error}")
        return None
    except Exception as e:
        print(f"ERROR: Error inesperado al subir a Google Drive: {e}")
        return None

# -------------------- Rutas de la Aplicación --------------------

@app.route('/relleno_formularios/<nomina_id>', methods=['GET'])
def relleno_formularios(nomina_id):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {session.get('usuario_id')}")

    nomina_data = None
    try:
        # Obtener form_type desde la nómina
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina,form_type"
        print(f"DEBUG: URL para obtener nómina en /relleno_formularios: {url_nomina}")
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        print(f"DEBUG: Datos de la nómina recibidos en /relleno_formularios: {nomina_data}")

        if not nomina_data:
            flash("❌ Nómina no encontrada.", 'error')
            return redirect(url_for('dashboard'))

        nomina = nomina_data[0]
        session['establecimiento'] = f"{nomina['nombre_nomina']} ({nomina['tipo_nomina'].replace('_', ' ').title()})"
        session['current_nomina_id'] = nomina_id
        session['establecimiento_nombre'] = nomina['nombre_nomina']
        # Guardar el form_type en la sesión para usarlo al renderizar la plantilla
        session['current_form_type'] = nomina.get('form_type', 'neurologia') 

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener datos de la nómina en /relleno_formularios: {e}")
        print(f"Response text: {res_nomina.text if 'res_nomina' in locals() else 'No response'}")
        flash('Error al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Error inesperado al procesar nómina en /relleno_formularios: {e}")
        flash('Error inesperado al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))

    estudiantes = []
    total_forms_completed_for_nomina = 0
    try:
        url_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        print(f"DEBUG: URL para obtener estudiantes en /relleno_formularios: {url_estudiantes}")
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        print(f"DEBUG: Estudiantes raw recibidos en /relleno_formularios: {estudiantes_raw}")


        for est in estudiantes_raw:
            if 'fecha_nacimiento' in est and isinstance(est['fecha_nacimiento'], str): 
                try:
                    fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                    est['edad'] = calculate_age(fecha_nac_obj)
                    est['fecha_nacimiento_formato'] = fecha_nac_obj.strftime("%d-%m-%Y")
                except ValueError:
                    est['fecha_nacimiento_formato'] = 'Fecha Inválida'
                    est['edad'] = 'N/A'
            else:
                est['fecha_nacimiento_formato'] = 'N/A'
                est['edad'] = 'N/A'
            
            if est.get('fecha_relleno') is not None:
                total_forms_completed_for_nomina += 0

            estudiantes.append(est)
        print(f"DEBUG: Estudiantes procesados para plantilla en /relleno_formularios: {estudiantes}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener estudiantes de la nómina en /relleno_formularios: {e}")
        print(f"Response text: {res_estudiantes.text if 'res_estudiantes' in locals() else 'No response'}")
        flash('Error al cargar la lista de estudiantes.', 'error')
        estudiantes = []
    except Exception as e:
        print(f"❌ Error inesperado al procesar estudiantes en /relleno_formularios: {e}")
        flash('Error inesperado al cargar la lista de estudiantes.', 'error')
        estudiantes = []

    # Determinar qué plantilla HTML renderizar según el form_type
    template_name = 'formulario_relleno.html' # Default
    if session.get('current_form_type') == 'medicina_familiar':
        template_name = 'formulario_medicina_familiar.html'
    elif session.get('current_form_type') == 'neurologia':
        template_name = 'formulario_relleno.html' # Asumiendo que este es el de neurología

    return render_template(template_name, 
                           estudiantes=estudiantes, 
                           total_forms_completed_for_nomina=total_forms_completed_for_nomina,
                           establecimiento_nombre=nomina['nombre_nomina'])


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        flash('Debes iniciar sesión para acceder a esta página.', 'danger')
        return redirect(url_for('index'))

    # Obtener todos los campos del formulario al principio para evitar NameErrors
    estudiante_id = request.form.get('estudiante_id', '')
    nomina_id = request.form.get('nomina_id', '')
    nombre = request.form.get('nombre', '') # Para neurología
    rut = request.form.get('rut', '')
    fecha_nac_original = request.form.get('fecha_nacimiento_original', '') 
    fecha_nac_formato = request.form.get('fecha_nacimiento_formato', '') # Ya formateado para PDF
    edad = request.form.get('edad', '')
    nacionalidad = request.form.get('nacionalidad', '')
    sexo = request.form.get('sexo', '') # Para neurología
    estado_general = request.form.get('estado', '') # Para neurología
    diagnostico = request.form.get('diagnostico', '') # Para neurología
    derivaciones = request.form.get('derivaciones', '') # Para ambos
    fecha_eval = datetime.today().strftime('%d/%m/%Y')

    # Campos específicos de Medicina Familiar
    nombre_apellido_familiar = request.form.get('nombre_apellido', '')
    genero_f_form = request.form.get('genero_f', '')
    genero_m_form = request.form.get('genero_m', '')
    diagnostico_1 = request.form.get('diagnostico_1', '')
    diagnostico_2 = request.form.get('diagnostico_2', '')
    diagnostico_complementario = request.form.get('diagnostico_complementario', '')
    fecha_reevaluacion_select = request.form.get('fecha_reevaluacion_select', '')
    observacion_1 = request.form.get('observacion_1', '')
    observacion_2 = request.form.get('observacion_2', '')
    observacion_3 = request.form.get('observacion_3', '')
    observacion_4 = request.form.get('observacion_4', '')
    observacion_5 = request.form.get('observacion_5', '')
    observacion_6 = request.form.get('observacion_6', '')
    observacion_7 = request.form.get('observacion_7', '')
    altura = request.form.get('altura', '')
    peso = request.form.get('peso', '')
    imc = request.form.get('imc', '')
    clasificacion = request.form.get('clasificacion', '')

    # Checkboxes de Medicina Familiar
    check_cesarea = request.form.get('check_cesarea') == 'on'
    check_atermino = request.form.get('check_atermino') == 'on'
    check_vaginal = request.form.get('check_vaginal') == 'on'
    check_prematuro = request.form.get('check_prematuro') == 'on'
    check_acorde = request.form.get('check_acorde') == 'on'
    check_retrasogeneralizado = request.form.get('check_retrasogeneralizado') == 'on'
    check_esquemai = request.form.get('check_esquemai') == 'on'
    check_esquemac = request.form.get('check_esquemac') == 'on'
    check_alergiano = request.form.get('check_alergiano') == 'on'
    check_alergiasi = request.form.get('check_alergiasi') == 'on'
    check_cirugiano = request.form.get('check_cirugiano') == 'on'
    check_cirugiasi = request.form.get('check_cirugiasi') == 'on'
    check_visionsinalteracion = request.form.get('check_visionsinalteracion') == 'on'
    check_visionrefraccion = request.form.get('check_visionrefraccion') == 'on'
    check_hipoacusia = request.form.get('check_hipoacusia') == 'on'
    check_retenciondental = request.form.get('check_retenciondental') == 'on'
    check_hipertrofia = request.form.get('check_hipertrofia') == 'on'
    check_frenillolingual = request.form.get('check_frenillolingual') == 'on'
    check_sinhallazgos = request.form.get('check_sinhallazgos') == 'on'
    check_caries = request.form.get('check_caries') == 'on'
    check_audicionnormal = request.form.get('check_audicionnormal') == 'on'
    check_tapondecerumen = request.form.get('check_tapondecerumen') == 'on'
    check_apinamientodental = request.form.get('check_apinamientodental') == 'on'


    # Obtener el form_type de la sesión para saber qué PDF base usar
    form_type = session.get('current_form_type', 'neurologia') 

    print(f"DEBUG: generar_pdf - Datos recibidos: nombre={nombre}, rut={rut}, form_type={form_type}")

    # Validaciones específicas por tipo de formulario
    if form_type == 'neurologia':
        if not all([estudiante_id, nomina_id, nombre, rut, fecha_nac_original, edad, nacionalidad, sexo, estado_general, diagnostico, request.form.get('fecha_reevaluacion'), derivaciones]):
            flash('Faltan campos obligatorios en el formulario de Neurología para guardar y generar PDF.', 'danger')
            if 'current_nomina_id' in session:
                return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
            return redirect(url_for('dashboard'))
    elif form_type == 'medicina_familiar':
        # Validar campos específicos de Medicina Familiar
        required_familiar_fields = [
            'nombre_apellido', 'rut', 'fecha_nacimiento_original', 'edad', 'nacionalidad', 
            'diagnostico_1', 'derivaciones', 'fecha_reevaluacion_select'
        ]
        # Verificar que al menos uno de los géneros esté marcado
        if not (genero_f_form or genero_m_form):
            flash('Debe seleccionar el género (Femenino o Masculino) en el formulario Familiar.', 'danger')
            if 'current_nomina_id' in session:
                return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
            return redirect(url_for('dashboard'))

        for field_name in required_familiar_fields:
            if not request.form.get(field_name):
                print(f"DEBUG: Campo familiar faltante: {field_name}")
                flash(f'Faltan campos obligatorios en el formulario de Medicina Familiar para guardar y generar PDF (campo: {field_name}).', 'danger')
                if 'current_nomina_id' in session:
                    return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
                return redirect(url_for('dashboard'))
    else:
        flash('Tipo de formulario no reconocido para validación.', 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # Calcular fecha_reevaluacion para la DB y PDF
    fecha_reeval_db = None
    fecha_reeval_pdf = None

    if form_type == 'neurologia':
        fecha_reeval_db = request.form.get('fecha_reevaluacion')
        if fecha_reeval_db and "-" in fecha_reeval_db:
            try:
                fecha_reeval_pdf = datetime.strptime(fecha_reeval_db, '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                fecha_reeval_pdf = fecha_reeval_db
        else:
            fecha_reeval_pdf = fecha_reeval_db # Si viene en otro formato, se usa tal cual
    elif form_type == 'medicina_familiar':
        if fecha_reevaluacion_select:
            try:
                plazo_reevaluacion_years = int(fecha_reevaluacion_select)
                fecha_reeval_obj = date.today() + timedelta(days=plazo_reevaluacion_years * 365) # Aproximación
                fecha_reeval_db = fecha_reeval_obj.strftime('%Y-%m-%d')
                fecha_reeval_pdf = fecha_reeval_obj.strftime('%d/%m/%Y')
            except ValueError:
                print(f"ADVERTENCIA: Valor inválido para fecha_reevaluacion_select: {fecha_reevaluacion_select}")
                fecha_reeval_db = None
                fecha_reeval_pdf = None
        else:
            fecha_reeval_db = None
            fecha_reeval_pdf = None


    # 1. Persistir los datos del formulario en Supabase
    try:
        update_data = {
            'fecha_relleno': str(date.today()) 
        }
        
        if form_type == 'neurologia':
            update_data.update({
                'sexo': sexo,
                'estado_general': estado_general, 
                'diagnostico': diagnostico,
                'fecha_reevaluacion': fecha_reeval_db,
                'derivaciones': derivaciones,
            })
        elif form_type == 'medicina_familiar':
            if nombre_apellido_familiar:
                update_data['nombre'] = nombre_apellido_familiar # Actualizar el campo 'nombre' en Supabase

            if genero_f_form == 'Femenino':
                update_data["sexo"] = 'F'
            elif genero_m_form == 'Masculino':
                update_data["sexo"] = 'M'
            else:
                update_data["sexo"] = None 

            update_data.update({
                "diagnostico_1": diagnostico_1,
                "diagnostico_2": diagnostico_2,
                "diagnostico_complementario": diagnostico_complementario,
                "derivaciones": derivaciones,
                "fecha_reevaluacion": fecha_reeval_db, # Usar la fecha calculada
                "observacion_1": observacion_1,
                "observacion_2": observacion_2,
                "observacion_3": observacion_3,
                "observacion_4": observacion_4,
                "observacion_5": observacion_5,
                "observacion_6": observacion_6,
                "observacion_7": observacion_7,
                "altura": float(altura) if altura else None,
                "peso": float(peso) if peso else None,
                "imc": imc,
                "clasificacion": clasificacion,
                # Checkboxes
                "check_cesarea": check_cesarea, 
                "check_atermino": check_atermino,
                "check_vaginal": check_vaginal,
                "check_prematuro": check_prematuro,
                "check_acorde": check_acorde,
                "check_retrasogeneralizado": check_retrasogeneralizado,
                "check_esquemac": check_esquemac,
                "check_esquemai": check_esquemai,
                "check_alergiano": check_alergiano,
                "check_alergiasi": check_alergiasi,
                "check_cirugiano": check_cirugiano,
                "check_cirugiasi": check_cirugiasi,
                "check_visionsinalteracion": check_visionsinalteracion,
                "check_visionrefraccion": check_visionrefraccion,
                "check_audicionnormal": check_audicionnormal,
                "check_tapondecerumen": check_tapondecerumen,
                "check_sinhallazgos": check_sinhallazgos,
                "check_caries": check_caries,
                "check_apinamientodental": check_apinamientodental,
                "check_retenciondental": check_retenciondental,
                "check_frenillolingual": check_frenillolingual,
                "check_hipertrofia": check_hipertrofia,
            })
        
        print(f"DEBUG: Datos a actualizar en Supabase para estudiante {estudiante_id}: {update_data}")
        response_db = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=update_data
        )
        response_db.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al actualizar estudiante (status): {response_db.status_code}")
        print(f"DEBUG: Respuesta de Supabase al actualizar estudiante (text): {response_db.text}")
        flash('Formulario guardado en la base de datos.', 'success')

    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR AL GUARDAR FORMULARIO EN DB: {e} - {response_db.text if 'response_db' in locals() else ''}")
        flash("❌ Error al guardar el formulario en la base de datos. Intente de nuevo.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Error inesperado al guardar formulario en DB: {e}")
        flash(f"❌ Error inesperado al guardar el formulario: {str(e)}", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # 2. Generar el PDF con los datos actualizados
    # Seleccionar el PDF base según el form_type
    pdf_base_path = ''
    if form_type == 'neurologia':
        pdf_base_path = PDF_BASE_NEUROLOGIA
    elif form_type == 'medicina_familiar':
        pdf_base_path = PDF_BASE_FAMILIAR
    else:
        flash("❌ Tipo de formulario no reconocido para generar PDF.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    if not os.path.exists(pdf_base_path):
        flash(f"❌ Error: El archivo '{pdf_base_path}' no se encontró en la carpeta del servidor.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    try:
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        # Los campos a rellenar deben ser específicos para cada tipo de formulario
        campos = {}
        if form_type == 'neurologia':
            campos = {
                "nombre": nombre,
                "rut": rut,
                "fecha_nacimiento": fecha_nac_formato, 
                "nacionalidad": nacionalidad,
                "edad": edad,
                "diagnostico_1": diagnostico,
                "diagnostico_2": diagnostico, # Puede ser el mismo para neurología si no hay un segundo campo
                "estado_general": estado_general, 
                "fecha_evaluacion": fecha_eval,
                "fecha_reevaluacion": fecha_reeval_pdf,
                "derivaciones": derivaciones,
                "sexo_f": "X" if sexo == "F" else "",
                "sexo_m": "X" if sexo == "M" else "",
            }
        elif form_type == 'medicina_familiar':
            # Mapeo de los campos del formulario HTML a los campos del PDF Familiar
            # Usando los nombres EXACTOS encontrados en el PDF
            campos = {
                "Nombres y Apellidos": nombre_apellido_familiar,
                "GENERO": genero_f_form if genero_f_form else genero_m_form, # Asumiendo que es un campo de texto o radio que toma 'Femenino'/'Masculino'
                "RUN": rut,
                "Fecha nacimiento (dd/mm/aaaa)": fecha_nac_formato,
                "Edad (en años y meses)": edad,
                "Nacionalidad": nacionalidad,
                "Fecha evaluación": fecha_eval,
                "Fecha reevaluación": fecha_reeval_pdf, 
                "DIAGNÓSTICO": diagnostico_1, # Mapeado a DIAGNOSTICO principal
                "DIAGNÓSTICO COMPLEMENTARIO": diagnostico_complementario,
                "DERIVACIONES": derivaciones,
                # Campos de observación (necesitaríamos nombres únicos si se rellenan individualmente)
                "OBS:_1": observacion_1, # Ejemplo si el PDF tiene OBS_1
                "OBS:_2": observacion_2, # Ejemplo si el PDF tiene OBS_2
                "OBS:_3": observacion_3,
                "OBS:_4": observacion_4,
                "OBS:_5": observacion_5,
                "OBS:_6": observacion_6,
                "OBS:_7": observacion_7,
                "Altura:": altura, # Con dos puntos
                "Peso": peso,
                "I.M.C": imc, # Con puntos
                "Clasificación": clasificacion,
                # Checkboxes - Usando los nombres EXACTOS del PDF y el valor "/Yes"
                "CESAREA": "/Yes" if check_cesarea else "",
                "A TÉRMINO": "/Yes" if check_atermino else "",
                "VAGINAL": "/Yes" if check_vaginal else "",
                "PREMATURO": "/Yes" if check_prematuro else "",
                "LOGRADO ACORDE A LA EDAD": "/Yes" if check_acorde else "",
                "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if check_retrasogeneralizado else "",
                "ESQUEMA INCOMPLETO": "/Yes" if check_esquemai else "",
                "ESQUEMA COMPLETO": "/Yes" if check_esquemac else "",
                "NO": "/Yes" if check_alergiano else "", # Checkbox para ALERGIAS
                "NO_2": "/Yes" if check_cirugiano else "", # Checkbox para HOSPITALIZACIONES/CIRUGIAS
                "ST": "/Yes" if check_cirugiasi else "", # Checkbox para HOSPITALIZACIONES/CIRUGIAS
                "SIN ALTERACIÓN": "/Yes" if check_visionsinalteracion else "",
                "VICIOS DE REFRACCIÓN": "/Yes" if check_visionrefraccion else "",
                "NORMAL": "/Yes" if check_audicionnormal else "", # Checkbox para AUDICIÓN
                "TAPÓN DE CERUMEN": "/Yes" if check_tapondecerumen else "",
                "HIPOACUSIA": "/Yes" if check_hipoacusia else "",
                "SIN HALLAZGOS": "/Yes" if check_sinhallazgos else "",
                "CARIES": "/Yes" if check_caries else "",
                "APIÑAMIENTO DENTAL": "/Yes" if check_apinamientodental else "",
                "RETENCIÓN DENTAL.": "/Yes" if check_retenciondental else "", # Con punto
                "FRENILLO LINGUAL": "/Yes" if check_frenillolingual else "",
                "HIPERTROFIA AMIGDALINA": "/Yes" if check_hipertrofia else "",
            }

        print(f"DEBUG: Campos a rellenar en PDF (JSON): {json.dumps(campos, indent=2)}")

        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })

        writer.update_page_form_field_values(writer.pages[0], campos)

        # Forzar la regeneración de la apariencia para que los campos se muestren
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })

        # --- INICIO LÓGICA DE APLANADO EXPLÍCITO CON PyPDF2 ---
        # Iterar sobre las anotaciones de la página para "aplanar" los campos.
        # Esto los convierte en contenido estático y asegura su visibilidad.
        # Advertencia: Los campos ya no serán editables después de esto.
        page = writer.pages[0]
        if "/Annots" in page:
            for i in range(len(page["/Annots"])):
                annot = page["/Annots"][i].get_object()
                if "/FT" in annot: # Si es un campo de formulario
                    # Eliminar la bandera de campo de formulario para que no sea interactivo
                    if "/Ff" in annot:
                        del annot["/Ff"]
                    # Eliminar la apariencia (AP) para que el visor la regenere o use el valor (V)
                    # Si el visor no la genera, el valor (V) debería ser visible
                    if "/AP" in annot:
                        del annot["/AP"]
                    # Establecer el valor como el valor predeterminado para que se "imprima"
                    # Esto a menudo ayuda a la visibilidad en algunos visores
                    if "/V" in annot and "/DV" not in annot:
                        annot[Name("/DV")] = annot["/V"]
        
        # Eliminar el diccionario AcroForm del documento si todos los campos son aplanados
        # Esto hace que el PDF se trate como un documento estático por la mayoría de los visores.
        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]
        # --- FIN LÓGICA DE APLANADO EXPLÍCITO ---


        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        nombre_para_archivo = nombre_apellido_familiar if form_type == 'medicina_familiar' else nombre
        if not nombre_para_archivo: 
            nombre_para_archivo = "Desconocido"

        nombre_archivo_descarga = f"{nombre_para_archivo.replace(' ', '_')}_{rut}_formulario_{form_type}.pdf"
        print(f"DEBUG: PDF generado y listo para descarga: {nombre_archivo_descarga}")
        flash('PDF generado correctamente.', 'success')
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


@app.route('/marcar_evaluado', methods=['POST'])
def marcar_evaluado():
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401

    estudiante_id = request.form.get('estudiante_id', '')
    nomina_id = request.form.get('nomina_id', '')
    doctora_id = session.get('usuario_id')

    # Obtener el form_type de la sesión para saber qué campos actualizar
    form_type = session.get('current_form_type', 'neurologia') 

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}, form_type={form_type}")
    print(f"DEBUG: Datos completos recibidos para guardar: {request.form.to_dict()}")

    if not all([estudiante_id, nomina_id, doctora_id]):
        print(f"ERROR: Datos faltantes en /marcar_evaluado. Estudiante ID: {estudiante_id}, Nomina ID: {nomina_id}, Doctora ID: {doctora_id}. Campos del formulario: {request.form.to_dict()}")
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400

    update_data = {
        'fecha_relleno': str(date.today()), 
        'doctora_evaluadora_id': doctora_id, 
    }

    # Obtener campos comunes y específicos al principio para evitar NameErrors
    nombre_form = request.form.get('nombre', '') # Para neurología
    rut_form = request.form.get('rut', '')
    fecha_nacimiento_original_form = request.form.get('fecha_nacimiento_original', '')
    nacionalidad_form = request.form.get('nacionalidad', '')
    edad_form = request.form.get('edad', '')

    # Campos específicos de Neurología
    sexo_neuro = request.form.get('sexo', '')
    estado_general_neuro = request.form.get('estado', '')
    diagnostico_neuro = request.form.get('diagnostico', '')
    fecha_reevaluacion_neuro = request.form.get('fecha_reevaluacion', '')
    derivaciones_neuro = request.form.get('derivaciones', '')

    # Campos específicos de Medicina Familiar
    nombre_apellido_familiar = request.form.get('nombre_apellido', '')
    genero_f_form = request.form.get('genero_f', '')
    genero_m_form = request.form.get('genero_m', '')
    diagnostico_1_familiar = request.form.get('diagnostico_1', '')
    diagnostico_2_familiar = request.form.get('diagnostico_2', '')
    diagnostico_complementario_familiar = request.form.get('diagnostico_complementario', '')
    fecha_reevaluacion_select_familiar = request.form.get('fecha_reevaluacion_select', '')
    observacion_1_familiar = request.form.get('observacion_1', '')
    observacion_2_familiar = request.form.get('observacion_2', '')
    observacion_3_familiar = request.form.get('observacion_3', '')
    observacion_4_familiar = request.form.get('observacion_4', '')
    observacion_5_familiar = request.form.get('observacion_5', '')
    observacion_6_familiar = request.form.get('observacion_6', '')
    observacion_7_familiar = request.form.get('observacion_7', '')
    altura_familiar = request.form.get('altura', '')
    peso_familiar = request.form.get('peso', '')
    imc_familiar = request.form.get('imc', '')
    clasificacion_familiar = request.form.get('clasificacion', '')

    # Checkboxes de Medicina Familiar
    check_cesarea_familiar = request.form.get('check_cesarea') == 'on'
    check_atermino_familiar = request.form.get('check_atermino') == 'on'
    check_vaginal_familiar = request.form.get('check_vaginal') == 'on'
    check_prematuro_familiar = request.form.get('check_prematuro') == 'on'
    check_acorde_familiar = request.form.get('check_acorde') == 'on'
    check_retrasogeneralizado_familiar = request.form.get('check_retrasogeneralizado') == 'on'
    check_esquemai_familiar = request.form.get('check_esquemai') == 'on'
    check_esquemac_familiar = request.form.get('check_esquemac') == 'on'
    check_alergiano_familiar = request.form.get('check_alergiano') == 'on'
    check_alergiasi = request.form.get('check_alergiasi') == 'on'
    check_cirugiano_familiar = request.form.get('check_cirugiano') == 'on'
    check_cirugiasi_familiar = request.form.get('check_cirugiasi') == 'on'
    check_visionsinalteracion_familiar = request.form.get('check_visionsinalteracion') == 'on'
    check_visionrefraccion_familiar = request.form.get('check_visionrefraccion') == 'on'
    check_hipoacusia_familiar = request.form.get('check_hipoacusia') == 'on'
    check_retenciondental_familiar = request.form.get('check_retenciondental') == 'on'
    check_hipertrofia_familiar = request.form.get('check_hipertrofia') == 'on'
    check_frenillolingual_familiar = request.form.get('check_frenillolingual') == 'on'
    check_sinhallazgos_familiar = request.form.get('check_sinhallazgos') == 'on'
    check_caries_familiar = request.form.get('check_caries') == 'on'
    check_audicionnormal_familiar = request.form.get('check_audicionnormal') == 'on'
    check_tapondecerumen_familiar = request.form.get('check_tapondecerumen') == 'on'
    check_apinamientodental_familiar = request.form.get('check_apinamientodental') == 'on'


    # Es crucial obtener el nombre del estudiante de la base de datos si no viene en el formulario
    # para evitar que se ponga en 'None' si no se envía en el POST
    try:
        res_estudiante_actual = requests.get(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=nombre,rut,fecha_nacimiento,nacionalidad",
            headers=SUPABASE_HEADERS
        )
        res_estudiante_actual.raise_for_status()
        estudiante_actual_data = res_estudiante_actual.json()
        if estudiante_actual_data:
            update_data['nombre'] = estudiante_actual_data[0].get('nombre')
            update_data['rut'] = estudiante_actual_data[0].get('rut')
            update_data['fecha_nacimiento'] = estudiante_actual_data[0].get('fecha_nacimiento')
            update_data['nacionalidad'] = estudiante_actual_data[0].get('nacionalidad')
        else:
            print(f"ADVERTENCIA: Estudiante {estudiante_id} no encontrado en DB al marcar como evaluado. Usando datos del formulario POST como fallback.")
            update_data['nombre'] = nombre_form if form_type == 'neurologia' else nombre_apellido_familiar
            update_data['rut'] = rut_form
            update_data['fecha_nacimiento'] = fecha_nacimiento_original_form
            update_data['nacionalidad'] = nacionalidad_form
            
    except requests.exceptions.RequestException as e:
        print(f"ERROR: No se pudo obtener datos actuales del estudiante {estudiante_id}: {e}. Intentando usar datos del formulario POST.")
        update_data['nombre'] = nombre_form if form_type == 'neurologia' else nombre_apellido_familiar
        update_data['rut'] = rut_form
        update_data['fecha_nacimiento'] = fecha_nacimiento_original_form
        update_data['nacionalidad'] = nacionalidad_form

    update_data['edad'] = edad_form # Guardar la cadena de edad calculada

    # Lógica para campos específicos según el tipo de formulario
    if form_type == 'neurologia':
        update_data.update({
            'sexo': sexo_neuro,
            'estado_general': estado_general_neuro,
            'diagnostico': diagnostico_neuro,
            'fecha_reevaluacion': fecha_reevaluacion_neuro, 
            'derivaciones': derivaciones_neuro,
        })
    elif form_type == 'medicina_familiar':
        # Actualizar el campo 'sexo' general basado en los radio buttons de familiar
        # Aquí se asume que el campo 'sexo' en la DB puede almacenar 'F' o 'M'
        if genero_f_form == 'Femenino':
            update_data["sexo"] = 'F'
        elif genero_m_form == 'Masculino':
            update_data["sexo"] = 'M'
        else:
            update_data["sexo"] = None 

        # Calcular fecha_reevaluacion basada en el select de años
        fecha_reeval_db = None
        if fecha_reevaluacion_select_familiar:
            try:
                plazo_reevaluacion_years = int(fecha_reevaluacion_select_familiar)
                fecha_reeval_obj = date.today() + timedelta(days=plazo_reevaluacion_years * 365) 
                fecha_reeval_db = fecha_reeval_obj.strftime('%Y-%m-%d')
            except ValueError:
                print(f"ADVERTENCIA: Valor inválido para fecha_reevaluacion_select en marcar_evaluado: {fecha_reevaluacion_select_familiar}")
                fecha_reeval_db = None
        
        update_data.update({
            "diagnostico_1": diagnostico_1_familiar,
            "diagnostico_2": diagnostico_2_familiar,
            "diagnostico_complementario": diagnostico_complementario_familiar,
            "derivaciones": derivaciones, # Usar la variable general derivaciones
            "observacion_1": observacion_1_familiar,
            "observacion_2": observacion_2_familiar,
            "observacion_3": observacion_3_familiar,
            "observacion_4": observacion_4_familiar,
            "observacion_5": observacion_5_familiar,
            "observacion_6": observacion_6_familiar,
            "observacion_7": observacion_7_familiar,
            "altura": float(altura_familiar) if altura_familiar else None,
            "peso": float(peso_familiar) if peso_familiar else None,
            "imc": imc_familiar,
            "clasificacion": clasificacion_familiar,
            "fecha_evaluacion": str(date.today()), 
            "fecha_reevaluacion": fecha_reeval_db, 
            # Checkboxes - Estos valores se guardan como booleanos en la DB
            "check_cesarea": check_cesarea_familiar,
            "check_atermino": check_atermino_familiar,
            "check_vaginal": check_vaginal_familiar,
            "check_prematuro": check_prematuro_familiar,
            "check_acorde": check_acorde_familiar,
            "check_retrasogeneralizado": check_retrasogeneralizado_familiar,
            "check_esquemac": check_esquemac_familiar,
            "check_esquemai": check_esquemai_familiar,
            "check_alergiano": check_alergiano_familiar,
            "check_alergiasi": check_alergiasi_familiar,
            "check_cirugiano": check_cirugiano_familiar,
            "check_cirugiasi": check_cirugiasi_familiar,
            "check_visionsinalteracion": check_visionsinalteracion_familiar,
            "check_visionrefraccion": check_visionrefraccion_familiar,
            "check_audicionnormal": check_audicionnormal_familiar,
            "check_hipoacusia": check_hipoacusia_familiar,
            "check_retenciondental": check_retenciondental_familiar,
            "check_hipertrofia": check_hipertrofia_familiar,
            "check_frenillolingual": check_frenillolingual_familiar,
            "check_sinhallazgos": check_sinhallazgos_familiar,
            "check_caries": check_caries_familiar,
            "check_apinamientodental": check_apinamientodental_familiar,
            "check_retenciondental": check_retenciondental_familiar,
            "check_frenillolingual": check_frenillolingual_familiar,
            "check_hipertrofia": check_hipertrofia_familiar,
        })

    try:
        print(f"DEBUG: Intentando PATCH a estudiantes_nomina con ID: {estudiante_id}. Payload: {update_data}")
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=update_data
        )
        
        if response.status_code >= 400: 
            print(f"ERROR: Supabase PATCH falló en /marcar_evaluado.")
            print(f"ERROR: Estado HTTP: {response.status_code}")
            print(f"ERROR: Cuerpo de la respuesta de Supabase: {response.text}")
            return jsonify({"success": False, "message": f"Error al actualizar estudiante: {response.text}"}), response.status_code

        print(f"DEBUG: Estudiante {estudiante_id} marcado como evaluado y guardado en Supabase. Status: {response.status_code}")
        print(f"DEBUG: Respuesta exitosa de Supabase: {response.text}")
        return jsonify({"success": True, "message": "Estudiante marcado como evaluado y datos guardados."})

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al marcar estudiante como evaluado: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con Supabase: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al marcar estudiante como evaluado: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario = request.form['username']
    clave = request.form['password']
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario}&password=eq.{clave}"
    print(f"DEBUG: Intento de login para usuario: {usuario}, URL: {url}")
    try:
        res = requests.get(url, headers=SUPABASE_SERVICE_HEADERS) 
        res.raise_for_status()
        data = res.json()
        print(f"DEBUG: Respuesta Supabase login: {data}")
        if data:
            session['usuario'] = usuario
            session['usuario_id'] = data[0]['id']
            print(f"DEBUG: Sesión iniciada: usuario={session['usuario']}, usuario_id={session['usuario_id']}")
            flash(f'¡Bienvenido, {usuario}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrecta.', 'error')
        return redirect(url_for('index'))
    except requests.exceptions.RequestException as e:
        print(f"❌ Error en el login: {e} - {res.text if 'res' in locals() else ''}")
        flash('Error de conexión al intentar iniciar sesión. Intente de nuevo.', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario = session['usuario']
    usuario_id = session.get('usuario_id')
    print(f"DEBUG: Accediendo a dashboard para usuario: {usuario}, ID: {usuario_id}")

    doctoras = []
    establecimientos_admin_list = []
    admin_nominas_cargadas = []
    conteo = {}
    
    doctor_performance_data = {} # Para admin: conteo de formularios por cada doctora
    doctor_performance_data_single_doctor = {'completed': 0, 'pending': 0, 'total': 0} # Para doctora individual


    campos_establecimientos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo,doctora_id"
    eventos = []
    try:
        if usuario != 'admin':
            url_eventos = (
                f"{SUPABASE_URL}/rest/v1/establecimientos"
                f"?doctora_id=eq.{usuario_id}"
                f"&select={campos_establecimientos}"
            )
        else:
            url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos_establecimientos}"
            
        print(f"DEBUG: URL para obtener eventos: {url_eventos}")
        res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
        res_eventos.raise_for_status()
        eventos = res_eventos.json()
        print(f"DEBUG: Eventos recibidos: {eventos}")

        if isinstance(eventos, list):
            eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0] if e.get('horario') else '')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener eventos: {e}")
        print(f"Response text: {res_eventos.text if 'res_eventos' in locals() else 'No response'}")
        flash('Error al cargar el calendario de visitas.', 'error')

    formularios = []
    try:
        url_formularios_subidos = f"{SUPABASE_URL}/rest/v1/formularios_subidos"
        print(f"DEBUG: URL para obtener formularios subidos: {url_formularios_subidos}")
        res_formularios = requests.get(url_formularios_subidos, headers=SUPABASE_HEADERS)
        res_formularios.raise_for_status()
        formularios = res_formularios.json()
        print(f"DEBUG: Formularios subidos recibidos: {formularios}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener formularios subidos: {e}")
        print(f"Response text: {res_formularios.text if 'res_formularios' in locals() else 'No response'}")
        flash('Error al cargar los formularios subidos.', 'error')

    assigned_nominations = []
    if usuario != 'admin':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}"
                f"&select=id,nombre_nomina,tipo_nomina,form_type" # Incluir form_type
            )
            print(f"DEBUG: URL para obtener nóminas asignadas (doctor): {url_nominas_asignadas}")
            res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
            res_nominas_asignadas.raise_for_status()
            raw_nominas = res_nominas_asignadas.json()
            print(f"DEBUG: Nóminas raw recibidas para doctora: {raw_nominas}")

            for nom in raw_nominas:
                display_name = nom['tipo_nomina'].replace('_', ' ').title()
                assigned_nominations.append({
                    'id': nom['id'],
                    'nombre_establecimiento': nom['nombre_nomina'],
                    'tipo_nomina_display': display_name,
                    'form_type': nom.get('form_type') # Pasar el form_type
                })
            print(f"DEBUG: Nóminas asignadas procesadas para plantilla: {assigned_nominations}")
            
            # --- LÓGICA DE RENDIMIENTO PARA DOCTORA INDIVIDUAL ---
            # 1. Obtener todas las nóminas asignadas a esta doctora para determinar el "total" de alumnos a evaluar
            nomina_ids_for_doctor = [n['id'] for n in raw_nominas]
            
            total_students_in_assigned_nominas = 0
            if nomina_ids_for_doctor:
                nomina_ids_str = ",".join(nomina_ids_for_doctor)
                url_total_students_assigned_to_doctor_nominations = (
                    f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                    f"?nomina_id=in.({nomina_ids_str})"
                    f"&select=count"
                )
                print(f"DEBUG: URL para contar todos los estudiantes en nóminas asignadas a doctora {usuario_id}: {url_total_students_assigned_to_doctor_nominations}")
                res_total_students = requests.get(url_total_students_assigned_to_doctor_nominations, headers=SUPABASE_HEADERS)
                res_total_students.raise_for_status()
                total_students_count_range = res_total_students.headers.get('Content-Range')
                if total_students_count_range:
                    try:
                        total_students_in_assigned_nominas = int(total_students_count_range.split('/')[-1])
                    except ValueError:
                        pass
                print(f"DEBUG: Total de estudiantes en nóminas asignadas para doctora {usuario_id}: {total_students_in_assigned_nominas}")


            # 2. Contar los estudiantes que esta DOCTORA ESPECÍFICA ha evaluado
            url_completed_by_this_doctor = (
                f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                f"?doctora_evaluadora_id=eq.{usuario_id}" # Filtrar por la doctora que evaluó
                f"&fecha_relleno.not.is.null" # Que el formulario haya sido rellenado
                f"&select=count"
            )
            print(f"DEBUG: URL para contar formularios completados por doctora {usuario_id}: {url_completed_by_this_doctor}")
            # Usar SERVICE_HEADERS para el conteo de evaluaciones, ya que accede a datos de 'fecha_relleno' y 'doctora_evaluadora_id'
            res_completed_by_this_doctor = requests.get(url_completed_by_this_doctor, headers=SUPABASE_SERVICE_HEADERS) 
            res_completed_by_this_doctor.raise_for_status()
            completed_forms_count_range = res_completed_by_this_doctor.headers.get('Content-Range')
            completed_count_by_doctor = 0
            if completed_forms_count_range:
                try:
                    completed_count_by_doctor = int(completed_forms_count_range.split('/')[-1])
                except ValueError:
                    pass
            print(f"DEBUG: Formularios completados por doctora {usuario_id}: {completed_count_by_doctor}")


            doctor_performance_data_single_doctor = {
                'completed': completed_count_by_doctor,
                'total': total_students_in_assigned_nominas,
                'pending': total_students_in_assigned_nominas - completed_count_by_doctor if total_students_in_assigned_nominas >= completed_count_by_doctor else 0
            }
            print(f"DEBUG: Rendimiento final para doctora {usuario_id}: {doctor_performance_data_single_doctor}")


        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas o conteo de evaluaciones: {e}")
            print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
            flash('Error al cargar sus nóminas asignadas o conteo de evaluaciones.', 'error')

    if usuario == 'admin':
        try:
            url_doctoras = f"{SUPABASE_URL}/rest/v1/doctoras"
            print(f"DEBUG: URL para obtener doctoras (admin con service key): {url_doctoras}") 
            res_doctoras = requests.get(url_doctoras, headers=SUPABASE_SERVICE_HEADERS) 
            res_doctoras.raise_for_status()
            doctoras_raw = res_doctoras.json()
            doctoras = []
            for doc in doctoras_raw:
                doctoras.append({'id': doc['id'], 'usuario': doc['usuario']})
            print(f"DEBUG: Doctoras recibidas (admin): {doctoras}")
        except requests.exceptions.RequestException as e:
            print(f"❌ ERROR AL OBTENER DOCTORAS (ADMIN DASHBOARD) CON SERVICE KEY: {e} - {res_doctoras.text if 'res_doctoras' in locals() else ''}")
            flash('Error crítico al cargar doctoras en el panel de administrador. Verifique su SUPABASE_SERVICE_KEY.', 'error')
            doctoras = [] 

        try:
            url_establecimientos_admin = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre"
            print(f"DEBUG: URL para obtener establecimientos (admin con service key): {url_establecimientos_admin}") 
            res_establecimientos = requests.get(url_establecimientos_admin, headers=SUPABASE_SERVICE_HEADERS) 
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
            print(f"DEBUG: Establecimientos recibidos (admin): {establecimientos_admin_list}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener establecimientos (ADMIN DASHBOARD) CON SERVICE KEY: {e}")
            print(f"Response text: {res_establecimientos.text if 'res_establecimientos' in locals() else 'No response'}")
            flash('Error crítico al cargar establecimientos en el panel de administrador. Verifique su SUPABASE_SERVICE_KEY.', 'error')
            establecimientos_admin_list = [] 


        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1
        print(f"DEBUG: Conteo de formularios por establecimiento: {conteo}")

        try:
            # Incluir form_type en la consulta de nóminas para admin
            url_admin_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina,tipo_nomina,doctora_id,url_excel_original,nombre_excel_original,form_type"
            print(f"DEBUG: URL para obtener nóminas cargadas por admin: {url_admin_nominas}")
            res_admin_nominas = requests.get(url_admin_nominas, headers=SUPABASE_HEADERS)
            res_admin_nominas.raise_for_status()
            admin_nominas_cargadas = res_admin_nominas.json()
            print(f"DEBUG: Nóminas cargadas por admin recibidas: {admin_nominas_cargadas}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas cargadas por admin: {e}")
            print(f"Response text: {res_admin_nominas.text if 'res_admin_nominas' in locals() else 'No response'}")
            flash('Error al cargar la lista de nóminas en la vista de administrador.', 'error')
        
        # --- LÓGICA DE RENDIMIENTO POR DOCTORA PARA ADMIN ---
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
                    print(f"DEBUG: URL para contar formularios de doctora {doctor_name} (admin view): {url_doctor_forms_count}")
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
                    print(f"DEBUG: Doctora {doctor_name} (ID: {doctor_id}) ha completado {completed_forms_count} formularios.")

                except requests.exceptions.RequestException as e:
                    print(f"❌ ERROR AL OBTENER FORMULARIOS COMPLETADOS PARA DOCTORA {doctor_name} (ADMIN VIEW): {e}")
                    doctor_performance_data[doctor_name] = 0 
                except Exception as e:
                    print(f"❌ Error inesperado al procesar rendimiento de doctora {doctor_name} (admin view): {e}")
                    doctor_performance_data[doctor_name] = 0


    return render_template(
        'dashboard.html',
        usuario=usuario,
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
    

    print(f"DEBUG: admin_agregar - Datos recibidos: nombre={nombre}, fecha={fecha}, horario={horario}, doctora_id_from_form={doctora_id_from_form}, alumnos={cantidad_alumnos}")

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
    print(f"DEBUG: Payload para insertar establecimiento: {data_establecimiento}")

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_establecimiento
        )
        response_db.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar establecimiento (status): {response_db.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar establecimiento (text): {response_db.text}")
        flash("✅ Establecimiento agregado correctamente.", 'success')
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR AL GUARDAR ESTABLECIMIENTO EN DB: {e} - {response_db.text if 'response_db' in locals() else ''}")
        flash("❌ Error al guardar el establecimiento en la base de datos.", 'error')
    except Exception as e:
        print(f"❌ Error inesperado al guardar establecimiento: {e}")
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

    # Normalizar tipo_nomina para una comparación robusta (ej. "NEUROLOGIA" -> "neurologia")
    tipo_nomina_normalized = tipo_nomina_raw.strip().lower() if tipo_nomina_raw else ''

    # Determinar el form_type basado en tipo_nomina normalizado
    form_type = None
    if 'neurologia' in tipo_nomina_normalized: 
        form_type = 'neurologia'
    elif 'familiar' in tipo_nomina_normalized: 
        form_type = 'medicina_familiar'
    # Puedes añadir más condiciones aquí si tienes otros tipos de nómina que mapean a otros PDFs
    # elif 'otro_tipo' in tipo_nomina_normalized:
    #     form_type = 'otro_pdf_base'

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina_raw={tipo_nomina_raw}, tipo_nomina_normalized={tipo_nomina_normalized}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}, form_type_derivado={form_type}")

    # Validar campos obligatorios antes de intentar subir o insertar
    if not all([tipo_nomina_raw, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Falta uno o más campos obligatorios para cargar la nómina (tipo, nombre, doctora, archivo).', 'error')
        print(f"ERROR: Datos obligatorios faltantes: tipo_nomina_raw={tipo_nomina_raw}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, excel_file_present={bool(excel_file)}")
        return redirect(url_for('dashboard'))

    # Validar que se haya podido determinar un tipo de formulario
    if form_type is None: 
        flash(f'❌ El tipo de nómina "{tipo_nomina_raw}" no se pudo mapear a un tipo de formulario conocido. Por favor, verifique el tipo de nómina.', 'error')
        print(f"ERROR: Tipo de nómina no reconocido: {tipo_nomina_raw}. No se pudo derivar form_type.")
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
        print(f"DEBUG: Subiendo archivo Excel a Storage: {upload_url}")
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" 
        print(f"DEBUG: Archivo Excel subido, URL pública: {url_excel_publica}")
    except requests.exceptions.RequestException as e:
        error_detail = res_upload.text if 'res_upload' in locals() else 'No response from Supabase Storage.'
        print(f"❌ Error al subir archivo Excel a Storage: {e} - Detalles de Supabase Storage: {error_detail}")
        flash(f"❌ Error al subir el archivo de la nómina a Supabase Storage: {error_detail}", 'error')
        return redirect(url_for('dashboard'))

    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina_raw, # Guardamos el tipo_nomina original del formulario
        "doctora_id": doctora_id_from_form,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename,
        "form_type": form_type # Guardar el form_type derivado en la nómina
    }
    print(f"DEBUG: Payload para insertar nómina en nominas_medicas: {data_nomina}")

    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (status): {res_insert_nomina.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (text): {res_insert_nomina.text}")

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_nomina.text if 'res_insert_nomina' in locals() else 'No response from Supabase.'
        print(f"❌ Error al guardar nómina en DB: {e} - Detalles de Supabase: {error_detail}")
        flash(f"❌ Error al guardar los datos de la nómina en la base de datos: {error_detail}", 'error')
        # Intentar limpiar el archivo subido si falla la inserción en la DB
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            print("DEBUG: Archivo subido limpiado después de fallo en inserción de nómina.")
        except Exception as cleanup_e:
            print(f"ERROR: Fallo al limpiar archivo subido: {cleanup_e}")
        return redirect(url_for('dashboard'))

    excel_data_stream = io.BytesIO(excel_file_data)
    
    if excel_filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(excel_data_stream)
        print("DEBUG: Archivo leído como Excel.")
    elif excel_filename.endswith('.csv'):
        df = pd.read_csv(excel_data_stream, encoding='utf-8')
        print("DEBUG: Archivo leído como CSV.")
    else:
        flash('❌ Formato de archivo no soportado para la nómina.', 'error')
        # Intentar limpiar el archivo subido y la entrada de la nómina si el formato no es soportado
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
            print("DEBUG: Rollback completo después de formato de archivo no soportado.")
        except Exception as rollback_e:
            print(f"❌ Error durante el rollback: {rollback_e}")
        return redirect(url_for('dashboard'))

    estudiantes_a_insertar = []
    # Normalizar los nombres de las columnas del DataFrame para que coincidan con el mapeo
    df.columns = [normalizar(col) for col in df.columns]

    print(f"DEBUG: Columnas del archivo normalizadas: {df.columns}")

    # Mapeo de los nombres de columna del Excel a los nombres de campo de la base de datos
    # Basado en la imagen de tu Excel
    column_mapping = {
        'nombre_completo': ['nombre_completo', 'nombre_del_estudiante', 'nombre'], # "Nombre Completo"
        'rut': ['rut'], # "rut"
        'fecha_nacimiento': ['fecha_nacimiento', 'fecha_de_nacimiento'], # "fecha_nacimiento"
        'nacionalidad': ['nacionalidad'], # "nacionalidad"
        # 'sexo' no está en tu Excel, se adivina o es nulo
    }
    
    col_map = {}
    for key, possible_names in column_mapping.items():
        for name in possible_names:
            if name in df.columns:
                col_map[key] = name
                break
    
    print(f"DEBUG: Mapeo de columnas encontrado: {col_map}")

    # Validar que las columnas críticas existan en el Excel
    required_columns_excel = ['nombre_completo', 'rut', 'fecha_nacimiento']
    if not all(k in col_map for k in required_columns_excel):
        missing_cols = [col for col in required_columns_excel if col not in col_map]
        print(f"ERROR: No se encontraron columnas críticas en el Excel: {missing_cols}. Columnas esperadas: {column_mapping.keys()}. Columnas encontradas: {df.columns.tolist()}")
        flash(f"❌ El archivo no contiene las columnas necesarias: {', '.join(missing_cols)}. Verifique que los encabezados sean 'Nombre Completo', 'rut', y 'fecha nacimiento' exactamente.", 'error')
        try:
            # Rollback: eliminar la nómina y el archivo subido si falla la lectura del Excel
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
            print("DEBUG: Rollback completado.")
        except Exception as rollback_e:
            print(f"❌ Error durante el rollback: {rollback_e}")
        return redirect(url_for('dashboard'))
        
    for index, row in df.iterrows():
        try:
            nombre_completo_raw = row.get(col_map.get('nombre_completo'))
            rut_raw = row.get(col_map.get('rut'))
            fecha_nacimiento_raw = row.get(col_map.get('fecha_nacimiento'))
            nacionalidad_raw = row.get(col_map.get('nacionalidad')) # Obtener nacionalidad directamente

            # Validar que los datos esenciales de la fila no estén vacíos
            if pd.isna(nombre_completo_raw) or pd.isna(rut_raw) or pd.isna(fecha_nacimiento_raw):
                print(f"AVISO: Fila {index+2} ignorada por datos faltantes (Nombre, RUT o Fecha de Nacimiento). Datos: {row.to_dict()}")
                continue
            
            # Limpiar RUT: quitar puntos y guiones
            rut_limpio = str(rut_raw).replace('.', '').replace('-', '').strip()
            
            # Convertir fecha de nacimiento a formatoYYYY-MM-DD
            fecha_nac_str = None
            if isinstance(fecha_nacimiento_raw, datetime):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            elif isinstance(fecha_nacimiento_raw, date):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            else:
                # Intentar parsear varios formatos comunes (DD-MM-YYYY, DD/MM/YYYY,YYYY-MM-DD, Excel serial)
                try:
                    # Usar pd.to_datetime para una conversión más robusta de fechas
                    parsed_date = pd.to_datetime(fecha_nacimiento_raw, errors='coerce')
                    if pd.notna(parsed_date):
                        fecha_nac_str = parsed_date.strftime('%Y-%m-%d')
                    else:
                        raise ValueError("Formato de fecha no reconocido o inválido.")
                except Exception as date_e:
                    print(f"AVISO: Error al parsear fecha de nacimiento en fila {index+2} ({fecha_nacimiento_raw}): {date_e}")
                    fecha_nac_str = None # Asegurar que sea None si falla la conversión

            # Si la fecha de nacimiento no se pudo parsear, saltar la fila
            if fecha_nac_str is None:
                print(f"AVISO: Fila {index+2} ignorada: Fecha de Nacimiento inválida o no parseable ({fecha_nacimiento_raw}).")
                continue

            sexo_adivinado = guess_gender(str(nombre_completo_raw))
            # Asegurar que nacionalidad siempre tenga un valor (por defecto 'Chilena' if empty)
            nacionalidad_valor = str(nacionalidad_raw).strip() if pd.notna(nacionalidad_raw) else 'Chilena'


            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, 
                "nacionalidad": nacionalidad_valor,
                "sexo": sexo_adivinado, # Puede ser None si guess_gender no adivina y la columna es NULLABLE
                "estado_general": None, 
                "diagnostico": None,
                "fecha_reevaluacion": None,
                "derivaciones": None,
                "fecha_relleno": None # Este se rellena cuando la doctora evalúa
                # Asegúrate de que todos los campos de Medicina Familiar que puedan estar vacíos
                # estén inicializados a None o un valor por defecto aquí si son NOT NULL en Supabase.
                # Si son NULLABLE en Supabase, no es necesario inicializarlos aquí si no vienen del Excel.
            }
            estudiantes_a_insertar.append(estudiante)
            
        except Exception as e:
            print(f"❌ Error al procesar fila {index+2}: {e}. Datos de la fila: {row.to_dict()}")
            flash(f"Error al procesar la fila {index+2} del archivo. Verifique el formato de los datos. ({e})", 'error')
            try:
                requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
                requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
                print("DEBUG: Rollback completado.")
            except Exception as rollback_e:
                print(f"❌ Error durante el rollback: {rollback_e}")
            return redirect(url_for('dashboard'))

    if not estudiantes_a_insertar:
        flash("⚠️ El archivo Excel/CSV no contiene datos válidos para estudiantes. La nómina fue cargada, pero sin estudiantes.", 'warning')
        return redirect(url_for('dashboard'))

    print(f"DEBUG: Preparados para insertar {len(estudiantes_a_insertar)} estudiantes.")
    try:
        res_insert_estudiantes = requests.post(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=estudiantes_a_insertar
        )
        res_insert_estudiantes.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar estudiantes (status): {res_insert_estudiantes.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar estudiantes (text): {res_insert_estudiantes.text}")

        flash(f"✅ Nómina '{nombre_especifico}' cargada con éxito. Se agregaron {len(estudiantes_a_insertar)} estudiantes.", 'success')
        return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_estudiantes.text if 'res_insert_estudiantes' in locals() else 'No response from Supabase.'
        print(f"❌ Error al insertar estudiantes en la DB: {e} - Detalles de Supabase: {error_detail}")
        flash(f"❌ Error al guardar los estudiantes en la base de datos. La nómina fue creada, pero no se agregaron los estudiantes. ({e}). Detalles: {error_detail}", 'error')
        return redirect(url_for('dashboard'))

@app.route('/enviar_formulario_a_drive', methods=['POST'])
def enviar_formulario_a_drive():
    """
    Endpoint para enviar el formulario PDF a Google Drive de la empresa.
    Genera el PDF en memoria y lo sube a una carpeta específica por colegio.
    """
    if 'usuario_id' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401

    doctor_id = session['usuario_id']
    
    creds = get_company_google_credentials()
    if not creds:
        return jsonify({"success": False, "message": "Error de autenticación con Google Drive de la empresa. Contacte al administrador (refresh token no configurado o inválido)."}), 500

    # Obtener todos los campos del formulario al principio para evitar NameErrors
    estudiante_id = request.form.get('estudiante_id', '')
    nomina_id = request.form.get('nomina_id', '')
    nombre = request.form.get('nombre', '') # Para neurología
    rut = request.form.get('rut', '')
    fecha_nac_original = request.form.get('fecha_nacimiento_original', '') 
    fecha_nac_formato = request.form.get('fecha_nacimiento_formato', '') # Ya formateado para PDF
    edad = request.form.get('edad', '')
    nacionalidad = request.form.get('nacionalidad', '')
    sexo = request.form.get('sexo', '') # Para neurología
    estado_general = request.form.get('estado', '') # Para neurología
    diagnostico = request.form.get('diagnostico', '') # Para neurología
    derivaciones = request.form.get('derivaciones', '') # Para ambos
    fecha_eval = datetime.today().strftime('%d/%m/%Y')

    # Campos específicos de Medicina Familiar
    nombre_apellido_familiar = request.form.get('nombre_apellido', '')
    genero_f_form = request.form.get('genero_f', '')
    genero_m_form = request.form.get('genero_m', '')
    diagnostico_1 = request.form.get('diagnostico_1', '')
    diagnostico_2 = request.form.get('diagnostico_2', '')
    diagnostico_complementario = request.form.get('diagnostico_complementario', '')
    fecha_reevaluacion_select = request.form.get('fecha_reevaluacion_select', '')
    observacion_1 = request.form.get('observacion_1', '')
    observacion_2 = request.form.get('observacion_2', '')
    observacion_3 = request.form.get('observacion_3', '')
    observacion_4 = request.form.get('observacion_4', '')
    observacion_5 = request.form.get('observacion_5', '')
    observacion_6 = request.form.get('observacion_6', '')
    observacion_7 = request.form.get('observacion_7', '')
    altura = request.form.get('altura', '')
    peso = request.form.get('peso', '')
    imc = request.form.get('imc', '')
    clasificacion = request.form.get('clasificacion', '')

    # Checkboxes de Medicina Familiar
    check_cesarea = request.form.get('check_cesarea') == 'on'
    check_atermino = request.form.get('check_atermino') == 'on'
    check_vaginal = request.form.get('check_vaginal') == 'on'
    check_prematuro = request.form.get('check_prematuro') == 'on'
    check_acorde = request.form.get('check_acorde') == 'on'
    check_retrasogeneralizado = request.form.get('check_retrasogeneralizado') == 'on'
    check_esquemai = request.form.get('check_esquemai') == 'on'
    check_esquemac = request.form.get('check_esquemac') == 'on'
    check_alergiano = request.form.get('check_alergiano') == 'on'
    check_alergiasi = request.form.get('check_alergiasi') == 'on'
    check_cirugiano = request.form.get('check_cirugiano') == 'on'
    check_cirugiasi = request.form.get('check_cirugiasi') == 'on'
    check_visionsinalteracion = request.form.get('check_visionsinalteracion') == 'on'
    check_visionrefraccion = request.form.get('check_visionrefraccion') == 'on'
    check_hipoacusia = request.form.get('check_hipoacusia') == 'on'
    check_retenciondental = request.form.get('check_retenciondental') == 'on'
    check_hipertrofia = request.form.get('check_hipertrofia') == 'on'
    check_frenillolingual = request.form.get('check_frenillolingual') == 'on'
    check_sinhallazgos = request.form.get('check_sinhallazgos') == 'on'
    check_caries = request.form.get('check_caries') == 'on'
    check_audicionnormal = request.form.get('check_audicionnormal') == 'on'
    check_tapondecerumen = request.form.get('check_tapondecerumen') == 'on'
    check_apinamientodental = request.form.get('check_apinamientodental') == 'on'


    # Obtener el form_type de la sesión para saber qué PDF base usar
    form_type = session.get('current_form_type', 'neurologia') 

    if not all([estudiante_id, nomina_id, (nombre if form_type == 'neurologia' else nombre_apellido_familiar), rut]): 
        return jsonify({"success": False, "message": "Faltan datos esenciales del formulario para subir a Drive."}), 400

    establecimiento_nombre = "Formularios Varios" 
    try:
        res_nomina = requests.get(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina",
            headers=SUPABASE_HEADERS
        )
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        if nomina_data and nomina_data[0] and 'nombre_nomina' in nomina_data[0]:
            establecimiento_nombre = nomina_data[0]['nombre_nomina']
        else:
            print(f"ADVERTENCIA: No se pudo encontrar el nombre de la nómina para ID: {nomina_id}, usando '{establecimiento_nombre}'.")
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error al obtener nombre de nómina para Drive: {e}")
    except Exception as e:
        print(f"ERROR: Error inesperado al obtener nombre de nómina para Drive: {e}")

    # Calcular fecha_reevaluacion para el PDF
    fecha_reeval_pdf = None
    if form_type == 'neurologia':
        fecha_reeval_pdf = request.form.get('fecha_reevaluacion')
        if fecha_reeval_pdf and "-" in fecha_reeval_pdf:
            try:
                fecha_reeval_pdf = datetime.strptime(fecha_reeval_pdf, '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                pass
    elif form_type == 'medicina_familiar':
        if fecha_reevaluacion_select:
            try:
                plazo_reevaluacion_years = int(fecha_reevaluacion_select)
                fecha_reeval_obj = date.today() + timedelta(days=plazo_reevaluacion_years * 365) 
                fecha_reeval_pdf = fecha_reeval_obj.strftime('%d/%m/%Y')
            except ValueError:
                print(f"ADVERTENCIA: Valor inválido para fecha_reevaluacion_select en enviar_formulario_a_drive: {fecha_reevaluacion_select}")
                fecha_reeval_pdf = None
        else:
            fecha_reeval_pdf = None

    # Seleccionar el PDF base según el form_type
    pdf_base_path = ''
    if form_type == 'neurologia':
        pdf_base_path = PDF_BASE_NEUROLOGIA
    elif form_type == 'medicina_familiar':
        pdf_base_path = PDF_BASE_FAMILIAR
    else:
        return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400


    if not os.path.exists(pdf_base_path):
        print("ERROR: Archivo FORMULARIO.pdf no encontrado para generar PDF para Drive.")
        return jsonify({"success": False, "message": "Error interno: Archivo base del formulario no encontrado en el servidor."}), 500

    try:
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        # Los campos a rellenar deben ser específicos para cada tipo de formulario
        campos = {}
        if form_type == 'neurologia':
            campos = {
                "nombre": nombre,
                "rut": rut,
                "fecha_nacimiento": fecha_nac_formato, 
                "nacionalidad": nacionalidad,
                "edad": edad,
                "diagnostico_1": diagnostico,
                "diagnostico_2": diagnostico, 
                "estado_general": estado_general, 
                "fecha_evaluacion": fecha_eval,
                "fecha_reevaluacion": fecha_reeval_pdf,
                "derivaciones": derivaciones,
                "sexo_f": "X" if sexo == "F" else "",
                "sexo_m": "X" if sexo == "M" else "",
            }
        elif form_type == 'medicina_familiar':
            # Mapeo de los campos del formulario HTML a los campos del PDF Familiar
            # Usando los nombres EXACTOS encontrados en el PDF
            campos = {
                "Nombres y Apellidos": nombre_apellido_familiar,
                "GENERO": genero_f_form if genero_f_form else genero_m_form, # Asumiendo que es un campo de texto o radio que toma 'Femenino'/'Masculino'
                "RUN": rut,
                "Fecha nacimiento (dd/mm/aaaa)": fecha_nac_formato,
                "Edad (en años y meses)": edad,
                "Nacionalidad": nacionalidad,
                "Fecha evaluación": fecha_eval,
                "Fecha reevaluación": fecha_reeval_pdf, 
                "DIAGNÓSTICO": diagnostico_1, # Mapeado a DIAGNOSTICO principal
                "DIAGNÓSTICO COMPLEMENTARIO": diagnostico_complementario,
                "DERIVACIONES": derivaciones,
                # Campos de observación
                "OBS:_1": observacion_1, 
                "OBS:_2": observacion_2, 
                "OBS:_3": observacion_3,
                "OBS:_4": observacion_4,
                "OBS:_5": observacion_5,
                "OBS:_6": observacion_6,
                "OBS:_7": observacion_7,
                "Altura:": altura, 
                "Peso": peso,
                "I.M.C": imc, 
                "Clasificación": clasificacion,
                # Checkboxes - Usando los nombres EXACTOS del PDF y el valor "/Yes"
                "CESAREA": "/Yes" if check_cesarea else "",
                "A TÉRMINO": "/Yes" if check_atermino else "",
                "VAGINAL": "/Yes" if check_vaginal else "",
                "PREMATURO": "/Yes" if check_prematuro else "",
                "LOGRADO ACORDE A LA EDAD": "/Yes" if check_acorde else "",
                "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if check_retrasogeneralizado else "",
                "ESQUEMA INCOMPLETO": "/Yes" if check_esquemai else "",
                "ESQUEMA COMPLETO": "/Yes" if check_esquemac else "",
                "NO": "/Yes" if check_alergiano else "", 
                "NO_2": "/Yes" if check_cirugiano else "", 
                "ST": "/Yes" if check_cirugiasi else "", 
                "SIN ALTERACIÓN": "/Yes" if check_visionsinalteracion else "",
                "VICIOS DE REFRACCIÓN": "/Yes" if check_visionrefraccion else "",
                "NORMAL": "/Yes" if check_audicionnormal else "", 
                "TAPÓN DE CERUMEN": "/Yes" if check_tapondecerumen else "",
                "HIPOACUSIA": "/Yes" if check_hipoacusia else "",
                "SIN HALLAZGOS": "/Yes" if check_sinhallazgos else "",
                "CARIES": "/Yes" if check_caries else "",
                "APIÑAMIENTO DENTAL": "/Yes" if check_apinamientodental else "",
                "RETENCIÓN DENTAL.": "/Yes" if check_retenciondental else "", 
                "FRENILLO LINGUAL": "/Yes" if check_frenillolingual else "",
                "HIPERTROFIA AMIGDALINA": "/Yes" if check_hipertrofia else "",
            }

        writer.update_page_form_field_values(writer.pages[0], campos)
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({NameObject("/AcroForm"): DictionaryObject()})
        writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})

        # --- INICIO LÓGICA DE APLANADO EXPLÍCITO CON PyPDF2 para Drive ---
        # Iterar sobre las anotaciones de la página para "aplanar" los campos.
        # Esto los convierte en contenido estático y asegura su visibilidad.
        # Advertencia: Los campos ya no serán editables después de esto.
        page = writer.pages[0]
        if "/Annots" in page:
            for i in range(len(page["/Annots"])):
                annot = page["/Annots"][i].get_object()
                if "/FT" in annot: # Si es un campo de formulario
                    # Eliminar la bandera de campo de formulario para que no sea interactivo
                    if "/Ff" in annot:
                        del annot["/Ff"]
                    # Eliminar la apariencia (AP) para que el visor la regenere o use el valor (V)
                    if "/AP" in annot:
                        del annot["/AP"]
                    # Establecer el valor como el valor predeterminado para que se "imprima"
                    if "/V" in annot and "/DV" not in annot:
                        annot[Name("/DV")] = annot["/V"]
        
        # Eliminar el diccionario AcroForm del documento si todos los campos son aplanados
        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]
        # --- FIN LÓGICA DE APLANADO EXPLÍCITO ---

        output_pdf_io = io.BytesIO()
        writer.write(output_pdf_io)
        output_pdf_io.seek(0) 

        nombre_para_archivo = nombre_apellido_familiar if form_type == 'medicina_familiar' else nombre
        if not nombre_para_archivo: 
            nombre_para_archivo = "Desconocido"
        
        file_name = f"{nombre_para_archivo.replace(' ', '_')}_{rut}_formulario_{form_type}.pdf" 
        
        service = build('drive', 'v3', credentials=creds)

        colegio_folder_id = find_or_create_drive_folder(service, establecimiento_nombre, GOOGLE_DRIVE_PARENT_FOLDER_ID)

        if not colegio_folder_id:
            return jsonify({"success": False, "message": "Error al encontrar o crear la carpeta del colegio en Google Drive."}), 500

        file_id = upload_pdf_to_google_drive(creds, output_pdf_io, file_name, colegio_folder_id)

        if file_id:
            return jsonify({"success": True, "message": f"Formulario enviado a Google Drive (ID: {file_id}) en la carpeta '{establecimiento_nombre}'."})
        else:
            return jsonify({"success": False, "message": "Error al subir el formulario a Google Drive."}), 500

    except Exception as e:
        print(f"ERROR: Error al procesar y subir formulario a Drive: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al procesar y subir a Drive: {str(e)}"}), 500

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo')
    print(f"DEBUG: subir - Establecimiento ID: {establecimiento}, Cantidad de archivos: {len(archivos)}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /subir: {session.get('usuario_id')}")


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
            print(f"DEBUG: Subiendo archivo completado a Storage: {upload_url}")
            
            try:
                res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
                res_upload.raise_for_status()
                
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
                print(f"DEBUG: Archivo completado subido, URL pública: {url_publica}")

                data = {
                    "doctoras_id": usuario_id,
                    "establecimientos_id": establecimiento,
                    "nombre_archivo": filename,
                    "url_archivo": url_publica
                }
                print(f"DEBUG: Payload para insertar formulario subido en DB: {data}")

                res_insert = requests.post(
                    f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                    headers=SUPABASE_SERVICE_HEADERS, 
                    json=data
                )
                res_insert.raise_for_status()
                print(f"DEBUG: Respuesta de Supabase al insertar formulario subido (status): {res_insert.status_code}")
                print(f"DEBUG: Respuesta de Supabase al insertar formulario subido (text): {res_insert.text}")
                mensajes.append(f"✅ Archivo '{filename}' subido y registrado correctamente.")
            
            except requests.exceptions.RequestException as e:
                error_msg = f"❌ Error al subir o registrar '{filename}': {e} - {res_upload.text if 'res_upload' in locals() else res_insert.text if 'res_insert' in locals() else 'No response'}"
                print(error_msg)
                mensajes.append(error_msg)
            except Exception as e:
                error_msg = f"❌ Error inesperado al procesar '{filename}': {e}"
                print(error_msg)
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

    print(f"DEBUG: Accediendo a /mis_nominas. ID de usuario en sesión: {usuario_id}")

    if not usuario_id:
        flash("No se pudo obtener el ID de usuario.", "error")
        print(f"DEBUG: usuario_id no encontrado en sesión para /mis_nominas.")
        return redirect(url_for('dashboard'))

    try:
        url_nominas_asignadas = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?doctora_id=eq.{usuario_id}"
            f"&select=id,nombre_nomina,tipo_nomina,form_type" # Incluir form_type
        )
        print(f"DEBUG: URL para mis_nominas: {url_nominas_asignadas}")
        res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
        res_nominas_asignadas.raise_for_status()
        raw_nominas = res_nominas_asignadas.json()
        print(f"DEBUG: Nóminas raw recibidas para mis_nominas: {raw_nominas}")

        for nom in raw_nominas:
            display_name = nom['tipo_nomina'].replace('_', ' ').title()
            assigned_nominations.append({
                'id': nom['id'],
                'nombre_establecimiento': nom['nombre_nomina'],
                'tipo_nomina_display': display_name,
                'form_type': nom.get('form_type') # Pasar el form_type
            })
        print(f"DEBUG: Nóminas asignadas procesadas para plantilla /mis_nominas: {assigned_nominations}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener mis nóminas: {e}")
        print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
        flash('Error al cargar sus nóminas asignadas.', 'error')
    except Exception as e:
        print(f"❌ Error inesperado al procesar mis nóminas: {e}")
        flash('Error inesperado al cargar sus nóminas asignadas.', 'error')


    return render_template('mis_nominas.html', assigned_nominations=assigned_nominations)

@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    alumnos_evaluados = request.form.get('alumnos')
    
    print(f"DEBUG: evaluados - Establecimiento ID: {establecimiento}, Alumnos evaluados: {alumnos_evaluados}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /evaluados: {session.get('usuario_id')}")


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
        print(f"DEBUG: Respuesta de Supabase al actualizar alumnos evaluados (status): {response_db.status_code}")
        print(f"DEBUG: Respuesta de Supabase al actualizar alumnos evaluados (text): {response_db.text}")
        flash("✅ Cantidad de alumnos evaluados registrada correctamente.", 'success')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al registrar alumnos evaluados: {e} - {response_db.text if 'response_db' in locals() else ''}")
        flash("❌ Error al registrar la cantidad de alumnos evaluados.", 'error')
    except Exception as e:
        print(f"❌ Error inesperado al registrar alumnos evaluados: {e}")
        flash("❌ Error inesperado al registrar la cantidad de alumnos evaluados.", 'error')

    return redirect(url_for('dashboard'))

@app.route('/doctor_performance/<doctor_id>')
def doctor_performance_detail(doctor_id):
    """
    Ruta para que el administrador vea el detalle de los formularios evaluados por una doctora.
    """
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
        print(f"DEBUG: Obteniendo rendimiento para doctora: {doctor_name} (ID: {doctor_id})")

        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?doctora_evaluadora_id=eq.{doctor_id}" 
            f"&fecha_relleno.not.is.null" 
            f"&select=nombre,rut,fecha_relleno,nomina_id,nominas_medicas(nombre_nomina)" 
            f"&order=fecha_relleno.desc" 
        )
        print(f"DEBUG: URL para obtener estudiantes evaluados: {url_students}")
        res_students = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS)
        res_students.raise_for_status()
        students_raw = res_students.json()
        print(f"DEBUG: Estudiantes evaluados recibidos: {students_raw}")

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
                'rut': student.get('rut'),
                'fecha_relleno': formatted_date,
                'nomina_nombre': nomina_nombre 
            })

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error al obtener el rendimiento de la doctora: {e} - {res_students.text if 'res_students' in locals() else 'No response'}")
        flash('Error al cargar el detalle de rendimiento de la doctora.', 'error')
    except Exception as e:
        print(f"ERROR: Error inesperado al cargar rendimiento de doctora: {e}")
        flash('Error inesperado al cargar el detalle de rendimiento de la doctora.', 'error')

    return render_template('doctor_performance.html', 
                           doctor_name=doctor_name, 
                           evaluated_students=evaluated_students)

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
        print(f"DEBUG: URL para descargar Excel de evaluados (simplificado): {url_students}")
        res_students = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS)
        res_students.raise_for_status()
        evaluated_students_data = res_students.json()
        print(f"DEBUG: Datos de estudiantes evaluados para Excel: {evaluated_students_data}")

        if not evaluated_students_data:
            return jsonify({"success": False, "message": "No hay formularios evaluados para esta nómina."}), 404

        df = pd.DataFrame(evaluated_students_data)

        df.rename(columns={
            'nombre': 'Nombre Completo',
            'rut': 'RUT',
            'fecha_nacimiento': 'Fecha de Nacimiento',
            'fecha_relleno': 'Fecha de Evaluación'
        }, inplace=True)

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
        print(f"ERROR: Error de solicitud al descargar Excel de evaluados: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con Supabase: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al generar Excel: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al generar el Excel: {str(e)}"}), 500

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

    # Obtener el form_type de la sesión para saber qué PDF base usar
    form_type = session.get('current_form_type', 'neurologia') 

    pdf_base_path = ''
    if form_type == 'neurologia':
        pdf_base_path = PDF_BASE_NEUROLOGIA
    elif form_type == 'medicina_familiar':
        pdf_base_path = PDF_BASE_FAMILIAR
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
                print(f"ADVERTENCIA: Estudiante con ID {student_id} no encontrado. Saltando.")
                continue

            est = student_data[0] 

            fecha_nac_obj = None
            if 'fecha_nacimiento' in est and isinstance(est['fecha_nacimiento'], str):
                try:
                    fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                    est['edad'] = calculate_age(fecha_nac_obj)
                    est['fecha_nacimiento_formato'] = fecha_nac_obj.strftime("%d-%m-%Y")
                except ValueError:
                    est['fecha_nacimiento_formato'] = 'Fecha Inválida'
                    est['edad'] = 'N/A'
            else:
                est['fecha_nacimiento_formato'] = 'N/A'
                est['edad'] = 'N/A'

            fecha_reeval_pdf = est.get('fecha_reevaluacion')
            if fecha_reeval_pdf and "-" in fecha_reeval_pdf:
                try:
                    fecha_reeval_pdf = datetime.strptime(fecha_reeval_pdf, '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass

            reader = PdfReader(pdf_base_path)
            writer_single_pdf = PdfWriter()
            writer_single_pdf.add_page(reader.pages[0])

            campos = {}
            if form_type == 'neurologia':
                campos = {
                    "nombre": est.get('nombre', ''),
                    "rut": est.get('rut', ''),
                    "fecha_nacimiento": est.get('fecha_nacimiento_formato', ''),
                    "nacionalidad": est.get('nacionalidad', ''),
                    "edad": est.get('edad', ''),
                    "diagnostico_1": est.get('diagnostico', ''),
                    "diagnostico_2": est.get('diagnostico', ''), 
                    "estado_general": est.get('estado_general', ''),
                    "fecha_evaluacion": est.get('fecha_relleno', ''), 
                    "fecha_reevaluacion": fecha_reeval_pdf,
                    "derivaciones": est.get('derivaciones', ''),
                    "sexo_f": "X" if est.get('sexo') == "F" else "",
                    "sexo_m": "X" if est.get('sexo') == "M" else "",
                }
            elif form_type == 'medicina_familiar':
                # Mapeo de los campos de la DB a los nombres EXACTOS encontrados en el PDF
                campos = {
                    "Nombres y Apellidos": est.get('nombre', ''),
                    "GENERO": est.get('sexo', ''), 
                    "RUN": est.get('rut', ''),
                    "Fecha nacimiento (dd/mm/aaaa)": est.get('fecha_nacimiento_formato', ''),
                    "Edad (en años y meses)": est.get('edad', ''),
                    "Nacionalidad": est.get('nacionalidad', ''),
                    "Fecha evaluación": est.get('fecha_relleno', ''),
                    "Fecha reevaluación": fecha_reeval_pdf,
                    "DIAGNÓSTICO": est.get('diagnostico_1', ''), 
                    "DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', ''),
                    "DERIVACIONES": est.get('derivaciones', ''),
                    "OBS:_1": est.get('observacion_1', ''), 
                    "OBS:_2": est.get('observacion_2', ''), 
                    "OBS:_3": est.get('observacion_3', ''),
                    "OBS:_4": est.get('observacion_4', ''),
                    "OBS:_5": est.get('observacion_5', ''),
                    "OBS:_6": est.get('observacion_6', ''),
                    "OBS:_7": est.get('observacion_7', ''),
                    "Altura:": est.get('altura', ''), 
                    "Peso": est.get('peso', ''),
                    "I.M.C": est.get('imc', ''), 
                    "Clasificación": est.get('clasificacion', ''),
                    # Checkboxes - Usando los nombres EXACTOS del PDF y el valor "/Yes"
                    "CESAREA": "/Yes" if est.get('check_cesarea') else "",
                    "A TÉRMINO": "/Yes" if est.get('check_atermino') else "",
                    "VAGINAL": "/Yes" if est.get('check_vaginal') else "",
                    "PREMATURO": "/Yes" if est.get('check_prematuro') else "",
                    "LOGRADO ACORDE A LA EDAD": "/Yes" if est.get('check_acorde') else "",
                    "RETRASO GENERALIZADO DEL DESARROLLO": "/Yes" if est.get('check_retrasogeneralizado') else "",
                    "ESQUEMA INCOMPLETO": "/Yes" if est.get('check_esquemai') else "",
                    "ESQUEMA COMPLETO": "/Yes" if est.get('check_esquemac') else "",
                    "NO": "/Yes" if est.get('check_alergiano') else "", 
                    "NO_2": "/Yes" if est.get('check_cirugiano') else "", 
                    "ST": "/Yes" if est.get('check_cirugiasi') else "", 
                    "SIN ALTERACIÓN": "/Yes" if est.get('check_visionsinalteracion') else "",
                    "VICIOS DE REFRACCIÓN": "/Yes" if est.get('check_visionrefraccion') else "",
                    "NORMAL": "/Yes" if est.get('check_audicionnormal') else "", 
                    "TAPÓN DE CERUMEN": "/Yes" if est.get('check_tapondecerumen') else "",
                    "HIPOACUSIA": "/Yes" if est.get('check_hipoacusia') else "",
                    "SIN HALLAZGOS": "/Yes" if est.get('check_sinhallazgos') else "",
                    "CARIES": "/Yes" if est.get('check_caries') else "",
                    "APIÑAMIENTO DENTAL": "/Yes" if est.get('check_apinamientodental') else "",
                    "RETENCIÓN DENTAL.": "/Yes" if est.get('check_retenciondental') else "", 
                    "FRENILLO LINGUAL": "/Yes" if est.get('check_frenillolingual') else "",
                    "HIPERTROFIA AMIGDALINA": "/Yes" if est.get('check_hipertrofia') else "",
                }

            writer_single_pdf.update_page_form_field_values(writer_single_pdf.pages[0], campos)
            if "/AcroForm" not in writer_single_pdf._root_object:
                writer_single_pdf._root_object.update({NameObject("/AcroForm"): DictionaryObject()})
            writer_single_pdf._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})

            # --- INICIO LÓGICA DE APLANADO EXPLÍCITO CON PyPDF2 para PDF combinado ---
            page = writer_single_pdf.pages[0]
            if "/Annots" in page:
                for i in range(len(page["/Annots"])):
                    annot = page["/Annots"][i].get_object()
                    if "/FT" in annot: # Si es un campo de formulario
                        if "/Ff" in annot:
                            del annot["/Ff"]
                        if "/AP" in annot:
                            del annot["/AP"]
                        if "/V" in annot and "/DV" not in annot:
                            annot[Name("/DV")] = annot["/V"]
            
            if "/AcroForm" in writer_single_pdf._root_object:
                del writer_single_pdf._root_object["/AcroForm"]
            # --- FIN LÓGICA DE APLANADO EXPLÍCITO ---

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
        print(f"ERROR: Error de solicitud al obtener datos de estudiante para PDF combinado: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con Supabase al generar PDF: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al generar PDFs visibles: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al generar PDFs: {str(e)}"}), 500


# --- Rutas de Eliminación (Solo para Admin) ---

@app.route('/admin/eliminar_establecimiento/<establecimiento_id>', methods=['DELETE'])
def eliminar_establecimiento(establecimiento_id):
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado. Solo administradores pueden eliminar."}), 403
    
    print(f"DEBUG: Intentando eliminar establecimiento con ID: {establecimiento_id}")

    try:
        # Eliminar el establecimiento
        res_delete_est = requests.delete(
            f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_est.raise_for_status()

        if res_delete_est.status_code == 204: # 204 No Content typically means successful deletion
            print(f"DEBUG: Establecimiento {establecimiento_id} eliminado de la DB.")
            return jsonify({"success": True, "message": "Colegio eliminado correctamente."})
        else:
            print(f"ERROR: Error inesperado al eliminar establecimiento. Status: {res_delete_est.status_code}, Response: {res_delete_est.text}")
            return jsonify({"success": False, "message": f"Error al eliminar el colegio: {res_delete_est.text}"}), 500

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al eliminar establecimiento: {e}")
        return jsonify({"success": False, "message": f"Error de conexión al eliminar colegio: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al eliminar establecimiento: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al eliminar colegio: {str(e)}"}), 500

@app.route('/admin/eliminar_nomina/<nomina_id>', methods=['DELETE'])
def eliminar_nomina(nomina_id):
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado. Solo administradores pueden eliminar."}), 403
    
    print(f"DEBUG: Intentando eliminar nómina y sus estudiantes con ID: {nomina_id}")

    try:
        # 1. Eliminar todos los estudiantes asociados a esta nómina
        res_delete_students = requests.delete(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_students.raise_for_status()
        print(f"DEBUG: Estudiantes de nómina {nomina_id} eliminados. Status: {res_delete_students.status_code}")

        # 2. Eliminar la propia nómina
        res_delete_nomina = requests.delete(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}",
            headers=SUPABASE_SERVICE_HEADERS
        )
        res_delete_nomina.raise_for_status()
        print(f"DEBUG: Nómina {nomina_id} eliminada. Status: {res_delete_nomina.status_code}")

        if res_delete_nomina.status_code == 204:
            return jsonify({"success": True, "message": "Nómina y sus estudiantes eliminados correctamente."})
        else:
            print(f"ERROR: Error inesperado al eliminar nómina. Status: {res_delete_nomina.status_code}, Response: {res_delete_nomina.text}")
            return jsonify({"success": False, "message": f"Error al eliminar la nómina: {res_delete_nomina.text}"}), 500

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al eliminar nómina: {e}")
        return jsonify({"success": False, "message": f"Error de conexión al eliminar nómina: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al eliminar nómina: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al eliminar nómina: {str(e)}"}), 500

# --- NUEVA RUTA PARA DEPURAR CAMPOS DE PDF ---
@app.route('/debug_pdf_fields', methods=['GET', 'POST'])
def debug_pdf_fields():
    form_fields = []
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No se seleccionó ningún archivo.', 'error')
            return redirect(request.url)
        
        pdf_file = request.files['pdf_file']
        if pdf_file.filename == '':
            flash('No se seleccionó ningún archivo.', 'error')
            return redirect(request.url)
        
        if pdf_file and pdf_file.filename.lower().endswith('.pdf'):
            try:
                reader = PdfReader(io.BytesIO(pdf_file.read()))
                if reader.acro_form:
                    for field_name in reader.acro_form.get_fields():
                        form_fields.append(field_name)
                    form_fields.sort() # Ordenar para facilitar la revisión
                else:
                    flash('El PDF no contiene campos de formulario rellenables (AcroForm).', 'warning')
            except Exception as e:
                flash(f'Error al leer el PDF: {e}', 'error')
        else:
            flash('El archivo no es un PDF válido.', 'error')
    
    return render_template('debug_pdf_fields.html', form_fields=form_fields)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
