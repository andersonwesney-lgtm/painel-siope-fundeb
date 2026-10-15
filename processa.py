"""Regras e processamento nacional.

Para cada exercício e bimestre, avalia todos os entes (municípios, estados e DF)
e grava arquivos compactos em site/dados/. Toda a lógica de cumprimento, prazos
e alertas está AQUI. O painel (JavaScript) e os PDFs (Python e navegador) só
leem o resultado; nenhum deles recalcula situação.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import coleta
from .config import Config
from .territorio import SIGLAS, SIGLA_PARA_COD, UFS, id_estado, uf_do_municipio

NOMES_BIMESTRE = {1: "jan-fev", 2: "mar-abr", 3: "mai-jun", 4: "jul-ago", 5: "set-out", 6: "nov-dez"}

# chave: (rótulo, nível). Níveis: ok | atencao | critico | neutro
SITUACOES = {
    "cumprida": ("Cumprida", "ok"),
    "descumprida": ("Descumprida", "critico"),
    "parcial_ok": ("No rumo (parcial)", "ok"),
    "parcial_abaixo": ("Fora da regra (parcial)", "atencao"),
    "apuracao_anual": ("Apurado no 6º bimestre", "neutro"),
    "verificar": ("Verificar", "atencao"),
    "sem_dados": ("Sem dados", "neutro"),
    "nao_aplica": ("Não se aplica", "neutro"),
    "informativo": ("Acompanhamento", "neutro"),
    # transmissões
    "no_prazo": ("Transmitido no prazo", "ok"),
    "fora_prazo": ("Transmitido após o prazo", "atencao"),
    "atrasado": ("Não transmitido, prazo vencido", "critico"),
    "aguardando": ("Dentro do prazo", "neutro"),
    "em_curso": ("Bimestre em curso", "neutro"),
    "nao_consultado": ("Não consultado", "neutro"),
    "sem_data": ("Transmitido, data não informada", "neutro"),
    # situação geral do ente
    "irregular": ("Irregular", "critico"),
    "atencao": ("Atenção", "atencao"),
    "regular": ("Regular", "ok"),
    "sem_info": ("Sem dados", "neutro"),
}

# Situação de transmissão dos 6 bimestres numa string de 6 letras (coluna "tx6").
COD_TX = {"no_prazo": "n", "fora_prazo": "f", "atrasado": "a", "aguardando": "g", "em_curso": "c",
          "nao_consultado": "x", "sem_data": "s"}

# Brasília (530010) consta da lista do IBGE, mas o DF declara ao SIOPE como ente distrital.
FORA_DO_CATALOGO_MUNICIPAL = {"530010"}


def numero(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        s = str(v).strip().replace("%", "").replace("R$", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None


# --------------------------------------------------------------- prazos ----

def fim_bimestre(ano: int, b: int) -> date:
    return date(ano, 2 * b, calendar.monthrange(ano, 2 * b)[1])


def prazo_bimestre(cfg: Config, ano: int, b: int) -> dict:
    oficial = ((cfg.prazos.get("cronograma_oficial") or {}).get(ano) or {})
    item = oficial.get(b) or oficial.get(str(b))
    if item and item.get("data") and "A" not in str(item["data"]):
        return {"data": str(item["data"]), "calculado": False,
                "base": f"Cronograma oficial: {item.get('ato', 'ato não informado')}"}
    r = cfg.prazos["regra_bimestral"]
    d = fim_bimestre(ano, b) + timedelta(days=int(r["dias_apos_fim_do_bimestre"]))
    return {"data": d.isoformat(), "calculado": True,
            "base": f"{r['dispositivo']} (fim do bimestre + {r['dias_apos_fim_do_bimestre']} dias)"}


# ---------------------------------------------------------- leitura bruta ----

def _id_ente(tipo: str, muni, uf: str) -> str | None:
    if tipo == "E":
        return id_estado(uf)
    if muni in (None, ""):
        return None
    return str(int(muni)).zfill(6)


def carregar_periodo(cfg: Config, ano: int, b: int) -> dict:
    """Indicadores e declarações de um bimestre, para todas as UFs coletadas."""
    ind, dg, nomes, ufs_ind, ufs_dg, coletas = {}, {}, {}, set(), set(), []
    for uf in SIGLAS:
        bruto = coleta.ler_json_gz(coleta.caminho(cfg, ano, b, uf, "indicadores"))
        if bruto is not None:
            ufs_ind.add(uf)
            coletas.append(bruto.get("coletado_em") or "")
            for cod, nome in bruto.get("nomes", {}).items():
                nomes.setdefault(cod, nome)
            for tipo, muni, nom, cod, val in bruto["linhas"]:
                i = _id_ente(tipo, muni, uf)
                if i:
                    ind.setdefault(i, {"_nome": nom, "_uf": uf})[cod] = numero(val)
        bruto = coleta.ler_json_gz(coleta.caminho(cfg, ano, b, uf, "dados_gerais"))
        if bruto is not None:
            ufs_dg.add(uf)
            coletas.append(bruto.get("coletado_em") or "")
            for tipo, muni, nom, data, reti, recibo, pop in bruto["linhas"]:
                i = _id_ente(tipo, muni, uf)
                if not i:
                    continue
                atual = dg.get(i)
                if atual is None or (data or "") > (atual["data"] or ""):
                    dg[i] = {"data": data, "reti": bool(reti), "recibo": str(recibo or ""), "pop": pop,
                             "nome": nom, "uf": uf}
    return {"ind": ind, "dg": dg, "nomes": nomes, "ufs_ind": ufs_ind, "ufs_dg": ufs_dg,
            "ultima_coleta": max(coletas) if coletas else None}


def catalogo_entes(cfg: Config, periodos: list[dict]) -> dict:
    """Todos os entes: 27 estados/DF + municípios do IBGE + qualquer ente visto no SIOPE."""
    entes = {}
    for cod, (sigla, nome, regiao) in UFS.items():
        entes[id_estado(sigla)] = {"nome": nome if sigla == "DF" else f"{nome} (governo estadual)",
                                   "uf": sigla, "regiao": regiao, "esfera": "estadual", "pop": None}
    ibge = coleta.ler_json_gz(cfg.dir_brutos / "ibge_municipios.json.gz")
    if ibge:
        for cod, nome, uf in ibge["municipios"]:
            if cod in FORA_DO_CATALOGO_MUNICIPAL:
                continue
            entes[cod] = {"nome": nome, "uf": uf, "regiao": UFS[SIGLA_PARA_COD[uf]][2],
                          "esfera": "municipal", "pop": None}
    for p in periodos:
        for fonte in (p["ind"], p["dg"]):
            for i, d in fonte.items():
                if i in entes:
                    continue
                uf = d.get("_uf") or d.get("uf")
                entes[i] = {"nome": d.get("_nome") or d.get("nome") or i, "uf": uf,
                            "regiao": UFS[SIGLA_PARA_COD[uf]][2], "esfera": "municipal", "pop": None}
    for p in sorted(periodos, key=lambda x: (x["ano"], x["b"])):
        for i, d in p["dg"].items():
            if i in entes and d.get("pop"):
                entes[i]["pop"] = d["pop"]
    return entes


def beneficiarios_vaat(cfg: Config, ano: int) -> set[str] | None:
    arq = cfg.dir_importados / f"vaat_{ano}.csv"
    if not arq.exists():
        return None
    with open(arq, encoding="utf-8-sig") as f:
        amostra = f.read(2048)
        f.seek(0)
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
        except csv.Error:  # arquivo de uma coluna só
            dialeto = csv.excel
        leitor = csv.DictReader(f, dialect=dialeto)
        ids = set()
        for linha in leitor:
            v = str(linha.get("ente") or "").strip().upper()
            if v in SIGLAS:
                ids.add(id_estado(v))
            elif v.isdigit():
                ids.add(v[:6].zfill(6))
            elif v.startswith("UF-"):
                ids.add(v)
        return ids


# --------------------------------------------------------------- regras ----

def situacao_vaat(i: str, ind: dict | None, lista: set[str] | None) -> str:
    """sim | nao (lista oficial) | sim_inf | nao_inf (inferido dos valores) | ? (sem dados)."""
    if lista is not None:
        return "sim" if i in lista else "nao"
    if not ind:
        return "?"
    vals = [ind.get(c) for c in ("1.5", "1.6", "1.7")]
    if any(v for v in vals if v is not None and v > 0):
        return "sim_inf"
    return "nao_inf"


def avaliar(o: dict, esfera: str, ind: dict | None, ano: int, b: int, vaat: str) -> tuple[str, float | None, float | None]:
    """(situação, valor, valor de referência) de uma obrigação para um ente."""
    valor = (ind or {}).get(o["cod_exib"])
    ref = (ind or {}).get(o.get("referencia_cod_exib")) if o.get("referencia_cod_exib") else None
    if esfera not in o.get("aplica_a", ["municipal", "estadual"]) or ano < int(o.get("a_partir_de", 0)):
        return "nao_aplica", valor, ref
    if o.get("condicao") == "recebe_complementacao_vaat":
        if vaat in ("nao", "nao_inf"):
            return "nao_aplica", valor, ref
        if vaat == "?":
            return "sem_dados", valor, ref
    regra = o["regra"]
    if regra == "informativo":
        return "informativo", valor, ref
    if valor is None or (regra == "comparar_minimo" and ref is None):
        return "sem_dados", valor, ref
    if regra == "minimo":
        atende = valor >= o["limite"]
    elif regra == "maximo":
        atende = valor <= o["limite"]
    else:
        atende = valor >= ref
    if b == 6 or o.get("avaliacao") != "anual":
        return ("cumprida" if atende else "descumprida"), valor, ref
    if o.get("avaliar_parcial") is False:
        return "apuracao_anual", valor, ref
    return ("parcial_ok" if atende else "parcial_abaixo"), valor, ref


def transmissao(i: str, uf: str, p: dict, prazo: dict, ano: int, b: int, hoje: date) -> list:
    """[data, situação, retificada, recibo]"""
    if hoje <= fim_bimestre(ano, b):
        return [None, "em_curso", False, ""]
    if p is None or uf not in p["ufs_dg"]:
        return [None, "nao_consultado", False, ""]
    d = p["dg"].get(i)
    if d is None:
        return [None, "atrasado" if hoje > date.fromisoformat(prazo["data"]) else "aguardando", False, ""]
    if not d["data"]:
        return [None, "sem_data", d["reti"], d["recibo"]]
    sit = "no_prazo" if d["data"] <= prazo["data"] else "fora_prazo"
    return [d["data"], sit, d["reti"], d["recibo"]]


# ----------------------------------------------------------- saída ----

def _hash(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _gravar(destino: Path, obj) -> str:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return _hash(destino)


def catalogo(cfg: Config, nomes: dict) -> dict:
    obrig = []
    for o in cfg.obrigacoes:
        if o["regra"] == "minimo":
            regra = f"mínimo de {fmt_limite(o['limite'], o.get('unidade'))}"
        elif o["regra"] == "maximo":
            regra = f"máximo de {fmt_limite(o['limite'], o.get('unidade'))}"
        elif o["regra"] == "comparar_minimo":
            regra = f"igual ou superior ao indicador {o['referencia_cod_exib']}"
        else:
            regra = "sem limite próprio na norma"
        obrig.append({
            "id": o["id"], "cod_exib": o["cod_exib"], "titulo": o["titulo"],
            "curto": cfg.rotulos_curtos.get(o["id"], o["cod_exib"]),
            "obrigacao": " ".join(o["obrigacao"].split()), "dispositivo": o["dispositivo"],
            "fonte_url": cfg.fontes_legais.get(o.get("fonte"), ""), "regra": regra, "tipo": o["regra"],
            "unidade": o.get("unidade"), "limite": o.get("limite"),
            "referencia_cod_exib": o.get("referencia_cod_exib"),
            "conferir": bool(o.get("conferir", True)), "nota": " ".join((o.get("nota") or "").split()),
            "aplica_a": o.get("aplica_a", ["municipal", "estadual"]), "a_partir_de": o.get("a_partir_de"),
            "condicao": o.get("condicao"),
        })
    r = cfg.prazos["regra_bimestral"]
    rv = cfg.prazos.get("regra_habilitacao_vaat") or {}
    return {
        "painel": cfg.painel,
        "obrigacoes": obrig,
        "situacoes": {k: {"rotulo": v[0], "nivel": v[1]} for k, v in SITUACOES.items()},
        "indicadores": nomes,
        "grupos": cfg.grupos,
        "documentais": [{k: " ".join(str(v).split()) for k, v in d.items()} for d in cfg.documentais],
        "prazo_regra": {"dispositivo": r["dispositivo"], "dias": r["dias_apos_fim_do_bimestre"],
                        "consequencia": " ".join(r["consequencia"].split()), "conferir": bool(r.get("conferir", True))},
        "vaat_regra": {"dispositivo": rv.get("dispositivo"), "mes": rv.get("mes"), "dia": rv.get("dia")},
        "vaat_rotulos": {"sim": "Beneficiário (lista oficial)", "nao": "Não beneficiário (lista oficial)",
                         "sim_inf": "Beneficiário (inferido)", "nao_inf": "Não beneficiário (inferido)",
                         "?": "Sem dados"},
        "vaat_nota": ("O SIOPE não informa quem recebe complementação-VAAT. Sem a lista oficial em "
                      "dados/importados/vaat_<ano>.csv, o ente é tratado como beneficiário quando declara "
                      "valor em 1.5, 1.6 ou 1.7 (inferido). Conferir na lista oficial do FNDE/MEC."),
        "fontes_legais": cfg.fontes_legais,
        "regioes": ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"],
        "ufs": {s: {"nome": n, "regiao": r} for _, (s, n, r) in UFS.items()},
        "faixas_pop": FAIXAS_POP,
        "cod_tx": {v: k for k, v in COD_TX.items()},
    }


FAIXAS_POP = [
    {"id": "ate5", "rotulo": "até 5 mil", "min": 0, "max": 5000},
    {"id": "5a20", "rotulo": "5 a 20 mil", "min": 5000, "max": 20000},
    {"id": "20a50", "rotulo": "20 a 50 mil", "min": 20000, "max": 50000},
    {"id": "50a100", "rotulo": "50 a 100 mil", "min": 50000, "max": 100000},
    {"id": "100a500", "rotulo": "100 a 500 mil", "min": 100000, "max": 500000},
    {"id": "mais500", "rotulo": "mais de 500 mil", "min": 500000, "max": None},
]


def fmt_num(v, casas=2) -> str:
    if v is None:
        return "-"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_limite(v, unidade) -> str:
    return fmt_num(v, 0 if float(v).is_integer() else 2) + ("%" if unidade == "%" else "")


def processar(cfg: Config, saida: Path, hoje: date, log=print, demo: str | None = None) -> dict:
    """Gera site/dados/: catalogo.json, entes.json, <ano>/b<b>.json, <ano>/b<b>/<UF>.json, manifest.json."""
    dados = saida / "dados"
    anos = cfg.exercicios(hoje)
    periodos = {}
    for ano in anos:
        for b in coleta.bimestres_encerrados(ano, hoje):
            p = carregar_periodo(cfg, ano, b)
            p.update(ano=ano, b=b)
            if p["ufs_ind"] or p["ufs_dg"]:
                periodos[(ano, b)] = p
    entes = catalogo_entes(cfg, list(periodos.values()))
    ids = sorted(entes, key=lambda i: (entes[i]["uf"], entes[i]["esfera"] != "estadual", entes[i]["nome"]))

    nomes = {}
    for p in periodos.values():
        for c, n in p["nomes"].items():
            nomes.setdefault(c, n)
    h_cat = _gravar(dados / "catalogo.json", catalogo(cfg, nomes))
    h_entes = _gravar(dados / "entes.json", {
        "colunas": ["id", "nome", "uf", "regiao", "esfera", "pop"],
        "linhas": [[i, entes[i]["nome"], entes[i]["uf"], entes[i]["regiao"], entes[i]["esfera"], entes[i]["pop"]]
                   for i in ids]})

    manifest = {"gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
                "data_referencia": hoje.isoformat(), "catalogo": h_cat, "entes": h_entes, "exercicios": [],
                "demo": demo}
    obrig = cfg.obrigacoes
    for ano in anos:
        lista_vaat = beneficiarios_vaat(cfg, ano)
        prazos = [prazo_bimestre(cfg, ano, b) for b in range(1, 7)]
        # transmissões do exercício inteiro (mesmas para todos os bimestres de referência)
        tx = {i: [transmissao(i, entes[i]["uf"], periodos.get((ano, bb)), prazos[bb - 1], ano, bb, hoje)
                  for bb in range(1, 7)] for i in ids}
        bims = []
        for b in range(1, 7):
            p = periodos.get((ano, b))
            if p is None or not p["ufs_ind"]:
                continue
            colunas = ["id", "sg", "nc", "na", "al", "tb", "td", "vaat", "tx6"]
            for o in obrig:
                colunas += [f"v.{o['id']}", f"s.{o['id']}"]
            linhas, detalhe = [], {uf: {} for uf in SIGLAS}
            contagem = {"irregular": 0, "atencao": 0, "regular": 0, "sem_info": 0}
            com_indicadores = 0
            for i in ids:
                e = entes[i]
                ind = p["ind"].get(i) if e["uf"] in p["ufs_ind"] else None
                if ind is None and e["uf"] in p["ufs_ind"]:
                    ind = {}
                com_indicadores += bool(ind)
                vaat = situacao_vaat(i, ind, lista_vaat)
                alertas, celulas = [], []
                for o in obrig:
                    s, v, _ = avaliar(o, e["esfera"], ind, ano, b, vaat)
                    celulas += [v, s]
                    if s == "descumprida":
                        alertas.append(f"c:o:{o['id']}")
                    elif s in ("parcial_abaixo", "verificar"):
                        alertas.append(f"a:o:{o['id']}")
                for bb in range(1, b + 1):
                    st = tx[i][bb - 1][1]
                    if st == "atrasado":
                        alertas.append(f"c:t:{bb}")
                    elif st == "fora_prazo":
                        alertas.append(f"a:t:{bb}")
                nc = sum(1 for a in alertas if a.startswith("c:"))
                na = len(alertas) - nc
                tem_dado = bool(ind) or any(t[0] for t in tx[i][:b])
                sg = "irregular" if nc else "atencao" if na else "regular" if tem_dado else "sem_info"
                contagem[sg] += 1
                tx6 = "".join(COD_TX[t[1]] for t in tx[i])
                linhas.append([i, sg, nc, na, alertas, tx[i][b - 1][1], tx[i][b - 1][0], vaat, tx6] + celulas)
                if ind or any(t[0] for t in tx[i]):
                    detalhe[e["uf"]][i] = {"ind": {k: v for k, v in (ind or {}).items() if not k.startswith("_")},
                                           "tx": tx[i]}
            arq = dados / str(ano) / f"b{b}.json"
            h = _gravar(arq, {"ano": ano, "bimestre": b, "data_referencia": hoje.isoformat(),
                              "prazos": prazos, "ultima_coleta": p["ultima_coleta"],
                              "colunas": colunas, "linhas": linhas})
            hashes_uf = {uf: _gravar(dados / str(ano) / f"b{b}" / f"{uf}.json",
                                     {"ano": ano, "bimestre": b, "uf": uf, "entes": detalhe[uf]})
                         for uf in SIGLAS}
            bims.append({"bimestre": b, "rotulo": f"{b}º bimestre ({NOMES_BIMESTRE[b]})",
                         "arquivo": f"dados/{ano}/b{b}.json", "sha256": h, "ufs": hashes_uf,
                         "ufs_com_dados": sorted(p["ufs_ind"]), "contagem": contagem,
                         "entes_com_indicadores": com_indicadores, "cobertura": round(com_indicadores / len(ids), 4),
                         "ultima_coleta": p["ultima_coleta"]})
            log(f"  {ano} {b}º bim.: {len(linhas)} entes · irregulares {contagem['irregular']} · "
                f"atenção {contagem['atencao']} · regulares {contagem['regular']} · sem dados {contagem['sem_info']}")
        if bims:
            # Bimestre exibido ao abrir: o mais recente em que ao menos metade dos entes já declarou.
            maduros = [x["bimestre"] for x in bims if x["cobertura"] >= 0.5]
            manifest["exercicios"].append({"ano": ano, "bimestres": bims, "prazos": prazos,
                                           "bimestre_padrao": maduros[-1] if maduros else bims[-1]["bimestre"],
                                           "vaat_lista_oficial": lista_vaat is not None})
    _gravar(dados / "manifest.json", manifest)
    return manifest
