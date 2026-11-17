"""Alertas de posible devolución: cruce cliente → supervisor y BDR, mensaje para WhatsApp y seguimiento."""
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .auth import puede, requiere
from .db import TZ, ahora, db, hoy, registrar

bp = Blueprint("alertas", __name__, url_prefix="/alertas")

TIPOS_PEDIDO = ["B2B", "Preventa", "Televenta", "Otro"]
ESTADOS = ["Abierta", "Evitada", "Devolución parcial", "Devolución total"]
CODIGO_PAIS = "503"


def es_ruta():
    return g.usuario["rol"] == "ruta"


def tel_whatsapp(tel):
    """Convierte un teléfono local a formato internacional para wa.me (El Salvador por defecto)."""
    d = re.sub(r"\D", "", tel or "")
    if len(d) == 8:
        d = CODIGO_PAIS + d
    return d if len(d) >= 10 else None


def num_txt(v):
    if v is None:
        return "–"
    return f"{v:,.3f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"


def contactos(a):
    """Datos de supervisor y BDR del cliente, tomados de los maestros vigentes."""
    cn = db()
    res = {}
    for clave in ("bdr", "supervisor"):
        cod = a.get(f"{clave}_codigo")
        p = cn.uno("SELECT codigo, nombre, telefono FROM personal_ventas WHERE codigo = ?", (cod,)) if cod else None
        res[clave] = p or {"codigo": cod, "nombre": None, "telefono": None}
    ruta = cn.uno("SELECT * FROM rutas WHERE codigo = ?", (a.get("ruta_codigo"),)) or {}
    res["ruta"] = ruta
    cli = cn.uno("SELECT telefono FROM clientes WHERE codigo = ?", (a.get("cliente_codigo"),)) or {}
    res["cliente_telefono"] = cli.get("telefono")
    return res


def mensaje(a, c):
    """Mismo formato que usaba la alerta de Roadmap."""
    sup, bdr = c["supervisor"], c["bdr"]
    lineas = [
        f"⚠️ *ALERTA DE POSIBLE DEVOLUCIÓN* · {a['folio']}",
        f"*Código:* {a['cliente_codigo']}",
        f"*Nombre:* {a['cliente_nombre'] or '–'}",
        f"*Teléfono Cliente:* {c['cliente_telefono'] or '–'}",
        f"*Supervisor:* {sup['nombre'] or sup['codigo'] or '–'}",
        f"*BDR:* {' '.join(x for x in (bdr['codigo'], bdr['nombre']) if x) or '–'}",
        f"*Telf.BDR:* {bdr['telefono'] or '–'}",
        f"*Pedido|Cliente|Riesgo:* {a['tipo_pedido'] or '–'}",
        *([f"*Órdenes:* {a['ordenes']}"] if a.get("ordenes") else []),
        f"*Cajas:* {num_txt(a['cajas'])}",
        f"*Hectolitros:* {num_txt(a['hectolitros'])}",
        f"*Cajas Riesgo:* {num_txt(a['cajas_riesgo'])}",
        f"*Ruta:* {a['ruta_codigo']}",
        f"*Teléfono Ruta:* {c['ruta'].get('telefono') or '–'}",
        f"*Localidad:* {a['localidad'] or '–'}",
        f"*Hubo comunicación con ventas:* {'SÍ' if a['hubo_comunicacion'] else 'NO'}",
        f"*Motivo:* {a['motivo']}",
    ]
    if a["comentario"]:
        lineas.append(f"💬 {a['comentario']}")
    lineas.append(f"🕐 {a['creado'][11:16]} {a['ruta_codigo']}")
    if a["latitud"] is not None and a["longitud"] is not None:
        lineas.append(f"🌍 *Ubicación:* https://www.google.com/maps?q={a['latitud']},{a['longitud']}")
    return "\n".join(lineas)


def parada_permitida(pid):
    """Parada de la planificación, si existe y el usuario puede usarla."""
    if not pid:
        return None
    p = db().uno("SELECT * FROM planificacion WHERE id = ? AND activo = 1", (pid,))
    if p and es_ruta() and p["ruta_codigo"] != g.usuario["ruta_codigo"]:
        abort(403)
    return p


