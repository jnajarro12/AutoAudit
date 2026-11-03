# Modelo de datos propuesto

## Entidades
- `autoaudit.audit_table_config`: configuración por tabla y tipos de operación.
- `autoaudit.audit_column_config`: columnas que deben auditarse.
- `autoaudit.audit_event_type`: catálogo de operaciones soportadas.
- `autoaudit.audit_users`: catálogo opcional de usuarios de aplicación.
- `autoaudit.audit_workstations`: IP y agente de usuario.
- `autoaudit.audit_log`: cabecera del evento con valores completos anterior/nuevo.
- `autoaudit.audit_log_detail`: valores por columna auditada.

## Relaciones
- `audit_table_config` 1:N `audit_column_config`.
- `audit_log` 1:N `audit_log_detail`.
- `audit_log` N:1 `audit_workstations`.
- Cada fila de `audit_log` identifica esquema, tabla, operación y hora. No tiene FK a la tabla auditada para que la evidencia sobreviva a un DELETE.

## Decisiones
- Los valores anterior/nuevo se almacenan como JSONB para soportar diferentes tipos de datos.
- Se registra un detalle por cada columna configurada y relevante.
- La clave de fila se guarda como JSONB. La implementación inicial usa `ctid` como identificador físico ilustrativo; para una identificación estable, se recomienda adaptar el generador para descubrir y registrar las columnas de la clave primaria de cada tabla.
- `audit_users` es un catálogo previsto para una futura autenticación; la versión base recibe el nombre de usuario desde el contexto de PostgreSQL o de la aplicación.
