from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Video:
    """Representa la grabación de videojuego original."""
    filepath: str
    duration: float  # en segundos

@dataclass
class Clip:
    """Representa un fragmento de video marcado para extracción."""
    id: str
    name: str
    start_seconds: float
    end_seconds: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

@dataclass
class Proyecto:
    """Representa la sesión de trabajo actual."""
    video: Optional[Video] = None
    clips: List[Clip] = field(default_factory=list)
    filepath: Optional[str] = None  # Ruta del archivo del proyecto (.json)
