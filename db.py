import mysql.connector as MySQLdb
# Queries
GET_UNSENT = "SELECT * FROM mensaje_a_python_email WHERE men_status = 0"
MARK_AS_SENT = "UPDATE mensaje_a_python_email SET men_status = 1 WHERE id = {0}"
GET_CLIENT_EMAIL = "SELECT cli_mail FROM cli_clientes WHERE cli_codigo = {0}"

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

