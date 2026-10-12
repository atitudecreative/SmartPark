"""Meus testes automatizados. Para rodar: python -m pytest -q"""
import datetime as dt
import json
import random

import pytest

from smartpark.alocador import Alocador, EstadoPatio, Reserva
from smartpark.banco import Banco
from smartpark.barramento import BarramentoMemoria, _casa
from smartpark.controlador import Controlador
from smartpark.layout import layout_igreja, layout_maquete
from smartpark.lpr import LPRSimulado, normalizar_placa
from smartpark.roteamento import a_estrela
from simulador.chegadas import CULTOS, gerar_chegadas
from simulador.motor import Simulacao


# ------------------------------------------------------------------ LPR
@pytest.mark.parametrize("bruto,esperado", [
    ("ABC1D23", "ABC1D23"),
    ("abc-1d23", "ABC1D23"),
    ("A8C1D23", "ABC1D23"),   # 8 lido no lugar de B (posição de letra)
    ("ABC1DZ3", "ABC1D23"),   # Z lido no lugar de 2 (posição de número)
    ("0BC1234", "OBC1234"),   # padrão antigo
    ("ABC12", None),
])
def test_normalizar_placa(bruto, esperado):
    assert normalizar_placa(bruto) == esperado


def test_lpr_simulado_taxas():
    lpr = LPRSimulado(taxa_ilegivel=0.1, taxa_troca=0.0, seed=1)
    leituras = [lpr.ler("ABC1D23").placa for _ in range(2000)]
    ilegiveis = leituras.count(None) / len(leituras)
    assert 0.07 < ilegiveis < 0.13


# ------------------------------------------------------------- roteamento
def test_a_estrela_menor_caminho():
    lay = layout_igreja()
    custo, caminho = a_estrela(lay, "G", "TC", lambda a, b: lay.aresta(a, b).comprimento)
    assert caminho[0] == "G" and caminho[-1] == "TC"
    assert custo == pytest.approx(25 + 35 + 35 + 26, abs=0.5)


# --------------------------------------------------------------- alocador
def test_mais_proxima_escolhe_vaga_do_corredor_A():
    lay = layout_igreja()
    al = Alocador(lay, "mais_proxima")
    est = EstadoPatio(0, {v.id for v in lay.vagas})
    dec = al.decidir("VISITANTE", est)       # visitante não tem penalidade de setor: vale a distância pura
    assert dec.vaga.startswith("A") and lay.vaga(dec.vaga).tipo == "comum"


def test_prioritario_recebe_vaga_preferencial():
    lay = layout_igreja()
    for estrategia in ("mais_proxima", "reativa", "preditiva"):
        dec = Alocador(lay, estrategia).decidir("IDOSO", EstadoPatio(0, {v.id for v in lay.vagas}, previsao_5min=5))
        assert lay.vaga(dec.vaga).tipo in ("idoso", "pcd")


def test_comum_nunca_recebe_preferencial():
    lay = layout_igreja()
    so_pref = {v.id for v in lay.vagas if v.tipo != "comum"}
    dec = Alocador(lay, "reativa").decidir("MEMBRO", EstadoPatio(0, so_pref))
    assert dec.vaga is None  # lotado para ele


def test_equipe_vai_para_o_fundo():
    lay = layout_igreja()
    dec = Alocador(lay, "reativa").decidir("EQUIPE", EstadoPatio(0, {v.id for v in lay.vagas}))
    assert lay.vaga(dec.vaga).zona == "C"


def test_preditiva_espalha_sob_demanda_alta():
    """Com um carro já manobrando à frente em A: se a demanda é baixa, vale esperar (A fica mais perto
    da porta); se a previsão é de muita gente chegando, a preditiva já desvia para B."""
    lay = layout_igreja()
    livres = {v.id for v in lay.vagas if v.tipo == "comum"}
    rotas_a = [Reserva(f"A{n:02d}", [("G", "J1"), ("J1", "TA")], 0) for n in range(5, 6)]
    for r in rotas_a:
        livres.discard(r.vaga)
    # uso VISITANTE (sem penalidade de setor) para isolar o efeito do congestionamento
    calma = Alocador(lay, "preditiva").decidir("VISITANTE", EstadoPatio(0, livres, rotas_a, previsao_5min=0))
    pico = Alocador(lay, "preditiva").decidir("VISITANTE", EstadoPatio(0, livres, rotas_a, previsao_5min=14))
    assert lay.vaga(calma.vaga).zona == "A"
    assert lay.vaga(pico.vaga).zona != "A"


