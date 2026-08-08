# IFC BIM Technical Test

Aplicación web local para cargar, procesar, visualizar y analizar modelos IFC.
Cubre registro/login, procesamiento BIM con IfcOpenShell, persistencia en PostgreSQL,
visor 3D interactivo y un dashboard analítico con Chart.js.

Todo el runtime funciona localmente mediante Docker Compose, sin dependencias externas
en tiempo de ejecución.

---

## Funcionalidades principales

**Autenticación**

- Registro de usuarios con validación de correo electrónico.
- Hash de contraseña con Argon2.
- Login mediante formulario estándar OAuth2.
- Access token JWT firmado con HS256.
- Endpoint protegido `/auth/me` para consultar el usuario autenticado.
- Token almacenado exclusivamente en memoria React (sin localStorage ni sessionStorage).

**Carga y procesamiento de modelos IFC**

- Upload de archivos `.ifc` con validación de nombre, extensión, contenido no vacío y límite de tamaño.
- La validez estructural del contenido IFC se determina posteriormente durante el procesamiento con IfcOpenShell.
- Almacenamiento local con nombre UUID (no expone nombre original en el sistema de archivos).
- Transición de estados: `PENDING → PROCESSING → COMPLETED | FAILED`.
- Procesamiento asíncrono mediante FastAPI `BackgroundTasks`.
- Parseo con IfcOpenShell 0.8.5.
- Extracción y persistencia de:
  - Jerarquía espacial (IfcProject, IfcSite, IfcBuilding, IfcBuildingStorey, IfcSpace).
  - Elementos constructivos con GlobalId, clase IFC, tipo y containment.
  - Tipos de elementos con referencia cruzada.
  - PropertySets (PSET) y Quantities (QTO) por elemento.
- Errores clasificados: archivo inválido/corrupto vs. schema no soportado.
- Mensajes de error públicos sin traceback ni rutas físicas.

**Visor 3D**

- Visualización del modelo IFC en Three.js mediante That Open Components y web-ifc.
- Controles orbit, pan y zoom.
- Selección de elementos mediante clic en el modelo.
- Panel BIM lateral con GlobalId, clase, tipo, planta y PropertySets/QTOs del elemento seleccionado.
- Datos del panel servidos desde PostgreSQL, no recalculados en el visor.

**Dashboard analítico**

- Métricas agregadas: total de elementos, nodos espaciales, propiedades y elementos sin planta resuelta.
- Gráfico de barras horizontales por clase IFC (Chart.js, top 15 clases en UI).
- Tabla de distribución por planta con elevación y conteo.
- Tabla paginada de elementos con GlobalId, clase, nombre, tipo y planta.
- Todos los datos provienen de PostgreSQL; el IFC no se vuelve a abrir.

---

## Arquitectura

```text
Navegador
    |
    v
  Nginx (puerto 5173)
    |-- /         → SPA React
    |-- /api/*    → proxy → FastAPI (puerto 8000)

React + TypeScript (Vite)
    ├── Dashboard / Chart.js          (analítica)
    ├── That Open / web-ifc / Three.js (visor 3D)
    └── /api/*                        (fetch al backend)
              |
              v
           FastAPI
              ├── JWT / auth
              ├── upload + validación
              ├── BackgroundTasks → IfcOpenShell
              ├── consultas BIM
              ├── analytics
              │
              ├── SQLAlchemy → PostgreSQL 17
              │
              └── storage/ (archivos IFC locales, bind mount del host)
```

**Separación canónica de responsabilidades**

```text
BACKEND (fuente de verdad BIM)
    IfcOpenShell
        → extracción y persistencia
        → PostgreSQL

FRONTEND (visualización)
    That Open / web-ifc
        → renderizado 3D e interacción
        → no persiste datos BIM
```

El visor renderiza el archivo IFC descargado bajo demanda.
Los datos del panel BIM y del dashboard se consultan exclusivamente desde PostgreSQL.

