import csv
import io
import os
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, Response, url_for, session
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from audit_service import (
    list_user_tables,
    list_columns,
    get_config,
    save_config,
    deploy_trigger,
    query_logs
)

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "development-only-change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Configura DATABASE_URL en el archivo .env")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)
# ==========================================
# AUTENTICACIÓN Y CONTROL DE ACCESO
# ==========================================

@app.before_request
def verificar_sesion():

    if request.endpoint in ("login", "static"):
        return

    if not session.get("user_id"):
        return redirect(url_for("login"))

    # Permisos del auditor
    if session.get("role") == "auditor":

        rutas_permitidas = [
            "index",
            "logs",
            "export_csv",
            "logout"
        ]

        if request.endpoint not in rutas_permitidas:
            flash("No tienes permisos para acceder a este módulo.", "danger")
            return redirect(url_for("index"))


# ==========================================
# INICIAR SESIÓN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT user_id, username, password_hash, role
                    FROM autoaudit.app_users
                    WHERE username = %s
                """, (username,))

                user = cur.fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):

            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]

            flash("Bienvenido a AutoAudit.", "success")

            return redirect(url_for("index"))

        flash("Usuario o contraseña incorrectos.", "danger")

    return render_template("login.html")


# ==========================================
# CERRAR SESIÓN
# ==========================================

@app.route("/logout")
def logout():

    session.clear()

    flash("Sesión cerrada correctamente.", "success")

    return redirect(url_for("login"))
def db_page(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            app.logger.exception("Error procesando solicitud")
            flash(f"Error: {exc}", "danger")
            return redirect(url_for("index"))
    return wrapper

@app.context_processor
def inject_now():
    from datetime import datetime
    return {"year": datetime.now().year}

@app.get("/")
@db_page
def index():
    with get_conn() as conn:
        tables = list_user_tables(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM autoaudit.audit_log")
            total = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS total FROM autoaudit.audit_table_config WHERE enabled=TRUE")
            active = cur.fetchone()["total"]
            cur.execute("SELECT audit_id, occurred_at, schema_name, table_name, operation, app_username FROM autoaudit.audit_log ORDER BY occurred_at DESC LIMIT 8")
            recent = cur.fetchall()
    return render_template("index.html", tables=tables, total=total, active=active, recent=recent)

@app.route("/configurar", methods=["GET", "POST"])
@db_page
def configure():
    with get_conn() as conn:
        tables = list_user_tables(conn)
        schema_name = request.values.get("schema_name", "public")
        table_name = request.values.get("table_name", "")
        columns = list_columns(conn, schema_name, table_name) if table_name else []
        cfg, saved_columns = get_config(conn, schema_name, table_name) if table_name else (None, [])
        saved_set = {c["column_name"] for c in saved_columns if c["enabled"]}
        if request.method == "POST":
            selected = request.form.getlist("columns")
            operations = request.form.getlist("operations")
            enabled = request.form.get("enabled") == "on"
            save_config(conn, schema_name, table_name, selected, operations, enabled)
            msg = deploy_trigger(conn, schema_name, table_name)
            conn.commit()
            flash(msg, "success")
            return redirect(url_for("configure", schema_name=schema_name, table_name=table_name))
    return render_template("configure.html", tables=tables, columns=columns,
                           schema_name=schema_name, table_name=table_name,
                           cfg=cfg, saved_set=saved_set)

@app.get("/triggers")
@db_page
def triggers():
    configurations = []

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            cur.execute("""
                SELECT config_id, schema_name, table_name,
                       enabled, audit_insert, audit_update, audit_delete
                FROM autoaudit.audit_table_config
                ORDER BY schema_name, table_name
            """)

            configurations = cur.fetchall()

            for item in configurations:

                cur.execute("""
                    SELECT column_name
                    FROM autoaudit.audit_column_config
                    WHERE config_id = %s AND enabled = TRUE
                    ORDER BY column_name
                """, (item["config_id"],))

                item["columns"] = [
                    row["column_name"] for row in cur.fetchall()
                ]

                item["trigger_name"] = (
                    f'aa_{item["table_name"]}_audit'
                )

                events = []

                if item["audit_insert"]:
                    events.append("INSERT")

                if item["audit_update"]:
                    events.append("UPDATE")

                if item["audit_delete"]:
                    events.append("DELETE")

                def quote_identifier(value):
                    return '"' + value.replace('"', '""') + '"'

                schema = quote_identifier(item["schema_name"])
                table = quote_identifier(item["table_name"])
                trigger = quote_identifier(item["trigger_name"])

                if item["enabled"] and events:

                    event_sql = " OR ".join(events)

                    item["sql_preview"] = f"""
DROP TRIGGER IF EXISTS {trigger} ON {schema}.{table};

CREATE TRIGGER {trigger}
AFTER {event_sql} ON {schema}.{table}
FOR EACH ROW
EXECUTE FUNCTION autoaudit.capture_row_change();
"""

                else:
                    item["sql_preview"] = (
                        "-- Auditoría deshabilitada o sin operaciones."
                    )

    return render_template(
        "triggers.html",
        configurations=configurations
    )


@app.post("/triggers/generar")
@db_page
def generate_trigger():

    schema_name = request.form.get("schema_name")
    table_name = request.form.get("table_name")

    if not schema_name or not table_name:
        flash("Selecciona una tabla válida.", "danger")
        return redirect(url_for("triggers"))

    with get_conn() as conn:
        msg = deploy_trigger(conn, schema_name, table_name)
        conn.commit()

    flash(msg, "success")

    return redirect(url_for("triggers"))
@app.get("/bitacora")
@db_page
def logs():
    username = request.args.get("usuario", "").strip()
    table_name = request.args.get("tabla", "").strip()
    column_name = request.args.get("columna", "").strip()
    with get_conn() as conn:
        rows = query_logs(conn, username, table_name, column_name)
    return render_template("logs.html", rows=rows, usuario=username, tabla=table_name, columna=column_name)

@app.get("/exportar")
@db_page
def export_csv():
    with get_conn() as conn:
        rows = query_logs(conn, request.args.get("usuario", "").strip(),
                          request.args.get("tabla", "").strip(),
                          request.args.get("columna", "").strip(), 5000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Fecha", "Esquema", "Tabla", "Operación", "Usuario", "Clave fila", "Columna", "Valor anterior", "Valor nuevo", "IP"])
    for r in rows:
        writer.writerow([r["audit_id"], r["occurred_at"], r["schema_name"], r["table_name"],
                         r["operation"], r["app_username"], r["row_pk"], r["column_name"],
                         r["old_value"], r["new_value"], r["ip_address"]])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=autoaudit_bitacora.csv"})

@app.after_request
def attach_audit_context(response):
    # La ruta no puede establecer SET LOCAL después de que la transacción ya cerró.
    # El contexto se establece en cada operación de escritura de la aplicación de negocio.
    return response

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
