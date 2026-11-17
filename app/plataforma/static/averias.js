/* Formulario de registro de averías: buscador de SKU, botón Cajas/Unidades, foto comprimida. */
(function () {
  const $ = id => document.getElementById(id);
  const norm = t => String(t).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const SKUS = JSON.parse($('skus-data').textContent).map(([id, cod, nombre, cat, upc]) =>
    ({ id: String(id), cod, nombre, cat, upc, txt: norm(cod + ' ' + nombre + ' ' + cat) }));
  let SKU = null, MANUAL = false;

  /* ---------- Lista desplegable con búsqueda ---------- */
  const btn = $('skuBtn'), panel = $('panel');
  function abrir() {
    panel.classList.remove('oculto'); btn.setAttribute('aria-expanded', 'true');
    $('buscaSku').value = ''; pintarLista(); $('listaSku').scrollTop = 0;
    setTimeout(() => $('buscaSku').focus(), 30);
  }
  function cerrar() { panel.classList.add('oculto'); btn.setAttribute('aria-expanded', 'false'); }
  btn.addEventListener('click', () => panel.classList.contains('oculto') ? abrir() : cerrar());
  document.addEventListener('click', e => { if (!$('combo').contains(e.target)) cerrar(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') cerrar(); });

  function resaltar(texto, palabras) {
    let h = esc(texto);
    palabras.forEach(p => {
      const re = new RegExp('(' + p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
      h = h.replace(re, '<mark>$1</mark>');
    });
    return h;
  }
  function pintarLista() {
    const crudo = $('buscaSku').value.trim();
    const palabras = norm(crudo).split(/\s+/).filter(Boolean);
    const res = palabras.length ? SKUS.filter(s => palabras.every(p => s.txt.includes(p))) : SKUS;
    if (!SKUS.length) { $('listaSku').innerHTML = '<div class="info">No hay SKUs cargados. Pide al administrador que cargue el catálogo.</div>'; return; }
    if (!res.length) { $('listaSku').innerHTML = '<div class="info">Sin resultados para «' + esc(crudo) + '».</div>'; return; }
    const pal = crudo.split(/\s+/).filter(Boolean);
    let html = '<div class="info">' + res.length + (palabras.length ? ' resultado' + (res.length === 1 ? '' : 's') : ' SKUs · desplázate o escribe para filtrar') + '</div>';
    let grupo = '';
    res.forEach(s => {
      if (s.cat !== grupo) { grupo = s.cat; html += '<div class="grupo">' + esc(grupo) + '</div>'; }
      html += '<button type="button" class="op" role="option" aria-selected="' + (SKU && SKU.id === s.id) + '" data-id="' + s.id + '"><code>' +
              resaltar(s.cod, pal) + '</code><span>' + resaltar(s.nombre, pal) + '</span></button>';
    });
    $('listaSku').innerHTML = html;
  }
  let t;
  $('buscaSku').addEventListener('input', () => { clearTimeout(t); t = setTimeout(pintarLista, 120); });
  $('buscaSku').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); const p = $('listaSku').querySelector('.op'); if (p) p.click(); }
  });
  $('listaSku').addEventListener('click', e => {
    const b = e.target.closest('.op'); if (b) { elegir(SKUS.find(s => s.id === b.dataset.id)); cerrar(); }
  });
  function elegir(s) {
    SKU = s; MANUAL = false;
    $('sku_id').value = s.id; $('sku_manual').value = '';
    $('skuTexto').textContent = s.cod + ' – ' + s.nombre; $('skuTexto').classList.remove('combo-placeholder');
    btn.classList.add('elegido-ok');
    $('skuDetalle').textContent = s.cat + (s.upc > 1 ? ' · ' + s.upc + ' unidades por caja' : '');
    $('skuDetalle').classList.remove('oculto');
    $('combo').classList.remove('oculto'); $('zonaManual').classList.add('oculto');
    equivalencia();
  }
  function reiniciar() {
    SKU = null; MANUAL = false; $('sku_id').value = ''; $('sku_manual').value = '';
    $('skuTexto').textContent = 'Selecciona el SKU…'; $('skuTexto').classList.add('combo-placeholder');
    btn.classList.remove('elegido-ok'); $('skuDetalle').classList.add('oculto');
    $('combo').classList.remove('oculto'); $('zonaManual').classList.add('oculto');
    equivalencia();
  }
  function modoManual() {
    SKU = null; MANUAL = true; $('sku_id').value = ''; cerrar();
    $('combo').classList.add('oculto'); $('zonaManual').classList.remove('oculto');
    equivalencia();
  }
  $('noListado').addEventListener('click', () => { modoManual(); $('sku_manual').focus(); });
  $('volverLista').addEventListener('click', () => { reiniciar(); abrir(); });

  /* ---------- Cajas / Unidades ---------- */
  function marcar(u) {
    $('unidad').value = u;
    document.querySelectorAll('#unidadSeg button').forEach(b => b.setAttribute('aria-pressed', b.dataset.u === u));
    $('cantidad').placeholder = '¿Cuántas ' + u.toLowerCase() + '?';
    equivalencia();
  }
  $('unidadSeg').addEventListener('click', e => { const b = e.target.closest('button'); if (b) marcar(b.dataset.u); });
  $('cantidad').addEventListener('input', equivalencia);
  function equivalencia() {
    const n = Number($('cantidad').value), u = $('unidad').value;
    let txt = '';
    if (SKU && n > 0 && SKU.upc > 1) {
      if (u === 'Unidades') txt = '≈ ' + (Math.round(n / SKU.upc * 100) / 100) + ' cajas de ' + SKU.upc + ' unidades';
      if (u === 'Cajas') txt = '= ' + (n * SKU.upc) + ' unidades';
    }
    $('equiv').textContent = txt;
  }

  /* ---------- Fotos de evidencia (hasta 3) ---------- */
  const MAX_FOTOS = 3;
  let FOTOS = [];
  function pintarFotos() {
    $('fotos').querySelectorAll('.foto-item').forEach(n => n.remove());
    FOTOS.forEach((b64, i) => {
      const d = document.createElement('div'); d.className = 'foto-item';
      d.innerHTML = '<img alt="Foto ' + (i + 1) + '"><button type="button" aria-label="Quitar foto">×</button>';
      d.querySelector('img').src = 'data:image/jpeg;base64,' + b64;
      d.querySelector('button').addEventListener('click', () => { FOTOS.splice(i, 1); pintarFotos(); });
      $('fotos').insertBefore(d, $('fotoAdd'));
    });
    $('fotoAdd').classList.toggle('oculto', FOTOS.length >= MAX_FOTOS);
    $('fotosInputs').innerHTML = '';
    FOTOS.forEach(b64 => { const h = document.createElement('input'); h.type = 'hidden'; h.name = 'foto_b64'; h.value = b64; $('fotosInputs').appendChild(h); });
  }
  $('foto').addEventListener('change', async e => {
    const file = e.target.files[0]; e.target.value = '';
    if (!file || FOTOS.length >= MAX_FOTOS) return;
    try { FOTOS.push(await comprimir(file)); pintarFotos(); }
    catch (err) { mostrar(err.message); }
  });
  function comprimir(file) {
    return new Promise((res, rej) => {
      const img = new Image(), url = URL.createObjectURL(file);
      img.onload = () => {
        const k = Math.min(1, 1280 / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        res(c.toDataURL('image/jpeg', 0.75).split(',')[1]);
      };
      img.onerror = () => rej(new Error('No se pudo leer la foto. Intenta tomarla de nuevo.'));
      img.src = url;
    });
  }

  /* ---------- Envío ---------- */
  function mostrar(t) { $('msg').textContent = t; $('msg').classList.remove('oculto'); $('msg').scrollIntoView({ block: 'center' }); }
  $('f').addEventListener('submit', e => {
    $('msg').classList.add('oculto');
    const faltan = [];
    if ($('ruta').tagName === 'SELECT' && !$('ruta').value) faltan.push('la ruta');
    if (!$('reportado_por').value.trim()) faltan.push('quién reporta');
    if (!$('sku_id').value && !(MANUAL && $('sku_manual').value.trim())) faltan.push('el SKU');
    if (!(Number($('cantidad').value) > 0)) faltan.push('la cantidad');
    if (!FOTOS.length) faltan.push('al menos una foto');
    if (!$('motivo').value) faltan.push('el motivo');
    if (faltan.length) { e.preventDefault(); mostrar('Completa ' + faltan.join(', ') + '.'); return; }
    $('btn').disabled = true; $('btn').textContent = 'Guardando…';
  });

  /* ---------- Estado inicial (también al volver con errores) ---------- */
  pintarFotos();
  marcar($('unidad').value || 'Cajas');
  const previo = $('sku_id').value && SKUS.find(s => s.id === $('sku_id').value);
  if (previo) elegir(previo);
  else if ($('sku_manual').value) modoManual();
  else reiniciar();
})();
