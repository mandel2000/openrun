# Investigación: qué hace Runna y en qué se basa OpenRun

## 1. Qué hace Runna (2026)

Fuentes: [the5krunner – Runna](https://the5krunner.com/runna/), [the5krunner – Is Runna AI?](https://the5krunner.com/2026/09/28/is-runna-ai/), [endurance.biz – Runna 2026 updates](https://endurance.biz/2026/industry-news/runna-updates-beginner-and-return-to-running-training-plans/). Strava compró Runna en abril de 2025; sigue siendo una app independiente.

| Función Runna | OpenRun |
|---|---|
| Planes 5K / 10K / medio / maratón, principiante / vuelta a correr | ✅ 5K, 10K, medio, maratón, "base" (forma general / vuelta a correr), 3 niveles |
| Onboarding: marca reciente, días/semana, día de tirada larga, volumen actual, fecha de carrera, objetivo | ✅ mismo formulario |
| Ritmos personalizados por sesión | ✅ VDOT de Daniels, 10 zonas |
| Predicción de tiempo de carrera que se actualiza | ✅ al inicio, al final (estimada) y tras cada marca/test |
| **Pace Insights**: propone cambiar ritmos según cómo corres | ✅ "Nueva marca/test" y estimación de VDOT por FC (Swain); el coach IA puede recalibrar |
| Las sesiones completadas alimentan el plan | ✅ sync Garmin empareja actividad↔entreno; carga TRIMP/CTL/ATL |
| **"Not feeling 100%"**: bajar intensidad 3–14 días | ✅ mismo botón (reducir o descanso activo) |
| Fuerza, calentamiento, movilidad | ✅ fuerza 2×/sem según fase; calentamientos en cada sesión de calidad |
| Envío al reloj Garmin | ✅ Garmin Connect workout + calendario (se sincroniza al 265) |
| Mileage Insights / briefings de sesión | ✅ % baja intensidad por semana, descripción fisiológica por sesión; el coach IA analiza |
| Adapt for Heat | ✅ temperatura + punto de rocío (Open-Meteo) a tu hora de entreno |
| Coach conversacional | ✅ Claude con herramientas sobre tus datos (Runna no lo tiene) |
| HRV / readiness | ✅ HRV de Garmin, Zepp o medición propia con la Helio Strap (Runna no lo usa) |

Nota: un reportaje del WSJ (febrero 2026) citado por the5krunner recogía fisioterapeutas viendo lesiones asociadas a Runna; por eso OpenRun limita progresión, intensidad y volumen por sesión y usa readiness.

## 2. Bases científicas del motor de planes

### Ritmos: VDOT (Daniels & Gilbert)
- Coste de O₂: `VO2 = -4.60 + 0.182258·v + 0.000104·v²` (v en m/min); fracción sostenible: `0.8 + 0.1894393·e^(-0.012778·t) + 0.2989558·e^(-0.1932605·t)`.
- Zonas (Daniels' Running Formula, 3ª ed.): E 59–74 % VDOT, M = ritmo maratón previsto, T 83–88 %, I 95–100 %, R ~105–110 %.
- Validado en tests: 5K 19:57 ≈ VDOT 50, T ≈ 4:15/km.

### Distribución de intensidad
- ~80 % baja / ~20 % moderada-alta; máximo 2 sesiones de calidad por semana. Seiler & Kjerland 2006; Seiler 2010; Stöggl & Sperlich 2014 (polarizado > umbral/volumen); Casado et al. 2022 (pirámide en fondistas de élite).
- Si la tirada larga lleva bloque a ritmo de carrera, la 2ª sesión de calidad pasa a suave + progresivos.

### Volumen por sesión (Daniels)
- Umbral ≤ 10 % del volumen semanal; I ≤ min(10 km, 8 %), repeticiones de 3–5 min con recuperación ≈ igual; R ≤ min(8 km, 5 %), recuperación completa.
- Tirada larga ≤ 25–33 % del volumen semanal (hasta 42 % en el pico de maratón) y con tope de tiempo; +2 km/semana como máximo.

### Progresión y carga
- ≤ +8 %/semana con semana de descarga (−25 %) cada 4 semanas (cada 3 en principiantes y > 50 años). Nielsen et al. 2014 (lesión en noveles con incrementos > 30 %/2 sem); Gabbett 2016 (ACWR 0,8–1,3).
- El ACWR se muestra solo como guía orientativa: su valor predictivo está discutido (Impellizzeri et al. 2020).
- TRIMP de Banister (1991); fitness/fatiga como EWMA de 42/7 días.

### Periodización y taper
- Base (~40 %) → desarrollo (~35 %) → específico (~25 %) → afinamiento. Issurin 2010.
- Taper: −40–60 % de volumen manteniendo intensidad y frecuencia, ~2 semanas (3 en maratón, 1 en 5K/10K). Bosquet et al. 2007 (meta-análisis); Mujika & Padilla 2003.

### Ritmo objetivo realista
- La mejora esperada se limita a +0,1–0,3 VDOT/semana según nivel; si el objetivo excede lo alcanzable, se avisa y se entrena con la forma actual (re-calibrando con resultados reales), no con el objetivo.

### Readiness guiada por HRV
- Media 7 días de ln(RMSSD) frente a línea base de 60 días ± 0,5 DE (cambio mínimo relevante). Kiviniemi 2007; Plews et al. 2013; Vesterinen 2016; Javaloyes 2019; Düking 2021 (meta-análisis).
- Ámbar → −30 % del volumen de calidad manteniendo intensidad. Rojo → regenerativo.
- FC reposo +5 ppm sobre la media o mal sueño también bajan la readiness.
- Medición propia con la Helio Strap: 3 min tumbado, se descartan los primeros 30 s; filtro de artefactos (>20 % de cambio entre RR).

### Fuerza
- Fuerza pesada + pliometría 2×/semana mejora la economía de carrera 2–8 % sin perjudicar el VO₂máx. Blagrove et al. 2018 (revisión sistemática); Støren 2008. Mismo día que la calidad ("días duros duros").

### Estimación de forma por FC
- %FCR ≈ %VO₂R (Swain 1997): `VO2max ≈ (VO2(v) − 3,5) / %FCR + 3,5` en rodajes continuos > 20 min al 60–90 % FCR; se usa la mediana de ≥ 3 rodajes. Es orientativa (deriva cardiaca, desnivel, calor).

## 3. Integraciones

### Garmin Forerunner 265
- La API oficial de Garmin es solo para empresas aprobadas. OpenRun usa [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) (≥ 0.3, ya sin garth): login SSO móvil con MFA, tokens guardados en `~/.openrun/garmin`, auto-refresh.
- Datos: actividades, HRV nocturna, sueño, FC en reposo, body battery, training readiness, LTHR, VO₂máx, predicciones.
- Entrenos: `upload_workout` (JSON de pasos con objetivos de ritmo en m/s) + `schedule_workout` → calendario de Connect → el 265 los descarga al sincronizar.
- Es una API no oficial: Garmin puede cambiarla sin aviso.

### Amazfit Helio Strap
- Zepp no tiene API pública. La banda emite el perfil BLE estándar de FC (0x180D) con intervalos RR.
- En carrera: emparejar como sensor de FC externo en el 265 → la FC de la banda queda en la actividad de Garmin.
- HRV matinal: Web Bluetooth (Chrome/Edge) → RMSSD calculado en el backend.
- Histórico: importación del export de datos de Zepp (.zip/CSV).

## 4. Récords, predicciones y carreras

- **Récords**: Garmin incluye en cada actividad el tramo más rápido de 1 km, milla, 5 km y 10 km (`fastestSplit_*`). Si falta (p. ej. un "10K" de 9,95 km), se usa la actividad completa (−0,5 %/+5 % de la distancia) escalada al ritmo y marcada como aproximada. El histórico "Siempre" se completa con los PR que guarda Garmin.
- **Predicciones**: VDOT de Daniels del mejor esfuerzo ≥ 1 milla en 90 días; Riegel (1981) `T2 = T1·(D2/D1)^1,06` desde el esfuerzo de distancia más cercana; predictor de Garmin; VDOT por FC (Swain). Consenso = mediana. Las predicciones de media/maratón asumen volumen y tiradas largas suficientes (Riegel y VDOT sobreestiman a corredores de poco volumen).
- **Carreras durante la preparación**: A = objetivo (plan periodizado hacia ella). B = preparatoria: mini-taper de 3 días (calidad → suave + progresivos, víspera activación) siguiendo la lógica de reducir volumen manteniendo intensidad (Mujika & Padilla 2003; Bosquet 2007), y recuperación de ~1 día suave por cada 3 km (Daniels). C = de entreno: sin taper, cuenta como sesión de calidad. Quitar una carrera restaura el plan original.
- **Calendario**: [Orycron Sport](https://www.orycronsport.com/competiciones/?proximas=1) no tiene API; se lee el listado público (HTML) y la ficha de cada prueba (día, lugar, recorrido), con caché de 12 h. Filtra BTT/marchas/ciclismo.

## 5. Importación del histórico

- Formatos: export completo de Strava (`activities.csv` + `activities/*.fit.gz|gpx|tcx`), export de Garmin (zips anidados) y archivos sueltos. FIT con `fitdecode`; GPX/TCX con la librería estándar.
- Mejores tramos: ventana deslizante sobre la serie distancia–tiempo con interpolación del punto de inicio exacto. Validado contra los `fastestSplit` de Garmin en dos FIT reales: diferencia ≤ 0,1 s en 1K, milla y 5K.
- GPX (solo GPS): media móvil de 5 puntos y descarte de saltos > 8,5 m/s. En las pruebas, los tramos salen un 0,2–1,2 % más lentos que con la distancia del reloj (conservador); se marcan como aproximados. Se descartan tiempos más rápidos que récords mundiales.
- Duplicados: misma fecha (±1 día, por diferencias UTC/local), distancia ±3 % y duración ±5 %, o mismo ID externo. Reimportar es idempotente.

## 6. Análisis post-entreno, ritmos automáticos y calor

- **Vuelta ↔ paso**: Garmin graba una vuelta por paso ejecutado (`wktStepIndex` = orden del paso − 1 en el entreno subido; las repeticiones comparten índice), así que cada serie se compara con su rango de ritmo. Tolerancia ±2 % fuera del rango.
- **Veredicto** (solo sesiones de calidad): «más fácil» si las series van de media ≥ 2 % más rápidas sin FC por encima de LTHR+2 % (en umbral/maratón; en I/R la FC va retrasada y no se usa); «más dura» si la mitad de las series van ≥ 3 % más lentas o la FC supera LTHR+5 % yendo a ritmo.
- **Ajuste de VDOT**: ±0,5 cuando 2 de las 3 últimas sesiones (21 días) coinciden; máximo una vez por semana y nunca en los 10 días previos a la carrera objetivo. Conservador para que un día bueno (o uno frío) no mueva todos los ritmos. Es la misma idea que *Pace Insights* de Runna, con reglas explícitas.
- **Calor**: el rendimiento cae al aumentar el estrés térmico (Ely et al. 2007; El Helou et al. 2012, óptimo ~4–10 °C; Mantzios et al. 2022). Se usa la regla de entrenadores T + punto de rocío (°F) (Hadley): ≤ 100 sin ajuste, 101–110 +0,5 %, … , 171–180 +11 %, > 180 no hacer calidad al aire libre. Se mantiene el esfuerzo (y la adaptación buscada), no el ritmo. Se deshace solo si la previsión baja.

## 7. Readiness 0–100

- Partes: HRV (35 %, z-score de hoy y de la media de 7 días frente a la línea base; estado de HRV de Garmin si aún no hay base), sueño de anoche (20 %), FC en reposo frente a su media de 60 días (15 %), carga (15 %: forma/TSB y ACWR > 1,5) y un check-in de dos preguntas (15 %: sensación general y piernas, 1–5).
- El bienestar subjetivo responde a la carga al menos tan bien como los marcadores objetivos (Saw, Main & Gastin 2016, revisión sistemática): por eso pesa junto a los fisiológicos.
- Las partes que faltan se omiten y los pesos se reparten; sin datos, no hay nota. ≥ 65 verde, 45–64 ámbar, < 45 rojo. La nota solo puede endurecer el estado por HRV, nunca relajarlo.
- "Estoy enfermo/a" en el check-in: descanso o muy suave hoy ("regla del cuello", Eichner 1993).

## 8. Reajuste del plan

- **Rodajes suaves perdidos**: se dejan pasar; recuperarlos amontona fatiga en los días siguientes.
- **Sesión clave perdida** (calidad o tirada larga): se propone en el primer día de los 4 siguientes (3 en tiradas largas, y como mucho 6 días después de la perdida) con rodaje suave o libre y sin día duro antes ni después; sustituye a ese rodaje. Si no hay hueco, se deja pasar: una sesión perdida no cuesta nada medible y juntar dos días duros sí (principio duro/suave; Seiler 2010).
- Una carrera hecha uno o dos días tarde, en un día sin nada planificado, cuenta para la sesión perdida.
- **Vuelta tras un parón**: menos de una semana apenas desentrena; 2–4 semanas cuestan ~4–7 % de VO₂máx; más de 8 semanas, mucho más (Mujika & Padilla 2000; Coyle 1984). Siguiendo a Daniels: ≤ 5 días sin cambio de VDOT; 6–28 días hasta −7 %; 29–56 días hasta −14 %; más, −15 % y conviene un plan nuevo. Primero días solo suaves (tras enfermedad, tantos como días enfermo; tras lesión, dos más) y luego volumen reducido (−20–40 %) el resto de una o dos semanas. Con fiebre o síntomas en el pecho, nada de correr hasta 24–48 h sin síntomas (Eichner 1993; Nieman).

## 9. Fuerza y movilidad

- Fuerza pesada (≥ 80 % 1RM) y pliometría 2×/semana mejoran la economía de carrera un 2–8 % sin perjudicar el VO₂máx (Blagrove et al. 2018; Balsalobre-Fernández et al. 2016; Støren et al. 2008).
- Capacidad del sóleo (soporta ~6–8 veces el peso corporal por zancada): elevaciones de gemelo con rodilla flexionada y carga (Dorn et al. 2012). Fuerza de abductores y control a una pierna se relacionan con el riesgo de lesión (Willy & Davis 2011). El Copenhagen reduce lesiones de aductores (Harøy 2019).
- El mismo día que la calidad y después de ella; volumen de mantenimiento en el pico y nada en la semana de carrera (Beattie 2014).
- Sin estiramientos estáticos antes de correr (no previenen lesiones y pueden restar potencia); calentamiento dinámico sí (Behm 2016). Movilidad corta y suave después.

## 10. Estrategia de carrera

- Esfuerzo constante, no ritmo constante: en recorridos con desnivel lo más rápido es mantener la potencia metabólica (Minetti et al. 2002; Townshend et al. 2010).
- Los costes de laboratorio de Minetti exageran el efecto a ritmo de carrera (modelos de ritmo ajustado por pendiente como el GAP de Strava de 2017 penalizan menos la subida) y el ahorro en bajada no se aprovecha entero: se toma el 80 % del coste en subida y el 50 % del ahorro en bajada, con pendientes limitadas a −12…+15 %.
- Primer o segundo km algo prudentes (Abbiss & Laursen 2008); el total se mantiene en el objetivo.
- Hidratos: 30–60 g/h en esfuerzos de 1–2,5 h y enjuague o gel antes de 75 min (Jeukendrup 2014; ACSM 2016); carga de 7–10 g/kg/día 24–36 h antes en carreras de más de 90 min (Burke 2011).
