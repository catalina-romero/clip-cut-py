import os
import sys
import logging

# Configurar logging global de la aplicación
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("ApplicationMain")

# Aseguramos que la ruta del ejecutable o script actual esté en el PATH.
# Esto garantiza que python-mpv pueda enlazar 'libmpv-2.dll' que se encuentra en la raíz del proyecto.
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in os.environ["PATH"]:
    os.environ["PATH"] = app_dir + os.pathsep + os.environ["PATH"]
    logger.info(f"Directorio de la aplicación añadido al PATH del sistema: {app_dir}")

try:
    from presentation.mpv_player import MPVPlayer
    from infrastructure.ffmpeg_processor import FFmpegProcessor
    from infrastructure.project_repository import JSONProjectRepository
    from presentation.dpg_app import VideoEditorApp
except Exception as e:
    logger.critical(f"Fallo crítico al importar módulos de la aplicación: {e}")
    logger.critical("Asegúrese de haber instalado pywin32, dearpygui y python-mpv, además de poseer libmpv-2.dll en la raíz.")
    sys.exit(1)

def main():
    logger.info("Iniciando la aplicación Video Clip Extractor Pro...")

    # Instanciación de adaptadores de infraestructura y reproductor (Inyección de Dependencias)
    player = MPVPlayer()
    processor = FFmpegProcessor(ffmpeg_path="ffmpeg")
    repository = JSONProjectRepository()

    # Creación y arranque del controlador de la aplicación
    app = VideoEditorApp(
        player=player,
        processor=processor,
        repository=repository
    )

    try:
        app.run()
    except Exception as e:
        logger.exception(f"Excepción no controlada en el bucle principal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
