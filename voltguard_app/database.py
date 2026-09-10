# -*- coding: utf-8 -*-
"""
database.py
-----------
Camada de acesso ao banco de dados (SQLite).

Usa apenas a biblioteca padrão (sqlite3) de propósito: é um projeto
acadêmico e não precisamos de um ORM para isso — fica mais fácil de
explicar/apresentar o funcionamento do banco.

Tabelas:
  leituras      -> histórico de cada leitura (ESP32, simulador ou manual)
  aparelhos     -> cadastro dos equipamentos, referência, potência, horário e relé
  configuracoes -> limites de tensão, tarifa, bandeira, meta diária (1 linha)
  alertas       -> ocorrências de proteção (sub/sobretensão, sobrecorrente...)
  observacoes   -> anotações livres do usuário (ex.: "técnico trocou o transformador")
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import config


def get_connection():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def conectar():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _garantir_coluna(conn, tabela, coluna, definicao):
    """Adiciona uma coluna se ela ainda não existir (migração simples)."""
    colunas = [c["name"] for c in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]
    if coluna not in colunas:
        conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def init_db():
    """Cria as tabelas (se ainda não existirem), migra colunas novas e popula os padrões."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS aparelhos (
                nome TEXT PRIMARY KEY,
                corrente_referencia REAL NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1
            )
        """)
        _garantir_coluna(conn, "aparelhos", "potencia_estimada", "REAL")
        _garantir_coluna(conn, "aparelhos", "horario_inicio", "TEXT")
        _garantir_coluna(conn, "aparelhos", "horario_fim", "TEXT")
        _garantir_coluna(conn, "aparelhos", "tem_rele", "INTEGER NOT NULL DEFAULT 1")
        _garantir_coluna(conn, "aparelhos", "rele_estado", "TEXT NOT NULL DEFAULT 'ligado'")
        _garantir_coluna(conn, "aparelhos", "rele_motivo", "TEXT")
        _garantir_coluna(conn, "aparelhos", "rele_alterado_em", "TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS leituras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dispositivo_id TEXT,
                aparelho TEXT NOT NULL,
                corrente REAL NOT NULL,
                tensao REAL,
                potencia REAL,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        _garantir_coluna(conn, "leituras", "temperatura", "REAL")
        _garantir_coluna(conn, "leituras", "origem", "TEXT NOT NULL DEFAULT 'esp32'")

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_leituras_aparelho_tempo
            ON leituras (aparelho, timestamp)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS configuracoes (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                nome_local TEXT,
                tensao_nominal REAL,
                tensao_minima REAL,
                tensao_maxima REAL,
                tarifa_kwh REAL,
                bandeira TEXT,
                consumo_max_diario_kwh REAL,
                temperatura_maxima REAL,
                protecao_automatica INTEGER,
                religar_automatico INTEGER,
                leituras_para_religar INTEGER,
                atualizado_em TEXT
            )
        """)
        if conn.execute("SELECT COUNT(*) AS n FROM configuracoes").fetchone()["n"] == 0:
            c = config.CONFIG_INICIAL
            conn.execute("""
                INSERT INTO configuracoes (id, nome_local, tensao_nominal, tensao_minima, tensao_maxima,
                    tarifa_kwh, bandeira, consumo_max_diario_kwh, temperatura_maxima,
                    protecao_automatica, religar_automatico, leituras_para_religar, atualizado_em)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c["nome_local"], c["tensao_nominal"], c["tensao_minima"], c["tensao_maxima"],
                  c["tarifa_kwh"], c["bandeira"], c["consumo_max_diario_kwh"], c["temperatura_maxima"],
                  c["protecao_automatica"], c["religar_automatico"], c["leituras_para_religar"],
                  datetime.now().isoformat(timespec="seconds")))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                aparelho TEXT,
                tipo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL,
                acao TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alertas_tempo ON alertas (timestamp)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS observacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                autor TEXT,
                aparelho TEXT,
                texto TEXT NOT NULL
            )
        """)

        # Popula aparelhos padrão apenas se a tabela estiver vazia
        existentes = conn.execute("SELECT COUNT(*) AS n FROM aparelhos").fetchone()["n"]
        if existentes == 0:
            for nome, referencia in config.APARELHOS_REFERENCIA_PADRAO.items():
                conn.execute(
                    "INSERT INTO aparelhos (nome, corrente_referencia, ativo, potencia_estimada) VALUES (?, ?, 1, ?)",
                    (nome, referencia, config.APARELHOS_POTENCIA_PADRAO.get(nome)),
                )


