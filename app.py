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

# Importaciones específicas para Google Drive API
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}

# --- Constantes para los archivos PDF base ---
PDF_NEUROLOGIA_BASE = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_FAMILIAR_BASE = 'formulario_familiar.pdf' # Asegúrate de que este archivo exista en static/

# -------------------- Supabase Configuration --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IlNJUDU4IiwicmVmIjoiYnhzbnFmZml4d2pkcWl2eGJrZXkiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzE5Mjg3MzI1LCJleHAiOjE3NTA4MjMzMjV9.qNlSg_p4_u1O5xQ9s6bN0K2Z0f0v_N9s8k0k0k0k0k") # ASEGÚRATE DE USAR TU SERVICE_KEY REAL

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
# Estas variables deben obtenerse de Google Cloud Console y el script get_refresh_token.py
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
    if months < 0 or (months == 0 and today.day < birth_date.day): # Corrected: === to ==
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    """Intenta adivinar el género basado en el nombre (heurística simple)."""
    name_lower = name.lower().strip()
    first_word = name_lower.split(' ')[0]

    nombres_masculinos = ["juan", "pedro", "luis", "carlos", "jose", "manuel", "alejandro", "ignacio", "felipe", "vicente", "emilio", "cristobal", "mauricio", "diego", "jean", "agustin", "joaquin", "thomas", "martin", "angel", "alonso"]
    nombres_femeninos = ["maria", "ana", "sofia", "laura", "paula", "trinidad", "mariana", "lizeth", "alexandra", "lisset"] 

    if first_word in nombres_masculinos:
        return 'M'
    elif first_word in nombres_femeninos:
        return 'F'
    
    # Fallback heurístico
    if name_lower.endswith(('o', 'n', 'r', 'l')):
        return 'M'
    if name_lower.endswith(('a', 'e')):
        return 'F'
    return "M" # Default to Male if unsure

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
    form_type = None
    try:
        # Incluir 'form_type' en la selección de la nómina
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
        form_type = nomina.get('form_type', 'neurologia') # Default a neurologia si no está definido
        session['current_form_type'] = form_type # Guardar en sesión para usar en otras rutas
        print(f"DEBUG: Tipo de formulario para esta nómina: {form_type}")

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
        # Seleccionar todos los campos para la "matriz"
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
                total_forms_completed_for_nomina += 1

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

    # Condicionalmente renderizar la plantilla correcta
    if form_type == 'neurologia':
        return render_template('formulario_relleno.html', 
                               estudiantes=estudiantes, 
                               total_forms_completed_for_nomina=total_forms_completed_for_nomina,
                               establecimiento_nombre=nomina['nombre_nomina'])
    elif form_type == 'medicina_familiar':
        return render_template('formulario_medicina_familiar.html', 
                               estudiantes=estudiantes, 
                               total_forms_completed_for_nomina=total_forms_completed_for_nomina,
                               establecimiento_nombre=nomina['nombre_nomina'])
    else:
        flash("Tipo de formulario no soportado para esta nómina.", 'error')
        return redirect(url_for('dashboard'))


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        flash('Debes iniciar sesión para acceder a esta página.', 'danger')
        return redirect(url_for('index'))

    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    
    # Obtener el tipo de formulario de la sesión o de la nómina
    form_type = session.get('current_form_type', 'neurologia') 
    
    # Recuperar todos los datos del formulario enviado
    form_data = request.form.to_dict()
    print(f"DEBUG: generar_pdf - Datos recibidos del formulario: {form_data}")
    print(f"DEBUG: Tipo de formulario detectado para PDF: {form_type}")

    ruta_pdf_base = ""
    campos_a_rellenar = {}

    if form_type == 'neurologia':
        ruta_pdf_base = os.path.join("static", PDF_NEUROLOGIA_BASE)
        campos_a_rellenar = {
            "nombre": form_data.get('nombre', ''),
            "rut": form_data.get('rut', ''),
            "fecha_nacimiento": form_data.get('fecha_nacimiento_formato', ''), 
            "nacionalidad": form_data.get('nacionalidad', ''),
            "edad": form_data.get('edad', ''),
            "diagnostico_1": form_data.get('diagnostico', ''), # En neurologia, diagnostico_1 es el principal
            "diagnostico_2": form_data.get('diagnostico', ''), # Y diagnostico_2 es el mismo
            "estado_general": form_data.get('estado', ''), 
            "fecha_evaluacion": datetime.today().strftime('%d/%m/%Y'),
            "fecha_reevaluacion": form_data.get('fecha_reevaluacion_pdf', ''), # Usar el formato PDF
            "derivaciones": form_data.get('derivaciones', ''),
            "sexo_f": "X" if form_data.get('sexo') == "F" else "",
            "sexo_m": "X" if form_data.get('sexo') == "M" else "",
        }
    elif form_type == 'medicina_familiar':
        ruta_pdf_base = os.path.join("static", PDF_FAMILIAR_BASE)
        campos_a_rellenar = {
            "nombre_apellido": form_data.get('nombre_apellido', ''),
            "rut": form_data.get('rut', ''),
            "fecha_nacimiento": form_data.get('fecha_nacimiento_formato', ''), # Formato dd-mm-yyyy
            "edad": form_data.get('edad', ''),
            "nacionalidad": form_data.get('nacionalidad', ''),
            "fecha_evaluacion": datetime.today().strftime('%d/%m/%Y'),
            "diagnostico_1": form_data.get('diagnostico_1', ''),
            "diagnostico_2": form_data.get('diagnostico_2', ''),
            "diagnostico_complementario": form_data.get('diagnostico_complementario', ''),
            "derivaciones": form_data.get('derivaciones', ''),
            "fecha_reevaluacion": form_data.get('fecha_reevaluacion_pdf', ''), # Formato dd/mm/yyyy
            "observacion_1": form_data.get('observacion_1', ''),
            "observacion_2": form_data.get('observacion_2', ''),
            "observacion_3": form_data.get('observacion_3', ''),
            "observacion_4": form_data.get('observacion_4', ''),
            "observacion_5": form_data.get('observacion_5', ''),
            "observacion_6": form_data.get('observacion_6', ''),
            "observacion_7": form_data.get('observacion_7', ''),
            "altura": form_data.get('altura', ''),
            "peso": form_data.get('peso', ''),
            "imc": form_data.get('imc', ''),
            "clasificacion": form_data.get('clasificacion', ''),
            "genero_f": "X" if form_data.get('genero_f') == "Femenino" else "",
            "genero_m": "X" if form_data.get('genero_m') == "Masculino" else "",
            "check_cesarea": "X" if form_data.get('check_cesarea') == "CESAREA" else "",
            "check_atermino": "X" if form_data.get('check_atermino') == "A_TERMINO" else "",
            "check_vaginal": "X" if form_data.get('check_vaginal') == "VAGINAL" else "",
            "check_prematuro": "X" if form_data.get('check_prematuro') == "PREMATURO" else "",
            "check_acorde": "X" if form_data.get('check_acorde') == "LOGRADO_ACORDE_A_LA_EDAD" else "",
            "check_retrasogeneralizado": "X" if form_data.get('check_retrasogeneralizado') == "RETRASO_GENERALIZADO_DEL_DESARROLLO" else "",
            "check_esquemai": "X" if form_data.get('check_esquemai') == "ESQUEMA_INCOMPLETO" else "",
            "check_esquemac": "X" if form_data.get('check_esquemac') == "ESQUEMA_COMPLETO" else "",
            "check_alergiano": "X" if form_data.get('check_alergiano') == "NO_ALERGIAS" else "",
            "check_alergiasi": "X" if form_data.get('check_alergiasi') == "SI_ALERGIAS" else "",
            "check_cirugiano": "X" if form_data.get('check_cirugiano') == "NO_CIRUGIAS" else "",
            "check_cirugiasi": "X" if form_data.get('check_cirugiasi') == "SI_CIRUGIAS" else "",
            "check_visionsinalteracion": "X" if form_data.get('check_visionsinalteracion') == "SIN_ALTERACION_VISION" else "",
            "check_visionrefraccion": "X" if form_data.get('check_visionrefraccion') == "VICIOS_DE_REFRACCION" else "",
            "check_hipoacusia": "X" if form_data.get('check_hipoacusia') == "HIPOACUSIA" else "",
            "check_retenciondental": "X" if form_data.get('check_retenciondental') == "RETENCION_DENTAL" else "",
            "check_hipertrofia": "X" if form_data.get('check_hipertrofia') == "HIPERTROFIA_AMIGDALINA" else "",
            "check_frenillolingual": "X" if form_data.get('check_frenillolingual') == "FRENILLO_LINGUAL" else "",
            "check_sinhallazgos": "X" if form_data.get('check_sinhallazgos') == "SIN_HALLAZGOS" else "",
            "check_caries": "X" if form_data.get('check_caries') == "CARIES" else "",
            "check_audicionnormal": "X" if form_data.get('check_audicionnormal') == "NORMAL_AUDICION" else "",
            "check_tapondecerumen": "X" if form_data.get('check_tapondecerumen') == "TAPON_DE_CERUMEN" else "",
            "check_apinamientodental": "X" if form_data.get('check_apinamientodental') == "APINAMIENTO_DENTAL" else "",
        }
    else:
        flash("❌ Tipo de formulario desconocido para la generación de PDF.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


    if not os.path.exists(ruta_pdf_base):
        flash(f"❌ Error: El archivo base del formulario '{os.path.basename(ruta_pdf_base)}' no se encontró en la carpeta 'static'.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    try:
        reader = PdfReader(ruta_pdf_base)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        print(f"DEBUG: Fields to fill in PDF for {form_type}: {campos_a_rellenar}")

        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })

        writer.update_page_form_field_values(writer.pages[0], campos_a_rellenar)

        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        nombre_archivo_descarga = f"{form_data.get('nombre_apellido', form_data.get('nombre', 'Estudiante')).replace(' ', '_')}_{form_data.get('rut', 'sin_rut')}_{form_type}.pdf"
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

    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    doctora_id = session.get('usuario_id') # ID de la doctora que está realizando la evaluación
    
    form_type = session.get('current_form_type', 'neurologia') # Obtener el tipo de formulario de la sesión

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}")
    print(f"DEBUG: Tipo de formulario para guardar: {form_type}")
    print(f"DEBUG: Todos los datos recibidos del formulario: {request.form.to_dict()}")

    if not all([estudiante_id, nomina_id, doctora_id]):
        print(f"ERROR: Datos básicos faltantes en /marcar_evaluado. Estudiante ID: {estudiante_id}, Nomina ID: {nomina_id}, Doctora ID: {doctora_id}.")
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400

    update_data = {
        'doctora_evaluadora_id': doctora_id, # Esto es clave para el rendimiento
        'fecha_relleno': str(date.today()) # Fecha en que se marca como rellenado
    }

    # Recopilar todos los campos enviados por el formulario dinámicamente
    for key, value in request.form.items():
        if key not in ['estudiante_id', 'nomina_id', 'fecha_nacimiento_original', 'fecha_reevaluacion_pdf']: # Excluir campos de control
            # Convertir 'on' de checkboxes a True/False si es necesario, o manejar valores específicos
            if value == 'on': # Para checkboxes
                update_data[key] = True
            elif key == 'genero_f' or key == 'genero_m': # Para género, asegúrate de que sea True/False
                update_data[key] = (value == 'Femenino' or value == 'Masculino') # True if checked, False if not
            elif key.startswith('check_'): # Para el resto de checkboxes
                update_data[key] = (value == 'on') # True if checked, False if not
            else:
                update_data[key] = value

    # Manejar fechas que vienen en formato dd/mm/yyyy o YYYY-MM-DD
    for date_field in ['fecha_nacimiento', 'fecha_reevaluacion', 'fecha_evaluacion']:
        if date_field in update_data and update_data[date_field]:
            try:
                # Intenta parsear YYYY-MM-DD (desde el input type="date")
                datetime.strptime(update_data[date_field], '%Y-%m-%d').date()
            except ValueError:
                try:
                    # Intenta parsear DD/MM/YYYY (desde el JS o el PDF)
                    update_data[date_field] = datetime.strptime(update_data[date_field], '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    print(f"ADVERTENCIA: Formato de fecha inválido para {date_field}: {update_data[date_field]}")
                    update_data[date_field] = None # O mantener el valor original si prefieres

    # Asegurarse de que los campos numéricos se conviertan a float/int
    for num_field in ['altura', 'peso', 'imc']:
        if num_field in update_data and update_data[num_field]:
            try:
                update_data[num_field] = float(update_data[num_field])
            except ValueError:
                print(f"ADVERTENCIA: Valor numérico inválido para {num_field}: {update_data[num_field]}")
                update_data[num_field] = None
    
    # Las observaciones se manejan como campos separados en el formulario de Medicina Familiar
    # Asegurarse de que los campos de observación se guarden correctamente
    for i in range(1, 8):
        obs_key = f'observacion_{i}'
        if obs_key in request.form:
            update_data[obs_key] = request.form.get(obs_key)

    print(f"DEBUG: Datos a actualizar en Supabase para estudiante {estudiante_id}: {update_data}")

    try:
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
            # Incluir form_type en la selección para la doctora
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}"
                f"&select=id,nombre_nomina,tipo_nomina,doctora_id,form_type" 
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
                    'form_type': nom.get('form_type', 'neurologia') # Pasar el tipo de formulario
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
            # Incluir form_type en la selección para el admin también
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
                        f"?doctora_evaluadora_id=eq.{doctor_id}" # Filtrar por la doctora que evaluó
                        f"&fecha_relleno.not.is.null" # Que el formulario haya sido rellenado
                        f"&select=count" 
                    )
                    print(f"DEBUG: URL para contar formularios de doctora {doctor_name} (admin view): {url_doctor_forms_count}")
                    res_doctor_forms = requests.get(url_doctor_forms_count, headers=SUPABASE_SERVICE_HEADERS) # Usar SERVICE_HEADERS
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
        doctor_performance_data=doctor_performance_data, # Dict {doctor_name: count}
        doctor_performance_data_single_doctor=doctor_performance_data_single_doctor # Dict {completed, pending, total}
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

    tipo_nomina = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id_from_form = request.form.get('doctora', '').strip()
    excel_file = request.files.get('excel')
    form_type = request.form.get('form_type') # Nuevo campo: tipo de formulario

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}, form_type={form_type}")

    if not all([tipo_nomina, nombre_especifico, doctora_id_from_form, excel_file, form_type]):
        flash('❌ Falta uno o más campos obligatorios para cargar la nómina (tipo, nombre, doctora, archivo, tipo de formulario).', 'error')
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
        print(f"❌ Error al subir archivo Excel a Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo de la nómina.", 'error')
        return redirect(url_for('dashboard'))

    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina,
        "doctora_id": doctora_id_from_form,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename,
        "form_type": form_type # Guardar el tipo de formulario
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
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
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
        return redirect(url_for('dashboard'))

    estudiantes_a_insertar = []
    df.columns = [normalizar(col) for col in df.columns]

    print(f"DEBUG: Columnas del archivo normalizadas: {df.columns}")

    column_mapping = {
        'nombre_completo': ['nombre_completo', 'nombre_y_apellido', 'nombre'],
        'rut': ['rut'],
        'fecha_nacimiento': ['fecha_nacimiento', 'fecha_de_nacimiento', 'fnac'], 
        'nacionalidad': ['nacionalidad'],
    }
    
    col_map = {}
    for key, possible_names in column_mapping.items():
        for name in possible_names:
            if name in df.columns:
                col_map[key] = name
                break
    
    print(f"DEBUG: Mapeo de columnas encontrado: {col_map}")

    if not all(k in col_map for k in ['nombre_completo', 'rut', 'fecha_nacimiento']):
        print(f"ERROR: No se encontraron columnas críticas. Columnas esperadas: {column_mapping.keys()}. Columnas encontradas: {df.columns.tolist()}")
        flash("❌ El archivo no contiene las columnas necesarias: 'Nombre', 'RUT', y 'Fecha de Nacimiento'.", 'error')
        try:
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

            if not all([nombre_completo_raw, rut_raw, fecha_nacimiento_raw]):
                print(f"AVISO: Fila {index+2} ignorada por datos faltantes. Datos: {row.to_dict()}")
                continue
            
            rut_limpio = str(rut_raw).replace('.', '').replace('-', '').strip()
            
            if isinstance(fecha_nacimiento_raw, datetime):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            elif isinstance(fecha_nacimiento_raw, date):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            else:
                try:
                    fecha_nac_str = pd.to_datetime(fecha_nacimiento_raw, errors='coerce').strftime('%Y-%m-%d')
                except Exception as date_e:
                    print(f"AVISO: Error al parsear fecha de nacimiento en fila {index+2}: {fecha_nacimiento_raw} - {date_e}")
                    fecha_nac_str = None
            
            sexo_adivinado = guess_gender(str(nombre_completo_raw))
            # Asegurar que nacionalidad siempre tenga un valor
            nacionalidad_valor = str(row.get(col_map.get('nacionalidad'), 'Chilena')).strip()


            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, 
                "nacionalidad": nacionalidad_valor,
                "sexo": sexo_adivinado,
                # Campos comunes inicializados a None, se llenarán al evaluar
                "estado_general": None, 
                "diagnostico": None, # Este es el campo 'diagnostico' para neurología
                "fecha_reevaluacion": None,
                "derivaciones": None,
                "fecha_relleno": None, # Este se rellena cuando la doctora evalúa
                "doctora_evaluadora_id": None,

                # Campos específicos de medicina familiar (inicializados a None)
                "fecha_evaluacion": None,
                "diagnostico_1": None, # Este es el campo 'diagnostico_1' para medicina familiar
                "diagnostico_2": None, # Este es el campo 'diagnostico_2' para medicina familiar
                "diagnostico_complementario": None,
                "altura": None,
                "peso": None,
                "imc": None,
                "clasificacion": None,
                "genero_f": None,
                "genero_m": None,
                "check_cesarea": None,
                "check_atermino": None,
                "check_vaginal": None,
                "check_prematuro": None,
                "check_acorde": None,
                "check_retrasogeneralizado": None,
                "check_esquemai": None,
                "check_esquemac": None,
                "check_alergiano": None,
                "check_alergiasi": None,
                "check_cirugiano": None,
                "check_cirugiasi": None,
                "check_visionsinalteracion": None,
                "check_visionrefraccion": None,
                "check_hipoacusia": None,
                "check_retenciondental": None,
                "check_hipertrofia": None,
                "check_frenillolingual": None,
                "check_sinhallazgos": None,
                "check_caries": None,
                "check_audicionnormal": None,
                "check_tapondecerumen": None,
                "check_apinamientodental": None,
                "observacion_1": None,
                "observacion_2": None,
                "observacion_3": None,
                "observacion_4": None,
                "observacion_5": None,
                "observacion_6": None,
                "observacion_7": None,
            }
            estudiantes_a_insertar.append(estudiante)
            
        except Exception as e:
            print(f"❌ Error al procesar fila {index+2}: {e}")
            flash(f"Error al procesar la fila {index+2} del archivo. Verifique el formato de los datos.", 'error')
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
        print(f"❌ Error al insertar estudiantes en la DB: {e} - {res_insert_estudiantes.text if 'res_insert_estudiantes' in locals() else ''}")
        flash(f"❌ Error al guardar los estudiantes en la base de datos. La nómina fue creada, pero no se agregaron los estudiantes. ({e})", 'error')
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

    # Obtener el tipo de formulario de la sesión o de la nómina
    form_type = session.get('current_form_type', 'neurologia') 

    # Recuperar todos los datos del formulario enviado
    form_data = request.form.to_dict()
    print(f"DEBUG: enviar_formulario_a_drive - Datos recibidos del formulario: {form_data}")
    print(f"DEBUG: Tipo de formulario detectado para Drive: {form_type}")

    estudiante_id = form_data.get('estudiante_id')
    nomina_id = form_data.get('nomina_id') 
    nombre_estudiante = form_data.get('nombre_apellido', form_data.get('nombre')) # Para nombre de archivo
    rut_estudiante = form_data.get('rut')

    if not all([estudiante_id, nomina_id, nombre_estudiante, rut_estudiante]): 
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

    ruta_pdf_base = ""
    campos_a_rellenar = {}

    if form_type == 'neurologia':
        ruta_pdf_base = os.path.join("static", PDF_NEUROLOGIA_BASE)
        campos_a_rellenar = {
            "nombre": form_data.get('nombre', ''),
            "rut": form_data.get('rut', ''),
            "fecha_nacimiento": form_data.get('fecha_nacimiento_formato', ''), 
            "nacionalidad": form_data.get('nacionalidad', ''),
            "edad": form_data.get('edad', ''),
            "diagnostico_1": form_data.get('diagnostico', ''), 
            "diagnostico_2": form_data.get('diagnostico', ''), 
            "estado_general": form_data.get('estado', ''), 
            "fecha_evaluacion": datetime.today().strftime('%d/%m/%Y'),
            "fecha_reevaluacion": form_data.get('fecha_reevaluacion_pdf', ''), 
            "derivaciones": form_data.get('derivaciones', ''),
            "sexo_f": "X" if form_data.get('sexo') == "F" else "",
            "sexo_m": "X" if form_data.get('sexo') == "M" else "",
        }
    elif form_type == 'medicina_familiar':
        ruta_pdf_base = os.path.join("static", PDF_FAMILIAR_BASE)
        campos_a_rellenar = {
            "nombre_apellido": form_data.get('nombre_apellido', ''),
            "rut": form_data.get('rut', ''),
            "fecha_nacimiento": form_data.get('fecha_nacimiento_formato', ''), 
            "edad": form_data.get('edad', ''),
            "nacionalidad": form_data.get('nacionalidad', ''),
            "fecha_evaluacion": datetime.today().strftime('%d/%m/%Y'),
            "diagnostico_1": form_data.get('diagnostico_1', ''),
            "diagnostico_2": form_data.get('diagnostico_2', ''),
            "diagnostico_complementario": form_data.get('diagnostico_complementario', ''),
            "derivaciones": form_data.get('derivaciones', ''),
            "fecha_reevaluacion": form_data.get('fecha_reevaluacion_pdf', ''),
            "observacion_1": form_data.get('observacion_1', ''),
            "observacion_2": form_data.get('observacion_2', ''),
            "observacion_3": form_data.get('observacion_3', ''),
            "observacion_4": form_data.get('observacion_4', ''),
            "observacion_5": form_data.get('observacion_5', ''),
            "observacion_6": form_data.get('observacion_6', ''),
            "observacion_7": form_data.get('observacion_7', ''),
            "altura": form_data.get('altura', ''),
            "peso": form_data.get('peso', ''),
            "imc": form_data.get('imc', ''),
            "clasificacion": form_data.get('clasificacion', ''),
            "genero_f": "X" if form_data.get('genero_f') == "Femenino" else "",
            "genero_m": "X" if form_data.get('genero_m') == "Masculino" else "",
            "check_cesarea": "X" if form_data.get('check_cesarea') == "CESAREA" else "",
            "check_atermino": "X" if form_data.get('check_atermino') == "A_TERMINO" else "",
            "check_vaginal": "X" if form_data.get('check_vaginal') == "VAGINAL" else "",
            "check_prematuro": "X" if form_data.get('check_prematuro') == "PREMATURO" else "",
            "check_acorde": "X" if form_data.get('check_acorde') == "LOGRADO_ACORDE_A_LA_EDAD" else "",
            "check_retrasogeneralizado": "X" if form_data.get('check_retrasogeneralizado') == "RETRASO_GENERALIZADO_DEL_DESARROLLO" else "",
            "check_esquemai": "X" if form_data.get('check_esquemai') == "ESQUEMA_INCOMPLETO" else "",
            "check_esquemac": "X" if form_data.get('check_esquemac') == "ESQUEMA_COMPLETO" else "",
            "check_alergiano": "X" if form_data.get('check_alergiano') == "NO_ALERGIAS" else "",
            "check_alergiasi": "X" if form_data.get('check_alergiasi') == "SI_ALERGIAS" else "",
            "check_cirugiano": "X" if form_data.get('check_cirugiano') == "NO_CIRUGIAS" else "",
            "check_cirugiasi": "X" if form_data.get('check_cirugiasi') == "SI_CIRUGIAS" else "",
            "check_visionsinalteracion": "X" if form_data.get('check_visionsinalteracion') == "SIN_ALTERACION_VISION" else "",
            "check_visionrefraccion": "X" if form_data.get('check_visionrefraccion') == "VICIOS_DE_REFRACCION" else "",
            "check_hipoacusia": "X" if form_data.get('check_hipoacusia') == "HIPOACUSIA" else "",
            "check_retenciondental": "X" if form_data.get('check_retenciondental') == "RETENCION_DENTAL" else "",
            "check_hipertrofia": "X" if form_data.get('check_hipertrofia') == "HIPERTROFIA_AMIGDALINA" else "",
            "check_frenillolingual": "X" if form_data.get('check_frenillolingual') == "FRENILLO_LINGUAL" else "",
            "check_sinhallazgos": "X" if form_data.get('check_sinhallazgos') == "SIN_HALLAZGOS" else "",
            "check_caries": "X" if form_data.get('check_caries') == "CARIES" else "",
            "check_audicionnormal": "X" if form_data.get('check_audicionnormal') == "NORMAL_AUDICION" else "",
            "check_tapondecerumen": "X" if form_data.get('check_tapondecerumen') == "TAPON_DE_CERUMEN" else "",
            "check_apinamientodental": "X" if form_data.get('check_apinamientodental') == "APINAMIENTO_DENTAL" else "",
        }
    else:
        print(f"ERROR: Tipo de formulario desconocido '{form_type}' para Google Drive.")
        return jsonify({"success": False, "message": "Error interno: Tipo de formulario desconocido para Google Drive."}), 500

    if not os.path.exists(ruta_pdf_base):
        print(f"ERROR: Archivo base del formulario '{os.path.basename(ruta_pdf_base)}' no encontrado para generar PDF para Drive.")
        return jsonify({"success": False, "message": "Error interno: Archivo base del formulario no encontrado en el servidor."}), 500

    try:
        reader = PdfReader(ruta_pdf_base)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        writer.update_page_form_field_values(writer.pages[0], campos_a_rellenar)
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({NameObject("/AcroForm"): DictionaryObject()})
        writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})

        output_pdf_io = io.BytesIO()
        writer.write(output_pdf_io)
        output_pdf_io.seek(0) 

        file_name = f"{nombre_estudiante.replace(' ', '_')}_{rut_estudiante}_{form_type}.pdf"
        
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
            f"&select=id,nombre_nomina,tipo_nomina,doctora_id,form_type" # Incluir form_type
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
                'form_type': nom.get('form_type', 'neurologia') # Pasar el tipo de formulario
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

        # Seleccionar todos los campos para mostrar el detalle completo
        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?doctora_evaluadora_id=eq.{doctor_id}" 
            f"&fecha_relleno.not.is.null" 
            f"&select=*,nominas_medicas(nombre_nomina,form_type)" # Incluir form_type de la nómina
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
            form_type_display = "Desconocido"
            if student.get('nominas_medicas') and student['nominas_medicas']:
                if isinstance(student['nominas_medicas'], list) and student['nominas_medicas']:
                    nomina_info = student['nominas_medicas'][0]
                elif isinstance(student['nominas_medicas'], dict):
                    nomina_info = student['nominas_medicas']
                
                nomina_nombre = nomina_info.get('nombre_nomina', nomina_nombre)
                form_type_display = nomina_info.get('form_type', form_type_display).replace('_', ' ').title()


            evaluated_students.append({
                'nombre': student.get('nombre'),
                'rut': student.get('rut'),
                'fecha_relleno': formatted_date,
                'nomina_nombre': nomina_nombre,
                'form_type': form_type_display # Mostrar el tipo de formulario
            })

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener el rendimiento de la doctora: {e} - {res_students.text if 'res_students' in locals() else 'No response'}")
        flash('Error al cargar el detalle de rendimiento de la doctora.', 'error')
    except Exception as e:
        print(f"❌ Error inesperado al cargar rendimiento de doctora: {e}")
        flash('Error inesperado al cargar el detalle de rendimiento de la doctora.', 'error')

    return render_template('doctor_performance.html', 
                           doctor_name=doctor_name, 
                           evaluated_students=evaluated_students)

