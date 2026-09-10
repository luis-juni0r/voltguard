# -*- coding: utf-8 -*-
"""
app.py
------
VoltGuard — App principal (Flask).

Como executar (ver README.md para o passo a passo completo no PyCharm):
    python app.py

O dashboard fica em: http://localhost:5000
O ESP32 (ou o simulador esp32_simulator.py) envia leituras via HTTP POST
para o endpoint /api/leitura.
"""

import os
import csv
import io
import logging
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, render_template, send_file, Response

import config
import database as db
import logic
import report_generator
import servico
import mqtt_bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
db.init_db()


def _e_processo_pai_do_reloader():
    """Com debug=True + reloader, o Flask sobe 2 processos; só o filho deve abrir o MQTT."""
    return (__name__ == "__main__" and os.environ.get("VOLTGUARD_NO_RELOAD") != "1"
            and os.environ.get("WERKZEUG_RUN_MAIN") != "true")


if not _e_processo_pai_do_reloader():
    mqtt_bridge.iniciar(servico.processar_leitura)


def _api_key_ok():
    if not config.API_KEY:
        return True
    enviada = request.headers.get("X-Api-Key") or request.args.get("api_key")
    return enviada == config.API_KEY


def _url_base():
    return request.url_root.rstrip("/")


# ---------------------------------------------------------------------------
# Página principal
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/aparelhos-config")
def pagina_aparelhos():
    return render_template("aparelhos.html")


@app.route("/configuracoes")
def pagina_configuracoes():
    return render_template("configuracoes.html")


@app.route("/health")
def health():
    """Usado pela hospedagem (Render/Railway) para saber que o app está vivo."""
    return jsonify({"ok": True, "mqtt": mqtt_bridge.estado()["conectado"]})


# ---------------------------------------------------------------------------
# Recepção de dados do ESP32
# ---------------------------------------------------------------------------

@app.route("/api/leitura", methods=["POST"])
def receber_leitura():
    """
    Endpoint que o ESP32 (ou o simulador) chama para enviar uma nova leitura.

    JSON esperado:
    {
        "dispositivo_id": "VG001",
        "aparelho": "Forno elétrico",
        "corrente": 7.6,          # A  (ACS712)
        "tensao": 218.4,          # V  (ZMPT101B)
        "temperatura": 31.2,      # °C (DHT22, opcional)
        "potencia": 1660          # opcional: se ausente, é calculada como V x I
    }
    Resposta traz "rele": "ligado"|"desligado" -> o firmware HTTP usa isso
    para acionar o relé sem precisar de MQTT.
    """
    if not _api_key_ok():
        return jsonify({"erro": "X-Api-Key inválida"}), 401
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "JSON inválido ou ausente"}), 400
    try:
        resultado = servico.processar_leitura(dados, origem=dados.get("origem") or "esp32")
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    return jsonify(resultado), 201


@app.route("/api/leitura-manual", methods=["POST"])
def leitura_manual():
    """Entrada manual pelo painel (valor lido no multímetro / teste sem sensor)."""
    dados = request.get_json(silent=True) or {}
    try:
        resultado = servico.processar_leitura(dados, origem="manual")
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    return jsonify(resultado), 201


# ---------------------------------------------------------------------------
# Relé (atuador de proteção)
# ---------------------------------------------------------------------------

@app.route("/api/rele/<nome>", methods=["GET"])
def estado_rele(nome):
    """O ESP32 (HTTP) pode consultar isto de tempos em tempos para saber se deve desligar."""
    ap = db.obter_aparelho(nome)
    if not ap:
        return jsonify({"erro": "Aparelho não encontrado"}), 404
    return jsonify({"aparelho": nome, "tem_rele": bool(ap["tem_rele"]), "rele": ap["rele_estado"],
                    "motivo": ap["rele_motivo"], "alterado_em": ap["rele_alterado_em"]})


@app.route("/api/rele/<nome>", methods=["POST"])
def comandar_rele(nome):
    """Comando manual pelo painel: {"comando": "ligar" | "desligar"}."""
    dados = request.get_json(silent=True) or {}
    comando = dados.get("comando")
    if comando not in ("ligar", "desligar"):
        return jsonify({"erro": "comando deve ser 'ligar' ou 'desligar'"}), 400
    ap = db.obter_aparelho(nome)
    if not ap:
        return jsonify({"erro": "Aparelho não encontrado"}), 404
    if not ap["tem_rele"]:
        return jsonify({"erro": "Este aparelho está cadastrado sem relé"}), 400
    estado = "desligado" if comando == "desligar" else "ligado"
    servico.acionar_rele(nome, estado, "manual", origem="painel")
    return jsonify({"ok": True, "rele": estado})