---

## Flujo de procesamiento IFC

```text
POST /api/v1/models (upload)
    |
    v
validación (extensión, tamaño, nombre)
    |
    v
almacenamiento local (UUID.ifc)
    |
    v
persist → PENDING
    |
    v
BackgroundTask disparada
    |
    v
PROCESSING
    |
    v
ifcopenshell.open()
    ├── SchemaError → FAILED ("El esquema IFC del archivo no está soportado.")
    └── Exception   → FAILED ("No se pudo procesar el archivo IFC.")
    |
    v (si open() exitoso)
extract_and_persist_spatial_structure
    |
    v
extract_and_persist_elements
    |
    v
extract_and_persist_element_properties (PSET / QTO)
    |
    v
COMPLETED
```

El procesamiento usa FastAPI `BackgroundTasks`, que corre en el mismo proceso del servidor.
Es suficiente para el alcance local definido. No se utiliza Redis, Celery ni ninguna cola
durable, porque están fuera del alcance requerido.

---

## Modelo de datos y persistencia

**Tablas**

```text
users
  └── ifc_models (owner_id → users.id)
        ├── spatial_nodes (model_id → ifc_models.id)
        │      └── parent_id → spatial_nodes.id  (jerarquía)
        └── elements (model_id → ifc_models.id)
               ├── direct_spatial_node_id → spatial_nodes.id
               ├── resolved_storey_id     → spatial_nodes.id
               ├── parent_element_id      → elements.id
               └── element_properties (element_id → elements.id)
```

**Campos clave**

| Tabla               | Campos destacados |
|---------------------|-------------------|
| `users`             | email, hashed_password, is_active |
| `ifc_models`        | status, ifc_schema, sha256, element_count, spatial_node_count, property_count |
| `spatial_nodes`     | global_id, ifc_type, name, elevation, parent_id |
| `elements`          | global_id, ifc_type, name, object_type, tag, predefined_type, type_global_id, type_ifc_type, type_name |
| `element_properties`| group_type (PSET/QTO), group_name, property_name, value_kind, value_text/number/boolean, unit |

Las migraciones son gestionadas exclusivamente por Alembic.

---

## Tecnologías

**Backend**

| Componente    | Versión |
|---------------|---------|
| Python        | 3.12    |
| FastAPI       | 0.139.2 |
| IfcOpenShell  | 0.8.5   |
| SQLAlchemy    | 2.0.51  |
| Alembic       | 1.19.0  |
| psycopg       | 3.3.4   |
| pwdlib/Argon2 | 0.3.0   |
| PyJWT         | 2.13.0  |

**Frontend**

| Componente              | Versión |
|-------------------------|---------|
| React                   | 19.x    |
| TypeScript              | 6.x     |
| Vite                    | 8.x     |
| That Open Components    | 3.4.8   |
| That Open Fragments     | 3.4.7   |
| web-ifc                 | 0.0.77  |
| Three.js                | 0.184.0 |
| Chart.js                | 4.5.1   |
| camera-controls         | 3.1.2   |

**Infraestructura**

- Docker / Docker Compose
- Nginx (alpine)
- PostgreSQL 17

Chart.js y el viewer (web-ifc, Three.js) se empaquetan localmente por Vite.
No se carga ninguna dependencia desde CDN en tiempo de ejecución.

---

## Requisitos previos

Para ejecutar la aplicación:

- Git
- Docker Desktop (Windows/macOS) o Docker Engine + Docker Compose (Linux)

Node.js y Python no son necesarios para ejecutar la aplicación con Docker.
Son necesarios únicamente para validaciones locales fuera de contenedor.

---

## Variables de entorno

Basado en `.env.example`:

