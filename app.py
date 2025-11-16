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
import secrets
# Las importaciones específicas para Google Drive API han sido eliminadas.


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}

# Define los PDFs base para cada tipo de formulario
# Asegúrate de que estos archivos PDF existan en la misma carpeta que app.py
PDF_BASE_NEUROLOGIA = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_BASE_FAMILIAR = 'formulario_familiar.pdf' 

# Nuevo: Directorio para los PDFs de neurología específicos por doctora
# Asegúrate de que esta carpeta exista en la misma ubicación que app.py
PDF_BASES_NEUROLOGIA_DIR = 'pdf_bases_doctoras_neurologia'


# -------------------- Supabase Configuration --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IlNJUDU4IiwicmVmIjoiYnhzbnFmZml4d2pkcWl2eGJrZXkiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzE5Mjg3MzI1LCJleHAiOjE3NTA4MjMzMjV9.qNlSg_p4_u1O5xQ9s6bNN0K2Z0f0v_N9s8k0k0k0k0k") # ASEGÚRATE DE USAR TU SERVICE_KEY REAL

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


# -------------------- Utilidades --------------------
def format_rut_python(rut):
    """
    Formatea un RUT chileno (ej: 12345678-9) a un formato con puntos y guion (ej: 12.345.678-9).
    Acepta RUTs con o sin puntos y guiones.
    """
    if not rut:
        return ""
    
    # Asegurarse de que el RUT sea una cadena y limpiar puntos y guiones existentes
    rut = str(rut).replace('.', '').replace('-', '').strip().upper() 

    if not rut:
        return ""

    # Separar cuerpo y dígito verificador
    body = rut[:-1]
    dv = rut[-1]

    # Formatear el cuerpo con puntos
    formatted_body = ""
    for i, digit in enumerate(reversed(body)):
        if i > 0 and i % 3 == 0:
            formatted_body = "." + formatted_body
        formatted_body = digit + formatted_body

    return f"{formatted_body}-{dv}"


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

# app-30.py (Función generate_and_upload_pdf corregida)

# Asegúrate de que 'os' y 'requests' estén importados al inicio de app-30.py
# import os
# import requests
# ...
# import io
# from PyPDF2 import PdfReader, PdfWriter
# ...

# app-30.py (Función auxiliar generate_and_upload_pdf COMPLETA)

def generate_and_upload_pdf(estudiante_id, nomina_id, doctora_id, form_type, datos_actualizacion):
    """Genera el PDF rellenado y lo sube al almacenamiento de Supabase.
       Incluye lógica para seleccionar plantilla específica por doctora.
    """
    
    # ---------------------------------------------------------------------
    # 1. OBTENCIÓN DEL ID PARA EL FORMULARIO (CORRECCIÓN CLAVE)
    # ---------------------------------------------------------------------
    pdf_template_path = None
    
    # Usamos el ID de la Doctora LOGUEADA como la clave para la plantilla.
    # El ID de la sesión es la única fuente de verdad fiable en este punto.
    current_doctora_id = session.get('usuario_id')
    
    if form_type == 'neurologia' and current_doctora_id:

        # 1.1. Definir la ruta del formulario específico usando el ID LOGUEADO
        doctora_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{current_doctora_id}.pdf"
        # La carpeta donde deben estar tus archivos personalizados
        doctora_pdf_path = os.path.join(PDF_BASES_NEUROLOGIA_DIR, doctora_pdf_filename)

        # 1.2. Comprobar si existe el archivo PDF específico
        if os.path.exists(doctora_pdf_path):
            pdf_template_path = doctora_pdf_path
            print(f"DEBUG: Usando PDF específico de Doctora LOGUEADA: {pdf_template_path}")
        else:
            # Fallback: Si no existe el archivo específico, usar el genérico
            pdf_template_path = PDF_BASE_NEUROLOGIA
            print(f"DEBUG: Usando PDF genérico de Neurología.")
            
    elif form_type == 'medicina_familiar':
        pdf_template_path = PDF_BASE_FAMILIAR
    
    if not pdf_template_path or not os.path.exists(pdf_template_path):
        message = f"ERROR: Plantilla PDF no encontrada para el tipo de formulario '{form_type}' en la ruta: {pdf_template_path}"
        print(message)
        return {"success": False, "message": message}

    # ---------------------------------------------------------------------
    # 2. CONTINUACIÓN DE LA GENERACIÓN Y RELLENO DEL PDF
    # ---------------------------------------------------------------------
    try:
        # 2.1. Recuperar información completa del estudiante (ya que update_data solo tiene lo nuevo)
        url_estudiante_completo = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?id=eq.{estudiante_id}"
            f"&select=nombre,rut,fecha_nacimiento,edad,nacionalidad,sexo,estado_general,diagnostico,derivaciones,fecha_evaluacion,fecha_reevaluacion"
        )
        res_est = requests.get(url_estudiante_completo, headers=SUPABASE_SERVICE_HEADERS)
        estudiante_data = res_est.json()[0] if res_est.ok and res_est.json() else {}

        # 2.2. Recuperar información de la Doctora (Firma)
        url_doctora = f"{SUPABASE_URL}/rest/v1/doctoras?id=eq.{doctora_id}&select=nombre"
        res_doc = requests.get(url_doctora, headers=SUPABASE_SERVICE_HEADERS)
        doctora_nombre = res_doc.json()[0]['nombre'] if res_doc.ok and res_doc.json() else 'Doctora Asignada'
        
        # --- MAPEO DE CAMPOS (ADAPTAR ESTO A TU FORMATO PDF REAL) ---
        campos_pdf = {} 
        # Campos comunes
        campos_pdf['NOMBRE_ESTUDIANTE'] = estudiante_data.get('nombre', '')
        campos_pdf['RUT'] = estudiante_data.get('rut', '')
        campos_pdf['FECHA_EVALUACION'] = estudiante_data.get('fecha_evaluacion', '')
        campos_pdf['FECHA_REVALUACION'] = estudiante_data.get('fecha_reevaluacion', '')
        campos_pdf['DOCTORA_NOMBRE'] = doctora_nombre
        # Si form_type es neurologia (solo un ejemplo)
        if form_type == 'neurologia':
            campos_pdf['ESTADO_GENERAL'] = estudiante_data.get('estado_general', '')
            campos_pdf['DIAGNOSTICO'] = estudiante_data.get('diagnostico', '')
            campos_pdf['DERIVACIONES'] = estudiante_data.get('derivaciones', '')
        # Si form_type es medicina_familiar (solo un ejemplo)
        elif form_type == 'medicina_familiar':
            # Aquí iría el mapeo de todos los campos específicos de medicina familiar
            pass
        # --------------------------------------------------------------
        
        # 2.3. Rellenar PDF
        # Nota: Asegúrate de que PdfReader y PdfWriter estén importados
        with open(pdf_template_path, 'rb') as file:
            reader = PdfReader(file)
            writer = PdfWriter()
            page = reader.pages[0]
            writer.add_page(page)

            # Rellenar los campos
            if reader.get_form_text_fields():
                writer.update_page_form_field_values(writer.pages[0], campos_pdf)
                print(f"DEBUG: Campos PDF rellenados: {list(campos_pdf.keys())}")
            else:
                print("ADVERTENCIA: No se encontraron campos de formulario en el PDF.")

            # Crear un buffer en memoria para el PDF
            output_buffer = io.BytesIO()
            writer.write(output_buffer)
            output_buffer.seek(0)
            
            # 2.4. Subir a Supabase Storage
            rut_estudiante = estudiante_data.get('rut', 'SinRut')
            # Usamos UUID para asegurar unicidad del archivo
            unique_id = str(uuid.uuid4())
            filename = f"Evaluacion_{form_type}_{rut_estudiante}_{unique_id}.pdf"
            
            # Ruta de Storage: formularios_completados/nomina_id/nombre_archivo.pdf
            supabase_path = f"formularios_completados/{nomina_id}/{filename}"
            supabase_url = f"{SUPABASE_URL}/storage/v1/object/formularios_completados/{nomina_id}/{filename}"
            
            # Usar requests.put para subir el archivo
            upload_res = requests.put(
                supabase_url,
                data=output_buffer.getvalue(),
                headers={
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", # Usar SERVICE KEY para Storage
                    "Content-Type": "application/pdf",
                    "x-upsert": "true" 
                }
            )
            upload_res.raise_for_status()
            print(f"DEBUG: PDF subido con éxito a: {supabase_path}")
            
            return {"success": True, "path": supabase_path}

    except requests.exceptions.RequestException as e:
        message = f"Error de conexión al generar/subir PDF: {str(e)}"
        print(f"❌ ERROR: {message}")
        if 'upload_res' in locals() and upload_res.text:
             print(f"ERROR DETAIL: {upload_res.text}")
        return {"success": False, "message": message}
    except Exception as e:
        message = f"Error inesperado al generar/subir PDF: {str(e)}"
        print(f"❌ ERROR: {message}")
        return {"success": False, "message": message}
        
