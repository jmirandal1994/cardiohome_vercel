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
import re
import urllib.parse
# Las importaciones específicas para Google Drive API han sido eliminadas.


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_super_segura_cardiohome_2025")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx', 'csv'}

# Define los PDFs base para cada tipo de formulario
# Asegúrate de que estos archivos PDF existan en la misma carpeta que app.py
PDF_BASE_NEUROLOGIA = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_BASE_FAMILIAR = 'formulario_familiar.pdf' 
# 🟢 NUEVA CONSTANTE PARA EL INFORME NEUROLÓGICO
PDF_BASE_INFORME_NEURO = 'INFORME_NEUROLOGICO_BASE.pdf'
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
    "Accept": "application/json",
    "Prefer": "count=exact"
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

# app-30.py (VERSIÓN FINAL CON PREFER HEADER Y MANEJO DE FILTROS)

# Asegúrate de que 'import uuid' esté al inicio de app.py

# Reemplaza la función get_supabase_count en app.py por esta versión:

# --- Asegúrate de que esta línea esté al inicio de app.py:
# from datetime import datetime, date
# import requests 
# import uuid
# ---

# app-31.py (Reemplazo de la función get_supabase_count)
# app.py (Reemplazo de la función get_supabase_count)

# app.py (Reemplazo de la función get_supabase_count)
# Asegúrate de tener: 
# import urllib.parse 
# from datetime import datetime 
# import requests 
# ...

# app.py (Reemplazo de la función get_supabase_count)
# app.py (Reemplazo de la función get_supabase_count)
# Necesita: from datetime import datetime, import requests

# app.py (Reemplazo de la función get_supabase_count)
# Necesita: from datetime import datetime, import requests

# app.py (Reemplazo de la función get_supabase_count)

# app.py (Reemplazo de la función get_supabase_count)
# Asegúrate de tener import requests y from datetime import datetime

# --- UTILIDAD ROBUSTA DE CONTEO: get_supabase_count ---
def get_supabase_count(filter_params=""):
    """
    Retorna un entero con el conteo de filas coincidentes en estudiantes_nomina.
    Usa select=id y lee Content-Range. filter_params debe ser algo como:
      "nomina_id=eq.<uuid>&evaluado_flag=eq.true"
    """
    # Normalizar filtro (no empezar con &)
    if filter_params and filter_params.startswith('&'):
        filter_params = filter_params[1:]

    url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?select=id"
    if filter_params:
        url = f"{url}&{filter_params}"

    try:
        # Usamos SERVICE headers (tienes Prefer: count=exact ahí)
        res = requests.get(url, headers=SUPABASE_SERVICE_HEADERS)
        res.raise_for_status()

        # Content-Range ejemplo: "0-9/24" → total = 24
        content_range = res.headers.get("Content-Range")
        if content_range and '/' in content_range:
            total_str = content_range.split('/')[-1]
            try:
                return int(total_str)
            except ValueError:
                pass

        # Si no hay Content-Range, fallback a len(json)
        data = res.json()
        return len(data) if isinstance(data, list) else 0

    except Exception as e:
        print(f"❌ ERROR en get_supabase_count. URL: {url}. Error: {e}")
        return 0


# app-30.py (Función get_assigned_nomina_ids)

# app-30.py (Función get_assigned_nomina_ids - CORREGIDA)

def get_assigned_nomina_ids(user_id):
    """Obtiene la lista de IDs de nóminas asignadas directamente al user_id."""
    
    # 🟢 CORRECCIÓN CLAVE: Usamos el nombre de columna real 'coord_general_id'
    columna_asignacion = "coord_general_id" 
    
    url_asignaciones = (
        f"{SUPABASE_URL}/rest/v1/nominas_medicas"
        f"?{columna_asignacion}=eq.{user_id}" 
        f"&select=id"
    )
    
    try:
        print(f"DEBUG: Consultando nóminas asignadas: {url_asignaciones}") 
        
        # Usa SERVICE HEADERS para asegurar el acceso a la tabla de nóminas
        res = requests.get(url_asignaciones, headers=SUPABASE_SERVICE_HEADERS)
        res.raise_for_status()
        
        nomina_ids = [item['id'] for item in res.json()]
        print(f"DEBUG: Nóminas asignadas a {user_id}: {len(nomina_ids)} nóminas encontradas.")
        return nomina_ids
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR al obtener nóminas asignadas para {user_id}: {e}")
        return []
        
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

# Coloca esta función en la sección de utilidades de app-38.py:
def map_db_value_to_x(db_value):
    """Convierte el valor True/False o string de la base de datos a 'X' o ''."""
    if db_value is True or (isinstance(db_value, str) and db_value.strip()):
        return "X"
    return ""

# -------------------- Rutas de la Aplicación --------------------

# app-30.py (Reemplaza la función relleno_formulario completa)
# app-32.py (REEMPLAZO COMPLETO DE relleno_formulario - BASADO EN tipo_nomina)

