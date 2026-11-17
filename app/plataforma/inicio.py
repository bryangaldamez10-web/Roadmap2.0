from flask import Blueprint, g, render_template

from .auth import puede, requiere
from .db import db, hoy

bp = Blueprint("inicio", __name__)


@bp.route("/salud")
def salud():
    """Revisión de estado para Railway: responde 200 si la base de datos contesta."""
    db().valor("SELECT 1 AS ok")
    return {"estado": "ok"}


@bp.route("/")
@requiere()
def inicio():
    cn = db()
    dia = hoy()
    resumen = {}
    if puede("averias_validar"):
        resumen["hoy"] = cn.valor("SELECT COUNT(*) AS n FROM averias WHERE fecha_jornada = ?", (dia,), 0)
        resumen["cajas_hoy"] = cn.valor("SELECT COALESCE(SUM(cajas_equiv), 0) AS n FROM averias "
                                        "WHERE fecha_jornada = ?", (dia,), 0)
        resumen["pendientes"] = cn.valor("SELECT COUNT(*) AS n FROM averias WHERE estado = 'Pendiente'", (), 0)
    elif g.usuario["rol"] == "ruta":
        resumen["mias_hoy"] = cn.valor("SELECT COUNT(*) AS n FROM averias WHERE fecha_jornada = ? "
                                       "AND ruta_codigo = ?", (dia, g.usuario["ruta_codigo"]), 0)
    if puede("alertas_gestionar"):
        resumen["alertas_abiertas"] = cn.valor("SELECT COUNT(*) AS n FROM alertas WHERE estado = 'Abierta'", (), 0)
    if puede("maestros"):
        resumen["clientes"] = cn.valor("SELECT COUNT(*) AS n FROM clientes WHERE activo = 1", (), 0)
        resumen["rutas"] = cn.valor("SELECT COUNT(*) AS n FROM rutas WHERE activo = 1", (), 0)
        resumen["skus"] = cn.valor("SELECT COUNT(*) AS n FROM skus WHERE activo = 1", (), 0)
    return render_template("inicio.html", r=resumen)
