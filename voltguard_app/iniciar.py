# -*- coding: utf-8 -*-
"""
iniciar.py
----------
Lançador de clique único do VoltGuard.

Sobe os três processos na ordem certa, usando o MESMO interpretador Python
do PyCharm (o venv do projeto):

    1. app.py               -> backend Flask (porta 5000)
    2. esp32_simulator.py   -> dados de teste (pule com --sem-simulador)
    3. flet_app.py          -> interface Flet (abre o navegador em :8550)

Como usar no PyCharm:
    - Clique com o botão direito neste arquivo > Run 'iniciar'
    - ou selecione a configuração "VoltGuard - Tudo (iniciar.py)" e aperte ▶

Para encerrar tudo de uma vez: botão ■ (Stop) do PyCharm ou Ctrl+C.

Opções:
    python iniciar.py                      # backend + simulador + Flet
    python iniciar.py --sem-simulador      # quando o ESP32 real já envia dados
    python iniciar.py --sem-flet           # só backend (+ simulador); use o
                                           # dashboard web em http://localhost:5000
"""

import os
import sys
import socket
import subprocess
import time
import argparse
import signal
import atexit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable  # garante o venv escolhido no PyCharm
PORTA_BACKEND = 5000
PORTA_FLET = 8550


def porta_aberta(porta, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, porta)) == 0


def esperar_porta(porta, timeout=30):
    inicio = time.time()
    while time.time() - inicio < timeout:
        if porta_aberta(porta):
            return True
        time.sleep(0.5)
    return False


def iniciar(script, *args, env=None):
    ambiente = dict(os.environ)
    ambiente["PYTHONUNBUFFERED"] = "1"   # mostra os prints na hora
    ambiente["PYTHONIOENCODING"] = "utf-8"
    if env:
        ambiente.update(env)
    return subprocess.Popen(
        [PYTHON, os.path.join(BASE_DIR, script), *args],
        cwd=BASE_DIR,
        env=ambiente,
    )


def encerrar(processos):
    for p in reversed(processos):
        if p.poll() is None:
            p.terminate()
    time.sleep(1.5)
    for p in processos:
        if p.poll() is None:
            p.kill()


def main():
    parser = argparse.ArgumentParser(description="Inicia todos os processos do VoltGuard")
    parser.add_argument("--sem-simulador", action="store_true",
                        help="não inicia o esp32_simulator.py (use com o ESP32 real)")
    parser.add_argument("--sem-flet", action="store_true",
                        help="não inicia a interface Flet (use o dashboard web em :5000)")
    parser.add_argument("--anomalia", action="store_true",
                        help="simulador força leituras ANORMAIS (para demonstração)")
    opcoes = parser.parse_args()

    if os.path.basename(PYTHON).lower().startswith("python") is False:
        print(f"[aviso] interpretador incomum: {PYTHON}")

    print("=" * 60)
    print(" VoltGuard — iniciando todos os processos")
    print(f" Python: {PYTHON}")
    print("=" * 60)

    processos = []

    # Garante que os filhos morrem junto (Stop do PyCharm, SIGTERM, fechar janela)
    atexit.register(lambda: encerrar(processos))

    def _sinal(_sig, _frame):
        raise KeyboardInterrupt

    for nome_sinal in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        if hasattr(signal, nome_sinal):
            try:
                signal.signal(getattr(signal, nome_sinal), _sinal)
            except (ValueError, OSError):
                pass

    try:
        # 1) Backend --------------------------------------------------------
        if porta_aberta(PORTA_BACKEND):
            print(f"[backend] porta {PORTA_BACKEND} já está em uso — assumindo que o "
                  "app.py já está rodando (feche-o se não for o caso).")
        else:
            print("[backend] iniciando app.py ...")
            processos.append(iniciar("app.py", env={"VOLTGUARD_NO_RELOAD": "1"}))
            if not esperar_porta(PORTA_BACKEND):
                print("[erro] o backend não respondeu na porta 5000 em 30 s. "
                      "Veja as mensagens acima.")
                encerrar(processos)
                sys.exit(1)
        print(f"[backend] OK -> http://localhost:{PORTA_BACKEND}")

        # 2) Simulador ------------------------------------------------------
        if not opcoes.sem_simulador:
            args = ["--anomalia"] if opcoes.anomalia else []
            print("[simulador] iniciando esp32_simulator.py ...")
            processos.append(iniciar("esp32_simulator.py", *args))
            time.sleep(2)  # dá tempo de chegar a primeira leitura
        else:
            print("[simulador] pulado (--sem-simulador)")

        # 3) Interface Flet -------------------------------------------------
        if not opcoes.sem_flet:
            if porta_aberta(PORTA_FLET):
                print(f"[flet] porta {PORTA_FLET} já em uso — feche a janela do Flet "
                      "anterior ou mude a porta no final do flet_app.py.")
            else:
                print("[flet] iniciando flet_app.py (o navegador abre sozinho) ...")
                processos.append(iniciar("flet_app.py"))
        else:
            print(f"[flet] pulado (--sem-flet). Dashboard web: http://localhost:{PORTA_BACKEND}")

        print("-" * 60)
        print(" Tudo no ar. Para encerrar: Stop (■) no PyCharm ou Ctrl+C.")
        print("-" * 60)

        # Fica vigiando: se algum processo cair, avisa
        while True:
            time.sleep(1)
            for p in processos:
                if p.poll() is not None:
                    nome = os.path.basename(p.args[1])
                    print(f"[aviso] {nome} encerrou (código {p.returncode}).")
                    processos.remove(p)
            if not processos:
                print("Nenhum processo restante. Saindo.")
                break

    except KeyboardInterrupt:
        print("\nEncerrando VoltGuard ...")
    finally:
        encerrar(processos)


if __name__ == "__main__":
    main()
