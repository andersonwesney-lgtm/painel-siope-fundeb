import re, json, urllib.request, urllib.parse, http.cookiejar
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
U = "https://www.fnde.gov.br/siope/recibosTransmissao.do"
def get(u, data=None, t=60):
    req = urllib.request.Request(u, data=urllib.parse.urlencode(data).encode() if data else None, headers={"User-Agent": "sonda"})
    with op.open(req, timeout=t) as r:
        return r.headers.get("Content-Type", ""), r.read().decode("latin-1", "replace")
def opts(h, nome):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % nome, h, re.S | re.I)
    if not m: return []
    out = []
    for a, n in re.findall(r'<option([^>]*)>([^<]*)', m.group(1), re.I):
        v = re.search(r'value\s*=\s*["\']?([^"\'\s>]*)', a, re.I)
        out.append((v.group(1) if v else n.strip(), n.strip()))
    return out
ct, h = get(U)
i = h.find('name="cod_uf_mun"'); print(repr(h[i-50:i+500]))
print("cod_uf_mun:", opts(h, "cod_uf_mun"))
al = [v for v, n in opts(h, "cod_uf_mun") if "Alagoas" in n][0]
ct, h = get(U, {"tipoDeRecibo": "1", "cod_uf_mun": al})
mun = opts(h, "municipios"); print("AL municipios:", len(mun), mun[:5])
cap = [v for v, n in mun if n.strip().startswith("Capela")]
print("Capela:", cap)
ct, h = get(U, {"tipoDeRecibo": "1", "cod_uf_mun": al, "municipios": cap[0], "consultar": "Consultar"})
print("captcha?", "recaptcha" in h.lower())
tab = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I)
for t in tab:
    cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", t, re.S | re.I)]
    if any(cells): print(cells)
print("abrirHistorico calls:", re.findall(r"abrirHistorico\(([^)]*)\)", h)[:6])
i = h.find("const url"); print(h[i:i+700])
