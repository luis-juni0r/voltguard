# VoltGuard — Sistema IoT de Monitoramento e Proteção de Energia

**Cliente:** Panificadora e Confeitaria Shekinah · **Problema:** rede 220 V instável
(quedas/picos de tensão) danificando equipamentos · **Solução:** ESP32 + sensores
(ACS712 corrente, ZMPT101B tensão, DHT22 temperatura) + **relé de proteção**
+ painel web em tempo real com histórico, custo, alertas e relatórios.

```
ACS712 / ZMPT101B / DHT22 → ESP32 → Wi-Fi ─┬─ HTTP POST ──┐
                                           └─ MQTT ───────┤
                                                          ▼
                              app.py (Flask + ponte MQTT) → SQLite
                                     │                        ▲
                       link único ◄──┤  API REST (JSON)       │ comando do relé
                  (nuvem / rede)     └──────────────► flet_app.py (opcional)
```

**Link único para os usuários:** veja **[DEPLOY.md](DEPLOY.md)** (nuvem com URL
fixa ou túnel a partir do PC).

## O que o app faz (funcionalidades do projeto)

| Bloco | Funcionalidade |
|---|---|
| Monitoramento | tensão, corrente, potência, kWh, temperatura do quadro — ao vivo e histórico (hoje/ontem, 24 h, 30 dias) |
| Proteção | limites de tensão mín/máx configuráveis; fora da faixa (ou curto/sobrecarga, ou temperatura alta) → alerta + **relé desliga o aparelho**; religamento automático quando normaliza; comando manual ligar/desligar no painel |
| Comunicação | ESP32 envia por **HTTP** (`/api/leitura`) ou **MQTT** (`<prefixo>/sensores`); o app devolve o estado do relé na resposta HTTP e publica em `<prefixo>/comando` |
| Cadastro (usuário) | aparelhos com corrente de referência, potência estimada, horário de funcionamento e se possui relé |
| Configurações (usuário) | tarifa R$/kWh, bandeira tarifária, meta diária de kWh, limites de tensão/temperatura, proteção automática |
| Custo | custo de hoje por aparelho e total, tarifa efetiva (tarifa + bandeira), barra da meta diária |
| Dicas | dicas de economia/segurança geradas por regras (aparelho fora do horário, acima da potência cadastrada, rede instável, bandeira ativa…) |
| Entrada manual | leitura digitada do multímetro (backup/teste/calibração) |
| Observações | anotações livres com data ("técnico trocou o transformador") para cruzar com os gráficos |
| Relatórios | PDF técnico do aparelho e exportação CSV (abre no Excel) |

## ⚡ Início rápido no PyCharm (3 passos)

1. **Abrir**: descompacte o `.zip` e, no PyCharm, `File > Open...` → selecione a
   pasta `voltguard_app` → **Trust Project**.
2. **Interpretador**: o PyCharm vai mostrar um aviso de "No Python interpreter
   configured" / sugerir criar um ambiente virtual a partir do
   `requirements.txt` — aceite (**Create**). Se não sugerir:
   `Settings > Project: voltguard_app > Python Interpreter > Add Interpreter >
   Add Local Interpreter > Venv > OK` e depois, no **Terminal** do PyCharm:
   ```bash
   pip install -r requirements.txt
   ```
3. **Rodar**: no canto superior direito, escolha a configuração
   **`VoltGuard - Tudo (iniciar.py)`** e clique em ▶ (Run).
   Isso sobe o backend, o simulador do ESP32 e a interface Flet, que abre
   sozinha no navegador em `http://localhost:8550`.
   Para parar tudo: botão ■ (Stop).

As configurações já vêm prontas no menu de Run (pasta `.idea/runConfigurations`):