# Helper function to get form field values, converting None to empty string
def get_form_field_value(field_name, form_data, return_none_if_empty=False):
    """
    Retrieves a form field value from form_data.
    If return_none_if_empty is True, returns None for empty strings.
    Otherwise, returns an empty string for empty values.
    """
    value = form_data.get(field_name)
    if value is None:
        return None # If field is not present in form data at all
    
    stripped_value = value.strip()
    if not stripped_value: # If it's an empty string after stripping
        return None if return_none_if_empty else '' # Return None for dates/numeric, empty string for text/select
    return stripped_value


# Nuevo: Función para obtener el PDF de neurología específico para una doctora
def get_doctor_specific_neurologia_pdf(doctora_id):
    """
    Intenta encontrar un PDF de neurología específico para la doctora en el directorio configurado.
    Si no lo encuentra, retorna el PDF de neurología por defecto.
    """
    # Construir la ruta completa al directorio de bases de PDF
    base_dir = os.path.dirname(os.path.abspath(__file__)) # Obtiene el directorio del script actual
    full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)

    # Corregido: Asume que los PDFs están nombrados como 'FORMULARIO TIPO NEUROLOGIA_{doctora_id}.pdf'
    specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{doctora_id}.pdf"
    specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)

    print(f"DEBUG: Buscando PDF en la ruta absoluta: {specific_pdf_path}") # Añadido para depuración

    if os.path.exists(specific_pdf_path):
        print(f"DEBUG: Se encontró PDF específico para doctora {doctora_id}: {specific_pdf_path}")
        return specific_pdf_path
    else:
        print(f"ADVERTENCIA: No se encontró PDF específico para doctora {doctora_id} en {specific_pdf_path}. Usando PDF por defecto: {PDF_BASE_NEUROLOGIA}")
        # Fallback al PDF por defecto, asegurando que su ruta también sea absoluta para claridad
        default_pdf_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
        print(f"DEBUG: Usando PDF por defecto en la ruta absoluta: {default_pdf_path}")
        return default_pdf_path


# -------------------- Rutas de la Aplicación --------------------

