# -*- coding: utf-8 -*-
"""
logic.py
--------
Regras de análise dos dados do VoltGuard:
  - Classificação do status (NORMAL / ATENCAO / ANORMAL)
  - Cálculo estimado de potência (P = V x I)
  - Estimativa de perda em standby
  - Status do painel de proteções

Mantido separado do app.py para ficar fácil de testar e de explicar
na apresentação do trabalho (é aqui que fica a "inteligência" do sistema).
"""

import statistics
from datetime import datetime

import config

STATUS_NORMAL = "NORMAL"
STATUS_ATENCAO = "ATENCAO"
STATUS_ANORMAL = "ANORMAL"

TARIFA_KWH = 0.95  # fallback; o valor real vem de configuracoes.tarifa_kwh

# Tipos de alerta de proteção
ALERTA_SUBTENSAO = "SUBTENSAO"
ALERTA_SOBRETENSAO = "SOBRETENSAO"
ALERTA_SOBRECORRENTE = "SOBRECORRENTE"
ALERTA_CURTO = "CURTO_CIRCUITO"
ALERTA_TEMPERATURA = "TEMPERATURA"
ALERTA_META_DIARIA = "META_DIARIA"


def classificar_status(corrente: float, referencia: float) -> str:
    """
    Compara a corrente medida com a faixa de referência do aparelho.
    Segue a lógica descrita no documento-base (seção 12):
    o sistema não afirma que há defeito, apenas sinaliza que a leitura
    merece atenção/investigação.
    """
    if referencia is None or referencia <= 0:
        return STATUS_NORMAL

    if corrente <= referencia * config.FATOR_ATENCAO:
        return STATUS_NORMAL
    elif corrente <= referencia * config.FATOR_ANORMAL:
        return STATUS_ATENCAO
    else:
        return STATUS_ANORMAL


def calcular_potencia(tensao, corrente):
    """P = V x I (estimativa simplificada, ver seção 15 do documento-base)."""
    if tensao is None or corrente is None:
        return None
    return round(tensao * corrente, 2)


def estatisticas_periodo(leituras: list) -> dict:
    """Recebe uma lista de leituras (dicts) e devolve as estatísticas
    usadas tanto no dashboard quanto no relatório técnico."""
    if not leituras:
        return {
            "quantidade": 0,
            "corrente_media": None, "corrente_min": None, "corrente_max": None,
            "tensao_media": None, "tensao_min": None, "tensao_max": None,
            "potencia_media": None, "potencia_max": None,
            "ocorrencias": 0,
            "horarios_ocorrencias": [],
        }

    correntes = [l["corrente"] for l in leituras if l["corrente"] is not None]
    tensoes = [l["tensao"] for l in leituras if l["tensao"] is not None]
    potencias = [l["potencia"] for l in leituras if l["potencia"] is not None]

    ocorrencias = [l for l in leituras if l["status"] in (STATUS_ATENCAO, STATUS_ANORMAL)]

    return {
        "quantidade": len(leituras),
        "corrente_media": round(statistics.mean(correntes), 2) if correntes else None,
        "corrente_min": round(min(correntes), 2) if correntes else None,
        "corrente_max": round(max(correntes), 2) if correntes else None,
        "tensao_media": round(statistics.mean(tensoes), 2) if tensoes else None,
        "tensao_min": round(min(tensoes), 2) if tensoes else None,
        "tensao_max": round(max(tensoes), 2) if tensoes else None,
        "potencia_media": round(statistics.mean(potencias), 2) if potencias else None,
        "potencia_max": round(max(potencias), 2) if potencias else None,
        "ocorrencias": len(ocorrencias),
        "horarios_ocorrencias": [l["timestamp"] for l in ocorrencias],
    }