# ---------------------------------------------------------------------------
# Aparelhos
# ---------------------------------------------------------------------------

def listar_aparelhos():
    with conectar() as conn:
        linhas = conn.execute("SELECT * FROM aparelhos ORDER BY nome").fetchall()
        return [dict(linha) for linha in linhas]


def obter_aparelho(nome: str):
    with conectar() as conn:
        linha = conn.execute("SELECT * FROM aparelhos WHERE nome = ?", (nome,)).fetchone()
        return dict(linha) if linha else None


def obter_referencia(aparelho: str):
    with conectar() as conn:
        linha = conn.execute(
            "SELECT corrente_referencia FROM aparelhos WHERE nome = ?", (aparelho,)
        ).fetchone()
        return linha["corrente_referencia"] if linha else None


def upsert_aparelho(nome: str, corrente_referencia: float, potencia_estimada=None,
                    horario_inicio=None, horario_fim=None, tem_rele=None):
    """Cria ou atualiza o cadastro. Campos None não sobrescrevem o valor já gravado."""
    with conectar() as conn:
        conn.execute("""
            INSERT INTO aparelhos (nome, corrente_referencia, ativo, potencia_estimada,
                                   horario_inicio, horario_fim, tem_rele)
            VALUES (?, ?, 1, ?, ?, ?, COALESCE(?, 1))
            ON CONFLICT(nome) DO UPDATE SET
                corrente_referencia = excluded.corrente_referencia,
                potencia_estimada = COALESCE(excluded.potencia_estimada, aparelhos.potencia_estimada),
                horario_inicio = COALESCE(excluded.horario_inicio, aparelhos.horario_inicio),
                horario_fim = COALESCE(excluded.horario_fim, aparelhos.horario_fim),
                tem_rele = COALESCE(?, aparelhos.tem_rele)
        """, (nome, corrente_referencia, potencia_estimada, horario_inicio, horario_fim,
              tem_rele, tem_rele))


def definir_rele(nome: str, estado: str, motivo: str = None):
    """estado: 'ligado' | 'desligado'. Devolve True se o estado mudou."""
    with conectar() as conn:
        atual = conn.execute("SELECT rele_estado FROM aparelhos WHERE nome = ?", (nome,)).fetchone()
        if atual is None:
            return False
        mudou = atual["rele_estado"] != estado
        conn.execute("""
            UPDATE aparelhos SET rele_estado = ?, rele_motivo = ?, rele_alterado_em = ?
            WHERE nome = ?
        """, (estado, motivo, datetime.now().isoformat(timespec="seconds"), nome))
        return mudou


def excluir_aparelho(nome: str) -> bool:
    """Remove o cadastro do aparelho (o histórico de leituras é mantido)."""
    with conectar() as conn:
        cursor = conn.execute("DELETE FROM aparelhos WHERE nome = ?", (nome,))
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Leituras
# ---------------------------------------------------------------------------

