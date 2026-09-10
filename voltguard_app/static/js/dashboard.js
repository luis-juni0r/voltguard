// ============================================================================
// dashboard.js — VoltGuard
// Busca dados da API Flask (app.py) periodicamente e atualiza o dashboard:
// gauges de tensão/corrente, gráfico de leituras, cards de 24h, gráfico de
// 30 dias, donut de standby e status das proteções.
// ============================================================================

const CORES = {
  teal: "#2dd4bf",
  tealDark: "#0d9488",
  amarelo: "#eab308",
  navy: "#334469",
  fundoGauge: "#1e2a45",
  verde: "#22c55e",
  vermelho: "#ef4444",
  azul: "#3b82f6",
};

let aparelhoAtual = null;
let periodoAtual = "hoje";
let chartLeituras = null;
let chart30Dias = null;
let ultimoStatusConhecido = {}; // aparelho -> status, para detectar transição p/ alerta sonoro
let somenteAparelhoSelecionado = false;

// ---------------------------------------------------------------------------
// Alerta sonoro (beep curto via Web Audio API) — toca só na TRANSIÇÃO de
// NORMAL para ATENCAO/ANORMAL, nunca a cada leitura, para não incomodar.
// ---------------------------------------------------------------------------
function tocarBeepAlerta(grave = false) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = grave ? 320 : 660;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
  } catch (e) {
    // navegador pode bloquear áudio sem interação prévia do usuário — ok ignorar
  }
}

// ---------------------------------------------------------------------------
// Relógio
// ---------------------------------------------------------------------------
function atualizarRelogio() {
  const agora = new Date();
  document.getElementById("clock").textContent = agora.toLocaleTimeString("pt-BR");
}
setInterval(atualizarRelogio, 1000);
atualizarRelogio();

// ---------------------------------------------------------------------------
// Gauge semicircular (canvas puro — sem depender do Chart.js para isso)
// ---------------------------------------------------------------------------
function desenharGauge(canvasId, valor, min, max, cor) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext("2d");
  const largura = canvas.width, altura = canvas.height;
  ctx.clearRect(0, 0, largura, altura);

  const cx = largura / 2, cy = altura - 15, raio = Math.min(largura, altura * 2) / 2 - 14;
  const fracao = Math.max(0, Math.min(1, (valor - min) / (max - min)));

  // Arco de fundo (trilho)
  ctx.beginPath();
  ctx.lineWidth = 14;
  ctx.lineCap = "round";
  ctx.strokeStyle = CORES.fundoGauge;
  ctx.arc(cx, cy, raio, Math.PI, 2 * Math.PI, false);
  ctx.stroke();

  // Arco de valor
  ctx.beginPath();
  ctx.lineWidth = 14;
  ctx.lineCap = "round";
  ctx.strokeStyle = cor;
  ctx.arc(cx, cy, raio, Math.PI, Math.PI + fracao * Math.PI, false);
  ctx.stroke();

  // Marcadores nas pontas
  ctx.fillStyle = "#3a4a6b";
  [Math.PI, 2 * Math.PI].forEach((ang) => {
    const x1 = cx + (raio - 10) * Math.cos(ang), y1 = cy + (raio - 10) * Math.sin(ang);
    ctx.beginPath();
    ctx.arc(x1, y1, 2.5, 0, 2 * Math.PI);
    ctx.fill();
  });
}

// ---------------------------------------------------------------------------
// Donut simples (para "Perda em Standby")
// ---------------------------------------------------------------------------
function desenharDonut(canvasId, pctAtivo) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext("2d");
  const largura = canvas.width, altura = canvas.height;
  ctx.clearRect(0, 0, largura, altura);

  const cx = largura / 2, cy = altura / 2, raio = Math.min(largura, altura) / 2 - 12;
  const fracaoAtivo = Math.max(0, Math.min(1, pctAtivo / 100));
  const inicio = -Math.PI / 2;

  ctx.lineWidth = 22;
  ctx.lineCap = "butt";

  ctx.beginPath();
  ctx.strokeStyle = CORES.navy;
  ctx.arc(cx, cy, raio, inicio, inicio + 2 * Math.PI, false);
  ctx.stroke();

  ctx.beginPath();
  ctx.strokeStyle = CORES.teal;
  ctx.arc(cx, cy, raio, inicio, inicio + fracaoAtivo * 2 * Math.PI, false);
  ctx.stroke();
}

