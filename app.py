from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, Response
import os
import requests
import base64
from werkzeug.utils import secure_filename
from datetime import datetime, date
from openpyxl import load_workbook
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject, NumberObject
import mimetypes
import io
import uuid
import json

app = Flask(__name__)
app.secret_key = 'clave_super_segura'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx'}
PDF_BASE = 'FORMULARIO TIPO NEUROLOGIA INFANTIL EDITABLE.pdf'

# -------------------- Supabase Config --------------------
SUPABASE_URL = 'https://rbzxolreglwndvsrxhmg.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y'
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'jmiraandal@gmail.com'
SENDGRID_TO = 'jmiraandal@gmail.com'

# -------------------- Utilidades --------------------
def permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_age(birth_date):
    today = date.today()
    years = today.year - birth_date.year
    months = today.month - birth_date.month
    if months < 0:
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    name = name.lower()
    if name.endswith("a"):
        return "F"
    return "M"

def enviar_correo_sendgrid(asunto, cuerpo, adjuntos=None):
    if not SENDGRID_API_KEY:
        print("Falta SENDGRID_API_KEY en variables de entorno")
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
    except Exception as e:
        print(f"Error al enviar correo con SendGrid: {e}")
# -------------------- Rutas --------------------

import pandas as pd
import unicodedata

def normalizar(texto):
    if not isinstance(texto, str):
        return ""
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = texto.replace(" ", "_")
    return texto

from openpyxl import load_workbook
from datetime import datetime, date
from flask import render_template, request, session, redirect, url_for, flash

def calculate_age(birth_date):
    today = date.today()
    years = today.year - birth_date.year
    months = today.month - birth_date.month
    if months < 0:
        years -= 1
        months += 12
    return f"{years} años con {months} meses"

def guess_gender(name):
    name = name.lower()
    if name.endswith("a"):
        return "F"
    return "M"

@app.route('/relleno_formularios', methods=['GET', 'POST'])
def relleno_formularios():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        establecimiento = request.form.get('establecimiento')
        file = request.files.get('excel')

        if not file or file.filename == '':
            flash('No se ha seleccionado ningún archivo.', 'error')
            return redirect(request.url)

        try:
            wb = load_workbook(file)
            ws = wb.active

            estudiantes = []
            i = 2  # Comenzamos en la fila 2
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or row[0] is None:
                    continue

                nombre, rut, fecha_nac_str, nacionalidad = row[:4]

                try:
                    if isinstance(fecha_nac_str, datetime):
                        fecha_nac = fecha_nac_str.date()
                    else:
                        try:
                            fecha_nac = datetime.strptime(str(fecha_nac_str), "%d-%m-%y").date()
                        except ValueError:
                            fecha_nac = datetime.strptime(str(fecha_nac_str), "%d-%m-%Y").date()
                except Exception as e:
                    print(f"⚠️ Fila {i} con fecha inválida: {fecha_nac_str} ({e})")
                    i += 1
                    continue

                edad = calculate_age(fecha_nac)
                sexo = guess_gender(nombre.split()[0])

                estudiante = {
                    'nombre': nombre,
                    'rut': rut,
                    'fecha_nacimiento': fecha_nac.strftime("%d-%m-%Y"),
                    'edad': edad,
                    'nacionalidad': nacionalidad,
                    'sexo': sexo
                }
                estudiantes.append(estudiante)
                i += 1

            session['estudiantes'] = estudiantes
            session['establecimiento'] = establecimiento

            return render_template('formulario_relleno.html', estudiantes=estudiantes)

        except Exception as e:
            print(f"❌ Error al procesar el archivo Excel: {e}")
            flash('Error al procesar el archivo Excel. Verifique que el formato sea correcto.', 'error')
            return redirect(request.url)

    return render_template('subir_excel.html')


