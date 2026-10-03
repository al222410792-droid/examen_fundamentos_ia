#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reportes.py - Exportación de reportes (PDF / CSV / JSON) para LogiSmart AI Suite.

Requiere:  pip install reportlab
Depende de DBManager con: obtener_accesos(n), obtener_incidentes(),
obtener_agregacion_incidentes(), obtener_riesgos()
"""

import csv
import json
import os
from datetime import datetime, date

CAMPOS_FECHA = ("fecha_registro", "timestamp", "fecha", "marca_tiempo", "creado", "created_at")


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def _serializar(o):
    """Convierte ObjectId, datetime, etc. a texto para JSON."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def _aplanar(d, prefijo=""):
    """{'premisas': {'P': True}} -> {'premisas.P': True} (para CSV)."""
    plano = {}
    for k, v in d.items():
        clave = f"{prefijo}{k}"
        if isinstance(v, dict):
            plano.update(_aplanar(v, clave + "."))
        elif isinstance(v, (list, tuple)):
            plano[clave] = "; ".join(str(x) for x in v)
        elif isinstance(v, (datetime, date)):
            plano[clave] = v.isoformat()
        else:
            plano[clave] = v
    return plano


def _fecha_doc(doc):
    for campo in CAMPOS_FECHA:
        v = doc.get(campo)
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                pass
    return None