# ------------------------------------------------------------- barramento
def test_curingas_mqtt():
    assert _casa("smartpark/vagas/+", "smartpark/vagas/A01")
    assert not _casa("smartpark/vagas/+", "smartpark/vagas/A01/reserva")
    assert _casa("smartpark/#", "smartpark/vagas/A01/reserva")


# ------------------------------------------------------------ controlador
def test_fluxo_completo_da_guarita():
    lay = layout_maquete()
    banco = Banco()
    banco.cadastrar("ABC1D23", "PCD", "Ana")
    bus = BarramentoMemoria()

    class LPRFixo:
        def ler(self, *_):
            return LPRSimulado(0, 0).ler("ABC1D23")

    ctl = Controlador(lay, banco, bus, LPRFixo(), estrategia="reativa")
    bus.publicar("smartpark/entrada/presenca", "1")
    assert ("smartpark/cancela/cmd", "ABRIR") in bus.historico
    painel = json.loads([p for t, p in bus.historico if t == "smartpark/guarita/painel"][-1])
    assert painel["categoria"] == "PCD" and lay.vaga(painel["vaga"]).tipo == "pcd"
    assert painel["vaga"] in ctl.reservas
    bus.publicar(f"smartpark/vagas/{painel['vaga']}", "OCUPADA")  # sensor confirma
    assert painel["vaga"] not in ctl.reservas and ctl.ocupada[painel["vaga"]]


def test_lotado():
    lay = layout_maquete()
    bus = BarramentoMemoria()
    ctl = Controlador(lay, Banco(), bus, LPRSimulado(0, 0, seed=1), estrategia="reativa")
    for v in lay.vagas:
        bus.publicar(f"smartpark/vagas/{v.id}", "OCUPADA")
    ctl._ao_detectar_veiculo("", "1", placa_simulada="XYZ9A99")
    assert ctl.painel.vaga == "--" and ("smartpark/cancela/cmd", "ABRIR") not in bus.historico


# -------------------------------------------------------------- simulação
def test_simulacao_estaciona_todos_e_sistema_ajuda():
    lay = layout_igreja()
    ch = gerar_chegadas(CULTOS[1], random.Random(1))
    sem = Simulacao(lay, ch, "sem_sistema", 1, seed=0).rodar()
    rea = Simulacao(lay, ch, "reativa", 1, seed=0).rodar()
    if len(ch) <= len(lay.vagas):
        assert rea["estacionados"] == len(ch)
    assert rea["tempo_medio_s"] < sem["tempo_medio_s"]


# ------------------------------------------------------------ permanências
class Relogio:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _ctl_com_relogio(placa="ABC1D23", categoria="IDOSO"):
    lay = layout_maquete()
    banco = Banco()
    banco.cadastrar(placa, categoria, "Dona Maria")
    bus = BarramentoMemoria()
    rel = Relogio()

    class LPRFixo:
        def ler(self, *_):
            return LPRSimulado(0, 0).ler(placa)

    ctl = Controlador(lay, banco, bus, LPRFixo(), estrategia="reativa", relogio=rel)
    return ctl, bus, banco, rel


def test_permanencia_registra_placa_vaga_e_tempo():
    ctl, bus, banco, rel = _ctl_com_relogio()
    bus.publicar("smartpark/entrada/presenca", "1")
    vaga = ctl.painel.vaga
    rel.t += 40
    bus.publicar(f"smartpark/vagas/{vaga}", "OCUPADA")
    rel.t += 5400                                   # 1h30 de culto
    bus.publicar(f"smartpark/vagas/{vaga}", "LIVRE")
    [p] = banco.permanencias(agora=rel.t)
    assert p["vaga"] == vaga and p["placa"] == "ABC1D23" and p["categoria"] == "IDOSO"
    assert p["origem"] == "atribuida" and not p["em_andamento"]
    assert p["duracao_s"] == pytest.approx(5400)


def test_carro_fora_da_vaga_indicada_fica_sem_placa():
    ctl, bus, banco, rel = _ctl_com_relogio()
    bus.publicar("smartpark/entrada/presenca", "1")
    outra = next(v.id for v in ctl.lay.vagas if v.id != ctl.painel.vaga)
    bus.publicar(f"smartpark/vagas/{outra}", "OCUPADA")
    [p] = banco.permanencias(agora=rel.t)
    assert p["vaga"] == outra and p["placa"] is None and p["origem"] == "desconhecida"


