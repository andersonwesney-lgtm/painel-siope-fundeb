/* Painel SIOPE e Fundeb: lê os arquivos gerados por siope_brasil/processa.py.
 * Este script NÃO calcula cumprimento, prazos ou alertas: só filtra, conta e
 * formata o que veio processado. O PDF do recorte usa exatamente as mesmas linhas
 * exibidas na tela. */
"use strict";

const S = {
  manifest: null, cat: null, entes: [], entePorId: new Map(), rotuloParaId: new Map(),
  periodo: null, linhas: [], cachePeriodo: new Map(), cacheUF: new Map(),
  f: {}, ordem: { col: "grav", dir: -1 }, limite: 100, detalhe: null,
};
const FILTROS = ["ano", "bim", "regiao", "uf", "esfera", "ente", "sit", "obr", "tx", "pop", "vaat"];
const SIT_PROBLEMA = ["descumprida", "parcial_abaixo", "verificar"];
const $ = (id) => document.getElementById(id);
const fmt2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = new Intl.NumberFormat("pt-BR");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function fv(v, u) {
  if (v === null || v === undefined) return "-";
  if (u === "%") return fmt2.format(v) + "%";
  if (u === "R$") return "R$ " + fmt2.format(v);
  return fmt2.format(v);
}
function fd(iso) {
  if (!iso) return "-";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}
const pct = (n, d) => (d ? fmt2.format((100 * n) / d).replace(/,00$/, "") + "%" : "-");
const sit = (k) => S.cat.situacoes[k] || { rotulo: k, nivel: "neutro" };
const pill = (k) => `<span class="pill ${sit(k).nivel}">${esc(sit(k).rotulo)}</span>`;
const obrPorId = (id) => S.cat.obrigacoes.find((o) => o.id === id);
const curto = (h) => (h || "").slice(0, 12).toUpperCase();

async function getJSON(p) {
  const r = await fetch(p);
  if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
  return r.json();
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (t.hidden = true), 3500);
}

/* ------------------------------------------------------------ alertas ---- */
function alertaInfo(cod) {
  const [nivel, tipo, ref] = cod.split(":");
  if (tipo === "o") {
    const o = obrPorId(ref);
    const titulo = nivel === "c" ? `${o.titulo}: descumprida` : `${o.titulo}: fora da regra até o bimestre`;
    return { nivel: nivel === "c" ? "critico" : "atencao", titulo, base: o.dispositivo, filtro: { obr: ref } };
  }
  if (tipo === "s") return { nivel: "atencao", titulo: `${ref}º bimestre sem registro na base aberta do SIOPE, prazo vencido (pode já ter sido transmitido)`,
    base: S.cat.prazo_regra.dispositivo, filtro: { tx: "vencido" } };
  const titulo = nivel === "c" ? `${ref}º bimestre não transmitido, prazo vencido` : `${ref}º bimestre transmitido após o prazo`;
  return { nivel: nivel === "c" ? "critico" : "atencao", titulo, base: S.cat.prazo_regra.dispositivo,
    filtro: nivel === "c" ? { tx: "vencido" } : {} };
}

/* ------------------------------------------------------------ carga ---- */
async function iniciar() {
  try {
    [S.manifest, S.cat] = await Promise.all([getJSON("dados/manifest.json"), getJSON("dados/catalogo.json")]);
    const ent = await getJSON("dados/entes.json");
    const ix = Object.fromEntries(ent.colunas.map((c, i) => [c, i]));
    S.entes = ent.linhas.map((l) => ({ id: l[ix.id], nome: l[ix.nome], uf: l[ix.uf], regiao: l[ix.regiao], esfera: l[ix.esfera], pop: l[ix.pop] }));
    S.entes.forEach((e) => S.entePorId.set(e.id, e));
  } catch (err) {
    $("meta").textContent = "Não foi possível carregar os dados do painel (" + err.message + "). Rode a geração do site e abra-o por um servidor (ver README).";
    return;
  }
  montarControles();
  carregarLote();
  lerURL();
  await carregarPeriodo();
}

function montarControles() {
  const c = S.cat;
  $("titulo").textContent = c.painel.titulo || "Painel SIOPE e Fundeb";
  $("subtitulo").textContent = c.painel.subtitulo || "SIOPE e Lei 14.113/2020";
  if (S.manifest.demo) { $("aviso-demo").textContent = S.manifest.demo; $("aviso-demo").hidden = false; }
  $("f-ano").innerHTML = S.manifest.exercicios.map((e) => `<option value="${e.ano}">${e.ano}</option>`).join("");
  $("f-regiao").innerHTML += c.regioes.map((r) => `<option>${esc(r)}</option>`).join("");
  $("f-obr").innerHTML += c.obrigacoes.filter((o) => o.tipo !== "informativo")
    .map((o) => `<option value="${o.id}">${esc(o.cod_exib + " " + o.titulo)}</option>`).join("");
  $("f-pop").innerHTML += c.faixas_pop.map((f) => `<option value="${f.id}">${esc(f.rotulo)}</option>`).join("");
  preencherUFs();
  for (const k of FILTROS) {
    const el = $("f-" + k);
    el.addEventListener(k === "ente" ? "change" : "change", () => aoMudar(k));
  }
  $("f-ente").addEventListener("input", sugerirEntes);
  $("b-limpar").addEventListener("click", () => {
    for (const k of FILTROS) if (k !== "ano" && k !== "bim") S.f[k] = "";
    S.detalhe = null;
    sincronizarControles(); preencherUFs(); renderizar();
  });
  $("b-pdf").addEventListener("click", () => gerarPDF());
  $("b-mais").addEventListener("click", () => { S.limite += 200; renderEntes(filtrar()); });
}

function preencherUFs() {
  const reg = S.f.regiao || $("f-regiao").value;
  const ufs = Object.entries(S.cat.ufs).filter(([, u]) => !reg || u.regiao === reg).sort((a, b) => a[0].localeCompare(b[0]));
  const atual = S.f.uf || "";
  $("f-uf").innerHTML = `<option value="">Todas</option>` + ufs.map(([s, u]) => `<option value="${s}">${s} · ${esc(u.nome)}</option>`).join("");
  $("f-uf").value = ufs.some(([s]) => s === atual) ? atual : "";
}

function rotuloEnte(e) { return `${e.nome} · ${e.uf}`; }
function sugerirEntes() {
  const q = norm($("f-ente").value.trim());
  const uf = S.f.uf, esf = S.f.esfera;
  const cand = [];
  if (q.length >= 2) {
    for (const e of S.entes) {
      if (uf && e.uf !== uf) continue;
      if (esf && e.esfera !== esf) continue;
      if (norm(e.nome).includes(q)) { cand.push(e); if (cand.length >= 40) break; }
    }
  }
  $("l-entes").innerHTML = cand.map((e) => { S.rotuloParaId.set(rotuloEnte(e), e.id); return `<option value="${esc(rotuloEnte(e))}"></option>`; }).join("");
}

