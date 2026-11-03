"""Lectura de rebotes por IMAP.

Cuando un email no se puede entregar, el servidor del destinatario (o el propio
Gmail) manda un rebote a la casilla que lo envió, desde "Mail Delivery
Subsystem", MAILER-DAEMON, postmaster... El rebote cita el Message-ID del email
original, y como cada envío tiene el suyo (EmailAccount.send_to), alcanza para
saber a qué destinatario corresponde.

Se leen los rebotes de los últimos días sin marcarlos como leídos. Volver a
procesar uno no cambia nada: mark_bounced solo toca filas que todavía no están
como rebotadas.
"""
import email
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.parser import HeaderParser

BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
# Sin timeout, un servidor IMAP colgado frenaría el ciclo hasta que el watchdog reinicie el servicio
IMAP_TIMEOUT = 30
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MESSAGE_ID_RE = re.compile(r"^Message-ID:\s*<([^>\s]+)>", re.IGNORECASE | re.MULTILINE)
# Avisos de que el email sigue en cola: no son rebotes, puede llegar más tarde
_DELAY_SUBJECT_RE = re.compile(r"delay|retras|demor|warning", re.IGNORECASE)


def _imap_date(day):
    # IMAP pide el mes en inglés y strftime("%b") depende del idioma del sistema
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _header(msg, name):
    value = msg.get(name)
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _original_message_id(msg):
    """Message-ID del email que rebotó, de la copia o los encabezados que adjunta el rebote.
    Nunca el del rebote mismo, que está en los encabezados de arriba."""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload and payload[0].get("Message-ID"):
                return payload[0].get("Message-ID").strip().strip("<>")
        elif ctype == "text/rfc822-headers":
            text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            value = HeaderParser().parsestr(text).get("Message-ID")
            if value:
                return value.strip().strip("<>")

    # Rebotes que pegan el original como texto en el cuerpo
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            match = _MESSAGE_ID_RE.search(text)
            if match:
                return match.group(1)
    return None


def parse_bounce(msg):
    """(Message-ID del original, motivo) si msg es un rebote definitivo, o None."""
    original = _original_message_id(msg)
    if not original:
        return None

    subject = _header(msg, "Subject")
    reports = [part for part in msg.walk() if part.get_content_type() == "message/delivery-status"]
    if reports:
        # Reporte estándar (RFC 3464): un bloque por destinatario con su Action
        failed = [
            block for part in reports for block in part.get_payload()
            if (block.get("Action") or "").strip().lower() == "failed"
        ]
        if not failed:
            return None  # "delayed", "delivered"...: no es un rebote
        reason = failed[0].get("Diagnostic-Code") or failed[0].get("Status") or subject
    else:
        if _DELAY_SUBJECT_RE.search(subject):
            return None
        reason = subject

    reason = " ".join(str(reason or "Rebote sin motivo").split())
    reason = re.sub(r"^(smtp|x-[\w-]+)\s*;\s*", "", reason, flags=re.IGNORECASE)  # "smtp; 550 ..." -> "550 ..."
    return original, reason


def fetch_bounces(account, days):
    """Rebotes de los últimos `days` días en la casilla de envío: [(Message-ID original, motivo)]."""
    since = _imap_date(datetime.now() - timedelta(days=days))
    found = []
    try:
        imap = imaplib.IMAP4_SSL(account.imap_server, timeout=IMAP_TIMEOUT)
    except TypeError:  # Python < 3.9 no acepta timeout
        imap = imaplib.IMAP4_SSL(account.imap_server)
    try:
        imap.login(account.sender_email, account.passwd)
        imap.select("INBOX", readonly=True)  # solo lectura: no marca nada como leído

        numbers = set()
        for sender in BOUNCE_SENDERS:
            status, data = imap.search(None, "SINCE", since, "FROM", f'"{sender}"')
            if status == "OK" and data and data[0]:
                numbers.update(data[0].split())

        for number in sorted(numbers, key=int):
            status, data = imap.fetch(number, "(BODY.PEEK[])")
            if status != "OK":
                continue
            for item in data:
                if isinstance(item, tuple):
                    bounce = parse_bounce(email.message_from_bytes(item[1]))
                    if bounce:
                        found.append(bounce)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return found