def estimar_perda_standby(leituras: list, limiar_standby_w: float = None) -> dict:
    """
    Estima a proporção do tempo em que o aparelho ficou em 'standby'
    (potência baixa, porém diferente de zero) x 'ativo'.

    limiar_standby_w: potência (W) abaixo da qual consideramos standby.
    Se não for informado, usa 15% da potência máxima observada.
    """
    potencias = [l["potencia"] for l in leituras if l["potencia"] is not None]
    if not potencias:
        return {"pct_ativo": 0, "pct_standby": 0, "perda_estimada_reais": 0.0}

    pico = max(potencias)
    limiar = limiar_standby_w if limiar_standby_w is not None else max(pico * 0.15, 1.0)

    amostras_standby = [p for p in potencias if p <= limiar]
    pct_standby = round(100 * len(amostras_standby) / len(potencias))
    pct_ativo = 100 - pct_standby

    # Estimativa grosseira de energia "desperdiçada" em standby no período,
    # extrapolada para 30 dias, convertida em R$ pela tarifa configurada.
    media_standby_w = statistics.mean(amostras_standby) if amostras_standby else 0
    horas_standby_dia = 24 * (pct_standby / 100)
    kwh_mes = (media_standby_w / 1000) * horas_standby_dia * 30
    perda_reais = round(kwh_mes * TARIFA_KWH, 2)

    return {
        "pct_ativo": pct_ativo,
        "pct_standby": pct_standby,
        "perda_estimada_reais": perda_reais,
    }


def avaliar_tensao(tensao, cfg: dict):
    """Devolve None, ALERTA_SUBTENSAO ou ALERTA_SOBRETENSAO conforme os limites do usuário."""
    if tensao is None:
        return None
    if tensao < float(cfg["tensao_minima"]):
        return ALERTA_SUBTENSAO
    if tensao > float(cfg["tensao_maxima"]):
        return ALERTA_SOBRETENSAO
    return None


def avaliar_temperatura(temperatura, cfg: dict):
    if temperatura is None:
        return None
    return ALERTA_TEMPERATURA if temperatura > float(cfg["temperatura_maxima"]) else None


def tarifa_efetiva(cfg: dict) -> float:
    """Tarifa base + adicional da bandeira tarifária (R$/kWh)."""
    return round(float(cfg["tarifa_kwh"]) + config.BANDEIRAS.get(cfg.get("bandeira", "verde"), 0.0), 4)


def custo(kwh: float, cfg: dict) -> float:
    return round(kwh * tarifa_efetiva(cfg), 2)


