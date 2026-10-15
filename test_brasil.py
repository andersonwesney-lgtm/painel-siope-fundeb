"""Testes do painel nacional. Usam dados FICTÍCIOS (tests/sintetico.py)."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from siope_brasil import cli, coleta, config, pdf_lote, processa

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 9)


@pytest.fixture()
def projeto(tmp_path):
    for d in ("config", "web"):
        shutil.copytree(RAIZ / d, tmp_path / d)
    (tmp_path / "dados" / "importados").mkdir(parents=True)
    return tmp_path


def grava(cfg, ano, b, uf, recurso, linhas, nomes=None):
    coleta.gravar_json_gz(coleta.caminho(cfg, ano, b, uf, recurso),
                          {"coletado_em": "2026-01-01T00:00:00+00:00", "linhas": linhas, "nomes": nomes or {}})


def obr(cfg, i):
    return next(o for o in cfg.obrigacoes if o["id"] == i)


def test_regras_basicas(projeto):
    cfg = config.carregar(projeto)
    o = obr(cfg, "remuneracao_70")
    assert processa.avaliar(o, "municipal", {"1.2": 70.0}, 2025, 6, "?")[0] == "cumprida"
    assert processa.avaliar(o, "municipal", {"1.2": 69.99}, 2025, 6, "?")[0] == "descumprida"
    assert processa.avaliar(o, "municipal", {"1.2": 60.0}, 2026, 2, "?")[0] == "parcial_abaixo"
    assert processa.avaliar(o, "municipal", {}, 2025, 6, "?")[0] == "sem_dados"
    o10 = obr(cfg, "nao_aplicado_10")
    assert processa.avaliar(o10, "municipal", {"1.4": 40.0}, 2026, 2, "?")[0] == "apuracao_anual"
    assert processa.avaliar(o10, "municipal", {"1.4": 10.5}, 2025, 6, "?")[0] == "descumprida"
    est = obr(cfg, "destinacao_estado_20")
    assert processa.avaliar(est, "municipal", {"1.8": 20.0}, 2025, 6, "?")[0] == "nao_aplica"
    ti = obr(cfg, "tempo_integral_4")
    assert processa.avaliar(ti, "municipal", {"1.9": 1.0}, 2025, 6, "?")[0] == "nao_aplica"  # só a partir de 2026
    assert processa.avaliar(ti, "municipal", {"1.9": 1.0}, 2026, 6, "?")[0] == "descumprida"


def test_vaat(projeto):
    cfg = config.carregar(projeto)
    o = obr(cfg, "vaat_capital_15")
    assert processa.situacao_vaat("140005", {"1.5": 0, "1.6": 0, "1.7": 0}, None) == "nao_inf"
    assert processa.situacao_vaat("140005", {"1.5": 0, "1.7": 50}, None) == "sim_inf"
    assert processa.situacao_vaat("140005", {}, {"140005"}) == "sim"
    assert processa.avaliar(o, "municipal", {"1.5": 10}, 2025, 6, "nao_inf")[0] == "nao_aplica"
    assert processa.avaliar(o, "municipal", {"1.5": 10}, 2025, 6, "sim_inf")[0] == "descumprida"
    (projeto / "dados" / "importados" / "vaat_2025.csv").write_text("ente\n140005\nRR\n", encoding="utf-8")
    assert processa.beneficiarios_vaat(cfg, 2025) == {"140005", "UF-RR"}


def test_prazos(projeto):
    cfg = config.carregar(projeto)
    assert processa.prazo_bimestre(cfg, 2024, 1)["data"] == "2024-03-30"
    cfg.prazos["cronograma_oficial"] = {2026: {1: {"data": "2026-04-15", "ato": "ato de teste"}}}
    p = processa.prazo_bimestre(cfg, 2026, 1)
    assert p["data"] == "2026-04-15" and not p["calculado"]
    assert coleta.bimestres_encerrados(2026, HOJE) == [1, 2, 3, 4]


def test_processamento_e_nao_transmissao(projeto):
    cfg = config.carregar(projeto)
    cfg.exercicios_cfg = {"lista": [2026]}
    cfg.coleta["usar_lista_ibge"] = True
    coleta.gravar_json_gz(cfg.dir_brutos / "ibge_municipios.json.gz",
                          {"municipios": [["149001", "Município Teste A", "RR"], ["149002", "Município Teste B", "RR"],
                                          ["530010", "Brasília", "DF"]]})
    for b in (1, 2, 3, 4):
        grava(cfg, 2026, b, "RR", "dados_gerais",
              [["M", 149001, "Município Teste A", f"2026-{2 * b + 1:02d}-10", False, 1, 1000]] if b < 4 else [])
        grava(cfg, 2026, b, "RR", "indicadores",
              [["M", 149001, "Município Teste A", "1.2", "65.0"]] if b < 4 else [], {"1.2": "Remuneração"})
    m = processa.processar(cfg, projeto / "site", HOJE)
    dados = json.loads((projeto / "site" / "dados" / "2026" / "b3.json").read_text(encoding="utf-8"))
    ix = {c: i for i, c in enumerate(dados["colunas"])}
    linhas = {l[ix["id"]]: l for l in dados["linhas"]}
    assert "530010" not in linhas  # Brasília: o DF declara como ente distrital
    a, b_ = linhas["149001"], linhas["149002"]
    assert a[ix["s.remuneracao_70"]] == "parcial_abaixo" and a[ix["tx6"]].startswith("nnn")
    assert b_[ix["sg"]] == "irregular" and "c:t:1" in b_[ix["al"]]  # nunca transmitiu
    assert linhas["UF-SP"][ix["tx6"]][0] == "x"  # SP não consultada: não conclui atraso
    ex = m["exercicios"][0]
    assert ex["bimestres"][-1]["bimestre"] == 4 and ex["bimestres"][-1]["entes_com_indicadores"] == 0
    assert ex["bimestre_padrao"] == 4  # nenhum bimestre com metade dos entes: fica no mais recente


def test_site_completo_e_pdf_com_mesmo_identificador(projeto):
    import sys
    sys.path.insert(0, str(RAIZ / "tests"))
    import sintetico

    cfg = config.carregar(projeto)
    cfg.exercicios_cfg = {"lista": [2026]}
    sintetico.gerar(cfg, [2026], HOJE, escala=0.05)
    cli.construir_site(cfg, projeto / "site", HOJE, lote=False)
    d = pdf_lote.Dados(projeto / "site")
    b = d.manifest["exercicios"][0]["bimestre_padrao"]
    ex, bim, rows = d.periodo(2026, b)
    arq = pdf_lote.gerar(d, 2026, b, [r for r in rows if r["e"]["uf"] == "MG"], "Minas Gerais", ex, bim, projeto / "mg.pdf")
    assert bim["sha256"].encode() in arq.read_bytes()
    assert (projeto / "site" / "index.html").exists() and (projeto / "site" / "app.js").exists()
    manifest = json.loads((projeto / "site" / "dados" / "manifest.json").read_text(encoding="utf-8"))
    assert next(x for x in manifest["exercicios"][0]["bimestres"] if x["bimestre"] == b)["sha256"] == bim["sha256"]


def test_compactar_api():
    regs = [{"TIPO": "Municipal", "COD_MUNI": 140005, "NOM_MUNI": "X", "COD_EXIB": "1.2", "NOM_INDI": "Rem", "VAL_INDI": "84.41"},
            {"TIPO": "Estadual", "COD_MUNI": None, "NOM_MUNI": None, "COD_EXIB": "1.1", "NOM_INDI": "MDE", "VAL_INDI": "27"}]
    linhas, nomes = coleta.compactar("indicadores", regs)
    assert linhas[0] == ["M", 140005, "X", "1.2", "84.41"] and linhas[1][0] == "E" and nomes["1.2"] == "Rem"
