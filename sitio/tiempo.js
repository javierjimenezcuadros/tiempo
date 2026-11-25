/* Módulo del tiempo. Lee mapa.json (dónde va cada punto y cada ciudad, fijo)
   y datos/<fecha>.json: la «emisión» de ese día, con su previsión y la de los
   cinco siguientes tal como se dio ese día (lo genera GitHub). Tocar un día en
   «6 días» cambia todo el módulo a ese día.

   Lugares: las 59 ciudades vienen en la emisión. Los demás municipios (unos
   8.100, nomenclátor del IGN) están en municipios.json, que solo se descarga al
   tocar el buscador; al elegir uno se descarga el archivo de su zona
   (datos/<fecha>/z/<zona>.json) con la previsión de su celda del modelo, que
   la página corrige por la altitud del municipio. Si falta ese archivo (las
   emisiones de hace más de dos semanas no lo guardan), se ve la ciudad más
   cercana y se avisa.

   Dirección:
     /                 el día de hoy (o el más cercano que haya)
     /?d=2026-11-21    ese día, para siempre (el shot de ese día hace de archivo)
     &ciudad=Sevilla   ciudad o municipio con el que abre
     &vista=lluvia     pestaña con la que abre
     &ficha=dias       la ficha abre en «6 días» en vez de «Por horas»

   Sin &ciudad, abre en el último lugar que eligió el lector en ese navegador;
   si no hay, en Las Palmas cuando su hora es la de Canarias, y si no, en Madrid.

   Tocar un punto del mapa elige el municipio más poblado de los que caen en
   él (mapa.json lo trae calculado); tocar el rótulo de una ciudad, esa ciudad.

   Lo único que guarda es ese lugar (localStorage, clave tiempo.lugar), y solo
   cuando el lector lo elige: su nombre y su provincia y, para abrir sin
   descargar la lista de municipios, su zona, su celda, su corrección por
   altitud, su sitio en el dibujo y la marca de las tablas (mapa.json «tablas»;
   si cambian, se vuelve a buscar por el nombre). No envía nada. Si cambia lo que guarda o envía,
   hay que cambiar también privacidad.html. */
