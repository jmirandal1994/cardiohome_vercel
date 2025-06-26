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
PDF_BASE = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf' 

# -------------------- Supabase Configuration --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtY4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImiYXRiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.i3ixl5ws3Z3QTxIcZNjI29ZknRmX0Z0khc")

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
# Es CRUCIAL que se configuren como variables de entorno en Vercel para producción.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID") 
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET")
# Este es el Refresh Token de la cuenta de Google Drive de la EMPRESA.
# Se obtiene una sola vez con el script get_refresh_token.py (ejecución local temporal).
GOOGLE_DRIVE_REFRESH_TOKEN = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", None)
# ID de la carpeta padre en Google Drive (ej. "Formularios CardioHome")
# Si se deja None, las carpetas de colegios se crearán en la raíz de "Mi unidad".
GOOGLE_DRIVE_PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", None)

SCOPES = ['https://www.googleapis.com/auth/drive.file'] # Acceso solo a archivos creados o abiertos por la app


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
    """Intenta adivinar el género basado en el nombre (heurística simple)."""
    name_lower = name.lower().strip()
    first_word = name_lower.split(' ')[0]

    nombres_masculinos = ["juan", "pedro", "luis", "carlos", "jose", "manuel", "alejandro", "ignacio", "felipe", "vicente", "emilio", "cristobal", "mauricio", "diego", "jean", "agustin", "joaquin", "thomas", "martin", "angel", "alonso"]
    nombres_femeninos = ["maria", "ana", "sofia", "laura", "paula", "trinidad", "mariana", "lizeth", "alexandra", "lisset"] 

    if first_word in nombres_masculinos:
        return 'M'
    elif first_word in nombres_femeninos:
        return 'F'
    
    if name_lower.endswith(('o', 'n', 'r', 'l')):
        return 'M'
    if name_lower.endswith(('a', 'e')):
        return 'F'
    return "M" 

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
        None, # access_token es None inicialmente, se refrescará
        refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )
    
    # Intenta refrescar el token de acceso
    try:
        print("DEBUG: Intentando refrescar token de Google Drive de empresa...")
        creds.refresh(Request())
        _COMPANY_DRIVE_CREDS = creds # Almacena en caché
        print("DEBUG: Token de acceso de Google Drive de empresa refrescado y credenciales obtenidas.")
        return creds
    except Exception as e:
        print(f"ERROR: No se pudo refrescar el token de Google Drive de empresa: {e}")
        return None

