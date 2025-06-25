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

# -------------------- Configuración de Supabase --------------------
# Estas variables serán inyectadas por el entorno de Canvas o tomadas de .env local
# Se usa un fallback con las claves directas, pero en producción, SIEMPRE usar variables de entorno.
firebaseConfig = json.loads(os.getenv("FIREBASE_CONFIG", "{}")) # Cargar desde variable de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL") or firebaseConfig.get("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or firebaseConfig.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or firebaseConfig.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NzU0MTc4NywiZXhwIjoyMDYzMTE3Nzg3fQ.i3ixl5ws3Z3QTxIcZNjI29ZknRmJwwQfUyLmX0Z0khc")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}
SUPABASE_SERVICE_HEADERS = { # Cabeceras para service_role (permisos elevados, ¡usar solo en el backend!)
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}


# Configuración de SendGrid (asegúrate de tener tus claves en las variables de entorno)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'tu_correo_sendgrid@example.com' # ¡Cambia esto a tu correo verificado en SendGrid!
SENDGRID_TO = 'correo_destino_admin@example.com' # Correo al que se enviarán las notificaciones

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
    name = name.lower()
    # Heurística simple: nombres que terminan en 'a' o contienen 'maria' suelen ser femeninos.
    if name.endswith("a") or "maria" in name:
        return "F"
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
                "type": "application/octet-stream", # Tipo genérico para archivos binarios
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

# -------------------- Rutas de la Aplicación --------------------