# app-30.py (Reemplaza la función relleno_formulario completa)
@app.route('/relleno_formulario/<string:nomina_id>', methods=['GET'])
def relleno_formulario(nomina_id):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    user_role = session.get('usuario')
    user_id = session.get('usuario_id')
    
    # --- CORRECCIÓN CLAVE ---
    # Guardamos el ID de la nómina en la sesión para que esté disponible en otras rutas (como /marcar_evaluado)
    session['current_nomina_id'] = nomina_id 
    # ------------------------

    # 1. Obtener detalles de la nómina
    url_nomina = (
        f"{SUPABASE_URL}/rest/v1/nominas_medicas"
        f"?id=eq.{nomina_id}"
        f"&select=form_type,doctora_id,nombre_nomina"
    )
    
    try:
        res_nomina = requests.get(url_nomina, headers=SUPABASE_SERVICE_HEADERS) 
        res_nomina.raise_for_status()
        nomina_data = res_nomina.json()
        
        if not nomina_data:
            flash(f'Error: Nómina con ID {nomina_id} no encontrada.', 'error')
            return redirect(url_for('dashboard'))
        
        nomina = nomina_data[0]
        form_type = nomina['form_type']
        
        # Validación de acceso: Solo el Admin o la Doctora Asignada pueden acceder
        if user_role == 'doctora' and nomina['doctora_id'] != user_id:
            flash('Acceso no autorizado a esta nómina.', 'error')
            return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR al obtener detalles de la nómina {nomina_id}: {e}")
        flash('Error al cargar la nómina.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ ERROR Inesperado al procesar detalles de la nómina: {e}")
        flash('Error interno del servidor.', 'error')
        return redirect(url_for('dashboard'))

    # 2. Obtener la lista de estudiantes
    url_estudiantes = (
        f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
        f"?nomina_id=eq.{nomina_id}"
        f"&select=id,nombre,rut,fecha_nacimiento,nacionalidad,sexo,estado_general,diagnostico,derivaciones,fecha_evaluacion,fecha_reevaluacion,fecha_relleno"
        f"&order=nombre.asc"
    )

    try:
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_SERVICE_HEADERS) 
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        
        print(f"DEBUG: Se encontraron {len(estudiantes_raw)} estudiantes para la nómina {nomina_id}.")
        
        # 3. Preparar los datos de estudiantes para el template
        estudiantes = []
        for est in estudiantes_raw:
            # Asegurarse de que los campos existan o sean None/'' para evitar KeyErrors en el template/procesamiento
            fecha_nacimiento_obj = None
            if est.get('fecha_nacimiento') and est['fecha_nacimiento'].strip():
                 try:
                    # Asumiendo que datetime.strptime está disponible
                    fecha_nacimiento_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                 except:
                    pass

            edad_calculada = "N/A"
            if fecha_nacimiento_obj:
                # Asumiendo que calculate_age está definida en tu app-30.py
                edad_calculada = calculate_age(fecha_nacimiento_obj) 

            estudiantes.append({
                'id': est['id'],
                'nombre': est.get('nombre', ''),
                'rut': est.get('rut', ''),
                'fecha_nacimiento': est.get('fecha_nacimiento', ''), # ISO YYYY-MM-DD
                'fecha_nacimiento_formato': fecha_nacimiento_obj.strftime("%d/%m/%Y") if fecha_nacimiento_obj else 'N/A',
                'edad': edad_calculada,
                'nacionalidad': est.get('nacionalidad', ''),
                'sexo': est.get('sexo', ''),

                # Campos de evaluación que vienen de la DB
                'estado_general': est.get('estado_general', ''),
                'diagnostico': est.get('diagnostico', ''),
                'derivaciones': est.get('derivaciones', ''),
                'fecha_evaluacion': est.get('fecha_evaluacion', ''), # Campo de fecha_evaluacion (YYYY-MM-DD)
                'fecha_reevaluacion': est.get('fecha_reevaluacion', ''),
                'fecha_relleno': est.get('fecha_relleno'),
            })
        
        # 4. Obtener la doctora asignada (para el nombre del archivo PDF)
        doctora_asignada_id = nomina['doctora_id']
        url_doctora = f"{SUPABASE_URL}/rest/v1/doctoras?id=eq.{doctora_asignada_id}&select=nombre"
        res_doctora = requests.get(url_doctora, headers=SUPABASE_SERVICE_HEADERS) 
        doctora_nombre = res_doctora.json()[0]['nombre'] if res_doctora.ok and res_doctora.json() else 'Doctora Asignada'
        
        # Total de formularios completados (necesario para el contador del formulario_relleno.html)
        total_forms_completed_for_nomina = sum(1 for est in estudiantes if est['fecha_relleno'] is not None)


        # 5. Renderizar
        return render_template(
            'formulario_relleno.html',
            nomina_id=nomina_id,
            establecimiento_nombre=nomina['nombre_nomina'], # Usamos nombre_nomina como nombre del establecimiento
            form_type=form_type,
            estudiantes=estudiantes,
            total_forms_completed_for_nomina=total_forms_completed_for_nomina,
            doctora_asignada_id=doctora_asignada_id,
            doctora_nombre=doctora_nombre,
            usuario=user_role
        )

    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR al obtener estudiantes para nómina {nomina_id}: {e}")
        flash('Error al cargar la lista de estudiantes. Verifique su conexión y permisos en Supabase.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ ERROR Inesperado en relleno_formulario: {e}")
        flash('Error interno del servidor. Detalle: ' + str(e), 'error')
        return redirect(url_for('dashboard'))
        
@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    
    # Obtener el form_type y doctora_id_para_formulario de la sesión
    form_type = session.get('current_form_type', 'neurologia') 
    
    # 1. OBTENER EL ID DE LA DOCTORA LOGUEADA PARA BUSCAR EL FORMULARIO
    # Si la doctora está en la sesión, este es el ID que usaremos para la plantilla
    current_doctora_id = session.get('usuario_id')
    
    print(f"DEBUG: generar_pdf - Solicitud para generar PDF para estudiante_id={estudiante_id}, nomina_id={nomina_id}, form_type={form_type}, doctora_id_para_formulario={current_doctora_id}")


    if not all([estudiante_id, nomina_id]):
        flash("❌ Faltan datos esenciales del formulario para generar PDF.", 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formulario', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # Usar los datos del request.form directamente para rellenar el PDF.
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
        # En el formulario familiar, el género se maneja con checkboxes/radio buttons diferentes
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

    # 2. LÓGICA DE SELECCIÓN DE PLANTILLA (CORREGIDA)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_base_path = ''
    
    if form_type == 'neurologia':
        # Intenta usar el PDF específico de la Doctora LOGUEADA
        specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{current_doctora_id}.pdf"
        full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)
        specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)

        if current_doctora_id and os.path.exists(specific_pdf_path):
            pdf_base_path = specific_pdf_path
            print(f"DEBUG: Usando PDF específico de Doctora LOGUEADA: {pdf_base_path}")
        else:
            # Fallback al PDF por defecto
            pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
            print(f"ADVERTENCIA: No se encontró PDF específico. Usando PDF por defecto: {pdf_base_path}")
            
    elif form_type == 'medicina_familiar':
        pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
    
    else:
        flash("❌ Tipo de formulario no reconocido para generar PDF.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formulario', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    if not os.path.exists(pdf_base_path):
        flash(f"❌ Error: El archivo '{pdf_base_path}' no se encontró en la carpeta del servidor. Verifique la ruta y el nombre del archivo.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formulario', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # 3. Lógica de Relleno y Generación
    try:
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        campos = {}
        if form_type == 'neurologia':
            # Campos estrictamente para neurología
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
            # Campos para medicina familiar (usa los campos del request.form directamente)
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

        print(f"DEBUG: Fields to fill in PDF for {form_type} form: {campos}")

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

        nombre_archivo_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario_{form_type}.pdf"
        print(f"DEBUG: PDF generado y listo para descarga: {nombre_archivo_descarga}")
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}. Verifique el archivo base o los campos.", 'error')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formulario', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))
        

@app.route('/marcar_evaluado', methods=['POST'])
def marcar_evaluado():
    if 'usuario' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401

    estudiante_id = request.form.get('estudiante_id')
    
    # --- CORRECCIÓN CLAVE: Fallback si nomina_id no viene en el formulario (era "") ---
    nomina_id = request.form.get('nomina_id')
    if not nomina_id:
        nomina_id = session.get('current_nomina_id')
    # ----------------------------------------------------------------------------------
    
    doctora_id = session.get('usuario_id')
    form_type = session.get('current_form_type', 'neurologia') 
    
    nombre = get_form_field_value('nombre', request.form)
    rut = get_form_field_value('rut', request.form)

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}, form_type={form_type}")
    print(f"DEBUG: Contenido completo de request.form: {request.form.to_dict()}")

    # Validación básica de datos obligatorios (ahora nomina_id ya no debería ser vacío)
    if not all([estudiante_id, nomina_id, doctora_id]):
        print(f"ERROR: Datos faltantes en /marcar_evaluado. Estudiante ID: {estudiante_id}, Nomina ID: {nomina_id}, Doctora ID: {doctora_id}. Campos del formulario: {request.form.to_dict()}")
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400

    # --- 1. DATOS BASE (Comunes a todos los formularios) ---
    update_data = {
        'fecha_relleno': str(date.today()), # Fecha actual de rellenado
        'doctora_evaluadora_id': doctora_id, 
        'nombre': nombre,
        'rut': rut, 
        # Para fechas, queremos None si están vacías para que se mapeen a NULL en la DB
        'fecha_nacimiento': get_form_field_value('fecha_nacimiento_original', request.form, return_none_if_empty=True), 
        'fecha_evaluacion': get_form_field_value('fecha_evaluacion', request.form, return_none_if_empty=True),
        'fecha_reevaluacion': get_form_field_value('fecha_reevaluacion', request.form, return_none_if_empty=True),
        'edad': get_form_field_value('edad', request.form), 
        'nacionalidad': get_form_field_value('nacionalidad', request.form), 
        # Sexo (general) siempre se guarda
        'sexo': get_form_field_value('sexo', request.form),
    }

    # --- 2. LÓGICA PARA CAMPOS ESPECÍFICOS ---
    if form_type == 'neurologia':
        # Campos específicos de Neurología se añaden a update_data
        update_data.update({
            'estado_general': get_form_field_value('estado', request.form),
            'diagnostico': get_form_field_value('diagnostico', request.form), 
            'derivaciones': get_form_field_value('derivaciones', request.form),
        })
    elif form_type == 'medicina_familiar':
        # Campos específicos de Medicina Familiar se añaden a update_data
        update_data.update({
            # Diagnósticos
            'diagnostico_1': get_form_field_value('diagnostico_1', request.form),
            'diagnostico_2': get_form_field_value('diagnostico_2', request.form),
            'diagnostico_complementario': get_form_field_value('diagnostico_complementario', request.form),
            'clasificacion': get_form_field_value('clasificacion_imc', request.form),
            'derivaciones': get_form_field_value('derivaciones', request.form),
            
            # Observaciones
            'observacion_1': get_form_field_value('observacion_1', request.form),
            'observacion_2': get_form_field_value('observacion_2', request.form),
            'observacion_3': get_form_field_value('observacion_3', request.form),
            'observacion_4': get_form_field_value('observacion_4', request.form),
            'observacion_5': get_form_field_value('observacion_5', request.form),
            'observacion_6': get_form_field_value('observacion_6', request.form),
            'observacion_7': get_form_field_value('observacion_7', request.form),

            # Checkboxes (Guardar el valor del formulario si está presente)
            'check_cesarea': get_form_field_value('check_cesarea', request.form),
            'check_atermino': get_form_field_value('check_atermino', request.form),
            'check_vaginal': get_form_field_value('check_vaginal', request.form),
            'check_prematuro': get_form_field_value('check_prematuro', request.form),
            'check_acorde': get_form_field_value('check_acorde', request.form),
            'check_retrasogeneralizado': get_form_field_value('check_retrasogeneralizado', request.form),
            'check_esquemac': get_form_field_value('check_esquemac', request.form),
            'check_esquemai': get_form_field_value('check_esquemai', request.form),
            'check_alergiano': get_form_field_value('check_alergiano', request.form),
            'check_alergiasi': get_form_field_value('check_alergiasi', request.form),
            'check_cirugiano': get_form_field_value('check_cirugiano', request.form),
            'si_2': get_form_field_value('si_2', request.form),
            'check_visionsinalteracion': get_form_field_value('check_visionsinalteracion', request.form),
            'check_visionrefraccion': get_form_field_value('check_visionrefraccion', request.form),
            'check_audicionnormal': get_form_field_value('check_audicionnormal', request.form),
            'check_hipoacusia': get_form_field_value('check_hipoacusia', request.form),
            'check_tapondecerumen': get_form_field_value('check_tapondecerumen', request.form),
            'check_sinhallazgos': get_form_field_value('check_sinhallazgos', request.form),
            'caries': get_form_field_value('caries', request.form),
            'check_apinamientodental': get_form_field_value('check_apinamientodental', request.form),
            'check_retenciondental': get_form_field_value('check_retenciondental', request.form),
            'check_frenillolingual': get_form_field_value('check_frenillolingual', request.form),
            'check_hipertrofia': get_form_field_value('check_hipertrofia', request.form),
            
            # Medidas (Usando return_none_if_empty=True para numéricos)
            'altura': get_form_field_value('altura', request.form, return_none_if_empty=True),
            'peso': get_form_field_value('peso', request.form, return_none_if_empty=True),
            'imc': get_form_field_value('imc', request.form, return_none_if_empty=True),
        })
    
    print(f"DEBUG: Payload final para Supabase PATCH en /marcar_evaluado: {update_data}")
    
    try:
        print(f"DEBUG: Intentando PATCH a estudiantes_nomina con ID: {estudiante_id}.")
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
        print(f"ERROR: Error de conexión con Supabase: {str(e)}")
        return jsonify({"success": False, "message": f"Error de conexión con Supabase: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al marcar estudiante como evaluado: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500
        
@app.route('/')
def index():
    return render_template('login.html')

# --- INICIO MODIFICACIONES CLAVE PARA COORDINADOR DE ESCUELA ---

@app.route('/login', methods=['POST'])
def login():
    usuario_login = request.form['username']
    clave = request.form['password']
    
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario_login}&password=eq.{clave}&select=id,rol"
    
    print(f"DEBUG: Intento de login para usuario: {usuario_login}, URL: {url}")
    try:
        res = requests.get(url, headers=SUPABASE_SERVICE_HEADERS) 
        res.raise_for_status()
        data = res.json()
        print(f"DEBUG: Respuesta Supabase login (Initial): {data}")
        
        if data:
            user_data = data[0]
            role = user_data['rol']
            
            session['usuario'] = role
            session['usuario_id'] = user_data['id']
            
            # 2. Lógica específica para COORDINADOR DE ESCUELA
            if role == 'coordinador_escuela':
                
                # --- OBTENER COLEGIOS/NÓMINAS ASIGNADAS DESDE NOMINAS_MEDICAS ---
                url_nominas_asignadas_por_colegio = (
                    f"{SUPABASE_URL}/rest/v1/nominas_medicas"
                    f"?coord_escuela_id=eq.{user_data['id']}" # Filtrar por el ID del coordinador
                    f"&select=nombre_colegio,token_acceso"
                )
                res_nominas = requests.get(url_nominas_asignadas_por_colegio, headers=SUPABASE_SERVICE_HEADERS)
                res_nominas.raise_for_status()
                nominas_raw = res_nominas.json()
                
                # Agrupar por nombre_colegio para tener una lista única de colegios
                colegios_asignados_data = {}
                for nom in nominas_raw:
                    nombre_colegio = nom.get('nombre_colegio')
                    
                    if nombre_colegio and nombre_colegio not in colegios_asignados_data:
                        # Usamos el nombre del colegio como ID temporal para el frontend
                        colegios_asignados_data[nombre_colegio] = {
                            'id': nombre_colegio, # Usar el nombre como ID/clave de acceso temporal
                            'nombre_colegio': nombre_colegio
                        }

                colegios_asignados_list = list(colegios_asignados_data.values())
                # Los IDs ahora son los nombres de los colegios
                establecimientos_ids = [c['id'] for c in colegios_asignados_list] 

                session['colegios_asignados_ids'] = establecimientos_ids
                session['colegios_asignados'] = colegios_asignados_list
            
            print(f"DEBUG: Sesión iniciada: usuario={session['usuario']}, usuario_id={session['usuario_id']}")
            flash(f'¡Bienvenido, {usuario_login}!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Usuario o contraseña incorrecta.', 'error')
        return redirect(url_for('index'))
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error en el login: {e} - {res.text if 'res' in locals() else ''}")
        flash('Error de conexión al intentar iniciar sesión o error de base de datos.', 'error')
        return redirect(url_for('index'))
        
# - Ruta /dashboard corregida y modificada para la Fase 3

# app-30.py (Reemplaza la función dashboard completa)
@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    user_role = session.get('usuario')
    user_id = session.get('usuario_id')
    
    print(f"DEBUG: Accediendo a dashboard para usuario: {user_role}, ID: {user_id}")

    # --- Variables de inicialización ---
    doctoras_all = [] # Lista completa de doctoras (para select en admin)
    admin_nominas_cargadas = [] # Lista de nóminas para admin
    assigned_nominations = [] # Lista de nóminas para doctora

    # --- Lógica de carga de USUARIOS (Necesaria para Admin/Coord.) ---
    try:
        url_doctoras = f"{SUPABASE_URL}/rest/v1/doctoras?select=id,usuario,rol,nombre" 
        res_doctoras = requests.get(url_doctoras, headers=SUPABASE_SERVICE_HEADERS) 
        res_doctoras.raise_for_status()
        doctoras_raw = res_doctoras.json()
        
        # Filtros de roles
        doctoras_all = [{'id': doc['id'], 'usuario': doc['usuario'], 'rol': doc.get('rol'), 'nombre': doc.get('nombre')} for doc in doctoras_raw]
        all_users_for_lookup = doctoras_all # Para las búsquedas en el HTML
        doctoras_relleno = [user for user in doctoras_all if user['rol'] == 'doctora'] 
        coordinadoras_generales = [user for user in doctoras_all if user['rol'] == 'coordinadora'] 
        coordinadores_escuela = [user for user in doctoras_all if user['rol'] == 'coordinador_escuela']

    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR AL OBTENER DATOS DE DOCTORAS: {e}")
        flash('Error al cargar datos de doctoras o usuarios.', 'error')
        all_users_for_lookup = []
        doctoras_relleno = []
        coordinadoras_generales = []
        coordinadores_escuela = []


    # --- Lógica de carga de NÓMINAS (Admin y Doctora) ---
    if user_role == 'admin':
        # Admin ve TODAS las nóminas
        url_nominas = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?select=id,nombre_nomina,tipo_nomina,doctora_id,url_excel_original,nombre_excel_original,form_type,doctora_id_para_formulario,nombre_colegio,coord_general_id,coord_escuela_id"
            f"&order=nombre_nomina.asc"
        )
        
        try:
            res_nominas = requests.get(url_nominas, headers=SUPABASE_SERVICE_HEADERS) 
            res_nominas.raise_for_status()
            nominas_raw = res_nominas.json()

            for nom in nominas_raw:
                # Buscar nombre de la doctora principal en la lista local de usuarios
                doctora_obj = next((doc for doc in all_users_for_lookup if doc['id'] == nom.get('doctora_id')), None)
                doctora_nombre = doctora_obj['usuario'] if doctora_obj else 'N/A'
                
                admin_nominas_cargadas.append({
                    'id': nom['id'],
                    'nombre_nomina': nom['nombre_nomina'],
                    'tipo_nomina': nom['tipo_nomina'],
                    'doctora_id': nom['doctora_id'],
                    'url_excel_original': nom['url_excel_original'],
                    'nombre_excel_original': nom['nombre_excel_original'],
                    'form_type': nom['form_type'],
                    'doctora_id_para_formulario': nom.get('doctora_id_para_formulario'),
                    'coord_general_id': nom.get('coord_general_id'),
                    'coord_escuela_id': nom.get('coord_escuela_id'),
                    
                    # --- ARREGLO CLAVE PARA NÓMINAS ANTIGUAS ---
                    # Si 'nombre_colegio' es NULL, usamos 'nombre_nomina' (o un placeholder)
                    'nombre_colegio': nom.get('nombre_colegio') or nom['nombre_nomina'] 
                })

        except requests.exceptions.RequestException as e:
            print(f"❌ ERROR AL OBTENER NÓMINAS (ADMIN): {e}")
            flash('Error al cargar nóminas del administrador.', 'error')
            admin_nominas_cargadas = []


    elif user_role == 'doctora':
        # Doctora ve solo sus nóminas asignadas (filtrando por doctora_id)
        url_nominas_asignadas = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?doctora_id=eq.{user_id}"
            f"&select=id,nombre_nomina,tipo_nomina,form_type,doctora_id_para_formulario,nombre_colegio"
            f"&order=nombre_nomina.asc"
        )
        
        try:
            res_nominas_asignadas = requests.get(url_nominas_asignadas, headers=SUPABASE_SERVICE_HEADERS) 
            res_nominas_asignadas.raise_for_status()
            nominas_raw = res_nominas_asignadas.json()
            
            for nom in nominas_raw:
                assigned_nominations.append({
                    'id': nom['id'],
                    'nombre_establecimiento': nom['nombre_nomina'],
                    'tipo_nomina_display': nom['tipo_nomina'].replace('_', ' ').title(),
                    'form_type': nom.get('form_type'),
                    'doctora_id_para_formulario': nom.get('doctora_id_para_formulario'),
                    
                    # --- ARREGLO CLAVE PARA NÓMINAS ANTIGUAS ---
                    # Si 'nombre_colegio' es NULL, usa 'nombre_nomina'
                    'nombre_colegio': nom.get('nombre_colegio') or nom['nombre_nomina']
                })
        
        except requests.exceptions.RequestException as e:
            print(f"❌ ERROR AL OBTENER NÓMINAS ASIGNADAS (DOCTORA): {e}")
            flash('Error al cargar nóminas asignadas.', 'error')
            assigned_nominations = []

    # --- Lógica de carga para Coordinador de Escuela (Usa datos de Session) ---
    colegios_asignados_escuela = session.get('colegios_asignados', [])

    # ------------------ Renderizado del Dashboard ------------------
    return render_template(
        'dashboard-23.html',
        usuario=user_role,
        rol=user_role, # Mantener rol para compatibilidad
        
        # Datos para ADMIN/COORDINADORA
        admin_nominas_cargadas=admin_nominas_cargadas,
        doctoras=doctoras_relleno, # Doctoras para SELECTS
        coordinadoras_generales=coordinadoras_generales, 
        coordinadores_escuela=coordinadores_escuela,
        all_users_for_lookup=all_users_for_lookup, # CRUCIAL: Lista de todos los usuarios
        
        # Datos para DOCTORA
        assigned_nominations=assigned_nominations,
        
        # Datos para COORDINADOR DE ESCUELA
        colegios_asignados=colegios_asignados_escuela,
        
        # Relleno de variables vacías (para evitar TemplateErrors)
        eventos=[], formularios=[], conteo={}, establecimientos=[],
        doctor_performance_data={}, doctor_performance_data_single_doctor={'completed': 0, 'pending': 0, 'total': 0},
        nombre_establecimiento_coordinador=None, nominas_completadas_escuela=None
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

    # ... (Lógica existente para agregar establecimiento) ...
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
        print(f"❌ ERROR AL GUARDAR ESTABLECIMIENTO EN DB: {e} - {response_db.text if 'response_db' in locals() else ''}")
        flash("❌ Error al guardar el establecimiento en la base de datos.", 'error')
    except Exception as e:
        print(f"❌ Error inesperado al guardar establecimiento: {e}")
        flash("❌ Error inesperado al guardar el establecimiento.", 'error')

    return redirect(url_for('dashboard'))


# - Modificar la función admin_cargar_nomina

# - Modificar la función admin_cargar_nomina

# Asegúrate de que esta importación esté en la parte superior de app-30.py:
# import secrets 

@app.route('/admin/cargar_nomina', methods=['POST'])
def admin_cargar_nomina():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    
    # 1. Obtener datos del formulario
    tipo_nomina_raw = request.form.get('tipo_nomina', '').strip()
    nombre_colegio_o_establecimiento = request.form.get('nombre_especifico', '').strip() # ¡Usamos este campo como nombre del colegio!
    doctora_id_from_form = request.form.get('doctora', '').strip()
    excel_file = request.files.get('excel')
    doctora_id_para_formulario = request.form.get('doctora_id_para_formulario', '').strip()

    # Obtener IDs de coordinación
    coord_general_id_from_form = request.form.get('coord_general_id', '').strip()
    coord_escuela_id_from_form = request.form.get('coord_escuela_id', '').strip()
    
    tipo_nomina_normalized = tipo_nomina_raw.strip().lower() if tipo_nomina_raw else ''
    
    form_type = None
    if 'neurologia' in tipo_nomina_normalized: 
        form_type = 'neurologia'
    elif 'familiar' in tipo_nomina_normalized or 'medicina familiar' in tipo_nomina_normalized: 
        form_type = 'medicina_familiar'

    # Validaciones básicas
    if not all([tipo_nomina_raw, nombre_colegio_o_establecimiento, doctora_id_from_form, excel_file]):
        flash('❌ Falta uno o más campos obligatorios.', 'error')
        return redirect(url_for('dashboard'))

    if form_type is None: 
        flash(f'❌ El tipo de nómina "{tipo_nomina_raw}" no se pudo mapear a un tipo de formulario conocido.', 'error')
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

    # Mapear cadenas vacías a None para la DB (Crucial para NULL en UUID)
    coord_general_id_db = coord_general_id_from_form if coord_general_id_from_form else None
    coord_escuela_id_db = coord_escuela_id_from_form if coord_escuela_id_from_form else None

    # GENERACIÓN DEL TOKEN DE ACCESO (solo si hay coordinador de escuela asignado)
    token_generado = None
    if coord_escuela_id_db: 
        token_generado = secrets.token_hex(2) 

    # 3. Payload de Inserción (NOMBRES DE COLUMNA EXACTOS)
    data_nomina = {
        "id": nomina_id,
        "nombre_nomina": nombre_colegio_o_establecimiento, 
        "tipo_nomina": tipo_nomina_raw, 
        "doctora_id": doctora_id_from_form, 
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename,
        "form_type": form_type, 
        "doctora_id_para_formulario": doctora_id_para_formulario if form_type == 'neurologia' else None,
        
        # --- CAMPOS CLAVE 100% INTEGRADOS ---
        "nombre_colegio": nombre_colegio_o_establecimiento, # <-- COLUMNA DE TEXTO EN NOMINAS_MEDICAS
        "coord_general_id": coord_general_id_db,
        "coord_escuela_id": coord_escuela_id_db,
        "token_acceso": token_generado,
        # Nota: Establecimiento_id se setea a None o debe ser eliminado/renombrado en tu DB.
        "establecimiento_id": None 
        # -----------------------------------------------------------
    }
    
    try:
        # Intento de inserción en nominas_medicas
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_nomina
        )
        res_insert_nomina.raise_for_status()

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_nomina.text if 'res_insert_nomina' in locals() else 'No response from Supabase.'
        print(f"❌ ERROR AL GUARDAR NÓMINA EN DB: {error_detail}")
        flash(f"❌ Error al guardar los datos de la nómina en la base de datos. {error_detail}", 'error')
        # Rollback
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
        except Exception: pass
        return redirect(url_for('dashboard'))

    excel_data_stream = io.BytesIO(excel_file_data)
    
    
    if excel_filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(excel_data_stream)
    elif excel_filename.endswith('.csv'):
        df = pd.read_csv(excel_data_stream, encoding='utf-8')
    else:
        flash('❌ Formato de archivo no soportado para la nómina.', 'error')
        # Rollback
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
        except Exception: pass
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
        flash(f"❌ El archivo no contiene las columnas necesarias: {', '.join(missing_cols)}.", 'error')
        # Rollback
        try:
            requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
            requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
        except Exception: pass
        return redirect(url_for('dashboard'))
        
    establecimiento_id_db_para_estudiantes = None # Siempre NULL para no causar error si la columna era INT8 y ya no apunta a nada

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
            if isinstance(fecha_nacimiento_raw, (datetime, date)):
                fecha_nac_str = fecha_nacimiento_raw.strftime('%Y-%m-%d')
            else:
                try:
                    parsed_date = pd.to_datetime(fecha_nacimiento_raw, errors='coerce')
                    if pd.notna(parsed_date):
                        fecha_nac_str = parsed_date.strftime('%Y-%m-%d')
                    else:
                        raise ValueError("Formato de fecha no reconocido o inválido.")
                except Exception:
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
                "fecha_relleno": None,
                 # <-- Nulo
            }
            estudiantes_a_insertar.append(estudiante)
            
        except Exception as e:
            print(f"❌ Error al procesar fila {index+2}: {e}. Datos de la fila: {row.to_dict()}")
            flash(f"Error al procesar la fila {index+2} del archivo. Verifique el formato de los datos. ({e})", 'error')
            # Rollback: eliminar la nómina y el archivo subido
            try:
                requests.delete(upload_url, headers=SUPABASE_SERVICE_HEADERS)
                requests.delete(f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}", headers=SUPABASE_SERVICE_HEADERS)
            except Exception: pass
            return redirect(url_for('dashboard'))

    if not estudiantes_a_insertar:
        flash("⚠️ El archivo Excel/CSV no contiene datos válidos para estudiantes.", 'warning')
        return redirect(url_for('dashboard'))

    try:
        res_insert_estudiantes = requests.post(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=estudiantes_a_insertar
        )
        res_insert_estudiantes.raise_for_status()

        flash(f"✅ Nómina '{nombre_colegio_o_establecimiento}' cargada con éxito. Se agregaron {len(estudiantes_a_insertar)} estudiantes. Token: {token_generado if token_generado else 'N/A'}", 'success')
        return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_estudiantes.text if 'res_insert_estudiantes' in locals() else 'No response from Supabase.'
        flash(f"❌ Error al guardar los estudiantes en la base de datos. La nómina fue creada, pero no se agregaron los estudiantes. ({e}). Detalles: {error_detail}", 'error')
        return redirect(url_for('dashboard'))


