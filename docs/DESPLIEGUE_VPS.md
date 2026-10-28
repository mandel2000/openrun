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

El contenedor corre sin root (uid 1000), con `TZ=Europe/Madrid` y healthcheck en `/api/health`.

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `OPENRUN_PASSWORD` | Sí | Contraseña de acceso. **Mínimo 12 caracteres**: si no, el servidor no arranca |
| `OPENRUN_API_TOKEN` | Para el MCP | Token para que el coach de Claude Desktop hable con el servidor (≥ 32 caracteres) |
| `OPENRUN_PUBLIC_URL` | Recomendada | `https://run.tudominio.com` (se muestra en *Ajustes* y en la config del MCP) |
| `ANTHROPIC_API_KEY` / `OPENRUN_PROVIDER` / `GEMINI_API_KEY` / `OPENRUN_MODEL` | No | Coach IA dentro de la app |
| `OPENRUN_DATABASE_URL` | No | Base de datos externa (p. ej. `postgresql+psycopg://…`); por defecto SQLite en `/data` |

En la imagen ya vienen `OPENRUN_TRUST_LOCAL=0` (detrás de un proxy nada es «local») y `OPENRUN_TRUST_PROXY=1` (IP real y HTTPS desde las cabeceras de Traefik).

Genera secretos con:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # contraseña
python3 -c "import secrets; print(secrets.token_urlsafe(40))"   # API token
```

## Seguridad

- Toda la API pide sesión (contraseña) o el API token; solo `/api/health` y el login son públicos.
- Sesiones firmadas que caducan a los 90 días; cambiar la contraseña cierra todas.
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

**Por qué una red propia (`openrun`)**: la red `coolify` del servidor tiene la puerta de enlace IPv6 guardada como `fde4:…::1/64` (fallo de Docker 27) y la versión de Docker Compose del ayudante de Coolify la rechaza (`ParseAddr … unexpected character`), así que cualquier despliegue en esa red falla. OpenRun usa una red solo IPv4 creada a mano y conectada al proxy (`docker network create --attachable openrun && docker network connect openrun coolify-proxy`).
