"""Leitura de config/ (painel.yaml, obrigacoes.yaml, prazos.yaml)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    raiz: Path
    painel: dict
    exercicios_cfg: dict
    coleta: dict
    pdf_lote: dict
    obrigacoes: list[dict]
    fontes_legais: dict
    grupos: dict
    rotulos_curtos: dict
    documentais: list[dict]
    prazos: dict

    def exercicios(self, hoje: date) -> list[int]:
        lista = self.exercicios_cfg.get("lista") or []
        if lista:
            return sorted(int(a) for a in lista)
        n = int(self.exercicios_cfg.get("quantidade", 2))
        return list(range(hoje.year - n + 1, hoje.year + 1))

    @property
    def dir_brutos(self) -> Path:
        return self.raiz / "dados" / "brutos"

    @property
    def dir_importados(self) -> Path:
        return self.raiz / "dados" / "importados"


def _ler(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def carregar(raiz: Path | None = None) -> Config:
    raiz = Path(raiz or RAIZ)
    p = _ler(raiz / "config" / "painel.yaml")
    o = _ler(raiz / "config" / "obrigacoes.yaml")
    return Config(
        raiz=raiz,
        painel=p.get("painel", {}),
        exercicios_cfg=p.get("exercicios", {}),
        coleta=p.get("coleta", {}),
        pdf_lote=p.get("pdf_lote", {}),
        obrigacoes=o["obrigacoes"],
        fontes_legais=o.get("fontes", {}),
        grupos={str(k): v for k, v in o.get("grupos_acompanhados", {}).items()},
        rotulos_curtos=o.get("rotulos_curtos", {}),
        documentais=o.get("obrigacoes_documentais", []),
        prazos=_ler(raiz / "config" / "prazos.yaml"),
    )
