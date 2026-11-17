/**
 * Registro de averías – BU CAM | La Constancia
 * Formulario para rutas + panel de validación para administradores.
 * Pegar en Extensiones > Apps Script de una hoja de Google.
 */

const TZ = 'America/El_Salvador';
const HOJA_REG = 'Registros';
const HOJA_CAT = 'Catalogos';
const HOJA_CFG = 'Config';
const HOJA_SKU = 'SKUs';
const UNIDADES_DEF = 'Cajas,Unidades';
const ESTADOS = ['Pendiente', 'Validado', 'Rechazado'];
const MOTIVOS = [
  'Huecos', 'Caja o empaque en mal estado', 'Ponchado debidamente sellado', 'Desfondada o estallada',
  'Estallada por calor', 'Objetos extraños', 'Destapada', 'Mal coronado o tapado', 'Bajo nivel'
];
const ENCABEZADOS = [
  'ID', 'Fecha y hora de registro', 'Fecha de jornada', 'Ruta', 'Reportado por',
  'Tipo de producto', 'Producto / SKU', 'Cantidad', 'Unidad', 'Motivo de avería',
  'Comentario', 'Foto', 'Estado', 'Validado por', 'Fecha de validación', 'Observación de validación',
  'CODSAP', 'Unidades por caja', 'Equivalente en cajas'
];

/** EJECUTAR UNA SOLA VEZ: crea las hojas, catálogos de ejemplo y el PIN. */
function configurar() {
  const ss = SpreadsheetApp.getActive();
  ss.setSpreadsheetTimeZone(TZ);

  const reg = ss.getSheetByName(HOJA_REG) || ss.insertSheet(HOJA_REG);
  if (reg.getLastRow() === 0) {
    reg.appendRow(ENCABEZADOS);
    reg.getRange(1, 1, 1, ENCABEZADOS.length)
      .setFontWeight('bold').setBackground('#1f2937').setFontColor('#ffffff');
    reg.setFrozenRows(1);
    reg.getRange('A:G').setNumberFormat('@'); // texto plano: evita que Sheets cambie fechas/códigos
    reg.getRange('I:Q').setNumberFormat('@');
  } else if (reg.getLastColumn() < ENCABEZADOS.length) {
    // Actualiza una hoja creada con la versión anterior (agrega CODSAP y equivalencias)
    reg.getRange(1, 1, 1, ENCABEZADOS.length).setValues([ENCABEZADOS])
      .setFontWeight('bold').setBackground('#1f2937').setFontColor('#ffffff');
    reg.getRange('Q:Q').setNumberFormat('@');
  }

  if (!ss.getSheetByName(HOJA_CAT)) {
    const cat = ss.insertSheet(HOJA_CAT);
    cat.getRange(1, 1, 1, 3).setValues([['Rutas', 'Tipos de producto', 'Motivos de avería']])
      .setFontWeight('bold').setBackground('#fde68a');
    const rutas = ['DS0012', 'DS0051', 'DS0055', 'DS0090', 'DS0099'];
    const tipos = ['Cerveza lata', 'Cerveza botella retornable', 'Cerveza botella no retornable',
      'Agua', 'Gaseosa', 'Jugo / néctar', 'Bebida energizante', 'Envase vacío / caja plástica'];
    const motivos = MOTIVOS;
    const n = Math.max(rutas.length, tipos.length, motivos.length);
    const filas = [];
    for (let i = 0; i < n; i++) filas.push([rutas[i] || '', tipos[i] || '', motivos[i] || '']);
    cat.getRange(2, 1, n, 3).setValues(filas);
    cat.setFrozenRows(1);
    cat.autoResizeColumns(1, 3);
  }

  if (!ss.getSheetByName(HOJA_CFG)) {
    const cfg = ss.insertSheet(HOJA_CFG);
    cfg.getRange('B:B').setNumberFormat('@');
    cfg.getRange(1, 1, 2, 2).setValues([['PIN_ADMIN', '1234'], ['ID_CARPETA_FOTOS', '']]);
  }
  if (!getCfg_('UNIDADES')) {
    const cfg = ss.getSheetByName(HOJA_CFG);
    cfg.getRange(cfg.getLastRow() + 1, 1, 1, 2).setValues([['UNIDADES', UNIDADES_DEF]]);
  }
  const hoja1 = ss.getSheetByName('Hoja 1') || ss.getSheetByName('Sheet1');
  if (hoja1 && ss.getSheets().length > 1 && hoja1.getLastRow() === 0) ss.deleteSheet(hoja1);
}