def inserir_leitura(dispositivo_id, aparelho, corrente, tensao, potencia, status,
                    timestamp=None, temperatura=None, origem="esp32"):
    timestamp = timestamp or datetime.now().isoformat(timespec="seconds")
    with conectar() as conn:
        conn.execute("""
            INSERT INTO leituras (dispositivo_id, aparelho, corrente, tensao, potencia, status,
                                  timestamp, temperatura, origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (dispositivo_id, aparelho, corrente, tensao, potencia, status, timestamp, temperatura, origem))


def ultimas_leituras(aparelho: str, quantidade: int = 5):
    """As N leituras mais recentes do aparelho, da mais nova para a mais antiga."""
    with conectar() as conn:
        linhas = conn.execute("""
            SELECT * FROM leituras WHERE aparelho = ?
            ORDER BY timestamp DESC, id DESC LIMIT ?
        """, (aparelho, quantidade)).fetchall()
        return [dict(linha) for linha in linhas]


def ultima_leitura(aparelho: str = None):
    with conectar() as conn:
        if aparelho:
            linha = conn.execute("""
                SELECT * FROM leituras WHERE aparelho = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (aparelho,)).fetchone()
        else:
            linha = conn.execute("""
                SELECT * FROM leituras ORDER BY timestamp DESC LIMIT 1
            """).fetchone()
        return dict(linha) if linha else None


def leituras_periodo(aparelho: str, inicio: datetime, fim: datetime):
    with conectar() as conn:
        linhas = conn.execute("""
            SELECT * FROM leituras
            WHERE aparelho = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (aparelho, inicio.isoformat(timespec="seconds"), fim.isoformat(timespec="seconds"))).fetchall()
        return [dict(linha) for linha in linhas]


def leituras_periodo_todos(inicio: datetime, fim: datetime):
    """Igual a leituras_periodo, mas sem filtrar por aparelho (usado na exportação geral em CSV)."""
    with conectar() as conn:
        linhas = conn.execute("""
            SELECT * FROM leituras
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (inicio.isoformat(timespec="seconds"), fim.isoformat(timespec="seconds"))).fetchall()
        return [dict(linha) for linha in linhas]


def leituras_recentes(aparelho: str, minutos: int = 10):
    inicio = datetime.now() - timedelta(minutes=minutos)
    with conectar() as conn:
        linhas = conn.execute("""
            SELECT * FROM leituras
            WHERE aparelho = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (aparelho, inicio.isoformat(timespec="seconds"))).fetchall()
        return [dict(linha) for linha in linhas]


def aparelhos_com_dados():
    """Lista (distinct) de aparelhos que já enviaram alguma leitura."""
    with conectar() as conn:
        linhas = conn.execute("SELECT DISTINCT aparelho FROM leituras ORDER BY aparelho").fetchall()
        return [linha["aparelho"] for linha in linhas]


def listar_ocorrencias(limite: int = 30, aparelho: str = None):
    """
    Histórico de ocorrências: leituras cujo status é ATENCAO ou ANORMAL
    (seção 10 do documento-base: 'Alertas de corrente acima da referência' e
    'Histórico de ocorrências'). Por padrão traz de todos os aparelhos,
    das mais recentes para as mais antigas.
    """
    with conectar() as conn:
        if aparelho:
            linhas = conn.execute("""
                SELECT * FROM leituras
                WHERE status != 'NORMAL' AND aparelho = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (aparelho, limite)).fetchall()
        else:
            linhas = conn.execute("""
                SELECT * FROM leituras
                WHERE status != 'NORMAL'
                ORDER BY timestamp DESC LIMIT ?
            """, (limite,)).fetchall()
        return [dict(linha) for linha in linhas]


# ---------------------------------------------------------------------------
# Configurações do usuário (uma única linha, id = 1)
# ---------------------------------------------------------------------------

CAMPOS_CONFIG = ["nome_local", "tensao_nominal", "tensao_minima", "tensao_maxima", "tarifa_kwh",
                 "bandeira", "consumo_max_diario_kwh", "temperatura_maxima",
                 "protecao_automatica", "religar_automatico", "leituras_para_religar"]


def obter_configuracoes() -> dict:
    with conectar() as conn:
        linha = conn.execute("SELECT * FROM configuracoes WHERE id = 1").fetchone()
        return dict(linha) if linha else dict(config.CONFIG_INICIAL)


