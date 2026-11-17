"""Login, roles, permisos y protección CSRF."""
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import TZ, ahora, db, registrar

bp = Blueprint("auth", __name__)

ROLES = {
    "admin": "Administrador",
    "supervisor": "Supervisor de Distribución",
    "validador": "Validador de averías",
    "ruta": "Ruta / Conductor",
    "ventas": "Ventas (consulta)",
}

PERMISOS = {
    "admin": {"usuarios", "cargas", "maestros", "contactos", "averias_registrar", "averias_validar", "bitacora",
              "alertas_registrar", "alertas_gestionar"},
    "supervisor": {"cargas", "maestros", "contactos", "averias_registrar", "averias_validar",
                   "alertas_registrar", "alertas_gestionar"},
    "validador": {"maestros", "averias_validar"},
    "ruta": {"averias_registrar", "alertas_registrar"},
    "ventas": set(),
}

MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15


def puede(permiso):
    u = g.get("usuario")
    return bool(u) and permiso in PERMISOS.get(u["rol"], set())


def requiere(*permisos):
    """Decorador: exige sesión iniciada y (si se indican) al menos uno de los permisos."""
    def deco(f):
        @wraps(f)
        def envoltura(*a, **kw):
            if not g.get("usuario"):
                return redirect(url_for("auth.login", next=request.full_path))
            if g.usuario["debe_cambiar"] and request.endpoint not in ("auth.cambiar_clave", "auth.logout"):
                return redirect(url_for("auth.cambiar_clave"))
            if permisos and not any(puede(p) for p in permisos):
                abort(403)
            return f(*a, **kw)
        return envoltura
    return deco


def cargar_usuario():
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = db().uno("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (uid,))
        if u and session.get("sello") == u["password_hash"][-12:]:
            g.usuario = u
        else:
            session.clear()


# ---------- CSRF ----------

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verificar_csrf():
    if request.method == "POST":
        enviado = request.form.get("csrf") or request.headers.get("X-CSRF")
        if not enviado or not secrets.compare_digest(enviado, session.get("csrf", "")):
            abort(400, "Sesión vencida. Recarga la página e inténtalo de nuevo.")


# ---------- Contraseñas ----------

def hash_clave(clave):
    return generate_password_hash(clave)


def clave_valida(clave):
    return len(clave) >= 8 and any(c.isdigit() for c in clave) and any(c.isalpha() for c in clave)


# ---------- Vistas ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip().lower()
        clave = request.form.get("clave", "")
        u = db().uno("SELECT * FROM usuarios WHERE usuario = ?", (usuario,))
        ahora_dt = datetime.now(TZ)

        if u and u["bloqueado_hasta"] and u["bloqueado_hasta"] > ahora():
            flash(f"Usuario bloqueado temporalmente por intentos fallidos. Intenta después de las "
                  f"{u['bloqueado_hasta'][11:16]}.", "error")
            return render_template("login.html", usuario_form=usuario), 429

        if not u or not u["activo"] or not check_password_hash(u["password_hash"], clave):
            if u:
                intentos = u["intentos_fallidos"] + 1
                bloqueo = None
                if intentos >= MAX_INTENTOS:
                    bloqueo = (ahora_dt + timedelta(minutes=MINUTOS_BLOQUEO)).strftime("%Y-%m-%d %H:%M:%S")
                    intentos = 0
                db().ejecutar("UPDATE usuarios SET intentos_fallidos = ?, bloqueado_hasta = ? WHERE id = ?",
                              (intentos, bloqueo, u["id"]))
                registrar("Login fallido", "usuarios", usuario, usuario=usuario)
                db().commit()
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("login.html", usuario_form=usuario), 401

        session.clear()
        session.permanent = True
        session["uid"] = u["id"]
        session["usuario"] = u["usuario"]
        session["sello"] = u["password_hash"][-12:]
        db().ejecutar("UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL, ultimo_acceso = ? "
                      "WHERE id = ?", (ahora(), u["id"]))
        registrar("Inicio de sesión", "usuarios", u["usuario"], usuario=u["usuario"])
        db().commit()
        destino = request.args.get("next", "")
        if not destino.startswith("/") or destino.startswith("//"):
            destino = url_for("inicio.inicio")
        return redirect(destino)
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/cambiar-clave", methods=["GET", "POST"])
@requiere()
def cambiar_clave():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")
        if not check_password_hash(g.usuario["password_hash"], actual):
            flash("La contraseña actual no es correcta.", "error")
        elif nueva != confirmar:
            flash("Las contraseñas nuevas no coinciden.", "error")
        elif not clave_valida(nueva):
            flash("La contraseña debe tener al menos 8 caracteres, con letras y números.", "error")
        elif nueva == actual:
            flash("La contraseña nueva debe ser distinta a la actual.", "error")
        else:
            h = hash_clave(nueva)
            db().ejecutar("UPDATE usuarios SET password_hash = ?, debe_cambiar = 0 WHERE id = ?",
                          (h, g.usuario["id"]))
            registrar("Cambio de contraseña", "usuarios", g.usuario["usuario"])
            db().commit()
            session["sello"] = h[-12:]
            flash("Contraseña actualizada.", "ok")
            return redirect(url_for("inicio.inicio"))
    return render_template("cambiar_clave.html")