def cliente_en_plan_de_ruta(codigo, ruta):
    return bool(db().uno("SELECT id FROM planificacion WHERE cliente_codigo = ? AND ruta_codigo = ? AND activo = 1 "
                         "AND fecha >= ?", (codigo, ruta, (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d"))))


def obtener(aid):
    a = db().uno("SELECT * FROM alertas WHERE id = ?", (aid,)) or abort(404)
    if not puede("alertas_gestionar") and a["ruta_codigo"] != g.usuario["ruta_codigo"]:
        abort(403)
    return a


# ---------- Búsqueda de cliente (la usa el formulario) ----------

@bp.route("/cliente/<codigo>")
@requiere("alertas_registrar")
def buscar_cliente(codigo):
    codigo = codigo.strip().upper()
    c = db().uno("SELECT codigo, nombre, localidad, ruta_codigo, bdr_codigo, supervisor_codigo, activo "
                 "FROM clientes WHERE codigo = ?", (codigo,))
    if not c:
        return jsonify(ok=False, error=f"El cliente {codigo} no está en la base de clientes."), 404
    if (es_ruta() and c["ruta_codigo"] and c["ruta_codigo"] != g.usuario["ruta_codigo"]
            and not cliente_en_plan_de_ruta(codigo, g.usuario["ruta_codigo"])):
        return jsonify(ok=False, error=f"El cliente {codigo} pertenece a la ruta {c['ruta_codigo']}."), 403
    k = contactos(c)
    return jsonify(ok=True, codigo=c["codigo"], nombre=c["nombre"], localidad=c["localidad"],
                   ruta=c["ruta_codigo"], inactivo=not c["activo"],
                   bdr={"codigo": k["bdr"]["codigo"], "nombre": k["bdr"]["nombre"], "telefono": k["bdr"]["telefono"]},
                   supervisor={"codigo": k["supervisor"]["codigo"], "nombre": k["supervisor"]["nombre"],
                               "telefono": k["supervisor"]["telefono"]})


# ---------- Registro ----------

@bp.route("/nueva", methods=["GET", "POST"])
@requiere("alertas_registrar")
def nueva():
    cn = db()
    motivos = [m["nombre"] for m in cn.todos("SELECT nombre FROM motivos_devolucion WHERE activo = 1 ORDER BY orden")]
    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas WHERE activo = 1 ORDER BY codigo")]
    ruta_fija = g.usuario["ruta_codigo"] if es_ruta() else None
    if es_ruta() and not ruta_fija:
        flash("Tu usuario no tiene una ruta asignada. Pide al administrador que la configure.", "error")
        return redirect(url_for("inicio.inicio"))

    if request.method == "POST":
        f = request.form
        errores = []
        parada = parada_permitida(f.get("planificacion_id"))
        codigo = (parada["cliente_codigo"] if parada else f.get("cliente", "")).strip().upper()
        cli = cn.uno("SELECT * FROM clientes WHERE codigo = ?", (codigo,))
        if not cli and parada:  # cliente planificado que aún no está en el maestro
            cli = {"codigo": codigo, "nombre": parada["nombre_negocio"], "localidad": parada["ciudad"],
                   "ruta_codigo": parada["ruta_codigo"], "bdr_codigo": None, "supervisor_codigo": None}
        if not cli:
            errores.append("Busca un código de cliente válido.")
        elif (es_ruta() and not parada and cli["ruta_codigo"] and cli["ruta_codigo"] != ruta_fija
              and not cliente_en_plan_de_ruta(codigo, ruta_fija)):
            errores.append(f"El cliente pertenece a la ruta {cli['ruta_codigo']}.")
        ruta = (parada or {}).get("ruta_codigo") or ruta_fija or f.get("ruta") or (cli or {}).get("ruta_codigo") or ""
        if ruta not in rutas:
            errores.append("Elige la ruta que entrega.")

        def numero(campo, titulo, requerido=False):
            v = f.get(campo, "").strip().replace(",", ".")
            if not v:
                if requerido:
                    errores.append(f"Indica {titulo}.")
                return None
            try:
                n = float(v)
                if n < 0 or n > 100000:
                    raise ValueError
                return n
            except ValueError:
                errores.append(f"{titulo.capitalize()} no es un número válido.")
                return None

        cajas = numero("cajas", "las cajas del pedido")
        riesgo = numero("cajas_riesgo", "las cajas en riesgo", requerido=True)
        hl = numero("hectolitros", "los hectolitros")
        if riesgo is not None and riesgo <= 0:
            errores.append("Las cajas en riesgo deben ser mayores que cero.")
        if cajas is not None and riesgo is not None and riesgo > cajas:
            errores.append("Las cajas en riesgo no pueden ser más que las cajas del pedido.")
        motivo = f.get("motivo", "")
        if motivo not in motivos:
            errores.append("Elige el motivo.")
        tipo = f.get("tipo_pedido", "")
        if tipo and tipo not in TIPOS_PEDIDO:
            tipo = "Otro"
        comunicacion = f.get("hubo_comunicacion")
        if comunicacion not in ("1", "0"):
            errores.append("Indica si hubo comunicación con ventas.")
        lat = lng = None
        try:
            if f.get("latitud") and f.get("longitud"):
                lat, lng = round(float(f["latitud"]), 7), round(float(f["longitud"]), 7)
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    lat = lng = None
        except ValueError:
            lat = lng = None

        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("alertas/nueva.html", motivos=motivos, tipos=TIPOS_PEDIDO, rutas=rutas,
                                   ruta_fija=ruta_fija, form=f, parada=parada), 400

        momento = ahora()
        aid = cn.insertar(
            "INSERT INTO alertas (creado, fecha, usuario_id, reportado_por, ruta_codigo, cliente_codigo, cliente_nombre, "
            "localidad, bdr_codigo, supervisor_codigo, tipo_pedido, cajas, cajas_riesgo, hectolitros, hubo_comunicacion, "
            "motivo, comentario, latitud, longitud, estado, ordenes, planificacion_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Abierta', ?, ?)",
            (momento, (parada or {}).get("fecha") or momento[:10], g.usuario["id"], g.usuario["nombre"], ruta,
             cli["codigo"], cli["nombre"], cli["localidad"], cli["bdr_codigo"], cli["supervisor_codigo"], tipo or None,
             cajas, riesgo, hl, int(comunicacion), motivo, f.get("comentario", "").strip()[:500] or None, lat, lng,
             (parada or {}).get("ordenes"), (parada or {}).get("id")))
        folio = f"AL-{momento[2:4]}{momento[5:7]}{momento[8:10]}-{aid:05d}"
        cn.ejecutar("UPDATE alertas SET folio = ? WHERE id = ?", (folio, aid))
        registrar("Registró alerta de devolución", "alertas", f"{folio} cliente {cli['codigo']}")
        cn.commit()
        return redirect(url_for("alertas.detalle", aid=aid, nueva=1))

    parada = parada_permitida(request.args.get("parada"))
    form = {}
    if parada:
        form = {"cliente": parada["cliente_codigo"], "ruta": parada["ruta_codigo"],
                "cajas": f"{parada['cajas']:g}" if parada["cajas"] is not None else "",
                "hectolitros": f"{parada['hectolitros']:g}" if parada["hectolitros"] is not None else ""}
    return render_template("alertas/nueva.html", motivos=motivos, tipos=TIPOS_PEDIDO, rutas=rutas,
                           ruta_fija=ruta_fija, form=form, parada=parada)


# ---------- Detalle con botones de WhatsApp ----------

@bp.route("/<int:aid>")
@requiere("alertas_registrar", "alertas_gestionar")
def detalle(aid):
    a = obtener(aid)
    c = contactos(a)
    texto = mensaje(a, c)
    enlaces = {"elegir": "https://wa.me/?text=" + quote(texto)}
    for clave, titulo in (("bdr", "BDR"), ("supervisor", "Supervisor")):
        tel = tel_whatsapp(c[clave]["telefono"])
        if tel:
            enlaces[clave] = (f"https://wa.me/{tel}?text=" + quote(texto),
                              f"{titulo}: {c[clave]['nombre'] or c[clave]['codigo']}")
    return render_template("alertas/detalle.html", a=a, c=c, texto=texto, enlaces=enlaces, estados=ESTADOS,
                           nueva=request.args.get("nueva"))


@bp.route("/<int:aid>/estado", methods=["POST"])
@requiere("alertas_gestionar")
def gestionar(aid):
    cn = db()
    a = obtener(aid)
    estado = request.form.get("estado")
    if estado not in ESTADOS:
        abort(400)
    resultado = request.form.get("resultado", "").strip()[:500] or None
    devueltas = None
    if estado == "Devolución parcial":
        try:
            devueltas = float(request.form.get("cajas_devueltas", "").replace(",", "."))
            if not 0 < devueltas <= (a["cajas_riesgo"] or 0):
                raise ValueError
        except ValueError:
            flash("En una devolución parcial indica cuántas cajas se devolvieron (mayor que cero y no más que las cajas en riesgo).", "error")
            return redirect(request.form.get("volver") or url_for("alertas.detalle", aid=aid))
    elif estado == "Devolución total":
        devueltas = a["cajas_riesgo"]
    elif estado == "Evitada":
        devueltas = 0
    cerrada = estado != "Abierta"
    cn.ejecutar("UPDATE alertas SET estado = ?, resultado = ?, cajas_devueltas = ?, gestionado_por = ?, gestionado_en = ? "
                "WHERE id = ?", (estado, resultado, devueltas, g.usuario["nombre"] if cerrada else None,
                                 ahora() if cerrada else None, aid))
    registrar(f"Alerta {estado.lower()}", "alertas", f"{a['folio']} {resultado or ''}".strip())
    cn.commit()
    flash(f"{a['folio']} quedó como {estado.lower()}.", "ok")
    return redirect(request.form.get("volver") or url_for("alertas.detalle", aid=aid))


# ---------- Lista y seguimiento ----------

@bp.route("/")
@requiere("alertas_registrar", "alertas_gestionar")
def lista():
    cn = db()
    f = {
        "desde": request.args.get("desde") or (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d"),
        "hasta": request.args.get("hasta") or hoy(),
        "ruta": request.args.get("ruta", ""),
        "estado": request.args.get("estado", ""),
    }
    where, params = ["fecha >= ?", "fecha <= ?"], [f["desde"], f["hasta"]]
    if not puede("alertas_gestionar"):
        where.append("ruta_codigo = ?")
        params.append(g.usuario["ruta_codigo"] or "-")
    elif f["ruta"]:
        where.append("ruta_codigo = ?")
        params.append(f["ruta"])
    if f["estado"]:
        where.append("estado = ?")
        params.append(f["estado"])
    w = " WHERE " + " AND ".join(where)
    filas = cn.todos(f"SELECT * FROM alertas{w} ORDER BY id DESC LIMIT 300", params)
    kpi = cn.uno(
        "SELECT COUNT(*) AS alertas, COALESCE(SUM(cajas_riesgo), 0) AS riesgo, "
        "COALESCE(SUM(CASE WHEN estado = 'Abierta' THEN 1 ELSE 0 END), 0) AS abiertas, "
        "COALESCE(SUM(CASE WHEN estado <> 'Abierta' THEN cajas_riesgo - COALESCE(cajas_devueltas, 0) ELSE 0 END), 0) AS salvadas, "
        "COALESCE(SUM(CASE WHEN estado <> 'Abierta' THEN cajas_riesgo ELSE 0 END), 0) AS riesgo_cerrado "
        f"FROM alertas{w}", params)
    kpi["efectividad"] = (kpi["salvadas"] / kpi["riesgo_cerrado"] * 100) if kpi["riesgo_cerrado"] else None
    por_motivo = cn.todos(f"SELECT motivo AS nombre, COALESCE(SUM(cajas_riesgo), 0) AS cajas, COUNT(*) AS n "
                          f"FROM alertas{w} GROUP BY motivo ORDER BY cajas DESC", params)
    nombres = {p["codigo"]: p["nombre"] for p in cn.todos("SELECT codigo, nombre FROM personal_ventas")}
    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas ORDER BY codigo")]
    return render_template("alertas/lista.html", filas=filas, kpi=kpi, por_motivo=por_motivo, f=f, rutas=rutas,
                           estados=ESTADOS, nombres=nombres)
