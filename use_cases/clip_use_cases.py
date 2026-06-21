from domain.entities import Proyecto, Clip
import uuid

class AgregarClipUseCase:
    """Caso de uso para añadir un clip al proyecto con validación y auto-incremento."""

    def ejecutar(self, proyecto: Proyecto, start_seconds: float, end_seconds: float, name_prefix: str = "clip") -> Clip:
        # Validación de límites
        if start_seconds < 0:
            start_seconds = 0.0
        
        if proyecto.video and end_seconds > proyecto.video.duration:
            end_seconds = proyecto.video.duration

        if start_seconds >= end_seconds:
            raise ValueError("El tiempo de inicio debe ser menor que el tiempo de fin.")

        # Generar nombre auto-incremental
        clip_index = len(proyecto.clips) + 1
        name = f"{name_prefix}_{clip_index:03d}"

        # Crear el clip
        clip_id = str(uuid.uuid4())
        nuevo_clip = Clip(
            id=clip_id,
            name=name,
            start_seconds=round(start_seconds, 2),
            end_seconds=round(end_seconds, 2)
        )

        # Añadir al proyecto
        proyecto.clips.append(nuevo_clip)
        return nuevo_clip


class EliminarClipUseCase:
    """Caso de uso para eliminar un clip del proyecto."""

    def ejecutar(self, proyecto: Proyecto, clip_id: str) -> bool:
        for i, clip in enumerate(proyecto.clips):
            if clip.id == clip_id:
                proyecto.clips.pop(i)
                return True
        return False
