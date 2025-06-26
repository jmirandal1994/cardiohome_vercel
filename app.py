from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response
import os
import requests
import base64
from werkzeug.utils import secure_filename
from datetime import datetime, date
from openpyxl import load_workbook # Asumo que aún la necesitas para alguna parte, si no, puedes quitarla
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject, NumberObject, DictionaryObject
import mimetypes
import io
import uuid
import json
import pandas as pd
import unicodedata
from dateutil.relativedelta import relativedelta # Importación necesaria para cálculo de fechas

app = Flask(__name__)
# ¡IMPORTANTE! Cambia esta clave por una cadena larga y aleatoria en producción.
app.secret_key = 'clave_super_segura_cardiohome_2025'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}
# Usar el nombre de archivo PDF base que el usuario confirmó que funciona
PDF_BASE = 'FORMULARIO.pdf' # ¡CORREGIDO! Vuelve a ser FORMULARIO.pdf

# -------------------- Supabase Configuration --------------------
# Estas variables serán inyectadas por el entorno de Canvas o tomadas de .env local
firebaseConfig = json.loads(os.getenv("FIREBASE_CONFIG", "{}")) 
SUPABASE_URL = os.getenv("SUPABASE_URL") or firebaseConfig.get("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or firebaseConfig.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or firebaseConfig.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NzU0MTc4NywiZXhwIjoyMDYzMTE3Nzg3fQ.i3ixl5ws3Z3QTxIcZNjI29ZknRmJwwQfUyLmX0Z0khc")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}
SUPABASE_SERVICE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}


