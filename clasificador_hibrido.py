#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import time
import unicodedata
from typing import Any, Callable, Dict, Literal, Optional

import requests
from pydantic import BaseModel, ConfigDict

log = logging.getLogger("clasificador")

CATEGORIAS = ["materiales_peligrosos", "sobrepeso", "falla_hardware",
              "acceso_no_autorizado", "otro"]
PRIORIDADES = ["baja", "media", "alta", "critica"]
RANGO = {p: i for i, p in enumerate(PRIORIDADES)}

# Placas tipo CAM-102, XYZ-987, ABC-123-A
PLACA_RE = re.compile(r"\b[A-Z]{2,4}-\d{2,4}(?:-[A-Z0-9]{1,2})?\b|\b[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}\b")
UBIC_RE = re.compile(r"\b(and[eé]n|puerta|muelle|rampa|caseta|garita|almac[eé]n|patio)\s*#?\s*(\d+|[a-z])\b", re.I)


class Entidades(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placa: Optional[str] = None
    ubicacion: Optional[str] = None


class EsquemaIncidente(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categoria: Literal["materiales_peligrosos", "sobrepeso", "falla_hardware",
                       "acceso_no_autorizado", "otro"]
    prioridad: Literal["baja", "media", "alta", "critica"]
    entidades: Entidades
    resumen: str


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t)


PALABRAS = [  # el orden define la precedencia
    ("materiales_peligrosos", "critica",
     ["quimic", "derrame", "fuga", "toxic", "inflamable", "peligros", "corrosiv",
      "acido", "hazmat", "combustible", " gas "]),
    ("acceso_no_autorizado", "alta",
     ["sin autorizacion", "no autorizado", "intruso", "forzo", "sin permiso",
      "sin registro", "clonad", "suplant"]),
    ("sobrepeso", "media",
     ["sobrepeso", "sobre peso", "exceso de peso", "bascula", "tonelad", "sobrecarga"]),
    ("falla_hardware", "media",
     ["camara", "sensor", "lector", "barrera", "no enciende", "falla", "pantalla"]),
]
URGENTE = ["urgente", "inmediat", "emergencia"]


class ClasificadorHibrido:
    def __init__(self, modelo: str = "llama3.2", timeout: int = 60, reintentos: int = 2,
                 on_evaluacion: Optional[Callable[[Dict], None]] = None):
        self.modelo = modelo
        self.timeout = timeout
        self.reintentos = reintentos
        self.on_evaluacion = on_evaluacion
        self.url_ollama = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")

    # ------------------------------------------------------------------ reglas
    def clasificar_por_reglas(self, texto: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        n = f" {normalizar(texto)} "   # espacios para palabras cortas como ' gas '
        cat, prio = "otro", "baja"
        for c, p, kws in PALABRAS:
            if any(k in n for k in kws):
                cat, prio = c, p
                break
        if cat != "otro" and any(u in n for u in URGENTE):
            prio = PRIORIDADES[min(RANGO[prio] + 1, 3)]
        m = PLACA_RE.search(texto.upper())
        u = UBIC_RE.search(texto)
        return {
            "categoria": cat, "prioridad": prio,
            "entidades": {"placa": m.group(0) if m else None,
                          "ubicacion": u.group(0) if u else None},
            "resumen": texto.strip()[:100],
            "origen": "reglas", "requiere_revision_humana": False,
            "latencia": time.perf_counter() - t0,
        }

    # ------------------------------------------------------------------ LLM
    @staticmethod
    def _prompt(texto: str, error_previo: Optional[str] = None) -> str:
        extra = (f"\nTu respuesta anterior fue inválida ({error_previo}). "
                 "Corrígela y responde SOLO el JSON.\n") if error_previo else ""
        return f"""Eres un clasificador de incidentes logísticos. Devuelve SOLO un JSON con este esquema exacto, sin texto adicional:
{{
  "categoria": "materiales_peligrosos" | "sobrepeso" | "falla_hardware" | "acceso_no_autorizado" | "otro",
  "prioridad": "baja" | "media" | "alta" | "critica",
  "entidades": {{"placa": string o null, "ubicacion": string o null}},
  "resumen": string de máximo 100 caracteres
}}
Si el texto no describe un incidente, usa categoria "otro" y prioridad "baja".{extra}
Texto: {texto}
"""

    def clasificar_llm(self, texto: str) -> Dict[str, Any]:
        """Llama a Ollama; valida con pydantic; reintenta si el JSON es inválido."""
        error, crudo, prompt, lat = None, "", "", 0.0
        intento = 0
        for intento in range(1, self.reintentos + 2):
            prompt = self._prompt(texto, error)
            payload = {"model": self.modelo, "prompt": prompt, "stream": False,
                       "format": "json", "options": {"temperature": 0}}
            t0 = time.perf_counter()
            try:
                r = requests.post(self.url_ollama, json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                lat += time.perf_counter() - t0
                error = f"Ollama no disponible: {e}"
                break
            lat += time.perf_counter() - t0
            try:
                r.raise_for_status()
                crudo = r.json().get("response", "")
                valido = EsquemaIncidente.model_validate_json(crudo)
            except requests.HTTPError as e:
                error = f"HTTP {r.status_code}: {e}"
                break
            except ValueError as e:  # JSON inválido o esquema incorrecto -> reintento
                error = str(e)[:300]
                log.warning("JSON inválido del LLM (intento %d): %s", intento, error)
                continue
            d = valido.model_dump()
            placa = (d["entidades"].get("placa") or None)
            d["entidades"]["placa"] = placa.upper() if placa else None
            return {"ok": True, **d, "prompt": prompt, "respuesta_cruda": crudo,
                    "intentos": intento, "latencia": lat}
        return {"ok": False, "error": error, "prompt": prompt, "respuesta_cruda": crudo,
                "intentos": intento, "latencia": lat}

    # ------------------------------------------------------------------ fusión
    def fusionar(self, reglas: Dict, llm: Dict) -> Dict[str, Any]:
        if not llm.get("ok"):
            res = dict(reglas)
            res.update(origen="reglas_fallback", llm_ok=False, llm_error=llm.get("error"),
                       latencia=reglas["latencia"] + llm.get("latencia", 0.0))
            return res
        discrepa = (llm["categoria"] != reglas["categoria"]
                    or llm["prioridad"] != reglas["prioridad"])
        base = llm if RANGO[llm["prioridad"]] >= RANGO[reglas["prioridad"]] else reglas
        prioridad = PRIORIDADES[max(RANGO[llm["prioridad"]], RANGO[reglas["prioridad"]])]
        ent = dict(llm["entidades"])
        for k in ("placa", "ubicacion"):
            ent[k] = ent.get(k) or reglas["entidades"].get(k)
        return {
            "categoria": base["categoria"], "prioridad": prioridad, "entidades": ent,
            "resumen": llm["resumen"] or reglas["resumen"],
            "origen": "hibrido", "requiere_revision_humana": discrepa, "llm_ok": True,
            "latencia": reglas["latencia"] + llm["latencia"],
            "prediccion_reglas": {"categoria": reglas["categoria"], "prioridad": reglas["prioridad"]},
            "prediccion_llm": {"categoria": llm["categoria"], "prioridad": llm["prioridad"]},
        }

    def registrar_evaluacion(self, llm: Dict, reglas: Dict):
        """Guarda prompt, respuesta, modelo, latencia y si coincidió con las reglas."""
        if not self.on_evaluacion:
            return
        coincide = (bool(llm.get("ok")) and llm["categoria"] == reglas["categoria"]
                    and llm["prioridad"] == reglas["prioridad"])
        try:
            self.on_evaluacion({
                "prompt": llm.get("prompt"),
                "respuesta": llm.get("respuesta_cruda") or llm.get("error"),
                "modelo": self.modelo, "latencia": round(llm.get("latencia", 0.0), 3),
                "json_valido": bool(llm.get("ok")), "intentos": llm.get("intentos"),
                "coincide_reglas": coincide,
            })
        except Exception:
            log.exception("No se pudo registrar la evaluación del LLM")

    def clasificar_hibrido(self, texto: str) -> Dict[str, Any]:
        reglas = self.clasificar_por_reglas(texto)
        llm = self.clasificar_llm(texto)
        self.registrar_evaluacion(llm, reglas)
        return self.fusionar(reglas, llm)