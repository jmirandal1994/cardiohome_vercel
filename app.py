from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response
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
import pandas as pd # Importado para un manejo más robusto de Excel/CSV
import unicodedata # Necesario para la función normalizar

app = Flask(__name__)
# ¡IMPORTANTE! Cambia esta clave por una cadena larga y aleatoria en producción.
app.secret_key = 'clave_super_segura_cardiohome_2025'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'} # Añadido 'csv' para las nóminas
PDF_BASE = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf' # Asegúrate de que este archivo exista en la carpeta 'static'

# -------------------- Supabase Configuration --------------------
# These variables will be injected by the Canvas environment or taken from .env locally
# A fallback with direct keys is used, but in production, ALWAYS use environment variables.
firebaseConfig = json.loads(os.getenv("FIREBASE_CONFIG", "{}")) # Load from environment variable
SUPABASE_URL = os.getenv("SUPABASE_URL") or firebaseConfig.get("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or firebaseConfig.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or firebaseConfig.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImiWF0IjoxNzQ3NTQxNzg3LCJleHAiOjIwNjMxMTc3ODd9.i3ixl5ws3Z3QTxIcZNjI29ZknRmJwwQfUyLmX0Z0khc")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}
SUPABASE_SERVICE_HEADERS = { # Headers for service_role (elevated permissions, use only on the backend!)
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}


# SendGrid Configuration (make sure to have your keys in environment variables)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'your_sendgrid_email@example.com' # Change this to your verified SendGrid email!
SENDGRID_TO = 'destination_admin_email@example.com' # Email to which notifications will be sent

