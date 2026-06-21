from domain.entities import Proyecto
from domain.interfaces import ProjectRepositoryInterface

class GuardarProyectoUseCase:
    """Caso de uso para persistir el proyecto actual a disco."""
    
    def __init__(self, repository: ProjectRepositoryInterface):
        self.repository = repository

    def ejecutar(self, proyecto: Proyecto, filepath: str) -> None:
        if not filepath:
            raise ValueError("Ruta de archivo inválida para guardar el proyecto.")
        
        # Guardar proyecto usando el repositorio
        self.repository.guardar(proyecto, filepath)
        proyecto.filepath = filepath


class CargarProyectoUseCase:
    """Caso de uso para recuperar un proyecto de disco."""
    
    def __init__(self, repository: ProjectRepositoryInterface):
        self.repository = repository

    def ejecutar(self, filepath: str) -> Proyecto:
        if not filepath:
            raise ValueError("Ruta de archivo inválida para cargar el proyecto.")
            
        proyecto = self.repository.cargar(filepath)
        proyecto.filepath = filepath
        return proyecto
