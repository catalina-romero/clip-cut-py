# Video Clip Extractor Pro 🎮✂️

Una aplicación de escritorio para Windows extremadamente ligera y de alto rendimiento, optimizada para extraer clips de video a partir de grabaciones de videojuegos de larga duración (hasta 4 horas o más) de forma instantánea.

La aplicación utiliza la aceleración por GPU nativa para la interfaz de usuario y la reproducción de video, y delega el proceso de corte a **FFmpeg** utilizando copia directa de flujo (`-c copy`) para evitar la re-codificación y renderizado tradicional, realizando el proceso de forma inmediata.

---

## 🏗️ Arquitectura del Software (Clean Architecture)

El proyecto está diseñado siguiendo estrictamente **Clean Architecture** y los principios **SOLID**, manteniendo la lógica de negocio totalmente desacoplada de la interfaz gráfica y los frameworks externos.

```
video_editor/
│
├── domain/                  # Capa de Dominio (Entidades puras y Abstracciones)
│   ├── entities.py          # Modelos de datos: Video, Clip, Proyecto
│   └── interfaces.py        # Contratos (Abstracciones del Player, Procesador y Repo)
│
├── use_cases/               # Capa de Casos de Uso (Lógica pura de negocio)
│   ├── clip_use_cases.py    # Crear y eliminar clips de la sesión
│   ├── project_use_cases.py # Cargar y guardar sesión en JSON
│   └── export_use_cases.py  # Orquestación de exportación por lotes/individual
│
├── infrastructure/          # Capa de Infraestructura (Detalles técnicos y adaptadores)
│   ├── ffmpeg_processor.py  # Ejecución asíncrona de FFmpeg (-c copy) en hilos
│   └── project_repository.py# Serialización/Deserialización del proyecto en JSON
│
├── presentation/            # Capa de Presentación (UI y Reproducción nativa)
│   ├── mpv_player.py        # Adaptador de MPV emparentado a ventana Win32 "STATIC"
│   └── dpg_app.py           # Interfaz de Dear PyGui, línea de tiempo, zoom y atajos
│
├── main.py                  # Punto de entrada (Inyección de dependencias y Bootstrap)
└── libmpv-2.dll             # Biblioteca dinámica oficial de libmpv (Windows x64)
```

---

## ⚙️ Requisitos del Sistema y Dependencias

Para ejecutar la aplicación se requiere tener instalado en Windows:

1. **Python 3.10+**
2. **FFmpeg** instalado y agregado al `PATH` del sistema (la aplicación valida su disponibilidad automáticamente).
3. **Módulo nativo `libmpv-2.dll`** (ya incluido en la raíz de este repositorio).

### Librerías de Python
Las dependencias requeridas se instalan vía `pip`:
```bash
pip install pywin32 python-mpv dearpygui
```

---

## 🚀 Cómo Iniciar la Aplicación

Una vez instaladas las dependencias, inicia la aplicación ejecutando el punto de entrada desde la raíz del proyecto:
```bash
python main.py
```

---

## 🎛️ Manual de Usuario e Interfaz

### 1. Carga de Archivos e Interfaz
* **Panel Izquierdo:** Visualizador de video nativo integrado. Carga un video desde **Archivo > Abrir Video...**.
* **Línea de Tiempo Inferior:** Permite arrastrar el cabezal de reproducción.
* **Zoom Temporal (Slider):** "Amplía" la escala temporal de la barra de reproducción (hasta enfocar un rango de 15 segundos) para seleccionar momentos con precisión de milisegundos en archivos muy extensos.
* **Panel Derecho (Gestor de Clips):** Contiene la lista de clips creados en la sesión.
  * *Click Izquierdo:* Salta instantáneamente al segundo de inicio del clip para previsualizarlo.
  * *Click Derecho:* Abre el menú contextual para:
    * **Exportar este clip...**: Abre el diálogo nativo para seleccionar la ruta y exportarlo con FFmpeg de inmediato.
    * **Eliminar clip**: Lanza un modal de confirmación antes de borrar el clip de la sesión.
* **Botón Naranja "EXPORTAR TODOS LOS CLIPS":** Pide una carpeta de destino y procesa asíncronamente en cola la exportación de todos los clips de la lista.

### 2. Atajos de Teclado (Accesibilidad Gamer)
* `[Espacio]`: Reproducir / Pausar el video.
* `[←] / [→]` (Flechas): Retroceder o avanzar el video exactamente 1 segundo.
* `[I]`: Fijar marcador de **Inicio** del fragmento.
* `[O]`: Fijar marcador de **Fin** del fragmento.

### 3. Persistencia Ligera
Puedes guardar tu sesión de trabajo actual y recargarla más tarde desde el menú:
* **Archivo > Guardar Proyecto JSON...**
* **Archivo > Cargar Proyecto JSON...**
*(El archivo generado ocupa pocos kilobytes y guarda las rutas absolutas del video y los tiempos de tus marcadores).*

---

## 🔧 Detalles Técnicos de Alto Rendimiento
* **Renderizado Directo por Hardware (MPV Win32 Swallowing):** 
  Dear PyGui dibuja su interfaz completa en DirectX 11. Para evitar la lentitud de pasar fotogramas en Python a texturas de DPG, creamos una ventana Win32 `"STATIC"` de fondo como subventana del viewport principal, y se la asignamos a `libmpv`. MPV dibuja por hardware a 60 FPS estables sin tocar el hilo principal de la CPU.
* **Corte Instantáneo Sin Pérdida:**
  FFmpeg se ejecuta en segundo plano (`subprocess.run`) con `-c copy`. Esto significa que en lugar de decodificar y volver a codificar el video (proceso que toma minutos o gigabytes de memoria), FFmpeg extrae los paquetes binarios originales directamente y los copia a un archivo nuevo, tardando menos de 1 segundo incluso en videos enormes de 4 horas.
