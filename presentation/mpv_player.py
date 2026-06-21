import os
import sys
import logging
from typing import Callable, Optional
import win32gui
import win32con

# Configurar el PATH de Windows para que python-mpv pueda encontrar libmpv-2.dll en la raíz del proyecto
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in os.environ["PATH"]:
    os.environ["PATH"] = root_dir + os.pathsep + os.environ["PATH"]

import mpv
from domain.interfaces import VideoPlayerInterface

class MPVPlayer(VideoPlayerInterface):
    """Implementación del reproductor de video utilizando libmpv y una ventana nativa de Windows."""

    def __init__(self):
        self.player: Optional[mpv.MPV] = None
        self.child_hwnd: int = 0
        self.parent_hwnd: int = 0
        self.logger = logging.getLogger("MPVPlayer")
        
        self.on_time_change_callback: Optional[Callable[[float], None]] = None
        self.on_video_loaded_callback: Optional[Callable[[float], None]] = None

    def embed_in_window(self, parent_hwnd: int, x: int, y: int, width: int, height: int) -> None:
        """
        Crea una subventana Win32 "STATIC" dentro de la ventana padre y la asocia
        como superficie de renderizado para MPV.
        """
        self.parent_hwnd = parent_hwnd
        self.logger.info(f"Emparentando MPV al HWND padre: {parent_hwnd}")

        # Registrar un estilo de ventana hijo que reciba eventos de pintado del sistema
        style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS

        # Creamos una ventana de tipo "STATIC" (es una clase de control de Windows estándar)
        # Esto nos evita registrar una clase de ventana personalizada y escribir un bucle de mensajes
        self.child_hwnd = win32gui.CreateWindow(
            "STATIC",
            "MPV_Render_Surface",
            style,
            x, y, width, height,
            parent_hwnd,
            0,
            0,
            None
        )

        if not self.child_hwnd:
            raise RuntimeError("No se pudo crear la ventana Win32 hija para MPV.")

        self.logger.info(f"Subventana Win32 creada con HWND: {self.child_hwnd}")

        # Deshabilitar la ventana para evitar capturar el foco de teclado
        win32gui.EnableWindow(self.child_hwnd, False)

        # Inicializar el reproductor MPV pasándole el WID (Window ID) de nuestra subventana
        self.player = mpv.MPV(
            wid=str(self.child_hwnd),
            hwdec="auto",           # Habilitar decodificación por hardware de la GPU (DirectX11/DXVA2)
            vo="gpu",               # Usar el backend GPU de MPV
            keep_open="yes",        # No cerrar el frame al terminar el video
            input_default_bindings=False  # Deshabilitar atajos de MPV por defecto para no colisionar con la UI
        )

        # Configurar observers de propiedades para notificar a la interfaz
        @self.player.property_observer("time-pos")
        def on_time_change(name, value):
            if value is not None and self.on_time_change_callback:
                # El callback se ejecuta en el hilo de MPV, la UI debe manejarlo asíncronamente
                self.on_time_change_callback(value)

        @self.player.property_observer("duration")
        def on_duration_change(name, value):
            if value is not None and self.on_video_loaded_callback:
                self.on_video_loaded_callback(value)

    def resize_window(self, x: int, y: int, width: int, height: int) -> None:
        """Ajusta las dimensiones y posición de la subventana de video."""
        if self.child_hwnd:
            win32gui.SetWindowPos(
                self.child_hwnd,
                0,
                x, y, width, height,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )

    # --- Métodos de la Interfaz VideoPlayerInterface ---

    def load_video(self, filepath: str) -> None:
        if not self.player:
            raise RuntimeError("El reproductor MPV no está inicializado. Debe llamar primero a embed_in_window.")
        
        self.logger.info(f"Cargando video: {filepath}")
        self.player.play(filepath)

    def play(self) -> None:
        if self.player:
            self.player.pause = False

    def pause(self) -> None:
        if self.player:
            self.player.pause = True

    def seek(self, seconds: float) -> None:
        if self.player:
            # seek absolute: salta al segundo específico de forma exacta
            self.player.time_pos = seconds

    def get_current_time(self) -> float:
        if self.player:
            return self.player.time_pos or 0.0
        return 0.0

    def is_playing(self) -> bool:
        if self.player:
            return not self.player.pause
        return False

    def set_on_time_change_callback(self, callback: Callable[[float], None]) -> None:
        self.on_time_change_callback = callback

    def set_on_video_loaded_callback(self, callback: Callable[[float], None]) -> None:
        self.on_video_loaded_callback = callback

    def shutdown(self) -> None:
        if self.player:
            self.player.terminate()
            self.player = None
        if self.child_hwnd:
            win32gui.DestroyWindow(self.child_hwnd)
            self.child_hwnd = 0
