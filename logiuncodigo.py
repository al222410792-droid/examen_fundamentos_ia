#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 LogiSmart AI Suite - Dashboard modular (Dark/Light)
 Páginas: Dashboard, Control de Acceso, Camiones, Simulador, Incidentes,
          Asistente RAG, Riesgos Éticos, Reportes, Configuración/Evaluación
==============================================================================
"""
import json
import logging
import os
import queue
import random
import re
import textwrap
import threading
import urllib.request
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import evaluacion
from asistente_rag import AsistenteRAG
from clasificador_hibrido import ClasificadorHibrido, CATEGORIAS, PRIORIDADES
from db_manager import DBManager
from motor_reglas import MotorReglas, VARS, NOMBRES
from reportes import GeneradorReportes

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
PLACA_OK = re.compile(r"^[A-Z0-9-]{3,12}$")
ESTADOS = ["nuevo", "en_atencion", "cerrado"]
CATEGORIAS_RIESGO = ["Fiabilidad", "Equidad", "Privacidad", "Seguridad", "Humano en el bucle", "Otro"]
CONFIG_FILE = "config_logismart.json"
CONFIG_DEFAULT = {
    "modelo_ollama": "llama3.2", "timeout_llm": 60, "reintentos": 2,
    "umbral_prioridad_moderada": 3, "umbral_prioridad_critica": 6,
    "umbral_riesgo_critico": 12, "modo_simulacion_correo": False,
    "operador": "Edith Villanueva",
}

THEMES = {
    "dark": {
        "bg_app": "#121316", "sidebar_bg": "#1A1C20", "card_bg": "#22252A", "card_border": "#2E3239",
        "text_light": "#F2F3F5", "text_muted": "#8A8F98", "accent_blue": "#00A2FF",
        "accent_green": "#23A55A", "accent_pill": "#181A1D", "table_head_bg": "#2A2D34",
        "table_head_fg": "#F2F3F5", "table_row_alt": "#1D1F24", "chart_bg": "#22252A",
        "warn": "#FF9800", "danger": "#FF5252",
    },
    "light": {
        "bg_app": "#F4F5F8", "sidebar_bg": "#FFFFFF", "card_bg": "#FFFFFF", "card_border": "#E1E4EA",
        "text_light": "#1B4332", "text_muted": "#2D6A4F", "accent_blue": "#007AFF",
        "accent_green": "#10B981", "accent_pill": "#E8F5E9", "table_head_bg": "#2D6A4F",
        "table_head_fg": "#FFFFFF", "table_row_alt": "#F0F7F4", "chart_bg": "#FFFFFF",
        "warn": "#E65100", "danger": "#D32F2F",
    },
}


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def cargar_config():
    cfg = dict(CONFIG_DEFAULT)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def guardar_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def fmt_fecha(v):
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else str(v or "")


def puntaje_inicial(r):
    return r.get("prob_inicial", 1) * r.get("impacto_inicial", 1)


def puntaje_residual(r):
    return r.get("prob_mitigada", 1) * r.get("impacto_mitigado", 1)


def parse_rango(txt_desde, txt_hasta):
    def p(t, fin=False):
        t = t.strip()
        if not t:
            return None
        try:
            d = datetime.strptime(t, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Fecha inválida '{t}'. Usa el formato AAAA-MM-DD.")
        return d.replace(hour=23, minute=59, second=59) if fin else d
    d, h = p(txt_desde), p(txt_hasta, True)
    if d and h and d > h:
        raise ValueError("La fecha inicial no puede ser posterior a la final.")
    return d, h


# ----------------------------------------------------------------------------
# Tarjetas
# ----------------------------------------------------------------------------
class RoundedCard(tk.Canvas):
    def __init__(self, parent, theme_colors, radius=16, **kwargs):
        super().__init__(parent, bg=theme_colors["bg_app"], highlightthickness=0, **kwargs)
        self.colors = theme_colors
        self.radius = radius
        self.bind("<Configure>", self._draw)

    def set_theme(self, theme_colors):
        self.colors = theme_colors
        self.configure(bg=self.colors["bg_app"])
        self._draw()

    def _draw(self, event=None):
        self.delete("card_bg")
        w, h, r = self.winfo_width(), self.winfo_height(), self.radius
        if w > 2 * r and h > 2 * r:
            self.create_round_rect(2, 2, w - 2, h - 2, r, fill=self.colors["card_bg"],
                                   outline=self.colors["card_border"], width=1, tag="card_bg")
            self.tag_lower("card_bg")

    def create_round_rect(self, x1, y1, x2, y2, radius=20, **kw):
        pts = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
               x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)


class MetricCard(RoundedCard):
    def __init__(self, parent, theme_colors, title, value="0", unit="", color_key="accent_blue", **kw):
        super().__init__(parent, theme_colors, **kw)
        self.color_key = color_key
        c = self.colors
        self.lbl_title = tk.Label(self, text=title.upper(), font=("Segoe UI", 9, "bold"),
                                  bg=c["card_bg"], fg=c["text_muted"])
        self.lbl_title.place(x=20, y=14)
        self.lbl_val = tk.Label(self, text=value, font=("Segoe UI", 26, "bold"),
                                bg=c["card_bg"], fg=c[color_key])
        self.lbl_val.place(x=20, y=38)
        self.lbl_unit = tk.Label(self, text=unit, font=("Segoe UI", 9),
                                 bg=c["card_bg"], fg=c["text_muted"])
        self.lbl_unit.place(x=20, y=88)

    def set_theme(self, theme_colors):
        super().set_theme(theme_colors)
        c = self.colors
        self.lbl_title.config(bg=c["card_bg"], fg=c["text_muted"])
        self.lbl_val.config(bg=c["card_bg"], fg=c[self.color_key])
        self.lbl_unit.config(bg=c["card_bg"], fg=c["text_muted"])

    def set_value(self, v):
        self.lbl_val.config(text=str(v))


# ----------------------------------------------------------------------------
# Panel CRUD genérico (tabla + formulario + Nuevo/Guardar/Eliminar)
# ----------------------------------------------------------------------------
class FormCrud:
    def __init__(self, gui, parent, coleccion, campos, columnas, tree_h=7,
                 validar=None, preparar=None, tras_cambio=None):
        self.g, self.col, self.campos = gui, coleccion, campos
        self.validar, self.preparar, self.tras_cambio = validar, preparar, tras_cambio
        self.sel, self.docs, self.w, self.columnas = None, {}, {}, columnas
        g = gui

        ft = g.F(parent)
        ft.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(ft, columns=[c[0] for c in columnas], show="headings",
                                 height=tree_h, selectmode="browse")
        for cid, head, ancho, _ in columnas:
            self.tree.heading(cid, text=head)
            self.tree.column(cid, width=ancho, anchor="w")
        sb = ttk.Scrollbar(ft, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        g.trees.append(self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = g.F(parent)
        form.pack(fill="x", pady=(10, 0))
        fila = col = 0
        for f in campos:
            k, t = f["k"], f["t"]
            if f.get("span") and col != 0:
                fila, col = fila + 1, 0
            if t == "bool":
                var = tk.BooleanVar(value=f.get("def", False))
                g.CK(form, f["et"], var).grid(row=fila, column=col * 2 + 1, sticky="w", pady=3)
                self.w[k] = var
            else:
                g.L(form, f["et"] + ":", font=FONT_B).grid(row=fila, column=col * 2, sticky="w", padx=(0, 8), pady=3)
                if t == "text":
                    w = g.E(form, width=f.get("w", 24))
                elif t == "int":
                    lo, hi = f.get("rng", (1, 5))
                    w = tk.Spinbox(form, from_=lo, to=hi, width=5, font=("Segoe UI", 11), relief="flat", bd=0)
                    g._reg(w, "input")
                else:
                    w = g.CB(form, f["op"], f.get("w", 22))
                w.grid(row=fila, column=col * 2 + 1, sticky="w", pady=3, padx=(0, 25),
                       columnspan=3 if f.get("span") else 1, ipady=3 if t != "combo" else 0)
                self.w[k] = w
            if f.get("span"):
                fila, col = fila + 1, 0
            else:
                col += 1
                if col == 2:
                    fila, col = fila + 1, 0

        fb = g.F(parent)
        fb.pack(fill="x", pady=(10, 0))
        g.B(fb, "✚ Nuevo", self.nuevo, "btn_sec").pack(side="left", padx=(0, 8))
        g.B(fb, "💾 Guardar", self.guardar).pack(side="left", padx=(0, 8))
        g.B(fb, "🗑 Eliminar", self.eliminar, "btn_danger").pack(side="left")
        self.nuevo()

    # --- lectura / escritura del formulario
    def _leer(self):
        datos = {}
        for f in self.campos:
            k, t, w = f["k"], f["t"], self.w[f["k"]]
            if t == "text":
                v = w.get().strip()
                v = v.upper() if f.get("mayus") else v
            elif t == "bool":
                v = bool(w.get())
            elif t == "int":
                lo, hi = f.get("rng", (1, 5))
                try:
                    v = int(w.get())
                except ValueError:
                    raise ValueError(f"'{f['et']}' debe ser un entero entre {lo} y {hi}.")
                if not lo <= v <= hi:
                    raise ValueError(f"'{f['et']}' debe estar entre {lo} y {hi}.")
            else:
                v = w.get()
            datos[k] = v
        return datos

    def _poner(self, f, val):
        w, t = self.w[f["k"]], f["t"]
        if t == "bool":
            w.set(bool(val))
        elif t == "combo":
            w.set(val if val is not None else "")
        else:
            w.delete(0, "end")
            w.insert(0, "" if val is None else val)

    def nuevo(self):
        self.sel = None
        if self.tree.selection():
            self.tree.selection_remove(*self.tree.selection())
        for f in self.campos:
            self._poner(f, f.get("def", ""))

    def _on_select(self, _):
        s = self.tree.selection()
        if not s:
            return
        self.sel = s[0]
        d = self.docs.get(self.sel, {})
        for f in self.campos:
            self._poner(f, d.get(f["k"], f.get("def", "")))

    def refrescar(self):
        self.docs = {}
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, d in enumerate(self.g.db.listar(self.col, orden=("fecha_registro", -1))):
            self.docs[d["_id"]] = d
            self.tree.insert("", "end", iid=d["_id"], values=[c[3](d) for c in self.columnas],
                             tags=("even" if idx % 2 == 0 else "odd",))
        self.g.estilo_tags(self.tree)
        self.g.actualizar_estado_db()

    def guardar(self):
        try:
            datos = self._leer()
        except ValueError as e:
            messagebox.showwarning("Validación", str(e))
            return
        if self.validar:
            err = self.validar(datos, self.sel)
            if err:
                messagebox.showwarning("Validación", err)
                return
        push = None
        if self.preparar:
            datos, push = self.preparar(datos, self.docs.get(self.sel))
        if self.sel:
            ok = self.g.db.actualizar(self.col, self.sel, datos, push)
            if not ok:
                messagebox.showerror("Error", "No se pudo actualizar el registro (¿conexión perdida?).")
        else:
            if push:
                datos.update({k: [v] for k, v in push.items()})
            self.g.db.insertar(self.col, datos)
        self.refrescar()
        self.nuevo()
        if self.tras_cambio:
            self.tras_cambio()

    def eliminar(self):
        if not self.sel:
            messagebox.showinfo("Eliminar", "Selecciona un registro de la tabla.")
            return
        if messagebox.askyesno("Confirmar", "¿Eliminar el registro seleccionado? No se puede deshacer."):
            self.g.db.eliminar(self.col, self.sel)
            self.refrescar()
            self.nuevo()
            if self.tras_cambio:
                self.tras_cambio()


# ----------------------------------------------------------------------------
# Aplicación
# ----------------------------------------------------------------------------
class LogiSmartGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("LogiSmart Management — AI Dashboard")
        root.geometry("1300x860")
        root.minsize(1100, 720)

        self.cfg = cargar_config()
        self.current_theme_name = "dark"
        self.colors = THEMES["dark"]
        root.configure(bg=self.colors["bg_app"])

        self.db = DBManager()
        self.clasificador = ClasificadorHibrido(
            self.cfg["modelo_ollama"], self.cfg["timeout_llm"], self.cfg["reintentos"],
            on_evaluacion=lambda d: self.db.insertar("evaluaciones_llm", d))
        self.asistente = AsistenteRAG(self.db, self.cfg["modelo_ollama"], self.cfg["timeout_llm"])
        self.reportes = GeneradorReportes(self.db)

        self.paginas, self.botones_nav, self.cards_list = {}, {}, []
        self.themed, self.trees, self.estado_sem = [], [], {}
        self.pagina_actual = "dashboard"
        self.filtro_placa = None
        self.inc_sel, self.inc_docs, self.ultimo_clasif = None, {}, None
        self.acc_docs = {}
        self._eval_corriendo = False
        self._eval_estado = {"i": 0, "n": len(evaluacion.DATASET)}
        self.modelos_ollama = []

        self.construir_layout_principal()
        self.aplicar_config()
        if not self.db.esta_conectado():
            root.after(600, lambda: messagebox.showwarning(
                "MongoDB no disponible",
                "No se pudo conectar a MongoDB. La app trabaja en MODO LOCAL "
                "(los datos se pierden al cerrar).\n\nDetalle: " + self.db.ultimo_error))

    # ------------------------------------------------------------------ fábrica de widgets
    def _reg(self, w, rol):
        self.themed.append((w, rol))
        self._estilizar(w, rol)
        return w

    def _estilizar(self, w, rol):
        c = self.colors
        cfg = {
            "app": dict(bg=c["bg_app"]),
            "card": dict(bg=c["card_bg"]),
            "pill": dict(bg=c["accent_pill"]),
            "sidebar": dict(bg=c["sidebar_bg"]),
            "sidebar_text": dict(bg=c["sidebar_bg"], fg=c["text_light"]),
            "titulo": dict(bg=c["bg_app"], fg=c["text_light"]),
            "texto": dict(bg=c["card_bg"], fg=c["text_light"]),
            "muted": dict(bg=c["card_bg"], fg=c["text_muted"]),
            "dyn": dict(bg=c["card_bg"]),
            "dynpill": dict(bg=c["accent_pill"]),
            "pilltext": dict(bg=c["accent_pill"], fg=c["text_light"]),
            "input": dict(bg=c["accent_pill"], fg=c["text_light"], insertbackground=c["text_light"]),
            "check": dict(bg=c["card_bg"], fg=c["text_light"], activebackground=c["card_bg"],
                          activeforeground=c["text_light"], selectcolor=c["accent_pill"]),
            "btn": dict(bg=c["accent_blue"], fg="#FFFFFF", activebackground=c["accent_blue"], activeforeground="#FFFFFF"),
            "btn_sec": dict(bg=c["accent_pill"], fg=c["text_light"], activebackground=c["card_border"],
                            activeforeground=c["text_light"]),
            "btn_danger": dict(bg=c["danger"], fg="#FFFFFF", activebackground=c["danger"], activeforeground="#FFFFFF"),
        }[rol]
        try:
            w.configure(**cfg)
        except tk.TclError:
            pass

    def L(self, parent, text, rol="texto", font=FONT, **kw):
        return self._reg(tk.Label(parent, text=text, font=font, **kw), rol)

    def B(self, parent, text, cmd, rol="btn", **kw):
        kw.setdefault("pady", 8)
        return self._reg(tk.Button(parent, text=text, command=cmd, font=FONT_B, relief="flat", bd=0,
                                   padx=16, cursor="hand2", **kw), rol)

    def E(self, parent, **kw):
        return self._reg(tk.Entry(parent, font=("Segoe UI", 11), relief="flat", bd=0, **kw), "input")

    def T(self, parent, **kw):
        kw.setdefault("padx", 10)
        kw.setdefault("pady", 8)
        return self._reg(tk.Text(parent, font=FONT, relief="flat", bd=0, wrap="word", **kw), "input")

    def F(self, parent, rol="card", **kw):
        return self._reg(tk.Frame(parent, **kw), rol)

    def CK(self, parent, text, var, cmd=None):
        return self._reg(tk.Checkbutton(parent, text=text, variable=var, command=cmd, font=FONT, anchor="w"), "check")

    def CB(self, parent, values, width=22, state="readonly"):
        return ttk.Combobox(parent, values=values, width=width, state=state, font=FONT)

    def barra(self, parent):
        b = ttk.Progressbar(parent, mode="indeterminate")
        b.pack(fill="x", pady=4)
        return b

    @staticmethod
    def _set_text(tw, s):
        tw.config(state="normal")
        tw.delete("1.0", "end")
        tw.insert("end", s)
        tw.config(state="disabled")

    def run_async(self, fn, on_ok, on_err=None):
        """Ejecuta fn en un hilo (LLM / disco / red) sin congelar la GUI."""
        q = queue.Queue()

        def work():
            try:
                q.put(("ok", fn()))
            except Exception as e:  # noqa
                q.put(("err", e))
        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                estado, val = q.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            if estado == "ok":
                on_ok(val)
            else:
                (on_err or self._error_generico)(val)
        self.root.after(100, poll)

    def _error_generico(self, e):
        logging.exception("Error en tarea asíncrona", exc_info=e)
        messagebox.showerror("Error", f"Ocurrió un problema:\n{e}")

    # ------------------------------------------------------------------ layout
    def construir_layout_principal(self):
        self.sidebar = self.F(self.root, "sidebar", width=250)
        self.sidebar.pack(side="left", fill="y", padx=(15, 10), pady=15)
        self.sidebar.pack_propagate(False)

        self.lbl_brand = self.L(self.sidebar, "⚡ LogiSmart AI", "sidebar_text", ("Segoe UI", 16, "bold"))
        self.lbl_brand.pack(anchor="w", padx=20, pady=(18, 12))

        self.btn_theme = self.B(self.sidebar, "🌙 Modo Oscuro", self.toggle_theme, "btn_sec", pady=6)
        self.btn_theme.pack(fill="x", padx=15, pady=(0, 10))

        opciones = [("dashboard", "📊 Dashboard"), ("acceso", "🚛 Control Acceso"), ("camiones", "🚚 Camiones"),
                    ("simulador", "⚡ Simulador"), ("incidentes", "📥 Incidentes"), ("chat", "💬 Asistente RAG"),
                    ("riesgos", "🛡️ Riesgos Éticos"), ("reportes", "📄 Reportes"), ("config", "⚙️ Configuración")]
        for key, label in opciones:
            b = tk.Button(self.sidebar, text=label, font=FONT_B, anchor="w", relief="flat", bd=0,
                          padx=18, pady=7, cursor="hand2", command=lambda k=key: self.cambiar_pagina(k))
            b.pack(fill="x", padx=12, pady=2)
            self.botones_nav[key] = b

        # estado (abajo)
        self.frame_user = self.F(self.sidebar, "pill")
        self.frame_user.pack(side="bottom", fill="x", padx=12, pady=12)
        self.lbl_user = self.L(self.frame_user, self.cfg["operador"], "pilltext", ("Segoe UI", 9, "bold"))
        self.lbl_user.pack(anchor="w", padx=12, pady=(10, 2))
        self.lbl_st = self.L(self.frame_user, "", "dynpill", ("Segoe UI", 8, "bold"))
        self.lbl_st.pack(anchor="w", padx=12, pady=(0, 2))
        self.lbl_ollama_st = self.L(self.frame_user, "● Verificando Ollama...", "dynpill", ("Segoe UI", 8, "bold"),
                                    fg=self.colors["text_muted"])
        self.lbl_ollama_st.pack(anchor="w", padx=12, pady=(0, 10))
        self.actualizar_estado_db()

        self.container = self.F(self.root, "app")
        self.container.pack(side="right", fill="both", expand=True, padx=(0, 15), pady=15)

        for key in self.botones_nav:
            self.paginas[key] = self.F(self.container, "app")
        self.aplicar_estilos_tabla()
        self.ui_dashboard()
        self.ui_acceso()
        self.ui_camiones()
        self.ui_simulador()
        self.ui_incidentes()
        self.ui_chat()
        self.ui_riesgos()
        self.ui_reportes()
        self.ui_config()

        self.al_entrar = {
            "dashboard": self.actualizar_dashboard,
            "acceso": self.refrescar_accesos,
            "camiones": lambda: self.crud_camiones.refrescar(),
            "incidentes": self.refrescar_incidentes,
            "riesgos": self._refrescar_riesgos,
        }
        self.cambiar_pagina("dashboard")

    def _pagina_card(self, key, titulo, rx=0.03, ry=0.04, rw=0.94, rh=0.92):
        pag = self.paginas[key]
        if titulo:
            self.L(pag, titulo, "titulo", ("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 12))
        card = RoundedCard(pag, self.colors)
        card.pack(fill="both", expand=True)
        self.cards_list.append(card)
        content = self.F(card)
        content.place(relx=rx, rely=ry, relwidth=rw, relheight=rh)
        return content

    def _marcar_nav(self):
        c = self.colors
        for k, b in self.botones_nav.items():
            if k == self.pagina_actual:
                b.configure(bg=c["accent_blue"], fg="#FFFFFF", activebackground=c["accent_blue"])
            else:
                b.configure(bg=c["sidebar_bg"], fg=c["text_muted"], activebackground=c["sidebar_bg"])

    def cambiar_pagina(self, destino):
        self.pagina_actual = destino
        self._marcar_nav()
        for k, p in self.paginas.items():
            if k == destino:
                p.pack(fill="both", expand=True)
            else:
                p.pack_forget()
        hook = self.al_entrar.get(destino)
        if hook:
            hook()

    # ------------------------------------------------------------------ tema
    def toggle_theme(self):
        self.current_theme_name = "light" if self.current_theme_name == "dark" else "dark"
        self.colors = THEMES[self.current_theme_name]
        self.btn_theme.config(text="☀️ Modo Claro" if self.current_theme_name == "light" else "🌙 Modo Oscuro")
        self.root.configure(bg=self.colors["bg_app"])
        for w, rol in list(self.themed):
            self._estilizar(w, rol)
        for card in self.cards_list:
            card.set_theme(self.colors)
        self.aplicar_estilos_tabla()
        self._marcar_nav()
        for cv, est in self.estado_sem.items():
            self._set_semaforo(cv, est)
        self._estilo_chat_tags()
        self.renderizar_grafica_riesgos()
        self.verificar_ollama_status()
        self.actualizar_estado_db()

    def estilo_tags(self, tree):
        c = self.colors
        tree.tag_configure("even", background=c["card_bg"], foreground=c["text_light"])
        tree.tag_configure("odd", background=c["table_row_alt"], foreground=c["text_light"])

    def aplicar_estilos_tabla(self):
        c = self.colors
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Treeview", background=c["card_bg"], foreground=c["text_light"],
                    fieldbackground=c["card_bg"], rowheight=30, font=("Segoe UI", 9), borderwidth=0)
        s.configure("Treeview.Heading", background=c["table_head_bg"], foreground=c["table_head_fg"],
                    font=("Segoe UI", 9, "bold"), borderwidth=0)
        s.map("Treeview", background=[("selected", c["accent_blue"])], foreground=[("selected", "#FFFFFF")])
        s.configure("TCombobox", fieldbackground=c["accent_pill"], background=c["accent_pill"],
                    foreground=c["text_light"], arrowcolor=c["text_light"], bordercolor=c["card_border"],
                    lightcolor=c["accent_pill"], darkcolor=c["accent_pill"])
        s.map("TCombobox", fieldbackground=[("readonly", c["accent_pill"])],
              foreground=[("readonly", c["text_light"])],
              selectbackground=[("readonly", c["accent_pill"])],
              selectforeground=[("readonly", c["text_light"])])
        s.configure("Horizontal.TProgressbar", troughcolor=c["accent_pill"], background=c["accent_blue"],
                    borderwidth=0, thickness=6)
        s.configure("Vertical.TScrollbar", background=c["accent_pill"], troughcolor=c["card_bg"],
                    bordercolor=c["card_bg"], arrowcolor=c["text_light"])
        self.root.option_add("*TCombobox*Listbox.background", c["card_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text_light"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent_blue"])
        for t in self.trees:
            self.estilo_tags(t)

    # ------------------------------------------------------------------ estado
    def actualizar_estado_db(self):
        ok = self.db.esta_conectado()
        self.lbl_st.config(text="● MongoDB conectado" if ok else "● Modo local (sin persistencia)",
                           fg=self.colors["accent_green"] if ok else self.colors["danger"])

    @staticmethod
    def _consultar_ollama():
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "LogiSmart"})
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]

    def verificar_ollama_status(self):
        c = self.colors
        self.lbl_ollama_st.config(text="● Verificando Ollama...", fg=c["text_muted"])
        base = self.cfg["modelo_ollama"]

        def ok(modelos):
            self.modelos_ollama = modelos
            if hasattr(self, "cmb_modelo"):
                self.cmb_modelo.configure(values=modelos or [base])
            listo = any(m == base or m.startswith(base + ":") for m in modelos)
            if listo:
                self.lbl_ollama_st.config(text=f"● Ollama ({base} listo)", fg=self.colors["accent_green"])
            else:
                self.lbl_ollama_st.config(text=f"⚠ Ollama On (falta {base})", fg=self.colors["warn"])

        def err(_):
            self.lbl_ollama_st.config(text="● Ollama Off (respaldo: reglas)", fg=self.colors["danger"])
        self.run_async(self._consultar_ollama, ok, err)

    # ------------------------------------------------------------------ semáforo
    def crear_semaforo(self, parent, w=90, h=230):
        cv = tk.Canvas(parent, width=w, height=h, highlightthickness=0)
        self._reg(cv, "card")
        self._set_semaforo(cv, None)
        return cv

    def _set_semaforo(self, cv, activo):
        self.estado_sem[cv] = activo
        c = self.colors
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        cv.create_rectangle(8, 4, w - 8, h - 4, fill=c["accent_pill"], outline=c["card_border"])
        paso = (h - 8) / 3
        colores = {"rojo": "#FF5252", "amarillo": "#FFC107", "verde": "#23A55A"}
        for i, nombre in enumerate(("rojo", "amarillo", "verde")):
            cy, r = 4 + paso * (i + 0.5), min(w / 2 - 14, paso / 2 - 8)
            cv.create_oval(w / 2 - r, cy - r, w / 2 + r, cy + r,
                           fill=colores[nombre] if activo == nombre else c["card_border"], outline="")

    # ================================================================== 1. DASHBOARD
    def ui_dashboard(self):
        pag = self.paginas["dashboard"]
        head = self.F(pag, "app")
        head.pack(fill="x", pady=(0, 8))
        self.L(head, "Overview — Control Center", "titulo", ("Segoe UI", 20, "bold")).pack(side="left")
        self.B(head, "🔄 Actualizar", self.actualizar_dashboard).pack(side="right")

        flt = self.F(pag, "app")
        flt.pack(fill="x", pady=(0, 10))
        self.L(flt, "Desde (AAAA-MM-DD):", "titulo", ("Segoe UI", 9)).pack(side="left")
        self.dash_desde = self.E(flt, width=12)
        self.dash_desde.pack(side="left", padx=6, ipady=4)
        self.L(flt, "Hasta:", "titulo", ("Segoe UI", 9)).pack(side="left")
        self.dash_hasta = self.E(flt, width=12)
        self.dash_hasta.pack(side="left", padx=6, ipady=4)
        self.B(flt, "Aplicar filtro", self.actualizar_dashboard, "btn_sec", pady=4).pack(side="left", padx=4)
        self.B(flt, "Limpiar", self._limpiar_filtro_dash, "btn_sec", pady=4).pack(side="left")

        kp = self.F(pag, "app")
        kp.pack(fill="x", pady=(0, 12))
        specs = [("Camiones Atendidos", "Evaluaciones de acceso", "accent_blue"),
                 ("Incidentes Abiertos", "Nuevo + en atención", "warn"),
                 ("Riesgos Críticos", "Residual ≥ umbral", "danger"),
                 ("Base de Datos", self.db.db_name, "accent_green")]
        self.kpis = []
        for i, (t, u, ck) in enumerate(specs):
            m = MetricCard(kp, self.colors, t, "0", u, ck, height=125)
            m.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            self.kpis.append(m)
            self.cards_list.append(m)

        c = self._pagina_card("dashboard", None, 0.03, 0.05, 0.94, 0.9)
        self.L(c, "Incidentes por categoría y semana ISO", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        cols = ("categoria", "semana", "total", "estado")
        self.tree_agregacion = ttk.Treeview(c, columns=cols, show="headings", height=8)
        for cid, txt, w, an in (("categoria", "Categoría", 240, "w"), ("semana", "Semana", 100, "center"),
                                ("total", "Total", 100, "center"), ("estado", "Nivel de prioridad", 160, "center")):
            self.tree_agregacion.heading(cid, text=txt)
            self.tree_agregacion.column(cid, width=w, anchor=an)
        self.tree_agregacion.pack(fill="both", expand=True)
        self.trees.append(self.tree_agregacion)

    def _limpiar_filtro_dash(self):
        self.dash_desde.delete(0, "end")
        self.dash_hasta.delete(0, "end")
        self.actualizar_dashboard()

    def actualizar_dashboard(self):
        try:
            desde, hasta = parse_rango(self.dash_desde.get(), self.dash_hasta.get())
        except ValueError as e:
            messagebox.showwarning("Validación", str(e))
            return
        filtro = DBManager.filtro_fecha(desde, hasta)
        accesos = self.db.listar("accesos", filtro)
        incidentes = self.db.listar("incidentes", filtro)
        abiertos = sum(1 for i in incidentes if i.get("estado", "nuevo") != "cerrado")
        criticos = sum(1 for r in self.db.obtener_riesgos()
                       if puntaje_residual(r) >= self.cfg["umbral_riesgo_critico"])
        self.kpis[0].set_value(len(accesos))
        self.kpis[1].set_value(abiertos)
        self.kpis[2].set_value(criticos)
        self.kpis[3].set_value("Atlas" if self.db.esta_conectado() else "Local")

        for r in self.tree_agregacion.get_children():
            self.tree_agregacion.delete(r)
        for idx, it in enumerate(self.db.obtener_agregacion_incidentes(desde, hasta)):
            tot = it.get("total", 0)
            prio = ("🟢 Normal" if tot < self.cfg["umbral_prioridad_moderada"]
                    else "🟡 Moderada" if tot < self.cfg["umbral_prioridad_critica"] else "🔴 Crítica")
            self.tree_agregacion.insert("", "end", tags=("even" if idx % 2 == 0 else "odd",), values=(
                str(it["_id"].get("categoria", "N/A")).replace("_", " ").title(),
                f"Semana {it['_id'].get('semana', 'N/A')}", tot, prio))
        self.estilo_tags(self.tree_agregacion)
        self.actualizar_estado_db()

    # ================================================================== 2. CONTROL DE ACCESO
    def ui_acceso(self):
        c = self._pagina_card("acceso", "Control de Acceso Vehicular")
        fila = self.F(c)
        fila.pack(fill="x", pady=(0, 6))
        self.L(fila, "Placa:", font=FONT_B).pack(side="left")
        self.ent_placa = self.E(fila, width=16)
        self.ent_placa.pack(side="left", ipady=6, padx=8)
        self.B(fila, "🔍 Buscar camión", self.buscar_camion, "btn_sec", pady=5).pack(side="left", padx=4)
        self.B(fila, "Ver todos", self.limpiar_filtro_accesos, "btn_sec", pady=5).pack(side="left")
        self.lbl_camion = self.L(fila, "", "dyn")
        self.lbl_camion.pack(side="left", padx=12)

        cuerpo = self.F(c)
        cuerpo.pack(fill="x")
        izq = self.F(cuerpo)
        izq.pack(side="left", anchor="n")
        defaults = {"P": True, "Q": False, "R": False, "S": True, "H": False, "V": True}
        self.var_acc = {v: tk.BooleanVar(value=defaults[v]) for v in VARS}
        for v in VARS:
            self.CK(izq, f"{v}: {NOMBRES[v]}", self.var_acc[v]).pack(anchor="w", pady=2)
        self.B(izq, "Evaluar y guardar", self.evaluar_acceso).pack(anchor="w", pady=10)

        der = self.F(cuerpo)
        der.pack(side="left", fill="both", expand=True, padx=25)
        self.sem_acceso = self.crear_semaforo(der)
        self.sem_acceso.pack(side="left")
        caja = self.F(der)
        caja.pack(side="left", fill="both", expand=True, padx=15)
        self.lbl_decision = self.L(caja, "Esperando evaluación", "dyn", ("Segoe UI", 14, "bold"),
                                   fg=self.colors["text_muted"], wraplength=520, justify="left")
        self.lbl_decision.pack(anchor="w", pady=(0, 6))
        self.txt_pasos = self.T(caja, height=8, state="disabled")
        self.txt_pasos.pack(fill="both", expand=True)

        self.L(c, "Bitácora de accesos", font=FONT_B).pack(anchor="w", pady=(10, 4))
        ft = self.F(c)
        ft.pack(fill="both", expand=True)
        cols = ("fecha", "placa", "decision", "A", "E", "operador")
        self.tree_accesos = ttk.Treeview(ft, columns=cols, show="headings", height=5)
        for cid, txt, w in (("fecha", "Fecha", 140), ("placa", "Placa", 110), ("decision", "Decisión", 110),
                            ("A", "A_ext", 60), ("E", "E_ext", 60), ("operador", "Operador", 160)):
            self.tree_accesos.heading(cid, text=txt)
            self.tree_accesos.column(cid, width=w, anchor="w")
        self.tree_accesos.pack(fill="both", expand=True)
        self.trees.append(self.tree_accesos)
        self.B(c, "🗑 Eliminar registro seleccionado", self.eliminar_acceso, "btn_danger", pady=5).pack(anchor="w", pady=(6, 0))

    def _placa_valida(self):
        placa = self.ent_placa.get().strip().upper()
        if not PLACA_OK.match(placa):
            messagebox.showwarning("Validación", "Placa inválida. Usa 3 a 12 caracteres: letras, números y guiones (ej. CAM-102).")
            return None
        return placa

    def buscar_camion(self):
        placa = self._placa_valida()
        if not placa:
            return
        cam = self.db.buscar_camion(placa)
        self.filtro_placa = placa
        self.refrescar_accesos()
        if cam:
            self.var_acc["P"].set(bool(cam.get("autorizacion")))
            self.var_acc["S"].set(bool(cam.get("certificacion_conductor")))
            self.var_acc["V"].set(bool(cam.get("certificacion_vigente", True)))
            self.lbl_camion.config(text=f"✔ {cam.get('empresa', '')} · {cam.get('camion_id', '')} (premisas P, S, V cargadas)",
                                   fg=self.colors["accent_green"])
        else:
            self.lbl_camion.config(text="⚠ Camión no registrado: captura las premisas manualmente.",
                                   fg=self.colors["warn"])

    def limpiar_filtro_accesos(self):
        self.filtro_placa = None
        self.lbl_camion.config(text="")
        self.refrescar_accesos()

    def evaluar_acceso(self):
        placa = self._placa_valida()
        if not placa:
            return
        v = {k: self.var_acc[k].get() for k in VARS}
        res = MotorReglas.evaluar_camion_extendido(**v)
        self.db.registrar_acceso({
            "placa": placa, "premisas": v,
            "resultado_A": res["acceso_estandar"], "resultado_E": res["inspeccion_especial"],
            "resultado_A_ext": res["acceso_estandar_extendido"],
            "resultado_E_ext": res["inspeccion_especial_extendida"],
            "decision": res["decision"], "explicacion": res["explicacion"], "pasos": res["pasos"],
            "operador": self.cfg["operador"],
        })
        col = {"verde": self.colors["accent_green"], "amarillo": self.colors["warn"], "rojo": self.colors["danger"]}[res["semaforo"]]
        self._set_semaforo(self.sem_acceso, res["semaforo"])
        self.lbl_decision.config(text=res["resumen"], fg=col)
        self._set_text(self.txt_pasos, "\n".join(res["pasos"]))
        self.refrescar_accesos()

    def refrescar_accesos(self):
        for i in self.tree_accesos.get_children():
            self.tree_accesos.delete(i)
        f = {"placa": self.filtro_placa} if self.filtro_placa else None
        for idx, d in enumerate(self.db.obtener_accesos(50, f)):
            self.tree_accesos.insert("", "end", iid=d["_id"], tags=("even" if idx % 2 == 0 else "odd",), values=(
                fmt_fecha(d.get("fecha_registro")), d.get("placa", ""), d.get("decision", ""),
                "V" if d.get("resultado_A_ext") else "F", "V" if d.get("resultado_E_ext") else "F",
                d.get("operador", "")))
        self.estilo_tags(self.tree_accesos)
        self.actualizar_estado_db()

    def eliminar_acceso(self):
        s = self.tree_accesos.selection()
        if not s:
            messagebox.showinfo("Eliminar", "Selecciona un registro de la bitácora.")
            return
        if messagebox.askyesno("Confirmar", "¿Eliminar este registro de la bitácora?"):
            self.db.eliminar("accesos", s[0])
            self.refrescar_accesos()

    # ================================================================== 3. CAMIONES (CRUD)
    def ui_camiones(self):
        c = self._pagina_card("camiones", "Catálogo de Camiones")
        ck = lambda k: (lambda d: "✔" if d.get(k) else "✖")
        campos = [
            {"k": "placa", "et": "Placa", "t": "text", "mayus": True, "w": 16},
            {"k": "camion_id", "et": "ID camión", "t": "text", "w": 16},
            {"k": "empresa", "et": "Empresa", "t": "text", "w": 40, "span": True},
            {"k": "autorizacion", "et": "P: Autorización previa", "t": "bool", "def": True},
            {"k": "certificacion_conductor", "et": "S: Conductor certificado", "t": "bool", "def": True},
            {"k": "certificacion_vigente", "et": "V: Certificación vigente", "t": "bool", "def": True},
        ]
        cols = [("placa", "Placa", 110, lambda d: d.get("placa", "")),
                ("camion_id", "ID", 100, lambda d: d.get("camion_id", "")),
                ("empresa", "Empresa", 260, lambda d: d.get("empresa", "")),
                ("P", "Autoriz.", 80, ck("autorizacion")),
                ("S", "Certif.", 80, ck("certificacion_conductor")),
                ("V", "Vigente", 80, ck("certificacion_vigente"))]
        self.crud_camiones = FormCrud(self, c, "camiones", campos, cols, tree_h=9, validar=self.validar_camion)

    def validar_camion(self, d, sel):
        if not PLACA_OK.match(d["placa"]):
            return "Placa inválida (3 a 12 caracteres: letras, números y guiones)."
        if not d["camion_id"]:
            return "El ID del camión es obligatorio."
        if not d["empresa"]:
            return "La empresa es obligatoria."
        if [x for x in self.db.listar("camiones", {"placa": d["placa"]}) if x["_id"] != sel]:
            return f"Ya existe un camión con la placa {d['placa']}."
        return None

    # ================================================================== 4. SIMULADOR
    def ui_simulador(self):
        c = self._pagina_card("simulador", "Simulador de Tablas de Verdad")
        top = self.F(c)
        top.pack(fill="x")
        izq = self.F(top)
        izq.pack(side="left", anchor="n")
        self.L(izq, "Activa los interruptores:", font=FONT_B).pack(anchor="w", pady=(0, 4))
        self.var_sim = {v: tk.BooleanVar(value=v in ("P", "S", "V")) for v in VARS}
        for v in VARS:
            self.CK(izq, f"{v}: {NOMBRES[v]}", self.var_sim[v], self.actualizar_sim).pack(anchor="w", pady=2)
        self.B(izq, "🔎 Analizar reglas", self.analizar_reglas, "btn_sec", pady=5).pack(anchor="w", pady=8)

        der = self.F(top)
        der.pack(side="left", fill="both", expand=True, padx=25)
        self.sem_sim = self.crear_semaforo(der, 70, 190)
        self.sem_sim.pack(side="left")
        caja = self.F(der)
        caja.pack(side="left", fill="both", expand=True, padx=15)
        self.lbl_sim = self.L(caja, "", "dyn", ("Segoe UI", 12, "bold"), justify="left")
        self.lbl_sim.pack(anchor="w", pady=(0, 6))
        self.txt_sim = self.T(caja, height=7, state="disabled")
        self.txt_sim.pack(fill="both", expand=True)

        ft = self.F(c)
        ft.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("P", "Q", "R", "S", "H", "V", "A", "E", "A_ext", "E_ext")
        self.tree_truth = ttk.Treeview(ft, columns=cols, show="headings", height=8)
        for col in cols:
            self.tree_truth.heading(col, text=col)
            self.tree_truth.column(col, width=60, anchor="center")
        sb = ttk.Scrollbar(ft, orient="vertical", command=self.tree_truth.yview)
        self.tree_truth.configure(yscrollcommand=sb.set)
        self.tree_truth.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.trees.append(self.tree_truth)
        vf = lambda b: "V" if b else "F"
        for idx, f in enumerate(MotorReglas.generar_tabla_verdad_extendida()):
            iid = "".join("1" if f[v] else "0" for v in VARS)
            self.tree_truth.insert("", "end", iid=iid, tags=("even" if idx % 2 == 0 else "odd",),
                                   values=[vf(f[k]) for k in cols])
        self.estilo_tags(self.tree_truth)
        self.actualizar_sim()

    def actualizar_sim(self):
        v = {k: self.var_sim[k].get() for k in VARS}
        r = MotorReglas.evaluar_camion_extendido(**v)
        col = {"verde": self.colors["accent_green"], "amarillo": self.colors["warn"], "rojo": self.colors["danger"]}[r["semaforo"]]
        vf = lambda b: "V" if b else "F"
        self.lbl_sim.config(
            text=f"A = {vf(r['acceso_estandar'])}   E = {vf(r['inspeccion_especial'])}   │   "
                 f"A_ext = {vf(r['acceso_estandar_extendido'])}   E_ext = {vf(r['inspeccion_especial_extendida'])}\n"
                 f"Decisión: {r['decision']}", fg=col)
        self._set_semaforo(self.sem_sim, r["semaforo"])
        self._set_text(self.txt_sim, "\n".join(r["pasos"]))
        iid = "".join("1" if v[k] else "0" for k in VARS)
        if self.tree_truth.exists(iid):
            self.tree_truth.selection_set(iid)
            self.tree_truth.see(iid)

    def analizar_reglas(self):
        messagebox.showinfo("Análisis de reglas (contradicciones y redundancias)",
                            "\n\n".join(MotorReglas.analizar_reglas()))

    # ================================================================== 5. INCIDENTES
    def ui_incidentes(self):
        c = self._pagina_card("incidentes", "Bandeja de Incidentes (IA)", 0.03, 0.03, 0.94, 0.94)
        self.L(c, "Correo / reporte:", font=FONT_B).pack(anchor="w")
        self.txt_correo = self.T(c, height=4)
        self.txt_correo.pack(fill="x", pady=(2, 6))

        fb = self.F(c)
        fb.pack(fill="x")
        self.btn_clasif = self.B(fb, "⚡ Clasificar con IA", self.clasificar_incidente, pady=6)
        self.btn_clasif.pack(side="left")
        self.btn_sim = self.B(fb, "🎲 Correo simulado", self.correo_simulado, "btn_sec", pady=6)
        self.barra_inc = self.barra(c)
        self.lbl_inc_info = self.L(c, "El resultado de la clasificación aparecerá aquí.", "dyn",
                                   fg=self.colors["text_muted"], justify="left", wraplength=900)
        self.lbl_inc_info.pack(anchor="w")

        form = self.F(c)
        form.pack(fill="x", pady=6)
        self.cmb_inc_cat = self.CB(form, CATEGORIAS, 22)
        self.cmb_inc_pri = self.CB(form, PRIORIDADES, 12)
        self.cmb_inc_est = self.CB(form, ESTADOS, 14)
        self.ent_inc_placa = self.E(form, width=14)
        self.ent_inc_ubic = self.E(form, width=18)
        self.ent_inc_res = self.E(form, width=70)
        self.var_rev = tk.BooleanVar()
        items = [("Categoría:", self.cmb_inc_cat, 0, 0), ("Prioridad:", self.cmb_inc_pri, 0, 2),
                 ("Estado:", self.cmb_inc_est, 0, 4), ("Placa:", self.ent_inc_placa, 1, 0),
                 ("Ubicación:", self.ent_inc_ubic, 1, 2)]
        for txt, w, r, col in items:
            self.L(form, txt, font=FONT_B).grid(row=r, column=col, sticky="w", padx=(0, 6), pady=3)
            w.grid(row=r, column=col + 1, sticky="w", padx=(0, 18), pady=3, ipady=0 if isinstance(w, ttk.Combobox) else 3)
        self.L(form, "Resumen:", font=FONT_B).grid(row=2, column=0, sticky="w", pady=3)
        self.ent_inc_res.grid(row=2, column=1, columnspan=5, sticky="w", pady=3, ipady=3)
        self.CK(form, "Requiere revisión humana", self.var_rev).grid(row=1, column=4, columnspan=2, sticky="w")

        fa = self.F(c)
        fa.pack(fill="x", pady=4)
        self.B(fa, "✚ Nuevo", self.nuevo_incidente, "btn_sec", pady=5).pack(side="left", padx=(0, 8))
        self.B(fa, "💾 Guardar", self.guardar_incidente_ui, pady=5).pack(side="left", padx=(0, 8))
        self.B(fa, "🗑 Eliminar", self.eliminar_incidente, "btn_danger", pady=5).pack(side="left")

        ft = self.F(c)
        ft.pack(fill="both", expand=True, pady=(6, 4))
        cols = ("fecha", "categoria", "prioridad", "estado", "placa", "rev")
        self.tree_inc = ttk.Treeview(ft, columns=cols, show="headings", height=4, selectmode="browse")
        for cid, txt, w in (("fecha", "Fecha", 130), ("categoria", "Categoría", 170), ("prioridad", "Prioridad", 90),
                            ("estado", "Estado", 100), ("placa", "Placa", 100), ("rev", "Revisión", 90)):
            self.tree_inc.heading(cid, text=txt)
            self.tree_inc.column(cid, width=w, anchor="w")
        sb = ttk.Scrollbar(ft, orient="vertical", command=self.tree_inc.yview)
        self.tree_inc.configure(yscrollcommand=sb.set)
        self.tree_inc.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_inc.bind("<<TreeviewSelect>>", self._seleccionar_incidente)
        self.trees.append(self.tree_inc)

        self.L(c, "Historial del incidente seleccionado:", font=FONT_B).pack(anchor="w")
        self.txt_hist = self.T(c, height=3, state="disabled")
        self.txt_hist.pack(fill="x")
        self.nuevo_incidente()

    def correo_simulado(self):
        self.txt_correo.delete("1.0", "end")
        self.txt_correo.insert("end", random.choice(evaluacion.DATASET)[0])

    def clasificar_incidente(self):
        texto = self.txt_correo.get("1.0", "end").strip()
        if len(texto) < 10:
            messagebox.showwarning("Validación", "Pega un correo o reporte de al menos 10 caracteres.")
            return
        self.btn_clasif.config(state="disabled")
        self.barra_inc.start(12)
        self.lbl_inc_info.config(text="⏳ Consultando el LLM local… (si no responde se usan las reglas)",
                                 fg=self.colors["text_muted"])

        def fin():
            self.barra_inc.stop()
            self.btn_clasif.config(state="normal")

        def ok(res):
            fin()
            self.ultimo_clasif = res
            self.cmb_inc_cat.set(res["categoria"])
            self.cmb_inc_pri.set(res["prioridad"])
            if not self.cmb_inc_est.get():
                self.cmb_inc_est.set("nuevo")
            self.ent_inc_placa.delete(0, "end")
            self.ent_inc_placa.insert(0, res["entidades"].get("placa") or "")
            self.ent_inc_ubic.delete(0, "end")
            self.ent_inc_ubic.insert(0, res["entidades"].get("ubicacion") or "")
            self.ent_inc_res.delete(0, "end")
            self.ent_inc_res.insert(0, res.get("resumen", ""))
            self.var_rev.set(bool(res.get("requiere_revision_humana")))
            info = f"Origen: {res['origen']} · Latencia: {res['latencia']:.2f}s"
            if res.get("llm_ok") is False:
                info += " · ⚠ LLM no disponible o JSON inválido: se usaron reglas"
            if res.get("requiere_revision_humana"):
                info += "\n⚠ LLM y reglas discrepan: prevalece la prioridad más alta. REQUIERE REVISIÓN HUMANA."
            self.lbl_inc_info.config(text=info, fg=self.colors["warn"] if res.get("requiere_revision_humana")
                                     else self.colors["accent_green"])

        def err(e):
            fin()
            self.lbl_inc_info.config(text=f"✖ Error al clasificar: {e}", fg=self.colors["danger"])
        self.run_async(lambda: self.clasificador.clasificar_hibrido(texto), ok, err)

    def nuevo_incidente(self):
        self.inc_sel = None
        if self.tree_inc.selection():
            self.tree_inc.selection_remove(*self.tree_inc.selection())
        self.txt_correo.delete("1.0", "end")
        for cb in (self.cmb_inc_cat, self.cmb_inc_pri):
            cb.set("")
        self.cmb_inc_est.set("nuevo")
        for e in (self.ent_inc_placa, self.ent_inc_ubic, self.ent_inc_res):
            e.delete(0, "end")
        self.var_rev.set(False)
        self.ultimo_clasif = None
        self._set_text(self.txt_hist, "")

    def guardar_incidente_ui(self):
        texto = self.txt_correo.get("1.0", "end").strip()
        cat, pri, est = self.cmb_inc_cat.get(), self.cmb_inc_pri.get(), self.cmb_inc_est.get()
        placa = self.ent_inc_placa.get().strip().upper()
        if not texto:
            messagebox.showwarning("Validación", "El texto del correo es obligatorio.")
            return
        if cat not in CATEGORIAS or pri not in PRIORIDADES or est not in ESTADOS:
            messagebox.showwarning("Validación", "Selecciona categoría, prioridad y estado (o usa «Clasificar con IA»).")
            return
        if placa and not PLACA_OK.match(placa):
            messagebox.showwarning("Validación", "La placa extraída no es válida (ej. CAM-102).")
            return
        datos = {
            "correo_original": texto, "categoria": cat, "prioridad": pri, "estado": est,
            "entidades": {"placa": placa or None, "ubicacion": self.ent_inc_ubic.get().strip() or None},
            "resumen": self.ent_inc_res.get().strip() or texto[:100],
            "requiere_revision_humana": bool(self.var_rev.get()),
        }
        ahora = datetime.now()
        if self.inc_sel:
            prev = self.inc_docs.get(self.inc_sel, {})
            nota = (f"Estado: {prev.get('estado')} → {est}" if prev.get("estado") != est
                    else "Clasificación editada por el operador")
            self.db.actualizar("incidentes", self.inc_sel, datos,
                               {"historial": {"fecha": ahora, "estado": est, "nota": nota,
                                              "operador": self.cfg["operador"]}})
        else:
            datos["origen"] = (self.ultimo_clasif or {}).get("origen", "manual")
            datos["historial"] = [{"fecha": ahora, "estado": est, "nota": "Incidente creado",
                                   "operador": self.cfg["operador"]}]
            self.db.guardar_incidente(datos)
        self.refrescar_incidentes()
        self.nuevo_incidente()

    def refrescar_incidentes(self):
        self.inc_docs = {}
        for i in self.tree_inc.get_children():
            self.tree_inc.delete(i)
        for idx, d in enumerate(self.db.obtener_incidentes()):
            self.inc_docs[d["_id"]] = d
            self.tree_inc.insert("", "end", iid=d["_id"], tags=("even" if idx % 2 == 0 else "odd",), values=(
                fmt_fecha(d.get("fecha_registro")), d.get("categoria", ""), d.get("prioridad", ""),
                d.get("estado", "nuevo"), (d.get("entidades") or {}).get("placa") or "",
                "⚠ Sí" if d.get("requiere_revision_humana") else "No"))
        self.estilo_tags(self.tree_inc)
        self.actualizar_estado_db()

    def _seleccionar_incidente(self, _):
        s = self.tree_inc.selection()
        if not s:
            return
        self.inc_sel = s[0]
        d = self.inc_docs.get(self.inc_sel, {})
        self.txt_correo.delete("1.0", "end")
        self.txt_correo.insert("end", d.get("correo_original", ""))
        self.cmb_inc_cat.set(d.get("categoria", ""))
        self.cmb_inc_pri.set(d.get("prioridad", ""))
        self.cmb_inc_est.set(d.get("estado", "nuevo"))
        ent = d.get("entidades") or {}
        for w, k in ((self.ent_inc_placa, "placa"), (self.ent_inc_ubic, "ubicacion")):
            w.delete(0, "end")
            w.insert(0, ent.get(k) or "")
        self.ent_inc_res.delete(0, "end")
        self.ent_inc_res.insert(0, d.get("resumen", ""))
        self.var_rev.set(bool(d.get("requiere_revision_humana")))
        hist = "\n".join(f"{fmt_fecha(h.get('fecha'))} · {h.get('estado')} · {h.get('nota', '')}"
                         for h in d.get("historial", [])) or "Sin historial."
        self._set_text(self.txt_hist, hist)

    def eliminar_incidente(self):
        if not self.inc_sel:
            messagebox.showinfo("Eliminar", "Selecciona un incidente de la tabla.")
            return
        if messagebox.askyesno("Confirmar", "¿Eliminar el incidente seleccionado?"):
            self.db.eliminar("incidentes", self.inc_sel)
            self.refrescar_incidentes()
            self.nuevo_incidente()

    # ================================================================== 6. CHAT RAG
    def ui_chat(self):
        c = self._pagina_card("chat", "Asistente RAG & Consultas")
        self.txt_chat = self.T(c, state="disabled", padx=15, pady=15)
        self.txt_chat.pack(fill="both", expand=True, pady=(0, 6))
        self._estilo_chat_tags()
        self.barra_chat = self.barra(c)
        self.L(c, "Ej.: «¿Por qué CAM-102 fue enviado a inspección?»  ·  Responde solo con datos de MongoDB y cita la fuente.",
               "muted", ("Segoe UI", 9)).pack(anchor="w")
        fila = self.F(c)
        fila.pack(fill="x", pady=8)
        self.ent_pregunta = self.E(fila)
        self.ent_pregunta.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 10))
        self.ent_pregunta.bind("<Return>", lambda e: self.preguntar_rag())
        self.btn_enviar = self.B(fila, "Enviar ➔", self.preguntar_rag)
        self.btn_enviar.pack(side="right")
        self.B(fila, "🗑 Limpiar vista", lambda: self._set_text(self.txt_chat, ""), "btn_sec").pack(side="right", padx=8)
        for d in reversed(self.db.listar("chat_historial", None, 20, ("fecha_registro", -1))):
            self._chat_agregar(d.get("pregunta", ""), d.get("respuesta", ""), d.get("fuente", ""))

    def _estilo_chat_tags(self):
        c = self.colors
        self.txt_chat.tag_configure("usr", foreground=c["accent_blue"], font=("Segoe UI", 10, "bold"))
        self.txt_chat.tag_configure("bot", foreground=c["text_light"])
        self.txt_chat.tag_configure("src", foreground=c["text_muted"], font=("Segoe UI", 9, "italic"))

    def _chat_agregar(self, pregunta, respuesta, fuente):
        t = self.txt_chat
        t.config(state="normal")
        t.insert("end", f"Usuario: {pregunta}\n", "usr")
        t.insert("end", f"Asistente: {respuesta}\n", "bot")
        t.insert("end", f"Fuentes consultadas: {fuente}\n\n", "src")
        t.config(state="disabled")
        t.see("end")

    def preguntar_rag(self):
        pregunta = self.ent_pregunta.get().strip()
        if len(pregunta) < 3:
            messagebox.showwarning("Validación", "Escribe una pregunta (mínimo 3 caracteres).")
            return
        self.ent_pregunta.delete(0, "end")
        self.btn_enviar.config(state="disabled")
        self.barra_chat.start(12)

        def fin():
            self.barra_chat.stop()
            self.btn_enviar.config(state="normal")

        def ok(res):
            fin()
            self._chat_agregar(pregunta, res["respuesta"], res["fuente"])
            self.db.insertar("chat_historial", {"pregunta": pregunta, "respuesta": res["respuesta"],
                                                "fuente": res["fuente"], "origen": res.get("origen"),
                                                "latencia": round(res.get("latencia", 0), 3)})

        def err(e):
            fin()
            self._chat_agregar(pregunta, f"⚠ Error al consultar: {e}", "—")
        self.run_async(lambda: self.asistente.responder_consulta(pregunta), ok, err)

    # ================================================================== 7. RIESGOS ÉTICOS
    def ui_riesgos(self):
        c = self._pagina_card("riesgos", "Evaluación de Riesgos Éticos", 0.02, 0.03, 0.96, 0.94)
        self.f_chart = self.F(c, height=250)
        self.f_chart.pack(fill="x")
        self.f_chart.pack_propagate(False)
        campos = [
            {"k": "modulo", "et": "Módulo", "t": "text", "w": 24},
            {"k": "categoria", "et": "Categoría", "t": "combo", "op": CATEGORIAS_RIESGO, "def": "Fiabilidad"},
            {"k": "descripcion", "et": "Descripción", "t": "text", "w": 80, "span": True},
            {"k": "prob_inicial", "et": "Prob. inicial (1-5)", "t": "int", "def": 3},
            {"k": "impacto_inicial", "et": "Impacto inicial (1-5)", "t": "int", "def": 3},
            {"k": "prob_mitigada", "et": "Prob. mitigada (1-5)", "t": "int", "def": 2},
            {"k": "impacto_mitigado", "et": "Impacto mitigado (1-5)", "t": "int", "def": 2},
            {"k": "mitigacion", "et": "Mitigación", "t": "text", "w": 80, "span": True},
        ]
        nivel = lambda d: ("🔴 Crítico" if puntaje_residual(d) >= self.cfg["umbral_riesgo_critico"]
                           else "🟡 Medio" if puntaje_residual(d) >= 6 else "🟢 Bajo")
        cols = [("modulo", "Módulo", 140, lambda d: d.get("modulo", "")),
                ("desc", "Descripción", 270, lambda d: d.get("descripcion", "")),
                ("cat", "Categoría", 120, lambda d: d.get("categoria", "")),
                ("ini", "Inicial", 60, lambda d: puntaje_inicial(d)),
                ("res", "Residual", 70, lambda d: puntaje_residual(d)),
                ("niv", "Nivel", 90, nivel)]
        self.crud_riesgos = FormCrud(self, c, "riesgos_eticos", campos, cols, tree_h=4,
                                     validar=self.validar_riesgo, preparar=self.preparar_riesgo,
                                     tras_cambio=self.renderizar_grafica_riesgos)

    def validar_riesgo(self, d, sel):
        if not d["modulo"] or not d["descripcion"]:
            return "Módulo y descripción son obligatorios."
        if not d["categoria"]:
            return "Selecciona una categoría."
        if d["prob_mitigada"] * d["impacto_mitigado"] > d["prob_inicial"] * d["impacto_inicial"]:
            return "El riesgo residual no puede ser mayor que el inicial."
        return None

    def preparar_riesgo(self, d, previo):
        d["puntaje_inicial"] = d["prob_inicial"] * d["impacto_inicial"]
        d["puntaje_residual"] = d["prob_mitigada"] * d["impacto_mitigado"]
        snap = {"fecha": datetime.now(), **{k: d[k] for k in (
            "prob_inicial", "impacto_inicial", "prob_mitigada", "impacto_mitigado",
            "puntaje_inicial", "puntaje_residual")}}
        return d, {"historico": snap}

    def _refrescar_riesgos(self):
        self.crud_riesgos.refrescar()
        self.renderizar_grafica_riesgos()

    def renderizar_grafica_riesgos(self):
        for w in self.f_chart.winfo_children():
            w.destroy()
        c = self.colors
        fig = Figure(figsize=(8.5, 2.6), facecolor=c["card_bg"])
        ax = fig.add_subplot(111)
        ax.set_facecolor(c["card_bg"])
        riesgos = self.db.obtener_riesgos()
        if not riesgos:
            ax.text(0.5, 0.5, "Sin riesgos registrados", ha="center", va="center", color=c["text_muted"],
                    transform=ax.transAxes)
            ax.axis("off")
        else:
            nombres = ["\n".join(textwrap.wrap(r.get("descripcion", "?"), 16)) for r in riesgos]
            ini = [puntaje_inicial(r) for r in riesgos]
            res = [puntaje_residual(r) for r in riesgos]
            x = list(range(len(nombres)))
            w = 0.35
            r1 = ax.bar([i - w / 2 for i in x], ini, w, label="Riesgo inicial", color=c["danger"], alpha=0.65, zorder=3)
            r2 = ax.bar([i + w / 2 for i in x], res, w, label="Riesgo residual", color=c["accent_blue"], alpha=0.9, zorder=3)
            ax.bar_label(r1, padding=2, color=c["text_light"], fontsize=8, fontweight="bold")
            ax.bar_label(r2, padding=2, color=c["text_light"], fontsize=8, fontweight="bold")
            ax.axhline(self.cfg["umbral_riesgo_critico"], color=c["warn"], linestyle="--", linewidth=1,
                       label=f"Umbral crítico ({self.cfg['umbral_riesgo_critico']})")
            ax.set_xticks(x)
            ax.set_xticklabels(nombres, color=c["text_light"], fontsize=7)
            ax.set_ylim(0, 28)
            ax.set_ylabel("Puntaje (prob × impacto)", color=c["text_muted"], fontsize=8)
            ax.grid(axis="y", linestyle="--", alpha=0.2, color=c["text_muted"], zorder=0)
            for sp in ax.spines.values():
                sp.set_visible(False)
            ax.tick_params(colors=c["text_light"], labelsize=8)
            ax.legend(facecolor=c["card_bg"], edgecolor=c["card_border"], labelcolor=c["text_light"],
                      fontsize=8, ncol=3, loc="upper right")
        ax.set_title("Matriz de mitigación de riesgos éticos (riesgo residual)", color=c["text_light"],
                     fontsize=10, fontweight="bold")
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.f_chart)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ================================================================== 8. REPORTES
    def ui_reportes(self):
        c = self._pagina_card("reportes", "Reportes y Exportación")
        self.L(c, "Periodo (AAAA-MM-DD, opcional):", font=FONT_B).pack(anchor="w", pady=(0, 8))
        f = self.F(c)
        f.pack(anchor="w", pady=(0, 14))
        self.rep_desde = self.E(f, width=14)
        self.rep_desde.pack(side="left", ipady=6, padx=(0, 10))
        self.rep_hasta = self.E(f, width=14)
        self.rep_hasta.pack(side="left", ipady=6)
        fb = self.F(c)
        fb.pack(anchor="w")
        for txt, fmt in (("📕 Exportar PDF", "pdf"), ("📊 Exportar CSV", "csv"), ("🧾 Exportar JSON", "json")):
            self.B(fb, txt, lambda x=fmt: self.exportar(x)).pack(side="left", padx=(0, 10))
        self.barra_rep = ttk.Progressbar(c, mode="indeterminate", length=320)
        self.barra_rep.pack(anchor="w", pady=12)
        self.lbl_rep = self.L(c, "", "dyn", justify="left", wraplength=800)
        self.lbl_rep.pack(anchor="w")

    def exportar(self, fmt):
        try:
            desde, hasta = parse_rango(self.rep_desde.get(), self.rep_hasta.get())
        except ValueError as e:
            messagebox.showwarning("Validación", str(e))
            return
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "csv":
            destino = filedialog.askdirectory(title="Carpeta destino para los CSV")
        else:
            destino = filedialog.asksaveasfilename(defaultextension=f".{fmt}",
                                                   initialfile=f"reporte_logismart_{sello}.{fmt}",
                                                   filetypes=[(fmt.upper(), f"*.{fmt}")])
        if not destino:
            return
        self.barra_rep.start(12)
        self.lbl_rep.config(text="⏳ Generando reporte…", fg=self.colors["text_muted"])

        def tarea():
            if fmt == "csv":
                a = self.reportes.exportar_csv(destino, desde, hasta)
                return f"✔ {len(a)} archivos CSV creados en:\n{destino}"
            if fmt == "pdf":
                self.reportes.exportar_pdf(destino, desde, hasta)
            else:
                self.reportes.exportar_json(destino, desde, hasta)
            return f"✔ Reporte generado:\n{destino}"

        def ok(msg):
            self.barra_rep.stop()
            self.lbl_rep.config(text=msg, fg=self.colors["accent_green"])

        def err(e):
            self.barra_rep.stop()
            self.lbl_rep.config(text=f"✖ No se pudo exportar: {e}", fg=self.colors["danger"])
            messagebox.showerror("Error de exportación", str(e))
        self.run_async(tarea, ok, err)

    # ================================================================== 9. CONFIGURACIÓN + EVALUACIÓN
    def ui_config(self):
        c = self._pagina_card("config", "Configuración y Evaluación", 0.03, 0.03, 0.94, 0.94)
        form = self.F(c)
        form.pack(fill="x")
        self.L(form, "Modelo Ollama:", font=FONT_B).grid(row=0, column=0, sticky="w", pady=4)
        self.cmb_modelo = self.CB(form, [self.cfg["modelo_ollama"]], 26, state="normal")
        self.cmb_modelo.set(self.cfg["modelo_ollama"])
        self.cmb_modelo.grid(row=0, column=1, sticky="w", padx=8)
        self.B(form, "🔄 Detectar modelos", self.verificar_ollama_status, "btn_sec", pady=4).grid(row=0, column=2, padx=8)

        self.cfg_w = {}
        filas = [("timeout_llm", "Timeout LLM (s):", 5, 600), ("reintentos", "Reintentos JSON inválido:", 0, 5),
                 ("umbral_prioridad_moderada", "Dashboard: total «Moderada» desde:", 1, 99),
                 ("umbral_prioridad_critica", "Dashboard: total «Crítica» desde:", 1, 99),
                 ("umbral_riesgo_critico", "Riesgo residual crítico desde (1-25):", 1, 25)]
        for i, (k, et, lo, hi) in enumerate(filas, 1):
            self.L(form, et, font=FONT_B).grid(row=i, column=0, sticky="w", pady=4)
            sp = tk.Spinbox(form, from_=lo, to=hi, width=6, font=("Segoe UI", 11), relief="flat", bd=0)
            self._reg(sp, "input")
            sp.delete(0, "end")
            sp.insert(0, self.cfg[k])
            sp.grid(row=i, column=1, sticky="w", padx=8, ipady=3)
            self.cfg_w[k] = sp
        self.L(form, "Operador:", font=FONT_B).grid(row=6, column=0, sticky="w", pady=4)
        self.ent_operador = self.E(form, width=26)
        self.ent_operador.insert(0, self.cfg["operador"])
        self.ent_operador.grid(row=6, column=1, sticky="w", padx=8, ipady=3)
        self.var_modo_sim = tk.BooleanVar(value=self.cfg["modo_simulacion_correo"])
        self.CK(form, "Modo simulación de correo (botón «Correo simulado» en Incidentes)", self.var_modo_sim).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=4)

        fb = self.F(c)
        fb.pack(fill="x", pady=8)
        self.B(fb, "💾 Guardar configuración", self.guardar_config_ui, pady=6).pack(side="left", padx=(0, 8))
        self.B(fb, "🔌 Reconectar MongoDB", self.reconectar_db, "btn_sec", pady=6).pack(side="left")
        self.lbl_cfg = self.L(fb, "", "dyn")
        self.lbl_cfg.pack(side="left", padx=12)

        self.L(c, "Evaluación del clasificador (30 correos etiquetados: reglas vs LLM vs híbrido)",
               font=FONT_B).pack(anchor="w", pady=(10, 4))
        fe = self.F(c)
        fe.pack(fill="x")
        self.btn_eval = self.B(fe, "▶ Ejecutar evaluación", self.ejecutar_evaluacion, pady=6)
        self.btn_eval.pack(side="left")
        self.lbl_eval = self.L(fe, "", "dyn")
        self.lbl_eval.pack(side="left", padx=12)
        self.barra_eval = self.barra(c)
        self.txt_eval = self.T(c, height=10, state="disabled")
        self.txt_eval.configure(font=("Consolas", 9))
        self.txt_eval.pack(fill="both", expand=True)

    def guardar_config_ui(self):
        try:
            nuevo = {k: int(w.get()) for k, w in self.cfg_w.items()}
        except ValueError:
            messagebox.showwarning("Validación", "Los umbrales, timeout y reintentos deben ser números enteros.")
            return
        if nuevo["umbral_prioridad_moderada"] >= nuevo["umbral_prioridad_critica"]:
            messagebox.showwarning("Validación", "El umbral «Moderada» debe ser menor que el «Crítica».")
            return
        modelo = self.cmb_modelo.get().strip()
        operador = self.ent_operador.get().strip()
        if not modelo or not operador:
            messagebox.showwarning("Validación", "El modelo y el operador no pueden estar vacíos.")
            return
        nuevo.update(modelo_ollama=modelo, operador=operador, modo_simulacion_correo=bool(self.var_modo_sim.get()))
        self.cfg.update(nuevo)
        try:
            guardar_config(self.cfg)
            self.lbl_cfg.config(text="✔ Configuración guardada", fg=self.colors["accent_green"])
        except OSError as e:
            self.lbl_cfg.config(text=f"⚠ Aplicada, pero no se pudo guardar el archivo: {e}", fg=self.colors["warn"])
        self.aplicar_config()

    def aplicar_config(self):
        self.clasificador.modelo = self.cfg["modelo_ollama"]
        self.clasificador.timeout = self.cfg["timeout_llm"]
        self.clasificador.reintentos = self.cfg["reintentos"]
        self.asistente.modelo = self.cfg["modelo_ollama"]
        self.asistente.timeout = self.cfg["timeout_llm"]
        self.lbl_user.config(text=self.cfg["operador"])
        if self.cfg["modo_simulacion_correo"]:
            self.btn_sim.pack(side="left", padx=8)
        else:
            self.btn_sim.pack_forget()
        self.verificar_ollama_status()
        if self.pagina_actual == "dashboard":
            self.actualizar_dashboard()

    def reconectar_db(self):
        ok = self.db.reconectar()
        self.actualizar_estado_db()
        if ok:
            self.lbl_cfg.config(text="✔ Conectado a MongoDB", fg=self.colors["accent_green"])
        else:
            self.lbl_cfg.config(text="✖ Sigue sin conexión", fg=self.colors["danger"])
            messagebox.showerror("MongoDB", "No se pudo conectar:\n" + self.db.ultimo_error)

    def ejecutar_evaluacion(self):
        if self._eval_corriendo:
            return
        n = len(evaluacion.DATASET)
        if not messagebox.askyesno("Evaluación", f"Se clasificarán {n} correos con «{self.cfg['modelo_ollama']}». "
                                                 "Puede tardar varios minutos. ¿Continuar?"):
            return
        self._eval_corriendo = True
        self.btn_eval.config(state="disabled")
        self.barra_eval.start(12)

        def prog(i, total):
            self._eval_estado.update(i=i, n=total)

        def tick():
            if self._eval_corriendo:
                self.lbl_eval.config(text=f"⏳ Evaluando {self._eval_estado['i']}/{self._eval_estado['n']}…",
                                     fg=self.colors["text_muted"])
                self.root.after(400, tick)

        def fin():
            self._eval_corriendo = False
            self.barra_eval.stop()
            self.btn_eval.config(state="normal")

        def tarea():
            res = evaluacion.ejecutar(self.clasificador, prog)
            evaluacion.guardar_json(res)
            return res

        def ok(res):
            fin()
            self._set_text(self.txt_eval, evaluacion.formatear(res))
            self.lbl_eval.config(text="✔ Listo (guardado en evaluacion_resultados.json)", fg=self.colors["accent_green"])

        def err(e):
            fin()
            self.lbl_eval.config(text=f"✖ Error: {e}", fg=self.colors["danger"])
        tick()
        self.run_async(tarea, ok, err)


if __name__ == "__main__":
    root = tk.Tk()
    LogiSmartGUI(root)
    root.mainloop()