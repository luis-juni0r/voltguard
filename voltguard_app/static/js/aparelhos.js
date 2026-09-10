// ============================================================================
// aparelhos.js — VoltGuard
// Tela de cadastro/edição das correntes de referência de cada aparelho.
// ============================================================================

const FATOR_ATENCAO_INFO = 1.0;
const FATOR_ANORMAL_INFO = 1.2; // igual ao config.py (FATOR_ANORMAL) — só para exibição

let editando = null; // nome do aparelho em edição (null = cadastro novo)

async function carregarTabela() {
  const resp = await fetch("/api/aparelhos");
  const lista = await resp.json();
  const corpo = document.getElementById("tabela-aparelhos-body");

  const comReferencia = lista.filter((a) => a.corrente_referencia != null);

  if (comReferencia.length === 0) {
    corpo.innerHTML = '<tr><td colspan="5" class="tabela-vazio">Nenhum aparelho cadastrado ainda.</td></tr>';
    return;
  }

  window._aparelhos = {};
  corpo.innerHTML = comReferencia.map((a) => {
    window._aparelhos[a.nome] = a;
    const ref = a.corrente_referencia;
    const horario = a.horario_inicio && a.horario_fim ? `${a.horario_inicio}–${a.horario_fim}` : "—";
    const rele = a.tem_rele ? (a.rele_estado === "desligado" ? '<span class="badge badge-anormal">DESLIGADO</span>' : '<span class="badge badge-normal">ligado</span>') : "sem relé";
    return `
      <tr>
        <td>${a.nome}</td>
        <td>${ref.toFixed(2)} A</td>
        <td>&gt; ${(ref * FATOR_ATENCAO_INFO).toFixed(2)} A / &gt; ${(ref * FATOR_ANORMAL_INFO).toFixed(2)} A</td>
        <td>${a.potencia_estimada != null ? a.potencia_estimada.toFixed(0) + " W" : "—"}</td>
        <td>${horario}</td>
        <td>${rele}</td>
        <td class="tabela-acoes">
          <button class="btn-link" data-acao="editar" data-nome="${a.nome}">Editar</button>
          <button class="btn-link btn-link-perigo" data-acao="excluir" data-nome="${a.nome}">Excluir</button>
        </td>
      </tr>`;
  }).join("");

  corpo.querySelectorAll('[data-acao="editar"]').forEach((btn) => {
    btn.addEventListener("click", () => iniciarEdicao(btn.dataset.nome));
  });
  corpo.querySelectorAll('[data-acao="excluir"]').forEach((btn) => {
    btn.addEventListener("click", () => excluirAparelho(btn.dataset.nome));
  });
}

function iniciarEdicao(nome) {
  const a = window._aparelhos[nome];
  editando = nome;
  document.getElementById("input-nome").value = nome;
  document.getElementById("input-nome").disabled = true;
  document.getElementById("input-referencia").value = a.corrente_referencia;
  document.getElementById("input-potencia").value = a.potencia_estimada != null ? a.potencia_estimada : "";
  document.getElementById("input-inicio").value = a.horario_inicio || "";
  document.getElementById("input-fim").value = a.horario_fim || "";
  document.getElementById("input-rele").checked = !!a.tem_rele;
  document.getElementById("form-titulo").textContent = `EDITANDO: ${nome.toUpperCase()}`;
  document.getElementById("btn-salvar").textContent = "Salvar alteração";
  document.getElementById("btn-cancelar").style.display = "inline-block";
  document.getElementById("input-referencia").focus();
}

function cancelarEdicao() {
  editando = null;
  document.getElementById("form-aparelho").reset();
  document.getElementById("input-rele").checked = true;
  document.getElementById("input-nome").disabled = false;
  document.getElementById("form-titulo").textContent = "NOVO APARELHO";
  document.getElementById("btn-salvar").textContent = "Salvar";
  document.getElementById("btn-cancelar").style.display = "none";
}

function mostrarMensagem(texto, tipo = "ok") {
  const el = document.getElementById("form-msg");
  el.textContent = texto;
  el.className = "form-msg " + tipo;
  setTimeout(() => { el.textContent = ""; el.className = "form-msg"; }, 3500);
}

async function excluirAparelho(nome) {
  if (!confirm(`Excluir o cadastro de "${nome}"? O histórico de leituras já registrado é mantido.`)) return;
  const resp = await fetch(`/api/aparelhos/${encodeURIComponent(nome)}`, { method: "DELETE" });
  if (resp.ok) {
    mostrarMensagem(`"${nome}" removido do cadastro.`, "ok");
    if (editando === nome) cancelarEdicao();
    carregarTabela();
  } else {
    mostrarMensagem("Não foi possível excluir.", "erro");
  }
}

document.getElementById("form-aparelho").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const nome = document.getElementById("input-nome").value.trim();
  const referencia = parseFloat(document.getElementById("input-referencia").value);

  if (!nome || isNaN(referencia) || referencia <= 0) {
    mostrarMensagem("Preencha um nome e uma corrente de referência válida (> 0).", "erro");
    return;
  }

  const resp = await fetch("/api/aparelhos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nome, corrente_referencia: referencia,
      potencia_estimada: document.getElementById("input-potencia").value || null,
      horario_inicio: document.getElementById("input-inicio").value || null,
      horario_fim: document.getElementById("input-fim").value || null,
      tem_rele: document.getElementById("input-rele").checked,
    }),
  });

  if (resp.ok) {
    mostrarMensagem(`"${nome}" salvo com sucesso.`, "ok");
    cancelarEdicao();
    carregarTabela();
  } else {
    mostrarMensagem("Não foi possível salvar. Confira os dados.", "erro");
  }
});

document.getElementById("btn-cancelar").addEventListener("click", cancelarEdicao);

carregarTabela();
