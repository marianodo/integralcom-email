import mysql.connector as MySQLdb
from time import sleep

# Queries
# Columnas por nombre (no SELECT *) para que agregar columnas a la tabla no rompa el script.
GET_UNSENT = "SELECT id, mensaje, cliente, datetime FROM mensaje_a_python_email WHERE men_status = 0"
MARK_AS_SENT = "UPDATE mensaje_a_python_email SET men_status = 1 WHERE id = {0}"
GET_CLIENT_EMAIL = "SELECT cli_mail FROM cli_clientes WHERE cli_codigo = {0}"

# Resultado por destinatario (la tabla está en python-twilio/sql/mensaje_entrega.sql).
# Si ya hay fila para ese mensaje y casilla se actualiza el estado; enviado_en guarda el primer envío.
UPSERT_DELIVERY = """
INSERT INTO mensaje_entrega
    (canal, mensaje_id, cliente, alarma_en, destino, estado, detalle, referencia, enviado_en, actualizado_en)
VALUES ('email', %s, %s, %s, %s, %s, %s, %s, IF(%s, NOW(), NULL), NOW())
ON DUPLICATE KEY UPDATE
    estado = VALUES(estado),
    detalle = VALUES(detalle),
    referencia = COALESCE(VALUES(referencia), referencia),
    enviado_en = COALESCE(enviado_en, VALUES(enviado_en)),
    actualizado_en = NOW()
"""
# Cada email sale con su propio Message-ID, así que la referencia identifica a la casilla.
MARK_BOUNCED = """
UPDATE mensaje_entrega SET estado = 'rebotado', detalle = %s, actualizado_en = NOW()
WHERE canal = 'email' AND referencia = %s AND estado <> 'rebotado'
"""


def _latin1(text, size):
    """mensaje_entrega es latin1: un carácter fuera de ese juego haría fallar el INSERT."""
    if text is None:
        return None
    return str(text)[:size].encode("latin-1", "replace").decode("latin-1")


# Clase Database con manejo de conexión y reintento
class Database:
    def __init__(self, user, password, host, port, database):
        self.__user = user
        self.__password = password
        self.__host = host
        self.__port = port
        self.__database = database
        self.__connection = None
        self.__session = None

    def open(self, retries=3, delay=5):
        for attempt in range(retries):
            try:
                self.__connection = MySQLdb.connect(
                    host=self.__host,
                    user=self.__user,
                    passwd=self.__password,
                    db=self.__database,
                    port=self.__port
                )
                self.__session = self.__connection.cursor()
                return
            except MySQLdb.Error as e:
                print(f"Intento {attempt+1} - Error conectando a MySQL: {e}")
                if attempt < retries - 1:
                    sleep(delay)
                else:
                    raise

    def close(self):
        if self.__session:
            self.__session.close()
        if self.__connection:
            self.__connection.close()

    def mark_as_sent(self, message_id):
        self.__session.execute(MARK_AS_SENT.format(message_id))
        self.__connection.commit()

    def get_email_from_code(self, code):
        self.__session.execute(GET_CLIENT_EMAIL.format(code))
        result = self.__session.fetchone()
        return result[0] if result else None

    def get_unsent(self):
        self.__session.execute(GET_UNSENT)
        return self.__session.fetchall()

    def set_delivery(self, mensaje_id, cliente, alarma_en, destino, estado,
                     detalle=None, referencia=None, enviado=False):
        """Guarda en mensaje_entrega el resultado del envío a una casilla."""
        self.__session.execute(UPSERT_DELIVERY, (
            int(mensaje_id), int(cliente), alarma_en, _latin1(destino, 150), estado,
            _latin1(detalle, 255), _latin1(referencia, 255), 1 if enviado else 0,
        ))
        self.__connection.commit()

    def mark_bounced(self, referencia, detalle):
        """Marca como rebotado el email con ese Message-ID. Devuelve True si había uno sin marcar."""
        self.__session.execute(MARK_BOUNCED, (_latin1(detalle, 255), _latin1(referencia, 255)))
        self.__connection.commit()
        return self.__session.rowcount > 0
