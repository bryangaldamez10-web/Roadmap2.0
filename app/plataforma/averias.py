"""Módulo de averías: registro por la ruta, validación y exportación."""
import base64
import binascii
import io
import json
from datetime import datetime, timedelta

from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .auth import puede, requiere
from .db import TZ, ahora, db, hoy, registrar

bp = Blueprint("averias", __name__, url_prefix="/averias")

UNIDADES = ["Cajas", "Unidades"]
ESTADOS = ["Pendiente", "Validado", "Rechazado"]
MAX_FOTO = 3 * 1024 * 1024
MAX_FOTOS = 3


def equivalente_cajas(cantidad, unidad, upc):
    if unidad == "Cajas":
        return cantidad
    if unidad == "Unidades" and upc and upc > 0:
        return round(cantidad / upc, 3)
    return None


def filtros_desde_request():
    f = {
        "desde": request.args.get("desde") or (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d"),
        "hasta": request.args.get("hasta") or hoy(),
        "ruta": request.args.get("ruta", ""),
        "estado": request.args.get("estado", ""),
        "motivo": request.args.get("motivo", ""),
    }
    where = ["fecha_jornada >= ?", "fecha_jornada <= ?"]
    params = [f["desde"], f["hasta"]]
    if g.usuario["rol"] == "ruta" and not puede("averias_validar"):
        where.append("ruta_codigo = ?")
        params.append(g.usuario["ruta_codigo"] or "-")
    elif f["ruta"]:
        where.append("ruta_codigo = ?")
        params.append(f["ruta"])
    if f["estado"]:
        where.append("estado = ?")
        params.append(f["estado"])
    if f["motivo"]:
        where.append("motivo = ?")
        params.append(f["motivo"])
    return f, " WHERE " + " AND ".join(where), params


COLUMNAS_LISTA = ("id, folio, fecha_jornada, creado, ruta_codigo, reportado_por, codsap, sku_nombre, categoria, "
                  "cantidad, unidad, unidades_por_caja, cajas_equiv, motivo, comentario, estado, validado_por, "
                  "validado_en, observacion, "
                  "(SELECT COUNT(*) FROM averia_fotos f WHERE f.averia_id = averias.id) AS n_fotos")


@bp.route("/nueva", methods=["GET", "POST"])
@requiere("averias_registrar")
def nueva():
    cn = db()
    u = g.usuario
    ruta_fija = u["ruta_codigo"] if u["rol"] == "ruta" else None
    if u["rol"] == "ruta" and not ruta_fija:
        flash("Tu usuario no tiene una ruta asignada. Pide al administrador que la configure.", "error")
        return redirect(url_for("inicio.inicio"))

    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas WHERE activo = 1 ORDER BY codigo")]
    motivos = [m["nombre"] for m in cn.todos("SELECT nombre FROM motivos_averia WHERE activo = 1 ORDER BY orden")]

    if request.method == "POST":
        f = request.form
        errores = []
        ruta = ruta_fija or f.get("ruta", "").strip()
        if ruta not in rutas:
            errores.append("Elige una ruta válida.")
        fecha = f.get("fecha_jornada", "")
        try:
            dt = datetime.strptime(fecha, "%Y-%m-%d")
            if not (datetime.now(TZ).date() - timedelta(days=30) <= dt.date() <= datetime.now(TZ).date()):
                errores.append("La fecha debe ser de los últimos 30 días.")
        except ValueError:
            errores.append("Fecha no válida.")
        reportado = f.get("reportado_por", "").strip()[:120]
        if not reportado:
            errores.append("Indica quién reporta.")

        sku = None
        manual = f.get("sku_manual", "").strip()[:200]
        if f.get("sku_id"):
            sku = cn.uno("SELECT * FROM skus WHERE id = ? AND activo = 1", (f.get("sku_id"),))
            if not sku:
                errores.append("El SKU elegido no existe.")
        elif not manual:
            errores.append("Elige el SKU averiado.")

        unidad = f.get("unidad")
        if unidad not in UNIDADES:
            errores.append("Elige si reportas cajas o unidades.")
        try:
            cantidad = float(f.get("cantidad", "").replace(",", "."))
            if not 0 < cantidad <= 100000:
                raise ValueError
        except ValueError:
            errores.append("La cantidad debe ser mayor que cero.")
            cantidad = 0
        motivo = f.get("motivo", "")
        if motivo not in motivos:
            errores.append("Elige el motivo de la avería.")
        comentario = f.get("comentario", "").strip()[:500]

        fotos = []
        for b64 in [x for x in f.getlist("foto_b64") if x][:MAX_FOTOS]:
            try:
                foto = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                errores.append("Una de las fotos no se pudo procesar. Tómala de nuevo.")
                continue
            if len(foto) > MAX_FOTO or not foto.startswith(b"\xff\xd8"):
                errores.append("Una de las fotos no es válida o es demasiado grande.")
                continue
            fotos.append(foto)
        if not fotos:
            errores.append("Toma al menos una foto del producto averiado como evidencia.")

        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("averias/nueva.html", rutas=rutas, motivos=motivos, unidades=UNIDADES,
                                   skus_json=skus_json(), ruta_fija=ruta_fija, form=f, hoy=hoy()), 400

        upc = sku["unidades_por_caja"] if sku else None
        aid = cn.insertar(
            "INSERT INTO averias (fecha_jornada, creado, ruta_codigo, usuario_id, reportado_por, codsap, sku_nombre, "
            "categoria, cantidad, unidad, unidades_por_caja, cajas_equiv, motivo, comentario, estado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente')",
            (fecha, ahora(), ruta, u["id"], reportado, sku["codsap"] if sku else None,
             sku["nombre"] if sku else manual, sku["categoria"] if sku else "SKU no listado",
             cantidad, unidad, upc, equivalente_cajas(cantidad, unidad, upc), motivo, comentario))
        momento = ahora()
        cn.varios("INSERT INTO averia_fotos (averia_id, creado, foto, tipo, bytes) VALUES (?, ?, ?, 'image/jpeg', ?)",
                  [(aid, momento, ft, len(ft)) for ft in fotos])
        folio = f"AV-{fecha[2:4]}{fecha[5:7]}{fecha[8:10]}-{aid:05d}"
        cn.ejecutar("UPDATE averias SET folio = ? WHERE id = ?", (folio, aid))
        registrar("Registró avería", "averias", folio)
        cn.commit()
        return redirect(url_for("averias.registrada", aid=aid))

    return render_template("averias/nueva.html", rutas=rutas, motivos=motivos, unidades=UNIDADES,
                           skus_json=skus_json(), ruta_fija=ruta_fija, form={}, hoy=hoy())


def skus_json():
    filas = db().todos("SELECT id, codsap, nombre, categoria, unidades_por_caja FROM skus WHERE activo = 1 "
                       "ORDER BY categoria, nombre")
    orden = ["CERVEZA", "CARBONATADOS", "NO CARBONATADOS", "AGUA", "ENVASE"]
    filas.sort(key=lambda s: (orden.index(s["categoria"]) if s["categoria"] in orden else 99, s["categoria"] or "", s["nombre"]))
    datos = [[s["id"], s["codsap"], s["nombre"], s["categoria"] or "OTROS", s["unidades_por_caja"] or 1] for s in filas]
    return json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")


def obtener(aid):
    a = db().uno(f"SELECT {COLUMNAS_LISTA} FROM averias WHERE id = ?", (aid,)) or abort(404)
    if not puede("averias_validar") and a["ruta_codigo"] != g.usuario["ruta_codigo"]:
        abort(403)
    return a


def fotos_de(ids):
    """{averia_id: [foto_id, ...]} para las averías indicadas."""
    if not ids:
        return {}
    res = {}
    marcas = ", ".join("?" for _ in ids)
    for r in db().todos(f"SELECT id, averia_id FROM averia_fotos WHERE averia_id IN ({marcas}) ORDER BY id", list(ids)):
        res.setdefault(r["averia_id"], []).append(r["id"])
    return res


@bp.route("/registrada/<int:aid>")
@requiere("averias_registrar")
def registrada(aid):
    return render_template("averias/registrada.html", a=obtener(aid), fotos=fotos_de([aid]).get(aid, []))


@bp.route("/")
@requiere("averias_registrar", "averias_validar")
def lista():
    cn = db()
    f, where, params = filtros_desde_request()
    filas = cn.todos(f"SELECT {COLUMNAS_LISTA} FROM averias{where} ORDER BY id DESC LIMIT 300", params)
    kpi = cn.uno(f"SELECT COUNT(*) AS registros, COALESCE(SUM(cajas_equiv), 0) AS cajas, "
                 f"COALESCE(SUM(CASE WHEN estado = 'Pendiente' THEN 1 ELSE 0 END), 0) AS pendientes, "
                 f"COALESCE(SUM(CASE WHEN estado = 'Validado' THEN cajas_equiv ELSE 0 END), 0) AS validadas "
                 f"FROM averias{where}", params)
    por_motivo = cn.todos(f"SELECT motivo AS nombre, COALESCE(SUM(cajas_equiv), 0) AS cajas FROM averias{where} "
                          f"GROUP BY motivo ORDER BY cajas DESC", params)
    por_ruta = cn.todos(f"SELECT ruta_codigo AS nombre, COALESCE(SUM(cajas_equiv), 0) AS cajas FROM averias{where} "
                        f"GROUP BY ruta_codigo ORDER BY cajas DESC LIMIT 10", params)
    rutas = [r["codigo"] for r in cn.todos("SELECT codigo FROM rutas ORDER BY codigo")]
    motivos = [m["nombre"] for m in cn.todos("SELECT nombre FROM motivos_averia ORDER BY orden")]
    return render_template("averias/lista.html", filas=filas, kpi=kpi, por_motivo=por_motivo, por_ruta=por_ruta,
                           f=f, rutas=rutas, motivos=motivos, estados=ESTADOS,
                           fotos=fotos_de([a["id"] for a in filas]))


@bp.route("/<int:aid>/estado", methods=["POST"])
@requiere("averias_validar")
def cambiar_estado(aid):
    cn = db()
    a = obtener(aid)
    estado = request.form.get("estado")
    obs = request.form.get("observacion", "").strip()[:500]
    if estado not in ESTADOS:
        abort(400)
    if estado == "Validado" and not a["n_fotos"]:
        flash(f"{a['folio']}: no tiene foto de evidencia; no se puede validar. Recházala o pide la foto.", "error")
    elif estado == "Rechazado" and not obs:
        flash(f"{a['folio']}: escribe el motivo del rechazo.", "error")
    else:
        valida = estado != "Pendiente"
        cn.ejecutar("UPDATE averias SET estado = ?, observacion = ?, validado_por = ?, validado_en = ? WHERE id = ?",
                    (estado, obs or None, g.usuario["nombre"] if valida else None, ahora() if valida else None, aid))
        registrar(f"Avería {estado.lower()}", "averias", f"{a['folio']} {obs}".strip())
        cn.commit()
        flash(f"{a['folio']} quedó como {estado.lower()}.", "ok")
    return redirect(request.form.get("volver") or url_for("averias.lista"))


@bp.route("/foto/<int:fid>")
@requiere("averias_registrar", "averias_validar")
def foto(fid):
    r = db().uno("SELECT averia_id, foto, tipo FROM averia_fotos WHERE id = ?", (fid,)) or abort(404)
    obtener(r["averia_id"])  # valida que el usuario pueda ver esa avería
    return Response(bytes(r["foto"]), mimetype=r["tipo"] or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@bp.route("/exportar")
@requiere("averias_validar")
def exportar():
    f, where, params = filtros_desde_request()
    filas = db().todos(f"SELECT {COLUMNAS_LISTA} FROM averias{where} ORDER BY fecha_jornada, id", params)
    cols = [("folio", "Folio"), ("fecha_jornada", "Fecha de jornada"), ("creado", "Registrado"),
            ("ruta_codigo", "Ruta"), ("reportado_por", "Reportado por"), ("codsap", "CODSAP"),
            ("sku_nombre", "SKU"), ("categoria", "Categoría"), ("cantidad", "Cantidad"), ("unidad", "Unidad"),
            ("unidades_por_caja", "Unidades por caja"), ("cajas_equiv", "Cajas equivalentes"),
            ("motivo", "Motivo"), ("comentario", "Comentario"), ("estado", "Estado"),
            ("validado_por", "Validado por"), ("validado_en", "Fecha de validación"), ("observacion", "Observación")]
    wb = Workbook()
    ws = wb.active
    ws.title = "Averías"
    ws.append([t for _, t in cols])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1C1B19")
    for fila in filas:
        ws.append([fila[k] for k, _ in cols])
    for i, (_, t) in enumerate(cols, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(t) + 2)
    ws.column_dimensions["G"].width = 38
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    registrar("Exportó averías", "averias", f"{f['desde']} a {f['hasta']} ({len(filas)} filas)")
    db().commit()
    return send_file(buf, as_attachment=True, download_name=f"averias_{f['desde']}_a_{f['hasta']}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
