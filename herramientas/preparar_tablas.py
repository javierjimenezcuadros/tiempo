"""Prepara las tablas fijas del módulo: ciudades y puntos del mapa.

Escribe:
  - datos_fijos/ciudades.json: cada ciudad con su celda del modelo, la
    corrección por altitud y la máxima y la mínima normales (ERA5 1991-2020)
    de cada día del año.
  - datos_fijos/puntos.json: las celdas de 0,25° que forman el mapa de España.
  - sitio/mapa.json: dónde va cada punto y cada ciudad en el dibujo.
  - datos_fijos/celdas.json: las celdas donde caen los ~8.100 municipios del
    nomenclátor del IGN, con su zona de 2° × 2° y sus normales.
  - sitio/municipios.json: cada municipio con su provincia, su celda, su
    corrección por altitud y su sitio en el dibujo, de más a menos poblado.
    Obra derivada de NGMEP CC-BY 4.0 ign.es (datos_fijos/fuentes/).

Se ejecuta en el Mac con el entorno de BenBaso, porque necesita datos que
solo están allí: el relieve ETOPO 2022 y la climatología ERA5 de máximas y
mínimas diarias. Solo hay que repetirlo si cambia la lista de ciudades o el
dibujo del mapa:

    ~/miniconda3/envs/meteoxataka/bin/python herramientas/preparar_tablas.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
import unicodedata
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
FUENTE_MUNICIPIOS = FIJOS / "fuentes" / "MUNICIPIOS_NGMEP_2026.csv"
# Ciudades cuyo municipio no se llama igual (ni en una de sus partes «a/b»).
MUNICIPIO_DE_CIUDAD = {
    "Castellón": "Castelló de la Plana/Castellón de la Plana",
    "Vitoria": "Vitoria-Gasteiz",
    "Las Palmas": "Las Palmas de Gran Canaria",
}

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
    with xr.open_dataset(ETOPO) as ds:
        celdas_m, lista_m = preparar_municipios(lats, lons, tierra, oro, clim, ds["z"])
    (FIJOS / "celdas.json").write_text(json.dumps({
        "version": 1,
        "fuentes": "Municipios: obra derivada de NGMEP CC-BY 4.0 ign.es. Celdas: ECMWF Open Data "
                   "(CC BY 4.0). Normal: ERA5 1991-2020 (Copernicus).",
        "celdas": celdas_m,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITIO / "municipios.json").write_text(json.dumps({
        "version": 1, "fuente": "Obra derivada de NGMEP CC-BY 4.0 ign.es",
        "campos": ["nombre", "provincia", "zona", "celda", "corr", "x", "y", "ciudad"],
        "lista": lista_m,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(ciudades)} ciudades · {len(puntos)} puntos")
    for c in ciudades:
        print(f"  {c['nombre']:24s} alt {c['altitud']:5d} celda {c['altitud_celda']:5d} "
              f"corr {c['correccion']:+.2f} normal max (21 nov) "
              f"{c['normal_max'][dia_21nov()] if c['normal_max'] else '—'}")


def llano(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


def leer_municipios() -> list[dict]:
    """La tabla MUNICIPIOS del nomenclátor: nombre, provincia, población, coordenadas y altitud."""
    def num(v):
        return float(v.replace(",", ".")) if v and v.strip() else None

    out = []
    with open(FUENTE_MUNICIPIOS, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            out.append({
                "ine": r["COD_INE"], "nombre": r["NOMBRE_ACTUAL"].strip(),
                # «Alacant/Alicante» → «Alicante»: la última parte es la castellana
                "provincia": r["PROVINCIA"].split("/")[-1].strip(),
                "poblacion": int(r["POBLACION_MUNI"] or 0),
                "lat": num(r["LATITUD_ETRS89_REGCAN95"]), "lon": num(r["LONGITUD_ETRS89_REGCAN95"]),
                "altitud": num(r["ALTITUD"]),
            })
    return out


def ciudades_en_municipios(ciudades: list[str], municipios: list[dict]) -> dict[str, str]:
    """{código INE: ciudad} para enlazar cada una de las 59 ciudades con su municipio."""
    out = {}
    for ciudad in ciudades:
        objetivo = llano(MUNICIPIO_DE_CIUDAD.get(ciudad, ciudad))
        cand = [m for m in municipios
                if llano(m["nombre"]) == objetivo or any(llano(p) == objetivo for p in m["nombre"].split("/"))]
        if not cand:
            print(f"Aviso: no encuentro el municipio de {ciudad}")
            continue
        out[max(cand, key=lambda m: m["poblacion"])["ine"]] = ciudad
    return out


def zona_de(lat: float, lon: float) -> str:
    """Zona de 2° × 2° (esquina suroeste): «40_-4»."""
    return f"{2 * math.floor(lat / 2)}_{2 * math.floor(lon / 2)}"


def preparar_municipios(lats, lons, tierra, oro, clim, etopo) -> tuple[list[dict], list[list]]:
    """Celda, corrección y sitio en el dibujo de cada municipio; normales de cada celda."""
    municipios = leer_municipios()
    a_ciudad = ciudades_en_municipios(list(CIUDADES), municipios)
    indice, celdas, lista = {}, [], []
    for m in sorted(municipios, key=lambda m: -m["poblacion"]):
        if m["lat"] is None:
            continue
        alt = m["altitud"]
        if alt is None:
            alt = max(0.0, float(etopo.sel(lat=m["lat"], lon=m["lon"], method="nearest")))
        n = elegir_nodo(m["lat"], m["lon"], lats, lons, tierra, oro, alt)
        clave = (n.lat, n.lon)
        if clave not in indice:
            indice[clave] = len(celdas)
            celdas.append({"lat": n.lat, "lon": n.lon, "zona": zona_de(n.lat, n.lon),
                           "altitud": round(n.altitud_celda), "normal_max": None, "normal_min": None})
        k = indice[clave]
        p = xy(m["lat"], m["lon"])
        lista.append([m["nombre"], m["provincia"], celdas[k]["zona"], k, round(n.correccion, 1),
                      None if p is None else round(p[0]), None if p is None else round(p[1]),
                      a_ciudad.get(m["ine"])])
    for c in celdas:
        if c["lat"] >= 30:   # Canarias sin normal, como las ciudades
            for kind in ("max", "min"):
                c0 = clim[kind][0]
                i = int(np.argmin(np.abs(c0.lats - c["lat"])))
                j = int(np.argmin(np.abs(c0.lons - c["lon"])))
                c[f"normal_{kind}"] = [round(float(f.data[i, j]), 1) for f in clim[kind]]
    print(f"{len(lista)} municipios en {len(celdas)} celdas y {len({c['zona'] for c in celdas})} zonas; "
          f"{sum(1 for x in lista if x[7])} enlazados con su ciudad")
    return celdas, lista


def dia_21nov() -> int:
    return date(2024, 11, 21).timetuple().tm_yday - 1


if __name__ == "__main__":
    main()
