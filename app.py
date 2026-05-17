from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import psycopg2
import random
import string
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# LLAVE PARA CIFRAR LAS SESIONES (COOKIES) DEL ADMINISTRADOR
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("¡Error Crítico! No se encontró app.secret_key en el entorno.")

# CONFIGURACIÓN DE ACCESO AL POS
ADMIN_USER = os.getenv("ADMIN_USER")
if not ADMIN_USER:
    raise ValueError("¡Error Crítico! No se encontró ADMIN_USER en el entorno.")
ADMIN_PASS = os.getenv("ADMIN_PASS")
if not ADMIN_PASS:
    raise ValueError("¡Error Crítico! No se encontró ADMIN_PASS en el entorno.")

# --- CONFIGURACIÓN Y SEGURIDAD ---
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if not API_SECRET_KEY:
    raise ValueError("¡Error Crítico! No se encontró API_SECRET_KEY en el entorno.")

# URL de conexión que nos dará Render (en local la leerá del .env)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("¡Error Crítico! No se encontró DATABASE_URL de PostgreSQL.")


def get_db_connection():
    """Establece una conexión segura con el motor PostgreSQL"""
    # sslmode='require' es obligatorio para conectar con Render de forma segura
    return psycopg2.connect(DATABASE_URL, sslmode='require')


# --- 1. CAPA DE DATOS (Adaptada a PostgreSQL) ---
def init_db():
    print("[BD] Asegurando la existencia de tablas en PostgreSQL...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabla de Usuarios (Wallet) - PostgreSQL usa SERIAL para autoincrementales
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            rut TEXT PRIMARY KEY,
            nombre TEXT,
            puntos_wallet INTEGER DEFAULT 0,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de Transacciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id SERIAL PRIMARY KEY,
            codigo_tiza TEXT UNIQUE,
            modelo_declarado TEXT,
            estado TEXT,
            rut_usuario TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rut_usuario) REFERENCES usuarios (rut)
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()
    print("[BD] Infraestructura de tablas validada con éxito.")


def generar_codigo_tiza():
    letra = random.choice(string.ascii_uppercase)
    numeros = ''.join(random.choices(string.digits, k=2))
    return f"#{letra}{numeros}"


# --- 2. RUTAS WEB (Frontend) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    rut = request.form.get('rut')
    nombre = request.form.get('nombre')
    modelo = request.form.get('modelo')
    
    # FILTRO DE SEGURIDAD NACIONAL: Validar el RUT matemáticamente
    if not validar_rut_chileno(rut):
        # Si el RUT es falso o inválido, redirige con un aviso o puedes retornar un error
        return "<h3>Error: El RUT ingresado no es válido en el sistema nacional.</h3><a href='/'>Volver a intentar</a>", 400
        
    # Limpiar formato para guardarlo estándar en la base de datos (ej: 19123456K)
    rut_limpio = rut.replace(".", "").replace("-", "").upper().strip()
    codigo = generar_codigo_tiza()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT rut FROM usuarios WHERE rut = %s", (rut_limpio,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (rut, nombre, puntos_wallet) VALUES (%s, %s, 0)", (rut_limpio, nombre))
    
    cursor.execute('''
        INSERT INTO transacciones (codigo_tiza, modelo_declarado, estado, rut_usuario)
        VALUES (%s, %s, 'ESPERANDO_DEPOSITO', %s)
    ''', (codigo, modelo, rut_limpio))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('mostrar_codigo', codigo=codigo))

@app.route('/codigo/<codigo>')
def mostrar_codigo(codigo):
    return render_template('codigo.html', codigo=codigo)


# --- 3. RUTAS API (Backend seguro para el Hardware y futuro POS) ---