# La ruta '/enviar_formulario_a_drive' ha sido eliminada por completo.

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
        print(f"❌ Error al obtener mis nóminas: {e}")
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
        print(f"❌ Error al registrar alumnos evaluados: {e} - {response_db.text if 'response_db' in locals() else ''}")
        flash("❌ Error al registrar la cantidad de alumnos evaluados.", 'error')
    except Exception as e:
        print(f"❌ Error inesperado al registrar alumnos evaluados: {e}")
        flash("❌ Error inesperado al registrar la cantidad de alumnos evaluados.", 'error')

    return redirect(url_for('dashboard'))

# --- NUEVA RUTA: RUTA DE DESBLOQUEO DEL COORDINADOR DE ESCUELA ---
# app-30.py (Reemplaza la función /api/nomina/desbloquear completa)
# app-30.py (Reemplaza la función /api/nomina/desbloquear completa)
# app-30.py (Reemplaza la función /api/nomina/desbloquear completa)
# app-30.py (Reemplaza la función /api/nomina/desbloquear completa)
@app.route('/api/nomina/desbloquear', methods=['POST'])
def desbloquear_nomina():
    # 1. Verificación Inicial de Seguridad
    if session.get('usuario') != 'coordinador_escuela':
        return jsonify({"success": False, "message": "Acceso no autorizado al recurso"}), 403
    
    data = request.get_json()
    password_ingresada = data.get('password')
    school_name = data.get('school_id') 
    
    # 2. Verificación de Asignación
    colegios_permitidos = session.get('colegios_asignados_ids', [])
    if school_name not in colegios_permitidos:
        return jsonify({"success": False, "message": "No tiene permiso asignado para este establecimiento."}), 403
        
    # 3. Validar el token de acceso para ese colegio (Envuelto en TRY/EXCEPT para errores de conexión)
    try:
        url_token = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?nombre_colegio=eq.{school_name}"
            f"&coord_escuela_id=eq.{session.get('usuario_id')}"
            f"&select=token_acceso,id"
        )
        
        res_token = requests.get(url_token, headers=SUPABASE_SERVICE_HEADERS)
        res_token.raise_for_status()
        nominas_con_token = res_token.json()
        
        token_esperado = nominas_con_token[0].get('token_acceso') if nominas_con_token and nominas_con_token[0] else None
        
        # 4. Comparamos la contraseña
        if token_esperado and token_esperado == password_ingresada:
            
            nomina_ids = [nom.get('id') for nom in nominas_con_token if nom.get('id')]
            nomina_ids_str = ",".join(nomina_ids)

            if not nomina_ids:
                return jsonify({"success": True, "nominas": []}) 
                
            # 5. CONSULTA FINAL DE ESTUDIANTES (Sin filtro de fecha)
            url_students = (
                f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
                f"?nomina_id=in.({nomina_ids_str})"
                f"&select=id,nombre,rut,fecha_evaluacion,fecha_relleno"
                f"&order=nombre.asc"
            )

            nominas_raw = requests.get(url_students, headers=SUPABASE_SERVICE_HEADERS).json()
            
            # 6. Procesamiento de datos (Recuperación del nombre de nómina en el bucle)
            nominas_procesadas = []
            for alumno in nominas_raw:
                
                if not isinstance(alumno, dict):
                    print(f"ADVERTENCIA: Elemento inesperado saltado: {alumno}")
                    continue 
                
                # Consulta de apoyo para el nombre de la nómina (usando el nomina_id)
                nombre_nomina = 'N/A'
                if alumno.get('nomina_id'):
                    url_nomina_name = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{alumno['nomina_id']}&select=nombre_nomina"
                    res_nomina_name = requests.get(url_nomina_name, headers=SUPABASE_SERVICE_HEADERS)
                    if res_nomina_name.ok and res_nomina_name.json():
                        nombre_nomina = res_nomina_name.json()[0]['nombre_nomina']

                fecha_relleno = alumno.get('fecha_relleno')
                estado_evaluacion = "Evaluado" if fecha_relleno else "PENDIENTE"
                puede_descargar = estado_evaluacion == "Evaluado"
                
                nominas_procesadas.append({
                    'id': alumno.get('id'),
                    'nombre_alumno': alumno.get('nombre'), 
                    'rut_alumno': format_rut_python(alumno.get('rut')), 
                    'fecha_evaluacion': alumno.get('fecha_evaluacion') or 'N/A',
                    'nombre_nomina': nombre_nomina, 
                    'estado': estado_evaluacion, 
                    'descarga_habilitada': puede_descargar 
                })
            
            return jsonify({"success": True, "nominas": nominas_procesadas})
        else:
            # Token incorrecto
            return jsonify({"success": False, "message": "Token de acceso incorrecto"}), 401
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR DE CONEXIÓN CON SUPABASE: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con Supabase al validar token: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ ERROR INESPERADO AL DESBLOQUEAR NÓMINA: {e}")
        # Retornar 500 para el cliente
        return jsonify({"success": False, "message": f"Error inesperado del servidor: {str(e)}"}), 500
        
