# VoltGuard — Link único para os usuários (deploy)

O objetivo: **uma URL só** (ex.: `https://voltguard-shekinah.onrender.com`) que o
dono da padaria, o professor e a banca abrem no celular ou no PC, de qualquer
lugar, e veem o painel funcionando — com o ESP32 (ou o simulador) mandando dados
para essa mesma URL.

Há duas formas. Use a **Opção A** como principal e a **Opção B** como reserva
para o dia da apresentação.

---

## Opção A — Nuvem com URL fixa (Render, plano gratuito)

O app sobe 24 h por dia num servidor do Render. Não depende do PC do laboratório.

### A.1 Colocar o projeto no GitHub (uma vez)

1. Crie uma conta em https://github.com (um integrante do grupo).
2. **New repository** → nome `voltguard` → Public → Create.
3. Suba a pasta `voltguard_app`:
   - **Sem instalar nada**: na página do repositório, *Add file › Upload files*,
     arraste todos os arquivos e pastas de `voltguard_app` (menos `.venv`,
     `voltguard.db`, `relatorios/`) → *Commit changes*.
   - **Ou pelo GitHub Desktop / PyCharm** (*Git › Share project on GitHub*).

   > O `.gitignore` já impede que o banco local e o venv sejam enviados.

### A.2 Criar o serviço no Render (uma vez)

1. Crie uma conta em https://render.com (pode entrar com a conta do GitHub).
2. **New + › Blueprint** → conecte o repositório `voltguard` → o Render lê o
   arquivo `render.yaml` que já está na pasta → **Apply**.
3. Aguarde o build (2–4 min). Quando aparecer *Live*, o link é:

   **`https://voltguard-shekinah.onrender.com`**

   (o nome vem de `render.yaml`; se já estiver em uso, o Render acrescenta um
   sufixo — copie o link que aparecer no topo do painel do Render).

4. Abra o link → o painel carrega, ainda sem dados.

### A.3 Mandar dados para a nuvem

**Simulador (para testar agora):** no PyCharm, configuração
**`2d - Simulador -> app na nuvem`** (ou no terminal):

```bash
python esp32_simulator.py --url https://voltguard-shekinah.onrender.com --instabilidade alta
```

Em segundos o painel da nuvem começa a mostrar leituras, quedas de tensão e o
relé desligando/religando.

**ESP32 real:** abra o link → **⚙ Configurações › Conexão do ESP32** → copie a
URL/endpoint e os tópicos MQTT para o firmware:

- `esp32_firmware_http/` → `SERVER_URL = "https://voltguard-shekinah.onrender.com/api/leitura"`
- `esp32_firmware_mqtt/` → `MQTT_BROKER = "broker.hivemq.com"` e os tópicos
  `voltguard/shekinah-2026/...` (o app na nuvem já está assinando esse broker).

### A.4 Limitações do plano gratuito (e como contornar)

| Limitação | O que acontece | Solução |
|---|---|---|
| "Dorme" após 15 min sem acesso | 1º acesso demora ~30 s para acordar; o ESP32 continua enviando e o app acorda sozinho | Abrir o link 1 min antes da apresentação; ou usar um monitor gratuito (ex.: UptimeRobot) chamando `/health` a cada 10 min |
| Disco não persistente | o `voltguard.db` é apagado a cada novo deploy/reinício | Para a demonstração isso não atrapalha (o simulador repovoa em segundos). Para guardar histórico de meses: plano *Starter* + descomentar o bloco `disk` no `render.yaml` |
| Endpoint aberto na internet | qualquer um que descubra a URL poderia enviar leituras falsas | Defina `VOLTGUARD_API_KEY` no painel do Render (Environment) e o mesmo valor em `API_KEY` no firmware / `--api-key` no simulador |

**Atualizar o app** depois de mudar código: basta enviar os arquivos novos para o
GitHub — o Render refaz o deploy sozinho.

### Alternativas equivalentes
- **Railway** (railway.app): *New Project › Deploy from GitHub repo* — ele detecta o
  `Dockerfile`/`Procfile`. Coloque as mesmas variáveis de ambiente do `render.yaml`.
- **Fly.io / Google Cloud Run**: usam o `Dockerfile`.

---

## Opção B — Link temporário a partir do PC do laboratório (túnel)

Não precisa de conta nem de GitHub. O app continua rodando no PyCharm e o
Cloudflare cria um link público que aponta para o seu PC.

1. Deixe o VoltGuard rodando (`VoltGuard - Tudo (iniciar.py)`).
2. Dê dois cliques em **`link_publico.bat`** (na primeira vez ele baixa o
   `cloudflared.exe`, ~30 MB).
3. Na janela que abrir, procure a linha:
   `https://algum-nome-aleatorio.trycloudflare.com` ← **esse é o link**.
4. Compartilhe. Vale enquanto a janela e o app estiverem abertos; o link muda a
   cada vez que você abre o .bat.

Para o ESP32 mandar dados por esse link, use a mesma URL + `/api/leitura` no
firmware HTTP (ou continue com o IP local `http://10.101.29.99:5000/api/leitura`
se o ESP32 estiver na mesma rede Wi-Fi do PC — os dois funcionam ao mesmo tempo).

> Se a rede da escola bloquear o túnel, use o 4G do celular como hotspot para o PC.

---

## Opção C — Só a rede da escola (sem internet)

`http://<IP-do-PC>:5000` — o IP aparece no console ao iniciar (`Running on
http://10.101.29.99:5000`). Funciona para qualquer celular/PC no mesmo Wi-Fi.
É a mesma URL que o ESP32 usa quando está no laboratório.

---

## Resumo do que fica em cada lugar

```
ESP32 (padaria / laboratório)
   │  HTTP POST /api/leitura   ou   MQTT broker.hivemq.com
   ▼
app.py na nuvem  ──►  https://voltguard-shekinah.onrender.com   ◄── celular do dono / banca
   │  resposta {"rele": "desligado"}  ou  MQTT <prefixo>/comando
   ▼
ESP32 abre o relé → equipamento protegido
```

O `flet_app.py` continua existindo como cliente local (janela no PC ou futuro
.apk) e usa exatamente a mesma API: `BASE_URL` no início do arquivo pode apontar
para a URL da nuvem.
