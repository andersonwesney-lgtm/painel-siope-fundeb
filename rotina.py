"""Rotina diária: coleta (API + recibos), valida, gera o site e registra a execução.

Saída (código de retorno):
  0  site novo pronto para publicar (pode haver avisos em estado/ultimo_status.json)
  1  falha grave: NÃO publicar; o site publicado continua o da última execução válida
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

from . import coleta, recibos
from .config import Config

MAX_REGISTRO = 400  # execuções guardadas no histórico


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validar_site(cfg: Config, saida: Path, anterior: dict | None) -> list[str]:
    """Problemas que impedem publicar. Lista vazia = pode publicar."""
    v, erros = cfg.validacao, []
    man_arq = saida / "dados" / "manifest.json"
    if not man_arq.exists():
        return ["manifest.json não foi gerado"]
    man = json.loads(man_arq.read_text(encoding="utf-8"))
    entes = json.loads((saida / "dados" / "entes.json").read_text(encoding="utf-8"))
    n_mun = sum(1 for i in _ids_entes(entes) if not str(i).startswith("UF-"))
    if n_mun < int(v.get("municipios_minimos", 5500)):
        erros.append(f"só {n_mun} municípios no catálogo (mínimo {v.get('municipios_minimos', 5500)})")
    if not man.get("exercicios"):
        erros.append("nenhum exercício com dados")
    for ex in man.get("exercicios", []):
        for b in ex.get("bimestres", []):
            arq = saida / b["arquivo"]
            if not arq.exists() or arq.stat().st_size < 1000:
                erros.append(f"arquivo vazio ou ausente: {b['arquivo']}")
    atual = resumo_publicacao(man)
    if anterior:
        queda = float(v.get("queda_maxima_entes_com_dados", 0.2))
        for k, n_ant in anterior.get("entes_com_dados", {}).items():
            n = atual["entes_com_dados"].get(k, 0)
            if n_ant >= 100 and n < n_ant * (1 - queda):
                erros.append(f"{k}: entes com dados caiu de {n_ant} para {n} (queda maior que {queda:.0%})")
    return erros


def _ids_entes(entes) -> list:
    if isinstance(entes, dict) and "linhas" in entes:
        return [l[0] for l in entes["linhas"]]
    if isinstance(entes, dict):
        return list(entes.get("entes", entes).keys())
    return [e[0] if isinstance(e, list) else e.get("id") for e in entes]


def resumo_publicacao(man: dict) -> dict:
    """Números de referência para comparar uma publicação com a seguinte."""
    r = {}
    for ex in man.get("exercicios", []):
        for b in ex.get("bimestres", []):
            if b.get("todos"):
                continue
            r[f"{ex['ano']}-b{b['bimestre']}"] = b.get("entes_com_indicadores", 0)
    return {"entes_com_dados": r}


def executar(cfg: Config, saida: Path, hoje: date, construir, log=print) -> int:
    est = cfg.dir_estado
    est.mkdir(parents=True, exist_ok=True)
    reg = {"inicio": _agora(), "data_referencia": hoje.isoformat(), "etapas": {}, "avisos": [], "status": "ok"}
    codigo = 0
    try:
        anos = cfg.exercicios(hoje)
        log(f"[1/4] API de dados abertos do SIOPE: exercícios {anos}")
        r = coleta.coletar(cfg, anos, hoje)
        total = r["gravadas"] + len(r["falhas"])
        reg["etapas"]["api"] = {"gravadas": r["gravadas"], "reaproveitadas": r["puladas"], "falhas": len(r["falhas"]),
                                "exemplos_falha": r["falhas"][:5]}
        if r["falhas"]:
            msg = f"API do SIOPE: {len(r['falhas'])} de {total} consulta(s) falharam; usados os dados guardados"
            if total and len(r["falhas"]) / total > 0.25:
                raise RuntimeError(msg + " (falhas demais: não publica)")
            reg["avisos"].append(msg)

        if cfg.recibos.get("ativo", True):
            log("[2/4] Recibos de transmissão do SIOPE (página pública, sem captcha)")
            rr = recibos.atualizar(cfg, hoje, log)
            reg["etapas"]["recibos"] = rr
            if rr["status"] == "falha":
                reg["avisos"].append(f"Recibos do SIOPE: {rr['mensagem']}. Mantidos os recibos já guardados.")
            elif rr["status"] == "parcial":  # esperado nos primeiros dias de um bimestre: só registra
                log(f"  recibos: {rr['consultados']} de {rr['alvos']} consultados; o restante fica para amanhã")

        log("[3/4] Processamento e montagem do site")
        construir(saida)
        anterior_arq = est / "ultima_publicacao.json"
        anterior = json.loads(anterior_arq.read_text(encoding="utf-8")) if anterior_arq.exists() else None
        log("[4/4] Validação antes de publicar")
        erros = validar_site(cfg, saida, anterior)
        if erros:
            raise RuntimeError("Validação reprovou o site novo: " + "; ".join(erros))
        man = json.loads((saida / "dados" / "manifest.json").read_text(encoding="utf-8"))
        pub = resumo_publicacao(man) | {"gerado_em": man.get("gerado_em")}
        reg["etapas"]["site"] = pub
        anterior_arq.write_text(json.dumps(pub, ensure_ascii=False, indent=1), encoding="utf-8")
        if reg["avisos"]:
            reg["status"] = "aviso"
    except Exception as exc:
        reg["status"], codigo = "falha", 1
        reg["erro"] = str(exc)
        reg["detalhe"] = traceback.format_exc(limit=3)
        log(f"FALHA: {exc}")
    reg["fim"] = _agora()
    _registrar(cfg, reg)
    if codigo == 0:
        _copiar_registro_para_site(cfg, saida)
    return codigo


def _registrar(cfg: Config, reg: dict) -> None:
    est = cfg.dir_estado
    hist = est / "execucoes.jsonl"
    linhas = hist.read_text(encoding="utf-8").splitlines() if hist.exists() else []
    linhas = (linhas + [json.dumps(reg, ensure_ascii=False, sort_keys=True)])[-MAX_REGISTRO:]
    hist.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    (est / "ultimo_status.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Registro: status={reg['status']} avisos={len(reg['avisos'])}", file=sys.stderr)


def _copiar_registro_para_site(cfg: Config, saida: Path) -> None:
    hist = cfg.dir_estado / "execucoes.jsonl"
    ult = [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()][-30:]
    leve = [{k: r.get(k) for k in ("inicio", "fim", "status", "avisos", "erro")} |
            {"recibos": {k: (r.get("etapas", {}).get("recibos") or {}).get(k)
                         for k in ("periodos", "consultados", "novos", "atualizados", "erros", "status")}}
            for r in ult]
    (saida / "dados" / "execucoes.json").write_text(json.dumps(leve, ensure_ascii=False), encoding="utf-8")