# ---------------------------------------------------------------------------
# Configurações do usuário
# ---------------------------------------------------------------------------

@app.route("/api/configuracoes", methods=["GET"])
def obter_configuracoes():
    cfg = db.obter_configuracoes()
    cfg["tarifa_efetiva"] = logic.tarifa_efetiva(cfg)
    cfg["bandeiras"] = config.BANDEIRAS
    return jsonify(cfg)


@app.route("/api/configuracoes", methods=["POST"])
def salvar_configuracoes():
    dados = request.get_json(silent=True) or {}
    limpos = {}
    for campo in db.CAMPOS_CONFIG:
        if campo not in dados:
            continue
        valor = dados[campo]
        if campo in ("nome_local", "bandeira"):
            limpos[campo] = str(valor).strip()
        elif campo in ("protecao_automatica", "religar_automatico", "leituras_para_religar"):
            limpos[campo] = int(valor)
        else:
            limpos[campo] = float(valor)
    if "tensao_minima" in limpos and "tensao_maxima" in limpos and limpos["tensao_minima"] >= limpos["tensao_maxima"]:
        return jsonify({"erro": "A tensão mínima precisa ser menor que a máxima"}), 400
    if limpos.get("bandeira") and limpos["bandeira"] not in config.BANDEIRAS:
        return jsonify({"erro": f"Bandeira inválida. Use: {', '.join(config.BANDEIRAS)}"}), 400
    cfg = db.salvar_configuracoes(limpos)
    cfg["tarifa_efetiva"] = logic.tarifa_efetiva(cfg)
    return jsonify(cfg)


# ---------------------------------------------------------------------------
# Alertas de proteção, observações e dicas
# ---------------------------------------------------------------------------

@app.route("/api/alertas")
def listar_alertas():
    aparelho = request.args.get("aparelho")
    limite = int(request.args.get("limite", 30))
    horas = request.args.get("horas")
    desde = datetime.now() - timedelta(hours=float(horas)) if horas else None
    return jsonify(db.listar_alertas(limite=limite, aparelho=aparelho, desde=desde))


@app.route("/api/observacoes", methods=["GET"])
def listar_observacoes():
    return jsonify(db.listar_observacoes(limite=int(request.args.get("limite", 50))))


@app.route("/api/observacoes", methods=["POST"])
def criar_observacao():
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    if not texto:
        return jsonify({"erro": "Informe o texto da observação"}), 400
    id_obs = db.inserir_observacao(texto, autor=(dados.get("autor") or "").strip() or None,
                                   aparelho=dados.get("aparelho") or None)
    return jsonify({"ok": True, "id": id_obs}), 201


@app.route("/api/observacoes/<int:id_obs>", methods=["DELETE"])
def apagar_observacao(id_obs):
    if not db.excluir_observacao(id_obs):
        return jsonify({"erro": "Observação não encontrada"}), 404
    return jsonify({"ok": True})


@app.route("/api/dicas")
def dicas():
    cfg = db.obter_configuracoes()
    kwh_hoje = db.kwh_todos_hoje()
    aparelhos = []
    for ap in db.listar_aparelhos():
        ultima = db.ultima_leitura(ap["nome"])
        ap["ultima_potencia"] = ultima["potencia"] if ultima else None
        aparelhos.append(ap)
    alertas_24h = db.listar_alertas(limite=200, desde=datetime.now() - timedelta(hours=24))
    return jsonify({
        "dicas": logic.gerar_dicas(aparelhos, kwh_hoje, cfg, alertas_24h),
        "kwh_hoje_total": round(sum(kwh_hoje.values()), 2),
        "custo_hoje_total": logic.custo(sum(kwh_hoje.values()), cfg),
        "kwh_por_aparelho": kwh_hoje,
    })


@app.route("/api/info")
def info_conexao():
    """Dados que o ESP32 precisa (URL pública, tópicos MQTT) — exibidos na tela Configurações."""
    base = _url_base()
    return jsonify({
        "url_base": base,
        "endpoint_leitura": f"{base}/api/leitura",
        "api_key_exigida": bool(config.API_KEY),
        "mqtt": mqtt_bridge.estado(),
        "exemplo_json": {"dispositivo_id": "VG001", "aparelho": "Forno elétrico",
                         "corrente": 7.6, "tensao": 218.4, "temperatura": 31.2},
    })


