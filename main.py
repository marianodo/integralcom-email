import json
import traceback
import time
import os
import signal
import sys
from datetime import datetime
from threading import Timer
from db import Database
from flask import Flask, jsonify
from threading import Thread

# Configuración de entorno y paths
ACCOUNT_SETTINGS = "/data/account_settings.json"

# Configuración del servidor Flask para health checks
app = Flask(__name__)

# Variables para monitoreo y watchdog
LAST_SUCCESSFUL_RUN = datetime.now()
WATCHDOG_TIMEOUT = 300  # 5 minutos sin actividad exitosa
MAX_CONSECUTIVE_ERRORS = 5

# Variables de entorno
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))  # Por seguridad lo casteo a int
DB_DATABASE = os.getenv("DB_DATABASE")
SLEEP = int(os.getenv("SLEEP", "10"))  # Cambiado a 10 segundos por defecto


def load_settings(file):
    """Carga la configuración de cuentas de correo desde un archivo JSON"""
    try:
        with open(file) as settings:
            accounts = json.load(settings)
        print(f"Configuración cargada: {len(accounts)} cuentas encontradas")
        return accounts
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo de configuración: {file}")
        return []
    except json.JSONDecodeError:
        print(f"Error: El archivo de configuración no es un JSON válido: {file}")
        return []
    except Exception as e:
        print(f"Error inesperado al cargar configuración: {str(e)}")
        return []


