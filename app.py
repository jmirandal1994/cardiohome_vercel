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
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IlNJUDU4IiwicmVmIjoiYnhzbnFmZml4d2pkcWl2eGJrZXkiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzE5Mjg3MzI1LCJleHAiOjE3NTA4MjMzMjV9.qNlS_p4_u1O5xQ9s6bN0K2Z0f0v_N9s8k0k0k0k0k") # ASEGÚRATE DE USAR TU SERVICE_KEY REAL

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
    rut = request.form.get('rut', '')
    fecha_nac_original = request.form.get('fecha_nacimiento_original', '') 
    fecha_nac_formato = request.form.get('fecha_nacimiento_formato', '') # Ya formateado para PDF
    edad = request.form.get('edad', '')
    nacionalidad = request.form.get('nacionalidad', '')
    derivaciones = request.form.get('derivaciones', '') # Campo común para ambos formularios
    fecha_eval = datetime.today().strftime('%d/%m/%Y')

    # Campos específicos de Neurología (mantienen sus nombres originales del formulario HTML)
    nombre_neuro = request.form.get('nombre', '') 
    sexo_neuro = request.form.get('sexo', '') 
    estado_general_neuro = request.form.get('estado', '') 
    diagnostico_neuro = request.form.get('diagnostico', '') 
    fecha_reevaluacion_neuro_input = request.form.get('fecha_reevaluacion', '') # Input para el date picker de neurología

    # Campos específicos de Medicina Familiar (se renombran a las variables solicitadas por el usuario)
    nombre = request.form.get('nombre', '') # Renombrado a 'nombre' para Medicina Familiar
    genero_f = request.form.get('genero_f', '') # Renombrado a 'genero_f'
    genero_m = request.form.get('genero_m', '') # Renombrado a 'genero_m'
    diagnostico_1 = request.form.get('diagnostico_1', '')
    diagnostico_2 = request.form.get('diagnostico_2', '')
    diagnostico_complementario = request.form.get('diagnostico_complementario', '')
    fecha_reevaluacion_select = request.form.get('fecha_reevaluacion_select', '') # Input para el select de años de Medicina Familiar
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

    # Checkboxes de Medicina Familiar (nombres de variables ya coinciden con los solicitados)
    check_cesarea = request.form.get('check_cesarea') == 'on'
    check_atermino = request.form.get('check_atermino') == 'on'
    check_vaginal = request.form.get('check_vaginal') == 'on'
    check_prematuro = request.form.get('check_prematuro') == 'on'
    check_acorde = request.form.get('check_acorde') == 'on'
    # CORREGIDO: Usar 'check_retraso' en lugar de 'check_retrasogeneralizado'
    check_retrasogeneralizado = request.form.get('check_retrasogeneralizado') == 'on' # Mantener para la DB si existe, pero el PDF usará 'check_retraso'
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

    print(f"DEBUG: generar_pdf - Datos recibidos: rut={rut}, form_type={form_type}")
    
    if form_type == 'medicina_familiar':
        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nacimiento,
            "edad": edad,
            "nacionalidad": nacionalidad,
            "fecha_evaluacion": fecha_evaluacion,
            "fecha_reevaluacion": fecha_reevaluacion,
            "diagnostico_complementario": diagnostico_complementario,
            "diagnostico_1": diagnostico_1,
            "diagnostico_2": diagnostico_2,
            "observacion_1": observacion_1,
            "observacion_2": observacion_2,
            "observacion_3": observacion_3,
            "observacion_4": observacion_4,
            "observacion_5": observacion_5,
            "observacion_6": observacion_6,
            "observacion_7": observacion_7,
            "altura": altura,
            "peso": peso,
            "imc": imc,
            "clasificacion": clasificacion,
            "sexo_f": "Yes" if sexo == "F" else "Off",
            "sexo_m": "Yes" if sexo == "M" else "Off",
            "check_cesarea": "Yes" if cesarea else "Off",
            "check_atermino": "Yes" if atermino else "Off",
            "check_vaginal": "Yes" if vaginal else "Off",
            "check_prematuro": "Yes" if prematuro else "Off",
            "check_acorde": "Yes" if acorde else "Off",
            "check_retraso": "Yes" if retraso else "Off",
            "check_retrasogeneralizado": "Yes" if retrasogeneralizado else "Off",
            "check_esquemac": "Yes" if esquema_completo else "Off",
            "check_esquemai": "Yes" if esquema_incompleto else "Off",
            "check_alergiano": "Yes" if alergia == "no" else "Off",
            "check_alergiasi": "Yes" if alergia == "si" else "Off",
            "check_cirugiano": "Yes" if cirugia == "no" else "Off",
            "check_cirugiasi": "Yes" if cirugia == "si" else "Off",
            "check_visionsinalteracion": "Yes" if vision == "normal" else "Off",
            "check_visionrefraccion": "Yes" if vision == "refraccion" else "Off",
            "check_audicionnormal": "Yes" if audicion == "normal" else "Off",
            "check_tapondecerumen": "Yes" if audicion == "cerumen" else "Off",
            "check_hipoacusia": "Yes" if audicion == "hipoacusia" else "Off",
            "check_caries": "Yes" if caries else "Off",
            "check_apinamientodental": "Yes" if apinamiento else "Off",
            "check_retenciondental": "Yes" if retencion_dental else "Off",
            "check_sinhallazgos": "Yes" if sinhallazgos else "Off",
            "check_frenillolingual": "Yes" if frenillo else "Off",
            "check_hipertrofia": "Yes" if hipertrofia else "Off",
        }

    if form_type == 'neurologia':
        print(f"DEBUG: generar_pdf (Neurología) – nombre={nombre_neuro}, sexo={sexo_neuro}, diagnostico={diagnostico_neuro}")
        campos = {
            "nombre": nombre_neuro,
            "rut": rut,
            "fecha_nacimiento": fecha_nac_formato,
            "edad": edad,
            "nacionalidad": nacionalidad,
            "fecha_evaluacion": fecha_eval,
            "fecha_reevaluacion": fecha_reeval_pdf,
            "diagnostico_1": diagnostico_neuro,
            "estado_general": estado_general_neuro,
            "derivaciones": derivaciones,
            "sexo_f": "X" if sexo_neuro == "F" else "",
            "sexo_m": "X" if sexo_neuro == "M" else "",
        }
    if form_type == 'medicina_familiar':
        print(f"DEBUG: generar_pdf (Familiar) – nombre={nombre}, genero_f={genero_f}, genero_m={genero_m}, diagnostico_1={diagnostico_1}")
        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac_formato,
            "edad": edad,
            "nacionalidad": nacionalidad,
            "fecha_evaluacion": fecha_eval,
            "fecha_reevaluacion": fecha_reeval_pdf,
            "diagnostico_complementario": diagnostico_complementario,
            "diagnostico_1": diagnostico_1,
            "diagnostico_2": diagnostico_2,
            "observacion_1": observacion_1,
            "observacion_2": observacion_2,
            "observacion_3": observacion_3,
            "observacion_4": observacion_4,
            "observacion_5": observacion_5,
            "observacion_6": observacion_6,
            "observacion_7": observacion_7,
            "altura": altura,
            "peso": peso,
            "imc": imc,
            "clasificacion": clasificacion,
            "sexo_f": "X" if genero_f == "Femenino" else "",
            "sexo_m": "X" if genero_m == "Masculino" else "",
        }
        if form_type == 'neurologia':
            campos = {
                "nombre": str(nombre_neuro), # Usa el nombre de neurología
                "rut": str(rut),
                "fecha_nacimiento": str(fecha_nac_formato), 
                "nacionalidad": str(nacionalidad),
                "edad": str(edad),
                "diagnostico_1": str(diagnostico_neuro),
                "diagnostico_2": str(diagnostico_neuro), # Puede ser el mismo para neurología si no hay un segundo campo
                "estado_general": str(estado_general_neuro), 
                "fecha_evaluacion": str(fecha_eval),
                "fecha_reevaluacion": str(fecha_reeval_pdf if fecha_reeval_pdf is not None else ""), # Explicitamente None a ""
                "derivaciones": str(derivaciones),
                "sexo_f": "X" if sexo_neuro == "F" else "",
                "sexo_m": "X" if sexo_neuro == "M" else "",
            }
    if form_type == 'medicina_familiar':
        # Mapeo de los campos del formulario HTML a los campos del PDF Familiar
        # Usando los nombres EXACTOS de tus variables y campos de PDF
        campos = {
            "nombre": str(nombre), # Mapea directamente la variable 'nombre' (de Medicina Familiar)
            "rut": str(rut),
            "fecha_nacimiento": str(fecha_nac_formato),
            "edad": str(edad),
            "nacionalidad": str(nacionalidad),
            "fecha_evaluacion": str(fecha_eval),
            "fecha_reevaluacion": str(fecha_reeval_pdf if fecha_reeval_pdf is not None else ""), # Explicitamente None a ""
            "sexo_f": "X" if genero_f == "Femenino" else "", # CORREGIDO: Mapea a 'sexo_f'
            "sexo_m": "X" if genero_m == "Masculino" else "", # CORREGIDO: Mapea a 'sexo_m'
            "diagnostico_1": str(diagnostico_1),
            "diagnostico_2": str(diagnostico_2),
            "diagnostico_complementario": str(diagnostico_complementario),
            "derivaciones": str(derivaciones),
            "observacion_1": str(observacion_1), 
            "observacion_2": str(observacion_2), 
            "observacion_3": str(observacion_3),
            "observacion_4": str(observacion_4),
            "observacion_5": str(observacion_5),
            "observacion_6": str(observacion_6),
            "observacion_7": str(observacion_7),
            "altura": str(altura), 
            "peso": str(peso),
            "imc": str(imc), 
            "clasificacion": str(clasificacion),
            "check_cesarea": "/Yes" if check_cesarea else "",
            "check_atermino": "/Yes" if check_atermino else "",
            "check_vaginal": "/Yes" if check_vaginal else "",
            "check_prematuro": "/Yes" if check_prematuro else "",
            "check_acorde": "/Yes" if check_acorde else "",
            "check_retraso": "/Yes" if check_retrasogeneralizado else "", # CORREGIDO: Mapea a 'check_retraso'
            "check_esquemai": "/Yes" if check_esquemai else "",
            "check_esquemac": "/Yes" if check_esquemac else "",
            "check_alergiano": "/Yes" if check_alergiano else "", 
            "check_alergiasi": "/Yes" if check_alergiasi else "", 
            "check_cirugiano": "/Yes" if check_cirugiano else "", 
            "check_cirugiasi": "/Yes" if check_cirugiasi else "", 
            "check_visionsinalteracion": "/Yes" if check_visionsinalteracion else "",
            "check_visionrefraccion": "/Yes" if check_visionrefraccion else "",
            "check_audicionnormal": "/Yes" if check_audicionnormal else "", 
            "check_tapondecerumen": "/Yes" if check_tapondecerumen else "",
            "check_hipoacusia": "/Yes" if check_hipoacusia else "",
            "check_sinhallazgos": "/Yes" if check_sinhallazgos else "",
            "check_caries": "/Yes" if check_caries else "",
            "check_apinamientodental": "/Yes" if check_apinamientodental else "",
            "check_retenciondental": "/Yes" if check_retenciondental else "", 
            "check_frenillolingual": "/Yes" if check_frenillolingual else "",
            "check_hipertrofia": "/Yes" if check_hipertrofia else "",
        }

        print(f"DEBUG: Fields to fill in PDF for {form_type} form: {campos}")
        print(f"DEBUG: Campos a rellenar en PDF (JSON): {json.dumps(campos, indent=2)}")

        # Convertir todos los valores del diccionario 'campos' a string
        # Esto previene errores de "string index out of range" si un valor es None o no es una cadena
        for key, value in campos.items():
            campos[key] = str(value) if value is not None else ""


        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })

        writer.update_page_form_field_values(writer.pages[0], campos)

        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        nombre_para_archivo = nombre if form_type == 'medicina_familiar' else nombre_neuro # Usa el nombre correcto para el archivo
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
    doctora_id = session.get('usuario_id') # Obtener el form_type de la sesión para saber qué campos actualizar
    form_type = session.get('current_form_type', 'neurologia') 

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}, form_type={form_type}")
    print(f"DEBUG: Datos completos recibidos para guardar: {request.form.to_dict()}")

    if not all([estudiante_id, nomina_id, doctora_id]):
        print(f"ERROR: Datos faltantes en /marcar_evaluado. Estudiante ID: {estudiante_id}, Nomina ID: {nomina_id}, Doctora ID: {doctora_id}. Campos del formulario: {request.form.to_dict()}")
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400

    update_data = {
        'fecha_relleno': str(date.today())
    }

    # Obtener campos comunes y específicos al principio para evitar NameErrors
    # Campos comunes que pueden venir de ambos formularios
    rut_form = request.form.get('rut', '')
    fecha_nacimiento_original_form = request.form.get('fecha_nacimiento_original', '')
    nacionalidad_form = request.form.get('nacionalidad', '')
    edad_form = request.form.get('edad', '')
    derivaciones_comun = request.form.get('derivaciones', '') # Variable común para derivaciones

    # Campos específicos de Neurología
    nombre_neuro = request.form.get('nombre', '') # Nombre del formulario de neurología
    sexo_neuro = request.form.get('sexo', '')
    estado_general_neuro = request.form.get('estado', '')
    diagnostico_neuro = request.form.get('diagnostico', '')
    fecha_reevaluacion_neuro_input = request.form.get('fecha_reevaluacion', '')

    # Campos específicos de Medicina Familiar (utilizando los nombres de variables solicitados)
    nombre = request.form.get('nombre', '') # Nombre del formulario de medicina familiar
    genero_f = request.form.get('genero_f', '')
    genero_m = request.form.get('genero_m', '')
    diagnostico_1 = request.form.get('diagnostico_1', '')
    diagnostico_2 = request.form.get('diagnostico_2', '')
    diagnostico_complementario = request.form.get('diagnostico_complementario', '')
    fecha_reevaluacion_select = request.form.get('fecha_reevaluacion_select', '') # Input para el select de años de Medicina Familiar
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

    # Checkboxes de Medicina Familiar (nombres de variables ya coinciden con los solicitados)
    check_cesarea = request.form.get('check_cesarea') == 'on'
    check_atermino = request.form.get('check_atermino') == 'on'
    check_vaginal = request.form.get('check_vaginal') == 'on'
    check_prematuro = request.form.get('check_prematuro') == 'on'
    check_acorde = request.form.get('check_acorde') == 'on'
    # CORREGIDO: Usar 'check_retraso' en lugar de 'check_retrasogeneralizado'
    check_retrasogeneralizado = request.form.get('check_retrasogeneralizado') == 'on' # Mantener para la DB si existe, pero el PDF usará 'check_retraso'
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

    # Lógica condicional para actualizar campos específicos según el tipo de formulario
    if form_type == 'neurologia':
        update_data.update({
            'nombre_estudiante': nombre_neuro,
            'sexo': sexo_neuro,
            'estado_general': estado_general_neuro,
            'diagnostico': diagnostico_neuro,
            'fecha_reevaluacion': fecha_reevaluacion_neuro_input if fecha_reevaluacion_neuro_input else None,
            'derivaciones': derivaciones_comun,
            'rut': rut_form,
            'fecha_nacimiento': fecha_nacimiento_original_form,
            'nacionalidad': nacionalidad_form,
            'edad': edad_form,
        })
    elif form_type == 'medicina_familiar':
        # Aquí se guardan los campos del formulario de Medicina Familiar
        update_data.update({
            'nombre_estudiante': nombre,
            'sexo': genero_f if genero_f else genero_m, # Guardar el género seleccionado
            'diagnostico_1': diagnostico_1,
            'diagnostico_2': diagnostico_2,
            'diagnostico_complementario': diagnostico_complementario,
            'fecha_reevaluacion': fecha_reevaluacion_select if fecha_reevaluacion_select else None,
            'derivaciones': derivaciones_comun,
            'observacion_1': observacion_1,
            'observacion_2': observacion_2,
            'observacion_3': observacion_3,
            'observacion_4': observacion_4,
            'observacion_5': observacion_5,
            'observacion_6': observacion_6,
            'observacion_7': observacion_7,
            'altura': altura,
            'peso': peso,
            'imc': imc,
            'clasificacion': clasificacion,
            'rut': rut_form,
            'fecha_nacimiento': fecha_nacimiento_original_form,
            'nacionalidad': nacionalidad_form,
            'edad': edad_form,
            'check_cesarea': check_cesarea,
            'check_atermino': check_atermino,
            'check_vaginal': check_vaginal,
            'check_prematuro': check_prematuro,
            'check_acorde': check_acorde,
            'check_retrasogeneralizado': check_retrasogeneralizado,
            'check_esquemai': check_esquemai,
            'check_esquemac': check_esquemac,
            'check_alergiano': check_alergiano,
            'check_alergiasi': check_alergiasi,
            'check_cirugiano': check_cirugiano,
            'check_cirugiasi': check_cirugiasi,
            'check_visionsinalteracion': check_visionsinalteracion,
            'check_visionrefraccion': check_visionrefraccion,
            'check_hipoacusia': check_hipoacusia,
            'check_retenciondental': check_retenciondental,
            'check_hipertrofia': check_hipertrofia,
            'check_frenillolingual': check_frenillolingual,
            'check_sinhallazgos': check_sinhallazgos,
            'check_caries': check_caries,
            'check_audicionnormal': check_audicionnormal,
            'check_tapondecerumen': check_tapondecerumen,
            'check_apinamientodental': check_apinamientodental,
        })
    
    # Asegúrate de que las fechas estén en formato 'YYYY-MM-DD' si se guardan como string
    if 'fecha_nacimiento' in update_data and update_data['fecha_nacimiento']:
        try:
            # Si viene en 'DD-MM-YYYY', convertir a 'YYYY-MM-DD' para la DB
            update_data['fecha_nacimiento'] = datetime.strptime(update_data['fecha_nacimiento'], '%d-%m-%Y').strftime('%Y-%m-%d')
        except ValueError:
            # Si ya está en 'YYYY-MM-DD' o es inválida, mantenerla o manejar el error
            pass # No hacer nada si ya está bien o es None/vacío

    if 'fecha_reevaluacion' in update_data and update_data['fecha_reevaluacion']:
        try:
            # Si es del date picker de neurología ('DD/MM/YYYY')
            if '/' in update_data['fecha_reevaluacion']:
                update_data['fecha_reevaluacion'] = datetime.strptime(update_data['fecha_reevaluacion'], '%d/%m/%Y').strftime('%Y-%m-%d')
            # Si es del select de medicina familiar (año, asumimos fin de año)
            elif len(update_data['fecha_reevaluacion']) == 4 and update_data['fecha_reevaluacion'].isdigit():
                year = int(update_data['fecha_reevaluacion'])
                update_data['fecha_reevaluacion'] = str(date(year, 12, 31))
        except ValueError:
            pass # No hacer nada si el formato no coincide o es inválido

    print(f"DEBUG: Datos a actualizar en Supabase para estudiante {estudiante_id}: {json.dumps(update_data, indent=2)}")

    try:
        url_update = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}"
        response = requests.patch(url_update, headers=SUPABASE_HEADERS, json=update_data)
        response.raise_for_status() 
        print(f"DEBUG: Respuesta Supabase PATCH status: {response.status_code}")
        print(f"DEBUG: Respuesta Supabase PATCH body: {response.text}")

        if response.status_code == 204: # No Content para PATCH exitoso
            flash('Estudiante marcado como evaluado y datos guardados correctamente.', 'success')
        else:
            flash(f'Error al marcar como evaluado o guardar datos. Status: {response.status_code}', 'error')
            print(f"ERROR: Respuesta de Supabase no esperada: {response.status_code}, {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red/API al marcar estudiante: {e}")
        flash(f'Error al conectar con la base de datos: {e}', 'error')
    except Exception as e:
        print(f"❌ Error inesperado al marcar estudiante: {e}")
        flash(f'Error inesperado al guardar la evaluación: {e}', 'error')

    return jsonify({"success": True, "message": "Evaluación guardada y marcada."}) # Mantener esta respuesta para que AJAX funcione correctamente

