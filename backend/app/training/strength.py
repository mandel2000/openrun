"""Strength & mobility for runners: structured sessions instead of a text blob.

Evidence:
- Heavy (≥80 % 1RM) and explosive/plyometric training improves running economy 2-8 % and
  time-trial performance without hurting VO2max (Blagrove et al. 2018; Balsalobre-Fernández
  et al. 2016 meta-analysis; Støren et al. 2008).
- Calf-soleus capacity: the soleus takes ~6-8× body weight per stride; loaded calf raises with
  bent knee target it (Dorn et al. 2012; Achilles/calf injury prevention).
- Hip abductor / glute strength and single-leg control relate to running-injury risk (Willy &
  Davis 2011; patellofemoral pain). Copenhagen adduction lowers groin injuries (Harøy 2019).
- Same day as quality runs, after them (hard days hard), ≥6 h apart if possible; drop to
  maintenance volume in the peak and none in race week (Beattie 2014; periodisation).
- Static stretching before running does not prevent injury and can blunt power; a dynamic
  warm-up does help (Behm 2016). Post-run mobility is for comfort/range, short and gentle.
"""

from __future__ import annotations


def ex(name: str, sets: int, reps: str, rest_s: int, cue: str, load: str = "") -> dict:
    return {"name": name, "sets": sets, "reps": reps, "rest_s": rest_s, "cue": cue, "load": load}


SESSIONS: dict[str, dict] = {
    "base": {
        "title": "Fuerza general",
        "goal": "Base de fuerza y control en una pierna: tendones y articulaciones preparados para cargar más km.",
        "minutes": 35,
        "exercises": [
            ex("Sentadilla goblet", 3, "10-12", 75, "Pecho alto, rodillas siguen la punta del pie, baja hasta muslo paralelo.", "RPE 7: te sobran 3 reps"),
            ex("Peso muerto rumano", 3, "10", 75, "Cadera atrás con espalda neutra, mancuernas pegadas a las piernas; siente los isquios."),
            ex("Zancada atrás", 3, "8 por pierna", 60, "Paso largo atrás, rodilla delantera estable sin irse hacia dentro."),
            ex("Puente de glúteo a 1 pierna", 3, "12 por pierna", 45, "Empuja con el talón, pelvis nivelada, aprieta glúteo arriba 1 s."),
            ex("Elevación de gemelos de pie (rodilla recta)", 3, "15", 45, "Sube 1 s, baja en 3 s, rango completo en un escalón."),
            ex("Elevación de gemelos sentado (rodilla flexionada)", 3, "15", 45, "Sóleo: peso sobre las rodillas, lento y completo."),
            ex("Plancha lateral", 3, "30 s por lado", 30, "Cuerpo en línea, cadera alta, sin hundir el hombro."),
        ],
    },
    "build": {
        "title": "Fuerza máxima + pliometría",
        "goal": "Fuerza pesada y rigidez del tendón para mejorar la economía de carrera (2-8 %).",
        "minutes": 40,
        "exercises": [
            ex("Saltos al cajón", 3, "5", 90, "Máxima intención, aterriza suave y bájate andando. Calidad > cansancio.", "Primero, sin fatiga"),
            ex("Pogos (saltitos de tobillo)", 3, "20", 60, "Rodillas casi rectas, rebote rápido sobre antepié, poco tiempo de contacto."),
            ex("Sentadilla o peso muerto trap-bar", 4, "5", 150, "Pesado pero limpio: técnica perfecta en todas las reps.", "RPE 8 (te sobran 2)"),
            ex("Step-up con carga", 3, "6 por pierna", 90, "Cajón a altura de rodilla, empuja solo con la pierna de arriba."),
            ex("Gemelo sóleo con carga (sentado)", 3, "10-12", 60, "Carga alta, 3 s de bajada."),
            ex("Copenhagen (aductores)", 2, "6-8 por lado", 45, "Versión corta (rodilla apoyada) si es la primera vez."),
        ],
    },
    "maintenance": {
        "title": "Mantenimiento de fuerza",
        "goal": "Mantener lo ganado con poco volumen: no debe dejarte cansado para la próxima sesión de calidad.",
        "minutes": 25,
        "exercises": [
            ex("Pogos", 2, "15", 60, "Rebote rápido y elástico."),
            ex("Sentadilla trap-bar o goblet pesada", 2, "5", 120, "Pesado, pocas reps, lejos del fallo.", "RPE 7-8"),
            ex("Peso muerto rumano", 2, "6", 90, "Controlado."),
            ex("Gemelo sóleo con carga", 2, "12", 45, "Lento al bajar."),
            ex("Plancha frontal", 2, "40 s", 30, "Glúteos activos, sin arquear la lumbar."),
        ],
    },
}

MOBILITY = {
    "title": "Movilidad post-carrera",
    "goal": "10 minutos suaves después de correr para recuperar rango de movimiento. Sin rebotes ni dolor.",
    "minutes": 10,
    "exercises": [
        ex("Estiramiento de flexor de cadera (rodilla en el suelo)", 1, "45 s por lado", 0, "Mete la pelvis y empuja la cadera adelante."),
        ex("Gemelo y sóleo en pared", 1, "30 s + 30 s por pierna", 0, "Primero rodilla recta, luego flexionada."),
        ex("Isquios con pierna en alto", 1, "45 s por pierna", 0, "Espalda recta, inclínate desde la cadera."),
        ex("Figura 4 (glúteo/piriforme)", 1, "45 s por lado", 0, "Tumbado, tobillo sobre la rodilla contraria."),
        ex("Rotación torácica en cuadrupedia", 1, "8 por lado", 0, "Mano en la nuca, abre el codo al techo siguiéndolo con la vista."),
        ex("Respiración diafragmática tumbado", 1, "1 min", 0, "Inhala 4 s, exhala 6 s: baja pulsaciones y activa la recuperación."),
    ],
}

WARMUP = {
    "title": "Calentamiento dinámico",
    "goal": "5-8 minutos antes de series o carreras. Nada de estiramientos estáticos aquí.",
    "minutes": 7,
    "exercises": [
        ex("Balanceos de pierna adelante-atrás", 1, "10 por pierna", 0, "Apoyado en una pared, amplitud progresiva."),
        ex("Balanceos laterales", 1, "10 por pierna", 0, "Cadera suelta."),
        ex("Zancada con rotación", 1, "5 por lado", 0, "Gira el tronco hacia la pierna delantera."),
        ex("Skipping bajo", 2, "20 m", 0, "Cadencia rápida, contacto corto."),
        ex("Talones al glúteo", 2, "20 m", 0, "Relajado."),
        ex("Progresivos", 3, "80 m", 45, "De suave a rápido (no sprint), vuelve andando."),
    ],
}


def session(focus: str) -> dict:
    return SESSIONS.get(focus) or SESSIONS["base"]


def focus_for_title(title: str) -> str:
    t = (title or "").lower()
    return "build" if "máxima" in t or "pliometr" in t else "maintenance" if "manten" in t else "base"


def describe(sess: dict) -> str:
    return " · ".join(f"{e['name']} {e['sets']}×{e['reps']}" for e in sess["exercises"])