# --- NUEVA RUTA: DESCARGA DE PDF POR ALUMNO ID ---@app.route('/descargar_pdf_alumno/<alumno_id>', methods=['GET'])
@app.route('/descargar_pdf_alumno/<alumno_id>', methods=['GET'])
def descargar_pdf_alumno(alumno_id):
    
    if session.get('usuario') != 'coordinador_escuela':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    try:
        # --- CONSULTA 1 (DATOS ESENCIALES DEL ALUMNO Y FK) ---
        # SELECT MÍNIMO MÁS SEGURO: Sólo IDs, nombre, RUT, Fechas de control y nomina_id.
        url_student_data = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?id=eq.{alumno_id}"
            f"&select=id,nombre,rut,fecha_nacimiento,fecha_evaluacion,doctora_evaluadora_id,fecha_relleno,nomina_id,sexo,nacionalidad,fecha_reevaluacion"
        )
        res_student = requests.get(url_student_data, headers=SUPABASE_SERVICE_HEADERS)
        res_student.raise_for_status() 
        student_data = res_student.json()

        if not student_data or not student_data[0].get('fecha_relleno'):
            flash(f"❌ Alumno ID {alumno_id} no encontrado o no evaluado.", 'error')
            return redirect(url_for('dashboard'))

        est = student_data[0]
        nomina_id_fk = est.get('nomina_id') 
        
        # --- CONSULTA 2 (METADATA DE LA NÓMINA - SIN JOIN) ---
        url_nomina_meta = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?id=eq.{nomina_id_fk}"
            f"&select=form_type,nombre_nomina"
        )
        res_nomina_meta = requests.get(url_nomina_meta, headers=SUPABASE_SERVICE_HEADERS)
        res_nomina_meta.raise_for_status()
        nomina_meta = res_nomina_meta.json()[0] if res_nomina_meta.json() else {}

        # 3. Mapeo de Variables y Lógica de Plantilla
        form_type = nomina_meta.get('form_type', 'neurologia')
        nombre_nomina = nomina_meta.get('nombre_nomina', 'Valoracion')
        doctora_evaluadora_id = est.get('doctora_evaluadora_id')
        
        # --- Cálculo de campos y Formato de Fechas (sin cambios) ---
        edad = 'N/A'
        if est.get('fecha_nacimiento'):
            try:
                birth_date = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                edad = calculate_age(birth_date)
            except: pass
        
        fecha_nac_formato = est.get('fecha_nacimiento')
        fecha_evaluacion_formatted = est.get('fecha_evaluacion')
        fecha_reeval_pdf = est.get('fecha_reevaluacion')

        # 4. Lógica de plantilla (sin cambios)
        pdf_base_path = ''
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        if form_type == 'neurologia':
            specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{doctora_evaluadora_id}.pdf"
            full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)
            specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)

            if doctora_evaluadora_id and os.path.exists(specific_pdf_path):
                pdf_base_path = specific_pdf_path
            else:
                pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
                
        elif form_type == 'medicina_familiar':
            pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
        
        else:
             raise FileNotFoundError(f"Tipo de formulario no reconocido: {form_type}")
        
        if not os.path.exists(pdf_base_path):
             raise FileNotFoundError(f"Archivo base del formulario no encontrado: {pdf_base_path}")

        # 5. Inicializar el rellenador de PDF y Mapear Campos
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])

        # --- Mapeo de Campos (Usando est.get() para seguridad máxima) ---
        nombre = est.get('nombre', '')
        rut = format_rut_python(est.get('rut', ''))
        
        campos = {}
        if form_type == 'neurologia':
            campos = {
                "nombre": nombre,
                "rut": rut, 
                "fecha_nacimiento": fecha_nac_formato, 
                "nacionalidad": est.get('nacionalidad', ''),
                "edad": edad, 
                "diagnostico_1": est.get('diagnostico_1', est.get('diagnostico', '')),
                "estado_general": est.get('estado_general', ''),
                "fecha_evaluacion": fecha_evaluacion_formatted, 
                "fecha_reevaluacion": fecha_reeval_pdf,
                "derivaciones": est.get('derivaciones', ''),
                "sexo_f": "X" if est.get('sexo') == "F" else "",
                "sexo_m": "X" if est.get('sexo') == "M" else "",
                # Nota: Los campos que no se pidieron en el SELECT (como estado_general) se llenarán como ''
            }
        elif form_type == 'medicina_familiar':
             campos = {
                 "nombre": nombre,
                 "rut": rut,
                 "fecha_nacimiento": fecha_nac_formato,
                 "edad": edad, 
                 "nacionalidad": est.get('nacionalidad', ''),
                 "sexo_f": "X" if est.get('sexo') == "F" else "",
                 "sexo_m": "X" if est.get('sexo') == "M" else "",
                 "diagnostico_1": est.get('diagnostico_1', est.get('diagnostico', '')),
                 "derivaciones": est.get('derivaciones', ''),
                 "fecha_evaluacion": fecha_evaluacion_formatted,
                 "fecha_reevaluacion": fecha_reeval_pdf,
             }

        # 6. Llenado y Descarga (sin cambios)
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

        # Nombre del archivo para la descarga
        nombre_archivo_descarga = f"Valoracion_{nombre.replace(' ', '_')}_{rut}_{nombre_nomina.replace(' ', '_')}.pdf"
        
        # Usamos send_file con as_attachment=True para forzar la descarga
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener datos de Supabase para PDF: {e}")
        flash(f"❌ Error crítico: Fallo de conexión/consulta. Detalles: {e}. Revise el log.", 'error')
        return redirect(url_for('dashboard'))
    except FileNotFoundError as e:
        print(f"❌ Error File Not Found: {e}")
        flash(f"❌ Error al generar el PDF: Archivo base no encontrado.", 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Error inesperado al generar PDF de alumno: {e}")
        flash(f"❌ Error inesperado al generar el PDF. Detalle: {e}", 'error')
        return redirect(url_for('dashboard'))
        
# - Añadir en la sección de rutas
def get_supabase_count(filter_params=""):
    """Función auxiliar para obtener un conteo de Supabase usando SERVICE HEADERS."""
    # El conteo se pide usando el filtro 'select=count()' y se obtiene del encabezado 'Content-Range'.
    url_count = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?select=count(){filter_params}"
    
    try:
        response = requests.get(url_count, headers=SUPABASE_SERVICE_HEADERS, params={'limit': 1})
        response.raise_for_status()

        content_range = response.headers.get('Content-Range')
        if content_range:
            count_str = content_range.split('/')[-1]
            return int(count_str)
        return 0
    except Exception as e:
        print(f"ERROR en get_supabase_count con filtro {filter_params}: {e}")
        return 0


@app.route('/api/dashboard_counts', methods=['GET'])
def dashboard_counts():
    """Retorna el conteo total y por especialidad de evaluaciones completadas."""
    
    # Asumimos que la Coordinadora General tiene el rol 'coordinadora'
    if session.get('usuario') != 'coordinadora':
        return jsonify({"success": False, "message": "Acceso denegado."}), 403

    try:
        # Filtro base para evaluaciones completadas: fecha_relleno no es nulo.
        base_filter = "&fecha_relleno.not.is.null"
        
        # 1. Conteo Total
        total_evaluados = get_supabase_count(base_filter)
        
        # 2. Conteo por Neurología (Usando un proxy de diagnóstico o asumiendo el campo 'form_type' si existe)
        filter_neurologia = f"{base_filter}&diagnostico=in.('Trastorno Del Espectro Autista','TDAH','Trastorno Motor Moderado','Hipoacusia')" 
        neurologia_count = get_supabase_count(filter_neurologia)
        
        # 3. Conteo por Familiar (Proxy: el resto)
        familiar_count = total_evaluados - neurologia_count
        
        # Si la columna form_type existe en estudiantes_nomina, el filtrado ideal sería:
        # filter_neurologia = f"{base_filter}&form_type=eq.neurologia"
        # filter_familiar = f"{base_filter}&form_type=eq.medicina_familiar"


        return jsonify({
            "success": True, 
            "total_evaluados": total_evaluados,
            "neurologia_count": neurologia_count,
            "familiar_count": familiar_count
        })

    except Exception as e:
        print(f"❌ Error interno en dashboard_counts: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor al obtener conteos: {e}"}), 500

