# Guía de MultiScope

¡Bienvenido a la guía de MultiScope! Este documento te guiará por el proceso de configuración y uso de la aplicación MultiScope para ejecutar múltiples instancias de Steam.

[IMAGEN]

## 1. Número de instancias

Primero, necesitas decidir cuántas instancias de Steam deseas ejecutar. MultiScope soporta hasta 8 instancias en total.

- **Pantalla dividida (Splitscreen):** Puedes ejecutar un máximo de 4 instancias por monitor.
- **Pantalla completa (Fullscreen):** Puedes ejecutar un máximo de 1 instancia por monitor.

Usa el selector numérico "Número de instancias" para definir la cantidad deseada.

[IMAGEN]

## 2. Modo de pantalla

Puedes elegir entre dos modos de pantalla:

- **Pantalla completa (Fullscreen):** Cada instancia se ejecutará en un monitor separado.
- **Pantalla dividida (Splitscreen):** Las instancias se distribuirán en un solo monitor, ya sea horizontal o verticalmente.

### Opciones de Pantalla dividida

Al seleccionar "Splitscreen", puedes elegir entre dos orientaciones:

- **Horizontal:** Las instancias se colocan una al lado de la otra.
- **Vertical:** Las instancias se colocan una encima de la otra.

Las posiciones y los formatos varían automáticamente según el número de instancias.

Nota: La organización automática de las instancias solo funciona con entornos KDE Plasma.

[IMAGEN]

## 3. Configuración de la instancia

Para cada instancia, puedes configurar las siguientes opciones:

- **Control (Gamepad):** Asignar un control específico a la instancia.
- **Capturar Mouse y Teclado:** Dedicar el mouse y el teclado a una sola instancia. Por ahora, solo una instancia a la vez puede usar el mouse y el teclado.
- **Dispositivo de audio:** Seleccionar un dispositivo de salida de audio específico para la instancia.
- **Tasa de actualización (Refresh Rate):** Definir la tasa de actualización para la instancia. Es útil si quieres limitar los FPS o usar una tasa de actualización específica.

[IMAGEN]

## 4. Iniciar una instancia

Después de configurar una instancia, haz clic en el botón **"Iniciar"** junto a ella para lanzar una instancia aislada de Steam sin gamescope. La primera vez, Steam se instalará automáticamente; este proceso puede tomar unos minutos.

Cada instancia puede iniciarse individualmente con su botón **"Iniciar"**. Para ejecutar varias a la vez, utiliza el botón **"Jugar"** ubicado en la parte inferior de la ventana.

Solo las instancias que ya tienen Steam instalado pueden iniciarse con el botón **"Jugar"**. Puedes verificarlo por el ícono de palomita (✓) en la instancia. Si el ícono no está presente, instala Steam haciendo clic en el botón **"Iniciar"** de esa instancia. Esto permite configurar, agregar juegos o aplicaciones de manera rápida y directa en una instancia específica.

[IMAGEN]

## 5. Modo Big Picture de Steam

Para una mejor experiencia, se recomienda activar el "Modo Big Picture" en la configuración de Steam. Esto proporcionará una interfaz amigable para controles, ideal para MultiScope.

Para hacerlo, ve a `Configuración > Interfaz` y marca la casilla para "Iniciar Steam en modo Big Picture".

Repite este proceso para todas las instancias que desees iniciar en Modo Big Picture.

[IMAGEN]

## 6. Jugar

¡Cuando todas tus instancias estén configuradas y en ejecución, puedes comenzar a jugar! Cada instancia tendrá sus propios dispositivos de entrada y audio dedicados, permitiéndote jugar con tus amigos o familiares en la misma computadora.

¡Disfruta tu sesión de juego!

[IMAGEN]

## 7. Aplicaciones (Opcional)

Para agregar aplicaciones a tu instancia, ve a `Agregar un juego` y haz clic en "Agregar un juego que no es de Steam...". Selecciona la aplicación que deseas agregar.

### ¿Por qué hacer esto?

Esto te permite ejecutar aplicaciones directamente desde la instancia, haciendo posible tener una configuración única por instancia para esa aplicación. Esto sucede porque cada instancia tiene su propio directorio HOME único. Se pueden encontrar en `~/.local/share/multiscope/home_{n}`.

Un buen ejemplo de uso es [mangojuice](https://github.com/radiolamp/mangojuice); si quieres usarlo con configuraciones personalizadas, necesitarás ejecutarlo y configurarlo para cada instancia individualmente.

[IMAGEN]
