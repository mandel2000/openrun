# 🏃 OpenRun

[![CI](https://github.com/mandel2000/openrun/actions/workflows/ci.yml/badge.svg)](https://github.com/mandel2000/openrun/actions/workflows/ci.yml)
[![Licencia: AGPL-3.0](https://img.shields.io/badge/licencia-AGPL--3.0-blue.svg)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/apoya-Ko--fi-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/manueldelgado54792)

En español e inglés (cada usuario lo elige en *Ajustes*).

**Entrenador de running open source que instalas tú.** Planes basados en evidencia, sincronización con Garmin (datos y entrenos estructurados al reloj), readiness guiada por HRV y un coach IA que trabaja con tus datos reales. Una alternativa gratuita a apps de suscripción como Runna.

[Read in English](README.md) · [Instalar en un servidor](docs/es/servidor.md) · [Arranque automático y móvil](docs/es/arranque-y-movil.md) · [La ciencia](docs/es/ciencia.md) · [Contribuir](CONTRIBUTING.md)

## Funciones

- **Planes** de 5K, 10K, media, maratón y forma general: periodización (base → desarrollo → específico → afinamiento), ritmos VDOT de Daniels, ~80/20 de intensidad, progresión ≤ 10 % con descargas, fuerza y movilidad.
- **Garmin** (probado con un Forerunner 265): descarga actividades, HRV, sueño y FC en reposo; envía entrenos estructurados con objetivos de ritmo al calendario de Garmin Connect, que se sincroniza con el reloj.
- **¿Sin Garmin?** Sube `.fit`, `.gpx` o `.tcx` de cualquier reloj o app, o tu exportación completa de Strava. Tienen mapa, gráficas y parciales y cuentan para el plan.
- **Readiness 0–100** con HRV, sueño, FC en reposo, carga (forma/ACWR) y un check-in diario de dos toques. Si llegas cansado propone suavizar el entreno de hoy; tú aceptas o mantienes el plan, y el coach explica por qué.
- **El plan se adapta**: una sesión clave perdida se propone más adelante en la semana (nunca junto a otro día duro), una carrera hecha un día tarde cuenta, y "He estado parado N días" (enfermedad, lesión, viaje) hace la vuelta progresiva y reajusta ritmos si hace falta.
- **Análisis post-entreno**: cada serie frente a su objetivo; si las sesiones salen sistemáticamente más fáciles o más duras, se recalibran los ritmos (como *Pace Insights*).
- **Ajuste por calor**: temperatura y punto de rocío previstos a tu hora de entreno.
- **Estrategia de carrera**: ritmo km a km a esfuerzo constante sobre el perfil real (GPX/TCX/KML o enlace), calor previsto ese día, geles e hidratos y entreno de carrera en el reloj.
- **Actividades**: mapa, ritmo/FC/altitud sincronizados, parciales por km y dinámica de carrera.
- **Récords y predicciones** (1K a maratón), carga de entrenamiento (TRIMP, CTL/ATL) y resumen semanal con comentario del coach.
- **Coach IA** dentro de la app (planes gratuitos de NVIDIA o Gemini, Ollama en local, o APIs de Anthropic/OpenAI/Groq/OpenRouter) o desde **Claude Desktop / Gemini CLI por MCP** con tu propia suscripción. Los ritmos los calcula siempre el servidor desde tu VDOT, nunca el modelo.
- **Varios usuarios** por invitación: cada persona con su plan, su Garmin, su coach, sus datos y su token personal para el MCP. Límite diario de IA por usuario.
- **App instalable (PWA)** con notificaciones propias: entreno del día, análisis tras cada carrera, sesiones perdidas y resumen semanal.
- Bandas de pulso Bluetooth (p. ej. Amazfit Helio Strap) para medir la HRV por la mañana desde el navegador; importación de datos de Zepp.

## Empezar

### Con Docker (recomendado)

```bash
git clone https://github.com/mandel2000/openrun.git && cd openrun
cp .env.example .env          # pon OPENRUN_PASSWORD (12+ caracteres) y, si quieres, la clave de un proveedor de IA
docker compose up -d
```

Abre http://localhost:8000 y entra como `admin` con esa contraseña. Los datos quedan en el volumen `openrun-data`.

### En tu ordenador, sin Docker

Requisitos: Python ≥ 3.12 y Node ≥ 20.

```bash
./run.sh
```

Abre http://localhost:8000 (desde el mismo ordenador no pide contraseña). Los datos se guardan en `~/.openrun/`. Para que arranque solo y usarlo desde el móvil: [docs/es/arranque-y-movil.md](docs/es/arranque-y-movil.md).

### En un servidor

Con HTTPS, varios usuarios, notificaciones y dominio propio: [docs/es/servidor.md](docs/es/servidor.md).

## Primeros pasos

1. **Entra.** Los usuarios nuevos ven una bienvenida: perfil, de dónde salen sus datos (Garmin o archivos) y objetivo.
2. **Ajustes › Garmin**: inicia sesión (admite MFA) y sincroniza el histórico. O sube archivos en **Progreso › Actividades**.
3. **Plan**: objetivo, fecha, días por semana y una marca reciente → *Generar plan*.
4. **Hoy**: el entreno del día, el check-in de readiness y los ajustes del plan. Envía la semana al reloj.
5. **Ajustes › Notificaciones** en el móvil (en iPhone, antes añade la app a la pantalla de inicio).

## Opciones de coach IA

| Opción | Cómo | Coste |
|---|---|---|
| **Tu suscripción de Claude** (Free/Pro/Max) | OpenRun como servidor MCP en Claude Desktop ([docs/mcp.md](docs/mcp.md)) | Sin coste extra |
| **Gemini CLI** | El mismo bloque MCP en `~/.gemini/settings.json` | Gratis con cuenta Google |
| **NVIDIA** (chat en la app) | `OPENRUN_PROVIDER=nvidia`, `NVIDIA_API_KEY=nvapi-…` | Cuenta NVIDIA Developer gratuita, ~40 peticiones/min, condiciones de prueba |
| **Gemini API** (chat en la app) | `OPENRUN_PROVIDER=gemini`, `GEMINI_API_KEY=…` | Plan gratuito con límites; Google puede usar los datos |
| **Ollama** (local) | `ollama pull qwen3:8b`, `OPENRUN_PROVIDER=ollama` | Gratis y privado; razona peor |
| **APIs de pago** | `ANTHROPIC_API_KEY`, o `OPENRUN_PROVIDER=openai\|groq\|openrouter` con su clave | Pago por uso |

Las suscripciones de consumo (Claude, ChatGPT, Gemini) no incluyen acceso a la API para apps de terceros; MCP es la forma soportada de usarlas con tus datos. Todas las variables: [docs/configuration.md](docs/configuration.md) (en inglés).

## Documentación

| | |
|---|---|
| [Servidor](docs/es/servidor.md) | Docker, servidor con HTTPS, usuarios, notificaciones, dominio, monitorización, seguridad |
| [Arranque automático y móvil](docs/es/arranque-y-movil.md) | OpenRun en tu ordenador, siempre encendido y accesible desde el móvil |
| [La ciencia](docs/es/ciencia.md) | En qué se basan los planes |
| [English docs](docs/) | Self-hosting, configuración, MCP, integraciones, arquitectura |

## Limitaciones

- La API de Garmin no es oficial ([python-garminconnect](https://github.com/cyberjunky/python-garminconnect)); puede romperse si Garmin cambia el login o sus endpoints.
- Web Bluetooth (medir la HRV en el navegador) funciona en Chrome y Edge, no en Safari ni Firefox.

**No es consejo médico.** Ante dolor o síntomas raros, para y consulta a un profesional.

## Contribuir

Issues y pull requests bienvenidos: lee [CONTRIBUTING.md](CONTRIBUTING.md) (entorno de desarrollo, flujo de ramas y formato de commits) y [SECURITY.md](SECURITY.md) para avisar de vulnerabilidades en privado.

## Apoya el proyecto

OpenRun es gratis y se hace en ratos libres. Si te ayuda a entrenar, puedes [invitarme a un café en Ko-fi](https://ko-fi.com/manueldelgado54792) ♥. Las estrellas, los avisos de fallos y las pull requests también ayudan.

## Licencia

[GNU Affero General Public License v3.0](LICENSE). Puedes usar, modificar e instalar OpenRun libremente; si ofreces una versión modificada como servicio a otras personas, debes compartir tus cambios con la misma licencia.
