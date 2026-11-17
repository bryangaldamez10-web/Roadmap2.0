"""Pruebas de la fase 1. Ejecutar desde la carpeta app/:  python -m pytest -q   (o  python tests/test_plataforma.py)"""
import base64
import io
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openpyxl import Workbook, load_workbook  # noqa: E402

from plataforma import create_app  # noqa: E402
from plataforma import db as dbmod  # noqa: E402
from plataforma.datos_base import cargar_demo  # noqa: E402

CLAVE = "Demo-2026"


def nueva_app():
    tmp = tempfile.mkdtemp()
    app = create_app({"DATABASE_URL": "sqlite:///" + os.path.join(tmp, "t.db"), "TESTING": True})
    with app.app_context():
        dbmod.crear_esquema()
        cargar_demo()
    return app


def csrf(cliente, url="/login"):
    html = cliente.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else ""


def entrar(app, usuario):
    c = app.test_client()
    r = c.post("/login", data={"usuario": usuario, "clave": CLAVE, "csrf": csrf(c)})
    assert r.status_code == 302, f"login de {usuario} falló"
    return c


def excel(filas):
    wb = Workbook()
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_login_y_bloqueo():
    app = nueva_app()
    c = app.test_client()
    assert c.get("/").status_code == 302  # sin sesión → login
    t = csrf(c)
    assert c.post("/login", data={"usuario": "admin.demo", "clave": "mala", "csrf": t}).status_code == 401
    assert c.post("/login", data={"usuario": "admin.demo", "clave": CLAVE}).status_code == 400  # sin CSRF
    for _ in range(4):
        c.post("/login", data={"usuario": "admin.demo", "clave": "mala", "csrf": t})
    r = c.post("/login", data={"usuario": "admin.demo", "clave": CLAVE, "csrf": t})
    assert r.status_code == 429  # bloqueado tras 5 intentos


def test_permisos_por_rol():
    app = nueva_app()
    ruta = entrar(app, "ruta.ds0099")
    assert ruta.get("/averias/nueva").status_code == 200
    for url in ("/usuarios/", "/cargas/", "/maestros/clientes", "/averias/exportar", "/usuarios/bitacora"):
        assert ruta.get(url).status_code == 403, url
    ventas = entrar(app, "ventas.demo")
    assert ventas.get("/averias/nueva").status_code == 403
    validador = entrar(app, "validador.demo")
    html = validador.get("/maestros/clientes").get_data(as_text=True)
    assert "6000-" not in html, "el validador no debe ver teléfonos de clientes"
    sup = entrar(app, "supervisor.demo")
    assert "6000-" in sup.get("/maestros/clientes").get_data(as_text=True)
    assert sup.get("/usuarios/").status_code == 403


def test_ruta_solo_ve_su_ruta_y_registra():
    app = nueva_app()
    c = entrar(app, "ruta.ds0099")
    html = c.get("/averias/").get_data(as_text=True)
    rutas = set(re.findall(r"<b>(DS\d{4})</b>", html))
    assert rutas <= {"DS0099"}, rutas
    with app.app_context():
        sku = dbmod.db().uno("SELECT * FROM skus WHERE unidades_por_caja = 24 LIMIT 1")
        hoy = dbmod.hoy()
    foto = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 100).decode()
    t = csrf(c, "/averias/nueva")
    datos = {"csrf": t, "fecha_jornada": hoy, "ruta": "DS0012", "reportado_por": "Prueba", "sku_id": sku["id"],
             "unidad": "Unidades", "cantidad": "12", "motivo": "Huecos"}
    assert c.post("/averias/nueva", data=datos).status_code == 400, "sin foto no se registra"
    datos["foto_b64"] = [foto, foto]
    r = c.post("/averias/nueva", data=datos)
    assert r.status_code == 302
    with app.app_context():
        a = dbmod.db().uno("SELECT * FROM averias ORDER BY id DESC LIMIT 1")
    assert a["ruta_codigo"] == "DS0099", "la ruta del conductor se fuerza, no la del formulario"
    assert a["cajas_equiv"] == 0.5 and a["codsap"] == sku["codsap"]
    with app.app_context():
        fids = [r["id"] for r in dbmod.db().todos("SELECT id FROM averia_fotos WHERE averia_id = ?", (a["id"],))]
        ajena = dbmod.db().valor("SELECT f.id FROM averia_fotos f JOIN averias v ON v.id = f.averia_id "
                                 "WHERE v.ruta_codigo <> 'DS0099' LIMIT 1")
    assert len(fids) == 2 and c.get(f"/averias/foto/{fids[0]}").status_code == 200
    assert c.get(f"/averias/foto/{ajena}").status_code == 403, "no ve fotos de otras rutas"
    # una avería de otra ruta no es visible para el conductor
    with app.app_context():
        otra = dbmod.db().valor("SELECT id FROM averias WHERE ruta_codigo <> 'DS0099' LIMIT 1")
    assert c.get(f"/averias/registrada/{otra}").status_code == 403


