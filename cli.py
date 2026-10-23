"""Linha de comando.

  python -m siope_brasil coletar      baixa da API do SIOPE (todas as UFs) e a lista do IBGE
  python -m siope_brasil gerar        processa, monta site/ (painel + dados) e os PDFs em lote
  python -m siope_brasil tudo         coletar + gerar
  python -m siope_brasil recibos      consulta só os Recibos de Transmissão que faltam (sem captcha)
  python -m siope_brasil diario       rotina diária: API + recibos + site + validação + registro
                                      (código de saída 1 = não publicar; usado no GitHub Actions)
  python -m siope_brasil pdf --uf MG  um PDF em lote sob demanda (Brasil, UF), a partir de site/
  python -m siope_brasil servir       abre o painel em http://localhost:8000
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

from . import coleta, config, pdf_lote, processa, recibos, rotina
from .territorio import SIGLAS


def construir_site(cfg, saida: Path, hoje: date, demo: str | None = None, lote: bool = True) -> None:
    if saida.exists():
        shutil.rmtree(saida)
    shutil.copytree(cfg.raiz / "web", saida)
    (saida / ".nojekyll").write_text("", encoding="utf-8")
    print("Processando regras para todos os entes...")
    processa.processar(cfg, saida, hoje, demo=demo)
    if lote and (cfg.pdf_lote.get("brasil", True) or cfg.pdf_lote.get("ufs", True)):
        print("Gerando PDFs em lote...")
        pdf_lote.gerar_lote(saida, cfg.pdf_lote.get("brasil", True), cfg.pdf_lote.get("ufs", True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="siope_brasil", description="Painel nacional SIOPE x Lei 14.113/2020")
    ap.add_argument("--raiz", help="pasta do projeto (padrão: a deste pacote)")
    ap.add_argument("--data-ref", help="data de referência AAAA-MM-DD (padrão: hoje)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coletar")
    c.add_argument("--anos", type=int, nargs="*")
    c.add_argument("--ufs", nargs="*", choices=SIGLAS)
    c.add_argument("--forcar", action="store_true", help="baixa de novo mesmo o que já existe")
    g = sub.add_parser("gerar")
    g.add_argument("--saida", default="site")
    g.add_argument("--sem-pdf", action="store_true", help="não gera os PDFs em lote")
    sub.add_parser("recibos")
    d = sub.add_parser("diario")
    d.add_argument("--saida", default="site")
    d.add_argument("--sem-pdf", action="store_true")
    t = sub.add_parser("tudo")
    t.add_argument("--saida", default="site")
    p = sub.add_parser("pdf")
    p.add_argument("--saida", default="site", help="pasta do site já gerado")
    p.add_argument("--ano", type=int)
    p.add_argument("--bimestre", type=int, choices=range(1, 7))
    p.add_argument("--uf", choices=SIGLAS, help="omita para Brasil")
    p.add_argument("--arquivo")
    s = sub.add_parser("servir")
    s.add_argument("--saida", default="site")
    s.add_argument("--porta", type=int, default=8000)

    a = ap.parse_args(argv)
    cfg = config.carregar(Path(a.raiz) if a.raiz else None)
    hoje = date.fromisoformat(a.data_ref) if a.data_ref else date.today()
    saida = Path(getattr(a, "saida", "site"))
    saida = saida if saida.is_absolute() else cfg.raiz / saida

    if a.cmd == "recibos":
        r = recibos.atualizar(cfg, hoje)
        return 1 if r["status"] == "falha" else 0
    if a.cmd == "diario":
        return rotina.executar(cfg, saida, hoje,
                               lambda s: construir_site(cfg, s, hoje, lote=not a.sem_pdf))
    if a.cmd in ("coletar", "tudo"):
        anos = getattr(a, "anos", None) or cfg.exercicios(hoje)
        print(f"Coletando SIOPE: exercícios {anos}...")
        r = coleta.coletar(cfg, anos, hoje, getattr(a, "ufs", None), getattr(a, "forcar", False))
        print(f"{r['gravadas']} consulta(s) gravada(s), {r['puladas']} reaproveitada(s), {len(r['falhas'])} falha(s).")
        for f in r["falhas"][:20]:
            print("  " + f, file=sys.stderr)
    if a.cmd in ("gerar", "tudo"):
        construir_site(cfg, saida, hoje, lote=not getattr(a, "sem_pdf", False))
        print(f"Pronto: {saida}. Para ver: python -m siope_brasil servir")
    if a.cmd == "pdf":
        d = pdf_lote.Dados(saida)
        ex = d.manifest["exercicios"][-1] if not a.ano else next(e for e in d.manifest["exercicios"] if e["ano"] == a.ano)
        b = a.bimestre or ex.get("bimestre_padrao") or ex["bimestres"][-1]["bimestre"]
        ex_, bim, rows = d.periodo(ex["ano"], b)
        recorte = d.cat["ufs"][a.uf]["nome"] if a.uf else "Brasil (todos os entes)"
        if a.uf:
            rows = [r for r in rows if r["e"]["uf"] == a.uf]
        destino = Path(a.arquivo) if a.arquivo else cfg.raiz / "relatorios" / f"siope-fundeb_{ex['ano']}_b{b}_{a.uf or 'BR'}.pdf"
        pdf_lote.gerar(d, ex["ano"], b, rows, recorte, ex_, bim, destino)
        print(f"PDF gerado: {destino}")
    if a.cmd == "servir":
        import functools
        import http.server

        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(saida))
        print(f"Painel em http://localhost:{a.porta} (Ctrl+C para sair)")
        http.server.ThreadingHTTPServer(("127.0.0.1", a.porta), h).serve_forever()
    return 0
