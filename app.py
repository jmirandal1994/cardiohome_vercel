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

    # DEBUG: Imprimir el nomina_id que llega a la función
    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")

    # 1. Obtener la información de la nómina específica (nombre, tipo, etc.)
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
        print(f"DEBUG: URL para obtener nómina: {url_nomina}")
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
        nomina_data = res_nomina.json()
        print(f"DEBUG: Datos de la nómina recibidos: {nomina_data}")

        if not nomina_data:
            flash("❌ Nómina no encontrada.", 'error')
            return redirect(url_for('dashboard'))

        nomina = nomina_data[0]
        session['establecimiento'] = f"{nomina['nombre_nomina']} ({nomina['tipo_nomina'].replace('_', ' ').title()})"
        session['current_nomina_id'] = nomina_id

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener datos de la nómina: {e}")
        print(f"Response text: {res_nomina.text if 'res_nomina' in locals() else 'No response'}")
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
        print(f"DEBUG: URL para obtener estudiantes: {url_estudiantes}")
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        print(f"DEBUG: Estudiantes raw recibidos: {estudiantes_raw}")


        for est in estudiantes_raw:
            # Asegurarse de que fecha_nacimiento es un objeto date para calculate_age
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
        print(f"DEBUG: Estudiantes procesados para plantilla: {estudiantes}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener estudiantes de la nómina: {e}")
        print(f"Response text: {res_estudiantes.text if 'res_estudiantes' in locals() else 'No response'}")
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
    print(f"DEBUG: Intento de login para usuario: {usuario}, URL: {url}")
    try:
        res = requests.get(url, headers=SUPABASE_HEADERS)
        res.raise_for_status() # Lanza una excepción para errores HTTP
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
    """Muestra el panel de control del usuario (admin o doctora)."""
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario = session['usuario']
    usuario_id = session.get('usuario_id')
    print(f"DEBUG: Accediendo a dashboard para usuario: {usuario}, ID: {usuario_id}")


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
        
        print(f"DEBUG: URL para obtener eventos: {url_eventos}")
        res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
        res_eventos.raise_for_status()
        eventos = res_eventos.json()
        print(f"DEBUG: Eventos recibidos: {eventos}")

        if isinstance(eventos, list):
            # Ordenar por horario si existe y es válido
            eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0] if e.get('horario') else '')
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener eventos: {e}")
        print(f"Response text: {res_eventos.text if 'res_eventos' in locals() else 'No response'}")
        flash('Error al cargar el calendario de visitas.', 'error')

    # --- Lógica para Formularios Subidos (General, por cualquier doctora) ---
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

    # --- Lógica para Nóminas Asignadas (Solo para Doctores) ---
    assigned_nominations = []
    if usuario != 'admin':
        try:
            url_nominas_asignadas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                f"?doctora_id=eq.{usuario_id}" # Filtra por el ID de la doctora logueada
                f"&select=id,nombre_nomina,tipo_nomina"
            )
            print(f"DEBUG: URL para obtener nóminas asignadas (doctor): {url_nominas_asignadas}")
            res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
            res_nominas_asignadas.raise_for_status()
            raw_nominas = res_nominas_asignadas.json()
            print(f"DEBUG: Nóminas raw recibidas para doctora: {raw_nominas}")


            for nom in raw_nominas:
                # Formatear el tipo de nómina para mostrarlo de forma legible
                display_name = nom['tipo_nomina'].replace('_', ' ').title()
                assigned_nominations.append({
                    'id': nom['id'],
                    'nombre_establecimiento': nom['nombre_nomina'], # Renombrado para consistencia en la plantilla
                    'tipo_nomina_display': display_name
                })
            print(f"DEBUG: Nóminas asignadas procesadas: {assigned_nominations}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas: {e}")
            print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
            flash('Error al cargar sus nóminas asignadas.', 'error')

    # --- Lógica específica para Admin (mostrar listas de doctoras y conteos) ---
    doctoras = []
    establecimientos_admin_list = [] # Una lista separada para el admin con todos los establecimientos
    conteo = {} # Conteo de formularios por establecimiento

    if usuario == 'admin':
        try:
            # Obtener lista completa de doctoras
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
            # Obtener todos los establecimientos (no solo los del admin logueado)
            url_establecimientos_admin = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id,nombre"
            print(f"DEBUG: URL para obtener establecimientos (admin): {url_establecimientos_admin}")
            res_establecimientos = requests.get(url_establecimientos_admin, headers=SUPABASE_HEADERS)
            res_establecimientos.raise_for_status()
            establecimientos_admin_list = res_establecimientos.json()
            print(f"DEBUG: Establecimientos recibidos (admin): {establecimientos_admin_list}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener establecimientos para conteo: {e}")
            print(f"Response text: {res_establecimientos.text if 'res_establecimientos' in locals() else 'No response'}")


        # Contar formularios subidos por establecimiento
        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1
        print(f"DEBUG: Conteo de formularios por establecimiento: {conteo}")


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

    print(f"DEBUG: admin_agregar - Datos recibidos: nombre={nombre}, fecha={fecha}, horario={horario}, doctora_id={doctora_id}, alumnos={cantidad_alumnos}, archivo_presente={bool(archivo)}")

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
        upload_path = f"formularios/{nuevo_id}/{filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo a Storage: {upload_url}")
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
        res_upload.raise_for_status() # Lanza excepción si la subida falla

        url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
        print(f"DEBUG: Archivo subido, URL pública: {url_publica}")
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
    print(f"DEBUG: Payload para insertar establecimiento: {data_establecimiento}")

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_HEADERS, # Se usa SUPABASE_HEADERS porque las RLS deben permitir insertar
            json=data_establecimiento
        )
        response_db.raise_for_status() # Lanza excepción si la inserción en DB falla
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

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id={doctora_id}, archivo_presente={bool(excel_file)}")

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

    # 2. Insertar la entrada de la nómina en la tabla 'nominas_medicas'
    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_especifico,
        "tipo_nomina": tipo_nomina,
        "doctora_id": doctora_id,
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename
    }
    print(f"DEBUG: Payload para insertar nómina en nominas_medicas: {data_nomina}")

    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_HEADERS, # Se usa SUPABASE_HEADERS porque las RLS deben permitir insertar
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (status): {res_insert_nomina.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (text): {res_insert_nomina.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
        # Considerar limpiar el archivo de Storage si la inserción en DB falla
        return redirect(url_for('dashboard'))

    # 3. Leer y procesar el contenido del Excel/CSV para guardar estudiantes
    try:
        excel_data_io = io.BytesIO(excel_file_data)
        if excel_filename.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(excel_data_io, engine='openpyxl')
        elif excel_filename.lower().endswith('.csv'):
            df = pd.read_csv(excel_data_io)
        else:
            raise ValueError("Formato de archivo no soportado para lectura (solo .xls, .xlsx, .csv).")

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


        # Insertar todos los estudiantes en un solo lote (Supabase soporta esto con un array de objetos)
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
    print(f"DEBUG: subir - Establecimiento ID: {establecimiento}, Cantidad de archivos: {len(archivos)}")

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
            upload_path = f"formularios_completados/{establecimiento}/{unique_file_id}/{filename}"
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
            print(f"DEBUG: Subiendo archivo completado a Storage: {upload_url}")
            
            try:
                res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data)
                res_upload.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
                
                # 🌐 2. Construir URL pública del archivo
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}"
                print(f"DEBUG: Archivo completado subido, URL pública: {url_publica}")

                # 📝 3. Guardar metadatos en la tabla 'formularios_subidos'
                data = {
                    "doctoras_id": usuario_id,
                    "establecimientos_id": establecimiento, # ID del establecimiento asociado
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
    
    # Después de procesar todos los archivos, usar flash para mostrar todos los mensajes
    for msg in mensajes:
        flash(msg, 'success' if '✅' in msg else 'error' if '❌' in msg else 'warning')

    return redirect(url_for('dashboard'))

# Nueva ruta para el admin para ver detalles de colegios evaluados (si existe en tu navbar)
@app.route('/colegios')
def colegios():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    
    # Aquí puedes añadir la lógica para cargar y mostrar datos relevantes a los colegios evaluados
    # Por ahora, solo renderiza una plantilla de ejemplo.
    return render_template('colegios.html') # Asegúrate de tener este archivo de plantilla

# Nueva ruta para que la doctora vea solo sus nóminas asignadas
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
            f"&select=id,nombre_nomina,tipo_nomina"
        )
        print(f"DEBUG: URL para mis_nominas: {url_nominas_asignadas}")
        res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_HEADERS)
        res_nominas_asignadas.raise_for_status()
        raw_nominas = res_nominas_asignadas.json()
        print(f"DEBUG: Nóminas recibidas para mis_nominas: {raw_nominas}")

        for nom in raw_nominas:
            display_name = nom['tipo_nomina'].replace('_', ' ').title()
            assigned_nominations.append({
                'id': nom['id'],
                'nombre_establecimiento': nom['nombre_nomina'],
                'tipo_nomina_display': display_name
            })
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener mis nóminas: {e}")
        print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
        flash('Error al cargar sus nóminas asignadas.', 'error')

    # Es importante renderizar una plantilla que muestre estas nóminas, por ejemplo, una versión simplificada
    # o reutilizando la sección de nóminas asignadas de dashboard.
    return render_template('mis_nominas.html', assigned_nominations=assigned_nominations) # Debes crear 'mis_nominas.html'

@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    alumnos_evaluados = request.form.get('alumnos')
    
    print(f"DEBUG: evaluados - Establecimiento ID: {establecimiento}, Alumnos evaluados: {alumnos_evaluados}")

    # Aquí debes actualizar la tabla 'establecimientos' para registrar la cantidad de alumnos evaluados
    # Suponiendo que hay una columna 'alumnos_evaluados' en tu tabla 'establecimientos'
    data_update = {
        "cantidad_alumnos_evaluados": int(alumnos_evaluados) if alumnos_evaluados else 0
    }

    try:
        response_db = requests.patch( # Usamos PATCH para actualizar un registro existente
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

    return redirect(url_for('dashboard')) # Redirige al dashboard o a la página específica del establecimiento si existe