| Configuração | O que faz |
|---|---|
| `VoltGuard - Tudo (iniciar.py)` | Backend + simulador + Flet, em uma única aba, na ordem certa |
| `VoltGuard - Tudo sem simulador (ESP32 real)` | Backend + Flet — use quando o ESP32 de verdade já estiver enviando dados |
| `VoltGuard - 3 processos em abas separadas` | Os mesmos 3 processos, cada um em sua aba de Run (bom para ver o log de cada um) |
| `1 - Backend Flask (app.py)` | Só o backend (`http://localhost:5000`) |
| `2 - Simulador ESP32` / `2b - ... (anomalia)` | Só o simulador HTTP (o 2b força leituras ANORMAIS no Forno elétrico) |
| `2c - Simulador ESP32 (MQTT)` | Simulador publicando por MQTT no broker do `config.py` |
| `2d - Simulador -> app na nuvem` | Simulador enviando para a URL pública (edite a URL nos parâmetros) |
| `3 - Interface Flet (flet_app.py)` | Só a interface (precisa do backend rodando) |

Fora do PyCharm (Windows): dê dois cliques em **`iniciar_windows.bat`** — ele
cria o `.venv`, instala as dependências e chama o `iniciar.py`.

Opções do lançador direto no terminal:
```bash
python iniciar.py                   # tudo
python iniciar.py --sem-simulador   # ESP32 real
python iniciar.py --sem-flet        # só backend (+simulador); use http://localhost:5000
python iniciar.py --anomalia        # simulador em modo demonstração de alerta
python esp32_simulator.py --instabilidade alta   # rede caindo toda hora (mostra o relé agindo)
```

### Variáveis de ambiente (opcionais — nuvem ou PyCharm › Run › Environment variables)

| Variável | Padrão | Para quê |
|---|---|---|
| `MQTT_BROKER` | `broker.hivemq.com` | `localhost` para o Mosquitto do PC; vazio desliga o MQTT |
| `MQTT_TOPIC_PREFIX` | `voltguard/shekinah-2026` | prefixo dos tópicos (troque para algo só do grupo) |
| `VOLTGUARD_API_KEY` | vazio | se definida, `/api/leitura` exige o header `X-Api-Key` |
| `VOLTGUARD_DB_DIR` | pasta do projeto | onde gravar `voltguard.db` (na nuvem: disco persistente) |
| `PORT` | `5000` | porta do servidor |

---

App em Python que recebe leituras de corrente/tensão enviadas por um
ESP32 (ACS712 + ZMPT101B), armazena o histórico, exibe um dashboard ao vivo
e gera relatórios técnicos automáticos em PDF.

```
Eletrodoméstico → ACS712/ZMPT101B → ESP32 → Wi-Fi (HTTP) → app.py (Flask) → SQLite
                                                                    |
                                                          API REST (JSON)
                                                                    |
                                                          flet_app.py (Flet)
                                                       janela / navegador / futuro .apk
```

## Duas partes, dois processos

- **`app.py` (Flask)** — o backend. Recebe os dados do ESP32, grava no
  banco SQLite, calcula os status (NORMAL/ATENÇÃO/ANORMAL) e gera o
  relatório em PDF. Continua funcionando sozinho como um dashboard web
  completo em `http://localhost:5000` (HTML/CSS/JS), caso prefiram usá-lo
  diretamente no navegador sem o Flet.
- **`flet_app.py` (Flet)** — a interface "de aplicativo" propriamente dita,
  escrita 100% em Python. Ela **não acessa o banco diretamente** — busca
  tudo pela API do Flask. Roda como uma janela/aba que abre sozinha, e no
  futuro pode virar um `.apk` real com `flet build apk` (fora do escopo
  deste projeto, mas é o caminho natural caso queiram distribuir num
  celular Android de verdade).

**Os dois processos precisam estar rodando ao mesmo tempo**: primeiro o
`app.py`, depois o `flet_app.py` (ou o simulador, se ainda não tiverem o
hardware pronto).

## Estrutura do projeto

