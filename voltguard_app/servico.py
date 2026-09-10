# -*- coding: utf-8 -*-
"""
servico.py
----------
O "coração" do VoltGuard: processa cada leitura, seja ela vinda por HTTP
(/api/leitura), por MQTT (mqtt_bridge) ou digitada à mão no painel.

Para cada leitura:
  1. garante o cadastro do aparelho;
  2. classifica a corrente (NORMAL / ATENCAO / ANORMAL);
  3. grava no banco;
  4. aplica a PROTEÇÃO: tensão fora dos limites, curto/sobrecarga ou
     temperatura alta -> registra alerta e, se a proteção automática estiver
     ligada, DESLIGA o relé do aparelho (e avisa o ESP32 via MQTT);
  5. quando a rede normaliza por N leituras seguidas, religa (se configurado);
  6. verifica a meta diária de consumo.

Devolve um dict que vai na resposta HTTP para o ESP32 — inclui "rele"
("ligado"/"desligado"), assim o firmware HTTP também consegue acionar o
relé sem precisar de MQTT.
"""

from datetime import datetime

import config
import database as db
import logic
import mqtt_bridge


def _float_ou_none(valor):
    try:
        return None if valor is None or valor == "" else float(valor)
    except (TypeError, ValueError):
        return None


JANELA_REPETICAO_S = 60   # mesmo alerta (tipo + aparelho) só é gravado de novo após esse tempo


def _registrar_alerta(tipo, aparelho, descricao, valor=None):
    """Grava o alerta, mas não repete o mesmo tipo/aparelho a cada leitura."""
    ultimo = db.ultimo_alerta(aparelho, tipo)
    if ultimo:
        idade = (datetime.now() - datetime.fromisoformat(ultimo["timestamp"])).total_seconds()
        if idade < JANELA_REPETICAO_S:
            return
    db.inserir_alerta(tipo=tipo, aparelho=aparelho, descricao=descricao, valor=valor)


def acionar_rele(aparelho: str, estado: str, motivo: str, origem: str = "protecao") -> bool:
    """Muda o estado do relé no banco, registra alerta e avisa o ESP32. Devolve True se mudou."""
    mudou = db.definir_rele(aparelho, estado, motivo)
    if mudou:
        db.inserir_alerta(
            tipo="RELE", aparelho=aparelho,
            descricao=f"Relé {estado.upper()} ({origem}): {motivo}",
            acao=f"rele_{estado}",
        )
    mqtt_bridge.publicar_comando(aparelho, "desligar" if estado == "desligado" else "ligar", motivo)
    return mudou


def _verificar_meta_diaria(aparelho: str, cfg: dict):
    meta = float(cfg.get("consumo_max_diario_kwh") or 0)
    if meta <= 0:
        return None
    total = sum(db.kwh_todos_hoje().values())
    if total < meta:
        return None
    # só um alerta de meta por dia
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if any(a["tipo"] == logic.ALERTA_META_DIARIA for a in db.listar_alertas(limite=200, desde=hoje)):
        return None
    db.inserir_alerta(tipo=logic.ALERTA_META_DIARIA, aparelho=None, valor=round(total, 2),
                      descricao=f"Meta diária de {meta:.0f} kWh ultrapassada ({total:.1f} kWh).")
    return logic.ALERTA_META_DIARIA


