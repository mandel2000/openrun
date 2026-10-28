# 🏃 OpenRun

Alternativa open source y local a Runna: planes de running basados en evidencia, sincronización con Garmin (datos + envío de entrenos al reloj), Amazfit Helio Strap (FC/HRV) y un coach IA que crea entrenos con tus datos reales.

- **Planes** 5K / 10K / medio / maratón / base: periodización, ritmos VDOT (Daniels), 80/20, progresión ≤10 % con descargas, taper, fuerza.
- **Garmin Forerunner 265**: descarga actividades, HRV, sueño y FC reposo; envía entrenos estructurados (con objetivos de ritmo) al calendario → reloj.
- **Helio Strap**: sensor de FC del 265 en carrera, medición de HRV matinal por Bluetooth desde el navegador e importación del export de Zepp.
- **Readiness**: ajusta el entreno del día según HRV/FC reposo/sueño. Botón "No me encuentro al 100 %".
- **Análisis post-entreno**: cada serie real (vueltas de Garmin) frente a lo planificado; si 2 de las 3 últimas sesiones de calidad salen más fáciles o más duras, ajusta el VDOT ±0,5 automáticamente (como *Pace Insights*).
- **Ajuste por calor**: previsión de Open-Meteo a tu hora de entreno → ritmos más lentos según temperatura + punto de rocío.
- **Rutina diaria automática** (06:30 por defecto): sync Garmin → análisis → ritmos → calor → readiness → próximos 7 días al reloj (solo lo que cambió).
- **Varios usuarios**: cada persona con su cuenta (por invitación), su plan, su Garmin, su coach y sus datos, aislados.
- **App en el móvil** (PWA instalable) con **notificaciones push** propias: entreno del día, análisis de cada carrera al sincronizar y resumen semanal.
- **Arrastrar y soltar** entrenos entre días en el plan (ratón o pulsación larga en el móvil): intercambia con lo que hubiera, reprograma el reloj y avisa si quedan dos días duros seguidos.
- **Estrategia de carrera**: ritmo km a km a esfuerzo constante sobre el perfil real (GPX/TCX/KML o enlace; altitud del terreno si falta), salida prudente, calor previsto el día de la carrera, geles e hidratos, mapa, y entreno de carrera en el reloj con un paso por km. Perfil aproximado de la Behobia incluido.
- **Actividades**: mapa, ritmo/FC/altitud sincronizados, parciales por km y dinámica de carrera (cadencia, zancada, contacto, oscilación, potencia).
- **Fuerza y movilidad** estructuradas: ejercicios con series, repeticiones, descanso y técnica (lista para marcar en el gimnasio), calentamiento dinámico y movilidad post-carrera.
- **Resumen semanal** cada lunes: cumplimiento, km, carga y foco de la semana, con comentario del coach IA.
- **Récords** 1K / milla / 5K / 10K / media / maratón: histórico, 12 meses, 6 meses y 30 días (mejores tramos de Garmin).
- **Importar histórico** antiguo: export completo de Strava o Garmin (.zip) o archivos .fit / .gpx / .tcx sueltos, con mejores tramos calculados y sin duplicar lo que ya está en Garmin.
- **Predicciones** de carrera: VDOT (Daniels) de tus mejores esfuerzos, Riegel, predictor de Garmin y FC; consenso y tendencia. Sugiere recalibrar ritmos (como *Pace Insights*).
- **Carreras** de la preparación desde el calendario de [Orycron Sport](https://www.orycronsport.com) o a mano: A (objetivo), B (mini-taper + recuperación), C (entreno). El plan se ajusta solo y el reloj se resincroniza.
- **Coach IA**: lee plan, actividades, HRV, carga, récords y carreras; crea/mueve/ajusta entrenos y los envía a Garmin. Los ritmos los calcula el servidor desde tu VDOT, nunca el modelo. Funciona con tu suscripción de Claude (MCP), Gemini gratis, Ollama local o API de pago.

La justificación científica de cada decisión está en [docs/RESEARCH.md](docs/RESEARCH.md).

## Arranque

Requisitos: Python ≥ 3.12, Node ≥ 20.

```bash
./run.sh
```

Abre http://localhost:8000. Todos los datos se guardan en `~/.openrun/` (SQLite + tokens de Garmin).

Para el coach IA necesitas una API key de Anthropic (pago por uso, sin suscripción):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Modelo por defecto `claude-opus-5-5` con esfuerzo `medium`. Para gastar menos: `export OPENRUN_MODEL=claude-haiku-5-5` (mucho más barato) u `OPENRUN_EFFORT=low`.

### Coach sin coste extra

| Opción | Cómo | Coste |
|---|---|---|
| **Tu suscripción de Claude** (Free/Pro/Max) | OpenRun como servidor MCP en Claude Desktop (config lista para copiar en *Ajustes › Coach IA*): `python -m app.mcp_server` | 0 € extra |
| **Gemini CLI** | Mismo bloque `mcpServers` en `~/.gemini/settings.json` | Gratis con cuenta Google |
| **NVIDIA** (chat dentro de la app) | `OPENRUN_PROVIDER=nvidia NVIDIA_API_KEY=nvapi-…` (modelo por defecto `minimaxai/minimax-m3.1-flash`) | Gratis con cuenta NVIDIA Developer, ~40 peticiones/min, condiciones de prueba |
| **Gemini API** (chat dentro de la app) | `OPENRUN_PROVIDER=gemini GEMINI_API_KEY=…` | Plan gratuito con límites; Google puede usar los datos |
| **Ollama** (local) | `ollama pull qwen3:8b` + `OPENRUN_PROVIDER=ollama` | Gratis, privado; peor calidad |
| Otras | `OPENRUN_PROVIDER=groq|openrouter|openai` + su key; `OPENRUN_MODEL` para cambiar modelo | Según proveedor |

Las suscripciones de consumo (Claude, ChatGPT, Gemini) no incluyen acceso API para apps propias; MCP es la forma soportada de usarlas con tus datos.

### Desarrollo

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload       # API en :8000
cd frontend && npm run dev                                   # UI en :5173 (proxy a /api)
cd backend && .venv/bin/python -m pytest                     # tests
```

### Automático y en el móvil

```bash
scripts/install-autostart.sh                              # arranca OpenRun al iniciar sesión (rutina diaria)
OPENRUN_PIN=<pin> scripts/install-autostart.sh --lan      # además, accesible desde el móvil en la misma wifi
```

En el móvil abre `http://<IP-del-Mac>:8000` (la ves en *Ajustes › OpenRun en el móvil*), entra con tu usuario (`admin` y el PIN la primera vez) y añádela a la pantalla de inicio. Fuera de casa, Tailscale; no abras puertos en el router.

Guía completa (comprobar estado, reiniciar, cambiar el PIN, desinstalar, seguridad y problemas frecuentes): [docs/AUTOSTART_Y_MOVIL.md](docs/AUTOSTART_Y_MOVIL.md). Para tenerlo en un servidor 24 h con HTTPS: [docs/DESPLIEGUE_VPS.md](docs/DESPLIEGUE_VPS.md).

## Primeros pasos

1. **Ajustes** → login de Garmin (soporta MFA) y *Sincronizar histórico completo*. Rellena FC máx/reposo.
2. **Ajustes › Importar histórico** → sube el export de Strava para tener récords de años anteriores.
3. **Progreso** → récords y predicciones; si te sugiere recalibrar, acepta.
4. **Plan** → objetivo, fecha, días, marca reciente → *Generar plan*.
5. **Carreras** → añade las de tu preparación (A/B/C).
6. *Enviar Sx al reloj* y sincroniza el 265 (Entrenamiento › Calendario).
7. Helio Strap: en la app Zepp activa *compartir FC*; en el 265, *Sensores y accesorios › Añadir › FC*. Por la mañana, *Ajustes › Conectar banda › Medir HRV*.

## Estructura

```
backend/app/training/   vdot.py (Daniels), plan.py (generador), workouts.py (biblioteca de sesiones),
                        load.py (TRIMP, CTL/ATL, HRV readiness, RMSSD), adapt.py (ajustes)
                        records.py (PRs, predicciones)
backend/app/integrations/ garmin.py (python-garminconnect), zepp.py (CSV/zip), orycron.py (calendario),
                          history_import.py (Strava/FIT/GPX/TCX)
backend/app/ai/coach.py   coach multi-proveedor + herramientas
backend/app/mcp_server.py servidor MCP (Claude Desktop, Gemini CLI)
frontend/src/             React (Hoy, Plan, Carreras, Progreso, Coach, Ajustes)
```

## Limitaciones

- La API de Garmin no es oficial; puede romperse si Garmin cambia el login/endpoints.
- Web Bluetooth solo en Chrome/Edge (no Safari/Firefox).
- Pendiente: ajuste por calor, exportar entrenos .FIT por USB, app móvil.

No es consejo médico: ante dolor o síntomas, para y consulta a un profesional.