@app.route('/relleno_formulario/<string:nomina_id>', methods=['GET'])
def relleno_formulario(nomina_id):
    # Asumo que las importaciones (datetime, requests, etc.) y funciones (calculate_age, etc.) existen

    if 'usuario' not in session:
        return redirect(url_for('index'))

    user_role = session.get('usuario')
    user_id = session.get('usuario_id')
    
    # Guardamos el ID de la nómina en la sesión para que esté disponible en otras rutas
    session['current_nomina_id'] = nomina_id 

    # 1. Obtener detalles de la nómina
    url_nomina = (
        f"{SUPABASE_URL}/rest/v1/nominas_medicas"
        f"?id=eq.{nomina_id}"
        f"&select=form_type,tipo_nomina,doctora_id,nombre_nomina,doctora_id_para_formulario"
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
        
        # Guardar form_type y doctora_id_para_formulario en la sesión (CRÍTICO para otras rutas)
        session['current_form_type'] = form_type
        session['doctora_id_para_formulario'] = nomina.get('doctora_id_para_formulario')
        
        # Validación de acceso
        if user_role == 'doctora' and nomina['doctora_id'] != user_id:
            flash('Acceso no autorizado a esta nómina.', 'error')
            return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        error_detail = e.response.text if e.response is not None else 'Conexión Fallida'
        print(f"❌ ERROR al obtener detalles de la nómina {nomina_id}: {e}. Detalle: {error_detail}")
        flash(f'Error al cargar la nómina. Detalle: {error_detail}', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ ERROR Inesperado al procesar detalles de la nómina: {e}")
        flash('Error interno del servidor.', 'error')
        return redirect(url_for('dashboard'))

    # 2. Obtener la lista de estudiantes con TODOS los campos de evaluación
    url_estudiantes = (
        f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
        f"?nomina_id=eq.{nomina_id}"
        f"&select=id,nombre,rut,fecha_nacimiento,nacionalidad,sexo,estado_general,diagnostico,derivaciones,fecha_evaluacion,fecha_reevaluacion,fecha_relleno,diagnostico_1,diagnostico_2,diagnostico_complementario,clasificacion,observacion_1,observacion_2,observacion_3,observacion_4,observacion_5,observacion_6,observacion_7,check_cesarea,check_atermino,check_vaginal,check_prematuro,check_acorde,check_retrasogeneralizado,check_esquemac,check_esquemai,check_alergiano,check_alergiasi,check_cirugiano,si_2,check_visionsinalteracion,check_visionrefraccion,check_audicionnormal,check_hipoacusia,check_tapondecerumen,check_sinhallazgos,caries,check_apinamientodental,check_retenciondental,check_frenillolingual,check_hipertrofia,altura,peso,imc,indicaciones,fecha_reevaluacion_select,motivo_consulta,observacion_neurologia,observaciones,diagnostico_sospecha,diagnostico_definitivo" 
        f"&order=nombre.asc"
    )

    try:
        res_estudiantes = requests.get(url_estudiantes, headers=SUPABASE_SERVICE_HEADERS) 
        res_estudiantes.raise_for_status()
        estudiantes_raw = res_estudiantes.json()
        
        # 3. Preparar los datos de estudiantes para el template
        estudiantes = []
        for est_raw in estudiantes_raw:
            est = est_raw.copy()
            
            # Procesamiento de Fechas y Edad
            fecha_nacimiento_obj = None
            if est.get('fecha_nacimiento') and est['fecha_nacimiento'].strip():
                try:
                    fecha_nacimiento_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()
                except:
                    pass

            edad_calculada = "N/A"
            if fecha_nacimiento_obj:
                edad_calculada = calculate_age(fecha_nacimiento_obj) 

            est['edad'] = edad_calculada
            # 💡 Aseguramos que el formato de fecha de nacimiento siempre esté disponible:
            est['fecha_nacimiento_formato'] = fecha_nacimiento_obj.strftime("%d/%m/%Y") if fecha_nacimiento_obj else 'N/A'
            est['fecha_nacimiento'] = est.get('fecha_nacimiento', '')
            est['fecha_evaluacion'] = est.get('fecha_evaluacion', '')
            est['fecha_reevaluacion'] = est.get('fecha_reevaluacion', '')
            
            # 💡 Corrección del Mapeo de check_cirugiasi / si_2 (Medicina Familiar)
            # Aunque ya no está en el formulario, es necesario para cargar datos antiguos de la DB.
            if est.get('si_2'):
                est['check_cirugiasi'] = est.get('si_2') 
                
            # Mapeo de género (sexo) a los checkboxes (Medicina Familiar)
            sexo_db = (est.get('sexo') or "").upper()
            est['genero_f'] = (sexo_db == 'F')
            est['genero_m'] = (sexo_db == 'M')
            
            estudiantes.append(est)
        
        # 4. Obtener la doctora asignada
        doctora_asignada_id = nomina['doctora_id']
        url_doctora = f"{SUPABASE_URL}/rest/v1/doctoras?id=eq.{doctora_asignada_id}&select=nombre"
        res_doctora = requests.get(url_doctora, headers=SUPABASE_SERVICE_HEADERS) 
        doctora_nombre = res_doctora.json()[0]['nombre'] if res_doctora.ok and res_doctora.json() else 'Doctora Asignada'
        
        # Total de formularios completados
        total_forms_completed_for_nomina = sum(1 for est in estudiantes if est.get('fecha_relleno') is not None)


        # 5. LÓGICA DE REDIRECCIÓN CLAVE (UNIFICADA POR form_type)
        base_render_params = {
            'nomina_id': nomina_id,
            'establecimiento_nombre': nomina['nombre_nomina'],
            'form_type': form_type, 
            'estudiantes': estudiantes,
            'total_forms_completed_for_nomina': total_forms_completed_for_nomina,
            'doctora_asignada_id': doctora_asignada_id,
            'doctora_nombre': doctora_nombre,
            'usuario': user_role
        }
        
        # Redirección basada en la columna 'form_type'
        if form_type == 'informe_neurologico':
            # Usa el HTML para el nuevo informe
            return render_template('formulario_informe_neurologico.html', **base_render_params)

        elif form_type == 'medicina_familiar':
            # Usa el HTML de Medicina Familiar
            return render_template('formulario_medicina_familiar.html', **base_render_params)
        
        elif form_type == 'neurologia':
            # Usa el HTML de Neurología
            return render_template('formulario_relleno.html', **base_render_params)
        
        else:
            flash(f'❌ El tipo de formulario "{form_type.capitalize()}" no se pudo mapear a un formulario conocido.', 'error')
            return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        error_detail = e.response.text if e.response is not None else 'Conexión Fallida'
        print(f"❌ ERROR al obtener estudiantes para nómina {nomina_id}: {e}. Detalle: {error_detail}")
        flash(f'Error al cargar la lista de estudiantes. Revise si todas las columnas del SELECT existen en su tabla estudiantes_nomina.', 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ ERROR Inesperado en relleno_formulario: {e}")
        flash('Error interno del servidor. Detalle: ' + str(e), 'error')
        return redirect(url_for('dashboard'))
        

# app.py (REEMPLAZO FINAL Y CORREGIDO DE generar_pdf - INTEGRIDAD DEL PDF)
# Asegúrate de que todas las demás importaciones necesarias (flask, get_form_field_value, format_rut_python, etc.) 
# estén definidas al inicio de tu app.py

# REEMPLAZA COMPLETAMENTE ESTA FUNCIÓN EN TU app.py
@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    
    form_type = session.get('current_form_type', 'neurologia') 
    current_doctora_id = session.get('usuario_id')
    
    print(f"DEBUG: generar_pdf - Solicitud para generar PDF para estudiante_id={estudiante_id}, nomina_id={nomina_id}, form_type={form_type}, doctora_id={current_doctora_id}")

    if not all([estudiante_id, nomina_id]):
        flash("❌ Faltan datos esenciales del formulario para generar PDF.", 'danger')
        if 'current_nomina_id' in session:
            return redirect(url_for('relleno_formulario', nomina_id=session['current_nomina_id']))
        return redirect(url_for('dashboard'))

    # --- 1. Obtener datos de la nómina para el ID de la Doctora Firmante ---
    doctora_id_para_pdf = current_doctora_id 
    try:
        nomina_data = obtener_nomina_por_id(nomina_id)
        doctora_id_para_pdf = nomina_data.get('doctora_id_para_formulario') if nomina_data.get('doctora_id_para_formulario') else current_doctora_id
    except Exception as e:
        print(f"ADVERTENCIA: No se pudo obtener el ID de la doctora firmante. Usando ID de sesión. {e}")
        
    # --- 2. Procesamiento de Campos Comunes y Fechas ---
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

    # Funciones auxiliares
    def map_check_value(field_name):
        return get_form_field_value(field_name, request.form) or ""
    
    # Función para escribir "X" en campos de texto que actúan como casillas
    def map_check_as_text(field_name):
        val = request.form.get(field_name)
        if val and val.strip() != "":
            return "X"
        return ""

    # Mapeos de Género (como texto "X")
    sexo_f_pdf = "X" if get_form_field_value('genero_f', request.form) or get_form_field_value('sexo', request.form) == 'F' else ""
    sexo_m_pdf = "X" if get_form_field_value('genero_m', request.form) or get_form_field_value('sexo', request.form) == 'M' else ""

    # Formatos de Fecha
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
            
    derivaciones = get_form_field_value('derivaciones', request.form)

    # --- 3. Selección de Plantilla ---
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_base_path = ''
    
    if form_type == 'neurologia':
        specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{doctora_id_para_pdf}.pdf"
        full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)
        specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)
        pdf_base_path = specific_pdf_path if os.path.exists(specific_pdf_path) else os.path.join(base_dir, PDF_BASE_NEUROLOGIA)
            
    elif form_type == 'informe_neurologico':
        specific_pdf_filename = f"INFORME_NEUROLOGICO_BASE_{doctora_id_para_pdf}.pdf"
        pdf_bases_dir = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)
        specific_pdf_path = os.path.join(pdf_bases_dir, specific_pdf_filename)
        pdf_base_path = specific_pdf_path if os.path.exists(specific_pdf_path) else os.path.join(base_dir, PDF_BASE_INFORME_NEURO)
    
    elif form_type == 'medicina_familiar':
        pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)

    # --- 4. Lógica de Relleno y Generación ---
    try:
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
            
        campos = {}
        
        # 🟢 NEUROLOGÍA: SE MANTIENE TU LÓGICA ORIGINAL COMPLETA
        if form_type == 'neurologia':
            print("DEBUG: Usando mapeo original de Neurología.")
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
                "derivaciones": derivaciones,
                "sexo_f": sexo_f_pdf,
                "sexo_m": sexo_m_pdf,
            }
        
        # 🟢 INFORME NEUROLÓGICO: SE MANTIENE TU LÓGICA ORIGINAL COMPLETA
        elif form_type == 'informe_neurologico':
            campos = {
                "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac_formato, 
                "edad": edad, "genero_m": sexo_m_pdf, "genero_f": sexo_f_pdf, 
                "nacionalidad": nacionalidad,
                "motivo_consulta": get_form_field_value('motivo_consulta', request.form),
                "observaciones": get_form_field_value('observaciones', request.form),      
                "observacion_neurologia": get_form_field_value('observacion_neurologia', request.form), 
                "diagnostico": get_form_field_value('diagnostico', request.form),
                "indicaciones": get_form_field_value('indicaciones', request.form),        
                "derivaciones": derivaciones, 
                "fecha_evaluacion": fecha_evaluacion_formatted,
                "fecha_reevaluacion": fecha_reeval_pdf,
            }
            
        # 🟢 MEDICINA FAMILIAR: CORRECCIÓN DE LA "X" EN CAMPOS DE TEXTO
        elif form_type == 'medicina_familiar':
            diagnostico_unificado_valor = get_form_field_value('diagnostico_unificado', request.form)
            campos = {
                "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac_formato, "edad": edad, "nacionalidad": nacionalidad,
                "sexo_f": sexo_f_pdf, "sexo_m": sexo_m_pdf,
                "diagnostico_1": diagnostico_unificado_valor, "diagnostico_2": diagnostico_unificado_valor, 
                "diagnostico_complementario": get_form_field_value('diagnostico_complementario', request.form),
                "clasificacion": get_form_field_value('clasificacion_imc', request.form),
                "indicaciones": get_form_field_value('indicaciones', request.form), "derivaciones": derivaciones, 
                "fecha_evaluacion": fecha_evaluacion_formatted, "fecha_reevaluacion": fecha_reeval_pdf,
                "altura": get_form_field_value('altura', request.form), "peso": get_form_field_value('peso', request.form), "imc": get_form_field_value('imc', request.form),
                "observacion_1": get_form_field_value('observacion_1', request.form), "observacion_2": get_form_field_value('observacion_2', request.form),
                "observacion_3": get_form_field_value('observacion_3', request.form), "observacion_4": get_form_field_value('observacion_4', request.form),
                "observacion_5": get_form_field_value('observacion_5', request.form), "observacion_6": get_form_field_value('observacion_6', request.form),
                "observacion_7": get_form_field_value('observacion_7', request.form),
                
                # Campos "check" que son de texto: escribimos "X" si están marcados
                "check_cesarea": map_check_as_text('check_cesarea'),
                "check_atermino": map_check_as_text('check_atermino'),
                "check_vaginal": map_check_as_text('check_vaginal'),
                "check_prematuro": map_check_as_text('check_prematuro'),
                "check_acorde": map_check_as_text('check_acorde'),
                "check_retraso": map_check_as_text('check_retraso'),
                "check_retrasogeneralizado": map_check_as_text('check_retrasogeneralizado'),
                "check_esquemac": map_check_as_text('check_esquemac'),
                "check_esquemai": map_check_as_text('check_esquemai'),
                "check_alergiano": map_check_as_text('check_alergiano'),
                "check_alergiasi": map_check_as_text('check_alergiasi'),
                "check_cirugiano": map_check_as_text('check_cirugiano'),
                "check_cirugiasi": map_check_as_text('check_cirugiasi'),
                "check_visionsinalteracion": map_check_as_text('check_visionsinalteracion'),
                "check_visionrefraccion": map_check_as_text('check_visionrefraccion'),
                "check_audicionnormal": map_check_as_text('check_audicionnormal'),
                "check_hipoacusia": map_check_as_text('check_hipoacusia'),
                "check_tapondecerumen": map_check_as_text('check_tapondecerumen'),
                "check_sinhallazgos": map_check_as_text('check_sinhallazgos'),
                "check_caries": map_check_as_text('check_caries'),
                "check_apinamientodental": map_check_as_text('check_apinamientodental'),
                "check_retenciondental": map_check_as_text('check_retenciondental'),
                "check_frenillolingual": map_check_as_text('check_frenillolingual'),
                "check_hipertrofia": map_check_as_text('check_hipertrofia'),
            }

        # Aplicar el relleno
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({NameObject("/AcroForm"): DictionaryObject()})
            
        for page in writer.pages:
            writer.update_page_form_field_values(page, campos)

        writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        nombre_descarga = f"{nombre.replace(' ', '_')}_{rut}_formulario_{form_type}.pdf"
        return send_file(output, as_attachment=True, download_name=nombre_descarga, mimetype='application/pdf')

    except Exception as e:
        print(f"❌ Error al generar PDF: {e}")
        flash(f"❌ Error al generar el PDF: {e}", 'error')
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
    
    # Nota: Debes tener get_form_field_value y date importados
    nombre = get_form_field_value('nombre', request.form)
    rut = get_form_field_value('rut', request.form)

    print(f"DEBUG: Recibida solicitud para marcar como evaluado: estudiante_id={estudiante_id}, nomina_id={nomina_id}, doctora_id={doctora_id}, form_type={form_type}")
    print(f"DEBUG: Contenido completo de request.form: {request.form.to_dict()}")

    # Validación básica de datos obligatorios
    if not all([estudiante_id, nomina_id, doctora_id]):
        print(f"ERROR: Datos faltantes en /marcar_evaluado. Estudiante ID: {estudiante_id}, Nomina ID: {nomina_id}, Doctora ID: {doctora_id}. Campos del formulario: {request.form.to_dict()}")
        return jsonify({"success": False, "message": "Faltan datos obligatorios para marcar y guardar la evaluación."}), 400

    # --- 1. DATOS BASE (Comunes a todos los formularios) ---
    update_data = {
        'fecha_relleno': str(date.today()),
        'doctora_evaluadora_id': doctora_id, 
        'nombre': nombre,
        'rut': rut, 
        'fecha_nacimiento': get_form_field_value('fecha_nacimiento_original', request.form, return_none_if_empty=True), 
        'fecha_evaluacion': get_form_field_value('fecha_evaluacion', request.form, return_none_if_empty=True),
        'fecha_reevaluacion': get_form_field_value('fecha_reevaluacion', request.form, return_none_if_empty=True),
        'edad': get_form_field_value('edad', request.form), 
        'nacionalidad': get_form_field_value('nacionalidad', request.form), 
        'sexo': get_form_field_value('sexo', request.form),
        'evaluado_flag': True,
    }

    # --- 2. LÓGICA PARA CAMPOS ESPECÍFICOS ---
    if form_type == 'neurologia':
        # Campos específicos de Neurología (Antiguo) se añaden a update_data
        update_data.update({
            'estado_general': get_form_field_value('estado', request.form),
            'diagnostico': get_form_field_value('diagnostico', request.form), 
            'derivaciones': get_form_field_value('derivaciones', request.form),
        })
    
    # 🟢 CORRECCIÓN: Lógica para guardar el Informe Neurológico Individual
    elif form_type == 'informe_neurologico':
         update_data.update({
             # Campos de Evaluación Confirmados (5 campos)
             'motivo_consulta': get_form_field_value('motivo_consulta', request.form),
             'observaciones': get_form_field_value('observaciones', request.form),
             'observacion_neurologia': get_form_field_value('observacion_neurologia', request.form),
             'diagnostico': get_form_field_value('diagnostico', request.form), 
             'indicaciones': get_form_field_value('indicaciones', request.form),
             
             # Nota: Los campos que no se usan en este formulario (como diagnostico_sospecha o historia_actual) se omiten o se dejan en NULL.
             # Para evitar errores en otros procesos (como la generación del PDF), 
             # rellenamos los campos relacionados si es necesario, pero solo con la data existente.
             # Si el PDF necesita 'derivaciones', debemos agregarlo al formulario HTML, pero aquí solo guardamos lo que el HTML envía.
         })
         
    elif form_type == 'medicina_familiar':
        
        # OBTENEMOS EL VALOR UNIFICADO DEL CAMPO DIAGNOSTICO
        diagnostico_unificado_valor = get_form_field_value('diagnostico_unificado', request.form)

        # FUNCIÓN AUXILIAR PARA MAPEO BOOLEANO (True o None)
        def map_to_boolean(field_name):
            value = get_form_field_value(field_name, request.form)
            if value and value.strip():
                return True
            return get_form_field_value(field_name, request.form, return_none_if_empty=True)
            
        # 💡 CORRECCIÓN 1: Capturar y mapear el género (sexo) para guardar en el campo maestro 'sexo'
        genero_f_check = get_form_field_value('genero_f', request.form)
        genero_m_check = get_form_field_value('genero_m', request.form)
        sexo_final = None
        if genero_f_check:
            sexo_final = 'F'
        elif genero_m_check:
            sexo_final = 'M'
        # Sobreescribir el campo 'sexo' en el payload base con el valor final
        update_data['sexo'] = sexo_final
        # -----------------------------------------------------------------------------------------


        # Campos específicos de Medicina Familiar
        update_data.update({
            # Diagnósticos y Derivaciones
            'diagnostico_1': diagnostico_unificado_valor,
            'diagnostico_2': diagnostico_unificado_valor,
            'diagnostico_complementario': get_form_field_value('diagnostico_complementario', request.form),
            'clasificacion': get_form_field_value('clasificacion_imc', request.form),
            'derivaciones': get_form_field_value('derivaciones', request.form),
            
            # Mapeo Corregido: Guardado del campo 'indicaciones'
            'indicaciones': get_form_field_value('indicaciones', request.form), 
            
            # 💡 CORRECCIÓN 3: Guardado del valor del SELECT de años
            'fecha_reevaluacion_select': get_form_field_value('fecha_reevaluacion_select', request.form, return_none_if_empty=True),
            
            # Observaciones
            'observacion_1': get_form_field_value('observacion_1', request.form),
            'observacion_2': get_form_field_value('observacion_2', request.form),
            'observacion_3': get_form_field_value('observacion_3', request.form),
            'observacion_4': get_form_field_value('observacion_4', request.form),
            'observacion_5': get_form_field_value('observacion_5', request.form),
            'observacion_6': get_form_field_value('observacion_6', request.form),
            'observacion_7': get_form_field_value('observacion_7', request.form),

            # Checkboxes y Numéricos - CRÍTICO: USAR map_to_boolean para booleanos
            'check_cesarea': map_to_boolean('check_cesarea'),
            'check_atermino': map_to_boolean('check_atermino'),
            'check_vaginal': map_to_boolean('check_vaginal'),
            'check_prematuro': map_to_boolean('check_prematuro'),
            'check_acorde': map_to_boolean('check_acorde'),
            'check_retraso': map_to_boolean('check_retraso'), 
            'check_retrasogeneralizado': map_to_boolean('check_retrasogeneralizado'),
            'check_esquemac': map_to_boolean('check_esquemac'),
            'check_esquemai': map_to_boolean('check_esquemai'),
            'check_alergiano': map_to_boolean('check_alergiano'),
            'check_alergiasi': map_to_boolean('check_alergiasi'),
            'check_cirugiano': map_to_boolean('check_cirugiano'),
            'check_cirugiasi': map_to_boolean('check_cirugiasi'), 
            'check_visionsinalteracion': map_to_boolean('check_visionsinalteracion'),
            'check_visionrefraccion': map_to_boolean('check_visionrefraccion'),
            'check_audicionnormal': map_to_boolean('check_audicionnormal'),
            'check_hipoacusia': map_to_boolean('check_hipoacusia'),
            'check_tapondecerumen': map_to_boolean('check_tapondecerumen'),
            'check_sinhallazgos': map_to_boolean('check_sinhallazgos'),
            'check_caries': map_to_boolean('check_caries'),
            'check_apinamientodental': map_to_boolean('check_apinamientodental'),
            'check_retenciondental': map_to_boolean('check_retenciondental'),
            'check_frenillolingual': map_to_boolean('check_frenillolingual'),
            'check_hipertrofia': map_to_boolean('check_hipertrofia'),
            'altura': get_form_field_value('altura', request.form, return_none_if_empty=True),
            'peso': get_form_field_value('peso', request.form, return_none_if_empty=True),
            'imc': get_form_field_value('imc', request.form, return_none_if_empty=True),
            'clasificacion_imc': get_form_field_value('clasificacion_imc', request.form, return_none_if_empty=True),
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

@app.route('/api/admin/reporte_proyecto/<project_id>')
def reporte_proyecto_detalle(project_id):
    if session.get('usuario') != 'admin': 
        return jsonify({"success": False, "message": "No autorizado"}), 403

    try:
        # 1. Obtener nombre del proyecto
        proyecto_nombre = "Reporte Global"
        if project_id != 'all':
            url_p = f"{SUPABASE_URL}/rest/v1/proyectos?id=eq.{project_id}&select=nombre_proyecto"
            res_p = requests.get(url_p, headers=SUPABASE_SERVICE_HEADERS)
            if res_p.ok and res_p.json():
                proyecto_nombre = res_p.json()[0]['nombre_proyecto']

        # 2. Obtener las nóminas asociadas
        if project_id == 'all':
            url_n = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina"
        else:
            url_n = f"{SUPABASE_URL}/rest/v1/nominas_medicas?proyecto_id=eq.{project_id}&select=id,nombre_nomina"
        
        res_n = requests.get(url_n, headers=SUPABASE_SERVICE_HEADERS)
        nominas = res_n.json() if res_n.ok else []
        
        # 3. Construir el detalle contando alumnos por nómina
        reporte_data = []
        for nom in nominas:
            # Usamos tu función get_supabase_count que ya sabemos que funciona
            evaluados = get_supabase_count(f"nomina_id=eq.{nom['id']}&evaluado_flag=eq.true")
            pendientes = get_supabase_count(f"nomina_id=eq.{nom['id']}&evaluado_flag=eq.false")
            
            reporte_data.append({
                "nomina": nom['nombre_nomina'],
                "evaluados": evaluados,
                "pendientes": pendientes,
                "total": evaluados + pendientes
            })

        return jsonify({
            "success": True,
            "proyecto": proyecto_nombre,
            "fecha_emision": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "detalles": reporte_data
        })
    except Exception as e:
        print(f"❌ ERROR REPORTE: {e}")
        return jsonify({"success": False, "error": str(e)})
        
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

@app.route('/admin/cargar_informe_individual', methods=['POST'])
def admin_cargar_informe_individual():
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))
    
    # 1. Obtener datos del formulario
    nombre_establecimiento = request.form.get('nombre_establecimiento_informe', '').strip()
    doctora_id_asignada = request.form.get('doctora_asignada_informe', '').strip()
    excel_file = request.files.get('excel_informe_individual')

    # Validaciones básicas
    if not all([nombre_establecimiento, doctora_id_asignada, excel_file]):
        flash('❌ Faltan campos obligatorios para cargar el informe.', 'error')
        return redirect(url_for('dashboard'))

    if not permitido(excel_file.filename):
        flash('❌ Archivo Excel o CSV no válido. Extensiones permitidas: .xls, .xlsx, .csv', 'error')
        return redirect(url_for('dashboard'))

    # Generar un ID ÚNICO para esta carga (como si fuera una "mini-nomina")
    nomina_id_individual = str(uuid.uuid4())
    excel_filename = secure_filename(excel_file.filename)
    excel_file_data = excel_file.read()

    try:
        # (Opcional) Subir el archivo a Supabase Storage (se mantiene el flujo de la nómina)
        upload_path = f"informes-individuales/{nomina_id_individual}/{excel_filename}"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{upload_path}"
        
        res_upload = requests.put(upload_url, headers=SUPABASE_SERVICE_HEADERS, data=excel_file_data)
        res_upload.raise_for_status()
        url_excel_publica = f"{SUPABASE_URL}/storage/v1/object/public/{upload_path}" 

    except requests.exceptions.RequestException as e:
        error_detail = res_upload.text if 'res_upload' in locals() else 'No response from Supabase Storage.'
        flash(f"❌ Error al subir el archivo a Supabase Storage: {error_detail}", 'error')
        return redirect(url_for('dashboard'))

    # 2. Procesar Excel y mapear datos
    excel_data_stream = io.BytesIO(excel_file_data)
    
    if excel_filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(excel_data_stream)
    elif excel_filename.endswith('.csv'):
        df = pd.read_csv(excel_data_stream, encoding='utf-8')
    else:
        flash('❌ Formato de archivo no soportado.', 'error')
        return redirect(url_for('dashboard'))

    # Normalizar columnas
    df.columns = [normalizar(col) for col in df.columns]

    # Mapeo estricto a las columnas requeridas (nombre, rut, fecha_nacimiento, nacionalidad)
    required_cols = {'nombre', 'rut', 'fecha_nacimiento', 'nacionalidad'}
    
    if not all(col in df.columns for col in required_cols):
        missing_cols = [col for col in required_cols if col not in df.columns]
        flash(f"❌ El archivo no contiene las columnas necesarias: {', '.join(missing_cols)}.", 'error')
        return redirect(url_for('dashboard'))

    # 3. Crear la "Mini-Nómina" de Informe Individual (en la tabla nominas_medicas)
    data_nomina_individual = {
        "id": nomina_id_individual,
        "nombre_nomina": f"INF_{nombre_establecimiento}",
        "tipo_nomina": "INFORME_INDIVIDUAL_NEURO", # Nuevo tipo de nómina para filtrado
        "doctora_id": doctora_id_asignada, 
        "url_excel_original": url_excel_publica,
        "nombre_excel_original": excel_filename,
        "form_type": "informe_neurologico", # Nuevo tipo de formulario específico para routing
        "nombre_colegio": nombre_establecimiento,
        "coord_general_id": None, 
        "coord_escuela_id": None,
        "token_acceso": None,
        "establecimiento_id": None 
    }
    
    try:
        res_insert_nomina = requests.post(
            f"{SUPABASE_URL}/rest/v1/nominas_medicas",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=data_nomina_individual
        )
        res_insert_nomina.raise_for_status()

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_nomina.text if 'res_insert_nomina' in locals() else 'No response from Supabase.'
        flash(f"❌ Error al guardar la nómina individual en DB: {error_detail}", 'error')
        return redirect(url_for('dashboard'))

    # 4. Insertar estudiantes
    estudiantes_a_insertar = []
    
    for index, row in df.iterrows():
        try:
            nombre_completo_raw = row['nombre']
            rut_raw = row['rut']
            fecha_nacimiento_raw = row['fecha_nacimiento']
            nacionalidad_raw = row['nacionalidad'] 

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

            # Calcular edad para pre-rellenar el campo
            fecha_nac_obj = datetime.strptime(fecha_nac_str, '%Y-%m-%d').date()
            edad_calculada = calculate_age(fecha_nac_obj)

            estudiante = {
                "nomina_id": nomina_id_individual,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, 
                "nacionalidad": nacionalidad_valor,
                "sexo": sexo_adivinado,
                "edad": edad_calculada, # Guardamos la edad calculada
                "fecha_relleno": None,
                "evaluado_flag": False,
                "tipo_registro_individual": "INFORME_NEURO", # Flag para diferenciar
            }
            estudiantes_a_insertar.append(estudiante)
            
        except Exception as e:
            print(f"❌ Error al procesar fila {index+2} para informe individual: {e}. Datos de la fila: {row.to_dict()}")
            flash(f"Error al procesar la fila {index+2} del archivo. ({e})", 'error')
            return redirect(url_for('dashboard'))

    if not estudiantes_a_insertar:
        flash("⚠️ El archivo Excel/CSV no contiene datos válidos para informes.", 'warning')
        return redirect(url_for('dashboard'))

    try:
        res_insert_estudiantes = requests.post(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=estudiantes_a_insertar
        )
        res_insert_estudiantes.raise_for_status()

        flash(f"✅ Informe(s) individual(es) cargado(s) con éxito. Se agregaron {len(estudiantes_a_insertar)} estudiantes.", 'success')
        return redirect(url_for('dashboard'))

    except requests.exceptions.RequestException as e:
        error_detail = res_insert_estudiantes.text if 'res_insert_estudiantes' in locals() else 'No response from Supabase.'
        flash(f"❌ Error al guardar los estudiantes en la base de datos. {error_detail}", 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/admin/reporte_proyecto/<project_id>')
def reporte_proyecto_detalle(project_id):
    # Verificación de seguridad
    if session.get('usuario') != 'admin': 
        return jsonify({"success": False, "message": "No autorizado"}), 403

    try:
        # 1. Obtener el nombre del proyecto real
        proyecto_nombre = "Reporte Global"
        if project_id != 'all':
            url_p = f"{SUPABASE_URL}/rest/v1/proyectos?id=eq.{project_id}&select=nombre_proyecto"
            res_p = requests.get(url_p, headers=SUPABASE_SERVICE_HEADERS)
            if res_p.ok and res_p.json():
                proyecto_nombre = res_p.json()[0]['nombre_proyecto']

        # 2. Buscar las nóminas vinculadas a este proyecto
        if project_id == 'all':
            url_n = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,nombre_nomina"
        else:
            url_n = f"{SUPABASE_URL}/rest/v1/nominas_medicas?proyecto_id=eq.{project_id}&select=id,nombre_nomina"
        
        res_n = requests.get(url_n, headers=SUPABASE_SERVICE_HEADERS)
        nominas = res_n.json() if res_n.ok else []
        
        # 3. Contar alumnos evaluados vs pendientes por cada nómina
        reporte_data = []
        for nom in nominas:
            # Reutilizamos tu lógica de flags que ya funciona
            evaluados = get_supabase_count(f"nomina_id=eq.{nom['id']}&evaluado_flag=eq.true")
            pendientes = get_supabase_count(f"nomina_id=eq.{nom['id']}&evaluado_flag=eq.false")
            
            reporte_data.append({
                "nomina": nom['nombre_nomina'],
                "evaluados": evaluados,
                "pendientes": pendientes,
                "total": evaluados + pendientes
            })

        print(f"📊 Reporte generado para proyecto: {proyecto_nombre}")
        
        return jsonify({
            "success": True,
            "proyecto": proyecto_nombre,
            "fecha_emision": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "detalles": reporte_data
        })
    except Exception as e:
        print(f"❌ ERROR AL GENERAR DATOS DE REPORTE: {e}")
        return jsonify({"success": False, "error": str(e)})
        
# - Ruta 
@app.route('/api/admin/stats/<project_id>')
def get_admin_stats(project_id):
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "No autorizado"}), 403

    try:
        # 1. Obtener las nóminas que pertenecen al proyecto
        if project_id == 'all':
            url_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,tipo_nomina"
        else:
            url_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?proyecto_id=eq.{project_id}&select=id,tipo_nomina"
        
        res_n = requests.get(url_nominas, headers=SUPABASE_SERVICE_HEADERS)
        nominas = res_n.json() if res_n.ok else []

        # Inicializamos contadores exactos como los de tu perfil de coordinadora
        total_evaluados = 0
        total_pendientes = 0
        neuro_count = 0
        familiar_count = 0
        doctor_stats = {}

        # 2. Recorrer cada nómina para contar usando tu lógica de flags
        for nom in nominas:
            nom_id = nom.get("id")
            tipo = (nom.get("tipo_nomina") or "").lower().strip()
            
            # Usamos tu misma lógica de get_supabase_count
            evaluados = get_supabase_count(f"nomina_id=eq.{nom_id}&evaluado_flag=eq.true")
            pendientes = get_supabase_count(f"nomina_id=eq.{nom_id}&evaluado_flag=eq.false")

            total_evaluados += evaluados
            total_pendientes += pendientes

            # Conteo por especialidad (Neurología vs Familiar/Medicina)
            if "neuro" in tipo:
                neuro_count += evaluados
            elif "familiar" in tipo or "medicina" in tipo:
                familiar_count += evaluados

        # 3. Calcular porcentaje
        total_alumnos = total_evaluados + total_pendientes
        percent = round((total_evaluados / total_alumnos * 100), 1) if total_alumnos > 0 else 0

        return jsonify({
            "success": True,
            "total": total_alumnos,
            "completed": total_evaluados,
            "pending": total_pendientes,
            "percent": f"{percent}%",
            "neuro": neuro_count,
            "familiar": familiar_count,
            # Por ahora enviamos un objeto vacío para el gráfico si no quieres complicarlo
            "chart_data": {} 
        })
    except Exception as e:
        print(f"❌ Error en stats premium: {e}")
        return jsonify({"success": False, "error": str(e)})
        
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
    proyectos = []
    
    # --- Lógica de carga de USUARIOS (Necesaria para Admin/Coord.) ---