function aoMudar(k) {
  const el = $("f-" + k);
  if (k === "ente") {
    const id = S.rotuloParaId.get(el.value) || "";
    if (el.value && !id) { toast("Escolha um nome da lista de sugestões."); return; }
    S.f.ente = id;
    S.detalhe = id || null;
  } else {
    S.f[k] = el.value;
  }
  if (k === "regiao") preencherUFs();
  if (k === "ano") { S.f.bim = ""; carregarPeriodo(); return; }
  if (k === "bim") { carregarPeriodo(); return; }
  S.limite = 100;
  renderizar();
}

function lerURL() {
  let p;
  try { p = new URLSearchParams(location.search); } catch { return; }
  for (const k of FILTROS) S.f[k] = p.get(k) || "";
  if (S.f.ente) S.detalhe = S.f.ente;
}
function escreverURL() {
  try {
    const p = new URLSearchParams();
    for (const k of FILTROS) if (S.f[k]) p.set(k, S.f[k]);
    const q = p.toString();
    history.replaceState(null, "", q ? "?" + q : location.pathname);
  } catch { /* visualizadores que não permitem alterar o endereço */ }
}

// [prefixo, período] para os textos: um bimestre, ou todos os bimestres consolidados.
function rotuloPeriodo(bim) {
  return bim.todos ? ["todos os bimestres,", `1º ao ${bim.bimestre}º (situação pelo bimestre mais recente de cada ente; evolução bimestre a bimestre)`]
    : ["dados até o", bim.rotulo];
}

function exercicioAtual() {
  const ex = S.manifest.exercicios;
  return ex.find((e) => String(e.ano) === String(S.f.ano)) || ex[ex.length - 1];
}

async function carregarPeriodo() {
  const ex = exercicioAtual();
  S.f.ano = String(ex.ano);
  $("f-bim").innerHTML = (ex.todos ? `<option value="todos">${esc(ex.todos.rotulo)}</option>` : "") + ex.bimestres.map((b) => `<option value="${b.bimestre}">${esc(b.rotulo)}${b.cobertura < 0.5 ? ` (${fmt2.format(b.cobertura * 100).replace(/,00$/, "")}% dos entes declararam)` : ""}</option>`).join("");
  const bim = (S.f.bim === "todos" && ex.todos) || ex.bimestres.find((b) => String(b.bimestre) === String(S.f.bim))
    || ex.bimestres.find((b) => b.bimestre === ex.bimestre_padrao) || ex.bimestres[ex.bimestres.length - 1];
  S.f.bim = bim.todos ? "todos" : String(bim.bimestre);
  sincronizarControles();
  let dados = S.cachePeriodo.get(bim.arquivo);
  if (!dados) {
    $("meta").textContent = "Carregando " + bim.rotulo + " de " + ex.ano + "…";
    dados = await getJSON(bim.arquivo);
    S.cachePeriodo.set(bim.arquivo, dados);
  }
  const ix = Object.fromEntries(dados.colunas.map((c, i) => [c, i]));
  const obr = S.cat.obrigacoes;
  S.linhas = dados.linhas.map((l) => {
    const r = { id: l[ix.id], sg: l[ix.sg], nc: l[ix.nc], na: l[ix.na], al: l[ix.al], tb: l[ix.tb], td: l[ix.td],
      vaat: l[ix.vaat], tx6: l[ix.tx6], bv: ix.bv != null ? l[ix.bv] : null, sgb: ix.sgb != null ? l[ix.sgb] : null, v: {}, s: {} };
    for (const o of obr) { r.v[o.id] = l[ix["v." + o.id]]; r.s[o.id] = l[ix["s." + o.id]]; }
    r.e = S.entePorId.get(r.id) || { id: r.id, nome: r.id, uf: "", regiao: "", esfera: "", pop: null };
    return r;
  });
  S.periodo = { ex, bim, dados };
  renderizar();
}

function sincronizarControles() {
  for (const k of FILTROS) {
    if (k === "ente") {
      const e = S.entePorId.get(S.f.ente);
      $("f-ente").value = e ? rotuloEnte(e) : "";
      if (e) S.rotuloParaId.set(rotuloEnte(e), e.id);
    } else if ($("f-" + k)) {
      $("f-" + k).value = S.f[k] || "";
    }
  }
}

/* ------------------------------------------------------------ filtro ---- */
function filtrar() {
  const f = S.f;
  const faixa = f.pop ? S.cat.faixas_pop.find((x) => x.id === f.pop) : null;
  return S.linhas.filter((r) => {
    const e = r.e;
    if (f.regiao && e.regiao !== f.regiao) return false;
    if (f.uf && e.uf !== f.uf) return false;
    if (f.esfera && e.esfera !== f.esfera) return false;
    if (f.ente && r.id !== f.ente) return false;
    if (f.sit && r.sg !== f.sit) return false;
    if (f.obr && !SIT_PROBLEMA.includes(r.s[f.obr])) return false;
    if (f.tx) {
      if (f.tx === "vencido") { if (!r.al.some((a) => a.startsWith("c:t:") || a.startsWith("a:s:"))) return false; }
      else if (r.tb !== f.tx) return false;
    }
    if (faixa && (e.pop == null || e.pop < faixa.min || (faixa.max != null && e.pop >= faixa.max))) return false;
    if (f.vaat === "sim" && !(r.vaat === "sim" || r.vaat === "sim_inf")) return false;
    if (f.vaat === "nao" && !(r.vaat === "nao" || r.vaat === "nao_inf")) return false;
    return true;
  });
}

function descreverRecorte() {
  const f = S.f, partes = [];
  if (f.ente) { const e = S.entePorId.get(f.ente); return e ? rotuloEnte(e) : f.ente; }
  if (f.regiao) partes.push("Região " + f.regiao);
  if (f.uf) partes.push(S.cat.ufs[f.uf].nome);
  if (f.esfera) partes.push(f.esfera === "municipal" ? "municípios" : "estados e DF");
  if (f.sit) partes.push("situação: " + sit(f.sit).rotulo.toLowerCase());
  if (f.obr) partes.push("problema em: " + obrPorId(f.obr).titulo);
  if (f.tx) partes.push("transmissão: " + $("f-tx").selectedOptions[0].textContent.toLowerCase());
  if (f.pop) partes.push("população " + S.cat.faixas_pop.find((x) => x.id === f.pop).rotulo);
  if (f.vaat) partes.push(f.vaat === "sim" ? "beneficiários do VAAT" : "não beneficiários do VAAT");
  return partes.length ? partes.join(" · ") : "Brasil (todos os entes)";
}

