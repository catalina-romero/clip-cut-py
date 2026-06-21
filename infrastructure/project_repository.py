import json
import os
from domain.interfaces import ProjectRepositoryInterface
from domain.entities import Proyecto, Video, Clip

class JSONProjectRepository(ProjectRepositoryInterface):
    """Implementación de persistencia para proyectos usando formato JSON."""

    def guardar(self, proyecto: Proyecto, filepath: str) -> None:
        """Guarda la sesión del proyecto en un archivo JSON ligero."""
        data = {
            "video_path": proyecto.video.filepath if proyecto.video else None,
            "video_duration": proyecto.video.duration if proyecto.video else 0.0,
            "clips": [
                {
                    "id": clip.id,
                    "name": clip.name,
                    "start_seconds": clip.start_seconds,
                    "end_seconds": clip.end_seconds
                }
                for clip in proyecto.clips
            ]
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def cargar(self, filepath: str) -> Proyecto:
        """Carga y reconstruye la entidad Proyecto a partir de un JSON."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"El archivo de proyecto no existe: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        proyecto = Proyecto()
        video_path = data.get("video_path")
        if video_path:
            # Reconstruir la entidad Video
            video_duration = data.get("video_duration", 0.0)
            proyecto.video = Video(filepath=video_path, duration=video_duration)

        # Reconstruir los clips
        proyecto.clips = []
        for c_data in data.get("clips", []):
            clip = Clip(
                id=c_data.get("id"),
                name=c_data.get("name"),
                start_seconds=float(c_data.get("start_seconds", 0.0)),
                end_seconds=float(c_data.get("end_seconds", 0.0))
            )
            proyecto.clips.append(clip)

        return proyecto
