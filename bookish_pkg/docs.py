"""
Technical cheat sheet and interactive documentation for the Bookish PDF Converter.
Provides quick reference accessible from both the CLI and Neovim floating window.
"""

import os
import json


def get_converter_cheatsheet() -> str:
    """
    Returns a concise, practical cheat sheet for the Markdown to PDF converter.
    """
    return """================================================================================
                    CONVERTER FORMAT & CHEAT SHEET
================================================================================

1. SINTAXIS RÁPIDA DE IMÁGENES EN MARKDOWN
--------------------------------------------------------------------------------
Sintaxis extendida: ![Texto de Leyenda|clase1|clase2](ruta/a/imagen.png)

Ejemplos:
  ![Esquema del Circuito|center|w-50](circuito.png)
  -> Imagen centrada, al 50% del ancho, con pie de foto "Esquema del Circuito".

  ![Captura de Ejecución|center|screenshot](captura.png)
  -> Imagen centrada con marco/borde gris académico.

  ![Diagrama en Bloque|center|w-75|medium](diagrama.png)
  -> Imagen centrada, 75% ancho y máximo 4.0 pulgadas de altura.

  ![|center|w-50](foto.png)
  -> Sin pie de foto si no se coloca texto antes del primer '|'.


2. CLASES UTILITARIAS DISPONIBLES
--------------------------------------------------------------------------------
- Alineación:
    center, img-center : Centrado en bloque (margin: auto)
    left               : Flotante a la izquierda con margen derecho
    right              : Flotante a la derecha con margen izquierdo

- Anchura Proporcional:
    w-25               : 25% del ancho de la página
    w-50               : 50% del ancho de la página
    w-75               : 75% del ancho de la página
    w-100              : 100% del ancho de la página

- Altura Máxima (Escala Absoluta):
    small              : Altura máx 2.2 in (firmas o diagramas pequeños)
    medium             : Altura máx 4.0 in (esquemas de circuitos medianos)
    large              : Altura máx 6.5 in (gráficos o diagramas verticales)

- Estilos Especiales:
    screenshot         : Marco gris sutil (#cccccc) y centrado


3. SINTAXIS HTML AVANZADA
--------------------------------------------------------------------------------
- Figuras con pie de foto explícito:
    <figure class="center w-50">
      <img src="simulacion.png" class="center w-50" alt="Simulación" />
      <figcaption>Figura 1: Simulación en Proteus / Multisim</figcaption>
    </figure>

- Grilla de 2 imágenes lado a lado (comparativas):
    <div class="image-grid-2">
      <figure>
        <img src="circuito_teorico.png" />
        <figcaption>Circuito Teórico</figcaption>
      </figure>
      <figure>
        <img src="circuito_medido.png" />
        <figcaption>Medición Osciloscopio</figcaption>
      </figure>
    </div>


4. SALTOS DE PÁGINA
--------------------------------------------------------------------------------
Para forzar un salto de página antes de una sección o imagen:
    <div class="page-break"></div>
O usando clases CSS directas en elementos:
    <h2 class="page-break-before">Nueva Sección</h2>


5. TABLAS Y CÓDIGO
--------------------------------------------------------------------------------
- Tablas estándar en Markdown:
    | Parámetro | Valor Teórico | Valor Medido | Error (%) |
    |---|---|---|---|
    | Vsal | 5.0 V | 4.92 V | 1.6% |
    | Rin  | 2.0 kΩ | 2.01 kΩ | 0.5% |

- Bloques de código con resaltado:
    ```python
    def calcular_ganancia(r_f, r_in):
        return 1 + (r_f / r_in)
    ```

6. NORMALIZACIÓN DE RUTAS DE WINDOWS EN WSL
--------------------------------------------------------------------------------
Puedes pegar directamente rutas absolutas de Windows en tu Markdown:
    ![Evidencia|center|w-50](C:\\Users\\frank\\Pictures\\foto.png)
El convertidor traduce automáticamente C:\\ a /mnt/c/ sin errores.
================================================================================
"""