// ---------------------------------------------------------------------------
// Formatação de horário para o eixo X do gráfico "Leituras"
// ---------------------------------------------------------------------------
function formatarHora(isoString) {
  const d = new Date(isoString);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

// ---------------------------------------------------------------------------
// Lista de aparelhos (dropdown)
// ---------------------------------------------------------------------------
async function carregarAparelhos() {
  const resp = await fetch("/api/aparelhos");
  const lista = await resp.json();
  const select = document.getElementById("aparelho-select");
  const selecaoAnterior = aparelhoAtual || select.value;

  select.innerHTML = "";
  if (lista.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "Aguardando dados do ESP32...";
    select.appendChild(opt);
    return;
  }

  const selManual = document.getElementById("manual-aparelho");
  const manualAnterior = selManual.value;
  selManual.innerHTML = "";
  lista.forEach((a) => {
    const om = document.createElement("option");
    om.value = a.nome; om.textContent = a.nome; selManual.appendChild(om);
  });
  if (manualAnterior) selManual.value = manualAnterior;

  lista.forEach((a) => {
    const opt = document.createElement("option");
    opt.value = a.nome;
    opt.textContent = a.nome;
    select.appendChild(opt);
  });

  const nomes = lista.map((a) => a.nome);
  aparelhoAtual = nomes.includes(selecaoAnterior) ? selecaoAnterior : nomes[0];
  select.value = aparelhoAtual;
  document.getElementById("filtro-aparelho-nome").textContent = aparelhoAtual || "--";
}

// ---------------------------------------------------------------------------
// Dados "ao vivo" (gauges, potência, kWh, status, proteções)
// ---------------------------------------------------------------------------
async function atualizarAoVivo() {
  if (!aparelhoAtual) return;
  const resp = await fetch(`/api/atual?aparelho=${encodeURIComponent(aparelhoAtual)}`);
  const dados = await resp.json();
  if (!dados.leitura) return;

  const leitura = dados.leitura;
  const referencia = dados.referencia;

  document.getElementById("meter-subtitle").textContent =
    `${aparelhoAtual} · ${new Date(leitura.timestamp).toLocaleDateString("pt-BR")}`;

  document.getElementById("valor-tensao").textContent = leitura.tensao != null ? leitura.tensao.toFixed(1) : "--";
  document.getElementById("valor-corrente").textContent = leitura.corrente != null ? leitura.corrente.toFixed(2) : "--";
  document.getElementById("valor-potencia").innerHTML =
    (leitura.potencia != null ? (leitura.potencia / 1000).toFixed(2) : "--") + " <span>kW</span>";
  document.getElementById("valor-kwh-hoje").innerHTML = dados.kwh_hoje.toFixed(2) + " <span>kWh</span>";
  document.getElementById("leituras-kwh").textContent = dados.kwh_hoje.toFixed(2) + " kWh";
  document.getElementById("valor-temperatura").innerHTML =
    (leitura.temperatura != null ? leitura.temperatura.toFixed(1) : "--") + " <span>°C</span>";

  const lim = dados.limites || {};
  const vMin = (lim.tensao_minima || 200) - 30, vMax = (lim.tensao_maxima || 240) + 30;
  const corTensao = dados.tensao_alerta ? CORES.vermelho : CORES.amarelo;
  desenharGauge("gauge-tensao", leitura.tensao || 0, vMin, vMax, corTensao);
  document.getElementById("tensao-info").textContent =
    lim.tensao_minima != null ? `· faixa segura: ${lim.tensao_minima}–${lim.tensao_maxima} V` : "";

  atualizarCustoERele(dados);
  const pill = document.getElementById("mqtt-pill");
  pill.classList.toggle("on", !!dados.mqtt_conectado);
  pill.title = dados.mqtt_conectado ? "MQTT conectado ao broker" : "MQTT desconectado — usando HTTP";
  document.getElementById("rodape-local").textContent = dados.nome_local || "";

  const maxCorrente = Math.max((referencia || 5) * 1.5, leitura.corrente * 1.2, 5);
  desenharGauge("gauge-corrente", leitura.corrente || 0, 0, maxCorrente, CORES.teal);

  const badge = document.getElementById("status-badge");
  badge.textContent = leitura.status;
  badge.className = "badge " + (
    leitura.status === "NORMAL" ? "badge-normal" :
    leitura.status === "ATENCAO" ? "badge-atencao" : "badge-anormal"
  );
  document.getElementById("referencia-info").textContent =
    referencia ? `(referência: ${referencia.toFixed(2)} A)` : "";

  // Banner de alerta + beep sonoro na transição para ATENCAO/ANORMAL
  const banner = document.getElementById("alerta-banner");
  if (dados.tensao_alerta) {
    const sub = dados.tensao_alerta === "SUBTENSAO";
    banner.style.display = "flex";
    banner.className = "alerta-banner anormal";
    document.getElementById("alerta-icone").textContent = "⛔";
    document.getElementById("alerta-texto").textContent =
      `${sub ? "SUBTENSÃO" : "SOBRETENSÃO"}: ${leitura.tensao.toFixed(1)} V (faixa segura ${lim.tensao_minima}–${lim.tensao_maxima} V)` +
      (dados.rele && dados.rele.estado === "desligado" ? " — relé DESLIGADO para proteger o aparelho." : "");
  } else if (leitura.status === "NORMAL") {
    banner.style.display = "none";
  } else {
    const anormal = leitura.status === "ANORMAL";
    banner.style.display = "flex";
    banner.className = "alerta-banner " + (anormal ? "anormal" : "atencao");
    document.getElementById("alerta-icone").textContent = anormal ? "⛔" : "⚠";
    document.getElementById("alerta-texto").textContent = anormal
      ? `Consumo muito acima do esperado em "${aparelhoAtual}" (${leitura.corrente.toFixed(2)} A, referência ${referencia ? referencia.toFixed(2) : "?"} A). Recomenda-se inspeção.`
      : `Consumo acima da referência em "${aparelhoAtual}" (${leitura.corrente.toFixed(2)} A, referência ${referencia ? referencia.toFixed(2) : "?"} A).`;
  }

  const statusAgora = dados.tensao_alerta ? "ANORMAL" : leitura.status;
  const statusAnterior = ultimoStatusConhecido[aparelhoAtual];
  if (statusAnterior && statusAnterior === "NORMAL" && statusAgora !== "NORMAL") {
    tocarBeepAlerta(statusAgora === "ANORMAL");
  }
  ultimoStatusConhecido[aparelhoAtual] = statusAgora;

  // Status das proteções
  const protecoes = dados.protecoes || {};
  Object.keys(protecoes).forEach((chave) => {
    const card = document.querySelector(`.protecao-card[data-prot="${chave}"]`);
    if (!card) return;
    const info = protecoes[chave];
    const dot = card.querySelector(".dot");
    const statusEl = card.querySelector(".protecao-status");

    statusEl.textContent = info.status;
    card.classList.remove("alerta", "atencao");
    dot.className = "dot";
    if (info.status === "ALERTA") { dot.classList.add("dot-vermelho"); card.classList.add("alerta"); }
    else if (info.status === "ATENCAO") { dot.classList.add("dot-amarelo"); card.classList.add("atencao"); }
    else if (info.status === "STANDBY") { dot.classList.add("dot-azul"); }
    else { dot.classList.add("dot-verde"); }
  });
}

// ---------------------------------------------------------------------------
// Custo, meta diária e relé
// ---------------------------------------------------------------------------
function moeda(v) { return "R$ " + (v != null ? v.toFixed(2).replace(".", ",") : "--"); }

function atualizarCustoERele(dados) {
  document.getElementById("custo-aparelho").textContent = moeda(dados.custo_hoje);
  document.getElementById("custo-total").textContent = moeda(dados.total_hoje_custo);
  document.getElementById("custo-tarifa").textContent =
    "R$ " + (dados.tarifa_efetiva || 0).toFixed(3).replace(".", ",") + "/kWh";

  const meta = dados.meta_diaria_kwh || 0;
  const total = dados.total_hoje_kwh || 0;
  document.getElementById("meta-texto").textContent = `${total.toFixed(1)} / ${meta.toFixed(0)} kWh`;
  const barra = document.getElementById("meta-barra");
  const pct = meta > 0 ? Math.min(100, (100 * total) / meta) : 0;
  barra.style.width = pct + "%";
  barra.className = "meta-barra-preenchida " + (pct >= 100 ? "estourou" : pct >= 80 ? "perto" : "");

  const r = dados.rele || {};
  const badge = document.getElementById("rele-badge");
  const motivo = document.getElementById("rele-motivo");
  const btnOff = document.getElementById("btn-rele-desligar");
  const btnOn = document.getElementById("btn-rele-ligar");
  if (!r.tem) {
    badge.textContent = "SEM RELÉ"; badge.className = "badge badge-neutro";
    motivo.textContent = "Este aparelho está cadastrado sem relé de proteção (edite em ⚙ Aparelhos).";
    btnOff.disabled = btnOn.disabled = true;
    return;
  }
  const desligado = r.estado === "desligado";
  badge.textContent = desligado ? "DESLIGADO" : "LIGADO";
  badge.className = "badge " + (desligado ? "badge-anormal" : "badge-normal");
  motivo.textContent = desligado
    ? `Desligado: ${r.motivo || "proteção"}${r.alterado_em ? " · " + formatarDataHora(r.alterado_em) : ""}`
    : "Aparelho energizado. O relé desliga sozinho se a tensão sair da faixa segura (proteção automática).";
  btnOff.disabled = desligado; btnOn.disabled = !desligado;
}

async function comandarRele(comando) {
  if (!aparelhoAtual) return;
  const msg = document.getElementById("rele-msg");
  const resp = await fetch(`/api/rele/${encodeURIComponent(aparelhoAtual)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comando }),
  });
  const r = await resp.json();
  msg.textContent = resp.ok ? `Comando "${comando}" enviado ao ESP32.` : (r.erro || "Falhou");
  msg.className = "form-msg " + (resp.ok ? "ok" : "erro");
  setTimeout(() => { msg.textContent = ""; }, 3500);
  atualizarAoVivo(); atualizarOcorrencias();
}
document.getElementById("btn-rele-desligar").addEventListener("click", () => comandarRele("desligar"));
document.getElementById("btn-rele-ligar").addEventListener("click", () => comandarRele("ligar"));

// ---------------------------------------------------------------------------
// Dicas de economia (regras simples no backend — /api/dicas)
// ---------------------------------------------------------------------------
async function atualizarDicas() {
  const resp = await fetch("/api/dicas");
  const d = await resp.json();
  const icones = { alerta: "⛔", atencao: "⚠", info: "💡", ok: "✅" };
  document.getElementById("dicas-lista").innerHTML = (d.dicas || []).map((x) => `
    <div class="dica dica-${x.nivel}">
      <span class="dica-icone">${icones[x.nivel] || "•"}</span>
      <div><div class="dica-titulo">${x.titulo}</div><div class="dica-texto">${x.texto}</div></div>
    </div>`).join("");
}

// ---------------------------------------------------------------------------
// Observações do usuário
// ---------------------------------------------------------------------------
async function atualizarObservacoes() {
  const resp = await fetch("/api/observacoes?limite=20");
  const lista = await resp.json();
  const el = document.getElementById("obs-lista");
  if (!lista.length) { el.innerHTML = '<div class="ocorrencias-vazio">Nenhuma observação ainda.</div>'; return; }
  el.innerHTML = lista.map((o) => `
    <div class="obs-item">
      <span class="oc-horario">${formatarDataHora(o.timestamp)}</span>
      <span class="obs-texto">${o.texto}${o.autor ? ` <i>— ${o.autor}</i>` : ""}</span>
      <button class="btn-link btn-link-perigo" data-id="${o.id}">apagar</button>
    </div>`).join("");
  el.querySelectorAll("button[data-id]").forEach((b) => b.addEventListener("click", async () => {
    await fetch(`/api/observacoes/${b.dataset.id}`, { method: "DELETE" });
    atualizarObservacoes();
  }));
}
document.getElementById("form-obs").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const texto = document.getElementById("obs-texto").value.trim();
  if (!texto) return;
  await fetch("/api/observacoes", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texto, autor: document.getElementById("obs-autor").value.trim(), aparelho: aparelhoAtual }),
  });
  document.getElementById("obs-texto").value = "";
  atualizarObservacoes();
});

// ---------------------------------------------------------------------------
// Leitura manual (multímetro)
// ---------------------------------------------------------------------------
document.getElementById("form-manual").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = document.getElementById("manual-msg");
  const corpo = {
    aparelho: document.getElementById("manual-aparelho").value,
    corrente: parseFloat(document.getElementById("manual-corrente").value),
    tensao: document.getElementById("manual-tensao").value || null,
    temperatura: document.getElementById("manual-temperatura").value || null,
    dispositivo_id: "MANUAL",
  };
  const resp = await fetch("/api/leitura-manual", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  const r = await resp.json();
  if (resp.ok) {
    msg.textContent = `Registrado: status ${r.status}` + (r.alertas.length ? ` · alertas: ${r.alertas.join(", ")}` : "") +
      (r.rele ? ` · relé ${r.rele}` : "");
    msg.className = "form-msg ok";
    aparelhoAtual = corpo.aparelho;
    document.getElementById("aparelho-select").value = aparelhoAtual;
    atualizarTudo(); atualizarPainelSecundario();
  } else {
    msg.textContent = r.erro || "Não foi possível registrar."; msg.className = "form-msg erro";
  }
});

// ---------------------------------------------------------------------------
// Gráfico "Leituras" (potência x tempo, com toggle Ontem/Hoje)
// ---------------------------------------------------------------------------
async function atualizarHistorico() {
  if (!aparelhoAtual) return;
  const resp = await fetch(`/api/historico?aparelho=${encodeURIComponent(aparelhoAtual)}&periodo=${periodoAtual}`);
  const pontos = await resp.json();

  const labels = pontos.map((p) => formatarHora(p.timestamp));
  const valores = pontos.map((p) => p.potencia);

  if (!chartLeituras) {
    const ctx = document.getElementById("chart-leituras").getContext("2d");
    chartLeituras = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [{
          label: "Watts",
          data: valores,
          borderColor: CORES.teal,
          backgroundColor: "rgba(45,212,191,0.08)",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          tension: 0.35,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#94a3b8" } },
          tooltip: {
            backgroundColor: "#0f1729",
            borderColor: CORES.teal,
            borderWidth: 1,
            titleColor: CORES.amarelo,
            bodyColor: "#fff",
          },
        },
        scales: {
          x: { ticks: { color: "#5b6b8c" }, grid: { color: "#1e2a45" } },
          y: { ticks: { color: "#5b6b8c" }, grid: { color: "#1e2a45" } },
        },
      },
    });
  } else {
    chartLeituras.data.labels = labels;
    chartLeituras.data.datasets[0].data = valores;
    chartLeituras.update();
  }
}

// ---------------------------------------------------------------------------
// Cards de 24 horas + donut de standby
// ---------------------------------------------------------------------------
async function atualizar24h() {
  if (!aparelhoAtual) return;
  const resp = await fetch(`/api/24h?aparelho=${encodeURIComponent(aparelhoAtual)}`);
  const dados = await resp.json();

  document.getElementById("stat-atual").textContent = dados.atual != null ? dados.atual : "--";
  document.getElementById("stat-standby").textContent = dados.standby_w != null ? dados.standby_w : "--";
  document.getElementById("stat-pico").textContent = dados.pico != null ? dados.pico : "--";
  document.getElementById("stat-hoje").textContent = dados.hoje_kwh != null ? dados.hoje_kwh.toFixed(2) : "--";

  if (dados.standby) {
    desenharDonut("chart-standby", dados.standby.pct_ativo);
    document.getElementById("pct-ativo").textContent = dados.standby.pct_ativo + "%";
    document.getElementById("pct-standby").textContent = dados.standby.pct_standby + "%";
    document.getElementById("perda-reais").textContent = "R$ " + dados.standby.perda_estimada_reais.toFixed(2) + "/mês";
  }
}

// ---------------------------------------------------------------------------
// Gráfico dos últimos 30 dias (Dia / Noite)
// ---------------------------------------------------------------------------
async function atualizar30Dias() {
  if (!aparelhoAtual) return;
  const resp = await fetch(`/api/30dias?aparelho=${encodeURIComponent(aparelhoAtual)}`);
  const dias = await resp.json();

  const labels = dias.map((d) => d.data);
  const dia = dias.map((d) => d.dia);
  const noite = dias.map((d) => d.noite);

  if (!chart30Dias) {
    const ctx = document.getElementById("chart-30dias").getContext("2d");
    chart30Dias = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          { label: "Dia", data: dia, backgroundColor: CORES.teal, stack: "s" },
          { label: "Noite", data: noite, backgroundColor: CORES.navy, stack: "s" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#94a3b8" } } },
        scales: {
          x: { stacked: true, ticks: { color: "#5b6b8c", maxRotation: 0 }, grid: { display: false } },
          y: { stacked: true, ticks: { color: "#5b6b8c" }, grid: { color: "#1e2a45" } },
        },
      },
    });
  } else {
    chart30Dias.data.labels = labels;
    chart30Dias.data.datasets[0].data = dia;
    chart30Dias.data.datasets[1].data = noite;
    chart30Dias.update();
  }
}

// ---------------------------------------------------------------------------
// Histórico de ocorrências (alertas)
// ---------------------------------------------------------------------------
function formatarDataHora(isoString) {
  const d = new Date(isoString);
  return d.toLocaleDateString("pt-BR") + " " + d.toLocaleTimeString("pt-BR");
}

async function atualizarOcorrencias() {
  const usarFiltro = somenteAparelhoSelecionado && aparelhoAtual;
  const url = usarFiltro
    ? `/api/alertas?aparelho=${encodeURIComponent(aparelhoAtual)}&limite=40`
    : `/api/alertas?limite=40`;
  const resp = await fetch(url);
  const alertas = await resp.json();

  const container = document.getElementById("ocorrencias-lista");
  if (alertas.length === 0) {
    container.innerHTML = '<div class="ocorrencias-vazio">Nenhuma ocorrência registrada até o momento.</div>';
    return;
  }
  const rotulos = {
    SUBTENSAO: "SUBTENSÃO", SOBRETENSAO: "SOBRETENSÃO", SOBRECORRENTE: "SOBRECORRENTE",
    CURTO_CIRCUITO: "CURTO/SOBRECARGA", TEMPERATURA: "TEMPERATURA", META_DIARIA: "META DIÁRIA", RELE: "RELÉ",
  };
  const graves = ["SUBTENSAO", "SOBRETENSAO", "CURTO_CIRCUITO", "TEMPERATURA"];
  container.innerHTML = alertas.map((a) => `
      <div class="ocorrencia-item ${graves.includes(a.tipo) ? "anormal" : a.tipo === "RELE" ? "rele" : ""}">
        <span class="oc-horario">${formatarDataHora(a.timestamp)}</span>
        <span class="oc-aparelho">${a.aparelho || "Todos"}</span>
        <span class="oc-valores">${a.descricao}</span>
        <span class="oc-status">${rotulos[a.tipo] || a.tipo}</span>
      </div>`).join("");
}

// ---------------------------------------------------------------------------
// Ciclo de atualização
// ---------------------------------------------------------------------------
async function atualizarTudo() {
  await carregarAparelhos();
  await atualizarAoVivo();
  await atualizarHistorico();
}

async function atualizarPainelSecundario() {
  await atualizar24h();
  await atualizar30Dias();
  await atualizarOcorrencias();
  await atualizarDicas();
  await atualizarObservacoes();
}

document.getElementById("periodo-toggle").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".toggle-btn");
  if (!btn) return;
  document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  periodoAtual = btn.dataset.periodo;
  atualizarHistorico();
});

document.getElementById("aparelho-select").addEventListener("change", (ev) => {
  aparelhoAtual = ev.target.value;
  document.getElementById("filtro-aparelho-nome").textContent = aparelhoAtual;
  atualizarAoVivo();
  atualizarHistorico();
  atualizarPainelSecundario();
});

document.getElementById("filtro-ocorrencias-aparelho").addEventListener("change", (ev) => {
  somenteAparelhoSelecionado = ev.target.checked;
  atualizarOcorrencias();
});

document.getElementById("btn-relatorio").addEventListener("click", () => {
  if (!aparelhoAtual) return;
  window.open(`/relatorio?aparelho=${encodeURIComponent(aparelhoAtual)}&dias=1`, "_blank");
});

document.getElementById("btn-exportar-csv").addEventListener("click", () => {
  if (!aparelhoAtual) return;
  window.open(`/exportar?aparelho=${encodeURIComponent(aparelhoAtual)}&dias=30`, "_blank");
});

// Primeira carga (o painel secundário depende do aparelho já estar definido,
// por isso só roda depois que atualizarTudo() termina)
(async () => {
  await atualizarTudo();
  await atualizarPainelSecundario();
})();

// Atualização periódica
setInterval(atualizarAoVivo, 4000);
setInterval(atualizarHistorico, 6000);
setInterval(atualizarPainelSecundario, 20000);
setInterval(carregarAparelhos, 15000);
