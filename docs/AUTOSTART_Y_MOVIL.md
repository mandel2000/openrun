# Arranque automático y acceso desde el móvil

OpenRun es un servidor local. Para que la **rutina diaria** (sync con Garmin, análisis, ajuste de ritmos, calor, readiness y envío al reloj) se ejecute cada mañana, el servidor tiene que estar en marcha. En macOS eso se consigue registrándolo en `launchd`. Para usarlo desde el **móvil**, el servidor se abre a la red local y pide un **PIN**.

## 1. Modos de arranque

| Modo | Comando | Quién puede entrar |
|---|---|---|
| Solo este ordenador (por defecto) | `./run.sh` | `http://localhost:8000` |
| Ordenador + móvil en la misma wifi | `OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=<pin> ./run.sh` | El ordenador sin PIN; el resto de la red con PIN |

`run.sh` se niega a arrancar en modo red sin `OPENRUN_PIN`.

## 2. Arranque automático (macOS)

```bash
scripts/install-autostart.sh                              # solo este ordenador
OPENRUN_PIN=<pin> scripts/install-autostart.sh --lan      # también desde el móvil
```

Qué hace el script:

- Crea `~/Library/LaunchAgents/com.openrun.server.plist` (permisos `600`, porque contiene el PIN y las API keys) y lo carga con `launchctl`.
- `RunAtLoad`: arranca al iniciar sesión. `KeepAlive`: si el proceso se cae, launchd lo vuelve a lanzar.
- Copia al plist el `PATH` donde están `python3` y `npm` (también si vienen de nvm o Homebrew), porque launchd arranca con un `PATH` mínimo y `run.sh` puede necesitar recompilar el frontend.
- Copia al plist las variables del coach que tengas exportadas en ese momento: `ANTHROPIC_API_KEY`, `OPENRUN_PROVIDER` y `GEMINI_API_KEY`. Si las cambias, vuelve a ejecutar el script.
- Escribe el log en `~/.openrun/server.log`.

Volver a ejecutar el script es seguro: descarga la versión anterior y carga la nueva.

### Comprobar que está funcionando

```bash
launchctl list | grep openrun                 # PID y último código de salida (0 = bien)
tail -f ~/.openrun/server.log                 # log del servidor
curl -s localhost:8000/api/garmin/status      # {"connected": true, ...}
curl -s localhost:8000/api/daily/log          # última ejecución de la rutina diaria
```

En la app: *Ajustes › Automatización diaria* muestra la última rutina, el resultado de cada paso y el botón *Ejecutar ahora*.

### Reiniciar (p. ej. tras `git pull`)

```bash
launchctl kickstart -k gui/$(id -u)/com.openrun.server
```

`run.sh` instala las dependencias nuevas y recompila el frontend si hay cambios en el código.

### Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.openrun.server.plist
rm ~/Library/LaunchAgents/com.openrun.server.plist
```

### Cuándo se ejecuta la rutina diaria

- A la hora configurada en *Ajustes › Automatización diaria* (06:30 por defecto), una vez al día.
- Si a esa hora el Mac estaba dormido o apagado, se ejecuta en cuanto OpenRun vuelve a estar en marcha. El planificador comprueba cada minuto.
- Con el Mac apagado no se ejecuta.
- Cada paso (sync, análisis, ritmos, calor, readiness, reloj) se puede activar o desactivar en la misma pantalla.

## 3. Acceso desde el móvil

1. Instala en modo `--lan` (o arranca con `OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=<pin> ./run.sh`).
2. Con el móvil en la **misma wifi**, abre `http://<IP-del-Mac>:8000`. La dirección aparece en *Ajustes › OpenRun en el móvil*; también con `ipconfig getifaddr en0`.
3. Introduce el PIN. La sesión dura 180 días en ese navegador.
4. Instálala como app:
   - **iPhone:** Safari › Compartir › *Añadir a pantalla de inicio*.
   - **Android:** Chrome › menú › *Instalar app*.
5. La primera vez, macOS puede preguntar si permites conexiones entrantes a Python. **Acepta**; si no, el móvil no podrá conectar. Si lo rechazaste: *Ajustes del Sistema › Red › Firewall › Opciones*.

La IP del Mac la asigna el router y puede cambiar. Para fijarla, reserva una IP para el Mac en el router (DHCP estático).

### Fuera de casa

No abras el puerto 8000 en el router. Usa [Tailscale](https://tailscale.com) (gratis): instálalo en el Mac y en el móvil y abre `http://<IP-Tailscale-del-Mac>:8000`. El PIN se sigue pidiendo.

## 4. Cómo funciona el PIN (seguridad)

- Las peticiones desde el propio ordenador (`127.0.0.1` / `::1`) no piden PIN. Cualquier otro equipo necesita la cookie de sesión, que solo se obtiene enviando el PIN correcto a `POST /api/auth`.
- Sin PIN configurado, el acceso desde otros equipos está **bloqueado** (401), aunque el servidor escuche en la red.
- La cookie es `HttpOnly` y `SameSite=Lax`, y su valor deriva del PIN. Si cambias el PIN, las sesiones de los móviles dejan de valer y hay que volver a introducirlo.
- **Contra fuerza bruta:** 1 s de espera por intento fallido y bloqueo de 10 minutos tras 10 fallos desde la misma IP.
- La app y los iconos se sirven sin PIN, para poder mostrar la pantalla de acceso. Todos los datos (`/api/*`) piden PIN.
- La conexión en la red local va **sin cifrar** (HTTP), así que alguien en tu misma wifi podría verla. Úsalo solo en redes de confianza (casa o Tailscale), nunca en wifis públicas.
- **Elige un PIN que no sea obvio** (`1234`, `0000`, fechas…). Cualquiera conectado a tu wifi puede intentarlo; con 10 intentos cada 10 minutos, un PIN de 4 cifras aguanta poco frente a alguien persistente. Mejor 6 o más caracteres.

### Cambiar el PIN

```bash
OPENRUN_PIN=<nuevo-pin> scripts/install-autostart.sh --lan
```

### Volver a «solo este ordenador»

```bash
scripts/install-autostart.sh
```

## 5. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| El móvil no carga la página | Firewall de macOS, otra wifi, IP cambiada | Acepta la conexión en el firewall; revisa la IP en *Ajustes › OpenRun en el móvil* |
| «Acceso remoto desactivado» | Servidor arrancado en modo red sin PIN | Reinstala con `OPENRUN_PIN=<pin> … --lan` |
| `launchctl list` muestra un código de salida distinto de 0 | Fallo al arrancar | Mira `~/.openrun/server.log` |
| `npm: command not found` en el log | Node instalado después de instalar el arranque | Vuelve a ejecutar `install-autostart.sh` |
| La rutina no se ejecuta | Mac apagado, `auto_sync` desactivado o Garmin desconectado | *Ajustes › Automatización diaria*; reconecta Garmin si hace falta |
| Permiso denegado al leer el proyecto | El proyecto está en Escritorio/Documentos (protegidos por macOS) | Muévelo fuera (p. ej. `~/OpenRun`) o da acceso a `/bin/bash` en *Privacidad › Acceso total al disco* |