# --- NUEVA RUTA: SOLICITUD DE CORRECCIÓN ---
@app.route('/api/correccion/solicitar', methods=['POST'])
def solicitar_correccion():
    if session.get('usuario') != 'coordinador_escuela':
        return jsonify({"success": False, "message": "Acceso denegado."}), 403
    
    data = request.get_json()
    alumno_id = data.get('alumno_id')
    detalles = data.get('detalles')
    coordinador_id = session.get('usuario_id')
    
    if not all([alumno_id, detalles]):
        return jsonify({"success": False, "message": "Faltan datos de la solicitud (ID de alumno o detalles)."}), 400
    
    payload = {
        "alumno_id": alumno_id,
        "detalles": detalles,
        "coordinador_id": coordinador_id, 
        "fecha_solicitud": datetime.now().isoformat()
    }
    
    try:
        # Insertar la solicitud en la tabla 'solicitudes_correccion'
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/solicitudes_correccion",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=payload
        )
        res.raise_for_status()
        
        return jsonify({"success": True, "message": "✅ Solicitud de corrección registrada exitosamente. El equipo de soporte lo revisará pronto."})
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR AL INSERTAR SOLICITUD DE CORRECCIÓN: {e} - {res.text if 'res' in locals() else ''}")
        return jsonify({"success": False, "message": "❌ Error al guardar la solicitud en la base de datos."}), 500