(() => {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const coma = (v) => String(v).replace('.', ',');
  const llano = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const dos = (n) => String(n).padStart(2, '0');
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const params = new URLSearchParams(location.search);

  // Escala de temperatura (°C → color) y categorías de lluvia (mm en el día)
  const TEMP = [[-6, '#23336e'], [-2, '#2f5fb3'], [2, '#4f8fd0'], [6, '#86bfe0'], [10, '#b9dcc8'],
                [14, '#f2d98b'], [18, '#f4b45e'], [22, '#ea7f43'], [26, '#d4502f'], [30, '#a8282a'], [34, '#6e1424']];
  const LLUVIA = [[0.5, 'Sin lluvia', '#D3D9DF'], [5, 'Poca', '#A8D4F0'], [20, 'Moderada', '#4A9CD8'],
                  [50, 'Mucha', '#1858A0'], [Infinity, 'Muchísima', '#0A2060']];
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  function colorTemp(v) {
    if (v <= TEMP[0][0]) return TEMP[0][1];
    for (let k = 1; k < TEMP.length; k++) {
      const [b, cb] = TEMP[k];
      if (v <= b) {
        const [a, ca] = TEMP[k - 1];
        const f = (v - a) / (b - a);
        const [r1, g1, b1] = hex(ca), [r2, g2, b2] = hex(cb);
        return `rgb(${Math.round(r1 + f * (r2 - r1))},${Math.round(g1 + f * (g2 - g1))},${Math.round(b1 + f * (b2 - b1))})`;
      }
    }
    return TEMP[TEMP.length - 1][1];
  }
  const catLluvia = (mm) => LLUVIA.findIndex(([lim]) => mm < lim);

  let M = null;          // mapa.json
  let E = null;          // la emisión: {fecha, pasada_texto, dias: [...], enlace}
  let D = null;          // el día que se ve (uno de E.dias)
  let activo = 0;        // su índice en E.dias
  let vista = params.get('vista') === 'lluvia' ? 'lluvia' : 'temp';
  // El lugar que se ve: una ciudad {nombre, ciudad} o un municipio
  // {nombre, provincia, zona, celda, corr, pos}.
  let lugar = { nombre: 'Madrid', ciudad: 'Madrid' };
  let circulos = [];
  const svg = $('mapa');
  const capa = el('g');
  const capaTexto = el('g', { class: 'rotulos' });
  const capaApunta = el('g', { class: 'apunta' });    // adónde llevaría el toque

  // --- Datos -----------------------------------------------------------
  async function leer(url) {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  }

  function fechaLocal(d) {
    return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  }
  const hoy = () => fechaLocal(new Date());

  /** La fecha pedida en la dirección o, sin ella, hoy, la siguiente que haya o la última. */
  async function elegirFecha() {
    const pedida = params.get('d');
    if (pedida && /^\d{4}-\d{2}-\d{2}$/.test(pedida)) return { fecha: pedida, vieja: false };
    const { fechas } = await leer('datos/indice.json');
    if (!fechas.length) throw new Error('sin datos');
    const h = hoy();
    if (fechas.includes(h)) return { fecha: h, vieja: false };
    const siguiente = fechas.find((f) => f > h);
    if (siguiente) return { fecha: siguiente, vieja: false };
    return { fecha: fechas[fechas.length - 1], vieja: true };
  }

  // Municipios (se descargan la primera vez que se toca el buscador) y zonas
  let municipios = null;
  let cargaMunicipios = null;
  /** De una fila compacta (campos de municipios.json) a un municipio. */
  function lector(campos) {
    const i = Object.fromEntries(campos.map((c, k) => [c, k]));
    return (m) => ({
      nombre: m[i.nombre], provincia: m[i.provincia], zona: m[i.zona], celda: m[i.celda],
      corr: m[i.corr], pos: m[i.x] === null ? null : [m[i.x], m[i.y]], ciudad: m[i.ciudad] || null,
      clave: llano(m[i.nombre]),
    });
  }
  function cargarMunicipios() {
    if (!cargaMunicipios) {
      cargaMunicipios = leer('municipios.json').then((j) => {
        municipios = j.lista.map(lector(j.campos));
        return municipios;
      }).catch(() => { cargaMunicipios = null; return null; });
    }
    return cargaMunicipios;
  }

  const zonas = new Map();          // zona → archivo de la zona, o null si no está
  async function cargarZona(zona) {
    if (!zonas.has(zona)) {
      try { zonas.set(zona, await leer(`datos/${E.fecha}/z/${zona}.json`)); } catch (e) { zonas.set(zona, null); }
    }
    return zonas.get(zona);
  }

  /** De la celda compacta (ver celda_dia en el generador) a la ficha, ya corregida por altitud. */
  function fichaCelda(c, corr, horas) {
    const max = c[0] + corr, min = c[1] + corr;
    const rango = (v, a, b) => (a === null ? null
      : [Math.min(Math.round(v - a), Math.round(v)), Math.max(Math.round(v + b), Math.round(v))]);
    return {
      max: Math.round(max), min: Math.round(min), lluvia: c[2],
      max_dif: c[3], min_dif: c[4],
      max_rango: rango(max, c[5], c[6]), min_rango: rango(min, c[7], c[8]),
      seguridad: { a: 'alta', m: 'media', b: 'baja' }[c[9]] || null,
      prob_lluvia: c[10], prob_lluvia_fuerte: c[11],
      horas: horas.map((h, i) => [h, c[12][i] === null ? null : Math.round(c[12][i] + corr), c[13][i], c[14][i]]),
    };
  }

  /** La ficha del lugar elegido en el día k de la emisión (null si no hay datos). */
  function fichaDe(k) {
    if (lugar.ciudad) return E.dias[k].ciudades[lugar.ciudad] || null;
    const z = zonas.get(lugar.zona);
    const dias = z && z.celdas[String(lugar.celda)];
    return dias && dias[k] ? fichaCelda(dias[k], lugar.corr, z.horas[k]) : null;
  }

  const posLugar = () => (lugar.ciudad ? M.ciudades[lugar.ciudad] : lugar.pos) || null;

  // --- Mapa ------------------------------------------------------------
  function montarMapa() {
    svg.setAttribute('viewBox', `0 0 ${M.ancho} ${M.alto}`);
    const [rx, ry, rw, rh] = M.recuadro;
    svg.append(el('rect', { class: 'recuadro', x: rx - 4, y: ry - 4, width: rw + 8, height: rh + 8, rx: 6 }));
    svg.append(capa, capaTexto, capaApunta);
    circulos = M.puntos.map(([x, y]) => {
      const c = el('circle', { cx: x, cy: y, r: 3.1 });
      capa.append(c);
      return c;
    });
  }

  function valor(f) {
    if (!f) return '';
    if (vista === 'lluvia') return f.lluvia >= 0.5 ? `${Math.round(f.lluvia)} mm` : '';
    return `${f.max}°`;
  }

  const CORTOS = { 'Santa Cruz de Tenerife': 'S. C. Tenerife', 'Santiago de Compostela': 'Santiago',
                   'Jerez de la Frontera': 'Jerez' };

  function rotulo(nombre, [x, y], texto, lado, ciudad = '') {
    const pos = { der: [x + 7, y + 5, 'start'], izq: [x - 7, y + 5, 'end'], abajo: [x, y + 19, 'middle'] }[lado];
    const t = el('text', { x: pos[0], y: pos[1], 'text-anchor': pos[2], 'data-ciudad': ciudad });
    t.append(document.createTextNode(`${CORTOS[nombre] || nombre} `));
    const v = el('tspan', { class: 'valor' });
    v.textContent = texto;
    t.append(v);
    capaTexto.append(t);
  }

  function pintar() {
    circulos.forEach((c, k) => {
      if (vista === 'lluvia') {
        const i = catLluvia(D.puntos.lluvia[k]);
        c.setAttribute('fill', LLUVIA[i][2]);
        c.setAttribute('r', i === 0 ? 2.2 : 3.1);
      } else {
        c.setAttribute('fill', colorTemp(D.puntos.max[k]));
        c.setAttribute('r', 3.1);
      }
    });
    capaTexto.replaceChildren();
    for (const [nombre, lado] of Object.entries(M.etiquetas)) {
      if (!M.ciudades[nombre] || !D.ciudades[nombre]) continue;
      const [x, y] = M.ciudades[nombre];
      capaTexto.append(el('circle', { cx: x, cy: y, r: 2.4, fill: '#10161D' }));
      rotulo(nombre, [x, y], valor(D.ciudades[nombre]), lado, nombre);
    }
    const pos = posLugar();
    if (pos) {
      capaTexto.append(el('circle', { class: 'anillo', cx: pos[0], cy: pos[1], r: 7 }));
      if (!(lugar.ciudad && lugar.ciudad in M.etiquetas)) {
        rotulo(lugar.ciudad || lugar.nombre, pos, valor(fichaDe(activo)), pos[0] > M.ancho * 0.7 ? 'izq' : 'der');
      }
    }
    leyenda();
  }

  function leyenda() {
    const L = $('leyenda');
    if (vista === 'lluvia') {
      L.className = 'leyenda';
      L.innerHTML = '<div class="chips">' + LLUVIA.map(([lim, nombre, color], i) => {
        const rango = i === 0 ? '' : i === LLUVIA.length - 1 ? ' (+50 mm)' : ` (hasta ${lim})`;
        return `<span class="chip"><i style="background:${color}"></i>${nombre}<span class="rango">${rango}</span></span>`;
      }).join('') + '</div>';
      return;
    }
    L.className = 'leyenda temp';
    const lo = -6, hi = 34, pct = (v) => ((v - lo) / (hi - lo)) * 100;
    const grad = TEMP.map(([v, c]) => `${c} ${pct(v)}%`).join(',');
    const marcas = [0, 10, 20, 30].map((v) => `<span style="left:${pct(v)}%">${v}°</span>`).join('');
    L.innerHTML = `<span>Máxima</span><div class="rampa" style="background:linear-gradient(90deg,${grad})">${marcas}</div>`;
  }

  // --- Ficha -------------------------------------------------------------
  function nota(dif) {
    if (dif === null || dif === undefined) return ['Sin referencia en Canarias', ''];
    if (dif >= 1) return [`${dif}° más de lo normal`, 'calor'];
    if (dif <= -1) return [`${-dif}° menos de lo normal`, 'frio'];
    return ['Lo normal para la fecha', ''];
  }

  function textoLluvia(f) {
    const p = f.prob_lluvia, mm = f.lluvia;
    let frase;
    if (p === null) frase = mm >= 1 ? 'Lluvia' : 'Sin lluvia';
    else if (p < 20) frase = 'Sin lluvia';
    else if (p < 50) frase = 'Puede llover';
    else if (p < 80) frase = 'Lluvia probable';
    else frase = 'Lluvia casi segura';
    const partes = [`<strong>${frase}</strong>`];
    if (p !== null) partes.push(`${p} %`);
    if (mm >= 0.5) partes.push(`${coma(Math.round(mm * 10) / 10)} mm en el día`);
    return partes.join(' · ');
  }

  function panel() {
    const f = fichaDe(activo);
    $('buscar').value = lugar.nombre;
    if (!f) return;
    $('vmax').textContent = `${f.max}°`;
    $('vmin').textContent = `${f.min}°`;
    for (const [id, dif] of [['nmax', f.max_dif], ['nmin', f.min_dif]]) {
      const [txt, cls] = nota(dif);
      $(id).textContent = txt;
      $(id).className = `nota ${cls}`;
    }
    $('lluvia').innerHTML = textoLluvia(f);
    if (f.seguridad && f.max_rango) {
      const [a, b] = f.max_rango;
      const rango = a === b ? `máxima de ${a}°` : `máxima entre ${a} y ${b}°`;
      $('seguridad').innerHTML = `<i class="${f.seguridad}"></i>Seguridad ${f.seguridad}: ${rango}`;
    } else {
      $('seguridad').textContent = '';
    }
    const cab = '<li class="cabecera"><span>Hora</span><span>Temp.</span><span>Lluvia</span></li>';
    $('horas').innerHTML = cab + f.horas.map(([h, t, p, mm]) => {
      let ancho = 0, txt = '—', nada = ' nada';
      if (p !== null) {
        ancho = p; txt = `${p} %`; nada = p < 10 ? ' nada' : '';
      } else if (mm !== null && mm >= 0.1) {
        ancho = Math.min(100, mm * 20); txt = `${coma(mm)} mm`; nada = '';
      }
      return `<li><span>${h} h</span><span class="t">${t === null ? '—' : `${t}°`}</span>`
        + `<span class="barra-p"><b style="width:${ancho}%"></b></span>`
        + `<span class="p${nada}">${txt}</span></li>`;
    }).join('');
    listaDias();
  }

  // --- Próximos días ---------------------------------------------------------
  /** «Hoy» o «Mañana» según la fecha del aparato del lector; si no, «sáb 21». */
  function etiquetaDia(dia) {
    const h = new Date();
    if (dia.fecha === fechaLocal(h)) return 'Hoy';
    h.setDate(h.getDate() + 1);
    if (dia.fecha === fechaLocal(h)) return 'Mañana';
    return dia.corto || dia.fecha.slice(8);
  }

  function listaDias() {
    $('boton-dias').textContent = `${E.dias.length} días`;
    // Las emisiones antiguas traen un solo día: entonces no hay nada que elegir.
    document.querySelector('.ficha-vista').hidden = E.dias.length < 2;
    const cab = '<li class="cabecera"><span>Día</span><span>Máx.</span><span>Mín.</span><span>Lluvia</span></li>';
    $('dias').innerHTML = cab + E.dias.map((dia, k) => {
      const f = fichaDe(k);
      if (!f) return '';
      const p = f.prob_lluvia;
      const lluvia = p === null ? (f.lluvia >= 1 ? `${Math.round(f.lluvia)} mm` : '—') : `${p} %`;
      return `<li><button type="button" class="dia-btn" data-k="${k}" aria-pressed="${k === activo}">`
        + `<span class="d">${etiquetaDia(dia)}</span>`
        + `<span class="t">${f.max}°</span><span class="m">${f.min}°</span>`
        + `<span class="p${p !== null && p < 10 ? ' nada' : ''}">${lluvia}</span>`
        + '</button></li>';
    }).join('');
  }

  function cabecera() {
    $('dia').textContent = D.dia;
    $('titular').textContent = D.titular;
  }

  /** Cambia todo el módulo (mapa, titular, cajas y tabla por horas) a otro día. */
  function elegirDia(k) {
    if (!E.dias[k] || !fichaDe(k)) return;
    activo = k;
    D = E.dias[k];
    cabecera();
    panel();
    pintar();
  }

  function mostrarFicha(cual) {
    document.querySelectorAll('.ficha-vista button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.ficha === cual)));
    $('horas').hidden = cual !== 'horas';
    $('dias').hidden = cual !== 'dias';
  }

  // --- Elegir lugar ----------------------------------------------------------
  function avisoLugar(texto) {
    $('aviso-lugar').textContent = texto || '';
    $('aviso-lugar').hidden = !texto;
  }

  function ciudadCercana(pos) {
    let mejor = 'Madrid', dist = Infinity;
    for (const [nombre, p] of Object.entries(M.ciudades)) {
      if (!p || !D.ciudades[nombre] || !pos) continue;
      const d = Math.hypot(p[0] - pos[0], p[1] - pos[1]);
      if (d < dist) { mejor = nombre; dist = d; }
    }
    return mejor;
  }

  /** Pone un lugar (sin pintar). Devuelve false si no hay con qué mostrarlo. */
  async function ponerLugar(m) {
    avisoLugar('');
    if (m.ciudad && D.ciudades[m.ciudad]) {
      lugar = { nombre: m.nombre || m.ciudad, ciudad: m.ciudad };
      return true;
    }
    if (m.zona === undefined) return false;
    const z = await cargarZona(m.zona);
    const mismas = !z || !z.tablas || !M.tablas || z.tablas === M.tablas;   // si no, la celda sería otra
    if (z && mismas && z.celdas[String(m.celda)]) {
      lugar = { nombre: m.nombre, provincia: m.provincia, zona: m.zona, celda: m.celda, corr: m.corr, pos: m.pos };
      return true;
    }
    const c = ciudadCercana(m.pos);
    lugar = { nombre: c, ciudad: c };
    avisoLugar(`Sin datos de ${m.nombre} en esta fecha: se ve ${c}, la ciudad más cercana`);
    return true;
  }

  /** Elección del lector (buscador o mapa): se recuerda para la próxima vez. */
  async function elegir(m) {
    if (!(await ponerLugar(m))) return;
    recordar(m);
    panel();
    pintar();
  }

  // --- Lugar recordado y zona horaria ----------------------------------------
  // En un iframe de otro sitio el almacenamiento puede estar bloqueado o
  // borrarse (Safari lo limita): nada de esto puede romper el módulo.
  const CLAVE = 'tiempo.lugar';
  function recordado() {
    try {
      const j = localStorage.getItem(CLAVE);
      if (j) return JSON.parse(j);
      const viejo = localStorage.getItem('tiempo.ciudad');    // la primera versión guardaba solo la ciudad
      return viejo ? { nombre: viejo } : null;
    } catch (e) { return null; }
  }
  function recordar(m) {
    const g = { nombre: m.nombre || m.ciudad, provincia: m.provincia || null };
    if (m.ciudad) g.ciudad = m.ciudad;
    else if (m.zona !== undefined) Object.assign(g, { zona: m.zona, celda: m.celda, corr: m.corr, pos: m.pos, tablas: M.tablas || null });
    try {
      localStorage.setItem(CLAVE, JSON.stringify(g));
      localStorage.removeItem('tiempo.ciudad');
    } catch (e) { /* sin almacenamiento */ }
  }
  /** El lugar recordado, si se puede poner sin descargar la lista de municipios. */
  function recordadoDirecto(g) {
    if (g.ciudad) return D.ciudades[g.ciudad] ? { nombre: g.nombre || g.ciudad, ciudad: g.ciudad } : null;
    if (g.zona === undefined || !M.tablas || g.tablas !== M.tablas) return null;
    return { nombre: g.nombre, provincia: g.provincia, zona: g.zona, celda: g.celda, corr: g.corr, pos: g.pos || null };
  }
  function horaDeCanarias() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone === 'Atlantic/Canary'; } catch (e) { return false; }
  }

  /** Busca un lugar por nombre: primero entre las ciudades, luego entre los municipios. */
  async function buscarLugar(nombre, provincia) {
    if (!nombre) return null;
    const ciudad = Object.keys(D.ciudades).find((c) => llano(c) === llano(nombre));
    if (ciudad) return { nombre: ciudad, ciudad };
    const lista = await cargarMunicipios();
    if (!lista) return null;
    const q = llano(nombre);
    return lista.find((m) => m.clave === q && (!provincia || m.provincia === provincia))
      || lista.find((m) => m.clave.split('/').some((p) => p.trim() === q)) || null;
  }

  /** Lugar con el que abre: el de la dirección, el recordado, Las Palmas o Madrid. */
  async function lugarInicial() {
    const pedido = params.get('ciudad');
    if (pedido) {
      const m = await buscarLugar(pedido, null);
      if (m && (await ponerLugar(m))) return;
    }
    const g = recordado();
    if (g) {
      const directo = recordadoDirecto(g);
      if (directo && (await ponerLugar(directo))) return;
      const m = await buscarLugar(g.nombre, g.provincia);       // guardado antes o con otras tablas
      if (m && (await ponerLugar(m))) { recordar(m); return; }    // completo, para la próxima vez
    }
    const c = horaDeCanarias() && D.ciudades['Las Palmas'] ? 'Las Palmas' : (D.ciudades.Madrid ? 'Madrid' : Object.keys(D.ciudades)[0]);
    lugar = { nombre: c, ciudad: c };
  }

  // --- Buscador --------------------------------------------------------
  const buscar = $('buscar'), sug = $('sugerencias');
  let opciones = [];
  let activa = 0;

  /** Hasta 8 lugares que casan: primero los que empiezan así (por población), luego los que lo contienen. */
  function candidatos(q) {
    if (!municipios) {
      const ciudades = Object.keys(D.ciudades).sort((a, b) => a.localeCompare(b, 'es'));
      return ciudades.filter((c) => !q || llano(c).includes(q)).slice(0, 8).map((c) => ({ nombre: c, ciudad: c }));
    }
    if (!q) return municipios.slice(0, 8);
    const empieza = [], contiene = [];
    for (const m of municipios) {
      if (m.clave.startsWith(q) || m.clave.split(/[/ -]/).some((p) => p.startsWith(q))) empieza.push(m);
      else if (m.clave.includes(q)) contiene.push(m);
      if (empieza.length >= 8) break;
    }
    return empieza.concat(contiene).slice(0, 8);
  }

  function sugerir() {
    opciones = candidatos(llano(buscar.value.trim()));
    activa = 0;
    sug.innerHTML = opciones.map((m, i) => `<li role="option" data-i="${i}" class="${i === 0 ? 'activa' : ''}">`
      + `${esc(m.nombre)}${m.provincia ? `<small>${esc(m.provincia)}</small>` : ''}</li>`).join('')
      || `<li class="vacio">${municipios ? 'No está en la lista' : 'Cargando municipios…'}</li>`;
    sug.hidden = false;
  }
  function cerrar() { sug.hidden = true; buscar.value = lugar.nombre; buscar.blur(); }
  buscar.addEventListener('focus', () => {
    buscar.select();
    sugerir();
    cargarMunicipios().then(() => { if (document.activeElement === buscar) sugerir(); });
  });
  buscar.addEventListener('input', sugerir);
  buscar.addEventListener('keydown', (e) => {
    const items = [...sug.querySelectorAll('li[data-i]')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      activa = (activa + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % Math.max(1, items.length);
      items.forEach((li, i) => li.classList.toggle('activa', i === activa));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const m = opciones[activa];
      cerrar();
      if (m) elegir(m);
    } else if (e.key === 'Escape') {
      cerrar();
    }
  });
  sug.addEventListener('pointerdown', (e) => {
    const li = e.target.closest('li[data-i]');
    if (!li) return;
    e.preventDefault();
    const m = opciones[Number(li.dataset.i)];
    cerrar();
    if (m) elegir(m);
  });
  buscar.addEventListener('blur', () => setTimeout(() => { sug.hidden = true; buscar.value = lugar.nombre; }, 150));

  // --- Arranque ----------------------------------------------------------
  function fallo(texto) {
    $('fallo').textContent = texto;
    $('fallo').hidden = false;
  }

  async function arrancar() {
    try {
      const [mapa, eleccion] = await Promise.all([leer('mapa.json'), elegirFecha()]);
      M = mapa;
      E = await leer(`datos/${eleccion.fecha}.json`);
      if (!E.dias) {             // emisiones antiguas (versión 1): un solo día
        E = { fecha: E.fecha, pasada_texto: E.pasada_texto, enlace: E.enlace,
              dias: [{ fecha: E.fecha, dia: E.dia, titular: E.titular, puntos: E.puntos, ciudades: E.ciudades }] };
      }
      if (!E.dias.length) throw new Error('emisión vacía');
      if (eleccion.vieja) {
        $('aviso').textContent = ' · sin actualizar';
        $('aviso').hidden = false;
        // Si la emisión vieja llega hasta hoy, al menos se abre en hoy.
        const k = E.dias.findIndex((d) => d.fecha === hoy());
        if (k > 0) activo = k;
      }
      D = E.dias[activo];
    } catch (e) {
      fallo(params.get('d') ? 'No hay previsión guardada para esa fecha.' : 'No se ha podido cargar la previsión.');
      return;
    }
    await lugarInicial();

    cabecera();
    $('pie').textContent = `ECMWF (CC BY 4.0) · Normal 1991-2020: ERA5, Copernicus · Municipios: NGMEP CC-BY 4.0 ign.es · Pasada de las ${E.pasada_texto}`;
    if (E.enlace && E.enlace.url) {
      const a = document.createElement('a');
      a.href = E.enlace.url;
      a.target = '_top';
      a.textContent = E.enlace.texto || 'Lee la historia';
      $('pie').append(' · ', a);
    }
    const priv = document.createElement('a');
    priv.href = 'privacidad.html';
    priv.target = '_blank';          // nunca saca al lector de la portada de Xataka
    priv.rel = 'noopener';
    priv.textContent = 'Privacidad';
    $('pie').append(' · ', priv);
    document.querySelectorAll('.pestanas button').forEach((b) => {
      b.setAttribute('aria-selected', String(b.dataset.vista === vista));
      b.addEventListener('click', () => {
        vista = b.dataset.vista;
        document.querySelectorAll('.pestanas button').forEach((o) => o.setAttribute('aria-selected', String(o === b)));
        pintar();
      });
    });
    document.querySelectorAll('.ficha-vista button').forEach((b) => {
      b.addEventListener('click', () => mostrarFicha(b.dataset.ficha));
    });
    $('dias').addEventListener('click', (e) => {
      const b = e.target.closest('.dia-btn');
      if (b) elegirDia(Number(b.dataset.k));
    });
    montarMapa();
    panel();
    pintar();
    mostrarFicha(params.get('ficha') === 'dias' && E.dias.length > 1 ? 'dias' : 'horas');
    $('modulo').setAttribute('aria-busy', 'false');
  }

  // Tocar el mapa. Cada una de las 59 ciudades tiene un imán: un toque cerca de
  // ella la elige. El de las diez con rótulo es mayor y abarca su rótulo. Fuera
  // de los imanes, cada punto elige el municipio más poblado de los que caen en
  // él (mapa.json «lugares»). Mientras se apunta (con el ratón encima o con el
  // dedo apoyado), los rótulos y los puntos negros se apagan y se ve el destino:
  // un anillo y su nombre. Los radios van en píxeles de pantalla, no del dibujo:
  // en el móvil el mapa mide unos 150 px de alto, y con 18 px el 82 % de los
  // puntos caía en alguna de las diez ciudades.
  const IMAN = { touch: [12, 6], mouse: [8, 4] };       // [con rótulo, sin rótulo]
  const MARGEN_ROTULO = 3;
  let puntero = 'touch';

  function enElDibujo(e) {
    const ctm = svg.getScreenCTM();
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return { p: pt.matrixTransform(ctm.inverse()), escala: ctm.a || 1 };
  }

  const aCaja = (p, b) => Math.hypot(Math.max(b.x - p.x, 0, p.x - b.x - b.width),
                                     Math.max(b.y - p.y, 0, p.y - b.y - b.height));

  /**
   * Qué elige un toque en p: {ciudad, pos}, {fila, pos} o null.
   * - Con el dedo, encima de un rótulo gana su ciudad, salvo justo en el punto
   *   de otra ciudad que el rótulo tapa (Granada bajo «Sevilla 19°»).
   * - Si no, cada ciudad saca una nota, su distancia partida por su radio, y
   *   gana la más baja si no pasa de 1 (el margen de un rótulo cuenta como 1).
   * - Si no, el municipio más poblado del punto más cercano.
   * Con el ratón los rótulos están apagados y no cuentan.
   */
  function destino(p, escala, raton) {
    const [conRotulo, sinRotulo] = IMAN[raton ? 'mouse' : 'touch'];
    // Nunca menos de 8 unidades con rótulo: el punto negro de una ciudad cae
    // entre cuatro puntos de color, a 5-7 unidades, y solo uno es la ciudad.
    const grande = Math.max(8, conRotulo / escala);
    const chico = Math.max(5, sinRotulo / escala);
    const margen = Math.max(2, MARGEN_ROTULO / escala);
    const vale = (c) => M.ciudades[c] && D.ciudades[c];
    const dist = (c) => Math.hypot(M.ciudades[c][0] - p.x, M.ciudades[c][1] - p.y);
    const rotulos = new Map();                          // ciudad → [caja, distancia a la caja]
    for (const t of capaTexto.querySelectorAll('text')) {
      const c = t.getAttribute('data-ciudad');          // vacío: el del lugar que se ve, que no tapa
      if (c && vale(c)) { const b = t.getBBox(); rotulos.set(c, [b, aCaja(p, b)]); }
    }
    if (!raton) {
      let encima = null;
      for (const [c, [, d]] of rotulos) if (d <= 2 && (!encima || d < rotulos.get(encima)[1])) encima = c;
      if (encima) {
        const [b] = rotulos.get(encima);
        let ciudad = encima, nota = 1;
        for (const c of Object.keys(M.ciudades)) {
          if (c === encima || !vale(c) || aCaja({ x: M.ciudades[c][0], y: M.ciudades[c][1] }, b) > 2) continue;
          const n = dist(c) / 4;                        // pequeño: que el rótulo siga siendo de su ciudad
          if (n < nota) { ciudad = c; nota = n; }
        }
        return { ciudad, pos: M.ciudades[ciudad] };
      }
    }
    let ciudad = null, nota = 1.0001;
    for (const c of Object.keys(M.ciudades)) {
      if (!vale(c)) continue;
      const r = rotulos.get(c);
      let n = dist(c) / (r ? grande : chico);
      if (r && !raton && r[1] <= margen) n = Math.min(n, 1);
      if (n < nota) { ciudad = c; nota = n; }
    }
    if (ciudad) return { ciudad, pos: M.ciudades[ciudad] };
    let mejor = -1, cerca = 12;                         // entre dos puntos vecinos hay de 8 a 10
    M.puntos.forEach(([x, y], k) => {
      const d = Math.hypot(x - p.x, y - p.y);
      if (d < cerca) { mejor = k; cerca = d; }
    });
    const fila = mejor >= 0 && M.lugares && M.lugares[mejor];
    return fila ? { fila, pos: M.puntos[mejor] } : null;
  }

  /** Apaga los rótulos y marca el destino: un anillo y su nombre (con el dedo, por encima de él). */
  function apuntar(d, escala = 1, raton = true) {
    capaApunta.replaceChildren();
    svg.classList.toggle('apuntando', !!d);
    if (raton) svg.style.cursor = d ? '' : 'default';
    if (!d) return;
    const [x, y] = d.pos;
    capaApunta.append(el('circle', { cx: x, cy: y, r: Math.max(6, 7 / escala), 'stroke-width': 2 / escala }));
    const t = el('text', raton
      ? { x: x + 11 / escala, y: y - 6 / escala }
      : { x, y: y - 30 / escala, 'text-anchor': 'middle' });
    t.style.fontSize = `${13 / escala}px`;
    t.style.strokeWidth = `${3.5 / escala}px`;
    t.textContent = d.ciudad || lector(M.campos)(d.fila).nombre;
    capaApunta.append(t);
    // Que el nombre no se salga del dibujo.
    const b = t.getBBox();
    const dx = b.x < 2 ? 2 - b.x : b.x + b.width > M.ancho - 2 ? M.ancho - 2 - b.x - b.width : 0;
    const dy = b.y < 2 ? 2 - b.y : 0;
    if (dx || dy) { t.setAttribute('x', +t.getAttribute('x') + dx); t.setAttribute('y', +t.getAttribute('y') + dy); }
  }

  svg.addEventListener('pointerdown', (e) => {
    puntero = e.pointerType || 'touch';
    if (puntero === 'mouse' || !M || !D) return;
    const { p, escala } = enElDibujo(e);
    apuntar(destino(p, escala, false), escala, false);
  });
  svg.addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse' || !M || !D) return;
    const { p, escala } = enElDibujo(e);
    apuntar(destino(p, escala, true), escala, true);
  });
  // Con el dedo, si se desliza (la página se mueve) no se elige nada.
  svg.addEventListener('pointerup', (e) => { if (e.pointerType !== 'mouse') setTimeout(() => apuntar(null, 1, false), 300); });
  svg.addEventListener('pointercancel', () => apuntar(null, 1, false));
  svg.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') apuntar(null); });
  svg.addEventListener('click', (e) => {
    if (!M || !D) return;
    const { p, escala } = enElDibujo(e);
    const d = destino(p, escala, puntero === 'mouse');
    if (puntero === 'mouse') apuntar(null);
    if (!d) return;
    if (d.ciudad) { if (lugar.ciudad !== d.ciudad) elegir({ nombre: d.ciudad, ciudad: d.ciudad }); return; }
    const m = lector(M.campos)(d.fila);
    if (m.nombre !== lugar.nombre || m.provincia !== lugar.provincia) elegir(m);
  });

  arrancar();
})();
