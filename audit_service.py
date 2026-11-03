from psycopg import sql
from psycopg.rows import dict_row

SYSTEM_SCHEMA = "autoaudit"

def list_user_tables(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT n.nspname AS schema_name, c.relname AS table_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r','p')
              AND n.nspname NOT IN ('pg_catalog','information_schema','autoaudit')
              AND n.nspname NOT LIKE 'pg_toast%'
            ORDER BY n.nspname, c.relname
        """)
        return cur.fetchall()

def list_columns(conn, schema_name, table_name):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema_name, table_name))
        return cur.fetchall()

def get_config(conn, schema_name, table_name):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT * FROM autoaudit.audit_table_config
            WHERE schema_name=%s AND table_name=%s
        """, (schema_name, table_name))
        config = cur.fetchone()
        if not config:
            return None, []
        cur.execute("""
            SELECT column_name, enabled FROM autoaudit.audit_column_config
            WHERE config_id=%s ORDER BY column_name
        """, (config["config_id"],))
        return config, cur.fetchall()

def save_config(conn, schema_name, table_name, columns, operations, enabled):
    # Confirmar tabla y columnas directamente en el catálogo antes de persistir.
    available = {c["column_name"] for c in list_columns(conn, schema_name, table_name)}
    if not available:
        raise ValueError("La tabla no existe o no tiene columnas accesibles.")
    selected = set(columns) & available
    if not selected:
        raise ValueError("Selecciona al menos una columna válida.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            INSERT INTO autoaudit.audit_table_config
              (schema_name, table_name, enabled, audit_insert, audit_update, audit_delete, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (schema_name, table_name) DO UPDATE SET
              enabled=EXCLUDED.enabled,
              audit_insert=EXCLUDED.audit_insert,
              audit_update=EXCLUDED.audit_update,
              audit_delete=EXCLUDED.audit_delete,
              updated_at=CURRENT_TIMESTAMP
            RETURNING config_id
        """, (schema_name, table_name, enabled,
              "INSERT" in operations, "UPDATE" in operations, "DELETE" in operations))
        config_id = cur.fetchone()["config_id"]
        cur.execute("DELETE FROM autoaudit.audit_column_config WHERE config_id=%s", (config_id,))
        for col in sorted(selected):
            cur.execute("""
                INSERT INTO autoaudit.audit_column_config(config_id, column_name, enabled)
                VALUES (%s,%s,TRUE)
            """, (config_id, col))
    return selected

def deploy_trigger(conn, schema_name, table_name):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT config_id, enabled, audit_insert, audit_update, audit_delete
            FROM autoaudit.audit_table_config
            WHERE schema_name=%s AND table_name=%s
        """, (schema_name, table_name))
        cfg = cur.fetchone()
        if not cfg:
            raise ValueError("Primero guarda una configuración.")
        trigger_name = f"aa_{table_name}_audit"
        if not cfg["enabled"] or not any([cfg["audit_insert"], cfg["audit_update"], cfg["audit_delete"]]):
            cur.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON {}.{}").format(
                sql.Identifier(trigger_name), sql.Identifier(schema_name), sql.Identifier(table_name)))
            return "Auditoría desactivada; trigger eliminado si existía."
        events = []
        if cfg["audit_insert"]: events.append(sql.SQL("INSERT"))
        if cfg["audit_update"]: events.append(sql.SQL("UPDATE"))
        if cfg["audit_delete"]: events.append(sql.SQL("DELETE"))
        event_sql = sql.SQL(" OR ").join(events)
        cur.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON {}.{}").format(
            sql.Identifier(trigger_name), sql.Identifier(schema_name), sql.Identifier(table_name)))
        cur.execute(sql.SQL("CREATE TRIGGER {} AFTER {} ON {}.{} FOR EACH ROW EXECUTE FUNCTION autoaudit.capture_row_change()").format(
            sql.Identifier(trigger_name), event_sql, sql.Identifier(schema_name), sql.Identifier(table_name)))
        return f"Trigger {trigger_name} creado correctamente."

def query_logs(conn, username="", table_name="", column_name="", limit=500):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT l.audit_id, l.occurred_at, l.schema_name, l.table_name, l.operation,
                   l.app_username, l.row_pk, d.column_name, d.old_value, d.new_value,
                   w.ip_address
            FROM autoaudit.audit_log l
            LEFT JOIN autoaudit.audit_log_detail d ON d.audit_id=l.audit_id
            LEFT JOIN autoaudit.audit_workstations w ON w.workstation_id=l.workstation_id
            WHERE (%s='' OR l.app_username ILIKE %s)
              AND (%s='' OR l.table_name ILIKE %s)
              AND (%s='' OR COALESCE(d.column_name,'') ILIKE %s)
            ORDER BY l.occurred_at DESC, l.audit_id DESC
            LIMIT %s
        """, (username, f"%{username}%", table_name, f"%{table_name}%",
              column_name, f"%{column_name}%", limit))
        return cur.fetchall()
