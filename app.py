from flask import Flask, render_template, request, redirect, url_for, jsonify
import psycopg2  # Reemplazamos sqlite3 por psycopg2
import random
import string
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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
    codigo = generar_codigo_tiza()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lógica de negocio (Cambiamos '?' por '%s' para PostgreSQL)
    cursor.execute("SELECT rut FROM usuarios WHERE rut = %s", (rut,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (rut, nombre, puntos_wallet) VALUES (%s, %s, 0)", (rut, nombre))
    
    cursor.execute('''
        INSERT INTO transacciones (codigo_tiza, modelo_declarado, estado, rut_usuario)
        VALUES (%s, %s, 'ESPERANDO_DEPOSITO', %s)
    ''', (codigo, modelo, rut))
    
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


# Inicializar base de datos de manera segura al arrancar el servicio
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)