def test_validacion_de_averias():
    app = nueva_app()
    c = entrar(app, "validador.demo")
    with app.app_context():
        cn = dbmod.db()
        aid = cn.valor("SELECT id FROM averias v WHERE estado = 'Pendiente' AND EXISTS "
                       "(SELECT 1 FROM averia_fotos f WHERE f.averia_id = v.id) LIMIT 1")
        sin_foto = cn.valor("SELECT id FROM averias v WHERE estado <> 'Validado' AND NOT EXISTS "
                            "(SELECT 1 FROM averia_fotos f WHERE f.averia_id = v.id) LIMIT 1")
    t = csrf(c, "/averias/")
    c.post(f"/averias/{sin_foto}/estado", data={"csrf": t, "estado": "Validado"})
    with app.app_context():
        assert dbmod.db().valor("SELECT estado FROM averias WHERE id = ?", (sin_foto,)) != "Validado", "no se valida sin foto"
    c.post(f"/averias/{aid}/estado", data={"csrf": t, "estado": "Rechazado", "observacion": ""})
    with app.app_context():
        assert dbmod.db().valor("SELECT estado FROM averias WHERE id = ?", (aid,)) == "Pendiente"
    c.post(f"/averias/{aid}/estado", data={"csrf": t, "estado": "Validado", "observacion": "ok"})
    with app.app_context():
        a = dbmod.db().uno("SELECT * FROM averias WHERE id = ?", (aid,))
    assert a["estado"] == "Validado" and a["validado_por"] == "Validador Demo"
    r = c.get("/averias/exportar?desde=2020-01-01&hasta=2099-01-01")
    ws = load_workbook(io.BytesIO(r.data)).active
    assert ws.max_row == 41 and ws["A1"].value == "Folio"


def test_carga_de_clientes_con_vista_previa():
    app = nueva_app()
    c = entrar(app, "supervisor.demo")
    archivo = excel([
        ["Reporte de clientes"],
        ["Cod Cliente", "Nombre Cliente", "Municipio", "Teléfono", "Lat", "Long", "Ruta", "Cod BDR"],
        [13151328, "TEXACO PRUEBA", "Nuevo Cuscatlán", 60024029, 13.655772, -89.2787249, "DS0099", "SP0001"],
        ["90000001", "Nombre actualizado", "X", None, None, None, "DS0051", "SP0002"],
        [None, "Sin código", None, None, None, None, None, None],
        ["555", "Coordenada mala", None, None, 200, -89, "DS9999", None],
    ])
    t = csrf(c, "/cargas/")
    r = c.post("/cargas/", data={"csrf": t, "tipo": "clientes", "archivo": (archivo, "clientes.xlsx")},
               content_type="multipart/form-data")
    assert r.status_code == 302 and "/vista-previa/" in r.location
    html = c.get(r.location).get_data(as_text=True)
    assert "Filas con error" in html and "latitud fuera de rango" in html
    c.post(r.location, data={"csrf": t, "desactivar_faltantes": "1"})
    with app.app_context():
        cn = dbmod.db()
        nuevo = cn.uno("SELECT * FROM clientes WHERE codigo = '13151328'")
        assert nuevo["telefono"] == "60024029" and nuevo["ruta_codigo"] == "DS0099" and abs(nuevo["latitud"] - 13.655772) < 1e-6
        assert cn.valor("SELECT nombre FROM clientes WHERE codigo = '90000001'") == "Nombre actualizado"
        assert cn.valor("SELECT COUNT(*) AS n FROM clientes WHERE activo = 1") == 2
        assert cn.valor("SELECT COUNT(*) AS n FROM cargas") == 1


def test_carga_skus_desde_archivo_original():
    """El archivo de SKUs del almacén (NOMBRE, CODSAP, NUMSUU…) se reconoce tal cual."""
    app = nueva_app()
    c = entrar(app, "admin.demo")
    archivo = excel([["NOMBRE", "CODSAP", "NUMSUU", "DIVISION"],
                     ["SKU NUEVO PRUEBA 12U", 99999, 12, "CERVEZA"], ["SIN CODIGO", None, 1, "OTROS"]])
    t = csrf(c, "/cargas/")
    r = c.post("/cargas/", data={"csrf": t, "tipo": "skus", "archivo": (archivo, "skus.xlsx")},
               content_type="multipart/form-data")
    c.post(r.location, data={"csrf": t})
    with app.app_context():
        s = dbmod.db().uno("SELECT * FROM skus WHERE codsap = '99999'")
    assert s and s["unidades_por_caja"] == 12 and s["categoria"] == "CERVEZA"


