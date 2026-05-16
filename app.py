from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import random
import string
import os
from dotenv import load_dotenv

# Cargar las variables del archivo .env al sistema
load_dotenv()

app = Flask(__name__)

# --- SEGURIDAD ---
# Ahora Python va a buscar la clave en el entorno. 
# Si por algún motivo no la encuentra, se bloquea por defecto.
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if not API_SECRET_KEY:
    raise ValueError("¡Error Crítico! No se encontró API_SECRET_KEY en las variables de entorno.")

DB_PATH = 'buzon.db'

# --- 1. CAPA DE DATOS (Arquitectura Limpia) ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla de Usuarios (Wallet)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            rut TEXT PRIMARY KEY,
            nombre TEXT,
            puntos_wallet INTEGER DEFAULT 0,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de Transacciones (Relacionada al RUT)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_tiza TEXT UNIQUE,
            modelo_declarado TEXT,
            estado TEXT,
            rut_usuario TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rut_usuario) REFERENCES usuarios (rut)
        )
    ''')
    conn.commit()
    conn.close()

def generar_codigo_tiza():
    letra = random.choice(string.ascii_uppercase)
    numeros = ''.join(random.choices(string.digits, k=2))
    return f"#{letra}{numeros}"

# --- 2. RUTAS WEB (Frontend para el Usuario) ---

@app.route('/')
def index():
    # El nuevo formulario ahora debe pedir el RUT para saber a quién darle los puntos
    return render_template('index.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    rut = request.form.get('rut')
    nombre = request.form.get('nombre')
    modelo = request.form.get('modelo')
    codigo = generar_codigo_tiza()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Lógica de negocio: Si el usuario no existe, lo creamos (Upsert manual)
    cursor.execute("SELECT rut FROM usuarios WHERE rut = ?", (rut,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (rut, nombre, puntos_wallet) VALUES (?, ?, 0)", (rut, nombre))
    
    # Insertar la transacción amarrada al RUT del usuario
    cursor.execute('''
        INSERT INTO transacciones (codigo_tiza, modelo_declarado, estado, rut_usuario)
        VALUES (?, ?, 'ESPERANDO_DEPOSITO', ?)
    ''', (codigo, modelo, rut))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('mostrar_codigo', codigo=codigo))

@app.route('/codigo/<codigo>')
def mostrar_codigo(codigo):
    return render_template('codigo.html', codigo=codigo)


# --- 3. RUTAS API (Backend seguro para el Hardware) ---

@app.route('/api/hardware/confirmar', methods=['POST'])
def api_confirmar_deposito():
    """
    Este endpoint NO es para navegadores. Es exclusivo para que vision_buzon.py
    avise que el celular cayó en la caja y asigne los puntos.
    """
    datos = request.get_json()
    
    # 1. Validación de Seguridad (Evita hackeos)
    llave_recibida = datos.get('api_key')
    if llave_recibida != API_SECRET_KEY:
        return jsonify({"error": "Acceso denegado. Llave de hardware incorrecta."}), 403

    codigo_recibido = datos.get('codigo_tiza')
    if not codigo_recibido:
        return jsonify({"error": "Falta el código de transacción"}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Buscar de quién es este código y si realmente está esperando depósito
    cursor.execute("SELECT rut_usuario, estado FROM transacciones WHERE codigo_tiza = ?", (codigo_recibido,))
    transaccion = cursor.fetchone()
    
    if not transaccion:
        return jsonify({"error": "Código no existe en la base de datos"}), 404
        
    rut_usuario, estado = transaccion
    
    if estado != 'ESPERANDO_DEPOSITO':
        return jsonify({"error": "Esta transacción ya fue procesada o cancelada"}), 400
        
    # --- TRANSACCIÓN SEGURA (Si llegamos aquí, el hardware confirmó físicamente el celular) ---
    try:
        # A) Marcar el depósito como exitoso
        cursor.execute("UPDATE transacciones SET estado = 'DEPOSITADO' WHERE codigo_tiza = ?", (codigo_recibido,))
        
        # B) SUMAR LOS PUNTOS A LA WALLET DEL USUARIO (Ejemplo: 1500 puntos por equipo)
        PUNTOS_POR_RECICLAJE = 1500
        cursor.execute("UPDATE usuarios SET puntos_wallet = puntos_wallet + ? WHERE rut = ?", (PUNTOS_POR_RECICLAJE, rut_usuario))
        
        conn.commit()
        respuesta = {"status": "success", "mensaje": f"Depósito confirmado. {PUNTOS_POR_RECICLAJE} puntos sumados al RUT {rut_usuario}"}
        codigo_http = 200
    except Exception as e:
        conn.rollback()
        respuesta = {"status": "error", "mensaje": "Error interno en la base de datos"}
        codigo_http = 500
    finally:
        conn.close()

    return jsonify(respuesta), codigo_http

# --- INICIALIZAR LA BASE DE DATOS EN PRODUCCIÓN ---
# Al dejar esta línea aquí afuera, Gunicorn la ejecutará sí o sí al arrancar.
init_db() 

if __name__ == '__main__':
    # El app.run ya no necesita el init_db() adentro
    app.run(host='0.0.0.0', port=5000, debug=True)