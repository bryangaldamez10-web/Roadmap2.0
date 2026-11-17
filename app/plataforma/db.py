"""Capa de base de datos: SQLite en local y PostgreSQL en producción (Railway / Azure).

Todas las consultas se escriben con marcadores "?"; para PostgreSQL se convierten a "%s".
"""
import os
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app, g

TZ = ZoneInfo("America/El_Salvador")
ESQUEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def ahora():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def hoy():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _url():
    url = current_app.config["DATABASE_URL"]
    # Railway entrega "postgres://"; psycopg acepta ambos, normalizamos.
    return url.replace("postgres://", "postgresql://", 1)


def es_postgres():
    return _url().startswith("postgresql://")


class Conexion:
    def __init__(self):
        self.pg = es_postgres()
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.cn = psycopg.connect(_url(), row_factory=dict_row)
        else:
            ruta = _url().replace("sqlite:///", "", 1)
            os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
            self.cn = sqlite3.connect(ruta)
            self.cn.row_factory = sqlite3.Row
            self.cn.execute("PRAGMA foreign_keys = ON")

    def _sql(self, sql):
        if self.pg:
            sql = sql.replace("%", "%%").replace("?", "%s")
        return sql

    def _cur(self, sql, params=()):
        cur = self.cn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur

    def todos(self, sql, params=()):
        return [dict(r) for r in self._cur(sql, params).fetchall()]

    def uno(self, sql, params=()):
        r = self._cur(sql, params).fetchone()
        return dict(r) if r else None

    def valor(self, sql, params=(), defecto=None):
        r = self.uno(sql, params)
        return list(r.values())[0] if r else defecto

    def ejecutar(self, sql, params=()):
        return self._cur(sql, params).rowcount

    def insertar(self, sql, params=()):
        """INSERT … y devuelve el id generado (la consulta no debe traer RETURNING)."""
        r = self._cur(sql + " RETURNING id", params).fetchone()
        return r["id"] if self.pg else r[0]

    def varios(self, sql, filas):
        cur = self.cn.cursor()
        cur.executemany(self._sql(sql), [tuple(f) for f in filas])

    def commit(self):
        self.cn.commit()

    def rollback(self):
        self.cn.rollback()

    def cerrar(self):
        self.cn.close()


def db():
    if "db" not in g:
        g.db = Conexion()
    return g.db


def cerrar_db(_exc=None):
    cn = g.pop("db", None)
    if cn is not None:
        cn.cerrar()


def crear_esquema():
    cn = db()
    with open(ESQUEMA, encoding="utf-8") as f:
        sql = f.read()
    if cn.pg:
        sql = sql.replace("{PK}", "SERIAL PRIMARY KEY").replace("{BLOB}", "BYTEA")
    else:
        sql = sql.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{BLOB}", "BLOB")
    for sentencia in [s.strip() for s in sql.split(";") if s.strip()]:
        cn.cn.cursor().execute(sentencia)
    cn.commit()
    migrar(cn)


# Columnas agregadas después de la primera versión: (tabla, columna, tipo)
COLUMNAS_NUEVAS = [
    ("alertas", "ordenes", "TEXT"),
    ("alertas", "planificacion_id", "INTEGER"),
]


def columnas(cn, tabla):
    if cn.pg:
        filas = cn.todos("SELECT column_name AS c FROM information_schema.columns WHERE table_name = ?", (tabla,))
        return {f["c"] for f in filas}
    return {f["name"] for f in cn.todos(f"PRAGMA table_info({tabla})")}


def migrar(cn):
    """Agrega columnas nuevas a bases creadas con versiones anteriores, sin perder datos."""
    for tabla, col, tipo in COLUMNAS_NUEVAS:
        if col not in columnas(cn, tabla):
            cn.cn.cursor().execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
    cn.commit()


def registrar(accion, entidad="", detalle="", usuario=None):
    """Bitácora: quién hizo qué y cuándo."""
    from flask import session
    usuario = usuario or session.get("usuario", "sistema")
    db().ejecutar(
        "INSERT INTO bitacora (creado, usuario, accion, entidad, detalle) VALUES (?, ?, ?, ?, ?)",
        (ahora(), usuario, accion, entidad, str(detalle)[:1000]),
    )


def normalizar(texto):
    """Minúsculas, sin tildes ni espacios dobles: para comparar encabezados y búsquedas."""
    import unicodedata
    t = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