| Variable                    | Descripción                                             |
|-----------------------------|---------------------------------------------------------|
| `POSTGRES_DB`               | Nombre de la base de datos                              |
| `POSTGRES_USER`             | Usuario de PostgreSQL                                   |
| `POSTGRES_PASSWORD`         | Contraseña de PostgreSQL                                |
| `POSTGRES_PORT`             | Puerto expuesto en el host (default 5432)               |
| `POSTGRES_HOST`             | Nombre del servicio de base de datos (default `db`)     |
| `POSTGRES_INTERNAL_PORT`    | Puerto interno del contenedor PostgreSQL                |
| `BACKEND_PORT`              | Puerto expuesto del backend en el host (default 8000)   |
| `FRONTEND_PORT`             | Puerto expuesto del frontend en el host (default 5173)  |
| `JWT_SECRET_KEY`            | Clave secreta para firmar y verificar tokens JWT        |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Tiempo de expiración del access token (default 30)    |
| `IFC_STORAGE_DIR`           | Directorio de almacenamiento de archivos IFC            |
| `IFC_MAX_FILE_SIZE_MB`      | Tamaño máximo de archivo IFC permitido (default 50)     |

**Consideraciones**

- El archivo `.env` está excluido de Git. No versionar secretos.
- Cambiar `POSTGRES_PASSWORD` y `JWT_SECRET_KEY` antes de cualquier uso.
- `JWT_SECRET_KEY` debe ser largo y aleatorio.
- **No sobrescribir un `.env` existente sin respaldarlo**: en un volumen PostgreSQL ya
  inicializado, cambiar `POSTGRES_PASSWORD` en `.env` no modifica automáticamente la
  contraseña del rol almacenado en PostgreSQL. Esto puede provocar que Alembic y el
  backend no puedan autenticarse aunque PostgreSQL esté levantado y healthy.

---

## Instalación y ejecución

**Primera instalación (PowerShell)**

```powershell
Copy-Item .env.example .env
# Editar .env: cambiar POSTGRES_PASSWORD y JWT_SECRET_KEY

docker compose up -d --build
docker compose ps
```

**Primera instalación (Linux/macOS)**

```bash
cp .env.example .env
# Editar .env: cambiar POSTGRES_PASSWORD y JWT_SECRET_KEY

docker compose up -d --build
docker compose ps
```

**Orden de arranque automático**

```text
PostgreSQL (healthcheck)
    |
    v (healthy)
alembic upgrade head   ← automático al iniciar el backend
    |
    v (exit 0)
uvicorn (FastAPI)
    |
    v (healthy)
frontend (Nginx)
```

No es necesario ejecutar `alembic upgrade head` manualmente. El backend lo ejecuta
automáticamente antes de iniciar Uvicorn. Si la migración falla, Uvicorn no arranca.

**URLs predeterminadas**

| Servicio | URL                                  |
|----------|--------------------------------------|
| Frontend | http://127.0.0.1:5173                |
| Backend  | http://127.0.0.1:8000                |
| Swagger  | http://127.0.0.1:8000/docs           |
| Health   | http://127.0.0.1:8000/api/v1/health  |

**Detener servicios**

```bash
docker compose down
```

> **Advertencia:** El siguiente comando elimina el volumen de PostgreSQL y por tanto
> **todos los registros persistidos en la base de datos**. El directorio `./storage`
> (bind mount del host) **no** se elimina automáticamente con este comando.
> No ejecutar si se quieren conservar los modelos.
>
> ```bash
> docker compose down -v
> ```

---

## Cómo probar el flujo completo

