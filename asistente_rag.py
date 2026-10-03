#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List

import requests

from clasificador_hibrido import PLACA_RE

log = logging.getLogger("rag")
NO_INFO = "No tengo información registrada sobre esa consulta."


def _f(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v


class AsistenteRAG:
    def __init__(self, db_manager, modelo_ollama: str = "llama3.2", timeout: int = 60):
        self.db = db_manager
        self.modelo = modelo_ollama
        self.timeout = timeout
        self.url_ollama = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")

    # ------------------------------------------------------------------ recuperación
    def recuperar(self, pregunta: str) -> List[Dict[str, Any]]:
        m = PLACA_RE.search(pregunta.upper())
        placa = m.group(0) if m else None
        orden = ("fecha_registro", -1)
        fuentes: List[Dict[str, Any]] = []

        if placa:
            camiones = self.db.listar("camiones", {"placa": placa}, 1)
            accesos = self.db.listar("accesos", {"placa": placa}, 5, orden)
            incidentes = self.db.listar("incidentes", {"entidades.placa": placa}, 5, orden)
        else:
            camiones = []
            accesos = self.db.listar("accesos", None, 3, orden)
            incidentes = self.db.listar("incidentes", None, 3, orden)

        for i, d in enumerate(camiones, 1):
            fuentes.append({"tag": f"CAM-{i}", "coleccion": "camiones", "id": d["_id"],
                            "fecha": _f(d.get("fecha_registro")),
                            "datos": {k: d.get(k) for k in ("placa", "camion_id", "empresa", "autorizacion",
                                                            "certificacion_conductor", "certificacion_vigente")}})
        for i, d in enumerate(accesos, 1):
            fuentes.append({"tag": f"ACC-{i}", "coleccion": "accesos", "id": d["_id"],
                            "fecha": _f(d.get("fecha_registro")),
                            "datos": {"placa": d.get("placa"), "premisas": d.get("premisas"),
                                      "decision": d.get("decision"), "explicacion": d.get("explicacion"),
                                      "operador": d.get("operador")}})
        for i, d in enumerate(incidentes, 1):
            fuentes.append({"tag": f"INC-{i}", "coleccion": "incidentes", "id": d["_id"],
                            "fecha": _f(d.get("fecha_registro")),
                            "datos": {"categoria": d.get("categoria"), "prioridad": d.get("prioridad"),
                                      "estado": d.get("estado"), "entidades": d.get("entidades"),
                                      "resumen": d.get("resumen"),
                                      "requiere_revision_humana": d.get("requiere_revision_humana")}})
        return fuentes

    # ------------------------------------------------------------------ respuesta
    def responder_consulta(self, pregunta: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        fuentes = self.recuperar(pregunta)
        if not fuentes:
            return {"respuesta": NO_INFO, "fuente": "MongoDB: sin registros relacionados",
                    "fuentes": [], "latencia": time.perf_counter() - t0, "origen": "sin_datos"}

        contexto = "\n".join(
            f"[{f['tag']}] ({f['coleccion']}, id={f['id']}, fecha={f['fecha']}): "
            f"{json.dumps(f['datos'], ensure_ascii=False, default=str)}" for f in fuentes)
        prompt = (
            "Eres un asistente de seguridad y logística. Responde en español SOLO con los datos del "
            "contexto, citando la fuente entre corchetes (por ejemplo [ACC-1]). No inventes nada. "
            f'Si el contexto no contiene la respuesta, responde exactamente: "{NO_INFO}"\n\n'
            f"Contexto:\n{contexto}\n\nPregunta: {pregunta}\nRespuesta:")
        etiqueta = ", ".join(f"{f['tag']} ({f['coleccion']})" for f in fuentes)

        try:
            r = requests.post(self.url_ollama, timeout=self.timeout,
                              json={"model": self.modelo, "prompt": prompt, "stream": False,
                                    "options": {"temperature": 0}})
            r.raise_for_status()
            texto = r.json().get("response", "").strip() or NO_INFO
            if texto != NO_INFO and "[" not in texto:
                texto += "\n(Fuentes: " + ", ".join(f["tag"] for f in fuentes) + ")"
            return {"respuesta": texto, "fuente": etiqueta, "fuentes": fuentes,
                    "latencia": time.perf_counter() - t0, "origen": "ollama_rag"}
        except Exception as e:
            log.warning("LLM no disponible en RAG: %s", e)
            lineas = [f"- [{f['tag']}] {f['coleccion']} · {f['fecha']}: "
                      f"{f['datos'].get('explicacion') or f['datos'].get('resumen') or f['datos']}"
                      for f in fuentes]
            return {"respuesta": "⚠ El LLM local no respondió. Registros encontrados:\n" + "\n".join(lineas),
                    "fuente": etiqueta, "fuentes": fuentes,
                    "latencia": time.perf_counter() - t0, "origen": "respaldo_sin_llm"}