@app.route('/subir_documento', methods=['POST'])
def subir_documento():
    if 'usuario' not in session:
        flash('Debes iniciar sesión para subir documentos.', 'danger')
        return redirect(url_for('index'))

    if 'file' not in request.files:
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('dashboard')) 

    file = request.files['file']
    if file.filename == '':
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(file.filename):
        flash('Tipo de archivo no permitido.', 'error')
        return redirect(url_for('dashboard'))

    # Intentar subir a Google Drive si las credenciales están configuradas
    creds = get_company_google_credentials()
    if creds:
        try:
            service = build('drive', 'v3', credentials=creds)
            # Asegurarse de que el ID de la carpeta padre esté configurado
            if not GOOGLE_DRIVE_PARENT_FOLDER_ID:
                flash("Error: El ID de la carpeta padre de Google Drive no está configurado.", 'error')
                return redirect(url_for('dashboard'))

            # Crear una carpeta para el año actual si no existe
            current_year_folder_id = find_or_create_drive_folder(service, str(datetime.now().year), GOOGLE_DRIVE_PARENT_FOLDER_ID)
            if not current_year_folder_id:
                flash("Error: No se pudo encontrar o crear la carpeta del año en Google Drive.", 'error')
                return redirect(url_for('dashboard'))

            # Crear una carpeta para el mes actual dentro de la del año
            current_month_name = datetime.now().strftime("%B").capitalize() # Nombre del mes
            current_month_folder_id = find_or_create_drive_folder(service, current_month_name, current_year_folder_id)
            if not current_month_folder_id:
                flash("Error: No se pudo encontrar o crear la carpeta del mes en Google Drive.", 'error')
                return redirect(url_for('dashboard'))

            # Crear una carpeta para la fecha actual (DD-MM-YYYY) dentro de la del mes
            current_date_folder_name = datetime.now().strftime("%d-%m-%Y")
            current_date_folder_id = find_or_create_drive_folder(service, current_date_folder_name, current_month_folder_id)
            if not current_date_folder_id:
                flash("Error: No se pudo encontrar o crear la carpeta de la fecha en Google Drive.", 'error')
                return redirect(url_for('dashboard'))

            file_content = file.read()
            file_name = secure_filename(file.filename)
            file_mime_type, _ = mimetypes.guess_type(file_name)
            if not file_mime_type:
                file_mime_type = 'application/octet-stream' # Tipo genérico si no se puede adivinar

            file_metadata = {
                'name': file_name,
                'mimeType': file_mime_type,
                'parents': [current_date_folder_id] 
            }

            media = io.BytesIO(file_content)

            uploaded_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink, name'
            ).execute()
            
            print(f"DEBUG: Archivo subido a Google Drive: {uploaded_file.get('name')} ({uploaded_file.get('id')})")
            
            # Guardar información en Supabase (tabla 'documentos')
            document_id = str(uuid.uuid4())
            new_document = {
                'id': document_id,
                'nombre_archivo': uploaded_file.get('name'),
                'tipo_archivo': uploaded_file.get('mimeType', file_mime_type),
                'url_drive': uploaded_file.get('webViewLink'),
                'id_drive': uploaded_file.get('id'),
                'fecha_subida': str(date.today()),
                'subido_por_id': session.get('usuario_id')
            }
            
            supabase_doc_url = f"{SUPABASE_URL}/rest/v1/documentos"
            res_supabase_doc = requests.post(supabase_doc_url, headers=SUPABASE_HEADERS, json=new_document)
            res_supabase_doc.raise_for_status()

            flash('Archivo subido y registrado correctamente.', 'success')
            return redirect(url_for('dashboard'))

        except HttpError as error:
            print(f"❌ Error al interactuar con Google Drive API: {error}")
            flash(f'Error al subir el archivo a Google Drive: {error}', 'error')
            return redirect(url_for('dashboard'))
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al guardar el documento en Supabase: {e}")
            flash(f'Error al registrar el documento en la base de datos: {e}', 'error')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"❌ Error inesperado al subir documento: {e}")
            flash(f'Ocurrió un error inesperado al subir el archivo: {e}', 'error')
            return redirect(url_for('dashboard'))
    else:
        flash('Error: Las credenciales de Google Drive no están configuradas para la empresa.', 'error')
        return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        flash('Debes iniciar sesión para acceder a la página de administración.', 'danger')
        return redirect(url_for('index'))

    print(f"DEBUG: Accediendo a /dashboard. Usuario en sesión: {session.get('usuario')}, ID: {session.get('usuario_id')}, Rol: {session.get('rol_usuario')}")

    # Obtener todas las nóminas médicas
    nominas = []
    try:
        url_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina,tipo_nomina,fecha_creacion,creada_por,form_type"
        res_nominas = requests.get(url_nominas, headers=SUPABASE_HEADERS)
        res_nominas.raise_for_status()
        nominas_raw = res_nominas.json()
        
        # Procesar nóminas para obtener el creador y la cantidad de estudiantes
        for nomina in nominas_raw:
            # Convertir fecha_creacion a formato legible
            if 'fecha_creacion' in nomina and nomina['fecha_creacion']:
                nomina['fecha_creacion_formato'] = datetime.strptime(nomina['fecha_creacion'], '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%d/%m/%Y')
            else:
                nomina['fecha_creacion_formato'] = 'N/A'

            # Contar estudiantes y completados para cada nómina
            try:
                url_est_count = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina['id']}&select=id,fecha_relleno"
                res_est_count = requests.get(url_est_count, headers=SUPABASE_HEADERS)
                res_est_count.raise_for_status()
                estudiantes_nomina = res_est_count.json()
                
                nomina['total_estudiantes'] = len(estudiantes_nomina)
                nomina['formularios_completados'] = sum(1 for e in estudiantes_nomina if e['fecha_relleno'] is not None)
            except requests.exceptions.RequestException as e:
                print(f"❌ Error al contar estudiantes para nomina {nomina['id']}: {e}")
                nomina['total_estudiantes'] = 0
                nomina['formularios_completados'] = 0
            
            nominas.append(nomina)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener nóminas: {e}")
        flash('Error al cargar la lista de nóminas.', 'error')
        nominas = [] # Asegurar que sea una lista vacía si falla

    # Obtener todos los documentos subidos
    documentos = []
    try:
        url_documentos = f"{SUPABASE_URL}/rest/v1/documentos?select=*,subido_por_id:id_usuario(username)"
        res_documentos = requests.get(url_documentos, headers=SUPABASE_HEADERS)
        res_documentos.raise_for_status()
        documentos_raw = res_documentos.json()
        
        for doc in documentos_raw:
            if 'fecha_subida' in doc and doc['fecha_subida']:
                doc['fecha_subida_formato'] = datetime.strptime(doc['fecha_subida'], '%Y-%m-%d').strftime('%d/%m/%Y')
            else:
                doc['fecha_subida_formato'] = 'N/A'
            
            # Asegurar que 'subido_por_id' tenga un 'username' y no sea solo el ID
            if doc.get('subido_por_id') and isinstance(doc['subido_por_id'], dict):
                doc['subido_por_username'] = doc['subido_por_id'].get('username', 'Desconocido')
            else:
                doc['subido_por_username'] = 'Desconocido' # Si no se pudo obtener el username
            documentos.append(doc)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener documentos: {e}")
        flash('Error al cargar la lista de documentos.', 'error')
        documentos = []

    return render_template('dashboard.html', 
                           nominas=nominas, 
                           documentos=documentos,
                           establecimiento_nombre=session.get('establecimiento_nombre'))

