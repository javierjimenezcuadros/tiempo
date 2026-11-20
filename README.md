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
  unos 27 KB. Cloudflare aguanta el tráfico de la portada sin coste.
- **GitHub Actions** ejecuta el generador a las 9:20 y a las 21:20 UTC, cuando
  ECMWF ya ha publicado la pasada de las 00 y la de las 12. Genera hoy y mañana,
  guarda los JSON en el repositorio (así queda el archivo) y publica en
  Cloudflare. También se lanza a mano: pestaña *Actions* → *Generar el tiempo*
  → *Run workflow*. Marcando «Solo publicar la web» no genera datos: sube la
  página tal como está en el repositorio (para cambios de diseño, en un minuto).
- El shot de primera hora sale con la pasada de la noche anterior; a media
  mañana se actualiza con la de las 00.

## De dónde sale cada cifra

| Cifra | Fuente |
|---|---|
| Máxima, mínima, lluvia del día (mapa y ficha) | IFS determinista de ECMWF (mx2t3, mn2t3, tp), celdas de 0,25° |
| Cada 3 horas | 2t y tp del determinista (ECMWF Open Data no da pasos de una hora) |
| Probabilidad de lluvia y seguridad | Los 50 escenarios del ensemble de ECMWF, misma pasada |
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

1. Repositorio privado en GitHub con este código.
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

Con `?d=AAAA-MM-DD` el shot se queda con la previsión de ese día. Con
`&ciudad=Sevilla` abre en esa ciudad y con `&vista=lluvia`, en la pestaña de
lluvia. La versión AMP del shot no ejecuta iframes: necesita una imagen y un
enlace de respaldo (pendiente).

## Con qué ciudad abre

Sin `&ciudad`, con la última que eligió el lector en ese navegador; si no hay
ninguna, con Las Palmas cuando la hora del navegador es la de Canarias, y si
no, con Madrid. No se pide la ubicación (se descartó un botón «Usar mi
ubicación» de momento: necesitaría `allow="geolocation"` en el iframe y que
portada lo acepte, porque Chrome muestra el aviso como si lo pidiera
xataka.com).

## Privacidad

Lo único que se guarda es el nombre de la ciudad elegida (localStorage,
clave `tiempo.ciudad`), y solo cuando el lector la elige. No hay cookies,
medición ni recursos de terceros. Está contado en `sitio/privacidad.html`,
enlazada en el pie del módulo: si cambia lo que la página guarda o envía, hay
que cambiarla también.