def test_mensagem_repetida_nao_duplica_e_em_andamento_conta_ate_agora():
    ctl, bus, banco, rel = _ctl_com_relogio()
    bus.publicar("smartpark/vagas/B01", "OCUPADA")
    bus.publicar("smartpark/vagas/B01", "OCUPADA")  # MQTT retido reenviado na reconexão
    rel.t += 600
    perms = banco.permanencias(agora=rel.t)
    assert len(perms) == 1 and perms[0]["em_andamento"] and perms[0]["duracao_s"] == pytest.approx(600)


def test_busca_por_placa_e_por_vaga():
    banco = Banco()
    banco.abrir_permanencia("A01", 100, "AAA1A11", "MEMBRO")
    banco.fechar_permanencia("A01", 200)
    banco.abrir_permanencia("B02", 150, "BBB2B22", "MEMBRO")
    assert [p["vaga"] for p in banco.permanencias(placa="aaa1a11", agora=300)] == ["A01"]
    assert [p["placa"] for p in banco.permanencias(vaga="b02", agora=300)] == ["BBB2B22"]


def test_lgpd_anonimiza_e_remove_placa_das_permanencias():
    banco = Banco(retencao_dias=30)
    banco.abrir_permanencia("A01", 0, "AAA1A11", "MEMBRO")
    banco.fechar_permanencia("A01", 3600)
    banco.abrir_permanencia("A02", 40 * 86400, "BBB2B22", "MEMBRO")
    banco.anonimizar_antigos(agora=40 * 86400)
    perms = banco.permanencias(agora=41 * 86400)
    assert perms[0]["placa"] is None and perms[0]["duracao_s"] == 3600   # o tempo continua
    assert perms[1]["placa"] == "BBB2B22"
    banco.remover("BBB2B22")
    assert banco.permanencias(agora=41 * 86400)[1]["placa"] is None


def test_resumo_ocupacao_e_lotacao():
    from smartpark.relatorio import resumo
    lay = layout_maquete()
    banco = Banco()
    for i, v in enumerate(lay.vagas):
        banco.abrir_permanencia(v.id, 100 + i * 10, f"AAA1A{i:02d}", "MEMBRO")
    banco.fechar_permanencia("A01", 1000)
    r = resumo(banco.permanencias(agora=2000), lay, 2000)
    assert r["ocupacao_maxima"] == 6 and r["lotou_em"] == 150
    assert r["em_andamento"] == 5 and r["por_zona"]["B"]["lotou_em"] == 150


def _ctl_visitante(placa="XYZ9A99"):
    lay = layout_maquete()
    banco, bus, rel = Banco(), BarramentoMemoria(), Relogio(dt.datetime(2026, 10, 11, 9, 50).timestamp())

    class LPRFixo:
        def ler(self, *_):
            return LPRSimulado(0, 0).ler(placa)

    return Controlador(lay, banco, bus, LPRFixo(), estrategia="reativa", relogio=rel), bus, banco, rel, lay


def test_visitante_entra_e_placa_fica_so_ate_o_fim_do_dia():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    ctl._ao_detectar_veiculo("", "1")
    p = ctl.painel
    assert p.categoria == "VISITANTE" and p.visitante and p.entradas_hoje == 1
    assert ("smartpark/cancela/cmd", "ABRIR") in bus.historico          # visitante entra normalmente
    assert lay.vaga(p.vaga).tipo == "comum"
    bus.publicar(f"smartpark/vagas/{p.vaga}", "OCUPADA")
    [perm] = banco.permanencias(agora=rel.t)
    assert perm["placa"] == "XYZ9A99" and perm["categoria"] == "VISITANTE"   # guardada hoje
    assert [v["placa"] for v in ctl.visitantes_hoje()] == ["XYZ9A99"]
    rel.t += 86400                                                      # dia seguinte
    assert ctl.visitantes_hoje() == []
    assert banco.permanencias(agora=rel.t)[0]["placa"] is None
    assert banco.con.execute("SELECT COUNT(*) FROM eventos WHERE placa='XYZ9A99'").fetchone()[0] == 0