def processar_leitura(dados: dict, origem: str = "esp32") -> dict:
    """
    dados: {"aparelho": str, "corrente": float, "tensao": float?, "potencia": float?,
            "temperatura": float?, "dispositivo_id": str?}
    Lança ValueError se faltar campo obrigatório.
    """
    aparelho = (dados.get("aparelho") or "").strip()
    corrente = _float_ou_none(dados.get("corrente"))
    if not aparelho or corrente is None:
        raise ValueError("Campos obrigatórios: 'aparelho' e 'corrente'")

    tensao = _float_ou_none(dados.get("tensao"))
    temperatura = _float_ou_none(dados.get("temperatura"))
    potencia = _float_ou_none(dados.get("potencia"))
    if potencia is None:
        potencia = logic.calcular_potencia(tensao, corrente)

    cfg = db.obter_configuracoes()

    # 1) cadastro
    cadastro = db.obter_aparelho(aparelho)
    if cadastro is None:
        referencia = config.APARELHOS_REFERENCIA_PADRAO.get(aparelho, max(corrente, 0.1))
        db.upsert_aparelho(aparelho, referencia,
                           potencia_estimada=config.APARELHOS_POTENCIA_PADRAO.get(aparelho))
        cadastro = db.obter_aparelho(aparelho)
    referencia = cadastro["corrente_referencia"]

    # 2) classificação por corrente
    status = logic.classificar_status(corrente, referencia)

    # 3) grava
    db.inserir_leitura(
        dispositivo_id=dados.get("dispositivo_id"), aparelho=aparelho, corrente=corrente,
        tensao=tensao, potencia=potencia, status=status, temperatura=temperatura, origem=origem,
    )

    # 4) proteção
    alertas = []
    motivo_desligar = None

    tipo_tensao = logic.avaliar_tensao(tensao, cfg)
    if tipo_tensao:
        texto = (f"Subtensão: {tensao:.1f} V (mínimo {float(cfg['tensao_minima']):.0f} V)"
                 if tipo_tensao == logic.ALERTA_SUBTENSAO else
                 f"Sobretensão: {tensao:.1f} V (máximo {float(cfg['tensao_maxima']):.0f} V)")
        _registrar_alerta(tipo_tensao, aparelho, texto, tensao)
        alertas.append(tipo_tensao)
        motivo_desligar = motivo_desligar or texto

    if referencia and corrente >= referencia * config.FATOR_CURTO_CIRCUITO:
        texto = f"Pico de corrente: {corrente:.2f} A (referência {referencia:.2f} A) — possível curto/sobrecarga"
        _registrar_alerta(logic.ALERTA_CURTO, aparelho, texto, corrente)
        alertas.append(logic.ALERTA_CURTO)
        motivo_desligar = motivo_desligar or texto
    elif status == logic.STATUS_ANORMAL:
        _registrar_alerta(logic.ALERTA_SOBRECORRENTE, aparelho,
                          f"Corrente {corrente:.2f} A acima de 120% da referência ({referencia:.2f} A)", corrente)
        alertas.append(logic.ALERTA_SOBRECORRENTE)

    tipo_temp = logic.avaliar_temperatura(temperatura, cfg)
    if tipo_temp:
        texto = f"Temperatura alta no quadro: {temperatura:.1f} °C (máx. {float(cfg['temperatura_maxima']):.0f} °C)"
        _registrar_alerta(tipo_temp, aparelho, texto, temperatura)
        alertas.append(tipo_temp)
        motivo_desligar = motivo_desligar or texto

    rele_mudou = False
    if cadastro.get("tem_rele"):
        desligado_manual = (cadastro.get("rele_estado") == "desligado"
                            and (cadastro.get("rele_motivo") or "").lower() == "manual")
        if motivo_desligar and int(cfg.get("protecao_automatica") or 0) and not desligado_manual:
            rele_mudou = acionar_rele(aparelho, "desligado", motivo_desligar, origem="proteção automática")
        elif (cadastro.get("rele_estado") == "desligado" and int(cfg.get("religar_automatico") or 0)
              and (cadastro.get("rele_motivo") or "").lower() != "manual"):
            # 5) religa quando as últimas N leituras estão todas dentro dos limites
            n = int(cfg.get("leituras_para_religar") or 5)
            ultimas = db.ultimas_leituras(aparelho, n)
            if len(ultimas) >= n and all(
                logic.avaliar_tensao(l["tensao"], cfg) is None
                and logic.avaliar_temperatura(l.get("temperatura"), cfg) is None
                and (not referencia or l["corrente"] < referencia * config.FATOR_CURTO_CIRCUITO)
                for l in ultimas
            ):
                rele_mudou = acionar_rele(aparelho, "ligado",
                                          f"Rede normalizada por {n} leituras seguidas", origem="religamento automático")

    # 6) meta diária
    meta = _verificar_meta_diaria(aparelho, cfg)
    if meta:
        alertas.append(meta)

    cadastro = db.obter_aparelho(aparelho)
    return {
        "status": status,
        "referencia": referencia,
        "potencia": potencia,
        "alertas": alertas,
        "rele": cadastro.get("rele_estado", "ligado") if cadastro.get("tem_rele") else None,
        "rele_mudou": rele_mudou,
    }