def gerar_dicas(aparelhos: list, kwh_hoje: dict, cfg: dict, alertas_recentes: list) -> list:
    """
    Dicas de economia/segurança baseadas em regras simples (if/else) — como
    definido no projeto: sem IA, só cruzando o que o sensor mediu com o que o
    usuário cadastrou (potência, horário) e com a meta diária.
    Devolve lista de dicts {nivel, titulo, texto}.
    """
    dicas = []
    total_hoje = sum(kwh_hoje.values())
    meta = float(cfg["consumo_max_diario_kwh"] or 0)
    tarifa = tarifa_efetiva(cfg)

    if meta and total_hoje >= meta:
        dicas.append({"nivel": "alerta", "titulo": "Meta diária ultrapassada",
                      "texto": f"Hoje já foram {total_hoje:.1f} kWh (meta: {meta:.0f} kWh) — "
                               f"cerca de R$ {total_hoje * tarifa:.2f}. Revise o uso dos aparelhos de maior consumo."})
    elif meta and total_hoje >= meta * 0.8:
        dicas.append({"nivel": "atencao", "titulo": "Perto da meta diária",
                      "texto": f"{total_hoje:.1f} de {meta:.0f} kWh consumidos hoje ({100 * total_hoje / meta:.0f}%)."})

    if kwh_hoje:
        maior = max(kwh_hoje, key=kwh_hoje.get)
        if total_hoje > 0 and kwh_hoje[maior] / total_hoje >= 0.4:
            pct = 100 * kwh_hoje[maior] / total_hoje
            dicas.append({"nivel": "info", "titulo": f"{maior} concentra o consumo",
                          "texto": f"Responde por {pct:.0f}% do consumo de hoje "
                                   f"(R$ {kwh_hoje[maior] * tarifa:.2f}). Concentrar o uso em um turno "
                                   f"e evitar deixá-lo aquecendo vazio reduz esse valor."})

    agora = datetime.now().strftime("%H:%M")
    for ap in aparelhos:
        ini, fim = ap.get("horario_inicio"), ap.get("horario_fim")
        if ini and fim and ap.get("ultima_potencia") and ap["ultima_potencia"] > 50:
            fora = (ini <= fim and not (ini <= agora <= fim)) or (ini > fim and (fim < agora < ini))
            if fora:
                dicas.append({"nivel": "atencao", "titulo": f"{ap['nome']} ligado fora do horário",
                              "texto": f"Horário cadastrado: {ini} às {fim}. Está consumindo "
                                       f"{ap['ultima_potencia']:.0f} W agora ({agora})."})
        if ap.get("potencia_estimada") and ap.get("ultima_potencia"):
            if ap["ultima_potencia"] > 1.3 * float(ap["potencia_estimada"]):
                dicas.append({"nivel": "atencao", "titulo": f"{ap['nome']} acima da potência esperada",
                              "texto": f"Medido {ap['ultima_potencia']:.0f} W, cadastrado "
                                       f"{float(ap['potencia_estimada']):.0f} W. Pode indicar desgaste, "
                                       f"sobrecarga ou necessidade de manutenção."})

    n_tensao = sum(1 for a in alertas_recentes if a["tipo"] in (ALERTA_SUBTENSAO, ALERTA_SOBRETENSAO))
    if n_tensao >= 5:
        dicas.append({"nivel": "alerta", "titulo": "Rede instável nas últimas 24 h",
                      "texto": f"{n_tensao} eventos de tensão fora da faixa. Considere um estabilizador/"
                               f"nobreak para os equipamentos sensíveis e registre a ocorrência junto à "
                               f"concessionária — o VoltGuard exporta o histórico em CSV/PDF como evidência."})

    if cfg.get("bandeira", "verde") != "verde":
        dicas.append({"nivel": "info", "titulo": "Bandeira tarifária ativa",
                      "texto": f"Bandeira {cfg['bandeira']}: cada kWh custa R$ {tarifa:.3f}. "
                               f"Vale adiantar processos de forno para o horário de menor demanda."})

    if not dicas:
        dicas.append({"nivel": "ok", "titulo": "Tudo dentro do esperado",
                      "texto": "Consumo e tensão dentro dos limites configurados. Mantenha o monitoramento."})
    return dicas


