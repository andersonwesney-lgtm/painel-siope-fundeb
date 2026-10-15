# Painel nacional SIOPE e Fundeb (Lei 14.113/2020)

Sistema em Python que baixa os dados abertos do SIOPE de **todos os entes**
(5.569 municípios, 26 estados e o Distrito Federal), avalia as obrigações do
Fundeb para cada um, publica um **painel com filtros** no GitHub Pages e gera
**relatórios em PDF** do recorte filtrado, todos a partir dos mesmos arquivos.

## O que o painel mostra (para o recorte filtrado)

- **Cumprimento das obrigações**: MDE 25% (CF art. 212), remuneração 70%
  (art. 26), até 10% não aplicado (art. 25 § 3º), VAAT 15% em capital (art. 27),
  VAAT na educação infantil (art. 28), destinação de 20% pelos estados (CF art.
  212-A, II) e, a partir de 2026, 4% no fomento ao tempo integral (CF art.
  212-A, XV). Cada linha traz o indicador do SIOPE, a regra e o dispositivo.
- **Sinais de alerta**: obrigação descumprida, fora da regra no meio do ano,
  bimestre vencido sem envio, envio após o prazo. Clique para filtrar.
- **Prazos de transmissão** de cada bimestre e quantos entes enviaram no prazo,
  depois do prazo ou não enviaram.
- **Comparativo por UF** e **comparativo entre entes** (ordenável, do mais grave
  ao menos grave), para achar quem está irregular.
- **Detalhe do ente**: alertas, obrigações, as seis transmissões do ano com
  recibo, todos os indicadores do SIOPE e a lista de verificação documental.

## Filtros

Pedidos: região, UF, município (busca por nome), esfera, exercício, bimestre e
situação (irregular, atenção, regular, sem dados).

Incluídos por fazerem diferença no acompanhamento do Fundeb:

| Filtro | Por quê |
|---|---|
| Obrigação com problema | Responde "quem descumpriu os 70%?" ou "quem está abaixo dos 25%?" sem misturar com outros alertas. |
| Transmissão | Separa quem não enviou o SIOPE (sujeito à suspensão de transferências voluntárias, art. 38 § 1º) de quem enviou atrasado. |
| População | Compara entes de porte parecido; um município de 3 mil habitantes não se compara com uma capital. |
| Complementação-VAAT | As regras dos arts. 27 e 28 só valem para quem recebe VAAT; o filtro isola esse grupo. |

O endereço da página guarda os filtros (`?uf=MG&sit=irregular`), então dá para
enviar a um conselheiro o link já filtrado.

## Escolhas confirmadas

| Tema | Escolha |
|---|---|
| Dados | Download automático da API de dados abertos do SIOPE, todas as UFs |
| Exercícios | Atual e anterior. Hoje: 2025 e 2026. Em janeiro passa sozinho para 2026 e 2027 (`config/painel.yaml`) |
| Publicação | GitHub Pages, atualizado pelo GitHub Actions toda segunda-feira |
| PDFs | Botão no painel que gera o PDF do filtro aplicado, mais lote com Brasil e as 27 UFs a cada atualização |

### Por que GitHub Pages aguenta o volume nacional

O processamento pesado (avaliar as regras de ~5.600 entes em cada bimestre)
roda uma vez no GitHub Actions. O resultado é dividido em arquivos pequenos:

- `dados/<ano>/b<bimestre>.json`: uma linha por ente, com valores, situações e
  alertas já calculados (cerca de 160 KB comprimido);
- `dados/<ano>/b<bimestre>/<UF>.json`: todos os indicadores, carregado só
  quando alguém abre o detalhe de um ente daquela UF.

O navegador baixa só o bimestre escolhido e filtra 5.600 linhas em
milissegundos. Não há servidor, banco de dados ou senha para manter, o link é
fixo, com HTTPS, e abre no celular. Os dois exercícios somam cerca de 40 MB,
bem abaixo do limite de 1 GB do Pages.

Atenção: no plano gratuito do GitHub, o Pages publica só a partir de
repositório **público**. Os dados do SIOPE já são públicos (Lei 14.113, art. 38,
§ 3º). Para repositório privado é preciso plano pago.

### O endereço da página do SIOPE com captcha

A página `indicadoresFinanceirosEEducacionais.do` exige captcha e não é raspada.
A API traz os mesmos indicadores, com a mesma numeração (1.1, 1.2...).

## Por que o painel e os PDFs nunca divergem

Toda a lógica de cumprimento, prazos e alertas está em `siope_brasil/processa.py`.
O painel (JavaScript), o PDF do botão (gerado no navegador) e os PDFs em lote
(Python) **só leem** os mesmos arquivos `dados/<ano>/b<bimestre>.json`. Nenhum
deles recalcula situação. O SHA-256 desse arquivo aparece no painel e no rodapé
e nos metadados de cada PDF; se o identificador for o mesmo, os dados são os
mesmos. Há um teste automatizado que confere isso.

## Estrutura

