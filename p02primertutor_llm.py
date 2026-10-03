import sys
import math
import random
import threading
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QTimer, QPointF
from PyQt6.QtGui import QColor, QFont, QPainter, QRadialGradient, QBrush, QPen
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QLabel, QFrame, QMessageBox
)
import ollama

MODELO = "llama3.2"

# 1. Configuración del Sistema orientada a Diseño Gráfico
MENSAJE_SISTEMA = """
Eres un mentor y consultor experto en Diseño Gráfico, Teoría del Color, Tipografía, Composición Visual e Identidad de Marca. Tu función es orientar a estudiantes y creativos en sus proyectos de diseño.

Tu tono debe ser profesional, creativo, empático, directo y conversacional, como una charla entre colegas creativos en un estudio de diseño. Evita sonar robótico y no abuses de listas innecesarias a menos que sea indispensable para la claridad.

Sigue estas directrices al responder:
1. Explica los principios visuales (equilibrio, contraste, jerarquía, paletas cromáticas, etc.) de manera clara y conceptual.
2. Detalla el proceso creativo o paso a paso para resolver un problema de diseño o maquetación.
3. Proporciona ejemplos prácticos de aplicaciones visuales o combinación de herramientas creativas.
4. Si el usuario comparte una idea o concepto débil, dale retroalimentación constructiva para elevar el nivel gráfico.
5. Mantén tus respuestas enfocadas en la estética, la usabilidad y la comunicación visual efectiva.
"""

class HiloOllama(QThread):
    respuesta_lista = pyqtSignal(str)
    error_ocurrido = pyqtSignal(str)

    def __init__(self, mensajes):
        super().__init__()
        self.mensajes = mensajes

    def run(self):
        try:
            respuesta = ollama.chat(model=MODELO, messages=self.mensajes)
            contenido = respuesta["message"]["content"]
            self.respuesta_lista.emit(contenido)
        except Exception as e:
            self.error_ocurrido.emit(str(e))