@app.route('/relleno_formularios/<nomina_id>', methods=['GET'])
def relleno_formularios(nomina_id):
    """
    Muestra el formulario de relleno para una nómina específica.
    Carga los estudiantes asociados a la `nomina_id` desde Supabase.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # 1. Obtener la información de la nómina específica (nombre, tipo, etc.)
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
        nomina_data = res_nomina.json()

        if not nomina_data:
            flash("❌ Nómina no encontrada.", 'error')
            return redirect(url_for('dashboard'))

        nomina = nomina_data[0]
        # Guardar en sesión para el breadcrumb o simplemente para usarlo en la plantilla
        session['establecimiento'] = f"{nomina['nombre_nomina']} ({nomina['tipo_nomina'].replace('_', ' ').title()})"
        session['current_nomina_id'] = nomina_id # Guardar el ID de la nómina actual

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener datos de la nómina: {e}")
        flash('Error al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Error inesperado al procesar nómina: {e}")
        flash('Error inesperado al cargar la información de la nómina.', 'error')
        return redirect(url_for('dashboard'))

    # 2. Obtener los estudiantes asociados a esta nómina
    estudiantes = []
    try:
        url_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()

        for est in estudiantes_raw:
            # Asegurarse de que fecha_nacimiento es un objeto date para calculate_age
            if 'fecha_nacimiento' in est and isinstance(est['fecha_nacimiento'], str):
                try:
                    # Supabase guarda las fechas en formato ISO (YYYY-MM-DD)
                    fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                    est['edad'] = calculate_age(fecha_nac_obj)
                    est['fecha_nacimiento_formato'] = fecha_nac_obj.strftime("%d-%m-%Y") # Formato para mostrar en el HTML
                except ValueError:
                    est['fecha_nacimiento_formato'] = 'Fecha Inválida'
                    est['edad'] = 'N/A'
            else: # Si no es string (ej. ya es un datetime object o None)
                 est['fecha_nacimiento_formato'] = 'N/A'
                 est['edad'] = 'N/A'

            estudiantes.append(est)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener estudiantes de la nómina: {e}")
        flash('Error al cargar la lista de estudiantes.', 'error')
        estudiantes = []
    except Exception as e:
        print(f"❌ Error inesperado al procesar estudiantes: {e}")
        flash('Error inesperado al cargar la lista de estudiantes.', 'error')
        estudiantes = []

    return render_template('formulario_relleno.html', estudiantes=estudiantes)


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    """Genera un archivo PDF rellenado con los datos del formulario."""
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # Datos del formulario recibidos del POST
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento') # Viene ya formateado desde el HTML
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo')
    estado = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    fecha_reeval = request.form.get('fecha_reevaluacion')
    derivaciones = request.form.get('derivaciones')
    fecha_eval = datetime.today().strftime('%d/%m/%Y') # Fecha de la evaluación actual

    # Reformatear fecha de reevaluación a DD/MM/YYYY si viene en formato YYYY-MM-DD (del date input HTML)
    if fecha_reeval and "-" in fecha_reeval:
        try:
            fecha_reeval = datetime.strptime(fecha_reeval, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass # Si ya está en formato correcto o no es una fecha válida, se deja como está.

    # Ruta al archivo PDF base (debe estar en la carpeta 'static')
    ruta_pdf = os.path.join("static", "FORMULARIO.pdf")
    if not os.path.exists(ruta_pdf):
        flash("❌ Error: El archivo 'FORMULARIO.pdf' no se encontró en la carpeta 'static'.", 'error')
        # Intentar redirigir a la nómina actual si está en sesión
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    try:
        reader = PdfReader(ruta_pdf)
        writer = PdfWriter()
        writer.add_page(reader.pages[0]) # Añadir la primera página del PDF base

        # Diccionario de campos a rellenar en el PDF.
        # ¡Asegúrate de que las claves aquí (ej. "nombre", "rut") coincidan exactamente con los nombres de los campos en tu PDF editable!
        campos = {
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac,
            "nacionalidad": nacionalidad,
            "edad": edad,
            "diagnostico_1": diagnostico,
            "diagnostico_2": diagnostico, # Si tienes un campo secundario para el mismo diagnóstico
            "estado_general": estado,
            "fecha_evaluacion": fecha_eval,
            "fecha_reevaluacion": fecha_reeval,
            "derivaciones": derivaciones,
            "sexo_f": "X" if sexo == "F" else "", # Marcar casilla de sexo femenino
            "sexo_m": "X" if sexo == "M" else "", # Marcar casilla de sexo masculino
        }

        # Asegurarse de que /AcroForm exista en el objeto raíz del PDF
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })

        # Actualizar los valores de los campos del formulario en la página
        writer.update_page_form_field_values(writer.pages[0], campos)

        # Forzar la visualización de los campos rellenados sin necesidad de hacer clic
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })

        # Generar el PDF final en memoria
        output = io.BytesIO()
        writer.write(output)
        output.seek(0) # Mover el cursor al inicio del stream

        # Preparar el nombre del archivo para la descarga
        nombre_archivo_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario.pdf"
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        # Redirigir de vuelta a la página de relleno si es posible
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


@app.route('/')
def index():
    """Muestra la página de inicio de sesión."""
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    """Procesa el intento de inicio de sesión."""
    usuario = request.form['username']
    clave = request.form['password']
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario}&password=eq.{clave}"
    try:
        res = requests.get(url, headers=SUPABASE_HEADERS)
        res.raise_for_status() # Lanza una excepción para errores HTTP
        data = res.json()
        if data:
            session['usuario'] = usuario
            session['usuario_id'] = data[0]['id']
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
    """Muestra el panel de control del usuario (admin o doctora)."""
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario = session['usuario']
    usuario_id = session.get('usuario_id')

    # --- Lógica para Eventos/Establecimientos (Visitas Programadas) ---
    campos_establecimientos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo"
    eventos = []
    try:
        if usuario != 'admin':
            # Para doctores, solo sus eventos asignados
            url_eventos = (
                f"{SUPABASE_URL}/rest/v1/establecimientos"
                f"?doctora_id=eq.{usuario_id}"
                f"&select={campos_establecimientos}"
            )
        else:
            # Para admin, todos los eventos
            url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos_establecimientos}"

        res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
        res_eventos.raise_for_status()
        eventos = res_eventos.json()
        if isinstance(eventos, list):
            # Ordenar por horario si existe y es válido
            eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0] if e.get('horario') else '')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener eventos: {e}")
        flash('Error al cargar el calendario de visitas.', 'error')

    # --- Lógica para Formularios Subidos (General, por cualquier doctora) ---
    formularios = []
    try:
        res_formularios = requests.get(f"{SUPABASE_URL}/rest/v1/formularios_subidos", headers=SUPABASE_HEADERS)
        res_formularios.raise_for_status()
        formularios = res_formularios.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener formularios subidos: {e}")
        flash('Error al cargar los formularios subidos.', 'error')

    # --- Lógica para Nóminas Asignadas (Solo para Doctores) ---
    assigned_nominations = []
    if usuario != 'admin':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}"
                f"&select=id,nombre_nomina,tipo_nomina"
            )
            res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
            res_nominas_asignadas.raise_for_status()
            raw_nominas = res_nominas_asignadas.json()

            for nom in raw_nominas:
                # Formatear el tipo de nómina para mostrarlo de forma legible
                display_name = nom['tipo_nomina'].replace('_', ' ').title()
                assigned_nominations.append({
                    'id': nom['id'],
                    'nombre_establecimiento': nom['nombre_nomina'], # Renombrado para consistencia en la plantilla
                    'tipo_nomina_display': display_name
                })
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas: {e}")
            flash('Error al cargar sus nóminas asignadas.', 'error')

    # --- Lógica específica para Admin (mostrar listas de doctoras y conteos) ---
    doctoras = []
    establecimientos_admin_list = [] # Una lista separada para el admin con todos los establecimientos
    conteo = {} # Conteo de formularios por establecimiento

    if usuario == 'admin':
        try:
            # Obtener lista completa de doctoras
            res_doctoras = requests.get(f"{SUPABASE_URL}/rest/v1/doctoras", headers=SUPABASE_HEADERS)
            res_doctoras.raise_for_status()
            doctoras = res_doctoras.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener doctoras: {e}")
            flash('Error al cargar la lista de doctoras para administración.', 'error')

        try:
            # Obtener todos los establecimientos (no solo los del admin logueado)
            res_establecimientos = requests.get(f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre", headers=SUPABASE_HEADERS)
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener establecimientos para conteo: {e}")

        # Contar formularios subidos por establecimiento
        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1

    return render_template(
        'dashboard.html',
        usuario=usuario,
        eventos=eventos,
        doctoras=doctoras, # Lista de doctoras para admin
        establecimientos=establecimientos_admin_list, # Lista de establecimientos para admin
        formularios=formularios, # Formularios subidos por las doctoras
        conteo=conteo,
        assigned_nominations=assigned_nominations # Nóminas asignadas a la doctora logueada
    )

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/agregar', methods=['POST'])
def admin_agregar():
    """
    Ruta para que el **administrador** agregue un nuevo **establecimiento**
    (una visita programada) y suba un formulario base asociado.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    nombre = request.form.get('nombre')
    fecha = request.form.get('fecha')
    horario = request.form.get('horario')
    obs = request.form.get('obs')
    doctora_id = request.form.get('doctora', '').strip() # Asegurarse de que sea string y limpiar
    cantidad_alumnos = request.form.get('alumnos')
    archivo = request.files.get('formulario') # Archivo PDF o DOCX base

    if not all([nombre, fecha, horario, doctora_id]):
        flash("❌ Faltan campos obligatorios para el establecimiento.", 'error')
        return redirect(url_for('dashboard'))

    if not archivo or not permitido(archivo.filename):
        flash("❌ Archivo de formulario base no válido o no seleccionado.", 'error')
        return redirect(url_for('dashboard'))

    nuevo_id = str(uuid.uuid4()) # ID único para el establecimiento
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    # 1. Subir el archivo del formulario base a Supabase Storage
    try:
        # La ruta de almacenamiento incluirá el ID del establecimiento para organización
        upload_path = f"formularios/{nuevo_id}/{filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
        res_upload.raise_for_status() # Lanza excepción si la subida falla

        url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" # URL accesible públicamente
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al subir el archivo base al Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo del formulario base.", 'error')
        return redirect(url_for('dashboard'))

    # 2. Insertar los datos del establecimiento en la tabla 'establecimientos'
    data_establecimiento = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha": fecha,
        "horario": horario,
        "observaciones": obs,
        "doctora_id": doctora_id,
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None,
        "url_archivo": url_publica,
        "nombre_archivo": filename
    }

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_HEADERS, # Se usa SUPABASE_HEADERS porque las RLS deben permitir insertar
            json=data_establecimiento
        )
        response_db.raise_for_status() # Lanza excepción si la inserción en DB falla
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
    Ruta para que el **administrador** cargue una nómina de estudiantes
    desde un archivo Excel y la asigne a una doctora.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    tipo_nomina = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id = request.form.get('doctora', '').strip()
    excel_file = request.files.get('excel')

    if not all([tipo_nomina, nombre_especifico, doctora_id, excel_file]):
        flash('❌ Faltan campos obligatorios para cargar la nómina.', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    nomina_id = str(uuid.uuid4()) # ID único para esta nómina
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read() # Leer el contenido binario del archivo
    mime_type = mimetypes.guess_type(excel_filename)[0] or 'application/octet-stream'

    # 1. Subir el archivo Excel/CSV original a Supabase Storage
    try:
        # Almacenar en un bucket específico para nóminas médicas
        upload_path = f"nominas_medicas/{nomina_id}/{excel_filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al subir archivo Excel a Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo de la nómina.", 'error')
        return redirect(url_for('dashboard'))

    # 2. Insertar la entrada de la nómina en la tabla 'nominas_medicas'
    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina,
        "doctora_id": doctora_id,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename
    }
    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_HEADERS, # Se usa SUPABASE_HEADERS porque las RLS deben permitir insertar
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
        # Considerar limpiar el archivo de Storage si la inserción en DB falla
        return redirect(url_for('dashboard'))

    # 3. Leer y procesar el contenido del Excel/CSV para guardar estudiantes
    try:
        excel_data_io = io.BytesIO(excel_file_data)
        if excel_filename.lower().endswith(('.xlsx', '.xls')):
            # Usar pandas para leer Excel, es más robusto para diferentes formatos de fechas
            df = pd.read_excel(excel_data_io, engine='openpyxl')
        elif excel_filename.lower().endswith('.csv'):
            df = pd.read_csv(excel_data_io)
        else:
            raise ValueError("Formato de archivo no soportado para lectura (solo .xls, .xlsx, .csv).")

        estudiantes_a_insertar = []
        # Normalizar nombres de columnas a minúsculas y sin acentos para un acceso más fácil
        df.columns = [normalizar(col) for col in df.columns]

        for index, row in df.iterrows():
            # Buscar nombres de columnas comunes para los datos
            nombre = row.get('nombre') or row.get('nombres') or row.get('alumno')
            rut = row.get('rut')
            fecha_nac_excel = row.get('fecha_nacimiento') or row.get('fecha_nac')
            nacionalidad = row.get('nacionalidad')

            # Validar que los campos mínimos existen
            if not all([nombre, rut, fecha_nac_excel]):
                print(f"⚠️ Fila {index+2} incompleta en Excel, se omite: {row.to_dict()}")
                continue # Saltar esta fila y continuar con la siguiente

            try:
                # pandas suele convertir fechas automáticamente. Convertir a string YYYY-MM-DD para la BD
                fecha_nac_obj = pd.to_datetime(fecha_nac_excel).date()
                fecha_nac_str = fecha_nac_obj.isoformat() # Formato 'YYYY-MM-DD' estándar para bases de datos
                edad = calculate_age(fecha_nac_obj)
            except Exception as e:
                print(f"⚠️ Fila {index+2} con fecha inválida '{fecha_nac_excel}': {e}. Se omitirá esta entrada.")
                flash(f"⚠️ Atención: Fecha de nacimiento inválida en la fila {index+2} del Excel. Se omitirá esa entrada.", 'warning')
                continue # Saltar esta fila

            sexo = guess_gender(str(nombre).split()[0]) # Asegurarse que nombre es string antes de split

            estudiantes_a_insertar.append({
                "nomina_id": nomina_id,
                "nombre": str(nombre),
                "rut": str(rut),
                "fecha_nacimiento": fecha_nac_str,
                "edad": edad,
                "nacionalidad": str(nacionalidad) if nacionalidad else "Desconocida",
                "sexo": sexo
            })

        # Insertar todos los estudiantes en un solo lote (Supabase soporta esto con un array de objetos)
        if estudiantes_a_insertar:
            res_insert_estudiantes = requests.post(
                f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
                headers=SUPABASE_HEADERS,
                json=estudiantes_a_insertar
            )
            res_insert_estudiantes.raise_for_status()
            flash(f"✅ Nómina '{nombre_especifico}' cargada y {len(estudiantes_a_insertar)} estudiantes procesados exitosamente.", 'success')
        else:
            flash("⚠️ El archivo de la nómina no contiene estudiantes válidos para procesar.", 'warning')

    except Exception as e:
        print(f"❌ Error al procesar el archivo Excel o insertar estudiantes: {e}")
        flash('❌ Error al procesar el archivo de la nómina. Verifique que el formato de las columnas ("nombre", "rut", "fecha_nacimiento") sea correcto.', 'error')
        # Si la carga de estudiantes falla catastróficamente, podrías considerar eliminar la entrada de la nómina creada
        # requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
    
    return redirect(url_for('dashboard'))