@app.route('/api/hardware/confirmar', methods=['POST'])
def api_confirmar_deposito():
    datos = request.get_json()
    
    llave_recibida = datos.get('api_key')
    if llave_recibida != API_SECRET_KEY:
        return jsonify({"error": "Acceso denegado. Llave incorrecta."}), 403

    codigo_recibido = datos.get('codigo_tiza')
    if not codigo_recibido:
        return jsonify({"error": "Falta el código de transacción"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT rut_usuario, estado FROM transacciones WHERE codigo_tiza = %s", (codigo_recibido,))
    transaccion = cursor.fetchone()
    
    if not transaccion:
        cursor.close()
        conn.close()
        return jsonify({"error": "Código no existe en la base de datos"}), 404
        
    rut_usuario, estado = transaccion
    
    if estado != 'ESPERANDO_DEPOSITO':
        cursor.close()
        conn.close()
        return jsonify({"error": "Esta transacción ya fue procesada"}), 400
        
    try:
        cursor.execute("UPDATE transacciones SET estado = 'DEPOSITADO' WHERE codigo_tiza = %s", (codigo_recibido,))
        
        PUNTOS_POR_RECICLAJE = 1500
        cursor.execute("UPDATE usuarios SET puntos_wallet = puntos_wallet + %s WHERE rut = %s", (PUNTOS_POR_RECICLAJE, rut_usuario))
        
        conn.commit()
        respuesta = {"status": "success", "mensaje": f"Depósito confirmado. {PUNTOS_POR_RECICLAJE} puntos sumados al RUT {rut_usuario}"}
        codigo_http = 200
    except Exception as e:
        conn.rollback()
        respuesta = {"status": "error", "mensaje": f"Error interno: {str(e)}"}
        codigo_http = 500
    finally:
        cursor.close()
        conn.close()

    return jsonify(respuesta), codigo_http

# --- VISTA DEL CLIENTE: MI WALLET ---
@app.route('/wallet', methods=['GET', 'POST'])
def mi_wallet():
    puntos = None
    rut_buscado = None
    error = None
    
    if request.method == 'POST':
        rut = request.form.get('rut')
        
        if not validar_rut_chileno(rut):
            error = "RUT inválido. Por favor, revisa el formato."
        else:
            # ... adentro de tu ruta /wallet, donde se ejecuta la consulta:
            rut_limpio = rut.replace(".", "").replace("-", "").upper().strip()
            conn = get_db_connection()
            cursor = conn.cursor()

            # Usamos REPLACE en SQL para que compare el RUT de la base de datos sin guiones ni puntos
            cursor.execute('''
                SELECT puntos_wallet FROM usuarios 
                WHERE rut = %s 
                OR REPLACE(REPLACE(rut, '-', ''), '.', '') = %s
            ''', (rut, rut_limpio))

            resultado = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if resultado:
                puntos = resultado[0]
                rut_buscado = rut
            else:
                error = "No encontramos este RUT en nuestra base de datos. ¡Anímate a hacer tu primer reciclaje!"
                
    return render_template('wallet.html', puntos=puntos, rut=rut_buscado, error=error)

# --- 4. PANEL DE ADMINISTRACIÓN (POS) ---

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        usuario = request.form.get('username')
        clave = request.form.get('password')
        
        # Validar contra las variables de entorno seguras
        if usuario == ADMIN_USER and clave == ADMIN_PASS:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Credenciales incorrectas. Acceso denegado."
            
    return render_template('login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
def admin_dashboard():
    # ESCUDO DE AUTENTICACIÓN: Si no hay sesión activa, rebota al login
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(puntos_wallet), 0) FROM usuarios")
        kpis = cursor.fetchone()
        total_usuarios = kpis[0]
        total_puntos = kpis[1]
        
        cursor.execute("SELECT rut, nombre, puntos_wallet, TO_CHAR(fecha_registro, 'DD-MM-YYYY HH24:MI') FROM usuarios ORDER BY fecha_registro DESC")
        usuarios = cursor.fetchall()
        
        cursor.execute('''
            SELECT codigo_tiza, modelo_declarado, estado, rut_usuario, TO_CHAR(fecha, 'DD-MM-YYYY HH24:MI') 
            FROM transacciones 
            ORDER BY fecha DESC LIMIT 50
        ''')
        transacciones = cursor.fetchall()
        
    except Exception as e:
        print(f"Error: {e}")
        total_usuarios, total_puntos, usuarios, transacciones = 0, 0, [], []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin.html', total_usuarios=total_usuarios, total_puntos=total_puntos, usuarios=usuarios, transacciones=transacciones)

def validar_rut_chileno(rut):
    """Aplica el algoritmo Módulo 11 para verificar la validez del RUT"""
    if not rut:
        return False
    # Limpiar caracteres comunes
    rut = rut.replace(".", "").replace("-", "").upper().strip()
    if len(rut) < 2:
        return False
    
    cuerpo = rut[:-1]
    dv = rut[-1]
    
    if not cuerpo.isdigit():
        return False
        
    # Calcular dígito verificador esperado
    suma = 0
    multiplicador = 2
    for c in reversed(cuerpo):
        suma += int(c) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2
        
    dv_esperado = 11 - (suma % 11)
    if dv_esperado == 11:
        dv_esperado = "0"
    elif dv_esperado == 10:
        dv_esperado = "K"
    else:
        dv_esperado = str(dv_esperado)
        
    return dv == dv_esperado

# Inicializar base de datos de manera segura al arrancar el servicio
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)