# Configuración de SendGrid (asegúrate de tener tus claves en las variables de entorno)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'your_sendgrid_email@example.com' # ¡Cambia esto a tu correo verificado en SendGrid!
SENDGRID_TO = 'destination_admin_email@example.com' # Correo al que se enviarán las notificaciones

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
    name = str(name).lower().strip()
    # Nombres comunes femeninos que no terminan en 'a' pero son conocidos
    female_names = ['giselle', 'nicole', 'evelyn', 'loreto', 'carmen', 'margaret', 'ruth', 'izaskun']
    # Nombres comunes masculinos que terminan en 'a' pero son conocidos
    male_names = ['nicolas', 'mateo', 'andrea', 'patricio']

    first_word = name.split(' ')[0] # Considera solo la primera palabra del nombre

    if first_word in female_names:
        return "F"
    if first_word in male_names:
        return "M"

    # Heurística simple: nombres que terminan en 'a' suelen ser femeninos, el resto masculinos
    if first_word.endswith("a"):
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
    También obtiene el conteo de formularios ya completados para esta nómina por el usuario actual.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    usuario_id = session.get('usuario_id')
    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {usuario_id}")


    # 1. Obtener la información de la nómina específica (nombre, tipo, etc.)
    nomina = None
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

    # 2. Obtener los estudiantes asociados a esta nómina
    estudiantes = []
    try:
        url_estudiantes = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        print(f"DEBUG: URL para obtener estudiantes en /relleno_formularios: {url_estudiantes}")
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_HEADERS)
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        print(f"DEBUG: Estudiantes raw recibidos en /relleno_formularios: {estudiantes_raw}")


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

            # Auto-inferir sexo
            if 'nombre' in est and est['nombre']:
                est['sexo_inferido'] = guess_gender(est['nombre']) # Pasa el nombre completo a guess_gender
            else:
                est['sexo_inferido'] = 'M' # Default to Male if name is not available

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

    # 3. Obtener el conteo de formularios completados para esta nómina por el usuario actual
    total_forms_completed_for_nomina = 0
    if usuario_id and nomina_id:
        try:
            forms_completed_count_url = (
                f"{SUPABASE_URL}/rest/v1/formularios_subidos?select=id&"
                f"doctoras_id=eq.{usuario_id}&"
                f"establecimientos_id=eq.{nomina_id}" # establecimientos_id en esta tabla se usa para el nomina_id
            )
            res_forms_completed_count = requests.get(forms_completed_count_url, headers={
                **SUPABASE_HEADERS,
                "Prefer": "count=exact"
            })
            res_forms_completed_count.raise_for_status()

            if 'content-range' in res_forms_completed_count.headers:
                content_range = res_forms_completed_count.headers['content-range']
                total_forms_completed_for_nomina = int(content_range.split('/')[-1])
            else:
                total_forms_completed_for_nomina = len(res_forms_completed_count.json())
            print(f"DEBUG: Forms completed for current nomina ({nomina_id}) by doctor ({usuario_id}): {total_forms_completed_for_nomina}")

        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener el conteo de formularios completados: {e}")
            print(f"Response text: {res_forms_completed_count.text if 'res_forms_completed_count' in locals() else 'No response'}")
            total_forms_completed_for_nomina = 0
        except Exception as e:
            print(f"❌ Error inesperado al obtener el conteo de formularios: {e}")
            total_forms_completed_for_nomina = 0


    return render_template('formulario_relleno.html', estudiantes=estudiantes, total_forms_completed_for_nomina=total_forms_completed_for_nomina)


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    """
    Genera un archivo PDF rellenado con los datos del formulario,
    lo sube a Supabase Storage y registra la finalización en formularios_subidos.
    """
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # Datos del formulario recibidos del POST
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento')
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo')
    estado = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    
    # Campo para la reevaluación en años
    reeval_anos_str = request.form.get('fecha_reevaluacion_anos')
    derivaciones = request.form.get('derivaciones') # Reincorporado
    
    fecha_eval_dt = datetime.now() # Fecha de evaluación actual
    fecha_eval_formatted = fecha_eval_dt.strftime('%d/%m/%Y')

    # Calcular fecha de reevaluación basada en los años seleccionados
    fecha_reeval_formatted = ""
    try:
        # El valor del select es un número entero ("1", "2", etc.)
        reeval_cantidad_anos = int(reeval_anos_str) 
        if reeval_cantidad_anos > 0:
            future_date = fecha_eval_dt + relativedelta(years=reeval_cantidad_anos)
            fecha_reeval_formatted = future_date.strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        print(f"DEBUG: Valor no válido para años de reevaluación: '{reeval_anos_str}'. Estableciendo a 'N/A'.")
        fecha_reeval_formatted = "N/A" # Manejar si el input es inválido o no se seleccionó

    # IDs para registro en Supabase
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = session.get('current_nomina_id') # Obtener de sesión, más seguro
    doctora_id = session.get('usuario_id')

    # Añadir más DEBUG prints para los IDs antes de construir la URL de subida
    print(f"DEBUG: Valores para Supabase upload: estudiante_id='{estudiante_id}', nomina_id='{nomina_id}', doctora_id='{doctora_id}'")
    print(f"DEBUG: Datos de formulario para PDF: nombre='{nombre}', rut='{rut}', fecha_nac='{fecha_nac}', edad='{edad}', sexo='{sexo}', diagnostico='{diagnostico}', fecha_reeval_formatted='{fecha_reeval_formatted}', derivaciones='{derivaciones}'")


    if not all([estudiante_id, nomina_id, doctora_id, nombre, rut, fecha_nac]):
        flash("❌ Error: Faltan datos esenciales para generar y guardar el formulario. Asegúrate de que todos los campos del estudiante están cargados.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


    # Ruta al archivo PDF base (debe estar en la carpeta 'static')
    ruta_pdf_base = os.path.join("static", PDF_BASE)
    if not os.path.exists(ruta_pdf_base):
        flash(f"❌ Error: El archivo base '{PDF_BASE}' no se encontró en la carpeta 'static'.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    output_buffer = io.BytesIO() # Buffer para el PDF generado en memoria
    nombre_archivo_generado = f"Formulario_{normalizar(nombre)}_{normalizar(rut)}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"

    try:
        reader = PdfReader(ruta_pdf_base)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        campos = {
            "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac,
            "nacionalidad": nacionalidad, "edad": edad, 
            "diagnostico_1": diagnostico, # Ahora del desplegable
            "diagnostico_2": diagnostico, # Si tienes un campo secundario para el mismo diagnóstico
            "estado_general": estado,
            "fecha_evaluacion": fecha_eval_formatted,
            "fecha_reevaluacion": fecha_reeval_formatted, # Fecha calculada y formateada
            "derivaciones": derivaciones, # Campo derivaciones
            "sexo_f": "X" if sexo == "F" else "",
            "sexo_m": "X" if sexo == "M" else "",
        }
        writer.update_page_form_field_values(writer.pages[0], campos)
        writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})

        writer.write(output_buffer)
        output_buffer.seek(0) # Reset buffer position for reading/uploading

        # 📤 1. Subir el PDF generado a Supabase Storage
        unique_file_uuid = str(uuid.uuid4())
        upload_path_corrected = f"formularios_completados_estudiantes/{nomina_id}/{estudiante_id}/{unique_file_uuid}_{nombre_archivo_generado}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path_corrected}"
        
        # Headers específicos para la subida de archivos (Content-Type y x-upsert)
        upload_headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/pdf", # ¡CRÍTICO! Especificar el tipo de contenido del archivo.
            "x-upsert": "true" # Sobrescribir si el archivo ya existe (opcional, pero útil)
        }

        print(f"DEBUG: Iniciando subida de PDF a Supabase Storage.")
        print(f"DEBUG: URL de subida: {upload_url}")
        # Truncar la clave de autorización para no mostrarla completa en los logs
        auth_header_for_log = f"Bearer {SUPABASE_SERVICE_KEY[:10]}..." if SUPABASE_SERVICE_KEY else "No Key"
        print(f"DEBUG: Encabezados de subida (Autorización truncada): {{'apikey': '...', 'Authorization': '{auth_header_for_log}', 'Content-Type': 'application/pdf', 'x-upsert': 'true'}}") 
        print(f"DEBUG: Tamaño de los datos del PDF a subir: {len(output_buffer.getvalue())} bytes")

        try:
            res_upload = requests.put(upload_url, headers=upload_headers, data=output_buffer.getvalue())
            # *** Add more detailed logging here BEFORE raise_for_status() ***
            print(f"DEBUG: Raw response status from Supabase Storage: {res_upload.status_code}")
            print(f"DEBUG: Raw response headers from Supabase Storage: {res_upload.headers}")
            print(f"DEBUG: Raw response text from Supabase Storage: {res_upload.text[:500]}..." if res_upload.text else "No response body (raw text)") # Print first 500 chars, handle empty text

            res_upload.raise_for_status() # Esto levantará una excepción HTTPError si el status code es 4xx o 5xx
            print(f"DEBUG: Subida a Supabase Storage exitosa. Código de estado: {res_upload.status_code}")

            url_publica_generado = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path_corrected}"
            print(f"DEBUG: PDF generado y subido, URL pública: {url_publica_generado}")

            # 📝 2. Registrar en la tabla 'formularios_subidos'
            data_registro_formulario = {
                "doctoras_id": doctora_id,
                "establecimientos_id": nomina_id, # Usamos nomina_id aquí para el conteo de rendimiento
                "nombre_archivo": nombre_archivo_generado,
                "url_archivo": url_publica_generado
            }
            print(f"DEBUG: Payload para registrar formulario en formularios_subidos: {data_registro_formulario}")

            res_insert_registro = requests.post(
                f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                headers=SUPABASE_HEADERS,
                json=data_registro_formulario
            )
            res_insert_registro.raise_for_status()
            print(f"DEBUG: Registro en formularios_subidos (status): {res_insert_registro.status_code}")
            print(f"DEBUG: Registro en formularios_subidos (text): {res_insert_registro.text}")

            flash(f"✅ Formulario de {nombre} guardado y generado exitosamente.", 'success')

            # Devolver el PDF para descarga al usuario
            output_buffer.seek(0)
            return send_file(output_buffer, as_attachment=True, download_name=nombre_archivo_generado, mimetype='application/pdf')

        except requests.exceptions.RequestException as e:
            error_msg = f"❌ Error al interactuar con Supabase (generar_pdf): {e}. Detalle: "
            if e.response:
                error_msg += f"Response Status: {e.response.status_code} | Response Headers: {e.response.headers} | Response Body: {e.response.text[:500]}..."
            else:
                error_msg += "No response object available in exception."
            print(error_msg)
            flash(error_msg, 'error')
        except Exception as e:
            error_msg = f"❌ Error inesperado al generar o guardar el PDF: {e}"
            print(error_msg)
            flash(error_msg, 'error')

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
        res.raise_for_status()
        data = res.json()
        print(f"DEBUG: Respuesta Supabase login: {data}")
        if data:
            session['usuario'] = usuario
            session['usuario_id'] = data[0]['id']
            print(f"DEBUG: Sesión iniciada: usuario={session['usuario']}, usuario_id={session['usuario_id']}")
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

    doctoras = []
    establecimientos_admin_list = []
    admin_nominas_cargadas = []
    conteo = {}
    my_forms_completed_count = 0 # Inicializar para doctores normales

    # --- Lógica para Eventos/Establecimientos (Visitas Programadas) ---
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

    # --- Lógica para Formularios Subidos (General, por cualquier doctora) ---
    formularios = []
    try:
        url_formularios_subidos = f"{SUPABASE_URL}/rest/v1/formularios_subidos"
        print(f"DEBUG: URL para obtener formularios subidos: {url_formularios_subidos}")
        res_formularios = requests.get(url_formularios_subidos, headers=SUPABASE_HEADERS)
        res_formularios.raise_for_status()
        formularios = res_formularios.json()
        print(f"DEBUG: Formularios subidos recibidos: {formularios}")

        if usuario != 'admin':
            # Conteo de formularios completados por el usuario logueado (doctora)
            my_forms_completed_count = len([f for f in formularios if f.get('doctoras_id') == usuario_id])
            print(f"DEBUG: Formularios completados por {usuario}: {my_forms_completed_count}")

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
        except requests.exceptions.RequestException as e:
            print(f"❌ Error al obtener nóminas asignadas: {e}")
            print(f"Response text: {res_nominas_asignadas.text if 'res_nominas_asignadas' in locals() else 'No response'}")
            flash('Error al cargar sus nóminas asignadas.', 'error')

    # --- Lógica específica del Administrador (mostrar listas de doctores y conteos de rendimiento) ---
    doctor_performance_data = [] # Siempre inicializar aquí
    if usuario == 'admin':
        try:
            url_doctoras = f"{SUPABASE_URL}/rest/v1/doctoras"
            print(f"DEBUG: URL para obtener doctoras (admin): {url_doctoras}")
            res_doctoras = requests.get(url_doctoras, headers=SUPABASE_HEADERS)
            res_doctoras.raise_for_status()
            doctoras = res_doctoras.json()
            print(f"DEBUG: Doctoras recibidas (admin): {doctoras}")

            # Calcular el rendimiento de cada doctora
            if doctoras and formularios:
                for doc in doctoras:
                    forms_by_doc = [f for f in formularios if f.get('doctoras_id') == doc['id']]
                    doctor_performance_data.append({
                        'doctor_name': doc['usuario'],
                        'completed_forms_count': len(forms_by_doc)
                    })
            print(f"DEBUG: Datos de rendimiento por doctora (admin): {doctor_performance_data}")

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
        doctoras=doctoras,
        establecimientos=establecimientos_admin_list,
        formularios=formularios,
        conteo=conteo,
        assigned_nominations=assigned_nominations,
        admin_nominas_cargadas=admin_nominas_cargadas,
        my_forms_completed_count=my_forms_completed_count,
        doctor_performance_data=doctor_performance_data
    )

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.clear()
    # flash('Has cerrado sesión correctamente.', 'info') # Eliminado para evitar mensajes inesperados
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
    doctora_id_from_form = request.form.get('doctora', '').strip()
    cantidad_alumnos = request.form.get('alumnos')
    archivo = request.files.get('formulario') # Archivo PDF o DOCX base

    print(f"DEBUG: admin_agregar - Datos recibidos: nombre={nombre}, fecha={fecha}, horario={horario}, doctora_id_from_form={doctora_id_from_form}, alumnos={cantidad_alumnos}, archivo_presente={bool(archivo)}")

    if not all([nombre, fecha, horario, doctora_id_from_form]):
        flash("❌ Faltan campos obligatorios para el establecimiento.", 'error')
        return redirect(url_for('dashboard'))

    if not archivo or not permitido(archivo.filename):
        flash("❌ Archivo de formulario base no válido o no seleccionado.", 'error')
        return redirect(url_for('dashboard'))

    nuevo_id = str(uuid.uuid4()) # ID único para el establecimiento
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    # 1. Subir el archivo de formulario base a Supabase Storage
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
        "doctora_id": doctora_id_from_form, # <-- Usa el ID del formulario
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None,
        "url_archivo": url_publica,
        "nombre_archivo": filename
    }
    print(f"DEBUG: Payload para insertar establecimiento: {data_establecimiento}")

    try:
        response_db = requests.post(
            f"{SUPABASE_URL}/rest/v1/establecimientos",
            headers=SUPABASE_HEADERS, # Se usan SUPABASE_HEADERS porque RLS debe permitir la inserción
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
    Ruta para que el **administrador** suba una lista de estudiantes
    desde un archivo Excel y la asigne a una doctora.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    tipo_nomina = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id_from_form = request.form.get('doctora', '').strip()
    excel_file = request.files.get('excel')

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}")

    if not all([tipo_nomina, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Faltan campos obligatorios para cargar la nómina.', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    nomina_id = str(uuid.uuid4()) # ID único para esta nómina
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read() # Leer contenido binario del archivo
    mime_type = mimetypes.guess_type(excel_filename)[0] or 'application/octet-stream'

    # 1. Subir el archivo Excel/CSV original a Supabase Storage
    try:
        # Usar el nombre de bucket 'nominas-medicas' (con guion medio)
        upload_path = f"nominas-medicas/{nomina_id}/{excel_filename}" 
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo Excel a Storage: {upload_url}")
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/nominas-medicas/{upload_path}" 
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
        "doctora_id": doctora_id_from_form, # <-- Usa el ID del formulario
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename
    }
    print(f"DEBUG: Payload para insertar nómina en nominas_medicas: {data_nomina}")

    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_HEADERS, # Se usan SUPABASE_HEADERS porque RLS debe permitir la inserción
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (status): {res_insert_nomina.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (text): {res_insert_nomina.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
        return redirect(url_for('dashboard'))

    # 3. Procesar el archivo Excel/CSV y subir los estudiantes a 'estudiantes_nomina'
    try:
        excel_data_io = io.BytesIO(excel_file_data)
        if excel_filename.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(excel_data_io, engine='openpyxl')
        elif excel_filename.lower().endswith('.csv'):
            df = pd.read_csv(excel_data_io)
        else:
            raise ValueError("Formato de archivo no soportado para lectura (solo .xls, .xlsx, .csv).")

        estudiantes_a_insertar = []
        # Normalizar los nombres de las columnas para asegurar coincidencia
        df.columns = [normalizar(col) for col in df.columns]
        print(f"DEBUG: Columnas del Excel normalizadas: {df.columns.tolist()}")

        for index, row in df.iterrows():
            # Intentar obtener los datos con nombres de columna comunes
            nombre = row.get('nombre') or row.get('nombres') or row.get('alumno')
            rut = row.get('rut')
            fecha_nac_excel = row.get('fecha_nacimiento') or row.get('fecha_nac')
            nacionalidad = row.get('nacionalidad')

            if not all([nombre, rut, fecha_nac_excel]):
                print(f"⚠️ Fila {index+2} incompleta en Excel, se omite: {row.to_dict()}")
                continue

            try:
                # Convertir la fecha de nacimiento a formato ISO (YYYY-MM-DD)
                fecha_nac_obj = pd.to_datetime(fecha_nac_excel).date()
                fecha_nac_str = fecha_nac_obj.isoformat()
                edad = calculate_age(fecha_nac_obj)
            except Exception as e:
                print(f"⚠️ Fila {index+2} con fecha inválida '{fecha_nac_excel}': {e}. Se omitirá esta entrada.")
                flash(f"⚠️ Atención: Fecha de nacimiento inválida en la fila {index+2} del Excel. Se omitirá esa entrada.", 'warning')
                continue

            sexo = guess_gender(str(nombre).split()[0]) # Usar la función de inferencia

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
        
    return redirect(url_for('dashboard'))


@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    """
    Ruta para que la doctora suba formularios completados (PDF, Word, Excel)
    asociados a un establecimiento específico. Esta ruta es para subida manual
    de archivos, diferente a la generación automática de PDF en /generar_pdf.
    """
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

            upload_path = f"formularios_subidos_manual/{establecimiento}/{unique_file_id}/{filename}"
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
            
            print(f"DEBUG: Subiendo archivo completado manualmente a Storage: {upload_url}")
            
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
                print(f"DEBUG: Payload para insertar formulario subido manualmente en DB: {data}")

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
            f"&select=id,nombre_nomina,tipo_nomina,doctora_id"
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

    return redirect(url_for('dashboard'))
