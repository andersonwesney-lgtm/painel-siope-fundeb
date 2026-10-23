"""Testes dos Recibos de Transmissão e da rotina diária. HTML e dados FICTÍCIOS no formato da página real."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from siope_brasil import coleta, config, processa, recibos, rotina

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 23)

PAGINA = """<html><body><script>var x = "<tr><td>lixo</td></tr>";</script>
<table><tr><td>UF:</td><td><select><option>Alagoas</option></select></td></tr></table>
<table>
<tr><th>Per&iacute;odo</th><th>Situa&ccedil;&atilde;o</th><th>N&ordm; do Recibo</th><th>Data de Processamento</th>
<th>Data de Transmiss&atilde;o</th><th>Declara&ccedil;&atilde;o Retificadora</th><th>MAVS</th></tr>
<tr><td>2026 - 4&ordm; Bimestre</td><td>Processado com sucesso <br/>Com manifestação do CACS</td><td>454170</td>
<td>13/10/2026 17:02</td><td>08/10/2026 15:41</td><td>Não</td><td><a>Hist&oacute;rico</a></td></tr>
<tr><td>2026 - 3&ordm; Bimestre</td><td>Processado com sucesso</td><td>450572</td>
<td>14/09/2026 10:01</td><td>10/09/2026 15:11</td><td>Sim</td><td>Hist&oacute;rico</td></tr>
<tr><td>2025 - Anual</td><td>Processado com sucesso</td><td>431631</td>
<td>18/03/2026 11:31</td><td>13/03/2026 17:05</td><td>Não</td><td>Hist&oacute;rico</td></tr>
</table>
<table><tr><th>Protocolo</th><th>Data de Transmiss&atilde;o</th><th>Data de Atua&ccedil;&atilde;o</th><th>Status</th></tr>
<tr><td>Dados n&atilde;o encontrados</td></tr></table></body></html>"""


@pytest.fixture()
def projeto(tmp_path):
    for d in ("config", "web"):
        shutil.copytree(RAIZ / d, tmp_path / d)
    (tmp_path / "dados" / "importados").mkdir(parents=True)
    cfg = config.carregar(tmp_path)
    cfg.exercicios_cfg = {"lista": [2026]}
    coleta.gravar_json_gz(cfg.dir_brutos / "ibge_municipios.json.gz",
                          {"municipios": [["270170", "Capela", "AL"], ["270020", "Anadia", "AL"]]})
    for b in (1, 2, 3, 4):
        dg = [["M", 270020, "Anadia", "2026-09-25" if b == 4 else f"2026-{2 * b + 1:02d}-10", False, 9, 1000]]
        if b < 4:
            dg.append(["M", 270170, "Capela", f"2026-{2 * b + 1:02d}-20", False, 8, 2000])
        coleta.gravar_json_gz(coleta.caminho(cfg, 2026, b, "AL", "dados_gerais"),
                              {"coletado_em": "2026-10-23T00:00:00+00:00", "linhas": dg, "nomes": {}})
        coleta.gravar_json_gz(coleta.caminho(cfg, 2026, b, "AL", "indicadores"),
                              {"coletado_em": "2026-10-23T00:00:00+00:00", "nomes": {"1.2": "Remuneração"},
                               "linhas": [["M", 270020, "Anadia", "1.2", "72"], ["M", 270170, "Capela", "1.2", "71"]]})
    return cfg


def test_le_a_tabela_real():
    rs = recibos.ler_tabela(PAGINA, HOJE)
    assert [(r["ano"], r["bimestre"]) for r in rs] == [(2026, 4), (2026, 3), (2025, 6)]
    assert rs[0]["transmitido_em"] == "2026-10-08T15:41" and rs[0]["recibo"] == "454170" and rs[0]["valido"]
    assert rs[1]["retificadora"] and not rs[0]["retificadora"]


@pytest.mark.parametrize("pagina", [
    "<html><div class='g-recaptcha'></div><script src='https://www.google.com/recaptcha/api.js'></script></html>",
    PAGINA.replace("Data de Transmiss&atilde;o</th>", "Transmitido em</th>", 1),
    PAGINA.replace("08/10/2026 15:41", "ontem"),
    PAGINA.replace("08/10/2026 15:41", "08/10/2031 15:41"),
])
def test_formato_estranho_e_recusado(pagina):
    with pytest.raises(recibos.FonteMudou):
        recibos.ler_tabela(pagina, HOJE)


class ClienteFalso:
    def __init__(self, paginas):
        self.paginas, self.chamadas = paginas, []

    def municipio(self, cod_uf, cod_muni):
        self.chamadas.append(cod_muni)
        p = self.paginas.get(cod_muni)
        if isinstance(p, Exception):
            raise p
        return p

    def estado(self, cod_uf):
        self.chamadas.append("UF" + cod_uf)
        return PAGINA.replace("454170", "1").replace("08/10/2026", "20/09/2026")


def test_capela_corrigida_sem_duplicar(projeto, monkeypatch):
    cfg = projeto
    cfg.recibos.update(pausa_entre_consultas_s=0, incluir_estados=False)
    falso = ClienteFalso({"270170": PAGINA})
    monkeypatch.setattr(recibos, "Cliente", lambda *a, **k: falso)

    alvos = recibos.alvos(cfg, HOJE, recibos.carregar(cfg))
    assert [a[0] for a in alvos] == ["270170"]  # só quem falta na base aberta (Anadia já está lá)

    r1 = recibos.atualizar(cfg, HOJE, log=lambda *_: None)
    assert r1["novos"] == 3 and r1["status"] == "ok"
    conteudo = recibos.arquivo(cfg).read_text(encoding="utf-8")

    # mesma execução no mesmo dia: não consulta de novo, não muda nada
    r2 = recibos.atualizar(cfg, HOJE, log=lambda *_: None)
    assert r2["alvos"] == 0 and recibos.arquivo(cfg).read_text(encoding="utf-8") == conteudo
    assert falso.chamadas == ["270170"]

    # dia seguinte: Capela já tem recibo do 4º bim., então nem entra na lista
    assert recibos.alvos(cfg, date(2026, 10, 24), recibos.carregar(cfg)) == []

    p = processa.carregar_periodo(cfg, 2026, 4)
    assert p["dg"]["270170"]["data"] == "2026-10-08" and p["dg"]["270170"]["fonte"] == "recibo"
    assert p["n_recibos"] == 1
    m = processa.processar(cfg, cfg.raiz / "site", HOJE, log=lambda *_: None)
    dados = json.loads((cfg.raiz / "site" / "dados" / "2026" / "b4.json").read_text(encoding="utf-8"))
    ix = {c: k for k, c in enumerate(dados["colunas"])}
    capela = next(l for l in dados["linhas"] if l[ix["id"]] == "270170")
    assert capela[ix["tb"]] == "fora_prazo" and capela[ix["td"]] == "2026-10-08"
    assert m["exercicios"][0]["bimestres"][-1]["via_recibo"] == 1


def test_pagina_mudou_mantem_o_que_havia(projeto, monkeypatch):
    cfg = projeto
    cfg.recibos.update(pausa_entre_consultas_s=0, incluir_estados=False, parar_apos_falhas_seguidas=1)
    monkeypatch.setattr(recibos, "Cliente", lambda *a, **k: ClienteFalso({"270170": PAGINA}))
    recibos.atualizar(cfg, HOJE, log=lambda *_: None)
    antes = recibos.arquivo(cfg).read_text(encoding="utf-8")

    estado = recibos.carregar(cfg)
    estado["registros"] = {k: v for k, v in estado["registros"].items() if not k.endswith("|2026|4")}
    estado["consultados"] = {}
    recibos.gravar(cfg, estado)
    monkeypatch.setattr(recibos, "Cliente",
                        lambda *a, **k: ClienteFalso({"270170": "<html>captcha recaptcha</html>"}))
    r = recibos.atualizar(cfg, date(2026, 10, 24), log=lambda *_: None)
    assert r["status"] == "falha" and "captcha" in r["mensagem"]
    depois = recibos.carregar(cfg)
    assert "270170|2026|3" in depois["registros"]  # o que já estava guardado continua
    assert antes  # e nada inválido foi gravado no lugar


def test_rotina_nao_publica_site_suspeito(projeto, monkeypatch):
    cfg = projeto
    cfg.recibos["ativo"] = False
    monkeypatch.setattr(coleta, "coletar", lambda *a, **k: {"gravadas": 4, "puladas": 0, "falhas": []})
    saida = cfg.raiz / "site"

    def construir(s):
        shutil.copytree(cfg.raiz / "web", s, dirs_exist_ok=True)
        processa.processar(cfg, s, HOJE, log=lambda *_: None)

    # catálogo com 2 municípios: abaixo do mínimo nacional -> não publica
    assert rotina.executar(cfg, saida, HOJE, construir, log=lambda *_: None) == 1
    st = json.loads((cfg.dir_estado / "ultimo_status.json").read_text(encoding="utf-8"))
    assert st["status"] == "falha" and "municípios" in st["erro"]

    cfg.validacao["municipios_minimos"] = 2
    assert rotina.executar(cfg, saida, HOJE, construir, log=lambda *_: None) == 0
    assert (saida / "dados" / "execucoes.json").exists()
    hist = (cfg.dir_estado / "execucoes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(hist) == 2 and json.loads(hist[-1])["status"] == "ok"

    # queda brusca de entes com dados em relação à última publicação -> não publica
    pub = json.loads((cfg.dir_estado / "ultima_publicacao.json").read_text(encoding="utf-8"))
    pub["entes_com_dados"] = {k: 1000 for k in pub["entes_com_dados"]}
    (cfg.dir_estado / "ultima_publicacao.json").write_text(json.dumps(pub), encoding="utf-8")
    assert rotina.executar(cfg, saida, HOJE, construir, log=lambda *_: None) == 1