```
voltguard_app/
├── app.py                     -> App Flask (API + dashboard web opcional)
├── flet_app.py                -> App Flet (a interface principal do projeto)
├── iniciar.py                 -> Lançador: sobe backend + simulador + Flet com um clique
├── iniciar_windows.bat        -> Mesmo lançador, para dois cliques fora do PyCharm
├── .idea/runConfigurations/   -> Configurações de Run prontas para o PyCharm
├── config.py                  -> Padrões e variáveis de ambiente (MQTT, porta, API key, banco)
├── database.py                -> SQLite: leituras, aparelhos, configuracoes, alertas, observacoes
├── logic.py                   -> Classificação, limites de tensão/temperatura, custo, dicas
├── servico.py                 -> Processa cada leitura e aplica a PROTEÇÃO (relé)
├── mqtt_bridge.py             -> Ponte MQTT (assina sensores, publica comandos) em thread
├── report_generator.py        -> Geração do relatório técnico em PDF
├── esp32_simulator.py         -> Simula os ESP32 (HTTP ou MQTT), com quedas de tensão e obedecendo o relé
├── requirements.txt
├── templates/                 -> painel web (o que o link único abre)
│   ├── dashboard.html, aparelhos.html, configuracoes.html
├── static/css, static/js      -> estilo e scripts do painel (Chart.js incluído)
├── DEPLOY.md                  -> Como gerar o LINK ÚNICO (nuvem / túnel)
├── render.yaml, Procfile, Dockerfile -> deploy na nuvem
├── link_publico.bat / .sh     -> link público temporário a partir do PC (Cloudflare Tunnel)
├── esp32_firmware_http/       -> firmware ESP32 via HTTP (relé pela resposta do servidor)
└── esp32_firmware_mqtt/       -> firmware ESP32 via MQTT (PubSubClient)
```

## Passo a passo no PyCharm

### 1. Abrir o projeto
`File > Open...` e selecione a pasta `voltguard_app`.

### 2. Criar o ambiente virtual (venv)
O PyCharm normalmente sugere isso automaticamente ao abrir o projeto. Se não:
`File > Settings > Project: voltguard_app > Python Interpreter > Add Interpreter > Add Local Interpreter > Venv`.

### 3. Instalar as dependências
Abra o terminal do PyCharm (aba **Terminal**, na parte de baixo) e rode:
```bash
pip install -r requirements.txt
```

### 4. Rodar o app
Abra `app.py`, clique com o botão direito no editor e escolha **Run 'app'**
(ou clique na seta verde ao lado de `if __name__ == "__main__":`).

Você deverá ver algo como:
```
VoltGuard rodando em: http://localhost:5000
Endpoint para o ESP32 enviar dados: POST /api/leitura
```

### 5. Alimentar o app com dados (sem hardware ainda)
Como a montagem do ESP32 ainda está em andamento, use o simulador para
testar o dashboard e o relatório agora mesmo. Em **outro terminal** do
PyCharm (ícone **+** na aba Terminal), com o `app.py` já rodando:

```bash
python esp32_simulator.py
```

Isso envia leituras simuladas de 4 aparelhos (Geladeira, Micro-ondas, Forno
elétrico, Máquina de lavar) a cada 3 segundos, incluindo picos ocasionais
para testar os status ATENÇÃO/ANORMAL e os alertas.

Para forçar sempre uma leitura anormal (bom para testar/gravar demonstração):
```bash
python esp32_simulator.py --aparelho "Forno elétrico" --anomalia
```

### 6. Abrir a interface do VoltGuard

Vocês têm duas opções (podem usar as duas, se quiserem):

**Opção A — App em Flet (recomendada, é o "aplicativo" pedido no trabalho)**

Em um **terceiro terminal** do PyCharm, com o `app.py` (e o simulador, se
estiver usando) já rodando:
```bash
python flet_app.py
```
Isso abre uma janela/aba própria em `http://localhost:8550` com a interface
completa: gauges de tensão/corrente, gráficos, alertas, histórico de
ocorrências e o cadastro de aparelhos (botão **"⚙ Aparelhos"** no topo).

**Opção B — Dashboard web do próprio Flask**

Abra o navegador em `http://localhost:5000`. É a versão HTML/CSS/JS do
mesmo dashboard, útil se quiserem comparar as duas interfaces ou se algum
computador tiver dificuldade para rodar o Flet.

Nas duas opções, o painel tem um seletor de **"Aparelho"** para trocar
entre os aparelhos que já enviaram dados.

