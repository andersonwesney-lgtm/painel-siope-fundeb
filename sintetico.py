"""Gera dados FICTÍCIOS no formato da coleta, para testes e para a prévia de demonstração.

Os nomes dos entes são inventados ("Município Fictício 0001") e os códigos não
correspondem a municípios reais. Nada aqui representa a situação de ente algum.
"""
from __future__ import annotations

import random
from datetime import date

from siope_brasil import coleta
from siope_brasil.config import Config
from siope_brasil.territorio import UFS

# quantidade aproximada de municípios por UF (para simular o volume nacional)
QTD = {"RO": 52, "AC": 22, "AM": 62, "RR": 15, "PA": 144, "AP": 16, "TO": 139, "MA": 217, "PI": 224,
       "CE": 184, "RN": 167, "PB": 223, "PE": 185, "AL": 102, "SE": 75, "BA": 417, "MG": 853, "ES": 78,
       "RJ": 92, "SP": 645, "PR": 399, "SC": 295, "RS": 497, "MS": 79, "MT": 141, "GO": 246, "DF": 0}
CODS = ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.9", "2.1", "2.2", "2.8", "4.8", "4.10",
        "7.2", "7.3", "8.1", "8.2"]
NOMES = {c: f"Indicador fictício {c}" for c in CODS}


def gerar(cfg: Config, anos: list[int], hoje: date, semente: int = 7, escala: float = 1.0) -> int:
    rnd = random.Random(semente)
    municipios = []
    for cod_uf, (sigla, _, _) in UFS.items():
        for n in range(max(1, int(QTD[sigla] * escala)) if QTD[sigla] else 0):
            municipios.append((f"{cod_uf}{9000 + n:04d}", f"Município Fictício {sigla} {n + 1:03d}", sigla))
    coleta.gravar_json_gz(cfg.dir_brutos / "ibge_municipios.json.gz",
                          {"fonte": "sintético", "coletado_em": "2026-01-01T00:00:00+00:00",
                           "municipios": [list(m) for m in municipios]})
    perfil = {m[0]: rnd.random() for m in municipios}
    for ano in anos:
        for b in coleta.bimestres_encerrados(ano, hoje):
            for cod_uf, (sigla, nome_uf, _) in UFS.items():
                ind, dg = [], []
                entes = [("E", None, None)] + [("M", int(c), n) for c, n, uf in municipios if uf == sigla]
                for tipo, muni, nome in entes:
                    p = perfil.get(str(muni).zfill(6), 0.5) if muni else 0.6
                    if p < 0.04 or (p < 0.12 and b >= 3 and ano == hoje.year):
                        continue  # não transmitiu
                    atraso = int(rnd.random() * 80 * (1 - p))
                    fim = coleta_fim(ano, b)
                    data = date.fromordinal(fim.toordinal() + 10 + atraso)
                    if data > hoje:
                        continue
                    dg.append([tipo, muni, nome, data.isoformat(), rnd.random() < 0.1, 100000 + rnd.randint(0, 9999),
                               rnd.randint(1500, 900000)])
                    vaat = p > 0.55
                    base = {"1.1": rnd.gauss(27.5, 2.2), "1.2": rnd.gauss(79, 6.5), "1.4": abs(rnd.gauss(3, 4)),
                            "1.5": rnd.gauss(30, 18) if vaat else 0, "1.6": rnd.gauss(55, 10) if vaat else 0,
                            "1.7": rnd.gauss(50, 6) if vaat else 0, "1.9": abs(rnd.gauss(5, 2.5)),
                            "2.1": rnd.uniform(15, 50), "2.2": rnd.uniform(40, 80), "2.8": rnd.uniform(12, 35),
                            "4.8": rnd.uniform(6000, 22000), "4.10": rnd.uniform(3000, 12000),
                            "7.2": rnd.uniform(0, 5e6), "7.3": rnd.uniform(0, 8e5)}
                    if b < 6:
                        base["1.4"] = rnd.uniform(5, 60)
                    base["1.3"] = max(0, 100 - base["1.2"] - base["1.4"])
                    base["8.1"] = rnd.uniform(2e6, 9e7)
                    base["8.2"] = base["8.1"] * base["1.1"] / 25
                    for c, v in base.items():
                        ind.append([tipo, muni, nome, c, f"{v:.2f}"])
                coleta.gravar_json_gz(coleta.caminho(cfg, ano, b, sigla, "indicadores"),
                                      {"fonte": "sintético", "coletado_em": hoje.isoformat(), "linhas": ind,
                                       "nomes": NOMES})
                coleta.gravar_json_gz(coleta.caminho(cfg, ano, b, sigla, "dados_gerais"),
                                      {"fonte": "sintético", "coletado_em": hoje.isoformat(), "linhas": dg})
    return len(municipios)


def coleta_fim(ano, b):
    from siope_brasil.processa import fim_bimestre
    return fim_bimestre(ano, b)