def status_protecoes(leituras_recentes: list, referencia: float, cfg: dict = None, aparelho: dict = None) -> dict:
    """
    Calcula o estado dos quatro indicadores do painel 'Status das Proteções'.

    IMPORTANTE (para a apresentação do trabalho): 'Sobretensão' e
    'Curto-circuito' usam limites reais configuráveis (config.py).
    'Harmônicas DHT' é uma aproximação (ver comentário em config.py),
    pois DHT real exige amostragem da forma de onda, não apenas o valor RMS
    que o ACS712 fornece. 'Backup UPS' é um indicador reservado para uma
    futura expansão de hardware (não há UPS no escopo atual do projeto).
    """
    cfg = cfg or dict(config.CONFIG_INICIAL)
    resultado = {
        "sobretensao": {"status": "ATIVO", "detalhe": "Dentro da faixa"},
        "curto_circuito": {"status": "ATIVO", "detalhe": "Nenhum pico detectado"},
        "harmonicas_dht": {"status": "ATIVO", "detalhe": "Variação normal"},
        "temperatura": {"status": "STANDBY", "detalhe": "Sem sensor DHT22"},
        "rele": {"status": "ATIVO", "detalhe": "Ligado"},
    }
    if aparelho:
        if not aparelho.get("tem_rele"):
            resultado["rele"] = {"status": "STANDBY", "detalhe": "Sem relé neste aparelho"}
        elif aparelho.get("rele_estado") == "desligado":
            resultado["rele"] = {"status": "ALERTA", "detalhe": f"DESLIGADO — {aparelho.get('rele_motivo') or 'proteção'}"}

    if not leituras_recentes:
        return resultado

    temperaturas = [l.get("temperatura") for l in leituras_recentes if l.get("temperatura") is not None]
    if temperaturas:
        t = temperaturas[-1]
        if t > float(cfg["temperatura_maxima"]):
            resultado["temperatura"] = {"status": "ALERTA", "detalhe": f"{t:.1f} °C no quadro"}
        elif t > float(cfg["temperatura_maxima"]) - 5:
            resultado["temperatura"] = {"status": "ATENCAO", "detalhe": f"{t:.1f} °C — aquecendo"}
        else:
            resultado["temperatura"] = {"status": "ATIVO", "detalhe": f"{t:.1f} °C"}

    tensoes = [l["tensao"] for l in leituras_recentes if l["tensao"] is not None]
    correntes = [l["corrente"] for l in leituras_recentes if l["corrente"] is not None]

    if tensoes:
        ultima_tensao = tensoes[-1]
        if ultima_tensao > float(cfg["tensao_maxima"]):
            resultado["sobretensao"] = {"status": "ALERTA", "detalhe": f"{ultima_tensao:.1f} V — sobretensão"}
        elif ultima_tensao < float(cfg["tensao_minima"]):
            resultado["sobretensao"] = {"status": "ALERTA", "detalhe": f"{ultima_tensao:.1f} V — subtensão"}
        elif ultima_tensao < float(cfg["tensao_minima"]) + 5 or ultima_tensao > float(cfg["tensao_maxima"]) - 5:
            resultado["sobretensao"] = {"status": "ATENCAO", "detalhe": f"{ultima_tensao:.1f} V — perto do limite"}

    if correntes and referencia:
        pico = max(correntes)
        if pico >= referencia * config.FATOR_CURTO_CIRCUITO:
            resultado["curto_circuito"] = {"status": "ALERTA", "detalhe": f"Pico de {pico:.1f} A"}

    if len(correntes) >= 5:
        media = statistics.mean(correntes)
        desvio = statistics.pstdev(correntes)
        coef_variacao = (desvio / media) if media else 0
        if coef_variacao >= config.DHT_VARIACAO_ATENCAO:
            resultado["harmonicas_dht"] = {"status": "ATENCAO", "detalhe": "Variação elevada na corrente"}

    return resultado


def classificar_comportamento(stats: dict) -> str:
    """Usado no relatório técnico: um resumo textual curto do comportamento observado."""
    if stats["quantidade"] == 0:
        return "Sem dados suficientes para classificação."

    pct_ocorrencias = stats["ocorrencias"] / stats["quantidade"]
    if pct_ocorrencias == 0:
        return "Comportamento estável, dentro da faixa de referência durante todo o período."
    elif pct_ocorrencias < 0.1:
        return "Comportamento majoritariamente estável, com poucas ocorrências pontuais acima da referência."
    elif pct_ocorrencias < 0.4:
        return "Comportamento instável, com ocorrências recorrentes de consumo acima da referência."
    else:
        return "Comportamento predominantemente anormal, com consumo frequentemente acima da referência."


def gerar_recomendacao(stats: dict, referencia: float) -> str:
    if stats["quantidade"] == 0 or referencia is None:
        return "Não há dados suficientes no período para gerar uma recomendação técnica."

    if stats["ocorrencias"] == 0:
        return ("Nenhuma ação corretiva é necessária no momento. Recomenda-se manter o "
                "monitoramento periódico do equipamento.")

    excesso = (stats["corrente_max"] - referencia) if stats["corrente_max"] else 0
    return (
        f"Durante o período analisado, o equipamento apresentou corrente acima da faixa de "
        f"referência em determinados momentos. Foi registrada corrente máxima de "
        f"{stats['corrente_max']:.2f} A, enquanto o valor de referência configurado é de "
        f"{referencia:.2f} A (excesso de {excesso:.2f} A). Recomenda-se realizar uma inspeção "
        f"técnica para investigar possíveis condições de sobrecarga, funcionamento inadequado "
        f"ou necessidade de manutenção."
    )
