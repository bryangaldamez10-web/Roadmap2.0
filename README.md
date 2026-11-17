# Plataforma de Distribución – BU CAM | La Constancia

Plataforma web (Python + Flask + PostgreSQL) que centraliza los procesos diarios de Distribución.
Se publica en **Railway**; el mismo código podrá moverse a Azure más adelante sin reescribirse.

## Estructura

```
plataforma-distribucion/
├── app/                          ← la plataforma (esto es lo que se sube a GitHub/Railway)
│   ├── plataforma/
│   │   ├── __init__.py           creación de la app, seguridad y comandos
│   │   ├── db.py                 conexión (SQLite local / PostgreSQL en Railway)
│   │   ├── schema.sql            tablas
│   │   ├── auth.py               login, roles y permisos
│   │   ├── entidades.py          definición de maestros y columnas que reconocen los Excel
│   │   ├── maestros.py           consulta de rutas, vendedores, clientes, SKUs y motivos
│   │   ├── cargas.py             carga de Excel/CSV con vista previa
│   │   ├── averias.py            registro, validación y exportación de averías
│   │   ├── usuarios.py           usuarios y bitácora
│   │   ├── datos_base.py         motivos oficiales, catálogo de SKUs y datos ficticios de demo
│   │   ├── datos/catalogo_skus.xlsx
│   │   ├── templates/            pantallas (HTML)
│   │   └── static/               estilos, script del formulario, ícono
│   ├── tests/test_plataforma.py  pruebas automáticas
│   ├── wsgi.py · requirements.txt · Procfile · railway.json · .python-version · variables_railway_ejemplo.txt
├── datos/maestros/               bases de referencia (SKUs original y depurado)
├── docs/                         referencias (alerta de devolución de Roadmap)
└── prototipos/                   primer prototipo en Google Apps Script (ya reemplazado)
```

## Qué incluye la fase 1

- **Login y roles**: Administrador, Supervisor de Distribución, Validador de averías, Ruta/Conductor y Ventas.
  Contraseñas cifradas, cambio obligatorio de la temporal, bloqueo de 15 min tras 5 intentos, protección CSRF.
- **Maestros**: rutas (con conductor y teléfonos), personal de ventas (con jefe directo), clientes (con coordenadas, ruta, BDR y supervisor), SKUs y motivos.
  Los teléfonos de clientes solo los ven Administrador y Supervisor.
- **Cargas de Excel/CSV**: reconoce los encabezados aunque cambien de orden, de nombre o lleven tildes; muestra vista previa con nuevos, actualizados, errores y avisos antes de guardar.
  La base mensual de clientes puede marcar como inactivos a los que ya no vienen. Hay plantillas descargables.
- **Averías**: buscador de SKU (CODSAP – Nombre), botón Cajas | Unidades con equivalencia a cajas, 9 motivos oficiales, foto comprimida desde la cámara.
  Validación con observación obligatoria al rechazar, indicadores y exportación a Excel. El conductor solo ve y registra su ruta.
- **Alertas de devolución** (Administrador, Supervisor y Ruta): se escribe el código de cliente y se llenan solos el supervisor y el BDR.
  Se arma el mensaje con el formato de Roadmap, con botones para enviarlo por WhatsApp al BDR, al supervisor o a cualquier chat o grupo.
  El Administrador y el Supervisor ven todas las alertas y registran el resultado: Evitada, Devolución parcial o Devolución total.
  La ruta solo ve las alertas de sus propios clientes.
- **Bitácora**: inicios de sesión, cargas, validaciones, cambios de usuarios y exportaciones.
- **Regla de seguridad**: la plataforma no guarda precios, costos ni montos.

## Probarlo en tu computadora (Windows)

Requiere Python 3.12 o superior (python.org, marcando "Add python.exe to PATH").

- **`app\iniciar.bat`**: doble clic. La primera vez instala todo y crea la base con datos FICTICIOS; luego abre http://127.0.0.1:5000.
- **`app\probar.bat`**: corre las pruebas automáticas.
- **`app\reiniciar_datos_demo.bat`**: borra la base local y la vuelve a crear.

Usuarios de demostración (contraseña `Demo-2026`): `admin.demo`, `supervisor.demo`, `validador.demo`, `ruta.ds0099`, `ventas.demo`.

## Publicar en Railway

1. Sube la carpeta **`app/`** a un repositorio **privado** de GitHub (su contenido queda en la raíz del repositorio).
2. En Railway: **New Project › Deploy from GitHub repo** y elige el repositorio.
3. En el mismo proyecto: **New › Database › PostgreSQL**. Railway crea `DATABASE_URL`.
4. En el servicio web, pestaña **Variables**, agrega:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencia a la base)
   - `SECRET_KEY` = una cadena larga y aleatoria (por ejemplo, 50 caracteres)
   - `ADMIN_USUARIO` y `ADMIN_CLAVE` = el primer administrador (se pide cambiar la clave al entrar)
   - `COOKIE_SEGURA` = `1`
   - `CARGAR_DEMO` = `1` solo si quieres una demostración con datos ficticios
5. **Settings › Networking › Generate Domain** para obtener la dirección pública.
6. Entra con el administrador, crea los usuarios y carga los Excel en **Cargar datos**.

Cada `git push` vuelve a publicar automáticamente. Al arrancar, la app crea las tablas que falten sin borrar datos.

## Fases siguientes

2. **Planificación + mapa**: carga diaria de planificación, clientes planificados por ruta, estimado de cajas por carga, mapa con coordenadas.
3. **Tableros e indicadores**.

## Decisiones tomadas

- Hospedaje actual: Railway. Más adelante, posible migración a Azure corporativo con login de Microsoft.
- WhatsApp: solo un botón que abre WhatsApp con el mensaje armado; sin envío automático.
- Seguridad: sin precios, costos ni montos; todo detrás de login; cada rol ve solo lo que le toca; bitácora de cambios.
  Usar datos ficticios hasta confirmar con TI qué información de clientes puede alojarse fuera de los sistemas corporativos.
