# -*- coding: utf-8 -*-
"""
flet_app.py
-----------
VoltGuard — Interface em Flet.

Este é o "aplicativo" propriamente dito: uma UI nativa (roda como janela
desktop, como página web, ou pode virar .apk/.ipa mais tarde com
`flet build`), escrita 100% em Python.

Ele NÃO acessa o banco de dados diretamente — todo dado vem da API do
app.py (Flask), que continua sendo o responsável por: receber os dados do
ESP32, gravar no SQLite, calcular status/estatísticas e gerar o PDF.

    ESP32 / esp32_simulator.py --HTTP--> app.py (Flask, porta 5000)
                                              |
                                   API REST (JSON)
                                              |
                                        flet_app.py  <- você está aqui

Como rodar (ver README.md para o passo a passo completo):
    1. python app.py            (num terminal — backend)
    2. python esp32_simulator.py (opcional, outro terminal — dados de teste)
    3. python flet_app.py       (terceiro terminal — a interface)

flet_app.py abre automaticamente no navegador padrão (modo web do Flet).
"""

import asyncio
from datetime import datetime

import requests
import flet as ft
import flet_charts as fc

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:5000"
INTERVALO_ATUALIZACAO_S = 5

# Paleta de cores (mesmos valores usados no dashboard web, static/css/style.css)
BG = "#0a0f1e"
CARD_BG = "#111a2e"
CARD_BORDER = "#1e2a45"
TEXT_MAIN = "#e2e8f0"
TEXT_MUTED = "#7c8aa8"
TEAL = "#2dd4bf"
TEAL_DARK = "#0d9488"
YELLOW = "#eab308"
GREEN = "#22c55e"
BLUE = "#3b82f6"
RED = "#ef4444"
NAVY_SOFT = "#1e2a45"
NAVY_DOT = "#334469"


# ---------------------------------------------------------------------------
# Cliente HTTP assíncrono (requests é bloqueante, então roda em thread à
# parte para não travar a interface enquanto espera a resposta do Flask)
# ---------------------------------------------------------------------------
async def api_get(path: str, params: dict = None):
    def _fazer_chamada():
        try:
            resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=5)
            if resp.ok:
                return resp.json()
        except requests.exceptions.RequestException:
            return None
        return None
    return await asyncio.to_thread(_fazer_chamada)


async def api_post(path: str, json_data: dict):
    def _fazer_chamada():
        try:
            resp = requests.post(f"{BASE_URL}{path}", json=json_data, timeout=5)
            return resp.ok, (resp.json() if resp.content else {})
        except requests.exceptions.RequestException:
            return False, {}
    return await asyncio.to_thread(_fazer_chamada)


async def api_delete(path: str):
    def _fazer_chamada():
        try:
            resp = requests.delete(f"{BASE_URL}{path}", timeout=5)
            return resp.ok
        except requests.exceptions.RequestException:
            return False
    return await asyncio.to_thread(_fazer_chamada)


