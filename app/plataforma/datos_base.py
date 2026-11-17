"""Datos iniciales: motivos oficiales, catálogo de SKUs y datos FICTICIOS de demostración."""
import os
import random
from datetime import datetime, timedelta

from openpyxl import load_workbook

from .auth import hash_clave
from .db import TZ, ahora, db

MOTIVOS = [
    "Huecos", "Caja o empaque en mal estado", "Ponchado debidamente sellado", "Desfondada o estallada",
    "Estallada por calor", "Objetos extraños", "Destapada", "Mal coronado o tapado", "Bajo nivel",
]
MOTIVOS_DEVOLUCION = [
    "NEN - Mal facturado: error de SKU", "NEN - Mal facturado: error de cantidad", "Cliente no realizó el pedido",
    "Cliente cerrado", "Cliente sin efectivo", "Cliente sin espacio para recibir", "Pedido duplicado",
    "Producto no requerido por el cliente", "Fuera de horario de recepción", "Otro",
]
CATALOGO = os.path.join(os.path.dirname(__file__), "datos", "catalogo_skus.xlsx")


def cargar_motivos():
    cn = db()
    if not cn.valor("SELECT COUNT(*) AS n FROM motivos_averia"):
        cn.varios("INSERT INTO motivos_averia (nombre, orden) VALUES (?, ?)", [(m, i) for i, m in enumerate(MOTIVOS, 1)])
        cn.commit()


def cargar_motivos_devolucion():
    cn = db()
    if not cn.valor("SELECT COUNT(*) AS n FROM motivos_devolucion"):
        cn.varios("INSERT INTO motivos_devolucion (nombre, orden) VALUES (?, ?)",
                  [(m, i) for i, m in enumerate(MOTIVOS_DEVOLUCION, 1)])
        cn.commit()


def cargar_skus():
    cn = db()
    if cn.valor("SELECT COUNT(*) AS n FROM skus"):
        return 0
    wb = load_workbook(CATALOGO, read_only=True)
    filas = [(str(r[0]), r[1], r[2], int(r[3] or 1)) for r in wb.active.iter_rows(min_row=2, values_only=True) if r[0]]
    cn.varios("INSERT INTO skus (codsap, nombre, categoria, unidades_por_caja) VALUES (?, ?, ?, ?)", filas)
    cn.commit()
    return len(filas)


