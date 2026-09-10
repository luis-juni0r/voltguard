# -*- coding: utf-8 -*-
"""
mqtt_bridge.py
--------------
Ponte MQTT do VoltGuard (o "mqtt_listener.py" do guia, integrado ao app).

- Assina  <prefixo>/sensores : o ESP32 publica JSON {"aparelho": ..., "tensao": ..., "corrente": ...}
- Publica <prefixo>/comando  : o app manda {"aparelho": ..., "comando": "ligar"|"desligar"}
  (também publica em <prefixo>/comando/<aparelho> só com "ligar"/"desligar",
   para o firmware mais simples)

Roda numa thread em segundo plano dentro do próprio app.py — não precisa de
um segundo processo. Se o broker cair, reconecta sozinho.
"""

import json
import logging
import threading
import re

import config

log = logging.getLogger("voltguard.mqtt")

_cliente = None
_handler = None          # função(dados: dict, origem: str) -> dict
_conectado = False


def slug(texto: str) -> str:
    """'Forno elétrico' -> 'forno-eletrico' (nome de tópico seguro)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def estado() -> dict:
    return {
        "ativo": config.MQTT_ATIVO,
        "conectado": _conectado,
        "broker": config.MQTT_BROKER,
        "porta": config.MQTT_PORTA,
        "topico_sensores": config.MQTT_TOPICO_SENSORES,
        "topico_comando": config.MQTT_TOPICO_COMANDO,
    }


def publicar_comando(aparelho: str, comando: str, motivo: str = ""):
    """Envia o comando do relé para o ESP32 (se o MQTT estiver ativo/conectado)."""
    if not (_cliente and _conectado):
        return False
    payload = json.dumps({"aparelho": aparelho, "comando": comando, "motivo": motivo}, ensure_ascii=False)
    _cliente.publish(config.MQTT_TOPICO_COMANDO, payload, qos=1, retain=False)
    _cliente.publish(f"{config.MQTT_TOPICO_COMANDO}/{slug(aparelho)}", comando, qos=1, retain=True)
    log.info("MQTT -> %s: %s", aparelho, comando)
    return True


def _on_connect(client, userdata, flags, reason_code, properties=None):
    global _conectado
    _conectado = (str(reason_code) in ("0", "Success"))
    if _conectado:
        client.subscribe(config.MQTT_TOPICO_SENSORES, qos=1)
        log.info("MQTT conectado em %s:%s — escutando %s",
                 config.MQTT_BROKER, config.MQTT_PORTA, config.MQTT_TOPICO_SENSORES)
    else:
        log.warning("MQTT recusou a conexão: %s", reason_code)


def _on_disconnect(client, userdata, flags, reason_code, properties=None):
    global _conectado
    _conectado = False
    log.warning("MQTT desconectado (%s) — tentando reconectar...", reason_code)


def _on_message(client, userdata, msg):
    try:
        dados = json.loads(msg.payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as erro:
        log.warning("MQTT: mensagem inválida ignorada (%s)", erro)
        return
    if _handler:
        try:
            resultado = _handler(dados, origem="mqtt")
            log.info("MQTT <- %s: %s", dados.get("aparelho"), resultado.get("status"))
        except Exception as erro:  # noqa: BLE001 — não derruba a thread por uma leitura ruim
            log.exception("Erro ao processar leitura MQTT: %s", erro)


def iniciar(handler):
    """Inicia a thread MQTT. `handler(dados, origem)` processa cada leitura recebida."""
    global _cliente, _handler
    if not config.MQTT_ATIVO or _cliente is not None:
        return
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log.warning("paho-mqtt não instalado — MQTT desligado (pip install paho-mqtt)")
        return

    _handler = handler
    _cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                           client_id=f"voltguard-app-{slug(config.MQTT_PREFIXO)}")
    _cliente.on_connect = _on_connect
    _cliente.on_disconnect = _on_disconnect
    _cliente.on_message = _on_message
    _cliente.reconnect_delay_set(min_delay=2, max_delay=30)

    def _rodar():
        try:
            _cliente.connect(config.MQTT_BROKER, config.MQTT_PORTA, keepalive=60)
        except OSError as erro:
            log.warning("MQTT: não foi possível conectar em %s:%s (%s). Vou continuar tentando.",
                        config.MQTT_BROKER, config.MQTT_PORTA, erro)
        _cliente.loop_forever(retry_first_connection=True)

    threading.Thread(target=_rodar, name="voltguard-mqtt", daemon=True).start()
