# IFC BIM Technical Test

Proyecto de aplicación web local orientado a cargar, procesar, visualizar y analizar modelos IFC.

El estado actual corresponde al PR1. En esta fase están implementados el entorno local, la persistencia base y la autenticación JWT. El procesamiento IFC, el visor 3D y la analítica pertenecen a fases posteriores.

---

## Estado del proyecto

- PR1 en desarrollo final.
- Bootstrap completado.
- Backend FastAPI funcional.
- Frontend React funcional.
- PostgreSQL persistente.
- Registro y login implementados.
- JWT implementado.
- Endpoint protegido implementado.
- Interfaz frontend de autenticación implementada.
- Procesamiento IFC, visor y analítica pendientes para PR2 y PR3.

---

## Funcionalidad disponible en PR1

- Registro de usuarios.
- Normalización del correo.
- Hash de contraseña con Argon2.
- Inicio de sesión.
- Emisión de access token JWT.
- Consulta autenticada del usuario actual.
- Rechazo de usuarios inexistentes o inactivos.
- Frontend de registro y login.
- Cierre de sesión local.
- Token almacenado únicamente en memoria React.
- PostgreSQL con volumen persistente.
- Migraciones mediante Alembic.
- Health checks.

---

## Arquitectura actual

```text
Usuario / navegador
        |
        v
      Nginx
      |   |
    / |   | /api/*
      |   |
      v   v
React + TypeScript
          FastAPI
             |
             v
        SQLAlchemy
             |
             v
        PostgreSQL
```

- React gestiona la interfaz ejecutada en el navegador.
- Nginx sirve la SPA y actúa como proxy inverso para las solicitudes `/api/*`.
- FastAPI contiene la autenticación y las reglas de negocio.
- SQLAlchemy administra la persistencia.
- PostgreSQL almacena los usuarios.
- Alembic administra las migraciones.

---

## Tecnologías

**Frontend**

- React
- TypeScript
- Vite
- Nginx

**Backend**

- Python
- FastAPI
- SQLAlchemy
- Alembic
- PyJWT
- pwdlib / Argon2
- Pydantic

**Persistencia**

- PostgreSQL

**Infraestructura**

- Docker
- Docker Compose

**Pruebas**

- pytest
- FastAPI TestClient

---

## Estructura del repositorio

```
frontend/          Aplicación React y configuración Nginx
backend/           API FastAPI, modelos, migraciones y pruebas
docs/              Directorio reservado para documentación técnica y diagramas
storage/           Directorio reservado para archivos IFC locales a partir del PR2
docker-compose.yml Orquestación de servicios
.env.example       Plantilla de variables de entorno
README.md          Este archivo
```

---

## Requisitos previos

- Git
- Docker Desktop
- Docker Compose

Node.js y Python solo son necesarios para ejecutar validaciones locales fuera de Docker.

---

## Variables de entorno

Copiar la plantilla:

**PowerShell**

```powershell
Copy-Item .env.example .env
```

**Linux/macOS**

```bash
cp .env.example .env
```

Variables disponibles:

| Variable                    | Descripción                                           |
|-----------------------------|-------------------------------------------------------|
| `POSTGRES_DB`               | Nombre de la base de datos                            |
| `POSTGRES_USER`             | Usuario de PostgreSQL                                 |
| `POSTGRES_PASSWORD`         | Contraseña de PostgreSQL                              |
| `POSTGRES_PORT`             | Puerto expuesto en el host                            |
| `POSTGRES_HOST`             | Nombre del servicio de base de datos                  |
| `POSTGRES_INTERNAL_PORT`    | Puerto interno del contenedor PostgreSQL              |
| `BACKEND_PORT`              | Puerto expuesto del backend en el host                |
| `FRONTEND_PORT`             | Puerto expuesto del frontend en el host               |
| `JWT_SECRET_KEY`            | Clave secreta para firmar y verificar tokens JWT      |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Tiempo de expiración del access token en minutos    |

Consideraciones:

- No utilizar los valores de ejemplo en producción.
- `JWT_SECRET_KEY` debe ser largo, aleatorio y secreto.
- El archivo `.env` está excluido de Git.
- Los secretos no deben colocarse en el frontend.

---

## Instalación y ejecución

Desde la raíz del repositorio:

```bash
# Iniciar la base de datos
docker compose up -d db

# Ejecutar migraciones
docker compose run --rm backend alembic upgrade head

# Iniciar backend y frontend
docker compose up -d backend frontend

# Verificar estado
docker compose ps
```

Los tres servicios deben aparecer en estado `healthy`.

URLs predeterminadas:

| Servicio | URL                               |
|----------|-----------------------------------|
| Frontend | http://127.0.0.1:5173             |
| Backend  | http://127.0.0.1:8000             |
| Swagger  | http://127.0.0.1:8000/docs        |
| Health   | http://127.0.0.1:8000/api/v1/health |

Detener servicios:

```bash
docker compose down
```

El siguiente comando elimina también el volumen de PostgreSQL y todos los datos almacenados:

```bash
docker compose down -v
```

---

## Flujo de autenticación

```
Registro
  → contraseña transformada con Argon2
  → usuario persistido en PostgreSQL
  → login
  → access token JWT emitido
  → Authorization: Bearer <token>
  → GET /api/v1/auth/me
  → consulta del usuario actual en PostgreSQL
```

Después de validar la firma y la expiración del JWT, el backend consulta PostgreSQL para confirmar que el usuario todavía exista y se encuentre activo.

---

## Endpoints disponibles

| Método | Endpoint                  | Protección | Descripción                           |
|--------|---------------------------|------------|---------------------------------------|
| POST   | /api/v1/auth/register     | Pública    | Registrar usuario                     |
| POST   | /api/v1/auth/login        | Pública    | Iniciar sesión y obtener JWT          |
| GET    | /api/v1/auth/me           | Bearer JWT | Consultar usuario autenticado         |
| GET    | /api/v1/health            | Pública    | Consultar estado del backend          |

El endpoint de login utiliza `application/x-www-form-urlencoded`. El correo electrónico se envía en el campo `username` por compatibilidad con `OAuth2PasswordRequestForm`.

---

## Decisiones de seguridad

- Las contraseñas nunca se almacenan en texto plano.
- Se aplica hash Argon2.
- El JWT se firma con HS256.
- Los algoritmos permitidos se definen explícitamente al decodificar.
- La expiración del token es configurable mediante variable de entorno.
- El secreto JWT se obtiene exclusivamente desde variables de entorno.
- Los errores de credenciales devuelven un mensaje genérico para no revelar información.
- La respuesta de `/auth/me` no expone `hashed_password`.
- El JWT del frontend permanece únicamente en memoria React.
- No se utiliza `localStorage` ni `sessionStorage`.
- Un usuario inactivo pierde acceso incluso con un token previamente emitido.

Esta implementación no ha sido auditada para entornos de producción.

---

## Pruebas y validaciones

**Backend**

```bash
python -m pytest backend/tests -q
```

**Compilación backend**

```bash
python -m compileall -q backend/app
```

**Frontend**

```bash
npm --prefix frontend run lint

npm --prefix frontend run build
```

**Docker Compose**

```bash
docker compose config --quiet
```

Estado actual:

- 103 pruebas backend aprobadas.
- Lint frontend aprobado.
- Build frontend aprobado.
- PostgreSQL, backend y frontend ejecutados correctamente en Docker.
- Registro, login, token válido, token inválido, token expirado y usuario inactivo validados.
- QA manual de interfaz aprobado.
- Ningún error 500 ni traceback observado durante el flujo validado.

---

## Limitaciones actuales

- El procesamiento IFC aún no está implementado.
- El visor 3D aún no está implementado.
- Las métricas y consultas analíticas aún no están implementadas.
- No existen refresh tokens.
- La sesión del frontend no persiste al recargar la página.
- Las migraciones se ejecutan manualmente antes de iniciar el backend.
- La interfaz visual es deliberadamente mínima.
- No se contempla concurrencia avanzada en esta fase.

---

## Próximas fases

**PR2**

- Carga del IFC.
- Validación del archivo.
- Estados de procesamiento.
- Parseo con IfcOpenShell.
- Extracción de jerarquía, elementos, tipos y PropertySets.
- Persistencia de información IFC.
- Integración del visor 3D.

**PR3**

- Consultas analíticas.
- Métricas.
- Visualización analítica.
- Pruebas finales.
- Documentación definitiva.
- Preparación de sustentación.

---

## Uso responsable de IA

- Se utilizó IA como apoyo para planificación, revisión técnica y generación controlada de código.
- Cada cambio fue revisado, ejecutado y validado localmente.
- Los cambios se dividieron en commits incrementales.
- No se compartieron secretos ni credenciales reales.
- La responsabilidad final de las decisiones técnicas corresponde al candidato.

---

## Problemas conocidos

- Las pruebas pueden mostrar una advertencia de deprecación de Starlette/TestClient relacionada con `httpx`. La advertencia no afecta el resultado de las pruebas ni el funcionamiento en runtime.
- El frontend no conserva la sesión al recargar la página. Esta es una decisión consciente de seguridad y alcance del PR1.