# -------------------- Utilities --------------------
def permitido(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_age(birth_date):
    """Calculates age in years and months from a birth date."""
    today = date.today()
    years = today.year - birth_date.year
    months = today.month - birth_date.month
    if months < 0:
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    """Attempts to guess gender based on name (simple heuristic)."""
    name = name.lower()
    # Simple heuristic: names ending in 'a' or containing 'maria' are usually feminine.
    if name.endswith("a") or "maria" in name:
        return "F"
    return "M"

def normalizar(texto):
    """Normalizes text: removes spaces, lowercases, removes accents, and replaces spaces with underscores."""
    if not isinstance(texto, str):
        return ""
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = texto.replace(" ", "_")
    return texto

def enviar_correo_sendgrid(asunto, cuerpo, adjuntos=None):
    """Sends an email using the SendGrid API."""
    if not SENDGRID_API_KEY:
        print("Missing SENDGRID_API_KEY in environment variables. Email will not be sent.")
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
                "type": "application/octet-stream", # Generic type for binary files
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
        print(f"Email sent, status: {response.status_code}")
        if response.status_code >= 400:
            print(f"SendGrid Error Response: {response.text}")
    except Exception as e:
        print(f"Error sending email with SendGrid: {e}")

# -------------------- Application Routes --------------------

@app.route('/relleno_formularios/<nomina_id>', methods=['GET'])
def relleno_formularios(nomina_id):
    """
    Displays the form filling page for a specific nomination.
    Loads students associated with the `nomina_id` from Supabase.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {session.get('usuario_id')}")


    # 1. Get information for the specific nomination (name, type, etc.)
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
        print(f"DEBUG: URL para obtener nómina en /relleno_formularios: {url_nomina}")
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status() # Raises exception for HTTP errors (4xx or 5xx)
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

    # 2. Get students associated with this nomination
    estudiantes = []
    try:
        url_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        print(f"DEBUG: URL para obtener estudiantes en /relleno_formularios: {url_estudiantes}")
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        print(f"DEBUG: Estudiantes raw recibidos en /relleno_formularios: {estudiantes_raw}")


        for est in estudiantes_raw:
            # Ensure fecha_nacimiento is a date object for calculate_age
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

    return render_template('formulario_relleno.html', estudiantes=estudiantes)


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    """Generates a PDF file filled with form data."""
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # Form data received from POST
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento') # Comes already formatted from HTML
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo')
    estado = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    fecha_reeval = request.form.get('fecha_reevaluacion')
    derivaciones = request.form.get('derivaciones')
    fecha_eval = datetime.today().strftime('%d/%m/%Y') # Current evaluation date

    print(f"DEBUG: generar_pdf - Datos recibidos: nombre={nombre}, rut={rut}, fecha_nac={fecha_nac}")


    # Reformat reevaluation date to DD/MM/YYYY if it comes in YYYY-MM-DD format (from HTML date input)
    if fecha_reeval and "-" in fecha_reeval:
        try:
            fecha_reeval = datetime.strptime(fecha_reeval, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass # If already in correct format or not a valid date, leave as is.

    # Path to the base PDF file (must be in the 'static' folder)
    ruta_pdf = os.path.join("static", "FORMULARIO.pdf")
    if not os.path.exists(ruta_pdf):
        flash("❌ Error: The file 'FORMULARIO.pdf' was not found in the 'static' folder.", 'error')
        # Attempt to redirect to the current nomination if it's in session
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    try:
        reader = PdfReader(ruta_pdf)
        writer = PdfWriter()
        writer.add_page(reader.pages[0]) # Add the first page of the base PDF

        # Dictionary of fields to fill in the PDF.
        # Make sure the keys here (e.g., "nombre", "rut") exactly match the field names in your editable PDF!
        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac,
            "nacionalidad": nacionalidad,
            "edad": edad,
            "diagnostico_1": diagnostico,
            "diagnostico_2": diagnostico, # If you have a secondary field for the same diagnosis
            "estado_general": estado,
            "fecha_evaluacion": fecha_eval,
            "fecha_reevaluacion": fecha_reeval,
            "derivaciones": derivaciones,
            "sexo_f": "X" if sexo == "F" else "", # Mark female sex checkbox
            "sexo_m": "X" if sexo == "M" else "", # Mark male sex checkbox
        }
        print(f"DEBUG: Fields to fill in PDF: {campos}")


        # Ensure /AcroForm exists in the PDF root object
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })

        # Update form field values on the page
        writer.update_page_form_field_values(writer.pages[0], campos)

        # Force display of filled fields without needing to click
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })

        # Generate the final PDF in memory
        output = io.BytesIO()
        writer.write(output)
        output.seek(0) # Move the cursor to the beginning of the stream

        # Prepare filename for download
        nombre_archivo_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario.pdf"
        print(f"DEBUG: PDF generated and ready for download: {nombre_archivo_descarga}")
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        # Redirect back to the filling page if possible
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


@app.route('/')
def index():
    """Displays the login page."""
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    """Processes the login attempt."""
    usuario = request.form['username']
    clave = request.form['password']
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario}&password=eq.{clave}"
    print(f"DEBUG: Intento de login para usuario: {usuario}, URL: {url}")
    try:
        res = requests.get(url, headers=SUPABASE_HEADERS)
        res.raise_for_status() # Raises an exception for HTTP errors
        data = res.json()
        print(f"DEBUG: Respuesta Supabase login: {data}")
        if data:
            session['usuario'] = usuario
            session['usuario_id'] = data[0]['id'] # <-- ID of the doctor/admin logging in
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
    """Displays the user's dashboard (admin or doctor)."""
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario = session['usuario']
    usuario_id = session.get('usuario_id')
    print(f"DEBUG: Accediendo a dashboard para usuario: {usuario}, ID: {usuario_id}")


    # --- Logic for Establishments/Events (Scheduled Visits) ---
    campos_establecimientos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo,doctora_id" # Added doctora_id
    eventos = []
    try:
        if usuario != 'admin':
            # For doctors, only their assigned events
            url_eventos = (
                f"{SUPABASE_URL}/rest/v1/establecimientos"
                f"?doctora_id=eq.{usuario_id}" # Filter by logged-in doctor's ID
                f"&select={campos_establecimientos}"
            )
        else:
            # For admin, all events
            url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos_establecimientos}"
        
        print(f"DEBUG: URL para obtener eventos: {url_eventos}")
        res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
        res_eventos.raise_for_status()
        eventos = res_eventos.json()
        print(f"DEBUG: Eventos recibidos: {eventos}")

        if isinstance(eventos, list):
            # Sort by schedule if exists and is valid
            eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0] if e.get('horario') else '')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener eventos: {e}")
        print(f"Response text: {res_eventos.text if 'res_eventos' in locals() else 'No response'}")
        flash('Error al cargar el calendario de visitas.', 'error')

    # --- Logic for Uploaded Forms (General, by any doctor) ---
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

    # --- Logic for Assigned Nominations (For Doctors Only) ---
    assigned_nominations = []
    if usuario != 'admin':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}" # Filter by logged-in doctor's ID
                f"&select=id,nombre_nomina,tipo_nomina,doctora_id" # Added doctora_id for debugging
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
                    'nombre_establecimiento': nom['nombre_nomina'], # Renamed for consistency in the template
                    'tipo_nomina_display': display_name
                })
            print(f"DEBUG: Nóminas asignadas procesadas para plantilla: {assigned_nominations}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas: {e}")
            print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
            flash('Error al cargar sus nóminas asignadas.', 'error')

    # --- Admin-specific Logic (display doctor lists and counts) ---
    doctoras = []
    establecimientos_admin_list = [] # A separate list for admin with all establishments
    conteo = {} # Count of forms per establishment

    if usuario == 'admin':
        try:
            # Get complete list of doctors
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
            # Get all establishments (not just those of the logged-in admin)
            url_establecimientos_admin = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre"
            print(f"DEBUG: URL para obtener establecimientos (admin): {url_establecimientos_admin}")
            res_establecimientos = requests.get(url_establecimientos_admin, headers=SUPABASE_HEADERS)
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
            print(f"DEBUG: Establecimientos recibidos (admin): {establecimientos_admin_list}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener establecimientos para conteo: {e}")
            print(f"Response text: {res_establecimientos.text if 'res_establecimientos' in locals() else 'No response'}")


        # Count uploaded forms per establishment
        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1
        print(f"DEBUG: Conteo de formularios por establecimiento: {conteo}")

        # NEW: Get nominations loaded by the admin (all nominations)
        admin_nominas_cargadas = []
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


    return render_template(
        'dashboard.html',
        usuario=usuario,
        eventos=eventos,
        doctoras=doctoras, # List of doctors for admin
        establecimientos=establecimientos_admin_list, # List of establishments for admin
        formularios=formularios, # Uploaded forms by doctors
        conteo=conteo,
        assigned_nominations=assigned_nominations, # Nominations assigned to the logged-in doctor
        admin_nominas_cargadas=admin_nominas_cargadas # NEW! Nominations loaded by the admin
    )

