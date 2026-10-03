#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    from pymongo import MongoClient
    from bson import ObjectId
    from bson.errors import InvalidId
except ImportError:  # sin pymongo: solo modo memoria
    MongoClient = None
    ObjectId = None
    InvalidId = Exception

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("db_manager")

COLECCIONES = ("camiones", "accesos", "incidentes", "riesgos_eticos",
               "evaluaciones_llm", "chat_historial")

RIESGOS_BASE = [
    {"modulo": "Clasificador LLM", "descripcion": "Alucinación del LLM",
     "categoria": "Fiabilidad", "prob_inicial": 4, "impacto_inicial": 4,
     "prob_mitigada": 2, "impacto_mitigado": 3,
     "mitigacion": "Salida JSON validada con pydantic, reintentos, respaldo por reglas y revisión humana ante discrepancias."},
    {"modulo": "Clasificador LLM", "descripcion": "Sesgo con ortografía informal",
     "categoria": "Equidad", "prob_inicial": 4, "impacto_inicial": 3,
     "prob_mitigada": 2, "impacto_mitigado": 2,
     "mitigacion": "Normalizar texto, evaluar con correos informales y fusionar con reglas (prevalece la prioridad más alta)."},
    {"modulo": "Control de acceso", "descripcion": "Privacidad de datos del conductor",
     "categoria": "Privacidad", "prob_inicial": 3, "impacto_inicial": 5,
     "prob_mitigada": 2, "impacto_mitigado": 3,
     "mitigacion": "LLM local (Ollama), datos mínimos, credenciales por variables de entorno y acceso restringido a Atlas."},
    {"modulo": "Operación", "descripcion": "Dependencia excesiva de la automatización",
     "categoria": "Humano en el bucle", "prob_inicial": 3, "impacto_inicial": 4,
     "prob_mitigada": 2, "impacto_mitigado": 2,
     "mitigacion": "Bandera requiere_revision_humana, decisiones críticas confirmadas por el operador y bitácora de accesos."},
]


# ---------------------------------------------------------------------------
# Utilidades para el respaldo en memoria (imitan filtros simples de Mongo)
# ---------------------------------------------------------------------------
def _get(doc: Any, ruta: str) -> Any:
    for p in ruta.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(p)
    return doc


def _coincide(doc: Dict, filtro: Optional[Dict]) -> bool:
    for k, cond in (filtro or {}).items():
        v = _get(doc, k)
        if isinstance(cond, dict):
            try:
                if "$gte" in cond and (v is None or v < cond["$gte"]):
                    return False
                if "$lte" in cond and (v is None or v > cond["$lte"]):
                    return False
            except TypeError:
                return False
            if "$ne" in cond and v == cond["$ne"]:
                return False
        elif v != cond:
            return False
    return True


