"""Generador del módulo del tiempo para un shot de la portada de Xataka.

Escribe, para cada día, un JSON en sitio/datos/ que la página (sitio/index.html)
pinta dentro de un iframe de 620 px de alto: un mapa de España por puntos (uno
por celda del modelo) con la máxima, la mínima y la lluvia, y la ficha de cada
ciudad con su previsión cada 3 horas.

De dónde sale cada cifra (ECMWF Open Data, licencia CC BY 4.0):
  - Máxima, mínima y lluvia del día: IFS determinista, con mx2t3/mn2t3, que no
    pierden el pico entre dos salidas del modelo.
  - Cada 3 horas: temperatura (2t) y lluvia (tp) del determinista. ECMWF Open
    Data no da pasos de una hora.
  - Probabilidad de lluvia y seguridad: los 50 escenarios del ensemble de la
    MISMA pasada. La horquilla se centra en el valor determinista para que el
    mapa y la ficha digan la misma cifra; el ensemble pone la anchura.
  - Lo normal: ERA5 1991-2020 (Copernicus), precalculado por ciudad y día del
    año en datos_fijos/ciudades.json (ver herramientas/preparar_tablas.py).

No necesita nada del Mac: solo descarga de ECMWF y las tablas de datos_fijos/.
Así puede correr en GitHub Actions dos veces al día.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
SITIO = RAIZ / "sitio"
DATOS = SITIO / "datos"
FIJOS = RAIZ / "datos_fijos"
CACHE = Path(os.environ.get("TIEMPO_CACHE", RAIZ / "cache"))
TZ = ZoneInfo("Europe/Madrid")
VERSION = 1

# Región que se lee de cada GRIB: Península, Baleares, Canarias, Ceuta y Melilla.
LAT_N, LAT_S = 44.6, 27.3
LON_W, LON_E = -18.6, 4.7

PASO_MAX = 144          # último paso cada 3 h de las pasadas 00 y 12 UTC
LLUVIA_MIN = 1.0        # mm en el día: a partir de aquí, «llueve»
LLUVIA_FUERTE = 10.0    # mm en el día
LLUVIA_FRANJA = 0.2     # mm en 3 h: a partir de aquí, esa franja «llueve»

# Fuentes de ECMWF Open Data, por orden: el portal y, si falla, la copia en AWS.
FUENTES = [f for f in (os.environ.get("TIEMPO_FUENTE", "ecmwf"), "aws") if f]

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def dia_texto(d: date) -> str:
    """'sábado 21 de noviembre'."""
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"


def dia_del_ano(d: date) -> int:
    """Índice 0-365 en un año bisiesto, para las tablas de normales."""
    return date(2024, d.month, d.day).timetuple().tm_yday - 1


def a_utc(d: date) -> datetime:
    """Medianoche peninsular de `d`, en UTC sin zona."""
    return datetime.combine(d, time(0), tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def hora_local(t_utc: datetime) -> int:
    return t_utc.replace(tzinfo=timezone.utc).astimezone(TZ).hour


@dataclass
class Ventana:
    """Pasos del modelo que cubren un día peninsular."""
    instantes: list[int]    # 2t cada 3 h dentro del día
    extremos: list[int]     # tramos de mx2t3/mn2t3 cuyo punto medio cae en el día
    tp: list[int]           # pasos de tp necesarios (acumulado desde el inicio)
    tp_ini: int             # inicio y fin del acumulado del día
    tp_fin: int


def ventana(run: datetime, dia: date) -> Ventana:
    """Traduce el día a pasos de la pasada `run`.

    Raises:
        ValueError si la pasada no cubre el día: empezó más de 3 h después de
        la medianoche o el día acaba después del paso 144.
    """
    h0 = (a_utc(dia) - run).total_seconds() / 3600
    h1 = (a_utc(dia + timedelta(days=1)) - run).total_seconds() / 3600
    if h0 < -3 or h1 > PASO_MAX + 1.5:
        raise ValueError(f"La pasada de las {run:%H} UTC del {run:%d/%m} no cubre el {dia:%d/%m}.")
    pasos = list(range(0, PASO_MAX + 1, 3))
    instantes = [s for s in pasos if h0 <= s < h1]
    extremos = [s for s in pasos if s > 0 and h0 <= s - 1.5 < h1]
    tp_ini = min(pasos, key=lambda s: abs(s - h0))
    tp_fin = min(pasos, key=lambda s: abs(s - h1))
    tp = sorted({tp_ini, tp_fin, *instantes, *(s - 3 for s in instantes if s >= 3)})
    return Ventana(instantes, extremos, tp, tp_ini, tp_fin)


def pasadas_candidatas(dia: date, ahora: datetime | None = None) -> list[datetime]:
    """Pasadas 00/12 UTC que cubren el día, de la más reciente a la más antigua."""
    ahora = ahora or datetime.utcnow()
    base = ahora.replace(minute=0, second=0, microsecond=0)
    base = base.replace(hour=12 if base.hour >= 12 else 0)
    out = []
    for k in range(6):
        run = base - timedelta(hours=12 * k)
        try:
            ventana(run, dia)
        except ValueError:
            continue
        out.append(run)
    return out


# ---------------------------------------------------------------------------
# Del grid del modelo a la ciudad
# ---------------------------------------------------------------------------

GRADIENTE = 0.0065       # °C por metro (atmósfera estándar)
CORRECCION_MAX = 1.5     # °C


@dataclass
class Nodo:
    """Celda del modelo que representa a una ciudad."""
    lat: float
    lon: float
    altitud_celda: float
    altitud_ciudad: float

    @property
    def correccion(self) -> float:
        """Grados que se suman al valor de la celda para llevarlo a la ciudad.

        Con tope de ±1,5 °C: si hace falta más, la celda ya no se parece a la
        ciudad y el gradiente estándar inventa. Pasa en Canarias, donde la
        única celda con tierra junto a Las Palmas está a 546 m y el modelo ya
        la calienta más que al mar de al lado (sin tope saldrían +3,5 °C).
        """
        bruta = GRADIENTE * (self.altitud_celda - self.altitud_ciudad)
        return float(np.clip(bruta, -CORRECCION_MAX, CORRECCION_MAX))


def elegir_nodo(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray,
                tierra: np.ndarray, orografia: np.ndarray, altitud_ciudad: float) -> Nodo:
    """La celda de las 3 × 3 más cercanas que mejor representa a la ciudad.

    Solo valen celdas con más de la mitad de tierra (en la costa, la de mar
    daría temperaturas de mar). Entre ellas, la de menor coste: distancia en
    km más un km por cada 10 m de desnivel con la ciudad. Si no hay ninguna
    de tierra, la más cercana.
    """
    i0 = int(np.argmin(np.abs(lats - lat)))
    j0 = int(np.argmin(np.abs(lons - lon)))
    mejor, mejor_coste = (i0, j0), np.inf
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            i, j = i0 + di, j0 + dj
            if not (0 <= i < len(lats) and 0 <= j < len(lons)) or tierra[i, j] < 0.5:
                continue
            dy = (lats[i] - lat) * 111.2
            dx = (lons[j] - lon) * 111.2 * np.cos(np.radians(lat))
            coste = np.hypot(dx, dy) + abs(orografia[i, j] - altitud_ciudad) / 10
            if coste < mejor_coste:
                mejor, mejor_coste = (i, j), coste
    i, j = mejor
    return Nodo(float(lats[i]), float(lons[j]), float(orografia[i, j]), float(altitud_ciudad))


def indices(lats: np.ndarray, lons: np.ndarray, puntos: list) -> tuple[np.ndarray, np.ndarray]:
    """Fila y columna de la rejilla más cercanas a cada (lat, lon)."""
    p = np.asarray(puntos, dtype=float).reshape(-1, 2)
    ii = np.abs(lats[None, :] - p[:, :1]).argmin(axis=1)
    jj = np.abs(lons[None, :] - p[:, 1:]).argmin(axis=1)
    return ii, jj


# ---------------------------------------------------------------------------
# Descargas y lectura (una carpeta de caché por pasada)
# ---------------------------------------------------------------------------

def bajar(run: datetime, nombre: str, **campos) -> Path:
    """Descarga a la caché (o reutiliza) un GRIB de la pasada `run`."""
    destino = CACHE / f"{run:%Y%m%d%H}" / f"{nombre}.grib2"
    if destino.exists() and destino.stat().st_size > 10_000:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")
    peticion = {"date": run.strftime("%Y%m%d"), "time": run.hour, **campos, "target": str(parcial)}
    if peticion.get("type") == "pf":
        peticion["stream"] = "enfo"
    from ecmwf.opendata import Client

    error = None
    for fuente in FUENTES:
        try:
            logger.info(f"Descargando {nombre} (pasada {run:%d/%m %H} UTC, {fuente})…")
            Client(source=fuente).retrieve(**peticion)
            parcial.rename(destino)
            return destino
        except Exception as e:     # noqa: BLE001 — se prueba la siguiente fuente
            logger.warning(f"{fuente}: {e}")
            parcial.unlink(missing_ok=True)
            error = e
    raise RuntimeError(f"No se pudo descargar {nombre}: {error}")


def leer(path: Path, var: str):
    """Lee `var` recortada a la región, con ejes (number?, step, lat, lon).

    Returns:
        (valores, pasos en horas, latitudes, longitudes)
    """
    import xarray as xr

    with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        da = ds[var].sel(latitude=slice(LAT_N, LAT_S), longitude=slice(LON_W, LON_E)).load()
    if "step" not in da.dims:
        da = da.expand_dims("step")
    da = da.transpose(*[d for d in ("number", "step", "latitude", "longitude") if d in da.dims])
    da = da.sortby("step")
    pasos = [int(round(s / np.timedelta64(1, "h"))) for s in da["step"].values]
    return da.values, pasos, da["latitude"].values, da["longitude"].values


def _por_paso(valores: np.ndarray, pasos: list[int], ventana_tp: list[int]) -> dict[int, np.ndarray]:
    """tp por paso (el paso 0 vale cero y no se descarga). El eje de pasos es el -3."""
    out = {p: np.take(valores, k, axis=-3) for k, p in enumerate(pasos)}
    if 0 in ventana_tp:
        out[0] = np.zeros_like(np.take(valores, 0, axis=-3))
    return out


# ---------------------------------------------------------------------------
# Previsión del día en los puntos del mapa y en las ciudades
# ---------------------------------------------------------------------------

@dataclass
class Prevision:
    run: datetime
    horas: list[int]            # hora peninsular de cada instante
    puntos: dict                # {"max", "min", "lluvia"}: (n_puntos,)
    ciudades: dict              # {"max", "min", "lluvia"}: (n_ciudades,), sin corregir
    horas_t: np.ndarray         # (n_instantes, n_ciudades), sin corregir
    horas_mm: np.ndarray        # (n_instantes, n_ciudades); NaN si no se sabe


def determinista(run: datetime, dia: date, celdas: list, nodos: list) -> Prevision:
    """Lee el IFS determinista y lo extrae en los puntos del mapa y las ciudades."""
    v = ventana(run, dia)
    tag = f"{dia:%Y%m%d}"
    vx, _, lats, lons = leer(bajar(run, f"fc_mx2t3_{tag}", type="fc", param="mx2t3", step=v.extremos), "mx2t3")
    vn, _, _, _ = leer(bajar(run, f"fc_mn2t3_{tag}", type="fc", param="mn2t3", step=v.extremos), "mn2t3")
    pasos_tp = [s for s in v.tp if s > 0]
    vtp, ptp, _, _ = leer(bajar(run, f"fc_tp_{tag}", type="fc", param="tp", step=pasos_tp), "tp")
    v2t, _, _, _ = leer(bajar(run, f"fc_2t_{tag}", type="fc", param="2t", step=v.instantes), "t2m")

    ip, jp = indices(lats, lons, celdas)
    ic, jc = indices(lats, lons, nodos)
    tmax = vx.max(axis=0) - 273.15
    tmin = vn.min(axis=0) - 273.15
    tp = _por_paso(vtp, ptp, v.tp)
    lluvia = np.clip(tp[v.tp_fin] - tp[v.tp_ini], 0, None) * 1000

    franjas = []
    for s in v.instantes:
        if s - 3 in tp:
            franjas.append(np.clip(tp[s][ic, jc] - tp[s - 3][ic, jc], 0, None) * 1000)
        else:                               # el análisis (paso 0): no hay 3 h previas
            franjas.append(np.full(len(nodos), np.nan))
    return Prevision(
        run=run,
        horas=[hora_local(run + timedelta(hours=s)) for s in v.instantes],
        puntos={"max": tmax[ip, jp], "min": tmin[ip, jp], "lluvia": lluvia[ip, jp]},
        ciudades={"max": tmax[ic, jc], "min": tmin[ic, jc], "lluvia": lluvia[ic, jc]},
        horas_t=v2t[:, ic, jc] - 273.15,
        horas_mm=np.array(franjas),
    )


def ensemble(run: datetime, dia: date, nodos: list) -> dict | None:
    """Los 50 escenarios en cada ciudad: máxima, mínima, lluvia del día y por franja.

    Returns:
        {"max", "min", "lluvia"}: (escenarios, ciudades) y "franjas":
        (escenarios, instantes, ciudades), sin corregir; None si el ensemble
        no está (el módulo sale entonces sin seguridad ni probabilidades).
    """
    v = ventana(run, dia)
    tag = f"{dia:%Y%m%d}"
    pasos_tp = [s for s in v.tp if s > 0]
    try:
        ex, _, lats, lons = leer(bajar(run, f"pf_mx2t3_{tag}", type="pf", param="mx2t3", step=v.extremos), "mx2t3")
        en, _, _, _ = leer(bajar(run, f"pf_mn2t3_{tag}", type="pf", param="mn2t3", step=v.extremos), "mn2t3")
        etp, ptp, _, _ = leer(bajar(run, f"pf_tp_{tag}", type="pf", param="tp", step=pasos_tp), "tp")
    except Exception as e:     # noqa: BLE001
        logger.warning(f"Sin ensemble ({e}): saldrá sin seguridad ni probabilidad de lluvia")
        return None
    ic, jc = indices(lats, lons, nodos)
    tp = {p: etp[:, k][:, ic, jc] for k, p in enumerate(ptp)}
    if 0 in v.tp:
        tp[0] = np.zeros_like(next(iter(tp.values())))
    franjas = np.stack([
        (tp[s] - tp[s - 3]) * 1000 if s - 3 in tp else np.full(tp[v.tp_fin].shape, np.nan)
        for s in v.instantes], axis=1)
    return {
        "max": ex[..., ic, jc].max(axis=1) - 273.15,
        "min": en[..., ic, jc].min(axis=1) - 273.15,
        "lluvia": np.clip(tp[v.tp_fin] - tp[v.tp_ini], 0, None) * 1000,
        "franjas": franjas,
    }


# ---------------------------------------------------------------------------
# Cifras de la ficha
# ---------------------------------------------------------------------------

def confianza(dispersion: float) -> str:
    """Seguridad según lo que se separan los escenarios (p90 − p10, °C).

    Los mismos umbrales que el gráfico «¿Qué seguridad hay?» de BenBaso.
    """
    if dispersion <= 3:
        return "alta"
    if dispersion <= 6:
        return "media"
    return "baja"


def horquilla(central: float, escenarios: np.ndarray) -> tuple[list[int], float]:
    """Horquilla probable (p10-p90 del ensemble) centrada en el valor determinista."""
    p10, p50, p90 = np.nanpercentile(escenarios, [10, 50, 90])
    c = round(central)
    return [min(round(central - (p50 - p10)), c), max(round(central + (p90 - p50)), c)], float(p90 - p10)


def ficha_ciudad(tmax: float, tmin: float, lluvia: float, normal: tuple | None,
                 ens: dict | None = None) -> dict:
    """Cifras de una ciudad tal como las lee la página."""
    f = {
        "max": round(tmax), "min": round(tmin), "lluvia": round(float(lluvia), 1),
        "max_normal": None, "min_normal": None, "max_dif": None, "min_dif": None,
        "max_rango": None, "min_rango": None, "seguridad": None,
        "prob_lluvia": None, "prob_lluvia_fuerte": None,
    }
    if normal is not None:
        f.update(max_normal=round(normal[0]), min_normal=round(normal[1]),
                 max_dif=round(tmax - normal[0]), min_dif=round(tmin - normal[1]))
    if ens is not None:
        f["max_rango"], s_max = horquilla(tmax, ens["max"])
        f["min_rango"], s_min = horquilla(tmin, ens["min"])
        f["seguridad"] = confianza(max(s_max, s_min))
        f["prob_lluvia"] = int(round(100 * np.mean(ens["lluvia"] >= LLUVIA_MIN)))
        f["prob_lluvia_fuerte"] = int(round(100 * np.mean(ens["lluvia"] >= LLUVIA_FUERTE)))
    return f


def filas_horas(horas: list[int], temps: np.ndarray, mm: np.ndarray,
                franjas_ens: np.ndarray | None) -> list[list]:
    """[[hora, temperatura, probabilidad de lluvia (%), mm], …] cada 3 h."""
    filas = []
    for k, h in enumerate(horas):
        p = None
        if franjas_ens is not None and not np.all(np.isnan(franjas_ens[:, k])):
            p = int(round(100 * np.mean(franjas_ens[:, k] >= LLUVIA_FRANJA)))
        litros = None if np.isnan(mm[k]) else round(float(mm[k]), 1)
        filas.append([int(h), round(float(temps[k])), p, litros])
    return filas


# ---------------------------------------------------------------------------
# Titular
# ---------------------------------------------------------------------------

def titular(fichas: dict[str, dict], valores: dict[str, dict], canarias: set[str]) -> str:
    """La frase del día a partir de las ciudades (la fecha la pone la página).

    Prioridad: lluvia fuerte, temperaturas raras para la fecha, heladas,
    lluvia moderada y, si no pasa nada, la máxima más alta de la Península.

    Args:
        fichas:   {ciudad: ficha_ciudad(...)}
        valores:  {ciudad: {"max", "min", "lluvia", "max_dif", "min_dif"}} sin redondear
        canarias: ciudades de Canarias (fuera de las comparaciones con lo normal)
    """
    def prob(c):     # sin ensemble, la lluvia del determinista se da por segura
        p = fichas[c].get("prob_lluvia")
        return 100 if p is None else p

    lluvia = sorted(((v["lluvia"], c) for c, v in valores.items() if prob(c) >= 60), reverse=True)
    if lluvia and lluvia[0][0] >= 30:
        mm, c = lluvia[0]
        return f"Día de lluvia: hasta {mm:.0f} litros por metro cuadrado en {c}"

    difs = [(v[k], c, k) for c, v in valores.items()
            for k in ("max_dif", "min_dif") if v.get(k) is not None]
    if difs:
        calor, frio = max(difs), min(difs)
        if calor[0] >= 3 and calor[0] >= -frio[0]:
            a, c, k = calor
            v = valores[c][k[:3]]
            if k == "max_dif":
                return f"{c} llegará a {v:.0f} grados, {a:.0f} por encima de lo normal"
            return f"Noche cálida: {c} no bajará de {v:.0f} grados, {a:.0f} más de lo normal"
        if frio[0] <= -3:
            a, c, k = frio
            v = valores[c][k[:3]]
            if k == "max_dif":
                return f"{c} no pasará de {v:.0f} grados, {-a:.0f} menos de lo normal"
            return f"Frío de madrugada: {c} bajará a {v:.0f} grados, {-a:.0f} menos de lo normal"

    peninsula = {c: v for c, v in valores.items() if c not in canarias}
    if peninsula:
        helada = min(peninsula, key=lambda c: peninsula[c]["min"])
        if peninsula[helada]["min"] <= -2:
            return f"Heladas: {helada} bajará a {abs(peninsula[helada]['min']):.0f} grados bajo cero"

    if lluvia and lluvia[0][0] >= 10:
        (mm, c), *resto = lluvia
        otra = f" y {resto[0][1]}" if resto and resto[0][0] >= 10 else ""
        return f"Lluvia en {c}{otra}: hasta {mm:.0f} litros por metro cuadrado"

    if peninsula:
        c = max(peninsula, key=lambda c: peninsula[c]["max"])
        cerca = " para la fecha" if difs else ""
        return f"Temperaturas normales{cerca}: máximas de hasta {peninsula[c]['max']:.0f} grados en {c}"
    return "El tiempo en España"


# ---------------------------------------------------------------------------
# Documento del día
# ---------------------------------------------------------------------------

def cargar_tablas() -> tuple[list[dict], list]:
    """Ciudades (con su celda, corrección y normales) y celdas de los puntos del mapa."""
    ciudades = json.loads((FIJOS / "ciudades.json").read_text(encoding="utf-8"))["ciudades"]
    celdas = json.loads((FIJOS / "puntos.json").read_text(encoding="utf-8"))["celdas"]
    return ciudades, celdas


def documento(dia: date, prev: Prevision, ens: dict | None, ciudades: list[dict]) -> dict:
    """El JSON del día a partir de la previsión ya extraída (sin red ni disco)."""
    doy = dia_del_ano(dia)
    fichas, valores, canarias = {}, {}, set()
    for k, c in enumerate(ciudades):
        nombre, corr = c["nombre"], c["correccion"]
        if c["lat"] < 30:
            canarias.add(nombre)
        normal = None
        if c.get("normal_max") is not None:
            normal = (c["normal_max"][doy] + corr, c["normal_min"][doy] + corr)
        tmax = float(prev.ciudades["max"][k]) + corr
        tmin = float(prev.ciudades["min"][k]) + corr
        lluvia = float(prev.ciudades["lluvia"][k])
        e = None
        if ens is not None:
            e = {"max": ens["max"][:, k] + corr, "min": ens["min"][:, k] + corr,
                 "lluvia": ens["lluvia"][:, k]}
        f = ficha_ciudad(tmax, tmin, lluvia, normal, e)
        f["horas"] = filas_horas(prev.horas, prev.horas_t[:, k] + corr, prev.horas_mm[:, k],
                                 None if ens is None else ens["franjas"][:, :, k])
        fichas[nombre] = f
        valores[nombre] = {"max": tmax, "min": tmin, "lluvia": lluvia,
                           "max_dif": None if normal is None else tmax - normal[0],
                           "min_dif": None if normal is None else tmin - normal[1]}
    run = prev.run
    return {
        "version": VERSION,
        "fecha": dia.isoformat(),
        "dia": dia_texto(dia),
        "titular": titular(fichas, valores, canarias),
        "pasada": run.strftime("%Y-%m-%dT%H:00Z"),
        "pasada_texto": f"{run.hour:02d} UTC del {run.day}/{run.month}",
        "generado": datetime.now(TZ).isoformat(timespec="minutes"),
        "con_ensemble": ens is not None,
        "puntos": {
            "max": [int(round(x)) for x in prev.puntos["max"]],
            "min": [int(round(x)) for x in prev.puntos["min"]],
            "lluvia": [round(float(x), 1) for x in prev.puntos["lluvia"]],
        },
        "ciudades": fichas,
        "enlace": None,
    }


def generar_dia(dia: date, pasada: datetime | None = None, salida: Path = DATOS,
                con_ensemble: bool = True) -> Path:
    """Descarga, calcula y escribe el JSON de `dia`. Devuelve su ruta."""
    ciudades, celdas = cargar_tablas()
    nodos = [c["nodo"] for c in ciudades]
    candidatas = [pasada] if pasada else pasadas_candidatas(dia)
    if not candidatas:
        raise ValueError(f"Ninguna pasada cubre el {dia:%d/%m/%Y}.")
    error = None
    for run in candidatas:
        try:
            prev = determinista(run, dia, celdas, nodos)
            break
        except Exception as e:     # noqa: BLE001 — pasada aún no publicada: la anterior
            logger.warning(f"Pasada {run:%d/%m %H} UTC no disponible: {e}")
            error = e
    else:
        raise RuntimeError(f"No hay ninguna pasada disponible para el {dia:%d/%m}: {error}")
    ens = ensemble(prev.run, dia, nodos) if con_ensemble else None
    doc = documento(dia, prev, ens, ciudades)
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / f"{dia:%Y-%m-%d}.json"
    destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    logger.info(f"{destino.name}: {doc['titular']} (pasada {doc['pasada_texto']})")
    return destino


def escribir_indice(salida: Path = DATOS) -> Path:
    """indice.json: las fechas con datos, para que la página sin fecha elija."""
    salida.mkdir(parents=True, exist_ok=True)
    fechas = []
    for p in salida.glob("????-??-??.json"):
        try:
            fechas.append(date.fromisoformat(p.stem).isoformat())
        except ValueError:
            continue
    destino = salida / "indice.json"
    destino.write_text(json.dumps({
        "fechas": sorted(fechas),
        "actualizado": datetime.now(TZ).isoformat(timespec="minutes"),
    }), encoding="utf-8")
    return destino


def limpiar_cache(dias: int = 3) -> None:
    """Borra las descargas de pasadas de hace más de `dias` días (~450 MB cada una)."""
    if not CACHE.exists():
        return
    limite = datetime.utcnow() - timedelta(days=dias)
    for carpeta in CACHE.iterdir():
        try:
            if carpeta.is_dir() and datetime.strptime(carpeta.name, "%Y%m%d%H") < limite:
                shutil.rmtree(carpeta, ignore_errors=True)
        except ValueError:
            continue


def generar(dias: list[date] | None = None, pasada: datetime | None = None,
            con_ensemble: bool = True) -> list[Path]:
    """Genera los días pedidos (por defecto, hoy y mañana) que alguna pasada cubra.

    Hoy solo se rehace con la pasada de las 00 UTC: la de las 12 UTC empieza a
    media tarde y ya no cubre el día entero, así que el de la mañana se queda.
    """
    hoy = datetime.now(TZ).date()
    dias = dias or [hoy, hoy + timedelta(days=1)]
    hechos = []
    for d in dias:
        if pasada is None and not pasadas_candidatas(d):
            logger.info(f"{d}: ninguna pasada reciente lo cubre entero; se deja como está")
            continue
        try:
            hechos.append(generar_dia(d, pasada, con_ensemble=con_ensemble))
        except Exception as e:     # noqa: BLE001
            logger.error(f"{d}: {e}")
    escribir_indice()
    limpiar_cache()
    return hechos
