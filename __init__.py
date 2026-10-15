"""Painel nacional SIOPE x Lei 14.113/2020 (Fundeb).

coletar (API do SIOPE, por UF) -> processar (regras, um arquivo por exercício e
bimestre) -> site estático (painel com filtros) + PDFs.
O painel e os PDFs leem os MESMOS arquivos processados; nenhum deles recalcula
situação de cumprimento.
"""

__version__ = "2.0.0"