1. Ejecutar `docker compose up -d --build` y esperar a que los tres servicios estén `healthy`.
2. Abrir `http://127.0.0.1:5173` en el navegador.
3. Registrar un nuevo usuario con correo y contraseña (mínimo 8 caracteres).
4. Iniciar sesión con las mismas credenciales.
5. Seleccionar un archivo `.ifc` válido de tamaño menor al límite configurado (`IFC_MAX_FILE_SIZE_MB`, por defecto 50 MB) y hacer clic en "Cargar IFC".
6. Observar los estados transitorios `PENDING` y `PROCESSING` en la lista de modelos (la interfaz realiza polling automático). Un archivo pequeño puede avanzar entre dos actualizaciones y no mostrar ambos estados de forma visible.
7. Esperar a que el estado cambie a `COMPLETED`.
8. Hacer clic en "Ver detalle" del modelo procesado.
9. Revisar el dashboard analítico:
   - Cards de métricas: total de elementos, nodos espaciales, propiedades y elementos sin planta.
   - Gráfico de barras horizontales con la distribución por clase IFC.
   - Tabla de plantas con elevación y cantidad de elementos.
   - Tabla paginada de elementos con GlobalId, clase, nombre, tipo y planta.
   - Navegar con los botones "Anterior" / "Siguiente".
10. Desplazarse al visor 3D. Esperar a que el modelo cargue.
11. Probar orbit (clic + arrastre), pan (clic derecho + arrastre) y zoom (rueda del ratón).
12. Hacer clic sobre un elemento del modelo en el visor.
13. Revisar el panel BIM lateral: GlobalId, clase IFC, tipo, planta y listado de PropertySets/QTOs.
14. Para verificar el manejo de errores: subir un archivo con extensión `.ifc` pero contenido corrupto o inválido. El upload se acepta, el procesamiento comienza y el estado pasa a `FAILED` con un mensaje informativo. Subir un archivo con extensión distinta a `.ifc` produce un rechazo inmediato en el upload (400), antes de procesamiento.

---

## Endpoints

| Método | Endpoint                                      | Auth       | Descripción                                              |
|--------|-----------------------------------------------|------------|----------------------------------------------------------|
| `GET`  | `/api/v1/health`                              | Pública    | Estado del backend                                       |
| `POST` | `/api/v1/auth/register`                       | Pública    | Registrar nuevo usuario                                  |
| `POST` | `/api/v1/auth/login`                          | Pública    | Login y emisión de JWT (`form-urlencoded`)               |
| `GET`  | `/api/v1/auth/me`                             | Bearer JWT | Datos del usuario autenticado                            |
| `GET`  | `/api/v1/models`                              | Bearer JWT | Listar modelos del usuario                               |
| `POST` | `/api/v1/models`                              | Bearer JWT | Subir archivo IFC (multipart/form-data)                  |
| `GET`  | `/api/v1/models/{model_id}`                   | Bearer JWT | Detalle y estado de un modelo                            |
| `GET`  | `/api/v1/models/{model_id}/file`              | Bearer JWT | Descarga del archivo IFC (solo COMPLETED)                |
| `GET`  | `/api/v1/models/{model_id}/analytics`         | Bearer JWT | Métricas analíticas BIM (solo COMPLETED)                 |
| `GET`  | `/api/v1/models/{model_id}/elements`          | Bearer JWT | Lista paginada de elementos (`limit`, `offset`)          |
| `GET`  | `/api/v1/models/{model_id}/elements/{global_id}` | Bearer JWT | Detalle BIM de un elemento por GlobalId              |

El endpoint `/auth/login` utiliza `application/x-www-form-urlencoded`. El correo se
envía en el campo `username` por compatibilidad con `OAuth2PasswordRequestForm`.

La documentación interactiva completa está disponible en `http://127.0.0.1:8000/docs`.

---

## Seguridad

- Contraseñas hasheadas con Argon2 (pwdlib).
- JWT firmado con HS256; algoritmo definido explícitamente al decodificar.
- Secretos exclusivamente desde variables de entorno; sin secretos versionados.
- Token JWT almacenado en memoria React (sin localStorage ni sessionStorage).
- Scoping por propietario: cada usuario solo accede a sus propios modelos.
- Protección IDOR: `model_id` y `owner_id` evaluados juntos en SQL; modelo inexistente
  y modelo de otro usuario retornan 404 idéntico (sin revelar existencia del recurso).
