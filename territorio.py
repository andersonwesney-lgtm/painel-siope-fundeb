"""Unidades da Federação e regiões (divisão regional do IBGE)."""

# código IBGE da UF: (sigla, nome, região)
UFS = {
    11: ("RO", "Rondônia", "Norte"), 12: ("AC", "Acre", "Norte"), 13: ("AM", "Amazonas", "Norte"),
    14: ("RR", "Roraima", "Norte"), 15: ("PA", "Pará", "Norte"), 16: ("AP", "Amapá", "Norte"),
    17: ("TO", "Tocantins", "Norte"),
    21: ("MA", "Maranhão", "Nordeste"), 22: ("PI", "Piauí", "Nordeste"), 23: ("CE", "Ceará", "Nordeste"),
    24: ("RN", "Rio Grande do Norte", "Nordeste"), 25: ("PB", "Paraíba", "Nordeste"),
    26: ("PE", "Pernambuco", "Nordeste"), 27: ("AL", "Alagoas", "Nordeste"), 28: ("SE", "Sergipe", "Nordeste"),
    29: ("BA", "Bahia", "Nordeste"),
    31: ("MG", "Minas Gerais", "Sudeste"), 32: ("ES", "Espírito Santo", "Sudeste"),
    33: ("RJ", "Rio de Janeiro", "Sudeste"), 35: ("SP", "São Paulo", "Sudeste"),
    41: ("PR", "Paraná", "Sul"), 42: ("SC", "Santa Catarina", "Sul"), 43: ("RS", "Rio Grande do Sul", "Sul"),
    50: ("MS", "Mato Grosso do Sul", "Centro-Oeste"), 51: ("MT", "Mato Grosso", "Centro-Oeste"),
    52: ("GO", "Goiás", "Centro-Oeste"), 53: ("DF", "Distrito Federal", "Centro-Oeste"),
}
SIGLA_PARA_COD = {v[0]: k for k, v in UFS.items()}
SIGLAS = [v[0] for v in UFS.values()]
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]


def uf_do_municipio(cod_muni: int | str) -> str:
    return UFS[int(str(cod_muni)[:2])][0]


def id_estado(sigla: str) -> str:
    """Identificador do ente estadual/distrital no painel (ex.: 'UF-RR')."""
    return f"UF-{sigla}"
