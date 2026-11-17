"""Plataforma de Distribución – BU CAM | La Constancia."""
import os
from datetime import timedelta

import click
from flask import Flask, g, render_template, request

from . import db as dbmod


def create_app(config=None):
    app = Flask(__name__)
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "solo-para-desarrollo-cambiar"),
        DATABASE_URL=os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(base, "instance", "plataforma.db")),
        MAX_CONTENT_LENGTH=15 * 1024 * 1024,           # cargas de Excel y fotos
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SEGURA", "0") == "1",
    )
    if config:
        app.config.update(config)

    if app.config["SECRET_KEY"] == "solo-para-desarrollo-cambiar" and os.environ.get("RAILWAY_ENVIRONMENT"):
        raise RuntimeError("Define la variable SECRET_KEY en Railway antes de publicar.")

    from . import alertas, auth, averias, cargas, inicio, maestros, planificacion, usuarios
    for m in (auth, inicio, averias, alertas, planificacion, maestros, cargas, usuarios):
        app.register_blueprint(m.bp)

    app.teardown_appcontext(dbmod.cerrar_db)

    # Crea o actualiza las tablas al arrancar (no borra datos); así una versión nueva nunca encuentra tablas faltantes.
    if not app.config.get("TESTING"):
        try:
            with app.app_context():
                dbmod.crear_esquema()
                from .datos_base import cargar_motivos, cargar_motivos_devolucion
                cargar_motivos()
                cargar_motivos_devolucion()
        except Exception as e:  # la base podría no estar disponible todavía (p. ej., Railway arrancando)
            app.logger.warning("No se pudo revisar el esquema al arrancar: %s", e)

    @app.before_request
    def antes():
        if request.endpoint == "static":
            return
        auth.cargar_usuario()
        auth.verificar_csrf()

    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")  # el mapa necesita enviar el origen
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.context_processor
    def globales():
        return dict(csrf_token=auth.csrf_token, puede=auth.puede, ROLES=auth.ROLES,
                    usuario=g.get("usuario"))

    @app.template_filter("num")
    def num(v, dec=1):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "–"
        txt = f"{v:,.{dec}f}".rstrip("0").rstrip(".") if dec else f"{v:,.0f}"
        return txt

    for codigo, titulo in ((400, "Solicitud no válida"), (403, "Sin permiso"), (404, "No encontrado"),
                           (413, "Archivo demasiado grande")):
        app.register_error_handler(codigo, lambda e, c=codigo, t=titulo: (
            render_template("error.html", codigo=c, titulo=t, detalle=getattr(e, "description", "")), c))

    # ---------- Comandos de consola ----------

    @app.cli.command("init-db")
    def init_db():
        """Crea las tablas (no borra datos existentes)."""
        dbmod.crear_esquema()
        from .datos_base import cargar_motivos, cargar_motivos_devolucion
        cargar_motivos()
        cargar_motivos_devolucion()
        click.echo("Base de datos lista.")

    @app.cli.command("crear-admin")
    @click.option("--usuario", prompt=True)
    @click.option("--nombre", prompt=True)
    @click.password_option("--clave")
    def crear_admin(usuario, nombre, clave):
        """Crea un usuario administrador."""
        dbmod.crear_esquema()
        cn = dbmod.db()
        cn.ejecutar("INSERT INTO usuarios (usuario, nombre, rol, password_hash, debe_cambiar, creado) "
                    "VALUES (?, ?, 'admin', ?, 0, ?)",
                    (usuario.strip().lower(), nombre, auth.hash_clave(clave), dbmod.ahora()))
        cn.commit()
        click.echo(f"Administrador '{usuario}' creado.")

    @app.cli.command("demo")
    def demo():
        """Carga datos FICTICIOS para pruebas y demostraciones."""
        from .datos_base import cargar_demo
        dbmod.crear_esquema()
        click.echo(cargar_demo())

    @app.cli.command("arranque")
    def arranque():
        """Usado al publicar: crea tablas y, si no hay usuarios, el admin inicial desde variables de entorno."""
        dbmod.crear_esquema()
        from .datos_base import cargar_motivos, cargar_motivos_devolucion
        cargar_motivos()
        cargar_motivos_devolucion()
        cn = dbmod.db()
        if not cn.valor("SELECT COUNT(*) AS n FROM usuarios"):
            u, c = os.environ.get("ADMIN_USUARIO"), os.environ.get("ADMIN_CLAVE")
            if u and c:
                cn.ejecutar("INSERT INTO usuarios (usuario, nombre, rol, password_hash, debe_cambiar, creado) "
                            "VALUES (?, 'Administrador', 'admin', ?, 1, ?)",
                            (u.strip().lower(), auth.hash_clave(c), dbmod.ahora()))
                cn.commit()
                click.echo(f"Administrador inicial '{u}' creado.")
            if os.environ.get("CARGAR_DEMO") == "1":
                from .datos_base import cargar_demo
                click.echo(cargar_demo())
        click.echo("Arranque completo.")

    return app
