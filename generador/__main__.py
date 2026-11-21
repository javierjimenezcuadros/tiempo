"""python -m generador [--dia AAAA-MM-DD …] [--pasada AAAAMMDDHH] [--sin-ensemble]

Sin argumentos mira cuál es la última pasada que ECMWF ha publicado y genera
las emisiones que tocan con ella: con la de las 00 UTC, la de hoy (hoy y cinco
días más) y la de mañana; con la de las 12, la de mañana. Si ya están hechas
con esa pasada, no hace nada. Es lo que ejecuta GitHub Actions cada dos horas.
"""

import argparse
import logging
import sys
from datetime import date, datetime

from generador.tiempo import generar


def main() -> int:
    p = argparse.ArgumentParser(description="Genera los datos del módulo del tiempo.")
    p.add_argument("--dia", action="append", type=date.fromisoformat,
                   help="día con el que empieza la emisión (se puede repetir); por defecto, el que toca")
    p.add_argument("--pasada", type=lambda s: datetime.strptime(s, "%Y%m%d%H"),
                   help="pasada UTC a usar, p. ej. 2026112000; por defecto, la más reciente")
    p.add_argument("--sin-ensemble", action="store_true", help="más rápido, sin seguridad ni probabilidades")
    p.add_argument("--forzar", action="store_true", help="rehacer aunque ya estén hechas con esa pasada")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for ruido in ("ecmwf", "cfgrib", "urllib3"):
        logging.getLogger(ruido).setLevel(logging.WARNING)
    hechos = generar(a.dia, a.pasada, con_ensemble=not a.sin_ensemble, forzar=a.forzar)
    if not hechos:
        logging.error("No se ha generado ninguna emisión.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