def test_visitante_pcd_troca_no_tablet_e_e_lembrado_no_mesmo_dia():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    ctl._ao_detectar_veiculo("", "1")
    comum = ctl.painel.vaga
    r = ctl.trocar_para_preferencial("PCD", origem="guarita")
    assert r["ok"] and lay.vaga(ctl.painel.vaga).tipo == "pcd" and ctl.painel.necessidade == "PCD"
    assert comum not in ctl.reservas and ctl.painel.vaga in ctl.reservas        # devolveu a vaga comum
    bus.publicar(f"smartpark/vagas/{ctl.painel.vaga}", "OCUPADA")
    bus.publicar(f"smartpark/vagas/{ctl.painel.vaga}", "LIVRE")                # foi embora depois do culto
    rel.t += 8 * 3600                                                          # volta à noite
    ctl._ao_detectar_veiculo("", "1")
    assert ctl.painel.entradas_hoje == 2 and ctl.painel.necessidade == "PCD"
    assert lay.vaga(ctl.painel.vaga).tipo == "pcd" and ctl.painel.msg == "Bem-vindo de volta!"


def test_troca_no_tablet_tem_limites():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    ctl._ao_detectar_veiculo("", "1")
    rel.t += 120
    assert not ctl.trocar_para_preferencial("IDOSO", origem="guarita")["ok"]   # passou de 60 s
    assert ctl.trocar_para_preferencial("IDOSO", origem="equipe")["ok"]        # a equipe ainda pode
    bus.publicar(f"smartpark/vagas/{ctl.painel.vaga}", "OCUPADA")
    assert not ctl.trocar_para_preferencial("PCD", origem="equipe")["ok"]      # já estacionou
    ctl2, *_ = _ctl_com_relogio(categoria="MEMBRO")
    ctl2._ao_detectar_veiculo("", "1")
    assert not ctl2.trocar_para_preferencial("IDOSO", origem="guarita")["ok"]  # membro: só pela equipe
    assert ctl2.trocar_para_preferencial("IDOSO", origem="equipe")["ok"]


# ------------------------------------------------------------ área admin
def test_autenticacao_senha_hash_e_bloqueio(tmp_path):
    from smartpark.admin import Autenticacao
    a = Autenticacao(tmp_path / "senha.txt")
    assert a.senha_gerada and len(a.senha_gerada) == 6
    assert a.senha_gerada not in (tmp_path / "senha.txt").read_text()   # guarda só o hash
    tok = a.entrar(a.senha_gerada)
    assert a.valido(tok) and not a.valido("qualquer")
    for _ in range(5):
        assert a.entrar("errada") is None
    assert a.bloqueado() and a.entrar(a.senha_gerada) is None          # bloqueia após 5 erros
    a.sair(tok)
    assert not a.valido(tok)


def test_visao_geral_agrupa_por_culto():
    import datetime as dt
    from smartpark.admin import visao_geral
    lay = layout_maquete()
    banco = Banco()
    inicio = dt.datetime(2026, 10, 4, 17, 0).timestamp()      # domingo 17h
    for i, v in enumerate(lay.vagas):
        banco.abrir_permanencia(v.id, inicio + (i - 8) * 60, f"AAA1A{i:02d}", "MEMBRO")
        banco.fechar_permanencia(v.id, inicio + 110 * 60)
    banco.abrir_permanencia("A01", inicio + 5 * 3600, None, None)  # fora de horário de culto
    agora = inicio + 6 * 3600
    v = visao_geral(banco.permanencias(agora=agora), lay, agora, 30)
    assert v["kpis"]["cultos"] == 1 and v["kpis"]["permanencias_fora_de_culto"] == 1
    [c] = v["cultos"]
    assert c["culto"] == "Domingo 17h" and c["carros"] == 6 and c["ocupacao_max_pct"] == 100
    assert c["lotou_min"] == pytest.approx(-3)
    assert set(v["uso_vagas_pct"]) == {x.id for x in lay.vagas}


# ------------------------------------------------------------ aviso de lotação
class PreditorFixo:
    """Preditor de mentira para o teste: 2 chegadas por minuto, sempre."""
    def __init__(self, por_min=2.0):
        self.perfil_medio = {(0, m): por_min * 5 for m in range(-90, 60)}
        self.por_min = por_min

    def prever(self, *a):
        return self.por_min * 5