Quando uma leitura chega em **ATENÇÃO** ou **ANORMAL**, o dashboard mostra:
- um **banner de alerta** no topo do medidor (amarelo para ATENÇÃO, vermelho
  para ANORMAL) — no dashboard web, também toca um **beep sonoro** curto na
  transição de NORMAL para um estado de alerta;
- o card **"Alertas e Histórico de Ocorrências"**, no final da página, com a
  lista das últimas ocorrências de todos os aparelhos (ou só do aparelho
  selecionado, marcando a caixa "somente ...").

### 7. Gerar o relatório técnico
Clique em **"Gerar relatório técnico (PDF)"** — abre/baixa o PDF
automaticamente com as estatísticas do aparelho selecionado (último dia por
padrão). O botão **"Exportar CSV"**, ao lado, baixa as leituras cruas dos
últimos 30 dias.

## Conectando o ESP32 de verdade (quando o hardware estiver pronto)

Abra no painel **⚙ Configurações › Conexão do ESP32**: lá estão a URL, o
endpoint, o broker e os tópicos exatos para copiar no firmware.

**Caminho 1 — HTTP (mais simples, funciona com a URL da nuvem):**
`esp32_firmware_http/esp32_firmware_http.ino` → preencha Wi-Fi e `SERVER_URL`.
O ESP32 faz POST a cada 3 s e lê na resposta `"rele": "ligado"|"desligado"`
para acionar o módulo relé.

**Caminho 2 — MQTT (como definido no projeto):**
`esp32_firmware_mqtt/esp32_firmware_mqtt.ino` → preencha Wi-Fi, `MQTT_BROKER`
(`broker.hivemq.com` ou o IP do PC com Mosquitto) e os tópicos. O ESP32
publica em `<prefixo>/sensores` e assina `<prefixo>/comando` (e
`<prefixo>/comando/<aparelho>` com "ligar"/"desligar").

Em ambos: ajuste `SENSIBILIDADE_ACS712` (5 A = 0,185; 20 A = 0,100; 30 A = 0,066)
e calibre `FATOR_ZMPT` comparando com o multímetro (digite a leitura do
multímetro em **Leitura manual** no painel para comparar lado a lado).
Grave, pare o simulador, e o app passa a receber os dados reais sem mudar nada.

### Como o relé é decidido
O ESP32 **não** decide sozinho: ele mede e envia; o `servico.py` compara com os
limites configurados pelo usuário e responde/publica o comando. Assim a regra
fica num lugar só (e o usuário muda os limites pela tela, sem regravar o ESP32).
Se a conexão cair, o firmware mantém o último estado.

### Mosquitto local x broker público
- **Mosquitto no PC** (`MQTT_BROKER=localhost` no app; IP do PC no ESP32): não
  depende de internet, ideal no laboratório.
- **broker.hivemq.com** (padrão): funciona com o app na nuvem e o ESP32 em qualquer
  lugar. É público: por isso o prefixo `voltguard/shekinah-2026` — troque por um
  nome só do grupo em `MQTT_TOPIC_PREFIX`.

## Configurando pelo painel (campos do usuário)

- **⚙ Configurações**: tensão mínima/máxima aceitável, temperatura máxima no
  quadro, proteção automática, religamento automático, tarifa (R$/kWh), bandeira
  tarifária, meta de consumo diário, nome do local.
- **⚙ Aparelhos**: nome, corrente de referência, potência estimada (W), horário
  de funcionamento, se possui relé.
- **Painel**: comando manual do relé, leitura manual (multímetro), observações.

## Ajustando as correntes de referência

A forma mais prática é pela própria tela do app: clique em **"⚙ Aparelhos"**
no topo do dashboard (ou acesse `http://localhost:5000/aparelhos-config`).
Lá dá para cadastrar um aparelho novo, editar a corrente de referência de um
já existente ou remover um cadastro (o histórico de leituras não é apagado).
A tabela já mostra, para cada aparelho, a partir de qual corrente ele entra
em ATENÇÃO e em ANORMAL — útil para explicar a lógica na apresentação.

