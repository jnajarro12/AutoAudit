# AutoAudit — Sistema de auditoría automatizada

Proyecto base funcional para PostgreSQL 18 y Ubuntu 26.04 LTS. Incluye:
- Modelo de configuración y bitácora.
- Interfaz web Flask para listar tablas/columnas y configurar auditoría.
- Generación dinámica de triggers `AFTER INSERT OR UPDATE OR DELETE`.
- Registro de usuario de aplicación, IP, fecha, operación, valores anterior/nuevo.
- Consulta y exportación CSV del historial.
- Scripts SQL, pruebas y guía de instalación.

> **Importante:** este es un punto de partida técnico que debe probarse y adaptarse con el grupo antes de entregar. La captura del usuario de base de datos de PostgreSQL no siempre equivale al usuario final de la aplicación; el proyecto registra el usuario de aplicación enviado por la interfaz. La IP se obtiene de la petición web. En producción se debe revisar autenticación, autorización, proxy/IP y permisos.

## Requisitos
- Ubuntu 26.04 LTS (o versión indicada por el docente).
- PostgreSQL 18.
- Python 3.12+ recomendado.
- Git opcional.

## Instalación rápida

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Dentro de `psql`, crear usuario y base de datos (cambiar contraseñas):
```sql
CREATE USER autoaudit_app WITH PASSWORD 'CAMBIAR_ESTA_CLAVE';
CREATE DATABASE autoaudit OWNER autoaudit_app;
\q
```

Desde la carpeta del proyecto:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
psql "postgresql://autoaudit_app:CAMBIAR_ESTA_CLAVE@localhost:5432/autoaudit" -f sql/01_schema.sql
psql "postgresql://autoaudit_app:CAMBIAR_ESTA_CLAVE@localhost:5432/autoaudit" -f sql/02_demo.sql
python app.py
```
Abrir `http://127.0.0.1:5000`.

## Configuración de `.env`
Editar `DATABASE_URL` con credenciales reales. Cambiar `SECRET_KEY`. No subir `.env` a Git.

## Uso
1. En el menú **Configuración**, elegir una tabla de usuario (por ejemplo `public.empleados_demo`).
2. Marcar columnas que se auditarán y operaciones INSERT, UPDATE, DELETE.
3. Guardar y activar. El sistema crea o reemplaza el trigger para esa tabla.
4. Modificar la tabla demo para probar; consultar **Bitácora**.
5. Exportar CSV desde la página de bitácora.

## Seguridad y limitaciones
- Solo el usuario de base de datos con permisos adecuados puede crear triggers. Para un entorno real, separar rol administrador y rol de ejecución.
- El generador valida identificadores contra el catálogo y los delimita con `psycopg.sql.Identifier`; no concatenar nombres recibidos directamente.
- La bitácora se protege de cambios directos mediante permisos de aplicación recomendados, pero un superusuario puede alterarla. La seguridad absoluta no se logra solo con triggers.
- Se almacena el JSON de la fila antes/después y se generan detalles por columna configurada. El esquema preserva la bitácora aunque la fila origen se elimine.
- El PDF menciona PL/SQL; PostgreSQL utiliza PL/pgSQL. Confirmar con el docente que acepta PL/pgSQL para PostgreSQL.
- Las operaciones UPDATE se registran solo si cambió al menos una columna seleccionada.
- Para auditar tablas nuevas, configurar la tabla desde la interfaz después de crearla.
- Para la IP detrás de proxy, configurar proxies confiables antes de usar `X-Forwarded-For`.

## Estructura
- `app.py`: interfaz y endpoints.
- `audit_service.py`: lectura de catálogo y generación de triggers.
- `sql/01_schema.sql`: tablas del sistema, función genérica y permisos recomendados.
- `sql/02_demo.sql`: datos de demostración.
- `tests/test_plan.md`: plan de pruebas.
