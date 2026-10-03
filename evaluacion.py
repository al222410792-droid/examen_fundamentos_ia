#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evaluación del clasificador con 30 correos etiquetados.
Compara reglas, LLM e híbrido: exactitud (categoría y prioridad), matriz de confusión y latencia.

IMPORTANTE: las etiquetas de DATASET son una propuesta; revísalas y corrígelas a mano
según tu criterio antes de reportar resultados.
Formato: (texto, categoria_real, prioridad_real)
"""
import json
import statistics
from datetime import datetime
from typing import Callable, Dict, Optional

from clasificador_hibrido import CATEGORIAS

DATASET = [
    # --- materiales_peligrosos (7)
    ("URGENTE: Fuga de químico en el andén 4. Vehículo placa XYZ-987 presenta derrame.", "materiales_peligrosos", "critica"),
    ("El camión CAM-102 trae un tanque con liquido inflamable goteando en la rampa 2", "materiales_peligrosos", "critica"),
    ("huele muy fuerte a gas en la caseta 3, creo q viene del tráiler ABC-123-A", "materiales_peligrosos", "critica"),
    ("Se detectó un derrame de ácido en el muelle 6, ya se aisló la zona.", "materiales_peligrosos", "critica"),
    ("ayuda!! se regó el kimico del camion de la empresa Quimex en el anden 1", "materiales_peligrosos", "critica"),
    ("Reporte: el conductor declaró carga peligrosa clase 3 sin la hoja de seguridad (hazmat).", "materiales_peligrosos", "alta"),
    ("Hay olor a combustible cerca del tanque del camión TRK-450, sin fuga visible por ahora.", "materiales_peligrosos", "alta"),
    # --- sobrepeso (6)
    ("La báscula marcó 48 toneladas para el camión CAM-210, excede el límite permitido.", "sobrepeso", "media"),
    ("Camión ABC-555 con sobrepeso, el chofer insiste en pasar.", "sobrepeso", "media"),
    ("el trailer TRK-300 viene muy cargado, pesa mas de lo permitido segun la bascula", "sobrepeso", "media"),
    ("Exceso de peso detectado en eje trasero del vehículo DEF-77, reincidente este mes.", "sobrepeso", "alta"),
    ("sobre peso en el camion de MegaTrans, creo q mas de 5 tons", "sobrepeso", "media"),
    ("El vehículo GHI-901 supera la carga máxima por 2 toneladas.", "sobrepeso", "media"),
    # --- falla_hardware (6)
    ("La cámara del acceso norte no enciende desde la mañana.", "falla_hardware", "media"),
    ("Sensor de la barrera 2 marca error y no levanta la pluma.", "falla_hardware", "alta"),
    ("no jala el lector de placas, se queda congelado la pantalla", "falla_hardware", "media"),
    ("Falla en el sistema de iluminación del patio 3, está muy oscuro.", "falla_hardware", "baja"),
    ("El lector RFID de la caseta 1 lee mal los gafetes, ya van 3 veces.", "falla_hardware", "media"),
    ("se cayó el internet en la garita y la cámara no graba", "falla_hardware", "media"),
    # --- acceso_no_autorizado (6)
    ("Una persona entró por la puerta lateral sin autorización, seguridad la detuvo.", "acceso_no_autorizado", "alta"),
    ("El camión QWE-321 intentó ingresar sin permiso previo y con placas que parecen clonadas.", "acceso_no_autorizado", "alta"),
    ("alguien forzó el candado del almacén 5 durante la noche", "acceso_no_autorizado", "alta"),
    ("Conductor no autorizado intentó usar el gafete de otro compañero.", "acceso_no_autorizado", "alta"),
    ("vi a un tipo q se coló x la reja de atrás, no traía gafete", "acceso_no_autorizado", "alta"),
    ("Visitante sin registro en bitácora acompañó al camión RTY-408 hasta el andén.", "acceso_no_autorizado", "media"),
    # --- otro (5)
    ("Solicito la constancia de entregas del mes de septiembre para contabilidad.", "otro", "baja"),
    ("Buenos días, ¿a qué hora abre la caseta de recepción los domingos?", "otro", "baja"),
    ("Recordatorio: capacitación de seguridad el viernes a las 10:00.", "otro", "baja"),
    ("Se perdió una carpeta con facturas, favor de buscarla en oficina.", "otro", "baja"),
    ("Felicitaciones al equipo de turno nocturno por la entrega sin incidentes.", "otro", "baja"),
]

CATS = CATEGORIAS + ["sin_respuesta"]
ABREV = {"materiales_peligrosos": "MAT", "sobrepeso": "SOB", "falla_hardware": "HW",
         "acceso_no_autorizado": "ACC", "otro": "OTR", "sin_respuesta": "N/R"}
NOMBRE_METODO = {"reglas": "Reglas", "llm": "LLM", "hibrido": "Híbrido"}


def _metricas(d: Dict) -> Dict:
    n = len(d["real_c"])
    matriz = {r: {p: 0 for p in CATS} for r in CATEGORIAS}
    for r, p in zip(d["real_c"], d["pred_c"]):
        matriz[r][p] += 1
    lats = d["lat"]
    return {
        "exactitud_categoria": sum(a == b for a, b in zip(d["real_c"], d["pred_c"])) / n,
        "exactitud_prioridad": sum(a == b for a, b in zip(d["real_p"], d["pred_p"])) / n,
        "latencia_media_s": statistics.mean(lats),
        "latencia_max_s": max(lats),
        "matriz_confusion": matriz,
    }


def ejecutar(clf, progreso: Optional[Callable[[int, int], None]] = None) -> Dict:
    n = len(DATASET)
    datos = {m: {"real_c": [], "real_p": [], "pred_c": [], "pred_p": [], "lat": []}
             for m in NOMBRE_METODO}
    revision = fallos = 0
    for i, (texto, cat, prio) in enumerate(DATASET, 1):
        if progreso:
            progreso(i - 1, n)
        reg = clf.clasificar_por_reglas(texto)
        llm = clf.clasificar_llm(texto)
        clf.registrar_evaluacion(llm, reg)
        hib = clf.fusionar(reg, llm)
        preds = {
            "reglas": (reg["categoria"], reg["prioridad"], reg["latencia"]),
            "llm": ((llm["categoria"], llm["prioridad"]) if llm["ok"]
                    else ("sin_respuesta", "sin_respuesta")) + (llm["latencia"],),
            "hibrido": (hib["categoria"], hib["prioridad"], hib["latencia"]),
        }
        for m, (pc, pp, lat) in preds.items():
            d = datos[m]
            d["real_c"].append(cat)
            d["real_p"].append(prio)
            d["pred_c"].append(pc)
            d["pred_p"].append(pp)
            d["lat"].append(lat)
        revision += int(hib["requiere_revision_humana"])
        fallos += int(not llm["ok"])
    if progreso:
        progreso(n, n)
    return {"n": n, "modelo": clf.modelo, "fecha": datetime.now().isoformat(timespec="seconds"),
            "metodos": {m: _metricas(d) for m, d in datos.items()},
            "revision_humana": revision, "llm_sin_respuesta": fallos}


def formatear(res: Dict) -> str:
    L = [f"EVALUACIÓN  n={res['n']}  modelo={res['modelo']}  {res['fecha']}", ""]
    L.append(f"{'Método':<10}{'Exact. cat.':>12}{'Exact. prio.':>14}{'Lat. media':>12}{'Lat. máx':>10}")
    for m, x in res["metodos"].items():
        L.append(f"{NOMBRE_METODO[m]:<10}{x['exactitud_categoria']:>11.0%} {x['exactitud_prioridad']:>13.0%} "
                 f"{x['latencia_media_s']:>10.2f}s {x['latencia_max_s']:>8.2f}s")
    L.append("")
    L.append(f"LLM sin respuesta válida: {res['llm_sin_respuesta']}/{res['n']}   |   "
             f"Híbrido con revisión humana: {res['revision_humana']}/{res['n']}")
    for m, x in res["metodos"].items():
        L += ["", f"Matriz de confusión — {NOMBRE_METODO[m]} (filas=real, columnas=predicho)",
              "      " + " ".join(f"{ABREV[c]:>4}" for c in CATS)]
        for r in CATEGORIAS:
            L.append(f"{ABREV[r]:<5} " + " ".join(f"{x['matriz_confusion'][r][c]:>4}" for c in CATS))
    return "\n".join(L)


def guardar_json(res: Dict, ruta: str = "evaluacion_resultados.json") -> str:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return ruta