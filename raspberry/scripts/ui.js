/*
 * SMART PARK · componentes de interface que todas as telas da equipe compartilham
 * Navegação lateral, tema, ícones, toasts, confirmação, tooltip, tabelas e formatadores.
 * Uso nas telas da equipe (painel ao vivo, histórico, admin). A tela do motorista não tem menu,
 * só aproveita as cores e fontes.
 *
 *   UI.shell({ ativo: 'equipe' })               monta a barra lateral no <aside id="sidebar">
 *   UI.toast('Salvo', 'success')                 success | danger | info
 *   await UI.confirmar({ titulo, texto, acao })  true/false (modal acessível)
 *   UI.tabela(el, { colunas, linhas, vazio, porPagina, ordenar })
 *   UI.f.dur(s), UI.f.hora(t), UI.f.data(t), UI.f.esc(txt) ...
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------ tema (aplico antes de pintar a tela)
  const CHAVE_TEMA = 'sp-tema', CHAVE_MENU = 'sp-menu-recolhido';
  const ler = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const gravar = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} };
  const temaSalvo = ler(CHAVE_TEMA);
  if (temaSalvo) document.documentElement.dataset.theme = temaSalvo;
  function temaAtual() {
    return document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  }

  // ------------------------------------------------------------------ ícones (traço 2px, 24x24)
  const P = {
    painel: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    celular: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    pessoas: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    tablet: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M12 18h.01"/>',
    relogio: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    grafico: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
    busca: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    carro: '<path d="M5 17h14v-5l-2-5H7l-2 5z"/><path d="M5 12h14"/><circle cx="8" cy="17" r="1.6"/><circle cx="16" cy="17" r="1.6"/>',
    sensor: '<path d="M4.9 19.1a10 10 0 0 1 0-14.2"/><path d="M7.8 16.2a6 6 0 0 1 0-8.4"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/>',
    lista: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    sol: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    lua: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    sair: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    recolher: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>',
    expandir: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="m14 9 3 3-3 3"/>',
    externo: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    cadeado: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    alerta: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    proibido: '<circle cx="12" cy="12" r="9"/><path d="M5.7 5.7l12.6 12.6"/>',
    ok: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    erro: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    mais: '<path d="M12 5v14M5 12h14"/>',
    lixo: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
    seta: '<path d="m9 18 6-6-6-6"/>',
    setaEsq: '<path d="m15 18-6-6 6-6"/>',
    ordem: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
    sobe: '<path d="m7 14 5-5 5 5"/>',
    desce: '<path d="m7 10 5 5 5-5"/>',
    vazio: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M9 15h6"/>',
    mapa: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
    toque: '<path d="M9 11V5a2 2 0 0 1 4 0v6"/><path d="M13 9a2 2 0 0 1 4 0v3"/><path d="M17 11a2 2 0 0 1 4 0v4a7 7 0 0 1-7 7h-1a7 7 0 0 1-6-3.4L4.5 15a2 2 0 0 1 3.3-2.2L9 14.5"/>',
  };
  function icone(nome, extra = '') {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${P[nome] || ''}</svg>`;
  }

  // ------------------------------------------------------------------ formatadores
  const f = {
    esc: s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
    num: (n, casas = 0) => n == null || Number.isNaN(n) ? '–' : Number(n).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }),
    pct: (n, casas = 0) => n == null ? '–' : f.num(n, casas) + '%',
    dur(s) {
      if (s == null) return '–';
      s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), seg = s % 60;
      return h ? `${h}h${String(m).padStart(2, '0')}` : m ? `${m} min` : `${seg} s`;
    },
    hora: t => t ? new Date(t * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '–',
    horaSeg: t => t ? new Date(t * 1000).toLocaleTimeString('pt-BR') : '–',
    data: t => new Date(t * 1000).toLocaleDateString('pt-BR'),
    dataISO: iso => iso ? iso.split('-').reverse().join('/') : '–',
    dataHora: t => new Date(t * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }),
    relMin: m => m == null ? '–' : Math.abs(m) < .5 ? 'no início' : (m < 0 ? `${Math.round(-m)} min antes` : `${Math.round(m)} min depois`),
    hojeISO: () => new Date().toLocaleDateString('sv-SE'),
    diasAtras: n => { const d = new Date(); d.setDate(d.getDate() - n); return d.toLocaleDateString('sv-SE'); },
    categoria: c => ({ MEMBRO: 'Membro', IDOSO: 'Idoso', PCD: 'PcD', EQUIPE: 'Equipe', VISITANTE: 'Visitante' }[c] || c || '—'),
  };
  const catBadge = c => c ? `<span class="cat cat--${f.esc(c)}">${f.esc(f.categoria(c))}</span>` : '<span class="subtle">—</span>';

  // ------------------------------------------------------------------ navegação
  const NAV = [
    { grupo: 'Operação', itens: [
      { id: 'equipe', rot: 'Painel ao vivo', href: '/equipe', ic: 'painel' },
      { id: 'guarita', rot: 'Tela do motorista', href: '/guarita', ic: 'tablet', nova: 'smartpark-guarita' },
      { id: 'corredor', rot: 'App do corredor', href: '/corredor', ic: 'celular', nova: 'smartpark-corredor' },
      { id: 'historico', rot: 'Histórico do dia', href: '/historico', ic: 'relogio' },
    ] },
    { grupo: 'Administração', admin: true, itens: [
      { id: 'visao', rot: 'Visão geral', href: '/admin#visao', ic: 'grafico' },
      { id: 'consultas', rot: 'Consultas', href: '/admin#consultas', ic: 'busca' },
      { id: 'cadastro', rot: 'Cadastro', href: '/admin#cadastro', ic: 'carro' },
      { id: 'visitantes', rot: 'Visitantes', href: '/admin#visitantes', ic: 'pessoas' },
      { id: 'sensores', rot: 'Sensores', href: '/admin#sensores', ic: 'sensor', contador: true },
      { id: 'eventos', rot: 'Eventos', href: '/admin#eventos', ic: 'lista' },
    ] },
    { grupo: 'Ferramentas', itens: [
      { id: 'simulador', rot: 'Simulador', href: '/simulador', ic: 'play', nova: '_blank' },
      { id: 'carro', rot: 'Carro de teste', href: '/carro', ic: 'celular', nova: '_blank' },
    ] },
  ];

  const estado = { ativo: null, logado: false, aoSair: null };

  function shell(opts = {}) {
    estado.ativo = opts.ativo; estado.aoSair = opts.aoSair || null;
    const app = document.querySelector('.app'), aside = document.getElementById('sidebar');
    if (!app || !aside) return;
    if (ler(CHAVE_MENU) === '1') app.classList.add('is-collapsed');

    const marca = `<a class="brand" href="/equipe" aria-label="Smart Park, ir para o painel ao vivo">
      <span class="brand-mark" aria-hidden="true"><span><b>P</b></span></span>
      <span class="brand-txt"><strong>Smart Park</strong><small>Igreja Batista Atitude</small></span></a>`;

    aside.setAttribute('aria-label', 'Navegação principal');
    aside.innerHTML = marca + NAV.map(g => `<nav class="nav-group" aria-label="${g.grupo}">
        <div class="nav-label"><span class="eyebrow">${g.grupo}</span>${g.admin ? `<span class="nav-aux" id="nav-cadeado" title="Requer senha do admin">${icone('cadeado')}</span>` : ''}</div>
        ${g.itens.map(i => `<a class="nav-item" href="${i.href}" data-id="${i.id}" ${i.nova ? `target="${i.nova}" rel="noopener"` : ''} title="${i.rot}">
          ${icone(i.ic)}<span class="nav-txt">${i.rot}</span>${i.contador ? '<span class="nav-count" id="nav-cont-sensores" hidden></span>' : ''}${i.nova ? `<span class="nav-aux">${icone('externo')}</span>` : ''}</a>`).join('')}
      </nav>`).join('') + `
      <div class="sidebar-foot">
        <div class="conn" id="conn" role="status" title="Conexão com o Raspberry"><span class="dot-live" id="conn-dot"></span><span id="conn-txt">Conectado</span></div>
        <button class="nav-item" id="btn-tema" type="button">${icone('lua')}<span class="nav-txt">Tema</span></button>
        <button class="nav-item btn-collapse" id="btn-recolher" type="button" aria-expanded="true">${icone('recolher')}<span class="nav-txt">Recolher menu</span></button>
        <button class="nav-item" id="btn-sair" type="button" hidden>${icone('sair')}<span class="nav-txt">Sair do admin</span></button>
      </div>`;

    // barra do celular + véu
    const main = document.querySelector('.main');
    if (main && !document.querySelector('.mobile-bar')) {
      main.insertAdjacentHTML('afterbegin', `<div class="mobile-bar"><button class="btn btn--ghost btn--icon" id="btn-menu" type="button" aria-label="Abrir menu" aria-expanded="false" aria-controls="sidebar">${icone('menu')}</button>${marca}</div>`);
      app.insertAdjacentHTML('beforeend', '<div class="scrim" id="scrim"></div>');
    }

    marcarAtivo(opts.ativo);
    atualizarBotaoTema();
    atualizarRecolher();

    document.getElementById('btn-tema').onclick = () => {
      const novo = temaAtual() === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = novo; gravar(CHAVE_TEMA, novo);
      atualizarBotaoTema(); document.dispatchEvent(new CustomEvent('sp:tema', { detail: novo }));
    };
    document.getElementById('btn-recolher').onclick = () => {
      app.classList.toggle('is-collapsed'); gravar(CHAVE_MENU, app.classList.contains('is-collapsed') ? '1' : null); atualizarRecolher();
    };
    const fechar = () => { app.classList.remove('is-nav-open'); document.getElementById('btn-menu')?.setAttribute('aria-expanded', 'false'); };
    document.getElementById('btn-menu')?.addEventListener('click', () => {
      const abrir = !app.classList.contains('is-nav-open');
      app.classList.toggle('is-nav-open', abrir); document.getElementById('btn-menu').setAttribute('aria-expanded', abrir);
      if (abrir) aside.querySelector('.nav-item')?.focus();
    });
    document.getElementById('scrim')?.addEventListener('click', fechar);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && app.classList.contains('is-nav-open')) { fechar(); document.getElementById('btn-menu')?.focus(); } });
    aside.addEventListener('click', e => { if (e.target.closest('a.nav-item')) fechar(); });
    document.getElementById('btn-sair').onclick = async () => {
      await fetch('/api/admin/logout', { method: 'POST' });
      definirLogado(false); toast('Você saiu da área administrativa.', 'info');
      if (estado.aoSair) estado.aoSair();
    };

    verificarSessao();
    pingar(); setInterval(pingar, 15000);
  }

  function marcarAtivo(id) {
    estado.ativo = id;
    document.querySelectorAll('#sidebar .nav-item[data-id]').forEach(a => {
      if (a.dataset.id === id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }
  function atualizarBotaoTema() {
    const b = document.getElementById('btn-tema'); if (!b) return;
    const escuro = temaAtual() === 'dark';
    b.innerHTML = `${icone(escuro ? 'sol' : 'lua')}<span class="nav-txt">${escuro ? 'Tema claro' : 'Tema escuro'}</span>`;
    b.title = escuro ? 'Mudar para o tema claro' : 'Mudar para o tema escuro';
  }
  function atualizarRecolher() {
    const b = document.getElementById('btn-recolher'), rec = document.querySelector('.app')?.classList.contains('is-collapsed');
    if (!b) return;
    b.innerHTML = `${icone(rec ? 'expandir' : 'recolher')}<span class="nav-txt">${rec ? 'Expandir menu' : 'Recolher menu'}</span>`;
    b.setAttribute('aria-expanded', String(!rec)); b.title = rec ? 'Expandir menu' : 'Recolher menu';
  }

  // sessão do admin: mostro "Sair", tiro o cadeado do menu e acompanho os sensores
  let timerSensores = null;
  async function verificarSessao() {
    try { const r = await fetch('/api/sessao', { cache: 'no-store' }); definirLogado(!!(await r.json()).admin); } catch (e) {}
  }
  function definirLogado(sim) {
    estado.logado = sim;
    const s = document.getElementById('btn-sair'), c = document.getElementById('nav-cadeado');
    if (s) s.hidden = !sim; if (c) c.hidden = sim;
    clearInterval(timerSensores);
    if (sim) { checarSensores(); timerSensores = setInterval(checarSensores, 60000); }
    else contadorSensores(null);
  }
  async function checarSensores() {
    try { const r = await fetch('/api/admin/saude'); if (r.ok) contadorSensores(await r.json()); } catch (e) {}
  }
  function contadorSensores(d) {
    const c = document.getElementById('nav-cont-sensores'); if (!c) return;
    if (!d) { c.hidden = true; return; }
    const off = d.esp32 && d.esp32.estado === 'offline';
    const n = d.resumo.atencao + d.resumo.falha + (off ? 1 : 0);
    c.hidden = !n; c.textContent = n;
    c.classList.toggle('is-warning', !(d.resumo.falha || off));
    c.setAttribute('aria-label', `${n} ${n === 1 ? 'sensor precisa' : 'sensores precisam'} de atenção`);
  }

  // conexão com o Raspberry
  let ultimoOk = true;
  async function pingar() {
    try { const r = await fetch('/ping', { cache: 'no-store' }); conexao(r.ok); }
    catch (e) { conexao(false); }
  }
  function conexao(ok) {
    const d = document.getElementById('conn-dot'), t = document.getElementById('conn-txt');
    if (!d) return;
    d.classList.toggle('is-off', !ok); t.textContent = ok ? 'Conectado' : 'Sem conexão';
    if (!ok && ultimoOk) toast('Sem conexão com o Raspberry. Tentando de novo…', 'danger');
    if (ok && !ultimoOk) toast('Conexão restabelecida.', 'success');
    ultimoOk = ok;
  }

  // ------------------------------------------------------------------ toasts
  function toast(msg, tipo = 'success', ms = 4200) {
    let caixa = document.getElementById('toasts');
    if (!caixa) { caixa = document.createElement('div'); caixa.id = 'toasts'; caixa.className = 'toasts'; caixa.setAttribute('role', 'status'); caixa.setAttribute('aria-live', 'polite'); document.body.appendChild(caixa); }
    const el = document.createElement('div');
    el.className = `toast toast--${tipo}`;
    el.innerHTML = `${icone({ success: 'ok', danger: 'erro', info: 'info' }[tipo] || 'info')}<div>${f.esc(msg)}</div>
      <button class="btn btn--ghost btn--sm btn--icon toast__x" type="button" aria-label="Fechar aviso">${icone('x')}</button>`;
    el.querySelector('button').onclick = () => el.remove();
    caixa.appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  // ------------------------------------------------------------------ confirmação (dialog nativo: foco e Esc acessíveis)
  function confirmar({ titulo, texto, acao = 'Confirmar', perigo = false }) {
    return new Promise(res => {
      const d = document.createElement('dialog');
      d.className = 'modal';
      d.setAttribute('aria-labelledby', 'modal-t'); d.setAttribute('aria-describedby', 'modal-d');
      d.innerHTML = `<form method="dialog"><div class="modal__body"><h2 class="h2" id="modal-t">${f.esc(titulo)}</h2><p id="modal-d">${f.esc(texto)}</p></div>
        <div class="modal__foot"><button class="btn" value="nao" autofocus>Cancelar</button><button class="btn ${perigo ? 'btn--danger' : 'btn--primary'}" value="sim">${f.esc(acao)}</button></div></form>`;
      document.body.appendChild(d);
      d.addEventListener('close', () => { res(d.returnValue === 'sim'); d.remove(); });
      d.showModal();
    });
  }

  // ------------------------------------------------------------------ tooltip (gráficos e mapas)
  let tipEl = null;
  function tip(e, html) {
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'tooltip'; tipEl.setAttribute('role', 'tooltip'); document.body.appendChild(tipEl); }
    tipEl.innerHTML = html; tipEl.hidden = false;
    const x = Math.min(e.clientX + 14, innerWidth - tipEl.offsetWidth - 8), y = Math.min(e.clientY + 14, innerHeight - tipEl.offsetHeight - 8);
    tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
  }
  function semTip() { if (tipEl) tipEl.hidden = true; }

  // ------------------------------------------------------------------ estados vazios / carregando
  const vazio = (titulo, texto = '', ic = 'vazio') => `<div class="empty">${icone(ic)}<strong>${f.esc(titulo)}</strong>${texto ? `<p>${texto}</p>` : ''}</div>`;
  const carregando = (linhas = 5) => `<div style="padding:16px 20px; display:grid; gap:12px" aria-busy="true" aria-label="Carregando">${Array.from({ length: linhas }, (_, i) => `<div class="skeleton" style="height:14px; width:${92 - (i % 3) * 14}%"></div>`).join('')}</div>`;

  // ------------------------------------------------------------------ tabela com ordenação, paginação e versão para celular
  /*  UI.tabela(el, {
   *    colunas: [{ id, titulo, num:true, ordem:(linha)=>valor, html:(linha)=>string, classe, largo:true }],
   *    linhas: [...], porPagina: 25, vazio: html, aoClicar: linha => {}, ordenarPor: 'id', desc: true })
   *  Retorna { atualizar(linhas) }.  */
  function tabela(el, cfg) {
    const st = { pag: 0, ordem: cfg.ordenarPor || null, desc: cfg.desc ?? true, linhas: cfg.linhas || [] };
    const porPag = cfg.porPagina || 25;
    function desenhar() {
      let ls = st.linhas.slice();
      const col = cfg.colunas.find(c => c.id === st.ordem);
      if (col && col.ordem) ls.sort((a, b) => { const x = col.ordem(a), y = col.ordem(b); return (x > y ? 1 : x < y ? -1 : 0) * (st.desc ? -1 : 1); });
      if (!ls.length) { el.innerHTML = cfg.vazio || vazio('Nada por aqui'); return; }
      const paginas = Math.ceil(ls.length / porPag); st.pag = Math.min(st.pag, paginas - 1);
      const pagina = ls.slice(st.pag * porPag, (st.pag + 1) * porPag);
      const th = c => {
        const cls = c.num ? ' class="n"' : '';
        if (!c.ordem) return `<th scope="col"${cls}>${c.titulo}</th>`;
        const ativa = st.ordem === c.id, aria = ativa ? (st.desc ? 'descending' : 'ascending') : 'none';
        return `<th scope="col"${cls} aria-sort="${aria}"><button type="button" data-ord="${c.id}">${c.titulo}${icone(ativa ? (st.desc ? 'desce' : 'sobe') : 'ordem')}</button></th>`;
      };
      el.innerHTML = `<div class="table-wrap"><table class="table is-stack"><thead><tr>${cfg.colunas.map(th).join('')}</tr></thead><tbody>
        ${pagina.map((l, i) => `<tr${cfg.aoClicar ? ` class="is-clickable" tabindex="0" data-i="${i}"` : ''}>${cfg.colunas.map(c => {
          const h = c.html(l), vazia = c.largo && /^<span class="subtle">[—–-]<\/span>$/.test(h);   // no celular, campo vazio não ocupa espaço
          return `<td data-label="${c.titulo ? f.esc(c.titulo.replace(/<[^>]+>/g, '')) : ''}" class="${[c.num ? 'n' : '', c.classe || '', c.largo ? 'is-wide' : '', vazia ? 'is-empty' : ''].join(' ').trim()}">${h}</td>`;
        }).join('')}</tr>`).join('')}
        </tbody></table></div>` + (paginas > 1 ? `<div class="pager"><span>${st.pag * porPag + 1}–${Math.min(ls.length, (st.pag + 1) * porPag)} de ${f.num(ls.length)}</span>
          <div class="row"><button class="btn btn--sm" type="button" data-pag="-1" ${st.pag === 0 ? 'disabled' : ''}>${icone('setaEsq')}Anterior</button>
          <span class="text-sm muted" style="padding:0 8px">Página ${st.pag + 1} de ${paginas}</span>
          <button class="btn btn--sm" type="button" data-pag="1" ${st.pag >= paginas - 1 ? 'disabled' : ''}>Próxima${icone('seta')}</button></div></div>` : '');
      el.querySelectorAll('[data-ord]').forEach(b => b.onclick = () => { if (st.ordem === b.dataset.ord) st.desc = !st.desc; else { st.ordem = b.dataset.ord; st.desc = true; } st.pag = 0; desenhar(); el.querySelector(`[data-ord="${b.dataset.ord}"]`)?.focus(); });
      el.querySelectorAll('[data-pag]').forEach(b => b.onclick = () => { st.pag += +b.dataset.pag; desenhar(); el.scrollIntoView({ block: 'nearest' }); });
      if (cfg.aoClicar) el.querySelectorAll('tr[data-i]').forEach(tr => {
        const go = () => cfg.aoClicar(pagina[+tr.dataset.i]);
        tr.addEventListener('click', e => { if (!e.target.closest('button, a')) go(); });
        tr.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === tr) { e.preventDefault(); go(); } });
      });
      if (cfg.depois) cfg.depois(el, pagina);
    }
    desenhar();
    return { atualizar(ls, manterPagina = false) { st.linhas = ls; if (!manterPagina) st.pag = 0; desenhar(); } };
  }

  // botão em estado de envio (evita clique duplo enquanto espera o servidor)
  async function enviando(btn, fn) {
    btn.disabled = true; btn.classList.add('is-loading');
    try { return await fn(); } finally { btn.disabled = false; btn.classList.remove('is-loading'); }
  }

  window.UI = { shell, marcarAtivo, definirLogado, conexao, toast, confirmar, tip, semTip, tabela, enviando, vazio, carregando, icone, catBadge, f, temaAtual };
})();
