"""Pruebas del generador sin red: ventanas, ciudades, cifras, titular y documento."""

from datetime import date, datetime

import numpy as np
import pytest

from generador import tiempo as t


# --- Ventana de pasos -------------------------------------------------------

def test_ventana_manana_con_la_pasada_de_las_00():
    # Sábado 21 de noviembre (UTC+1): de las 23 UTC del 20 a las 23 UTC del 21.
    v = t.ventana(datetime(2026, 11, 20, 0), date(2026, 11, 21))
    assert v.instantes == [24, 27, 30, 33, 36, 39, 42, 45]
    assert v.extremos == [27, 30, 33, 36, 39, 42, 45, 48]
    assert (v.tp_ini, v.tp_fin) == (24, 48)
    assert 21 in v.tp and 48 in v.tp


def test_ventana_hoy_con_la_pasada_de_las_00_empieza_en_el_analisis():
    v = t.ventana(datetime(2026, 11, 20, 0), date(2026, 11, 20))
    assert v.instantes[0] == 0 and v.tp_ini == 0
    assert t.hora_local(datetime(2026, 11, 20, 0)) == 1


def test_la_pasada_de_las_12_no_cubre_hoy():
    with pytest.raises(ValueError):
        t.ventana(datetime(2026, 11, 20, 12), date(2026, 11, 20))


def test_mas_alla_del_paso_144_no_se_cubre():
    with pytest.raises(ValueError):
        t.ventana(datetime(2026, 11, 20, 0), date(2026, 11, 26))


def test_pasadas_candidatas_de_la_mas_reciente_a_la_mas_antigua():
    ahora = datetime(2026, 11, 20, 22, 0)        # UTC: la de las 12 ya existe
    hoy = t.pasadas_candidatas(date(2026, 11, 20), ahora)
    assert hoy[0] == datetime(2026, 11, 20, 0)   # la de las 12 no cubre hoy
    manana = t.pasadas_candidatas(date(2026, 11, 21), ahora)
    assert manana[0] == datetime(2026, 11, 20, 12)
    assert manana == sorted(manana, reverse=True)


def test_dia_del_ano_bisiesto():
    assert t.dia_del_ano(date(2026, 1, 1)) == 0
    assert t.dia_del_ano(date(2026, 3, 1)) == 60      # el 29 de febrero ocupa el 59
    assert t.dia_del_ano(date(2026, 12, 31)) == 365


# --- Ciudades -------------------------------------------------------------

def _rejilla():
    lats = np.array([40.5, 40.25, 40.0])
    lons = np.array([-4.0, -3.75, -3.5])
    tierra = np.ones((3, 3))
    oro = np.full((3, 3), 650.0)
    return lats, lons, tierra, oro


def test_elegir_nodo_evita_el_mar():
    lats, lons, tierra, oro = _rejilla()
    tierra[1, 1] = 0.0                     # la celda más cercana es de mar
    n = t.elegir_nodo(40.25, -3.75, lats, lons, tierra, oro, 650)
    assert (n.lat, n.lon) != (40.25, -3.75)


def test_elegir_nodo_prefiere_altitud_parecida():
    lats, lons, tierra, oro = _rejilla()
    oro[1, 1] = 1500.0                      # la más cercana, en la sierra
    n = t.elegir_nodo(40.25, -3.75, lats, lons, tierra, oro, 650)
    assert n.altitud_celda == 650.0


def test_correccion_por_altitud_con_tope():
    assert t.Nodo(0, 0, 100, 0).correccion == pytest.approx(0.65)
    assert t.Nodo(0, 0, 546, 8).correccion == t.CORRECCION_MAX       # Las Palmas
    assert t.Nodo(0, 0, 0, 1000).correccion == -t.CORRECCION_MAX


def test_indices_cercanos():
    lats, lons, _, _ = _rejilla()
    ii, jj = t.indices(lats, lons, [[40.1, -3.6], [40.5, -4.0]])
    assert ii.tolist() == [2, 0] and jj.tolist() == [2, 0]


