from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import puede, requiere
from .db import db, registrar
from .entidades import ENTIDADES

bp = Blueprint("maestros", __name__, url_prefix="/maestros")
POR_PAGINA = 50


def columnas_visibles(ent):
    return [c for c in ent["columnas"] if not c.get("sensible") or puede("contactos")]


@bp.route("/<tipo>")
@requiere("maestros")
def lista(tipo):
    ent = ENTIDADES.get(tipo) or abort(404)
    if not ent.get("en_maestros", True):
        abort(404)
    cols = columnas_visibles(ent)
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "activos")
    ruta = request.args.get("ruta", "").strip()
    pagina = max(int(request.args.get("p", 1) or 1), 1)

    where, params = [], []
    if estado == "activos":
        where.append("activo = 1")
    elif estado == "inactivos":
        where.append("activo = 0")
    if q:
        textuales = [c["campo"] for c in cols if c["tipo"] in ("codigo", "texto")]
        where.append("(" + " OR ".join(f"LOWER(COALESCE({c}, '')) LIKE ?" for c in textuales) + ")")
        params += [f"%{q.lower()}%"] * len(textuales)
    if ruta and tipo == "clientes":
        where.append("ruta_codigo = ?")
        params.append(ruta)
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""

    cn = db()
    total = cn.valor(f"SELECT COUNT(*) AS n FROM {ent['tabla']}{sql_where}", params, 0)
    filas = cn.todos(
        f"SELECT {', '.join(c['campo'] for c in cols)}, activo FROM {ent['tabla']}{sql_where} "
        f"ORDER BY {ent['orden']} LIMIT {POR_PAGINA} OFFSET {(pagina - 1) * POR_PAGINA}", params)
    rutas = cn.todos("SELECT codigo FROM rutas WHERE activo = 1 ORDER BY codigo") if tipo == "clientes" else []
    nombres = {}
    if tipo in ("clientes", "personal_ventas"):
        nombres = {r["codigo"]: r["nombre"] for r in cn.todos("SELECT codigo, nombre FROM personal_ventas")}
    paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)
    return render_template("maestros/lista.html", tipo=tipo, ent=ent, cols=cols, filas=filas, total=total,
                           pagina=pagina, paginas=paginas, q=q, estado=estado, ruta=ruta, rutas=rutas,
                           nombres=nombres, entidades=ENTIDADES)


TABLAS_MOTIVOS = {
    "averia": ("motivos_averia", "Motivos de avería", "que la ruta puede elegir al registrar una avería"),
    "devolucion": ("motivos_devolucion", "Motivos de devolución", "que se eligen al crear una alerta de devolución"),
}


@bp.route("/motivos", methods=["GET", "POST"])
@bp.route("/motivos/<clase>", methods=["GET", "POST"])
@requiere("cargas")
def motivos(clase="averia"):
    tabla, titulo, descripcion = TABLAS_MOTIVOS.get(clase) or abort(404)
    cn = db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "agregar":
            nombre = request.form.get("nombre", "").strip()[:120]
            if not nombre:
                flash("Escribe el motivo.", "error")
            elif cn.uno(f"SELECT id FROM {tabla} WHERE LOWER(nombre) = ?", (nombre.lower(),)):
                flash("Ese motivo ya existe.", "error")
            else:
                orden = cn.valor(f"SELECT COALESCE(MAX(orden), 0) + 1 AS n FROM {tabla}", (), 1)
                cn.ejecutar(f"INSERT INTO {tabla} (nombre, orden) VALUES (?, ?)", (nombre, orden))
                registrar("Agregó motivo", tabla, nombre)
                flash("Motivo agregado.", "ok")
        elif accion == "alternar":
            m = cn.uno(f"SELECT * FROM {tabla} WHERE id = ?", (request.form.get("id"),)) or abort(404)
            cn.ejecutar(f"UPDATE {tabla} SET activo = ? WHERE id = ?", (0 if m["activo"] else 1, m["id"]))
            registrar("Desactivó motivo" if m["activo"] else "Activó motivo", tabla, m["nombre"])
        cn.commit()
        return redirect(url_for("maestros.motivos", clase=clase))
    lista_motivos = cn.todos(f"SELECT * FROM {tabla} ORDER BY activo DESC, orden")
    return render_template("maestros/motivos.html", motivos=lista_motivos, entidades=ENTIDADES, clase=clase,
                           titulo=titulo, descripcion=descripcion, clases=TABLAS_MOTIVOS)
