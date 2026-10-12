"""
Banco de dados (SQLite): veículos cadastrados, eventos e permanências nas vagas.

Segui o princípio da minimização (LGPD, art. 6º, III): guardo só o necessário
para indicar a vaga — placa, apelido opcional e categoria de atendimento.
Não guardo nenhuma imagem. A placa sai do registro de eventos e das
permanências depois do prazo de retenção (30 dias por padrão); a partir daí
ficam só vaga, horários e categoria, que é o que preciso para a estatística de ocupação.

Chamo de permanência cada período em que uma vaga ficou ocupada.
    entrada  : instante em que o sensor da vaga detectou o carro
    saida    : instante em que a vaga voltou a ficar livre (NULL = ainda ocupada)
    placa    : placa do carro para quem o sistema reservou a vaga
               (cadastrados: até 30 dias; visitantes: só até o fim do dia)
    origem   : 'atribuida'    -> a vaga estava reservada para esta placa
               'desconhecida' -> o carro parou numa vaga que não era a dele
                                 (ou entrou sem passar pela guarita)
O sensor da vaga não lê a placa: quem diz de quem é o carro é a reserva feita na guarita.
Por isso criei o campo 'origem', que deixa claro o grau de certeza de cada registro.

Visitantes do dia: a placa de quem não é cadastrado fica guardada só no dia
da visita, para (1) eu reconhecer o carro se ele voltar no mesmo dia (culto da
manhã e da noite) já com a necessidade que declarou (idoso/PcD) e (2) a
recepção saber quantos visitantes vieram. Na virada do dia eu esvazio a tabela
e tiro a placa do visitante de eventos e permanências
(finalidade e necessidade, LGPD art. 6º, I e III).

Histórico de visitas (para oferecer o cadastro na 3ª visita): aqui eu guardo só
um código pseudônimo da placa (HMAC-SHA256 com uma chave aleatória que fica num
arquivo separado do banco, LGPD art. 13, §4º) e os dias das visitas, por 6 meses.
Sem a chave não dá para voltar à placa, e a placa em si continua sendo apagada todo
dia. Quando o visitante aceita o cadastro, guardo a placa só até a secretaria
concluir o cadastro com o termo assinado. Quando ele se cadastra, apago o histórico
de visitante dele.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path

CATEGORIAS = ("MEMBRO", "IDOSO", "PCD", "EQUIPE", "VISITANTE")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS veiculos (
    placa       TEXT PRIMARY KEY,
    apelido     TEXT,
    categoria   TEXT NOT NULL CHECK (categoria IN ('MEMBRO','IDOSO','PCD','EQUIPE')),
    consentimento_em REAL NOT NULL           -- data/hora do aceite do termo
);
CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    instante    REAL NOT NULL,
    tipo        TEXT NOT NULL,               -- ENTRADA, VAGA_ATRIBUIDA, LOTADO, VAGA_OCUPADA, VAGA_LIVRE
    placa       TEXT,
    categoria   TEXT,
    vaga        TEXT,
    detalhe     TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_instante ON eventos(instante);
CREATE TABLE IF NOT EXISTS permanencias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vaga        TEXT NOT NULL,
    placa       TEXT,
    categoria   TEXT,
    origem      TEXT NOT NULL CHECK (origem IN ('atribuida','desconhecida')),
    entrada     REAL NOT NULL,
    saida       REAL
);
CREATE INDEX IF NOT EXISTS idx_perm_entrada ON permanencias(entrada);
CREATE INDEX IF NOT EXISTS idx_perm_placa ON permanencias(placa);
CREATE INDEX IF NOT EXISTS idx_perm_aberta ON permanencias(vaga, saida);
CREATE TABLE IF NOT EXISTS visitantes_dia (
    placa       TEXT PRIMARY KEY,
    dia         TEXT NOT NULL,               -- AAAA-MM-DD (horário local)
    necessidade TEXT CHECK (necessidade IN ('IDOSO','PCD')),   -- declarada na guarita (NULL = nenhuma)
    primeira_vez REAL NOT NULL,
    ultima_vez  REAL NOT NULL,
    entradas    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS visitantes_hist (
    id          TEXT PRIMARY KEY,            -- código pseudônimo (HMAC da placa), nunca a placa
    visitas     INTEGER NOT NULL DEFAULT 0,  -- dias diferentes em que veio
    primeira_dia TEXT,
    ultima_dia  TEXT,
    necessidade TEXT,
    oferta      TEXT CHECK (oferta IN ('aceitou','recusou')),
    oferta_em   REAL,
    placa_pendente TEXT                      -- só quando aceitou o cadastro, até ele ser feito
);
CREATE TABLE IF NOT EXISTS visitas_dias (
    id          TEXT NOT NULL,
    dia         TEXT NOT NULL,
    entradas    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (id, dia)
);
"""

