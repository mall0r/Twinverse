[English](../README.md) | [Português (Brasil)](./README.pt-br.md) | [Français](./README.fr.md) | [Español](./README.es.md)

# MultiScope

**MultiScope** es una herramienta de código abierto para Linux que permite la creación y gestión de múltiples instancias de gamescope, permitiendo que varios jugadores jueguen simultáneamente en un solo ordenador.

---

## Estado del Proyecto

MultiScope se encuentra actualmente en desarrollo activo, pero ya es completamente funcional para usuarios con **tarjetas gráficas AMD**. Aún no se han realizado pruebas en hardware **NVIDIA**, por lo que no se garantiza la compatibilidad.

- **Compatibilidad:**
  - ✅ **AMD:** Totalmente compatible
  - ⚠️ **NVIDIA:** Requiere pruebas
  - ⚠️ **Intel:** Requiere pruebas

## El Problema que Resuelve MultiScope

Muchos jugadores que se pasan a Linux echan de menos herramientas como **Nucleus Coop**, que facilitan el multijugador local en juegos que no lo soportan de forma nativa. MultiScope fue creado para llenar este vacío, ofreciendo una solución robusta y fácil de usar para que amigos y familiares puedan jugar juntos en el mismo PC, aunque no tengan varios ordenadores.

## Características

- **Gestión de Perfiles:** Crea, edita y elimina perfiles para diferentes juegos y configuraciones.
- **Interfaz Gráfica Amigable:** Una interfaz intuitiva para gestionar perfiles e instancias de juego.
- **Soporte para Múltiples Pantallas:** Configura cada instancia del juego para que se ejecute en una pantalla específica.
- **Configuración de Audio:** Dirige el audio de cada instancia a diferentes dispositivos de salida.
- **Soporte para Múltiples Teclados y Ratones:** Asigna dispositivos de entrada específicos a cada jugador.

## Demostración

*(Espacio reservado para capturas de pantalla, GIFs o vídeos de MultiScope en acción. Para añadir una imagen, utiliza la siguiente sintaxis:)*
`![Descripción de la Imagen](URL_DE_LA_IMAGEN)`

## Instalación

La forma más sencilla de instalar MultiScope es utilizando el paquete de la versión, que se encarga de todo por ti.

1.  **Descarga la última versión:**
    Ve a la página de [Releases](https://github.com/Mallor705/MultiScope/releases) y descarga el archivo `MultiScope.tar.gz`.

2.  **Extrae el archivo:**
    ```bash
    tar -xzvf MultiScope.tar.gz
    ```

3.  **Navega a la carpeta extraída:**
    (El nombre de la carpeta puede variar según la versión)
    ```bash
    cd MultiScope-*
    ```

4.  **Ejecuta el script de instalación:**
    ```bash
    ./install.sh
    ```

Después de la instalación, podrás encontrar MultiScope en el menú de aplicaciones de tu sistema o ejecutarlo desde el terminal con el comando `multi-scope gui`. El paquete también incluye un script `uninstall.sh` para eliminar la aplicación.

## Cómo Usar

1.  **Abre MultiScope:** Inicia la aplicación desde el menú de aplicaciones o el terminal.
2.  **Crea un Perfil:**
    - Haz clic en "Añadir Perfil".
    - Dale un nombre al perfil (ej: "Stardew Valley - Jugador 1").
    - Configura las opciones de pantalla, audio y dispositivos de entrada.
    - Guarda el perfil.
3.  **Inicia un Juego:**
    - Selecciona el perfil deseado.
    - Haz clic en "Iniciar" para abrir el juego con la configuración definida.

## Compilando desde el Código Fuente

Si eres desarrollador y deseas compilar el proyecto manualmente, sigue los siguientes pasos:

1.  **Clona el repositorio:**
    ```bash
    git clone https://github.com/Mallor705/MultiScope.git
    cd MultiScope
    ```

2.  **Para ejecutar directamente desde el código fuente:**
    - Crea y activa un entorno virtual:
      ```bash
      python3 -m venv .venv
      source .venv/bin/activate
      ```
    - Instala las dependencias:
      ```bash
      pip install -r requirements.txt
      ```
    - Ejecuta la aplicación:
      ```bash
      ./run.sh
      ```
    
3.  **Para compilar e instalar desde el código fuente:**
    ```bash
    ./build.sh
    ./install.sh
    ```

## Cómo Contribuir

¡Agradecemos tu interés en contribuir a MultiScope! Si deseas ayudar, sigue estas directrices:

1.  **Haz un Fork del Repositorio:** Crea una copia del proyecto en tu cuenta de GitHub.
2.  **Crea una Rama:** Crea una rama para tu nueva funcionalidad o corrección (`git checkout -b mi-funcionalidad`).
3.  **Realiza tus Cambios:** Implementa tus mejoras o correcciones.
4.  **Envía una Pull Request:** Abre una Pull Request detallando tus cambios.

Toda contribución es bienvenida, desde correcciones de errores hasta la implementación de nuevas funcionalidades.

## Licencia

Este proyecto está licenciado bajo la **Licencia Pública General de GNU v3.0 (GPL-3.0)**. Para más detalles, consulta el archivo [LICENSE](LICENSE).