from flask import Flask, request, redirect, url_for, session, send_file
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, BooleanObject, DictionaryObject
from datetime import datetime
import io, os

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # Datos del formulario
    nombre = request.form['nombre']
    rut = request.form['rut']
    fecha_nac = request.form['fecha_nacimiento']
    edad = request.form['edad']
    nacionalidad = request.form['nacionalidad']
    sexo = request.form['sexo']
    estado = request.form['estado']
    diagnostico = request.form['diagnostico']
    fecha_reeval = request.form['fecha_reevaluacion']
    derivaciones = request.form['derivaciones']
    fecha_eval = datetime.today().strftime('%d/%m/%Y')  # día/mes/año

    # Ruta al PDF base
    PDF_BASE = os.path.join("static", "FORMULARIO.pdf")
    reader = PdfReader(PDF_BASE)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])

    # Campos del formulario
    campos = {
        "nombre": nombre,
        "rut": rut,
        "fecha_nacimiento": fecha_nac,
        "nacionalidad": nacionalidad,
        "edad": edad,
        "diagnostico_1": diagnostico,
        "diagnostico_2": diagnostico,
        "estado_general": estado,
        "fecha_evaluacion": fecha_eval,
        "fecha_reevaluacion": fecha_reeval,
        "derivaciones": derivaciones,
        "sexo_f": "X" if sexo == "F" else "",
        "sexo_m": "X" if sexo == "M" else "",
    }

    writer.update_page_form_field_values(writer.pages[0], campos)

    # Forzar visibilidad de los campos rellenados
    if "/AcroForm" in writer._root_object:
        writer._root_object["/AcroForm"].update({
            NameObject("/NeedAppearances"): BooleanObject(True)
        })
    else:
        writer._root_object.update({
            NameObject("/AcroForm"): DictionaryObject({
                NameObject("/NeedAppearances"): BooleanObject(True)
            })
        })

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    nombre_archivo = f"{nombre.replace(' ', '_')}_{rut}_formulario.pdf"
    return send_file(output, as_attachment=True, download_name=nombre_archivo, mimetype='application/pdf')
    