def test_usuarios_y_cambio_de_clave():
    app = nueva_app()
    adm = entrar(app, "admin.demo")
    t = csrf(adm, "/usuarios/nuevo")
    r = adm.post("/usuarios/nuevo", data={"csrf": t, "usuario": "ruta.ds0012", "nombre": "Conductor Nuevo",
                                           "rol": "ruta", "ruta_codigo": "DS0012"})
    clave = re.search(r'font-size:20px">([^<]+)<', r.get_data(as_text=True)).group(1)
    c = app.test_client()
    c.post("/login", data={"usuario": "ruta.ds0012", "clave": clave, "csrf": csrf(c)})
    assert "/cambiar-clave" in c.get("/averias/nueva").location  # obligado a cambiarla
    t2 = csrf(c, "/cambiar-clave")
    c.post("/cambiar-clave", data={"csrf": t2, "actual": clave, "nueva": "NuevaClave1", "confirmar": "NuevaClave1"})
    assert c.get("/averias/nueva").status_code == 200
    with app.app_context():
        assert dbmod.db().valor("SELECT COUNT(*) AS n FROM bitacora WHERE accion = 'Creó usuario'") == 1


def test_alertas_permisos():
    app = nueva_app()
    for u in ("admin.demo", "supervisor.demo"):
        c = entrar(app, u)
        assert c.get("/alertas/").status_code == 200, u
        assert c.get("/alertas/nueva").status_code == 200, u
        assert "Alertas" in c.get("/").get_data(as_text=True)
    for u in ("validador.demo", "ventas.demo"):
        c = entrar(app, u)
        assert c.get("/alertas/").status_code == 403, u
        assert c.get("/alertas/nueva").status_code == 403, u


def test_alerta_cruce_y_whatsapp():
    app = nueva_app()
    with app.app_context():
        cn = dbmod.db()
        cli = cn.uno("SELECT * FROM clientes WHERE ruta_codigo = 'DS0099' LIMIT 1")
        otro = cn.uno("SELECT * FROM clientes WHERE ruta_codigo <> 'DS0099' LIMIT 1")
        bdr = cn.uno("SELECT * FROM personal_ventas WHERE codigo = ?", (cli["bdr_codigo"],))
    sup = entrar(app, "supervisor.demo")
    d = sup.get(f"/alertas/cliente/{cli['codigo']}").get_json()
    assert d["ok"] and d["bdr"]["codigo"] == cli["bdr_codigo"] and d["supervisor"]["codigo"] == cli["supervisor_codigo"]
    assert sup.get("/alertas/cliente/NOEXISTE").status_code == 404
    t = csrf(sup, "/alertas/nueva")
    r = sup.post("/alertas/nueva", data={"csrf": t, "cliente": cli["codigo"], "tipo_pedido": "B2B", "cajas": "55",
                                         "cajas_riesgo": "1", "hectolitros": "5.757", "hubo_comunicacion": "0",
                                         "motivo": "NEN - Mal facturado: error de SKU",
                                         "comentario": "Viene golden transparente", "latitud": "13.655772",
                                         "longitud": "-89.2787249"})
    assert r.status_code == 302
    html = sup.get(r.location).get_data(as_text=True)
    tel = "503" + "".join(ch for ch in bdr["telefono"] if ch.isdigit())
    assert f"https://wa.me/{tel}?text=" in html, "botón directo al BDR"
    assert "Hubo comunicación con ventas:* NO" in html and "google.com/maps?q=13.655772" in html
    # la ruta solo ve clientes de su ruta
    ruta = entrar(app, "ruta.ds0099")
    assert ruta.get(f"/alertas/cliente/{otro['codigo']}").status_code == 403
    assert ruta.get(f"/alertas/cliente/{cli['codigo']}").status_code == 200
    # gestión: solo admin/supervisor
    with app.app_context():
        aid = dbmod.db().valor("SELECT id FROM alertas ORDER BY id DESC LIMIT 1")
    t2 = csrf(ruta, "/alertas/nueva")
    assert ruta.post(f"/alertas/{aid}/estado", data={"csrf": t2, "estado": "Evitada"}).status_code == 403
    sup.post(f"/alertas/{aid}/estado", data={"csrf": t, "estado": "Evitada", "resultado": "BDR cambió el pedido"})
    with app.app_context():
        a = dbmod.db().uno("SELECT * FROM alertas WHERE id = ?", (aid,))
    assert a["estado"] == "Evitada" and a["cajas_devueltas"] == 0 and a["gestionado_por"] == "Supervisor Demo"


