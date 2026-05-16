import qrcode

def crear_qr():
    print("=== Generador de QR para Buzón Entel ===")
    print("Revisa la consola donde está corriendo app.py")
    
    # Pedir la IP al usuario por consola
    url_flask = input("\nIngresa la URL exacta (ej. http://192.168.1.15:5000) o presiona Enter para probar: ")
    
    if not url_flask:
        url_flask = "http://192.168.1.100:5000" # URL de prueba por defecto
        
    print(f"\n[INFO] Generando código QR para: {url_flask}")

    # Configuración de grado industrial para el QR
    qr = qrcode.QRCode(
        version=1,
        # Nivel 'H' (High): Permite que el QR se lea incluso si se raya o ensucia hasta un 30%
        error_correction=qrcode.constants.ERROR_CORRECT_H, 
        box_size=15, # Tamaño de los píxeles (más grande = mejor resolución al imprimir)
        border=2,    # Borde blanco
    )

    qr.add_data(url_flask)
    qr.make(fit=True)

    # Crear la imagen visual
    imagen = qr.make_image(fill_color="#002eff", back_color="white") # Azul Entel
    
    nombre_archivo = "qr_maqueta.png"
    imagen.save(nombre_archivo)

    print(f"[ÉXITO] ¡Imagen creada! Revisa tu carpeta, se guardó como '{nombre_archivo}'")
    print("[INFO] Imprímelo y pégalo en la puerta de tu maqueta.")

if __name__ == "__main__":
    crear_qr()