import json
import traceback
import time
import os
import signal
import sys
import logging
from datetime import datetime
from threading import Timer
from db import Database
from bounces import fetch_bounces
from flask import Flask, jsonify
from threading import Thread

# Configuración de entorno y paths
ACCOUNT_SETTINGS = "/data/account_settings.json"

# Configuración del sistema de logging estructurado
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_message = {
            "timestamp": self.formatTime(record),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
            "line_number": record.lineno
        }
        if record.exc_info: # Verifica si hay información de excepción
            exc_type, exc_value, exc_traceback = record.exc_info
            log_message["traceback"] = traceback.format_exception(exc_type, exc_value, exc_traceback)

        return json.dumps(log_message)

# Configurar el handler y formatter para logs
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])

# Crear logger para este módulo
logger = logging.getLogger(__name__)

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
# Cada cuánto se buscan rebotes en las casillas de envío (0 = no buscar) y cuántos días hacia atrás
BOUNCE_CHECK_INTERVAL = int(os.getenv("BOUNCE_CHECK_INTERVAL", "600"))
BOUNCE_LOOKBACK_DAYS = int(os.getenv("BOUNCE_LOOKBACK_DAYS", "3"))


def load_settings(file):
    """Carga la configuración de cuentas de correo desde un archivo JSON"""
    try:
        with open(file) as settings:
            accounts = json.load(settings)
        logger.info(f"Configuración cargada: {len(accounts)} cuentas encontradas")
        return accounts
    except FileNotFoundError:
        logger.error(f"No se encontró el archivo de configuración: {file}")
        return []
    except json.JSONDecodeError:
        logger.error(f"El archivo de configuración no es un JSON válido: {file}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al cargar configuración: {str(e)}", exc_info=True)
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
            logger.warning(f"Health check: El servicio lleva {time_since_last} segundos sin una ejecución exitosa")
        
        return jsonify({
            "status": status,
            "last_success": LAST_SUCCESSFUL_RUN.isoformat(),
            "seconds_since_success": time_since_last
        }), 200
    except Exception as e:
        logger.error(f"Error en health check: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500

def watchdog_check():
    """Comprueba si el programa está funcionando correctamente y lo reinicia si es necesario"""
    global LAST_SUCCESSFUL_RUN
    time_since_last = (datetime.now() - LAST_SUCCESSFUL_RUN).total_seconds()
    
    if time_since_last > WATCHDOG_TIMEOUT:
        logger.critical(f"¡WATCHDOG ACTIVADO! Han pasado {time_since_last} segundos sin actividad exitosa. Reiniciando...")
        os._exit(1)  # Fuerza reinicio en Railway
    
    # Programa la próxima verificación
    timer = Timer(60, watchdog_check)  # Comprobar cada minuto
    timer.daemon = True
    timer.start()

def signal_handler(sig, frame):
    """Maneja señales de terminación para una limpieza adecuada"""
    logger.info("Señal de terminación recibida. Limpiando recursos...")
    sys.exit(0)

def send_message(accounts, email, message):
    """Intenta enviar un mensaje usando las cuentas disponibles.
    Devuelve (Message-ID, None) si salió, o (None, motivo)."""
    if not email or '@' not in email:
        logger.warning(f"Dirección de correo inválida: {email}")
        return None, "Dirección de correo inválida"

    logger.info(f"Enviando mensaje a {email}...")

    if not accounts:
        logger.error("No hay cuentas de correo configuradas para enviar")
        return None, "No hay cuentas de correo configuradas"

    last_error = None
    for account in accounts:
        try:
            start_time = time.time()
            message_id = account.send_to(email, message)
            execution_time = time.time() - start_time

            if message_id:
                logger.info(f"Mensaje enviado correctamente a {email} en {execution_time:.2f}s")
                return message_id, None
        except Exception as e:
            logger.error(f"Error enviando a {email} usando {account}: {str(e)}", exc_info=True)
            last_error = f"{account.sender_email}: {e}"

    logger.warning(f"No se pudo enviar el mensaje a {email} usando ninguna cuenta")
    return None, last_error or "No se pudo enviar desde ninguna cuenta"


def record_delivery(db, message_id, code_cli, alarm_at, email, estado,
                    detalle=None, referencia=None, enviado=False):
    """Guarda en mensaje_entrega el resultado para una casilla. Si la base falla queda
    solo en el log: el email ya se mandó (o no) y el ciclo no se tiene que cortar por esto."""
    try:
        db.set_delivery(message_id, code_cli, alarm_at, email, estado, detalle, referencia, enviado)
    except Exception as e:
        logger.warning(f"No se pudo guardar en mensaje_entrega el email {message_id} a {email or '(sin destino)'}: {e}")


def process_message(db, accounts, message):
    """Envía un mensaje a cada email del cliente y guarda el resultado de cada uno.
    Devuelve (emails a los que salió, emails del cliente). Lo marca como enviado si
    salió a alguno, o si el cliente no tiene emails."""
    message_id, content, code_cli, alarm_at = message

    logger.info(f"Procesando mensaje ID: {message_id} para cliente {code_cli}")

    # Obtener emails del cliente
    emails = db.get_email_from_code(code_cli) or ""
    emails = [email.strip() for email in emails.split(";") if email.strip()]

    if not emails:
        logger.warning(f"No hay emails para el cliente {code_cli}, marcando como enviado")
        db.mark_as_sent(message_id)
        record_delivery(db, message_id, code_cli, alarm_at, "", "sin_destino",
                        "El cliente no tiene emails cargados")
        return 0, 0
    logger.info(f"Encontrados {len(emails)} emails para el cliente {code_cli}")

    emails_sent = 0
    for email in emails:
        reference, error = send_message(accounts, email, content)
        if reference:
            emails_sent += 1
            record_delivery(db, message_id, code_cli, alarm_at, email, "enviado",
                            referencia=reference, enviado=True)
        else:
            record_delivery(db, message_id, code_cli, alarm_at, email, "error", error)

    # Marcar como enviado si al menos un email recibió el mensaje
    if emails_sent:
        db.mark_as_sent(message_id)
    return emails_sent, len(emails)


def check_bounces(db, accounts):
    """Marca como rebotados los emails cuyo rebote llegó a alguna casilla de envío."""
    for account in accounts:
        try:
            bounces = fetch_bounces(account, BOUNCE_LOOKBACK_DAYS)
        except Exception as e:
            logger.warning(f"No se pudieron leer los rebotes de {account.sender_email} ({account.imap_server}): {e}")
            continue
        for reference, reason in bounces:
            try:
                if db.mark_bounced(reference, reason):
                    logger.info(f"Rebote: el email {reference} no llegó ({reason})")
            except Exception as e:
                logger.warning(f"No se pudo marcar el rebote de {reference}: {e}")


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
    logger.info("Servidor Flask iniciado para health checks en puerto 8080")
    
    # Inicia el watchdog
    watchdog_thread = Thread(target=watchdog_check)
    watchdog_thread.daemon = True
    watchdog_thread.start()
    logger.info("Watchdog iniciado")

    # Cargar la configuración de cuentas
    logger.info("Cargando configuración de cuentas de correo...")
    settings = load_settings(ACCOUNT_SETTINGS)
    
    # Solo inicializa las cuentas si hay configuración disponible
    accounts = []
    if settings:
        try:
            accounts = [
                EmailAccount(sett['email'], sett['password'], sett['server'], sett['port'], sett.get('imap_server'))
                for sett in settings
            ]
            logger.info(f"Se inicializaron {len(accounts)} cuentas de correo correctamente")
        except Exception as e:
            logger.error(f"Error al inicializar cuentas de correo: {str(e)}", exc_info=True)
    else:
        logger.warning("No se encontraron cuentas de correo configuradas")

    # Variables para el bucle principal
    consecutive_errors = 0
    last_bounce_check = None

    logger.info(f"Iniciando bucle principal con intervalo de {SLEEP} segundos")
    while True:
        try:
            # Las declaraciones global deben estar al nivel de la función, no dentro del bucle
            start_time = time.time()
            logger.info("Ejecutando rutina de verificación de mensajes...")
            
            # Crear una nueva conexión en cada iteración
            db = Database(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_DATABASE)
            db.open()

            # Limitar la cantidad de mensajes a procesar por ciclo
            messages = db.get_unsent()  # Asumimos que get_unsent acepta un parámetro limit
            
            if not messages:
                logger.info("No hay mensajes nuevos para enviar")
            else:
                logger.info(f"Procesando {len(messages)} mensajes...")
                
                messages_processed = 0
                messages_sent = 0
                messages_failed = 0

                for message in messages:
                    try:
                        message_id = message[0]
                        emails_sent, emails_total = process_message(db, accounts, message)

                        if emails_total == 0:
                            pass  # sin emails: queda procesado, no cuenta como enviado ni fallido
                        elif emails_sent:
                            messages_sent += 1
                            logger.info(f"Mensaje {message_id} enviado a {emails_sent} de {emails_total} destinatarios")
                        else:
                            messages_failed += 1
                            logger.warning(f"No se pudo enviar el mensaje {message_id} a ningún destinatario")

                        messages_processed += 1
                        
                    except Exception as msg_error:
                        logger.error(f"Error procesando mensaje {message[0]}: {str(msg_error)}", exc_info=True)
                        messages_failed += 1
                
                # Resumen de la ejecución
                logger.info(f"Resumen: {messages_processed} procesados, {messages_sent} enviados, {messages_failed} fallidos")

            # Rebotes que llegaron a las casillas de envío
            if BOUNCE_CHECK_INTERVAL and (last_bounce_check is None
                                          or time.monotonic() - last_bounce_check >= BOUNCE_CHECK_INTERVAL):
                check_bounces(db, accounts)
                last_bounce_check = time.monotonic()

            # Cerrar la conexión después de usarla
            db.close()
            
            # Actualiza el timestamp de última ejecución exitosa
            LAST_SUCCESSFUL_RUN = datetime.now()
            consecutive_errors = 0  # Reiniciar contador de errores
            
            # Calcula tiempo de ejecución y ajusta el tiempo de espera
            execution_time = time.time() - start_time
            logger.info(f"Rutina completada en {execution_time:.2f} segundos")
            
            # Asegura un intervalo constante ajustando el tiempo de espera
            sleep_time = max(0.1, SLEEP - execution_time)  # Al menos 0.1 segundos
            time.sleep(sleep_time)

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Error en el ciclo principal ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {str(e)}", exc_info=True)
            
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.critical(f"Demasiados errores consecutivos ({consecutive_errors}). Reiniciando el servicio...")
                os._exit(1)  # Fuerza reinicio
                
            # Esperar antes de reintentar tras un error
            time.sleep(SLEEP)