# ---------------------------------------------------------------------------
# Aparelhos
# ---------------------------------------------------------------------------

@app.route("/api/aparelhos", methods=["GET"])
def listar_aparelhos():
    cadastrados = {a["nome"]: a for a in db.listar_aparelhos()}
    com_dados = db.aparelhos_com_dados()
    # une cadastrados + quem já mandou dados mas ainda não tem cadastro formal
    nomes = sorted(set(cadastrados.keys()) | set(com_dados))
    resposta = []
    for nome in nomes:
        c = cadastrados.get(nome, {})
        resposta.append({
            "nome": nome,
            "corrente_referencia": c.get("corrente_referencia"),
            "potencia_estimada": c.get("potencia_estimada"),
            "horario_inicio": c.get("horario_inicio"),
            "horario_fim": c.get("horario_fim"),
            "tem_rele": bool(c.get("tem_rele", 1)),
            "rele_estado": c.get("rele_estado", "ligado"),
            "rele_motivo": c.get("rele_motivo"),
        })
    return jsonify(resposta)


@app.route("/api/aparelhos", methods=["POST"])
def salvar_aparelho():
    dados = request.get_json(silent=True) or {}
    nome = dados.get("nome")
    referencia = dados.get("corrente_referencia")
    if not nome or referencia is None:
        return jsonify({"erro": "Campos obrigatórios: 'nome' e 'corrente_referencia'"}), 400
    def _num(v):
        try:
            return None if v in (None, "") else float(v)
        except (TypeError, ValueError):
            return None
    tem_rele = dados.get("tem_rele")
    db.upsert_aparelho(
        nome, float(referencia),
        potencia_estimada=_num(dados.get("potencia_estimada")),
        horario_inicio=(dados.get("horario_inicio") or None),
        horario_fim=(dados.get("horario_fim") or None),
        tem_rele=None if tem_rele is None else int(bool(tem_rele)),
    )
    return jsonify({"ok": True})