PLAN_TSV = """FECHA\tNOMCD\tPESO\tNOM_ROUTSET\tCLIENTE\tNOM_REPARTO\tNOM_NEGOCIO\tCIUDAD\tDIRECCION\tCOD_VEHI\tORDENES\tCAJAS\tRUTAS\tLlegada\tSalida
10/11/2026\tMAZ SV Soyapango\t133.36\tPRIMARIO\t14507533\tNA\tPaisa Mini Super\tSANTA TECLA\tAv Sn Isidro Polig D8 No 2\tSV-0749\t1363963495, 1363963496\t12.00\tDS0099\t10/11/2026 08:05:00\t10/11/2026 08:15:00
10/11/2026\tMAZ SV Soyapango\t247.27\tPRIMARIO\t90000004\tNA\tPUPUSERIA NATHALY\tSANTA TECLA\tAV.SAN ISIDRO\tSV-0749\t1363963834\t18.00\tDS0099\t10/11/2026 08:16:00\t10/11/2026 08:29:00
10/11/2026\tMAZ SV Soyapango\t42.56\tPRIMARIO\t13133582\tNA\tPUPUSERIA LA CHIQUITA\tSANTA TECLA\tAV.SAN ISIDRO\tSV-0749\t1363963470\t2.00\tDS0012\t10/11/2026 08:30:00\t10/11/2026 08:37:00
"""


def test_planificacion_y_alerta_desde_parada():
    app = nueva_app()
    sup = entrar(app, "supervisor.demo")
    t = csrf(sup, "/cargas/")
    r = sup.post("/cargas/", data={"csrf": t, "tipo": "planificacion",
                                   "archivo": (io.BytesIO(PLAN_TSV.encode("utf-8")), "planificacion.txt")},
                 content_type="multipart/form-data")
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    r = sup.post(r.location, data={"csrf": t})
    assert "planificacion" in r.location
    with app.app_context():
        cn = dbmod.db()
        p = cn.uno("SELECT * FROM planificacion WHERE cliente_codigo = '14507533'")
        assert p["fecha"] == "2026-11-10" and p["cajas"] == 12 and p["peso"] == 133.36
        assert p["ordenes"] == "1363963495, 1363963496" and p["llegada"] == "2026-11-10 08:05" and p["vehiculo"] == "SV-0749"
    html = sup.get("/planificacion/?fecha=2026-11-10").get_data(as_text=True)
    assert "DS0099" in html and "DS0012" in html
    # el conductor ve su ruta, no la de otro
    ruta = entrar(app, "ruta.ds0099")
    assert ruta.get("/planificacion/ruta/DS0099?fecha=2026-11-10").status_code == 200
    assert ruta.get("/planificacion/ruta/DS0012?fecha=2026-11-10").status_code == 403
    with app.app_context():
        otra = dbmod.db().valor("SELECT id FROM planificacion WHERE ruta_codigo = 'DS0012' AND fecha = '2026-11-10'")
    assert ruta.get(f"/alertas/nueva?parada={otra}").status_code == 403
    # alerta desde la parada: toma cliente, cajas y órdenes reales, aunque el cliente no esté en el maestro
    html = ruta.get(f"/alertas/nueva?parada={p['id']}").get_data(as_text=True)
    assert "1363963495, 1363963496" in html and 'value="12"' in html
    t2 = csrf(ruta, "/alertas/nueva")
    r = ruta.post("/alertas/nueva", data={"csrf": t2, "planificacion_id": p["id"], "cliente": "OTRO", "cajas": "12",
                                          "cajas_riesgo": "3", "hubo_comunicacion": "1", "tipo_pedido": "B2B",
                                          "motivo": "Cliente cerrado"})
    assert r.status_code == 302
    with app.app_context():
        a = dbmod.db().uno("SELECT * FROM alertas ORDER BY id DESC LIMIT 1")
    assert a["cliente_codigo"] == "14507533" and a["planificacion_id"] == p["id"] and a["fecha"] == "2026-11-10"
    assert a["ordenes"] == "1363963495, 1363963496" and a["cliente_nombre"] == "Paisa Mini Super"
    assert "Órdenes:* 1363963495" in ruta.get(r.location).get_data(as_text=True)
    assert "Alerta AL-" in ruta.get("/planificacion/ruta/DS0099?fecha=2026-11-10").get_data(as_text=True)
    # recargar el día sin una parada la deja inactiva (no se borra)
    menos = "\n".join(l for l in PLAN_TSV.splitlines() if "90000004" not in l)
    r = sup.post("/cargas/", data={"csrf": t, "tipo": "planificacion",
                                   "archivo": (io.BytesIO(menos.encode()), "plan2.csv")}, content_type="multipart/form-data")
    sup.post(r.location, data={"csrf": t})
    with app.app_context():
        assert dbmod.db().valor("SELECT activo FROM planificacion WHERE cliente_codigo = '90000004' AND fecha = '2026-11-10'") == 0


if __name__ == "__main__":
    pruebas = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for p in pruebas:
        p()
        print("ok ", p.__name__)
    print(f"{len(pruebas)} pruebas superadas")