/** EJECUTAR UNA VEZ si ya tenías la hoja creada: reemplaza los motivos de la columna C de Catalogos. */
function actualizarMotivos() {
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_CAT);
  if (!sh) throw new Error('Primero ejecuta configurar().');
  const filas = Math.max(sh.getLastRow() - 1, 1);
  sh.getRange(2, 3, filas, 1).clearContent();
  sh.getRange(2, 3, MOTIVOS.length, 1).setValues(MOTIVOS.map(m => [m]));
  sh.autoResizeColumn(3);
}

/** Sirve el formulario (por defecto) o el panel (?p=admin). */
function doGet(e) {
  const esAdmin = e && e.parameter && e.parameter.p === 'admin';
  const t = HtmlService.createTemplateFromFile(esAdmin ? 'Admin' : 'Formulario');
  t.catJson = JSON.stringify(getCatalogos()).replace(/</g, '\\u003c');
  return t.evaluate()
    .setTitle(esAdmin ? 'Averías · Panel de validación' : 'Registro de averías')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getCatalogos() {
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_CAT);
  const col = i => {
    if (!sh || sh.getLastRow() < 2) return [];
    return sh.getRange(2, i, sh.getLastRow() - 1, 1).getDisplayValues()
      .map(r => String(r[0]).trim()).filter(Boolean);
  };
  const unidades = String(getCfg_('UNIDADES') || UNIDADES_DEF).split(',').map(x => x.trim()).filter(Boolean);
  return { rutas: col(1), motivos: col(3), unidades: unidades, estados: ESTADOS, skus: getSkus_() };
}

/** Lee la hoja SKUs: CODSAP | Nombre | Categoría | Unidades por caja → [cod, nombre, cat, upc] */
function getSkus_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_SKU);
  if (!sh || sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, 4).getDisplayValues()
    .filter(r => String(r[0]).trim() && String(r[1]).trim())
    .map(r => [String(r[0]).trim(), String(r[1]).trim(), String(r[2]).trim(), Number(r[3]) || 1]);
}

/** Convierte la cantidad reportada a cajas según la unidad elegida. */
function equivalenteCajas_(cantidad, unidad, upc) {
  const u = String(unidad).toLowerCase();
  if (u.indexOf('caja') === 0) return cantidad;
  if (u.indexOf('unidad') === 0 && upc > 0) return Math.round(cantidad / upc * 1000) / 1000;
  return '';
}

/** Llamado desde el formulario de la ruta. */
function registrarAveria(d) {
  const obligatorios = { fechaJornada: 'fecha', ruta: 'ruta', reportadoPor: 'nombre de quien reporta',
    producto: 'SKU', cantidad: 'cantidad', unidad: 'unidad', motivo: 'motivo' };
  Object.keys(obligatorios).forEach(k => {
    if (d[k] === undefined || String(d[k]).trim() === '') throw new Error('Falta: ' + obligatorios[k]);
  });
  const cantidad = Number(d.cantidad);
  if (!(cantidad > 0)) throw new Error('La cantidad debe ser mayor que cero.');

  // Toma nombre, categoría y unidades por caja del catálogo oficial (no del teléfono)
  let codsap = String(d.codsap || '').trim(), nombre = d.producto, tipo = 'SKU no listado', upc = '';
  if (codsap) {
    const sku = getSkus_().find(s => s[0] === codsap && (!d.producto || s[1] === d.producto)) ||
                getSkus_().find(s => s[0] === codsap);
    if (!sku) throw new Error('El CODSAP ' + codsap + ' no está en el catálogo.');
    nombre = sku[1]; tipo = sku[2]; upc = sku[3];
  }
  const equivCajas = equivalenteCajas_(cantidad, d.unidad, upc);

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_REG);
    const ahora = new Date();
    const id = 'AV-' + Utilities.formatDate(ahora, TZ, 'yyMMdd') + '-' +
      String(sh.getLastRow()).padStart(4, '0');

    let foto = '';
    if (d.fotoBase64) {
      try {
        const blob = Utilities.newBlob(Utilities.base64Decode(d.fotoBase64), 'image/jpeg', id + '.jpg');
        const archivo = carpetaFotos_().createFile(blob);
        try { archivo.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); } catch (err) {}
        foto = archivo.getUrl();
      } catch (err) {
        foto = 'Error al guardar foto';
      }
    }

    sh.appendRow([
      id, Utilities.formatDate(ahora, TZ, 'yyyy-MM-dd HH:mm'), limpio_(d.fechaJornada), limpio_(d.ruta),
      limpio_(d.reportadoPor), limpio_(tipo), limpio_(nombre), cantidad, limpio_(d.unidad),
      limpio_(d.motivo), limpio_(d.comentario), foto, 'Pendiente', '', '', '',
      codsap ? limpio_(codsap) : 'NO LISTADO', upc, equivCajas
    ]);
    return { ok: true, id: id };
  } finally {
    lock.releaseLock();
  }
}