def salvar_configuracoes(novos: dict) -> dict:
    """Atualiza só os campos enviados; devolve a configuração completa."""
    atual = obter_configuracoes()
    for campo in CAMPOS_CONFIG:
        if campo in novos and novos[campo] is not None:
            atual[campo] = novos[campo]
    with conectar() as conn:
        conn.execute("""
            UPDATE configuracoes SET nome_local=?, tensao_nominal=?, tensao_minima=?, tensao_maxima=?,
                tarifa_kwh=?, bandeira=?, consumo_max_diario_kwh=?, temperatura_maxima=?,
                protecao_automatica=?, religar_automatico=?, leituras_para_religar=?, atualizado_em=?
            WHERE id = 1
        """, tuple(atual[c] for c in CAMPOS_CONFIG) + (datetime.now().isoformat(timespec="seconds"),))
    return obter_configuracoes()


# ---------------------------------------------------------------------------
# Alertas de proteção
# ---------------------------------------------------------------------------

def inserir_alerta(tipo: str, descricao: str, aparelho: str = None, valor=None, acao: str = None):
    with conectar() as conn:
        conn.execute("""
            INSERT INTO alertas (timestamp, aparelho, tipo, descricao, valor, acao)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(timespec="seconds"), aparelho, tipo, descricao, valor, acao))


def listar_alertas(limite: int = 30, aparelho: str = None, desde: datetime = None):
    with conectar() as conn:
        sql = "SELECT * FROM alertas WHERE 1=1"
        params = []
        if aparelho:
            sql += " AND aparelho = ?"
            params.append(aparelho)
        if desde:
            sql += " AND timestamp >= ?"
            params.append(desde.isoformat(timespec="seconds"))
        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limite)
        return [dict(l) for l in conn.execute(sql, params).fetchall()]


def ultimo_alerta(aparelho: str, tipo: str):
    with conectar() as conn:
        linha = conn.execute("""
            SELECT * FROM alertas WHERE aparelho = ? AND tipo = ?
            ORDER BY timestamp DESC, id DESC LIMIT 1
        """, (aparelho, tipo)).fetchone()
        return dict(linha) if linha else None


# ---------------------------------------------------------------------------
# Observações do usuário
# ---------------------------------------------------------------------------

def inserir_observacao(texto: str, autor: str = None, aparelho: str = None):
    with conectar() as conn:
        cur = conn.execute("""
            INSERT INTO observacoes (timestamp, autor, aparelho, texto) VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(timespec="seconds"), autor, aparelho, texto))
        return cur.lastrowid


def listar_observacoes(limite: int = 50):
    with conectar() as conn:
        return [dict(l) for l in conn.execute(
            "SELECT * FROM observacoes ORDER BY timestamp DESC, id DESC LIMIT ?", (limite,)).fetchall()]


def excluir_observacao(id_obs: int) -> bool:
    with conectar() as conn:
        return conn.execute("DELETE FROM observacoes WHERE id = ?", (id_obs,)).rowcount > 0


# ---------------------------------------------------------------------------
# Consumo (kWh) por integração da potência no tempo — usado em vários lugares
# ---------------------------------------------------------------------------

def kwh_periodo(aparelho: str, inicio: datetime, fim: datetime) -> float:
    leituras = leituras_periodo(aparelho, inicio, fim)
    total = 0.0
    for a, b in zip(leituras, leituras[1:]):
        if a["potencia"] is None or b["potencia"] is None:
            continue
        t1, t2 = datetime.fromisoformat(a["timestamp"]), datetime.fromisoformat(b["timestamp"])
        horas = (t2 - t1).total_seconds() / 3600
        if horas > 1:      # buraco grande (app desligado) — não extrapola
            continue
        total += ((a["potencia"] + b["potencia"]) / 2 * horas) / 1000
    return round(total, 3)


def kwh_todos_hoje() -> dict:
    """kWh de hoje por aparelho (dict nome -> kWh)."""
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return {nome: kwh_periodo(nome, hoje, datetime.now()) for nome in aparelhos_com_dados()}