class DBManager:
    def __init__(self, uri: str = None, db_name: str = None):
        self.db_name = db_name or os.getenv("MONGO_DB", "Edith")
        self.client = None
        self.db = None
        self.conectado = False
        self.ultimo_error = ""
        self.mem: Dict[str, List[Dict]] = {c: [] for c in COLECCIONES}
        self._uri = uri or self._construir_uri()
        self.conectar()
        self._sembrar_riesgos()

    # ------------------------------------------------------------------ conexión
    @staticmethod
    def _construir_uri() -> Optional[str]:
        uri = os.getenv("MONGO_URI")
        if uri:
            return uri
        u, p, c = os.getenv("MONGO_USER"), os.getenv("MONGO_PASSWORD"), os.getenv("MONGO_CLUSTER")
        if u and p and c:
            return f"mongodb+srv://{quote_plus(u)}:{quote_plus(p)}@{c}/?retryWrites=true&w=majority"
        return None

    def conectar(self) -> bool:
        if MongoClient is None:
            self.ultimo_error = "pymongo no está instalado (pip install pymongo)."
            self.conectado = False
            return False
        if not self._uri:
            self.ultimo_error = ("Sin credenciales: define MONGO_URI o "
                                 "MONGO_USER / MONGO_PASSWORD / MONGO_CLUSTER.")
            self.conectado = False
            return False
        try:
            self.client = MongoClient(self._uri, serverSelectionTimeoutMS=3000)
            self.client.admin.command("ping")
            self.db = self.client[self.db_name]
            self.conectado = True
            self.ultimo_error = ""
            log.info("Conexión exitosa a MongoDB (%s)", self.db_name)
            return True
        except Exception as e:
            self.conectado = False
            self.ultimo_error = str(e)
            log.warning("No se pudo conectar a MongoDB; modo memoria: %s", e)
            return False

    def reconectar(self) -> bool:
        ok = self.conectar()
        if ok:
            self._sembrar_riesgos()
        return ok

    def esta_conectado(self) -> bool:
        return self.conectado

    def _fallo(self, e: Exception):
        log.error("Error de MongoDB, cambiando a modo local: %s", e)
        self.conectado = False
        self.ultimo_error = str(e)

    @staticmethod
    def _oid(_id):
        if ObjectId is None:
            return _id
        try:
            return ObjectId(_id)
        except (InvalidId, TypeError):
            return _id

    @staticmethod
    def _norm(d: Dict) -> Dict:
        d = dict(d)
        if "_id" in d:
            d["_id"] = str(d["_id"])
        return d

    # ------------------------------------------------------------------ CRUD genérico
    def insertar(self, col: str, doc: Dict[str, Any]) -> str:
        doc = dict(doc)
        doc.setdefault("fecha_registro", datetime.now())
        if self.conectado:
            try:
                return str(self.db[col].insert_one(doc).inserted_id)
            except Exception as e:
                self._fallo(e)
        doc["_id"] = uuid.uuid4().hex[:24]
        self.mem[col].append(doc)
        return doc["_id"]

    def listar(self, col: str, filtro: Optional[Dict] = None, limite: int = 0,
               orden: Optional[Tuple[str, int]] = None) -> List[Dict]:
        if self.conectado:
            try:
                cur = self.db[col].find(filtro or {})
                if orden:
                    cur = cur.sort(orden[0], orden[1])
                if limite:
                    cur = cur.limit(limite)
                return [self._norm(d) for d in cur]
            except Exception as e:
                self._fallo(e)
        docs = [dict(d) for d in self.mem[col] if _coincide(d, filtro)]
        if orden:
            docs.sort(key=lambda d: (_get(d, orden[0]) is None, _get(d, orden[0])),
                      reverse=(orden[1] == -1))
        return docs[:limite] if limite else docs

    def actualizar(self, col: str, _id: str, cambios: Optional[Dict] = None,
                   push: Optional[Dict] = None) -> bool:
        """cambios -> $set ; push -> $push (agrega elementos a listas, p. ej. historial)."""
        if self.conectado:
            try:
                op = {}
                if cambios:
                    op["$set"] = cambios
                if push:
                    op["$push"] = push
                if not op:
                    return False
                return self.db[col].update_one({"_id": self._oid(_id)}, op).matched_count > 0
            except Exception as e:
                self._fallo(e)
        for d in self.mem[col]:
            if d["_id"] == _id:
                d.update(cambios or {})
                for k, v in (push or {}).items():
                    d.setdefault(k, []).append(v)
                return True
        return False

    def eliminar(self, col: str, _id: str) -> bool:
        if self.conectado:
            try:
                return self.db[col].delete_one({"_id": self._oid(_id)}).deleted_count > 0
            except Exception as e:
                self._fallo(e)
        antes = len(self.mem[col])
        self.mem[col] = [d for d in self.mem[col] if d["_id"] != _id]
        return len(self.mem[col]) < antes

    # ------------------------------------------------------------------ atajos
    @staticmethod
    def filtro_fecha(desde: Optional[datetime], hasta: Optional[datetime],
                     campo: str = "fecha_registro") -> Optional[Dict]:
        r = {}
        if desde:
            r["$gte"] = desde
        if hasta:
            r["$lte"] = hasta
        return {campo: r} if r else None

    def registrar_acceso(self, datos: Dict[str, Any]) -> str:
        return self.insertar("accesos", datos)

    def obtener_accesos(self, limite: int = 100, filtro: Optional[Dict] = None):
        return self.listar("accesos", filtro, limite, ("fecha_registro", -1))

    def guardar_incidente(self, datos: Dict[str, Any]) -> str:
        return self.insertar("incidentes", datos)

    def obtener_incidentes(self, filtro: Optional[Dict] = None):
        return self.listar("incidentes", filtro, 0, ("fecha_registro", -1))

    def obtener_riesgos(self):
        return self.listar("riesgos_eticos", orden=("fecha_registro", 1))

    def buscar_camion(self, placa: str) -> Optional[Dict]:
        r = self.listar("camiones", {"placa": placa.upper()}, 1)
        return r[0] if r else None

    # ------------------------------------------------------------------ agregación
    def obtener_agregacion_incidentes(self, desde=None, hasta=None) -> List[Dict]:
        """Incidentes por categoría y semana ISO. Devuelve [{'_id': {'categoria','semana'}, 'total'}]."""
        filtro = self.filtro_fecha(desde, hasta)
        if self.conectado:
            try:
                pipeline = []
                if filtro:
                    pipeline.append({"$match": filtro})
                pipeline += [
                    {"$group": {
                        "_id": {
                            "categoria": "$categoria",
                            "semana": {"$isoWeek": {"$convert": {
                                "input": "$fecha_registro", "to": "date",
                                "onError": None, "onNull": None}}},
                        },
                        "total": {"$sum": 1}}},
                    {"$sort": {"_id.semana": -1, "total": -1}},
                ]
                res = list(self.db.incidentes.aggregate(pipeline))
                for r in res:
                    r["_id"]["semana"] = r["_id"].get("semana") or "N/A"
                    r["_id"]["categoria"] = r["_id"].get("categoria") or "sin_categoria"
                return res
            except Exception as e:
                self._fallo(e)
        cont: Dict[Tuple, int] = {}
        for d in self.listar("incidentes", filtro):
            f = d.get("fecha_registro")
            sem = f.isocalendar()[1] if isinstance(f, datetime) else "N/A"
            k = (d.get("categoria", "otro"), sem)
            cont[k] = cont.get(k, 0) + 1
        return [{"_id": {"categoria": k[0], "semana": k[1]}, "total": v}
                for k, v in sorted(cont.items(), key=lambda kv: (str(kv[0][1]), kv[0][0]), reverse=True)]

    # ------------------------------------------------------------------ semillas
    def _sembrar_riesgos(self):
        if self.listar("riesgos_eticos", limite=1):
            return
        for r in RIESGOS_BASE:
            doc = dict(r)
            doc["puntaje_inicial"] = doc["prob_inicial"] * doc["impacto_inicial"]
            doc["puntaje_residual"] = doc["prob_mitigada"] * doc["impacto_mitigado"]
            doc["historico"] = [{"fecha": datetime.now(),
                                 "prob_inicial": doc["prob_inicial"], "impacto_inicial": doc["impacto_inicial"],
                                 "prob_mitigada": doc["prob_mitigada"], "impacto_mitigado": doc["impacto_mitigado"],
                                 "puntaje_inicial": doc["puntaje_inicial"],
                                 "puntaje_residual": doc["puntaje_residual"]}]
            self.insertar("riesgos_eticos", doc)