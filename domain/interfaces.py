from abc import ABC, abstractmethod
from typing import Callable
from domain.entities import Proyecto

class VideoPlayerInterface(ABC):
    """Interfaz abstracta para el motor de reproducción de video."""

    @abstractmethod
    def load_video(self, filepath: str) -> None:
        """Carga un archivo de video en el reproductor."""
        pass

    @abstractmethod
    def play(self) -> None:
        """Inicia o reanuda la reproducción."""
        pass

    @abstractmethod
    def pause(self) -> None:
        """Pausa la reproducción."""
        pass

    @abstractmethod
    def seek(self, seconds: float) -> None:
        """Salta a un segundo específico en el video."""
        pass

    @abstractmethod
    def get_current_time(self) -> float:
        """Obtiene la posición de reproducción actual en segundos."""
        pass

    @abstractmethod
    def is_playing(self) -> bool:
        """Indica si el video está en reproducción activa."""
        pass

    @abstractmethod
    def set_on_time_change_callback(self, callback: Callable[[float], None]) -> None:
        """Establece una función callback que recibe el segundo actual al cambiar de posición."""
        pass

    @abstractmethod
    def set_on_video_loaded_callback(self, callback: Callable[[float], None]) -> None:
        """Establece una función callback que recibe la duración del video al completarse su carga."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Libera los recursos asociados al reproductor."""
        pass


class VideoProcessorInterface(ABC):
    """Interfaz abstracta para el procesamiento físico de video."""

    @abstractmethod
    def cortar_clip(self, video_path: str, start: float, end: float, output_path: str) -> None:
        """
        Extrae un clip del video fuente desde 'start' hasta 'end' segundos,
        escribiéndolo en 'output_path'. No debe bloquear el hilo principal.
        """
        pass


class ProjectRepositoryInterface(ABC):
    """Interfaz abstracta para persistencia y recuperación de proyectos."""

    @abstractmethod
    def guardar(self, proyecto: Proyecto, filepath: str) -> None:
        """Persiste el proyecto en disco."""
        pass

    @abstractmethod
    def cargar(self, filepath: str) -> Proyecto:
        """Carga un proyecto desde el disco y retorna su entidad."""
        pass