# --- Cifras ----------------------------------------------------------------

def test_horquilla_centrada_en_el_determinista():
    escenarios = np.linspace(10, 14, 50)     # p10 ≈ 10,4; p50 = 12; p90 ≈ 13,6
    (a, b), disp = t.horquilla(15.0, escenarios)
    assert a < 15 < b and disp == pytest.approx(3.2, abs=0.01)


def test_horquilla_siempre_incluye_el_valor():
    (a, b), _ = t.horquilla(20.4, np.full(50, 20.4))
    assert a == b == 20


def test_ficha_con_normal_y_ensemble():
    ens = {"max": np.linspace(16, 20, 50), "min": np.linspace(7, 9, 50),
           "lluvia": np.r_[np.zeros(30), np.full(20, 12.0)]}
    f = t.ficha_ciudad(18.4, 8.0, 3.24, (14.0, 5.0), ens)
    assert (f["max"], f["min"], f["lluvia"]) == (18, 8, 3.2)
    assert (f["max_dif"], f["min_dif"]) == (4, 3)
    assert f["seguridad"] == "media"         # 3,2 grados de p10 a p90
    assert (f["prob_lluvia"], f["prob_lluvia_fuerte"]) == (40, 40)


def test_ficha_sin_normal_ni_ensemble():
    f = t.ficha_ciudad(25.0, 19.0, 0.0, None)
    assert f["max_dif"] is None and f["seguridad"] is None and f["prob_lluvia"] is None


def test_filas_horas():
    temps = np.array([9.4, 12.6])
    mm = np.array([np.nan, 1.25])
    franjas = np.array([[0.0, 0.5]] * 30 + [[0.0, 0.0]] * 20)   # 50 escenarios
    filas = t.filas_horas([1, 4], temps, mm, franjas)
    assert filas == [[1, 9, 0, None], [4, 13, 60, 1.2]]


def test_confianza():
    assert [t.confianza(x) for x in (2, 4, 8)] == ["alta", "media", "baja"]


# --- Titular ---------------------------------------------------------------

def _v(maximo, minimo, lluvia=0.0, dmax=0.0, dmin=0.0):
    return {"max": maximo, "min": minimo, "lluvia": lluvia, "max_dif": dmax, "min_dif": dmin}


def test_titular_lluvia_fuerte_manda():
    fichas = {"Vigo": {"prob_lluvia": 100}, "Sevilla": {"prob_lluvia": 0}}
    valores = {"Vigo": _v(15, 11, 71.0), "Sevilla": _v(30, 15, 0, dmax=9)}
    assert t.titular(fichas, valores, set()).startswith("Día de lluvia: hasta 71 litros")


def test_titular_calor_raro():
    fichas = {"Granada": {"prob_lluvia": 0}, "Burgos": {"prob_lluvia": 0}}
    valores = {"Granada": _v(22.3, 8, dmax=8.1), "Burgos": _v(12, 4, dmax=1)}
    assert t.titular(fichas, valores, set()) == "Granada llegará a 22 grados, 8 por encima de lo normal"


def test_titular_heladas():
    fichas = {"Soria": {"prob_lluvia": 0}, "Madrid": {"prob_lluvia": 0}}
    valores = {"Soria": _v(8, -4.2), "Madrid": _v(11, 1)}
    assert t.titular(fichas, valores, set()) == "Heladas: Soria bajará a 4 grados bajo cero"


def test_titular_canarias_no_firma_la_maxima():
    fichas = {"Las Palmas": {"prob_lluvia": 0}, "Sevilla": {"prob_lluvia": 0}}
    valores = {"Las Palmas": {**_v(26, 20), "max_dif": None, "min_dif": None},
               "Sevilla": _v(21, 10)}
    assert t.titular(fichas, valores, {"Las Palmas"}).endswith("21 grados en Sevilla")


# --- Documento ---------------------------------------------------------------

