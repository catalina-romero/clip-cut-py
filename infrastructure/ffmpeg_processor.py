import subprocess
import threading
import os
import logging
from typing import Callable, Optional
from domain.interfaces import VideoProcessorInterface

class FFmpegProcessor(VideoProcessorInterface):
    """Implementación del procesador de video utilizando subprocess y comandos FFmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self.logger = logging.getLogger("FFmpegProcessor")
        # Configurar logging básico si no está configurado
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def cortar_clip(self, video_path: str, start: float, end: float, output_path: str,
                    on_success: Optional[Callable[[str], None]] = None,
                    on_error: Optional[Callable[[str], None]] = None) -> None:
        """
        Ejecuta FFmpeg en un hilo secundario para extraer el fragmento sin re-codificación.
        """
        def run_ffmpeg():
            try:
                if not os.path.exists(video_path):
                    raise FileNotFoundError(f"El archivo original de video no existe: {video_path}")

                duration = end - start
                if duration <= 0:
                    raise ValueError(f"Duración inválida para el fragmento ({duration}s).")

                # Comando FFmpeg optimizado con copiado directo de flujos (-c copy)
                # Se coloca -ss antes de -i para seek rápido
                cmd = [
                    self.ffmpeg_path,
                    "-y",
                    "-ss", f"{start:.3f}",
                    "-t", f"{duration:.3f}",
                    "-i", video_path,
                    "-c", "copy",
                    output_path
                ]

                self.logger.info(f"Iniciando corte de video: {' '.join(cmd)}")

                # Ocultar la ventana de consola negra de cmd en Windows
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                # Ejecutar proceso de FFmpeg
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    startupinfo=startupinfo,
                    encoding='utf-8',
                    errors='ignore'
                )

                if process.returncode != 0:
                    error_msg = f"FFmpeg finalizó con código de error {process.returncode}.\nDetalle: {process.stderr}"
                    self.logger.error(error_msg)
                    if on_error:
                        on_error(error_msg)
                    return

                self.logger.info(f"Corte completado con éxito: {output_path}")
                if on_success:
                    on_success(output_path)

            except Exception as e:
                error_msg = f"Excepción interna en el procesador FFmpeg: {str(e)}"
                self.logger.error(error_msg)
                if on_error:
                    on_error(error_msg)

        # Lanzar el hilo secundario para evitar congelamiento de la UI de Dear PyGui
        thread = threading.Thread(target=run_ffmpeg, daemon=True)
        thread.start()
