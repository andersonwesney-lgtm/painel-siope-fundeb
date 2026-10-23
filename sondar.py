import json, re, urllib.request, urllib.parse
B = "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata"
def get(u, t=60):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "sonda"}), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERRO {e}"
def q(rec, ano, p, uf, sel):
    ps = {"@A": str(ano), "@P": str(p), "@U": f"'{uf}'", "$format": "json", "$top": "100000", "$select": sel}
    t = get(f"{B}/{rec}(Ano_Consulta=@A,Num_Peri=@P,Sig_UF=@U)?" + urllib.parse.urlencode(ps))
    try: return json.loads(t)["value"]
    except Exception: return t[:200]
print("== AL 2026 por recurso")
for rec, sel in [("Dados_Gerais_Siope", "COD_MUNI,DAT_DECL"), ("Dados_Gerais_Siope_Dados_Responsaveis", "COD_MUNI,DAT_DECL"),
                 ("Indicadores_Siope", "COD_MUNI"), ("Informacoes_Complementares_Siope", "COD_MUNI")]:
    for p in (3, 4):
        v = q(rec, 2026, p, "AL", sel)
        if isinstance(v, str): print(rec, p, v); continue
        m = {str(x["COD_MUNI"]) for x in v}
        print(rec, f"b{p}", "linhas", len(v), "entes", len(m), "Capela", "270170" in m)
print("== maior DAT_DECL e contagem por bimestre")
for p in (1, 2, 3, 4):
    for uf in ("AL", "SP", "BA"):
        v = q("Dados_Gerais_Siope", 2026, p, uf, "DAT_DECL")
        if isinstance(v, str): print(p, uf, v); continue
        d = sorted((x["DAT_DECL"] or "")[:10] for x in v)
        print(f"b{p}", uf, len(v), d[-1] if d else None, "pós 30/09:", sum(x > "2026-09-30" for x in d))
print("== catálogo olinda")
t = get("https://www.fnde.gov.br/olinda-ide/servico")
print(sorted(set(re.findall(r"servico/([A-Za-z0-9_]+)", t)))[:80])
for s in ("DADOS_ABERTOS_SIOPE",):
    t = get(f"https://www.fnde.gov.br/olinda-ide/servico/{s}")
    print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))[:1500])
print("== CKAN / dados.gov.br")
for u in ["https://www.fnde.gov.br/dadosabertos/api/3/action/package_search?q=siope&rows=20",
          "https://www.fnde.gov.br/dadosabertos/dataset?q=siope"]:
    t = get(u, 30); print("--", u, len(t)); print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))[:1500])
print("== páginas do SIOPE: captcha?")
t = get("https://www.fnde.gov.br/siope/relatoriosMunicipais.jsp")
links = sorted(set(re.findall(r'href="([^"]+\.(?:do|jsp)[^"]*)"', t)))
for pg in ["municipiosTransmitidosPorUF.do"] + links[:40]:
    u = pg if pg.startswith("http") else "https://www.fnde.gov.br/siope/" + pg.lstrip("/")
    h = get(u, 25)
    print("captcha" if "recaptcha" in h.lower() else "LIVRE  ", len(h), u)