- Validación defensiva de `storage_path`: se rechaza cualquier path absoluto, con
  componentes de directorio o que escape la raíz de almacenamiento (incluye semántica Windows).
- Descarga y serving de archivos: path resuelto y verificado en la raíz de storage antes
  de servir; `original_filename` usado en `Content-Disposition`, no el path de storage.
- Validación de upload: extensión, tamaño máximo configurable, nombre de archivo.
- Mensajes de error sin traceback, sin rutas físicas, sin detalles internos de excepciones.
- SchemaError de IfcOpenShell produce mensaje específico y controlado, sin exponer el
  nombre del schema ni el contenido de la excepción.
- Sin secretos ni credenciales versionados en el repositorio.

Esta implementación no ha sido auditada formalmente para entornos de producción.

---

## Manejo de errores IFC

| Situación                       | Estado   | Mensaje público                                      |
|---------------------------------|----------|------------------------------------------------------|
| Archivo corrupto o inválido     | `FAILED` | "No se pudo procesar el archivo IFC."                |
| Schema IFC no soportado         | `FAILED` | "El esquema IFC del archivo no está soportado."      |
| Archivo demasiado grande        | `413`    | "El archivo supera el tamaño máximo permitido."      |
| Extensión incorrecta            | `400`    | Mensaje descriptivo sin path físico                  |
| Error de extracción BIM         | `FAILED` | "No se pudo procesar el archivo IFC."                |

IfcOpenShell es la fuente de verdad para determinar qué schemas son soportados.
El backend no mantiene una lista manual de schemas válidos.

---

## Dashboard analítico

Los datos analíticos se consultan desde PostgreSQL directamente. El archivo IFC no se
vuelve a abrir para generar métricas.

Datos disponibles:

- **Totales**: elementos, nodos espaciales, propiedades, elementos sin planta resuelta.
- **Por clase IFC**: distribución `GROUP BY ifc_type` ordenada por count descendente.
- **Por planta**: conteo de elementos por `IfcBuildingStorey` resuelto con elevación.
- **Sin planta resuelta**: elementos cuyo containment no llegó a un storey.
- **Paginación de elementos**: `limit` (1–100) y `offset` en SQL; no carga la tabla completa en memoria.

El gráfico de Chart.js muestra como máximo las 15 clases con mayor cantidad de elementos
cuando existen más de 15. Chart.js está empaquetado por Vite y no depende de ningún CDN.

---

## Pruebas y validación

**Tests del backend (canónico con Docker)**

PowerShell:

```powershell
docker compose run --rm --no-deps `
    -e JWT_SECRET_KEY=test_jwt_secret_key_only_for_automated_tests_123456 `
    --volume ./backend:/app `
    backend `
    sh -lc "pip install --no-cache-dir pytest httpx > /tmp/test-deps.log && python -m pytest -p no:cacheprovider -q"
```

> Nota en Windows: si el path `./backend` no se monta correctamente desde Git Bash,
> usar la ruta absoluta: `--volume "C:/ruta/absoluta/al/repo/backend:/app"`.

Resultado validado: **680 tests aprobados**, 0 fallos.

