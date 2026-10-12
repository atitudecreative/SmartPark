"""
Gero o web/simulador.html (página única, abre sem servidor) a partir de:
    web/simulador_fonte.html  +  scripts/planta.js  +  layout da planta, perfis de chegada e resultados.

    python scripts/gerar_simulador_web.py
"""
import json
import sys
import warnings
from pathlib import Path

warnings.simplefilter("ignore")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from smartpark.layout import layout_planta  # noqa: E402
from smartpark.preditor import Preditor  # noqa: E402
from simulador.chegadas import CULTOS  # noqa: E402
from simulador.treinar_preditor import MODELO  # noqa: E402

WEB = RAIZ.parent / "web"
RES = RAIZ.parent / "resultados"

pred = Preditor.carregar(MODELO)
perfil = {}
for (c, m), v in pred.perfil_medio.items():
    perfil.setdefault(str(c), {})[str(m)] = round(v, 2)
res = json.loads((RES / "experimento_resumo.json").read_text())
resultados = {cen: {e: {k: round(d[k]["media"], 1) for k in ["porta_a_porta_medio_s", "tempo_parado_medio_s", "tempo_p95_s"]}
                    for e, d in v.items()} for cen, v in res.items()}
dados = {
    "layout": layout_planta().para_dict(),
    "perfil": perfil,
    "resultados": resultados,
    "cultos": [dict(nome=c.nome, volume=c.volume_medio, pico=c.pico_min, disp=c.dispersao_min, atras=c.frac_atrasados, mix=c.mix)
               for c in CULTOS],
}
fonte = (WEB / "simulador_fonte.html").read_text(encoding="utf-8")
html = fonte.replace("__PLANTA_JS__", (RAIZ / "scripts" / "planta.js").read_text(encoding="utf-8")) \
            .replace("__DADOS__", json.dumps(dados, separators=(",", ":"), ensure_ascii=False))
(WEB / "simulador.html").write_text(html, encoding="utf-8")
print(f"web/simulador.html gerado ({len(html) // 1024} KB)")