class GeneradorReportes:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Recolección de datos (con filtro opcional de fechas)
    # ------------------------------------------------------------------
    def recolectar(self, desde=None, hasta=None):
        """desde/hasta: datetime o None. Devuelve dict con todos los datasets."""
        def filtrar(docs):
            if not desde and not hasta:
                return docs
            salida = []
            for d in docs:
                f = _fecha_doc(d)
                if f is None:           # sin fecha: se conserva
                    salida.append(d)
                    continue
                if desde and f < desde:
                    continue
                if hasta and f > hasta:
                    continue
                salida.append(d)
            return salida

        accesos = filtrar(list(self.db.obtener_accesos(1000) or []))
        incidentes = filtrar(list(self.db.obtener_incidentes() or []))
        riesgos = list(self.db.obtener_riesgos() or [])
        agregacion = []
        for item in (self.db.obtener_agregacion_incidentes(desde, hasta) or []):
            _id = item.get("_id", {})
            agregacion.append({
                "categoria": _id.get("categoria", "N/A"),
                "semana": _id.get("semana", "N/A"),
                "total": item.get("total", 0),
            })

        return {
            "meta": {
                "generado": datetime.now().isoformat(timespec="seconds"),
                "desde": desde.isoformat() if desde else None,
                "hasta": hasta.isoformat() if hasta else None,
                "total_accesos": len(accesos),
                "total_incidentes": len(incidentes),
                "total_riesgos": len(riesgos),
            },
            "accesos": accesos,
            "incidentes": incidentes,
            "riesgos_eticos": riesgos,
            "agregacion_incidentes": agregacion,
        }

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------
    def exportar_json(self, ruta, desde=None, hasta=None):
        datos = self.recolectar(desde, hasta)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, default=_serializar)
        return ruta

    # ------------------------------------------------------------------
    # CSV (un archivo por dataset dentro de una carpeta)
    # ------------------------------------------------------------------
    def exportar_csv(self, carpeta, desde=None, hasta=None):
        datos = self.recolectar(desde, hasta)
        os.makedirs(carpeta, exist_ok=True)
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        generados = []

        for nombre in ("accesos", "incidentes", "riesgos_eticos", "agregacion_incidentes"):
            filas = [_aplanar(d) for d in datos[nombre]]
            ruta = os.path.join(carpeta, f"{nombre}_{sello}.csv")
            columnas = []
            for fila in filas:
                for k in fila:
                    if k not in columnas:
                        columnas.append(k)
            # utf-8-sig para que Excel abra bien los acentos
            with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columnas or ["sin_datos"], extrasaction="ignore")
                w.writeheader()
                for fila in filas:
                    w.writerow(fila)
            generados.append(ruta)
        return generados

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------
    def exportar_pdf(self, ruta, desde=None, hasta=None):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                            Table, TableStyle, PageBreak)
        except ImportError as e:
            raise RuntimeError("Falta reportlab. Instala con: pip install reportlab") from e

        datos = self.recolectar(desde, hasta)
        styles = getSampleStyleSheet()
        celda = styles["BodyText"]
        celda.fontSize = 7
        celda.leading = 9

        def esc(x):
            s = str(x if x is not None else "")
            # Helvetica no tiene glifos de lógica/flechas: se pasan a texto ASCII
            for a, b in (("∧", " AND "), ("∨", " OR "), ("¬", "NOT "), ("→", "=>"), ("⇒", "=>")):
                s = s.replace(a, b)
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def tabla(encabezados, filas, anchos=None):
            data = [[Paragraph(f"<b>{esc(h)}</b>", celda) for h in encabezados]]
            for fila in filas:
                data.append([Paragraph(esc(c), celda) for c in fila])
            t = Table(data, colWidths=anchos, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D6A4F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F0F7F4")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            return t

        doc = SimpleDocTemplate(ruta, pagesize=landscape(letter),
                                leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                                topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                                title="Reporte LogiSmart AI")
        S = []
        m = datos["meta"]
        S.append(Paragraph("Reporte LogiSmart AI Suite", styles["Title"]))
        rango = f"{m['desde'] or 'inicio'}  a  {m['hasta'] or 'hoy'}"
        S.append(Paragraph(f"Generado: {m['generado']} &nbsp;|&nbsp; Periodo: {esc(rango)}", styles["Normal"]))
        S.append(Spacer(1, 10))
        S.append(tabla(["Indicador", "Valor"], [
            ["Registros de acceso", m["total_accesos"]],
            ["Incidentes", m["total_incidentes"]],
            ["Riesgos éticos", m["total_riesgos"]],
        ], anchos=[8 * cm, 4 * cm]))

        # Accesos
        S.append(Spacer(1, 14))
        S.append(Paragraph("Control de acceso", styles["Heading2"]))
        filas = []
        for a in datos["accesos"][:200]:
            p = a.get("premisas", {})
            prem = " ".join(f"{k}={'V' if v else 'F'}" for k, v in p.items())
            filas.append([a.get("placa", ""), prem,
                          "V" if a.get("resultado_A_ext") else "F",
                          "V" if a.get("resultado_E_ext") else "F",
                          a.get("explicacion", "")])
        S.append(tabla(["Placa", "Premisas", "A", "E", "Explicación"], filas,
                       anchos=[3 * cm, 5 * cm, 1 * cm, 1 * cm, 14 * cm]) if filas
                 else Paragraph("Sin registros.", styles["Normal"]))

        # Incidentes
        S.append(PageBreak())
        S.append(Paragraph("Incidentes por categoría y semana", styles["Heading2"]))
        filas = [[x["categoria"], f"Semana {x['semana']}", x["total"]]
                 for x in datos["agregacion_incidentes"]]
        S.append(tabla(["Categoría", "Semana", "Total"], filas,
                       anchos=[8 * cm, 4 * cm, 3 * cm]) if filas
                 else Paragraph("Sin datos.", styles["Normal"]))

        S.append(Spacer(1, 14))
        S.append(Paragraph("Detalle de incidentes", styles["Heading2"]))
        filas = []
        for i in datos["incidentes"][:200]:
            filas.append([i.get("categoria", ""), i.get("prioridad", ""),
                          i.get("estado", ""), i.get("origen", ""),
                          str(i.get("correo_original", i.get("texto", "")))[:160]])
        S.append(tabla(["Categoría", "Prioridad", "Estado", "Origen", "Texto"], filas,
                       anchos=[3.5 * cm, 2.5 * cm, 2.5 * cm, 3 * cm, 13 * cm]) if filas
                 else Paragraph("Sin incidentes.", styles["Normal"]))

        # Riesgos
        S.append(PageBreak())
        S.append(Paragraph("Matriz de riesgos éticos", styles["Heading2"]))
        filas = []
        for r in datos["riesgos_eticos"]:
            pi, pm = r.get("prob_inicial", ""), r.get("prob_mitigada", "")
            filas.append([r.get("descripcion", ""),
                          r.get("puntaje_inicial", pi), r.get("puntaje_residual", pm),
                          r.get("mitigacion", "")])
        S.append(tabla(["Riesgo", "Puntaje inicial", "Puntaje residual", "Mitigación"], filas,
                       anchos=[8 * cm, 2 * cm, 2 * cm, 12 * cm]) if filas
                 else Paragraph("Sin riesgos registrados.", styles["Normal"]))

        doc.build(S)
        return ruta