/* ---------- Panel de administradores (protegido con PIN) ---------- */

function adminEntrar(pin) {
  verificarPin_(pin);
  return { ok: true, urlHoja: SpreadsheetApp.getActive().getUrl() };
}

function adminListar(pin, f) {
  verificarPin_(pin);
  f = f || {};
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_REG);
  const n = sh.getLastRow();
  if (n < 2) return [];
  const filas = sh.getRange(2, 1, n - 1, ENCABEZADOS.length).getDisplayValues();
  return filas
    .map(r => ({
      id: r[0], registro: r[1], fecha: r[2], ruta: r[3], reportadoPor: r[4], tipo: r[5],
      producto: r[6], cantidad: r[7], unidad: r[8], motivo: r[9], comentario: r[10], foto: r[11],
      estado: r[12] || 'Pendiente', validadoPor: r[13], fechaVal: r[14], obsVal: r[15],
      codsap: r[16] || '', upc: r[17] || '', cajas: r[18] || ''
    }))
    .filter(x => x.id)
    .filter(x => !f.desde || x.fecha >= f.desde)
    .filter(x => !f.hasta || x.fecha <= f.hasta)
    .filter(x => !f.ruta || x.ruta === f.ruta)
    .filter(x => !f.estado || x.estado === f.estado)
    .reverse()
    .slice(0, 1000);
}

function adminValidar(pin, id, estado, validador, obs) {
  verificarPin_(pin);
  if (ESTADOS.indexOf(estado) < 0) throw new Error('Estado no válido.');
  if (!String(validador || '').trim()) throw new Error('Indica quién valida.');
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_REG);
    const celda = sh.getRange('A:A').createTextFinder(id).matchEntireCell(true).findNext();
    if (!celda) throw new Error('No se encontró el registro ' + id);
    sh.getRange(celda.getRow(), 13, 1, 4).setValues([[
      estado, limpio_(validador), Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm'), limpio_(obs)
    ]]);
    return { ok: true };
  } finally {
    lock.releaseLock();
  }
}

/* ---------- Utilidades ---------- */

function verificarPin_(pin) {
  if (String(pin || '') !== String(getCfg_('PIN_ADMIN'))) throw new Error('PIN incorrecto.');
}

function getCfg_(clave) {
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_CFG);
  const v = sh.getRange(1, 1, Math.max(sh.getLastRow(), 1), 2).getDisplayValues();
  const fila = v.find(r => r[0] === clave);
  return fila ? fila[1] : '';
}

function carpetaFotos_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(HOJA_CFG);
  const id = getCfg_('ID_CARPETA_FOTOS');
  if (id) { try { return DriveApp.getFolderById(id); } catch (e) {} }
  const carpeta = DriveApp.createFolder('Fotos de averías – La Constancia');
  const v = sh.getRange(1, 1, sh.getLastRow(), 1).getValues();
  const i = v.findIndex(r => r[0] === 'ID_CARPETA_FOTOS');
  sh.getRange(i + 1, 2).setValue(carpeta.getId());
  return carpeta;
}

/** Evita que un texto escrito por el usuario se interprete como fórmula. */
function limpio_(s) {
  s = String(s === undefined || s === null ? '' : s).trim().slice(0, 500);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}
