/* Módulo del tiempo. Lee mapa.json (dónde va cada punto y cada ciudad, fijo)
   y datos/<fecha>.json: la «emisión» de ese día, con su previsión y la de los
   cinco siguientes tal como se dio ese día (lo genera GitHub dos veces al día).
   Tocar un día en «6 días» cambia todo el módulo a ese día.

   Dirección:
     /                 el día de hoy (o el más cercano que haya)
     /?d=2026-11-21    ese día, para siempre (el shot de ese día hace de archivo)
     &ciudad=Sevilla   ciudad con la que abre
     &vista=lluvia     pestaña con la que abre
     &ficha=dias       la ficha abre en «6 días» en vez de «Por horas»

   Sin &ciudad, abre en la última ciudad que eligió el lector en ese navegador;
   si no hay, en Las Palmas cuando su hora es la de Canarias, y si no, en Madrid.

   Lo único que guarda es el nombre de esa ciudad (localStorage, clave
   tiempo.ciudad), y solo cuando el lector la elige. No envía nada. Si cambia lo
   que guarda o envía, hay que cambiar también privacidad.html. */
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
  let vistaFicha = 'horas';
  let vista = params.get('vista') === 'lluvia' ? 'lluvia' : 'temp';
  let ciudad = 'Madrid';
  let circulos = [];
  const svg = $('mapa');
  const capa = el('g');
  const capaTexto = el('g');

  // --- Datos -----------------------------------------------------------
  async function leer(url) {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  }

  function hoy() {
    const d = new Date();
    return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  }

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

  // --- Mapa ------------------------------------------------------------
  function montarMapa() {
    svg.setAttribute('viewBox', `0 0 ${M.ancho} ${M.alto}`);
    const [rx, ry, rw, rh] = M.recuadro;
    svg.append(el('rect', { class: 'recuadro', x: rx - 4, y: ry - 4, width: rw + 8, height: rh + 8, rx: 6 }));
    svg.append(capa, capaTexto);
    circulos = M.puntos.map(([x, y]) => {
      const c = el('circle', { cx: x, cy: y, r: 3.1 });
      capa.append(c);
      return c;
    });
  }

  function valorCiudad(nombre) {
    const f = D.ciudades[nombre];
    if (vista === 'lluvia') return f.lluvia >= 0.5 ? `${Math.round(f.lluvia)} mm` : '';
    return `${f.max}°`;
  }

  function rotulo(nombre, lado) {
    const [x, y] = M.ciudades[nombre];
    const pos = { der: [x + 7, y + 5, 'start'], izq: [x - 7, y + 5, 'end'], abajo: [x, y + 19, 'middle'] }[lado];
    const t = el('text', { x: pos[0], y: pos[1], 'text-anchor': pos[2] });
    const corto = { 'Santa Cruz de Tenerife': 'S. C. Tenerife', 'Santiago de Compostela': 'Santiago',
                    'Jerez de la Frontera': 'Jerez' }[nombre] || nombre;
    t.append(document.createTextNode(`${corto} `));
    const v = el('tspan', { class: 'valor' });
    v.textContent = valorCiudad(nombre);
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
      rotulo(nombre, lado);
    }
    const pos = M.ciudades[ciudad];
    if (pos) {
      capaTexto.append(el('circle', { class: 'anillo', cx: pos[0], cy: pos[1], r: 7 }));
      if (!(ciudad in M.etiquetas)) rotulo(ciudad, pos[0] > M.ancho * 0.7 ? 'izq' : 'der');
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

  // --- Ciudad ----------------------------------------------------------
  function nota(dif) {
    if (dif === null) return ['Sin referencia en Canarias', ''];
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
    const f = D.ciudades[ciudad];
    $('buscar').value = ciudad;
    $('vmax').textContent = `${f.max}°`;
    $('vmin').textContent = `${f.min}°`;
    for (const [id, dif] of [['nmax', f.max_dif], ['nmin', f.min_dif]]) {
      const [txt, cls] = nota(dif);
      $(id).textContent = txt;
      $(id).className = `nota ${cls}`;
    }
    $('lluvia').innerHTML = textoLluvia(f);
    if (f.seguridad) {
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
      return `<li><span>${h} h</span><span class="t">${t}°</span>`
        + `<span class="barra-p"><b style="width:${ancho}%"></b></span>`
        + `<span class="p${nada}">${txt}</span></li>`;
    }).join('');
    listaDias();
  }

  // --- Próximos días ---------------------------------------------------------
  function fechaLocal(d) {
    return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  }
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
      const f = dia.ciudades[ciudad];
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
    if (!E.dias[k] || !E.dias[k].ciudades[ciudad]) return;
    activo = k;
    D = E.dias[k];
    cabecera();
    panel();
    pintar();
  }

  function mostrarFicha(cual) {
    vistaFicha = cual;
    document.querySelectorAll('.ficha-vista button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.ficha === cual)));
    $('horas').hidden = cual !== 'horas';
    $('dias').hidden = cual !== 'dias';
  }

  /** Elección del lector (buscador o mapa): se recuerda para la próxima vez. */
  function elegir(nombre) {
    if (!D.ciudades[nombre]) return;
    ciudad = nombre;
    recordar(nombre);
    panel();
    pintar();
  }

  // --- Ciudad recordada y zona horaria -------------------------------------
  // En un iframe de otro sitio el almacenamiento puede estar bloqueado o
  // borrarse (Safari lo limita): nada de esto puede romper el módulo.
  const CLAVE = 'tiempo.ciudad';
  function recordada() {
    try { return localStorage.getItem(CLAVE); } catch (e) { return null; }
  }
  function recordar(nombre) {
    try { localStorage.setItem(CLAVE, nombre); } catch (e) { /* sin almacenamiento */ }
  }
  function horaDeCanarias() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone === 'Atlantic/Canary'; } catch (e) { return false; }
  }

  /** Ciudad con la que abre: la de la dirección, la recordada, Las Palmas o Madrid. */
  function ciudadInicial() {
    const existe = (n) => n && nombres.find((x) => llano(x) === llano(n));
    return existe(params.get('ciudad'))
      || existe(recordada())
      || (horaDeCanarias() && D.ciudades['Las Palmas'] ? 'Las Palmas' : null)
      || (D.ciudades.Madrid ? 'Madrid' : nombres[0]);
  }

  // --- Buscador --------------------------------------------------------
  const buscar = $('buscar'), sug = $('sugerencias');
  let nombres = [];
  let activa = 0;
  function sugerir() {
    const q = llano(buscar.value.trim());
    const lista = (q ? nombres.filter((n) => llano(n).includes(q)) : nombres).slice(0, 8);
    activa = 0;
    sug.innerHTML = lista.map((n, i) => `<li role="option" data-n="${n}" class="${i === 0 ? 'activa' : ''}">${n}</li>`).join('')
      || '<li class="vacio">No está en la lista</li>';
    sug.hidden = false;
  }
  function cerrar() { sug.hidden = true; buscar.value = ciudad; buscar.blur(); }
  buscar.addEventListener('focus', () => { buscar.select(); sugerir(); });
  buscar.addEventListener('input', sugerir);
  buscar.addEventListener('keydown', (e) => {
    const items = [...sug.querySelectorAll('li[data-n]')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      activa = (activa + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % Math.max(1, items.length);
      items.forEach((li, i) => li.classList.toggle('activa', i === activa));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (items[activa]) elegir(items[activa].dataset.n);
      cerrar();
    } else if (e.key === 'Escape') {
      cerrar();
    }
  });
  sug.addEventListener('pointerdown', (e) => {
    const li = e.target.closest('li[data-n]');
    if (!li) return;
    e.preventDefault();
    elegir(li.dataset.n);
    cerrar();
  });
  buscar.addEventListener('blur', () => setTimeout(() => { sug.hidden = true; buscar.value = ciudad; }, 150));

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
    nombres = Object.keys(D.ciudades).sort((a, b) => a.localeCompare(b, 'es'));
    ciudad = ciudadInicial();

    cabecera();
    $('pie').textContent = `Datos: ECMWF (CC BY 4.0) · Lo normal: ERA5 1991-2020 (Copernicus) · Pasada de las ${E.pasada_texto}`;
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

  // Tocar el mapa elige la ciudad más cercana (si está a menos de ~1°)
  svg.addEventListener('click', (e) => {
    if (!M || !D) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    let mejor = null, dist = 45;
    for (const [nombre, pos] of Object.entries(M.ciudades)) {
      if (!pos || !D.ciudades[nombre]) continue;
      const d = Math.hypot(pos[0] - p.x, pos[1] - p.y);
      if (d < dist) { mejor = nombre; dist = d; }
    }
    if (mejor) elegir(mejor);
  });

  arrancar();
})();
