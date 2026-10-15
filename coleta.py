"""Coleta nacional na API de dados abertos do SIOPE (FNDE) e na lista de municípios do IBGE.

API: https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata/
A API é consultada por exercício, bimestre e UF; cada consulta devolve o estado
e todos os municípios da UF. São 27 UFs x 6 bimestres x 2 recursos por exercício.

  Indicadores_Siope  -> mesmos indicadores do "Relatório de Indicadores" do SIOPE
                        (página com captcha, não usada), numeração COD_EXIB 1.1, 1.2...
  Dados_Gerais_Siope -> data da declaração, retificação, recibo e população

Cada consulta bem-sucedida vira um arquivo .json.gz em
dados/brutos/<ano>/b<bimestre>/<UF>_<recurso>.json.gz, mesmo quando vem vazia:
assim o processamento distingue "UF consultada e ente ausente" (não transmitiu)
de "UF não consultada".
"""
from __future__ import annotations

import gzip
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Config
from .territorio import SIGLAS, uf_do_municipio

BASE_API = "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata"
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
RECURSOS = {"indicadores": "Indicadores_Siope", "dados_gerais": "Dados_Gerais_Siope"}
SELECT = {
    "indicadores": "TIPO,COD_MUNI,NOM_MUNI,COD_EXIB,NOM_INDI,VAL_INDI",
    "dados_gerais": "TIPO,COD_MUNI,NOM_MUNI,DAT_DECL,IDN_DECL_RETI,NUM_RECI,NUM_POPU",
}
PAGINA = 10000


class ErroColeta(RuntimeError):
    pass


def bimestres_encerrados(ano: int, hoje: date) -> list[int]:
    if ano < hoje.year:
        return list(range(1, 7))
    if ano > hoje.year:
        return []
    return [b for b in range(1, 7) if hoje.month > 2 * b]


def caminho(cfg: Config, ano: int, b: int, uf: str, recurso: str) -> Path:
    return cfg.dir_brutos / str(ano) / f"b{b}" / f"{uf}_{recurso}.json.gz"


def gravar_json_gz(destino: Path, conteudo: dict) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(destino)


def ler_json_gz(origem: Path) -> dict | None:
    if not origem.exists():
        return None
    with gzip.open(origem, "rt", encoding="utf-8") as f:
        return json.load(f)


def _get(sessao, url, params, tentativas=5):
    espera = 2
    ultimo = None
    for i in range(tentativas):
        try:
            r = sessao.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}"
            if r.status_code in (400, 404):
                raise ErroColeta(f"{ultimo}: {r.text[:200]}")
        except ErroColeta:
            raise
        except Exception as exc:
            ultimo = str(exc)
        if i < tentativas - 1:
            time.sleep(espera)
            espera *= 2
    raise ErroColeta(ultimo or "sem resposta")


def compactar(recurso: str, regs: list[dict]) -> tuple[list[list], dict]:
    """Reduz os registros da API ao necessário. Nomes de indicador vão num dicionário à parte."""
    linhas, nomes = [], {}
    for r in regs:
        tipo = "E" if str(r.get("TIPO", "")).lower().startswith("estadual") else "M"
        muni = r.get("COD_MUNI")
        if recurso == "indicadores":
            cod = str(r.get("COD_EXIB") or "").strip()
            if not cod:
                continue
            if r.get("NOM_INDI") and cod not in nomes:
                nomes[cod] = " ".join(str(r["NOM_INDI"]).split())
            linhas.append([tipo, muni, r.get("NOM_MUNI"), cod, r.get("VAL_INDI")])
        else:
            linhas.append([tipo, muni, r.get("NOM_MUNI"), (r.get("DAT_DECL") or "")[:10] or None,
                           str(r.get("IDN_DECL_RETI") or "").upper() == "S", r.get("NUM_RECI"), r.get("NUM_POPU")])
    return linhas, nomes


