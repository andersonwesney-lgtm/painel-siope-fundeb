import re, time, urllib.request, urllib.parse, http.cookiejar
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
U = "https://www.fnde.gov.br/siope/recibosTransmissao.do"
def get(u, data=None, t=60):
    req = urllib.request.Request(u, data=urllib.parse.urlencode(data).encode() if data else None, headers={"User-Agent": "sonda"})
    with op.open(req, timeout=t) as r:
        return r.read().decode("latin-1", "replace")
def linhas(h):
    h = re.sub(r"<script.*?</script>", " ", h, flags=re.S | re.I)
    out = []
    for t in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I):
        c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).replace("&nbsp;", " ").strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", t, re.S | re.I)]
        if any(c): out.append(c)
    return out
get(U)
for cod in ("270170", "270020", "270030"):
    t0 = time.time()
    h = get(U, {"tipoDeRecibo": "1", "cod_uf_mun": "27", "municipios": cod, "consultar": "Consultar"})
    ls = linhas(h)
    print("====", cod, f"{time.time()-t0:.1f}s", len(h), "captcha" if "recaptcha" in h.lower() else "sem captcha")
    for l in ls[:12]: print(l)