# --- 1. Lógica de carga de PROYECTOS (ACTUALIZADO) ---
    try:
        # Añadimos descripcion_proyecto y created_at al select
        url_p = f"{SUPABASE_URL}/rest/v1/proyectos?select=id,nombre_proyecto,descripcion_proyecto,created_at&order=nombre_proyecto.asc"
        res_p = requests.get(url_p, headers=SUPABASE_SERVICE_HEADERS)
        if res_p.ok:
            raw_proyectos = res_p.json()
            # Mapeamos 'created_at' a 'fecha_creacion' para que el HTML lo entienda
            proyectos = []
            for p in raw_proyectos:
                proyectos.append({
                    "id": p['id'],
                    "nombre_proyecto": p['nombre_proyecto'],
                    "descripcion_proyecto": p.get('descripcion_proyecto'),
                    "fecha_creacion": p.get('created_at'), # <--- MAPEO CLAVE
                    "nominas": [] # Se llena más abajo
                })
    except Exception as e:
        print(f"❌ ERROR AL OBTENER PROYECTOS: {e}")
        proyectos = []
        
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
        # NUEVO: Se agregó 'proyecto_id' al select
        url_nominas = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?select=id,nombre_nomina,tipo_nomina,doctora_id,url_excel_original,nombre_excel_original,form_type,doctora_id_para_formulario,nombre_colegio,coord_general_id,coord_escuela_id,proyecto_id"
            f"&order=nombre_nomina.asc"
        )
        
        try:
            res_nominas = requests.get(url_nominas, headers=SUPABASE_SERVICE_HEADERS) 
            res_nominas.raise_for_status()
            nominas_raw = res_nominas.json()

            for nom in nominas_raw:
                doctora_obj = next((doc for doc in all_users_for_lookup if doc['id'] == nom.get('doctora_id')), None)
                
                # Preparamos el objeto de la nómina
                datos_nomina = {
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
                    'proyecto_id': nom.get('proyecto_id'), # NUEVO
                    'nombre_colegio': nom.get('nombre_colegio') or nom['nombre_nomina'] 
                }
                
                # 1. La agregamos a la lista general que ya tenías
                admin_nominas_cargadas.append(datos_nomina)

                # 2. NUEVO: Lógica de Carpetas
                # Buscamos el proyecto correspondiente en la lista 'proyectos' y le metemos esta nómina
                for p in proyectos:
                    if str(p['id']) == str(nom.get('proyecto_id')):
                        if 'nominas' not in p:
                            p['nominas'] = []
                        p['nominas'].append(datos_nomina)

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
        proyectos=proyectos,
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

