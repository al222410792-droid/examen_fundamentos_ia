#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de reglas (lógica proposicional)

Variables:  P autorización previa | Q exceso de peso | R materiales peligrosos
            S conductor certificado | H horario nocturno restringido
            V certificación vigente

Reglas base (se conservan):
    R1  A = P ∧ S ∧ ¬Q
    R2  E = P ∧ (R ∨ Q)

Reglas nuevas (justificación):
    R3  Vigencia: una certificación vencida (S ∧ ¬V) no basta para el acceso
        estándar; el camión se manda a inspección para verificar al conductor
        en vez de negarlo o dejarlo pasar.
    R4  Horario: materiales peligrosos en horario nocturno restringido (R ∧ H)
        no pueden ingresar (ni acceso ni inspección) hasta que termine el horario.

Resultado extendido:
    A_ext = P ∧ S ∧ V ∧ ¬Q ∧ ¬(R ∧ H)
    E_ext = P ∧ (R ∨ Q ∨ (S ∧ ¬V)) ∧ ¬(R ∧ H)

Decisión (ante la duda, seguridad):  E_ext -> INSPECCION ;  A_ext -> ACCESO ;  si no -> DENEGADO
"""
import itertools
from typing import Any, Dict, List

VARS = ("P", "Q", "R", "S", "H", "V")
NOMBRES = {
    "P": "Autorización previa", "Q": "Exceso de peso", "R": "Materiales peligrosos",
    "S": "Conductor certificado", "H": "Horario nocturno restringido", "V": "Certificación vigente",
}


def _vf(b: bool) -> str:
    return "V" if b else "F"


class MotorReglas:
    @staticmethod
    def evaluar_camion_extendido(P: bool, Q: bool, R: bool, S: bool,
                                 H: bool = False, V: bool = True) -> Dict[str, Any]:
        P, Q, R, S, H, V = map(bool, (P, Q, R, S, H, V))

        A = P and S and not Q                      # R1
        E = P and (R or Q)                         # R2
        venc = S and not V                         # R3
        bloqueo = R and H                          # R4
        A_ext = P and S and V and not Q and not bloqueo
        E_ext = P and (R or Q or venc) and not bloqueo

        pasos = [
            f"R1: A = P ∧ S ∧ ¬Q = {_vf(P)} ∧ {_vf(S)} ∧ ¬{_vf(Q)} → {_vf(A)}",
            f"R2: E = P ∧ (R ∨ Q) = {_vf(P)} ∧ ({_vf(R)} ∨ {_vf(Q)}) → {_vf(E)}",
            f"R3 (vigencia): S ∧ ¬V = {_vf(S)} ∧ ¬{_vf(V)} → {_vf(venc)}",
            f"R4 (horario): R ∧ H = {_vf(R)} ∧ {_vf(H)} → {_vf(bloqueo)}",
            f"A_ext = P ∧ S ∧ V ∧ ¬Q ∧ ¬(R ∧ H) → {_vf(A_ext)}",
            f"E_ext = P ∧ (R ∨ Q ∨ (S ∧ ¬V)) ∧ ¬(R ∧ H) → {_vf(E_ext)}",
        ]

        if E_ext:
            decision, semaforo = "INSPECCION", "amarillo"
            causas = []
            if R:
                causas.append("carga peligrosa (R)")
            if Q:
                causas.append("exceso de peso (Q)")
            if venc:
                causas.append("certificación vencida (S ∧ ¬V)")
        elif A_ext:
            decision, semaforo = "ACCESO", "verde"
            causas = ["cumple P, S y V, sin exceso de peso ni carga peligrosa en horario restringido"]
        else:
            decision, semaforo = "DENEGADO", "rojo"
            causas = []
            if not P:
                causas.append("sin autorización previa (P=F)")
            if bloqueo:
                causas.append("materiales peligrosos en horario restringido (R ∧ H)")
            if P and not S:
                causas.append("conductor sin certificación (S=F)")

        resumen = f"{decision}: " + "; ".join(causas)
        pasos.append(f"Decisión → {resumen}")

        return {
            "acceso_estandar": A,
            "inspeccion_especial": E,
            "acceso_estandar_extendido": A_ext,
            "inspeccion_especial_extendida": E_ext,
            "decision": decision,
            "semaforo": semaforo,
            "pasos": pasos,
            "resumen": resumen,
            "explicacion": " | ".join(pasos),
        }

    @staticmethod
    def generar_tabla_verdad_extendida() -> List[Dict[str, bool]]:
        filas = []
        for vals in itertools.product([True, False], repeat=len(VARS)):
            kw = dict(zip(VARS, vals))
            r = MotorReglas.evaluar_camion_extendido(**kw)
            filas.append({**kw,
                          "A": r["acceso_estandar"], "E": r["inspeccion_especial"],
                          "A_ext": r["acceso_estandar_extendido"],
                          "E_ext": r["inspeccion_especial_extendida"],
                          "decision": r["decision"]})
        return filas

    @staticmethod
    def analizar_reglas() -> List[str]:
        """Reto opcional: contradicciones, solapamientos y variables redundantes."""
        tabla = MotorReglas.generar_tabla_verdad_extendida()
        idx = {tuple(f[v] for v in VARS): f for f in tabla}
        out = []

        viol = [f for f in tabla if f["A_ext"] and not f["A"]]
        out.append(("✔" if not viol else "✖") +
                   f" A_ext ⇒ A (la extensión solo restringe): {len(viol)} violaciones.")

        ov = [f for f in tabla if f["E"] and not f["E_ext"]]
        todas = all(f["R"] and f["H"] for f in ov)
        out.append(f"ℹ E=V pero E_ext=F en {len(ov)} filas; "
                   f"{'todas' if todas else 'NO todas'} cumplen R ∧ H "
                   "(R4 prevalece sobre R2 por seguridad: no es contradicción, es una excepción).")

        ambas = [f for f in tabla if f["A_ext"] and f["E_ext"]]
        out.append(f"ℹ A_ext y E_ext son V a la vez en {len(ambas)} filas: "
                   "la decisión da prioridad a INSPECCION.")

        for i, v in enumerate(VARS):
            influye = False
            for k, f in idx.items():
                k2 = list(k)
                k2[i] = not k2[i]
                g = idx[tuple(k2)]
                if f["decision"] != g["decision"]:
                    influye = True
                    break
            out.append(f"✔ {v} ({NOMBRES[v]}) cambia la decisión en algún caso." if influye
                       else f"⚠ {v} ({NOMBRES[v]}) es redundante: nunca cambia la decisión.")

        conteo = {"ACCESO": 0, "INSPECCION": 0, "DENEGADO": 0}
        for f in tabla:
            conteo[f["decision"]] += 1
        out.append("ℹ Cobertura (64 combinaciones): " +
                   ", ".join(f"{k}={v}" for k, v in conteo.items()))
        return out