/* ---------------------------------------------------------- agregação ---- */
function agregar(rows) {
  const a = { total: rows.length, sg: { irregular: 0, atencao: 0, regular: 0, sem_info: 0 }, obr: {}, al: {}, tx: [], uf: {} };
  for (const o of S.cat.obrigacoes) a.obr[o.id] = {};
  for (let k = 0; k < 6; k++) a.tx.push({});
  for (const r of rows) {
    a.sg[r.sg]++;
    for (const o of S.cat.obrigacoes) { const s = r.s[o.id]; a.obr[o.id][s] = (a.obr[o.id][s] || 0) + 1; }
    for (const c of r.al) a.al[c] = (a.al[c] || 0) + 1;
    for (let k = 0; k < 6; k++) { const s = S.cat.cod_tx[r.tx6[k]]; a.tx[k][s] = (a.tx[k][s] || 0) + 1; }
    const u = (a.uf[r.e.uf] ||= { n: 0, irregular: 0, atencao: 0, sem_info: 0, vencido: 0, rem: 0, mde: 0 });
    u.n++; if (r.sg === "irregular") u.irregular++; if (r.sg === "atencao") u.atencao++; if (r.sg === "sem_info") u.sem_info++;
    if (r.al.some((c) => c.startsWith("c:t:") || c.startsWith("a:s:"))) u.vencido++;
    if (r.s.remuneracao_70 === "descumprida") u.rem++;
    if (r.s.mde_25 === "descumprida") u.mde++;
  }
  return a;
}

/* ------------------------------------------------------------ render ---- */
function renderizar() {
  escreverURL();
  const rows = filtrar();
  const ag = agregar(rows);
  const { ex, bim, dados } = S.periodo;
  $("meta").innerHTML = [
    `Exercício <strong>${ex.ano}</strong>`, `${esc(rotuloPeriodo(bim)[0])} <strong>${esc(rotuloPeriodo(bim)[1])}</strong>${bim.bimestre < 6 ? " (exercício em andamento)" : ""}`,
    `situação calculada em ${fd(dados.data_referencia)}`, `última coleta ${esc((dados.ultima_coleta || "-").slice(0, 10))}`,
    `identificador dos dados <span class="mono">${curto(bim.sha256)}</span>`,
  ].map((x) => `<span>${x}</span>`).join("");
  renderConferir(ex);
  renderResumo(rows, ag);
  renderEvolucao(rows);
  renderObrigacoes(rows, ag);
  renderAlertas(ag);
  renderPrazos(rows, ag);
  renderUF(ag);
  renderEntes(rows);
  renderDetalhe();
  renderDocs();
  renderRodape();
}

function renderConferir(ex) {
  const n = S.cat.obrigacoes.filter((o) => o.conferir).length;
  const itens = [];
  if (n) itens.push(`${n} referência(s) legal(is) marcadas para conferência na fonte oficial (config/obrigacoes.yaml).`);
  if (S.cat.base_aberta_so_aviso) itens.push("Transmissões: base de dados abertos do SIOPE (FNDE), completada diariamente pela página pública \"Recibos de Transmissão\" do SIOPE, porque a base aberta chega com atraso. Ente sem registro em nenhuma das duas após o prazo aparece em atenção, não como irregular.");
  if (ex.prazos.some((p) => p.calculado)) itens.push(`Prazos de transmissão calculados pela regra do ${esc(S.cat.prazo_regra.dispositivo)}; cadastre o cronograma oficial do FNDE em config/prazos.yaml, se houver.`);
  if (!ex.vaat_lista_oficial) itens.push(esc(S.cat.vaat_nota));
  $("conferir").innerHTML = itens.length ? `<strong>Conferir antes de usar em prestação de contas.</strong><ul>${itens.map((i) => `<li>${i}</li>`).join("")}</ul>` : "";
  $("conferir").hidden = !itens.length;
}

function renderResumo(rows, ag) {
  const t = (cls, rot, n, sub) => `<div class="tile ${cls}"><span class="eyebrow">${rot}</span><span class="n">${n}</span><span class="sub">${sub}</span></div>`;
  const b = S.periodo.bim.bimestre;
  const tb = ag.tx[b - 1];
  $("resumo").innerHTML = [
    t("", "Entes no recorte", fmtInt.format(ag.total), esc(descreverRecorte())),
    t("critico", "Irregulares", fmtInt.format(ag.sg.irregular), `${pct(ag.sg.irregular, ag.total)} · ${S.cat.base_aberta_so_aviso ? "descumprimento de obrigação" : "descumprimento ou prazo vencido"}`),
    t("atencao", "Atenção", fmtInt.format(ag.sg.atencao), `${pct(ag.sg.atencao, ag.total)} · a verificar ou acompanhar`),
    t("ok", "Regulares", fmtInt.format(ag.sg.regular), `${pct(ag.sg.regular, ag.total)} · sem alertas`),
    t("", `${b}º bimestre transmitido`, fmtInt.format((tb.no_prazo || 0) + (tb.fora_prazo || 0) + (tb.sem_data || 0)),
      `${fmtInt.format(tb.no_prazo || 0)} no prazo · ${fmtInt.format(tb.atrasado || 0)} sem registro após o prazo`),
  ].join("");
}

function celObrigacao(o, compacto) {
  return `<strong${compacto ? ` title="${esc(o.obrigacao)}"` : ""}>${esc(o.titulo)}</strong>${compacto ? "" : `<span class="disp">${esc(o.obrigacao)}</span>`}
    <span class="disp">${o.fonte_url ? `<a href="${esc(o.fonte_url)}" target="_blank" rel="noopener">${esc(o.dispositivo)}</a>` : esc(o.dispositivo)}</span>
    ${o.conferir ? `<span class="flag">Referência legal a conferir na fonte oficial</span>` : ""}`;
}