# Coloque esto en su archivo principal de Flask (app.py)

from flask import jsonify, session

# ... (otras importaciones y configuración de Supabase)

# app-38.py (Alrededor de la línea 1307)

# app-38.py (Añadir esta ruta en cualquier parte, por ejemplo, cerca de /api/correcciones_pendientes)

@app.route('/api/correcciones/pendientes_detalle', methods=['GET'])
def get_correcciones_detalle():
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado"}), 403
    
    try:
        # CONSULTA: Obtener todas las solicitudes pendientes, incluyendo datos del alumno y solicitante
        url_requests = (
            f"{SUPABASE_URL}/rest/v1/solicitudes_correccion"
            f"?select=*,estudiantes_nomina(nombre,rut),doctoras(usuario)" # Asume que 'solicitante_id' es la FK a 'doctoras'
            f"&estado=eq.Pendiente"
            f"&order=fecha_solicitud.desc"
        )
        
        res = requests.get(url_requests, headers=SUPABASE_SERVICE_HEADERS)
        res.raise_for_status()
        solicitudes = res.json()
        
        # Procesamiento de datos para el frontend
        processed_requests = []
        for req in solicitudes:
            
            # Nota: Si usas una FK en solicitante_id a doctoras, Supabase lo une automáticamente.
            solicitante_usuario = req.get('doctoras', {}).get('usuario') if req.get('doctoras') else 'N/A'
            alumno_nombre = req.get('estudiantes_nomina', {}).get('nombre') if req.get('estudiantes_nomina') else 'Alumno Desconocido'
            alumno_rut = format_rut_python(req.get('estudiantes_nomina', {}).get('rut')) if req.get('estudiantes_nomina') else 'N/A'
            
            processed_requests.append({
                'id': req['id'],
                'alumno_nombre': alumno_nombre,
                'alumno_rut': alumno_rut,
                'detalles': req['detalles'],
                'solicitante': solicitante_usuario,
                'fecha': req['fecha_solicitud'].split('T')[0] if req.get('fecha_solicitud') else 'N/A', # Formato YYYY-MM-DD
                'estado': req['estado']
            })
            
        return jsonify({"success": True, "data": processed_requests})
        
    except requests.exceptions.RequestException as e:
        print(f"ERROR al obtener detalle de solicitudes: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con BD: {str(e)}"}), 500
        