# --- FIN MODIFICACIONES CLAVE PARA COORDINADOR DE ESCUELA ---

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
        print(f"DEBUG: Obteniendo rendimiento para doctora: {doctor_name} (ID: {doctor_id})")

        url_students = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?doctora_evaluadora_id=eq.{doctor_id}" 
            f"&fecha_relleno.not.is.null" 
            f"&select=nombre,rut,fecha_nacimiento,fecha_relleno,nomina_id,nominas_medicas(nombre_nomina)" 
            f"&order=nombre.asc" 
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
                'rut': format_rut_python(student.get('rut')), # APLICA FORMATO AQUÍ TAMBIÉN SI SE MUESTRA EN ESTA VISTA
                'fecha_relleno': formatted_date,
                'nomina_nombre': nomina_nombre 
            })

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al obtener el rendimiento de la doctora: {e} - {res_students.text if 'res_students' in locals() else 'No response'}")
        flash('Error al cargar el detalle de rendimiento de la doctora.', 'error')
    except Exception as e:
        print(f"❌ Error inesperado al cargar rendimiento de doctora: {e}")
        flash('Error inesperado al cargar el detalle de rendimiento de la doctora.', 'error')

    return render_template('doctor_performance.html', 
                           doctor_name=doctor_name, 
                           evaluated_students=evaluated_students)

