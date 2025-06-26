from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response, jsonify
import os
import requests
import base64
from werkzeug.utils import secure_filename
from datetime import datetime, date
from openpyxl import load_workbook # Necesario si se usa openpyxl directamente en algún lugar
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
# Se recomienda encarecidamente usar variables de entorno para esta clave.
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'} # Añadido 'csv' para las nóminas
PDF_BASE = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf' # Asegúrate de que este archivo exista en la carpeta 'static'

# -------------------- Supabase Configuration --------------------
# Estas variables deben ser inyectadas por el entorno de Vercel (o tu entorno de despliegue).
# Se incluyen valores por defecto para pruebas locales, pero NUNCA deben usarse en producción.
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImiYXRiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.i3ixl5ws3Z3QTxIcZNjI29ZknRmJwwQfUyLmX0Z0khc")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json" # Asegurarse de que acepte JSON
}
SUPABASE_SERVICE_HEADERS = { # Cabeceras para service_role (permisos elevados, ¡usar solo en el backend!)
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json" # Asegurarse de que acepte JSON
}

# Configuración de SendGrid (asegúrate de tener tus claves en las variables de entorno)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = os.getenv("SENDGRID_FROM_EMAIL", 'your_sendgrid_email@example.com') # ¡Cambia esto a tu correo verificado en SendGrid!
SENDGRID_TO = os.getenv("SENDGRID_ADMIN_EMAIL", 'destination_admin_email@example.com') # Correo al que se enviarán las notificaciones

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
    """Intenta adivinar el género basado en el nombre (heurística simple y con librería names si disponible)."""
    # Puedes ampliar estas listas o usar una librería más robusta si necesitas mayor precisión
    name_lower = name.lower().strip()
    
    # Intenta con la primera palabra para nombres compuestos
    first_word = name_lower.split(' ')[0]

    # Heurística simple para nombres en español
    nombres_masculinos = ["juan", "pedro", "luis", "carlos", "jose", "manuel", "alejandro", "ignacio", "felipe", "vicente", "emilio", "cristobal", "mauricio", "diego", "jean", "agustin", "joaquin", "thomas", "martin", "angel", "alonso"]
    nombres_femeninos = ["maria", "ana", "sofia", "laura", "paula", "trinidad", "mariana", "lizeth", "alexandra", "lisset"] 

    if first_word in nombres_masculinos:
        return 'M'
    elif first_word in nombres_femeninos:
        return 'F'
    
    # Si no se encuentra en las listas, intenta con la terminación (menos fiable)
    if name_lower.endswith(('o', 'n', 'r', 'l')):
        return 'M'
    if name_lower.endswith(('a', 'e')): # 'e' es ambiguo, pero puede ayudar
        return 'F'

    # Fallback general si no se puede inferir
    return "M" # Por defecto masculino si no hay pistas claras

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

    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {session.get('usuario_id')}")

    # 1. Obtener la información de la nómina específica (nombre, tipo, etc.)
    nomina_data = None
    try:
        url_nomina = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina"
        print(f"DEBUG: URL para obtener nómina en /relleno_formularios: {url_nomina}")
        res_nomina = requests.get(url_nomina, headers=SUPABASE_HEADERS)
        res_nomina.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
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
    total_forms_completed_for_nomina = 0
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
            
            # Contar formularios completados para esta nómina
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
                           establecimiento_nombre=nomina['nombre_nomina']) # Pasar el nombre del establecimiento aquí