@app.route('/api/correcciones_pendientes', methods=['GET'])
def get_correcciones_pendientes():
    # 1. Ajustar la verificación de rol
    # Supabase guarda el rol como 'admin', no 'administrador'
    if 'usuario' not in session or session.get('usuario') != 'admin': 
        return jsonify({"count": 0, "success": True}), 200
    
    try:
        # 2. La consulta debe usar requests directamente si no tienes el objeto supabase-py
        # Usaremos get_supabase_count o una consulta directa con Prefer: count=exact

        url_count = (
            f"{SUPABASE_URL}/rest/v1/solicitudes_correccion"
            f"?select=id"
            f"&estado=eq.Pendiente" # Filtro crucial por el estado
        )
        
        # Usamos requests para obtener el conteo exacto (requiere el header Prefer: count=exact)
        res = requests.get(url_count, headers=SUPABASE_SERVICE_HEADERS)
        res.raise_for_status()
        
        # Leemos el conteo del Content-Range header
        content_range = res.headers.get("Content-Range")
        count_data = 0
        if content_range and '/' in content_range:
            count_data = int(content_range.split('/')[-1])
            
        print(f"DEBUG: Solicitudes Pendientes encontradas: {count_data}")

        return jsonify({
            "success": True, 
            "count": count_data 
        })

    except Exception as e:
        print(f"ERROR al consultar correcciones pendientes: {e}")
        return jsonify({"success": False, "count": 0, "message": "Error interno al consultar la base de datos."}), 500
        
# ==================================================================================
# RUTA /api/correccion/solicitar (ACTUALIZADA PARA USAR requests)
# ==================================================================================