def test_previsao_de_lotacao_basica():
    from smartpark.lotacao import prever_lotacao
    chegadas = [(-50 + i * 0.5) for i in range(80)]            # ritmo igual ao perfil (2/min)
    p = prever_lotacao(PreditorFixo(), -10, chegadas, 0, 0.5, livres=20)
    assert p["minutos"] == pytest.approx(10, abs=0.6) and p["nivel"] == "atencao"
    assert prever_lotacao(PreditorFixo(), -10, chegadas, 0, 0.5, livres=6)["nivel"] == "critico"
    assert prever_lotacao(PreditorFixo(), -10, chegadas, 0, 0.5, livres=200)["nivel"] == "ok"
    assert prever_lotacao(PreditorFixo(), -10, chegadas, 0, 1.0, livres=0)["nivel"] == "lotado"
    assert prever_lotacao(PreditorFixo(), -200, chegadas, 0, 0.5, livres=5)["nivel"] == "ok"   # longe do culto


def test_culto_mais_cheio_antecipa_a_lotacao():
    from smartpark.lotacao import prever_lotacao
    normal = [(-50 + i * 0.5) for i in range(80)]               # 2/min, como o perfil
    cheio = [(-50 + i * 0.3) for i in range(134)]               # ~3,3/min
    t_normal = prever_lotacao(PreditorFixo(), -10, normal, 0, 0.5, livres=40)["minutos"]
    t_cheio = prever_lotacao(PreditorFixo(), -10, cheio, 0, 0.5, livres=40)["minutos"]
    assert t_cheio < t_normal


def test_controlador_avisa_uma_vez_por_nivel_e_registra_lotacao():
    import datetime as dt
    lay = layout_maquete()
    banco = Banco()
    bus = BarramentoMemoria()
    inicio = dt.datetime(2026, 10, 4, 17, 0).timestamp()        # domingo 17h
    rel = Relogio(inicio - 8 * 60)
    avisos = []
    ctl = Controlador(lay, banco, bus, LPRSimulado(0, 0, seed=1), preditor=PreditorFixo(0.5),
                      estrategia="reativa", relogio=rel)
    ctl.escala = 1.0                                            # preditor de teste já está na escala da maquete
    ctl.notificadores.append(lambda txt, info: avisos.append(info["nivel"]))
    for v in lay.vagas[:4]:
        bus.publicar(f"smartpark/vagas/{v.id}", "OCUPADA")        # sobram 2 vagas, 0,5 carro/min => ~4 min
    assert ctl.painel.alerta["nivel"] == "critico" and avisos == ["critico"]
    ctl.verificar(); ctl.verificar()
    assert avisos == ["critico"]                                # não repete
    assert ("smartpark/alertas/lotacao" in [t for t, _ in bus.historico])
    for v in lay.vagas[4:]:
        bus.publicar(f"smartpark/vagas/{v.id}", "OCUPADA")
    assert ctl.painel.alerta["nivel"] == "lotado" and avisos == ["critico", "lotado"]
    assert banco.con.execute("SELECT COUNT(*) FROM eventos WHERE tipo='LOTOU'").fetchone()[0] == 1


def test_avisos_por_culto_mede_antecedencia():
    import json as js
    from smartpark.admin import avisos_por_culto
    t0 = 1_791_000_000.0
    evs = [
        {"tipo": "ALERTA_LOTACAO", "instante": t0 - 600, "detalhe": js.dumps({"nivel": "atencao", "minutos": 9, "culto_inicio": t0})},
        {"tipo": "LOTOU", "instante": t0 - 60, "detalhe": js.dumps({"culto_inicio": t0})},
        {"tipo": "ALERTA_LOTACAO", "instante": t0 + 86400 - 600, "detalhe": js.dumps({"nivel": "atencao", "minutos": 9, "culto_inicio": t0 + 86400})},
    ]
    r = avisos_por_culto(evs, agora=t0 + 3 * 86400)
    assert r["resumo"]["avisados_a_tempo"] == 1 and r["resumo"]["alarmes_falsos"] == 1
    assert r["resumo"]["antecedencia_media_min"] == pytest.approx(9)


