from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
import requests
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_super_segura'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xls', 'xlsx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

USUARIOS = {
    'admin': {'password': 'admin123', 'establecimientos': []},
    'doctora1': {'password': '1234', 'establecimientos': ['Escuela A', 'Liceo B']},
    'doctora2': {'password': 'abcd', 'establecimientos': []}
}

EVENTOS = [
    {'fecha': '20/05/2025', 'horario': '09:00 - 10:30', 'establecimiento': 'Escuela A', 'obs': 'Evaluación inicial'},
    {'fecha': '21/05/2025', 'horario': '11:00 - 12:30', 'establecimiento': 'Liceo B', 'obs': 'Entrega de informes'}
]

def permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario = request.form['username']
    clave = request.form['password']
    if usuario in USUARIOS and USUARIOS[usuario]['password'] == clave:
        session['usuario'] = usuario
        return redirect(url_for('dashboard'))
    flash('Usuario o contraseña incorrecta')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('index'))
    usuario = session['usuario']
    establecimientos = USUARIOS[usuario]['establecimientos']
    return render_template('dashboard.html', usuario=usuario, establecimientos=establecimientos, eventos=EVENTOS)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/subir/<establecimiento>', methods=['POST'])
def subir(establecimiento):
    if 'usuario' not in session:
        return redirect(url_for('index'))
    archivos = request.files.getlist('archivo')
    if not archivos or archivos[0].filename == '':
        return 'No se seleccionó ningún archivo.', 400
    mensajes = []
    for archivo in archivos:
        if permitido(archivo.filename):
            filename = secure_filename(f"{session['usuario']}_{establecimiento}_{archivo.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            archivo.save(filepath)
            mensajes.append(f'✔ {archivo.filename}')
        else:
            mensajes.append(f'✖ {archivo.filename} (no permitido)')
    enviar_correo_sendgrid(
        asunto=f'Nuevos formularios desde {establecimiento}',
        cuerpo=f'Doctora: {session["usuario"]}\nEstablecimiento: {establecimiento}\nSe subieron {len(mensajes)} archivo(s).'
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

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = 'noreply@cardiohome.cl'
SENDGRID_TO = 'jmiraandal@gmail.com'

def enviar_correo_sendgrid(asunto, cuerpo):
    if not SENDGRID_API_KEY:
        print("Falta SENDGRID_API_KEY en variables de entorno")
        return
    data = {
        "personalizations": [{"to": [{"email": SENDGRID_TO}]}],
        "from": {"email": SENDGRID_FROM},
        "subject": asunto,
        "content": [{"type": "text/plain", "value": cuerpo}]
    }
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

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if __name__ == '__main__':
    app.run(debug=True)
