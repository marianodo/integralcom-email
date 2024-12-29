import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json



class EmailAccount(object):
	def __init__(self, sender_email, passwd, server, port):
		self.sender_email = sender_email
		self.passwd = passwd
		self.server = server
		self.port = port

	def send_to(self, email, content):
		"""
        Envía un correo electrónico al destinatario especificado con el contenido proporcionado.
        """
		try:
			# Configurar el mensaje MIME
			message = MIMEMultipart()
			message['From'] = self.sender_email
			message['To'] = email
			message['Subject'] = 'Sistema de Mensajes'  # Línea de asunto
			message.attach(MIMEText(content, 'plain'))

			# Establecer conexión con el servidor SMTP
			with smtplib.SMTP(self.server, self.port) as session:
				session.ehlo()  # Identificación con el servidor SMTP
				session.starttls()  # Iniciar la conexión segura
				session.login(self.sender_email, self.passwd)  # Autenticarse
				session.sendmail(self.sender_email, email, message.as_string())  # Enviar correo

			return True
		except smtplib.SMTPAuthenticationError:
			print("Error de autenticación: verifica tu correo o contraseña de aplicación.")
			raise
		except smtplib.SMTPConnectError:
			print("Error al conectarse al servidor SMTP. Revisa tu configuración.")
			raise
		except Exception as e:
			print(f"Error inesperado: {e}")
			raise