Também é possível editar diretamente `config.py` (valores usados apenas
quando um aparelho novo manda dados e ainda não tem cadastro):
```python
APARELHOS_REFERENCIA_PADRAO = {
    "Geladeira": 2.0,
    "Micro-ondas": 5.0,
    "Forno elétrico": 8.0,
    "Máquina de lavar": 4.0,
}
```
Ou ainda pela API:
```bash
curl -X POST http://localhost:5000/api/aparelhos \
     -H "Content-Type: application/json" \
     -d '{"nome": "Geladeira", "corrente_referencia": 2.2}'
```

A regra de classificação (ajustável em `config.py`):
- `corrente <= referência` → **NORMAL**
- `referência < corrente <= referência × 1,20` → **ATENÇÃO**
- `corrente > referência × 1,20` → **ANORMAL**

## Exportando os dados brutos (CSV)

No dashboard, o botão **"Exportar CSV"** (ao lado de "Gerar relatório técnico")
baixa as leituras cruas dos últimos 30 dias do aparelho selecionado — útil
para levar os dados para uma planilha, gráfico externo ou anexo do trabalho.
O arquivo já sai com separador `;` e acentuação correta para abrir direto no
Excel em português. Também dá para exportar de todos os aparelhos de uma vez:
```
http://localhost:5000/exportar?dias=30
```

## Próximos passos sugeridos para a equipe

- **Harmônicas / DHT real**: hoje o painel usa uma aproximação (variação da
  corrente) porque o ACS712 fornece apenas o valor RMS. Uma medição real de
  DHT exigiria amostrar a forma de onda (ADC rápido no ESP32) e aplicar FFT.
- **Caixa 3D / unidade móvel**: fora do escopo do app, mas o firmware de
  exemplo já reforça os cuidados de isolamento elétrico descritos no
  documento-base (seção 17).
- **Autenticação**: já existe `VOLTGUARD_API_KEY` (header `X-Api-Key`). Um
  próximo passo seria login de usuário no painel.
- **Notificações**: enviar os alertas por WhatsApp/Telegram/e-mail (a lista de
  alertas já está em `/api/alertas`).

## Segurança elétrica (importante)

Este projeto envolve medição de instalações de 127/220 V. A protoboard não
deve conduzir diretamente a rede elétrica, e o ESP32 não deve receber
tensões incompatíveis em suas entradas. Toda montagem que tenha contato com
a rede elétrica deve ter isolamento adequado, proteção mecânica e,
idealmente, supervisão de uma pessoa habilitada — como já destacado no
documento-base do projeto.

## Problemas comuns

- **"No Python interpreter configured" ao abrir**: é esperado na primeira vez —
  o venv é criado na máquina de cada um. Siga o passo 2 do Início rápido.
- **As configurações de Run aparecem com ícone de erro/vermelhas**: o
  interpretador ainda não foi definido (passo 2). Depois de criar o venv elas
  ficam válidas sozinhas.
- **`ModuleNotFoundError: No module named 'flet'`**: as dependências não foram
  instaladas no venv que o PyCharm está usando. Terminal do PyCharm →
  `pip install -r requirements.txt`.
- **O navegador não abre sozinho com o Flet**: acesse manualmente
  `http://localhost:8550`.
- **Porta 5000 em uso** (ex.: outro app.py esquecido aberto): o `iniciar.py`
  avisa e reaproveita o backend que já está rodando; se preferir, feche o
  processo antigo pelo Gerenciador de Tarefas.
- **"Porta 8550 já em uso" ao rodar `flet_app.py`**: feche qualquer outra
  janela/processo do Flet aberta antes, ou troque a porta na última linha
  do arquivo (`ft.run(main, ..., port=8550)`) para outro número, ex: 8551.
- **A janela do Flet abre em branco ou trava**: confira se o `app.py` está
  rodando em outro terminal — o `flet_app.py` depende 100% da API dele.
- **Dropdown ou lista de aparelhos vazia**: significa que nenhum dado
  chegou ainda. Rode `python esp32_simulator.py` para gerar dados de teste.
