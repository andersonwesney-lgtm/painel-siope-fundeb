# Rotina diária do painel SIOPE x Fundeb

## O que roda, todo dia às 06:00 (Brasília)

1. **API de dados abertos do SIOPE** (FNDE, Olinda): indicadores e declarações de todos os entes.
2. **Recibos de Transmissão do SIOPE** (`https://www.fnde.gov.br/siope/recibosTransmissao.do`), uma
   página pública e **sem captcha**. A rotina consulta só os entes que ainda faltam na base aberta,
   a partir do 4º bimestre de 2026 e em todos os períodos seguintes, e grava recibo, data de
   transmissão e retificação.
3. **Processamento e montagem do site**: quem só aparece nos recibos passa a contar como transmitido,
   com a data real. Por exemplo, Capela (AL), 4º bim. 2026, transmitido em 08/10/2026.
4. **Validação**:
   - o catálogo precisa ter pelo menos 5.500 municípios;
   - todos os arquivos dos bimestres precisam existir;
   - nenhum bimestre pode perder mais de 20% dos entes com dados em relação à última publicação.
5. **Publicação** no GitHub Pages, só se tudo acima passou.

## Por que não o relatório "Municípios transmitidos por UF"

Esse relatório tem reCAPTCHA (Google) e não é coletado. A página "Recibos de Transmissão" é do mesmo
SIOPE e traz, para cada município e período, o que o relatório mostra: se transmitiu, o nº do recibo,
a data de transmissão e se é retificadora. Não há contorno de captcha em nenhuma etapa.

Conferência feita em 23/10/2026:

| Município | Base aberta (4º bim. 2026) | Recibos de Transmissão |
|---|---|---|
| Capela/AL | ausente | recibo 454170, transmitido em 08/10/2026 |
| Anadia/AL | 25/09/2026 | recibo 451644, transmitido em 25/09/2026 |
| Arapiraca/AL | 22/09/2026 | recibo 451110, transmitido em 22/09/2026 |

## Confiabilidade

- **Sem duplicação.**
  - Cada recibo é guardado com a chave `ente|ano|bimestre`. Rodar de novo atualiza o registro, não cria outro.
  - Um ente já consultado no dia não é consultado de novo.
  - O arquivo só é regravado se mudou.
- **Fonte fora do ar ou mudou.**
  - Toda resposta é conferida: as colunas precisam ser exatamente as esperadas e as datas precisam ser plausíveis.
  - Resposta com captcha ou fora do padrão é descartada.
  - Depois de 8 falhas seguidas, ou com mais de 30% de erros, a etapa para e os recibos já guardados continuam valendo.
- **Nunca publica dado quebrado.** Se a validação reprovar, ou se mais de 25% das consultas à API
  falharem, a execução termina com erro e o painel no ar continua o da última execução válida.
- **Aviso.**
  - Em falha ou aviso, a rotina abre (ou comenta) a issue **"Atualização do painel"** no repositório, e o GitHub manda e-mail ao dono.
  - Quando tudo volta ao normal, a issue é fechada sozinha.
  - O aviso por Telegram é opcional (veja abaixo).
- **Registro.** Cada execução fica gravada com início, fim, períodos capturados, consultas, novos
  recibos, erros e status:
  - no ramo `estado` do repositório: `execucoes.jsonl` (histórico), `ultimo_status.json` e `recibos.json`;
  - no painel: `dados/execucoes.json` (últimas 30 execuções).
- **Educação com o servidor do FNDE.**
  - No máximo 2 consultas simultâneas, com pausa de 1 s.
  - Até 3.000 consultas por dia.
  - Cada ente é consultado uma única vez por dia e só enquanto falta.
  - A rotina se identifica no User-Agent.

## Onde está agendado

No GitHub Actions do próprio repositório: `.github/workflows/publicar.yml`, `cron: "0 9 * * *"`
(09:00 UTC = 06:00 em Brasília). Não precisa de servidor. Para rodar na hora, use Actions >
Publicar painel SIOPE > **Run workflow**.

Em servidor próprio (alternativa), o mesmo comando roda pelo cron:

```
0 6 * * *  cd /caminho/painel && python -m siope_brasil diario >> registro.log 2>&1 && <comando de publicação>
```

O código de saída 1 significa "não publicar".

## Configuração (`config/painel.yaml`)

```yaml
recibos:
  a_partir_de: {ano: 2026, bimestre: 4}
  consultas_simultaneas: 2
  pausa_entre_consultas_s: 1.0
  max_consultas_por_execucao: 3000
validacao:
  municipios_minimos: 5500
  queda_maxima_entes_com_dados: 0.2
```

## O que depende de você

- **Nada no dia a dia.**
- **Opcional, aviso por Telegram:**
  1. Crie um bot com o @BotFather e copie o token.
  2. Mande uma mensagem ao bot e pegue o seu `chat_id` em `https://api.telegram.org/bot<TOKEN>/getUpdates`.
  3. No repositório, em Settings > Secrets and variables > Actions, crie os segredos `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`.
- **E-mail:** chega automaticamente pelas issues, desde que você esteja "Watching" o repositório, o
  que é o padrão para o dono.
- **Se o FNDE mudar a página de recibos:** a rotina para de usar essa fonte, mantém o que tem e abre a
  issue. Aí é preciso ajustar `siope_brasil/recibos.py`.