# ==================================================================================
# RUTA /api/correccion/solicitar (SOLUCIÓN DEFINITIVA Y FINAL)
# ==================================================================================
# ==================================================================================
# RUTA /api/correccion/solicitar (SOLUCIÓN FINAL CON COLUMNAS SIMPLES)
# ==================================================================================
# ==================================================================================
# RUTA /api/correccion/solicitar (SOLUCIÓN FINAL CON COLUMNA SOLICITANTE_ID)
# ==================================================================================
@app.route('/api/correccion/solicitar', methods=['POST'])
def solicitar_correccion():
    # 1. Verificar sesión con la clave 'usuario_id'
    usuario_solicitante_id = session.get('usuario_id')
    
    if not usuario_solicitante_id:
        return jsonify({"success": False, "message": "Acceso no autorizado. Debe iniciar sesión para solicitar una corrección."}), 403

    try:
        # 2. Obtener los datos enviados (JSON)
        data = request.get_json()
        
        alumno_id = data.get('alumno_id')
        detalles = data.get('detalles')
        
        if not alumno_id or not detalles:
            return jsonify({"success": False, "message": "Faltan campos requeridos (alumno_id o detalles)."}), 400

        # 3. Preparar el cuerpo de la petición para Supabase
        payload = {
            "alumno_id": alumno_id,
            "detalles": detalles,        
            "estado": "Pendiente", 
            
            # 🟢 CORRECCIÓN CLAVE: Usamos la nueva columna solicitante_id (tipo UUID)
            "solicitante_id": usuario_solicitante_id,  
            
            # Nota: La columna "id" (clave primaria) se dejará para que Supabase la autogenere.
        }
        
        # 4. Enviar la petición POST al endpoint de Supabase
        url_supabase_insert = f"{SUPABASE_URL}/rest/v1/solicitudes_correccion"
        res = requests.post(url_supabase_insert, headers=SUPABASE_SERVICE_HEADERS, json=payload)
        
        # 5. Manejar la respuesta
        res.raise_for_status() 
        
        if res.status_code == 201:
            return jsonify({"success": True, "message": "Solicitud enviada correctamente."}), 201
        else:
            return jsonify({"success": False, "message": f"Error desconocido al insertar. Código: {res.status_code}"}), 500

    except requests.exceptions.HTTPError as http_err:
        print(f"❌ Error HTTP de Supabase: {http_err}. Respuesta: {http_err.response.text}")
        return jsonify({"success": False, "message": f"Error de Base de Datos (Supabase). Detalles: {http_err.response.text}"}), 500
        
    except Exception as e:
        print(f"❌ ERROR al procesar solicitud de corrección: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor. Detalle: {str(e)}"}), 500

# app-38.py (Añadir esta ruta)

