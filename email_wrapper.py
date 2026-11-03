import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid



class EmailAccount(object):
	def __init__(self, sender_email, passwd, server, port, imap_server=None):
		self.sender_email = sender_email
		self.passwd = passwd
		self.server = server
		self.port = port
		# Para leer los rebotes. Si no se configura se deduce del SMTP (smtp.gmail.com -> imap.gmail.com).
		self.imap_server = imap_server or str(server).replace("smtp.", "imap.", 1)

	def send_to(self, email, content):
		"""
        Envía un correo electrónico al destinatario especificado con el contenido proporcionado.
        Devuelve el Message-ID del correo (sin <>): los rebotes lo citan, y así se sabe a qué envío corresponden.
        """
		try:
			# Configurar el mensaje MIME
			message = MIMEMultipart()
			message['From'] = self.sender_email
			message['To'] = email
			message['Subject'] = 'Sistema de Mensajes'  # Línea de asunto
			message_id = make_msgid(domain=self.sender_email.split('@')[-1])
			message['Message-ID'] = message_id
			message.attach(MIMEText(content, 'plain'))

			# Establecer conexión con el servidor SMTP
			with smtplib.SMTP(self.server, self.port) as session:
				session.ehlo()  # Identificación con el servidor SMTP
				session.starttls()  # Iniciar la conexión segura
				session.login(self.sender_email, self.passwd)  # Autenticarse
				# Si el servidor rechaza al destinatario lanza SMTPRecipientsRefused
				session.sendmail(self.sender_email, email, message.as_string())  # Enviar correo

			return message_id.strip('<>')
		except smtplib.SMTPAuthenticationError:
			print("Error de autenticación: verifica tu correo o contraseña de aplicación.")
			raise
		except smtplib.SMTPConnectError:
			print("Error al conectarse al servidor SMTP. Revisa tu configuración.")
			raise
		except Exception as e:
			print(f"Error inesperado: {e}")
			raise
