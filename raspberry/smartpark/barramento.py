"""
Comunicação entre o Raspberry Pi e o ESP32, por MQTT.

Tópicos que defini (o prefixo é configurável, o padrão é "smartpark"):
    ESP32 -> Pi
        smartpark/entrada/presenca     "1" quando o HC-SR04 detecta um veículo na cancela
        smartpark/vagas/<ID>           "OCUPADA" | "LIVRE"   (ex.: smartpark/vagas/A01)
        smartpark/esp32/status         "online" (mensagem de vida / last will "offline")
    Pi -> ESP32
        smartpark/cancela/cmd          "ABRIR"
        smartpark/guarita/painel       JSON {"placa","categoria","vaga","seta","msg"}
        smartpark/vagas/<ID>/reserva   "1" | "0"  (LED amarelo piscando na vaga reservada)

Fiz duas implementações com a mesma interface:
    BarramentoMemoria : tudo no mesmo processo (uso nos testes e na simulação)
    BarramentoMQTT    : broker real (Mosquitto no próprio Pi, ou público para o Wokwi)
"""
from __future__ import annotations

import fnmatch
from typing import Callable

Callback = Callable[[str, str], None]


class BarramentoMemoria:
    def __init__(self):
        self._subs: list[tuple[str, Callback]] = []
        self.historico: list[tuple[str, str]] = []

    def assinar(self, padrao: str, cb: Callback):
        self._subs.append((padrao, cb))

    def publicar(self, topico: str, payload: str, reter: bool = False):
        self.historico.append((topico, payload))
        for padrao, cb in list(self._subs):
            if _casa(padrao, topico):
                cb(topico, payload)


class BarramentoMQTT:
    def __init__(self, host="localhost", porta=1883, client_id="smartpark-pi", usuario=None, senha=None):
        import paho.mqtt.client as mqtt
        self._mqtt = mqtt
        self.cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if usuario:
            self.cli.username_pw_set(usuario, senha)
        self._subs: list[tuple[str, Callback]] = []
        self.cli.on_message = self._ao_receber
        self.cli.on_connect = self._ao_conectar
        self.cli.connect(host, porta, keepalive=30)
        self.cli.loop_start()

    def _ao_conectar(self, cli, userdata, flags, rc, props=None):
        for padrao, _ in self._subs:  # assino de novo depois de uma reconexão
            cli.subscribe(padrao)

    def _ao_receber(self, cli, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace")
        for padrao, cb in self._subs:
            if self._mqtt.topic_matches_sub(padrao, msg.topic):
                cb(msg.topic, payload)

    def assinar(self, padrao: str, cb: Callback):
        self._subs.append((padrao, cb))
        self.cli.subscribe(padrao)

    def publicar(self, topico: str, payload: str, reter: bool = False):
        self.cli.publish(topico, payload, qos=1, retain=reter)

    def fechar(self):
        self.cli.loop_stop()
        self.cli.disconnect()


def _casa(padrao: str, topico: str) -> bool:
    """Curingas MQTT: '+' = um nível, '#' = o resto."""
    p, t = padrao.split("/"), topico.split("/")
    for i, parte in enumerate(p):
        if parte == "#":
            return True
        if i >= len(t) or (parte != "+" and not fnmatch.fnmatchcase(t[i], parte)):
            return False
    return len(p) == len(t)