@app.route('/login', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            # Autenticar con Supabase Auth (Sign-in)
            auth_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
            headers_auth = SUPABASE_HEADERS.copy()
            headers_auth["Content-Type"] = "application/json"
            
            data = json.dumps({"email": email, "password": password})
            print(f"DEBUG: Intentando login para email: {email}")
            response = requests.post(auth_url, headers=headers_auth, data=data)
            response.raise_for_status() # Lanza excepción para códigos de estado de error

            auth_data = response.json()
            access_token = auth_data['access_token']
            user_id = auth_data['user']['id']
            email_returned = auth_data['user']['email']

            # Ahora, usa el access_token para obtener los datos del perfil del usuario (rol)
            # Necesitas una tabla `usuarios` en Supabase que tenga el `id_usuario` (UUID) y `rol`
            url_profile = f"{SUPABASE_URL}/rest/v1/usuarios?id_usuario=eq.{user_id}&select=username,rol"
            headers_profile = SUPABASE_HEADERS.copy()
            headers_profile["Authorization"] = f"Bearer {access_token}" # Usar el token de acceso del usuario
            
            profile_response = requests.get(url_profile, headers=headers_profile)
            profile_response.raise_for_status()

            profile_data = profile_response.json()

            if profile_data:
                user_profile = profile_data[0]
                session['usuario'] = user_profile['username']
                session['usuario_id'] = user_id
                session['rol_usuario'] = user_profile['rol'] # Guardar el rol en la sesión
                session['access_token'] = access_token
                flash('Has iniciado sesión exitosamente.', 'success')
                print(f"DEBUG: Usuario {session['usuario']} ({session['rol_usuario']}) ha iniciado sesión.")
                return redirect(url_for('dashboard'))
            else:
                flash('No se encontró el perfil de usuario. Contacta al administrador.', 'error')
                print(f"ERROR: No se encontró perfil de usuario para ID: {user_id}")
                return render_template('index.html')

        except requests.exceptions.RequestException as e:
            error_message = 'Error de autenticación. Verifica tus credenciales o intenta de nuevo.'
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_json = e.response.json()
                    if 'error_description' in error_json:
                        error_message = error_json['error_description']
                    elif 'msg' in error_json:
                        error_message = error_json['msg']
                except ValueError: # No es un JSON
                    error_message = f"Error de red o API: {e.response.text}"
            
            print(f"ERROR: Error durante el login: {error_message} (Detalle: {e})")
            flash(f'Error de login: {error_message}', 'error')
            return render_template('index.html')
        except Exception as e:
            print(f"ERROR: Error inesperado durante el login: {e}")
            flash(f'Ocurrió un error inesperado: {e}', 'error')
            return render_template('index.html')

    return render_template('index.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    session.pop('usuario_id', None)
    session.pop('rol_usuario', None)
    session.pop('access_token', None)
    session.pop('establecimiento', None)
    session.pop('current_nomina_id', None)
    session.pop('establecimiento_nombre', None)
    session.pop('current_form_type', None)
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        rol = request.form['rol']

        if session.get('rol_usuario') != 'admin':
            flash('Solo los administradores pueden registrar nuevos usuarios.', 'danger')
            return redirect(url_for('dashboard'))

        try:
            # 1. Crear el usuario en Supabase Auth
            auth_url = f"{SUPABASE_URL}/auth/v1/signup"
            headers_auth = {
                "apikey": SUPABASE_SERVICE_KEY, # Usar la service_key para signup de admin
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
            }
            auth_data = {
                "email": email,
                "password": password
            }
            print(f"DEBUG: Intentando registrar usuario en Auth: {email}")
            auth_response = requests.post(auth_url, headers=headers_auth, json=auth_data)
            auth_response.raise_for_status()
            
            user_auth_data = auth_response.json()
            user_id = user_auth_data['user']['id']

            # 2. Insertar el perfil del usuario en la tabla 'usuarios'
            profile_url = f"{SUPABASE_URL}/rest/v1/usuarios"
            profile_headers = {
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }
            profile_data = {
                "id_usuario": user_id,
                "username": username,
                "email": email,
                "rol": rol
            }
            print(f"DEBUG: Intentando crear perfil de usuario en DB: {username} ({rol})")
            profile_response = requests.post(profile_url, headers=profile_headers, json=profile_data)
            profile_response.raise_for_status()

            flash('Usuario registrado exitosamente.', 'success')
            print(f"DEBUG: Usuario {username} registrado con rol {rol}.")
            return redirect(url_for('admin_users'))

        except requests.exceptions.RequestException as e:
            error_message = 'Error al registrar usuario. Intenta de nuevo.'
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_json = e.response.json()
                    if 'msg' in error_json:
                        error_message = error_json['msg']
                    elif 'error_description' in error_json:
                        error_message = error_json['error_description']
                except ValueError:
                    error_message = f"Error de red o API: {e.response.text}"
            
            print(f"ERROR: Error durante el registro: {error_message} (Detalle: {e})")
            flash(f'Error de registro: {error_message}', 'error')
            return render_template('register.html')
        except Exception as e:
            print(f"ERROR: Error inesperado durante el registro: {e}")
            flash(f'Ocurrió un error inesperado: {e}', 'error')
            return render_template('register.html')
            
    return render_template('register.html')

@app.route('/admin_users')
def admin_users():
    if 'usuario' not in session or session.get('rol_usuario') != 'admin':
        flash('Acceso denegado. Solo administradores pueden ver esta página.', 'danger')
        return redirect(url_for('dashboard'))

    users = []
    try:
        url_users = f"{SUPABASE_URL}/rest/v1/usuarios?select=id_usuario,username,email,rol"
        res_users = requests.get(url_users, headers=SUPABASE_HEADERS) # Usar headers de usuario logueado si es admin
        res_users.raise_for_status()
        users = res_users.json()
    except requests.exceptions.RequestException as e:
        flash(f'Error al cargar usuarios: {e}', 'error')
        print(f"ERROR: Error al cargar usuarios: {e}")
    
    return render_template('admin_users.html', users=users)

@app.route('/delete_user/<user_id>', methods=['POST'])
def delete_user(user_id):
    if 'usuario' not in session or session.get('rol_usuario') != 'admin':
        flash('Acceso denegado. Solo administradores pueden eliminar usuarios.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        # 1. Eliminar de la tabla 'usuarios'
        url_profile = f"{SUPABASE_URL}/rest/v1/usuarios?id_usuario=eq.{user_id}"
        headers_profile = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
        }
        print(f"DEBUG: Intentando eliminar perfil de usuario de DB: {user_id}")
        profile_response = requests.delete(url_profile, headers=headers_profile)
        profile_response.raise_for_status()

        # 2. Eliminar de Supabase Auth (requiere Service Key)
        auth_url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
        headers_auth = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
        }
        print(f"DEBUG: Intentando eliminar usuario de Auth: {user_id}")
        auth_response = requests.delete(auth_url, headers=headers_auth)
        auth_response.raise_for_status()

        flash('Usuario eliminado exitosamente.', 'success')
        print(f"DEBUG: Usuario {user_id} eliminado completamente.")

    except requests.exceptions.RequestException as e:
        error_message = 'Error al eliminar usuario. Intenta de nuevo.'
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_json = e.response.json()
                if 'msg' in error_json:
                    error_message = error_json['msg']
                elif 'error_description' in error_json:
                    error_message = error_json['error_description']
            except ValueError:
                error_message = f"Error de red o API: {e.response.text}"
        print(f"ERROR: Error durante la eliminación del usuario {user_id}: {error_message} (Detalle: {e})")
        flash(f'Error al eliminar usuario: {error_message}', 'error')
    except Exception as e:
        print(f"ERROR: Error inesperado durante la eliminación del usuario {user_id}: {e}")
        flash(f'Ocurrió un error inesperado al eliminar el usuario: {e}', 'error')

    return redirect(url_for('admin_users'))

@app.route('/create_nomina', methods=['GET', 'POST'])
def create_nomina():
    if 'usuario' not in session or session.get('rol_usuario') not in ['admin', 'doctora']:
        flash('Acceso denegado. Solo administradores o doctoras pueden crear nóminas.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        nombre_nomina = request.form['nombre_nomina']
        tipo_nomina = request.form['tipo_nomina']
        form_type = request.form['form_type'] # Nuevo campo para el tipo de formulario

        if not nombre_nomina or not tipo_nomina or not form_type:
            flash('Todos los campos son obligatorios.', 'error')
            return render_template('create_nomina.html')

        try:
            url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            headers_nomina = {
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }
            nomina_data = {
                "nombre_nomina": nombre_nomina,
                "tipo_nomina": tipo_nomina,
                "fecha_creacion": str(datetime.now()),
                "creada_por": session.get('usuario_id'),
                "form_type": form_type # Guardar el tipo de formulario
            }
            print(f"DEBUG: Intentando crear nómina: {nombre_nomina} ({tipo_nomina}, {form_type})")
            response = requests.post(url_nomina, headers=headers_nomina, json=nomina_data)
            response.raise_for_status()

            flash('Nómina creada exitosamente.', 'success')
            print(f"DEBUG: Nómina '{nombre_nomina}' creada.")
            return redirect(url_for('dashboard'))

        except requests.exceptions.RequestException as e:
            error_message = 'Error al crear nómina. Intenta de nuevo.'
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_json = e.response.json()
                    if 'message' in error_json:
                        error_message = error_json['message']
                except ValueError:
                    error_message = f"Error de red o API: {e.response.text}"
            print(f"ERROR: Error durante la creación de nómina: {error_message} (Detalle: {e})")
            flash(f'Error al crear nómina: {error_message}', 'error')
            return render_template('create_nomina.html')
        except Exception as e:
            print(f"ERROR: Error inesperado durante la creación de nómina: {e}")
            flash(f'Ocurrió un error inesperado: {e}', 'error')
            return render_template('create_nomina.html')

    return render_template('create_nomina.html')


@app.route('/upload_estudiantes/<nomina_id>', methods=['GET', 'POST'])
def upload_estudiantes(nomina_id):
    if 'usuario' not in session or session.get('rol_usuario') not in ['admin', 'doctora']:
        flash('Acceso denegado. Solo administradores o doctoras pueden subir estudiantes.', 'danger')
        return redirect(url_for('dashboard'))

    nomina_nombre = "N/A"
    nomina_tipo = "N/A"
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        if nomina_data:
            nomina_nombre = nomina_data[0]['nombre_nomina']
            nomina_tipo = nomina_data[0]['tipo_nomina']
    except Exception as e:
        print(f"Error al obtener info de nómina {nomina_id}: {e}")
        flash('Error al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))


    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo.', 'error')
            return redirect(request.url)
        
        if not permitido(file.filename):
            flash('Tipo de archivo no permitido. Solo se permiten archivos Excel (xls, xlsx) y CSV.', 'error')
            return redirect(request.url)

        try:
            df = None
            if file.filename.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            elif file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                flash('Formato de archivo no soportado. Por favor, sube un archivo Excel o CSV.', 'error')
                return redirect(request.url)

            expected_columns = ['nombre', 'rut', 'fecha_nacimiento', 'nacionalidad']
            if not all(col in df.columns for col in expected_columns):
                flash(f'El archivo debe contener las columnas: {", ".join(expected_columns)}', 'error')
                return redirect(request.url)

            estudiantes_to_insert = []
            for index, row in df.iterrows():
                # Normalizar la fecha de nacimiento a 'YYYY-MM-DD'
                fecha_nac_str = None
                if pd.notna(row['fecha_nacimiento']):
                    try:
                        # Intentar parsear como fecha o string
                        if isinstance(row['fecha_nacimiento'], datetime):
                            fecha_nac_str = row['fecha_nacimiento'].strftime('%Y-%m-%d')
                        else: # Intentar como string con varios formatos
                            # Formato DD/MM/YYYY o DD-MM-YYYY
                            if isinstance(row['fecha_nacimiento'], str) and ('/' in row['fecha_nacimiento'] or '-' in row['fecha_nacimiento']):
                                try:
                                    fecha_nac_str = datetime.strptime(row['fecha_nacimiento'], '%d/%m/%Y').strftime('%Y-%m-%d')
                                except ValueError:
                                    fecha_nac_str = datetime.strptime(row['fecha_nacimiento'], '%d-%m-%Y').strftime('%Y-%m-%d')
                            else: # Otros posibles formatos que pandas podría haber interpretado como int/float
                                fecha_nac_str = str(row['fecha_nacimiento'])
                    except Exception as date_e:
                        print(f"Advertencia: No se pudo parsear la fecha de nacimiento '{row['fecha_nacimiento']}' en la fila {index+2}: {date_e}. Se guardará como NULL.")
                        fecha_nac_str = None
                
                # Intentar adivinar el género si no se proporciona directamente
                sexo_adivinado = guess_gender(str(row['nombre'])) if pd.notna(row['nombre']) else None

                estudiantes_to_insert.append({
                    'nomina_id': nomina_id,
                    'nombre_estudiante': str(row['nombre']) if pd.notna(row['nombre']) else None,
                    'rut': str(row['rut']) if pd.notna(row['rut']) else None,
                    'fecha_nacimiento': fecha_nac_str,
                    'nacionalidad': str(row['nacionalidad']) if pd.notna(row['nacionalidad']) else None,
                    'sexo': sexo_adivinado, # Asignar el género adivinado
                    'fecha_ingreso': str(date.today()),
                    'estado_evaluacion': 'pendiente'
                })
            
            if not estudiantes_to_insert:
                flash('No se encontraron estudiantes válidos en el archivo.', 'warning')
                return redirect(request.url)

            # Insertar en Supabase (usando el servicio_key para inserciones bulk)
            url_insert = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            headers_insert = {
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }
            
            print(f"DEBUG: Intentando insertar {len(estudiantes_to_insert)} estudiantes en Supabase.")
            response = requests.post(url_insert, headers=headers_insert, json=estudiantes_to_insert)
            response.raise_for_status()

            flash(f'Se subieron {len(estudiantes_to_insert)} estudiantes correctamente.', 'success')
            print(f"DEBUG: {len(estudiantes_to_insert)} estudiantes subidos exitosamente.")
            return redirect(url_for('dashboard'))

        except pd.errors.EmptyDataError:
            flash('El archivo está vacío.', 'error')
            return redirect(request.url)
        except Exception as e:
            print(f"Error al procesar archivo o subir a Supabase: {e}")
            flash(f'Error al procesar el archivo o subir estudiantes: {e}', 'error')
            return redirect(request.url)

    return render_template('upload_estudiantes.html', nomina_id=nomina_id, nombre_nomina=nomina_nombre, tipo_nomina=nomina_tipo)


@app.route('/delete_nomina/<nomina_id>', methods=['POST'])
def delete_nomina(nomina_id):
    if 'usuario' not in session or session.get('rol_usuario') != 'admin':
        flash('Acceso denegado. Solo administradores pueden eliminar nóminas.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        # Primero, eliminar estudiantes asociados (si hay una relación de clave externa con CASCADE DELETE no es necesario)
        # Si no hay CASCADE DELETE en la DB, descomentar lo siguiente:
        # url_delete_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}"
        # res_del_est = requests.delete(url_delete_estudiantes, headers=SUPABASE_SERVICE_HEADERS)
        # res_del_est.raise_for_status()
        # print(f"DEBUG: Estudiantes de nomina {nomina_id} eliminados.")

        url_delete_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}"
        response = requests.delete(url_delete_nomina, headers=SUPABASE_SERVICE_HEADERS)
        response.raise_for_status()

        flash('Nómina eliminada exitosamente.', 'success')
        print(f"DEBUG: Nómina {nomina_id} eliminada.")
    except requests.exceptions.RequestException as e:
        print(f"Error al eliminar nómina {nomina_id}: {e}")
        flash(f'Error al eliminar la nómina: {e}', 'error')
    except Exception as e:
        print(f"Error inesperado al eliminar nómina {nomina_id}: {e}")
        flash(f'Ocurrió un error inesperado al eliminar la nómina: {e}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/delete_document/<document_id>', methods=['POST'])
def delete_document(document_id):
    if 'usuario' not in session or session.get('rol_usuario') != 'admin':
        flash('Acceso denegado. Solo administradores pueden eliminar documentos.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        # 1. Obtener info del documento de Supabase para obtener id_drive
        url_doc = f"{SUPABASE_URL}/rest/v1/documentos?id=eq.{document_id}&select=id_drive"
        res_doc = requests.get(url_doc, headers=SUPABASE_HEADERS)
        res_doc.raise_for_status()
        doc_data = res_doc.json()

        if not doc_data:
            flash('Documento no encontrado en la base de datos.', 'error')
            return redirect(url_for('dashboard'))
        
        drive_file_id = doc_data[0].get('id_drive')

        # 2. Eliminar de Google Drive
        if drive_file_id:
            creds = get_company_google_credentials()
            if creds:
                try:
                    service = build('drive', 'v3', credentials=creds)
                    service.files().delete(fileId=drive_file_id).execute()
                    print(f"DEBUG: Archivo {drive_file_id} eliminado de Google Drive.")
                except HttpError as error:
                    if error.resp.status == 404:
                        print(f"Advertencia: Archivo {drive_file_id} no encontrado en Google Drive, pero se intentará eliminar de Supabase.")
                    else:
                        print(f"ERROR: Error al eliminar archivo de Google Drive {drive_file_id}: {error}")
                        flash(f'Error al eliminar el archivo de Google Drive: {error}', 'error')
                        return redirect(url_for('dashboard'))
            else:
                flash('Error: Las credenciales de Google Drive no están configuradas para la empresa.', 'error')
                return redirect(url_for('dashboard'))
        
        # 3. Eliminar de la tabla 'documentos' en Supabase
        url_delete_doc = f"{SUPABASE_URL}/rest/v1/documentos?id=eq.{document_id}"
        response = requests.delete(url_delete_doc, headers=SUPABASE_SERVICE_HEADERS)
        response.raise_for_status()

        flash('Documento eliminado exitosamente.', 'success')
        print(f"DEBUG: Documento {document_id} eliminado completamente.")

    except requests.exceptions.RequestException as e:
        print(f"Error al eliminar documento {document_id}: {e}")
        flash(f'Error al eliminar el documento: {e}', 'error')
    except Exception as e:
        print(f"Error inesperado al eliminar documento {document_id}: {e}")
        flash(f'Ocurrió un error inesperado al eliminar el documento: {e}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/download_document/<document_id>', methods=['GET'])
def download_document(document_id):
    if 'usuario' not in session:
        flash('Debes iniciar sesión para descargar documentos.', 'danger')
        return redirect(url_for('index'))

    try:
        # Obtener la URL de descarga o el id_drive del documento de Supabase
        url_doc = f"{SUPABASE_URL}/rest/v1/documentos?id=eq.{document_id}&select=id_drive,nombre_archivo,tipo_archivo"
        res_doc = requests.get(url_doc, headers=SUPABASE_HEADERS)
        res_doc.raise_for_status()
        doc_data = res_doc.json()

        if not doc_data:
            flash('Documento no encontrado.', 'error')
            return redirect(url_for('dashboard'))
        
        doc_info = doc_data[0]
        drive_file_id = doc_info.get('id_drive')
        file_name = doc_info.get('nombre_archivo', 'documento_descargado')
        mime_type = doc_info.get('tipo_archivo', 'application/octet-stream')

        if not drive_file_id:
            flash('ID de Google Drive no encontrado para este documento.', 'error')
            return redirect(url_for('dashboard'))

        creds = get_company_google_credentials()
        if creds:
            service = build('drive', 'v3', credentials=creds)
            # Para exportar Docs/Sheets/Slides de Google a PDF u otros formatos
            # Para archivos que NO son nativos de Google, simplemente se descarga el 'content'
            request_drive = service.files().get_media(fileId=drive_file_id)
            
            file_content = io.BytesIO()
            downloader = request_drive
            status, done = 0, False
            while done is False:
                status, done = downloader.next_chunk(file_content)
                print(f"Download {int(status.progress() * 100)}%.")
            
            file_content.seek(0)
            
            response = Response(file_content.read(), mimetype=mime_type)
            response.headers["Content-Disposition"] = f"attachment; filename={file_name}"
            print(f"DEBUG: Enviando archivo para descarga: {file_name}")
            return response

        else:
            flash('Error: Las credenciales de Google Drive no están configuradas para la empresa.', 'error')
            return redirect(url_for('dashboard'))

    except HttpError as error:
        print(f"ERROR: Error al descargar desde Google Drive: {error}")
        flash(f'Error al descargar el archivo de Google Drive: {error}', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"ERROR: Error inesperado al descargar documento: {e}")
        flash(f'Ocurrió un error inesperado al descargar el archivo: {e}', 'error')
        return redirect(url_for('dashboard'))


# -------------------- NUEVA RUTA PARA DEPURAR CAMPOS DE PDF --------------------
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
                # Cambiado de reader.acro_form.get_fields() a reader.get_fields()
                if reader.get_fields():
                    for field_name in reader.get_fields():
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
    app.run(debug=True, host='0.0.0.0', port=os.getenv("PORT", 5000))
