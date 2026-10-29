# Despliegue en un servidor (VPS)

En un servidor OpenRun está encendido 24 h (la rutina diaria se ejecuta aunque el Mac esté apagado), con HTTPS y accesible desde cualquier sitio.

## Imagen

`Dockerfile` (un contenedor: API + web compilada) y `docker-compose.yml`. Los datos viven en el volumen `/data`:

| Ruta | Contenido |
|---|---|
| `/data/openrun.db` | Base de datos SQLite (modo WAL) |
| `/data/garmin/` | Tokens de sesión de Garmin |
| `/data/secret.key` | Clave para firmar sesiones (se genera sola) |
| `/data/backups/` | Copia diaria de la base de datos (14 días) |
| `/data/vapid.pem` | Clave de las notificaciones push (se genera sola; si se borra, cada móvil tiene que volver a activarlas) |
| `/data/garmin/users/<id>/` | Tokens de Garmin de cada usuario (el administrador usa `/data/garmin/`) |

El contenedor corre sin root (uid 1000), con `TZ=Europe/Madrid` y healthcheck en `/api/health`.

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `OPENRUN_PASSWORD` | Sí | Contraseña **inicial** de la cuenta de administrador (solo se usa al crearla; luego se cambia en *Ajustes › Tu cuenta*). **Mínimo 12 caracteres**: si no, el servidor no arranca |
| `OPENRUN_ADMIN_USER` | No | Usuario de la cuenta de administrador (por defecto `admin`). La cuenta se crea en el primer arranque y se queda con los datos que hubiera |
| `OPENRUN_OPEN_SIGNUP` | No | `1` permite registrarse sin invitación. Por defecto `0`: solo con enlace de invitación |
| `OPENRUN_VAPID_SUB` | No | Contacto para los servicios de notificaciones push (`mailto:…`). Las claves VAPID se generan solas en `/data/vapid.pem` |
| `OPENRUN_API_TOKEN` | Para el MCP | Token para que el coach de Claude Desktop hable con el servidor (≥ 32 caracteres) |
| `OPENRUN_PUBLIC_URL` | Recomendada | `https://run.tudominio.com` (se muestra en *Ajustes* y en la config del MCP) |
| `ANTHROPIC_API_KEY` / `OPENRUN_PROVIDER` / `GEMINI_API_KEY` / `NVIDIA_API_KEY` / `OPENRUN_MODEL` | No | Coach IA dentro de la app (`OPENRUN_PROVIDER=nvidia` para el plan gratuito de NVIDIA) |
| `OPENRUN_MODEL_FALLBACKS` / `OPENRUN_REASONING_EFFORT` | No | Modelos de respaldo (separados por comas) y nivel de razonamiento; con NVIDIA por defecto `openai/gpt-oss-20b` y `low` (primera palabra en ~5 s en vez de 15–70 s) |
| `OPENRUN_AI_DAILY_LIMIT` | No | Peticiones diarias al coach IA por usuario (por defecto 40; los administradores sin límite). Se cambia por usuario en *Ajustes › Usuarios* |
| `OPENRUN_DATABASE_URL` | No | Base de datos externa (p. ej. `postgresql+psycopg://…`); por defecto SQLite en `/data` |

En la imagen ya vienen `OPENRUN_TRUST_LOCAL=0` (detrás de un proxy nada es «local») y `OPENRUN_TRUST_PROXY=1` (IP real y HTTPS desde las cabeceras de Traefik).