NECESSIDADES = ("IDOSO", "PCD")
RETENCAO_VISITANTES_DIAS = 180   # histórico pseudônimo de visitas: 6 meses


class Banco:
    def __init__(self, caminho: str | Path = ":memory:", retencao_dias: int = 30, chave: bytes | None = None):
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._migrar_categoria_geral()
        self.con.executescript(ESQUEMA)
        self.retencao_s = retencao_dias * 86400
        self._chave = chave or self._carregar_chave(caminho)

    def _migrar_categoria_geral(self):
        """Bancos criados antes de eu renomear a categoria GERAL para MEMBRO: refaço a tabela de
        cadastro com a regra nova e troco GERAL por MEMBRO também no histórico."""
        sql = self.con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='veiculos'").fetchone()
        if not sql or "'GERAL'" not in sql[0]:
            return
        with self.con:
            self.con.execute("ALTER TABLE veiculos RENAME TO veiculos_antigo")
            self.con.executescript(ESQUEMA)
            self.con.execute("INSERT INTO veiculos SELECT placa, apelido, "
                             "CASE categoria WHEN 'GERAL' THEN 'MEMBRO' ELSE categoria END, consentimento_em FROM veiculos_antigo")
            self.con.execute("DROP TABLE veiculos_antigo")
            for tabela in ("eventos", "permanencias"):
                self.con.execute(f"UPDATE {tabela} SET categoria='MEMBRO' WHERE categoria='GERAL'")

    @staticmethod
    def _carregar_chave(caminho) -> bytes:
        """Chave do código pseudônimo dos visitantes: deixo num arquivo próprio, fora do banco."""
        if str(caminho) == ":memory:":
            return secrets.token_bytes(32)
        arq = Path(caminho).with_name("chave_visitantes.bin")
        if not arq.exists():
            arq.write_bytes(secrets.token_bytes(32))
            try:
                arq.chmod(0o600)
            except OSError:
                pass
        return arq.read_bytes()

    def id_visitante(self, placa: str) -> str:
        return hmac.new(self._chave, placa.upper().encode(), hashlib.sha256).hexdigest()[:16]

    # ------------------------------------------------------------ cadastro
    def cadastrar(self, placa: str, categoria: str, apelido: str | None = None):
        if categoria not in CATEGORIAS or categoria == "VISITANTE":
            raise ValueError(f"Categoria inválida para cadastro: {categoria}")
        self.con.execute(
            "INSERT OR REPLACE INTO veiculos VALUES (?,?,?,?)",
            (placa.upper(), apelido, categoria, time.time()),
        )
        self._apagar_historico_visitante(placa)        # virou membro: não é mais visitante
        self.con.commit()

    def _apagar_historico_visitante(self, placa: str):
        vid = self.id_visitante(placa)
        self.con.execute("DELETE FROM visitantes_hist WHERE id=?", (vid,))
        self.con.execute("DELETE FROM visitas_dias WHERE id=?", (vid,))

    def remover(self, placa: str):
        """Direito de eliminação do titular (LGPD, art. 18, VI)."""
        p = placa.upper()
        self.con.execute("DELETE FROM veiculos WHERE placa=?", (p,))
        self.con.execute("UPDATE eventos SET placa=NULL WHERE placa=?", (p,))
        self.con.execute("UPDATE permanencias SET placa=NULL WHERE placa=?", (p,))
        self.con.execute("DELETE FROM visitantes_dia WHERE placa=?", (p,))
        self._apagar_historico_visitante(p)
        self.con.commit()

    def categoria_de(self, placa: str | None) -> tuple[str, str | None]:
        """Devolvo (categoria, apelido). Placa desconhecida ou ilegível vira VISITANTE."""
        if not placa:
            return "VISITANTE", None
        row = self.con.execute(
            "SELECT categoria, apelido FROM veiculos WHERE placa=?", (placa.upper(),)
        ).fetchone()
        return (row[0], row[1]) if row else ("VISITANTE", None)

    # ------------------------------------------------------------ eventos
    def registrar(self, tipo: str, placa=None, categoria=None, vaga=None, detalhe=None, instante=None):
        self.con.execute(
            "INSERT INTO eventos (instante,tipo,placa,categoria,vaga,detalhe) VALUES (?,?,?,?,?,?)",
            (instante if instante is not None else time.time(), tipo, placa, categoria, vaga, detalhe),
        )
        self.con.commit()

    def anonimizar_antigos(self, agora: float | None = None) -> int:
        """Tiro a placa de eventos e permanências mais antigos que o prazo de retenção."""
        limite = (agora or time.time()) - self.retencao_s
        n = self.con.execute("UPDATE eventos SET placa=NULL WHERE instante < ? AND placa IS NOT NULL", (limite,)).rowcount
        n += self.con.execute("UPDATE permanencias SET placa=NULL WHERE entrada < ? AND placa IS NOT NULL", (limite,)).rowcount
        self.con.commit()
        return n

    def chegadas_por_minuto(self, desde: float) -> list[float]:
        """Instantes de entrada a partir de 'desde' (é isso que alimenta o preditor)."""
        rows = self.con.execute(
            "SELECT instante FROM eventos WHERE tipo='ENTRADA' AND instante >= ? ORDER BY instante", (desde,)
        ).fetchall()
        return [r[0] for r in rows]

    # --------------------------------------------------- visitantes do dia
    def registrar_visitante(self, placa: str, dia: str, agora: float) -> dict:
        """Conto mais uma entrada do visitante hoje e devolvo o registro dele."""
        p = placa.upper()
        self.con.execute(
            """INSERT INTO visitantes_dia (placa, dia, primeira_vez, ultima_vez) VALUES (?,?,?,?)
               ON CONFLICT(placa) DO UPDATE SET
                 entradas = CASE WHEN dia = excluded.dia THEN entradas + 1 ELSE 1 END,
                 necessidade = CASE WHEN dia = excluded.dia THEN necessidade ELSE NULL END,
                 primeira_vez = CASE WHEN dia = excluded.dia THEN primeira_vez ELSE excluded.primeira_vez END,
                 ultima_vez = excluded.ultima_vez, dia = excluded.dia""",
            (p, dia, agora, agora))
        hist = self.registrar_visita(p, dia)
        self.con.commit()
        reg = dict(self.con.execute("SELECT * FROM visitantes_dia WHERE placa=?", (p,)).fetchone())
        return {**reg, "id": hist["id"], "visitas": hist["visitas"], "oferta": hist["oferta"]}

    def registrar_visita(self, placa: str, dia: str) -> dict:
        """Considero uma visita por dia (culto da manhã e da noite no mesmo dia contam como 1)."""
        vid = self.id_visitante(placa)
        novo_dia = self.con.execute("SELECT 1 FROM visitas_dias WHERE id=? AND dia=?", (vid, dia)).fetchone() is None
        if novo_dia:
            self.con.execute("INSERT INTO visitas_dias (id, dia) VALUES (?,?)", (vid, dia))
        else:
            self.con.execute("UPDATE visitas_dias SET entradas = entradas + 1 WHERE id=? AND dia=?", (vid, dia))
        self.con.execute("INSERT OR IGNORE INTO visitantes_hist (id, primeira_dia, ultima_dia) VALUES (?,?,?)", (vid, dia, dia))
        if novo_dia:
            self.con.execute("UPDATE visitantes_hist SET visitas = visitas + 1, ultima_dia = MAX(ultima_dia, ?), primeira_dia = MIN(primeira_dia, ?) WHERE id=?",
                             (dia, dia, vid))
        self.con.commit()
        return dict(self.con.execute("SELECT * FROM visitantes_hist WHERE id=?", (vid,)).fetchone())

    def registrar_oferta(self, placa: str, resultado: str, agora: float):
        """Guardo o resultado da oferta de cadastro feita pelo funcionário do corredor."""
        if resultado not in ("aceitou", "recusou"):
            raise ValueError(resultado)
        self.con.execute("UPDATE visitantes_hist SET oferta=?, oferta_em=?, placa_pendente=? WHERE id=?",
                         (resultado, agora, placa.upper() if resultado == "aceitou" else None, self.id_visitante(placa)))
        self.con.commit()

    def historico_visitantes(self, dia_hoje: str) -> list[dict]:
        """Devolvo um item por visitante (código pseudônimo), com os dias das visitas.
        Só mostro a placa se ele veio hoje ou se aceitou o cadastro e ainda não foi cadastrado."""
        hoje = {self.id_visitante(r["placa"]): r["placa"] for r in self.con.execute("SELECT placa FROM visitantes_dia WHERE dia=?", (dia_hoje,))}
        dias = {}
        for r in self.con.execute("SELECT id, dia, entradas FROM visitas_dias ORDER BY dia"):
            dias.setdefault(r["id"], []).append({"dia": r["dia"], "entradas": r["entradas"]})
        out = []
        for r in self.con.execute("SELECT * FROM visitantes_hist ORDER BY ultima_dia DESC, visitas DESC"):
            d = dict(r)
            d["codigo"] = "V-" + d["id"][:5].upper()
            d["placa"] = hoje.get(d["id"]) or d.pop("placa_pendente", None)
            d.pop("placa_pendente", None)
            d["veio_hoje"] = d["id"] in hoje
            d["dias"] = dias.get(d["id"], [])
            out.append(d)
        return out

    def limpar_historico_visitantes(self, dia_atual: str, retencao_dias: int = RETENCAO_VISITANTES_DIAS) -> int:
        limite = (dt.date.fromisoformat(dia_atual) - dt.timedelta(days=retencao_dias)).isoformat()
        n = self.con.execute("DELETE FROM visitantes_hist WHERE ultima_dia < ?", (limite,)).rowcount
        self.con.execute("DELETE FROM visitas_dias WHERE dia < ? OR id NOT IN (SELECT id FROM visitantes_hist)", (limite,))
        self.con.commit()
        return n

    def declarar_necessidade(self, placa: str, dia: str, necessidade: str | None):
        if necessidade is not None and necessidade not in NECESSIDADES:
            raise ValueError(necessidade)
        self.con.execute("UPDATE visitantes_dia SET necessidade=? WHERE placa=? AND dia=?", (necessidade, placa.upper(), dia))
        self.con.execute("UPDATE visitantes_hist SET necessidade=? WHERE id=?", (necessidade, self.id_visitante(placa)))
        self.con.commit()

    def visitantes_do_dia(self, dia: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM visitantes_dia WHERE dia=? ORDER BY primeira_vez DESC", (dia,))]

    def limpar_visitantes(self, dia_atual: str) -> int:
        """Virada do dia: apago os visitantes dos dias anteriores e tiro a placa deles do histórico.
        Placas que foram cadastradas nesse meio-tempo ficam (agora são de membros)."""
        antigos = "SELECT placa FROM visitantes_dia WHERE dia <> ? AND placa NOT IN (SELECT placa FROM veiculos)"
        n = self.con.execute(f"UPDATE eventos SET placa=NULL WHERE placa IN ({antigos})", (dia_atual,)).rowcount
        n += self.con.execute(f"UPDATE permanencias SET placa=NULL WHERE placa IN ({antigos})", (dia_atual,)).rowcount
        self.con.execute("DELETE FROM visitantes_dia WHERE dia <> ?", (dia_atual,))
        self.con.commit()
        return n

    # -------------------------------------------------------- permanências
    def permanencia_aberta(self, vaga: str):
        return self.con.execute(
            "SELECT * FROM permanencias WHERE vaga=? AND saida IS NULL ORDER BY entrada DESC LIMIT 1", (vaga,)
        ).fetchone()

    def abrir_permanencia(self, vaga: str, instante: float, placa=None, categoria=None,
                          atribuida: bool | None = None) -> int | None:
        """O carro chegou à vaga. Ignoro se já existe uma permanência aberta (mensagem MQTT repetida).
        atribuida=True quando a vaga estava reservada para um carro (mesmo com placa ilegível)."""
        if self.permanencia_aberta(vaga):
            return None
        if atribuida is None:
            atribuida = placa is not None
        origem = "atribuida" if atribuida else "desconhecida"
        cur = self.con.execute(
            "INSERT INTO permanencias (vaga,placa,categoria,origem,entrada) VALUES (?,?,?,?,?)",
            (vaga, placa, categoria, origem, instante),
        )
        self.con.commit()
        return cur.lastrowid

    def fechar_permanencia(self, vaga: str, instante: float) -> float | None:
        """O carro saiu da vaga. Devolvo a duração em segundos (None se não havia nada aberto)."""
        row = self.permanencia_aberta(vaga)
        if not row:
            return None
        self.con.execute("UPDATE permanencias SET saida=? WHERE id=?", (instante, row["id"]))
        self.con.commit()
        return instante - row["entrada"]

    def fechar_todas(self, instante: float) -> int:
        """Fecho permanências que ficaram abertas (ex.: sistema desligado com carros no pátio)."""
        n = self.con.execute("UPDATE permanencias SET saida=? WHERE saida IS NULL", (instante,)).rowcount
        self.con.commit()
        return n

    def veiculos(self, busca: str | None = None) -> list[dict]:
        sql, args = "SELECT placa, categoria, apelido, consentimento_em FROM veiculos", []
        if busca:
            sql += " WHERE placa LIKE ? OR apelido LIKE ?"
            args = [f"%{busca.upper()}%", f"%{busca}%"]
        return [dict(r) for r in self.con.execute(sql + " ORDER BY categoria, placa", args)]

    def eventos(self, limite: int = 200, tipo: str | None = None, desde: float | None = None) -> list[dict]:
        sql, args = "SELECT * FROM eventos WHERE 1=1", []
        if tipo:
            sql += " AND tipo = ?"; args.append(tipo)
        if desde is not None:
            sql += " AND instante >= ?"; args.append(desde)
        sql += " ORDER BY instante DESC LIMIT ?"
        args.append(limite)
        return [dict(r) for r in self.con.execute(sql, args)]

    def permanencias(self, desde: float | None = None, ate: float | None = None,
                     placa: str | None = None, vaga: str | None = None, agora: float | None = None,
                     categoria: str | None = None) -> list[dict]:
        """Listo as permanências com a duração calculada (as que estão abertas contam até 'agora')."""
        sql, args = "SELECT * FROM permanencias WHERE 1=1", []
        if desde is not None:
            sql += " AND entrada >= ?"; args.append(desde)
        if ate is not None:
            sql += " AND entrada < ?"; args.append(ate)
        if placa:
            sql += " AND placa = ?"; args.append(placa.upper())
        if vaga:
            sql += " AND vaga = ?"; args.append(vaga.upper())
        if categoria:
            sql += " AND categoria = ?"; args.append(categoria.upper())
        sql += " ORDER BY entrada"
        agora = agora if agora is not None else time.time()
        out = []
        for r in self.con.execute(sql, args):
            d = dict(r)
            d["em_andamento"] = d["saida"] is None
            d["duracao_s"] = (d["saida"] if d["saida"] is not None else agora) - d["entrada"]
            out.append(d)
        return out
