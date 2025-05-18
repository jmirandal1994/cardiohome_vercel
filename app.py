from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
import json
import requests
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_super_segura'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx'}

USUARIOS_FILE = 'usuarios.json'
EVENTOS_FILE = 'eventos.json'

def permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cargar_usuarios():
    if not os.path.exists(USUARIOS_FILE):
        return {}
    with open(USUARIOS_FILE, 'r') as f:
        return json.load(f)

def guardar_usuarios(data):
    with open(USUARIOS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def cargar_eventos():
    if not os.path.exists(EVENTOS_FILE):
        return []
    with open(EVENTOS_FILE, 'r') as f:
        return json.load(f)

def guardar_eventos(data):
    with open(EVENTOS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuarios = cargar_usuarios()
    usuario = request.form['username']
    clave = request.form['password']
    if usuario in usuarios and usuarios[usuario]['password'] == clave:
        session['usuario'] = usuario
        return redirect(url_for('dashboard'))
    flash('Usuario o contraseña incorrecta')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))
    usuario = session['usuario']
    usuarios = cargar_usuarios()
    eventos = cargar_eventos()
    establecimientos = usuarios[usuario]['establecimientos']
    return render_template('dashboard.html', usuario=usuario, establecimientos=establecimientos, eventos=eventos)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/agregar', methods=['POST'])
def admin_agregar():
    usuarios = cargar_usuarios()
    eventos = cargar_eventos()

    nombre = request.form['nombre']
    fecha = request.form['fecha']
    horario = request.form['horario']
    obs = request.form['obs']
    doctora = request.form['doctora']
    archivo = request.files['formulario']

    if archivo and permitido(archivo.filename):
        if doctora in usuarios:
            if nombre not in usuarios[doctora]['establecimientos']:
                usuarios[doctora]['establecimientos'].append(nombre)

    eventos.append({
        'fecha': fecha,
        'horario': horario,
        'establecimiento': nombre,
        'obs': obs
    })

    guardar_usuarios(usuarios)
    guardar_eventos(eventos)

    return redirect(url_for('dashboard'))

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))

    archivos = request.files.getlist('archivo')
    if not archivos or archivos[0].filename == '':
        return 'No se seleccionó ningún archivo.', 400

    mensajes = []
    adjuntos = []

    for archivo in archivos:
        if permitido(archivo.filename):
            mensajes.append(f'✔ {archivo.filename}')
            adjunto = base64.b64encode(archivo.read()).decode()
            adjuntos.append({"filename": archivo.filename, "content": adjunto})
        else:
            mensajes.append(f'✖ {archivo.filename} (no permitido)')

    enviar_correo_sendgrid(
        asunto=f'Nuevos formularios desde {establecimiento}',
        cuerpo=f'Doctora: {session["usuario"]}\nEstablecimiento: {establecimiento}\nSe subieron {len(mensajes)} archivo(s).',
        adjuntos=adjuntos
    )
    return "Archivos procesados:<br>" + "<br>".join(mensajes)

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
SENDGRID_FROM = 'noreply@cardiohome.cl'
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