@app.route('/subir_excel/<int:evento_id>', methods=['POST'])
def subir_excel(evento_id):
    if 'excel' not in request.files:
        return "Archivo no enviado", 400

    file = request.files['excel']
    if file.filename == '':
        return "Nombre de archivo vacío", 400

    wb = load_workbook(file)
    sheet = wb.active

    estudiantes = []

    for row in sheet.iter_rows(min_row=2, values_only=True):
        nombre, rut, fecha_nac_str, nacionalidad = row[:4]
        if not nombre or not rut or not fecha_nac_str:
            continue  # ignora filas incompletas

        fecha_nac = datetime.strptime(str(fecha_nac_str), '%d/%m/%Y')
        edad = calculate_age(fecha_nac)
        genero = guess_gender(nombre)

        estudiantes.append({
            "nombre": nombre,
            "rut": rut,
            "fecha_nacimiento": fecha_nac.strftime('%d/%m/%Y'),
            "edad": edad,
            "nacionalidad": nacionalidad,
            "genero": genero
        })

    session['estudiantes'] = estudiantes
    session['evento_id'] = evento_id

    return redirect(url_for('rellenar_formularios'))

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario = request.form['username']
    clave = request.form['password']
    url = f"{SUPABASE_URL}/rest/v1/doctoras?usuario=eq.{usuario}&password=eq.{clave}"
    res = requests.get(url, headers=SUPABASE_HEADERS)
    data = res.json()
    if data:
        session['usuario'] = usuario
        session['usuario_id'] = data[0]['id']
        return redirect(url_for('dashboard'))
    flash('Usuario o contraseña incorrecta')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))

    print("👤 usuario:", session.get('usuario'))
    print("🆔 usuario_id:", session.get('usuario_id'))

    usuario = session['usuario']
    usuario_id = session['usuario_id']

    # Campos necesarios para todos los eventos
    campos = "id,nombre,fecha,horario,observaciones,cantidad_alumnos,url_archivo,nombre_archivo"

    # Obtener los eventos asignados
    if usuario != 'admin':
        url_eventos = (
            f"{SUPABASE_URL}/rest/v1/establecimientos"
            f"?doctora_id=eq.{usuario_id}"
            f"&select={campos}"
        )
    else:
        url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos}"

    res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
    eventos = res_eventos.json()

    # Ordenar por hora de inicio si hay eventos
    if isinstance(eventos, list):
        eventos.sort(key=lambda e: e.get('horario', '').split(' - ')[0])

    # Obtener formularios (para todos)
    res_formularios = requests.get(f"{SUPABASE_URL}/rest/v1/formularios_subidos", headers=SUPABASE_HEADERS)
    try:
        formularios = res_formularios.json()
        if isinstance(formularios, str):
            import json
            formularios = json.loads(formularios)
    except Exception as e:
        print("❌ Error al procesar JSON de formularios:", e)
        formularios = []

    # Variables adicionales solo para el perfil admin
    doctoras = []
    establecimientos = []
    conteo = {}

    if usuario == 'admin':
        # Obtener lista de doctoras
        res_doctoras = requests.get(f"{SUPABASE_URL}/rest/v1/doctoras", headers=SUPABASE_HEADERS)
        doctoras = res_doctoras.json()

        # Obtener todos los establecimientos
        res_establecimientos = requests.get(f"{SUPABASE_URL}/rest/v1/establecimientos?select={campos}", headers=SUPABASE_HEADERS)
        establecimientos = res_establecimientos.json()

        # Contar formularios por establecimiento
        for f in formularios:
            if isinstance(f, dict) and 'establecimientos_id' in f:
                est_id = f['establecimientos_id']
                conteo[est_id] = conteo.get(est_id, 0) + 1

    return render_template(
        'dashboard.html',
        usuario=usuario,
        eventos=eventos,
        doctoras=doctoras,
        establecimientos=establecimientos,
        formularios=formularios,
        conteo=conteo
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/agregar', methods=['POST'])
def admin_agregar():
    import uuid
    nombre = request.form['nombre']
    fecha = request.form['fecha']
    horario = request.form['horario']
    obs = request.form['obs']
    doctora_id = request.form['doctora'].strip()
    cantidad_alumnos = request.form.get('alumnos')
    archivo = request.files['formulario']

    if not doctora_id or len(doctora_id) < 10:
        flash("❌ Debes seleccionar una doctora válida.")
        return redirect(url_for('dashboard'))

    if not archivo or not permitido(archivo.filename):
        flash("Archivo no válido.")
        return redirect(url_for('dashboard'))

    # Procesar archivo
    nuevo_id = str(uuid.uuid4())
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    # Subir a Supabase Storage
    upload_url = f"{SUPABASE_URL}/storage/v1/object/formularios/{nuevo_id}/{filename}"
    headers_storage = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": mime_type
    }
    res_upload = requests.put(upload_url, headers=headers_storage, data=file_data)

    if res_upload.status_code not in [200, 201]:
        flash("❌ Error al subir el archivo.")
        return redirect(url_for('dashboard'))

    url_publica = f"{SUPABASE_URL}/storage/v1/object/public/formularios/{nuevo_id}/{filename}"

    # Insertar establecimiento con archivo incluido
    data = {
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

    headers = SUPABASE_HEADERS.copy()
    headers["Prefer"] = "return=representation"

    url = f"{SUPABASE_URL}/rest/v1/establecimientos"
    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 201:
        print("❌ ERROR AL GUARDAR ESTABLECIMIENTO:", response.text)
        flash("❌ Error al guardar el establecimiento.")
        return redirect(url_for('dashboard'))

    establecimiento_id = response.json()[0]['id']

    # Registrar en formularios_subidos si deseas dejar trazabilidad (opcional)
    data_formulario = {
        "doctoras_id": doctora_id,
        "establecimientos_id": establecimiento_id,
        "nombre_archivo": filename,
        "url_archivo": url_publica
    }

    res_insert = requests.post(
        f"{SUPABASE_URL}/rest/v1/formularios_subidos",
        headers=SUPABASE_HEADERS,
        json=data_formulario
    )

    if res_insert.status_code == 201:
        flash("✅ Establecimiento y formulario agregado correctamente.")
    else:
        flash("⚠️ Establecimiento agregado, pero error al guardar el formulario.")

    return redirect(url_for('dashboard'))
from werkzeug.utils import secure_filename
import os

import mimetypes

import mimetypes

# 👉 Agrega esta línea junto a tus claves Supabase al inicio de tu app.py
SUPABASE_SERVICE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NzU0MTc4NywiZXhwIjoyMDYzMTE3Nzg3fQ.i3ixl5ws3Z3QTxIcZNjI29ZknRmJwwQfUyLmX0Z0khc'# ⚠️ Solo para backend, ¡nunca en frontend!

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo')
    if not archivos or archivos[0].filename == '':
        return 'No se seleccionó ningún archivo.', 400

    usuario_id = session['usuario_id']
    mensajes = []

    for archivo in archivos:
        if permitido(archivo.filename):
            filename = secure_filename(archivo.filename)
            file_data = archivo.read()
            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

            # 📤 1. Subir archivo a Supabase Storage usando service_role
            upload_url = f"{SUPABASE_URL}/storage/v1/object/formularios/{establecimiento}/{filename}"
            headers_storage = {
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": mime_type
            }

            res_upload = requests.put(upload_url, headers=headers_storage, data=file_data)
            print("🧾 PUT response:", res_upload.status_code, res_upload.text)

            if res_upload.status_code in [200, 201]:
                # 🌐 2. Construir URL pública del archivo
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/formularios/{establecimiento}/{filename}"

                # 📝 3. Guardar en la tabla 'formularios_subidos'
                data = {
                    "doctoras_id": usuario_id,
                    "establecimientos_id": establecimiento,
                    "nombre_archivo": filename,
                    "url_archivo": url_publica
                }

                res_insert = requests.post(
                    f"{SUPABASE_URL}/rest/v1/formularios_subidos",
                    headers=SUPABASE_HEADERS,
                    json=data
                )

                print("🧾 POST response:", res_insert.status_code, res_insert.text)

                if res_insert.status_code == 201:
                    mensajes.append(f'✔ {filename} subido correctamente')
                else:
                    mensajes.append(f'✖ Error al guardar en la base de datos: {res_insert.text}')
            else:
                mensajes.append(f'✖ Error al subir {filename} al bucket: {res_upload.text}')
        else:
            mensajes.append(f'✖ {archivo.filename} (tipo no permitido)')

    return "Resultado:<br>" + "<br>".join(mensajes)
    
    from flask import send_from_directory

@app.route('/descargar/<nombre_archivo>')
def descargar_archivo(nombre_archivo):
    return send_from_directory('static/formularios', nombre_archivo, as_attachment=True)

from flask import Response
import mimetypes

@app.route('/admin/registrar_colegio', methods=['POST'])
def registrar_colegio():
    if session.get('usuario') != 'admin':
        return redirect(url_for('dashboard'))

    import uuid
    nuevo_id = str(uuid.uuid4())
    nombre = request.form.get('nombre')
    fecha = request.form.get('fecha')
    obs = request.form.get('obs', '')
    alumnos = request.form.get('alumnos')

    # Validación rápida
    if not nombre or not fecha:
        flash("❌ Nombre y fecha son obligatorios.")
        return redirect(url_for('colegios'))

    data = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha_evaluacion": fecha,
        "observaciones": obs,
        "cantidad_alumnos": int(alumnos) if alumnos else None
    }

    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/colegios_registrados",
        headers={**SUPABASE_HEADERS, "Prefer": "return=representation"},
        json=data
    )

    if res.status_code == 201:
        flash("✅ Colegio registrado correctamente.")
    else:
        print("❌ Error al registrar:", res.status_code, res.text)
        flash("❌ Error al registrar el colegio.")

    return redirect(url_for('colegios'))

    import uuid
    nuevo_id = str(uuid.uuid4())
    nombre = request.form['nombre']
    fecha = request.form['fecha']
    obs = request.form.get('obs', '')
    alumnos = request.form.get('alumnos')

    data = {
        "id": nuevo_id,
        "nombre": nombre,
        "fecha_evaluacion": fecha,
        "observaciones": obs,
        "cantidad_alumnos": int(alumnos) if alumnos else None
    }

    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/colegios_registrados",
        headers=SUPABASE_HEADERS,
        json=data
    )

    if res.status_code == 201:
        flash("✅ Colegio registrado correctamente.")
    else:
        flash("❌ Error al registrar el colegio.")
    return redirect(url_for('colegios'))

