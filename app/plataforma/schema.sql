-- Esquema de la Plataforma de Distribución. {PK} y {BLOB} se adaptan a SQLite o PostgreSQL.
-- Regla: aquí NO se guardan precios, costos ni montos.

CREATE TABLE IF NOT EXISTS usuarios (
  id {PK},
  usuario TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  rol TEXT NOT NULL,
  ruta_codigo TEXT,
  telefono TEXT,
  password_hash TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1,
  debe_cambiar INTEGER NOT NULL DEFAULT 1,
  intentos_fallidos INTEGER NOT NULL DEFAULT 0,
  bloqueado_hasta TEXT,
  creado TEXT NOT NULL,
  ultimo_acceso TEXT
);

CREATE TABLE IF NOT EXISTS rutas (
  codigo TEXT PRIMARY KEY,
  nombre TEXT,
  telefono TEXT,
  conductor_nombre TEXT,
  conductor_telefono TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  actualizado TEXT
);

CREATE TABLE IF NOT EXISTS personal_ventas (
  codigo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  cargo TEXT,
  telefono TEXT,
  jefe_codigo TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  actualizado TEXT
);

CREATE TABLE IF NOT EXISTS clientes (
  codigo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  localidad TEXT,
  direccion TEXT,
  telefono TEXT,
  latitud REAL,
  longitud REAL,
  ruta_codigo TEXT,
  bdr_codigo TEXT,
  supervisor_codigo TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  actualizado TEXT
);
CREATE INDEX IF NOT EXISTS ix_clientes_ruta ON clientes (ruta_codigo);

CREATE TABLE IF NOT EXISTS skus (
  id {PK},
  codsap TEXT NOT NULL,
  nombre TEXT NOT NULL,
  categoria TEXT,
  unidades_por_caja INTEGER NOT NULL DEFAULT 1,
  activo INTEGER NOT NULL DEFAULT 1,
  UNIQUE (codsap, nombre)
);

CREATE TABLE IF NOT EXISTS motivos_averia (
  id {PK},
  nombre TEXT NOT NULL UNIQUE,
  orden INTEGER NOT NULL DEFAULT 0,
  activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS averias (
  id {PK},
  folio TEXT UNIQUE,
  fecha_jornada TEXT NOT NULL,
  creado TEXT NOT NULL,
  ruta_codigo TEXT NOT NULL,
  usuario_id INTEGER,
  reportado_por TEXT NOT NULL,
  codsap TEXT,
  sku_nombre TEXT NOT NULL,
  categoria TEXT,
  cantidad REAL NOT NULL,
  unidad TEXT NOT NULL,
  unidades_por_caja INTEGER,
  cajas_equiv REAL,
  motivo TEXT NOT NULL,
  comentario TEXT,
  foto {BLOB},
  foto_tipo TEXT,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  validado_por TEXT,
  validado_en TEXT,
  observacion TEXT
);
CREATE INDEX IF NOT EXISTS ix_averias_fecha ON averias (fecha_jornada);
CREATE INDEX IF NOT EXISTS ix_averias_ruta ON averias (ruta_codigo);

CREATE TABLE IF NOT EXISTS cargas (
  id {PK},
  tipo TEXT NOT NULL,
  archivo TEXT,
  usuario TEXT,
  creado TEXT NOT NULL,
  filas INTEGER, nuevas INTEGER, actualizadas INTEGER, desactivadas INTEGER, errores INTEGER
);

CREATE TABLE IF NOT EXISTS cargas_pendientes (
  token TEXT PRIMARY KEY,
  tipo TEXT NOT NULL,
  archivo TEXT,
  usuario TEXT,
  datos TEXT NOT NULL,
  creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bitacora (
  id {PK},
  creado TEXT NOT NULL,
  usuario TEXT,
  accion TEXT NOT NULL,
  entidad TEXT,
  detalle TEXT
);
CREATE INDEX IF NOT EXISTS ix_bitacora_creado ON bitacora (creado);

CREATE TABLE IF NOT EXISTS motivos_devolucion (
  id {PK},
  nombre TEXT NOT NULL UNIQUE,
  orden INTEGER NOT NULL DEFAULT 0,
  activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alertas (
  id {PK},
  folio TEXT UNIQUE,
  creado TEXT NOT NULL,
  fecha TEXT NOT NULL,
  usuario_id INTEGER,
  reportado_por TEXT NOT NULL,
  ruta_codigo TEXT NOT NULL,
  cliente_codigo TEXT NOT NULL,
  cliente_nombre TEXT,
  localidad TEXT,
  bdr_codigo TEXT,
  supervisor_codigo TEXT,
  tipo_pedido TEXT,
  cajas REAL,
  cajas_riesgo REAL NOT NULL,
  hectolitros REAL,
  hubo_comunicacion INTEGER NOT NULL DEFAULT 0,
  motivo TEXT NOT NULL,
  comentario TEXT,
  latitud REAL,
  longitud REAL,
  estado TEXT NOT NULL DEFAULT 'Abierta',
  resultado TEXT,
  cajas_devueltas REAL,
  gestionado_por TEXT,
  gestionado_en TEXT
);
CREATE INDEX IF NOT EXISTS ix_alertas_fecha ON alertas (fecha);
CREATE INDEX IF NOT EXISTS ix_alertas_ruta ON alertas (ruta_codigo)
;

CREATE TABLE IF NOT EXISTS averia_fotos (
  id {PK},
  averia_id INTEGER NOT NULL,
  creado TEXT NOT NULL,
  foto {BLOB} NOT NULL,
  tipo TEXT NOT NULL DEFAULT 'image/jpeg',
  bytes INTEGER
);
CREATE INDEX IF NOT EXISTS ix_averia_fotos_averia ON averia_fotos (averia_id)
;

CREATE TABLE IF NOT EXISTS planificacion (
  id {PK},
  fecha TEXT NOT NULL,
  ruta_codigo TEXT NOT NULL,
  cliente_codigo TEXT NOT NULL,
  nombre_negocio TEXT,
  ciudad TEXT,
  direccion TEXT,
  ordenes TEXT,
  cajas REAL,
  peso REAL,
  hectolitros REAL,
  vehiculo TEXT,
  centro TEXT,
  tipo_ruteo TEXT,
  reparto TEXT,
  llegada TEXT,
  salida TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  actualizado TEXT,
  UNIQUE (fecha, ruta_codigo, cliente_codigo)
);
CREATE INDEX IF NOT EXISTS ix_plan_fecha_ruta ON planificacion (fecha, ruta_codigo)
