"""Recibos de transmissão do SIOPE (página pública, sem captcha).

Por que existe: a base de dados abertos do FNDE (API Olinda, recurso Dados_Gerais_Siope) chega com
atraso em relação ao sistema SIOPE. Em 23/10/2026 ela tinha só 25 municípios de AL no 4º bimestre de
2026, todos com envio até 30/09; Capela (AL), que transmitiu em 08/10/2026, não aparecia.

O relatório "Municípios transmitidos por UF" tem reCAPTCHA e não é coletado. A mesma informação
(ente, período, recibo, data de transmissão, retificação) está na página pública "Recibos de
Transmissão" do SIOPE, que não tem captcha:
    https://www.fnde.gov.br/siope/recibosTransmissao.do
Ela responde por ente (um município por consulta, com todos os períodos dele). Por isso esta rotina
só consulta quem falta na base aberta, a partir do período configurado, e guarda o que já achou.

Garantias:
  - idempotente: chave única "ente|ano|bimestre"; rodar de novo não duplica, só atualiza o registro;
  - cada resposta é validada (cabeçalho exato, datas plausíveis); resposta fora do padrão é descartada;
  - se a página mudar (captcha, colunas, erro em série), a etapa para e o que já estava guardado fica.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Config

URL = "https://www.fnde.gov.br/siope/recibosTransmissao.do"
COLUNAS = ["Período", "Situação", "Nº do Recibo", "Data de Processamento", "Data de Transmissão",
           "Declaração Retificadora"]
VERSAO_ARQUIVO = 1


class FonteMudou(RuntimeError):
    """A página respondeu fora do formato conhecido (captcha, colunas novas, página de erro)."""


# ------------------------------------------------------------ leitura da página ----

def _texto(fragmento: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragmento)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _data(txt: str) -> str | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2}))?", txt or "")
    if not m:
        return None
    d, mes, a, hh, mm = m.groups()
    return f"{a}-{mes}-{d}" + (f"T{hh}:{mm}" if hh else "")


def periodo(txt: str) -> tuple[int, int] | None:
    """'2026 - 4º Bimestre' -> (2026, 4); '2025 - Anual' -> (2025, 6) (declaração anual = 6º bimestre)."""
    m = re.match(r"(\d{4})\s*-\s*(?:(\d)\s*º?\s*Bimestre|Anual)", txt, re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else 6


def ler_tabela(pagina: str, hoje: date) -> list[dict]:
    """Extrai os recibos da resposta. Levanta FonteMudou se o formato não for o esperado."""
    if "recaptcha" in pagina.lower() and "Data de Transmiss" not in pagina:
        raise FonteMudou("a página de recibos passou a exigir captcha")
    sem_script = re.sub(r"<script.*?</script>", " ", pagina, flags=re.S | re.I)
    linhas = [[_texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
              for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", sem_script, re.S | re.I)]
    cab = next((k for k, l in enumerate(linhas) if l[:len(COLUNAS)] == COLUNAS), None)
    if cab is None:
        raise FonteMudou("cabeçalho da tabela de recibos diferente do esperado")
    recibos = []
    for l in linhas[cab + 1:]:
        if len(l) < len(COLUNAS):
            break
        p = periodo(l[0])
        if p is None:
            break  # fim da tabela de recibos (vem a do histórico MAVS)
        transm = _data(l[4])
        if transm is None:
            raise FonteMudou(f"data de transmissão ilegível: {l[4]!r}")
        if not (2005 <= int(transm[:4]) <= hoje.year) or transm[:10] > hoje.isoformat():
            raise FonteMudou(f"data de transmissão implausível: {transm}")
        recibos.append({"ano": p[0], "bimestre": p[1], "situacao": l[1], "recibo": l[2],
                        "processado_em": _data(l[3]), "transmitido_em": transm,
                        "retificadora": l[5].strip().lower().startswith("s"),
                        "valido": l[1].lower().startswith("processado com sucesso")})
    return recibos


# --------------------------------------------------------------- consulta ----

class Cliente:
    """Sessões HTTP (uma por thread), com pausa mínima entre consultas e retentativas."""

    def __init__(self, pausa_s: float, agente: str):
        self.pausa_s, self.agente = pausa_s, agente
        self._local = threading.local()

    def _sessao(self):
        import requests

        s = getattr(self._local, "s", None)
        if s is None:
            s = self._local.s = requests.Session()
            s.headers["User-Agent"] = self.agente
            s.get(URL, timeout=60)  # abre a sessão como o navegador faria
        return s

    def municipio(self, cod_uf: str, cod_muni: str) -> str:
        return self._post({"tipoDeRecibo": "1", "cod_uf_mun": cod_uf, "municipios": cod_muni,
                           "consultar": "Consultar"})

    def estado(self, cod_uf: str) -> str:
        return self._post({"tipoDeRecibo": "0", "cod_uf": cod_uf, "consultar": "Consultar"})

    def _post(self, dados: dict) -> str:
        ultimo = None
        for tentativa in range(3):
            time.sleep(self.pausa_s * (1 + 2 * tentativa))
            try:
                r = self._sessao().post(URL, data=dados, timeout=90)
                if r.status_code == 200:
                    r.encoding = r.encoding or "iso-8859-1"
                    return r.text
                ultimo = f"HTTP {r.status_code}"
            except Exception as exc:  # rede instável no FNDE: tenta de novo
                ultimo = str(exc)
                self._local.s = None
        raise ConnectionError(ultimo or "sem resposta")


# ------------------------------------------------------------- armazenamento ----

def arquivo(cfg: Config) -> Path:
    return cfg.dir_estado / "recibos.json"


def carregar(cfg: Config) -> dict:
    a = arquivo(cfg)
    if not a.exists():
        return {"versao": VERSAO_ARQUIVO, "registros": {}, "consultados": {}}
    return json.loads(a.read_text(encoding="utf-8"))


def gravar(cfg: Config, estado: dict) -> bool:
    """Grava só se mudou (ordem estável). Devolve True se o arquivo mudou."""
    a = arquivo(cfg)
    novo = json.dumps(estado, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if a.exists() and a.read_text(encoding="utf-8") == novo:
        return False
    a.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.with_suffix(".tmp")
    tmp.write_text(novo, encoding="utf-8")
    tmp.replace(a)
    return True


def chave(ente: str, ano: int, b: int) -> str:
    return f"{ente}|{ano}|{b}"


def por_periodo(estado: dict, ano: int, b: int) -> dict[str, dict]:
    """{ente: recibo} válidos de um período, prontos para o processamento."""
    suf = f"|{ano}|{b}"
    return {k.split("|")[0]: v for k, v in estado.get("registros", {}).items() if k.endswith(suf) and v["valido"]}


# -------------------------------------------------------------- atualização ----

def periodos_acompanhados(cfg: Config, hoje: date) -> list[tuple[int, int]]:
    from . import processa

    ini = cfg.recibos.get("a_partir_de") or {}
    a0, b0 = int(ini.get("ano", hoje.year)), int(ini.get("bimestre", 1))
    return [(a, b) for a in cfg.exercicios(hoje) for b in range(1, 7)
            if (a, b) >= (a0, b0) and processa.fim_bimestre(a, b) < hoje]


def alvos(cfg: Config, hoje: date, estado: dict) -> list[tuple[str, str, str]]:
    """Entes a consultar: sem registro na base aberta E sem recibo guardado em algum período
    acompanhado. Quem já foi consultado hoje fica de fora (rodar duas vezes no dia não repete)."""
    from . import processa
    from .territorio import SIGLA_PARA_COD

    pers = periodos_acompanhados(cfg, hoje)
    if not pers:
        return []
    periodos = {}
    for a, b in pers:
        p = processa.carregar_periodo(cfg, a, b)
        p.update(ano=a, b=b)
        periodos[(a, b)] = p
    entes = processa.catalogo_entes(cfg, list(periodos.values()))
    regs, hoje_iso = estado["registros"], hoje.isoformat()
    saida = []
    for i, e in sorted(entes.items()):
        if estado["consultados"].get(i, "")[:10] == hoje_iso:
            continue
        falta = any(i not in periodos[(a, b)]["dg"] and not regs.get(chave(i, a, b), {}).get("valido")
                    for a, b in pers)
        if falta and (cfg.recibos.get("incluir_estados", True) or not i.startswith("UF-")):
            saida.append((i, e["uf"], str(SIGLA_PARA_COD[e["uf"]])))
    return saida


def atualizar(cfg: Config, hoje: date, log=print) -> dict:
    """Consulta os recibos que faltam e grava. Devolve um resumo para o registro de execução."""
    rc = cfg.recibos
    estado = carregar(cfg)
    # Guarda só os exercícios cobertos pelo painel. A página devolve o histórico inteiro do ente;
    # os bimestres anteriores ao ponto de partida vêm de graça e corrigem esses períodos também.
    anos = set(cfg.exercicios(hoje))
    estado["registros"] = {k: v for k, v in estado["registros"].items() if int(k.split("|")[1]) in anos}
    lista = alvos(cfg, hoje, estado)
    limite = int(rc.get("max_consultas_por_execucao", 3000))
    prazo_fim = time.monotonic() + 60 * float(rc.get("tempo_maximo_min", 150))
    resumo = {"alvos": len(lista), "consultados": 0, "novos": 0, "atualizados": 0, "erros": 0,
              "periodos": [f"{a}-b{b}" for a, b in periodos_acompanhados(cfg, hoje)], "status": "ok",
              "mensagem": ""}
    if not lista:
        log("  recibos: nada a consultar")
        return resumo
    lista = lista[:limite]
    log(f"  recibos: consultando {len(lista)} ente(s) (períodos {', '.join(resumo['periodos'])})")
    cli = Cliente(float(rc.get("pausa_entre_consultas_s", 1.0)),
                  rc.get("agente", "painel-siope-fundeb (acompanhamento publico do Fundeb; 1 consulta/ente/dia)"))
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trava, falhas_seguidas, parar = threading.Lock(), [0], threading.Event()

    def um(alvo):
        i, uf, cod_uf = alvo
        if parar.is_set() or time.monotonic() > prazo_fim:
            return i, None, "pulado"
        try:
            pagina = cli.estado(cod_uf) if i.startswith("UF-") else cli.municipio(cod_uf, i)
            return i, ler_tabela(pagina, hoje), None
        except FonteMudou as exc:
            return i, None, f"formato: {exc}"
        except Exception as exc:
            return i, None, f"rede: {exc}"

    with ThreadPoolExecutor(max_workers=int(rc.get("consultas_simultaneas", 2))) as ex:
        for fut in as_completed([ex.submit(um, a) for a in lista]):
            i, recs, erro = fut.result()
            with trava:
                if erro == "pulado":
                    continue
                resumo["consultados"] += 1
                if erro:
                    resumo["erros"] += 1
                    falhas_seguidas[0] += 1
                    if falhas_seguidas[0] >= int(rc.get("parar_apos_falhas_seguidas", 8)):
                        parar.set()
                        resumo["status"], resumo["mensagem"] = "falha", erro
                    continue
                falhas_seguidas[0] = 0
                estado["consultados"][i] = agora
                for r in recs:
                    if r["ano"] not in anos:
                        continue
                    k = chave(i, r["ano"], r["bimestre"])
                    antigo = estado["registros"].get(k)
                    novo = {kk: r[kk] for kk in ("situacao", "recibo", "processado_em", "transmitido_em",
                                                 "retificadora", "valido")}
                    if antigo is None:
                        resumo["novos"] += 1
                    elif {kk: antigo.get(kk) for kk in novo} != novo:
                        resumo["atualizados"] += 1
                    else:
                        continue
                    estado["registros"][k] = novo | {"visto_em": agora}
                if resumo["consultados"] % 200 == 0:
                    gravar(cfg, estado)  # progresso parcial: só registros já validados
                    log(f"  recibos: {resumo['consultados']}/{len(lista)} consultados")
    taxa = resumo["erros"] / max(resumo["consultados"], 1)
    if resumo["status"] == "ok" and resumo["consultados"] >= 20 and taxa > float(rc.get("taxa_maxima_erros", 0.3)):
        resumo["status"], resumo["mensagem"] = "falha", f"{taxa:.0%} das consultas falharam"
    elif resumo["status"] == "ok" and resumo["consultados"] < len(lista):
        resumo["status"], resumo["mensagem"] = "parcial", "limite de tempo/consultas; continua na próxima execução"
    gravar(cfg, estado)
    log(f"  recibos: {resumo['consultados']} consultados, {resumo['novos']} novos, "
        f"{resumo['atualizados']} atualizados, {resumo['erros']} erro(s) [{resumo['status']}]")
    return resumo