@app.route('/colegios')
def colegios():
    if session.get('usuario') != 'admin':
        return redirect(url_for('dashboard'))

    res = requests.get(f"{SUPABASE_URL}/rest/v1/colegios_registrados?select=*", headers=SUPABASE_HEADERS)
    colegios = res.json()
    colegios.sort(key=lambda x: x.get('fecha_evaluacion') or '', reverse=True)

    return render_template('colegios.html', colegios=colegios)

@app.route('/descargar_formulario/<establecimiento>/<nombre_archivo>')
def descargar_formulario(establecimiento, nombre_archivo):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    # Construye la URL del archivo en Supabase Storage
    supabase_url = f"{SUPABASE_URL}/storage/v1/object/formularios/{establecimiento}/{nombre_archivo}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }

    res = requests.get(supabase_url, headers=headers)

    if res.status_code == 200:
        # Detecta tipo MIME automáticamente según la extensión
        mime_type = mimetypes.guess_type(nombre_archivo)[0] or 'application/octet-stream'

        return Response(
            res.content,
            mimetype=mime_type,
            headers={
                "Content-Disposition": f"attachment; filename={nombre_archivo}"
            }
        )
    else:
        return f"Error al descargar archivo: {res.status_code} - {res.text}", 500


@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    cantidad = request.form.get('alumnos')
    usuario = session['usuario']

    # 🔍 Consultar el nombre del establecimiento por su ID (uuid)
    res_est = requests.get(
        f"{SUPABASE_URL}/rest/v1/establecimientos?id=eq.{establecimiento}&select=nombre",
        headers=SUPABASE_HEADERS
    )
    if res_est.status_code == 200 and res_est.json():
        nombre_establecimiento = res_est.json()[0]['nombre']
    else:
        nombre_establecimiento = 'Desconocido'

    # ✉️ Enviar correo con el nombre real
    enviar_correo_sendgrid(
        asunto=f'Alumnos evaluados - {nombre_establecimiento}',
        cuerpo=f'Doctora: {usuario}\nEstablecimiento: {nombre_establecimiento}\nCantidad evaluada: {cantidad}'
    )
    return f'Datos enviados correctamente: {cantidad} alumnos evaluados.'

# -------------------- SendGrid --------------------
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'jmiraandal@gmail.com'
SENDGRID_TO = 'jmiraandal@gmail.com'

def enviar_correo_sendgrid(asunto, cuerpo, adjuntos=None):
    if not SENDGRID_API_KEY:
        print("Falta SENDGRID_API_KEY en variables de entorno")
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
    except Exception as e:
        print(f"Error al enviar correo con SendGrid: {e}")

# -------------------- MAIN --------------------
if __name__ == '__main__':
    app.run(debug=True)







