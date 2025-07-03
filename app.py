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
# Define los PDFs base para cada tipo de formulario
PDF_BASE_NEUROLOGIA = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'
PDF_BASE_FAMILIAR = 'formulario_familiar.pdf' # Asegúrate de que este archivo PDF exista en tu proyecto

# -------------------- Supabase Configuration --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rbzxolreglwndvsrxhmg.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nI...")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nI...")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

SUPABASE_SERVICE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}


# -------------------- Google Drive API Configuration --------------------
# Credenciales de Google Drive (deben ser manejadas de forma segura, ej. en variables de entorno)
# CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI") # Debe coincidir con el configurado en Google Cloud Console

# SCOPES = ['https://www.googleapis.com/auth/drive.file'] # Permiso para crear y editar archivos
# creds = None # Se inicializará con las credenciales del usuario

# Función para verificar si el usuario está autenticado
def login_required(f):
    def wrap(*args, **kwargs):
        if 'usuario' not in session:
            flash("Debes iniciar sesión para acceder a esta página.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__ # Importante para Flask
    return wrap

# Ruta de inicio de sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Verificar credenciales en Supabase
        try:
            # Primero, obtener el usuario por nombre de usuario
            user_url = f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{username}&select=*"
            user_res = requests.get(user_url, headers=SUPABASE_SERVICE_HEADERS)
            user_res.raise_for_status()
            users = user_res.json()

            if users:
                user = users[0]
                # Comparar la contraseña (en un entorno real, usa hashing de contraseñas)
                if user['password'] == password: # ¡ADVERTENCIA: Esto no es seguro para producción!
                    session['usuario'] = user['username']
                    session['user_id'] = user['id'] # Guardar el ID del usuario en sesión
                    session['establecimiento'] = user['establecimiento'] # Guardar el establecimiento en sesión
                    flash("¡Inicio de sesión exitoso!", "success")
                    return redirect(url_for('dashboard'))
                else:
                    flash("Contraseña incorrecta.", "error")
            else:
                flash("Nombre de usuario no encontrado.", "error")
        except requests.exceptions.RequestException as e:
            flash(f"Error de conexión con la base de datos: {e}", "error")
        except Exception as e:
            flash(f"Ocurrió un error inesperado: {e}", "error")

    return render_template('login-2.html')

# Ruta de cierre de sesión
@app.route('/logout')
def logout():
    session.pop('usuario', None)
    session.pop('user_id', None)
    session.pop('establecimiento', None)
    session.pop('current_nomina_id', None) # Limpiar la nómina actual al cerrar sesión
    flash("Has cerrado sesión correctamente.", "info")
    return redirect(url_for('login'))

# Ruta del dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    establecimiento = session.get('establecimiento')

    if not user_id:
        flash("ID de usuario no encontrado en la sesión.", "error")
        return redirect(url_for('login'))

    try:
        # Obtener nóminas asociadas al establecimiento del usuario
        nominas_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?establecimiento=eq.{establecimiento}&select=*"
        nominas_res = requests.get(nominas_url, headers=SUPABASE_SERVICE_HEADERS)
        nominas_res.raise_for_status()
        nominas = nominas_res.json()

        # Obtener el conteo de estudiantes por nómina para el dashboard
        # Esto es más eficiente que obtener todos los estudiantes y contarlos en Flask
        estudiantes_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?select=nomina_id,fecha_relleno"
        estudiantes_res = requests.get(estudiantes_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiantes_res.raise_for_status()
        all_estudiantes_data = estudiantes_res.json()

        nomina_counts = {}
        for nomina in nominas:
            nomina_id = nomina['id']
            total_estudiantes = 0
            evaluados = 0
            for est in all_estudiantes_data:
                if est['nomina_id'] == nomina_id:
                    total_estudiantes += 1
                    if est['fecha_relleno']:
                        evaluados += 1
            nomina_counts[nomina_id] = {
                'total': total_estudiantes,
                'evaluados': evaluados
            }

        return render_template('dashboard-7.html', nominas=nominas, establecimiento_nombre=establecimiento, nomina_counts=nomina_counts)

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al cargar el dashboard: {e}", "error")
        return redirect(url_for('login'))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al cargar el dashboard: {e}", "error")
        return redirect(url_for('login'))

# Ruta para crear una nueva nómina
@app.route('/crear_nomina', methods=['POST'])
@login_required
def crear_nomina():
    nombre_nomina = request.form['nombre_nomina']
    tipo_nomina = request.form['tipo_nomina'] # 'NEUROLOGIA' o 'FAMILIAR'
    form_type = request.form['form_type'] # 'neurologia' o 'medicina_familiar'
    establecimiento = session.get('establecimiento')
    user_id = session.get('user_id')

    if not nombre_nomina or not tipo_nomina or not form_type or not establecimiento or not user_id:
        flash("Todos los campos son obligatorios.", "error")
        return redirect(url_for('dashboard'))

    try:
        new_nomina = {
            "nombre_nomina": nombre_nomina,
            "tipo_nomina": tipo_nomina,
            "form_type": form_type,
            "establecimiento": establecimiento,
            "creada_por": user_id
        }
        res = requests.post(f"{SUPABASE_URL}/rest/v1/nominas_medicas", headers=SUPABASE_SERVICE_HEADERS, json=new_nomina)
        res.raise_for_status()
        flash("Nómina creada exitosamente.", "success")
    except requests.exceptions.RequestException as e:
        flash(f"Error al crear la nómina: {e}", "error")
    return redirect(url_for('dashboard'))

# Ruta para eliminar una nómina
@app.route('/eliminar_nomina/<nomina_id>', methods=['POST'])
@login_required
def eliminar_nomina(nomina_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("No autorizado.", "error")
        return jsonify({"success": False, "message": "No autorizado."}), 401

    try:
        # Verificar si la nómina pertenece al usuario/establecimiento (opcional pero recomendado)
        nomina_check_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=creada_por"
        nomina_check_res = requests.get(nomina_check_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_check_res.raise_for_status()
        nomina_data = nomina_check_res.json()

        if not nomina_data or nomina_data[0]['creada_por'] != user_id:
            flash("No tienes permiso para eliminar esta nómina.", "error")
            return jsonify({"success": False, "message": "No tienes permiso para eliminar esta nómina."}), 403

        # 1. Eliminar estudiantes asociados a la nómina
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
            flash("Nómina y sus estudiantes eliminados correctamente.", "success")
            return jsonify({"success": True, "message": "Nómina y sus estudiantes eliminados correctamente."})
        else:
            print(f"ERROR: Error inesperado al eliminar nómina. Status: {res_delete_nomina.status_code}, Response: {res_delete_nomina.text}")
            return jsonify({"success": False, "message": f"Error al eliminar la nómina: {res_delete_nomina.text}"}), 500

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de solicitud al eliminar nómina: {e}")
        flash(f"Error de conexión al eliminar nómina: {str(e)}", "error")
        return jsonify({"success": False, "message": f"Error de conexión al eliminar nómina: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al eliminar nómina: {e}")
        flash(f"Error inesperado al eliminar nómina: {str(e)}", "error")
        return jsonify({"success": False, "message": f"Error inesperado al eliminar nómina: {str(e)}"}), 500

# Ruta para subir archivo de estudiantes
@app.route('/subir_estudiantes/<nomina_id>', methods=['POST'])
@login_required
def subir_estudiantes(nomina_id):
    if 'file' not in request.files:
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for('dashboard'))

    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            filepath = os.path.join('/tmp', filename) # Usar /tmp para escritura temporal
            file.save(filepath)

            df = pd.read_excel(filepath) # Leer el archivo Excel

            estudiantes_a_insertar = []
            for index, row in df.iterrows():
                nombre_completo = str(row.get('Nombre Completo', '')).strip()
                rut = str(row.get('RUT', '')).strip()
                fecha_nacimiento_excel = row.get('Fecha de Nacimiento') # Puede ser datetime object o string
                nacionalidad = str(row.get('Nacionalidad', '')).strip()
                sexo = str(row.get('Sexo', '')).strip().upper() # 'M' o 'F'

                # Normalizar RUT (quitar puntos y guiones, dejar solo números y K)
                rut_normalized = unicodedata.normalize('NFKD', rut).encode('ascii', 'ignore').decode('utf-8')
                rut_normalized = rut_normalized.replace('.', '').replace('-', '').upper()

                # Convertir fecha de nacimiento a formato YYYY-MM-DD
                fecha_nacimiento_str = None
                if isinstance(fecha_nacimiento_excel, datetime):
                    fecha_nacimiento_str = fecha_nacimiento_excel.strftime('%Y-%m-%d')
                elif isinstance(fecha_nacimiento_excel, date):
                    fecha_nacimiento_str = fecha_nacimiento_excel.strftime('%Y-%m-%d')
                elif isinstance(fecha_nacimiento_excel, str):
                    try:
                        # Intentar parsear varios formatos comunes (DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD)
                        if '/' in fecha_nacimiento_excel:
                            fecha_nacimiento_str = datetime.strptime(fecha_nacimiento_excel, '%d/%m/%Y').strftime('%Y-%m-%d')
                        elif '-' in fecha_nacimiento_excel:
                            # Puede ser YYYY-MM-DD o DD-MM-YYYY, intentar ambos
                            try:
                                fecha_nacimiento_str = datetime.strptime(fecha_nacimiento_excel, '%Y-%m-%d').strftime('%Y-%m-%d')
                            except ValueError:
                                fecha_nacimiento_str = datetime.strptime(fecha_nacimiento_excel, '%d-%m-%Y').strftime('%Y-%m-%d')
                        else:
                            # Si es solo una cadena de números, intentar como YYYYMMDD o DDMMYYYY
                            if len(fecha_nacimiento_excel) == 8:
                                try:
                                    fecha_nacimiento_str = datetime.strptime(fecha_nacimiento_excel, '%Y%m%d').strftime('%Y-%m-%d')
                                except ValueError:
                                    fecha_nacimiento_str = datetime.strptime(fecha_nacimiento_excel, '%d%m%Y').strftime('%Y-%m-%d')
                    except ValueError:
                        fecha_nacimiento_str = None # Fallback si no se puede parsear

                if nombre_completo and rut_normalized and fecha_nacimiento_str:
                    estudiantes_a_insertar.append({
                        "nomina_id": nomina_id,
                        "nombre": nombre_completo,
                        "rut": rut_normalized,
                        "fecha_nacimiento": fecha_nacimiento_str,
                        "nacionalidad": nacionalidad if nacionalidad else None,
                        "sexo": sexo if sexo in ['M', 'F'] else None, # Asegurarse que solo M o F
                        "fecha_relleno": None # Inicialmente no rellenado
                    })
                else:
                    flash(f"Fila {index+2} omitida: Faltan datos obligatorios (Nombre Completo, RUT, Fecha de Nacimiento) o formato incorrecto.", "warning")

            if estudiantes_a_insertar:
                res = requests.post(f"{SUPABASE_URL}/rest/v1/estudiantes_nomina", headers=SUPABASE_SERVICE_HEADERS, json=estudiantes_a_insertar)
                res.raise_for_status()
                flash(f"Se agregaron {len(estudiantes_a_insertar)} estudiantes a la nómina.", "success")
            else:
                flash("No se encontraron estudiantes válidos en el archivo para agregar.", "warning")

        except Exception as e:
            flash(f"Error al procesar el archivo o subir estudiantes: {e}", "error")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath) # Limpiar el archivo temporal

    else:
        flash("Tipo de archivo no permitido. Solo se aceptan .xls, .xlsx, .csv.", "error")

    return redirect(url_for('dashboard'))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función auxiliar para calcular la edad
def calculate_age(born):
    if not born:
        return None, None
    today = date.today()
    born_date = datetime.strptime(born, '%Y-%m-%d').date()
    years = today.year - born_date.year - ((today.month, today.day) < (born_date.month, born_date.day))
    months = today.month - born_date.month
    if months < 0:
        months += 12
    return years, months

# Ruta para rellenar formularios
@app.route('/relleno_formularios/<nomina_id>', methods=['GET'])
@login_required
def relleno_formularios(nomina_id):
    user_id = session.get('user_id')
    establecimiento = session.get('establecimiento')
    session['current_nomina_id'] = nomina_id # Guardar la nómina actual en sesión

    print(f"DEBUG: Accediendo a /relleno_formularios con nomina_id: {nomina_id}")
    print(f"DEBUG: ID de usuario en sesión (doctora) para /relleno_formularios: {user_id}")

    if not user_id:
        flash("No autorizado.", "error")
        return redirect(url_for('login'))

    try:
        # Obtener información de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina,tipo_nomina,form_type"
        print(f"DEBUG: URL para obtener nómina en /relleno_formularios: {nomina_url}")
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_data = nominas_res.json()

        if not nomina_data:
            flash("Nómina no encontrada.", "error")
            return redirect(url_for('dashboard'))

        nomina_info = nomina_data[0]
        form_type = nomina_info.get('form_type', 'neurologia') # Default a neurologia si no está definido
        print(f"DEBUG: Datos de la nómina recibidos en /relleno_formularios: {nomina_data}")
        print(f"DEBUG: Tipo de formulario para esta nómina: {form_type}")

        # Obtener estudiantes de la nómina
        estudiantes_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&select=*"
        print(f"DEBUG: URL para obtener estudiantes en /relleno_formularios: {estudiantes_url}")
        estudiantes_res = requests.get(estudiantes_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiantes_res.raise_for_status()
        estudiantes_raw = estudiantes_res.json()
        print(f"DEBUG: Estudiantes raw recibidos en /relleno_formularios: {estudiantes_raw}")

        processed_estudiantes = []
        total_forms_completed = 0
        for est in estudiantes_raw:
            years, months = calculate_age(est.get('fecha_nacimiento'))
            edad_str = f"{years} años, {months} meses" if years is not None else "N/A"
            
            fecha_nacimiento_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
            fecha_nacimiento_formato = fecha_nacimiento_obj.strftime('%d/%m/%Y') if fecha_nacimiento_obj else "N/A"

            # Determinar el sexo para mostrar en la tabla principal
            sexo_display = est.get('sexo')
            if sexo_display is None: # Si no está en 'sexo', verificar los campos de Medicina Familiar
                if est.get('genero_f'):
                    sexo_display = 'F'
                elif est.get('genero_m'):
                    sexo_display = 'M'
            
            # Convertir 'M'/'F' a 'Masculino'/'Femenino' para display en tabla
            if sexo_display == 'M':
                sexo_display = 'Masculino'
            elif sexo_display == 'F':
                sexo_display = 'Femenino'
            else:
                sexo_display = 'N/A'


            processed_estudiante = {
                "id": est['id'],
                "nomina_id": est['nomina_id'],
                "nombre": est['nombre'],
                "rut": est['rut'],
                "fecha_nacimiento": est['fecha_nacimiento'], # YYYY-MM-DD para el backend
                "fecha_nacimiento_formato": fecha_nacimiento_formato, # DD/MM/YYYY para display
                "edad": edad_str,
                "nacionalidad": est.get('nacionalidad', 'N/A'),
                "sexo": sexo_display, # Sexo para display en la tabla
                "estado_general": est.get('estado_general'), # Campo de neurologia
                "diagnostico": est.get('diagnostico'), # Campo de neurologia
                "fecha_reevaluacion": est.get('fecha_reevaluacion'), # Campo de neurologia
                "derivaciones": est.get('derivaciones'), # Campo de neurologia
                "fecha_relleno": est.get('fecha_relleno'), # Fecha de rellenado (común)
                "doctora_evaluadora_id": est.get('doctora_evaluadora_id'),

                # Nuevos campos de Medicina Familiar (asegúrate de que existan en la DB y sean nullable)
                "genero_f": est.get('genero_f'),
                "genero_m": est.get('genero_m'),
                "diagnostico_1": est.get('diagnostico_1'),
                "diagnostico_2": est.get('diagnostico_2'),
                "clasificacion": est.get('clasificacion'),
                "fecha_evaluacion": est.get('fecha_evaluacion'),
                "fecha_reevaluacion_select": est.get('fecha_reevaluacion_select'), # El valor del select (1, 2, 3 años)
                "diagnostico_complementario": est.get('diagnostico_complementario'),
                "observacion_1": est.get('observacion_1'),
                "observacion_2": est.get('observacion_2'),
                "observacion_3": est.get('observacion_3'),
                "observacion_4": est.get('observacion_4'),
                "observacion_5": est.get('observacion_5'),
                "observacion_6": est.get('observacion_6'),
                "observacion_7": est.get('observacion_7'),
                "altura": est.get('altura'),
                "peso": est.get('peso'),
                "imc": est.get('imc'),
                "clasificacion_imc": est.get('clasificacion_imc'),
                "check_cesarea": est.get('check_cesarea'),
                "check_atermino": est.get('check_atermino'),
                "check_vaginal": est.get('check_vaginal'),
                "check_prematuro": est.get('check_prematuro'),
                "check_acorde": est.get('check_acorde'),
                "check_retrasogeneralizado": est.get('check_retrasogeneralizado'),
                "check_esquemac": est.get('check_esquemac'),
                "check_esquemai": est.get('check_esquemai'),
                "check_alergiano": est.get('check_alergiano'),
                "check_alergiasi": est.get('check_alergiasi'),
                "check_cirugiano": est.get('check_cirugiano'),
                "check_cirugiasi": est.get('check_cirugiasi'),
                "check_visionsinalteracion": est.get('check_visionsinalteracion'),
                "check_visionrefraccion": est.get('check_visionrefraccion'),
                "check_audicionnormal": est.get('check_audicionnormal'),
                "check_hipoacusia": est.get('check_hipoacusia'),
                "check_tapondecerumen": est.get('check_tapondecerumen'),
                "check_sinhallazgos": est.get('check_sinhallazgos'),
                "check_caries": est.get('check_caries'),
                "check_apinamientodental": est.get('check_apinamientodental'),
                "check_retenciondental": est.get('check_retenciondental'),
                "check_frenillolingual": est.get('check_frenillolingual'),
                "check_hipertrofia": est.get('check_hipertrofia'),
            }
            processed_estudiantes.append(processed_estudiante)
            if est.get('fecha_relleno'):
                total_forms_completed += 1

        print(f"DEBUG: Estudiantes procesados para plantilla en /relleno_formularios: {processed_estudiantes}")

        template_name = ''
        if form_type == 'neurologia':
            template_name = 'formulario_relleno-2.html'
        elif form_type == 'medicina_familiar':
            template_name = 'formulario_medicina_familiar.html'
        else:
            flash("Tipo de formulario no reconocido.", "error")
            return redirect(url_for('dashboard'))

        return render_template(template_name,
                               estudiantes=processed_estudiantes,
                               establecimiento_nombre=establecimiento,
                               total_forms_completed_for_nomina=total_forms_completed)

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al cargar estudiantes: {e}", "error")
        print(f"ERROR: Error en /relleno_formularios: {e}")
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al cargar los formularios: {e}", "error")
        print(f"ERROR: Error inesperado en /relleno_formularios: {e}")
        return redirect(url_for('dashboard'))


@app.route('/marcar_evaluado', methods=['POST'])
@login_required
def marcar_evaluado():
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    doctora_evaluadora_id = session.get('user_id')

    if not estudiante_id or not nomina_id or not doctora_evaluadora_id:
        return jsonify({"success": False, "message": "Datos incompletos para marcar como evaluado."}), 400

    # Determinar el tipo de formulario para saber qué campos actualizar
    # Primero, obtener el form_type de la nómina
    try:
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_data = nomina_res.json()
        if not nomina_data:
            return jsonify({"success": False, "message": "Nómina no encontrada."}), 404
        form_type = nomina_data[0].get('form_type', 'neurologia')
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error al obtener form_type de la nómina: {e}")
        return jsonify({"success": False, "message": "Error al verificar el tipo de formulario."}), 500

    update_data = {
        "fecha_relleno": datetime.now().isoformat(), # Fecha actual de rellenado
        "doctora_evaluadora_id": doctora_evaluadora_id
    }

    if form_type == 'neurologia':
        update_data.update({
            "estado_general": request.form.get('estado'),
            "diagnostico": request.form.get('diagnostico'),
            "fecha_reevaluacion": request.form.get('fecha_reevaluacion'),
            "derivaciones": request.form.get('derivaciones'),
            "sexo": request.form.get('sexo') # Asegurarse de que el sexo se actualice si se cambió en el formulario de neurología
        })
    elif form_type == 'medicina_familiar':
        # Campos de identificación (ya deberían estar en la DB, pero se pueden actualizar si es necesario)
        # update_data["nombre"] = request.form.get('nombre_apellido') # No se actualiza si es readonly
        # update_data["rut"] = request.form.get('rut') # No se actualiza si es readonly
        # update_data["fecha_nacimiento"] = request.form.get('fecha_nacimiento_original') # No se actualiza si es readonly
        # update_data["nacionalidad"] = request.form.get('nacionalidad') # No se actualiza si es readonly

        # Manejo de género (radio buttons en HTML, se guardan como booleanos o texto en Supabase)
        update_data["genero_f"] = request.form.get('genero_f') == 'Femenino'
        update_data["genero_m"] = request.form.get('genero_m') == 'Masculino'
        
        # Si solo uno está marcado, actualizar el campo 'sexo' principal para compatibilidad
        if update_data["genero_f"]:
            update_data["sexo"] = 'F'
        elif update_data["genero_m"]:
            update_data["sexo"] = 'M'
        else:
            update_data["sexo"] = None # O el valor por defecto que prefieras si ninguno está marcado

        # Campos de Motivo de Consulta
        update_data["diagnostico_1"] = request.form.get('diagnostico_1')
        update_data["diagnostico_2"] = request.form.get('diagnostico_2')
        update_data["clasificacion"] = request.form.get('clasificacion')
        update_data["derivaciones"] = request.form.get('derivaciones') # Este campo es común, pero se actualiza aquí

        # Examen del Estado de Salud General
        update_data["observacion_1"] = request.form.get('observacion_1') # Primera parte de las observaciones

        # Antecedentes Perinatales (checkboxes)
        update_data["check_cesarea"] = request.form.get('check_cesarea') == 'CESAREA'
        update_data["check_atermino"] = request.form.get('check_atermino') == 'A_TERMINO'
        update_data["check_vaginal"] = request.form.get('check_vaginal') == 'VAGINAL'
        update_data["check_prematuro"] = request.form.get('check_prematuro') == 'PREMATURO'
        update_data["observacion_2"] = request.form.get('observacion_2') # Observación de perinatales

        # DSM (checkboxes)
        update_data["check_acorde"] = request.form.get('check_acorde') == 'LOGRADO_ACORDE_A_LA_EDAD'
        update_data["check_retrasogeneralizado"] = request.form.get('check_retrasogeneralizado') == 'RETRASO_GENERALIZADO_DEL_DESARROLLO'
        update_data["observacion_3"] = request.form.get('observacion_3') # Observación de DSM

        # Vacunas (checkboxes)
        update_data["check_esquemac"] = request.form.get('check_esquemac') == 'ESQUEMA_COMPLETO'
        update_data["check_esquemai"] = request.form.get('check_esquemai') == 'ESQUEMA_INCOMPLETO'
        update_data["observacion_4"] = request.form.get('observacion_4') # Observación de Vacunas

        # Alergias (checkboxes)
        update_data["check_alergiano"] = request.form.get('check_alergiano') == 'NO_ALERGIAS'
        update_data["check_alergiasi"] = request.form.get('check_alergiasi') == 'SI_ALERGIAS'
        update_data["observacion_5"] = request.form.get('observacion_5') # Observación de Alergias

        # Antecedentes Personales (campo reutilizado)
        update_data["diagnostico_complementario"] = request.form.get('diagnostico_complementario')

        # Hospitalizaciones/Cirugías (checkboxes)
        update_data["check_cirugiano"] = request.form.get('check_cirugiano') == 'NO_CIRUGIAS'
        update_data["check_cirugiasi"] = request.form.get('check_cirugiasi') == 'SI_CIRUGIAS'
        update_data["observacion_6"] = request.form.get('observacion_6') # Observación de Hospitalizaciones

        # Visión (checkboxes)
        update_data["check_visionsinalteracion"] = request.form.get('check_visionsinalteracion') == 'SIN_ALTERACION_VISION'
        update_data["check_visionrefraccion"] = request.form.get('check_visionrefraccion') == 'VICIOS_DE_REFRACCION'
        update_data["observacion_7"] = request.form.get('observacion_7') # Observación de Visión

        # Audición (checkboxes)
        update_data["check_audicionnormal"] = request.form.get('check_audicionnormal') == 'NORMAL_AUDICION'
        update_data["check_hipoacusia"] = request.form.get('check_hipoacusia') == 'HIPOACUSIA'
        update_data["check_tapondecerumen"] = request.form.get('check_tapondecerumen') == 'TAPON_DE_CERUMEN'

        # Salud Bucodental (checkboxes)
        update_data["check_sinhallazgos"] = request.form.get('check_sinhallazgos') == 'SIN_HALLAZGOS'
        update_data["check_caries"] = request.form.get('check_caries') == 'CARIES'
        update_data["check_apinamientodental"] = request.form.get('check_apinamientodental') == 'APINAMIENTO_DENTAL'
        update_data["check_retenciondental"] = request.form.get('check_retenciondental') == 'RETENCION_DENTAL'
        update_data["check_frenillolingual"] = request.form.get('check_frenillolingual') == 'FRENILLO_LINGUAL'
        update_data["check_hipertrofia"] = request.form.get('check_hipertrofia') == 'HIPERTROFIA_AMIGDALINA'

        # Medidas Antropométricas
        update_data["altura"] = float(request.form.get('altura')) if request.form.get('altura') else None
        update_data["peso"] = float(request.form.get('peso')) if request.form.get('peso') else None
        update_data["imc"] = request.form.get('imc')
        update_data["clasificacion_imc"] = request.form.get('clasificacion_imc')
        
        # Fechas específicas de Medicina Familiar
        update_data["fecha_evaluacion"] = request.form.get('fecha_evaluacion')
        update_data["fecha_reevaluacion"] = request.form.get('fecha_reevaluacion') # Fecha calculada YYYY-MM-DD
        update_data["fecha_reevaluacion_select"] = request.form.get('fecha_reevaluacion_select') # Valor del select (1, 2, 3 años)


    try:
        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}",
            headers=SUPABASE_SERVICE_HEADERS,
            json=update_data
        )
        res.raise_for_status()
        return jsonify({"success": True, "message": "Evaluación guardada y marcada como completada."})
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error al actualizar estudiante {estudiante_id}: {e} - {res.text if 'res' in locals() else ''}")
        return jsonify({"success": False, "message": f"Error al guardar la evaluación: {e}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al marcar como evaluado: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {e}"}), 500


@app.route('/generar_pdf', methods=['POST'])
@login_required
def generar_pdf():
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')
    
    if not estudiante_id or not nomina_id:
        flash("Datos de estudiante o nómina incompletos para generar PDF.", "error")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))

    try:
        # Obtener datos completos del estudiante desde Supabase
        estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=*"
        estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiante_res.raise_for_status()
        estudiante_data = estudiante_res.json()

        if not estudiante_data:
            flash("Estudiante no encontrado para generar PDF.", "error")
            return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))
        
        est = estudiante_data[0]

        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            flash("Tipo de formulario no reconocido para generar PDF.", "error")
            return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))

        # Abrir el PDF base
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()

        # Iterar sobre las páginas del PDF base
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            writer.add_page(page)

            # Obtener campos del formulario PDF
            if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                for field in page["/AcroForm"]["/Fields"]:
                    field_name = field.get("/T")
                    if field_name:
                        field_name = str(field_name) # Convertir a string

                        # Rellenar campos comunes
                        if field_name == "Nombres y Apellidos":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos": est.get('nombre', '')})
                        elif field_name == "RUN":
                            writer.update_page_form_field_values(writer.pages[page_num], {"RUN": est.get('rut', '')})
                        elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                            fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                            writer.update_page_form_field_values(writer.pages[page_num], {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                        elif field_name == "Edad (en años y meses)":
                            years, months = calculate_age(est.get('fecha_nacimiento'))
                            writer.update_page_form_field_values(writer.pages[page_num], {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                        elif field_name == "Nacionalidad":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nacionalidad": est.get('nacionalidad', '')})
                        
                        # Campos específicos de Neurología
                        elif form_type == 'neurologia':
                            if field_name == "Sexo":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Sexo": est.get('sexo', '')})
                            elif field_name == "Estado general del alumno":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Estado general del alumno": est.get('estado_general', '')})
                            elif field_name == "Diagnostico":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Diagnostico": est.get('diagnostico', '')})
                            elif field_name == "Fecha reevaluacion":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                            elif field_name == "Derivaciones":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Derivaciones": est.get('derivaciones', '')})
                        
                        # Campos específicos de Medicina Familiar
                        elif form_type == 'medicina_familiar':
                            # Género (checkboxes en PDF)
                            if field_name == "F" and est.get('genero_f'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"F": "/Yes"})
                            elif field_name == "M" and est.get('genero_m'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"M": "/Yes"})
                            
                            # Motivo de Consulta
                            elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                            elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                            elif field_name == "Clasificación":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación": est.get('clasificacion', '')})
                            elif field_name == "INDICACIONES": # Campo para derivaciones
                                writer.update_page_form_field_values(writer.pages[page_num], {"INDICACIONES": est.get('derivaciones', '')})
                            
                            # Fechas
                            elif field_name == "Fecha evaluación":
                                fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                            elif field_name == "Fecha reevaluación":
                                # Usar el campo fecha_reevaluacion que ya debe estar en formato YYYY-MM-DD
                                # y convertirlo a DD/MM/YYYY para el PDF
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                            # Observaciones (OBS1 a OBS7)
                            # This block needs to be an 'if' or part of the main elif chain
                            # A simple way to integrate it is to check if field_name starts with 'OBS'
                            elif field_name.startswith("OBS"):
                                obs_index = int(field_name.replace("OBS", ""))
                                if 1 <= obs_index <= 7:
                                    writer.update_page_form_field_values(writer.pages[page_num], {field_name: est.get(f'observacion_{obs_index}', '')})
                            
                            # Antecedentes Perinatales (checkboxes)
                            elif field_name == "CESAREA" and est.get('check_cesarea'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CESAREA": "/Yes"})
                            elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"A TÉRMINO": "/Yes"})
                            elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VAGINAL": "/Yes"})
                            elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"PREMATURO": "/Yes"})
                            
                            # DSM (checkboxes)
                            elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                            elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                            # Vacunas (checkboxes)
                            elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA COMPLETO": "/Yes"})
                            elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA INCOMPLETO": "/Yes"})
                            
                            # Alergias (checkboxes)
                            elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO": "/Yes"})
                            elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI": "/Yes"})

                            # Hospitalizaciones/Cirugías (checkboxes)
                            elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO_2": "/Yes"})
                            elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI_2": "/Yes"})

                            # Visión (checkboxes)
                            elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN ALTERACIÓN": "/Yes"})
                            elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VICIOS DE REFRACCIÓN": "/Yes"})

                            # Audición (checkboxes)
                            elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"NORMAL": "/Yes"})
                            elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPOACUSIA": "/Yes"})
                            elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"TAPÓN DE CERUMEN": "/Yes"})

                            # Salud Bucodental (checkboxes)
                            elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN HALLAZGOS": "/Yes"})
                            elif field_name == "CARIES" and est.get('check_caries'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CARIES": "/Yes"})
                            elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"APIÑAMIENTO DENTAL": "/Yes"})
                            elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETENCIÓN DENTAL": "/Yes"})
                            elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"FRENILLO LINGUAL": "/Yes"})
                            elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPERTROFIA AMIGDALINA": "/Yes"})

                            # Medidas Antropométricas
                            elif field_name == "Altura":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Altura": str(est.get('altura', ''))})
                            elif field_name == "Peso":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Peso": str(est.get('peso', ''))})
                            elif field_name == "I.M.C":
                                writer.update_page_form_field_values(writer.pages[page_num], {"I.M.C": est.get('imc', '')})
                            elif field_name == "Clasificación_IMC": # Asumiendo un campo para la clasificación del IMC
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                            
                            # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                            elif field_name == "Nombres y Apellidos_Doctor":
                                # Obtener nombre de la doctora
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos_Doctor": doctor_name})
                            elif field_name == "Rut_Doctor":
                                # Asumiendo que el RUT de la doctora también está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Rut_Doctor": doctor_rut})
                            elif field_name == "Nº Registro Profesional":
                                # Asumiendo que el número de registro está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nº Registro Profesional": doctor_reg})
                            elif field_name == "Especialidad":
                                # Asumiendo que la especialidad está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Especialidad": doctor_esp})
                            elif field_name == "Fono/E-Mail Contacto":
                                # Asumiendo que el email está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fono/E-Mail Contacto": doctor_email})
                            elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Salud pública": "/Yes"})
                            elif field_name == "Particular" and est.get('procedencia_particular'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Particular": "/Yes"})
                            elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Escuela": "/Yes"})
                            elif field_name == "Otro" and est.get('procedencia_otro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Otro": "/Yes"})

        # Guardar el PDF en un buffer en memoria
        output_pdf = io.BytesIO()
        writer.write(output_pdf)
        output_pdf.seek(0)

        # Enviar el PDF como respuesta
        filename = f"formulario_{est.get('nombre', 'sin_nombre').replace(' ', '_')}_{form_type}.pdf"
        return send_file(output_pdf, download_name=filename, as_attachment=False, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al generar PDF: {e}", "error")
        print(f"ERROR: Error en /generar_pdf (Supabase): {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al generar el PDF: {e}", "error")
        print(f"ERROR: Error inesperado en /generar_pdf: {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))


@app.route('/descargar_excel_evaluados/<nomina_id>', methods=['GET'])
@login_required
def descargar_excel_evaluados(nomina_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("No autorizado.", "error")
        return redirect(url_for('login'))

    try:
        # Obtener estudiantes de la nómina que han sido evaluados
        estudiantes_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&fecha_relleno=not.is.null&select=*"
        estudiantes_res = requests.get(estudiantes_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiantes_res.raise_for_status()
        estudiantes_data = estudiantes_res.json()

        if not estudiantes_data:
            flash("No hay estudiantes evaluados en esta nómina para descargar.", "info")
            return redirect(url_for('relleno_formularios', nomina_id=nomina_id))

        # Convertir la lista de diccionarios a un DataFrame de pandas
        df = pd.DataFrame(estudiantes_data)

        # Seleccionar y reordenar columnas para el Excel
        # Asegúrate de incluir TODAS las columnas que quieres en el Excel, tanto de Neurología como Familiar
        columns_order = [
            'nombre', 'rut', 'fecha_nacimiento', 'edad', 'nacionalidad', 'sexo',
            'fecha_relleno', 'doctora_evaluadora_id',
            # Campos de Neurología
            'estado_general', 'diagnostico', 'fecha_reevaluacion', 'derivaciones',
            # Campos de Medicina Familiar
            'genero_f', 'genero_m', 'diagnostico_1', 'diagnostico_2', 'clasificacion',
            'fecha_evaluacion', 'fecha_reevaluacion_select', 'diagnostico_complementario',
            'observacion_1', 'observacion_2', 'observacion_3', 'observacion_4',
            'observacion_5', 'observacion_6', 'observacion_7',
            'altura', 'peso', 'imc', 'clasificacion_imc',
            'check_cesarea', 'check_atermino', 'check_vaginal', 'check_prematuro',
            'check_acorde', 'check_retrasogeneralizado', 'check_esquemac', 'check_esquemai',
            'check_alergiano', 'check_alergiasi', 'check_cirugiano', 'check_cirugiasi',
            'check_visionsinalteracion', 'check_visionrefraccion', 'check_audicionnormal',
            'check_hipoacusia', 'check_tapondecerumen', 'check_sinhallazgos', 'check_caries',
            'check_apinamientodental', 'check_retenciondental', 'check_frenillolingual', 'check_hipertrofia'
        ]
        
        # Filtrar columnas que realmente existen en el DataFrame para evitar errores
        existing_columns = [col for col in columns_order if col in df.columns]
        df = df[existing_columns]

        # Renombrar columnas para que sean más legibles en el Excel
        df.rename(columns={
            'nombre': 'Nombre Completo',
            'rut': 'RUT',
            'fecha_nacimiento': 'Fecha de Nacimiento',
            'nacionalidad': 'Nacionalidad',
            'sexo': 'Sexo (General)', # Para distinguir del género_f/m
            'fecha_relleno': 'Fecha de Evaluación',
            'doctora_evaluadora_id': 'ID Doctora Evaluadora',
            'estado_general': 'Estado General (Neurología)',
            'diagnostico': 'Diagnóstico (Neurología)',
            'fecha_reevaluacion': 'Fecha Reevaluación (Neurología)',
            'derivaciones': 'Derivaciones (Neurología/Familiar)',
            'genero_f': 'Género Femenino (Familiar)',
            'genero_m': 'Género Masculino (Familiar)',
            'diagnostico_1': 'Diagnóstico 1 (Familiar)',
            'diagnostico_2': 'Diagnóstico 2 (Familiar)',
            'clasificacion': 'Clasificación (Familiar)',
            'fecha_evaluacion': 'Fecha Evaluación (Familiar)',
            'fecha_reevaluacion_select': 'Reevaluación Años (Familiar)',
            'diagnostico_complementario': 'Diagnóstico Complementario (Familiar)',
            'observacion_1': 'Observación 1',
            'observacion_2': 'Observación 2',
            'observacion_3': 'Observación 3',
            'observacion_4': 'Observación 4',
            'observacion_5': 'Observación 5',
            'observacion_6': 'Observación 6',
            'observacion_7': 'Observación 7',
            'altura': 'Altura (cm)',
            'peso': 'Peso (kg)',
            'imc': 'IMC',
            'clasificacion_imc': 'Clasificación IMC',
            'check_cesarea': 'Cesárea',
            'check_atermino': 'A Término',
            'check_vaginal': 'Vaginal',
            'check_prematuro': 'Prematuro',
            'check_acorde': 'DSM Acorde a Edad',
            'check_retrasogeneralizado': 'DSM Retraso Generalizado',
            'check_esquemac': 'Esquema Vacunas Completo',
            'check_esquemai': 'Esquema Vacunas Incompleto',
            'check_alergiano': 'No Alergias',
            'check_alergiasi': 'Sí Alergias',
            'check_cirugiano': 'No Hospitalizaciones/Cirugías',
            'check_cirugiasi': 'Sí Hospitalizaciones/Cirugías',
            'check_visionsinalteracion': 'Visión Sin Alteración',
            'check_visionrefraccion': 'Visión Vicios Refracción',
            'check_audicionnormal': 'Audición Normal',
            'check_hipoacusia': 'Audición Hipoacusia',
            'check_tapondecerumen': 'Audición Tapón Cerumen',
            'check_sinhallazgos': 'Bucodental Sin Hallazgos',
            'check_caries': 'Bucodental Caries',
            'check_apinamientodental': 'Bucodental Apiñamiento Dental',
            'check_retenciondental': 'Bucodental Retención Dental',
            'check_frenillolingual': 'Bucodental Frenillo Lingual',
            'check_hipertrofia': 'Bucodental Hipertrofia Amigdalina'
        }, inplace=True)

        # Crear un archivo Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Estudiantes Evaluados')
        output.seek(0)

        nomina_info_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina"
        nomina_info_res = requests.get(nomina_info_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_info_res.raise_for_status()
        nomina_nombre = nomina_info_res.json()[0]['nombre_nomina'] if nomina_info_res.json() else 'Nomina'

        filename = f"Evaluaciones_{nomina_nombre.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"

        return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al descargar Excel: {e}", "error")
        print(f"ERROR: Error en /descargar_excel_evaluados (Supabase): {e}")
        return redirect(url_for('relleno_formularios', nomina_id=nomina_id))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al generar el Excel: {e}", "error")
        print(f"ERROR: Error inesperado en /descargar_excel_evaluados: {e}")
        return redirect(url_for('relleno_formularios', nomina_id=nomina_id))


@app.route('/generar_pdfs_visibles', methods=['POST'])
@login_required
def generar_pdfs_visibles():
    data = request.get_json()
    nomina_id = data.get('nomina_id')
    student_ids = data.get('student_ids', [])

    if not nomina_id or not student_ids:
        return jsonify({"success": False, "message": "Datos incompletos para generar PDFs combinados."}), 400

    try:
        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

        combined_writer = PdfWriter()

        for student_id in student_ids:
            # Obtener datos completos del estudiante desde Supabase
            estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{student_id}&select=*"
            estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
            estudiante_res.raise_for_status()
            estudiante_data = estudiante_res.json()

            if not estudiante_data:
                print(f"WARNING: Estudiante {student_id} no encontrado, saltando.")
                continue # Saltar al siguiente estudiante si no se encuentra

            est = estudiante_data[0]

            # Abrir el PDF base para cada estudiante
            reader = PdfReader(pdf_base_path)
            
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                
                # Crear una nueva página para el combined_writer
                # Esto es crucial para que cada formulario sea independiente
                new_page = combined_writer.add_blank_page(page.mediabox.width, page.mediabox.height)
                new_page.merge_page(page) # Merge el contenido de la página original

                # Obtener campos del formulario PDF y rellenar
                if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                    for field in page["/AcroForm"]["/Fields"]:
                        field_name = field.get("/T")
                        if field_name:
                            field_name = str(field_name)

                            # Rellenar campos comunes
                            if field_name == "Nombres y Apellidos":
                                combined_writer.update_page_form_field_values(new_page, {"Nombres y Apellidos": est.get('nombre', '')})
                            elif field_name == "RUN":
                                combined_writer.update_page_form_field_values(new_page, {"RUN": est.get('rut', '')})
                            elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                                fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                                combined_writer.update_page_form_field_values(new_page, {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                            elif field_name == "Edad (en años y meses)":
                                years, months = calculate_age(est.get('fecha_nacimiento'))
                                combined_writer.update_page_form_field_values(new_page, {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                            elif field_name == "Nacionalidad":
                                combined_writer.update_page_form_field_values(new_page, {"Nacionalidad": est.get('nacionalidad', '')})
                            
                            # Campos específicos de Neurología
                            elif form_type == 'neurologia':
                                if field_name == "Sexo":
                                    combined_writer.update_page_form_field_values(new_page, {"Sexo": est.get('sexo', '')})
                                elif field_name == "Estado general del alumno":
                                    combined_writer.update_page_form_field_values(new_page, {"Estado general del alumno": est.get('estado_general', '')})
                                elif field_name == "Diagnostico":
                                    combined_writer.update_page_form_field_values(new_page, {"Diagnostico": est.get('diagnostico', '')})
                                elif field_name == "Fecha reevaluacion":
                                    fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                                elif field_name == "Derivaciones":
                                    combined_writer.update_page_form_field_values(new_page, {"Derivaciones": est.get('derivaciones', '')})
                            
                            # Campos específicos de Medicina Familiar
                            elif form_type == 'medicina_familiar':
                                # Género (checkboxes en PDF)
                                if field_name == "F" and est.get('genero_f'):
                                    combined_writer.update_page_form_field_values(new_page, {"F": "/Yes"})
                                elif field_name == "M" and est.get('genero_m'):
                                    combined_writer.update_page_form_field_values(new_page, {"M": "/Yes"})
                                
                                # Motivo de Consulta
                                elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                    combined_writer.update_page_form_field_values(new_page, {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                                elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                    combined_writer.update_page_form_field_values(new_page, {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                                elif field_name == "Clasificación":
                                    combined_writer.update_page_form_field_values(new_page, {"Clasificación": est.get('clasificacion', '')})
                                elif field_name == "INDICACIONES": # Campo para derivaciones
                                    combined_writer.update_page_form_field_values(new_page, {"INDICACIONES": est.get('derivaciones', '')})
                                
                                # Fechas
                                elif field_name == "Fecha evaluación":
                                    fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                                elif field_name == "Fecha reevaluación":
                                    # Usar el campo fecha_reevaluacion que ya debe estar en formato YYYY-MM-DD
                                    # y convertirlo a DD/MM/YYYY para el PDF
                                    fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                                # Observaciones (OBS1 a OBS7) - Corrected logic
                                # Instead of a for loop here, check if the field_name matches any OBS field
                                elif field_name.startswith("OBS") and len(field_name) == 4 and field_name[3].isdigit():
                                    obs_index = int(field_name[3])
                                    if 1 <= obs_index <= 7:
                                        combined_writer.update_page_form_field_values(new_page, {field_name: est.get(f'observacion_{obs_index}', '')})
                                
                                # Antecedentes Perinatales (checkboxes)
                                elif field_name == "CESAREA" and est.get('check_cesarea'):
                                    combined_writer.update_page_form_field_values(new_page, {"CESAREA": "/Yes"})
                                elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                    combined_writer.update_page_form_field_values(new_page, {"A TÉRMINO": "/Yes"})
                                elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                    combined_writer.update_page_form_field_values(new_page, {"VAGINAL": "/Yes"})
                                elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                    combined_writer.update_page_form_field_values(new_page, {"PREMATURO": "/Yes"})
                                
                                # DSM (checkboxes)
                                elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                    combined_writer.update_page_form_field_values(new_page, {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                                elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                    combined_writer.update_page_form_field_values(new_page, {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                                # Vacunas (checkboxes)
                                elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                    combined_writer.update_page_form_field_values(new_page, {"ESQUEMA COMPLETO": "/Yes"})
                                elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                    combined_writer.update_page_form_field_values(new_page, {"ESQUEMA INCOMPLETO": "/Yes"})
                                
                                # Alergias (checkboxes)
                                elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                    combined_writer.update_page_form_field_values(new_page, {"NO": "/Yes"})
                                elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                    combined_writer.update_page_form_field_values(new_page, {"SI": "/Yes"})

                                # Hospitalizaciones/Cirugías (checkboxes)
                                elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                    combined_writer.update_page_form_field_values(new_page, {"NO_2": "/Yes"})
                                elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                    combined_writer.update_page_form_field_values(new_page, {"SI_2": "/Yes"})

                                # Visión (checkboxes)
                                elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                    combined_writer.update_page_form_field_values(new_page, {"SIN ALTERACIÓN": "/Yes"})
                                elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                    combined_writer.update_page_form_field_values(new_page, {"VICIOS DE REFRACCIÓN": "/Yes"})

                                # Audición (checkboxes)
                                elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                    combined_writer.update_page_form_field_values(new_page, {"NORMAL": "/Yes"})
                                elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                    combined_writer.update_page_form_field_values(new_page, {"HIPOACUSIA": "/Yes"})
                                elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                    combined_writer.update_page_form_field_values(new_page, {"TAPÓN DE CERUMEN": "/Yes"})

                                # Salud Bucodental (checkboxes)
                                elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                    combined_writer.update_page_form_field_values(new_page, {"SIN HALLAZGOS": "/Yes"})
                                elif field_name == "CARIES" and est.get('check_caries'):
                                    combined_writer.update_page_form_field_values(new_page, {"CARIES": "/Yes"})
                                elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                    combined_writer.update_page_form_field_values(new_page, {"APIÑAMIENTO DENTAL": "/Yes"})
                                elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                    combined_writer.update_page_form_field_values(new_page, {"RETENCIÓN DENTAL": "/Yes"})
                                elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                    combined_writer.update_page_form_field_values(new_page, {"FRENILLO LINGUAL": "/Yes"})
                                elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                    combined_writer.update_page_form_field_values(new_page, {"HIPERTROFIA AMIGDALINA": "/Yes"})

                                # Medidas Antropométricas
                                elif field_name == "Altura":
                                    combined_writer.update_page_form_field_values(new_page, {"Altura": str(est.get('altura', ''))})
                                elif field_name == "Peso":
                                    combined_writer.update_page_form_field_values(new_page, {"Peso": str(est.get('peso', ''))})
                                elif field_name == "I.M.C":
                                    combined_writer.update_page_form_field_values(new_page, {"I.M.C": est.get('imc', '')})
                                elif field_name == "Clasificación_IMC":
                                    combined_writer.update_page_form_field_values(new_page, {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                                
                                # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                                elif field_name == "Nombres y Apellidos_Doctor":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Nombres y Apellidos_Doctor": doctor_name})
                                elif field_name == "Rut_Doctor":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Rut_Doctor": doctor_rut})
                                elif field_name == "Nº Registro Profesional":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Nº Registro Profesional": doctor_reg})
                                elif field_name == "Especialidad":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Especialidad": doctor_esp})
                                elif field_name == "Fono/E-Mail Contacto":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Fono/E-Mail Contacto": doctor_email})
                                elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                    combined_writer.update_page_form_field_values(new_page, {"Salud pública": "/Yes"})
                                elif field_name == "Particular" and est.get('procedencia_particular'):
                                    combined_writer.update_page_form_field_values(new_page, {"Particular": "/Yes"})
                                elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                    combined_writer.update_page_form_field_values(new_page, {"Escuela": "/Yes"})
                                elif field_name == "Otro" and est.get('procedencia_otro'):
                                    combined_writer.update_page_form_field_values(new_page, {"Otro": "/Yes"})

        output_pdf = io.BytesIO()
        combined_writer.write(output_pdf)
        output_pdf.seek(0)

        filename = f"Formularios_Combinados_{nomina_id}.pdf"
        return send_file(output_pdf, download_name=filename, as_attachment=False, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de conexión con la base de datos al generar PDFs visibles: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con la base de datos: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al generar PDFs visibles: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

@app.route('/enviar_formulario_a_drive', methods=['POST'])
@login_required
def enviar_formulario_a_drive():
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')

    if not estudiante_id or not nomina_id:
        return jsonify({"success": False, "message": "Datos incompletos para enviar a Google Drive."}), 400

    try:
        # Obtener datos completos del estudiante desde Supabase
        estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=*"
        estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiante_res.raise_for_status()
        est = estudiante_res.json()[0]

        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

        # Generar el PDF en memoria (similar a generar_pdf)
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()

        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            writer.add_page(page)

            if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                for field in page["/AcroForm"]["/Fields"]:
                    field_name = field.get("/T")
                    if field_name:
                        field_name = str(field_name)

                        # Rellenar campos comunes
                        if field_name == "Nombres y Apellidos":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos": est.get('nombre', '')})
                        elif field_name == "RUN":
                            writer.update_page_form_field_values(writer.pages[page_num], {"RUN": est.get('rut', '')})
                        elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                            fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                            writer.update_page_form_field_values(writer.pages[page_num], {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                        elif field_name == "Edad (en años y meses)":
                            years, months = calculate_age(est.get('fecha_nacimiento'))
                            writer.update_page_form_field_values(writer.pages[page_num], {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                        elif field_name == "Nacionalidad":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nacionalidad": est.get('nacionalidad', '')})
                        
                        # Campos específicos de Neurología
                        elif form_type == 'neurologia':
                            if field_name == "Sexo":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Sexo": est.get('sexo', '')})
                            elif field_name == "Estado general del alumno":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Estado general del alumno": est.get('estado_general', '')})
                            elif field_name == "Diagnostico":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Diagnostico": est.get('diagnostico', '')})
                            elif field_name == "Fecha reevaluacion":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                            elif field_name == "Derivaciones":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Derivaciones": est.get('derivaciones', '')})
                        
                        # Campos específicos de Medicina Familiar
                        elif form_type == 'medicina_familiar':
                            # Género (checkboxes en PDF)
                            if field_name == "F" and est.get('genero_f'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"F": "/Yes"})
                            elif field_name == "M" and est.get('genero_m'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"M": "/Yes"})
                            
                            # Motivo de Consulta
                            elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                            elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                            elif field_name == "Clasificación":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación": est.get('clasificacion', '')})
                            elif field_name == "INDICACIONES": # Campo para derivaciones
                                writer.update_page_form_field_values(writer.pages[page_num], {"INDICACIONES": est.get('derivaciones', '')})
                            
                            # Fechas
                            elif field_name == "Fecha evaluación":
                                fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                            elif field_name == "Fecha reevaluación":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                            # Observaciones (OBS1 a OBS7) - Corrected logic
                            elif field_name.startswith("OBS") and len(field_name) == 4 and field_name[3].isdigit():
                                obs_index = int(field_name[3])
                                if 1 <= obs_index <= 7:
                                    writer.update_page_form_field_values(writer.pages[page_num], {field_name: est.get(f'observacion_{obs_index}', '')})

                            # Antecedentes Perinatales (checkboxes)
                            elif field_name == "CESAREA" and est.get('check_cesarea'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CESAREA": "/Yes"})
                            elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"A TÉRMINO": "/Yes"})
                            elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VAGINAL": "/Yes"})
                            elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"PREMATURO": "/Yes"})
                            
                            # DSM (checkboxes)
                            elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                            elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                            # Vacunas (checkboxes)
                            elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA COMPLETO": "/Yes"})
                            elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA INCOMPLETO": "/Yes"})
                            
                            # Alergias (checkboxes)
                            elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO": "/Yes"})
                            elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI": "/Yes"})

                            # Hospitalizaciones/Cirugías (checkboxes)
                            elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO_2": "/Yes"})
                            elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI_2": "/Yes"})

                            # Visión (checkboxes)
                            elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN ALTERACIÓN": "/Yes"})
                            elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VICIOS DE REFRACCIÓN": "/Yes"})

                            # Audición (checkboxes)
                            elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"NORMAL": "/Yes"})
                            elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPOACUSIA": "/Yes"})
                            elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"TAPÓN DE CERUMEN": "/Yes"})

                            # Salud Bucodental (checkboxes)
                            elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN HALLAZGOS": "/Yes"})
                            elif field_name == "CARIES" and est.get('check_caries'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CARIES": "/Yes"})
                            elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"APIÑAMIENTO DENTAL": "/Yes"})
                            elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETENCIÓN DENTAL": "/Yes"})
                            elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"FRENILLO LINGUAL": "/Yes"})
                            elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPERTROFIA AMIGDALINA": "/Yes"})

                            # Medidas Antropométricas
                            elif field_name == "Altura":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Altura": str(est.get('altura', ''))})
                            elif field_name == "Peso":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Peso": str(est.get('peso', ''))})
                            elif field_name == "I.M.C":
                                writer.update_page_form_field_values(writer.pages[page_num], {"I.M.C": est.get('imc', '')})
                            elif field_name == "Clasificación_IMC": # Asumiendo un campo para la clasificación del IMC
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                            
                            # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                            elif field_name == "Nombres y Apellidos_Doctor":
                                # Obtener nombre de la doctora
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos_Doctor": doctor_name})
                            elif field_name == "Rut_Doctor":
                                # Asumiendo que el RUT de la doctora también está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Rut_Doctor": doctor_rut})
                            elif field_name == "Nº Registro Profesional":
                                # Asumiendo que el número de registro está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nº Registro Profesional": doctor_reg})
                            elif field_name == "Especialidad":
                                # Asumiendo que la especialidad está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Especialidad": doctor_esp})
                            elif field_name == "Fono/E-Mail Contacto":
                                # Asumiendo que el email está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fono/E-Mail Contacto": doctor_email})
                            elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Salud pública": "/Yes"})
                            elif field_name == "Particular" and est.get('procedencia_particular'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Particular": "/Yes"})
                            elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Escuela": "/Yes"})
                            elif field_name == "Otro" and est.get('procedencia_otro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Otro": "/Yes"})

        output_pdf = io.BytesIO()
        writer.write(output_pdf)
        output_pdf.seek(0)

        # Enviar el PDF como respuesta
        filename = f"formulario_{est.get('nombre', 'sin_nombre').replace(' ', '_')}_{form_type}.pdf"
        return send_file(output_pdf, download_name=filename, as_attachment=False, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al generar PDF: {e}", "error")
        print(f"ERROR: Error en /generar_pdf (Supabase): {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al generar el PDF: {e}", "error")
        print(f"ERROR: Error inesperado en /generar_pdf: {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))


@app.route('/descargar_excel_evaluados/<nomina_id>', methods=['GET'])
@login_required
def descargar_excel_evaluados(nomina_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("No autorizado.", "error")
        return redirect(url_for('login'))

    try:
        # Obtener estudiantes de la nómina que han sido evaluados
        estudiantes_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?nomina_id=eq.{nomina_id}&fecha_relleno=not.is.null&select=*"
        estudiantes_res = requests.get(estudiantes_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiantes_res.raise_for_status()
        estudiantes_data = estudiantes_res.json()

        if not estudiantes_data:
            flash("No hay estudiantes evaluados en esta nómina para descargar.", "info")
            return redirect(url_for('relleno_formularios', nomina_id=nomina_id))

        # Convertir la lista de diccionarios a un DataFrame de pandas
        df = pd.DataFrame(estudiantes_data)

        # Seleccionar y reordenar columnas para el Excel
        # Asegúrate de incluir TODAS las columnas que quieres en el Excel, tanto de Neurología como Familiar
        columns_order = [
            'nombre', 'rut', 'fecha_nacimiento', 'edad', 'nacionalidad', 'sexo',
            'fecha_relleno', 'doctora_evaluadora_id',
            # Campos de Neurología
            'estado_general', 'diagnostico', 'fecha_reevaluacion', 'derivaciones',
            # Campos de Medicina Familiar
            'genero_f', 'genero_m', 'diagnostico_1', 'diagnostico_2', 'clasificacion',
            'fecha_evaluacion', 'fecha_reevaluacion_select', 'diagnostico_complementario',
            'observacion_1', 'observacion_2', 'observacion_3', 'observacion_4',
            'observacion_5', 'observacion_6', 'observacion_7',
            'altura', 'peso', 'imc', 'clasificacion_imc',
            'check_cesarea', 'check_atermino', 'check_vaginal', 'check_prematuro',
            'check_acorde', 'check_retrasogeneralizado', 'check_esquemac', 'check_esquemai',
            'check_alergiano', 'check_alergiasi', 'check_cirugiano', 'check_cirugiasi',
            'check_visionsinalteracion', 'check_visionrefraccion', 'check_audicionnormal',
            'check_hipoacusia', 'check_tapondecerumen', 'check_sinhallazgos', 'check_caries',
            'check_apinamientodental', 'check_retenciondental', 'check_frenillolingual', 'check_hipertrofia'
        ]
        
        # Filtrar columnas que realmente existen en el DataFrame para evitar errores
        existing_columns = [col for col in columns_order if col in df.columns]
        df = df[existing_columns]

        # Renombrar columnas para que sean más legibles en el Excel
        df.rename(columns={
            'nombre': 'Nombre Completo',
            'rut': 'RUT',
            'fecha_nacimiento': 'Fecha de Nacimiento',
            'nacionalidad': 'Nacionalidad',
            'sexo': 'Sexo (General)', # Para distinguir del género_f/m
            'fecha_relleno': 'Fecha de Evaluación',
            'doctora_evaluadora_id': 'ID Doctora Evaluadora',
            'estado_general': 'Estado General (Neurología)',
            'diagnostico': 'Diagnóstico (Neurología)',
            'fecha_reevaluacion': 'Fecha Reevaluación (Neurología)',
            'derivaciones': 'Derivaciones (Neurología/Familiar)',
            'genero_f': 'Género Femenino (Familiar)',
            'genero_m': 'Género Masculino (Familiar)',
            'diagnostico_1': 'Diagnóstico 1 (Familiar)',
            'diagnostico_2': 'Diagnóstico 2 (Familiar)',
            'clasificacion': 'Clasificación (Familiar)',
            'fecha_evaluacion': 'Fecha Evaluación (Familiar)',
            'fecha_reevaluacion_select': 'Reevaluación Años (Familiar)',
            'diagnostico_complementario': 'Diagnóstico Complementario (Familiar)',
            'observacion_1': 'Observación 1',
            'observacion_2': 'Observación 2',
            'observacion_3': 'Observación 3',
            'observacion_4': 'Observación 4',
            'observacion_5': 'Observación 5',
            'observacion_6': 'Observación 6',
            'observacion_7': 'Observación 7',
            'altura': 'Altura (cm)',
            'peso': 'Peso (kg)',
            'imc': 'IMC',
            'clasificacion_imc': 'Clasificación IMC',
            'check_cesarea': 'Cesárea',
            'check_atermino': 'A Término',
            'check_vaginal': 'Vaginal',
            'check_prematuro': 'Prematuro',
            'check_acorde': 'DSM Acorde a Edad',
            'check_retrasogeneralizado': 'DSM Retraso Generalizado',
            'check_esquemac': 'Esquema Vacunas Completo',
            'check_esquemai': 'Esquema Vacunas Incompleto',
            'check_alergiano': 'No Alergias',
            'check_alergiasi': 'Sí Alergias',
            'check_cirugiano': 'No Hospitalizaciones/Cirugías',
            'check_cirugiasi': 'Sí Hospitalizaciones/Cirugías',
            'check_visionsinalteracion': 'Visión Sin Alteración',
            'check_visionrefraccion': 'Visión Vicios Refracción',
            'check_audicionnormal': 'Audición Normal',
            'check_hipoacusia': 'Audición Hipoacusia',
            'check_tapondecerumen': 'Audición Tapón Cerumen',
            'check_sinhallazgos': 'Bucodental Sin Hallazgos',
            'check_caries': 'Bucodental Caries',
            'check_apinamientodental': 'Bucodental Apiñamiento Dental',
            'check_retenciondental': 'Bucodental Retención Dental',
            'check_frenillolingual': 'Bucodental Frenillo Lingual',
            'check_hipertrofia': 'Bucodental Hipertrofia Amigdalina'
        }, inplace=True)

        # Crear un archivo Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Estudiantes Evaluados')
        output.seek(0)

        nomina_info_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=nombre_nomina"
        nomina_info_res = requests.get(nomina_info_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_info_res.raise_for_status()
        nomina_nombre = nomina_info_res.json()[0]['nombre_nomina'] if nomina_info_res.json() else 'Nomina'

        filename = f"Evaluaciones_{nomina_nombre.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"

        return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al descargar Excel: {e}", "error")
        print(f"ERROR: Error en /descargar_excel_evaluados (Supabase): {e}")
        return redirect(url_for('relleno_formularios', nomina_id=nomina_id))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al generar el Excel: {e}", "error")
        print(f"ERROR: Error inesperado en /descargar_excel_evaluados: {e}")
        return redirect(url_for('relleno_formularios', nomina_id=nomina_id))


@app.route('/generar_pdfs_visibles', methods=['POST'])
@login_required
def generar_pdfs_visibles():
    data = request.get_json()
    nomina_id = data.get('nomina_id')
    student_ids = data.get('student_ids', [])

    if not nomina_id or not student_ids:
        return jsonify({"success": False, "message": "Datos incompletos para generar PDFs combinados."}), 400

    try:
        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

        combined_writer = PdfWriter()

        for student_id in student_ids:
            # Obtener datos completos del estudiante desde Supabase
            estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{student_id}&select=*"
            estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
            estudiante_res.raise_for_status()
            estudiante_data = estudiante_res.json()

            if not estudiante_data:
                print(f"WARNING: Estudiante {student_id} no encontrado, saltando.")
                continue # Saltar al siguiente estudiante si no se encuentra

            est = estudiante_data[0]

            # Abrir el PDF base para cada estudiante
            reader = PdfReader(pdf_base_path)
            
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                
                # Crear una nueva página para el combined_writer
                # Esto es crucial para que cada formulario sea independiente
                new_page = combined_writer.add_blank_page(page.mediabox.width, page.mediabox.height)
                new_page.merge_page(page) # Merge el contenido de la página original

                # Obtener campos del formulario PDF y rellenar
                if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                    for field in page["/AcroForm"]["/Fields"]:
                        field_name = field.get("/T")
                        if field_name:
                            field_name = str(field_name)

                            # Rellenar campos comunes
                            if field_name == "Nombres y Apellidos":
                                combined_writer.update_page_form_field_values(new_page, {"Nombres y Apellidos": est.get('nombre', '')})
                            elif field_name == "RUN":
                                combined_writer.update_page_form_field_values(new_page, {"RUN": est.get('rut', '')})
                            elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                                fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                                combined_writer.update_page_form_field_values(new_page, {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                            elif field_name == "Edad (en años y meses)":
                                years, months = calculate_age(est.get('fecha_nacimiento'))
                                combined_writer.update_page_form_field_values(new_page, {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                            elif field_name == "Nacionalidad":
                                combined_writer.update_page_form_field_values(new_page, {"Nacionalidad": est.get('nacionalidad', '')})
                            
                            # Campos específicos de Neurología
                            elif form_type == 'neurologia':
                                if field_name == "Sexo":
                                    combined_writer.update_page_form_field_values(new_page, {"Sexo": est.get('sexo', '')})
                                elif field_name == "Estado general del alumno":
                                    combined_writer.update_page_form_field_values(new_page, {"Estado general del alumno": est.get('estado_general', '')})
                                elif field_name == "Diagnostico":
                                    combined_writer.update_page_form_field_values(new_page, {"Diagnostico": est.get('diagnostico', '')})
                                elif field_name == "Fecha reevaluacion":
                                    fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                                elif field_name == "Derivaciones":
                                    combined_writer.update_page_form_field_values(new_page, {"Derivaciones": est.get('derivaciones', '')})
                            
                            # Campos específicos de Medicina Familiar
                            elif form_type == 'medicina_familiar':
                                # Género (checkboxes en PDF)
                                if field_name == "F" and est.get('genero_f'):
                                    combined_writer.update_page_form_field_values(new_page, {"F": "/Yes"})
                                elif field_name == "M" and est.get('genero_m'):
                                    combined_writer.update_page_form_field_values(new_page, {"M": "/Yes"})
                                
                                # Motivo de Consulta
                                elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                    combined_writer.update_page_form_field_values(new_page, {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                                elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                    combined_writer.update_page_form_field_values(new_page, {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                                elif field_name == "Clasificación":
                                    combined_writer.update_page_form_field_values(new_page, {"Clasificación": est.get('clasificacion', '')})
                                elif field_name == "INDICACIONES": # Campo para derivaciones
                                    combined_writer.update_page_form_field_values(new_page, {"INDICACIONES": est.get('derivaciones', '')})
                                
                                # Fechas
                                elif field_name == "Fecha evaluación":
                                    fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                                elif field_name == "Fecha reevaluación":
                                    # Usar el campo fecha_reevaluacion que ya debe estar en formato YYYY-MM-DD
                                    # y convertirlo a DD/MM/YYYY para el PDF
                                    fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                    combined_writer.update_page_form_field_values(new_page, {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                                # Observaciones (OBS1 a OBS7) - Corrected logic
                                # Instead of a for loop here, check if the field_name matches any OBS field
                                # This ensures it remains part of the elif chain
                                elif field_name.startswith("OBS") and len(field_name) == 4 and field_name[3].isdigit():
                                    obs_index = int(field_name[3])
                                    if 1 <= obs_index <= 7: # Ensure index is valid
                                        combined_writer.update_page_form_field_values(new_page, {field_name: est.get(f'observacion_{obs_index}', '')})
                                
                                # Antecedentes Perinatales (checkboxes)
                                elif field_name == "CESAREA" and est.get('check_cesarea'):
                                    combined_writer.update_page_form_field_values(new_page, {"CESAREA": "/Yes"})
                                elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                    combined_writer.update_page_form_field_values(new_page, {"A TÉRMINO": "/Yes"})
                                elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                    combined_writer.update_page_form_field_values(new_page, {"VAGINAL": "/Yes"})
                                elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                    combined_writer.update_page_form_field_values(new_page, {"PREMATURO": "/Yes"})
                                
                                # DSM (checkboxes)
                                elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                    combined_writer.update_page_form_field_values(new_page, {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                                elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                    combined_writer.update_page_form_field_values(new_page, {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                                # Vacunas (checkboxes)
                                elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                    combined_writer.update_page_form_field_values(new_page, {"ESQUEMA COMPLETO": "/Yes"})
                                elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                    combined_writer.update_page_form_field_values(new_page, {"ESQUEMA INCOMPLETO": "/Yes"})
                                
                                # Alergias (checkboxes)
                                elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                    combined_writer.update_page_form_field_values(new_page, {"NO": "/Yes"})
                                elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                    combined_writer.update_page_form_field_values(new_page, {"SI": "/Yes"})

                                # Hospitalizaciones/Cirugías (checkboxes)
                                elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                    combined_writer.update_page_form_field_values(new_page, {"NO_2": "/Yes"})
                                elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                    combined_writer.update_page_form_field_values(new_page, {"SI_2": "/Yes"})

                                # Visión (checkboxes)
                                elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                    combined_writer.update_page_form_field_values(new_page, {"SIN ALTERACIÓN": "/Yes"})
                                elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                    combined_writer.update_page_form_field_values(new_page, {"VICIOS DE REFRACCIÓN": "/Yes"})

                                # Audición (checkboxes)
                                elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                    combined_writer.update_page_form_field_values(new_page, {"NORMAL": "/Yes"})
                                elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                    combined_writer.update_page_form_field_values(new_page, {"HIPOACUSIA": "/Yes"})
                                elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                    combined_writer.update_page_form_field_values(new_page, {"TAPÓN DE CERUMEN": "/Yes"})

                                # Salud Bucodental (checkboxes)
                                elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                    combined_writer.update_page_form_field_values(new_page, {"SIN HALLAZGOS": "/Yes"})
                                elif field_name == "CARIES" and est.get('check_caries'):
                                    combined_writer.update_page_form_field_values(new_page, {"CARIES": "/Yes"})
                                elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                    combined_writer.update_page_form_field_values(new_page, {"APIÑAMIENTO DENTAL": "/Yes"})
                                elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                    combined_writer.update_page_form_field_values(new_page, {"RETENCIÓN DENTAL": "/Yes"})
                                elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                    combined_writer.update_page_form_field_values(new_page, {"FRENILLO LINGUAL": "/Yes"})
                                elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                    combined_writer.update_page_form_field_values(new_page, {"HIPERTROFIA AMIGDALINA": "/Yes"})

                                # Medidas Antropométricas
                                elif field_name == "Altura":
                                    combined_writer.update_page_form_field_values(new_page, {"Altura": str(est.get('altura', ''))})
                                elif field_name == "Peso":
                                    combined_writer.update_page_form_field_values(new_page, {"Peso": str(est.get('peso', ''))})
                                elif field_name == "I.M.C":
                                    combined_writer.update_page_form_field_values(new_page, {"I.M.C": est.get('imc', '')})
                                elif field_name == "Clasificación_IMC":
                                    combined_writer.update_page_form_field_values(new_page, {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                                
                                # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                                elif field_name == "Nombres y Apellidos_Doctor":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Nombres y Apellidos_Doctor": doctor_name})
                                elif field_name == "Rut_Doctor":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Rut_Doctor": doctor_rut})
                                elif field_name == "Nº Registro Profesional":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Nº Registro Profesional": doctor_reg})
                                elif field_name == "Especialidad":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Especialidad": doctor_esp})
                                elif field_name == "Fono/E-Mail Contacto":
                                    doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                    doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                    doctor_res.raise_for_status()
                                    doctor_info = doctor_res.json()
                                    doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                    combined_writer.update_page_form_field_values(new_page, {"Fono/E-Mail Contacto": doctor_email})
                                elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                    combined_writer.update_page_form_field_values(new_page, {"Salud pública": "/Yes"})
                                elif field_name == "Particular" and est.get('procedencia_particular'):
                                    combined_writer.update_page_form_field_values(new_page, {"Particular": "/Yes"})
                                elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                    combined_writer.update_page_form_field_values(new_page, {"Escuela": "/Yes"})
                                elif field_name == "Otro" and est.get('procedencia_otro'):
                                    combined_writer.update_page_form_field_values(new_page, {"Otro": "/Yes"})

        output_pdf = io.BytesIO()
        combined_writer.write(output_pdf)
        output_pdf.seek(0)

        filename = f"Formularios_Combinados_{nomina_id}.pdf"
        return send_file(output_pdf, download_name=filename, as_attachment=False, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de conexión con la base de datos al generar PDFs visibles: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con la base de datos: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al generar PDFs visibles: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

@app.route('/enviar_formulario_a_drive', methods=['POST'])
@login_required
def enviar_formulario_a_drive():
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')

    if not estudiante_id or not nomina_id:
        return jsonify({"success": False, "message": "Datos incompletos para enviar a Google Drive."}), 400

    try:
        # Obtener datos completos del estudiante desde Supabase
        estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=*"
        estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiante_res.raise_for_status()
        est = estudiante_res.json()[0]

        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

        # Generar el PDF en memoria (similar a generar_pdf)
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()

        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            writer.add_page(page)

            if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                for field in page["/AcroForm"]["/Fields"]:
                    field_name = field.get("/T")
                    if field_name:
                        field_name = str(field_name)

                        # Rellenar campos comunes
                        if field_name == "Nombres y Apellidos":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos": est.get('nombre', '')})
                        elif field_name == "RUN":
                            writer.update_page_form_field_values(writer.pages[page_num], {"RUN": est.get('rut', '')})
                        elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                            fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                            writer.update_page_form_field_values(writer.pages[page_num], {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                        elif field_name == "Edad (en años y meses)":
                            years, months = calculate_age(est.get('fecha_nacimiento'))
                            writer.update_page_form_field_values(writer.pages[page_num], {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                        elif field_name == "Nacionalidad":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nacionalidad": est.get('nacionalidad', '')})
                        
                        # Campos específicos de Neurología
                        elif form_type == 'neurologia':
                            if field_name == "Sexo":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Sexo": est.get('sexo', '')})
                            elif field_name == "Estado general del alumno":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Estado general del alumno": est.get('estado_general', '')})
                            elif field_name == "Diagnostico":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Diagnostico": est.get('diagnostico', '')})
                            elif field_name == "Fecha reevaluacion":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                            elif field_name == "Derivaciones":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Derivaciones": est.get('derivaciones', '')})
                        
                        # Campos específicos de Medicina Familiar
                        elif form_type == 'medicina_familiar':
                            # Género (checkboxes en PDF)
                            if field_name == "F" and est.get('genero_f'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"F": "/Yes"})
                            elif field_name == "M" and est.get('genero_m'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"M": "/Yes"})
                            
                            # Motivo de Consulta
                            elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                            elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                            elif field_name == "Clasificación":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación": est.get('clasificacion', '')})
                            elif field_name == "INDICACIONES": # Campo para derivaciones
                                writer.update_page_form_field_values(writer.pages[page_num], {"INDICACIONES": est.get('derivaciones', '')})
                            
                            # Fechas
                            elif field_name == "Fecha evaluación":
                                fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                            elif field_name == "Fecha reevaluación":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                            # Observaciones (OBS1 a OBS7) - Corrected logic
                            elif field_name.startswith("OBS") and len(field_name) == 4 and field_name[3].isdigit():
                                obs_index = int(field_name[3])
                                if 1 <= obs_index <= 7:
                                    writer.update_page_form_field_values(writer.pages[page_num], {field_name: est.get(f'observacion_{obs_index}', '')})

                            # Antecedentes Perinatales (checkboxes)
                            elif field_name == "CESAREA" and est.get('check_cesarea'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CESAREA": "/Yes"})
                            elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"A TÉRMINO": "/Yes"})
                            elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VAGINAL": "/Yes"})
                            elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"PREMATURO": "/Yes"})
                            
                            # DSM (checkboxes)
                            elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                            elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                            # Vacunas (checkboxes)
                            elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA COMPLETO": "/Yes"})
                            elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA INCOMPLETO": "/Yes"})
                            
                            # Alergias (checkboxes)
                            elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO": "/Yes"})
                            elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI": "/Yes"})

                            # Hospitalizaciones/Cirugías (checkboxes)
                            elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO_2": "/Yes"})
                            elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI_2": "/Yes"})

                            # Visión (checkboxes)
                            elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN ALTERACIÓN": "/Yes"})
                            elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VICIOS DE REFRACCIÓN": "/Yes"})

                            # Audición (checkboxes)
                            elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"NORMAL": "/Yes"})
                            elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPOACUSIA": "/Yes"})
                            elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"TAPÓN DE CERUMEN": "/Yes"})

                            # Salud Bucodental (checkboxes)
                            elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN HALLAZGOS": "/Yes"})
                            elif field_name == "CARIES" and est.get('check_caries'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CARIES": "/Yes"})
                            elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"APIÑAMIENTO DENTAL": "/Yes"})
                            elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETENCIÓN DENTAL": "/Yes"})
                            elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"FRENILLO LINGUAL": "/Yes"})
                            elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPERTROFIA AMIGDALINA": "/Yes"})

                            # Medidas Antropométricas
                            elif field_name == "Altura":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Altura": str(est.get('altura', ''))})
                            elif field_name == "Peso":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Peso": str(est.get('peso', ''))})
                            elif field_name == "I.M.C":
                                writer.update_page_form_field_values(writer.pages[page_num], {"I.M.C": est.get('imc', '')})
                            elif field_name == "Clasificación_IMC": # Asumiendo un campo para la clasificación del IMC
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                            
                            # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                            elif field_name == "Nombres y Apellidos_Doctor":
                                # Obtener nombre de la doctora
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos_Doctor": doctor_name})
                            elif field_name == "Rut_Doctor":
                                # Asumiendo que el RUT de la doctora también está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Rut_Doctor": doctor_rut})
                            elif field_name == "Nº Registro Profesional":
                                # Asumiendo que el número de registro está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nº Registro Profesional": doctor_reg})
                            elif field_name == "Especialidad":
                                # Asumiendo que la especialidad está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Especialidad": doctor_esp})
                            elif field_name == "Fono/E-Mail Contacto":
                                # Asumiendo que el email está en la tabla de usuarios
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fono/E-Mail Contacto": doctor_email})
                            elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Salud pública": "/Yes"})
                            elif field_name == "Particular" and est.get('procedencia_particular'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Particular": "/Yes"})
                            elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Escuela": "/Yes"})
                            elif field_name == "Otro" and est.get('procedencia_otro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Otro": "/Yes"})

        output_pdf = io.BytesIO()
        writer.write(output_pdf)
        output_pdf.seek(0)

        # Enviar el PDF como respuesta
        filename = f"formulario_{est.get('nombre', 'sin_nombre').replace(' ', '_')}_{form_type}.pdf"
        return send_file(output_pdf, download_name=filename, as_attachment=False, mimetype='application/pdf')

    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la base de datos al generar PDF: {e}", "error")
        print(f"ERROR: Error en /generar_pdf (Supabase): {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))
    except Exception as e:
        flash(f"Ocurrió un error inesperado al generar el PDF: {e}", "error")
        print(f"ERROR: Error inesperado en /generar_pdf: {e}")
        return redirect(url_for('relleno_formularios', nomina_id=session.get('current_nomina_id')))


@app.route('/enviar_formulario_a_drive', methods=['POST'])
@login_required
def enviar_formulario_a_drive():
    estudiante_id = request.form.get('estudiante_id')
    nomina_id = request.form.get('nomina_id')

    if not estudiante_id or not nomina_id:
        return jsonify({"success": False, "message": "Datos incompletos para enviar a Google Drive."}), 400

    try:
        # Obtener datos completos del estudiante desde Supabase
        estudiante_url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=*"
        estudiante_res = requests.get(estudiante_url, headers=SUPABASE_SERVICE_HEADERS)
        estudiante_res.raise_for_status()
        est = estudiante_res.json()[0]

        # Obtener el tipo de formulario de la nómina
        nomina_url = f"{SUPABASE_URL}/rest/v1/nominas_medicas?id=eq.{nomina_id}&select=form_type"
        nomina_res = requests.get(nomina_url, headers=SUPABASE_SERVICE_HEADERS)
        nomina_res.raise_for_status()
        nomina_info = nomina_res.json()
        form_type = nomina_info[0].get('form_type', 'neurologia')

        pdf_base_path = ''
        if form_type == 'neurologia':
            pdf_base_path = PDF_BASE_NEUROLOGIA
        elif form_type == 'medicina_familiar':
            pdf_base_path = PDF_BASE_FAMILIAR
        else:
            return jsonify({"success": False, "message": "Tipo de formulario no reconocido para generar PDF."}), 400

        # Generar el PDF en memoria (similar a generar_pdf)
        reader = PdfReader(pdf_base_path)
        writer = PdfWriter()

        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            writer.add_page(page)

            if "/AcroForm" in page and "/Fields" in page["/AcroForm"]:
                for field in page["/AcroForm"]["/Fields"]:
                    field_name = field.get("/T")
                    if field_name:
                        field_name = str(field_name)

                        # Rellenar campos comunes
                        if field_name == "Nombres y Apellidos":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos": est.get('nombre', '')})
                        elif field_name == "RUN":
                            writer.update_page_form_field_values(writer.pages[page_num], {"RUN": est.get('rut', '')})
                        elif field_name == "Fecha nacimiento (dd/mm/aaaa)":
                            fecha_nac_obj = datetime.strptime(est['fecha_nacimiento'], '%Y-%m-%d').date() if est.get('fecha_nacimiento') else None
                            writer.update_page_form_field_values(writer.pages[page_num], {"Fecha nacimiento (dd/mm/aaaa)": fecha_nac_obj.strftime('%d/%m/%Y') if fecha_nac_obj else ''})
                        elif field_name == "Edad (en años y meses)":
                            years, months = calculate_age(est.get('fecha_nacimiento'))
                            writer.update_page_form_field_values(writer.pages[page_num], {"Edad (en años y meses)": f"{years} años {months} meses" if years is not None else ''})
                        elif field_name == "Nacionalidad":
                            writer.update_page_form_field_values(writer.pages[page_num], {"Nacionalidad": est.get('nacionalidad', '')})
                        
                        # Campos específicos de Neurología
                        elif form_type == 'neurologia':
                            if field_name == "Sexo":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Sexo": est.get('sexo', '')})
                            elif field_name == "Estado general del alumno":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Estado general del alumno": est.get('estado_general', '')})
                            elif field_name == "Diagnostico":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Diagnostico": est.get('diagnostico', '')})
                            elif field_name == "Fecha reevaluacion":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluacion": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})
                            elif field_name == "Derivaciones":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Derivaciones": est.get('derivaciones', '')})
                        
                        # Campos específicos de Medicina Familiar
                        elif form_type == 'medicina_familiar':
                            # Género (checkboxes en PDF)
                            if field_name == "F" and est.get('genero_f'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"F": "/Yes"})
                            elif field_name == "M" and est.get('genero_m'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"M": "/Yes"})
                            
                            # Motivo de Consulta
                            elif field_name == "DIAGNOSTICO": # Campo para diagnostico_1
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNOSTICO": est.get('diagnostico_1', '')})
                            elif field_name == "DIAGNÓSTICO COMPLEMENTARIO": # Campo para diagnostico_complementario (o diagnostico_2 si se mapea así)
                                writer.update_page_form_field_values(writer.pages[page_num], {"DIAGNÓSTICO COMPLEMENTARIO": est.get('diagnostico_complementario', '')})
                            elif field_name == "Clasificación":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación": est.get('clasificacion', '')})
                            elif field_name == "INDICACIONES": # Campo para derivaciones
                                writer.update_page_form_field_values(writer.pages[page_num], {"INDICACIONES": est.get('derivaciones', '')})
                            
                            # Fechas
                            elif field_name == "Fecha evaluación":
                                fecha_eval_obj = datetime.strptime(est['fecha_evaluacion'], '%Y-%m-%d').date() if est.get('fecha_evaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha evaluación": fecha_eval_obj.strftime('%d/%m/%Y') if fecha_eval_obj else ''})
                            elif field_name == "Fecha reevaluación":
                                fecha_reeval_obj = datetime.strptime(est['fecha_reevaluacion'], '%Y-%m-%d').date() if est.get('fecha_reevaluacion') else None
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fecha reevaluación": fecha_reeval_obj.strftime('%d/%m/%Y') if fecha_reeval_obj else ''})

                            # Observaciones (OBS1 a OBS7) - Corrected logic
                            elif field_name.startswith("OBS") and len(field_name) == 4 and field_name[3].isdigit():
                                obs_index = int(field_name[3])
                                if 1 <= obs_index <= 7:
                                    writer.update_page_form_field_values(writer.pages[page_num], {field_name: est.get(f'observacion_{obs_index}', '')})

                            # Antecedentes Perinatales (checkboxes)
                            elif field_name == "CESAREA" and est.get('check_cesarea'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CESAREA": "/Yes"})
                            elif field_name == "A TÉRMINO" and est.get('check_atermino'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"A TÉRMINO": "/Yes"})
                            elif field_name == "VAGINAL" and est.get('check_vaginal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VAGINAL": "/Yes"})
                            elif field_name == "PREMATURO" and est.get('check_prematuro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"PREMATURO": "/Yes"})
                            
                            # DSM (checkboxes)
                            elif field_name == "LOGRADO ACORDE A LA EDAD" and est.get('check_acorde'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"LOGRADO ACORDE A LA EDAD": "/Yes"})
                            elif field_name == "RETRASO GENERALIZADO DEL DESARROLLO" and est.get('check_retrasogeneralizado'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETRASO GENERALIZADO DEL DESARROLLO": "/Yes"})

                            # Vacunas (checkboxes)
                            elif field_name == "ESQUEMA COMPLETO" and est.get('check_esquemac'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA COMPLETO": "/Yes"})
                            elif field_name == "ESQUEMA INCOMPLETO" and est.get('check_esquemai'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"ESQUEMA INCOMPLETO": "/Yes"})
                            
                            # Alergias (checkboxes)
                            elif field_name == "NO" and est.get('check_alergiano'): # Alergias NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO": "/Yes"})
                            elif field_name == "SI" and est.get('check_alergiasi'): # Alergias SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI": "/Yes"})

                            # Hospitalizaciones/Cirugías (checkboxes)
                            elif field_name == "NO_2" and est.get('check_cirugiano'): # Hospitalizaciones NO
                                writer.update_page_form_field_values(writer.pages[page_num], {"NO_2": "/Yes"})
                            elif field_name == "SI_2" and est.get('check_cirugiasi'): # Hospitalizaciones SI
                                writer.update_page_form_field_values(writer.pages[page_num], {"SI_2": "/Yes"})

                            # Visión (checkboxes)
                            elif field_name == "SIN ALTERACIÓN" and est.get('check_visionsinalteracion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN ALTERACIÓN": "/Yes"})
                            elif field_name == "VICIOS DE REFRACCIÓN" and est.get('check_visionrefraccion'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"VICIOS DE REFRACCIÓN": "/Yes"})

                            # Audición (checkboxes)
                            elif field_name == "NORMAL" and est.get('check_audicionnormal'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"NORMAL": "/Yes"})
                            elif field_name == "HIPOACUSIA" and est.get('check_hipoacusia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPOACUSIA": "/Yes"})
                            elif field_name == "TAPÓN DE CERUMEN" and est.get('check_tapondecerumen'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"TAPÓN DE CERUMEN": "/Yes"})

                            # Salud Bucodental (checkboxes)
                            elif field_name == "SIN HALLAZGOS" and est.get('check_sinhallazgos'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"SIN HALLAZGOS": "/Yes"})
                            elif field_name == "CARIES" and est.get('check_caries'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"CARIES": "/Yes"})
                            elif field_name == "APIÑAMIENTO DENTAL" and est.get('check_apinamientodental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"APIÑAMIENTO DENTAL": "/Yes"})
                            elif field_name == "RETENCIÓN DENTAL" and est.get('check_retenciondental'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"RETENCIÓN DENTAL": "/Yes"})
                            elif field_name == "FRENILLO LINGUAL" and est.get('check_frenillolingual'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"FRENILLO LINGUAL": "/Yes"})
                            elif field_name == "HIPERTROFIA AMIGDALINA" and est.get('check_hipertrofia'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"HIPERTROFIA AMIGDALINA": "/Yes"})

                            # Medidas Antropométricas
                            elif field_name == "Altura":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Altura": str(est.get('altura', ''))})
                            elif field_name == "Peso":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Peso": str(est.get('peso', ''))})
                            elif field_name == "I.M.C":
                                writer.update_page_form_field_values(writer.pages[page_num], {"I.M.C": est.get('imc', '')})
                            elif field_name == "Clasificación_IMC":
                                writer.update_page_form_field_values(writer.pages[page_num], {"Clasificación_IMC": est.get('clasificacion_imc', '')})
                            
                            # Información del profesional (se asume que se rellena con datos de la doctora logeada)
                            elif field_name == "Nombres y Apellidos_Doctor":
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=username"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_name = doctor_info[0]['username'] if doctor_info else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nombres y Apellidos_Doctor": doctor_name})
                            elif field_name == "Rut_Doctor":
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=rut"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_rut = doctor_info[0]['rut'] if doctor_info and doctor_info[0].get('rut') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Rut_Doctor": doctor_rut})
                            elif field_name == "Nº Registro Profesional":
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=registro_profesional"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_reg = doctor_info[0]['registro_profesional'] if doctor_info and doctor_info[0].get('registro_profesional') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Nº Registro Profesional": doctor_reg})
                            elif field_name == "Especialidad":
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=especialidad"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_esp = doctor_info[0]['especialidad'] if doctor_info and doctor_info[0].get('especialidad') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Especialidad": doctor_esp})
                            elif field_name == "Fono/E-Mail Contacto":
                                doctor_url = f"{SUPABASE_URL}/rest/v1/usuarios?id=eq.{est.get('doctora_evaluadora_id')}&select=email"
                                doctor_res = requests.get(doctor_url, headers=SUPABASE_SERVICE_HEADERS)
                                doctor_res.raise_for_status()
                                doctor_info = doctor_res.json()
                                doctor_email = doctor_info[0]['email'] if doctor_info and doctor_info[0].get('email') else 'N/A'
                                writer.update_page_form_field_values(writer.pages[page_num], {"Fono/E-Mail Contacto": doctor_email})
                            elif field_name == "Salud pública" and est.get('procedencia_salud_publica'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Salud pública": "/Yes"})
                            elif field_name == "Particular" and est.get('procedencia_particular'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Particular": "/Yes"})
                            elif field_name == "Escuela" and est.get('procedencia_escuela'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Escuela": "/Yes"})
                            elif field_name == "Otro" and est.get('procedencia_otro'):
                                writer.update_page_form_field_values(writer.pages[page_num], {"Otro": "/Yes"})

        output_pdf = io.BytesIO()
        writer.write(output_pdf)
        output_pdf.seek(0)

        # Aquí es donde integrarías la API de Google Drive
        # Por ahora, solo se devuelve éxito simulado
        return jsonify({"success": True, "message": "Formulario enviado a Google Drive (simulado)."})

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error de conexión con la base de datos al enviar a Drive: {e}")
        return jsonify({"success": False, "message": f"Error de conexión con la base de datos: {str(e)}"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al enviar a Drive: {e}")
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500


# Nuevo endpoint para obtener los datos de un estudiante por ID para precargar el modal
@app.route('/api/estudiante/<estudiante_id>', methods=['GET'])
@login_required
def get_estudiante_data(estudiante_id):
    """
    Endpoint para obtener los datos completos de un estudiante por su ID.
    Utilizado por el frontend para precargar el modal de edición.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    
    print(f"DEBUG: Solicitud API para obtener datos de estudiante: {estudiante_id}")
    try:
        # Usar SUPABASE_SERVICE_HEADERS para asegurar que se puedan leer todos los campos,
        # incluso si RLS para la anon key es más restrictivo.
        url = f"{SUPABASE_URL}/rest/v1/estudiantes_nomina?id=eq.{estudiante_id}&select=*"
        res = requests.get(url, headers=SUPABASE_SERVICE_HEADERS)
        res.raise_for_status()
        data = res.json()
        
        if data:
            print(f"DEBUG: Datos de estudiante {estudiante_id} obtenidos: {data[0]}")
            return jsonify({"success": True, "estudiante": data[0]})
        
        print(f"DEBUG: Estudiante {estudiante_id} no encontrado.")
        return jsonify({"success": False, "message": "Estudiante no encontrado"}), 404
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Error al obtener datos del estudiante {estudiante_id}: {e} - {res.text if 'res' in locals() else ''}")
        return jsonify({"success": False, "message": "Error de conexión con la base de datos"}), 500
    except Exception as e:
        print(f"ERROR: Error inesperado al obtener datos del estudiante {estudiante_id}: {e}")
        return jsonify({"success": False, "message": "Error interno del servidor"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

