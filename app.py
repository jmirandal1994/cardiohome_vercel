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

    doctoras = []
    if usuario == 'admin':
        res_doctoras = requests.get(f"{SUPABASE_URL}/rest/v1/doctoras", headers=SUPABASE_HEADERS)
        doctoras = res_doctoras.json()

    return render_template('dashboard.html', usuario=usuario, establecimientos=[], eventos=eventos, doctoras=doctoras)

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
    archivo = request.files['formulario']

    if archivo and permitido(archivo.filename):
        data = {
            "nombre": nombre,
            "fecha": fecha,
            "horario": horario,
            "observaciones": obs,
            "doctora_id": doctora_id
        }
        url = f"{SUPABASE_URL}/rest/v1/establecimientos"
        response = requests.post(url, headers=SUPABASE_HEADERS, json=data)

        print("STATUS:", response.status_code)
        print("RESPUESTA:", response.text)

    return redirect(url_for('dashboard'))

from werkzeug.utils import secure_filename
import os

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo')
    if not archivos or archivos[0].filename == '':
        return 'No se seleccionó ningún archivo.', 400

    usuario_id = session['usuario_id']
    mensajes = []

    os.makedirs('static/uploads', exist_ok=True)  # Asegura que exista la carpeta

    for archivo in archivos:
        if permitido(archivo.filename):
            filename = secure_filename(archivo.filename)
            local_path = os.path.join('static/uploads', filename)
            archivo.save(local_path)

            data = {
                "doctoras_id": usuario_id,
                "establecimientos_id": establecimiento,
                "nombre_archivo": filename,
                "url_archivo": f"/static/uploads/{filename}"
            }

            url = f"{SUPABASE_URL}/rest/v1/formularios_subidos"
            res = requests.post(url, headers=SUPABASE_HEADERS, json=data)

            if res.status_code == 201:
                mensajes.append(f'✔ {filename} subido correctamente')
            else:
                mensajes.append(f'✖ Error al subir {filename}: {res.text}')

        else:
            mensajes.append(f'✖ {archivo.filename} (tipo no permitido)')

    return "Resultado:<br>" + "<br>".join(mensajes)
    
    from flask import send_from_directory

@app.route('/descargar/<nombre_archivo>')
def descargar_archivo(nombre_archivo):
    return send_from_directory('static/formularios', nombre_archivo, as_attachment=True)


@app.route('/evaluados/<establecimiento>', methods=['POST'])
def evaluados(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    cantidad = request.form.get('alumnos')
    usuario = session['usuario']
    enviar_correo_sendgrid(
        asunto=f'Alumnos evaluados - {establecimiento}',
        cuerpo=f'Doctora: {usuario}\nEstablecimiento: {establecimiento}\nCantidad evaluada: {cantidad}'
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