CIUDADES_PRUEBA = [
    {"nombre": "Madrid", "lat": 40.42, "lon": -3.7, "nodo": [40.5, -3.75], "correccion": 0.2,
     "normal_max": [14.0] * 366, "normal_min": [5.0] * 366},
    {"nombre": "Las Palmas", "lat": 28.12, "lon": -15.43, "nodo": [28.0, -15.75],
     "correccion": 1.5, "normal_max": None, "normal_min": None},
]


def _prevision(run=datetime(2026, 11, 20, 0)):
    return t.Prevision(
        run=run, horas=[1, 4],
        puntos={"max": np.array([12.6, 20.1]), "min": np.array([5.0, 10.0]), "lluvia": np.array([0.04, 3.333])},
        ciudades={"max": np.array([12.8, 23.9]), "min": np.array([7.8, 19.5]), "lluvia": np.array([5.0, 0.0])},
        horas_t=np.array([[9.0, 20.0], [9.0, 20.0]]),
        horas_mm=np.array([[np.nan, np.nan], [0.1, 0.0]]),
    )


def test_documento_dia_sin_red():
    doc = t.documento_dia(date(2026, 11, 21), _prevision(), None, CIUDADES_PRUEBA)
    assert (doc["dia"], doc["corto"]) == ("sábado 21 de noviembre", "sáb 21")
    assert doc["puntos"] == {"max": [13, 20], "min": [5, 10], "lluvia": [0.0, 3.3]}
    madrid = doc["ciudades"]["Madrid"]
    assert (madrid["max"], madrid["max_dif"]) == (13, -1)
    assert madrid["horas"][0] == [1, 9, None, None]
    assert doc["ciudades"]["Las Palmas"]["max"] == 25     # 23,9 + 1,5
    assert doc["ciudades"]["Las Palmas"]["max_dif"] is None
    assert doc["con_ensemble"] is False


def test_emision_de_seis_dias_sin_red(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "cargar_tablas", lambda: (CIUDADES_PRUEBA, [[40.5, -3.75], [28.0, -15.75]]))
    pedidos = []
    monkeypatch.setattr(t, "determinista", lambda run, d, c, n: pedidos.append(d) or _prevision(run))
    monkeypatch.setattr(t, "ensemble", lambda run, d, n: None)
    ruta = t.generar_emision(date(2026, 11, 20), datetime(2026, 11, 20, 0), salida=tmp_path)
    import json
    doc = json.loads(ruta.read_text(encoding="utf-8"))
    assert ruta.name == "2026-11-20.json" and doc["version"] == 2
    assert [d["fecha"] for d in doc["dias"]] == [f"2026-11-{n}" for n in range(20, 26)]
    assert doc["pasada_texto"] == "00 UTC del 20/11"
    # La de las 12 da un día menos: el sexto acabaría pasado el paso 144.
    ruta = t.generar_emision(date(2026, 11, 21), datetime(2026, 11, 20, 12), salida=tmp_path)
    assert len(json.loads(ruta.read_text(encoding="utf-8"))["dias"]) == 5


def test_ensemble_solo_tarde_y_madrugada():
    v = t.ventana(datetime(2026, 11, 20, 0), date(2026, 11, 21))
    # Tramos de 3 h que acaban en esos pasos; punto medio en hora peninsular (UTC+1).
    assert v.ens_max == [36, 39, 42]          # 11:30, 14:30 y 17:30
    assert v.ens_min == [27, 30, 33]          # 2:30, 5:30 y 8:30
    assert set(v.ens_max) | set(v.ens_min) <= set(v.extremos)


def test_dias_de_la_pasada():
    # Con la de las 00, la emisión de hoy y la de mañana; con la de las 12, solo mañana.
    assert t.dias_de_la_pasada(datetime(2026, 11, 20, 0), datetime(2026, 11, 20, 9, 20)) == \
        [date(2026, 11, 20), date(2026, 11, 21)]
    assert t.dias_de_la_pasada(datetime(2026, 11, 20, 12), datetime(2026, 11, 20, 21, 20)) == \
        [date(2026, 11, 21)]
    # Por la noche, si la de las 12 aún no está, se rehace con la de las 00.
    assert t.dias_de_la_pasada(datetime(2026, 11, 20, 0), datetime(2026, 11, 20, 21, 20)) == \
        [date(2026, 11, 20), date(2026, 11, 21)]