@app.route('/api/correcciones/actualizar_estado', methods=['POST'])
def actualizar_estado_correccion():
    if session.get('usuario') != 'admin':
        return jsonify({"success": False, "message": "Acceso denegado"}), 403
    
    try:
        data = request.get_json()
        request_id = data.get('request_id')
        nuevo_estado = data.get('estado') # 'Aprobada' o 'Rechazada'

        if not request_id or nuevo_estado not in ['Aprobada', 'Rechazada']:
            return jsonify({"success": False, "message": "Datos de entrada inválidos"}), 400

        # 1. Preparar el payload de actualización
        update_data = {
            "estado": nuevo_estado,
            "fecha_resolucion": str(date.today()), 
            # Opcional: Podrías añadir un campo 'admin_id'
        }

        # 2. Enviar la petición PATCH a Supabase
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/solicitudes_correccion?id=eq.{request_id}",
            headers=SUPABASE_SERVICE_HEADERS, 
            json=update_data
        )
        response.raise_for_status()

        return jsonify({"success": True, "message": "Estado actualizado"})

    except requests.exceptions.RequestException as e:
        print(f"ERROR al actualizar estado de corrección: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con BD: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR inesperado al actualizar estado: {e}")
        return jsonify({"success": False, "message": f"Error interno: {str(e)}"}), 500
        
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
    proyecto_id_from_form = request.form.get('proyecto_id', '').strip()
    
    # Obtener IDs de coordinación
    coord_general_id_from_form = request.form.get('coord_general_id', '').strip()
    coord_escuela_id_from_form = request.form.get('coord_escuela_id', '').strip()

    proyecto_id_db = proyecto_id_from_form if proyecto_id_from_form else None    
    
    tipo_nomina_normalized = tipo_nomina_raw.strip().lower() if tipo_nomina_raw else ''
    
    form_type = None
    if 'neurologia' in tipo_nomina_normalized: 
        form_type = 'neurologia'
    elif 'familiar' in tipo_nomina_normalized or 'medicina familiar' in tipo_nomina_normalized: 
        form_type = 'medicina_familiar'
    # 🟢 CORRECCIÓN DE INDENTACIÓN (Asegurado que esté alineado con los 'elif' anteriores)
    elif 'informe' in tipo_nomina_normalized and 'neuro' in tipo_nomina_normalized:
        form_type = 'informe_neurologico'
    # -----------------------------------------------------------------------------------
        
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
        "establecimiento_id": None,
        "proyecto_id": proyecto_id_db,
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
            # Usar .get() en el DataFrame con el nombre de columna mapeado
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

            # Pre-cálculo de edad y sexo (necesario para el nuevo Informe Neurológico)
            fecha_nac_obj = datetime.strptime(fecha_nac_str, '%Y-%m-%d').date()
            edad_calculada = calculate_age(fecha_nac_obj)
            sexo_adivinado = guess_gender(str(nombre_completo_raw))
            
            nacionalidad_valor = str(nacionalidad_raw).strip() if pd.notna(nacionalidad_raw) else 'Chilena'

            estudiante = {
                "nomina_id": nomina_id,
                "nombre": str(nombre_completo_raw).strip(),
                "rut": rut_limpio,
                "fecha_nacimiento": fecha_nac_str, 
                "nacionalidad": nacionalidad_valor,
                "sexo": sexo_adivinado,
                "edad": edad_calculada, # Añadir edad calculada
                "fecha_relleno": None,
            }
            # 🟢 Añadir flag específico si es el nuevo tipo de informe (para pre-relleno en DB)
            if form_type == 'informe_neurologico':
                 # Esto es redundante si form_type es 'informe_neurologico', pero asegura que si la tabla tiene un flag específico, se llene.
                 estudiante["tipo_registro_individual"] = "INFORME_NEURO" 
            
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
        # 1. CONSULTA ÚNICA: DATOS COMPLETOS DEL ESTUDIANTE (Select ALL FIELDS)
        url_student_data = (
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
            f"?id=eq.{alumno_id}"
            f"&select=id,nombre,rut,fecha_nacimiento,nacionalidad,sexo,estado_general,diagnostico,derivaciones,fecha_evaluacion,fecha_reevaluacion,fecha_relleno,diagnostico_1,diagnostico_2,diagnostico_complementario,clasificacion,observacion_1,observacion_2,observacion_3,observacion_4,observacion_5,observacion_6,observacion_7,check_cesarea,check_atermino,check_vaginal,check_prematuro,check_acorde,check_retrasogeneralizado,check_esquemac,check_esquemai,check_alergiano,check_alergiasi,check_cirugiano,check_cirugiasi,check_visionsinalteracion,check_visionrefraccion,check_audicionnormal,check_hipoacusia,check_tapondecerumen,check_sinhallazgos,check_caries,check_apinamientodental,check_retenciondental,check_frenillolingual,check_hipertrofia,altura,peso,imc,indicaciones,doctora_evaluadora_id,nomina_id,clasificacion_imc,motivo_consulta,observaciones,observacion_neurologia" 
        )
        res_student = requests.get(url_student_data, headers=SUPABASE_SERVICE_HEADERS)
        res_student.raise_for_status() 
        student_data = res_student.json()

        if not student_data or not student_data[0].get('fecha_relleno'):
            flash(f"❌ Alumno ID {alumno_id} no encontrado o no evaluado.", 'error')
            return redirect(url_for('dashboard'))

        est = student_data[0]
        nomina_id_fk = est.get('nomina_id') 
        
        # 2. CONSULTA 2: METADATA DE LA NÓMINA
        url_nomina_meta = (
            f"{SUPABASE_URL}/rest/v1/nominas_medicas"
            f"?id=eq.{nomina_id_fk}"
            f"&select=form_type,nombre_nomina,doctora_id_para_formulario"
        )
        res_nomina = requests.get(url_nomina_meta, headers=SUPABASE_SERVICE_HEADERS)
        res_nomina.raise_for_status()
        nomina_meta = res_nomina.json()[0] if res_nomina.json() else {}
        
        form_type = nomina_meta.get('form_type', 'neurologia')
        nombre_nomina = nomina_meta.get('nombre_nomina', 'Valoracion')
        doctora_evaluadora_id = est.get('doctora_evaluadora_id')
        doctora_id_para_formulario = nomina_meta.get('doctora_id_para_formulario')
        
        # 4. LÓGICA DE PLANTILLA (Selección del PDF)
        pdf_base_path = ''
        base_dir = os.path.dirname(os.path.abspath(__file__))
        full_pdf_bases_dir_path = os.path.join(base_dir, PDF_BASES_NEUROLOGIA_DIR)

        if form_type == 'neurologia':
            doc_id_for_pdf = doctora_id_para_formulario or doctora_evaluadora_id
            specific_pdf_filename = f"FORMULARIO TIPO NEUROLOGIA_{doc_id_for_pdf}.pdf"
            specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)

            if doc_id_for_pdf and os.path.exists(specific_pdf_path):
                pdf_base_path = specific_pdf_path
            else:
                pdf_base_path = os.path.join(base_dir, PDF_BASE_NEUROLOGIA)

        elif form_type == 'informe_neurologico':
            doc_id_for_pdf = doctora_id_para_formulario or doctora_evaluadora_id
            specific_pdf_filename = f"INFORME_NEUROLOGICO_BASE_{doc_id_for_pdf}.pdf"
            specific_pdf_path = os.path.join(full_pdf_bases_dir_path, specific_pdf_filename)

            if doc_id_for_pdf and os.path.exists(specific_pdf_path):
                pdf_base_path = specific_pdf_path
            else:
                pdf_base_path = os.path.join(base_dir, PDF_BASE_INFORME_NEURO)
                
        elif form_type == 'medicina_familiar':
            pdf_base_path = os.path.join(base_dir, PDF_BASE_FAMILIAR)
        
        else:
            raise FileNotFoundError(f"Tipo de formulario no reconocido: {form_type}")
        
        if not os.path.exists(pdf_base_path):
            raise FileNotFoundError(f"Archivo base del formulario no encontrado: {pdf_base_path}")
            
        print(f"DEBUG: Usando PDF Base Path: {pdf_base_path}") 


        # 5. INICIALIZAR EL RELLENADOR DE PDF
        reader = PdfReader(pdf_base_path) 
        writer = PdfWriter()
        
        # Iterar sobre las páginas
        for page in reader.pages:
            writer.add_page(page)

        # 6. Preparar y Mapear Campos del PDF 
        nombre = est.get('nombre', '')
        rut = format_rut_python(est.get('rut', ''))
        
        # --- FUNCIÓN AUXILIAR PARA MAPEO TEXTO A '/Yes' ---
        def map_db_value_to_yes_pdf(db_value):
            if db_value is True or (isinstance(db_value, str) and db_value.strip()):
                return "/Yes" 
            return ""

        # --- Cálculo de campos y formato de fechas ---
        edad = calculate_age(datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date()) if est.get('fecha_nacimiento') else 'N/A'
        fecha_nac_formato = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').strftime('%d/%m/%Y') if est.get('fecha_nacimiento') else ''
        fecha_evaluacion_formatted = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y') if est.get('fecha_evaluacion') else ''
        fecha_reeval_pdf = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').strftime('%d/%m/%Y') if est.get('fecha_reevaluacion') else ''
        
        # --- Mapeo General ---
        campos = {}
        
        if form_type == 'neurologia':
            # Mapeo COMPLETO de campos de Neurología (Antigua)
            campos = {
                "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac_formato, 
                "nacionalidad": est.get('nacionalidad', ''), "edad": edad, 
                "diagnostico_1": est.get('diagnostico', ''), "diagnostico_2": est.get('diagnostico', ''), 
                "estado_general": est.get('estado_general', ''), "derivaciones": est.get('derivaciones', ''),
                "fecha_evaluacion": fecha_evaluacion_formatted, "fecha_reevaluacion": fecha_reeval_pdf,
                "sexo_f": "X" if est.get('sexo') == "F" else "", "sexo_m": "X" if est.get('sexo') == "M" else "",
            }
        
        elif form_type == 'informe_neurologico':
            # 🟢 Mapeo Informe Neurológico (USANDO NOMBRES EXACTOS DE LAS COLUMNAS DE TU DB)
            campos = {
                "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac_formato, 
                "edad": edad, "nacionalidad": est.get('nacionalidad', ''), 
                "genero_m": "X" if est.get('sexo') == "M" else "", "genero_f": "X" if est.get('sexo') == "F" else "",
                
                # CAMPOS CRÍTICOS DE TEXTO - Mapeo Directo 
                "motivo_consulta": est.get('motivo_consulta', ''),
                "observaciones": est.get('observaciones', ''),      
                "observacion_neurologia": est.get('observacion_neurologia', ''), 
                
                "diagnostico": est.get('diagnostico', ''),
                "indicaciones": est.get('indicaciones', ''),
                "derivaciones": est.get('derivaciones', ''), 
                "fecha_evaluacion": fecha_evaluacion_formatted,
                "fecha_reevaluacion": fecha_reeval_pdf, 
            }
        
        elif form_type == 'medicina_familiar':
            # 🟢 MAPEO COMPLETO DE MEDICINA FAMILIAR - RESTAURADO A MÁXIMA EXTENSIÓN
             campos = {
                "nombre": nombre, "rut": rut, "fecha_nacimiento": fecha_nac_formato, "edad": edad, "nacionalidad": est.get('nacionalidad', ''),
                "sexo_f": "X" if est.get('sexo') == "F" else "", "sexo_m": "X" if est.get('sexo') == "M" else "",
                
                "diagnostico_1": est.get('diagnostico_1', ''), "diagnostico_2": est.get('diagnostico_2', ''),
                "diagnostico_complementario": est.get('diagnostico_complementario', ''), "clasificacion": est.get('clasificacion_imc', ''),
                "indicaciones": est.get('indicaciones', ''), "derivaciones": est.get('derivaciones', ''),
                "fecha_evaluacion": fecha_evaluacion_formatted, "fecha_reevaluacion": fecha_reeval_pdf,
                
                "altura": est.get('altura', ''), "peso": est.get('peso', ''), "I.M.C": est.get('imc', ''),
                "observacion_1": est.get('observacion_1', ''), "observacion_2": est.get('observacion_2', ''),
                "observacion_3": est.get('observacion_3', ''), "observacion_4": est.get('observacion_4', ''),
                "observacion_5": est.get('observacion_5', ''), "observacion_6": est.get('observacion_6', ''),
                "observacion_7": est.get('observacion_7', ''),
                
                # Checkboxes mapeados a /Yes (Incluyendo todos los de tu SELECT)
                "check_cesarea": map_db_value_to_yes_pdf(est.get('check_cesarea')), 
                "check_atermino": map_db_value_to_yes_pdf(est.get('check_atermino')),
                "check_vaginal": map_db_value_to_yes_pdf(est.get('check_vaginal')), 
                "check_prematuro": map_db_value_to_yes_pdf(est.get('check_prematuro')),
                "check_acorde": map_db_value_to_yes_pdf(est.get('check_acorde')), 
                "check_retraso": map_db_value_to_yes_pdf(est.get('check_retraso')),
                "check_retrasogeneralizado": map_db_value_to_yes_pdf(est.get('check_retrasogeneralizado')), 
                "check_esquemac": map_db_value_to_yes_pdf(est.get('check_esquemac')), 
                "check_esquemai": map_db_value_to_yes_pdf(est.get('check_esquemai')), 
                "check_alergiano": map_db_value_to_yes_pdf(est.get('check_alergiano')), 
                "check_alergiasi": map_db_value_to_yes_pdf(est.get('check_alergiasi')), 
                "check_cirugiano": map_db_value_to_yes_pdf(est.get('check_cirugiano')), 
                "check_cirugiasi": map_db_value_to_yes_pdf(est.get('check_cirugiasi')), 
                "check_visionsinalteracion": map_db_value_to_yes_pdf(est.get('check_visionsinalteracion')), 
                "check_visionrefraccion": map_db_value_to_yes_pdf(est.get('check_visionrefraccion')),
                "check_audicionnormal": map_db_value_to_yes_pdf(est.get('check_audicionnormal')), 
                "check_hipoacusia": map_db_value_to_yes_pdf(est.get('check_hipoacusia')), 
                "check_tapondecerumen": map_db_value_to_yes_pdf(est.get('check_tapondecerumen')), 
                "check_sinhallazgos": map_db_value_to_yes_pdf(est.get('check_sinhallazgos')), 
                "check_caries": map_db_value_to_yes_pdf(est.get('check_caries')), 
                "check_apinamientodental": map_db_value_to_yes_pdf(est.get('check_apinamientodental')), 
                "check_retenciondental": map_db_value_to_yes_pdf(est.get('check_retenciondental')), 
                "check_frenillolingual": map_db_value_to_yes_pdf(est.get('check_frenillolingual')), 
                "check_hipertrofia": map_db_value_to_yes_pdf(est.get('check_hipertrofia')),
            }


        # 7. Llenado final del PDF y send_file
        if "/AcroForm" not in writer._root_object:
            writer._root_object.update({
                NameObject("/AcroForm"): DictionaryObject()
            })
            
        # 💡 Esta parte asegura que todos los campos de todas las páginas se actualicen
        for page in writer.pages:
            writer.update_page_form_field_values(page, campos)
            
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        # Nombre del archivo para la descarga
        nombre_archivo_descarga = f"Valoracion_{nombre.replace(' ', '_')}_{rut}_{nombre_nomina.replace(' ', '_')}.pdf"
        
        return send_file(output, as_attachment=True, download_name=nombre_archivo_descarga, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al obtener datos de Supabase para PDF: {e}")
        flash(f"❌ Error al generar PDF: Fallo de conexión/consulta. Detalles: {e}. Revise el log para las columnas.", 'error')
        return redirect(url_for('dashboard'))
    except FileNotFoundError as e:
        # Esto atrapará si el PDF_BASE_INFORME_NEURO no existe
        print(f"❌ Error File Not Found: {e}")
        flash(f"❌ Error al generar el PDF: Archivo base no encontrado. Detalle: {e}", 'error')
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Error inesperado al generar PDF de alumno: {e}")
        flash(f"❌ Error inesperado al generar el PDF. Detalle: {e}", 'error')
        return redirect(url_for('dashboard'))
        
# app-30.py (Define esta ruta después de las funciones auxiliares)

# app-30.py (Define esta ruta después de las funciones auxiliares)

# app-30.py (Define esta ruta después de las funciones auxiliares)

# app-30.py (Reemplaza la función /api/dashboard_counts completa)
# app-30.py (Reemplaza la función /api/dashboard_counts completa y final)
# app-30.py (Reemplaza la función /api/dashboard_counts FINAL)
# app-30.py (Reemplaza la función /api/dashboard_counts FINAL)
# app-30.py (Reemplaza la función /api/dashboard_counts con la versión final basada en estado_general)
# app-30.py (Reemplaza la función /api/dashboard_counts con la versión de CONTEO INVERSO)
# app-30.py (Reemplaza la función /api/dashboard_counts con la versión de RESTA POR ESPECIALIDAD)
# app-30.py (Reemplaza la función /api/dashboard_counts con la versión HÍBRIDA FINAL)
# app-30.py (Reemplaza la función /api/dashboard_counts con la versión FINAL BASADA EN CONTEO DIRECTO)
# app-30.py (Versión de CONTINGENCIA FINAL)
# Asegúrate de que las importaciones de requests, uuid, y el resto estén al inicio de app.py
# from datetime import datetime, date  <-- CRÍTICO
# import requests
# import uuid
# ...

# Asegúrate de que las importaciones de requests, uuid, y datetime estén al inicio de app.py

# Reemplaza la función dashboard_counts en app.py con esta versión:

# Asegúrate de que las importaciones de requests, uuid, y datetime estén al inicio de app.py
# from datetime import datetime, date  <-- CRÍTICO
# import requests 
# import uuid
# ...

# Asegúrate de que las importaciones de requests, uuid, y datetime estén al inicio de app.py
# y que la función get_supabase_count esté definida.

# app.py (Reemplazo de la función dashboard_counts)

# app.py (Reemplazo de la función dashboard_counts)

# app.py (Reemplazo de la función dashboard_counts)

# app.py (Reemplazo de la función dashboard_counts)

# app.py (Reemplazo de la función dashboard_counts completa)

# app.py (Reemplazo de la función dashboard_counts completa)

# app.py (Reemplazo de la función dashboard_counts completa)

# app.py (Reemplazo de la función dashboard_counts completa)

# app.py (Reemplazo de la función dashboard_counts completa)

# app.py (Reemplazo de la función dashboard_counts completa)

@app.route('/api/dashboard_counts', methods=['GET'])
def dashboard_counts():
    print("🔍 Iniciando cálculo de dashboard_counts...")

    user_role = session.get('usuario')
    user_id = session.get('usuario_id')

    if not user_role or not user_id:
        print("❌ Usuario no autenticado")
        return jsonify({"error": "Usuario no autenticado", "success": False}), 401

    if user_role not in ['coordinadora', 'coordinadora_general', 'coordinador_general', 'admin']:
        print("❌ Usuario sin permisos")
        return jsonify({"error": "Permisos insuficientes", "success": False}), 403

    # --- CONSULTA DE NOMINAS MEDICAS ---
    try:
        if user_role == 'admin':
            url_nominas = f"{SUPABASE_URL}/rest/v1/nominas_medicas?select=id,tipo_nomina"
        else:
            url_nominas = (
                f"{SUPABASE_URL}/rest/v1/nominas_medicas?"
                f"coord_general_id=eq.{user_id}&select=id,tipo_nomina"
            )

        print("DEBUG URL NOMINAS:", url_nominas)

        res_n = requests.get(url_nominas, headers=SUPABASE_SERVICE_HEADERS)
        res_n.raise_for_status()
        nominas = res_n.json()

        print("NOMINAS RECIBIDAS:", nominas)

    except Exception as e:
        print("❌ Error al obtener nóminas:", e)
        return jsonify({"success": False, "error": str(e)}), 500

    # Desduplicar por id (por si acaso)
    nominas_unicas = { n["id"]: n for n in nominas if n.get("id") }
    nominas = list(nominas_unicas.values())

    # --- CONTADORES ---
    total_evaluados = 0
    total_pendientes = 0
    neuro_count = 0
    familiar_count = 0

    for nom in nominas:

        nom_id = nom.get("id")
        tipo = (nom.get("tipo_nomina") or "").lower().strip()

        if not nom_id:
            continue

        evaluados = get_supabase_count(
            f"nomina_id=eq.{nom_id}&evaluado_flag=eq.true"
        )

        pendientes = get_supabase_count(
            f"nomina_id=eq.{nom_id}&evaluado_flag=eq.false"
        )

        print(f"DEBUG NOMINA {nom_id} → {tipo} | Evaluados={evaluados}, Pendientes={pendientes}")

        total_evaluados += evaluados
        total_pendientes += pendientes

        if "neuro" in tipo:
            neuro_count += evaluados
        elif "familiar" in tipo or "medicina" in tipo:
            familiar_count += evaluados

    return jsonify({
        "success": True,
        "total_evaluados": total_evaluados,
        "evaluaciones_pendientes": total_pendientes,
        "neurologia_count": neuro_count,
        "familiar_count": familiar_count
    })

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
    if session.get('usuario') != 'admin':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('dashboard'))

    # 1. Obtener datos del formulario
    nombre = request.form.get('nombre_proyecto', '').strip()
    descripcion = request.form.get('descripcion_proyecto', '').strip()
    
    # Obtenemos el ID del admin de la sesión para cumplir con la Foreign Key
    admin_id = session.get('usuario_id') 
    
    if not nombre:
        flash('❌ El nombre del proyecto es obligatorio.', 'error')
        return redirect(url_for('dashboard'))

    # 2. Payload con nombres largos (como confirmaste)
    payload = {
        "nombre_proyecto": nombre,
        "descripcion_proyecto": descripcion,
        "doctora_id": admin_id  # <--- Esto evita el error de la Foreign Key
    }

    try:
        proyectos_url = f"{SUPABASE_URL}/rest/v1/proyectos"
        response = requests.post(proyectos_url, json=payload, headers=SUPABASE_SERVICE_HEADERS)
        
        if response.status_code not in [200, 201]:
            print(f"❌ ERROR SUPABASE ({response.status_code}): {response.text}")
            flash(f"Error al guardar: {response.text}", 'error')
        else:
            flash(f"✅ Proyecto '{nombre}' creado con éxito.", 'success')
        
    except Exception as e:
        print(f"❌ ERROR CRÍTICO: {e}")
        flash(f"Error inesperado: {str(e)}", 'error')

    return redirect(url_for('dashboard'))
    