@app.route('/admin/crear_proyecto', methods=['POST'])
def crear_proyecto():
    if request.method == 'POST':
        nombre_proyecto_form = request.form.get('nombre_proyecto') # Valor del formulario
        descripcion_proyecto_form = request.form.get('descripcion_proyecto') # Valor del formulario
        print(f"DEBUG: Intentando crear proyecto (via requests): {nombre_proyecto_form}, Desc: {descripcion_proyecto_form}")

        # Datos a enviar a Supabase, usando los nombres de columna que me indicaste
        payload = {
            "nombre_proyecto": nombre_proyecto_form,       # Nombre de la columna en Supabase
            "descripcion_proyecto": descripcion_proyecto_form, # Nombre de la columna en Supabase
            "fecha_creacion": datetime.now().isoformat() # Asegúrate de que este campo exista y sea 'timestamp with time zone'
        }

        # URL de tu tabla 'proyectos' en Supabase
        proyectos_url = f"{SUPABASE_URL}/rest/v1/proyectos"

        try:
            # Usar SUPABASE_SERVICE_HEADERS es generalmente más seguro para inserts desde el backend
            response = requests.post(proyectos_url, json=payload, headers=SUPABASE_SERVICE_HEADERS)

            # Para depurar el detalle del error de Supabase
            if response.status_code != 201: # El código de éxito para POST es 201 Created
                print(f"DEBUG: Respuesta de error de Supabase (Status {response.status_code}): {response.text}")

            response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)

            data = response.json() # Si todo va bien, obtén la respuesta JSON

            print(f"DEBUG: Proyecto '{nombre_proyecto_form}' creado exitosamente en Supabase. Respuesta: {data}")
            flash('Proyecto creado exitosamente!', 'success')
            return redirect(url_for('dashboard', _external=True, _scheme='https', section='gestionar_proyectos'))

        except requests.exceptions.HTTPError as errh:
            print(f"CRÍTICO: Error HTTP al insertar proyecto: {errh}")
            flash(f"Error al crear el proyecto (HTTP): {errh}", 'danger')
        except requests.exceptions.ConnectionError as errc:
            print(f"CRÍTICO: Error de Conexión al insertar proyecto: {errc}")
            flash(f"Error al crear el proyecto (Conexión): {errc}", 'danger')
        except requests.exceptions.Timeout as errt:
            print(f"CRÍTICO: Tiempo de espera agotado al insertar proyecto: {errt}")
            flash(f"Error al crear el proyecto (Timeout): {errt}", 'danger')
        except requests.exceptions.RequestException as err:
            print(f"CRÍTICO: Error inesperado al insertar proyecto: {err}")
            flash(f"Error en el servidor al crear el proyecto: {err}", 'danger')
        except Exception as e:
            print(f"CRÍTICO: Error general al procesar la creación del proyecto: {e}")
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

        # Formatear el RUT en el DataFrame antes de exportar a Excel
        df['RUT'] = df['RUT'].apply(format_rut_python) # APLICA EL FORMATO AQUÍ PARA EL EXCEL

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
    # Obtener el tipo de formulario y el ID de la doctora para el PDF base de la nómina
    res_nomina = requests.get(
        f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,form_type,doctora_id_para_formulario",
        headers=SUPABASE_SERVICE_HEADERS
    )
    res_nomina.raise_for_status()
    nomina_info = res_nomina.json()
    if not nomina_info:
        return jsonify({"success": False, "message": "Nómina no encontrada."}), 404
    
    nomina_nombre = nomina_info[0]['nombre_nomina']
    form_type = nomina_info[0]['form_type']
    doctora_id_para_formulario = nomina_info[0].get('doctora_id_para_formulario')

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

    # ... (Lógica de generación de ZIP omitida por brevedad, usa la función generar_pdfs_visibles) ...

    return jsonify({"success": False, "message": "Ruta de ZIP no implementada completamente."}), 501

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
    # Obtener el form_type y doctora_id_para_formulario de la sesión para saber qué PDF base usar
    form_type = session.get('current_form_type', 'neurologia') 
    doctora_id_para_formulario = session.get('doctora_id_para_formulario')

    pdf_base_path = ''
    if form_type == 'neurologia':
        if doctora_id_para_formulario:
            pdf_base_path = get_doctor_specific_neurologia_pdf(doctora_id_para_formulario)
        else:
            # Asegúrate de que PDF_BASE_NEUROLOGIA sea una ruta absoluta si no está en el mismo directorio
            base_dir = os.path.dirname(os.path.abspath(__file__))
            pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
    elif form_type == 'medicina_familiar':
        # Asegúrate de que PDF_BASE_FAMILIAR sea una ruta absoluta si no está en el mismo directorio
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
    else:
        return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

    if not os.path.exists(pdf_base_path):
        return jsonify({"success": False, "message": f"Error interno: Archivo base del formulario '{pdf_base_path}' no encontrado en el servidor."}), 500

    try:
        for student_id in student_ids:
            # Recuperar los datos del estudiante de la base de datos
            url_student_data = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{student_id}&select=*"
            res_student = requests.get(url_student_data, headers=SUPABASE_SERVICE_HEADERS)
            res_student.raise_for_status()
            student_data = res_student.json()

            if not student_data:
                print(f"ADVERTENCIA: Estudiante con ID {student_id} no encontrado. Saltando.")
                continue

            est = student_data[0] 

            # Preparar los datos para el PDF, asegurando que los Nones sean cadenas vacías
            nombre = est.get('nombre', '')
            # APLICA EL FORMATO AL RUT AQUÍ PARA PDFS VISIBLES
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
                    "rut": rut, # AHORA 'rut' YA VIENE FORMATEADO
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
                # Aquí deberías mapear los campos específicos de tu formulario de Medicina Familiar
                campos = {
                    "Nombres y Apellidos": nombre,
                    "RUN": rut, # AHORA 'rut' YA VIENE FORMATEADO
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
                    "SI_2": "/Yes" if est.get('si_2') else "", # Corregido nombre de campo
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