@app.route("/api/aparelhos/<nome>", methods=["DELETE"])
def deletar_aparelho(nome):
    removido = db.excluir_aparelho(nome)
    if not removido:
        return jsonify({"erro": "Aparelho não encontrado no cadastro"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Dados para o dashboard
# ---------------------------------------------------------------------------

def _aparelho_selecionado(args):
    """Resolve qual aparelho exibir: o passado na querystring ou o mais recente."""
    aparelho = args.get("aparelho")
    if aparelho:
        return aparelho
    ultima = db.ultima_leitura()
    return ultima["aparelho"] if ultima else None


@app.route("/api/atual")
def api_atual():
    aparelho = _aparelho_selecionado(request.args)
    if not aparelho:
        return jsonify({"aparelho": None})

    leitura = db.ultima_leitura(aparelho)
    referencia = db.obter_referencia(aparelho)

    recentes = db.leituras_recentes(aparelho, minutos=60)
    hoje_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    leituras_hoje = db.leituras_periodo(aparelho, hoje_inicio, datetime.now())

    kwh_hoje = 0.0
    if len(leituras_hoje) >= 2:
        # integração trapezoidal simples de potência (W) ao longo do tempo -> kWh
        for a, b in zip(leituras_hoje, leituras_hoje[1:]):
            if a["potencia"] is None or b["potencia"] is None:
                continue
            t1 = datetime.fromisoformat(a["timestamp"])
            t2 = datetime.fromisoformat(b["timestamp"])
            horas = (t2 - t1).total_seconds() / 3600
            media_w = (a["potencia"] + b["potencia"]) / 2
            kwh_hoje += (media_w * horas) / 1000

    cfg = db.obter_configuracoes()
    cadastro = db.obter_aparelho(aparelho) or {}
    protecoes = logic.status_protecoes(recentes, referencia, cfg, cadastro)

    total_hoje = sum(db.kwh_todos_hoje().values())
    tensao_alerta = logic.avaliar_tensao(leitura["tensao"], cfg) if leitura else None

    return jsonify({
        "aparelho": aparelho,
        "referencia": referencia,
        "leitura": leitura,
        "kwh_hoje": round(kwh_hoje, 2),
        "protecoes": protecoes,
        "custo_hoje": logic.custo(kwh_hoje, cfg),
        "total_hoje_kwh": round(total_hoje, 2),
        "total_hoje_custo": logic.custo(total_hoje, cfg),
        "tarifa_efetiva": logic.tarifa_efetiva(cfg),
        "meta_diaria_kwh": cfg["consumo_max_diario_kwh"],
        "limites": {"tensao_minima": cfg["tensao_minima"], "tensao_maxima": cfg["tensao_maxima"],
                    "tensao_nominal": cfg["tensao_nominal"], "temperatura_maxima": cfg["temperatura_maxima"]},
        "tensao_alerta": tensao_alerta,
        "rele": {"tem": bool(cadastro.get("tem_rele")), "estado": cadastro.get("rele_estado"),
                 "motivo": cadastro.get("rele_motivo"), "alterado_em": cadastro.get("rele_alterado_em")},
        "nome_local": cfg["nome_local"],
        "mqtt_conectado": mqtt_bridge.estado()["conectado"],
    })


@app.route("/api/historico")
def api_historico():
    aparelho = _aparelho_selecionado(request.args)
    periodo = request.args.get("periodo", "hoje")  # 'hoje' ou 'ontem'
    if not aparelho:
        return jsonify([])

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "ontem":
        inicio = hoje - timedelta(days=1)
        fim = hoje
    else:
        inicio = hoje
        fim = datetime.now()

    leituras = db.leituras_periodo(aparelho, inicio, fim)
    pontos = [
        {"timestamp": l["timestamp"], "corrente": l["corrente"], "tensao": l["tensao"],
         "potencia": l["potencia"], "status": l["status"], "temperatura": l.get("temperatura")}
        for l in leituras
    ]
    return jsonify(pontos)


@app.route("/api/24h")
def api_24h():
    aparelho = _aparelho_selecionado(request.args)
    if not aparelho:
        return jsonify({})

    inicio = datetime.now() - timedelta(hours=24)
    leituras = db.leituras_periodo(aparelho, inicio, datetime.now())
    potencias = [l["potencia"] for l in leituras if l["potencia"] is not None]

    ultima = db.ultima_leitura(aparelho)
    atual = ultima["potencia"] if ultima else None

    hoje_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    leituras_hoje = db.leituras_periodo(aparelho, hoje_inicio, datetime.now())
    kwh_hoje = 0.0
    for a, b in zip(leituras_hoje, leituras_hoje[1:]):
        if a["potencia"] is None or b["potencia"] is None:
            continue
        t1, t2 = datetime.fromisoformat(a["timestamp"]), datetime.fromisoformat(b["timestamp"])
        horas = (t2 - t1).total_seconds() / 3600
        kwh_hoje += ((a["potencia"] + b["potencia"]) / 2 * horas) / 1000

    standby = logic.estimar_perda_standby(leituras_hoje or leituras)

    return jsonify({
        "atual": round(atual, 1) if atual is not None else None,
        "pico": round(max(potencias), 1) if potencias else None,
        "standby_w": round(min(potencias), 1) if potencias else None,
        "hoje_kwh": round(kwh_hoje, 2),
        "standby": standby,
    })


@app.route("/api/30dias")
def api_30dias():
    aparelho = _aparelho_selecionado(request.args)
    if not aparelho:
        return jsonify([])

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dias = []
    for i in range(29, -1, -1):
        dia_inicio = hoje - timedelta(days=i)
        dia_fim = dia_inicio + timedelta(days=1)
        leituras_dia = db.leituras_periodo(aparelho, dia_inicio, dia_fim)

        kwh_dia = 0.0
        kwh_noite = 0.0
        for a, b in zip(leituras_dia, leituras_dia[1:]):
            if a["potencia"] is None or b["potencia"] is None:
                continue
            t1, t2 = datetime.fromisoformat(a["timestamp"]), datetime.fromisoformat(b["timestamp"])
            horas = (t2 - t1).total_seconds() / 3600
            kwh = ((a["potencia"] + b["potencia"]) / 2 * horas) / 1000
            hora_do_dia = t1.hour
            if 6 <= hora_do_dia < 18:
                kwh_dia += kwh
            else:
                kwh_noite += kwh

        dias.append({
            "data": dia_inicio.strftime("%d/%m"),
            "dia": round(kwh_dia, 2),
            "noite": round(kwh_noite, 2),
        })

    return jsonify(dias)


@app.route("/api/ocorrencias")
def api_ocorrencias():
    """
    Histórico de ocorrências (alertas) — leituras em ATENCAO/ANORMAL.
    Por padrão, retorna de todos os aparelhos (para dar uma visão geral no
    dashboard). Passe ?aparelho=Nome para filtrar por um aparelho específico
    e ?limite=N para mudar a quantidade (padrão 30).
    """
    aparelho = request.args.get("aparelho")
    limite = int(request.args.get("limite", 30))

    ocorrencias = db.listar_ocorrencias(limite=limite, aparelho=aparelho)

    # Anexa a corrente de referência de cada aparelho envolvido (cache simples
    # em memória durante a resposta, para não repetir consulta ao banco).
    cache_referencia = {}
    resposta = []
    for o in ocorrencias:
        nome = o["aparelho"]
        if nome not in cache_referencia:
            cache_referencia[nome] = db.obter_referencia(nome)
        resposta.append({
            "timestamp": o["timestamp"],
            "aparelho": nome,
            "corrente": o["corrente"],
            "referencia": cache_referencia[nome],
            "status": o["status"],
        })

    return jsonify(resposta)


@app.route("/exportar")
def exportar_csv():
    """
    Exporta as leituras cruas em CSV (separador ';' e BOM UTF-8, para abrir
    certinho no Excel em pt-BR). Sem ?aparelho, exporta de todos os aparelhos.
    """
    aparelho = request.args.get("aparelho")
    dias = int(request.args.get("dias", 30))
    fim = datetime.now()
    inicio = fim - timedelta(days=dias)

    if aparelho:
        leituras = db.leituras_periodo(aparelho, inicio, fim)
    else:
        leituras = db.leituras_periodo_todos(inicio, fim)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["timestamp", "aparelho", "dispositivo_id", "corrente_A", "tensao_V", "potencia_W",
                     "temperatura_C", "status", "origem"])
    for l in leituras:
        writer.writerow([
            l["timestamp"], l["aparelho"], l.get("dispositivo_id") or "",
            l["corrente"], l["tensao"] if l["tensao"] is not None else "",
            l["potencia"] if l["potencia"] is not None else "",
            l.get("temperatura") if l.get("temperatura") is not None else "",
            l["status"], l.get("origem") or "",
        ])

    nome_arquivo = f"voltguard_leituras_{(aparelho or 'todos').replace(' ', '_')}_{fim.strftime('%Y%m%d_%H%M%S')}.csv"
    conteudo = "\ufeff" + buffer.getvalue()  # BOM para o Excel reconhecer UTF-8 (acentos)

    resposta = Response(conteudo, mimetype="text/csv")
    resposta.headers["Content-Disposition"] = f"attachment; filename={nome_arquivo}"
    return resposta


# ---------------------------------------------------------------------------
# Relatório técnico (PDF)
# ---------------------------------------------------------------------------

@app.route("/relatorio")
def gerar_relatorio():
    aparelho = request.args.get("aparelho")
    if not aparelho:
        return jsonify({"erro": "Informe o parâmetro 'aparelho'"}), 400

    dias = int(request.args.get("dias", 1))
    fim = datetime.now()
    inicio = fim - timedelta(days=dias)

    leituras = db.leituras_periodo(aparelho, inicio, fim)
    referencia = db.obter_referencia(aparelho)

    pasta_relatorios = config.RELATORIOS_DIR
    os.makedirs(pasta_relatorios, exist_ok=True)
    nome_arquivo = f"relatorio_voltguard_{aparelho.replace(' ', '_')}_{fim.strftime('%Y%m%d_%H%M%S')}.pdf"
    caminho_saida = os.path.join(pasta_relatorios, nome_arquivo)

    report_generator.gerar_relatorio_pdf(aparelho, referencia, leituras, inicio, fim, caminho_saida)

    return send_file(caminho_saida, as_attachment=True, download_name=nome_arquivo)


if __name__ == "__main__":
    print("=" * 60)
    print(f" VoltGuard rodando em: http://localhost:{config.PORTA}")
    print(" Endpoint para o ESP32 enviar dados: POST /api/leitura")
    if config.MQTT_ATIVO:
        print(f" MQTT: {config.MQTT_BROKER}:{config.MQTT_PORTA}  tópico {config.MQTT_TOPICO_SENSORES}")
    else:
        print(" MQTT: desligado (defina MQTT_BROKER para ativar)")
    print("=" * 60)
    # use_reloader=False quando iniciado pelo iniciar.py (evita processo duplicado)
    app.run(debug=True, host="0.0.0.0", port=config.PORTA,
            use_reloader=os.environ.get("VOLTGUARD_NO_RELOAD") != "1")
