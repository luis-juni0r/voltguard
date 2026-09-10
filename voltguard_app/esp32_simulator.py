# -*- coding: utf-8 -*-
"""
esp32_simulator.py
-------------------
Simula os ESP32 da Panificadora Shekinah enviando leituras para o VoltGuard,
exatamente como o hardware real (ACS712 + ZMPT101B + DHT22 + relé) vai fazer.

O simulador também "obedece" ao relé: quando o app manda desligar um aparelho,
ele passa a enviar corrente ~0 para aquele aparelho até ser religado — assim dá
para demonstrar a proteção funcionando de ponta a ponta sem hardware.

Como usar:
    python esp32_simulator.py                         # HTTP para http://localhost:5000
    python esp32_simulator.py --url https://SEU-APP.onrender.com   # app na nuvem
    python esp32_simulator.py --mqtt                  # envia por MQTT (broker do config.py)
    python esp32_simulator.py --instabilidade alta    # rede caindo toda hora (demonstração)
    python esp32_simulator.py --aparelho "Forno elétrico" --anomalia
"""

import argparse
import json
import random
import time
from datetime import datetime

import requests

import config

# Corrente "normal" (A) de cada aparelho. Rede 220 V.
PERFIS = {
    "Forno elétrico":        {"corrente_base": 7.6, "dispositivo_id": "VG001"},
    "Geladeira":             {"corrente_base": 1.7, "dispositivo_id": "VG002"},
    "Batedeira industrial":  {"corrente_base": 3.9, "dispositivo_id": "VG003"},
    "Freezer":               {"corrente_base": 2.3, "dispositivo_id": "VG004"},
}
TENSAO_BASE = 220.0

# Probabilidade de um evento de instabilidade (queda/pico de tensão) por ciclo
INSTABILIDADE = {"baixa": 0.02, "media": 0.08, "alta": 0.25}

estado_rele = {}          # aparelho -> "ligado"/"desligado" (o que o app mandou)
tensao_rede = TENSAO_BASE
temperatura_quadro = 31.0
evento_restante = 0       # ciclos que a instabilidade ainda dura


def simular_rede(nivel: str):
    """Tensão da rede compartilhada por todos os aparelhos (é a mesma padaria)."""
    global tensao_rede, temperatura_quadro, evento_restante
    if evento_restante > 0:
        evento_restante -= 1
        tensao_rede += random.uniform(-2, 2)
    else:
        if random.random() < INSTABILIDADE[nivel]:
            evento_restante = random.randint(2, 4)
            # 70% das vezes é queda (o problema real da padaria), 30% pico
            tensao_rede = random.uniform(172, 198) if random.random() < 0.7 else random.uniform(242, 256)
        else:
            tensao_rede = TENSAO_BASE + random.uniform(-4, 4)
    # quadro esquenta quando a rede está instável
    alvo = 31.0 + (8 if evento_restante else 0) + random.uniform(-0.5, 0.5)
    temperatura_quadro += (alvo - temperatura_quadro) * 0.3


def gerar_leitura(aparelho: str, forcar_anomalia: bool = False) -> dict:
    perfil = PERFIS.get(aparelho, {"corrente_base": 3.0, "dispositivo_id": "VGXXX"})

    if estado_rele.get(aparelho) == "desligado":
        corrente = random.uniform(0.0, 0.05)     # relé abriu: aparelho sem energia
    else:
        corrente = perfil["corrente_base"] + random.uniform(-0.15, 0.15)
        if forcar_anomalia or random.random() < 0.05:
            corrente *= random.uniform(1.3, 1.8)  # pico de consumo -> ATENÇÃO/ANORMAL

    return {
        "dispositivo_id": perfil["dispositivo_id"],
        "aparelho": aparelho,
        "corrente": round(corrente, 2),
        "tensao": round(tensao_rede, 1),
        "temperatura": round(temperatura_quadro, 1),
        "origem": "simulador",
    }


def enviar_http(sessao, url, leitura, api_key):
    headers = {"X-Api-Key": api_key} if api_key else {}
    resp = sessao.post(url, json=leitura, timeout=8, headers=headers)
    dados = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code == 201 and dados.get("rele"):
        estado_rele[leitura["aparelho"]] = dados["rele"]
    return resp.status_code, dados


