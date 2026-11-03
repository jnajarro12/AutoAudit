# Plan de pruebas de validación

Preparación:
1. Instalar estructura `sql/01_schema.sql` y tabla demo `sql/02_demo.sql`.
2. Desde la interfaz, configurar `public.empleados_demo`.
3. Seleccionar columnas `nombre`, `puesto`, `salario`, `activo`.
4. Habilitar INSERT, UPDATE y DELETE.

## Caso 1 — INSERT
```sql
INSERT INTO public.empleados_demo(nombre, puesto, salario)
VALUES ('Ana López', 'Analista', 4200);
```
Esperado: fila en `autoaudit.audit_log` con operación INSERT y detalles con valor nuevo.

## Caso 2 — UPDATE
```sql
UPDATE public.empleados_demo SET salario=4500 WHERE nombre='Ana López';
```
Esperado: operación UPDATE, valor anterior 4200 y nuevo 4500 en `audit_log_detail`.

## Caso 3 — DELETE
```sql
DELETE FROM public.empleados_demo WHERE nombre='Ana López';
```
Esperado: operación DELETE y valores antiguos conservados en la bitácora.

## Caso 4 — Filtro por columna
Abrir Bitácora, filtrar columna `salario`.
Esperado: solo detalles de esa columna.

## Caso 5 — Desactivar
Desmarcar “Auditoría habilitada” y guardar.
Esperado: trigger eliminado; cambios posteriores no crean nuevos eventos.

## Caso 6 — Exportación
Pulsar CSV.
Esperado: descarga `autoaudit_bitacora.csv` con los resultados filtrados.

## Verificación SQL
```sql
SELECT audit_id, occurred_at, schema_name, table_name, operation, app_username
FROM autoaudit.audit_log ORDER BY occurred_at DESC;

SELECT d.column_name, d.old_value, d.new_value
FROM autoaudit.audit_log_detail d
ORDER BY d.detail_id DESC;
```