/* Evolução (só na opção "Todos os bimestres"): situação dos entes do recorte em cada bimestre. */
const LETRA_SIT = { I: "irregular", A: "atencao", R: "regular", S: "sem_info" };
function evolucao(rows) {
  const bims = S.periodo.bim.bimestres || [];
  return bims.map((b) => {
    const c = { irregular: 0, atencao: 0, regular: 0, sem_info: 0 };
    for (const r of rows) { const k = LETRA_SIT[(r.sgb || "")[b - 1]]; if (k) c[k]++; }
    return [b, c];
  });
}
function renderEvolucao(rows) {
  let sec = $("s-evolucao");
  if (!S.periodo.bim.todos) { if (sec) sec.hidden = true; return; }
  if (!sec) {
    sec = document.createElement("section");
    sec.id = "s-evolucao";
    $("s-obrigacoes").before(sec);
  }
  sec.hidden = false;
  const cols = [["irregular", "Irregulares"], ["atencao", "Atenção"], ["regular", "Regulares"], ["sem_info", "Sem dados"]];
  sec.innerHTML = `<h2>Evolução por bimestre</h2><p class="sub">Situação dos entes do recorte em cada bimestre, como avaliada no próprio bimestre.</p>
    <div class="tabela"><table><thead><tr><th>Bimestre</th>${cols.map(([, r]) => `<th class="num">${r}</th>`).join("")}</tr></thead><tbody>${
      evolucao(rows).map(([b, c]) => `<tr><td>${b}º bimestre</td>${cols.map(([k]) => `<td class="num">${c[k] ? `<span class="pill ${sit(k).nivel}">${fmtInt.format(c[k])}</span>` : "-"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
const faixaBimestres = (r) => [...(r.sgb || "")].map((l, k) => l === "-" ? "" : `<span class="pill ${sit(LETRA_SIT[l]).nivel}" title="${k + 1}º bimestre: ${esc(sit(LETRA_SIT[l]).rotulo)}">${k + 1}</span>`).join(" ");

function renderObrigacoes(rows, ag) {
  const unico = rows.length === 1 ? rows[0] : null;
  $("obr-sub").textContent = unico
    ? "Valores acumulados até o bimestre de referência. Obrigações anuais se fecham no 6º bimestre."
    : "Quantidade de entes do recorte em cada situação. Obrigações anuais se fecham no 6º bimestre; antes disso a situação é parcial.";
  if (S.periodo.bim.todos) $("obr-sub").textContent += " Em \"Todos os bimestres\", vale o bimestre mais recente com dados de cada ente.";
  if (unico) {
    $("t-obr").innerHTML = `<thead><tr><th>Ind.</th><th>Obrigação e dispositivo</th><th class="num">Valor</th><th>Regra</th><th>Situação</th></tr></thead><tbody>` +
      S.cat.obrigacoes.map((o) => `<tr><td class="code">${o.cod_exib}</td><td>${celObrigacao(o)}${o.nota ? `<span class="nota">${esc(o.nota)}</span>` : ""}</td>
        <td class="num">${fv(unico.v[o.id], o.unidade)}</td><td>${esc(o.regra)}</td><td>${pill(unico.s[o.id])}</td></tr>`).join("") + "</tbody>";
    return;
  }
  const cols = [["cumprida", "Cumpridas"], ["descumprida", "Descumpridas"], ["parcial_ok", "No rumo (parcial)"], ["parcial_abaixo", "Fora da regra (parcial)"], ["apuracao_anual", "Apurado no 6º bim."], ["sem_dados", "Sem dados"], ["nao_publicado", "Aguardando base aberta"], ["nao_aplica", "Não se aplica"]];
  $("t-obr").innerHTML = `<thead><tr><th>Ind.</th><th>Obrigação e dispositivo</th><th>Regra</th>${cols.map(([, r]) => `<th class="num">${r}</th>`).join("")}<th class="num">Cumprimento</th></tr></thead><tbody>` +
    S.cat.obrigacoes.filter((o) => o.tipo !== "informativo").map((o) => {
      const c = ag.obr[o.id];
      const bons = (c.cumprida || 0) + (c.parcial_ok || 0), ruins = (c.descumprida || 0) + (c.parcial_abaixo || 0);
      return `<tr><td class="code">${o.cod_exib}</td><td>${celObrigacao(o, true)}</td><td>${esc(o.regra)}</td>
        ${cols.map(([k]) => `<td class="num">${c[k] ? fmtInt.format(c[k]) : "-"}</td>`).join("")}
        <td class="num">${pct(bons, bons + ruins)}</td></tr>`;
    }).join("") + "</tbody>";
}

function renderAlertas(ag) {
  const itens = Object.entries(ag.al).map(([c, n]) => ({ c, n, ...alertaInfo(c) }))
    .sort((a, b) => (a.nivel === b.nivel ? b.n - a.n : a.nivel === "critico" ? -1 : 1));
  $("t-alertas").innerHTML = itens.length
    ? `<thead><tr><th>Nível</th><th>Alerta</th><th>Base legal</th><th class="num">Entes</th></tr></thead><tbody>` +
      itens.map((i) => `<tr class="clic" data-c="${i.c}"><td>${pill(i.nivel === "critico" ? "irregular" : "atencao").replace("Irregular", "Crítico")}</td>
        <td>${esc(i.titulo)}</td><td>${esc(i.base)}</td><td class="num">${fmtInt.format(i.n)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="vazio">Nenhum sinal de alerta no recorte.</td></tr></tbody>`;
  $("t-alertas").querySelectorAll("tr.clic").forEach((tr) => tr.addEventListener("click", () => {
    Object.assign(S.f, alertaInfo(tr.dataset.c).filtro); sincronizarControles(); renderizar();
  }));
}

function renderPrazos(rows, ag) {
  const ex = S.periodo.ex, unico = rows.length === 1 ? rows[0] : null;
  $("prazos-sub").textContent = `Registro bimestral exigido pelo ${S.cat.prazo_regra.dispositivo}. Consequência do atraso: ${S.cat.prazo_regra.consequencia}`;
  if (unico) {
    const det = S.cacheUF.get(chaveUF(unico.e.uf));
    const tx = det && det.entes[unico.id] ? det.entes[unico.id].tx : null;
    $("t-prazos").innerHTML = `<thead><tr><th>Bimestre</th><th>Prazo</th><th>Declaração</th><th>Situação</th></tr></thead><tbody>` +
      ex.prazos.map((p, k) => {
        const t = tx ? tx[k] : [null, S.cat.cod_tx[unico.tx6[k]], false, ""];
        return `<tr><td>${k + 1}º bimestre</td><td class="num">${fd(p.data)}<span class="disp">${p.calculado ? "calculado" : "oficial"}</span></td>
          <td class="num">${fd(t[0])}${t[3] ? `<span class="disp">recibo ${esc(t[3])}${t[2] ? " · retificada" : ""}</span>` : ""}</td><td>${pill(t[1])}${t[2] ? `<span class="nota">Declaração retificada: a data pode ser a da retificação. Confira o recibo no SIOPE.</span>` : ""}</td></tr>`;
      }).join("") + "</tbody>";
    return;
  }
  const cols = [["no_prazo", "No prazo"], ["fora_prazo", "Após o prazo"], ["atrasado", "Sem registro, prazo vencido"], ["aguardando", "Dentro do prazo"], ["em_curso", "Em curso"]];
  $("t-prazos").innerHTML = `<thead><tr><th>Bimestre</th><th>Prazo</th>${cols.map(([, r]) => `<th class="num">${r}</th>`).join("")}</tr></thead><tbody>` +
    ex.prazos.map((p, k) => `<tr><td>${k + 1}º bimestre</td><td class="num">${fd(p.data)}<span class="disp">${p.calculado ? "calculado" : "oficial"}</span></td>
      ${cols.map(([c]) => `<td class="num">${ag.tx[k][c] ? fmtInt.format(ag.tx[k][c]) : "-"}</td>`).join("")}</tr>`).join("") + "</tbody>";
}

function renderUF(ag) {
  const linhas = Object.entries(ag.uf).sort((a, b) => b[1].irregular / b[1].n - a[1].irregular / a[1].n);
  $("s-uf").hidden = linhas.length < 2;
  $("t-uf").innerHTML = `<thead><tr><th>UF</th><th class="num">Entes</th><th>Irregulares</th><th class="num">Atenção</th><th class="num">Vencido sem envio</th><th class="num">Remun. 70% descumprida</th><th class="num">MDE 25% descumprida</th><th class="num">Sem dados</th></tr></thead><tbody>` +
    linhas.map(([uf, u]) => {
      const p = u.n ? (100 * u.irregular) / u.n : 0;
      return `<tr class="clic" data-uf="${uf}" title="${esc(S.cat.ufs[uf].nome)}: ${fmtInt.format(u.irregular)} de ${fmtInt.format(u.n)} entes irregulares">
        <td><strong>${uf}</strong></td><td class="num">${fmtInt.format(u.n)}</td>
        <td><div class="barra"><span class="trilho"><span class="valor" style="width:${p.toFixed(1)}%"></span></span><span class="mono">${fmtInt.format(u.irregular)} (${pct(u.irregular, u.n)})</span></div></td>
        <td class="num">${fmtInt.format(u.atencao)}</td><td class="num">${fmtInt.format(u.vencido)}</td><td class="num">${fmtInt.format(u.rem)}</td><td class="num">${fmtInt.format(u.mde)}</td><td class="num">${fmtInt.format(u.sem_info)}</td></tr>`;
    }).join("") + "</tbody>";
  $("t-uf").querySelectorAll("tr.clic").forEach((tr) => tr.addEventListener("click", () => {
    S.f.uf = tr.dataset.uf; sincronizarControles(); renderizar();
  }));
}

function colunasEntes() {
  const ano = Number(S.f.ano);
  const obr = S.cat.obrigacoes.filter((o) => o.tipo !== "informativo" && o.unidade === "%" && (!o.a_partir_de || ano >= o.a_partir_de) && o.id !== "destinacao_estado_20");
  return obr;
}
const PESO = { irregular: 3, atencao: 2, regular: 1, sem_info: 0 };
function ordenar(rows) {
  const { col, dir } = S.ordem;
  const chave = (r) => {
    if (col === "grav") return [PESO[r.sg], r.nc, r.na];
    if (col === "nome") return [norm(r.e.nome)];
    if (col === "uf") return [r.e.uf, norm(r.e.nome)];
    if (col === "pop") return [r.e.pop ?? -1];
    return [r.v[col] ?? -Infinity];
  };
  return [...rows].sort((a, b) => {
    const ka = chave(a), kb = chave(b);
    for (let i = 0; i < ka.length; i++) { if (ka[i] < kb[i]) return -dir; if (ka[i] > kb[i]) return dir; }
    return 0;
  });
}
function renderEntes(rows) {
  const obr = colunasEntes();
  const ord = ordenar(rows);
  const vis = ord.slice(0, S.limite);
  const th = (col, rot, num) => `<th class="ord${num ? " num" : ""}" data-col="${col}"${S.ordem.col === col ? ` aria-sort="${S.ordem.dir > 0 ? "ascending" : "descending"}"` : ""}>${rot}</th>`;
  $("t-entes").innerHTML = `<thead><tr>${th("nome", "Ente")}${th("uf", "UF")}${th("grav", "Situação")}<th>Alertas</th><th>${S.periodo.bim.todos ? "Por bimestre" : `${S.periodo.bim.bimestre}º bim.`}</th>${obr.map((o) => th(o.id, esc(o.curto), true)).join("")}${th("pop", "População", true)}</tr></thead><tbody>` +
    (vis.length ? vis.map((r) => `<tr><td><button type="button" class="link" data-id="${r.id}">${esc(r.e.nome)}</button></td><td>${r.e.uf}</td><td>${pill(r.sg)}</td>
      <td class="num">${r.nc ? `<span class="pill critico">${r.nc}</span> ` : ""}${r.na ? `<span class="pill atencao">${r.na}</span>` : ""}</td><td>${S.periodo.bim.todos ? faixaBimestres(r) : pill(r.tb)}</td>
      ${obr.map((o) => `<td class="num"><span class="pill ${sit(r.s[o.id]).nivel}" title="${esc(sit(r.s[o.id]).rotulo)}">${fv(r.v[o.id], "%")}</span></td>`).join("")}
      <td class="num">${r.e.pop ? fmtInt.format(r.e.pop) : "-"}</td></tr>`).join("") : `<tr><td class="vazio" colspan="9">Nenhum ente no recorte.</td></tr>`) + "</tbody>";
  $("b-mais").hidden = ord.length <= S.limite;
  $("b-mais").textContent = `Mostrar mais (${fmtInt.format(ord.length - vis.length)} restantes)`;
  $("t-entes").querySelectorAll("th.ord").forEach((h) => h.addEventListener("click", () => {
    const c = h.dataset.col;
    S.ordem = { col: c, dir: S.ordem.col === c ? -S.ordem.dir : c === "nome" || c === "uf" ? 1 : -1 };
    renderEntes(filtrar());
  }));
  $("t-entes").querySelectorAll("button.link").forEach((b) => b.addEventListener("click", () => {
    S.f.ente = b.dataset.id; S.detalhe = b.dataset.id; sincronizarControles(); renderizar();
    $("s-ente").scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

/* ---------------------------------------------------- PDFs em lote ---- */
async function carregarLote() {
  let idx = [];
  try { idx = await getJSON("relatorios/indice.json"); } catch { /* sem lote gerado */ }
  if (!idx.length) { $("l-lote").innerHTML = `<div class="vazio">Nenhum relatório em lote gerado.</div>`; return; }
  const porAno = {};
  for (const r of idx) (porAno[r.ano] ||= []).push(r);
  $("l-lote").innerHTML = Object.entries(porAno).sort((a, b) => b[0] - a[0]).map(([ano, itens]) =>
    `<details${ano == S.manifest.exercicios.at(-1).ano ? " open" : ""}><summary>Exercício ${ano}, até o ${itens[0].bimestre}º bimestre · dados <span class="mono">${curto(itens[0].sha256_dados)}</span></summary>
     <div class="pdfs">${itens.map((r) => `<a href="${esc(r.arquivo)}">${esc(r.chave === "BR" ? "Brasil" : r.chave)}</a>`).join("")}</div></details>`).join("");
}

/* ------------------------------------------------------- detalhe do ente ---- */
const chaveUF = (uf, b) => `${S.f.ano}/b${b || S.periodo.bim.bimestre}/${uf}`;
async function detalheUF(uf, b) {
  const k = chaveUF(uf, b);
  if (!S.cacheUF.has(k)) S.cacheUF.set(k, await getJSON(`dados/${k}.json`));
  return S.cacheUF.get(k);
}

async function renderDetalhe() {
  const sec = $("s-ente");
  const r = S.detalhe ? S.linhas.find((x) => x.id === S.detalhe) : null;
  if (!r) { sec.hidden = true; sec.innerHTML = ""; return; }
  sec.hidden = false;
  sec.innerHTML = `<div class="vazio">Carregando detalhe…</div>`;
  let det;
  try { det = await detalheUF(r.e.uf, r.bv); } catch (e) { sec.innerHTML = `<div class="vazio">Não foi possível carregar o detalhe (${esc(e.message)}).</div>`; return; }
  if (S.detalhe !== r.id) return;
  const d = det.entes[r.id] || { ind: {}, tx: null };
  const alertas = r.al.map(alertaInfo);
  const grupos = {};
  for (const [c, v] of Object.entries(d.ind)) (grupos[c.split(".")[0]] ||= []).push([c, v]);
  const usados = new Set(S.cat.obrigacoes.flatMap((o) => [o.cod_exib, o.referencia_cod_exib]));
  sec.innerHTML = `<div class="ente-cab"><div><div class="eyebrow">${r.e.esfera === "municipal" ? "Município" : "Ente estadual ou distrital"} · ${esc(S.cat.ufs[r.e.uf]?.nome || r.e.uf)} · ${esc(r.e.regiao)}</div>
      <h2>${esc(r.e.nome)}</h2><div class="meta"><span>Situação ${pill(r.sg)}</span><span>População ${r.e.pop ? fmtInt.format(r.e.pop) : "-"}</span>
      <span>Complementação-VAAT: ${esc(S.cat.vaat_rotulos[r.vaat] || r.vaat)}</span><span>Código SIOPE ${esc(r.id)}</span></div></div>
      <div class="acoes"><button type="button" class="sec" id="b-fechar">Voltar ao recorte</button><button type="button" id="b-pdf-ente">PDF deste ente</button></div></div>
    <div class="tabela"><table><thead><tr><th>Nível</th><th>Alerta</th><th>Base legal</th></tr></thead><tbody>${alertas.length ? alertas.map((a) => `<tr><td><span class="pill ${a.nivel}">${a.nivel === "critico" ? "Crítico" : "Atenção"}</span></td><td>${esc(a.titulo)}</td><td>${esc(a.base)}</td></tr>`).join("") : `<tr><td colspan="3" class="vazio">Nenhum sinal de alerta.</td></tr>`}</tbody></table></div>
    <h3>Indicadores acompanhados</h3>
    ${Object.keys(grupos).length ? Object.entries(grupos).sort((a, b) => a[0] - b[0]).map(([g, itens]) => `<details><summary>${esc(S.cat.grupos[g] || "Grupo " + g)} (${itens.length})</summary><div class="tabela"><table><tbody>${
      itens.sort((a, b) => Number(a[0].split(".")[1]) - Number(b[0].split(".")[1])).map(([c, v]) => `<tr><td class="code">${c}</td><td>${esc(S.cat.indicadores[c] || "(nome não informado na fonte)")}${usados.has(c) ? ` <span class="disp">ligado a obrigação legal, ver tabela de cumprimento</span>` : ""}</td><td class="num">${fv(v, /^percentual/i.test(S.cat.indicadores[c] || "") ? "%" : null)}</td></tr>`).join("")}</tbody></table></div></details>`).join("") : `<div class="vazio">Sem indicadores do ente no bimestre.</div>`}`;
  $("b-fechar").addEventListener("click", () => { S.f.ente = ""; S.detalhe = null; sincronizarControles(); renderizar(); });
  $("b-pdf-ente").addEventListener("click", () => gerarPDF());
  if (S.f.ente === r.id) renderPrazos([r], null);
}

function renderDocs() {
  $("l-docs").innerHTML = S.cat.documentais.map((d) => `<li><strong>${esc(d.titulo)}</strong><span class="disp">${esc(d.dispositivo)}</span><span class="disp">${esc(d.descricao)}</span></li>`).join("");
}

function renderRodape() {
  const { bim } = S.periodo, fl = S.cat.fontes_legais;
  const vr = bim.via_recibo ? ` ${fmtInt.format(bim.via_recibo)} transmissão(ões) deste bimestre ainda ausentes da base aberta foram confirmadas na página pública "Recibos de Transmissão" do SIOPE.` : "";
  const vt = bim.via_tc ? ` Os indicadores de ${fmtInt.format(bim.via_tc)} ente(s) ainda incompletos na base aberta vieram do webservice do SIOPE para os Tribunais de Contas.` : "";
  $("rodape").innerHTML = `<span>Fonte: dados abertos do SIOPE/FNDE (API Olinda), webservice do SIOPE para os Tribunais de Contas, Recibos de Transmissão do SIOPE e lista de municípios do IBGE.${vr}${vt} Situações calculadas por siope_brasil/processa.py; este painel só filtra e conta.</span>
    <span>Normas: <a href="${esc(fl.lei_14113)}" target="_blank" rel="noopener">Lei 14.113/2020</a> · <a href="${esc(fl.cf)}" target="_blank" rel="noopener">Constituição Federal</a>.</span>
    <span>Identificador dos dados deste bimestre (SHA-256 de ${esc(bim.arquivo)}): <span class="mono" style="word-break:break-all">${bim.sha256}</span>. Os PDFs deste recorte trazem o mesmo identificador.</span>
    <span>Gerado em ${esc(S.manifest.gerado_em)}.</span>`;
}

/* --------------------------------------------------------------- PDF ---- */
async function gerarPDF() {
  if (!window.jspdf || !window.jspdf.jsPDF) { toast("O gerador de PDF não carregou. Verifique a conexão e recarregue a página."); return; }
  const botoes = [$("b-pdf"), $("b-pdf-ente")].filter(Boolean);
  botoes.forEach((b) => (b.disabled = true));
  try {
    const rows = filtrar();
    const unico = rows.length === 1 ? rows[0] : null;
    let det = null;
    if (unico) det = (await detalheUF(unico.e.uf, unico.bv)).entes[unico.id] || null;
    const doc = montarPDF(rows, unico, det);
    const nome = `siope-fundeb_${S.f.ano}_b${S.f.bim}_${norm(descreverRecorte()).replace(/[^a-z0-9]+/g, "-").slice(0, 60)}.pdf`;
    doc.save(nome);
    toast("PDF gerado: " + nome);
  } catch (e) {
    toast("Não foi possível gerar o PDF: " + e.message);
  } finally {
    botoes.forEach((b) => (b.disabled = false));
  }
}

function montarPDF(rows, unico, det) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const ag = agregar(rows);
  const { ex, bim, dados } = S.periodo;
  const M = 14, W = 210 - 2 * M;
  let y = 16;
  const cor = { critico: [163, 38, 42], atencao: [138, 90, 0], ok: [31, 111, 67], neutro: [77, 89, 97] };
  const titulo = (t) => { y = (doc.lastAutoTable && doc.lastAutoTable.finalY > y ? doc.lastAutoTable.finalY : y) + 7; if (y > 270) { doc.addPage(); y = 18; } doc.setFont("helvetica", "bold"); doc.setFontSize(11.5); doc.setTextColor(99, 45, 145); doc.text(t, M, y); y += 2; doc.setTextColor(27, 35, 40); };
  const paragrafo = (t, tam = 8.5, cinza = false) => { doc.setFont("helvetica", "normal"); doc.setFontSize(tam); doc.setTextColor(...(cinza ? [92, 82, 105] : [29, 19, 40])); const l = doc.splitTextToSize(t, W); if (y + l.length * tam * 0.42 > 282) { doc.addPage(); y = 18; } doc.text(l, M, y + 4); y += l.length * tam * 0.42 + 3; };
  const tabela = (head, body, opts = {}) => { doc.autoTable({ startY: y + 2, head: [head], body, margin: { left: M, right: M, bottom: 16 }, theme: "grid",
    styles: { font: "helvetica", fontSize: 7.4, cellPadding: 1.4, lineColor: [227, 218, 236], lineWidth: 0.15, textColor: [29, 19, 40], overflow: "linebreak" },
    headStyles: { fillColor: [243, 238, 248], textColor: [72, 32, 107], fontStyle: "bold" }, ...opts }); y = doc.lastAutoTable.finalY; };
  const corSit = (k) => cor[sit(k).nivel];
  const pintar = (colunas) => ({ didParseCell: (d) => { if (d.section === "body" && colunas.includes(d.column.index) && d.cell.raw && d.cell.raw._sit) { d.cell.styles.textColor = corSit(d.cell.raw._sit); d.cell.styles.fontStyle = "bold"; } } });
  const S_ = (k) => ({ content: sit(k).rotulo, _sit: k });

  doc.setFont("helvetica", "bold"); doc.setFontSize(15);
  doc.text(doc.splitTextToSize(`${S.cat.painel.titulo || "Painel SIOPE e Fundeb"}: ${descreverRecorte()}`, W), M, y); y += 8;
  paragrafo(`Exercício ${ex.ano} · ${rotuloPeriodo(bim).join(" ")}${bim.bimestre < 6 ? " (exercício em andamento)" : ""} · situação calculada em ${fd(dados.data_referencia)} · última coleta ${(dados.ultima_coleta || "-").slice(0, 10)}`, 8.5);
  paragrafo(`Recorte: ${descreverRecorte()}. Fonte: dados abertos do SIOPE/FNDE. Lei 14.113/2020 (Fundeb) e Constituição Federal.`, 7.6, true);
  if (S.manifest.demo) paragrafo(S.manifest.demo, 8.5);

  const pend = [];
  const nConf = S.cat.obrigacoes.filter((o) => o.conferir).length;
  if (nConf) pend.push(`${nConf} referência(s) legal(is) marcadas [conferir] na fonte oficial.`);
  if (S.cat.base_aberta_so_aviso) pend.push("Transmissões: base de dados abertos do SIOPE (FNDE), atualizada com atraso em relação ao sistema SIOPE. Ausência nela após o prazo = atenção, a conferir no relatório do SIOPE.");
  if (ex.prazos.some((p) => p.calculado)) pend.push(`Prazos de transmissão calculados pela regra do ${S.cat.prazo_regra.dispositivo} [conferir cronograma oficial do FNDE].`);
  if (!ex.vaat_lista_oficial) pend.push(S.cat.vaat_nota);
  if (pend.length) tabela(["Conferir antes de usar em prestação de contas"], pend.map((p) => [p]), { headStyles: { fillColor: [251, 239, 214], textColor: [138, 90, 0], fontStyle: "bold" } });

  titulo("Resumo");
  const tb = ag.tx[bim.bimestre - 1];
  tabela(["Entes", "Irregulares", "Atenção", "Regulares", "Sem dados", `${bim.bimestre}º bim. transmitido`],
    [[fmtInt.format(ag.total), `${fmtInt.format(ag.sg.irregular)} (${pct(ag.sg.irregular, ag.total)})`, `${fmtInt.format(ag.sg.atencao)} (${pct(ag.sg.atencao, ag.total)})`,
      `${fmtInt.format(ag.sg.regular)} (${pct(ag.sg.regular, ag.total)})`, fmtInt.format(ag.sg.sem_info),
      `${fmtInt.format((tb.no_prazo || 0) + (tb.fora_prazo || 0) + (tb.sem_data || 0))} (${fmtInt.format(tb.atrasado || 0)} sem registro após o prazo)`]]);

  if (bim.todos) {
    titulo("Evolução por bimestre");
    tabela(["Bimestre", "Irregulares", "Atenção", "Regulares", "Sem dados"],
      evolucao(rows).map(([b, c]) => [`${b}º bimestre`, ...["irregular", "atencao", "regular", "sem_info"].map((k) => (c[k] ? fmtInt.format(c[k]) : "-"))]));
  }

  titulo("Cumprimento das obrigações");
  paragrafo((bim.todos ? "Todos os bimestres: valores, situação e alertas do bimestre mais recente com dados de cada ente. " : "") + "Valores acumulados até o bimestre de referência. Obrigações anuais se fecham no 6º bimestre. [conferir] = referência legal a conferir na fonte oficial.", 7.4, true);
  const txtObr = (o) => `${o.titulo}\n${o.obrigacao}\n${o.dispositivo}${o.conferir ? " [conferir]" : ""}`;
  if (unico) {
    tabela(["Ind.", "Obrigação e dispositivo", "Valor", "Regra", "Situação"],
      S.cat.obrigacoes.map((o) => [o.cod_exib, txtObr(o) + (o.nota ? `\nNota: ${o.nota}` : ""), fv(unico.v[o.id], o.unidade), o.regra, S_(unico.s[o.id])]),
      { columnStyles: { 0: { cellWidth: 10 }, 2: { cellWidth: 24, halign: "right" }, 3: { cellWidth: 30 }, 4: { cellWidth: 28 } }, ...pintar([4]) });
  } else {
    const ks = [["cumprida", "Cumpr."], ["descumprida", "Descumpr."], ["parcial_ok", "No rumo"], ["parcial_abaixo", "Fora (parc.)"], ["apuracao_anual", "Apur. 6º bim."], ["sem_dados", "Sem dados"], ["nao_publicado", "Aguard. base"], ["nao_aplica", "N/A"]];
    tabela(["Ind.", "Obrigação e dispositivo", "Regra", ...ks.map((k) => k[1]), "Cumpr. %"],
      S.cat.obrigacoes.filter((o) => o.tipo !== "informativo").map((o) => {
        const c = ag.obr[o.id], bons = (c.cumprida || 0) + (c.parcial_ok || 0), ruins = (c.descumprida || 0) + (c.parcial_abaixo || 0);
        return [o.cod_exib, txtObr(o), o.regra, ...ks.map(([k]) => (c[k] ? fmtInt.format(c[k]) : "-")), pct(bons, bons + ruins)];
      }), { columnStyles: { 0: { cellWidth: 9 }, 2: { cellWidth: 22 } } });
  }

  titulo("Sinais de alerta");
  if (unico) {
    const al = unico.al.map(alertaInfo);
    if (al.length) tabela(["Nível", "Alerta", "Base legal"], al.map((a) => [{ content: a.nivel === "critico" ? "Crítico" : "Atenção", _sit: a.nivel === "critico" ? "irregular" : "atencao" }, a.titulo, a.base]), { columnStyles: { 0: { cellWidth: 18 } }, ...pintar([0]) });
    else paragrafo("Nenhum sinal de alerta.");
  } else {
    const it = Object.entries(ag.al).map(([c, n]) => ({ n, ...alertaInfo(c) })).sort((a, b) => (a.nivel === b.nivel ? b.n - a.n : a.nivel === "critico" ? -1 : 1));
    if (it.length) tabela(["Nível", "Alerta", "Base legal", "Entes"], it.map((a) => [{ content: a.nivel === "critico" ? "Crítico" : "Atenção", _sit: a.nivel === "critico" ? "irregular" : "atencao" }, a.titulo, a.base, fmtInt.format(a.n)]), { columnStyles: { 0: { cellWidth: 18 }, 3: { halign: "right", cellWidth: 16 } }, ...pintar([0]) });
    else paragrafo("Nenhum sinal de alerta no recorte.");
  }

  titulo("Prazos de transmissão ao SIOPE");
  paragrafo(`${S.cat.prazo_regra.dispositivo}. Consequência do atraso: ${S.cat.prazo_regra.consequencia}`, 7.4, true);
  if (unico) {
    const tx = det ? det.tx : null;
    tabela(["Bimestre", "Prazo", "Declaração", "Recibo", "Situação"], ex.prazos.map((p, k) => {
      const t = tx ? tx[k] : [null, S.cat.cod_tx[unico.tx6[k]], false, ""];
      return [`${k + 1}º bimestre`, `${fd(p.data)} (${p.calculado ? "calculado" : "oficial"})`, fd(t[0]), t[3] ? `${t[3]}${t[2] ? " (retificada)" : ""}` : "-", S_(t[1])];
    }), pintar([4]));
  } else {
    const cs = [["no_prazo", "No prazo"], ["fora_prazo", "Após o prazo"], ["atrasado", "Sem registro, prazo vencido"], ["aguardando", "Dentro do prazo"], ["em_curso", "Em curso"]];
    tabela(["Bimestre", "Prazo", ...cs.map((c) => c[1])], ex.prazos.map((p, k) => [`${k + 1}º bimestre`, `${fd(p.data)} (${p.calculado ? "calculado" : "oficial"})`, ...cs.map(([c]) => (ag.tx[k][c] ? fmtInt.format(ag.tx[k][c]) : "-"))]));
  }

  if (!unico) {
    const ufs = Object.entries(ag.uf).sort((a, b) => b[1].irregular / b[1].n - a[1].irregular / a[1].n);
    if (ufs.length > 1) {
      titulo("Comparativo por UF");
      tabela(["UF", "Entes", "Irregulares", "Atenção", "Sem registro, prazo vencido", "Remun. 70% descumpr.", "MDE 25% descumpr.", "Sem dados"],
        ufs.map(([uf, u]) => [uf, fmtInt.format(u.n), `${fmtInt.format(u.irregular)} (${pct(u.irregular, u.n)})`, fmtInt.format(u.atencao), fmtInt.format(u.vencido), fmtInt.format(u.rem), fmtInt.format(u.mde), fmtInt.format(u.sem_info)]));
    }
    const irr = ordenar(rows.filter((r) => r.sg === "irregular"));
    titulo(`Entes irregulares (${fmtInt.format(irr.length)})`);
    if (irr.length) {
      const obr = colunasEntes();
      tabela(["Ente", "UF", "Alertas críticos", ...obr.map((o) => o.curto)], irr.map((r) => [r.e.nome, r.e.uf, r.al.filter((c) => c.startsWith("c:")).map((c) => alertaInfo(c).titulo).join("; "), ...obr.map((o) => ({ content: fv(r.v[o.id], "%"), _sit: r.s[o.id] }))]),
        { styles: { fontSize: 6.6, cellPadding: 1, font: "helvetica", lineColor: [227, 218, 236], lineWidth: 0.15 }, columnStyles: { 2: { cellWidth: 52 } }, ...pintar(obr.map((_, i) => i + 3)) });
    } else paragrafo("Nenhum ente irregular no recorte.");
    const at = rows.filter((r) => r.sg === "atencao").length;
    if (at) paragrafo(`Entes em atenção no recorte: ${fmtInt.format(at)}. A lista completa está no painel, filtro Situação = Atenção.`, 7.6, true);
  } else if (det && Object.keys(det.ind).length) {
    titulo("Indicadores acompanhados");
    tabela(["Ind.", "Indicador", "Valor"], Object.entries(det.ind).sort((a, b) => { const [ga, sa] = a[0].split(".").map(Number), [gb, sb] = b[0].split(".").map(Number); return ga - gb || sa - sb; })
      .map(([c, v]) => [c, S.cat.indicadores[c] || "(nome não informado na fonte)", fv(v, /^percentual/i.test(S.cat.indicadores[c] || "") ? "%" : null)]), { columnStyles: { 0: { cellWidth: 10 }, 2: { halign: "right", cellWidth: 30 } } });
  }

  titulo("Verificação documental (obrigações que o SIOPE não mede)");
  tabela(["Feito", "Obrigação", "Base legal"], S.cat.documentais.map((d) => ["[  ]", `${d.titulo}\n${d.descricao}`, d.dispositivo]), { columnStyles: { 0: { cellWidth: 12 }, 2: { cellWidth: 55 } } });

  titulo("Fonte e integridade");
  paragrafo(`Normas: Lei 14.113/2020 (${S.cat.fontes_legais.lei_14113}); Constituição Federal (${S.cat.fontes_legais.cf}).`, 7.4, true);
  paragrafo(`Identificador dos dados (SHA-256 de ${bim.arquivo}): ${bim.sha256}. É o mesmo identificador exibido no painel para este exercício e bimestre. PDF gerado no navegador em ${new Date().toLocaleString("pt-BR")}.`, 7.4, true);
  if (S.cat.painel.url_publica) paragrafo(`Painel: ${S.cat.painel.url_publica}`, 7.4, true);
  y += 8; paragrafo("Ciência / visto: ______________________________________   Data: ____/____/______", 8.5);

  const n = doc.getNumberOfPages();
  for (let i = 1; i <= n; i++) {
    doc.setPage(i); doc.setFont("helvetica", "normal"); doc.setFontSize(6.8); doc.setTextColor(92, 82, 105); doc.setFillColor(99, 45, 145); doc.rect(0, 0, 210, 2.2, "F"); doc.setFillColor(252, 216, 4); doc.rect(0, 2.2, 210, 0.8, "F");
    doc.text(`${descreverRecorte().slice(0, 70)} · ${ex.ano} · ${bim.todos ? `todos os bim. (1º ao ${bim.bimestre}º)` : `${bim.bimestre}º bim.`} · dados ${curto(bim.sha256)}`, M, 290);
    doc.text(`Página ${i} de ${n}`, 210 - M, 290, { align: "right" });
  }
  doc.setProperties({ title: `SIOPE e Fundeb: ${descreverRecorte()}`, subject: `Exercício ${ex.ano}, ${bim.rotulo}`, keywords: `SIOPE; Fundeb; Lei 14.113/2020; ${bim.sha256}` });
  return doc;
}

iniciar();
