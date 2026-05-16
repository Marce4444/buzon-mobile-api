import cv2
import serial
import time
import sqlite3
import os
from dotenv import load_dotenv
from ultralytics import YOLO


load_dotenv()

# --- CONFIGURACIÓN ---
PUERTO_ARDUINO = os.getenv('PUERTO_ARDUINO', 'COM3') 
BAUD_RATE = 9600
DB_PATH = os.getenv('DB_PATH', 'buzon.db')
API_SECRET_KEY = os.getenv('API_SECRET_KEY')


def conectar_arduino():
    try:
        arduino = serial.Serial(PUERTO_ARDUINO, BAUD_RATE, timeout=1)
        time.sleep(2)
        print(f"[HW] Arduino conectado en {PUERTO_ARDUINO}")
        return arduino
    except Exception as e:
        print(f"[HW-AVISO] Arduino NO detectado. MODO SIMULACIÓN ACTIVADO.")
        return None

def verificar_deposito_pendiente():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, codigo_tiza, modelo_declarado FROM transacciones WHERE estado = 'ESPERANDO_DEPOSITO' LIMIT 1")
    resultado = cursor.fetchone()
    conn.close()
    return resultado

def actualizar_estado_bd(transaccion_id, nuevo_estado):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE transacciones SET estado = ? WHERE id = ?", (nuevo_estado, transaccion_id))
    conn.commit()
    conn.close()

def iniciar_sistema():
    print("=== INICIANDO SISTEMA CENTRAL BUZÓN ENTEL ===")
    arduino = conectar_arduino()
    
    print("[IA] Cargando modelo YOLO (best.pt)...")
    model = YOLO("best.pt")
    
    print("[SYS] Sistema en espera. Leyendo base de datos...")

    while True:
        transaccion = verificar_deposito_pendiente()
        
        if transaccion:
            t_id, t_codigo, t_modelo = transaccion
            print(f"\n[WEB] ¡Solicitud {t_codigo} recibida! (Modelo: {t_modelo})")
            
            # --- PASO 1: ABRIR LA COMPUERTA PRIMERO ---
            print(">> ENVIANDO SEÑAL DE APERTURA AL ARDUINO >>")
            if arduino:
                arduino.write(b'1')
            else:
                print(">> (SIMULACIÓN) ¡Click! Compuerta de 12V abierta.")
                
            # --- PASO 2: LA PAUSA DE 5 SEGUNDOS ---
            print("[SYS] Esperando 5 segundos para depósito y cierre de compuerta...")
            for i in range(5, 0, -1):
                print(f"... {i} ...")
                time.sleep(1)
                
            # --- PASO 3: ENCENDER CÁMARA Y AUDITAR ---
            print("[IA] Activando cámara interna para verificar equipo...")
            cap = cv2.VideoCapture(0)
            
            tiempo_inicio_auditoria = time.time()
            equipo_validado = False
            
            # Le damos a la IA una ventana de 10 segundos para encontrar el celular
            while time.time() - tiempo_inicio_auditoria < 10:
                exito, frame = cap.read()
                if not exito: break
                
                resultados = model(frame, stream=True, verbose=False)
                
                for r in resultados:
                    frame_anotado = r.plot()
                    for caja in r.boxes:
                        confianza = float(caja.conf[0])
                        
                        if confianza > 0.85:
                            print(f"[IA-ÉXITO] ¡Equipo confirmado dentro del buzón! (Confianza: {confianza*100:.1f}%)")
                            actualizar_estado_bd(t_id, 'DEPOSITADO')
                            equipo_validado = True
                            break # Sale del for de las cajas
                            
                    cv2.imshow("Auditoria Interna - Entel", frame_anotado)
                    
                if equipo_validado:
                    time.sleep(1.5) # Dejar la ventana abierta un segundo más para ver el bounding box
                    break # Sale del while de la cámara
                    
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            # --- PASO 4: MANEJO DE ERRORES/FRAUDE ---
            if not equipo_validado:
                print(f"[ALERTA] Pasaron 10s y no se detectó ningún celular. Marcando para revisión.")
                actualizar_estado_bd(t_id, 'ERROR_SIN_EQUIPO')
                
            # Apagamos la cámara hasta que llegue la siguiente persona
            cap.release()
            cv2.destroyAllWindows()
            print("\n[SYS] Cámara apagada. Volviendo a monitorear la web...")
            time.sleep(2)
            
        else:
            time.sleep(2)

if __name__ == "__main__":
    iniciar_sistema()