Genera secretos con:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # contraseña
python3 -c "import secrets; print(secrets.token_urlsafe(40))"   # API token
```

## Usuarios

- Cada usuario tiene sus propios datos: plan, entrenos, actividades, salud, carreras, chat del coach, ajustes y cuenta de Garmin. Toda tabla de datos lleva `user_id` y el filtro se aplica en el ORM (`app/tenancy.py`): una consulta sin usuario en contexto falla en vez de devolver datos de otro.
- Al actualizar desde la versión de un solo usuario, el primer arranque crea el administrador (usuario 1, `OPENRUN_ADMIN_USER`) y le asigna todos los datos existentes. Antes guarda una copia completa en `/data/openrun-pre-multiuser.db`, y la migración va en una sola transacción.
- **Invitar a alguien**: *Ajustes › Usuarios › Crear invitación* → copia el enlace (`https://…/#invitacion=…`) y envíaselo. Sirve una sola vez y caduca en 14 días. Al abrirlo, la persona elige usuario y contraseña (mínimo 10 caracteres) y conecta su Garmin en *Ajustes*.
- El administrador puede borrar cuentas (con todos sus datos).
- El coach IA (y su API key) es común: cada usuario habla con él sobre sus propios datos. Con NVIDIA gratis el límite es de ~40 peticiones por minuto entre todos. Cada usuario tiene un máximo diario de peticiones (chat, resumen semanal, explicaciones de readiness): `OPENRUN_AI_DAILY_LIMIT`, editable por usuario en *Ajustes › Usuarios*.
- Un usuario nuevo ve una bienvenida guiada en *Hoy* hasta que crea su plan o la salta.
- El API token del MCP actúa como el administrador.

## Notificaciones

Push del navegador (Web Push con claves VAPID), sin apps de terceros. Cada usuario las activa en *Ajustes › Notificaciones* en cada dispositivo:

- **iPhone**: iOS 16.4 o superior y la app añadida a la pantalla de inicio (desde Safari: Compartir › *Añadir a pantalla de inicio*), abriéndola desde el icono.
- **Android / ordenador**: Chrome, Edge o Firefox, directamente.

Avisos: entreno del día tras la rutina de la mañana, análisis de cada carrera nueva (el servidor revisa Garmin cada ~2 h entre las 9 y las 22 h), resumen semanal los lunes y «Garmin desconectado». Cada tipo se puede apagar.

## Dominio propio

1. En el proveedor del dominio, crea un registro **A** `run.tudominio.com → <SERVER_IP>` (y AAAA si tienes IPv6). Espera a que resuelva (`dig +short run.tudominio.com`).
2. En Coolify, app OpenRun › *Domains*: cambia `https://openrun.<server-ip>.sslip.io` por `https://run.tudominio.com` (puedes dejar los dos separados por coma durante el cambio). Traefik pide el certificado de Let's Encrypt solo.
3. Cambia la variable `OPENRUN_PUBLIC_URL` a la nueva dirección y redespliega.
4. En el móvil, abre la nueva dirección, inicia sesión, vuelve a añadirla a la pantalla de inicio y reactiva las notificaciones (son por dominio).

## Monitorización

- `GET /api/health` responde siempre (lo usa el healthcheck del contenedor). `GET /api/health?deep=1` comprueba además la base de datos, que el planificador interno siga ejecutándose y que la última copia de seguridad no haya fallado; si algo va mal responde 503 con la lista de problemas.
- GitHub Actions (`.github/workflows/uptime.yml`) llama a `?deep=1` cada hora. Si falla 3 veces seguidas, la ejecución falla y GitHub manda un email al dueño del repositorio. Para recibirlo también en el móvil: instala la app **ntfy**, suscríbete a un tema con un nombre largo y aleatorio y guárdalo como *secret* `NTFY_TOPIC` del repositorio. La dirección se cambia con la variable `OPENRUN_URL` del repositorio.
- Si falla la copia de seguridad diaria, los administradores reciben una notificación push.
- `.github/workflows/ci.yml` pasa los tests del backend y compila el frontend en cada push.

## Seguridad