@app.route('/logout')
def logout():
    """Closes the user's session."""
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/agregar', methods=['POST'])
def admin_agregar():
    """
    Route for the **administrator** to add a new **establishment**
    (a scheduled visit) and upload an associated base form.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    nombre = request.form.get('nombre')
    fecha = request.form.get('fecha')
    horario = request.form.get('horario')
    obs = request.form.get('obs')
    doctora_id_from_form = request.form.get('doctora', '').strip() # <-- Gets the selected ID from the form
    cantidad_alumnos = request.form.get('alumnos')
    archivo = request.files.get('formulario') # Base PDF or DOCX file

    print(f"DEBUG: admin_agregar - Datos recibidos: nombre={nombre}, fecha={fecha}, horario={horario}, doctora_id_from_form={doctora_id_from_form}, alumnos={cantidad_alumnos}, archivo_presente={bool(archivo)}")

    if not all([nombre, fecha, horario, doctora_id_from_form]):
        flash("❌ Faltan campos obligatorios para el establecimiento.", 'error')
        return redirect(url_for('dashboard'))

    if not archivo or not permitido(archivo.filename):
        flash("❌ Archivo de formulario base no válido o no seleccionado.", 'error')
        return redirect(url_for('dashboard'))

    nuevo_id = str(uuid.uuid4()) # Unique ID for the establishment
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    # 1. Upload the base form file to Supabase Storage
    try:
        upload_path = f"formularios/{nuevo_id}/{filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo a Storage: {upload_url}")
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
        res_upload.raise_for_status() # Raises exception if upload fails

        url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
        print(f"DEBUG: Archivo subido, URL pública: {url_publica}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al subir el archivo base al Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo del formulario base.", 'error')
        return redirect(url_for('dashboard'))

    # 2. Insert establishment data into the 'establecimientos' table
    data_establecimiento = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha": fecha,
        "horario": horario,
        "observaciones": obs,
        "doctora_id": doctora_id_from_form, # <-- Uses the ID from the form
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None,
        "url_archivo": url_publica,
        "nombre_archivo": filename
    }
    print(f"DEBUG: Payload para insertar establecimiento: {data_establecimiento}")

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_HEADERS, # SUPABASE_HEADERS is used because RLS must allow insertion
            json=data_establecimiento
        )
        response_db.raise_for_status() # Raises exception if DB insertion fails
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
    """
    Route for the **administrator** to upload a student roster
    from an Excel file and assign it to a doctor.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    tipo_nomina = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id_from_form = request.form.get('doctora', '').strip() # <-- Gets the selected ID from the form
    excel_file = request.files.get('excel')

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}")

    if not all([tipo_nomina, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Faltan campos obligatorios para cargar la nómina.', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    nomina_id = str(uuid.uuid4()) # Unique ID for this nomination
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read() # Read binary content of the file
    mime_type = mimetypes.guess_type(excel_filename)[0] or 'application/octet-stream'

    # 1. Upload the original Excel/CSV file to Supabase Storage
    try:
        upload_path = f"nominas_medicas/{nomina_id}/{excel_filename}"
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

    # 2. Insert the nomination entry into the 'nominas_medicas' table
    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina,
        "doctora_id": doctora_id_from_form, # <-- Uses the ID from the form
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename
    }
    print(f"DEBUG: Payload para insertar nómina en nominas_medicas: {data_nomina}")

    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_HEADERS, # SUPABASE_HEADERS is used because RLS must allow insertion
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (status): {res_insert_nomina.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (text): {res_insert_nomina.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
        # Consider cleaning up the file from Storage if DB insertion fails
        return redirect(url_for('dashboard'))

    # 3. Read and process Excel/CSV content to save students
    try:
        excel_data_io = io.BytesIO(excel_file_data)
        if excel_filename.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(excel_data_io, engine='openpyxl')
        elif excel_filename.lower().endswith('.csv'):
            df = pd.read_csv(excel_data_io)
        else:
            raise ValueError("File format not supported for reading (only .xls, .xlsx, .csv).")

        estudiantes_a_insertar = []
        df.columns = [normalizar(col) for col in df.columns]
        print(f"DEBUG: Columnas del Excel normalizadas: {df.columns.tolist()}")

        for index, row in df.iterrows():
            nombre = row.get('nombre') or row.get('nombres') or row.get('alumno')
            rut = row.get('rut')
            fecha_nac_excel = row.get('fecha_nacimiento') or row.get('fecha_nac')
            nacionalidad = row.get('nacionalidad')

            if not all([nombre, rut, fecha_nac_excel]):
                print(f"⚠️ Fila {index+2} incompleta en Excel, se omite: {row.to_dict()}")
                continue

            try:
                fecha_nac_obj = pd.to_datetime(fecha_nac_excel).date()
                fecha_nac_str = fecha_nac_obj.isoformat()
                edad = calculate_age(fecha_nac_obj)
            except Exception as e:
                print(f"⚠️ Fila {index+2} con fecha inválida '{fecha_nac_excel}': {e}. Se omitirá esta entrada.")
                flash(f"⚠️ Atención: Fecha de nacimiento inválida en la fila {index+2} del Excel. Se omitirá esa entrada.", 'warning')
                continue

            sexo = guess_gender(str(nombre).split()[0])

            estudiantes_a_insertar.append({
                "nomina_id": nomina_id,
                "nombre": str(nombre),
                "rut": str(rut),
                "fecha_nacimiento": fecha_nac_str,
                "edad": edad,
                "nacionalidad": str(nacionalidad) if nacionalidad else "Desconocida",
                "sexo": sexo
            })
        
        print(f"DEBUG: Estudiantes listos para insertar ({len(estudiantes_a_insertar)}): {estudiantes_a_insertar}")


        # Insert all students in a single batch (Supabase supports this with an array of objects)
        if estudiantes_a_insertar:
            res_insert_estudiantes = requests.post(
                f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
                headers=SUPABASE_HEADERS,
                json=estudiantes_a_insertar
            )
            res_insert_estudiantes.raise_for_status()
            print(f"DEBUG: Respuesta de Supabase al insertar estudiantes (status): {res_insert_estudiantes.status_code}")
            print(f"DEBUG: Respuesta de Supabase al insertar estudiantes (text): {res_insert_estudiantes.text}")
            flash(f"✅ Nómina '{nombre_especifico}' cargada y {len(estudiantes_a_insertar)} estudiantes procesados exitosamente.", 'success')
        else:
            flash("⚠️ El archivo de la nómina no contiene estudiantes válidos para procesar.", 'warning')

    except Exception as e:
        print(f"❌ Error al procesar el archivo Excel o insertar estudiantes: {e}")
        flash('❌ Error al procesar el archivo de la nómina. Verifique que el formato de las columnas ("nombre", "rut", "fecha_nacimiento") sea correcto.', 'error')
        # If student loading fails catastrophically, you might consider deleting the nomination entry created
        # requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
        
    return redirect(url_for('dashboard'))


@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    """
    Route for the doctor to upload completed forms (PDF, Word, Excel)
    associated with a specific establishment.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo') # Get all selected files
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

            # Generate a unique ID for each file, to avoid name collisions
            unique_file_id = str(uuid.uuid4())

            # 📤 1. Upload file to Supabase Storage using service_role
            upload_path = f"formularios_completados/{establecimiento}/{unique_file_id}/{filename}"
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
            print(f"DEBUG: Subiendo archivo completado a Storage: {upload_url}")
            
            try:
                res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
                res_upload.raise_for_status() # Raises exception for HTTP errors (4xx or 5xx)
                
                # 🌐 2. Build public URL of the file
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
                print(f"DEBUG: Archivo completado subido, URL pública: {url_publica}")

                # 📝 3. Save metadata to the 'formularios_subidos' table
                data = {
                    "doctoras_id": usuario_id, # <-- ID of the doctor uploading the file
                    "establecimientos_id": establecimiento, # Associated establishment ID
                    "nombre_archivo": filename,
                    "url_archivo": url_publica
                }
                print(f"DEBUG: Payload para insertar formulario subido en DB: {data}")

                res_insert = requests.post(
                    f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                    headers=SUPABASE_HEADERS,
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
    
    # After processing all files, use flash to display all messages
    for msg in mensajes:
        flash(msg, 'success' if '✅' in msg else 'error' if '❌' in msg else 'warning')

    return redirect(url_for('dashboard'))

# New route for admin to view details of evaluated schools (if it exists in your navbar)
@app.route('/colegios')
def colegios():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    
    # Here you can add logic to load and display data relevant to evaluated schools
    # For now, it just renders an example template.
    return render_template('colegios.html') # Make sure to have this template file

# New route for the doctor to view only their assigned nominations
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
            f"?doctora_id=eq.{usuario_id}" # Filter by logged-in doctor's ID
            f"&select=id,nombre_nomina,tipo_nomina,doctora_id" # Added doctora_id for debugging
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
                'tipo_nomina_display': display_name
            })
        print(f"DEBUG: Nóminas asignadas procesadas para plantilla /mis_nominas: {assigned_nominations}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener mis nóminas: {e}")
        print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
        flash('Error al cargar sus nóminas asignadas.', 'error')
    except Exception as e:
        print(f"❌ Error inesperado al procesar mis nóminas: {e}")
        flash('Error inesperado al cargar sus nóminas asignadas.', 'error')


    # It's important to render a template that displays these nominations, for example, a simplified version
    # or by reusing the assigned nominations section of dashboard.
    return render_template('mis_nominas.html', assigned_nominations=assigned_nominations)

@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    alumnos_evaluados = request.form.get('alumnos')
    
    print(f"DEBUG: evaluados - Establecimiento ID: {establecimiento}, Alumnos evaluados: {alumnos_evaluados}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /evaluados: {session.get('usuario_id')}")


    # Here you should update the 'establecimientos' table to record the number of evaluated students
    # Assuming there's an 'alumnos_evaluados' column in your 'establecimientos' table
    data_update = {
        "cantidad_alumnos_evaluados": int(alumnos_evaluados) if alumnos_evaluados else 0
    }

    try:
        response_db = requests.patch( # We use PATCH to update an existing record
            f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento}",
            headers=SUPABASE_HEADERS,
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

    return redirect(url_for('dashboard')) # Redirect to the dashboard or to the specific establishment page if it exists
