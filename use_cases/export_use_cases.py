import os
from typing import List, Tuple, Callable
from domain.entities import Proyecto, Clip
from domain.interfaces import VideoProcessorInterface

class ExportarClipUseCase:
    """Caso de uso para exportar un clip individual."""

    def __init__(self, processor: VideoProcessorInterface):
        self.processor = processor

    def ejecutar(self, video_path: str, clip: Clip, output_path: str) -> None:
        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"No se encuentra el video original en: {video_path}")
        
        self.processor.cortar_clip(
            video_path=video_path,
            start=clip.start_seconds,
            end=clip.end_seconds,
            output_path=output_path
        )


class ExportarTodosLosClipsUseCase:
    """Caso de uso para exportar en lote todos los clips de un proyecto."""

    def __init__(self, processor: VideoProcessorInterface):
        self.processor = processor

    def ejecutar(self, proyecto: Proyecto, output_dir: str, progress_callback: Callable[[int, int, str], None] = None) -> List[Tuple[Clip, str]]:
        if not proyecto.video:
            raise ValueError("El proyecto no tiene un video cargado.")
        
        if not os.path.exists(proyecto.video.filepath):
            raise FileNotFoundError(f"No se encuentra el video original en: {proyecto.video.filepath}")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        results = []
        total_clips = len(proyecto.clips)

        for i, clip in enumerate(proyecto.clips):
            # Obtener extensión original para preservar el formato
            _, ext = os.path.splitext(proyecto.video.filepath)
            if not ext:
                ext = ".mp4"  # Extensión por defecto

            output_filename = f"{clip.name}{ext}"
            output_path = os.path.join(output_dir, output_filename)

            if progress_callback:
                progress_callback(i + 1, total_clips, clip.name)

            self.processor.cortar_clip(
                video_path=proyecto.video.filepath,
                start=clip.start_seconds,
                end=clip.end_seconds,
                output_path=output_path
            )
            results.append((clip, output_path))

        return results
