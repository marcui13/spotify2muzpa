# 🎵 Spotify to Muzpa Studio (v2.0)

> **Plataforma de Alta Fidelidad para Migración de Metadatos, Búsqueda Inteligente y Descarga de Audio para DJs, Productores y Coleccionistas.**

[![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/FastAPI-Modern%20Async-009688.svg)](https://fastapi.tiangolo.com/)
[![Automation](https://img.shields.io/badge/Playwright-Chromium%20Native-2EAD33.svg)](https://playwright.dev/)
[![Scoring](https://img.shields.io/badge/FuzzyMatch-RapidFuzz-orange.svg)](https://github.com/maxbachmann/RapidFuzz)
[![ID3 Tagging](https://img.shields.io/badge/Metadata-Mutagen%20EasyID3-red.svg)](https://mutagen.readthedocs.io/)
[![Desktop Ready](https://img.shields.io/badge/Desktop-macOS%20%7C%20Windows-lightgrey.svg)](#-empaquetado-y-distribución-desktop)

---

## 📌 Tabla de Contenidos
1. [Visión General y Solución al Problema Histórico (HTTP 400)](#-visión-general-y-solución-al-problema-histórico-http-400)
2. [Arquitectura del Sistema](#-arquitectura-del-sistema)
3. [Características Principales](#-características-principales)
4. [Librerías y Dependencias de Python Utilizadas](#-librerías-y-dependencias-de-python-utilizadas)
5. [Instalación y Configuración](#-instalación-y-configuración)
6. [Guía de Uso](#-guía-de-uso)
   - [Modo 1: Aplicación de Escritorio Nativa (Desktop App)](#modo-1-aplicación-de-escritorio-nativa-desktop-app)
   - [Modo 2: Dashboard Web en Tiempo Real](#modo-2-dashboard-web-en-tiempo-real)
   - [Modo 3: Modo Consola CLI](#modo-3-modo-consola-cli)
7. [Empaquetado y Distribución Desktop (.app / .dmg / .exe)](#-empaquetado-y-distribución-desktop)
8. [Manejo de Errores y Resiliencia](#-manejo-de-errores-y-resiliencia)
9. [Términos y Condiciones de Uso](#-términos-y-condiciones-de-uso)
10. [Política de Privacidad y Descargo de Responsabilidad Legal](#-política-de-privacidad-y-descargo-de-responsabilidad-legal)
11. [Estructura del Proyecto](#-estructura-del-proyecto)

---

## 🔍 Visión General y Solución al Problema Histórico (HTTP 400)

### El Problema Anterior
En implementaciones tradicionales de scraping para plataformas SPA como Muzpa, existía una desconexión crítica entre la capa de automatización de navegador y la descarga de archivos:
- **Pérdida de Cookies y Tokens Efímeros:** El scraping se ejecutaba con Chromium, pero las descargas se delegaban a librerías como `requests.get()`. Muzpa genera tokens únicos y cabeceras dinámicas en cada interacción DOM.
- **Error HTTP 400 (Bad Request):** Los servidores de streaming rechazaban solicitudes que no incluían la huella TLS, tokens de sesión actualizados (`localStorage`) ni las cabeceras `Referer`/`Origin` auténticas.

### La Solución Implementada en la v2.0
- **Captura Nativa Playwright (`page.expect_download()`):** Las descargas se gestionan dentro del propio contexto de navegador autenticado. Al hacer clic o despachar eventos nativos, se transmiten todas las cookies de sesión, tokens y cabeceras sin interrupciones ni desincronización.
- **Cola Asíncrona No Bloqueante (`DownloadQueueManager`):** Cuando confirmas una canción, esta entra de inmediato a una cola en segundo plano con workers concurrentes. La interfaz continúa inmediatamente con la búsqueda de la siguiente canción.
- **Auto-Relleno Reactivo de Login:** Detección de campos de login y disparo de eventos reactivos (`input`, `change`) para AngularJS (`ng-model`), permitiendo iniciar sesión automáticamente o guardar credenciales de forma segura.

---

## 🏛 Arquitectura del Sistema

```
┌─────────────────────────┐          ┌──────────────────────────────────────────────┐
│  Spotify Web API        │ ───────▶ │              SpotifyService                  │
│  (Client Credentials)   │          │   (Paginación automática de 100 en 100)      │
└─────────────────────────┘          └──────────────────────┬───────────────────────┘
                                                            │
                                             ┌──────────────▼──────────────┐
                                             │     DownloadOrchestrator    │
                                             │  (Coordina Búsqueda y Cola) │
                                             └──────────────┬──────────────┘
                                                            │
                                   ┌────────────────────────┴────────────────────────┐
                                   │                                                 │
                      ┌────────────▼────────────┐                       ┌────────────▼────────────┐
                      │    MuzpaCrawlerEngine   │                       │   DownloadQueueManager  │
                      │ (Playwright Chromium +  │                       │ (Workers en Background  │
                      │   Fuzzy Match Ranker)   │                       │  + Mutagen ID3 Tagger)  │
                      └─────────────────────────┘                       └─────────────────────────┘
                                   │                                                 │
                                   └────────────────────────┬────────────────────────┘
                                                            │
                                             ┌──────────────▼──────────────┐
                                             │   FastAPI + WebSockets      │
                                             │  (Desktop UI / Web Studio)  │
                                             └─────────────────────────────┘
```

---

## ✨ Características Principales

- 🔐 **Auto-relleno y Gestión de Credenciales Muzpa:** Configuración en `.env` o desde el modal web (*Muzpa Login*). Auto-rellena credenciales emitiendo eventos DOM nativos para sincronizar el estado reactivo de AngularJS.
- ⚡ **Cola de Descargas Asíncrona No Bloqueante:** Al confirmar un track, pasa inmediatamente a la cola de descargas en segundo plano mientras el buscador pasa a la siguiente canción al instante.
- 📊 **Tracker de Descargas en Vivo (Live Download Widget):** Widget visual interactivo con animaciones de spinner, tiempo transcurrido, estado de descargas activas y contador de tracks guardados.
- 🔄 **Controles de Reset Flexibles:** Botón *Reset All* para re-procesar toda la playlist, botón *Retry Failed* para canciones con error, y botón `↺` para reiniciar cualquier pista puntual.
- 🌐 **Selector Interactivo de Navegadores:** Compatible con **Google Chrome**, **Brave Browser**, **Microsoft Edge** y **Chromium empaquetado**.
- 📁 **Organización Automática:** Guarda los archivos en `~/Downloads/<Nombre de la Playlist>/<Artista> - <Título>.mp3`.
- 🧠 **Motor de Coincidencia Difusa (`RapidFuzz`):** Scoring ponderado (Título 40%, Artista 30%, Combinado 30%) con bonificación/penalización por desvío de duración en segundos.
- 🎛 **Identificador de Tracklists en DJ Sets (SoundCloud / YouTube):** Detecta automáticamente listas completas de canciones con marcas de tiempo mediante una combinación híbrida de heurísticas textuales (capítulos de YouTube, descripciones, comentarios) y reconocimiento acústico (fingerprinting de Shazam). Se enriquece con Spotify y se envía directamente a descargar en Muzpa.
- 🏷 **Etiquetado ID3 Oficial:** Escribe metadatos de Título, Artista y Álbum directamente en el MP3 descargado (`mutagen.easyid3`).
- 💾 **Persistencia y Recuperación de Sesión:** Guarda el progreso en `state/job_<id>.json` para reanudar sin perder descargas previas.

---

## 📦 Librerías y Dependencias de Python Utilizadas

El sistema fue construido utilizando una selección de librerías modernas de alto rendimiento en el ecosistema Python:

### 1. Automatización Web, Scraping y Captura de Red
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`playwright`** | `^1.40.0` | **Motor principal de automatización y scraping.** Controla instancias reales de Chromium, gestiona perfiles persistentes (`user_data_profile`), sortea desafíos SPA de AngularJS, auto-rellena formularios emitiendo eventos DOM (`input`, `change`) y captura descargas de audio autenticadas mediante `page.expect_download()`. |

### 2. Backend Asíncrono, API REST y Comunicación en Tiempo Real
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`fastapi`** | `^0.100.0` | **Framework web backend.** Proporciona los endpoints REST para control de jobs, decisiones manuales, endpoints de reset, gestión de credenciales y orquestación del ciclo de vida (`lifespan`). |
| **`uvicorn[standard]`** | `^0.22.0` | **Servidor ASGI asíncrono de alto rendimiento.** Ejecuta la aplicación FastAPI con aceleración de `uvloop` y `httptools`. |
| **`websockets`** | `^12.0` | **Canal de streaming bidireccional.** Transmite en tiempo real el log de ejecución estructurado, cambios de estado de canciones y métricas de la cola de descargas directamente al frontend. |
| **`aiofiles`** | `^23.0.0` | **I/O asíncrono de archivos.** Permite lectura y escritura no bloqueante de archivos estáticos y persistencia de estado JSON. |

### 3. Integración con APIs y Extracción de Metadatos
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`spotipy`** | `^2.23.0` | **Cliente oficial de la API de Spotify.** Implementa el flujo *Client Credentials*, extrae metadatos oficiales (título, artista, álbum, duración, carátulas) y gestiona paginación automática de 100 en 100 tracks. |
| **`requests`** / **`httpx`** | `^2.31.0` / `^0.25.0` | **Clientes HTTP sincrónicos y asíncronos.** Empleados en el motor de respaldo (*fallback parser*) para extraer playlists públicas directamente desde endpoints embebidos sin depender de tokens. |

### 4. Algoritmos de Búsqueda y Procesamiento de Audio
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`rapidfuzz`** | `^3.0.0` | **Motor de coincidencia difusa (Fuzzy Matching) en C++.** Calcula similitud con `token_set_ratio` y `token_sort_ratio` ponderando título, artista y variaciones de nombres para clasificar los mejores resultados de Muzpa. |
| **`mutagen`** | `^1.47.0` | **Manipulación y etiquetado de metadatos de audio.** Inyecta etiquetas oficiales ID3v2.3/ID3v2.4 (`EasyID3`, `MP3`) en los archivos `.mp3` descargados para que los reproductores y software de DJ (Traktor, Rekordbox, VirtualDJ) los reconozcan inmediatamente. |
| **`yt-dlp`** | `^2024.0.0` | **Extracción de audio y metadatos.** Extrae capítulos, descripciones y pistas de audio de YouTube y SoundCloud sin descargas innecesarias. |
| **`shazamio-core`** | `^1.1.0` | **Reconocimiento acústico.** Genera huellas acústicas nativas en Rust y consulta la base de datos de Shazam de forma gratuita y local. |

### 5. Validación de Datos, Configuración y CLI
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`pydantic`** & **`pydantic-settings`** | `^2.0.0` | **Modelado de dominio y validación estricta.** Define contratos de datos tipados (`SpotifyTrack`, `MuzpaCandidate`, `TrackState`, `PlaylistJob`) y centraliza la configuración desde variables de entorno. |
| **`python-dotenv`** | `^1.0.0` | **Carga de variables de entorno.** Lee archivos `.env` locales de forma segura. |
| **`rich`** | `^13.0.0` | **Interfaz visual en terminal.** Renderizado de tablas, paneles de progreso, colores y menús interactivos de selección de navegador en modo consola. |

### 6. Aplicación de Escritorio y Empaquetado Autónomo
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`pywebview`** | `^5.0.0` | **Wrapper de interfaz gráfica nativa.** Crea ventanas de escritorio Cocoa (macOS WebKit) o WebView2 (Windows) para ejecutar la suite como aplicación de escritorio independiente. |
| **`pyinstaller`** | `^6.0.0` | **Empaquetador y generador de binarios.** Compila el código fuente en bundles autónomos (`.app` y `.dmg` para macOS, `.exe` para Windows). |

### 7. Pruebas Unitarias y Aseguramiento de Calidad
| Librería | Versión | Rol en el Proyecto |
| :--- | :--- | :--- |
| **`pytest`** & **`pytest-asyncio`** | `^7.4.0` / `^0.21.0` | **Suite de testing automatizado.** Ejecución de pruebas unitarias sobre extracción de Spotify, algoritmo fuzzy, sanitización de archivos, cola asíncrona y endpoints REST. |

---

## 🚀 Instalación y Configuración

### 1. Requisitos del Sistema
- Python 3.9 o superior.
- Credenciales gratuitas de la API de Spotify ([Spotify Developer Dashboard](https://developer.spotify.com/dashboard)).

### 2. Clonar el Repositorio
```bash
git clone https://github.com/tu-usuario/spotify2muzpa.git
cd spotify2muzpa
```

### 3. Crear Entorno Virtual e Instalar Dependencias
```bash
python3 -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Configurar Variables de Entorno (`.env`)
```bash
cp .env.example .env
```

Edita `.env` con tus claves:
```ini
# Credenciales oficiales de Spotify API
SPOTIFY_CLIENT_ID="tu_client_id_aqui"
SPOTIFY_CLIENT_SECRET="tu_client_secret_aqui"

# Opcional: Credenciales de cuenta en Muzpa para auto-login
MUZPA_EMAIL="tu_email@ejemplo.com"
MUZPA_PASSWORD="tu_password"

# Configuración de ejecución
AUTO_MODE=false
SIMILARITY_THRESHOLD=75.0
HEADLESS=false
```

---

## 💻 Guía de Uso

### Modo 1: Aplicación de Escritorio Nativa (Desktop App)
Inicia la aplicación en una ventana nativa de escritorio independiente:
```bash
python desktop.py
```
Se abrirá una ventana de escritorio con tema oscuro integrada con macOS Cocoa o Windows WebView.

---

### Modo 2: Dashboard Web en Tiempo Real
Inicia el servidor local y accede desde cualquier navegador:
```bash
python run.py --server
```
1. Ingresa a `http://localhost:8000`.
2. Pega la URL de cualquier playlist de Spotify (pública o privada) y presiona **"Load Playlist"**.
3. Revisa y confirma coincidencias o activa el interruptor **Auto Mode** para procesar automáticamente las canciones que superen el porcentaje de similitud configurado.

---

### Modo 3: Modo Consola CLI
Para entornos sin interfaz gráfica o automatizaciones por script:
```bash
# Modo interactivo en terminal:
python run.py --playlist-url "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

# Modo 100% automático:
python run.py --playlist-url "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" --auto --threshold 80
```

---

### Modo 4: Identificador de Tracklists en DJ Sets (SoundCloud / YouTube)
Para extraer el tracklist completo de sesiones de DJs, sets en vivo (Cercle, Boiler Room, etc.) o mezclas de SoundCloud:
1. Inicia el servidor con `python server.py` y abre `http://localhost:8000`.
2. Haz clic en la pestaña **"DJ Set Link (YouTube / SoundCloud)"**.
3. Pega cualquier enlace de YouTube o SoundCloud (por ejemplo, sets de 1 a 3+ horas).
4. Haz clic en **"Identify Tracklist"**:
   - **Capa Heurística:** Si el set tiene marcas de tiempo en la descripción, capítulos o comentarios fijados, se extraen instantáneamente en < 2 segundos.
   - **Capa Acústica Adaptativa (Shazam):** Si el set no tiene lista de temas escrita, el sistema descarga el stream en segundo plano, corta fragmentos inteligentes con `ffmpeg`, los identifica con huellas acústicas nativas de Shazam evitando rate-limits mediante saltos adaptativos de 3 minutos, y enriquece cada track con BPM, Tonalidad Camelot (ej. `8A`, `11B`) y carátula oficial de Spotify.
5. Puedes exportar el tracklist a texto, sincronizarlo con Spotify o hacer clic en **"Download in Muzpa"** para descargar automáticamente todos los MP3 a 320 kbps.

---

## 🧹 Gestión de Archivos y Almacenamiento Local (Limpieza de Temporales)

Para mantener el disco limpio y optimizado, es importante comprender qué archivos se guardan y dónde:

### 1. ¿Dónde se guardan los archivos descargados definitivos?
- **Destino:** Por defecto, las canciones finales descargadas en MP3 (320 kbps) con sus etiquetas ID3 oficiales se guardan en:
  - macOS / Linux: `~/Downloads/<Nombre de la Playlist o DJ Set>/`
  - Windows: `C:\Users\<TuUsuario>\Downloads\<Nombre de la Playlist o DJ Set>\`
- Puedes cambiar este directorio editando `DOWNLOAD_DIR` en tu archivo `.env`.

### 2. ¿Dónde se guardan los archivos temporales de análisis acústico?
- **Directorios temporales del sistema:** Durante el análisis acústico de DJ sets largos, `yt-dlp` y `ffmpeg` procesan el audio dentro de carpetas temporales con prefijo `djset_audio_` y `djset_slices_`.
  - En macOS: Se ubican bajo `/var/folders/.../T/` o `/tmp/`.
  - En Linux / Windows: Se ubican en el directorio temporal estándar del sistema operativo.
- **Autolimpieza automática:** El código utiliza administradores de contexto seguros de Python (`tempfile.TemporaryDirectory`). **Tan pronto como finaliza o se cancela el análisis, la carpeta temporal completa y el audio descargado se eliminan automáticamente del disco.** Además, cada fragmento individual `.wav` se borra en memoria/disco inmediatamente tras ser reconocido por Shazam.

### 3. Cómo limpiar datos en caché periódicamente
Si utilizas la aplicación con frecuencia, puedes liberar espacio residual de las siguientes fuentes:

```bash
# 1. Limpiar la caché interna de descargas de yt-dlp:
yt-dlp --rm-cache-dir

# 2. Limpiar perfiles temporales de navegador antiguos (si deseas reiniciar sesión en Muzpa):
rm -rf user_data_profile/

# 3. Limpiar archivos de caché de Python y temporales de pytest:
find . -type d -name "__pycache__" -exec rm -rf {} +
rm -rf .pytest_cache
```

---

## 📦 Empaquetado y Distribución Desktop

Para generar ejecutables autónomos de un solo clic que no requieran que el usuario instale Python ni dependencias manuales:

### Compilar para macOS (`.app` y `.dmg`)
Ejecuta el script de empaquetado automatizado:
```bash
python build_desktop.py
```
- **Resultado:** Encontrarás el paquete `dist/Spotify2MuzpaStudio.app` y la imagen instaladora `dist/Spotify2MuzpaStudio-macOS.dmg`.

### Compilar para Windows (`.exe`)
En una máquina con Windows:
```cmd
python build_desktop.py
```
- **Resultado:** Encontrarás el ejecutable `dist\Spotify2MuzpaStudio\Spotify2MuzpaStudio.exe`.

---

## 🛠 Manejo de Errores y Resiliencia

- **Reintentos Inteligentes:** Las descargas cuentan con reintentos exponenciales configurables (`MAX_RETRIES=3`).
- **Paginación Robusta:** Procesa listas de 500+ pistas solicitando lotes de 100 elementos sin saturar la cuota de la API.
- **Sanitización de Nombres de Archivo:** Limpieza estricta de caracteres incompatibles con el sistema de archivos (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`).
- **Tolerancia a Fallos y Reanudación:** Si el proceso se detiene, al recargar la misma playlist se recupera el progreso exacto desde el archivo local `state/`.

---

## 📜 Términos y Condiciones de Uso

Al utilizar este software (**"Spotify to Muzpa Studio"**), aceptas expresamente los siguientes términos:

1. **Uso Personal y Educativo:** Esta herramienta ha sido diseñada exclusivamente con fines de investigación técnica, interoperabilidad de metadatos, desarrollo educativo y realización de copias de seguridad de audio de uso estrictamente personal.
2. **Responsabilidad del Usuario:** El usuario final asume total y absoluta responsabilidad por el uso que haga de esta aplicación, así como por el cumplimiento de los Términos de Servicio (ToS) y directrices de las plataformas web de terceros con las que interactúe (incluyendo Spotify AB y Muzpa).
3. **Prohibición de Uso Comercial no Autorizado:** Queda prohibida la redistribución, venta, retransmisión o explotación comercial de obras musicales protegidas por derechos de propiedad intelectual obtenidas mediante el uso de este software.
4. **Sin Garantías (AS IS):** El software se distribuye "tal cual" (*AS IS*), sin garantías expresas ni implícitas de disponibilidad ininterrumpida, exactitud de metadatos o adecuación para un fin particular.

---

## 🔒 Política de Privacidad y Descargo de Responsabilidad Legal

### 1. Privacidad y Seguridad Local (*Local-First Architecture*)
- **Cero Telemetría Externa:** Este software no recopila, almacena ni transmite datos personales, hábitos de escucha, URLs de playlists ni archivos descargados a ningún servidor externo o de terceros gestionado por los desarrolladores.
- **Credenciales Seguras en tu Máquina:** Tanto las claves de Spotify API (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`) como las credenciales de Muzpa y las cookies de sesión del navegador se guardan **100% de forma local** en tu propio equipo (`.env` y `./user_data_profile/`).

### 2. Propiedad Intelectual y Marcas Registradas
- **Spotify®:** Es una marca registrada de **Spotify AB**. Este proyecto es una herramienta independiente y **no está afiliado, respaldado, certificado ni patrocinado** de ninguna manera por Spotify AB ni por ninguna de sus subsidiarias.
- **Muzpa:** Es una marca/plataforma independiente. Este proyecto no mantiene ninguna relación comercial ni técnica con los propietarios o administradores de dicha plataforma.
- **Derechos de Autor (Copyright):** Los derechos patrimoniales y morales sobre las obras musicales, carátulas, fonogramas y metadatos pertenecen a sus respectivos autores, artistas, compositores y sellos discográficos. Este software no almacena ni distribuye material con copyright en servidores propios.

---

## 📂 Estructura del Proyecto

```
spotify2muzpa/
├── config.py             # Configuración centralizada Pydantic & variables .env
├── models.py             # Modelos de dominio tipados (SpotifyTrack, Candidate, TrackState)
├── spotify_service.py    # Cliente Spotify API con paginación automática y fallback
├── muzpa_crawler.py      # Crawler Playwright, auto-login y motor de coincidencia difusa (rapidfuzz)
├── downloader.py         # DownloadQueueManager asíncrono, Mutagen ID3 Tagger y persistencia
├── server.py             # Servidor FastAPI, endpoints REST y WebSockets en tiempo real
├── desktop.py            # Launcher de aplicación de escritorio nativa (PyWebView / Cocoa)
├── build_desktop.py      # Script de empaquetado multiplataforma (.app / .dmg / .exe)
├── run.py                # Entrypoint unificado (CLI & Servidor Web)
├── static/
│   └── index.html        # Dashboard Web interactivo (Tailwind, WebSockets, Dark Theme)
├── tests/                # Suite completa de pruebas unitarias (PyTest)
├── requirements.txt      # Dependencias del proyecto
├── .env.example          # Plantilla de variables de entorno
└── state/                # Almacén local de persistencia de jobs (git-ignored)
```

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Consulta el archivo `LICENSE` para más información.