@app.route("/health", methods=['GET'])
def health_check():
    """Endpoint para verificar el estado del servicio"""
    try:
        global LAST_SUCCESSFUL_RUN
        # Comprueba el tiempo desde la última ejecución exitosa
        time_since_last = (datetime.now() - LAST_SUCCESSFUL_RUN).total_seconds()
        
        status = "ok"
        if time_since_last > WATCHDOG_TIMEOUT:
            status = "warning"
            print(f"Health check: El servicio lleva {time_since_last} segundos sin una ejecución exitosa")
        
        return jsonify({
            "status": status,
            "last_success": LAST_SUCCESSFUL_RUN.isoformat(),
            "seconds_since_success": time_since_last
        }), 200
    except Exception as e:
        print(f"Error en health check: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def watchdog_check():
    """Comprueba si el programa está funcionando correctamente y lo reinicia si es necesario"""
    global LAST_SUCCESSFUL_RUN
    time_since_last = (datetime.now() - LAST_SUCCESSFUL_RUN).total_seconds()
    
    if time_since_last > WATCHDOG_TIMEOUT:
        print(f"¡WATCHDOG ACTIVADO! Han pasado {time_since_last} segundos sin actividad exitosa. Reiniciando...")
        os._exit(1)  # Fuerza reinicio en Railway
    
    # Programa la próxima verificación
    timer = Timer(60, watchdog_check)  # Comprobar cada minuto
    timer.daemon = True
    timer.start()

def signal_handler(sig, frame):
    """Maneja señales de terminación para una limpieza adecuada"""
    print("Señal de terminación recibida. Limpiando recursos...")
    sys.exit(0)

def send_message(accounts, email, message):
    """Intenta enviar un mensaje usando las cuentas disponibles"""
    if not email or '@' not in email:
        print(f"Dirección de correo inválida: {email}")
        return False
        
    print(f"Enviando mensaje a {email}...")
    
    if not accounts:
        print("No hay cuentas de correo configuradas para enviar")
        return False
        
    for account in accounts:
        try:
            start_time = time.time()
            result = account.send_to(email, message)
            execution_time = time.time() - start_time
            
            if result:
                print(f"✓ Mensaje enviado correctamente a {email} en {execution_time:.2f}s")
                return True
        except Exception as e:
            print(f"✗ Error enviando a {email} usando {account}: {str(e)}")
            traceback.print_exc()
    
    print(f"× No se pudo enviar el mensaje a {email} usando ninguna cuenta")
    return False


# Main loop
if __name__ == '__main__':
    from email_wrapper import EmailAccount  # Asumo que tenés el wrapper ya hecho
    
    # Configura manejadores de señales
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Inicia el servidor Flask en un hilo separado
    flask_thread = Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8080, 'debug': False, 'use_reloader': False})
    flask_thread.daemon = True
    flask_thread.start()
    print("Servidor Flask iniciado para health checks en puerto 8080")
    
    # Inicia el watchdog
    watchdog_thread = Thread(target=watchdog_check)
    watchdog_thread.daemon = True
    watchdog_thread.start()
    print("Watchdog iniciado")

    # Cargar la configuración de cuentas
    print("Cargando configuración de cuentas de correo...")
    settings = load_settings(ACCOUNT_SETTINGS)
    
    # Solo inicializa las cuentas si hay configuración disponible
    accounts = []
    if settings:
        try:
            accounts = [
                EmailAccount(sett['email'], sett['password'], sett['server'], sett['port'])
                for sett in settings
            ]
            print(f"Se inicializaron {len(accounts)} cuentas de correo correctamente")
        except Exception as e:
            print(f"Error al inicializar cuentas de correo: {str(e)}")
    else:
        print("ADVERTENCIA: No se encontraron cuentas de correo configuradas")

    # Variables para el bucle principal
    consecutive_errors = 0
    
    print(f"Iniciando bucle principal con intervalo de {SLEEP} segundos")
    while True:
        try:
            # Las declaraciones global deben estar al nivel de la función, no dentro del bucle
            start_time = time.time()
            print("Ejecutando rutina de verificación de mensajes...")
            
            # Crear una nueva conexión en cada iteración
            db = Database(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_DATABASE)
            db.open()

            # Limitar la cantidad de mensajes a procesar por ciclo
            messages = db.get_unsent(limit=50)  # Asumimos que get_unsent acepta un parámetro limit
            
            if not messages:
                print("No hay mensajes nuevos para enviar")
            else:
                print(f"Procesando {len(messages)} mensajes...")
                
                messages_processed = 0
                messages_sent = 0
                messages_failed = 0

                for message in messages:
                    try:
                        message_id = message[0]
                        content = message[1]
                        code_cli = message[3]

                        print(f"Procesando mensaje ID: {message_id} para cliente {code_cli}")

                        # Obtener emails del cliente
                        emails = db.get_email_from_code(code_cli)

                        if emails:
                            emails = emails.split(";")
                            emails = [email.strip() for email in emails if email.strip()]
                            print(f"Encontrados {len(emails)} emails para el cliente {code_cli}")
                        else:
                            print(f"No hay emails para el cliente {code_cli}, marcando como enviado")
                            db.mark_as_sent(message_id)
                            messages_processed += 1
                            continue

                        # Intentar enviar el mensaje a cada email
                        success = False
                        emails_sent = 0
                        emails_failed = 0
                        
                        for email in emails:
                            if send_message(accounts, email, content):
                                success = True
                                emails_sent += 1
                            else:
                                emails_failed += 1

                        # Marcar como enviado si al menos un email recibió el mensaje
                        if success:
                            db.mark_as_sent(message_id)
                            messages_sent += 1
                            print(f"Mensaje {message_id} enviado a {emails_sent} de {len(emails)} destinatarios")
                        else:
                            messages_failed += 1
                            print(f"No se pudo enviar el mensaje {message_id} a ningún destinatario")
                        
                        messages_processed += 1
                        
                    except Exception as msg_error:
                        print(f"Error procesando mensaje {message[0]}: {str(msg_error)}")
                        traceback.print_exc()
                        messages_failed += 1
                
                # Resumen de la ejecución
                print(f"Resumen: {messages_processed} procesados, {messages_sent} enviados, {messages_failed} fallidos")
            
            # Cerrar la conexión después de usarla
            db.close()
            
            # Actualiza el timestamp de última ejecución exitosa
            LAST_SUCCESSFUL_RUN = datetime.now()
            consecutive_errors = 0  # Reiniciar contador de errores
            
            # Calcula tiempo de ejecución y ajusta el tiempo de espera
            execution_time = time.time() - start_time
            print(f"Rutina completada en {execution_time:.2f} segundos")
            
            # Asegura un intervalo constante ajustando el tiempo de espera
            sleep_time = max(0.1, SLEEP - execution_time)  # Al menos 0.1 segundos
            time.sleep(sleep_time)

        except Exception as e:
            consecutive_errors += 1
            print(f"Error en el ciclo principal ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {str(e)}")
            traceback.print_exc()
            
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"Demasiados errores consecutivos ({consecutive_errors}). Reiniciando el servicio...")
                os._exit(1)  # Fuerza reinicio
                
            # Esperar antes de reintentar tras un error
            time.sleep(SLEEP)