# ------------------------------------------------------------ saúde dos sensores
def test_saude_detecta_sensor_preso_oscilando_sem_uso_e_curtas():
    from smartpark.saude import diagnosticar
    lay = layout_maquete()
    banco = Banco()
    agora = 2_000_000_000.0
    ids = [v.id for v in lay.vagas]
    # uso normal em A01, A02, B01: 6 ocupações cada nos últimos dias
    for vid in (ids[0], ids[1], ids[3]):
        for d in range(6):
            banco.abrir_permanencia(vid, agora - (d + 1) * 86400, "AAA1A11", "MEMBRO")
            banco.fechar_permanencia(vid, agora - (d + 1) * 86400 + 5400)
    banco.abrir_permanencia(ids[2], agora - 9 * 3600, None, None)            # A03 presa há 9 h
    for i in range(8):                                                       # B02 oscilando
        banco.registrar("VAGA_OCUPADA" if i % 2 == 0 else "VAGA_LIVRE", vaga=ids[4], instante=agora - 3600 + i * 30)
    for d in range(3):                                                       # B03 só leituras curtas
        banco.abrir_permanencia(ids[5], agora - (d + 2) * 86400, None, None)
        banco.fechar_permanencia(ids[5], agora - (d + 2) * 86400 + 10)
    r = diagnosticar(lay, banco, agora)
    prob = {v["vaga"]: {p["codigo"] for p in v["problemas"]} for v in r["vagas"]}
    estado = {v["vaga"]: v["estado"] for v in r["vagas"]}
    assert prob[ids[2]] == {"PRESO_OCUPADO"} and estado[ids[2]] == "falha"
    assert "OSCILANDO" in prob[ids[4]] and "SEM_USO" in prob[ids[4]]
    assert prob[ids[5]] == {"LEITURAS_CURTAS"}
    assert prob[ids[0]] == set() and estado[ids[0]] == "ok"


def test_status_do_esp32_vem_do_mqtt():
    lay = layout_maquete()
    bus = BarramentoMemoria()
    ctl = Controlador(lay, Banco(), bus, LPRSimulado(0, 0), estrategia="reativa")
    bus.publicar("smartpark/esp32/status", "offline")
    assert ctl.esp32["estado"] == "offline"


def test_escala_da_maquete_reduz_a_demanda_prevista():
    from smartpark.lotacao import prever_lotacao
    cheg = [(-50 + i * 4) for i in range(10)]
    igreja = prever_lotacao(PreditorFixo(), -10, cheg, 0, 0.5, livres=4)["minutos"]
    maquete = prever_lotacao(PreditorFixo(), -10, cheg, 0, 0.5, livres=4, escala=0.125)["minutos"]
    assert maquete > 4 * igreja


# ------------------------------------------------------------ planta de 250 vagas
def test_planta_tem_250_vagas_e_preferenciais_da_lei():
    from collections import Counter
    from smartpark.layout import layout_planta
    lay = layout_planta()
    tipos = Counter(v.tipo for v in lay.vagas)
    assert len(lay.vagas) == 250 and len({v.id for v in lay.vagas}) == 250
    assert tipos["idoso"] >= round(0.05 * 250) and tipos["pcd"] >= round(0.02 * 250)   # 13 e 5


def test_planta_todas_as_vagas_alcancaveis_e_sem_sobreposicao():
    import itertools, math
    from smartpark.layout import layout_planta
    from smartpark.roteamento import rota_ate_vaga
    lay = layout_planta()
    for v in lay.vagas:
        c, arestas, _ = rota_ate_vaga(lay, v, lambda a, b: lay.aresta(a, b).comprimento, lambda a, b, o: o)
        assert c < math.inf and arestas[0][0] == lay.entrada
    for a, b in itertools.combinations(lay.vagas, 2):                 # centros a pelo menos 2,5 m
        assert math.dist((a.x, a.y), (b.x, b.y)) >= 2.49, (a.id, b.id)


def test_planta_categoria_vai_para_a_vaga_certa_e_instrucao_tem_lado():
    from smartpark.layout import layout_planta
    lay = layout_planta()
    todas = {v.id for v in lay.vagas}
    for cat, tipo in (("IDOSO", "idoso"), ("PCD", "pcd")):
        d = Alocador(lay, "reativa").decidir(cat, EstadoPatio(0, todas))
        assert lay.vaga(d.vaga).tipo == tipo
    d = Alocador(lay, "reativa").decidir("EQUIPE", EstadoPatio(0, todas))
    assert lay.vaga(d.vaga).zona in "HI"                              # equipe deixa as vagas da frente
    assert d.instrucoes[-1].startswith(f"Vaga {d.vaga} à ") and d.pontos[0] == [lay.nos["E0"].x, lay.nos["E0"].y]


def test_simulacao_roda_na_planta():
    from smartpark.layout import layout_planta
    from simulador.chegadas import PerfilCulto
    lay = layout_planta()
    ch = gerar_chegadas(PerfilCulto("teste", 120, -10, 6, .1, CULTOS[1].mix), random.Random(3))
    m = Simulacao(lay, ch, "reativa", 1, seed=0).rodar(t_max_s=40 * 60)
    assert m["estacionados"] == len(ch)