class OrbeParticulas(QWidget):
    """Orbe de partículas dinámicas con brillo neón morado intensificado"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(190)
        self.angulo = 0.0
        self.pulsacion = 0.0
        self.pensando = False
        self.modo_oscuro = True
        
        self.particulas = []
        for i in range(120):
            capa = random.randint(1, 3)
            angulo_base = random.uniform(0, math.tau)
            radio_var = random.uniform(0.7, 1.3)
            tamano = random.uniform(2.0, 5.5)
            self.particulas.append({
                'capa': capa,
                'angulo': angulo_base,
                'radio_var': radio_var,
                'tamano': tamano,
                'fase': random.uniform(0, math.tau)
            })

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animar)
        self.timer.start(25)

    def set_modo_oscuro(self, es_oscuro):
        self.modo_oscuro = es_oscuro
        self.update()

    def set_estado_pensando(self, pensando):
        self.pensando = pensando

    def animar(self):
        vel_rotacion = 0.05 if self.pensando else 0.02
        vel_pulso = 0.1 if self.pensando else 0.04
        self.angulo = (self.angulo + vel_rotacion) % math.tau
        self.pulsacion += vel_pulso
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        
        factor_pulso = math.sin(self.pulsacion) * 10 if self.pensando else math.sin(self.pulsacion) * 4
        radio_base = 58 + factor_pulso

        glow_gradiente = QRadialGradient(cx, cy, radio_base * 1.8)
        if self.modo_oscuro:
            glow_gradiente.setColorAt(0.0, QColor(180, 0, 255, 160))
            glow_gradiente.setColorAt(0.4, QColor(255, 45, 140, 110))
            glow_gradiente.setColorAt(0.7, QColor(120, 20, 220, 50))
            glow_gradiente.setColorAt(1.0, QColor(11, 11, 14, 0))
        else:
            glow_gradiente.setColorAt(0.0, QColor(160, 60, 255, 150))
            glow_gradiente.setColorAt(0.4, QColor(230, 80, 200, 90))
            glow_gradiente.setColorAt(0.8, QColor(200, 150, 255, 30))
            glow_gradiente.setColorAt(1.0, QColor(248, 246, 252, 0))

        painter.setBrush(QBrush(glow_gradiente))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(cx - radio_base * 1.8, cy - radio_base * 1.8, radio_base * 3.6, radio_base * 3.6))

        colores_oscuro = [
            QColor(255, 230, 180),
            QColor(255, 45, 160),
            QColor(180, 70, 255),
            QColor(0, 240, 255)
        ]
        
        colores_claro = [
            QColor(255, 130, 0),
            QColor(210, 0, 120),
            QColor(140, 0, 255),
            QColor(0, 150, 230)
        ]

        colores = colores_oscuro if self.modo_oscuro else colores_claro

        for p in self.particulas:
            dir_rotacion = 1 if p['capa'] % 2 == 0 else -1
            ang = p['angulo'] + (self.angulo * dir_rotacion * (4 / p['capa']))
            r = radio_base * p['radio_var'] * (0.4 + (p['capa'] * 0.25))

            x = cx + r * math.cos(ang)
            y = cy + r * math.sin(ang) * 0.75

            brillo = (math.sin(self.pulsacion + p['fase']) + 1) / 2
            alpha = int(150 + brillo * 105)
            
            color_p = QColor(colores[p['capa'] % len(colores)])
            color_p.setAlpha(alpha)

            tam = p['tamano'] * (0.8 + brillo * 0.5)

            painter.setBrush(QBrush(color_p))
            painter.drawEllipse(QPointF(x, y), tam, tam)

        nucleo_grad = QRadialGradient(cx, cy, radio_base * 0.45)
        nucleo_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        nucleo_grad.setColorAt(0.5, QColor(220, 80, 255, 180))
        nucleo_grad.setColorAt(1.0, QColor(140, 0, 255, 0))
        painter.setBrush(QBrush(nucleo_grad))
        painter.drawEllipse(QRectF(cx - radio_base * 0.45, cy - radio_base * 0.45, radio_base * 0.9, radio_base * 0.9))

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Syncra AI — Design & Visual Mentor")
        self.resize(880, 800)
        self.setMinimumSize(650, 650)
        
        self.modo_oscuro = True
        self.mensajes_historial = []
        self.mensajes = [{"role": "system", "content": MENSAJE_SISTEMA}]
        
        self.configurar_ui()
        self.aplicar_tema()

    def configurar_ui(self):
        widget_central = QWidget()
        layout_principal = QVBoxLayout(widget_central)
        layout_principal.setContentsMargins(25, 15, 25, 20)
        layout_principal.setSpacing(12)

        # Header Superior
        self.header_frame = QFrame()
        self.header_frame.setObjectName("HeaderFrame")
        layout_header = QHBoxLayout(self.header_frame)
        layout_header.setContentsMargins(20, 10, 20, 10)

        info_layout = QVBoxLayout()
        self.label_titulo = QLabel("¿En qué puedo ayudarte hoy?")
        self.label_titulo.setObjectName("TitleLabel")
        self.label_subtitulo = QLabel("● Asistente Creativo de Diseño Gráfico • Llama 3.2")
        self.label_subtitulo.setObjectName("SubTitleLabel")
        info_layout.addWidget(self.label_titulo)
        info_layout.addWidget(self.label_subtitulo)

        layout_header.addLayout(info_layout)
        layout_header.addStretch()

        self.btn_modo = QPushButton("🌙 Modo Oscuro")
        self.btn_modo.setObjectName("ActionButton")
        self.btn_modo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_modo.clicked.connect(self.alternar_modo)
        layout_header.addWidget(self.btn_modo)

        self.btn_resumen = QPushButton("✨ Resumen")
        self.btn_resumen.setObjectName("ActionButton")
        self.btn_resumen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_resumen.clicked.connect(self.generar_resumen)
        layout_header.addWidget(self.btn_resumen)

        layout_principal.addWidget(self.header_frame)

        # ORBE RADIANTE DE PARTÍCULAS
        self.orbe_particulas = OrbeParticulas()
        layout_principal.addWidget(self.orbe_particulas)

        # CHAT DISPLAY
        self.chat_display = QTextEdit()
        self.chat_display.setObjectName("ChatDisplay")
        self.chat_display.setReadOnly(True)
        layout_principal.addWidget(self.chat_display)

        # CHIPS RÁPIDOS DE DISEÑO GRÁFICO
        layout_chips = QHBoxLayout()
        layout_chips.setSpacing(8)
        
        self.chip1 = QPushButton("🎨 Paleta de Color")
        self.chip1.setObjectName("ActionButton")
        self.chip1.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip1.clicked.connect(lambda: self.insertar_sugerencia("¿Puedes sugerirme una paleta de color para un proyecto con concepto minimalista y elegante?"))

        self.chip2 = QPushButton("🖋️ Pareja Tipográfica")
        self.chip2.setObjectName("ActionButton")
        self.chip2.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip2.clicked.connect(lambda: self.insertar_sugerencia("Recomiéndame una buena combinación de fuentes Serif y Sans Serif para una marca moderna."))

        layout_chips.addWidget(self.chip1)
        layout_chips.addWidget(self.chip2)
        layout_chips.addStretch()

        layout_principal.addLayout(layout_chips)

        # ENTRADA TIPO CÁPSULA
        layout_input = QHBoxLayout()
        layout_input.setSpacing(10)

        self.input_box = QLineEdit()
        self.input_box.setObjectName("InputBox")
        self.input_box.setPlaceholderText("Consulta sobre teoría del color, tipografía, composición...")
        self.input_box.returnPressed.connect(self.procesar_entrada)

        self.btn_enviar = QPushButton("Enviar ➔")
        self.btn_enviar.setObjectName("SendButton")
        self.btn_enviar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_enviar.clicked.connect(self.procesar_entrada)

        layout_input.addWidget(self.input_box)
        layout_input.addWidget(self.btn_enviar)

        layout_principal.addLayout(layout_input)
        self.setCentralWidget(widget_central)

        self.agregar_mensaje_al_chat("Mentor", "¡Hola! Soy tu tutor de Diseño Gráfico. ¿En qué concepto visual, paleta o proyecto trabajamos hoy?")

    def alternar_modo(self):
        self.modo_oscuro = not self.modo_oscuro
        self.orbe_particulas.set_modo_oscuro(self.modo_oscuro)
        self.btn_modo.setText("🌙 Modo Oscuro" if self.modo_oscuro else "☀️ Modo Claro")
        self.aplicar_tema()
        self.redibujar_chat()

    def aplicar_tema(self):
        font_serif = "'Georgia', 'Times New Roman', serif"
        if self.modo_oscuro:
            self.setStyleSheet(f"""
                QMainWindow {{ background-color: #0A090E; }}
                QFrame#HeaderFrame {{
                    background-color: rgba(22, 18, 32, 0.85);
                    border-radius: 20px;
                    border: 1px solid rgba(180, 80, 255, 0.3);
                }}
                QTextEdit#ChatDisplay {{
                    background-color: rgba(16, 14, 24, 0.9);
                    border: 1.5px solid rgba(160, 60, 255, 0.35);
                    border-radius: 20px; padding: 16px;
                    color: #EAE6F8; font-family: {font_serif}; font-size: 14px;
                }}
                QLineEdit#InputBox {{
                    background-color: rgba(24, 20, 36, 0.95);
                    border: 1.5px solid rgba(180, 70, 255, 0.4);
                    border-radius: 22px; padding: 10px 18px;
                    font-family: {font_serif}; font-size: 13px; color: #FFFFFF;
                }}
                QLineEdit#InputBox:focus {{ border: 2px solid #FF2D92; }}
                QPushButton#SendButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9D00FF, stop:1 #FF2D92);
                    color: white; border-radius: 20px; font-weight: bold; font-family: {font_serif};
                    font-size: 13px; padding: 8px 22px; border: none;
                }}
                QPushButton#ActionButton {{
                    background-color: rgba(35, 25, 52, 0.85); color: #D8CEF8;
                    border-radius: 16px; font-family: {font_serif}; font-size: 11px; padding: 6px 14px;
                    border: 1px solid rgba(180, 80, 255, 0.4);
                }}
                QPushButton#ActionButton:hover {{ background-color: rgba(55, 35, 85, 0.95); color: #FFFFFF; }}
                QLabel#TitleLabel {{ font-family: {font_serif}; font-size: 21px; color: #FFFFFF; font-weight: bold; }}
                QLabel#SubTitleLabel {{ font-family: {font_serif}; font-size: 11px; color: #B098E0; }}
            """)
        else:
            self.setStyleSheet(f"""
                QMainWindow {{ background-color: #F7F3FC; }}
                QFrame#HeaderFrame {{
                    background-color: #FFFFFF;
                    border-radius: 20px;
                    border: 1.5px solid #E2D1F9;
                }}
                QTextEdit#ChatDisplay {{
                    background-color: #FFFFFF;
                    border: 1.5px solid #D8BFFA;
                    border-radius: 20px; padding: 16px;
                    color: #2D0C54; font-family: {font_serif}; font-size: 14px;
                }}
                QLineEdit#InputBox {{
                    background-color: #FFFFFF;
                    border: 1.5px solid #D0B0FA;
                    border-radius: 22px; padding: 10px 18px;
                    font-family: {font_serif}; font-size: 13px; color: #2D0C54;
                }}
                QLineEdit#InputBox:focus {{ border: 2px solid #9D00FF; }}
                QPushButton#SendButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8A00FF, stop:1 #E6007E);
                    color: white; border-radius: 20px; font-weight: bold; font-family: {font_serif};
                    font-size: 13px; padding: 8px 22px; border: none;
                }}
                QPushButton#ActionButton {{
                    background-color: #F2E8FF; color: #4A1282;
                    border-radius: 16px; font-family: {font_serif}; font-size: 11px; padding: 6px 14px;
                    border: 1px solid #DDB8FF;
                }}
                QPushButton#ActionButton:hover {{ background-color: #E6D2FF; color: #2D0C54; }}
                QLabel#TitleLabel {{ font-family: {font_serif}; font-size: 21px; color: #2D0C54; font-weight: bold; }}
                QLabel#SubTitleLabel {{ font-family: {font_serif}; font-size: 11px; color: #6B21A8; }}
            """)

    def insertar_sugerencia(self, texto):
        self.input_box.setText(texto)
        self.input_box.setFocus()

    def agregar_mensaje_al_chat(self, remitente, texto):
        self.mensajes_historial.append((remitente, texto))
        self.redibujar_chat()

    def redibujar_chat(self):
        self.chat_display.clear()
        font_serif = "Georgia, 'Times New Roman', serif"
        for remitente, texto in self.mensajes_historial:
            if self.modo_oscuro:
                bg_usr, border_usr, fg_usr = "#28183B", "#FF2D92", "#FFFFFF"
                bg_ai, border_ai, fg_ai = "#151222", "rgba(180, 80, 255, 0.35)", "#EAE6F8"
            else:
                bg_usr, border_usr, fg_usr = "#F3E8FF", "#C084FC", "#3B0764"
                bg_ai, border_ai, fg_ai = "#FAF7FE", "#E9D5FF", "#2E1065"

            if remitente == "Usuario":
                html = f"""
                <div style='margin-bottom: 12px; text-align: right; font-family: {font_serif};'>
                    <span style='color: #FF2D92; font-weight: bold; font-size: 10px; letter-spacing: 1px;'>TÚ</span><br>
                    <div style='background-color: {bg_usr}; color: {fg_usr}; padding: 10px 15px; border-radius: 14px; border: 1px solid {border_usr}; display: inline-block; max-width: 80%; margin-top: 3px; font-size: 13.5px;'>
                        {texto}
                    </div>
                </div>
                """
            elif remitente == "Mentor":
                texto_formateado = texto.replace('\n', '<br>')
                color_tag = "#C080FF" if self.modo_oscuro else "#6B21A8"
                html = f"""
                <div style='margin-bottom: 14px; font-family: {font_serif};'>
                    <span style='color: {color_tag}; font-weight: bold; font-size: 10px; letter-spacing: 1px;'>SYNCRA DESIGN AI</span><br>
                    <div style='background-color: {bg_ai}; color: {fg_ai}; padding: 12px 16px; border-radius: 14px; border: 1px solid {border_ai}; margin-top: 3px; font-size: 13.5px; line-height: 1.4;'>
                        {texto_formateado}
                    </div>
                </div>
                """
            else:
                color_sys = "#A088C8" if self.modo_oscuro else "#6B21A8"
                html = f"""
                <div style='margin-bottom: 10px; text-align: center; font-family: {font_serif};'>
                    <span style='color: {color_sys}; font-size: 11px;'>{texto}</span>
                </div>
                """
            self.chat_display.append(html)

    def bloquear_interfaz(self, bloqueada):
        self.input_box.setEnabled(not bloqueada)
        self.btn_enviar.setEnabled(not bloqueada)
        self.btn_resumen.setEnabled(not bloqueada)
        self.orbe_particulas.set_estado_pensando(bloqueada)

    def procesar_entrada(self):
        texto = self.input_box.text().strip()
        if not texto:
            return

        self.input_box.clear()
        self.agregar_mensaje_al_chat("Usuario", texto)
        self.mensajes.append({"role": "user", "content": texto})

        self.bloquear_interfaz(True)
        self.label_subtitulo.setText("● Elaborando respuesta creativa con Ollama...")

        self.hilo = HiloOllama(self.mensajes)
        self.hilo.respuesta_lista.connect(self.al_recibir_respuesta)
        self.hilo.error_ocurrido.connect(self.al_ocurrir_error)
        self.hilo.start()

    def al_recibir_respuesta(self, contenido):
        self.mensajes.append({"role": "assistant", "content": contenido})
        self.agregar_mensaje_al_chat("Mentor", contenido)
        self.label_subtitulo.setText("● Asistente Creativo de Diseño Gráfico • Llama 3.2")
        self.bloquear_interfaz(False)

    def al_ocurrir_error(self, error):
        self.agregar_mensaje_al_chat("Sistema", f"Error de comunicación con Ollama: {error}")
        self.label_subtitulo.setText("● Error de Conexión")
        self.mensajes.pop()
        self.bloquear_interfaz(False)

    def generar_resumen(self):
        if len(self.mensajes) <= 1:
            QMessageBox.information(self, "Resumen", "No hay interacciones para resumir.")
            return

        self.bloquear_interfaz(True)
        self.label_subtitulo.setText("● Generando resumen de la sesión creativa...")

        peticion = self.mensajes.copy()
        peticion.append({
            "role": "user",
            "content": "Sintetiza la conversación en un breve resumen de un solo párrafo destacando los conceptos creativos, paletas o decisiones de diseño discutidas."
        })

        self.hilo_resumen = HiloOllama(peticion)
        self.hilo_resumen.respuesta_lista.connect(self.mostrar_resumen)
        self.hilo_resumen.error_ocurrido.connect(self.al_ocurrir_error)
        self.hilo_resumen.start()

    def mostrar_resumen(self, resumen):
        QMessageBox.information(self, "Resumen de la Sesión Creativa", resumen)
        self.label_subtitulo.setText("● Asistente Creativo de Diseño Gráfico • Llama 3.2")
        self.bloquear_interfaz(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec())