"""Prepara las tablas fijas del módulo: ciudades y puntos del mapa.

Escribe:
  - datos_fijos/ciudades.json: cada ciudad con su celda del modelo, la
    corrección por altitud y la máxima y la mínima normales (ERA5 1991-2020)
    de cada día del año.
  - datos_fijos/puntos.json: las celdas de 0,25° que forman el mapa de España.
  - sitio/mapa.json: dónde va cada punto y cada ciudad en el dibujo.

Se ejecuta en el Mac con el entorno de BenBaso, porque necesita datos que
solo están allí: el relieve ETOPO 2022 y la climatología ERA5 de máximas y
mínimas diarias. Solo hay que repetirlo si cambia la lista de ciudades o el
dibujo del mapa:

    ~/miniconda3/envs/meteoxataka/bin/python herramientas/preparar_tablas.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
BENBASO = Path.home() / "Dropbox" / "MacBook" / "benbaso"
sys.path[:0] = [str(RAIZ), str(BENBASO)]

from benbaso.charts._common import CITIES                      # noqa: E402
from benbaso.processing.masks import country_mask              # noqa: E402
from benbaso.sources.era5 import t2m_daily_extreme_climatology  # noqa: E402
from generador.tiempo import (                                  # noqa: E402
    CACHE, FIJOS, SITIO, elegir_nodo, leer,
)

ETOPO = BENBASO / "data" / "elevation" / "etopo2022_europe.nc"

# Las 45 de BenBaso (43 capitales, Vigo y Gijón) más las capitales que faltaban,
# Ceuta, Melilla y algunas ciudades grandes o capitales autonómicas.
EXTRA = {
    "Ávila":       (40.66, -4.70),
    "Segovia":     (40.95, -4.12),
    "Zamora":      (41.50, -5.75),
    "Palencia":    (42.01, -4.53),
    "Guadalajara": (40.63, -3.17),
    "Cuenca":      (40.07, -2.13),
    "Pontevedra":  (42.43, -8.64),
    "Ceuta":       (35.89, -5.32),
    "Melilla":     (35.29, -2.94),
    "Santiago de Compostela": (42.88, -8.54),
    "Mérida":      (38.92, -6.34),
    "Cartagena":   (37.60, -0.98),
    "Elche":       (38.27, -0.70),
    "Jerez de la Frontera": (36.69, -6.14),
}
CIUDADES = {**CITIES, **EXTRA}

# Rotuladas en el mapa y hacia dónde va el texto respecto al punto.
ETIQUETAS = {
    "Madrid": "der", "Barcelona": "abajo", "Valencia": "izq", "Sevilla": "der",
    "Bilbao": "der", "A Coruña": "der", "Zaragoza": "izq", "Málaga": "abajo",
    "Palma": "abajo", "Las Palmas": "abajo",
}

# Dibujo: proyección sencilla (equirrectangular corregida por la latitud).
K = 40.0
LON0, LON1, LAT_TOP, LAT_BOT = -9.6, 4.6, 44.0, 35.8
COS_P = np.cos(np.radians(40))
W = (LON1 - LON0) * COS_P * K
H_PEN = (LAT_TOP - LAT_BOT) * K
# Canarias, en un recuadro abajo a la derecha (bajo Baleares, sobre el mar).
C_LON0, C_LON1, C_LAT_TOP, C_LAT_BOT = -18.3, -13.25, 29.45, 27.55
COS_C = np.cos(np.radians(28.5))
C_W = (C_LON1 - C_LON0) * COS_C * K
C_H = (C_LAT_TOP - C_LAT_BOT) * K
C_X0, C_Y0 = W - C_W - 2, H_PEN - 32
H = C_Y0 + C_H + 4


def xy(lat: float, lon: float) -> list[float] | None:
    if lat < 30:
        x, y = C_X0 + (lon - C_LON0) * COS_C * K, C_Y0 + (C_LAT_TOP - lat) * K
    else:
        if not (LON0 <= lon <= LON1 and LAT_BOT <= lat <= LAT_TOP):
            return None
        x, y = (lon - LON0) * COS_P * K, (LAT_TOP - lat) * K
    return [round(float(x), 1), round(float(y), 1)]


def campos_fijos():
    """Fracción de tierra y orografía (m) del modelo, de la última pasada."""
    destino = CACHE / "estaticos.grib2"
    if not destino.exists():
        from ecmwf.opendata import Client
        destino.parent.mkdir(parents=True, exist_ok=True)
        Client(source="ecmwf").retrieve(type="fc", step=0, param=["lsm", "z"],
                                        levtype="sfc", target=str(destino))
    lsm, _, lats, lons = leer(destino, "lsm")
    z, _, _, _ = leer(destino, "z")
    return lats, lons, lsm[0], z[0] / 9.80665


def main() -> None:
    import xarray as xr

    lats, lons, tierra, oro = campos_fijos()
    with xr.open_dataset(ETOPO) as ds:
        altitudes = {n: max(0.0, float(ds["z"].sel(lat=la, lon=lo, method="nearest")))
                     for n, (la, lo) in CIUDADES.items()}

    # Normales de cada día del año (2024, bisiesto: 366 días)
    dias = [date(2024, 1, 1) + timedelta(days=k) for k in range(366)]
    clim = {k: [t2m_daily_extreme_climatology(datetime(d.year, d.month, d.day, 12), kind=k)
                for d in dias] for k in ("max", "min")}
    aprox = [d for d, c in zip(dias, clim["max"]) if "aprox" in str(c.metadata.get("kind", ""))]
    if aprox:
        print(f"Aviso: normal aproximada en {len(aprox)} días (falta la climatología diaria)")

    ciudades = []
    for nombre, (la, lo) in CIUDADES.items():
        n = elegir_nodo(la, lo, lats, lons, tierra, oro, altitudes[nombre])
        fila = {"nombre": nombre, "lat": la, "lon": lo, "altitud": round(altitudes[nombre]),
                "nodo": [n.lat, n.lon], "altitud_celda": round(n.altitud_celda),
                "correccion": round(n.correccion, 2), "normal_max": None, "normal_min": None}
        if la >= 30:   # Canarias sin normal: ERA5 (~31 km) mezcla las islas con el mar
            for k in ("max", "min"):
                c0 = clim[k][0]
                i = int(np.argmin(np.abs(c0.lats - n.lat)))
                j = int(np.argmin(np.abs(c0.lons - n.lon)))
                fila[f"normal_{k}"] = [round(float(c.data[i, j]), 1) for c in clim[k]]
        ciudades.append(fila)

    # Puntos del mapa: celdas con centro en España, más las islas por su tierra.
    LON, LAT = np.meshgrid(lons, lats)
    espana = country_mask(lons, lats, ("Spain",))
    canarias = (LON >= C_LON0) & (LON <= C_LON1) & (LAT >= C_LAT_BOT) & (LAT <= C_LAT_TOP)
    baleares = (LON > 1.0) & (LAT < 40.3) & (LAT > 38.5)
    dentro = (espana & (LAT > 30)) | ((canarias | baleares) & (tierra >= 0.4))
    celdas, puntos = [], []
    for i, j in zip(*np.nonzero(dentro)):
        p = xy(float(lats[i]), float(lons[j]))
        if p is not None:
            celdas.append([float(lats[i]), float(lons[j])])
            puntos.append(p)

    FIJOS.mkdir(parents=True, exist_ok=True)
    SITIO.mkdir(parents=True, exist_ok=True)
    (FIJOS / "ciudades.json").write_text(json.dumps({
        "version": 1,
        "fuentes": "Celda y orografía: ECMWF Open Data (CC BY 4.0). Altitud: ETOPO 2022 (NOAA). "
                   "Normal: ERA5 1991-2020, máximas y mínimas diarias (Copernicus).",
        "ciudades": ciudades,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (FIJOS / "puntos.json").write_text(json.dumps({"celdas": celdas}), encoding="utf-8")
    (SITIO / "mapa.json").write_text(json.dumps({
        "version": 1,
        "ancho": round(float(W), 1), "alto": round(float(H), 1),
        "recuadro": [round(float(v), 1) for v in (C_X0, C_Y0, C_W, C_H)],
        "puntos": puntos,
        "ciudades": {c["nombre"]: xy(c["lat"], c["lon"]) for c in ciudades},
        "etiquetas": ETIQUETAS,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(ciudades)} ciudades · {len(puntos)} puntos")
    for c in ciudades:
        print(f"  {c['nombre']:24s} alt {c['altitud']:5d} celda {c['altitud_celda']:5d} "
              f"corr {c['correccion']:+.2f} normal max (21 nov) "
              f"{c['normal_max'][dia_21nov()] if c['normal_max'] else '—'}")


def dia_21nov() -> int:
    return date(2024, 11, 21).timetuple().tm_yday - 1


if __name__ == "__main__":
    main()