def formatar_hora(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%H:%M")
    except (ValueError, TypeError):
        return "--"


def formatar_data_hora(iso_str: str) -> str:
    try:
        d = datetime.fromisoformat(iso_str)
        return d.strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        return "--"


# ---------------------------------------------------------------------------
# Componente: gauge semicircular (PieChart do Flet usado como "medidor")
# ---------------------------------------------------------------------------
class Gauge:
    """
    Widget de gauge semicircular, ao estilo velocímetro.
    Truque: um PieChart de 3 fatias (valor, restante, invisível) com
    start_degree_offset=180 faz o arco ir da esquerda, pelo topo, até a
    direita — exatamente como no layout de referência.
    """
    def __init__(self, minimo: float, maximo: float, cor: str, rotulo: str, unidade: str = ""):
        self.minimo = minimo
        self.maximo = maximo
        self.cor = cor
        self.unidade = unidade

        self.pie = fc.PieChart(
            sections=self._sections(0),
            start_degree_offset=180,
            center_space_radius=42,
            sections_space=0,
            height=150,
            width=170,
        )
        self.texto_valor = ft.Text("--", size=24, weight=ft.FontWeight.BOLD, color="#ffffff")
        texto_rotulo = ft.Text(rotulo, size=10.5, color=TEXT_MUTED)

        overlay = ft.Container(
            content=ft.Column(
                [self.texto_valor, texto_rotulo],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                tight=True,
            ),
            alignment=ft.alignment.Alignment(0, 0.5),
            width=170,
            height=150,
        )
        self.control = ft.Stack([self.pie, overlay], width=170, height=150)

    def _sections(self, fracao: float):
        fracao = max(0.0, min(1.0, fracao))
        return [
            fc.PieChartSection(value=fracao * 100, color=self.cor, radius=16),
            fc.PieChartSection(value=(1 - fracao) * 100, color=NAVY_SOFT, radius=16),
            fc.PieChartSection(value=100, color="transparent", radius=16),
        ]

    def atualizar(self, valor: float, maximo: float = None):
        if maximo is not None:
            self.maximo = maximo
        fracao = 0.0
        if self.maximo > self.minimo:
            fracao = (valor - self.minimo) / (self.maximo - self.minimo)
        self.pie.sections = self._sections(fracao)
        self.texto_valor.value = f"{valor:.2f}" if valor < 10 else f"{valor:.1f}"
        self.pie.update()
        self.texto_valor.update()


# ---------------------------------------------------------------------------
# Componentes visuais menores (cards, badges)
# ---------------------------------------------------------------------------
def cartao(*conteudo, padding=20) -> ft.Container:
    return ft.Container(
        content=ft.Column(list(conteudo), spacing=12),
        bgcolor=CARD_BG,
        border=ft.Border.all(1, CARD_BORDER),
        border_radius=12,
        padding=padding,
    )


def titulo_cartao(texto: str) -> ft.Text:
    return ft.Text(texto, size=13, weight=ft.FontWeight.BOLD, color="#cbd5e1")


def cor_status(status: str) -> str:
    return {"NORMAL": GREEN, "ATENCAO": YELLOW, "ANORMAL": RED}.get(status, TEXT_MUTED)


def cor_protecao(status: str) -> str:
    return {"ATIVO": GREEN, "ATENCAO": YELLOW, "ALERTA": RED, "STANDBY": BLUE}.get(status, TEXT_MUTED)


class CirculoStat:
    def __init__(self, rotulo: str, unidade: str):
        self.texto_valor = ft.Text("--", size=20, weight=ft.FontWeight.BOLD, color="#ffffff")
        self.control = ft.Container(
            content=ft.Column(
                [self.texto_valor, ft.Text(unidade, size=10, color=YELLOW),
                 ft.Text(rotulo, size=10.5, color=TEXT_MUTED)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0, tight=True,
            ),
            width=95, height=95, border_radius=95, bgcolor="#0f1729",
            border=ft.Border.all(1, CARD_BORDER), alignment=ft.alignment.Alignment(0, 0),
        )

    def atualizar(self, valor):
        self.texto_valor.value = "--" if valor is None else (f"{valor:.2f}" if isinstance(valor, float) and valor < 10 else f"{valor:g}")
        self.texto_valor.update()


class CartaoProtecao:
    def __init__(self, nome: str):
        self.dot = ft.Container(width=9, height=9, border_radius=9, bgcolor=GREEN)
        self.texto_status = ft.Text("--", size=11, color=TEXT_MUTED)
        self.control = ft.Container(
            content=ft.Row([
                self.dot,
                ft.Column([ft.Text(nome, size=13, weight=ft.FontWeight.W_600, color="#ffffff"),
                           self.texto_status], spacing=0, tight=True),
            ], spacing=10),
            bgcolor="#0f1729", border=ft.Border.all(1, CARD_BORDER), border_radius=8,
            padding=ft.Padding(14, 12, 14, 12), expand=True,
        )

    def atualizar(self, info: dict):
        status = info.get("status", "--")
        self.texto_status.value = status
        self.dot.bgcolor = cor_protecao(status)
        self.control.border = ft.Border.all(1, RED if status == "ALERTA" else (YELLOW if status == "ATENCAO" else CARD_BORDER))
        self.control.update()
        self.dot.update()
        self.texto_status.update()


# ---------------------------------------------------------------------------
# Aplicativo principal
# ---------------------------------------------------------------------------
async def main(page: ft.Page):
    page.title = "VoltGuard"
    page.bgcolor = BG
    page.padding = 0
    page.scroll = ft.ScrollMode.AUTO
    page.fonts = {}
    page.theme = ft.Theme(color_scheme_seed=TEAL)
    page.theme_mode = ft.ThemeMode.DARK

    # ------------------------------------------------------------------
    # Estado da sessão
    # ------------------------------------------------------------------
    estado = {
        "aparelho_atual": None,
        "periodo_atual": "hoje",
        "aparelhos": [],
    }

    # ------------------------------------------------------------------
    # Cabeçalho
    # ------------------------------------------------------------------
    relogio = ft.Text("--:--:--", size=15, color=TEXT_MUTED)

    async def atualizar_relogio_loop():
        while True:
            relogio.value = datetime.now().strftime("%H:%M:%S")
            relogio.update()
            await asyncio.sleep(1)

    btn_ontem = ft.TextButton(
        content=ft.Text("Ontem", size=12, color=TEXT_MUTED),
    )
    btn_hoje = ft.Container(
        content=ft.Text("Hoje", size=12, color=YELLOW, weight=ft.FontWeight.BOLD),
        border=ft.Border.all(1, YELLOW), border_radius=6, padding=ft.Padding(14, 6, 14, 6),
    )

    def marcar_periodo(periodo: str):
        estado["periodo_atual"] = periodo
        if periodo == "hoje":
            btn_hoje.content.color = YELLOW
            btn_hoje.border = ft.Border.all(1, YELLOW)
            btn_ontem.content.color = TEXT_MUTED
        else:
            btn_hoje.content.color = TEXT_MUTED
            btn_hoje.border = ft.Border.all(1, "transparent")
            btn_ontem.content.color = YELLOW
        btn_hoje.update()
        btn_ontem.content.update()
        page.run_task(atualizar_historico)

    btn_ontem.on_click = lambda e: marcar_periodo("ontem")
    btn_hoje_gesture = ft.GestureDetector(content=btn_hoje, on_tap=lambda e: marcar_periodo("hoje"))

    dropdown_aparelho = ft.Dropdown(width=190, options=[], text_size=13)

    aparelho_selecionado_manualmente = {"valor": False}

    def on_dropdown_change(e):
        aparelho_selecionado_manualmente["valor"] = True
        estado["aparelho_atual"] = dropdown_aparelho.value
        page.run_task(atualizar_secao_ao_vivo)
        page.run_task(atualizar_historico)
        page.run_task(atualizar_painel_secundario)

    dropdown_aparelho.on_change = on_dropdown_change

    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Container(
                    content=ft.Text("⚡", size=20, color=YELLOW),
                    width=42, height=42, border_radius=10, bgcolor="#0f1729",
                    border=ft.Border.all(1, YELLOW), alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Column([
                    ft.Row([
                        ft.Text("Volt", size=20, weight=ft.FontWeight.BOLD, color="#ffffff"),
                        ft.Text("Guard", size=20, weight=ft.FontWeight.BOLD, color=YELLOW),
                    ], spacing=0),
                    ft.Text("SISTEMA DE MONITORAMENTO E PROTEÇÃO DE ENERGIA ELÉTRICA",
                            size=9.5, color=TEXT_MUTED),
                ], spacing=0),
            ], spacing=14),
            ft.Row([
                relogio,
                ft.OutlinedButton(content=ft.Text("⚙ Aparelhos", size=12),
                                   on_click=lambda e: page.run_task(abrir_dialog_aparelhos)),
                ft.Container(
                    content=ft.Row([btn_ontem, btn_hoje_gesture], spacing=4),
                    bgcolor=CARD_BG, border=ft.Border.all(1, CARD_BORDER), border_radius=8,
                    padding=ft.Padding(3, 3, 3, 3),
                ),
            ], spacing=16),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.Padding(24, 18, 24, 18),
        border=ft.Border(bottom=ft.BorderSide(1, CARD_BORDER)),
    )

    # ------------------------------------------------------------------
    # Card: Medidor de energia ao vivo
    # ------------------------------------------------------------------
    banner_texto = ft.Text("", size=12.5, weight=ft.FontWeight.W_600, color=YELLOW)
    banner_icone = ft.Text("⚠", size=14)
    banner = ft.Container(
        content=ft.Row([banner_icone, banner_texto], spacing=10),
        padding=ft.Padding(12, 10, 12, 10), border_radius=8, visible=False,
    )

    subtitulo_medidor = ft.Text("Selecione um aparelho · --", size=12, color=TEXT_MUTED)

    gauge_tensao = Gauge(170, 270, YELLOW, "TENSÃO")   # rede 220 V; faixa ajustada pelos limites do app
    gauge_corrente = Gauge(0, 10, TEAL, "CORRENTE")

    texto_potencia = ft.Text("-- kW", size=26, weight=ft.FontWeight.BOLD, color="#ffffff")
    texto_kwh_hoje = ft.Text("-- kWh", size=26, weight=ft.FontWeight.BOLD, color="#ffffff")

    badge_status = ft.Container(
        content=ft.Text("--", size=12, weight=ft.FontWeight.BOLD, color=GREEN),
        border=ft.Border.all(1, GREEN), border_radius=20, padding=ft.Padding(12, 3, 12, 3),
    )
    texto_referencia = ft.Text("", size=12, color=TEXT_MUTED)

    card_medidor = cartao(
        banner,
        ft.Row([
            ft.Column([titulo_cartao("MEDIDOR DE ENERGIA — AO VIVO"), subtitulo_medidor], spacing=2, expand=True),
            dropdown_aparelho,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Row([
            gauge_tensao.control,
            gauge_corrente.control,
            ft.Column([
                ft.Text("POTÊNCIA", size=10.5, color=TEXT_MUTED),
                texto_potencia,
                ft.Container(height=10),
                ft.Text("KWH HOJE", size=10.5, color=TEXT_MUTED),
                texto_kwh_hoje,
            ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0),
        ], alignment=ft.MainAxisAlignment.SPACE_EVENLY, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
        ft.Divider(color=CARD_BORDER, height=1),
        ft.Row([ft.Text("Status:", size=13, color=TEXT_MUTED), badge_status, texto_referencia], spacing=10),
    )

    # ------------------------------------------------------------------
    # Card: Leituras (gráfico de linha)
    # ------------------------------------------------------------------
    texto_leituras_kwh = ft.Text("-- kWh", size=13, color=TEAL, weight=ft.FontWeight.BOLD)

    chart_leituras = fc.LineChart(
        data_series=[fc.LineChartData(points=[], color=TEAL, curved=True, stroke_width=2.5,
                                        above_line_bgcolor="#1a2d3a")],
        height=280,
        bgcolor="transparent",
        bottom_axis=fc.ChartAxis(labels=[], label_size=20),
        left_axis=fc.ChartAxis(label_size=40),
    )

    async def on_click_relatorio(e):
        aparelho = estado["aparelho_atual"]
        if not aparelho:
            return
        await page.launch_url(f"{BASE_URL}/relatorio?aparelho={aparelho}&dias=1")

    async def on_click_csv(e):
        aparelho = estado["aparelho_atual"]
        if not aparelho:
            return
        await page.launch_url(f"{BASE_URL}/exportar?aparelho={aparelho}&dias=30")

    card_leituras = cartao(
        ft.Row([
            ft.Row([titulo_cartao("LEITURAS"), texto_leituras_kwh], spacing=10),
            ft.Row([
                ft.OutlinedButton(content=ft.Text("Exportar CSV", size=12),
                                   on_click=lambda e: page.run_task(on_click_csv, e)),
                ft.Button(content=ft.Text("Gerar relatório técnico (PDF)", size=12),
                                    bgcolor=TEAL_DARK, color="#04201c",
                                    on_click=lambda e: page.run_task(on_click_relatorio, e)),
            ], spacing=10),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
        chart_leituras,
    )

    # ------------------------------------------------------------------
    # Card: Últimas 24 horas + Últimos 30 dias
    # ------------------------------------------------------------------
    circ_atual = CirculoStat("Atual", "W")
    circ_standby = CirculoStat("Standby", "W")
    circ_pico = CirculoStat("Pico", "W")
    circ_hoje = CirculoStat("Hoje", "kWh")

    card_24h = cartao(
        titulo_cartao("ÚLTIMAS 24 HORAS"),
        ft.Row([circ_atual.control, circ_standby.control, circ_pico.control, circ_hoje.control],
               alignment=ft.MainAxisAlignment.SPACE_EVENLY, wrap=True),
    )

    chart_30dias = fc.BarChart(
        groups=[], height=220,
        bottom_axis=fc.ChartAxis(labels=[], label_size=20),
        left_axis=fc.ChartAxis(label_size=32),
        group_spacing=6,
    )
    card_30dias = cartao(titulo_cartao("ÚLTIMOS 30 DIAS (barra clara = dia, escura = noite)"), chart_30dias)

    linha_24h_30dias = ft.ResponsiveRow([
        ft.Container(card_24h, col={"xs": 12, "md": 6}),
        ft.Container(card_30dias, col={"xs": 12, "md": 6}),
    ], spacing=18, run_spacing=18)

    # ------------------------------------------------------------------
    # Card: Perda em standby + Status das proteções
    # ------------------------------------------------------------------
    pie_standby = fc.PieChart(
        sections=[fc.PieChartSection(value=1, color=TEAL, radius=22),
                  fc.PieChartSection(value=1, color=NAVY_DOT, radius=22)],
        center_space_radius=45, sections_space=2, height=150, width=150,
    )
    texto_pct_ativo = ft.Text("--%", size=15, weight=ft.FontWeight.BOLD, color="#ffffff")
    texto_pct_standby = ft.Text("--%", size=15, weight=ft.FontWeight.BOLD, color="#ffffff")
    texto_perda = ft.Text("R$ --/mês", size=18, weight=ft.FontWeight.BOLD, color=YELLOW)

    card_standby = cartao(
        titulo_cartao("PERDA EM STANDBY — HOJE"),
        ft.Row([
            pie_standby,
            ft.Column([
                ft.Row([ft.Container(width=9, height=9, border_radius=9, bgcolor=TEAL),
                        ft.Text("ATIVO", size=11, color=TEXT_MUTED), texto_pct_ativo], spacing=6),
                ft.Row([ft.Container(width=9, height=9, border_radius=9, bgcolor=NAVY_DOT),
                        ft.Text("STANDBY", size=11, color=TEXT_MUTED), texto_pct_standby], spacing=6),
                ft.Container(height=8),
                ft.Text("PERDA ESTIMADA", size=10, color=TEXT_MUTED),
                texto_perda,
            ], spacing=8),
        ], spacing=24, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    protecao_sobretensao = CartaoProtecao("Sobretensão")
    protecao_curto = CartaoProtecao("Curto-circuito")
    protecao_dht = CartaoProtecao("Harmônicas DHT")
    protecao_ups = CartaoProtecao("Backup UPS")

    card_protecoes = cartao(
        titulo_cartao("STATUS DAS PROTEÇÕES"),
        ft.Row([protecao_sobretensao.control, protecao_curto.control], spacing=12),
        ft.Row([protecao_dht.control, protecao_ups.control], spacing=12),
    )

    linha_standby_protecoes = ft.ResponsiveRow([
        ft.Container(card_standby, col={"xs": 12, "md": 6}),
        ft.Container(card_protecoes, col={"xs": 12, "md": 6}),
    ], spacing=18, run_spacing=18)

    # ------------------------------------------------------------------
    # Card: Alertas e histórico de ocorrências
    # ------------------------------------------------------------------
    lista_ocorrencias = ft.Column(spacing=8, height=300, scroll=ft.ScrollMode.AUTO)
    checkbox_filtro = ft.Checkbox(label="somente aparelho selecionado", value=False, label_style=ft.TextStyle(size=11.5, color=TEXT_MUTED))
    checkbox_filtro.on_change = lambda e: page.run_task(atualizar_ocorrencias)

    card_ocorrencias = cartao(
        ft.Row([titulo_cartao("ALERTAS E HISTÓRICO DE OCORRÊNCIAS"), checkbox_filtro],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        lista_ocorrencias,
    )

    rodape = ft.Text(
        "VoltGuard — Projeto IoT de Monitoramento de Corrente Elétrica · dados atualizados automaticamente",
        size=11, color=TEXT_MUTED, text_align=ft.TextAlign.CENTER,
    )

    corpo = ft.Container(
        content=ft.Column([
            card_medidor, card_leituras, linha_24h_30dias, linha_standby_protecoes,
            card_ocorrencias, ft.Container(rodape, alignment=ft.alignment.Alignment(0, 0), padding=ft.Padding(0, 10, 0, 20)),
        ], spacing=18),
        padding=ft.Padding(24, 18, 24, 24),
    )

    page.add(ft.Column([header, corpo], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True))

    # ==================================================================
    # Funções de atualização de dados
    # ==================================================================
    async def carregar_aparelhos():
        lista = await api_get("/api/aparelhos") or []
        estado["aparelhos"] = lista
        nomes = [a["nome"] for a in lista]
        dropdown_aparelho.options = [ft.DropdownOption(n) for n in nomes]
        if nomes:
            if estado["aparelho_atual"] not in nomes:
                estado["aparelho_atual"] = nomes[0]
            dropdown_aparelho.value = estado["aparelho_atual"]
        dropdown_aparelho.update()

    async def atualizar_secao_ao_vivo():
        aparelho = estado["aparelho_atual"]
        if not aparelho:
            return
        dados = await api_get("/api/atual", {"aparelho": aparelho})
        if not dados or not dados.get("leitura"):
            return
        leitura = dados["leitura"]
        referencia = dados.get("referencia") or 5.0

        subtitulo_medidor.value = f"{aparelho} · {formatar_hora(leitura['timestamp'])}"
        subtitulo_medidor.update()

        lim = dados.get("limites") or {}
        if lim.get("tensao_minima") is not None:
            gauge_tensao.minimo = float(lim["tensao_minima"]) - 30
            gauge_tensao.maximo = float(lim["tensao_maxima"]) + 30
        gauge_tensao.cor = RED if dados.get("tensao_alerta") else YELLOW
        gauge_tensao.atualizar(leitura.get("tensao") or 0)
        max_corrente = max(referencia * 1.5, (leitura.get("corrente") or 0) * 1.2, 5)
        gauge_corrente.atualizar(leitura.get("corrente") or 0, maximo=max_corrente)

        potencia = leitura.get("potencia") or 0
        texto_potencia.value = f"{potencia / 1000:.2f} kW"
        texto_potencia.update()
        texto_kwh_hoje.value = f"{dados.get('kwh_hoje', 0):.2f} kWh"
        texto_kwh_hoje.update()
        texto_leituras_kwh.value = f"{dados.get('kwh_hoje', 0):.2f} kWh"
        texto_leituras_kwh.update()

        status = leitura.get("status", "NORMAL")
        badge_status.content.value = status
        badge_status.content.color = cor_status(status)
        badge_status.border = ft.Border.all(1, cor_status(status))
        badge_status.update()
        texto_referencia.value = f"(referência: {referencia:.2f} A)"
        texto_referencia.update()

        if status == "NORMAL":
            banner.visible = False
        else:
            anormal = status == "ANORMAL"
            banner.visible = True
            banner.bgcolor = "#3a1414" if anormal else "#3a2f0f"
            banner.border = ft.Border.all(1, RED if anormal else YELLOW)
            banner_icone.value = "⛔" if anormal else "⚠"
            banner_texto.value = (
                f'Consumo {"muito " if anormal else ""}acima da referência em "{aparelho}" '
                f'({leitura.get("corrente", 0):.2f} A, referência {referencia:.2f} A).'
            )
            banner_texto.color = "#fca5a5" if anormal else YELLOW
        banner.update()

        protecoes = dados.get("protecoes") or {}
        if protecoes.get("sobretensao"):
            protecao_sobretensao.atualizar(protecoes["sobretensao"])
        if protecoes.get("curto_circuito"):
            protecao_curto.atualizar(protecoes["curto_circuito"])
        if protecoes.get("harmonicas_dht"):
            protecao_dht.atualizar(protecoes["harmonicas_dht"])
        if protecoes.get("backup_ups"):
            protecao_ups.atualizar(protecoes["backup_ups"])

    async def atualizar_historico():
        aparelho = estado["aparelho_atual"]
        if not aparelho:
            return
        pontos = await api_get("/api/historico", {"aparelho": aparelho, "periodo": estado["periodo_atual"]}) or []
        dados_grafico = [fc.LineChartDataPoint(x=i, y=p["potencia"] or 0) for i, p in enumerate(pontos) if p.get("potencia") is not None]
        chart_leituras.data_series[0].points = dados_grafico

        rotulos = []
        passo = max(1, len(pontos) // 6)
        for i, p in enumerate(pontos):
            if i % passo == 0:
                rotulos.append(fc.ChartAxisLabel(value=i, label=formatar_hora(p["timestamp"])))
        chart_leituras.bottom_axis = fc.ChartAxis(labels=rotulos, label_size=20)
        chart_leituras.update()

    async def atualizar_painel_secundario():
        aparelho = estado["aparelho_atual"]
        if not aparelho:
            return

        dados_24h = await api_get("/api/24h", {"aparelho": aparelho}) or {}
        circ_atual.atualizar(dados_24h.get("atual"))
        circ_standby.atualizar(dados_24h.get("standby_w"))
        circ_pico.atualizar(dados_24h.get("pico"))
        circ_hoje.atualizar(dados_24h.get("hoje_kwh"))

        standby = dados_24h.get("standby") or {}
        pct_ativo = standby.get("pct_ativo", 0)
        pct_standby = standby.get("pct_standby", 0)
        pie_standby.sections = [
            fc.PieChartSection(value=max(pct_ativo, 0.001), color=TEAL, radius=22),
            fc.PieChartSection(value=max(pct_standby, 0.001), color=NAVY_DOT, radius=22),
        ]
        pie_standby.update()
        texto_pct_ativo.value = f"{pct_ativo}%"
        texto_pct_ativo.update()
        texto_pct_standby.value = f"{pct_standby}%"
        texto_pct_standby.update()
        texto_perda.value = f"R$ {standby.get('perda_estimada_reais', 0):.2f}/mês"
        texto_perda.update()

        dias = await api_get("/api/30dias", {"aparelho": aparelho}) or []
        grupos = []
        rotulos_dias = []
        passo = max(1, len(dias) // 8)
        for i, d in enumerate(dias):
            grupos.append(fc.BarChartGroup(x=i, rods=[
                fc.BarChartRod(to_y=d.get("dia", 0), color=TEAL, width=4, border_radius=2),
                fc.BarChartRod(to_y=d.get("noite", 0), color=NAVY_DOT, width=4, border_radius=2),
            ]))
            if i % passo == 0:
                rotulos_dias.append(fc.ChartAxisLabel(value=i, label=d.get("data", "")))
        chart_30dias.groups = grupos
        chart_30dias.bottom_axis = fc.ChartAxis(labels=rotulos_dias, label_size=20)
        chart_30dias.update()

        await atualizar_ocorrencias()

    async def atualizar_ocorrencias():
        aparelho = estado["aparelho_atual"]
        usar_filtro = checkbox_filtro.value and aparelho
        params = {"aparelho": aparelho, "limite": 30} if usar_filtro else {"limite": 30}
        ocorrencias = await api_get("/api/ocorrencias", params) or []

        if not ocorrencias:
            lista_ocorrencias.controls = [ft.Text("Nenhuma ocorrência registrada até o momento.",
                                                     size=12.5, color=TEXT_MUTED)]
        else:
            linhas = []
            for o in ocorrencias:
                anormal = o["status"] == "ANORMAL"
                ref_txt = f'{o["referencia"]:.2f} A' if o.get("referencia") is not None else "--"
                linhas.append(ft.Container(
                    content=ft.Row([
                        ft.Text(formatar_data_hora(o["timestamp"]), size=11.5, color=TEXT_MUTED, width=145),
                        ft.Text(o["aparelho"], size=12, weight=ft.FontWeight.W_600, color="#ffffff", expand=True),
                        ft.Text(f'{o["corrente"]:.2f} A (ref. {ref_txt})', size=11.5, color=TEXT_MUTED),
                        ft.Text(o["status"], size=11.5, weight=ft.FontWeight.BOLD,
                                 color=RED if anormal else YELLOW, width=80, text_align=ft.TextAlign.RIGHT),
                    ], spacing=12),
                    bgcolor="#0f1729", border=ft.Border(left=ft.BorderSide(3, RED if anormal else YELLOW)),
                    border_radius=6, padding=ft.Padding(14, 10, 14, 10),
                ))
            lista_ocorrencias.controls = linhas
        lista_ocorrencias.update()

    async def atualizar_tudo():
        await carregar_aparelhos()
        await atualizar_secao_ao_vivo()
        await atualizar_historico()
        await atualizar_painel_secundario()

    # ------------------------------------------------------------------
    # Diálogo de cadastro de aparelhos
    # ------------------------------------------------------------------
    campo_nome = ft.TextField(label="Nome do aparelho", width=250)
    campo_referencia = ft.TextField(label="Corrente de referência (A)", width=200, keyboard_type=ft.KeyboardType.NUMBER)
    msg_form = ft.Text("", size=12)
    lista_aparelhos_dialog = ft.Column(spacing=6, height=220, scroll=ft.ScrollMode.AUTO)

    async def carregar_lista_dialog():
        lista = await api_get("/api/aparelhos") or []
        linhas = []
        for a in lista:
            if a.get("corrente_referencia") is None:
                continue
            nome, ref = a["nome"], a["corrente_referencia"]

            def fazer_editar(nome=nome, ref=ref):
                def handler(e):
                    campo_nome.value = nome
                    campo_nome.disabled = True
                    campo_referencia.value = str(ref)
                    campo_nome.update()
                    campo_referencia.update()
                return handler

            def fazer_excluir(nome=nome):
                async def handler(e):
                    await api_delete(f"/api/aparelhos/{nome}")
                    await carregar_lista_dialog()
                    await carregar_aparelhos()
                return lambda e: page.run_task(handler, e)

            linhas.append(ft.Row([
                ft.Text(nome, size=12.5, color="#ffffff", expand=True),
                ft.Text(f"{ref:.2f} A", size=12, color=TEXT_MUTED, width=70),
                ft.TextButton(content=ft.Text("Editar", size=11.5, color=TEAL), on_click=fazer_editar()),
                ft.TextButton(content=ft.Text("Excluir", size=11.5, color=RED), on_click=fazer_excluir()),
            ], spacing=8))
        lista_aparelhos_dialog.controls = linhas or [ft.Text("Nenhum aparelho cadastrado.", size=12, color=TEXT_MUTED)]
        lista_aparelhos_dialog.update()

    async def salvar_aparelho(e):
        nome = (campo_nome.value or "").strip()
        try:
            referencia = float(campo_referencia.value)
        except (TypeError, ValueError):
            referencia = None
        if not nome or not referencia or referencia <= 0:
            msg_form.value = "Preencha nome e uma corrente de referência válida (> 0)."
            msg_form.color = RED
            msg_form.update()
            return
        ok, _ = await api_post("/api/aparelhos", {"nome": nome, "corrente_referencia": referencia})
        msg_form.value = f'"{nome}" salvo com sucesso.' if ok else "Não foi possível salvar."
        msg_form.color = GREEN if ok else RED
        msg_form.update()
        campo_nome.value, campo_referencia.value = "", ""
        campo_nome.disabled = False
        campo_nome.update()
        campo_referencia.update()
        await carregar_lista_dialog()
        await carregar_aparelhos()

    dialog_aparelhos = ft.AlertDialog(
        modal=True,
        title=ft.Text("Cadastro de aparelhos", color="#ffffff"),
        bgcolor=CARD_BG,
        content=ft.Container(
            content=ft.Column([
                ft.Text("A corrente de referência define quando o VoltGuard classifica uma leitura "
                        "como ATENÇÃO (>100%) ou ANORMAL (>120%).", size=11.5, color=TEXT_MUTED),
                ft.Row([campo_nome, campo_referencia]),
                ft.Row([
                    ft.Button(content=ft.Text("Salvar"), bgcolor=TEAL_DARK, color="#04201c",
                                        on_click=lambda e: page.run_task(salvar_aparelho, e)),
                    msg_form,
                ]),
                ft.Divider(color=CARD_BORDER),
                ft.Text("APARELHOS CADASTRADOS", size=11, color=TEXT_MUTED),
                lista_aparelhos_dialog,
            ], spacing=12, tight=True),
            width=520,
        ),
        actions=[ft.TextButton(content=ft.Text("Fechar"), on_click=lambda e: page.pop_dialog())],
    )

    async def abrir_dialog_aparelhos():
        page.show_dialog(dialog_aparelhos)
        await carregar_lista_dialog()

    # ------------------------------------------------------------------
    # Início: carrega dados e dispara os laços de atualização periódica
    # ------------------------------------------------------------------
    await atualizar_tudo()

    async def loop_atualizacao():
        while True:
            await asyncio.sleep(INTERVALO_ATUALIZACAO_S)
            await atualizar_secao_ao_vivo()
            await atualizar_historico()

    async def loop_painel_secundario():
        while True:
            await asyncio.sleep(INTERVALO_ATUALIZACAO_S * 4)
            await carregar_aparelhos()
            await atualizar_painel_secundario()

    page.run_task(atualizar_relogio_loop)
    page.run_task(loop_atualizacao)
    page.run_task(loop_painel_secundario)


if __name__ == "__main__":
    print("=" * 60)
    print(" VoltGuard (Flet) — certifique-se de que 'python app.py'")
    print(" já está rodando em outro terminal (http://localhost:5000)")
    print("=" * 60)
    ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550, no_cdn=True)
