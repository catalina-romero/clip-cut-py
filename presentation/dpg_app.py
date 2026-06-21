import os
import sys
import time
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

    def run(self):
        dpg.create_context()
        dpg.create_viewport(title="Video Clip Extractor Pro", width=1280, height=720, min_width=800, min_height=600)
        dpg.setup_dearpygui()

        self._build_theme()
        self._build_ui()
        dpg.show_viewport()

        # Obtener HWND nativo del viewport principal para emparentar MPV
        import win32gui
        hwnd = win32gui.FindWindow(None, "Video Clip Extractor Pro")
        if hwnd:
            # Inicializar el reproductor MPV incrustado
            self.player.embed_in_window(hwnd, 10, 40, 800, 450)
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
        last_time = time.time()
        while dpg.is_dearpygui_running():
            now = time.time()
            # Si el video se está reproduciendo, actualizamos la posición del slider desde la posición del reproductor
            if self.proyecto.video and self.player.is_playing() and not self.dragging_slider:
                self.current_time = self.player.get_current_time()
                self._update_timeline_ui()

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
        
        # Actualizar UI en el hilo principal
        self._update_timeline_ui()
        self._draw_timeline_visuals()

    def _on_viewport_resize(self):
        """Ajusta dinámicamente la disposición en rejilla (grid) de la UI."""
        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()

        padding = 10
        top_y = 35  # Espacio para el menú principal

        # Panel izquierdo (Video + Controles): 72% de ancho
        left_w = int(vw * 0.72) - padding * 2
        # Panel derecho (Clips): 28% de ancho
        right_w = int(vw * 0.28) - padding

        # Altura disponible total
        total_h = vh - top_y - padding * 4

        # El video ocupa el 70% del panel izquierdo
        video_h = int(total_h * 0.70)
        # Los controles ocupan el resto del panel izquierdo
        controls_h = total_h - video_h - padding

        # Ajustar dimensiones de contenedores en Dear PyGui
        dpg.configure_item("video_container", width=left_w, height=video_h)
        dpg.configure_item("controls_container", pos=(padding, top_y + video_h + padding), width=left_w, height=controls_h)
        dpg.configure_item("clips_container", pos=(padding + left_w + padding, top_y), width=right_w, height=total_h)

        # Ajustar tamaño de subventana de MPV (con offsets para conservar el borde del contenedor DPG)
        if self.player:
            self.player.resize_window(padding + 8, top_y + 8, left_w - 16, video_h - 16)

        # Redibujar la barra visual de la línea de tiempo
        self._draw_timeline_visuals()

    def _build_theme(self):
        """Configura un estilo oscuro premium y limpio."""
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                # Colores de ventanas y paneles
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (15, 15, 15))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (22, 22, 22))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (38, 38, 38))
                
                # Colores de campos de entrada y sliders
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (30, 30, 30))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (40, 40, 40))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (50, 50, 50))
                
                # Botones genéricos (Gris Carbón)
                dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 40, 40))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 60, 60))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (80, 80, 80))

                # Selección
                dpg.add_theme_color(dpg.mvThemeCol_Header, (55, 65, 80))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (70, 80, 100))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (80, 95, 120))
                
                # Deslizadores (Verde Esmeralda)
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (46, 204, 113))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (39, 174, 96))

                # Estilos visuales
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8.0, 8.0)

        dpg.bind_theme(global_theme)

    def _build_ui(self):
        """Define la estructura visual y controles de la aplicación."""
        # Menú Superior
        with dpg.viewport_menu_bar():
            with dpg.menu(label="Archivo"):
                dpg.add_menu_item(label="Abrir Video...", callback=self._menu_abrir_video)
                dpg.add_menu_item(label="Cargar Proyecto JSON...", callback=self._menu_cargar_proyecto)
                dpg.add_menu_item(label="Guardar Proyecto JSON...", callback=self._menu_guardar_proyecto)
                dpg.add_menu_item(label="Salir", callback=lambda: sys.exit(0))

        # Ventana Principal Invisible (Actúa como root de los paneles flotantes anclados por pos)
        with dpg.window(tag="primary_window", no_title_bar=True, no_resize=True, no_move=True):
            dpg.set_primary_window("primary_window", True)

            # 1. Panel Contenedor de Video
            with dpg.child_window(tag="video_container", pos=(10, 35)):
                # Se dibuja un fondo negro para simular el reproductor cuando no hay video cargado
                dpg.add_text("Abra un archivo de video desde el menú Archivo para comenzar.", tag="placeholder_text", pos=(30, 30), color=(180, 180, 180))

            # 2. Panel de Controles Inferior
            with dpg.child_window(tag="controls_container", pos=(10, 500)):
                # Línea de estado temporal superior
                with dpg.group(horizontal=True):
                    dpg.add_text("Tiempo:", color=(150, 150, 150))
                    dpg.add_text("00:00:00.000 / 00:00:00.000", tag="time_text", color=(255, 255, 255))
                    dpg.add_spacer(width=20)
                    dpg.add_text("Inicio:", color=(150, 150, 150))
                    dpg.add_text("No fijado", tag="start_marker_text", color=(46, 204, 113))
                    dpg.add_spacer(width=10)
                    dpg.add_text("Fin:", color=(150, 150, 150))
                    dpg.add_text("No fijado", tag="end_marker_text", color=(231, 76, 60))

                # Canvas de visualización de Marcadores
                with dpg.group():
                    dpg.add_drawlist(width=1, height=18, tag="timeline_drawlist")

                # Slider de Línea de Tiempo Principal
                dpg.add_slider_double(
                    label="",
                    tag="timeline_slider",
                    min_value=0.0,
                    max_value=1.0,
                    default_value=0.0,
                    width=-1,
                    callback=self._on_timeline_slider_change,
                    user_data="drag"
                )

                # Slider de Zoom Dedicado
                with dpg.group(horizontal=True):
                    dpg.add_text("Zoom Temporal:", color=(180, 180, 180))
                    dpg.add_slider_double(
                        label="x (Ampliar detalles)",
                        tag="zoom_slider",
                        min_value=1.0,
                        max_value=100.0,
                        default_value=1.0,
                        width=250,
                        callback=self._on_zoom_change
                    )

                dpg.add_spacer(height=5)

                # Fila de Botones Digitales
                with dpg.group(horizontal=True):
                    # Reproducir/Pausar
                    dpg.add_button(label="Reproducir/Pausar", callback=self._btn_toggle_play, width=130)
                    dpg.add_spacer(width=10)

                    # Fijar Inicio (Verde)
                    with dpg.theme() as green_btn_theme:
                        with dpg.theme_component(dpg.mvButton):
                            dpg.add_theme_color(dpg.mvThemeCol_Button, (39, 174, 96))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (46, 204, 113))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (30, 130, 70))
                    dpg.add_button(label="Fijar Inicio [I]", callback=self._btn_mark_start, width=120)
                    dpg.bind_item_theme(dpg.last_item(), green_btn_theme)

                    # Fijar Fin (Rojo)
                    with dpg.theme() as red_btn_theme:
                        with dpg.theme_component(dpg.mvButton):
                            dpg.add_theme_color(dpg.mvThemeCol_Button, (192, 57, 43))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (231, 76, 60))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (150, 40, 30))
                    dpg.add_button(label="Fijar Fin [O]", callback=self._btn_mark_end, width=120)
                    dpg.bind_item_theme(dpg.last_item(), red_btn_theme)

                    dpg.add_spacer(width=10)
                    # Descartar
                    dpg.add_button(label="Descartar Selección", callback=self._btn_clear_markers, width=140)
                    
                    # Añadir Clip (Azul)
                    with dpg.theme() as blue_btn_theme:
                        with dpg.theme_component(dpg.mvButton):
                            dpg.add_theme_color(dpg.mvThemeCol_Button, (41, 128, 185))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (52, 152, 219))
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (30, 100, 150))
                    dpg.add_button(label="Añadir a la Lista", callback=self._btn_add_clip, width=130)
                    dpg.bind_item_theme(dpg.last_item(), blue_btn_theme)

                dpg.add_spacer(height=8)
                # Leyenda de Atajos
                dpg.add_text("Atajos: [Espacio] Play/Pause | [Flecha Izquierda/Derecha] +-1 Segundo | [I] Fijar Inicio | [O] Fijar Fin", color=(100, 100, 100))

            # 3. Panel de Gestor de Clips (Derecho)
            with dpg.child_window(tag="clips_container", pos=(930, 35)):
                # Botón Exportar Todo Destacado
                with dpg.theme() as gold_btn_theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, (230, 126, 34))
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (243, 156, 18))
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (180, 90, 20))
                dpg.add_button(label="EXPORTAR TODOS LOS CLIPS", callback=self._btn_exportar_todos, width=-1, height=40)
                dpg.bind_item_theme(dpg.last_item(), gold_btn_theme)

                dpg.add_separator()
                dpg.add_text("Clips de la Sesión:", color=(160, 160, 160))
                
                # Lista interna scrolleable
                with dpg.child_window(tag="clip_list_window", width=-1, height=-60, border=False):
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
                dpg.add_button(label="Cancelar", callback=lambda: dpg.configure_item("confirm_delete_modal", show=False), width=120)

        # Modal de Progreso para Exportación en Lote
        with dpg.window(label="Exportando Clips...", modal=True, show=False, id="progress_modal", no_resize=True, no_move=True, no_close=True):
            dpg.add_text("Procesando cola de exportación...", tag="progress_modal_text")
            dpg.add_spacer(height=10)
            dpg.add_progress_bar(tag="progress_modal_bar", width=300, default_value=0.0)

    # --- Lógica de Timeline y Zoom ---

    def _update_timeline_ui(self):
        """Actualiza el valor, los límites y el formato digital del slider de tiempo."""
        if self.total_duration <= 0.0:
            return

        zoom = dpg.get_value("zoom_slider")
        if zoom <= 1.0:
            min_val = 0.0
            max_val = self.total_duration
        else:
            # Ventana dinámica en segundos. A zoom máximo (100x), se enfoca en una ventana de 15 segundos.
            min_window = 15.0
            window_size = min_window + (self.total_duration - min_window) * (1.0 - (zoom - 1.0) / 99.0)
            window_size = max(min_window, min(self.total_duration, window_size))

            # Centrar la ventana de visualización en la posición actual
            min_val = self.current_time - window_size / 2.0
            if min_val < 0.0:
                min_val = 0.0
            max_val = min_val + window_size
            if max_val > self.total_duration:
                max_val = self.total_duration
                min_val = max(0.0, max_val - window_size)

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

        # Obtener el rango visible actual del slider
        min_val = dpg.get_item_configuration("timeline_slider")["min_value"]
        max_val = dpg.get_item_configuration("timeline_slider")["max_value"]
        span = max_val - min_val
        if span <= 0:
            return

        # Función auxiliar para convertir segundos a píxeles
        def to_pixel(t: float) -> float:
            return ((t - min_val) / span) * canvas_width

        # 1. Dibujar fondo de la barra
        dpg.draw_rectangle([0, 2], [canvas_width, 16], color=(50, 50, 50), fill=(28, 28, 28), parent=canvas_tag)

        # 2. Dibujar zona de selección si ambos marcadores están puestos
        if self.clip_start is not None and self.clip_end is not None:
            px_start = to_pixel(self.clip_start)
            px_end = to_pixel(self.clip_end)
            # Acotar coordenadas al rango visible del canvas
            c_start = max(0.0, min(canvas_width, px_start))
            c_end = max(0.0, min(canvas_width, px_end))
            if c_start < c_end:
                # Rectángulo translúcido verde esmeralda
                dpg.draw_rectangle([c_start, 2], [c_end, 16], color=(46, 204, 113, 200), fill=(46, 204, 113, 40), parent=canvas_tag)

        # 3. Dibujar marcador de Inicio (Línea vertical verde)
        if self.clip_start is not None:
            px = to_pixel(self.clip_start)
            if 0.0 <= px <= canvas_width:
                dpg.draw_line([px, 0], [px, 18], color=(46, 204, 113), thickness=2, parent=canvas_tag)

        # 4. Dibujar de Fin (Línea vertical roja)
        if self.clip_end is not None:
            px = to_pixel(self.clip_end)
            if 0.0 <= px <= canvas_width:
                dpg.draw_line([px, 0], [px, 18], color=(231, 76, 60), thickness=2, parent=canvas_tag)

        # 5. Dibujar cursor de reproducción (Línea vertical blanca)
        px_curr = to_pixel(self.current_time)
        if 0.0 <= px_curr <= canvas_width:
            dpg.draw_line([px_curr, 0], [px_curr, 18], color=(255, 255, 255), thickness=2, parent=canvas_tag)

    def _on_timeline_slider_change(self):
        """Acción cuando el usuario desliza la línea de tiempo."""
        self.dragging_slider = True
        new_time = dpg.get_value("timeline_slider")
        self.current_time = new_time
        self.player.seek(new_time)
        self.dragging_slider = False
        self._update_timeline_ui()

    def _on_zoom_change(self):
        """Acción cuando se modifica el factor de zoom."""
        self._update_timeline_ui()

    # --- Gestión de Atajos y Botones de Reproducción ---

    def _register_keyboard_shortcuts(self):
        """Registra controladores de eventos de teclado rápidos en Dear PyGui."""
        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self._on_key_press)

    def _on_key_press(self, sender, app_data):
        key = app_data
        # Ignorar atajos si el usuario está interactuando con modales o cuadros de entrada activos
        if dpg.is_any_item_active():
            return

        if key == dpg.mvKey_Spacebar:
            self._btn_toggle_play()
        elif key == dpg.mvKey_I:
            self._btn_mark_start()
        elif key == dpg.mvKey_O:
            self._btn_mark_end()
        elif key == dpg.mvKey_Left:
            self._seek_relative(-1.0)
        elif key == dpg.mvKey_Right:
            self._seek_relative(1.0)

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

    def _btn_mark_start(self):
        if not self.proyecto.video:
            return
        self.clip_start = self.current_time
        dpg.set_value("start_marker_text", self._format_time(self.clip_start))
        self._update_timeline_ui()

    def _btn_mark_end(self):
        if not self.proyecto.video:
            return
        self.clip_end = self.current_time
        dpg.set_value("end_marker_text", self._format_time(self.clip_end))
        self._update_timeline_ui()

    def _btn_clear_markers(self):
        self.clip_start = None
        self.clip_end = None
        dpg.set_value("start_marker_text", "No fijado")
        dpg.set_value("end_marker_text", "No fijado")
        self._update_timeline_ui()

    # --- Gestión de Clips de Sesión ---

    def _btn_add_clip(self):
        if not self.proyecto.video:
            self._show_error("No hay ningún video cargado en la sesión.")
            return

        if self.clip_start is None or self.clip_end is None:
            self._show_error("Debe fijar tanto el marcador de Inicio como el de Fin para añadir un clip.")
            return

        try:
            nuevo_clip = self.agregar_clip_uc.ejecutar(
                proyecto=self.proyecto,
                start_seconds=self.clip_start,
                end_seconds=self.clip_end,
                name_prefix="clip_partida"
            )
            dpg.set_value("status_bar", f"Añadido: {nuevo_clip.name}")
            self._btn_clear_markers()
            self._rebuild_clip_list_ui()
        except Exception as e:
            self._show_error(f"Error al añadir clip: {str(e)}")

    def _rebuild_clip_list_ui(self):
        """Redibuja de forma dinámica el listado vertical en el Panel Derecho."""
        dpg.delete_item("clip_list_window", children_only=True)

        if not self.proyecto.clips:
            dpg.add_text("No hay clips creados.", tag="no_clips_text", parent="clip_list_window", color=(100, 100, 100))
            return

        for clip in self.proyecto.clips:
            clip_tag = f"clip_item_{clip.id}"
            
            with dpg.group(parent="clip_list_window", tag=clip_tag):
                # Elemento seleccionable que al hacer click salta al inicio del fragmento
                dpg.add_selectable(
                    label=f"{clip.name} ({self._format_time(clip.duration)})",
                    callback=self._on_clip_item_left_click,
                    user_data=clip,
                    width=-1
                )
                
                # Crear menú contextual de click derecho
                with dpg.popup(parent=dpg.last_item(), mousebutton=dpg.mvMouseButton_Right):
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

    def _menu_confirmar_eliminar_clip(self, sender, app_data, user_data: Clip):
        """Muestra el modal de confirmación antes de remover el clip."""
        self.target_delete_clip = user_data
        dpg.set_value("confirm_delete_text", f"¿Está seguro de que desea eliminar '{user_data.name}'?")
        dpg.configure_item("confirm_delete_modal", show=True)

    def _modal_confirm_delete_yes(self):
        """Acción cuando el usuario confirma la eliminación del clip."""
        dpg.configure_item("confirm_delete_modal", show=False)
        if self.target_delete_clip:
            self.eliminar_clip_uc.ejecutar(self.proyecto, self.target_delete_clip.id)
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
        
        # Ejecutar caso de uso
        try:
            self.exportar_clip_uc.ejecutar(
                video_path=self.proyecto.video.filepath,
                clip=clip,
                output_path=dest_path
            )
            # Nota: la notificación final se hará mediante los callbacks del procesador
            # que interceptan el hilo secundario
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

        # Mostrar ventana modal de progreso
        dpg.configure_item("progress_modal", show=True)
        dpg.set_value("progress_modal_bar", 0.0)
        dpg.set_value("progress_modal_text", "Preparando cola de corte...")

        total_clips = len(self.proyecto.clips)
        
        # Procesar en cola en un hilo secundario para no colgar la UI del modal de progreso
        def worker_cola():
            errors = []
            for i, clip in enumerate(self.proyecto.clips):
                # Actualizar texto del modal
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

            # Finalizar
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

        import threading
        t = threading.Thread(target=worker_cola, daemon=True)
        t.start()

    # --- Persistencia de Sesión (Menú Archivo) ---

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

    # --- Utilidades y Diálogos de Alerta ---

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