def consultar(sessao, recurso: str, ano: int, b: int, uf: str) -> tuple[list[dict], str]:
    url = f"{BASE_API}/{RECURSOS[recurso]}(Ano_Consulta=@Ano_Consulta,Num_Peri=@Num_Peri,Sig_UF=@Sig_UF)"
    regs, pulo, usar_select = [], 0, True
    while True:
        params = {"@Ano_Consulta": str(ano), "@Num_Peri": str(b), "@Sig_UF": f"'{uf}'",
                  "$format": "json", "$top": str(PAGINA), "$skip": str(pulo)}
        if usar_select:
            params["$select"] = SELECT[recurso]
        try:
            lote = _get(sessao, url, params).get("value", [])
        except ErroColeta:
            if usar_select:  # alguns recursos podem recusar $select: tenta sem
                usar_select = False
                continue
            raise
        regs.extend(lote)
        if len(lote) < PAGINA:
            return regs, url
        pulo += PAGINA


def precisa_coletar(cfg: Config, ano: int, b: int, uf: str, recurso: str, hoje: date, forcar: bool) -> bool:
    if forcar or not caminho(cfg, ano, b, uf, recurso).exists():
        return True
    recentes = int(cfg.coleta.get("recoletar_ultimos_exercicios", 2))
    return ano > hoje.year - recentes


def coletar(cfg: Config, anos: list[int], hoje: date, ufs: list[str] | None = None,
            forcar: bool = False, log=print) -> dict:
    import requests

    sessao = requests.Session()
    sessao.headers["User-Agent"] = "siope-painel-brasil/2.0 (acompanhamento Fundeb)"
    pausa = float(cfg.coleta.get("pausa_entre_consultas_s", 0.3))
    resumo = {"gravadas": 0, "puladas": 0, "falhas": []}
    for ano in anos:
        for b in bimestres_encerrados(ano, hoje):
            for uf in ufs or SIGLAS:
                for recurso in RECURSOS:
                    if not precisa_coletar(cfg, ano, b, uf, recurso, hoje, forcar):
                        resumo["puladas"] += 1
                        continue
                    try:
                        regs, url = consultar(sessao, recurso, ano, b, uf)
                    except ErroColeta as exc:
                        resumo["falhas"].append(f"{ano} b{b} {uf} {recurso}: {exc}")
                        log(f"  FALHA {ano} {b}º bim. {uf} {recurso}: {exc}")
                        continue
                    linhas, nomes = compactar(recurso, regs)
                    gravar_json_gz(caminho(cfg, ano, b, uf, recurso), {
                        "fonte": "api", "url": url, "ano": ano, "bimestre": b, "uf": uf,
                        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "linhas": linhas, "nomes": nomes,
                    })
                    resumo["gravadas"] += 1
                    time.sleep(pausa)
            log(f"  {ano} {b}º bimestre: concluído")
    if cfg.coleta.get("usar_lista_ibge", True):
        try:
            coletar_ibge(cfg, sessao)
            log("  lista de municípios do IBGE atualizada")
        except ErroColeta as exc:
            resumo["falhas"].append(f"IBGE: {exc}")
    return resumo


def coletar_ibge(cfg: Config, sessao) -> None:
    dados = _get(sessao, IBGE_MUNICIPIOS, {})
    municipios = []
    for m in dados:  # aceita o formato "nivelado" e o formato padrão da API do IBGE
        cod = str(m.get("municipio-id") or m.get("id") or "")
        nome = m.get("municipio-nome") or m.get("nome")
        if len(cod) == 7 and nome:
            municipios.append([cod[:6], nome, uf_do_municipio(cod)])
    if len(municipios) < 5000:
        raise ErroColeta(f"lista do IBGE incompleta ({len(municipios)} municípios)")
    gravar_json_gz(cfg.dir_brutos / "ibge_municipios.json.gz", {
        "fonte": IBGE_MUNICIPIOS,
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios,
    })