def test_ultima_pasada_publicada_salta_las_que_faltan():
    publicadas = {datetime(2026, 11, 21, 0), datetime(2026, 11, 20, 12)}
    run = t.ultima_pasada_publicada(datetime(2026, 11, 21, 18, 30), publicada=lambda r: r in publicadas)
    assert run == datetime(2026, 11, 21, 0)
    with pytest.raises(RuntimeError):
        t.ultima_pasada_publicada(datetime(2026, 11, 21, 18, 30), publicada=lambda r: False)


def test_no_pisa_una_emision_igual_o_mas_nueva(tmp_path, monkeypatch):
    import json
    (tmp_path / "2026-11-21.json").write_text(json.dumps({"pasada": "2026-11-21T00:00Z"}))
    monkeypatch.setattr(t, "determinista", lambda *a: pytest.fail("no debía descargar nada"))
    ruta = t.generar_emision(date(2026, 11, 21), datetime(2026, 11, 20, 12), salida=tmp_path)
    assert json.loads(ruta.read_text())["pasada"] == "2026-11-21T00:00Z"
    ruta = t.generar_emision(date(2026, 11, 21), datetime(2026, 11, 21, 0), salida=tmp_path)
    assert json.loads(ruta.read_text())["pasada"] == "2026-11-21T00:00Z"


def test_sin_publicar_no_se_pregunta_a_aws(tmp_path, monkeypatch):
    import sys
    import types
    fuentes = []

    class Cliente:
        def __init__(self, source):
            self.source = source

        def retrieve(self, **kw):
            fuentes.append(self.source)
            raise RuntimeError("404 Client Error: Not Found for url: https://data.ecmwf.int/…")

    monkeypatch.setitem(sys.modules, "ecmwf.opendata", types.SimpleNamespace(Client=Cliente))
    monkeypatch.setattr(t, "CACHE", tmp_path)
    with pytest.raises(RuntimeError):
        t.bajar(datetime(2026, 11, 21, 12), "fc_prueba", type="fc", param="2t", step=[3])
    assert fuentes == ["ecmwf"]


def test_indice_sin_cambios_no_se_reescribe(tmp_path):
    (tmp_path / "2026-11-21.json").write_text("{}")
    ruta = t.escribir_indice(tmp_path)
    antes = ruta.read_text()
    (tmp_path / "otra.json").write_text("{}")          # no es una fecha: no cuenta
    import time
    time.sleep(0.01)
    assert t.escribir_indice(tmp_path).read_text() == antes


def test_tablas_del_repositorio_coinciden():
    ciudades, celdas = t.cargar_tablas()
    import json
    mapa = json.loads((t.SITIO / "mapa.json").read_text(encoding="utf-8"))
    assert len(mapa["puntos"]) == len(celdas)
    assert {c["nombre"] for c in ciudades} == set(mapa["ciudades"])
    assert all(len(c["normal_max"]) == 366 for c in ciudades if c["normal_max"])
    assert set(mapa["etiquetas"]) <= set(mapa["ciudades"])


def test_por_paso_usa_el_eje_de_pasos():
    det = np.arange(2 * 3 * 4).reshape(2, 3, 4).astype(float)          # (paso, lat, lon)
    out = t._por_paso(det, [3, 6], [0, 3, 6])
    assert out[6].shape == (3, 4) and out[6][0, 0] == 12 and out[0].sum() == 0
    ens = np.arange(5 * 2 * 3 * 4).reshape(5, 2, 3, 4).astype(float)   # (escenario, paso, lat, lon)
    assert t._por_paso(ens, [3, 6], [3, 6])[6].shape == (5, 3, 4)
