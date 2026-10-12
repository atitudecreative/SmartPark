"""
Programa principal que eu rodo no Raspberry Pi.

Ele liga o controlador ao broker MQTT (ESP32) e à câmera (LPR), e serve as telas pela rede:
painel da equipe (/equipe), tablet do motorista (/guarita), app do corredor (/corredor) e admin (/admin).
No tablet da guarita, em modo quiosque: chromium-browser --kiosk http://localhost:8080/guarita

Como eu rodo em cada situação:
    # Pi de verdade, câmera USB, Mosquitto local, maquete de 6 vagas
    python scripts/ponte_guarita.py --broker localhost --camera 0 --layout maquete

    # Sem câmera (placas simuladas) e ESP32 no Wokwi, usando um broker público
    python scripts/ponte_guarita.py --broker broker.hivemq.com --prefixo smartpark-eduardo --layout maquete

    # Tudo no notebook, sem broker nem ESP32 (botão "Simular chegada" no painel)
    python scripts/ponte_guarita.py --sem-mqtt --layout maquete
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from smartpark.banco import Banco  # noqa: E402
from smartpark.barramento import BarramentoMemoria, BarramentoMQTT  # noqa: E402
from smartpark.controlador import Controlador  # noqa: E402
from smartpark.layout import LAYOUTS  # noqa: E402
from smartpark.lpr import LPRSimulado, placa_aleatoria  # noqa: E402
from smartpark.controlador import VISITAS_PARA_OFERECER_CADASTRO  # noqa: E402
from smartpark.banco import RETENCAO_VISITANTES_DIAS  # noqa: E402
from smartpark.relatorio import resumo, fmt_hora  # noqa: E402
from smartpark.admin import Autenticacao, visao_geral, filtrar_por_culto, NOMES_CULTO  # noqa: E402
from smartpark.banco import CATEGORIAS  # noqa: E402
from smartpark.lpr import normalizar_placa  # noqa: E402
from smartpark.saude import diagnosticar  # noqa: E402
from smartpark.admin import avisos_por_culto  # noqa: E402

PAINEL_HTML = (Path(__file__).parent / "painel.html").read_text(encoding="utf-8")
HISTORICO_HTML = (Path(__file__).parent / "historico.html").read_text(encoding="utf-8")
GUARITA_HTML = (Path(__file__).parent / "guarita.html").read_text(encoding="utf-8")   # tablet do motorista
SIMULADOR_WEB = Path(__file__).resolve().parents[2] / "web" / "simulador.html"
CORREDOR_HTML = (Path(__file__).parent / "corredor.html").read_text(encoding="utf-8")
CARRO_HTML = (Path(__file__).parent / "carro.html").read_text(encoding="utf-8")        # modo "carro de teste" (celular)
MAX_FOTO = 12 * 1024 * 1024   # foto da placa: até 12 MB  # celular do funcionário do corredor
ADMIN_HTML = (Path(__file__).parent / "admin.html").read_text(encoding="utf-8")
PASTA_WEB = Path(__file__).resolve().parent
ARQUIVOS_ESTATICOS = {"/planta.js", "/estilo.css", "/ui.js"}
TIPOS = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2"}


class LPRDemo:
    """Sem câmera: finjo que "li" uma placa cadastrada (ou de visitante) sorteada."""

    def __init__(self, banco: Banco, taxa_visitante=0.15):
        self.banco = banco
        self.taxa = taxa_visitante
        self.sim = LPRSimulado(taxa_ilegivel=0.0, taxa_troca=0.0)
        self.rng = random.Random()
        self.proxima: str | None = None

    def ler(self, placa=None):
        if placa is None:
            placa = self.proxima
            self.proxima = None
        if placa is None:
            cadastradas = [r[0] for r in self.banco.con.execute("SELECT placa FROM veiculos")]
            placa = placa_aleatoria(self.rng) if (not cadastradas or self.rng.random() < self.taxa) else self.rng.choice(cadastradas)
        return self.sim.ler(placa)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--porta-mqtt", type=int, default=1883)
    ap.add_argument("--prefixo", default="smartpark")
    ap.add_argument("--sem-mqtt", action="store_true", help="roda sem broker (demonstração local)")
    ap.add_argument("--camera", default=None, help="índice da câmera USB (0, 1...) ou endereço de câmera IP; omita para placas simuladas")
    ap.add_argument("--layout", choices=list(LAYOUTS), default="maquete")
    ap.add_argument("--banco", default=str(RAIZ / "smartpark" / "dados" / "smartpark.db"))
    ap.add_argument("--estrategia", default="preditiva", choices=["mais_proxima", "reativa", "preditiva"])
    ap.add_argument("--porta-web", type=int, default=int(os.environ.get("PORT", 8080)))   # no Render, a porta vem em $PORT
    ap.add_argument("--telegram-token", default=os.environ.get("SMARTPARK_TELEGRAM_TOKEN"),
                    help="token do bot do Telegram para avisos de lotação (ou variável SMARTPARK_TELEGRAM_TOKEN)")
    ap.add_argument("--telegram-chat", default=os.environ.get("SMARTPARK_TELEGRAM_CHAT"),
                    help="id do grupo da equipe de recepção (ou variável SMARTPARK_TELEGRAM_CHAT)")
    ap.add_argument("--ensaio", type=float, metavar="MIN",
                    help="modo ensaio: finge que um culto (Domingo 11h) começa daqui a MIN minutos")
    args = ap.parse_args()

    layout = LAYOUTS[args.layout]()
    banco = Banco(args.banco)

    bus = BarramentoMemoria() if args.sem_mqtt else BarramentoMQTT(args.broker, args.porta_mqtt)

    if args.camera is not None:
        from smartpark.lpr import LPRCamera
        lpr = LPRCamera(int(args.camera) if str(args.camera).isdigit() else args.camera)
    else:
        lpr = LPRDemo(banco)

    preditor = None
    modelo = RAIZ / "smartpark" / "dados" / "preditor.joblib"
    if modelo.exists():
        from smartpark.preditor import Preditor
        preditor = Preditor.carregar(modelo)

    ctl = Controlador(layout, banco, bus, lpr, preditor, args.estrategia, prefixo=args.prefixo)
    if args.sem_mqtt:
        ctl.esp32 = {"estado": "demonstracao", "desde": None}
    if args.ensaio is not None:
        ctl.culto_ensaio = (1, time.time() + args.ensaio * 60)
        print(f"Modo ensaio: culto simulado começa em {args.ensaio:g} min")
    ctl.verificar()
    if args.telegram_token and args.telegram_chat:
        ctl.notificadores.append(notificador_telegram(args.telegram_token, args.telegram_chat))
        print("Avisos de lotação: Telegram ativado")

    # verificação periódica: o aviso de lotação precisa andar mesmo quando nenhum carro chega
    def ciclo():
        while True:
            time.sleep(30)
            try:
                ctl.verificar()
            except Exception as e:
                print(f"[verificação] {e}")
    threading.Thread(target=ciclo, daemon=True).start()

    auth = Autenticacao(Path(args.banco).with_name("admin_senha.txt"))
    if os.environ.get("SMARTPARK_SENHA_ADMIN"):           # no servidor da nuvem, defino a senha por variável de ambiente
        auth.definir(os.environ["SMARTPARK_SENHA_ADMIN"])
        auth.senha_gerada = None

    servir_painel(ctl, bus, layout, args, auth)


def notificador_telegram(token, chat):
    """Mando o aviso para o grupo da equipe de recepção. Roda em segundo plano para não travar a cancela."""
    import urllib.parse
    import urllib.request

    def enviar(texto, info):
        icone = {"atencao": "⚠️", "critico": "🚨", "lotado": "⛔"}.get(info["nivel"], "")
        corpo = f"{icone} {texto}\nVagas livres agora: {info['livres']}"
        dados = urllib.parse.urlencode({"chat_id": chat, "text": corpo}).encode()

        def _post():
            try:
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=10).read()
            except Exception as e:
                print(f"[telegram] falha ao enviar: {e}")
        threading.Thread(target=_post, daemon=True).start()
    return enviar


def servir_painel(ctl: Controlador, bus, layout, args, auth: Autenticacao):
    leitor_foto = {"obj": None, "erro": None}

    def ler_foto(dados: bytes) -> dict:
        """OCR de verdade numa foto enviada pelo celular (modo carro de teste)."""
        if leitor_foto["obj"] is None and leitor_foto["erro"] is None:
            try:
                from smartpark.lpr import LeitorImagem
                leitor_foto["obj"] = LeitorImagem()
            except Exception as e:  # opencv/pytesseract/tesseract ausentes
                leitor_foto["erro"] = f"Leitura por foto indisponível neste servidor ({e.__class__.__name__}). Digite a placa."
        if leitor_foto["erro"]:
            return {"ok": False, "erro": leitor_foto["erro"]}
        t0 = time.time()
        r = leitor_foto["obj"].ler_bytes(dados)
        return {"ok": r.placa is not None, "placa": r.placa, "bruto": r.bruto, "confianca": r.confianca,
                "ms": round((time.time() - t0) * 1000),
                "erro": None if r.placa else "Não consegui ler a placa. Tente de frente, mais perto e sem reflexo, ou digite."}

    def mensagens_desde(n0):
        hist = getattr(bus, "historico", [])
        return [{"topico": t, "conteudo": c} for t, c in hist[n0:]]
    def visitante_na_terceira_visita():
        """Para a demonstração: placa fictícia (dados/visitantes_demo.json) com 2 visitas e que ainda não veio hoje."""
        arq = Path(args.banco).with_name("visitantes_demo.json")
        if not arq.exists():
            return None
        hoje = dt.date.today().isoformat()
        with ctl._trava:
            hist = {h["id"]: h for h in ctl.banco.historico_visitantes(hoje)}
        for placa in json.loads(arq.read_text()):
            h = hist.get(ctl.banco.id_visitante(placa))
            if h and h["visitas"] == VISITAS_PARA_OFERECER_CADASTRO - 1 and h["ultima_dia"] != hoje and not h["oferta"]:
                return placa
        return None

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # ------------------------------------------------ apoio da área admin
        def _token(self):
            for parte in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = parte.strip().partition("=")
                if k == "sp_admin":
                    return v
            return None

        def _admin_ok(self):
            if auth.valido(self._token()):
                return True
            self._json({"erro": "Faça login."}, 401)
            return False

        def _corpo(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        def _periodo(self, q):
            hoje = dt.date.today()
            de = dt.date.fromisoformat(q.get("de", [""])[0] or (hoje - dt.timedelta(days=7)).isoformat())
            ate = dt.date.fromisoformat(q.get("ate", [""])[0] or hoje.isoformat())
            return dt.datetime.combine(de, dt.time()).timestamp(), dt.datetime.combine(ate, dt.time()).timestamp() + 86400

        def _admin_get(self, url, q):
            agora = time.time()
            arg = lambda k: (q.get(k) or [""])[0].strip()
            if url.path == "/api/admin/me":
                return self._json({"ok": True, "nomes_culto": NOMES_CULTO, "layout": layout.para_dict()})
            if url.path == "/api/admin/visao":
                dias = max(1, min(90, int(arg("dias") or 30)))
                with ctl._trava:
                    perms = ctl.banco.permanencias(agora - dias * 86400, None, agora=agora)
                return self._json(visao_geral(perms, layout, agora, dias))
            if url.path == "/api/admin/permanencias":
                try:
                    desde, ate = self._periodo(q)
                except ValueError:
                    return self._json({"erro": "Data inválida."}, 400)
                with ctl._trava:
                    perms = ctl.banco.permanencias(desde, ate, placa=arg("placa") or None, vaga=arg("vaga") or None,
                                                   categoria=arg("categoria") or None, agora=agora)
                perms = filtrar_por_culto(perms, int(arg("culto")) if arg("culto") else None)
                if arg("formato") == "csv":
                    return self._csv(perms)
                return self._json({"permanencias": perms})
            if url.path == "/api/admin/veiculos":
                with ctl._trava:
                    return self._json(ctl.banco.veiculos(arg("busca") or None))
            if url.path == "/api/admin/eventos":
                with ctl._trava:
                    return self._json(ctl.banco.eventos(300, arg("tipo") or None))
            if url.path == "/api/admin/saude":
                with ctl._trava:
                    return self._json(diagnosticar(layout, ctl.banco, agora, ctl.esp32))
            if url.path == "/api/admin/avisos":
                dias = max(1, min(90, int(arg("dias") or 30)))
                with ctl._trava:
                    evs = ctl.banco.eventos(5000, None, agora - dias * 86400)
                return self._json(avisos_por_culto(evs))
            if url.path == "/api/admin/visitantes":
                ctl.visitantes_hoje()                    # faço a limpeza da virada do dia antes de listar
                with ctl._trava:
                    hist = ctl.banco.historico_visitantes(dt.date.today().isoformat())
                return self._json({"visitantes": hist, "oferecer_a_partir_de": VISITAS_PARA_OFERECER_CADASTRO,
                                   "retencao_dias": RETENCAO_VISITANTES_DIAS})
            self.send_error(404)

        def _csv(self, perms):
            import csv
            import io
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(["data", "vaga", "placa", "categoria", "chegou", "saiu", "minutos", "origem"])
            for p in perms:
                w.writerow([dt.datetime.fromtimestamp(p["entrada"]).strftime("%d/%m/%Y"), p["vaga"], p["placa"] or "",
                            p["categoria"] or "", fmt_hora(p["entrada"]), fmt_hora(p["saida"]) if p["saida"] else "",
                            f"{p['duracao_s'] / 60:.1f}".replace(".", ","), p["origem"]])
            corpo = ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM: assim o Excel abre com os acentos certos
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="smartpark_{dt.date.today():%Y%m%d}.csv"')
            self.end_headers()
            self.wfile.write(corpo)

        def do_DELETE(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/api/admin/veiculos":
                if not self._admin_ok():
                    return
                placa = (q.get("placa") or [""])[0].upper()
                with ctl._trava:
                    ctl.banco.remover(placa)
                return self._json({"ok": True})
            self.send_error(404)

        def _json(self, obj, code=200):
            corpo = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)

        def _html(self, texto):
            corpo = texto.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)

        def _estatico(self, caminho):
            """Arquivos do design system (estilo.css, ui.js), planta.js e fontes locais: funciona sem internet."""
            nome = caminho.lstrip("/")
            arq = (PASTA_WEB / nome).resolve()
            tipo = TIPOS.get(arq.suffix)
            if not tipo or PASTA_WEB not in arq.parents or not arq.is_file():
                return self.send_error(404)
            corpo = arq.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "max-age=86400" if arq.suffix == ".woff2" else "no-cache")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path in ("/", "/equipe"):          # painel da equipe do estacionamento
                self._html(PAINEL_HTML)
            elif url.path == "/guarita":              # tablet da guarita, para o motorista que chega
                self._html(GUARITA_HTML)
            elif url.path == "/corredor":             # celular do funcionário de cada corredor
                self._html(CORREDOR_HTML)
            elif url.path == "/carro":                # celular de quem testa o sistema fingindo ser um carro
                self._html(CARRO_HTML)
            elif url.path == "/api/corredor":
                setor = (q.get("setor") or [""])[0].upper()
                if setor not in {v.zona for v in layout.vagas}:
                    return self._json({"erro": "Setor inválido.", "setores": sorted({v.zona for v in layout.vagas})}, 400)
                self._json(ctl.corredor(setor))
            elif url.path == "/simulador":
                if SIMULADOR_WEB.exists():
                    self._html(SIMULADOR_WEB.read_text(encoding="utf-8"))
                else:
                    self.send_error(404)
            elif url.path == "/historico":
                self._html(HISTORICO_HTML)
            elif url.path == "/admin":
                self._html(ADMIN_HTML)
            elif url.path.startswith("/api/admin/"):
                if self._admin_ok():
                    self._admin_get(url, q)
            elif url.path in ARQUIVOS_ESTATICOS or url.path.startswith("/fontes/"):
                self._estatico(url.path)
            elif url.path == "/api/sessao":           # o menu pergunta se o admin está logado (sem gerar erro 401)
                self._json({"admin": bool(auth.valido(self._token()))})
            elif url.path == "/visitantes":            # visitantes de hoje (a placa só fica até o fim do dia)
                self._json({"dia": dt.date.today().isoformat(), "visitantes": ctl.visitantes_hoje()})
            elif url.path == "/ping":                 # as telas usam para mostrar "Conectado"
                self._json({"ok": True, "agora": time.time()})
            elif url.path == "/layout":
                self._json(layout.para_dict())
            elif url.path == "/estado":
                p = ctl.painel
                with ctl._trava:
                    abertas = {v.id: ctl.banco.permanencia_aberta(v.id) for v in layout.vagas}
                self._json({
                    "agora": time.time(),             # mando o relógio do Raspberry (o do tablet pode estar atrasado)
                    "demo": bool(args.sem_mqtt),      # sem hardware, o painel já abre com o modo simulação ligado
                    "painel": p.__dict__,
                    "vagas": [{"id": v.id,
                               "estado": "ocupada" if ctl.ocupada[v.id] else ("reservada" if v.id in ctl.reservas else "livre"),
                               "placa": abertas[v.id]["placa"] if abertas[v.id] else None,
                               "desde": abertas[v.id]["entrada"] if abertas[v.id] else None}
                              for v in layout.vagas],
                })
            elif url.path == "/api/historico":
                agora = time.time()
                placa = (q.get("placa") or [""])[0].strip() or None
                vaga = (q.get("vaga") or [""])[0].strip() or None
                dia = (q.get("dia") or [""])[0]
                try:
                    d = dt.date.fromisoformat(dia) if dia else dt.date.today()
                except ValueError:
                    return self._json({"erro": "Data inválida. Use AAAA-MM-DD."}, 400)
                desde = dt.datetime.combine(d, dt.time()).timestamp()
                with ctl._trava:
                    perms = ctl.banco.permanencias(desde, desde + 86400, placa=placa, vaga=vaga, agora=agora)
                r = resumo(perms, layout, agora)
                self._json({"dia": d.isoformat(), "agora": agora, "permanencias": perms, "resumo": r})
            else:
                self.send_error(404)

        def do_POST(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/api/admin/login":
                if auth.bloqueado():
                    return self._json({"ok": False, "erro": "Muitas tentativas. Aguarde 1 minuto."}, 429)
                token = auth.entrar(str(self._corpo().get("senha", "")))
                if not token:
                    return self._json({"ok": False, "erro": "Senha incorreta."}, 403)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"sp_admin={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
                return
            if url.path == "/api/admin/logout":
                auth.sair(self._token())
                self.send_response(200)
                self.send_header("Set-Cookie", "sp_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.end_headers()
                return
            if url.path == "/api/admin/veiculos":
                if not self._admin_ok():
                    return
                d = self._corpo()
                placa = normalizar_placa(str(d.get("placa", "")))
                cat = str(d.get("categoria", "")).upper()
                if not placa:
                    return self._json({"ok": False, "erro": "Placa inválida. Use o formato ABC1D23 ou ABC1234."})
                if cat not in CATEGORIAS or cat == "VISITANTE":
                    return self._json({"ok": False, "erro": "Categoria inválida."})
                with ctl._trava:
                    ctl.banco.cadastrar(placa, cat, (str(d.get("apelido") or "").strip() or None))
                return self._json({"ok": True, "placa": placa, "categoria": cat})
            if url.path == "/api/carro/ler-placa":
                # corpo = a própria imagem (image/jpeg, image/png...), enviada pelo celular
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= MAX_FOTO:
                    return self._json({"ok": False, "erro": "Envie uma foto de até 12 MB."}, 413 if n else 400)
                return self._json(ler_foto(self.rfile.read(n)))
            if url.path == "/api/carro/chegar":
                # o carro de teste "para na cancela": o HC-SR04 detecta e a câmera entrega esta placa
                d = self._corpo()
                bruta = str(d.get("placa") or "")
                placa = normalizar_placa(bruta) if bruta else None
                if bruta and not placa:
                    return self._json({"ok": False, "erro": "Placa inválida. Use o formato ABC1D23 ou ABC1234."}, 400)
                if not isinstance(ctl.lpr, LPRDemo):
                    return self._json({"ok": False, "erro": "Com câmera real ligada, o carro de teste não substitui a leitura."}, 409)
                n0 = len(getattr(bus, "historico", []))
                ctl.lpr.proxima = placa                      # None = placa ilegível (testa o caminho do visitante)
                if not placa:
                    ctl.lpr.proxima = "ILEGIVEL"
                antes = ctl.painel.instante
                bus.publicar(f"{args.prefixo}/entrada/presenca", "1")
                # com broker MQTT de verdade (Wokwi), a chegada volta pelo broker: espero o painel mudar
                limite = time.time() + 5
                while ctl.painel.instante == antes and time.time() < limite:
                    time.sleep(0.05)
                with ctl._trava:
                    cat, apelido = ctl.banco.categoria_de(placa)
                    painel = dict(ctl.painel.__dict__)
                return self._json({"ok": True, "placa": placa, "cadastro": {"categoria": cat, "apelido": apelido},
                                   "painel": painel, "mensagens": mensagens_desde(n0)})
            if url.path == "/api/carro/vaga":
                # o sensor da vaga muda de estado (carro estacionou ou saiu)
                d = self._corpo()
                vaga, estado = str(d.get("vaga") or ""), str(d.get("estado") or "").upper()
                if vaga not in {v.id for v in layout.vagas} or estado not in ("OCUPADA", "LIVRE"):
                    return self._json({"ok": False, "erro": "Vaga ou estado inválido."}, 400)
                n0 = len(getattr(bus, "historico", []))
                bus.publicar(f"{args.prefixo}/vagas/{vaga}", estado)
                with ctl._trava:
                    linha = ctl.banco.permanencia_aberta(vaga)
                    aberta = dict(linha) if linha else None
                    setor = layout.vaga(vaga).zona
                return self._json({"ok": True, "vaga": vaga, "estado": estado, "permanencia": aberta,
                                   "corredor": ctl.corredor(setor), "mensagens": mensagens_desde(n0)})
            if url.path == "/api/corredor/oferta":
                d = self._corpo()
                r = ctl.registrar_oferta(int(d.get("aviso") or 0), str(d.get("resultado", "")))
                return self._json(r, 200 if r["ok"] else 409)
            if url.path == "/guarita/preferencial":
                # {"necessidade": "IDOSO" | "PCD" | null, "origem": "guarita" | "equipe"}
                d = self._corpo()
                origem = "equipe" if d.get("origem") == "equipe" else "guarita"
                nec = d.get("necessidade")
                r = ctl.trocar_para_preferencial(nec.upper() if isinstance(nec, str) else None, origem)
                return self._json(r, 200 if r["ok"] else 409)
            if url.path == "/simular/chegada":
                if isinstance(ctl.lpr, LPRDemo) and q.get("placa"):
                    ctl.lpr.proxima = q["placa"][0].upper()
                elif isinstance(ctl.lpr, LPRDemo) and q.get("visitante"):
                    # placa nova que não está no cadastro (?visitante=1); "repetir" usa a última de hoje
                    hoje = ctl.visitantes_hoje()
                    modo = q["visitante"][0]
                    if modo == "repetir" and hoje:
                        ctl.lpr.proxima = hoje[0]["placa"]
                    elif modo == "terceira":
                        # demonstração: um visitante fictício que já veio 2 vezes em outros dias
                        ctl.lpr.proxima = visitante_na_terceira_visita() or placa_aleatoria(random.Random())
                    else:
                        ctl.lpr.proxima = placa_aleatoria(random.Random())
                bus.publicar(f"{args.prefixo}/entrada/presenca", "1")
                self._json({"ok": True})
            elif url.path == "/simular/vaga":
                bus.publicar(f"{args.prefixo}/vagas/{q['id'][0]}", q["estado"][0].upper())
                self._json({"ok": True})
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("0.0.0.0", args.porta_web), H)
    print(f"Painel da equipe:      http://localhost:{args.porta_web}/equipe")
    print(f"Tablet da guarita:     http://localhost:{args.porta_web}/guarita")
    print(f"App do corredor:       http://localhost:{args.porta_web}/corredor")
    print("  (em outro aparelho da mesma rede, troque 'localhost' pelo IP deste computador)")
    print(f"Área administrativa:   http://localhost:{args.porta_web}/admin")
    if auth.senha_gerada:
        print("")
        print(f"  SENHA DO ADMIN: {auth.senha_gerada}   (anote: ela só aparece agora)")
        print("  Para trocar: python scripts/senha_admin.py")
    print("\n(Ctrl+C para sair)")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
