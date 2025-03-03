import json
import traceback
from time import sleep
import os
from db import Database
# Configuración de entorno y paths
ACCOUNT_SETTINGS = "/data/account_settings.json"

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))  # Por seguridad lo casteo a int
DB_DATABASE = os.getenv("DB_DATABASE")


def load_settings(file):
    with open(file) as settings:
        accounts = json.load(settings)
    return accounts


def send_message(accounts, email, message):
    print(f"Enviando mensaje a {email}...")
    for account in accounts:
        try:
            if account.send_to(email, message):
                print(f"Mensaje enviado correctamente a {email}")
                return True
        except Exception as e:
            traceback.print_exc()
            print(f"Error enviando a {email}: {e}")
    return False


# Main loop
if __name__ == '__main__':
    from email_wrapper import EmailAccount  # Asumo que tenés el wrapper ya hecho

    settings = load_settings(ACCOUNT_SETTINGS)
    accounts = [
        EmailAccount(sett['email'], sett['password'], sett['server'], sett['port'])
        for sett in settings
    ]

    while True:
        try:
            db = Database(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_DATABASE)
            db.open()

            messages = db.get_unsent()
            if not messages:
                print("No hay mensajes nuevos.")

            for message in messages:
                message_id = message[0]
                content = message[1]
                code_cli = message[3]

                print(f"Procesando mensaje ID: {message_id}")

                emails = db.get_email_from_code(code_cli)

                if emails:
                    emails = emails.split(";")
                    emails = [email.strip() for email in emails]
                else:
                    print(f"No hay emails para el cliente {code_cli}, marcando como enviado.")
                    db.mark_as_sent(message_id)
                    continue

                success = False
                for email in emails:
                    success |= send_message(accounts, email, content)

                if success:
                    db.mark_as_sent(message_id)

            db.close()

        except Exception as e:
            print(f"Error en el ciclo principal: {e}")
            traceback.print_exc()

        sleep(60)  # Pausa de 1 minuto entre iteraciones
