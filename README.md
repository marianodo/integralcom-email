# integralcom-email

Envía por email los mensajes de `mensaje_a_python_email` a las casillas del cliente
(`cli_clientes.cli_mail`, separadas por `;`).

El resultado de cada casilla queda en `mensaje_entrega` (el `CREATE TABLE` está en
`python-twilio/sql/mensaje_entrega.sql`) y lo muestra el dashboard (integralcom-metrics):

- `enviado`: el servidor SMTP aceptó el email.
- `error`: no se pudo enviar desde ninguna cuenta (el detalle tiene el motivo).
- `rebotado`: volvió un rebote a la casilla de envío.

## Rebotes

Cada email sale con su propio Message-ID. Cada `BOUNCE_CHECK_INTERVAL` segundos se leen
por IMAP, en modo solo lectura, los rebotes de los últimos `BOUNCE_LOOKBACK_DAYS` días
(de mailer-daemon o postmaster) en el INBOX de cada cuenta de envío, y se marcan los
emails que citan.

Variables de entorno:

- `BOUNCE_CHECK_INTERVAL`: segundos entre búsquedas (600 por defecto; 0 las desactiva).
- `BOUNCE_LOOKBACK_DAYS`: días hacia atrás (3 por defecto).

El servidor IMAP se deduce del SMTP (`smtp.gmail.com` -> `imap.gmail.com`). Si es otro,
agregarlo a la cuenta en `account_settings.json`:

```json
[{"email": "...", "password": "...", "server": "smtp.ejemplo.com", "port": 587, "imap_server": "mail.ejemplo.com"}]
```
