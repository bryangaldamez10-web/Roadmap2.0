"""Administración de usuarios y bitácora (solo administradores)."""
import re
import secrets
import string

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .auth import ROLES, hash_clave, requiere
from .db import ahora, db, registrar

bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")


def clave_temporal():
    alfabeto = string.ascii_letters.replace("l", "").replace("I", "").replace("O", "") + "23456789"
    while True:
        c = "".join(secrets.choice(alfabeto) for _ in range(10))
        if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c):
            return c


def datos_form(f, cn):
    errores = []
    nombre = f.get("nombre", "").strip()[:120]
    rol = f.get("rol", "")
    ruta = f.get("ruta_codigo", "").strip().upper() or None
    telefono = re.sub(r"[^\d+]", "", f.get("telefono", ""))[:20] or None
    if not nombre:
        errores.append("Escribe el nombre.")
    if rol not in ROLES:
        errores.append("Elige un rol válido.")
    if rol == "ruta" and not ruta:
        errores.append("Un usuario de ruta necesita una ruta asignada.")
    if ruta and not cn.uno("SELECT codigo FROM rutas WHERE codigo = ?", (ruta,)):
        errores.append(f"La ruta {ruta} no existe en los maestros.")
    if rol != "ruta":
        ruta = None
    return dict(nombre=nombre, rol=rol, ruta_codigo=ruta, telefono=telefono), errores


@bp.route("/")
@requiere("usuarios")
def lista():
    filas = db().todos("SELECT id, usuario, nombre, rol, ruta_codigo, telefono, activo, debe_cambiar, ultimo_acceso "
                       "FROM usuarios ORDER BY activo DESC, rol, nombre")
    return render_template("usuarios/lista.html", filas=filas)


@bp.route("/nuevo", methods=["GET", "POST"])
@requiere("usuarios")
def nuevo():
    cn = db()
    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas WHERE activo = 1 ORDER BY codigo")]
    if request.method == "POST":
        datos, errores = datos_form(request.form, cn)
        usuario = request.form.get("usuario", "").strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,40}", usuario):
            errores.append("El usuario debe tener de 3 a 40 caracteres: letras, números, punto, guion.")
        elif cn.uno("SELECT id FROM usuarios WHERE usuario = ?", (usuario,)):
            errores.append("Ese usuario ya existe.")
        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("usuarios/form.html", u=dict(request.form), rutas=rutas, nuevo=True), 400
        temporal = clave_temporal()
        cn.ejecutar("INSERT INTO usuarios (usuario, nombre, rol, ruta_codigo, telefono, password_hash, debe_cambiar, creado) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                    (usuario, datos["nombre"], datos["rol"], datos["ruta_codigo"], datos["telefono"],
                     hash_clave(temporal), ahora()))
        registrar("Creó usuario", "usuarios", f"{usuario} ({ROLES[datos['rol']]})")
        cn.commit()
        return render_template("usuarios/clave.html", usuario=usuario, nombre=datos["nombre"], clave=temporal)
    return render_template("usuarios/form.html", u={}, rutas=rutas, nuevo=True)


@bp.route("/<int:uid>", methods=["GET", "POST"])
@requiere("usuarios")
def editar(uid):
    cn = db()
    u = cn.uno("SELECT * FROM usuarios WHERE id = ?", (uid,)) or abort(404)
    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas WHERE activo = 1 ORDER BY codigo")]
    if request.method == "POST":
        accion = request.form.get("accion", "guardar")
        if accion == "restablecer":
            temporal = clave_temporal()
            cn.ejecutar("UPDATE usuarios SET password_hash = ?, debe_cambiar = 1, intentos_fallidos = 0, "
                        "bloqueado_hasta = NULL WHERE id = ?", (hash_clave(temporal), uid))
            registrar("Restableció contraseña", "usuarios", u["usuario"])
            cn.commit()
            return render_template("usuarios/clave.html", usuario=u["usuario"], nombre=u["nombre"], clave=temporal)
        if accion == "alternar":
            if uid == g.usuario["id"]:
                flash("No puedes desactivar tu propio usuario.", "error")
            else:
                cn.ejecutar("UPDATE usuarios SET activo = ? WHERE id = ?", (0 if u["activo"] else 1, uid))
                registrar("Desactivó usuario" if u["activo"] else "Activó usuario", "usuarios", u["usuario"])
                cn.commit()
                flash("Usuario " + ("desactivado." if u["activo"] else "activado."), "ok")
            return redirect(url_for("usuarios.lista"))
        datos, errores = datos_form(request.form, cn)
        if uid == g.usuario["id"] and datos["rol"] != "admin":
            errores.append("No puedes quitarte el rol de administrador.")
        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("usuarios/form.html", u={**u, **request.form}, rutas=rutas, nuevo=False), 400
        cn.ejecutar("UPDATE usuarios SET nombre = ?, rol = ?, ruta_codigo = ?, telefono = ? WHERE id = ?",
                    (datos["nombre"], datos["rol"], datos["ruta_codigo"], datos["telefono"], uid))
        registrar("Editó usuario", "usuarios", f"{u['usuario']} → {ROLES[datos['rol']]}")
        cn.commit()
        flash("Cambios guardados.", "ok")
        return redirect(url_for("usuarios.lista"))
    return render_template("usuarios/form.html", u=u, rutas=rutas, nuevo=False)


@bp.route("/bitacora")
@requiere("bitacora")
def bitacora():
    q = request.args.get("q", "").strip().lower()
    params, where = [], ""
    if q:
        where = " WHERE LOWER(usuario) LIKE ? OR LOWER(accion) LIKE ? OR LOWER(COALESCE(detalle, '')) LIKE ?"
        params = [f"%{q}%"] * 3
    filas = db().todos(f"SELECT * FROM bitacora{where} ORDER BY id DESC LIMIT 300", params)
    return render_template("usuarios/bitacora.html", filas=filas, q=q)