def cargar_demo():
    """Todo lo que crea esta función es inventado: nombres, teléfonos y clientes no son reales."""
    cn = db()
    cargar_motivos()
    cargar_motivos_devolucion()
    n_skus = cargar_skus()
    if cn.valor("SELECT COUNT(*) AS n FROM rutas"):
        return f"Ya había datos; solo se revisaron motivos y SKUs ({n_skus} SKUs nuevos)."
    rnd = random.Random(2026)
    marca = ahora()

    rutas = ["DS0012", "DS0051", "DS0055", "DS0090", "DS0099"]
    nombres = ["Carlos", "José", "Luis", "Miguel", "Óscar", "Ricardo", "Mario", "Jorge", "Ana", "Karla", "Sofía", "Daniel"]
    apellidos = ["Demo", "Prueba", "Ejemplo", "Ficticio"]
    zonas = {"DS0012": ("Santa Tecla", 13.676, -89.289), "DS0051": ("Soyapango", 13.710, -89.150),
             "DS0055": ("Mejicanos", 13.740, -89.213), "DS0090": ("San Marcos", 13.661, -89.183),
             "DS0099": ("Nuevo Cuscatlán", 13.648, -89.265)}
    cn.varios("INSERT INTO rutas (codigo, nombre, telefono, conductor_nombre, conductor_telefono, actualizado) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              [(r, f"Zona {zonas[r][0]}", f"7000-00{i:02d}", f"{nombres[i]} {apellidos[i % 4]} (ficticio)",
                f"7000-10{i:02d}", marca) for i, r in enumerate(rutas)])

    ventas = [("SV0001", "Jefa de Ventas Demo", "Jefe de ventas", "7500-0001", None),
              ("SV0010", "Supervisora Ventas Norte Demo", "Supervisor de ventas", "7500-0010", "SV0001"),
              ("SV0020", "Supervisor Ventas Sur Demo", "Supervisor de ventas", "7500-0020", "SV0001")]
    for i in range(1, 7):
        ventas.append((f"SP{i:04d}", f"BDR {nombres[i]} {apellidos[i % 4]}", "BDR", f"7600-00{i:02d}",
                       "SV0010" if i <= 3 else "SV0020"))
    cn.varios("INSERT INTO personal_ventas (codigo, nombre, cargo, telefono, jefe_codigo, actualizado) "
              "VALUES (?, ?, ?, ?, ?, ?)", [v + (marca,) for v in ventas])

    giros = ["Tienda", "Abarrotería", "Restaurante", "Gasolinera", "Minisúper", "Comedor", "Depósito"]
    clientes = []
    for i in range(60):
        r = rutas[i % 5]
        zona, lat, lng = zonas[r]
        bdr = f"SP{(i % 6) + 1:04d}"
        clientes.append((str(90000000 + i), f"{rnd.choice(giros)} Demo {i + 1}", zona, f"Calle ficticia {i + 1}",
                         f"6000-{i:04d}", round(lat + rnd.uniform(-0.02, 0.02), 6),
                         round(lng + rnd.uniform(-0.02, 0.02), 6), r, bdr,
                         "SV0010" if int(bdr[2:]) <= 3 else "SV0020", marca))
    cn.varios("INSERT INTO clientes (codigo, nombre, localidad, direccion, telefono, latitud, longitud, ruta_codigo, "
              "bdr_codigo, supervisor_codigo, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", clientes)

    clave = "Demo-2026"
    usuarios = [("admin.demo", "Administrador Demo", "admin", None), ("supervisor.demo", "Supervisor Demo", "supervisor", None),
                ("validador.demo", "Validador Demo", "validador", None), ("ruta.ds0099", "Conductor DS0099 Demo", "ruta", "DS0099"),
                ("ventas.demo", "Ventas Demo", "ventas", None)]
    cn.varios("INSERT INTO usuarios (usuario, nombre, rol, ruta_codigo, password_hash, debe_cambiar, creado) "
              "VALUES (?, ?, ?, ?, ?, 0, ?)", [u + (hash_clave(clave), marca) for u in usuarios])

    skus = cn.todos("SELECT * FROM skus WHERE categoria IN ('CERVEZA', 'CARBONATADOS', 'AGUA') ORDER BY id LIMIT 120")
    hoy_dt = datetime.now(TZ)
    carpeta = os.path.dirname(CATALOGO)
    fotos_demo = [open(os.path.join(carpeta, f"demo_foto_{n}.jpg"), "rb").read() for n in (1, 2)]
    for i in range(40):
        s = rnd.choice(skus)
        unidad = rnd.choice(["Cajas", "Unidades"])
        cant = rnd.randint(1, 6) if unidad == "Cajas" else rnd.randint(1, 30)
        cajas = cant if unidad == "Cajas" else round(cant / (s["unidades_por_caja"] or 1), 3)
        fecha = (hoy_dt - timedelta(days=rnd.randint(0, 6))).strftime("%Y-%m-%d")
        estado = rnd.choice(["Pendiente", "Pendiente", "Validado", "Rechazado"])
        ruta = rnd.choice(rutas)
        aid = cn.insertar(
            "INSERT INTO averias (fecha_jornada, creado, ruta_codigo, reportado_por, codsap, sku_nombre, categoria, cantidad, "
            "unidad, unidades_por_caja, cajas_equiv, motivo, comentario, estado, validado_por, validado_en, observacion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fecha, fecha + " 10:00:00", ruta, f"Conductor {ruta} Demo", s["codsap"], s["nombre"], s["categoria"], cant,
             unidad, s["unidades_por_caja"], cajas, rnd.choice(MOTIVOS), "Dato de demostración", estado,
             None if estado == "Pendiente" else "Validador Demo", None if estado == "Pendiente" else fecha + " 16:00:00",
             "Sin evidencia suficiente" if estado == "Rechazado" else None))
        cn.ejecutar("UPDATE averias SET folio = ? WHERE id = ?", (f"AV-{fecha[2:4]}{fecha[5:7]}{fecha[8:10]}-{aid:05d}", aid))
        if i % 8:  # algunas quedan sin foto para ver cómo se muestran
            ft = fotos_demo[i % 2]
            cn.ejecutar("INSERT INTO averia_fotos (averia_id, creado, foto, tipo, bytes) VALUES (?, ?, ?, 'image/jpeg', ?)",
                        (aid, fecha + " 10:00:00", ft, len(ft)))
    # Planificación de hoy: los clientes de cada ruta en orden de visita
    dia = hoy_dt.strftime("%Y-%m-%d")
    plan = []
    for r in rutas:
        hora = hoy_dt.replace(hour=8, minute=0, second=0, microsecond=0)
        vehiculo = f"SV-0{700 + rutas.index(r)}"
        for n, c in enumerate([c for c in clientes if c[7] == r]):
            cajas = float(rnd.randint(2, 25))
            llegada = hora + timedelta(minutes=n * 14)
            plan.append((dia, r, c[0], c[1].upper(), c[2].upper(), c[3], f"{1363963400 + len(plan)}", cajas,
                         round(cajas * rnd.uniform(9, 14), 2), vehiculo, "MAZ SV Soyapango", "PRIMARIO", "NA",
                         llegada.strftime("%Y-%m-%d %H:%M"), (llegada + timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M"), marca))
    cn.varios("INSERT INTO planificacion (fecha, ruta_codigo, cliente_codigo, nombre_negocio, ciudad, direccion, ordenes, "
              "cajas, peso, vehiculo, centro, tipo_ruteo, reparto, llegada, salida, actualizado) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", plan)

    motivos_dev = [m["nombre"] for m in cn.todos("SELECT nombre FROM motivos_devolucion ORDER BY orden")]
    estados = ["Abierta", "Abierta", "Evitada", "Evitada", "Devolución parcial", "Devolución total"]
    for i, estado in enumerate(estados):
        cli = clientes[i * 7]
        fecha = (hoy_dt - timedelta(days=i % 3)).strftime("%Y-%m-%d")
        riesgo = float(rnd.randint(2, 20))
        devueltas = {"Evitada": 0, "Devolución parcial": round(riesgo / 2), "Devolución total": riesgo}.get(estado)
        aid = cn.insertar(
            "INSERT INTO alertas (creado, fecha, reportado_por, ruta_codigo, cliente_codigo, cliente_nombre, localidad, "
            "bdr_codigo, supervisor_codigo, tipo_pedido, cajas, cajas_riesgo, hubo_comunicacion, motivo, comentario, "
            "latitud, longitud, estado, resultado, cajas_devueltas, gestionado_por, gestionado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'B2B', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fecha + " 10:12:00", fecha, f"Conductor {cli[7]} Demo", cli[7], cli[0], cli[1], cli[2], cli[8], cli[9],
             riesgo + 30, riesgo, i % 2, motivos_dev[i % len(motivos_dev)], "Dato de demostración", cli[5], cli[6],
             estado, None if estado == "Abierta" else "Gestión de demostración", devueltas,
             None if estado == "Abierta" else "Supervisor Demo", None if estado == "Abierta" else fecha + " 11:00:00"))
        cn.ejecutar("UPDATE alertas SET folio = ? WHERE id = ?", (f"AL-{fecha[2:4]}{fecha[5:7]}{fecha[8:10]}-{aid:05d}", aid))
    cn.commit()
    return (f"Datos de demostración cargados: {len(rutas)} rutas, {len(ventas)} vendedores, {len(clientes)} clientes, "
            f"{n_skus} SKUs, 40 averías, 6 alertas y la planificación de hoy. Usuarios: {', '.join(u[0] for u in usuarios)} (contraseña: {clave}).")
