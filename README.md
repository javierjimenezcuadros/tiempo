# El tiempo · módulo para un shot de Xataka

Un módulo del tiempo que cabe en el hueco de un shot de la portada de Xataka
(iframe de 620 px de alto, de 300 a 608 px de ancho). Diseño de Javier
Jiménez (20 de noviembre de 2026): a la izquierda, un mapa de España por puntos
con pestañas Temperatura y Lluvia; a la derecha, un buscador de ciudad, la
máxima y la mínima, y una tabla con la hora, la temperatura y la probabilidad
de lluvia. En el móvil va todo en una columna.

Dirección: <https://tiempo.americaylosovnis.workers.dev/>

## Cómo funciona

```
ECMWF Open Data ──► GitHub Actions (2 veces al día) ──► sitio/datos/AAAA-MM-DD.json
                     python -m generador                       │
                                                               ▼
                    Cloudflare (Worker de archivos estáticos) ◄── wrangler deploy
                                                               │
                    iframe del shot ──► sitio/index.html lee el JSON del día
```

- **No hay servidor.** La página es estática y cada lector descarga un JSON de
  unos 160 KB (unos 30 KB comprimido). Cloudflare aguanta el tráfico de la portada sin coste.
- **GitHub Actions** mira cada dos horas qué pasada ha publicado ECMWF (una
  consulta de un segundo) y, si hay una nueva, genera las *emisiones* que
  tocan: un JSON con la previsión de un día y los cinco siguientes. Con la
  pasada de las 00 UTC (publicada hacia media mañana), la de hoy y la de
  mañana; con la de las 12 (por la noche), la de mañana, con un día menos. Si
  no hay nada nuevo, termina en un minuto. Guarda las emisiones en el
  repositorio (así queda el archivo: cada shot con fecha conserva la semana tal
  como se dio) y publica en Cloudflare. Nunca pisa una emisión con otra de una
  pasada más antigua.
- **Por qué cada dos horas:** GitHub lanza las tareas programadas con retraso,
  a veces de horas. Decidir por lo que ECMWF ha publicado, y no por la hora,
  hace que una tarea que llega tarde haga lo mismo que habría hecho a su hora.
  El repositorio es público, así que los minutos de Actions no tienen límite. También se lanza a mano: pestaña *Actions* → *Generar el tiempo*
  → *Run workflow*. Marcando «Solo publicar la web» no genera datos: sube la
  página tal como está en el repositorio (para cambios de diseño, en un minuto).
- El shot de primera hora sale con la pasada de la noche anterior; a media
  mañana (o en cuanto GitHub llegue) se actualiza con la de las 00.

## De dónde sale cada cifra

| Cifra | Fuente |
|---|---|
| Máxima, mínima, lluvia del día (mapa y ficha) | IFS determinista de ECMWF (mx2t3, mn2t3, tp), celdas de 0,25° |
| Cada 3 horas | 2t y tp del determinista (ECMWF Open Data no da pasos de una hora) |
| Probabilidad de lluvia y seguridad | Los 50 escenarios del ensemble de ECMWF, misma pasada (máxima y mínima, solo con los tramos de la tarde y de la madrugada, para no descargar 2,5 GB) |
| Lo normal | ERA5 1991-2020 (Copernicus), máximas y mínimas diarias |

Cada ciudad toma la celda cercana con tierra y altitud parecida, corregida por
altitud (6,5 °C por km, con tope de ±1,5 °C). Canarias no tiene normal: la
rejilla de ERA5 mezcla las islas con el mar.

## Archivos

- `generador/tiempo.py`: descarga, cálculo y JSON del día. `python -m generador`.
- `datos_fijos/`: ciudades (celda, corrección y normales de cada día del año)
  y celdas del mapa. Las calcula `herramientas/preparar_tablas.py` en el Mac,
  con el entorno de BenBaso (necesita ETOPO y la climatología ERA5). Solo hay
  que repetirlo si cambian las ciudades o el dibujo.
- `sitio/`: lo que se publica (página, estilos, `mapa.json` y `datos/`).
- `pruebas/incrustado.html`: simula el shot y da el código para pegar.
- `.github/workflows/generar.yml`: la tarea programada.
- `wrangler.jsonc`: el Worker de Cloudflare (nombre `tiempo`).

## Puesta en marcha (una vez)

1. Repositorio en GitHub con este código (público: así los minutos de Actions no tienen límite).
2. En Cloudflare: *My Profile* → *API Tokens* → *Create Token* → plantilla
   **Edit Cloudflare Workers**, limitada a tu cuenta. Copia el token.
3. En GitHub: *Settings* → *Secrets and variables* → *Actions* →
   *New repository secret*, con el nombre `CLOUDFLARE_API_TOKEN` y el token
   como valor (o `gh secret set CLOUDFLARE_API_TOKEN` en el Terminal).
4. *Actions* → *Generar el tiempo* → *Run workflow*.

## En local

```bash
pip install -r requirements.txt
python -m generador --dia 2026-11-21     # unos 2 minutos, ~450 MB de descargas en cache/
python -m pytest -q tests
python3 -m http.server 8127              # y abrir http://localhost:8127/pruebas/incrustado.html
```

## Código del shot

```html
<iframe src="https://tiempo.americaylosovnis.workers.dev/" title="El tiempo"
  width="100%" height="620"
  style="border:0;display:block;max-width:608px;margin:0 auto;border-radius:12px"
  loading="lazy"></iframe>
```

Con `?d=AAAA-MM-DD` el shot se queda con la previsión de esa semana. Con
`&ciudad=Sevilla` abre en esa ciudad; con `&vista=lluvia`, en la pestaña de
lluvia, y con `&ficha=dias`, con la lista de los próximos días a la vista.

## Municipios

El buscador encuentra los 8.132 municipios del Nomenclátor Geográfico de
Municipios y Entidades de Población del IGN (edición 2026, en
`datos_fijos/fuentes/`; obra derivada de NGMEP CC-BY 4.0 ign.es).

- Cada municipio toma la celda del modelo más parecida (cercana, con tierra y
  de altitud parecida), con la corrección por altitud desde la de su núcleo
  principal (tope de ±1,5 °C; lo alcanzan unos 300 pueblos de sierra o de costa).
  Caen en 836 celdas, repartidas en 31 zonas de 2° × 2°.
- La emisión principal sigue llevando las 59 ciudades. La previsión de cada
  celda va aparte, en `sitio/datos/AAAA-MM-DD/z/<zona>.json` (unos 18 KB por
  zona, 4 KB comprimido), que la página solo descarga al elegir un municipio de esa zona, y le
  aplica la corrección por altitud. La lista de municipios (`sitio/municipios.json`,
  ~450 KB, ~120 KB comprimida) solo se descarga al tocar el buscador.
- **Tocar el mapa:** cada punto elige el municipio más poblado de los que caen
  en él (cada municipio cae en el punto más cercano a su núcleo; los puntos
  donde no cae ninguno toman el más cercano). Va calculado en `mapa.json`
  («lugares»), que por eso pesa ~17 KB comprimido. Tocar el rótulo de una
  ciudad elige esa ciudad.
- **Marca de las tablas:** `preparar_tablas.py` pone la misma marca («tablas»)
  en `mapa.json`, `municipios.json` y `celdas.json`, y el generador la copia en
  cada archivo de zona. La página guarda el lugar elegido con su zona, su celda
  y esa marca, así que al volver abre sin descargar la lista de municipios; si
  la marca ya no coincide (se rehicieron las tablas), lo busca por el nombre.
  Tampoco usa un archivo de zona hecho con otras tablas.
- Los archivos por zona se guardan dos semanas; las emisiones, siempre. En un
  shot más antiguo, al elegir un municipio se ve la ciudad más cercana, con aviso.
- Las tablas las rehace `herramientas/preparar_tablas.py` (en el Mac, con el
  entorno de BenBaso).

## Próximos días

La ficha tiene un interruptor «Por horas | 6 días». En «6 días», una fila por
día (en el móvil, una columna) con la máxima, la mínima y la probabilidad de
lluvia (la diferencia con lo normal va solo en las cajas). Tocar un día cambia todo el módulo a ese
día: mapa, titular, cajas y tabla por horas. Son seis y no siete porque hasta
el paso 144 ECMWF Open Data da datos cada 3 horas; el séptimo caería en pasos
de 6 y necesitaría otra tabla. La versión AMP del shot no ejecuta iframes: necesita una imagen y un
enlace de respaldo (pendiente).

## Con qué ciudad abre

Sin `&ciudad`, con la última que eligió el lector en ese navegador; si no hay
ninguna, con Las Palmas cuando la hora del navegador es la de Canarias, y si
no, con Madrid. No se pide la ubicación (se descartó un botón «Usar mi
ubicación» de momento: necesitaría `allow="geolocation"` en el iframe y que
portada lo acepte, porque Chrome muestra el aviso como si lo pidiera
xataka.com).

## Privacidad

Lo único que se guarda es el lugar elegido (localStorage, clave
`tiempo.lugar`: nombre, provincia y, en los municipios, zona, celda,
corrección, sitio en el dibujo y marca de las tablas), y solo cuando el lector
lo elige. La primera versión guardaba `tiempo.ciudad`; la página lo borra al
guardar el nuevo. No hay cookies,
medición ni recursos de terceros. Está contado en `sitio/privacidad.html`,
enlazada en el pie del módulo: si cambia lo que la página guarda o envía, hay
que cambiarla también.