```
config/
  painel.yaml        título, exercícios, política de coleta, PDFs em lote
  obrigacoes.yaml    indicador -> obrigação -> dispositivo -> regra
  prazos.yaml        regra de prazo e cronograma oficial (quando houver)
siope_brasil/
  coleta.py          API do SIOPE (por exercício, bimestre e UF) e lista do IBGE
  processa.py        regras, prazos, alertas; grava site/dados/
  pdf_lote.py        PDFs do Brasil e das UFs (reportlab)
  territorio.py      UFs e regiões
  cli.py             linha de comando
web/                 o painel (HTML, CSS e JavaScript, sem etapa de build)
tests/               testes (pytest) e gerador de dados fictícios para teste
dados/importados/    arquivos opcionais (lista oficial de beneficiários do VAAT)
.github/workflows/publicar.yml
```

## Executar localmente

Python 3.10 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m siope_brasil coletar         # primeira vez: cerca de 540 consultas à API
python -m siope_brasil gerar           # processa, monta site/ e gera os PDFs em lote
python -m siope_brasil servir          # abre em http://localhost:8000
python -m pytest -q                    # testes
```

O painel precisa ser aberto por um servidor (comando `servir`), não com duplo
clique no arquivo, porque ele carrega os dados por `fetch`.

Coletar só algumas UFs, para testar: `python -m siope_brasil coletar --ufs RR AP`.

## Carregar e atualizar os dados nacionais

- **Automático**: o GitHub Actions roda toda segunda-feira. Os dados já baixados
  ficam guardados em cache; a cada execução só os exercícios recentes são
  baixados de novo, para captar envios atrasados e retificações
  (`coleta.recoletar_ultimos_exercicios`).
- **Na hora**: aba **Actions > Publicar painel SIOPE > Run workflow**. Marque
  "Baixar de novo todos os exercícios" para refazer tudo.
- **Novo exercício**: nada a fazer; a janela "atual e anterior" anda sozinha.
  Para fixar exercícios, use `exercicios.lista` em `config/painel.yaml`.
- Cada execução guarda os dados brutos como artefato por 90 dias, para
  auditoria.

Se um dia a API do FNDE recusar conexões vindas do GitHub, rode
`python -m siope_brasil coletar` no seu computador, retire `dados/brutos/` do
`.gitignore`, faça commit dos dados e a publicação segue usando o que estiver no
repositório.

## Publicar

1. Crie um repositório público no GitHub (por exemplo `painel-siope-fundeb`) e
   envie esta pasta:
   ```bash
   git init -b main && git add . && git commit -m "Painel SIOPE e Fundeb"
   git remote add origin https://github.com/<conta>/painel-siope-fundeb.git
   git push -u origin main
   ```
2. **Settings > Pages > Source: GitHub Actions**.
3. **Actions > Publicar painel SIOPE > Run workflow**. A primeira execução baixa
   tudo e leva mais tempo. Ao terminar, o link aparece no resumo:
   `https://<conta>.github.io/painel-siope-fundeb/`.
4. Copie o link para `painel.url_publica` em `config/painel.yaml` (ele passa a
   sair nos PDFs) e envie às secretarias, à contabilidade, aos conselheiros do
   CACS-Fundeb e aos órgãos de controle.

## Gerar os relatórios em PDF

- **No painel**: aplique os filtros (um município, uma UF, só irregulares...) e
  clique em **Gerar PDF deste recorte**. No detalhe de um ente, **PDF deste ente**.
- **Em lote**: a cada atualização, `site/relatorios/<ano>/` recebe o PDF do
  Brasil e de cada UF, listados no painel em "Relatórios em PDF prontos".
- **Pela linha de comando**:
  `python -m siope_brasil pdf --uf MG` ou `python -m siope_brasil pdf --ano 2025 --bimestre 6`.

Cada PDF traz o recorte, os avisos de conferência, o resumo, as obrigações com
dispositivo, os alertas, os prazos, o comparativo, a lista de entes irregulares
(ou o detalhe do ente), a verificação documental, o identificador dos dados e
um campo de ciência.

## O que precisa ser conferido (sinalizado no painel, nos PDFs e no código)

- **Referências legais**: todo item de `config/obrigacoes.yaml` está com
  `conferir: true`. Os percentuais vêm do texto da Lei 14.113/2020 e da
  Constituição; nenhum foi estimado. Confira o texto vigente e mude para
  `conferir: false`.
- **4% em tempo integral (1.9)**: indicador novo no SIOPE em 2026. Confira a
  base de cálculo e as hipóteses de dispensa na regulamentação da CIF.
- **Prazos de transmissão**: calculados como fim do bimestre + 30 dias (art. 38,
  § 1º). Se o FNDE publicar cronograma, cadastre as datas em
  `config/prazos.yaml` com o ato. O sistema não traz nenhuma data ou portaria.
- **Complementação-VAAT**: o SIOPE não informa quem é beneficiário. Sem a lista
  oficial em `dados/importados/vaat_<ano>.csv` (coluna `ente`, com o código de 6
  dígitos do município ou a sigla da UF), o ente é tratado como beneficiário
  quando declara valor de VAAT, e o painel mostra "inferido".
- **Data de transmissão**: a API traz a data da declaração. Em declarações
  retificadas, pode ser a da retificação; confira o recibo.

## Limitações conhecidas

- Este código foi testado com dados fictícios em volume nacional (5.596 entes,
  processados em cerca de 6 segundos) e com amostras reais da API consultadas
  manualmente para conferir o formato. A primeira coleta completa acontece na primeira execução no
  GitHub.
- Os indicadores são os calculados pelo FNDE; o sistema não os recalcula.
- Brasília (código 530010) não aparece como município: o DF declara ao SIOPE
  como ente distrital.