def find_or_create_drive_folder(service, folder_name, parent_folder_id=None):
    """
    Busca una carpeta por nombre. Si no existe, la crea.
    :param service: Objeto de servicio de Google Drive API.
    :param folder_name: Nombre de la carpeta a buscar o crear.
    :param parent_folder_id: (Opcional) ID de la carpeta padre donde buscar/crear.
    :return: ID de la carpeta encontrada o creada, o None si falla.
    """
    try:
        # Buscar la carpeta
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'"
        if parent_folder_id:
            query += f" and '{parent_folder_id}' in parents"
        
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])

        if items:
            print(f"DEBUG: Carpeta '{folder_name}' encontrada con ID: {items[0]['id']}")
            return items[0]['id']
        else:
            # Crear la carpeta si no existe
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
    :param creds: Objeto Credentials autenticado de Google.
    :param file_content_io: io.BytesIO que contiene el contenido del archivo PDF.
    :param file_name: Nombre del archivo a subir.
    :param folder_id: (Opcional) ID de la carpeta de Google Drive donde se subirá el archivo.
                      Si no se especifica, se subirá a la raíz de My Drive.
    :return: ID del archivo subido en Google Drive o None si falla.
    """
    try:
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': file_name, 'mimeType': 'application/pdf'}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        file_content_io.seek(0) # Asegurarse de que el cursor esté al inicio del stream

        file = service.files().create(
            body=file_metadata,
            media_body=file_content_io, # Pasar el objeto BytesIO directamente
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
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
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

    return render_template('formulario_relleno.html', 
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
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento')
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo')
    estado_general = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    plazo_reevaluacion_str = request.form.get('plazo')
    fecha_reeval = request.form.get('fecha_reevaluacion')
    derivaciones = request.form.get('derivaciones')
    fecha_eval = datetime.today().strftime('%d/%m/%Y')

    print(f"DEBUG: generar_pdf - Datos recibidos: nombre={nombre}, rut={rut}, sexo={sexo}, diagnostico={diagnostico}, fecha_reeval={fecha_reeval}")

    if not all([estudiante_id, nomina_id, nombre, rut, fecha_nac, edad, nacionalidad, sexo, estado_general, diagnostico, fecha_reeval, derivaciones]):
        flash('Faltan campos obligatorios en el formulario para guardar y generar PDF.', 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # 1. Persistir los datos del formulario en Supabase
    try:
        fecha_reevaluacion_db = fecha_reeval
        if fecha_reeval and "/" in fecha_reeval:
            try:
                fecha_reevaluacion_db = datetime.strptime(fecha_reeval, '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                pass

        update_data = {
            'sexo': sexo,
            'estado_general': estado_general,
            'diagnostico': diagnostico,
            'fecha_reevaluacion': fecha_reevaluacion_db,
            'derivaciones': derivaciones,
            'fecha_relleno': str(date.today())
        }
        
        print(f"DEBUG: Datos a actualizar en Supabase para estudiante {estudiante_id}: {update_data}")
        response_db = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_HEADERS,
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
    if fecha_reeval and "-" in fecha_reeval:
        try:
            fecha_reeval_pdf = datetime.strptime(fecha_reeval, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            fecha_reeval_pdf = fecha_reeval
    else:
        fecha_reeval_pdf = fecha_reeval

    ruta_pdf = os.path.join("static", "FORMULARIO.pdf")
    if not os.path.exists(ruta_pdf):
        flash("❌ Error: El archivo 'FORMULARIO.pdf' no se encontró en la carpeta 'static'.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    try:
        reader = PdfReader(ruta_pdf)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac,
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
        print(f"DEBUG: Fields to fill in PDF: {campos}")

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

        nombre_archivo_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario.pdf"
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
    doctora_id = session.get('usuario_id')

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}")

    if not estudiante_id or not nomina_id or not doctora_id:
        return jsonify({"success": False, "message": "Datos de estudiante, nómina o doctora faltantes"}), 400

    try:
        update_data = {
            'fecha_relleno': str(date.today()),
            'doctora_evaluadora_id': doctora_id
        }
        
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_HEADERS,
            json=update_data
        )
        response.raise_for_status()
        
        if response.status_code == 200 or response.status_code == 204:
            print(f"DEBUG: Estudiante {estudiante_id} marcado como evaluado y guardado en Supabase.")
            return jsonify({"success": True, "message": "Estudiante marcado como evaluado."})
        else:
            print(f"ERROR: No se pudo actualizar el estudiante al marcar como evaluado: {response.status_code} - {response.text}")
            return jsonify({"success": False, "message": "No se pudo actualizar el estudiante."}), response.status_code

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al marcar estudiante como evaluado: {e} - {response.text if 'response' in locals() else 'No response'}")
        return jsonify({"success": False, "message": f"Error de conexión: {str(e)}"}), 500
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
        res = requests.get(url, headers=SUPABASE_HEADERS)
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
    evaluaciones_doctora = 0 # This variable is for the individual doctor's count

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
    doctor_performance_data = {} # Initialize for admin view
    if usuario != 'admin':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}"
                f"&select=id,nombre_nomina,tipo_nomina,doctora_id"
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
                    'tipo_nomina_display': display_name
                })
            print(f"DEBUG: Nóminas asignadas procesadas para plantilla: {assigned_nominations}")
            
            # Conteo de evaluaciones solo para la doctora loggeada (no admin)
            url_evaluaciones_doctora = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?doctora_evaluadora_id=eq.{usuario_id}&fecha_relleno.not.is.null&select=count"
            print(f"DEBUG: URL para contar evaluaciones de doctora: {url_evaluaciones_doctora}")
            res_evaluaciones_doctora = requests.get(url_evaluaciones_doctora, headers=SUPABASE_HEADERS)
            res_evaluaciones_doctora.raise_for_status()
            content_range = res_evaluaciones_doctora.headers.get('Content-Range')
            if content_range:
                try:
                    evaluaciones_doctora = int(content_range.split('/')[-1])
                except ValueError:
                    evaluaciones_doctora = 0
            print(f"DEBUG: Total de evaluaciones para doctora {usuario_id}: {evaluaciones_doctora}")

        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas o contar evaluaciones: {e}")
            print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
            flash('Error al cargar sus nóminas asignadas o conteo de evaluaciones.', 'error')

    if usuario == 'admin':
        try:
            url_doctoras = f"{SUPABASE_URL}/rest/v1/doctoras"
            print(f"DEBUG: URL para obtener doctoras (admin): {url_doctoras}")
            res_doctoras = requests.get(url_doctoras, headers=SUPABASE_HEADERS)
            res_doctoras.raise_for_status()
            doctoras = res_doctoras.json()
            print(f"DEBUG: Doctoras recibidas (admin): {doctoras}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener doctoras: {e}")
            print(f"Response text: {res_doctoras.text if 'res_doctoras' in locals() else 'No response'}")
            flash('Error al cargar la lista de doctoras para administración.', 'error')

        try:
            url_establecimientos_admin = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre"
            print(f"DEBUG: URL para obtener establecimientos (admin): {url_establecimientos_admin}")
            res_establecimientos = requests.get(url_establecimientos_admin, headers=SUPABASE_HEADERS)
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
            print(f"DEBUG: Establecimientos recibidos (admin): {establecimientos_admin_list}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener establecimientos para conteo: {e}")
            print(f"Response text: {res_establecimientos.text if 'res_establecimientos' in locals() else 'No response'}")


        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1
        print(f"DEBUG: Conteo de formularios por establecimiento: {conteo}")

        try:
            url_admin_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina,tipo_nomina,doctora_id,url_excel_original,nombre_excel_original"
            print(f"DEBUG: URL para obtener nóminas cargadas por admin: {url_admin_nominas}")
            res_admin_nominas = requests.get(url_admin_nominas, headers=SUPABASE_HEADERS)
            res_admin_nominas.raise_for_status()
            admin_nominas_cargadas = res_admin_nominas.json()
            print(f"DEBUG: Nóminas cargadas por admin recibidas: {admin_nominas_cargadas}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas cargadas por admin: {e}")
            print(f"Response text: {res_admin_nominas.text if 'res_admin_nominas' in locals() else 'No response'}")
            flash('Error al cargar la lista de nóminas en la vista de administrador.', 'error')
        
        # --- NUEVA LÓGICA: Obtener rendimiento por doctora (para admin) ---
        for doc in doctoras:
            doctor_id = doc['id']
            try:
                # Query to count completed forms for this specific doctor
                url_doctor_forms = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?doctora_evaluadora_id=eq.{doctor_id}&fecha_relleno.not.is.null&select=count"
                print(f"DEBUG: URL para rendimiento de doctora {doc['usuario']}: {url_doctor_forms}")
                res_doctor_forms = requests.get(url_doctor_forms, headers=SUPABASE_HEADERS)
                res_doctor_forms.raise_for_status()
                count_range = res_doctor_forms.headers.get('Content-Range')
                if count_range:
                    doctor_performance_data[doctor_id] = int(count_range.split('/')[-1])
                else:
                    doctor_performance_data[doctor_id] = 0
                print(f"DEBUG: Doctora {doc['usuario']} (ID: {doctor_id}) ha completado {doctor_performance_data[doctor_id]} formularios.")
            except requests.exceptions.RequestException as e:
                print(f"❌ Error al obtener formularios completados para doctora {doc['usuario']}: {e}")
                doctor_performance_data[doctor_id] = 0 # Set to 0 on error
            except Exception as e:
                print(f"❌ Error inesperado al procesar rendimiento de doctora {doc['usuario']}: {e}")
                doctor_performance_data[doctor_id] = 0


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
        evaluaciones_doctora=evaluaciones_doctora, # For individual doctor (non-admin)
        doctor_performance_data=doctor_performance_data # NEW! For admin view
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
    archivo = request.files.get('formulario')

    print(f"DEBUG: admin_agregar - Datos recibidos: nombre={nombre}, fecha={fecha}, horario={horario}, doctora_id_from_form={doctora_id_from_form}, alumnos={cantidad_alumnos}, archivo_presente={bool(archivo)}")

    if not all([nombre, fecha, horario, doctora_id_from_form]):
        flash("❌ Faltan campos obligatorios para el establecimiento.", 'error')
        return redirect(url_for('dashboard'))

    if not archivo or not permitido(archivo.filename):
        flash("❌ Archivo de formulario base no válido o no seleccionado.", 'error')
        return redirect(url_for('dashboard'))

    nuevo_id = str(uuid.uuid4())
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()

    try:
        upload_path = f"formularios/{nuevo_id}/{filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo a Storage: {upload_url}")
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
        res_upload.raise_for_status()

        url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
        print(f"DEBUG: Archivo subido, URL pública: {url_publica}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al subir el archivo base al Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo del formulario base.", 'error')
        return redirect(url_for('dashboard'))

    data_establecimiento = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha": fecha,
        "horario": horario,
        "observaciones": obs,
        "doctora_id": doctora_id_from_form,
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None,
        "url_archivo": url_publica,
        "nombre_archivo": filename
    }
    print(f"DEBUG: Payload para insertar establecimiento: {data_establecimiento}")

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_HEADERS,
            json=data_establecimiento
        )
        response_db.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar establecimiento (status): {response_db.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar establecimiento (text): {response_db.text}")
        flash("✅ Establecimiento y formulario base agregado correctamente.", 'success')
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

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}")

    if not all([tipo_nomina, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Falta uno o más campos obligatorios para cargar la nómina (tipo, nombre, doctora, archivo).', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    nomina_id = str(uuid.uuid4())
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read()

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
        flash("❌ Error al subir el archivo de la nómina al almacenamiento. Por favor, inténtelo de nuevo.", 'error')
        return redirect(url_for('dashboard'))

    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina,
        "doctora_id": doctora_id_from_form,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename
    }
    print(f"DEBUG: Payload para insertar nómina en nominas_medicas: {data_nomina}")

    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_HEADERS,
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
        'comuna': ['comuna'],
        'direccion': ['direccion', 'dirección']
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

            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str,
                "nacionalidad": str(row.get(col_map.get('nacionalidad'), 'Chilena')).strip(),
                "comuna": str(row.get(col_map.get('comuna'), 'No especificada')).strip(),
                "direccion": str(row.get(col_map.get('direccion'), 'No especificada')).strip(),
                "sexo": sexo_adivinado,
                "estado_general": None,
                "diagnostico": None,
                "fecha_reevaluacion": None,
                "derivaciones": None,
                "fecha_relleno": None
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
        url_estudiantes_insert = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
        print(f"DEBUG: URL para insertar estudiantes: {url_estudiantes_insert}")
        res_insert_estudiantes = requests.post(
            url_estudiantes_insert,
            headers=SUPABASE_HEADERS,
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

    doctor_id = session['usuario_id'] # ID de la doctora actual, para logging o si se necesitara.
    
    # Obtener credenciales de la cuenta de empresa
    creds = get_company_google_credentials()
    if not creds:
        return jsonify({"success": False, "message": "Error de autenticación con Google Drive de la empresa. Contacte al administrador (refresh token no configurado o inválido)."}), 500

    # Recopilar datos del formulario para generar el PDF
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id') # Necesitamos la nomina_id para obtener el nombre del colegio/establecimiento
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento')
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo')
    estado_general = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    fecha_reeval = request.form.get('fecha_reevaluacion')
    derivaciones = request.form.get('derivaciones')
    fecha_eval = datetime.today().strftime('%d/%m/%Y')

    if not all([estudiante_id, nomina_id, nombre, rut]): # Campos mínimos para identificar y nombrar el archivo
        return jsonify({"success": False, "message": "Faltan datos esenciales del formulario para subir a Drive."}), 400

    # Obtener el nombre del colegio/establecimiento para crear la carpeta
    establecimiento_nombre = "Formularios Varios" # Nombre por defecto si no se encuentra
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

    # Reformatear fecha de reevaluación a DD/MM/YYYY si viene en formato ISO
    fecha_reeval_pdf = fecha_reeval
    if fecha_reeval and "-" in fecha_reeval:
        try:
            fecha_reeval_pdf = datetime.strptime(fecha_reeval, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass

    ruta_pdf = os.path.join("static", "FORMULARIO.pdf")
    if not os.path.exists(ruta_pdf):
        print("ERROR: Archivo FORMULARIO.pdf no encontrado para generar PDF para Drive.")
        return jsonify({"success": False, "message": "Error interno: Archivo base del formulario no encontrado en el servidor."}), 500

    try:
        reader = PdfReader(ruta_pdf)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac,
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
        writer.update_page_form_field_values(writer.pages[0], campos)
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({NameObject("/AcroForm"): DictionaryObject()})
        writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})

        output_pdf_io = io.BytesIO()
        writer.write(output_pdf_io)
        output_pdf_io.seek(0) # Reset buffer position

        file_name = f"{nombre.replace(' ', '_')}_{rut}_formulario.pdf"
        
        # 1. Obtener el servicio de Drive
        service = build('drive', 'v3', credentials=creds)

        # 2. Buscar o crear la carpeta del colegio
        # Si GOOGLE_DRIVE_PARENT_FOLDER_ID está configurado, la carpeta del colegio se creará dentro de ella.
        colegio_folder_id = find_or_create_drive_folder(service, establecimiento_nombre, GOOGLE_DRIVE_PARENT_FOLDER_ID)

        if not colegio_folder_id:
            return jsonify({"success": False, "message": "Error al encontrar o crear la carpeta del colegio en Google Drive."}), 500

        # 3. Subir el PDF a la carpeta del colegio
        file_id = upload_pdf_to_google_drive(creds, output_pdf_io, file_name, colegio_folder_id)

        if file_id:
            return jsonify({"success": True, "message": f"Formulario enviado a Google Drive (ID: {file_id}) en la carpeta '{establecimiento_nombre}'."})
        else:
            return jsonify({"success": False, "message": "Error al subir el formulario a Google Drive."}), 500

    except Exception as e:
        print(f"ERROR: Error al procesar y subir formulario a Drive: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al procesar y subir a Drive: {str(e)}"}), 500