**Frontend**

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
```

**Docker Compose**

```bash
docker compose config --quiet
```

**QA validado**

- 680 tests backend aprobados.
- Lint y build frontend sin errores.
- Docker Compose config válido.
- Arranque desde PostgreSQL limpio con migraciones automáticas.
- Flujo completo: registro → login → upload → COMPLETED → dashboard → visor → selección BIM.
- Analytics: métricas, gráfico Chart.js, tabla por planta, tabla paginada.
- Manejo de errores: archivo corrupto → FAILED genérico; schema IFC no soportado → FAILED específico.

Hay warnings conocidos de dependencias durante algunos tests, incluyendo cleanup de
IfcOpenShell sobre archivos corruptos y avisos de deprecación del stack de testing/API.
No producen fallos en la suite.

---

## Compatibilidad IFC

| Schema | Soporte |
|--------|---------|
| IFC2X3 | Probado en tests automatizados |
| IFC4   | Probado en tests automatizados |
| IFC4X3 | Soportado por IfcOpenShell 0.8.5; no validado end-to-end en este proyecto |
| IFC5   | No soportado (SchemaError) |

El soporte real de schemas depende de IfcOpenShell. El backend no aplica ninguna
restricción manual sobre el schema.

Tamaño máximo de archivo: configurable mediante `IFC_MAX_FILE_SIZE_MB` (default 50 MB).
Archivos más grandes o con geometría muy compleja pueden requerir más memoria y tiempo.

---

## Limitaciones y supuestos

- `BackgroundTasks` corre en el mismo proceso de Uvicorn. Procesamiento de múltiples
  modelos grandes simultáneamente puede saturar el proceso. No es una cola durable ni
  distribuida; es adecuado para el alcance local definido.
- Sin procesamiento distribuido, worker externo ni priorización de tareas.
- La sesión JWT del frontend permanece en memoria y se pierde al recargar la página.
  Esta es una decisión consciente de alcance y seguridad.
- Sin refresh token.
- Interfaz visual deliberadamente funcional y minimalista; no se persigue diseño avanzado.
- La compatibilidad IFC depende de la versión de IfcOpenShell instalada (0.8.5).
- El bundle del frontend supera los 500 KB minificados (Vite emite warning). Esto es
  consecuencia directa del tamaño de web-ifc y That Open, que se empaquetan localmente.
- Entorno diseñado para ejecución local; no orientado a producción ni a alta disponibilidad.
- La metadata del tipo de elemento se resuelve mediante `IfcRelDefinesByType` y se persiste
  en los campos `type_ifc_type` y `type_name` del elemento. La extracción de propiedades
  procesa `IfcRelDefinesByProperties`; los PSET/QTO heredados exclusivamente desde el type
  (sin asignación directa al elemento) no se expanden como propiedades persistidas del elemento.

---

## Decisiones técnicas principales

| Decisión | Razón |
|----------|-------|
| IfcOpenShell en backend | Fuente canónica de parseo y extracción BIM; permite persistencia estructurada en PostgreSQL. |
| That Open / web-ifc en frontend | Visualización e interacción 3D en el navegador sin backend adicional. |
| PostgreSQL | Persistencia relacional con queries analíticas directas; no requiere motor separado para analítica. |
| FastAPI BackgroundTasks | Suficiente para el alcance local sin introducir Redis, Celery ni infraestructura adicional. |
| Chart.js (empaquetado) | Gráficos open source, sin CDN, integrado en el bundle de Vite. |
| Alembic antes de Uvicorn | Instalación reproducible desde estado limpio; falla explícitamente si la base de datos o la migración no están disponibles. |
| Scoping por propietario | Cada usuario solo accede a sus propios modelos; protección IDOR consistente en todos los endpoints. |

---

## Historial de entrega

| PR  | Contenido principal |
|-----|---------------------|
| PR1 | Bootstrap Docker, PostgreSQL, autenticación JWT, frontend de login/registro |
| PR2 | Procesamiento IFC (IfcOpenShell), persistencia BIM, viewer 3D, selección de elementos, panel BIM |
| PR3 | Dashboard analítico (Chart.js), métricas, tabla paginada, hardening de errores IFC, migraciones automáticas, documentación |

---

## Uso responsable de IA

- IA utilizada como apoyo de planificación, revisión técnica y generación controlada de código.
- Cada cambio fue revisado, ejecutado y validado localmente por el candidato.
- El historial de commits refleja el desarrollo incremental y verificable.
- No se delegó responsabilidad técnica ni de validación a la IA.
- No se compartieron secretos ni credenciales reales.