def main():
    parser = argparse.ArgumentParser(description="Simulador de ESP32 para o VoltGuard")
    parser.add_argument("--url", default=f"http://localhost:{config.PORTA}",
                        help="URL base do app (ex.: https://voltguard.onrender.com)")
    parser.add_argument("--api-key", default=config.API_KEY, help="X-Api-Key, se o app exigir")
    parser.add_argument("--mqtt", action="store_true", help="publica por MQTT em vez de HTTP")
    parser.add_argument("--aparelho", help="simula apenas um aparelho (padrão: todos)")
    parser.add_argument("--anomalia", action="store_true", help="força corrente anormal sempre")
    parser.add_argument("--instabilidade", choices=INSTABILIDADE.keys(), default="media",
                        help="frequência das quedas/picos de tensão")
    parser.add_argument("--intervalo", type=float, default=3.0, help="segundos entre envios")
    opcoes = parser.parse_args()

    aparelhos = [opcoes.aparelho] if opcoes.aparelho else list(PERFIS.keys())
    url = opcoes.url.rstrip("/")
    if not url.endswith("/api/leitura"):
        url += "/api/leitura"

    print("VoltGuard - Simulador de ESP32 (Panificadora Shekinah, rede 220 V)")
    print(f"Modo: {'MQTT -> ' + config.MQTT_BROKER + ' ' + config.MQTT_TOPICO_SENSORES if opcoes.mqtt else 'HTTP -> ' + url}")
    print(f"Aparelhos: {', '.join(aparelhos)} | instabilidade: {opcoes.instabilidade}")
    print("Pressione Ctrl+C para parar.\n")

    cliente_mqtt = None
    if opcoes.mqtt:
        import paho.mqtt.client as mqtt
        cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="voltguard-simulador")

        def on_msg(_c, _u, msg):   # escuta os comandos de relé como o ESP32 faria
            try:
                cmd = json.loads(msg.payload.decode())
                estado_rele[cmd["aparelho"]] = "desligado" if cmd["comando"] == "desligar" else "ligado"
                print(f"   <- comando MQTT: {cmd['aparelho']} = {cmd['comando']} ({cmd.get('motivo', '')})")
            except (ValueError, KeyError):
                pass
        cliente_mqtt.on_message = on_msg
        cliente_mqtt.connect(config.MQTT_BROKER, config.MQTT_PORTA, 60)
        cliente_mqtt.subscribe(config.MQTT_TOPICO_COMANDO)
        cliente_mqtt.loop_start()

    sessao = requests.Session()
    try:
        while True:
            simular_rede(opcoes.instabilidade)
            for aparelho in aparelhos:
                leitura = gerar_leitura(aparelho, opcoes.anomalia)
                hora = datetime.now().strftime("%H:%M:%S")
                try:
                    if cliente_mqtt:
                        cliente_mqtt.publish(config.MQTT_TOPICO_SENSORES, json.dumps(leitura, ensure_ascii=False), qos=1)
                        info = f"MQTT ok  rele={estado_rele.get(aparelho, 'ligado')}"
                    else:
                        codigo, resposta = enviar_http(sessao, url, leitura, opcoes.api_key)
                        if codigo == 201:
                            extra = f" alertas={','.join(resposta['alertas'])}" if resposta.get("alertas") else ""
                            info = f"status={resposta['status']} rele={resposta.get('rele')}{extra}"
                        else:
                            info = f"HTTP {codigo}: {resposta.get('erro', '')}"
                    print(f"[{hora}] {aparelho:<22} {leitura['corrente']:>5.2f} A  {leitura['tensao']:>5.1f} V  "
                          f"{leitura['temperatura']:>4.1f} °C  ->  {info}")
                except requests.exceptions.ConnectionError:
                    print(f"[{hora}] Não foi possível conectar em {url}. O app.py está rodando?")
                    break
            time.sleep(opcoes.intervalo)
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")
    finally:
        if cliente_mqtt:
            cliente_mqtt.loop_stop()


if __name__ == "__main__":
    main()