@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    """
    Ruta para que la doctora suba formularios completados (PDF, Word, Excel)
    asociados a un establecimiento específico.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo') # Obtener todos los archivos seleccionados
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

            # Generar un ID único para cada archivo, para evitar colisiones de nombres
            unique_file_id = str(uuid.uuid4())

            # 📤 1. Subir archivo a Supabase Storage usando service_role
            # La ruta en Storage incluye el ID del establecimiento y un ID único para el archivo
            upload_path = f"formularios_completados/{establecimiento}/{unique_file_id}/{filename}"
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
            
            try:
                res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
                res_upload.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
                
                # 🌐 2. Construir URL pública del archivo
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"

                # 📝 3. Guardar metadatos en la tabla 'formularios_subidos'
                data = {
                    "doctoras_id": usuario_id,
                    "establecimientos_id": establecimiento, # ID del establecimiento asociado
                    "nombre_archivo": filename,
                    "url_archivo": url_publica
                }

                res_insert = requests.post(
                    f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                    headers=SUPABASE_HEADERS, # Se usa SUPABASE_HEADERS porque las RLS deben permitir insertar
                    json=data
                )
                res_insert.raise_for_status()
                mensajes.append(f'✔ "{filename}" subido correctamente y registrado.')
            except requests.exceptions.RequestException as e:
                # Capturar errores de red o HTTP (subida o inserción DB)
                error_detail = res_upload.text if 'res_upload' in locals() and res_upload.text else res_insert.text if 'res_insert' in locals() and res_insert.text else str(e)
                print(f"❌ Error al subir/registrar {filename}: {error_detail}")
                mensajes.append(f'✖ Error al subir "{filename}": {error_detail}')
            except Exception as e:
                # Capturar cualquier otro error inesperado
                print(f"❌ Error inesperado con {filename}: {e}")
                mensajes.append(f'✖ Error inesperado con "{filename}": {e}')
        else:
            mensajes.append(f'✖ "{archivo.filename}" (tipo de archivo no permitido)')
    
    # Unificar todos los mensajes de flash
    flash_type = 'success'
    if any('✖' in msg for msg in mensajes):
        flash_type = 'warning' if any('✔' in msg for msg in mensajes) else 'error'
    flash("<br>".join(mensajes), flash_type)
    
    return redirect(url_for('dashboard')) # Redirige al dashboard para ver el resultado


@app.route('/descargar/<nombre_archivo>')
def descargar_archivo(nombre_archivo):
    """
    Ruta para descargar archivos desde la carpeta 'static/formularios'.
    (Esta ruta es independiente de Supabase Storage).
    """
    # Si tus archivos se guardan directamente en el sistema de archivos local.
    # Asegúrate de que el archivo exista en 'static/formularios'.
    try:
        return send_from_directory('static/formularios', nombre_archivo, as_attachment=True)
    except FileNotFoundError:
        flash(f"❌ El archivo '{nombre_archivo}' no se encontró en el servidor.", 'error')
        return redirect(url_for('dashboard'))


@app.route('/admin/registrar_colegio', methods=['POST'])
def registrar_colegio():
    """
    Ruta para que el administrador registre un "colegio" (parece ser una entidad
    aparte de "establecimientos" en tu lógica original).
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    nuevo_id = str(uuid.uuid4())
    nombre = request.form.get('nombre')
    fecha = request.form.get('fecha')
    obs = request.form.get('obs', '')
    alumnos = request.form.get('alumnos')

    if not nombre or not fecha:
        flash("❌ Nombre y fecha son obligatorios para registrar un colegio.", 'error')
        return redirect(url_for('colegios'))

    data = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha_evaluacion": fecha,
        "observaciones": obs,
        "cantidad_alumnos": int(alumnos) if alumnos else None
    }

    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/colegios_registrados",
            headers=SUPABASE_HEADERS,
            json=data
        )
        res.raise_for_status()
        flash("✅ Colegio registrado correctamente.", 'success')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al registrar colegio: {e} - {res.text if 'res' in locals() else ''}")
        flash("❌ Error al registrar el colegio.", 'error')

    return redirect(url_for('colegios'))

