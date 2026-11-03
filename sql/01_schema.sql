-- AutoAudit: estructura principal. Ejecutar en la base de datos autoaudit.
CREATE SCHEMA IF NOT EXISTS autoaudit;

CREATE TABLE IF NOT EXISTS autoaudit.audit_table_config (
    config_id BIGSERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    audit_insert BOOLEAN NOT NULL DEFAULT TRUE,
    audit_update BOOLEAN NOT NULL DEFAULT TRUE,
    audit_delete BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (schema_name, table_name)
);

CREATE TABLE IF NOT EXISTS autoaudit.audit_column_config (
    column_config_id BIGSERIAL PRIMARY KEY,
    config_id BIGINT NOT NULL REFERENCES autoaudit.audit_table_config(config_id) ON DELETE CASCADE,
    column_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (config_id, column_name)
);

CREATE TABLE IF NOT EXISTS autoaudit.audit_event_type (
    event_code TEXT PRIMARY KEY CHECK (event_code IN ('INSERT', 'UPDATE', 'DELETE')),
    description TEXT NOT NULL
);
INSERT INTO autoaudit.audit_event_type(event_code, description) VALUES
 ('INSERT', 'Inserción de registro'),
 ('UPDATE', 'Actualización de registro'),
 ('DELETE', 'Eliminación de registro')
ON CONFLICT (event_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS autoaudit.audit_users (
    audit_user_id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS autoaudit.audit_workstations (
    workstation_id BIGSERIAL PRIMARY KEY,
    ip_address INET,
    user_agent TEXT,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ip_address, user_agent)
);

CREATE TABLE IF NOT EXISTS autoaudit.audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    row_pk JSONB,
    app_username TEXT NOT NULL DEFAULT 'desconocido',
    workstation_id BIGINT REFERENCES autoaudit.audit_workstations(workstation_id) ON DELETE SET NULL,
    old_row JSONB,
    new_row JSONB,
    transaction_id BIGINT NOT NULL DEFAULT txid_current()
);

CREATE TABLE IF NOT EXISTS autoaudit.audit_log_detail (
    detail_id BIGSERIAL PRIMARY KEY,
    audit_id BIGINT NOT NULL REFERENCES autoaudit.audit_log(audit_id) ON DELETE CASCADE,
    column_name TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_time ON autoaudit.audit_log(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON autoaudit.audit_log(app_username);
CREATE INDEX IF NOT EXISTS idx_audit_log_table ON autoaudit.audit_log(schema_name, table_name);
CREATE INDEX IF NOT EXISTS idx_audit_detail_column ON autoaudit.audit_log_detail(column_name);

-- La interfaz establece estas variables con SET LOCAL por transacción.
CREATE OR REPLACE FUNCTION autoaudit.capture_row_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, autoaudit
AS $$
DECLARE
    v_old JSONB;
    v_new JSONB;
    v_pk JSONB;
    v_user TEXT;
    v_ip INET;
    v_agent TEXT;
    v_workstation_id BIGINT;
    v_audit_id BIGINT;
    v_col RECORD;
    v_old_val JSONB;
    v_new_val JSONB;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_old := NULL;
        v_new := to_jsonb(NEW);
        v_pk := jsonb_build_object('ctid', NEW.ctid::TEXT);
    ELSIF TG_OP = 'UPDATE' THEN
        v_old := to_jsonb(OLD);
        v_new := to_jsonb(NEW);
        v_pk := jsonb_build_object('ctid_old', OLD.ctid::TEXT, 'ctid_new', NEW.ctid::TEXT);
    ELSE
        v_old := to_jsonb(OLD);
        v_new := NULL;
        v_pk := jsonb_build_object('ctid', OLD.ctid::TEXT);
    END IF;

    v_user := COALESCE(NULLIF(current_setting('autoaudit.username', true), ''), session_user);
    BEGIN
        v_ip := NULLIF(current_setting('autoaudit.client_ip', true), '')::INET;
    EXCEPTION WHEN OTHERS THEN
        v_ip := NULL;
    END;
    v_agent := NULLIF(current_setting('autoaudit.user_agent', true), '');

    INSERT INTO autoaudit.audit_workstations(ip_address, user_agent)
    VALUES (v_ip, v_agent)
    ON CONFLICT (ip_address, user_agent) DO UPDATE SET ip_address = EXCLUDED.ip_address
    RETURNING workstation_id INTO v_workstation_id;

    INSERT INTO autoaudit.audit_log(
        schema_name, table_name, operation, row_pk, app_username,
        workstation_id, old_row, new_row
    ) VALUES (
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP, v_pk, v_user,
        v_workstation_id, v_old, v_new
    ) RETURNING audit_id INTO v_audit_id;

    FOR v_col IN
        SELECT cc.column_name
        FROM autoaudit.audit_table_config tc
        JOIN autoaudit.audit_column_config cc ON cc.config_id = tc.config_id
        WHERE tc.schema_name = TG_TABLE_SCHEMA
          AND tc.table_name = TG_TABLE_NAME
          AND tc.enabled = TRUE AND cc.enabled = TRUE
    LOOP
        v_old_val := CASE WHEN v_old IS NULL THEN NULL ELSE v_old -> v_col.column_name END;
        v_new_val := CASE WHEN v_new IS NULL THEN NULL ELSE v_new -> v_col.column_name END;
        IF TG_OP <> 'UPDATE' OR v_old_val IS DISTINCT FROM v_new_val THEN
            INSERT INTO autoaudit.audit_log_detail(audit_id, column_name, old_value, new_value)
            VALUES (v_audit_id, v_col.column_name, v_old_val, v_new_val);
        END IF;
    END LOOP;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

-- El trigger dinámico invoca la función genérica.
-- La función es propiedad del rol que ejecutó este script. Revisar permisos antes de producción.