def test_planta_idoso_e_pcd_ficam_perto_da_porta():
    # com o pátio vazio, a vaga PcD/idoso da frente da igreja ganha da que está a 44 m
    from smartpark.layout import layout_planta
    lay = layout_planta()
    aloc = Alocador(lay, "preditiva")
    livres = {v.id for v in lay.vagas}
    for cat in ("PCD", "IDOSO"):
        v = lay.vaga(aloc.decidir(cat, EstadoPatio(0, livres, [], 0.0)).vaga)
        assert lay.distancia_caminhada(v) < 10


# ------------------------------------------------------------ corredor e histórico de visitantes
def test_corredor_lista_carro_mandado_para_ele_e_acompanha_o_estado():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    ctl._ao_detectar_veiculo("", "1")
    vaga = ctl.painel.vaga
    setor = lay.vaga(vaga).zona
    [c] = ctl.corredor(setor)["carros"]
    assert c["placa"] == "XYZ9A99" and c["vaga"] == vaga and c["estado"] == "a_caminho"
    outro = next(z for z in ctl.corredor(setor)["setores"] if z != setor)
    assert ctl.corredor(outro)["carros"] == []                      # só aparece no corredor dele
    bus.publicar(f"smartpark/vagas/{vaga}", "OCUPADA")
    assert ctl.corredor(setor)["carros"][0]["estado"] == "estacionou"
    livre = next(v.id for v in lay.vagas if v.zona == outro and v.tipo == "comum")
    bus.publicar(f"smartpark/vagas/{livre}", "OCUPADA")               # carro sem indicação
    assert ctl.corredor(outro)["carros"][0]["estado"] == "sem_indicacao"


def test_terceira_visita_avisa_o_corredor_e_oferta_fica_registrada():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    for dia in range(3):
        ctl._ao_detectar_veiculo("", "1")
        if dia < 2:
            assert ctl.avisos_cadastro == []
            ctl._ao_detectar_veiculo("", "1")                       # voltar no mesmo dia não conta visita
        rel.t += 86400 if dia < 2 else 0
    assert ctl.painel.visitas == 3
    setor = lay.vaga(ctl.painel.vaga).zona
    [aviso] = ctl.corredor(setor)["avisos"]
    assert aviso["placa"] == "XYZ9A99" and aviso["visitas"] == 3
    assert ctl.corredor(setor)["carros"][0]["oferecer_cadastro"]
    assert ctl.registrar_oferta(aviso["id"], "recusou")["ok"]
    assert ctl.corredor(setor)["avisos"] == []
    rel.t += 86400
    ctl._ao_detectar_veiculo("", "1")                               # 4ª visita: já ofereceram, não avisa de novo
    assert all(a["resolvido"] for a in ctl.avisos_cadastro)


def test_historico_de_visitante_e_pseudonimo_e_some_ao_cadastrar():
    ctl, bus, banco, rel, lay = _ctl_visitante()
    ctl._ao_detectar_veiculo("", "1")
    rel.t += 86400
    ctl._ao_detectar_veiculo("", "1")
    dia = ctl._dia(rel.t)
    [h] = banco.historico_visitantes(dia)
    assert h["visitas"] == 2 and h["placa"] == "XYZ9A99" and h["veio_hoje"]
    assert "XYZ9A99" not in str(banco.con.execute("SELECT * FROM visitantes_hist").fetchall())   # sem a placa
    rel.t += 86400
    ctl.visitantes_hoje()                                           # virada do dia
    [h] = banco.historico_visitantes(ctl._dia(rel.t))
    assert h["placa"] is None and h["visitas"] == 2                  # placa some, contagem fica
    banco.cadastrar("XYZ9A99", "MEMBRO")
    assert banco.historico_visitantes(ctl._dia(rel.t)) == []


def test_historico_de_visitante_expira_em_6_meses():
    banco = Banco()
    banco.registrar_visita("ABC1D23", "2026-01-10")
    assert banco.limpar_historico_visitantes("2026-05-01") == 0
    assert banco.limpar_historico_visitantes("2026-07-20") == 1