@app.route('/colegios')
def colegios():
    """Muestra la lista de 'colegios registrados' (solo para admin)."""
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    colegios_data = []
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/colegios_registrados?select=*", headers=SUPABASE_HEADERS)
        res.raise_for_status()
        colegios_data = res.json()
        if isinstance(colegios_data, list):
            colegios_data.sort(key=lambda x: x.get('fecha_evaluacion') or '', reverse=True)
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener colegios registrados: {e}")
        flash('Error al cargar la lista de colegios registrados.', 'error')

    return render_template('colegios.html', colegios=colegios_data)

@app.route('/descargar_formulario/<establecimiento>/<nombre_archivo>')
def descargar_formulario(establecimiento, nombre_archivo):
    """
    Descarga un formulario base (subido por el admin para un establecimiento)
    directamente desde Supabase Storage.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # La ruta del archivo en Supabase Storage
    supabase_path = f"formularios/{establecimiento}/{nombre_archivo}"
    supabase_url = f"{SUPABASE_URL}/storage/v1/object/{supabase_path}"
    
    # Se usa SUPABASE_KEY (ANON KEY) porque los formularios base pueden ser de lectura pública
    # si las RLS del bucket 'formularios' lo permiten. Si no, necesitarías la SERVICE_KEY.
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    try:
        res = requests.get(supabase_url, headers=headers)
        res.raise_for_status() # Lanza excepción para errores HTTP

        mime_type = mimetypes.guess_type(nombre_archivo)[0] or 'application/octet-stream'
        return Response(
            res.content,
            mimetype=mime_type,
            headers={
                "Content-Disposition": f"attachment; filename={nombre_archivo}"
            }
        )
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al descargar archivo de Supabase Storage: {e} - {res.text if 'res' in locals() else ''}")
        flash(f"Error al descargar el archivo: {nombre_archivo}. Puede que no exista o no tenga permisos.", 'error')
        return redirect(url_for('dashboard'))


@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    """
    Ruta para que las doctoras registren la cantidad de alumnos evaluados
    en un establecimiento y se envíe una notificación por correo.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    cantidad = request.form.get('alumnos')
    usuario_nombre = session.get('usuario') # Obtener el nombre de usuario de la sesión

    # 🔍 Consultar el nombre del establecimiento por su ID (UUID)
    nombre_establecimiento = 'Establecimiento Desconocido'
    try:
        res_est = requests.get(
            f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento}&select=nombre",
            headers=SUPABASE_HEADERS
        )
        res_est.raise_for_status()
        if res_est.json():
            nombre_establecimiento = res_est.json()[0]['nombre']
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener nombre de establecimiento para notificación: {e}")
        # No flashear aquí, es una acción de background.

    # ✉️ Enviar correo con la información de los alumnos evaluados
    enviar_correo_sendgrid(
        asunto=f'Alumnos evaluados - {nombre_establecimiento}',
        cuerpo=f'Doctora: {usuario_nombre}\nEstablecimiento: {nombre_establecimiento}\nCantidad evaluada: {cantidad} alumnos.'
    )
    flash(f'✅ Se ha registrado la cantidad de {cantidad} alumnos evaluados para "{nombre_establecimiento}" y se ha enviado la notificación.', 'success')
    return redirect(url_for('dashboard')) # Redirigir al dashboard

# -------------------- MAIN --------------------
if __name__ == '__main__':
    # Esto se usa para ejecutar la app localmente. En Canvas, el entorno de la plataforma ya la ejecuta.
    # El puerto 8080 es común para desarrollo local, puedes cambiarlo si es necesario.
    app.run(debug=True, port=int(os.environ.get("PORT", 8080)))





