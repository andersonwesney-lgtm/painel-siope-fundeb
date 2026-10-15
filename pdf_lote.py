"""PDFs em lote (Brasil e cada UF), lidos dos MESMOS arquivos que o painel usa (site/dados/).

O conteúdo segue as mesmas seções do PDF gerado pelo botão do painel. Os números
vêm das mesmas linhas processadas; o identificador SHA-256 impresso é o do
arquivo do bimestre, igual ao exibido no painel.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROBLEMA = ("descumprida", "parcial_abaixo", "verificar")
PESO = {"irregular": 3, "atencao": 2, "regular": 1, "sem_info": 0}


def fmt_num(v, casas=2):
    if v is None:
        return "-"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(n):
    return f"{n:,}".replace(",", ".")


def fv(v, u):
    if v is None:
        return "-"
    return fmt_num(v) + "%" if u == "%" else ("R$ " + fmt_num(v) if u == "R$" else fmt_num(v))


def fd(iso):
    if not iso:
        return "-"
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}"


def pct(n, d):
    if not d:
        return "-"
    return fmt_num(100 * n / d).removesuffix(",00") + "%"


class Dados:
    def __init__(self, site: Path):
        self.site = site
        ler = lambda p: json.loads((site / p).read_text(encoding="utf-8"))
        self.manifest = ler("dados/manifest.json")
        self.cat = ler("dados/catalogo.json")
        ent = ler("dados/entes.json")
        ix = {c: i for i, c in enumerate(ent["colunas"])}
        self.entes = {l[ix["id"]]: {c: l[i] for c, i in ix.items()} for l in ent["linhas"]}
        self._ler = ler

    def periodo(self, ano: int, b: int) -> tuple[dict, dict, list[dict]]:
        ex = next(e for e in self.manifest["exercicios"] if e["ano"] == ano)
        bim = next(x for x in ex["bimestres"] if x["bimestre"] == b)
        dados = self._ler(bim["arquivo"])
        ix = {c: i for i, c in enumerate(dados["colunas"])}
        linhas = []
        for l in dados["linhas"]:
            r = {k: l[ix[k]] for k in ("id", "sg", "nc", "na", "al", "tb", "td", "vaat", "tx6")}
            r["v"] = {o["id"]: l[ix["v." + o["id"]]] for o in self.cat["obrigacoes"]}
            r["s"] = {o["id"]: l[ix["s." + o["id"]]] for o in self.cat["obrigacoes"]}
            r["e"] = self.entes.get(r["id"], {"nome": r["id"], "uf": "", "regiao": "", "esfera": "", "pop": None})
            linhas.append(r)
        return ex, bim | {"data_referencia": dados["data_referencia"], "ultima_coleta": dados["ultima_coleta"]}, linhas


def alerta_info(cat: dict, cod: str) -> dict:
    nivel, tipo, ref = cod.split(":")
    if tipo == "o":
        o = next(x for x in cat["obrigacoes"] if x["id"] == ref)
        t = f"{o['titulo']}: descumprida" if nivel == "c" else f"{o['titulo']}: fora da regra até o bimestre"
        return {"nivel": "critico" if nivel == "c" else "atencao", "titulo": t, "base": o["dispositivo"]}
    t = (f"{ref}º bimestre não transmitido, prazo vencido" if nivel == "c"
         else f"{ref}º bimestre transmitido após o prazo")
    return {"nivel": "critico" if nivel == "c" else "atencao", "titulo": t, "base": cat["prazo_regra"]["dispositivo"]}


def agregar(cat: dict, rows: list[dict]) -> dict:
    a = {"total": len(rows), "sg": {"irregular": 0, "atencao": 0, "regular": 0, "sem_info": 0},
         "obr": {o["id"]: {} for o in cat["obrigacoes"]}, "al": {}, "tx": [{} for _ in range(6)], "uf": {}}
    for r in rows:
        a["sg"][r["sg"]] += 1
        for o in cat["obrigacoes"]:
            s = r["s"][o["id"]]
            a["obr"][o["id"]][s] = a["obr"][o["id"]].get(s, 0) + 1
        for c in r["al"]:
            a["al"][c] = a["al"].get(c, 0) + 1
        for k in range(6):
            s = cat["cod_tx"][r["tx6"][k]]
            a["tx"][k][s] = a["tx"][k].get(s, 0) + 1
        u = a["uf"].setdefault(r["e"]["uf"], {"n": 0, "irregular": 0, "atencao": 0, "sem_info": 0,
                                               "vencido": 0, "rem": 0, "mde": 0})
        u["n"] += 1
        for k in ("irregular", "atencao", "sem_info"):
            u[k] += r["sg"] == k
        u["vencido"] += any(c.startswith("c:t:") for c in r["al"])
        u["rem"] += r["s"].get("remuneracao_70") == "descumprida"
        u["mde"] += r["s"].get("mde_25") == "descumprida"
    return a


def gerar(d: Dados, ano: int, b: int, rows: list[dict], recorte: str, ex: dict, bim: dict, destino: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cat = d.cat
    ag = agregar(cat, rows)
    sit = lambda k: cat["situacoes"].get(k, {"rotulo": k, "nivel": "neutro"})
    cores = {"critico": "#a3262a", "atencao": "#8a5a00", "ok": "#1f6f43", "neutro": "#4d5961"}
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st = {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=3),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                             textColor=colors.HexColor("#1d5566"), spaceBefore=9, spaceAfter=3),
        "p": ParagraphStyle("p", fontName="Helvetica", fontSize=8.5, leading=11),
        "pm": ParagraphStyle("pm", fontName="Helvetica", fontSize=7.4, leading=9.4, textColor=colors.HexColor("#5a6670")),
        "c": ParagraphStyle("c", fontName="Helvetica", fontSize=7.2, leading=9),
        "cp": ParagraphStyle("cp", fontName="Helvetica", fontSize=6.5, leading=8),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=6.9, leading=8.5, textColor=colors.HexColor("#5a6670")),
    }
    P = lambda t, s="c": Paragraph(esc(t).replace("\n", "<br/>"), st[s])
    S_ = lambda k, s="c": Paragraph(f'<font color="{cores[sit(k)["nivel"]]}"><b>{esc(sit(k)["rotulo"])}</b></font>', st[s])
    W = A4[0] - 28 * mm

    def tabela(cab, linhas, larg=None, fundo_cab="#e3eef1"):
        t = Table([[P(c, "th") for c in cab]] + linhas, colWidths=larg, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(fundo_cab)),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9dee2")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return t

    h = []
    h.append(Paragraph(esc(f"{cat['painel'].get('titulo') or 'Painel SIOPE e Fundeb'}: {recorte}"), st["h1"]))
    h.append(P(f"Exercício {ano} · dados até o {bim['rotulo']}{' (exercício em andamento)' if b < 6 else ''} · "
               f"situação calculada em {fd(bim['data_referencia'])} · última coleta {(bim['ultima_coleta'] or '-')[:10]}", "p"))
    h.append(P(f"Recorte: {recorte}. Fonte: dados abertos do SIOPE/FNDE. Lei 14.113/2020 (Fundeb) e Constituição Federal.", "pm"))
    if d.manifest.get("demo"):
        h.append(P(d.manifest["demo"], "p"))
    pend = []
    n_conf = sum(1 for o in cat["obrigacoes"] if o["conferir"])
    if n_conf:
        pend.append(f"{n_conf} referência(s) legal(is) marcadas [conferir] na fonte oficial.")
    if any(p["calculado"] for p in ex["prazos"]):
        pend.append(f"Prazos de transmissão calculados pela regra do {cat['prazo_regra']['dispositivo']} "
                    "[conferir cronograma oficial do FNDE].")
    if not ex.get("vaat_lista_oficial"):
        pend.append(cat["vaat_nota"])
    if pend:
        h.append(Spacer(1, 4))
        h.append(tabela(["Conferir antes de usar em prestação de contas"], [[P(x)] for x in pend], [W], "#fbefd6"))

    h.append(Paragraph("Resumo", st["h2"]))
    tb = ag["tx"][b - 1]
    sg = ag["sg"]
    h.append(tabela(["Entes", "Irregulares", "Atenção", "Regulares", "Sem dados", f"{b}º bim. transmitido"],
                    [[P(fmt_int(ag["total"])), P(f"{fmt_int(sg['irregular'])} ({pct(sg['irregular'], ag['total'])})"),
                      P(f"{fmt_int(sg['atencao'])} ({pct(sg['atencao'], ag['total'])})"),
                      P(f"{fmt_int(sg['regular'])} ({pct(sg['regular'], ag['total'])})"), P(fmt_int(sg["sem_info"])),
                      P(f"{fmt_int(tb.get('no_prazo', 0) + tb.get('fora_prazo', 0) + tb.get('sem_data', 0))} "
                        f"({fmt_int(tb.get('atrasado', 0))} vencidos sem envio)")]], [W / 6] * 6))

    h.append(Paragraph("Cumprimento das obrigações", st["h2"]))
    h.append(P("Valores acumulados até o bimestre de referência. Obrigações anuais se fecham no 6º bimestre. "
               "[conferir] = referência legal a conferir na fonte oficial.", "pm"))
    ks = [("cumprida", "Cumpr."), ("descumprida", "Descumpr."), ("parcial_ok", "No rumo"),
          ("parcial_abaixo", "Fora (parc.)"), ("apuracao_anual", "Apur. 6º bim."), ("sem_dados", "Sem dados"),
          ("nao_aplica", "N/A")]
    linhas = []
    for o in cat["obrigacoes"]:
        if o["tipo"] == "informativo":
            continue
        c = ag["obr"][o["id"]]
        bons = c.get("cumprida", 0) + c.get("parcial_ok", 0)
        ruins = c.get("descumprida", 0) + c.get("parcial_abaixo", 0)
        txt = f"{o['titulo']}\n{o['obrigacao']}\n{o['dispositivo']}{' [conferir]' if o['conferir'] else ''}"
        linhas.append([P(o["cod_exib"]), P(txt, "cp"), P(o["regra"], "cp")] +
                      [P(fmt_int(c[k]) if c.get(k) else "-") for k, _ in ks] + [P(pct(bons, bons + ruins))])
    h.append(tabela(["Ind.", "Obrigação e dispositivo", "Regra"] + [r for _, r in ks] + ["Cumpr. %"], linhas,
                    [9 * mm, W - 9 * mm - 22 * mm - 8 * 12.5 * mm, 22 * mm] + [12.5 * mm] * 8))

    h.append(Paragraph("Sinais de alerta", st["h2"]))
    itens = sorted(((alerta_info(cat, c), n) for c, n in ag["al"].items()),
                   key=lambda x: (x[0]["nivel"] != "critico", -x[1]))
    if itens:
        h.append(tabela(["Nível", "Alerta", "Base legal", "Entes"],
                        [[Paragraph(f'<font color="{cores[a["nivel"]]}"><b>{"Crítico" if a["nivel"] == "critico" else "Atenção"}</b></font>', st["c"]),
                          P(a["titulo"]), P(a["base"]), P(fmt_int(n))] for a, n in itens],
                        [18 * mm, W - 18 * mm - 60 * mm - 16 * mm, 60 * mm, 16 * mm]))
    else:
        h.append(P("Nenhum sinal de alerta no recorte.", "p"))

    h.append(Paragraph("Prazos de transmissão ao SIOPE", st["h2"]))
    h.append(P(f"{cat['prazo_regra']['dispositivo']}. Consequência do atraso: {cat['prazo_regra']['consequencia']}", "pm"))
    cs = [("no_prazo", "No prazo"), ("fora_prazo", "Após o prazo"), ("atrasado", "Vencido sem envio"),
          ("aguardando", "Dentro do prazo"), ("em_curso", "Em curso")]
    h.append(tabela(["Bimestre", "Prazo"] + [r for _, r in cs],
                    [[P(f"{k + 1}º bimestre"), P(f"{fd(p['data'])} ({'calculado' if p['calculado'] else 'oficial'})")] +
                     [P(fmt_int(ag["tx"][k][c]) if ag["tx"][k].get(c) else "-") for c, _ in cs]
                     for k, p in enumerate(ex["prazos"])]))

    ufs = sorted(ag["uf"].items(), key=lambda x: -x[1]["irregular"] / x[1]["n"])
    if len(ufs) > 1:
        h.append(Paragraph("Comparativo por UF", st["h2"]))
        h.append(tabela(["UF", "Entes", "Irregulares", "Atenção", "Vencido sem envio", "Remun. 70% descumpr.",
                         "MDE 25% descumpr.", "Sem dados"],
                        [[P(uf), P(fmt_int(u["n"])), P(f"{fmt_int(u['irregular'])} ({pct(u['irregular'], u['n'])})"),
                          P(fmt_int(u["atencao"])), P(fmt_int(u["vencido"])), P(fmt_int(u["rem"])), P(fmt_int(u["mde"])),
                          P(fmt_int(u["sem_info"]))] for uf, u in ufs]))

    irr = sorted((r for r in rows if r["sg"] == "irregular"),
                 key=lambda r: (-r["nc"], -r["na"], r["e"]["uf"], r["e"]["nome"]))
    h.append(Paragraph(f"Entes irregulares ({fmt_int(len(irr))})", st["h2"]))
    if irr:
        obr = [o for o in cat["obrigacoes"] if o["tipo"] != "informativo" and o["unidade"] == "%"
               and (not o.get("a_partir_de") or ano >= o["a_partir_de"]) and o["id"] != "destinacao_estado_20"]
        larg_o = 15 * mm
        h.append(tabela(["Ente", "UF", "Alertas críticos"] + [o["curto"] for o in obr],
                        [[P(r["e"]["nome"], "cp"), P(r["e"]["uf"], "cp"),
                          P("; ".join(alerta_info(cat, c)["titulo"] for c in r["al"] if c.startswith("c:")), "cp")] +
                         [Paragraph(f'<font color="{cores[sit(r["s"][o["id"]])["nivel"]]}">{fv(r["v"][o["id"]], "%")}</font>', st["cp"])
                          for o in obr] for r in irr],
                        [36 * mm, 9 * mm, W - 45 * mm - larg_o * len(obr)] + [larg_o] * len(obr)))
    else:
        h.append(P("Nenhum ente irregular no recorte.", "p"))
    at = sum(1 for r in rows if r["sg"] == "atencao")
    if at:
        h.append(P(f"Entes em atenção no recorte: {fmt_int(at)}. A lista completa está no painel, filtro Situação = Atenção.", "pm"))

    h.append(Paragraph("Verificação documental (obrigações que o SIOPE não mede)", st["h2"]))
    h.append(tabela(["Feito", "Obrigação", "Base legal"],
                    [[P("[  ]"), P(f"{x['titulo']}\n{x['descricao']}"), P(x["dispositivo"])] for x in cat["documentais"]],
                    [12 * mm, W - 67 * mm, 55 * mm]))

    h.append(Paragraph("Fonte e integridade", st["h2"]))
    fl = cat["fontes_legais"]
    h.append(P(f"Normas: Lei 14.113/2020 ({fl.get('lei_14113', '')}); Constituição Federal ({fl.get('cf', '')}).", "pm"))
    h.append(P(f"Identificador dos dados (SHA-256 de {bim['arquivo']}): {bim['sha256']}. É o mesmo identificador exibido "
               f"no painel para este exercício e bimestre. PDF gerado em lote em "
               f"{datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}.", "pm"))
    if cat["painel"].get("url_publica"):
        h.append(P(f"Painel: {cat['painel']['url_publica']}", "pm"))
    h.append(Spacer(1, 14))
    h.append(P("Ciência / visto: ______________________________________   Data: ____/____/______", "p"))

    rodape = f"{recorte[:70]} · {ano} · {b}º bim. · dados {bim['sha256'][:12].upper()}"

    def pagina(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(colors.HexColor("#5a6670"))
        canvas.drawString(14 * mm, 8 * mm, rodape)
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Página {doc.page}")
        canvas.restoreState()

    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=15 * mm, title=f"SIOPE e Fundeb: {recorte}",
                            subject=f"Exercício {ano}, {bim['rotulo']}",
                            keywords=f"SIOPE; Fundeb; Lei 14.113/2020; {bim['sha256']}")
    doc.build(h, onFirstPage=pagina, onLaterPages=pagina)
    return destino


def gerar_lote(site: Path, brasil: bool = True, ufs: bool = True, log=print) -> list[dict]:
    """Para cada exercício, PDFs do bimestre mais recente: Brasil e cada UF. Grava em site/relatorios/."""
    d = Dados(site)
    gerados = []
    for ex in d.manifest["exercicios"]:
        ano = ex["ano"]
        b = ex.get("bimestre_padrao") or ex["bimestres"][-1]["bimestre"]
        ex_, bim, rows = d.periodo(ano, b)
        alvos = []
        if brasil:
            alvos.append(("BR", "Brasil (todos os entes)", rows))
        if ufs:
            for sigla in sorted(d.cat["ufs"]):
                alvos.append((sigla, d.cat["ufs"][sigla]["nome"], [r for r in rows if r["e"]["uf"] == sigla]))
        for chave, recorte, rr in alvos:
            arq = site / "relatorios" / str(ano) / f"siope-fundeb_{ano}_b{b}_{chave}.pdf"
            gerar(d, ano, b, rr, recorte, ex_, bim, arq)
            gerados.append({"ano": ano, "bimestre": b, "recorte": recorte, "chave": chave,
                            "arquivo": arq.relative_to(site).as_posix(), "sha256_dados": bim["sha256"]})
        log(f"  {ano} {b}º bim.: {len(alvos)} PDF(s) em lote")
    (site / "relatorios" / "indice.json").write_text(json.dumps(gerados, ensure_ascii=False, indent=1), encoding="utf-8")
    return gerados
