// ============================================================================
// configuracoes.js — VoltGuard
// Tela de limites de proteção, tarifa/bandeira, meta diária e dados de conexão.
// ============================================================================
const CAMPOS = ["nome_local", "tensao_nominal", "tensao_minima", "tensao_maxima", "temperatura_maxima",
  "leituras_para_religar", "tarifa_kwh", "bandeira", "consumo_max_diario_kwh"];
const CHECKS = ["protecao_automatica", "religar_automatico"];

function mostrar(texto, tipo) {
  const el = document.getElementById("cfg-msg");
  el.textContent = texto; el.className = "form-msg " + tipo;
  setTimeout(() => { el.textContent = ""; }, 4000);
}

function preencher(cfg) {
  CAMPOS.forEach((c) => { document.getElementById("cfg-" + c).value = cfg[c] != null ? cfg[c] : ""; });
  CHECKS.forEach((c) => { document.getElementById("cfg-" + c).checked = !!cfg[c]; });
  document.getElementById("cfg-tarifa-efetiva").textContent =
    "R$ " + Number(cfg.tarifa_efetiva || 0).toFixed(4).replace(".", ",") + " por kWh";
}

async function carregar() {
  const cfg = await (await fetch("/api/configuracoes")).json();
  preencher(cfg);
  const info = await (await fetch("/api/info")).json();
  document.getElementById("cx-url").textContent = info.url_base;
  document.getElementById("cx-endpoint").textContent = info.endpoint_leitura + (info.api_key_exigida ? "  (header X-Api-Key)" : "");
  document.getElementById("cx-broker").textContent = info.mqtt.ativo ? `${info.mqtt.broker}:${info.mqtt.porta}` : "MQTT desligado (só HTTP)";
  document.getElementById("cx-top-sens").textContent = info.mqtt.topico_sensores;
  document.getElementById("cx-top-cmd").textContent = info.mqtt.topico_comando + "   (ou " + info.mqtt.topico_comando + "/<aparelho>)";
  document.getElementById("cx-mqtt-estado").textContent = info.mqtt.ativo ? (info.mqtt.conectado ? "conectado ✅" : "tentando conectar…") : "—";
  document.getElementById("cx-json").textContent = JSON.stringify(info.exemplo_json, null, 2);
}

document.getElementById("form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const corpo = {};
  CAMPOS.forEach((c) => { corpo[c] = document.getElementById("cfg-" + c).value; });
  CHECKS.forEach((c) => { corpo[c] = document.getElementById("cfg-" + c).checked ? 1 : 0; });
  const resp = await fetch("/api/configuracoes", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  const r = await resp.json();
  if (resp.ok) { preencher(r); mostrar("Configurações salvas. Os novos limites já valem para a próxima leitura.", "ok"); }
  else mostrar(r.erro || "Não foi possível salvar.", "erro");
});

carregar();