- Toda la API pide sesión (usuario y contraseña) o el API token; solo `/api/health`, el login y el registro con invitación son públicos.
- Contraseñas guardadas con scrypt. Sesiones firmadas que caducan a los 90 días; cambiar la contraseña cierra las sesiones de esa cuenta.
- Máximo 10 intentos fallidos (login o códigos de invitación) por IP real cada 10 minutos.
- Importar un GPX por URL solo descarga `https://` de direcciones públicas (nada de la red interna) y como mucho 8 MB. Las notificaciones solo se envían a los servicios push de Google, Mozilla, Apple y Microsoft.
- Máximo 10 intentos fallidos por IP real cada 10 minutos.
- Cookie `Secure` + `HttpOnly`, HSTS y cabeceras anti-clickjacking.

## Base de datos: ¿SQLite o Postgres?

SQLite en el volumen es suficiente para un solo atleta: cero mantenimiento, sin RAM extra y copia diaria automática. Postgres solo compensa con varios usuarios o varias instancias; en ese caso basta `OPENRUN_DATABASE_URL` (añadiendo el driver `psycopg[binary]`). No reutilices la base de datos de otra app.

## Migrar los datos desde el Mac

1. Para OpenRun en el Mac (`launchctl unload ~/Library/LaunchAgents/com.openrun.server.plist`) para que nada escriba mientras copias.
2. Copia `~/.openrun/openrun.db` y `~/.openrun/garmin/` al volumen `/data` del contenedor (propietario uid 1000).
3. Arranca el contenedor. Garmin sigue conectado con los tokens copiados: mejor que iniciar sesión desde la IP del servidor, que Garmin puede bloquear o pedir verificación.

**Solo una instancia**: si OpenRun sigue arrancando en el Mac, las dos harían la rutina y enviarían entrenos al reloj por duplicado. Desinstala el arranque automático del Mac tras migrar.

## Coach en Claude Desktop (MCP) contra el servidor

El MCP se ejecuta en tu ordenador (desde un clon del repo) y llama a la API del servidor:

```json
{ "mcpServers": { "openrun": {
  "command": "/Users/<tu-usuario>/OpenRun/backend/.venv/bin/python",
  "args": ["-m", "app.mcp_server"],
  "env": { "PYTHONPATH": "/Users/<tu-usuario>/OpenRun/backend",
           "OPENRUN_URL": "https://run.tudominio.com", "OPENRUN_API_TOKEN": "<token>" } } } }
```

## Coolify

Recurso nuevo → repositorio Git (este repo) → *Dockerfile* o *Docker Compose* → puerto 8000 → variables de entorno de arriba → dominio (certificado Let's Encrypt automático) → volumen persistente en `/data`.

## Despliegue actual (VPS + Coolify)

| Dato | Valor |
|---|---|
| URL | https://openrun.<server-ip>.sslip.io (dominio temporal; cambiar en Coolify cuando haya uno propio y actualizar `OPENRUN_PUBLIC_URL`) |
| Coolify | proyecto `OpenRun`, app `<APP_UUID>`, destino (red) `openrun` |
| Datos | carpeta del servidor `/data/openrun` → `/data` en el contenedor |
| Secretos | variables de Coolify; copia en el Llavero del Mac (`openrun-password`, `<keychain-item>`) |
| Acceso al repo | clave de despliegue de solo lectura (`~/.ssh/<deploy-key>`) |

Redesplegar tras un `git push`:

```bash
TOKEN=$(security find-generic-password -a "$USER" -s <keychain-item> -w)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://<SERVER_IP>:8000/api/v1/deploy -d '{"uuid":"<APP_UUID>"}'
```

Ver la contraseña de acceso: app *Acceso a Llaveros* → buscar `openrun-password`, o `security find-generic-password -s openrun-password -w`.

**Red propia (`openrun`)**: OpenRun se desplegó en una red solo IPv4 creada a mano y conectada al proxy (`docker network create --attachable openrun && docker network connect openrun coolify-proxy`) porque la red `coolify` tenía la puerta de enlace IPv6 mal guardada (`fde4:…::1/64`, fallo de Docker 27) y el Docker Compose del ayudante de Coolify la rechazaba. La red `coolify` se recreó el 2026-10-28 con subredes explícitas y ya funciona; OpenRun puede quedarse en `openrun` sin problema.