# app.py (Nueva ruta)

# app.py

# Asegúrate de que las siguientes líneas estén importadas al inicio de app.py:
# from datetime import datetime, date
# import uuid
# import requests
# ...

@app.route('/agregar_alumno_manual', methods=['POST'])
def agregar_alumno_manual():
    """
    Ruta para que una doctora agregue manualmente un nuevo estudiante a su nómina.
    El estudiante se marca automáticamente como 'evaluado' y 'agregado_manual'.
    """
    # 1. Verificar sesión y tipo de usuario
    if 'usuario' not in session or session.get('tipo_usuario') != 'doctora':
        return jsonify({"success": False, "message": "Acceso denegado. Debe ser una doctora."}), 401

    try:
        data = request.json
        # Datos requeridos del formulario HTML
        nombre = data.get('nombre')
        rut = data.get('rut')
        fecha_nac_str = data.get('fecha_nacimiento')
        nomina_id = data.get('nomina_id')
        doctora_id = session.get('usuario_id')
        
        if not all([nombre, rut, fecha_nac_str, nomina_id, doctora_id]):
            return jsonify({"success": False, "message": "Faltan campos requeridos. Por favor, complete todos los campos."}), 400

        # 2. Procesar datos (reutilizando funciones existentes)
        rut_formateado = format_rut_python(rut) # Función existente
        
        try:
            fecha_nac = datetime.strptime(fecha_nac_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"success": False, "message": "Formato de fecha de nacimiento inválido."}), 400
        
        edad_calculada = calculate_age(fecha_nac) # Función existente
        sexo_adivinado = guess_gender(nombre) # Función existente

        # 3. Preparar datos para Supabase
        new_estudiante_id = str(uuid.uuid4()) # Generar un ID único
        
        payload = {
            "id": new_estudiante_id,
            "nomina_id": nomina_id,
            "nombre": nombre,
            "rut": rut_formateado,
            "fecha_nacimiento_formato": fecha_nac.strftime('%d/%m/%Y'),
            "fecha_nacimiento": fecha_nac_str,
            "edad": edad_calculada,
            "nacionalidad": data.get('nacionalidad', 'Chilena'), 
            "sexo": sexo_adivinado,
            "evaluado_flag": True, # CRÍTICO: Marcado como evaluado
            "agregado_manual": True, # CRÍTICO: Flag manual
            "fecha_evaluacion": date.today().isoformat(), # Fecha de registro/evaluación
            "doctora_evaluadora_id": doctora_id,
            "estado_general": "Pendiente", # Estado inicial
            # Dejar otros campos (diagnostico, etc.) en NULL/vacío para que la doctora los complete
        }

        # 4. Insertar en Supabase
        url_insert = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina"
        # Usamos SUPABASE_SERVICE_HEADERS para inserciones (asegura permisos)
        res = requests.post(url_insert, headers=SUPABASE_SERVICE_HEADERS, json=payload)
        res.raise_for_status()

        # 5. Respuesta exitosa (devolvemos los datos para actualizar la UI sin recargar)
        return jsonify({
            "success": True, 
            "message": f"Alumno '{nombre}' agregado y marcado como evaluado (Manual).",
            "estudiante_data": payload 
        })

    except requests.exceptions.HTTPError as e:
        print(f"❌ ERROR AL INSERTAR EN SUPABASE: {e} - {e.response.text}")
        return jsonify({"success": False, "message": f"Error al guardar el alumno en la base de datos. Verifique los datos o contacte a soporte."}), 500
    except Exception as e:
        print(f"❌ ERROR INESPERADO en /agregar_alumno_manual: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

# -------------------- FIN DE LA NUEVA RUTA --------------------        
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