@app.route('/descargar_excel_evaluados/<nomina_id>', methods=['GET'])
def descargar_excel_evaluados(nomina_id):
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    
    # Obtener el tipo de formulario de la nómina para saber qué campos relevantes incluir
    form_type = session.get('current_form_type', 'neurologia') # Default
    try:
        res_nomina = requests.get(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type", headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        if nomina_data:
            form_type = nomina_data[0].get('form_type', form_type)
    except requests.exceptions.RequestException as e:
        print(f"ADVERTENCIA: No se pudo obtener form_type para nomina {nomina_id} al descargar Excel: {e}. Usando default: {form_type}")

    select_fields = "nombre,rut,fecha_nacimiento,fecha_relleno" # Campos comunes
    
    if form_type == 'neurologia':
        select_fields += ",sexo,estado_general,diagnostico,fecha_reevaluacion,derivaciones"
    elif form_type == 'medicina_familiar':
        select_fields += ",genero_f,genero_m,fecha_evaluacion,diagnostico_1,diagnostico_2,diagnostico_complementario,derivaciones,fecha_reevaluacion,observacion_1,observacion_2,observacion_3,observacion_4,observacion_5,observacion_6,observacion_7,altura,peso,imc,clasificacion,check_cesarea,check_atermino,check_vaginal,check_prematuro,check_acorde,check_retrasogeneralizado,check_esquemai,check_esquemac,check_alergiano,check_alergiasi,check_cirugiano,check_cirugiasi,check_visionsinalteracion,check_visionrefraccion,check_hipoacusia,check_retenciondental,check_hipertrofia,check_frenillolingual,check_sinhallazgos,check_caries,check_audicionnormal,check_tapondecerumen,check_apinamientodental"
    
    try:
        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?nomina_id=eq.{nomina_id}"
            f"&fecha_relleno.not.is.null" 
            f"&select={select_fields}" 
            f"&order=nombre.asc" 
        )
        print(f"DEBUG: URL para descargar Excel de evaluados (con campos específicos de {form_type}): {url_students}")
        res_students = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS)
        res_students.raise_for_status()
        evaluated_students_data = res_students.json()
        print(f"DEBUG: Datos de estudiantes evaluados para Excel: {evaluated_students_data}")

        if not evaluated_students_data:
            return jsonify({"success": False, "message": "No hay formularios evaluados para esta nómina."}), 404

        df = pd.DataFrame(evaluated_students_data)

        # Renombrar columnas para mejor legibilidad en el Excel
        rename_map = {
            'nombre': 'Nombre Completo',
            'rut': 'RUT',
            'fecha_nacimiento': 'Fecha de Nacimiento (Original)',
            'fecha_relleno': 'Fecha de Evaluación',
            'sexo': 'Género (Neuro)',
            'estado_general': 'Estado General (Neuro)',
            'diagnostico': 'Diagnóstico (Neuro)',
            'fecha_reevaluacion': 'Fecha Reevaluación (Neuro)',
            'derivaciones': 'Derivaciones (Neuro)',
            
            'genero_f': 'Género Femenino (Familiar)',
            'genero_m': 'Género Masculino (Familiar)',
            'fecha_evaluacion': 'Fecha Evaluación (Familiar)',
            'diagnostico_1': 'Diagnóstico 1 (Familiar)',
            'diagnostico_2': 'Diagnóstico 2 (Familiar)',
            'diagnostico_complementario': 'Diagnóstico Complementario (Familiar)',
            # 'derivaciones' se repite, ya está arriba
            # 'fecha_reevaluacion' se repite, ya está arriba
            'observacion_1': 'Observación 1 (Familiar)',
            'observacion_2': 'Observación 2 (Familiar)',
            'observacion_3': 'Observación 3 (Familiar)',
            'observacion_4': 'Observación 4 (Familiar)',
            'observacion_5': 'Observación 5 (Familiar)',
            'observacion_6': 'Observación 6 (Familiar)',
            'observacion_7': 'Observación 7 (Familiar)',
            'altura': 'Altura (cm)',
            'peso': 'Peso (kg)',
            'imc': 'IMC',
            'clasificacion': 'Clasificación IMC',
            'check_cesarea': 'Check Cesárea',
            'check_atermino': 'Check A Término',
            'check_vaginal': 'Check Vaginal',
            'check_prematuro': 'Check Prematuro',
            'check_acorde': 'Check Acorde a Edad',
            'check_retrasogeneralizado': 'Check Retraso Generalizado',
            'check_esquemai': 'Check Esquema Incompleto',
            'check_esquemac': 'Check Esquema Completo',
            'check_alergiano': 'Check Alergia No',
            'check_alergiasi': 'Check Alergia Sí',
            'check_cirugiano': 'Check Cirugía No',
            'check_cirugiasi': 'Check Cirugía Sí',
            'check_visionsinalteracion': 'Check Visión Sin Alteración',
            'check_visionrefraccion': 'Check Vicios Refracción',
            'check_hipoacusia': 'Check Hipoacusia',
            'check_retenciondental': 'Check Retención Dental',
            'check_hipertrofia': 'Check Hipertrofia Amigdalina',
            'check_frenillolingual': 'Check Frenillo Lingual',
            'check_sinhallazgos': 'Check Sin Hallazgos',
            'check_caries': 'Check Caries',
            'check_audicionnormal': 'Check Audición Normal',
            'check_tapondecerumen': 'Check Tapón Cerumen',
            'check_apinamientodental': 'Check Apiñamiento Dental',
        }

        # Aplicar el mapeo de nombres de columnas
        df.rename(columns=rename_map, inplace=True)
        
        # Formatear fechas y booleanos
        for col in df.columns:
            if 'fecha' in col.lower() and ('original' not in col.lower()): # Evitar la fecha original que ya viene formateada
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
            # Modificado para manejar booleanos de forma más genérica
            elif any(kw in col.lower() for kw in ['check', 'genero', 'requiere', 'fonoaudiologo', 'terapeuta', 'psicologo', 'kinesiologo', 'psicopedagogo', 'educador']):
                df[col] = df[col].apply(lambda x: 'Sí' if x is True else 'No' if x is False else '')


        # Reordenar columnas para mejor visualización (opcional, puedes ajustar esto)
        # Obtener columnas que existen en el DataFrame
        existing_cols = df.columns.tolist()
        
        # Definir un orden preferido, incluyendo los campos específicos
        ordered_cols = [
            'Nombre Completo', 'RUT', 'Fecha de Nacimiento (Original)', 'Fecha de Evaluación',
            'Género (Neuro)', 'Estado General (Neuro)', 'Diagnóstico (Neuro)', 'Fecha Reevaluación (Neuro)', 'Derivaciones (Neuro)',
            
            'Género Femenino (Familiar)', 'Género Masculino (Familiar)', 'Fecha Evaluación (Familiar)',
            'Diagnóstico 1 (Familiar)', 'Diagnóstico 2 (Familiar)', 'Diagnóstico Complementario (Familiar)',
            'Observación 1 (Familiar)', 'Observación 2 (Familiar)', 'Observación 3 (Familiar)', 'Observación 4 (Familiar)',
            'Observación 5 (Familiar)', 'Observación 6 (Familiar)', 'Observación 7 (Familiar)',
            'Altura (cm)', 'Peso (kg)', 'IMC', 'Clasificación IMC',
            'Check Cesárea', 'Check A Término', 'Check Vaginal', 'Check Prematuro', 'Check Acorde a Edad',
            'Check Retraso Generalizado', 'Check Esquema Incompleto', 'Check Esquema Completo',
            'Check Alergia No', 'Check Alergia Sí', 'Check Cirugía No', 'Check Cirugía Sí',
            'Check Visión Sin Alteración', 'Check Vicios Refracción', 'Check Hipoacusia', 'Check Retención Dental',
            'Check Hipertrofia Amigdalina', 'Check Frenillo Lingual', 'Check Sin Hallazgos', 'Check Caries',
            'Check Audición Normal', 'Check Tapón Cerumen', 'Check Apiñamiento Dental'
        ]

        # Filtrar solo las columnas que realmente existen en el DataFrame
        final_cols = [col for col in ordered_cols if col in existing_cols]
        # Añadir cualquier columna que no haya sido mapeada o reordenada al final
        for col in existing_cols:
            if col not in final_cols:
                final_cols.append(col)
        
        df = df[final_cols]

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
    
    # Obtener el tipo de formulario de la nómina
    form_type = session.get('current_form_type', 'neurologia') # Default
    try:
        res_nomina = requests.get(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type", headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        if nomina_data:
            form_type = nomina_data[0].get('form_type', form_type)
    except requests.exceptions.RequestException as e:
        print(f"ADVERTENCIA: No se pudo obtener form_type para nomina {nomina_id} al generar PDFs visibles: {e}. Usando default: {form_type}")

    ruta_pdf_base = ""
    if form_type == 'neurologia':
        ruta_pdf_base = os.path.join("static", PDF_NEUROLOGIA_BASE)
    elif form_type == 'medicina_familiar':
        ruta_pdf_base = os.path.join("static", PDF_FAMILIAR_BASE)
    else:
        return jsonify({"success": False, "message": "Error interno: Tipo de formulario desconocido para la generación de PDFs visibles."}), 500

    if not os.path.exists(ruta_pdf_base):
        return jsonify({"success": False, "message": f"Error interno: Archivo base del formulario '{os.path.basename(ruta_pdf_base)}' no encontrado en el servidor."}), 500

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

            # Formatear fechas para PDF
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
            
            fecha_eval_pdf = est.get('fecha_relleno') # Fecha de relleno es la fecha de evaluación
            if fecha_eval_pdf and "-" in fecha_eval_pdf:
                try:
                    fecha_eval_pdf = datetime.strptime(fecha_eval_pdf, '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass

            reader = PdfReader(ruta_pdf_base)
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
                    "fecha_evaluacion": fecha_eval_pdf,
                    "fecha_reevaluacion": fecha_reeval_pdf,
                    "derivaciones": est.get('derivaciones', ''),
                    "sexo_f": "X" if est.get('sexo') == "F" else "",
                    "sexo_m": "X" if est.get('sexo') == "M" else "",
                }
            elif form_type == 'medicina_familiar':
                campos = {
                    "nombre_apellido": est.get('nombre', ''), # Mapear 'nombre' de estudiantes_nomina a 'nombre_apellido'
                    "rut": est.get('rut', ''),
                    "fecha_nacimiento": est.get('fecha_nacimiento_formato', ''), 
                    "edad": est.get('edad', ''),
                    "nacionalidad": est.get('nacionalidad', ''),
                    "fecha_evaluacion": fecha_eval_pdf,
                    "diagnostico_1": est.get('diagnostico_1', ''),
                    "diagnostico_2": est.get('diagnostico_2', ''),
                    "diagnostico_complementario": est.get('diagnostico_complementario', ''),
                    "derivaciones": est.get('derivaciones', ''),
                    "fecha_reevaluacion": fecha_reeval_pdf,
                    "observacion_1": est.get('observacion_1', ''),
                    "observacion_2": est.get('observacion_2', ''),
                    "observacion_3": est.get('observacion_3', ''),
                    "observacion_4": est.get('observacion_4', ''),
                    "observacion_5": est.get('observacion_5', ''),
                    "observacion_6": est.get('observacion_6', ''),
                    "observacion_7": est.get('observacion_7', ''),
                    "altura": str(est.get('altura', '')),
                    "peso": str(est.get('peso', '')),
                    "imc": str(est.get('imc', '')),
                    "clasificacion": est.get('clasificacion', ''),
                    "genero_f": "X" if est.get('genero_f') else "",
                    "genero_m": "X" if est.get('genero_m') else "",
                    "check_cesarea": "X" if est.get('check_cesarea') else "",
                    "check_atermino": "X" if est.get('check_atermino') else "",
                    "check_vaginal": "X" if est.get('check_vaginal') else "",
                    "check_prematuro": "X" if est.get('check_prematuro') else "",
                    "check_acorde": "X" if est.get('check_acorde') else "",
                    "check_retrasogeneralizado": "X" if est.get('check_retrasogeneralizado') else "",
                    "check_esquemai": "X" if est.get('check_esquemai') else "",
                    "check_esquemac": "X" if est.get('check_esquemac') else "",
                    "check_alergiano": "X" if est.get('check_alergiano') else "",
                    "check_alergiasi": "X" if est.get('check_alergiasi') else "",
                    "check_cirugiano": "X" if est.get('check_cirugiano') else "",
                    "check_cirugiasi": "X" if est.get('check_cirugiasi') else "",
                    "check_visionsinalteracion": "X" if est.get('check_visionsinalteracion') else "",
                    "check_visionrefraccion": "X" if est.get('check_visionrefraccion') else "",
                    "check_hipoacusia": "X" if est.get('hipoacusia') else "",
                    "check_retenciondental": "X" if est.get('check_retenciondental') else "",
                    "check_hipertrofia": "X" if est.get('check_hipertrofia') else "",
                    "check_frenillolingual": "X" if est.get('check_frenillolingual') else "",
                    "check_sinhallazgos": "X" if est.get('check_sinhallazgos') else "",
                    "check_caries": "X" if est.get('caries') else "",
                    "check_audicionnormal": "X" if est.get('audicionnormal') else "",
                    "check_tapondecerumen": "X" if est.get('tapondecerumen') else "",
                    "check_apinamientodental": "X" if est.get('apinamientodental') else "",
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
