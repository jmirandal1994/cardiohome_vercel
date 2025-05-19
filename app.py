from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
import requests
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_super_segura'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx'}

# -------------------- Supabase Config --------------------
SUPABASE_URL = 'https://rbzxolreglwndvsrxhmg.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJienhvbHJlZ2x3bmR2c3J4aG1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDE3ODcsImV4cCI6MjA2MzExNzc4N30.BbzsUhed1Y_dJYWFKLAHqtV4cXdvjF_ihGdQ_Bpov3Y'
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# -------------------- Utilidades --------------------
def permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------- Rutas --------------------
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

    usuario = session['usuario']
    usuario_id = session['usuario_id']

    url_eventos = f"{SUPABASE_URL}/rest/v1/establecimientos?doctora_id=eq.{usuario_id}&select=*"
    res_eventos = requests.get(url_eventos, headers=SUPABASE_HEADERS)
    eventos = res_eventos.json()
    # ✅ Ordenar eventos por hora de inicio
    eventos.sort(key=lambda e: e['horario'].split(' - ')[0])

    doctoras = []
    establecimientos = []
    formularios = []
    conteo = {}

    if usuario == 'admin':
        res_doctoras = requests.get(f"{SUPABASE_URL}/rest/v1/doctoras", headers=SUPABASE_HEADERS)
        doctoras = res_doctoras.json()

        res_establecimientos = requests.get(f"{SUPABASE_URL}/rest/v1/establecimientos", headers=SUPABASE_HEADERS)
        establecimientos = res_establecimientos.json()

        res_formularios = requests.get(f"{SUPABASE_URL}/rest/v1/formularios_subidos", headers=SUPABASE_HEADERS)
        
        try:
            formularios = res_formularios.json()
            # Si por alguna razón recibes un string, intenta convertirlo
            if isinstance(formularios, str):
                import json
                formularios = json.loads(formularios)
        except Exception as e:
            print("❌ Error al procesar JSON de formularios:", e)
            formularios = []

        # 👇 Aquí está el fix real
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
    nombre = request.form['nombre']
    fecha = request.form['fecha']
    horario = request.form['horario']
    obs = request.form['obs']
    doctora_id = request.form['doctora']
    cantidad_alumnos = request.form.get('alumnos')
    archivo = request.files['formulario']

    if not archivo or not permitido(archivo.filename):
        flash("Archivo no válido.")
        return redirect(url_for('dashboard'))

    # 1. Crear el establecimiento
    data = {
        "nombre": nombre,
        "fecha": fecha,
        "horario": horario,
        "observaciones": obs,
        "doctora_id": doctora_id,
        "cantidad_alumnos": int(cantidad_alumnos) if cantidad_alumnos else None
    }

    url = f"{SUPABASE_URL}/rest/v1/establecimientos?select=id"
    response = requests.post(url, headers=SUPABASE_HEADERS, json=data)

    if response.status_code != 201:
        flash("❌ Error al guardar el establecimiento.")
        print("ESTAB FALLO:", response.text)
        return redirect(url_for('dashboard'))

    try:
        establecimiento_id = response.json()[0]['id']
    except Exception as e:
        flash("❌ No se pudo obtener el ID del establecimiento.")
        print("Error parsing ID:", e)
        return redirect(url_for('dashboard'))

    # 2. Subir el archivo a Supabase Storage
    filename = secure_filename(archivo.filename)
    file_data = archivo.read()
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    upload_url = f"{SUPABASE_URL}/storage/v1/object/formularios/{establecimiento_id}/{filename}"
    headers_storage = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": mime_type
    }
    res_upload = requests.put(upload_url, headers=headers_storage, data=file_data)

    if res_upload.status_code not in [200, 201]:
        flash("❌ Error al subir el archivo.")
        print("UPLOAD ERROR:", res_upload.text)
        return redirect(url_for('dashboard'))

    # 3. Registrar archivo en formularios_subidos
    url_publica = f"{SUPABASE_URL}/storage/v1/object/public/formularios/{establecimiento_id}/{filename}"

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
        print("INSERT FORM FAIL:", res_insert.text)

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
