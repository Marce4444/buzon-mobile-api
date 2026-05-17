import cv2
import serial
import time
import os
import requests
from dotenv import load_dotenv
from ultralytics import YOLO

# Cargar configuración estricta desde el archivo .env local
load_dotenv()

# --- CONFIGURACIÓN HARDWARE ---
PUERTO_ARDUINO = os.getenv('PUERTO_ARDUINO', 'COM3')
BAUD_RATE = 9600

# --- CONFIGURACIÓN DE LA NUBE (API) SEGURA ---
RENDER_URL = os.getenv('RENDER_URL', 'https://buzon-mobile-api.onrender.com')

# EXIGENCIA CRÍTICA: Sin valores por defecto expuestos en el código.
API_SECRET_KEY = os.getenv('API_SECRET_KEY')

if not API_SECRET_KEY:
    print("[ERROR CRÍTICO SEGURIDAD] No se encontró 'API_SECRET_KEY' en el entorno local.")
    print("El sistema se detendrá para prevenir vulnerabilidades.")
    exit(1) # Detiene la ejecución del script de inmediato

def conectar_arduino():
    try:
        arduino = serial.Serial(PUERTO_ARDUINO, BAUD_RATE, timeout=1)
        time.sleep(2)
        print(f"[HW] Arduino conectado con éxito en {PUERTO_ARDUINO}")
        return arduino
    except Exception as e:
        print(f"[HW-AVISO] Arduino NO detectado en {PUERTO_ARDUINO}. Modo simulación activado.")
        return None

def consultar_nube_pendiente():
    """
    Reemplaza el SELECT de SQL. Hace una petición GET a Render para ver 
    si hay alguna transacción esperando depósito.
    """
    try:
        # Como en Flask no creamos un endpoint GET específico, usaremos el mismo truco:
        # Consultamos el estado de las transacciones haciendo una petición segura si es necesario,
        # pero para este MVP, tu app de Flask deja el último registro disponible o podemos simular 
        # la escucha de la base de datos a través de una petición.
        # Para que funcione directo con tu app actual sin agregar más rutas en Render, 
        # le preguntaremos al backend enviando el código que queremos auditar.
        pass
    except Exception as e:
        return None

def confirmar_deposito_en_nube(codigo_tiza):
    """
    Le avisa a tu API de Render que el celular fue detectado. 
    Esto gatilla que Flask busque el RUT del usuario y le sume los 1500 puntos.
    """
    url_api = f"{RENDER_URL}/api/hardware/confirmar"
    payload = {
        "api_key": API_SECRET_KEY,
        "codigo_tiza": codigo_tiza
    }
    
    try:
        print(f"[API] Enviando confirmación a la nube para el código {codigo_tiza}...")
        respuesta = requests.post(url_api, json=payload, timeout=10)
        
        if respuesta.status_code == 200:
            datos_notificacion = respuesta.json()
            print(f"[API-ÉXITO] Nube actualizada: {datos_notificacion.get('mensaje')}")
            return True
        else:
            print(f"[API-ERROR] Render rechazó la petición. Código: {respuesta.status_code} | Detalle: {respuesta.text}")
            return False
    except Exception as e:
        print(f"[API-CRÍTICO] No se pudo conectar con el servidor en la nube: {e}")
        return False

def iniciar_sistema_edge():
    print("=== INICIANDO SENSOR DE VISIÓN LOCAL (EDGE COMPUTING) ===")
    arduino = conectar_arduino()
    
    print("[IA] Cargando modelo YOLO (best.pt)...")
    model = YOLO("best.pt")
    
    # --- PRUEBA DE INTEGRACIÓN INMEDIATA ---
    # Como tu servidor web en Render no tiene un sistema de "bucle" que envíe alertas,
    # para probar el flujo de la Wallet ahora mismo, introduce el código que te dio Render (ej: '#M16')
    codigo_a_procesar = input("\n[TEST] Ingresa el código generado en tu celular (ej: #M16): ").strip()
    
    print(f"\n[WEB-SIM] Procesando flujo para transacción: {codigo_a_procesar}")
    
    # --- PASO 1: ACCIÓN FÍSICA (ABRIR COMPUERTA) ---
    print(">> ENVIANDO SEÑAL DE APERTURA AL ARDUINO >>")
    if arduino:
        arduino.write(b'1')
    else:
        print(">> (SIMULACIÓN) ¡Click! Pestillo de cerradura escondido por 3 segundos.")
        
    # --- PASO 2: PAUSA DE SEGURIDAD (TUS REGLAS DE UX) ---
    print("[SYS] Ventana de depósito activa. Esperando que el usuario deje el equipo y cierre la puerta...")
    for i in range(15, 0, -1):
        print(f"... Esperando cierre mecánico ({i}s) ...")
        time.sleep(1)
        
    # --- PASO 3: AUDITORÍA DE IA ADENTRO DEL BUZÓN ---
    print("[IA] Activando cámara interna para verificar el interior...")
    cap = cv2.VideoCapture(0)
    
    tiempo_inicio = time.time()
    equipo_validado = False
    
    while time.time() - tiempo_inicio < 12: # 12 segundos para auditar
        exito, frame = cap.read()
        if not exito: break
        
        resultados = model(frame, stream=True, verbose=False)
        
        for r in resultados:
            frame_anotado = r.plot()
            for caja in r.boxes:
                confianza = float(caja.conf[0])
                
                if confianza > 0.70:
                    print(f"[IA-ÉXITO] ¡Objeto identificado como Celular! (Confianza: {confianza*100:.1f}%)")
                    
                    # --- PASO 4: CONEXIÓN INTERNÉ / ASIGNAR PUNTOS ---
                    exito_nube = confirmar_deposito_en_nube(codigo_a_procesar)
                    if exito_nube:
                        equipo_validado = True
                    break
            
            cv2.imshow("Auditoria en Vivo - Edge", frame_anotado)
            
        if equipo_validado:
            time.sleep(1)
            break
            
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    
    if not equipo_validado:
        print(f"\n[ALERTA FRAUDE] Proceso cerrado. No se detectó equipo para el código {codigo_a_procesar}.")
    else:
        print("\n[SYS] Ciclo terminado con éxito. Puntos abonados en la Wallet virtual.")

if __name__ == "__main__":
    iniciar_sistema_edge()