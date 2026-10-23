import re, urllib.request, urllib.parse, http.cookiejar
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(u, data=None, t=60):
    try:
        req = urllib.request.Request(u, data=urllib.parse.urlencode(data).encode() if data else None, headers={"User-Agent": "sonda"})
        with op.open(req, timeout=t) as r:
            return r.headers.get("Content-Type", ""), r.read()
    except Exception as e:
        return "ERRO", str(e).encode()
def txt(b): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b.decode("latin-1", "replace")))
for pg in ("download.do", "recibosTransmissao.do"):
    ct, b = get("https://www.fnde.gov.br/siope/" + pg)
    h = b.decode("latin-1", "replace")
    print("=====", pg, ct, len(b))
    print("FORMS:", re.findall(r"<form[^>]*>", h, re.I))
    print("INPUTS:", re.findall(r"<(?:input|select)[^>]*name=\"[^\"]+\"[^>]*>", h, re.I)[:30])
    print("LINKS:", sorted(set(re.findall(r'href="([^"]+)"', h)))[:80])
    print("SCRIPTS:", re.findall(r"function\s+\w+\([^)]*\)\s*\{[^}]{0,300}", h)[:10])
    print("TEXTO:", txt(b)[:2500])
