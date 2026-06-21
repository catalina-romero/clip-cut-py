import os
import sys
import time
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, List, Tuple
import dearpygui.dearpygui as dpg

from domain.entities import Proyecto, Video, Clip
from domain.interfaces import VideoPlayerInterface, VideoProcessorInterface, ProjectRepositoryInterface
from use_cases.clip_use_cases import AgregarClipUseCase, EliminarClipUseCase
from use_cases.project_use_cases import GuardarProyectoUseCase, CargarProyectoUseCase
from use_cases.export_use_cases import ExportarClipUseCase, ExportarTodosLosClipsUseCase

class VideoEditorApp:
    """Clase principal de la UI que orquesta Dear PyGui y los Casos de Uso."""

    def __init__(self, player: VideoPlayerInterface, processor: VideoProcessorInterface, repository: ProjectRepositoryInterface):
        self.player = player
        self.processor = processor
        self.repository = repository
        self.proyecto = Proyecto()

        # Casos de Uso
        self.agregar_clip_uc = AgregarClipUseCase()
        self.eliminar_clip_uc = EliminarClipUseCase()
        self.guardar_proyecto_uc = GuardarProyectoUseCase(repository)
        self.cargar_proyecto_uc = CargarProyectoUseCase(repository)
        self.exportar_clip_uc = ExportarClipUseCase(processor)
        self.exportar_todos_uc = ExportarTodosLosClipsUseCase(processor)

        # Estado local de reproducción y edición
        self.current_time = 0.0
        self.total_duration = 0.0
        self.clip_start: Optional[float] = None
        self.clip_end: Optional[float] = None
        self.dragging_slider = False
        self.target_delete_clip: Optional[Clip] = None
        
        # Bandera lógica para bloquear atajos cuando hay un diálogo emergente
        self.modal_active = False

        # Carpetas y colas de carga asíncrona para miniaturas
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.temp_thumbs_dir = os.path.join(root_dir, "temp_thumbs")
        self.thumbs_to_load: List[Tuple[str, int]] = []
        self.clip_thumbs_to_load: List[Tuple[str, str]] = []

        # Inicializar y limpiar directorio temporal de miniaturas
        if not os.path.exists(self.temp_thumbs_dir):
            os.makedirs(self.temp_thumbs_dir, exist_ok=True)
        else:
            # Limpiar anteriores
            for f in os.listdir(self.temp_thumbs_dir):
                try:
                    os.remove(os.path.join(self.temp_thumbs_dir, f))
                except Exception:
                    pass

    def run(self):
        dpg.create_context()
        dpg.create_viewport(title="ClipCutPy", width=1280, height=720, min_width=800, min_height=600)
        dpg.setup_dearpygui()

        self._build_theme()
        self._build_ui()
        dpg.show_viewport()

        # Obtener HWND nativo del viewport principal para emparentar MPV
        import win32gui
        hwnd = win32gui.FindWindow(None, "ClipCutPy")
        if hwnd:
            # Inicializar el reproductor MPV incrustado
            self.player.embed_in_window(hwnd, 10, 35, 800, 350)
            
            # Deshabilitar ventana de MPV en Win32 para que no robe el foco del teclado
            win32gui.EnableWindow(self.player.child_hwnd, False)

            # Configurar callbacks del reproductor
            self.player.set_on_time_change_callback(self._on_time_change_from_mpv)
            self.player.set_on_video_loaded_callback(self._on_video_loaded_from_mpv)
        else:
            self._show_error("No se pudo obtener el manejador de la ventana principal de la aplicación.")

        # Registrar eventos de cambio de tamaño del viewport
        dpg.set_viewport_resize_callback(self._on_viewport_resize)
        # Forzar un primer redimensionamiento manual para colocar los elementos
        self._on_viewport_resize()

        # Registrar atajos de teclado globales
        self._register_keyboard_shortcuts()

        # Iniciar el bucle de renderizado personalizado
        self._main_loop()

        # Liberar recursos al salir
        self.player.shutdown()
        dpg.destroy_context()

    def _main_loop(self):
        """Bucle principal de ejecución a 60 FPS estables."""
        while dpg.is_dearpygui_running():
            # Detectar teclas espacio y flechas de forma directa y global para evitar que
            # Dear PyGui las devore cuando hay widgets enfocados
            if not self.modal_active and self.proyecto.video:
                if dpg.is_key_pressed(dpg.mvKey_Spacebar):
                    self._btn_toggle_play()
                elif dpg.is_key_pressed(dpg.mvKey_Left):
                    self._seek_relative(-1.0)
                elif dpg.is_key_pressed(dpg.mvKey_Right):
                    self._seek_relative(1.0)

            # Si el video se está reproduciendo, actualizamos la posición del slider desde la posición del reproductor
            if self.proyecto.video and self.player.is_playing() and not self.dragging_slider:
                self.current_time = self.player.get_current_time()
                self._update_timeline_ui()

            # Cargar texturas de la tira de la línea de tiempo cargadas de forma asíncrona
            if self.thumbs_to_load:
                thumb_path, idx = self.thumbs_to_load.pop(0)
                try:
                    width, height, channels, data = dpg.load_image(thumb_path)
                    tex_tag = f"timeline_thumb_tex_{idx}"
                    if dpg.does_item_exist(tex_tag):
                        dpg.delete_item(tex_tag)
                    with dpg.texture_registry():
                        dpg.add_static_texture(width=width, height=height, default_value=data, tag=tex_tag)
                    if dpg.does_item_exist(f"timeline_thumb_img_{idx}"):
                        dpg.configure_item(f"timeline_thumb_img_{idx}", texture_tag=tex_tag)
                except Exception as e:
                    print(f"Error al cargar textura de miniatura temporal: {e}")

            # Cargar texturas de miniaturas de clips cargados de forma asíncrona
            if self.clip_thumbs_to_load:
                clip_id, thumb_path = self.clip_thumbs_to_load.pop(0)
                try:
                    width, height, channels, data = dpg.load_image(thumb_path)
                    tex_tag = f"clip_thumb_tex_{clip_id}"
                    if dpg.does_item_exist(tex_tag):
                        dpg.delete_item(tex_tag)
                    with dpg.texture_registry():
                        dpg.add_static_texture(width=width, height=height, default_value=data, tag=tex_tag)
                    # Reconstruir la lista para mostrar la imagen recién cargada
                    self._rebuild_clip_list_ui()
                except Exception as e:
                    print(f"Error al cargar textura de clip temporal: {e}")

            dpg.render_dearpygui_frame()

    def _on_time_change_from_mpv(self, t: float):
        """Callback gatillado por MPV cuando avanza el tiempo de reproducción."""
        if not self.dragging_slider:
            self.current_time = t

    def _on_video_loaded_from_mpv(self, duration: float):
        """Callback gatillado por MPV cuando el video se carga exitosamente."""
        self.total_duration = duration
        if self.proyecto.video:
            self.proyecto.video.duration = duration
        self.current_time = 0.0
        self.clip_start = None
        self.clip_end = None
        
        # Poner todas las miniaturas de la línea de tiempo en placeholder mientras se extraen
        for i in range(8):
            if dpg.does_item_exist(f"timeline_thumb_img_{i}"):
                dpg.configure_item(f"timeline_thumb_img_{i}", texture_tag="placeholder_texture")

        # Lanzar la extracción asíncrona de miniaturas en la línea de tiempo
        if self.proyecto.video:
            t = threading.Thread(target=self._generate_timeline_thumbnails, args=(self.proyecto.video.filepath,), daemon=True)
            t.start()

        # Actualizar UI en el hilo principal
        self._update_timeline_ui()
        self._draw_timeline_visuals()

    def _on_viewport_resize(self):
        """Ajusta dinámicamente la disposición en rejilla (grid) de la UI."""
        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()

        padding = 10
        top_y = 30  # Espacio para el menú principal plano

        # Panel izquierdo (Video + Controles): 72% de ancho
        left_w = int(vw * 0.72) - padding * 2
        # Panel derecho (Clips): 28% de ancho
        right_w = int(vw * 0.28) - padding

        # Altura disponible total
        total_h = vh - top_y - padding * 4

        # Altura fija para la caja de controles al fondo (no escroleable) para acomodar todos los controles sin aplastarlos
        controls_h = 150
        
        # El video ocupa el espacio restante en el medio (se elimina cabecera redundante)
        video_h = total_h - controls_h - padding
        video_h = max(200, video_h) # Altura mínima segura

        # Ajustar dimensiones de contenedores en Dear PyGui
        # Video arriba
        dpg.configure_item("video_container", pos=(padding, top_y), width=left_w, height=video_h)
        # Controles abajo
        dpg.configure_item("controls_container", pos=(padding, top_y + video_h + padding), width=left_w, height=controls_h)
        # Clips a la derecha ocupando toda la altura
        dpg.configure_item("clips_container", pos=(padding + left_w + padding, top_y), width=right_w, height=total_h)

        # Ajustar tamaño de subventana de MPV (con offsets para conservar el borde del contenedor DPG)
        if self.player:
            self.player.resize_window(padding + 8, top_y + 8, left_w - 16, video_h - 16)

        # Ajustar tamaño de miniaturas de la línea de tiempo de forma adaptativa
        thumb_w = int(left_w / 8.0) - 4
        thumb_h = int(thumb_w * 9 / 16)
        thumb_h = min(35, thumb_h)
        for i in range(8):
            if dpg.does_item_exist(f"timeline_thumb_img_{i}"):
                dpg.configure_item(f"timeline_thumb_img_{i}", width=thumb_w, height=thumb_h)

        # Redibujar la barra visual de la línea de tiempo
        self._draw_timeline_visuals()

    def _build_theme(self):
        """Configura un estilo oscuro premium y limpio."""
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                # Colores de ventanas y paneles
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (12, 12, 12))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 20, 20))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (32, 32, 32))
                
                # Colores de campos de entrada y sliders
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (26, 26, 26))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (36, 36, 36))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (46, 46, 46))

                # Selección y Resaltados
                dpg.add_theme_color(dpg.mvThemeCol_Header, (45, 52, 64))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (60, 70, 85))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (70, 85, 105))
                
                # Deslizador Principal
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (46, 204, 113))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (39, 174, 96))

                # Estilos visuales redondeados premium
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8.0, 8.0)

        dpg.bind_theme(global_theme)

        # Generador de temas para botones individuales de estética premium
        def create_button_theme(color, hover_color, active_color):
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, color)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover_color)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active_color)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.5, 0.5)
            return theme

        # Paleta de Colores de Botones Premium
        self.play_btn_theme = create_button_theme((41, 128, 185), (52, 152, 219), (31, 97, 141))       # Azul
        self.start_btn_theme = create_button_theme((39, 174, 96), (46, 204, 113), (30, 130, 70))      # Verde
        self.end_btn_theme = create_button_theme((192, 57, 43), (231, 76, 60), (150, 40, 30))        # Rojo
        self.discard_btn_theme = create_button_theme((127, 140, 141), (149, 165, 166), (95, 109, 110)) # Gris
        self.add_btn_theme = create_button_theme((142, 68, 173), (155, 89, 182), (108, 52, 137))      # Morado
        self.export_all_btn_theme = create_button_theme((211, 84, 0), (230, 126, 34), (160, 60, 0))   # Naranja/Oro

    def _build_ui(self):
        """Define la estructura visual y controles de la aplicación."""
        # Textura por defecto para placeholders de miniaturas
        placeholder_data = [0.1, 0.1, 0.1, 1.0] * (160 * 90) # Gris oscuro
        with dpg.texture_registry():
            dpg.add_static_texture(width=160, height=90, default_value=placeholder_data, tag="placeholder_texture")

        # Menú Superior Plano sin submenús (Resuelve el bug de ocultamiento por Z-Order)
        with dpg.viewport_menu_bar():
            dpg.add_menu_item(label="Abrir Video", callback=self._menu_abrir_video)
            dpg.add_menu_item(label="Cargar Proyecto", callback=self._menu_cargar_proyecto)
            dpg.add_menu_item(label="Guardar Proyecto", callback=self._menu_guardar_proyecto)
            dpg.add_menu_item(label="Salir", callback=lambda: sys.exit(0))

        # Ventana Principal Invisible
        with dpg.window(tag="primary_window", no_title_bar=True, no_resize=True, no_move=True, no_scrollbar=True):
            dpg.set_primary_window("primary_window", True)

            # 1. Panel Contenedor de Video (Arriba)
            with dpg.child_window(tag="video_container", pos=(10, 30)):
                dpg.add_text("Abra un archivo de video para comenzar.", tag="placeholder_text", pos=(30, 30), color=(180, 180, 180))

            # 2. Panel de Controles Inferior (Debajo del video, estático sin scroll)
            with dpg.child_window(tag="controls_container", pos=(10, 390), no_scrollbar=True):
                # Tira de miniaturas de la línea de tiempo (Filmstrip)
                with dpg.group(horizontal=True, tag="timeline_thumbs_container"):
                    for i in range(8):
                        dpg.add_image("placeholder_texture", tag=f"timeline_thumb_img_{i}", width=100, height=56)

                # Slider de Línea de Tiempo Principal y Tiempos en la misma línea para ahorrar espacio
                with dpg.group(horizontal=True):
                    dpg.add_slider_double(
                        label="",
                        tag="timeline_slider",
                        min_value=0.0,
                        max_value=1.0,
                        default_value=0.0,
                        width=-420,
                        callback=self._on_timeline_slider_change,
                        user_data="drag"
                    )
                    dpg.add_text("00:00:00.000 / 00:00:00.000", tag="time_text", color=(255, 255, 255))
                    dpg.add_spacer(width=10)
                    dpg.add_text("In:", color=(150, 150, 150))
                    dpg.add_text("No fijado", tag="start_marker_text", color=(46, 204, 113))
                    dpg.add_spacer(width=10)
                    dpg.add_text("Out:", color=(150, 150, 150))
                    dpg.add_text("No fijado", tag="end_marker_text", color=(231, 76, 60))

                # Canvas de visualización de Marcadores
                with dpg.group():
                    dpg.add_drawlist(width=1, height=12, tag="timeline_drawlist")

                # Fila de Botones Digitales con Estética Premium
                with dpg.group(horizontal=True):
                    # Reproducir/Pausar
                    dpg.add_button(label="Reproducir/Pausar", callback=self._btn_toggle_play, width=130)
                    dpg.bind_item_theme(dpg.last_item(), self.play_btn_theme)
                    
                    dpg.add_spacer(width=5)

                    # Fijar Inicio [I]
                    dpg.add_button(label="Fijar Inicio [I]", callback=self._btn_mark_start, width=120)
                    dpg.bind_item_theme(dpg.last_item(), self.start_btn_theme)

                    # Fijar Fin [O]
                    dpg.add_button(label="Fijar Fin [O]", callback=self._btn_mark_end, width=120)
                    dpg.bind_item_theme(dpg.last_item(), self.end_btn_theme)

                    dpg.add_spacer(width=5)
                    
                    # Descartar
                    dpg.add_button(label="Descartar Selección [Esc]", callback=self._btn_clear_markers, width=160)
                    dpg.bind_item_theme(dpg.last_item(), self.discard_btn_theme)
                    
                    # Añadir Clip
                    dpg.add_button(label="Añadir a la Lista [Enter]", callback=self._btn_add_clip, width=160)
                    dpg.bind_item_theme(dpg.last_item(), self.add_btn_theme)

                dpg.add_spacer(height=3)
                # Leyenda de Atajos
                dpg.add_text("Atajos: [Espacio] Play/Pause | [←] / [→] +-1s | [I] Inicio | [O] Fin | [Enter] Guardar | [Esc] Descartar", color=(90, 90, 90))

            # 3. Panel de Gestor de Clips (Derecho)
            with dpg.child_window(tag="clips_container", pos=(930, 30), no_scrollbar=True):
                # Botón Exportar Todo Destacado
                dpg.add_button(label="EXPORTAR TODOS LOS CLIPS", callback=self._btn_exportar_todos, width=-1, height=40)
                dpg.bind_item_theme(dpg.last_item(), self.export_all_btn_theme)

                dpg.add_separator()
                dpg.add_text("Clips de la Sesión:", color=(160, 160, 160))
                
                # Lista interna scrolleable
                with dpg.child_window(tag="clip_list_window", width=-1, height=-65, border=False):
                    dpg.add_text("No hay clips creados.", tag="no_clips_text", color=(100, 100, 100))

                # Barra de estado inferior en el panel de clips
                dpg.add_separator()
                dpg.add_text("Listo", tag="status_bar", color=(150, 150, 150))

        # --- Ventanas Modales de Confirmación y Alertas ---
        # Modal Confirmación de Eliminación
        with dpg.window(label="Confirmar Eliminación", modal=True, show=False, id="confirm_delete_modal", no_resize=True, no_move=True):
            dpg.add_text("¿Está seguro de que desea eliminar este clip?", id="confirm_delete_text")
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Sí, eliminar", callback=self._modal_confirm_delete_yes, width=120)
                dpg.add_button(label="Cancelar", callback=lambda: self._close_delete_modal(), width=120)

        # Modal de Progreso para Exportación en Lote
        with dpg.window(label="Exportando Clips...", modal=True, show=False, id="progress_modal", no_resize=True, no_move=True, no_close=True):
            dpg.add_text("Procesando cola de exportación...", tag="progress_modal_text")
            dpg.add_spacer(height=10)
            dpg.add_progress_bar(tag="progress_modal_bar", width=300, default_value=0.0)

    # --- Lógica de Timeline ---

    def _update_timeline_ui(self):
        """Actualiza el valor, los límites y el formato digital del slider de tiempo."""
        if self.total_duration <= 0.0:
            return

        min_val = 0.0
        max_val = self.total_duration

        # Configurar límites del slider
        dpg.configure_item("timeline_slider", min_value=min_val, max_value=max_val)
        dpg.set_value("timeline_slider", self.current_time)

        # Actualizar leyenda digital
        dpg.set_value("time_text", f"{self._format_time(self.current_time)} / {self._format_time(self.total_duration)}")

        # Redibujar los marcadores en la barra visual
        self._draw_timeline_visuals()

    def _draw_timeline_visuals(self):
        """Dibuja en el Canvas los marcadores y la posición actual."""
        if self.total_duration <= 0.0:
            return

        canvas_tag = "timeline_drawlist"
        # Obtener el ancho real del contenedor de controles para ajustar el canvas
        canvas_width = dpg.get_item_width("controls_container") - 16
        if canvas_width <= 0:
            return

        # Ajustar ancho del canvas en Dear PyGui
        dpg.configure_item(canvas_tag, width=canvas_width)
        dpg.delete_item(canvas_tag, children_only=True)

        min_val = 0.0
        max_val = self.total_duration
        span = max_val - min_val
        if span <= 0:
            return

        # Función auxiliar para convertir segundos a píxeles
        def to_pixel(t: float) -> float:
            return ((t - min_val) / span) * canvas_width

        # 1. Dibujar fondo de la barra
        dpg.draw_rectangle([0, 2], [canvas_width, 10], color=(50, 50, 50), fill=(28, 28, 28), parent=canvas_tag)

        # 2. Dibujar zona de selección si ambos marcadores están puestos
        if self.clip_start is not None and self.clip_end is not None:
            px_start = to_pixel(self.clip_start)
            px_end = to_pixel(self.clip_end)
            c_start = max(0.0, min(canvas_width, px_start))
            c_end = max(0.0, min(canvas_width, px_end))
            if c_start < c_end:
                # Rectángulo translúcido verde esmeralda
                dpg.draw_rectangle([c_start, 2], [c_end, 10], color=(46, 204, 113, 200), fill=(46, 204, 113, 40), parent=canvas_tag)

        # 3. Dibujar marcador de Inicio (Línea vertical verde)
        if self.clip_start is not None:
            px = to_pixel(self.clip_start)
            if 0.0 <= px <= canvas_width:
                dpg.draw_line([px, 0], [px, 12], color=(46, 204, 113), thickness=2, parent=canvas_tag)

        # 4. Dibujar de Fin (Línea vertical roja)
        if self.clip_end is not None:
            px = to_pixel(self.clip_end)
            if 0.0 <= px <= canvas_width:
                dpg.draw_line([px, 0], [px, 12], color=(231, 76, 60), thickness=2, parent=canvas_tag)

        # 5. Dibujar cursor de reproducción (Línea vertical blanca)
        px_curr = to_pixel(self.current_time)
        if 0.0 <= px_curr <= canvas_width:
            dpg.draw_line([px_curr, 0], [px_curr, 12], color=(255, 255, 255), thickness=2, parent=canvas_tag)

    def _on_timeline_slider_change(self):
        """Acción cuando el usuario desliza la línea de tiempo."""
        self.dragging_slider = True
        new_time = dpg.get_value("timeline_slider")
        self.current_time = new_time
        self.player.seek(new_time)
        self.dragging_slider = False
        self._update_timeline_ui()
        dpg.focus_item("primary_window")

    # --- Gestión de Atajos y Botones de Reproducción ---

    def _register_keyboard_shortcuts(self):
        """Registra controladores de eventos de teclado rápidos en Dear PyGui."""
        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self._on_key_press)

    def _on_key_press(self, sender, app_data):
        key = app_data
        
        # Ignorar atajos si hay algún cuadro de diálogo o confirmación modal activo
        if self.modal_active:
            return

        # Teclas mapeadas por su código virtual nativo (Windows) y constantes de Dear PyGui
        # Nota: Espacio y Flechas se gestionan en el bucle principal (_main_loop) usando
        # dpg.is_key_pressed para evitar conflictos de foco con sliders y botones.
            
        # 1. Fijar marcador de Inicio: I / i (73, 105, dpg.mvKey_I)
        if key == 73 or key == 105 or key == dpg.mvKey_I:
            self._btn_mark_start()
            
        # 2. Fijar marcador de Fin: O / o (79, 111, dpg.mvKey_O)
        elif key == 79 or key == 111 or key == dpg.mvKey_O:
            self._btn_mark_end()
            
        # 3. Añadir clip a la lista: Enter (13), A / a (65, 97, dpg.mvKey_Return, dpg.mvKey_A)
        elif key == 13 or key == 65 or key == 97 or key == dpg.mvKey_Return or key == dpg.mvKey_A:
            self._btn_add_clip()
            
        # 4. Descartar selección: Escape (27), D / d (68, 100, dpg.mvKey_Escape, dpg.mvKey_D)
        elif key == 27 or key == 68 or key == 100 or key == dpg.mvKey_Escape or key == dpg.mvKey_D:
            self._btn_clear_markers()

    def _seek_relative(self, offset: float):
        """Avanza o retrocede de forma relativa en el video."""
        if not self.proyecto.video:
            return
        target = max(0.0, min(self.total_duration, self.current_time + offset))
        self.current_time = target
        self.player.seek(target)
        self._update_timeline_ui()

    def _btn_toggle_play(self):
        if not self.proyecto.video:
            return
        if self.player.is_playing():
            self.player.pause()
            dpg.set_value("status_bar", "Pausado")
        else:
            self.player.play()
            dpg.set_value("status_bar", "Reproduciendo...")
        dpg.focus_item("primary_window")

    def _btn_mark_start(self):
        if not self.proyecto.video:
            return
        self.clip_start = self.current_time
        dpg.set_value("start_marker_text", self._format_time(self.clip_start))
        self._update_timeline_ui()
        dpg.focus_item("primary_window")

    def _btn_mark_end(self):
        if not self.proyecto.video:
            return
        self.clip_end = self.current_time
        dpg.set_value("end_marker_text", self._format_time(self.clip_end))
        self._update_timeline_ui()
        dpg.focus_item("primary_window")

    def _btn_clear_markers(self):
        self.clip_start = None
        self.clip_end = None
        dpg.set_value("start_marker_text", "No fijado")
        dpg.set_value("end_marker_text", "No fijado")
        self._update_timeline_ui()
        dpg.focus_item("primary_window")

    # --- Gestión de Clips de Sesión ---

    def _btn_add_clip(self):
        if not self.proyecto.video:
            self._show_error("No hay ningún video cargado en la sesión.")
            return

        if self.clip_start is None or self.clip_end is None:
            self._show_error("Debe fijar tanto el marcador de Inicio como el de Fin para añadir un clip.")
            return

        try:
            # Obtener el nombre del video original sin extensión como prefijo para los clips
            video_basename = os.path.basename(self.proyecto.video.filepath)
            video_name, _ = os.path.splitext(video_basename)
            # Sanitizar nombre (reemplazar caracteres que no sean alfanuméricos por guion bajo)
            clean_prefix = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in video_name)
            while '__' in clean_prefix:
                clean_prefix = clean_prefix.replace('__', '_')
            clean_prefix = clean_prefix.strip('_')

            nuevo_clip = self.agregar_clip_uc.ejecutar(
                proyecto=self.proyecto,
                start_seconds=self.clip_start,
                end_seconds=self.clip_end,
                name_prefix=clean_prefix
            )
            dpg.set_value("status_bar", f"Añadido: {nuevo_clip.name}")
            
            # Lanzar extracción asíncrona de la miniatura para el listado de clips
            t = threading.Thread(target=self._generate_clip_thumbnail, args=(nuevo_clip,), daemon=True)
            t.start()

            self._btn_clear_markers()
            self._rebuild_clip_list_ui()
        except Exception as e:
            self._show_error(f"Error al añadir clip: {str(e)}")

    def _rebuild_clip_list_ui(self):
        """Redibuja de forma dinámica el listado vertical en el Panel Derecho con miniaturas y manejadores de click."""
        dpg.delete_item("clip_list_window", children_only=True)

        if not self.proyecto.clips:
            dpg.add_text("No hay clips creados.", tag="no_clips_text", parent="clip_list_window", color=(100, 100, 100))
            return

        for clip in self.proyecto.clips:
            clip_tag = f"clip_item_{clip.id}"
            row_tag = f"clip_row_{clip.id}"
            tex_tag = f"clip_thumb_tex_{clip.id}"
            
            has_tex = dpg.does_item_exist(tex_tag)
            
            with dpg.group(parent="clip_list_window", tag=clip_tag):
                with dpg.group(horizontal=True, tag=row_tag):
                    # Dibujar miniatura (o placeholder si aún se está extrayendo)
                    img_item = dpg.add_image(tex_tag if has_tex else "placeholder_texture", width=80, height=45)
                    
                    with dpg.group() as text_group:
                        title_item = dpg.add_text(clip.name, color=(255, 255, 255))
                        dur_item = dpg.add_text(f"Duración: {self._format_time(clip.duration)}", color=(150, 150, 150))

                dpg.add_spacer(height=3)
                dpg.add_separator()
                dpg.add_spacer(height=3)

                # Registro de gestor de click izquierdo (Seek instantáneo)
                handler_tag = f"clip_handler_{clip.id}"
                if dpg.does_item_exist(handler_tag):
                    dpg.delete_item(handler_tag)
                    
                with dpg.item_handler_registry(tag=handler_tag):
                    dpg.add_item_clicked_handler(button=dpg.mvMouseButton_Left, callback=self._on_clip_item_left_click, user_data=clip)
                
                # Vincular el handler a todos los elementos del renglón para que sea súper clickeable
                dpg.bind_item_handler_registry(row_tag, handler_tag)
                dpg.bind_item_handler_registry(img_item, handler_tag)
                dpg.bind_item_handler_registry(title_item, handler_tag)
                dpg.bind_item_handler_registry(dur_item, handler_tag)
                dpg.bind_item_handler_registry(text_group, handler_tag)

                # Crear menú contextual de click derecho (vincular a la fila principal)
                with dpg.popup(parent=row_tag, mousebutton=dpg.mvMouseButton_Right):
                    dpg.add_menu_item(label="Exportar este clip...", callback=self._menu_exportar_clip_individual, user_data=clip)
                    dpg.add_menu_item(label="Eliminar clip", callback=self._menu_confirmar_eliminar_clip, user_data=clip)

    def _on_clip_item_left_click(self, sender, app_data, user_data: Clip):
        """Seek instantáneo al segundo de inicio del clip seleccionado."""
        clip = user_data
        self.current_time = clip.start_seconds
        self.player.seek(clip.start_seconds)
        self.player.pause()  # pausar para previsualizar el frame de inicio
        self._update_timeline_ui()
        dpg.set_value("status_bar", f"Previsualizando {clip.name}")
        dpg.focus_item("primary_window")

    def _menu_confirmar_eliminar_clip(self, sender, app_data, user_data: Clip):
        """Muestra el modal de confirmación antes de remover el clip."""
        self.target_delete_clip = user_data
        self.modal_active = True
        dpg.set_value("confirm_delete_text", f"¿Está seguro de que desea eliminar '{user_data.name}'?")
        dpg.configure_item("confirm_delete_modal", show=True)

    def _close_delete_modal(self):
        self.modal_active = False
        dpg.configure_item("confirm_delete_modal", show=False)

    def _modal_confirm_delete_yes(self):
        """Acción cuando el usuario confirma la eliminación del clip."""
        self._close_delete_modal()
        if self.target_delete_clip:
            self.eliminar_clip_uc.ejecutar(self.proyecto, self.target_delete_clip.id)
            
            # Borrar la miniatura física si existe
            thumb_path = os.path.join(self.temp_thumbs_dir, f"clip_{self.target_delete_clip.id}.jpg")
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass
            
            # Borrar textura registrada
            tex_tag = f"clip_thumb_tex_{self.target_delete_clip.id}"
            if dpg.does_item_exist(tex_tag):
                dpg.delete_item(tex_tag)

            dpg.set_value("status_bar", f"Eliminado: {self.target_delete_clip.name}")
            self.target_delete_clip = None
            self._rebuild_clip_list_ui()

    # --- Casos de Uso de Exportación ---

    def _menu_exportar_clip_individual(self, sender, app_data, user_data: Clip):
        """Abre el diálogo para guardar un clip e inicia su corte por FFmpeg."""
        clip = user_data
        if not self.proyecto.video:
            return

        # Obtener la extensión original del video
        _, ext = os.path.splitext(self.proyecto.video.filepath)
        if not ext:
            ext = ".mp4"

        # Diálogo nativo para seleccionar destino
        root = tk.Tk()
        root.withdraw()
        dest_path = filedialog.asksaveasfilename(
            title=f"Exportar {clip.name}",
            initialfile=f"{clip.name}{ext}",
            filetypes=[("Archivos de Video", f"*{ext}"), ("Todos", "*.*")]
        )
        root.destroy()

        if not dest_path:
            return  # Cancelado por el usuario

        dpg.set_value("status_bar", f"Exportando {clip.name}...")
        
        # Ejecutar caso de uso asíncrono
        try:
            self.processor.cortar_clip(
                video_path=self.proyecto.video.filepath,
                start=clip.start_seconds,
                end=clip.end_seconds,
                output_path=dest_path,
                on_success=lambda p: dpg.set_value("status_bar", f"¡Exportación exitosa!: {os.path.basename(p)}"),
                on_error=lambda err: self._show_error(f"Fallo al exportar {clip.name}.\n{err}")
            )
        except Exception as e:
            self._show_error(f"Error al iniciar exportación: {str(e)}")

    def _btn_exportar_todos(self):
        """Exporta secuencialmente toda la cola de clips a un directorio seleccionado."""
        if not self.proyecto.video:
            self._show_error("No hay ningún video cargado.")
            return

        if not self.proyecto.clips:
            self._show_error("No hay clips en la lista para exportar.")
            return

        # Diálogo nativo para seleccionar la carpeta destino
        root = tk.Tk()
        root.withdraw()
        output_dir = filedialog.askdirectory(title="Seleccionar Carpeta para Guardar Todos los Clips")
        root.destroy()

        if not output_dir:
            return

        # Mostrar ventana modal de progreso y activar bloqueo de atajos
        self.modal_active = True
        dpg.configure_item("progress_modal", show=True)
        dpg.set_value("progress_modal_bar", 0.0)
        dpg.set_value("progress_modal_text", "Preparando cola de corte...")

        total_clips = len(self.proyecto.clips)
        
        # Procesar en cola en un hilo secundario para no colgar la UI del modal de progreso
        def worker_cola():
            errors = []
            for i, clip in enumerate(self.proyecto.clips):
                dpg.set_value("progress_modal_text", f"Procesando clip {i+1} de {total_clips}:\n'{clip.name}'")
                
                _, ext = os.path.splitext(self.proyecto.video.filepath)
                if not ext:
                    ext = ".mp4"
                dest_path = os.path.join(output_dir, f"{clip.name}{ext}")

                # Bandera de sincronización para esperar que termine cada proceso FFmpeg asíncrono
                done_event = threading.Event()

                def success_cb(p):
                    done_event.set()

                def error_cb(err):
                    errors.append(f"{clip.name}: {err}")
                    done_event.set()

                # Llamar al procesador
                self.processor.cortar_clip(
                    video_path=self.proyecto.video.filepath,
                    start=clip.start_seconds,
                    end=clip.end_seconds,
                    output_path=dest_path,
                    on_success=success_cb,
                    on_error=error_cb
                )

                # Esperar a que FFmpeg termine su tarea antes de pasar al siguiente
                done_event.wait()
                
                # Actualizar barra de progreso
                progress = (i + 1) / total_clips
                dpg.set_value("progress_modal_bar", progress)

            # Finalizar y desbloquear atajos
            self.modal_active = False
            dpg.configure_item("progress_modal", show=False)
            if errors:
                error_summary = "\n".join(errors)
                self._show_error(f"Se completó la cola con algunos errores:\n{error_summary}")
            else:
                dpg.set_value("status_bar", "¡Todos los clips exportados con éxito!")
                # Abrir aviso nativo de completado
                root_box = tk.Tk()
                root_box.withdraw()
                messagebox.showinfo("Exportación Completa", f"Se han exportado los {total_clips} clips exitosamente.")
                root_box.destroy()

        t = threading.Thread(target=worker_cola, daemon=True)
        t.start()

    # --- Persistencia de Sesión ---

    def _menu_abrir_video(self):
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Seleccionar Archivo de Video",
            filetypes=[("Archivos de Video", "*.mp4 *.mkv *.avi *.mov *.flv *.webm *.mpeg"), ("Todos", "*.*")]
        )
        root.destroy()

        if path:
            if dpg.does_item_exist("placeholder_text"):
                dpg.delete_item("placeholder_text")
            
            # Cargar video
            self._cargar_video_local(path)

    def _cargar_video_local(self, path: str):
        try:
            self.player.load_video(path)
            self.proyecto.video = Video(filepath=path, duration=0.0)
            self.proyecto.clips = []
            self.clip_start = None
            self.clip_end = None
            self._rebuild_clip_list_ui()
            dpg.set_value("status_bar", f"Cargado: {os.path.basename(path)}")
        except Exception as e:
            self._show_error(f"Error al cargar video: {str(e)}")

    def _menu_guardar_proyecto(self):
        if not self.proyecto.video:
            self._show_error("No hay ningún proyecto activo para guardar.")
            return

        root = tk.Tk()
        root.withdraw()
        path = filedialog.asksaveasfilename(
            title="Guardar Proyecto",
            defaultextension=".json",
            filetypes=[("Proyecto JSON", "*.json")]
        )
        root.destroy()

        if path:
            try:
                self.guardar_proyecto_uc.ejecutar(self.proyecto, path)
                dpg.set_value("status_bar", f"Proyecto guardado en: {os.path.basename(path)}")
            except Exception as e:
                self._show_error(f"Error al guardar proyecto: {str(e)}")

    def _menu_cargar_proyecto(self):
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfile(
            title="Cargar Proyecto",
            filetypes=[("Proyecto JSON", "*.json")]
        )
        root.destroy()

        if path:
            filepath = path.name
            try:
                proyecto_cargado = self.cargar_proyecto_uc.ejecutar(filepath)
                self.proyecto = proyecto_cargado
                
                # Cargar el video asociado
                if self.proyecto.video:
                    if dpg.does_item_exist("placeholder_text"):
                        dpg.delete_item("placeholder_text")
                    self._cargar_video_local(self.proyecto.video.filepath)
                
                self._rebuild_clip_list_ui()
                dpg.set_value("status_bar", f"Proyecto cargado: {os.path.basename(filepath)}")
            except Exception as e:
                self._show_error(f"Error al cargar proyecto: {str(e)}")

    # --- Métodos de Extracción de Miniaturas en Segundo Plano ---

    def _generate_timeline_thumbnails(self, video_path: str):
        """Extrae 8 imágenes de previsualización en segundo plano usando FFmpeg."""
        try:
            duration = self.total_duration
            if duration <= 0.0:
                return

            self.thumbs_to_load.clear()

            for i in range(8):
                # Calcular marcas de tiempo intermedias
                timestamp = i * (duration / 8.0) + (duration / 16.0)
                timestamp = min(timestamp, duration - 0.1)

                thumb_path = os.path.join(self.temp_thumbs_dir, f"thumb_{i}.jpg")

                # Comando FFmpeg para extraer fotograma escalado y rápido
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{timestamp:.3f}",
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "5",  # calidad media para acelerar
                    "-vf", "scale=160:90",
                    thumb_path
                ]

                # Ocultar consola cmd de fondo
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                # Ejecutar FFmpeg
                subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)

                if os.path.exists(thumb_path):
                    self.thumbs_to_load.append((thumb_path, i))

        except Exception as e:
            print(f"Error al generar miniaturas de línea de tiempo: {e}")

    def _generate_clip_thumbnail(self, clip: Clip):
        """Extrae un fotograma representativo del inicio del clip en segundo plano."""
        try:
            if not self.proyecto.video:
                return

            thumb_path = os.path.join(self.temp_thumbs_dir, f"clip_{clip.id}.jpg")

            # Buscar frame al inicio del clip y escalarlo
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{clip.start_seconds:.3f}",
                "-i", self.proyecto.video.filepath,
                "-vframes", "1",
                "-q:v", "4",
                "-vf", "scale=120:68",
                thumb_path
            ]

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)

            if os.path.exists(thumb_path):
                self.clip_thumbs_to_load.append((clip.id, thumb_path))

        except Exception as e:
            print(f"Error al generar miniatura para clip individual: {e}")

    # --- Utilidades ---

    def _show_error(self, message: str):
        """Muestra una alerta nativa de Windows en primer plano."""
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", message)
        root.destroy()

    def _format_time(self, seconds: float) -> str:
        """Formatea los segundos a un formato legible HH:MM:SS.FFF."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
