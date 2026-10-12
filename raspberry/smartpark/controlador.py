"""
Controlador central: é o "cérebro" que roda no Raspberry Pi.

O que acontece quando um carro chega à cancela:

    HC-SR04 (ESP32) ──"presença"──> Pi
    Pi: câmera -> LPR -> placa -> banco -> categoria
    Pi: preditor (demanda dos próximos 5 min) + estado das vagas -> Alocador
    Pi ──"ABRIR"──> ESP32 (servo da cancela)
    Pi ──painel──> ESP32 (OLED), tablet do motorista, painel da equipe e app do corredor

Quando o sensor de uma vaga muda para OCUPADA, eu encerro a reserva daquela vaga.
Reservas que não se confirmam em RESERVA_EXPIRA_S são liberadas para outro carro.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import itertools
import time
from collections import deque
from dataclasses import dataclass, field

from .alocador import Alocador, EstadoPatio, Reserva
from .banco import Banco
from .layout import Layout
from .lotacao import prever_lotacao, mensagem as msg_lotacao

RESERVA_EXPIRA_S = 300
VISITAS_PARA_OFERECER_CADASTRO = 3   # na 3ª visita (em dias diferentes) o funcionário do corredor oferece o cadastro
JANELA_CORREDOR_S = 3 * 3600         # o app do corredor mostra os carros das últimas 3 horas
VAGAS_REFERENCIA = 48   # tamanho do estacionamento que usei para treinar o preditor

# (dia da semana: seg=0 ... dom=6, "HH:MM", índice do culto no preditor)
HORARIOS_CULTO = [(6, "08:30", 0), (6, "11:00", 1), (6, "17:00", 2), (6, "19:30", 3)]   # todos aos domingos


def culto_de_referencia(agora: dt.datetime):
    """Devolvo (índice_do_culto, minutos_relativos_ao_início, início) do culto mais próximo."""
    melhor = None
    for dia, hhmm, idx in HORARIOS_CULTO:
        h, m = map(int, hhmm.split(":"))
        for delta in (-7, 0, 7):
            base = agora.date() + dt.timedelta(days=(dia - agora.weekday()) + delta)
            inicio = dt.datetime.combine(base, dt.time(h, m))
            rel = (agora - inicio).total_seconds() / 60
            if melhor is None or abs(rel) < abs(melhor[1]):
                melhor = (idx, rel, inicio)
    return melhor


@dataclass
class Painel:
    placa: str = "--"
    categoria: str = "--"
    vaga: str = "--"
    seta: str = "FRENTE"
    instrucoes: list = field(default_factory=list)
    msg: str = "Bem-vindo!"
    previsao_5min: float | None = None
    livres: int = 0
    instante: float = 0.0
    alerta: dict = field(default_factory=lambda: {"nivel": "ok", "minutos": None, "msg": ""})
    culto: str = ""
    rota: list = field(default_factory=list)       # pontos [x, y] da guarita até a vaga
    setor: str = ""
    caminhada_m: float | None = None             # distância da vaga até a porta da igreja
    visitante: bool = False                      # placa não cadastrada (ou ilegível)
    necessidade: str | None = None               # IDOSO/PCD declarado na guarita (visitante) ou pela equipe
    entradas_hoje: int = 0                       # visitante: quantas vezes entrou hoje (1 = primeira visita)
    visitas: int = 0                             # visitante: dias diferentes em que veio (histórico pseudônimo)
    oferecer_cadastro: bool = False              # 3ª visita: o corredor foi avisado para oferecer cadastro
    atualizado: float = 0.0                      # última mudança da vaga indicada (troca para preferencial)
    apelido: str | None = None                   # nome/apelido do cadastro (o app do corredor mostra)


class Controlador:
    def __init__(self, layout: Layout, banco: Banco, barramento, lpr, preditor=None,
                 estrategia="preditiva", relogio=time.time, prefixo="smartpark"):
        self.lay = layout
        self.banco = banco
        self.bus = barramento
        self.lpr = lpr
        self.preditor = preditor
        self.alocador = Alocador(layout, estrategia)
        self.relogio = relogio
        self.p = prefixo
        self.ocupada = {v.id: False for v in layout.vagas}
        self.reservas: dict[str, Reserva] = {}       # vaga -> reserva
        self.dono_reserva: dict[str, tuple] = {}     # vaga -> (placa, categoria)
        self.painel = Painel(livres=len(layout.vagas))
        self._trava = threading.Lock()
        self._ultima_anonimizacao = 0.0
        self._dia_visitantes = None
        # carros mandados para cada corredor (é o que alimenta o app do funcionário do corredor)
        self.direcionados: deque = deque(maxlen=600)
        self._ids = itertools.count(1)
        self._dir_atual: dict | None = None              # o registro do carro que está na cancela agora
        self.avisos_cadastro: list[dict] = []            # "ofereça cadastro" (3ª visita) para o corredor
        self.notificadores = []                      # funções (texto, previsão) chamadas a cada alerta novo
        self._avisados: set[tuple] = set()           # (início do culto, nível) já avisados
        self._lotacoes: set[float] = set()           # cultos em que a lotação real já foi registrada
        self.esp32 = {"estado": "desconhecido", "desde": None}
        self.culto_ensaio: tuple[int, float] | None = None   # (culto, início) para eu demonstrar fora do horário de culto
        self.escala = len(layout.vagas) / VAGAS_REFERENCIA    # 1,0 na igreja; 0,125 na maquete
        self.bus.assinar(f"{self.p}/entrada/presenca", self._ao_detectar_veiculo)
        self.bus.assinar(f"{self.p}/vagas/+", self._ao_mudar_vaga)
        self.bus.assinar(f"{self.p}/esp32/status", self._ao_status_esp32)

    # ------------------------------------------------------------ eventos
    def _ao_mudar_vaga(self, topico, payload):
        vid = topico.rsplit("/", 1)[-1]
        if vid not in self.ocupada:
            return
        with self._trava:
            agora = self.relogio()
            ocupada = payload.strip().upper() == "OCUPADA"
            self.ocupada[vid] = ocupada
            if ocupada:
                # o sensor não lê a placa: associo ao carro para quem a vaga foi reservada
                atribuida = vid in self.reservas
                placa, categoria = self.dono_reserva.pop(vid, (None, None))
                if atribuida:
                    del self.reservas[vid]
                    self.bus.publicar(f"{self.p}/vagas/{vid}/reserva", "0")
                    self._marcar(vid, "a_caminho", "estacionou", agora)
                else:
                    # carro que não passou pela indicação (ou parou na vaga errada): o funcionário do corredor precisa saber
                    self.direcionados.append({"id": next(self._ids), "instante": agora, "placa": None, "categoria": None,
                                              "necessidade": None, "visitante": False, "visitas": 0, "vaga": vid,
                                              "setor": self.lay.vaga(vid).zona, "estado": "sem_indicacao", "mudou_em": agora,
                                              "oferecer_cadastro": False})
                self.banco.abrir_permanencia(vid, agora, placa, categoria, atribuida)
            else:
                self._marcar(vid, ("estacionou", "sem_indicacao"), "saiu", agora)
                self.banco.fechar_permanencia(vid, agora)
            self.banco.registrar("VAGA_OCUPADA" if ocupada else "VAGA_LIVRE", vaga=vid, instante=agora)
            self.painel.livres = self._livres_count()
            self._atualizar_alertas(agora)

    def _ao_status_esp32(self, topico, payload):
        self.esp32 = {"estado": payload.strip().lower(), "desde": self.relogio()}

    def _ao_detectar_veiculo(self, topico, payload, placa_simulada: str | None = None):
        if payload.strip() != "1":
            return
        with self._trava:
            agora = self.relogio()
            self._expirar_reservas(agora)
            self._manutencao_lgpd(agora)
            leitura = self.lpr.ler(placa_simulada) if placa_simulada is not None else self.lpr.ler()
            categoria, apelido = self.banco.categoria_de(leitura.placa)
            visitante = categoria == "VISITANTE"
            necessidade, entradas = None, 0
            if visitante and leitura.placa:
                # visitante: a placa fica guardada só hoje; se ele já declarou idoso/PcD hoje, vale de novo
                reg = self.banco.registrar_visitante(leitura.placa, self._dia(agora), agora)
                necessidade, entradas = reg["necessidade"], reg["entradas"]
                visitas, oferta = reg["visitas"], reg["oferta"]
            else:
                visitas, oferta = 0, None
            placa_reg = leitura.placa or None
            self.banco.registrar("ENTRADA", placa=placa_reg, categoria=categoria, instante=agora)

            p = self.painel
            p.placa, p.categoria, p.instante = leitura.placa or "ILEGÍVEL", categoria, agora
            p.visitante, p.necessidade, p.entradas_hoje, p.visitas = visitante, necessidade, entradas, visitas
            p.oferecer_cadastro = False
            p.apelido = apelido if not visitante else None
            if visitante:
                p.msg = ("Bem-vindo de volta!" if entradas > 1 else
                         "Que bom ver você de novo!" if visitas > 1 else "Seja bem-vindo, visitante!")
            else:
                p.msg = f"Olá, {apelido}!" if apelido else "Bom culto!"
            self._dir_atual = None
            dec = self._atribuir(necessidade or categoria, placa_reg, categoria, agora)
            if dec.vaga is not None:
                self.bus.publicar(f"{self.p}/cancela/cmd", "ABRIR")
                # 3ª visita (ou mais) e ninguém ofereceu o cadastro ainda: aviso o funcionário do corredor
                if visitante and placa_reg and visitas >= VISITAS_PARA_OFERECER_CADASTRO and oferta is None and entradas == 1:
                    aviso = {"id": next(self._ids), "instante": agora, "placa": placa_reg, "visitas": visitas,
                             "vaga": dec.vaga, "setor": self.lay.vaga(dec.vaga).zona, "resolvido": None}
                    self.avisos_cadastro.append(aviso)
                    self._dir_atual["oferecer_cadastro"] = p.oferecer_cadastro = True
                    self.banco.registrar("OFERECER_CADASTRO", placa=placa_reg, categoria=categoria, vaga=dec.vaga, instante=agora,
                                         detalhe=json.dumps({"visitas": visitas, "setor": aviso["setor"]}))
                    self.bus.publicar(f"{self.p}/corredor/{aviso['setor']}/aviso", json.dumps(aviso, ensure_ascii=False))
            return dec

    def trocar_para_preferencial(self, necessidade: str | None, origem: str = "guarita") -> dict:
        """O carro que acabou de chegar precisa de vaga de idoso/PcD (ou volta para uma comum, com None).
        origem='guarita': o próprio motorista tocou no tablet (só visitantes, até 60 s depois da leitura);
        origem='equipe' : a equipe trocou pelo painel (qualquer categoria que não tenha vaga preferencial própria)."""
        if necessidade not in (None, "IDOSO", "PCD"):
            return {"ok": False, "erro": "Necessidade inválida."}
        with self._trava:
            agora, p = self.relogio(), self.painel
            if not p.instante:
                return {"ok": False, "erro": "Nenhum carro na cancela."}
            if origem == "guarita" and (not p.visitante or agora - p.instante > 60):
                return {"ok": False, "erro": "A troca pelo tablet vale só para visitantes, logo após a leitura da placa."}
            if p.categoria in ("IDOSO", "PCD"):
                return {"ok": False, "erro": "Este carro já é cadastrado com vaga preferencial."}
            if p.vaga != "--" and self.ocupada.get(p.vaga):
                return {"ok": False, "erro": "O carro já estacionou."}
            if p.necessidade == necessidade:
                return {"ok": True, "vaga": p.vaga}
            placa_reg = None if p.placa == "ILEGÍVEL" else p.placa
            if p.vaga in self.reservas:                       # primeiro devolvo a vaga que tinha indicado
                del self.reservas[p.vaga]
                self.dono_reserva.pop(p.vaga, None)
                self.bus.publicar(f"{self.p}/vagas/{p.vaga}/reserva", "0")
            anterior = self._dir_atual
            if anterior and anterior["estado"] == "a_caminho":
                anterior["estado"], anterior["mudou_em"] = "trocou", agora
            p.necessidade = necessidade
            if p.visitante and placa_reg:
                self.banco.declarar_necessidade(placa_reg, self._dia(agora), necessidade)
            self.banco.registrar("NECESSIDADE_DECLARADA", placa=placa_reg, categoria=p.categoria, instante=agora,
                                 detalhe=json.dumps({"necessidade": necessidade, "origem": origem}, ensure_ascii=False))
            dec = self._atribuir(necessidade or p.categoria, placa_reg, p.categoria, agora)
            if dec.vaga is not None and anterior:
                anterior["trocou_para"] = dec.vaga
                self._dir_atual["oferecer_cadastro"] = anterior.get("oferecer_cadastro", False)
                for a in self.avisos_cadastro:               # o aviso de cadastro segue o carro para o novo corredor
                    if a["resolvido"] is None and a["placa"] == placa_reg and a["vaga"] == anterior["vaga"]:
                        a["vaga"], a["setor"] = dec.vaga, self.lay.vaga(dec.vaga).zona
            return {"ok": dec.vaga is not None, "vaga": p.vaga, "erro": None if dec.vaga else "Sem vaga disponível."}

    def _atribuir(self, categoria_vaga, placa_reg, categoria_registro, agora):
        """Escolho a vaga e atualizo reserva, painel, eventos e MQTT. Precisa ser chamado com a trava."""
        previsao = self._prever(agora)
        estado = EstadoPatio(agora, self._livres(), list(self.reservas.values()), previsao)
        dec = self.alocador.decidir(categoria_vaga, estado)
        p = self.painel
        p.previsao_5min, p.atualizado = previsao, agora
        p.rota, p.setor, p.caminhada_m = [], "", None
        if dec.vaga is None:
            p.vaga, p.seta, p.instrucoes = "--", "PARE", []
            p.msg = "Estacionamento lotado. Procure a equipe de recepção."
            self.banco.registrar("LOTADO", placa=placa_reg, categoria=categoria_registro, instante=agora)
        else:
            self.reservas[dec.vaga] = Reserva(dec.vaga, dec.arestas, agora)
            self.dono_reserva[dec.vaga] = (placa_reg, categoria_registro)
            p.vaga, p.instrucoes = dec.vaga, dec.instrucoes
            vg = self.lay.vaga(dec.vaga)
            p.rota, p.setor, p.caminhada_m = dec.pontos, vg.zona, round(self.lay.distancia_caminhada(vg))
            p.seta = self._seta(dec.instrucoes)
            self.banco.registrar("VAGA_ATRIBUIDA", placa=placa_reg, categoria=categoria_registro, vaga=dec.vaga, instante=agora)
            self._dir_atual = {"id": next(self._ids), "instante": agora, "placa": p.placa, "categoria": categoria_registro,
                               "apelido": p.apelido,
                               "necessidade": p.necessidade, "visitante": p.visitante, "visitas": p.visitas,
                               "vaga": dec.vaga, "setor": vg.zona, "estado": "a_caminho", "mudou_em": agora,
                               "oferecer_cadastro": False}
            self.direcionados.append(self._dir_atual)
            self.bus.publicar(f"{self.p}/vagas/{dec.vaga}/reserva", "1")
        p.livres = self._livres_count()
        self._atualizar_alertas(agora)
        self.bus.publicar(f"{self.p}/guarita/painel", json.dumps(
            {"placa": p.placa, "categoria": p.necessidade or p.categoria, "vaga": p.vaga, "seta": p.seta, "msg": p.msg}, ensure_ascii=False))
        return dec

    def _marcar(self, vaga, de, para, agora):
        """Mudo o estado do carro mais recente que mandei para 'vaga' (app do corredor)."""
        de = (de,) if isinstance(de, str) else de
        for d in reversed(self.direcionados):
            if d["vaga"] == vaga and d["estado"] in de:
                d["estado"], d["mudou_em"] = para, agora
                return d

    def corredor(self, setor: str) -> dict:
        """Tudo o que o funcionário do corredor precisa ver: carros a caminho, estacionados e avisos."""
        with self._trava:
            agora = self.relogio()
            ordem = {"a_caminho": 0, "sem_indicacao": 1, "estacionou": 2, "trocou": 3, "expirou": 4, "saiu": 5}
            carros = [dict(d) for d in self.direcionados if d["setor"] == setor and agora - d["instante"] <= JANELA_CORREDOR_S]
            carros.sort(key=lambda d: (ordem[d["estado"]], -d["instante"]))
            vagas = [v for v in self.lay.vagas if v.zona == setor]
            return {"setor": setor, "agora": agora, "carros": carros,
                    "avisos": [a for a in self.avisos_cadastro if a["setor"] == setor and a["resolvido"] is None],
                    "livres": sum(1 for v in vagas if not self.ocupada[v.id] and v.id not in self.reservas),
                    "total": len(vagas), "setores": sorted({v.zona for v in self.lay.vagas})}

    def registrar_oferta(self, aviso_id: int, resultado: str) -> dict:
        """Resultado da oferta de cadastro feita no corredor: 'aceitou', 'recusou' ou 'nao_encontrei'."""
        if resultado not in ("aceitou", "recusou", "nao_encontrei"):
            return {"ok": False, "erro": "Resultado inválido."}
        with self._trava:
            agora = self.relogio()
            aviso = next((a for a in self.avisos_cadastro if a["id"] == aviso_id and a["resolvido"] is None), None)
            if not aviso:
                return {"ok": False, "erro": "Aviso não encontrado ou já resolvido."}
            aviso["resolvido"], aviso["resolvido_em"] = resultado, agora
            if resultado != "nao_encontrei":                # se não encontrou a pessoa, aviso de novo na próxima visita
                self.banco.registrar_oferta(aviso["placa"], resultado, agora)
            self.banco.registrar("CADASTRO_OFERECIDO", placa=aviso["placa"], vaga=aviso["vaga"], instante=agora,
                                 detalhe=json.dumps({"resultado": resultado, "visitas": aviso["visitas"]}))
            return {"ok": True}

    def _dia(self, agora) -> str:
        return dt.datetime.fromtimestamp(agora).date().isoformat()

    def _manutencao_lgpd(self, agora):
        """Regras de retenção: placa de cadastrado fica 30 dias; de visitante, só até o fim do dia."""
        if agora - self._ultima_anonimizacao > 3600:
            self.banco.anonimizar_antigos(agora)
            self._ultima_anonimizacao = agora
        dia = self._dia(agora)
        if dia != self._dia_visitantes:
            self.banco.limpar_visitantes(dia)
            self.banco.limpar_historico_visitantes(dia)
            self._dia_visitantes = dia
            self.avisos_cadastro = [a for a in self.avisos_cadastro if a["resolvido"] is None and agora - a["instante"] < 86400]

    def visitantes_hoje(self) -> list[dict]:
        with self._trava:
            agora = self.relogio()
            self._manutencao_lgpd(agora)
            return self.banco.visitantes_do_dia(self._dia(agora))

    # ------------------------------------------------------------ apoio
    def _livres(self):
        return {v for v, oc in self.ocupada.items() if not oc and v not in self.reservas}

    def _livres_count(self):
        return len(self._livres())

    def _livres_comuns_count(self):
        # O aviso de lotação olha só as vagas comuns: as preferenciais são reservadas por lei e não
        # servem à maioria dos motoristas. Sem isso, com uma vaga de idoso livre, o pátio "nunca lotava".
        return sum(1 for v in self._livres() if self.lay.vaga(v).tipo == "comum")

    def _expirar_reservas(self, agora):
        for vid in [v for v, r in self.reservas.items() if agora - r.instante > RESERVA_EXPIRA_S]:
            del self.reservas[vid]
            self.dono_reserva.pop(vid, None)
            self._marcar(vid, "a_caminho", "expirou", agora)
            self.bus.publicar(f"{self.p}/vagas/{vid}/reserva", "0")

    def _contexto(self, agora):
        """(culto, minutos em relação ao início, início em timestamp, chegadas do culto, ocupação)."""
        if self.culto_ensaio:
            idx, t0 = self.culto_ensaio
            rel_min = (agora - t0) / 60
        else:
            idx, rel_min, inicio = culto_de_referencia(dt.datetime.fromtimestamp(agora))
            t0 = inicio.timestamp()
        chegadas = [(t - t0) / 60 for t in self.banco.chegadas_por_minuto(t0 - 3600) if t <= agora]
        ocup = sum(self.ocupada.values()) / len(self.ocupada)
        return idx, rel_min, t0, chegadas, ocup

    def _prever(self, agora):
        if self.preditor is None:
            return None
        idx, rel_min, _, chegadas, ocup = self._contexto(agora)
        if not -60 <= rel_min <= 30:
            return 0.0
        if abs(self.escala - 1) < 0.05:
            return self.preditor.prever(rel_min, chegadas, idx, ocup)
        # estacionamento de outro tamanho (maquete): uso o perfil histórico proporcional ao número de vagas
        return self.escala * self.preditor.perfil_medio.get((idx, int(round(rel_min))), 0.0)

    # ------------------------------------------------------- aviso de lotação
    ORDEM_NIVEL = {"ok": 0, "atencao": 1, "critico": 2, "lotado": 3}

    def verificar(self):
        """Chamo isto a cada ~30 s para atualizar o aviso mesmo quando nenhum carro chega."""
        with self._trava:
            agora = self.relogio()
            self._expirar_reservas(agora)
            self._manutencao_lgpd(agora)
            self.painel.livres = self._livres_count()
            return self._atualizar_alertas(agora)

    def _atualizar_alertas(self, agora):
        idx, rel_min, t0, chegadas, ocup = self._contexto(agora)
        livres = self._livres_comuns_count()
        prev = prever_lotacao(self.preditor, rel_min, chegadas, idx, ocup, livres,
                              escala=1.0 if abs(self.escala - 1) < 0.05 else self.escala)
        perto_do_culto = -60 <= rel_min <= 90
        if prev["nivel"] == "lotado" and not perto_do_culto:
            prev = {**prev, "nivel": "ok"}          # pátio cheio fora de horário de culto não é alerta
        prev["msg"] = msg_lotacao(prev)
        from .admin import NOMES_CULTO
        nome = NOMES_CULTO[idx] + (" (ensaio)" if self.culto_ensaio else "")
        self.painel.culto = (f"{nome} · começa em {-rel_min:.0f} min" if -60 <= rel_min < 0
                             else f"{nome} · começou há {rel_min:.0f} min" if 0 <= rel_min <= 120 else "")
        prev["previsto_para"] = agora + prev["minutos"] * 60 if prev["minutos"] is not None else None
        self.painel.alerta = prev

        # registro a lotação real para depois medir com quanta antecedência o sistema avisou
        if livres == 0 and perto_do_culto and t0 not in self._lotacoes:
            self._lotacoes.add(t0)
            self.banco.registrar("LOTOU", detalhe=json.dumps({"culto_inicio": t0, "rel_min": round(rel_min, 1)}), instante=agora)

        # só gero alerta novo quando o nível sobe dentro do mesmo culto
        if prev["nivel"] != "ok" and perto_do_culto and (t0, prev["nivel"]) not in self._avisados:
            ja = max((self.ORDEM_NIVEL[n] for (c, n) in self._avisados if c == t0), default=0)
            self._avisados.add((t0, prev["nivel"]))
            if self.ORDEM_NIVEL[prev["nivel"]] > ja:
                info = {"nivel": prev["nivel"], "minutos": prev["minutos"], "livres": livres,
                        "culto_inicio": t0, "rel_min": round(rel_min, 1), "msg": prev["msg"]}
                self.banco.registrar("ALERTA_LOTACAO", detalhe=json.dumps(info, ensure_ascii=False), instante=agora)
                self.bus.publicar(f"{self.p}/alertas/lotacao", json.dumps(info, ensure_ascii=False))
                for notificar in self.notificadores:
                    try:
                        notificar(prev["msg"], info)
                    except Exception as e:  # se o Telegram cair, a guarita não pode parar por isso
                        print(f"[aviso] falha ao notificar: {e}")
        return prev

    @staticmethod
    def _seta(instrucoes):
        for i in instrucoes:
            if "esquerda" in i:
                return "ESQUERDA"
            if "direita" in i:
                return "DIREITA"
        return "FRENTE"
