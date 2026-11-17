"""Planificación diaria: resumen por ruta, detalle de paradas, mapa y "Mi ruta de hoy" para el conductor."""
import json
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .auth import puede, requiere
from .db import TZ, db, hoy

bp = Blueprint("planificacion", __name__, url_prefix="/planificacion")


def fecha_param():
    f = request.args.get("fecha") or hoy()
    try:
        datetime.strptime(f, "%Y-%m-%d")
    except ValueError:
        f = hoy()
    return f


def dia_vecino(fecha, delta):
    return (datetime.strptime(fecha, "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def paradas(fecha, ruta):
    """Paradas activas de una ruta con coordenadas del maestro de clientes y alertas ya creadas."""
    cn = db()
    filas = cn.todos(
        "SELECT p.*, c.latitud, c.longitud, c.nombre AS cliente_nombre, c.bdr_codigo, c.supervisor_codigo "
        "FROM planificacion p LEFT JOIN clientes c ON c.codigo = p.cliente_codigo "
        "WHERE p.fecha = ? AND p.ruta_codigo = ? AND p.activo = 1 ORDER BY p.llegada, p.id", (fecha, ruta))
    alertas = {}
    for a in cn.todos("SELECT id, folio, estado, planificacion_id, cliente_codigo FROM alertas "
                      "WHERE fecha = ? AND ruta_codigo = ?", (fecha, ruta)):
        alertas.setdefault(a["planificacion_id"] or ("c", a["cliente_codigo"]), []).append(a)
    for n, p in enumerate(filas, start=1):
        p["secuencia"] = n
        p["alertas"] = alertas.get(p["id"], []) + alertas.get(("c", p["cliente_codigo"]), [])
        if p["latitud"] is not None and p["longitud"] is not None:
            p["maps"] = f"https://www.google.com/maps/search/?api=1&query={p['latitud']},{p['longitud']}"
        else:
            p["maps"] = "https://www.google.com/maps/search/?api=1&query=" + quote_plus(
                f"{p['direccion'] or ''} {p['ciudad'] or ''} El Salvador")
    return filas


def totales(filas):
    return {
        "clientes": len(filas),
        "cajas": sum(p["cajas"] or 0 for p in filas),
        "peso": sum(p["peso"] or 0 for p in filas),
        "hl": sum(p["hectolitros"] or 0 for p in filas) if any(p["hectolitros"] for p in filas) else None,
        "inicio": min((p["llegada"] for p in filas if p["llegada"]), default=None),
        "fin": max((p["salida"] for p in filas if p["salida"]), default=None),
        "vehiculos": sorted({p["vehiculo"] for p in filas if p["vehiculo"]}),
        "alertas": sum(len(p["alertas"]) for p in filas),
    }


def puntos_mapa(filas):
    return json.dumps([{"lat": p["latitud"], "lng": p["longitud"], "n": p["secuencia"],
                        "t": f"{p['secuencia']}. {p['nombre_negocio'] or p['cliente_nombre'] or p['cliente_codigo']}",
                        "c": p["cajas"], "h": (p["llegada"] or "")[11:16], "a": bool(p["alertas"])}
                       for p in filas if p["latitud"] is not None], ensure_ascii=False).replace("<", "\\u003c")


@bp.route("/")
@requiere("alertas_gestionar")
def resumen():
    """Todas las rutas del día (administrador y supervisor)."""
    fecha = fecha_param()
    cn = db()
    rutas = cn.todos(
        "SELECT ruta_codigo, COUNT(*) AS clientes, COALESCE(SUM(cajas), 0) AS cajas, COALESCE(SUM(peso), 0) AS peso, "
        "SUM(hectolitros) AS hl, MIN(llegada) AS inicio, MAX(salida) AS fin, MIN(vehiculo) AS vehiculo "
        "FROM planificacion WHERE fecha = ? AND activo = 1 GROUP BY ruta_codigo ORDER BY ruta_codigo", (fecha,))
    alertas = {r["ruta_codigo"]: r for r in cn.todos(
        "SELECT ruta_codigo, COUNT(*) AS n, COALESCE(SUM(cajas_riesgo), 0) AS riesgo, "
        "COALESCE(SUM(CASE WHEN estado = 'Abierta' THEN 1 ELSE 0 END), 0) AS abiertas "
        "FROM alertas WHERE fecha = ? GROUP BY ruta_codigo", (fecha,))}
    averias = {r["ruta_codigo"]: r["cajas"] for r in cn.todos(
        "SELECT ruta_codigo, COALESCE(SUM(cajas_equiv), 0) AS cajas FROM averias WHERE fecha_jornada = ? "
        "GROUP BY ruta_codigo", (fecha,))}
    conductores = {r["codigo"]: r for r in cn.todos("SELECT codigo, conductor_nombre, conductor_telefono FROM rutas")}
    for r in rutas:
        a = alertas.get(r["ruta_codigo"]) or {}
        r.update(alertas=a.get("n", 0), riesgo=a.get("riesgo", 0), abiertas=a.get("abiertas", 0),
                 averias=averias.get(r["ruta_codigo"], 0),
                 conductor=(conductores.get(r["ruta_codigo"]) or {}).get("conductor_nombre"))
    tot = {
        "rutas": len(rutas), "clientes": sum(r["clientes"] for r in rutas), "cajas": sum(r["cajas"] for r in rutas),
        "peso": sum(r["peso"] for r in rutas), "alertas": sum(r["alertas"] for r in rutas),
        "riesgo": sum(r["riesgo"] for r in rutas),
    }
    tot["pct_riesgo"] = tot["riesgo"] / tot["cajas"] * 100 if tot["cajas"] else None
    fechas = [f["fecha"] for f in cn.todos("SELECT DISTINCT fecha FROM planificacion WHERE activo = 1 "
                                            "ORDER BY fecha DESC LIMIT 10")]
    return render_template("planificacion/resumen.html", fecha=fecha, rutas=rutas, tot=tot, fechas=fechas,
                           ayer=dia_vecino(fecha, -1), manana=dia_vecino(fecha, 1))


@bp.route("/ruta/<ruta>")
@requiere("alertas_registrar", "alertas_gestionar")
def ruta(ruta):
    """Detalle de una ruta con mapa. El conductor solo puede ver la suya."""
    if not puede("alertas_gestionar") and ruta != g.usuario["ruta_codigo"]:
        abort(403)
    fecha = fecha_param()
    filas = paradas(fecha, ruta)
    info = db().uno("SELECT * FROM rutas WHERE codigo = ?", (ruta,)) or {"codigo": ruta}
    return render_template("planificacion/ruta.html", fecha=fecha, ruta=info, filas=filas, tot=totales(filas),
                           puntos=puntos_mapa(filas), ayer=dia_vecino(fecha, -1), manana=dia_vecino(fecha, 1))


@bp.route("/mi-ruta")
@requiere("alertas_registrar")
def mi_ruta():
    if g.usuario["rol"] != "ruta":
        return redirect(url_for("planificacion.resumen"))
    return redirect(url_for("planificacion.ruta", ruta=g.usuario["ruta_codigo"] or "-", fecha=fecha_param()))
