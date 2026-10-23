"""Indicadores do SIOPE pelo webservice para os Tribunais de Contas (público, sem captcha).

Por que existe: a base de dados abertos do FNDE (API Olinda, recurso Indicadores_Siope) é publicada
com atraso. Em 23/10/2026 ela tinha só 2 dos 47 indicadores de Capela (AL) no 4º bimestre de 2026,
enquanto o SIOPE já mostrava todos. O "Relatório de Indicadores" do SIOPE tem reCAPTCHA e não é
coletado. O mesmo conteúdo sai, em JSON, do webservice do SIOPE para os Tribunais de Contas:
    https://www.fnde.gov.br/webservices/siope/tc/indicador?num_ano=2026&num_periodo=4&cod_municipio=270170
(estados: sgl_uf=AL, sem cod_municipio). Caminho encontrado a partir do projeto público
github.com/danielanza/SIOPE-Extracao-de-Dados, que usa o recurso irmão /tc/receita.

Só consulta quem transmitiu e está incompleto na base aberta, nos períodos acompanhados, e guarda o
que achou. Garantias iguais às dos recibos: chave única "ente|ano|bimestre" (sem duplicação),
resposta validada (estrutura, ente e período conferidos, códigos e valores numéricos), e parada
com o que já estava guardado se o serviço mudar ou cair.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Config

URL = "https://www.fnde.gov.br/webservices/siope/tc/indicador"
VERSAO_ARQUIVO = 1
CODIGO = re.compile(r"^\d{1,2}\.\d{1,2}$")


class FonteMudou(RuntimeError):
    """O serviço respondeu fora do formato conhecido."""


def ler_resposta(dados, ente: str, ano: int, b: int) -> dict[str, float]:
    """{código: valor} do ente no período. Vazio se o SIOPE ainda não tem o período. Levanta
    FonteMudou se a estrutura, o ente ou o período não baterem com o que foi pedido."""
    if not isinstance(dados, dict) or not isinstance(dados.get("ente"), list):
        raise FonteMudou("resposta sem a lista 'ente'")
    saida = {}
    for e in dados["ente"]:
        if not isinstance(e, dict) or not isinstance(e.get("indicador", []), list):
            raise FonteMudou("item de 'ente' fora do formato")
        if str(e.get("num_ano")) != str(ano) or str(e.get("num_periodo")) != str(b):
            raise FonteMudou(f"período diferente do pedido: {e.get('num_ano')}/{e.get('num_periodo')}")
        if ente.startswith("UF-"):
            if e.get("sgl_uf") != ente[3:]:
                raise FonteMudou(f"ente diferente do pedido: {e.get('sgl_uf')}")
        elif str(e.get("cod_municipio")) != ente:
            raise FonteMudou(f"ente diferente do pedido: {e.get('cod_municipio')}")
        for it in e.get("indicador", []):
            cod = str((it or {}).get("cod_indicador", ""))
            if not CODIGO.match(cod):
                raise FonteMudou(f"código de indicador inesperado: {cod!r}")
            try:
                v = float((it or {}).get("vlr_indicador"))
            except (TypeError, ValueError):
                raise FonteMudou(f"valor não numérico em {cod}: {it.get('vlr_indicador')!r}") from None
            if v != v or abs(v) > 1e13:
                raise FonteMudou(f"valor implausível em {cod}: {v}")
            saida[cod] = v
    return saida


class Cliente:
    def __init__(self, pausa_s: float, agente: str):
        self.pausa_s, self.agente = pausa_s, agente
        self._local = threading.local()
        self._todos, self._trava = {}, threading.Lock()

    def _sessao(self):
        import requests

        s = getattr(self._local, "s", None)
        if s is None:
            s = self._local.s = requests.Session()
            s.headers["User-Agent"] = self.agente
        return s

    def consultar(self, ente: str, ano: int, b: int):
        if ente.startswith("UF-"):
            # Filtro por sgl_uf falha no servidor (HTTP 400, ORA-01722, 23/10/2026). Sem filtro de ente,
            # o serviço devolve todos os entes do período: baixa uma vez e separa os governos estaduais.
            with self._trava:
                if (ano, b) not in self._todos:
                    self._todos[(ano, b)] = self._get({"num_ano": ano, "num_periodo": b}, timeout=300)
                todos = self._todos[(ano, b)]
            if not isinstance(todos, dict) or not isinstance(todos.get("ente"), list):
                raise FonteMudou("resposta sem a lista 'ente'")
            return {"ente": [e for e in todos["ente"] if isinstance(e, dict)
                             and e.get("sgl_uf") == ente[3:] and not e.get("cod_municipio")]}
        return self._get({"num_ano": ano, "num_periodo": b, "cod_municipio": ente})

    def _get(self, params: dict, timeout: int = 90):
        ultimo = None
        for tentativa in range(3):
            time.sleep(self.pausa_s * (1 + 2 * tentativa))
            try:
                r = self._sessao().get(URL, params=params, timeout=timeout)
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError:
                        raise FonteMudou("resposta não é JSON") from None
                ultimo = f"HTTP {r.status_code}"
            except FonteMudou:
                raise
            except Exception as exc:
                ultimo = str(exc)
                self._local.s = None
        raise ConnectionError(ultimo or "sem resposta")


# ------------------------------------------------------------- armazenamento ----

def arquivo(cfg: Config) -> Path:
    return cfg.dir_estado / "indicadores_tc.json"


def carregar(cfg: Config) -> dict:
    a = arquivo(cfg)
    if not a.exists():
        return {"versao": VERSAO_ARQUIVO, "registros": {}, "consultados": {}}
    return json.loads(a.read_text(encoding="utf-8"))


def gravar(cfg: Config, estado: dict) -> bool:
    a = arquivo(cfg)
    novo = json.dumps(estado, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if a.exists() and a.read_text(encoding="utf-8") == novo:
        return False
    a.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.with_suffix(".tmp")
    tmp.write_text(novo, encoding="utf-8")
    tmp.replace(a)
    return True


def por_periodo(estado: dict, ano: int, b: int) -> dict[str, dict]:
    """{ente: {"ind": {...}, "visto_em": ...}} de um período."""
    suf = f"|{ano}|{b}"
    return {k.split("|")[0]: v for k, v in estado.get("registros", {}).items() if k.endswith(suf)}


# -------------------------------------------------------------- atualização ----

def _cfg(cfg: Config) -> dict:
    return cfg.indicadores_tc or {}


def incompleto(ind: dict | None, minimo: int) -> bool:
    return sum(1 for k in (ind or {}) if not k.startswith("_")) < minimo


def alvos(cfg: Config, hoje: date, estado: dict) -> list[tuple[str, int, int]]:
    """(ente, ano, bimestre) a consultar: transmitiu, está incompleto na base aberta e não tem
    indicadores guardados desta transmissão. Quem já foi consultado hoje fica de fora."""
    from . import processa, recibos

    minimo = int(_cfg(cfg).get("minimo_indicadores", 30))
    incluir_estados = _cfg(cfg).get("incluir_estados", True)
    regs, consultados, hoje_iso = estado["registros"], estado["consultados"], hoje.isoformat()
    saida = []
    for a, b in recibos.periodos_acompanhados(cfg, hoje):
        p = processa.carregar_periodo(cfg, a, b, com_tc=False)
        for i, d in sorted(p["dg"].items()):
            if i.startswith("UF-") and not incluir_estados:
                continue
            k = f"{i}|{a}|{b}"
            if consultados.get(k, "")[:10] == hoje_iso or not incompleto(p["ind"].get(i), minimo):
                continue
            guardado = regs.get(k)
            # já tem os indicadores, salvo se houve transmissão (retificação) depois de lidos
            if guardado and guardado["ind"] and (d.get("data") or "") <= guardado["visto_em"][:10]:
                continue
            saida.append((i, a, b))
    return saida


def atualizar(cfg: Config, hoje: date, log=print) -> dict:
    c = _cfg(cfg)
    estado = carregar(cfg)
    anos = set(cfg.exercicios(hoje))
    estado["registros"] = {k: v for k, v in estado["registros"].items() if int(k.split("|")[1]) in anos}
    estado["consultados"] = {k: v for k, v in estado["consultados"].items() if int(k.split("|")[1]) in anos}
    lista = alvos(cfg, hoje, estado)
    from . import recibos

    resumo = {"alvos": len(lista), "consultados": 0, "com_dados": 0, "novos": 0, "atualizados": 0,
              "erros": 0, "periodos": [f"{a}-b{b}" for a, b in recibos.periodos_acompanhados(cfg, hoje)],
              "status": "ok", "mensagem": ""}
    if not lista:
        log("  indicadores (webservice TC): nada a consultar")
        return resumo
    lista = lista[:int(c.get("max_consultas_por_execucao", 6000))]
    prazo_fim = time.monotonic() + 60 * float(c.get("tempo_maximo_min", 90))
    log(f"  indicadores (webservice TC): consultando {len(lista)} ente/período(s)")
    cli = Cliente(float(c.get("pausa_entre_consultas_s", 0.5)),
                  c.get("agente", "painel-siope-fundeb (acompanhamento publico do Fundeb)"))
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trava, falhas_seguidas, parar = threading.Lock(), [0], threading.Event()

    def um(alvo):
        i, a, b = alvo
        if parar.is_set() or time.monotonic() > prazo_fim:
            return alvo, None, "pulado"
        try:
            return alvo, ler_resposta(cli.consultar(i, a, b), i, a, b), None
        except FonteMudou as exc:
            return alvo, None, f"formato: {exc}"
        except Exception as exc:
            return alvo, None, f"rede: {exc}"

    with ThreadPoolExecutor(max_workers=int(c.get("consultas_simultaneas", 2))) as ex:
        for fut in as_completed([ex.submit(um, a) for a in lista]):
            (i, a, b), ind, erro = fut.result()
            with trava:
                if erro == "pulado":
                    continue
                resumo["consultados"] += 1
                if erro:
                    resumo["erros"] += 1
                    falhas_seguidas[0] += 1
                    if falhas_seguidas[0] >= int(c.get("parar_apos_falhas_seguidas", 8)):
                        parar.set()
                        resumo["status"], resumo["mensagem"] = "falha", erro
                    continue
                falhas_seguidas[0] = 0
                k = f"{i}|{a}|{b}"
                estado["consultados"][k] = agora
                if not ind:
                    continue  # o SIOPE ainda não tem este período para o ente
                resumo["com_dados"] += 1
                antigo = estado["registros"].get(k)
                if antigo is None:
                    resumo["novos"] += 1
                elif antigo["ind"] != ind:
                    resumo["atualizados"] += 1
                estado["registros"][k] = {"ind": ind, "visto_em": agora}
                if resumo["consultados"] % 500 == 0:
                    gravar(cfg, estado)
                    log(f"  indicadores (webservice TC): {resumo['consultados']}/{len(lista)}")
    taxa = resumo["erros"] / max(resumo["consultados"], 1)
    if resumo["status"] == "ok" and resumo["consultados"] >= 20 and taxa > float(c.get("taxa_maxima_erros", 0.3)):
        resumo["status"], resumo["mensagem"] = "falha", f"{taxa:.0%} das consultas falharam"
    elif resumo["status"] == "ok" and resumo["consultados"] < len(lista):
        resumo["status"], resumo["mensagem"] = "parcial", "limite de tempo/consultas; continua na próxima execução"
    gravar(cfg, estado)
    log(f"  indicadores (webservice TC): {resumo['consultados']} consultados, {resumo['com_dados']} com dados, "
        f"{resumo['novos']} novos, {resumo['atualizados']} atualizados, {resumo['erros']} erro(s) [{resumo['status']}]")
    return resumo