def test_migra_banco_antigo_com_categoria_geral(tmp_path):
    # Banco criado antes da troca de GERAL para MEMBRO: o cadastro e o histórico precisam ser convertidos.
    import sqlite3
    arq = tmp_path / "antigo.db"
    con = sqlite3.connect(arq)
    con.executescript("""
        CREATE TABLE veiculos (placa TEXT PRIMARY KEY, apelido TEXT,
            categoria TEXT NOT NULL CHECK (categoria IN ('GERAL','IDOSO','PCD','EQUIPE')), consentimento_em REAL NOT NULL);
        INSERT INTO veiculos VALUES ('ABC1D23', 'Carlos', 'GERAL', 1.0);
        INSERT INTO veiculos VALUES ('XYZ9A99', NULL, 'IDOSO', 1.0);
        CREATE TABLE eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, instante REAL NOT NULL, tipo TEXT NOT NULL,
            placa TEXT, categoria TEXT, vaga TEXT, detalhe TEXT);
        INSERT INTO eventos (instante, tipo, placa, categoria) VALUES (1.0, 'ENTRADA', 'ABC1D23', 'GERAL');
    """)
    con.commit(); con.close()
    b = Banco(arq)
    assert b.categoria_de("ABC1D23")[0] == "MEMBRO"
    assert b.categoria_de("XYZ9A99")[0] == "IDOSO"
    assert b.con.execute("SELECT categoria FROM eventos").fetchone()[0] == "MEMBRO"
    b.cadastrar("NEW1A11", "MEMBRO")          # a regra nova aceita MEMBRO


def test_ordem_de_proximidade_por_categoria():
    # Com o pátio vazio: PcD, idoso e visitante ficam no setor da frente (A), membro no seguinte (B)
    # e equipe/voluntários no setor mais distante (C).
    lay = layout_igreja()
    livres = {v.id for v in lay.vagas}
    al = Alocador(lay, "preditiva")
    setor = {c: lay.vaga(al.decidir(c, EstadoPatio(0, livres, previsao_5min=2)).vaga).zona
             for c in ("PCD", "IDOSO", "VISITANTE", "MEMBRO", "EQUIPE")}
    assert setor == {"PCD": "A", "IDOSO": "A", "VISITANTE": "A", "MEMBRO": "B", "EQUIPE": "C"}


def test_membro_usa_vaga_da_frente_quando_so_ela_sobra():
    # A prioridade do visitante é suave: se só restar vaga no setor A, o membro recebe essa vaga.
    lay = layout_igreja()
    so_a = {v.id for v in lay.vagas if v.zona == "A" and v.tipo == "comum"}
    dec = Alocador(lay, "preditiva").decidir("MEMBRO", EstadoPatio(0, so_a))
    assert dec.vaga in so_a


def test_lotacao_considera_so_vagas_comuns():
    # Com todas as vagas comuns ocupadas, o pátio está lotado para a maioria dos motoristas,
    # mesmo que a vaga de PcD continue livre.
    import datetime as dt
    lay = layout_maquete()
    banco = Banco()
    bus = BarramentoMemoria()
    inicio = dt.datetime(2026, 10, 4, 17, 0).timestamp()
    ctl = Controlador(lay, banco, bus, LPRSimulado(0, 0, seed=1), preditor=PreditorFixo(0.5),
                      estrategia="reativa", relogio=Relogio(inicio - 8 * 60))
    ctl.escala = 1.0
    for v in lay.vagas:
        if v.tipo == "comum":
            bus.publicar(f"smartpark/vagas/{v.id}", "OCUPADA")
    assert any(v.tipo != "comum" for v in lay.vagas)
    assert ctl.painel.alerta["nivel"] == "lotado"


def test_leitura_de_placa_por_foto():
    # Usa as placas de teste geradas para imprimir. Pulo o teste se o OCR (tesseract) não estiver instalado.
    pytest.importorskip("cv2")
    pytest.importorskip("pytesseract")
    from pathlib import Path
    from smartpark.lpr import LeitorImagem
    try:
        leitor = LeitorImagem()
    except Exception:
        pytest.skip("tesseract não instalado")
    pasta = Path(__file__).resolve().parents[2] / "docs" / "placas_teste"
    for placa in ("UDA4H28", "TCC2A26"):
        assert leitor.ler_arquivo(pasta / f"placa_{placa}.png").placa == placa


def test_leitor_nao_inventa_placa_em_texto_qualquer():
    pytest.importorskip("cv2")
    pytest.importorskip("pytesseract")
    from smartpark.lpr import LeitorImagem
    assert LeitorImagem._procurar("AMOSTRA PARA TESTE SMART PARK", estrito=True) is None
    assert LeitorImagem._procurar("LNBA1G29") == "NBA1G29"        # borda lida como letra
    assert LeitorImagem._procurar("TCC2ZA26") == "TCC2A26"        # caractere fantasma no meio
