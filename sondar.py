import json, re, urllib.request, ssl
UA = {"User-Agent": "painel-siope-fundeb (sondagem)"}
def get(u, data=None):
    r = urllib.request.Request(u, data=data, headers=UA)
    with urllib.request.urlopen(r, timeout=90) as f:
        return f.status, f.read().decode("latin-1")
st, h = get("https://www.fnde.gov.br/siope/indicadoresFinanceirosEEducacionais.do")
print("STATUS", st, len(h))
print("CAPTCHA", sorted(set(m.lower() for m in re.findall(r"g-recaptcha|recaptcha|captcha|hcaptcha", h, re.I))))
for f in re.findall(r"<form[^>]*>", h, re.I): print("FORM", f)
print("CAMPOS", sorted(set(re.findall(r'name="([^"]+)"', h))))
for s in re.findall(r'<select[^>]*name="([^"]+)"', h): print("SELECT", s)
print("TRECHO", re.sub(r"\s+", " ", re.sub(r"<script.*?</script>", "", h, flags=re.S))[:3000])
st, j = get("https://andersonwesney-lgtm.github.io/painel-siope-fundeb/dados/2026/b4.json?v=9")
d = json.loads(j); ix = {c: k for k, c in enumerate(d["colunas"])}
print("COLUNAS", d["colunas"])
print("CAPELA", next(l for l in d["linhas"] if str(l[ix["id"]]) == "270170"))
