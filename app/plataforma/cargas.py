"""Carga de maestros desde Excel/CSV: lectura flexible de encabezados, validación, vista previa y confirmación."""
import csv
import io
from datetime import date, datetime
import json
import re
import secrets

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, send_file,
                   url_for)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from .auth import requiere
from .db import ahora, db, normalizar, registrar
from .entidades import ENTIDADES

bp = Blueprint("cargas", __name__, url_prefix="/cargas")
MAX_FILAS = 50000


# ---------- Lectura de archivos ----------

def leer_archivo(archivo):
    nombre = (archivo.filename or "").lower()
    contenido = archivo.read()
    if nombre.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif nombre.endswith((".csv", ".txt")):
        for cod in ("utf-8-sig", "latin-1"):
            try:
                texto = contenido.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialecto = csv.Sniffer().sniff(texto[:5000], delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel
        filas = [r for r in csv.reader(io.StringIO(texto), dialecto)]
    else:
        raise ValueError("Formato no soportado. Sube un archivo .xlsx o .csv.")
    filas = [f for f in filas if any(v not in (None, "") for v in f)]
    if not filas:
        raise ValueError("El archivo está vacío.")
    return filas


def ubicar_encabezados(filas, ent):
    """Busca en las primeras 10 filas la que mejor coincide con los alias y devuelve (índice, mapa campo→columna)."""
    mejor = (-1, {}, 0)
    for i, fila in enumerate(filas[:10]):
        norm = [normalizar(v) for v in fila]
        mapa = {}
        for col in ent["columnas"]:
            alias = [normalizar(a) for a in [col["campo"], col["titulo"]] + col["alias"]]
            for a in alias:  # el primer alias que coincida gana (orden de prioridad)
                if a in norm and norm.index(a) not in mapa.values():
                    mapa[col["campo"]] = norm.index(a)
                    break
        puntaje = len(mapa) + sum(2 for c in ent["columnas"] if c.get("requerido") and c["campo"] in mapa)
        if puntaje > mejor[2]:
            mejor = (i, mapa, puntaje)
    return mejor[0], mejor[1]


# ---------- Conversión y validación ----------

def convertir(valor, tipo):
    """Devuelve (valor_convertido, error)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None, None
    if tipo == "codigo":
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        v = str(valor).strip()
        v = re.sub(r"\.0$", "", v)
        return v.upper(), None
    if tipo == "texto":
        return re.sub(r"\s+", " ", str(valor)).strip()[:250], None
    if tipo == "telefono":
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        v = re.sub(r"[^\d+]", "", str(valor))
        return (v, None) if len(re.sub(r"\D", "", v)) >= 7 else (None, None)
    if tipo == "entero":
        try:
            n = float(str(valor).replace(",", "."))
            return int(n), None
        except ValueError:
            return None, f"número no válido ({valor})"
    if tipo in ("fecha", "fechahora"):
        if isinstance(valor, datetime):
            return valor.strftime("%Y-%m-%d" if tipo == "fecha" else "%Y-%m-%d %H:%M"), None
        if isinstance(valor, date):
            return valor.strftime("%Y-%m-%d") + ("" if tipo == "fecha" else " 00:00"), None
        txt = str(valor).strip()
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                d = datetime.strptime(txt, fmt)
                return d.strftime("%Y-%m-%d" if tipo == "fecha" else "%Y-%m-%d %H:%M"), None
            except ValueError:
                continue
        return None, f"fecha no válida ({valor})"
    if tipo in ("decimal", "latitud", "longitud"):
        try:
            n = float(str(valor).replace(",", "."))
        except ValueError:
            return None, f"número no válido ({valor})"
        if tipo == "latitud" and not -90 <= n <= 90:
            return None, f"latitud fuera de rango ({valor})"
        if tipo == "longitud" and not -180 <= n <= 180:
            return None, f"longitud fuera de rango ({valor})"
        return n, None
    return valor, None


def procesar(filas, ent, tipo):
    idx, mapa = ubicar_encabezados(filas, ent)
    faltan = [c["titulo"] for c in ent["columnas"] if c.get("requerido") and c["campo"] not in mapa]
    if faltan:
        raise ValueError("No encontré estas columnas obligatorias: " + ", ".join(faltan) +
                         ". Revisa los encabezados o descarga la plantilla.")
    datos = filas[idx + 1:]
    if len(datos) > MAX_FILAS:
        raise ValueError(f"El archivo tiene más de {MAX_FILAS:,} filas.")

    cn = db()
    refs = {}
    for c in ent["columnas"]:
        if c.get("ref") and c["campo"] in mapa:
            refs[c["campo"]] = {r["codigo"] for r in cn.todos(f"SELECT codigo FROM {c['ref']}")}

    validas, errores, avisos, vistos = [], [], [], set()
    for n, fila in enumerate(datos, start=idx + 2):
        reg, errs = {}, []
        for c in ent["columnas"]:
            if c["campo"] not in mapa:
                continue
            j = mapa[c["campo"]]
            valor, err = convertir(fila[j] if j < len(fila) else None, c["tipo"])
            if err:
                errs.append(f"{c['titulo']}: {err}")
            elif valor is None and c.get("requerido"):
                errs.append(f"{c['titulo']} vacío")
            reg[c["campo"]] = valor
        if errs:
            errores.append({"fila": n, "detalle": "; ".join(errs)})
            continue
        clave = tuple(reg[k] for k in ent["clave"])
        if clave in vistos:
            avisos.append({"fila": n, "detalle": f"repetido en el archivo ({' / '.join(map(str, clave))}); se usa la última fila"})
            validas = [v for v in validas if tuple(v[k] for k in ent["clave"]) != clave]
        vistos.add(clave)
        for campo, existentes in refs.items():
            if reg.get(campo) and reg[campo] not in existentes:
                avisos.append({"fila": n, "detalle": f"{campo.replace('_codigo', '').upper()} {reg[campo]} no está en los maestros"})
        validas.append(reg)

    claves_existentes = {tuple(r[k] for k in ent["clave"])
                         for r in cn.todos(f"SELECT {', '.join(ent['clave'])} FROM {ent['tabla']}")}
    nuevas = sum(1 for v in validas if tuple(v[k] for k in ent["clave"]) not in claves_existentes)
    return {
        "campos": [c["campo"] for c in ent["columnas"] if c["campo"] in mapa],
        "no_encontradas": [c["titulo"] for c in ent["columnas"] if c["campo"] not in mapa],
        "validas": validas, "errores": errores, "avisos": avisos,
        "nuevas": nuevas, "actualizadas": len(validas) - nuevas,
        "fila_encabezado": idx + 1,
    }


def aplicar(tipo, res, desactivar_faltantes):
    ent = ENTIDADES[tipo]
    cn = db()
    campos = res["campos"]
    tiene_actualizado = tipo != "skus"
    columnas = campos + ["activo"] + (["actualizado"] if tiene_actualizado else [])
    actualizar = [c for c in columnas if c not in ent["clave"]]
    sql = (f"INSERT INTO {ent['tabla']} ({', '.join(columnas)}) VALUES ({', '.join('?' for _ in columnas)}) "
           f"ON CONFLICT ({', '.join(ent['clave'])}) DO UPDATE SET "
           + ", ".join(f"{c} = excluded.{c}" for c in actualizar))
    marca = ahora()
    defectos = {"unidades_por_caja": 1}
    filas = [[v.get(c) if v.get(c) is not None else defectos.get(c) for c in campos]
             + [1] + ([marca] if tiene_actualizado else []) for v in res["validas"]]
    cn.varios(sql, filas)

    desactivadas = 0
    if ent.get("reemplazar_dia") and res["validas"]:
        # Las paradas de ese día y ruta que ya no vienen en el archivo quedan inactivas (no se borran).
        pares = {(v["fecha"], v["ruta_codigo"]) for v in res["validas"]}
        claves = {tuple(v[k] for k in ent["clave"]) for v in res["validas"]}
        quitar = []
        for fecha, ruta in pares:
            for r in cn.todos("SELECT cliente_codigo FROM planificacion WHERE fecha = ? AND ruta_codigo = ? AND activo = 1",
                              (fecha, ruta)):
                if (fecha, ruta, r["cliente_codigo"]) not in claves:
                    quitar.append((fecha, ruta, r["cliente_codigo"]))
        cn.varios("UPDATE planificacion SET activo = 0 WHERE fecha = ? AND ruta_codigo = ? AND cliente_codigo = ?", quitar)
        desactivadas = len(quitar)
    if desactivar_faltantes and ent.get("desactivar_faltantes") and res["validas"]:
        claves = {tuple(v[k] for k in ent["clave"]) for v in res["validas"]}
        existentes = cn.todos(f"SELECT {', '.join(ent['clave'])} FROM {ent['tabla']} WHERE activo = 1")
        quitar = [tuple(r[k] for k in ent["clave"]) for r in existentes if tuple(r[k] for k in ent["clave"]) not in claves]
        cond = " AND ".join(f"{k} = ?" for k in ent["clave"])
        cn.varios(f"UPDATE {ent['tabla']} SET activo = 0 WHERE {cond}", quitar)
        desactivadas = len(quitar)
    return desactivadas


# ---------- Vistas ----------

@bp.route("/", methods=["GET", "POST"])
@requiere("cargas")
def inicio():
    cn = db()
    if request.method == "POST":
        tipo = request.form.get("tipo")
        ent = ENTIDADES.get(tipo)
        archivo = request.files.get("archivo")
        if not ent or not archivo or not archivo.filename:
            flash("Elige qué vas a cargar y el archivo.", "error")
            return redirect(url_for("cargas.inicio"))
        try:
            res = procesar(leer_archivo(archivo), ent, tipo)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("cargas.inicio", tipo=tipo))
        except Exception:  # archivo dañado o protegido
            flash("No pude leer el archivo. Verifica que no esté protegido con contraseña ni dañado.", "error")
            return redirect(url_for("cargas.inicio", tipo=tipo))
        token = secrets.token_urlsafe(16)
        cn.ejecutar("DELETE FROM cargas_pendientes WHERE creado < ?", (ahora()[:10],))
        cn.ejecutar("INSERT INTO cargas_pendientes (token, tipo, archivo, usuario, datos, creado) VALUES (?, ?, ?, ?, ?, ?)",
                    (token, tipo, archivo.filename[:200], g.usuario["usuario"], json.dumps(res, default=str), ahora()))
        cn.commit()
        return redirect(url_for("cargas.vista_previa", token=token))

    historial = cn.todos("SELECT * FROM cargas ORDER BY id DESC LIMIT 20")
    return render_template("cargas/inicio.html", entidades=ENTIDADES, historial=historial,
                           tipo_sel=request.args.get("tipo", ""))


@bp.route("/vista-previa/<token>", methods=["GET", "POST"])
@requiere("cargas")
def vista_previa(token):
    cn = db()
    p = cn.uno("SELECT * FROM cargas_pendientes WHERE token = ? AND usuario = ?", (token, g.usuario["usuario"]))
    if not p:
        flash("Esta carga ya no está disponible. Sube el archivo de nuevo.", "error")
        return redirect(url_for("cargas.inicio"))
    res = json.loads(p["datos"])
    ent = ENTIDADES[p["tipo"]]

    if request.method == "POST":
        if not res["validas"]:
            flash("No hay filas válidas para guardar.", "error")
            return redirect(url_for("cargas.vista_previa", token=token))
        desactivar = request.form.get("desactivar_faltantes") == "1"
        try:
            desactivadas = aplicar(p["tipo"], res, desactivar)
            cn.ejecutar("INSERT INTO cargas (tipo, archivo, usuario, creado, filas, nuevas, actualizadas, desactivadas, errores) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (p["tipo"], p["archivo"], g.usuario["usuario"], ahora(), len(res["validas"]) + len(res["errores"]),
                         res["nuevas"], res["actualizadas"], desactivadas, len(res["errores"])))
            cn.ejecutar("DELETE FROM cargas_pendientes WHERE token = ?", (token,))
            registrar("Carga de " + ent["titulo"].lower(), p["tipo"],
                      f"{p['archivo']}: {res['nuevas']} nuevas, {res['actualizadas']} actualizadas, "
                      f"{desactivadas} desactivadas, {len(res['errores'])} con error")
            cn.commit()
        except Exception as e:
            cn.rollback()
            flash(f"No se pudo guardar la carga: {e}", "error")
            return redirect(url_for("cargas.vista_previa", token=token))
        msg = f"{ent['titulo']}: {res['nuevas']} nuevos y {res['actualizadas']} actualizados"
        if desactivadas:
            msg += f", {desactivadas} marcados como inactivos"
        flash(msg + ".", "ok")
        if p["tipo"] == "planificacion":
            return redirect(url_for("planificacion.resumen", fecha=max(v["fecha"] for v in res["validas"])))
        return redirect(url_for("maestros.lista", tipo=p["tipo"]))

    cols = [c for c in ent["columnas"] if c["campo"] in res["campos"]]
    return render_template("cargas/vista_previa.html", p=p, res=res, ent=ent, cols=cols,
                           muestra=res["validas"][:15])


@bp.route("/plantilla/<tipo>")
@requiere("cargas")
def plantilla(tipo):
    ent = ENTIDADES.get(tipo) or abort(404)
    wb = Workbook()
    ws = wb.active
    ws.title = ent["titulo"][:30]
    ws.append([c["titulo"] for c in ent["columnas"]])
    ws.append(ent["ejemplo"])
    for celda in ws[1]:
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="FDE68A")
    for i, c in enumerate(ent["columnas"], start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(14, len(c["titulo"]) + 4)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"plantilla_{tipo}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