@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    """
    Genera un archivo PDF rellenado con los datos del formulario.
    También persiste los datos del formulario en Supabase y actualiza 'fecha_relleno'.
    """
    if 'usuario' not in session:
        flash('Debes iniciar sesión para acceder a esta página.', 'danger')
        return redirect(url_for('index'))

    # Datos del formulario recibidos del POST
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    nombre = request.form.get('nombre')
    rut = request.form.get('rut')
    fecha_nac = request.form.get('fecha_nacimiento') # Viene ya formateado desde el HTML
    edad = request.form.get('edad')
    nacionalidad = request.form.get('nacionalidad')
    sexo = request.form.get('sexo') # Ahora viene del <select>
    estado_general = request.form.get('estado')
    diagnostico = request.form.get('diagnostico')
    plazo_reevaluacion_str = request.form.get('plazo') # El valor numérico del select
    fecha_reeval = request.form.get('fecha_reevaluacion')
    derivaciones = request.form.get('derivaciones')
    fecha_eval = datetime.today().strftime('%d/%m/%Y') # Fecha de la evaluación actual

    print(f"DEBUG: generar_pdf - Datos recibidos: nombre={nombre}, rut={rut}, sexo={sexo}, diagnostico={diagnostico}, fecha_reeval={fecha_reeval}")

    if not all([estudiante_id, nomina_id, nombre, rut, fecha_nac, edad, nacionalidad, sexo, estado_general, diagnostico, fecha_reeval, derivaciones]):
        flash('Faltan campos obligatorios en el formulario para guardar y generar PDF.', 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # 1. Persistir los datos del formulario en Supabase
    try:
        # Convertir fecha_reevaluacion a formato YYYY-MM-DD para Supabase si no lo está ya
        fecha_reevaluacion_db = fecha_reeval
        if fecha_reeval and "/" in fecha_reeval: # Si viene de la base de datos en DD/MM/YYYY
            try:
                fecha_reevaluacion_db = datetime.strptime(fecha_reeval, '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                pass # Si no es el formato esperado, se deja como está.

        # Data a actualizar en Supabase
        update_data = {
            'sexo': sexo,
            'estado_general': estado_general,
            'diagnostico': diagnostico,
            'fecha_reevaluacion': fecha_reevaluacion_db,
            'derivaciones': derivaciones,
            'fecha_relleno': str(date.today()) # Marcar la fecha actual de llenado
        }
        
        print(f"DEBUG: Datos a actualizar en Supabase para estudiante {estudiante_id}: {update_data}")
        response_db = requests.patch( # Usar PATCH para actualizar parcialmente
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
    # Reformatear fecha de reevaluación a DD/MM/YYYY si viene en formato YYYY-MM-DD (del date input HTML)
    if fecha_reeval and "-" in fecha_reeval:
        try:
            fecha_reeval_pdf = datetime.strptime(fecha_reeval, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            fecha_reeval_pdf = fecha_reeval # Si no es YYYY-MM-DD, se deja como está para el PDF
    else:
        fecha_reeval_pdf = fecha_reeval # Si ya viene en DD/MM/YYYY o es nulo

    ruta_pdf = os.path.join("static", "FORMULARIO.pdf")
    if not os.path.exists(ruta_pdf):
        flash("❌ Error: El archivo 'FORMULARIO.pdf' no se encontró en la carpeta 'static'.", 'error')
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
            "estado_general": estado_general,
            "fecha_evaluacion": fecha_eval,
            "fecha_reevaluacion": fecha_reeval_pdf,
            "derivaciones": derivaciones,
            "sexo_f": "X" if sexo == "F" else "", # Marcar casilla de sexo femenino
            "sexo_m": "X" if sexo == "M" else "", # Marcar casilla de sexo masculino
        }
        print(f"DEBUG: Fields to fill in PDF: {campos}")

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
        print(f"DEBUG: PDF generado y listo para descarga: {nombre_archivo_descarga}")
        flash('PDF generado correctamente.', 'success') # Muestra un flash message de éxito antes de la descarga
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formularios', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))


@app.route('/marcar_evaluado', methods=['POST'])
def marcar_evaluado():
    """
    Marca a un estudiante como evaluado, actualizando su fecha_relleno en Supabase.
    """
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401

    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    doctora_id = session.get('usuario_id') # Obtener el ID de la doctora de la sesión

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}")

    if not estudiante_id or not nomina_id or not doctora_id:
        return jsonify({"success": False, "message": "Datos de estudiante, nómina o doctora faltantes"}), 400

    try:
        update_data = {
            'fecha_relleno': str(date.today()), # Registrar la fecha actual
            'doctora_evaluadora_id': doctora_id # Opcional: Registrar qué doctora evaluó al alumno
        }
        
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_HEADERS, # Usar HEADERS normales para la API, RLS debe permitir PATCH por el usuario autenticado
            json=update_data
        )
        response.raise_for_status()
        
        if response.status_code == 200 or response.status_code == 204: # 200 OK or 204 No Content for successful PATCH
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
            session['usuario_id'] = data[0]['id'] # <-- ID de la doctora/admin que inicia sesión
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

    # --- Inicialización de variables para evitar UnboundLocalError ---
    doctoras = []
    establecimientos_admin_list = []
    admin_nominas_cargadas = []
    conteo = {} # Conteo de formularios subidos por establecimiento (para admin)
    evaluaciones_doctora = 0 # Conteo de evaluaciones para la doctora logueada

    # --- Lógica para Eventos/Establecimientos (Visitas Programadas) ---
    campos_establecimientos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo,doctora_id" # Added doctora_id
    eventos = []
    try:
        if usuario != 'admin':
            # Para doctores, solo sus eventos asignados
            url_eventos = (
                f"{SUPABASE_URL}/rest/v1/establecimientos"
                f"?doctora_id=eq.{usuario_id}" # Filtra por el ID de la doctora logueada
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
            
            # Contar evaluaciones para la doctora logueada
            # Se hace una consulta separada para mayor precisión y rendimiento si la tabla es grande
            url_evaluaciones_doctora = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?doctora_evaluadora_id=eq.{usuario_id}&fecha_relleno.not.is.null&select=count"
            print(f"DEBUG: URL para contar evaluaciones de doctora: {url_evaluaciones_doctora}")
            res_evaluaciones_doctora = requests.get(url_evaluaciones_doctora, headers=SUPABASE_HEADERS)
            res_evaluaciones_doctora.raise_for_status()
            # La cabecera Range-Unit content-range contiene el conteo total
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

    # --- Lógica específica del Administrador (mostrar listas de doctores y conteos) ---
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

        # Obtener nóminas cargadas por el admin (todas las nóminas)
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
        doctoras=doctoras, # Lista de doctoras para admin (ahora siempre inicializada)
        establecimientos=establecimientos_admin_list, # Lista de establecimientos para admin (ahora siempre inicializada)
        formularios=formularios, # Formularios subidos por las doctoras
        conteo=conteo,
        assigned_nominations=assigned_nominations, # Nóminas asignadas a la doctora logueada
        admin_nominas_cargadas=admin_nominas_cargadas, # ¡NUEVO! Nóminas cargadas por el admin (ahora siempre inicializada)
        evaluaciones_doctora=evaluaciones_doctora # Conteo de evaluaciones para la doctora logueada
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
    doctora_id_from_form = request.form.get('doctora', '').strip() # <-- Obtiene el ID seleccionado del formulario
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
    # mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream' # Not strictly needed for Storage upload

    # 1. Subir el archivo de formulario base a Supabase Storage
    try:
        upload_path = f"formularios/{nuevo_id}/{filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo a Storage: {upload_url}")
        res_upload = requests.post(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=file_data) # Use POST for first upload
        res_upload.raise_for_status() # Lanza excepción si la subida falla

        # The public URL needs to follow the bucket/path structure
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
    desde un archivo Excel o CSV y la asigne a una doctora.
    """
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    tipo_nomina = request.form.get('tipo_nomina')
    nombre_especifico = request.form.get('nombre_especifico')
    doctora_id_from_form = request.form.get('doctora', '').strip() # <-- Obtiene el ID seleccionado del formulario
    excel_file = request.files.get('excel')

    print(f"DEBUG: admin_cargar_nomina - Datos recibidos: tipo_nomina={tipo_nomina}, nombre_especifico={nombre_especifico}, doctora_id_from_form={doctora_id_from_form}, archivo_presente={bool(excel_file)}")

    if not all([tipo_nomina, nombre_especifico, doctora_id_from_form, excel_file]):
        flash('❌ Falta uno o más campos obligatorios para cargar la nómina (tipo, nombre, doctora, archivo).', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    nomina_id = str(uuid.uuid4()) # ID único para esta nómina
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read() # Leer contenido binario del archivo
    # mime_type = mimetypes.guess_type(excel_filename)[0] or 'application/octet-stream' # Not strictly needed for Storage

    # 1. Subir el archivo Excel/CSV original a Supabase Storage
    try:
        upload_path = f"nominas-medicas/{nomina_id}/{excel_filename}" 
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        print(f"DEBUG: Subiendo archivo Excel a Storage: {upload_url}")
        res_upload = requests.post(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" # Public URL is public/bucket/path
        print(f"DEBUG: Archivo Excel subido, URL pública: {url_excel_publica}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al subir archivo Excel a Storage: {e} - {res_upload.text if 'res_upload' in locals() else ''}")
        flash("❌ Error al subir el archivo de la nómina al almacenamiento. Por favor, inténtelo de nuevo.", 'error')
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
            headers=SUPABASE_HEADERS,
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (status): {res_insert_nomina.status_code}")
        print(f"DEBUG: Respuesta de Supabase al insertar nómina (text): {res_insert_nomina.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al guardar nómina en DB: {e} - {res_insert_nomina.text if 'res_insert_nomina' in locals() else ''}")
        flash("❌ Error al guardar los datos de la nómina en la base de datos.", 'error')
        # Considera limpiar el archivo de Storage si la inserción en DB falla
        return redirect(url_for('dashboard'))

    # 3. Leer y procesar el contenido del Excel/CSV para guardar estudiantes
    # Use io.BytesIO to read the file data from memory
    excel_data_stream = io.BytesIO(excel_file_data)
    
    # Check if the file is an Excel or CSV
    if excel_filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(excel_data_stream)
        print("DEBUG: Archivo leído como Excel.")
    elif excel_filename.endswith('.csv'):
        # Assuming UTF-8 encoding. You may need to adjust this.
        df = pd.read_csv(excel_data_stream, encoding='utf-8')
        print("DEBUG: Archivo leído como CSV.")
    else:
        # This case should be handled by 'permitido()' but it's good practice.
        flash('❌ Formato de archivo no soportado para la nómina.', 'error')
        return redirect(url_for('dashboard'))

    # Prepare data for insertion into 'estudiantes_nomina'
    estudiantes_a_insertar = []
    # Normalize column names to make them case-insensitive and handle accents
    df.columns = [normalizar(col) for col in df.columns]

    print(f"DEBUG: Columnas del archivo normalizadas: {df.columns}")

    # Map possible column names to their normalized versions
    column_mapping = {
        'nombre_completo': ['nombre_completo', 'nombre_y_apellido', 'nombre'],
        'rut': ['rut'],
        'fecha_nacimiento': ['fecha_nacimiento', 'fecha_de_nacimiento', 'fnac'],
        'nacionalidad': ['nacionalidad'],
        'comuna': ['comuna'],
        'direccion': ['direccion', 'dirección']
    }
    
    # Find the correct column names from the DataFrame
    # This loop is to make the code more robust against slight column name variations
    col_map = {}
    for key, possible_names in column_mapping.items():
        for name in possible_names:
            if name in df.columns:
                col_map[key] = name
                break
    
    # Log the found columns
    print(f"DEBUG: Mapeo de columnas encontrado: {col_map}")

    # Check if all critical columns are present
    if not all(k in col_map for k in ['nombre_completo', 'rut', 'fecha_nacimiento']):
        print(f"ERROR: No se encontraron columnas críticas. Columnas esperadas: {column_mapping.keys()}. Columnas encontradas: {df.columns.tolist()}")
        flash("❌ El archivo no contiene las columnas necesarias: 'Nombre', 'RUT', y 'Fecha de Nacimiento'.", 'error')
        # Rollback: delete the uploaded file and the nomina entry
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

            # Basic validation
            if not all([nombre_completo_raw, rut_raw, fecha_nacimiento_raw]):
                print(f"AVISO: Fila {index+2} ignorada por datos faltantes. Datos: {row.to_dict()}")
                continue
            
            # Format RUT without dots and hyphens
            rut_limpio = str(rut_raw).replace('.', '').replace('-', '').strip()
            
            # Convert date from Excel/CSV format to YYYY-MM-DD
            if isinstance(fecha_nacimiento_raw, datetime):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            elif isinstance(fecha_nacimiento_raw, date):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            else: # Try to parse from a string
                try:
                    fecha_nac_str = pd.to_datetime(fecha_nacimiento_raw, errors='coerce').strftime('%Y-%m-%d')
                except Exception as date_e:
                    print(f"AVISO: Error al parsear fecha de nacimiento en fila {index+2}: {fecha_nacimiento_raw} - {date_e}")
                    fecha_nac_str = None # Use None if parsing fails
            
            # Try to guess gender
            sexo_adivinado = guess_gender(str(nombre_completo_raw))

            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(), # Usar 'nombre' en vez de 'nombre_completo'
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, # Store as string
                "nacionalidad": str(row.get(col_map.get('nacionalidad'), 'Chilena')).strip(),
                "comuna": str(row.get(col_map.get('comuna'), 'No especificada')).strip(),
                "direccion": str(row.get(col_map.get('direccion'), 'No especificada')).strip(),
                "sexo": sexo_adivinado,
                "estado_general": None, # Se inicializan a None
                "diagnostico": None,
                "fecha_reevaluacion": None,
                "derivaciones": None,
                "fecha_relleno": None # Este campo se llenará cuando la doctora complete el formulario
            }
            estudiantes_a_insertar.append(estudiante)
            
        except Exception as e:
            print(f"❌ Error al procesar fila {index+2}: {e}")
            flash(f"Error al procesar la fila {index+2} del archivo. Verifique el formato de los datos.", 'error')
            # Rollback: delete the uploaded file and the nomina entry
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

    # 4. Insertar los estudiantes en la tabla 'estudiantes_nomina'
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
        # You might want to delete the nomina from nominas_medicas in case of error here too, for consistency.
        return redirect(url_for('dashboard'))

