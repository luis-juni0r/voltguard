# -*- coding: utf-8 -*-
"""
report_generator.py
--------------------
Gera o relatório técnico automático em PDF (seção 14 do documento-base).

Estrutura do relatório:
  1. Identificação do equipamento e período monitorado
  2. Estatísticas de corrente, tensão e potência
  3. Quantidade de ocorrências e horários das principais anormalidades
  4. Gráfico de corrente x tempo
  5. Classificação do comportamento
  6. Recomendação técnica
"""

import os
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # backend sem interface gráfica (necessário no servidor Flask)
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
)

import logic

COR_PRIMARIA = colors.HexColor("#0f172a")
COR_DESTAQUE = colors.HexColor("#14b8a6")
COR_ALERTA = colors.HexColor("#eab308")
COR_ANORMAL = colors.HexColor("#ef4444")


def _cor_status(status):
    return {
        logic.STATUS_NORMAL: colors.HexColor("#16a34a"),
        logic.STATUS_ATENCAO: COR_ALERTA,
        logic.STATUS_ANORMAL: COR_ANORMAL,
    }.get(status, colors.black)


def _gerar_grafico_corrente(leituras, referencia, caminho_imagem):
    """Gera o gráfico de corrente x tempo e salva como PNG temporário."""
    horarios = [datetime.fromisoformat(l["timestamp"]) for l in leituras]
    correntes = [l["corrente"] for l in leituras]

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(horarios, correntes, color="#0d9488", linewidth=1.8, label="Corrente medida (A)")

    if referencia:
        ax.axhline(referencia, color="#eab308", linestyle="--", linewidth=1.4,
                    label=f"Referência ({referencia:.2f} A)")

    ax.set_xlabel("Horário")
    ax.set_ylabel("Corrente (A)")
    ax.set_title("Corrente x Tempo")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(caminho_imagem, dpi=150)
    plt.close(fig)


def gerar_relatorio_pdf(aparelho: str, referencia: float, leituras: list,
                          inicio: datetime, fim: datetime, caminho_saida: str) -> str:
    """
    Monta o PDF completo e salva em `caminho_saida`. Retorna o caminho do arquivo.
    """
    stats = logic.estatisticas_periodo(leituras)
    comportamento = logic.classificar_comportamento(stats)
    recomendacao = logic.gerar_recomendacao(stats, referencia)

    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle(
        "TituloVoltGuard", parent=styles["Title"], textColor=COR_PRIMARIA, fontSize=22
    )
    subtitulo_style = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], textColor=colors.HexColor("#475569"), fontSize=11
    )
    secao_style = ParagraphStyle(
        "Secao", parent=styles["Heading2"], textColor=COR_PRIMARIA, spaceBefore=14, spaceAfter=6
    )
    corpo_style = styles["Normal"]

    doc = SimpleDocTemplate(
        caminho_saida, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=f"Relatório Técnico VoltGuard - {aparelho}",
    )

    story = []

    # Cabeçalho
    story.append(Paragraph("VoltGuard", titulo_style))
    story.append(Paragraph("Relatório Técnico de Monitoramento de Corrente Elétrica", subtitulo_style))
    story.append(Spacer(1, 0.6 * cm))

    # 1. Identificação
    story.append(Paragraph("1. Identificação do Equipamento e Período", secao_style))
    dados_ident = [
        ["Aparelho monitorado", aparelho],
        ["Corrente de referência", f"{referencia:.2f} A" if referencia else "não configurada"],
        ["Período monitorado", f"{inicio.strftime('%d/%m/%Y %H:%M')} até {fim.strftime('%d/%m/%Y %H:%M')}"],
        ["Quantidade de leituras", str(stats["quantidade"])],
        ["Relatório gerado em", datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
    ]
    tabela_ident = Table(dados_ident, colWidths=[6 * cm, 10 * cm])
    tabela_ident.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (0, -1), COR_PRIMARIA),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabela_ident)

    if stats["quantidade"] == 0:
        story.append(Spacer(1, 0.6 * cm))
        story.append(Paragraph(
            "Não foram encontradas leituras deste aparelho no período informado.", corpo_style))
        doc.build(story)
        return caminho_saida

    # 2. Estatísticas elétricas
    story.append(Paragraph("2. Estatísticas Elétricas do Período", secao_style))
    dados_stats = [
        ["Grandeza", "Média", "Mínima", "Máxima"],
        ["Corrente (A)", f"{stats['corrente_media']:.2f}", f"{stats['corrente_min']:.2f}", f"{stats['corrente_max']:.2f}"],
        ["Tensão (V)",
         f"{stats['tensao_media']:.2f}" if stats["tensao_media"] is not None else "-",
         f"{stats['tensao_min']:.2f}" if stats["tensao_min"] is not None else "-",
         f"{stats['tensao_max']:.2f}" if stats["tensao_max"] is not None else "-"],
        ["Potência estimada (W)",
         f"{stats['potencia_media']:.2f}" if stats["potencia_media"] is not None else "-",
         "-",
         f"{stats['potencia_max']:.2f}" if stats["potencia_max"] is not None else "-"],
    ]
    tabela_stats = Table(dados_stats, colWidths=[5.5 * cm, 3.5 * cm, 3.5 * cm, 3.5 * cm])
    tabela_stats.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COR_PRIMARIA),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tabela_stats)

    # 3. Ocorrências
    story.append(Paragraph("3. Ocorrências Acima da Referência", secao_style))
    story.append(Paragraph(
        f"Foram registradas <b>{stats['ocorrencias']}</b> ocorrências de leitura em status "
        f"ATENÇÃO ou ANORMAL, de um total de {stats['quantidade']} leituras "
        f"({(100 * stats['ocorrencias'] / stats['quantidade']):.1f}% do período).",
        corpo_style
    ))

    if stats["horarios_ocorrencias"]:
        story.append(Spacer(1, 0.2 * cm))
        horarios_fmt = [
            datetime.fromisoformat(h).strftime("%d/%m %H:%M:%S")
            for h in stats["horarios_ocorrencias"][:15]
        ]
        texto_horarios = " · ".join(horarios_fmt)
        if len(stats["horarios_ocorrencias"]) > 15:
            texto_horarios += f" · (+{len(stats['horarios_ocorrencias']) - 15} outras)"
        story.append(Paragraph(f"<b>Principais horários:</b> {texto_horarios}", corpo_style))

    # 4. Gráfico
    story.append(Paragraph("4. Gráfico de Corrente ao Longo do Tempo", secao_style))
    with tempfile.TemporaryDirectory() as tmp_dir:
        caminho_grafico = os.path.join(tmp_dir, "grafico_corrente.png")
        _gerar_grafico_corrente(leituras, referencia, caminho_grafico)
        story.append(Image(caminho_grafico, width=16 * cm, height=7 * cm))

        # 5. Classificação
        story.append(Paragraph("5. Classificação do Comportamento", secao_style))
        story.append(Paragraph(comportamento, corpo_style))

        # 6. Recomendação
        story.append(Paragraph("6. Recomendação Técnica", secao_style))
        story.append(Paragraph(recomendacao, corpo_style))

        story.append(Spacer(1, 1 * cm))
        story.append(Paragraph(
            "Relatório gerado automaticamente pelo sistema VoltGuard. Os limites de referência "
            "são configuráveis e o sistema não substitui a avaliação de um profissional habilitado.",
            ParagraphStyle("Rodape", parent=styles["Normal"], fontSize=8,
                            textColor=colors.HexColor("#94a3b8"))
        ))

        doc.build(story)

    return caminho_saida
