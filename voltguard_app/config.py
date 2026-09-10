# -*- coding: utf-8 -*-
"""
config.py
---------
Configurações centrais do VoltGuard.

Quase tudo pode ser sobrescrito por VARIÁVEL DE AMBIENTE — é assim que o
mesmo código roda no PyCharm (valores padrão) e na nuvem (Render/Railway),
sem editar arquivo nenhum. Ex.: MQTT_BROKER=localhost python app.py

Os limites de tensão, tarifa, bandeira e meta diária NÃO ficam mais aqui:
são configurados pelo usuário no próprio app (tela "Configurações") e
gravados no banco. Os valores abaixo são só o ponto de partida.
"""

import os

# ---------------------------------------------------------------------------
# Banco de dados e pastas
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Na nuvem, aponte VOLTGUARD_DB_DIR para um disco persistente (ex.: /var/data)
DATA_DIR = os.environ.get("VOLTGUARD_DB_DIR", BASE_DIR)
DATABASE_PATH = os.path.join(DATA_DIR, "voltguard.db")
RELATORIOS_DIR = os.path.join(DATA_DIR, "relatorios")

# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
PORTA = int(os.environ.get("PORT", 5000))
# Chave opcional para proteger o endpoint de leituras quando o app estiver na
# internet. Se definida, o ESP32/simulador precisa mandar o header
# X-Api-Key com esse valor (ou ?api_key= na URL). Vazia = aberto.
API_KEY = os.environ.get("VOLTGUARD_API_KEY", "")

# ---------------------------------------------------------------------------
# MQTT (Mosquitto local ou broker público)
# ---------------------------------------------------------------------------
# "localhost"        -> Mosquitto instalado no PC do laboratório
# "broker.hivemq.com"-> broker público gratuito (funciona na nuvem e na escola)
# ""                 -> desliga o MQTT (só HTTP)
MQTT_BROKER = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORTA = int(os.environ.get("MQTT_PORT", 1883))
# Prefixo único dos tópicos — em broker público, isso evita misturar com
# mensagens de outras pessoas. Troque o sufixo por algo só do grupo.
MQTT_PREFIXO = os.environ.get("MQTT_TOPIC_PREFIX", "voltguard/shekinah-2026")
MQTT_TOPICO_SENSORES = f"{MQTT_PREFIXO}/sensores"      # ESP32 -> app
MQTT_TOPICO_COMANDO = f"{MQTT_PREFIXO}/comando"        # app -> ESP32 (relé)
MQTT_ATIVO = bool(MQTT_BROKER)

# ---------------------------------------------------------------------------
# Cliente / local monitorado (texto exibido no painel)
# ---------------------------------------------------------------------------
NOME_LOCAL_PADRAO = os.environ.get("VOLTGUARD_LOCAL", "Panificadora e Confeitaria Shekinah")

# ---------------------------------------------------------------------------
# Aparelhos padrão (usados quando um aparelho novo manda dados sem cadastro)
# corrente de referência em A, potência estimada em W
# ---------------------------------------------------------------------------
APARELHOS_REFERENCIA_PADRAO = {
    "Forno elétrico": 8.0,
    "Geladeira": 2.0,
    "Batedeira industrial": 4.0,
    "Freezer": 2.5,
}
APARELHOS_POTENCIA_PADRAO = {
    "Forno elétrico": 1800.0,
    "Geladeira": 250.0,
    "Batedeira industrial": 900.0,
    "Freezer": 350.0,
}

# ---------------------------------------------------------------------------
# Classificação por corrente (comparada com a referência do aparelho)
# ---------------------------------------------------------------------------
FATOR_ATENCAO = 1.0      # acima da referência já entra em "ATENÇÃO"
FATOR_ANORMAL = 1.20     # 20% acima da referência é "ANORMAL"
FATOR_CURTO_CIRCUITO = 2.0   # 2x a referência = pico tratado como curto/sobrecarga grave

# ---------------------------------------------------------------------------
# Valores INICIAIS das configurações do usuário (gravados no banco na 1ª vez)
# Rede da padaria é 220 V; os limites seguem o que foi definido no projeto.
# ---------------------------------------------------------------------------
CONFIG_INICIAL = {
    "nome_local": NOME_LOCAL_PADRAO,
    "tensao_nominal": 220.0,
    "tensao_minima": 200.0,          # abaixo disso: SUBTENSÃO -> relé desliga
    "tensao_maxima": 240.0,          # acima disso: SOBRETENSÃO -> relé desliga
    "tarifa_kwh": 0.95,              # R$/kWh (Amapá ~ 0,90-1,00 em 2026; ajustar na tela)
    "bandeira": "verde",             # verde | amarela | vermelha1 | vermelha2
    "consumo_max_diario_kwh": 30.0,  # meta diária; passou -> alerta
    "temperatura_maxima": 45.0,      # °C no quadro elétrico (DHT22) -> alerta
    "protecao_automatica": 1,        # 1 = relé desliga sozinho ao detectar risco
    "religar_automatico": 1,         # 1 = religa quando a tensão normaliza
    "leituras_para_religar": 5,      # nº de leituras normais seguidas para religar
}

# Adicional das bandeiras tarifárias (R$ por kWh) — valores ANEEL de referência
BANDEIRAS = {
    "verde": 0.0,
    "amarela": 0.01885,
    "vermelha1": 0.04463,
    "vermelha2": 0.07877,
}

# Harmônicas / DHT: o ACS712 mede só o RMS, então usamos a variação recente
# da corrente como indicador aproximado (ver README).
DHT_VARIACAO_ATENCAO = 0.35
TIMEOUT_SEM_DADOS_SEGUNDOS = 30
