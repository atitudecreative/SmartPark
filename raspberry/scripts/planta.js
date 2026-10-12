/*
 * SmartPlanta — desenho a planta do estacionamento em SVG, no estilo de planta baixa
 * (asfalto, canteiros, prédios, vagas numeradas, vagas de idoso e PcD).
 * Uso o mesmo desenho em todas as telas: painel da equipe, tablet do motorista, admin e simulador.
 *
 *   const p = SmartPlanta.criar(elemento, layout, { aoClicar: id => ..., livresVerdes: true })
 *   p.estados({ "07": "ocupada", "12": "reservada" })          // livre | ocupada | reservada
 *   p.rota([[x,y], ...], "137")                                 // caminho até a vaga + destaque
 *   p.calor({ "07": 83.2, ... }, "% do tempo ocupada")          // mapa de uso (admin)
 *   p.saude({ "07": "atencao", ... })                           // ok | atencao | falha (admin)
 *   p.limpar()                                                  // volta ao desenho base
 *   p.paraTela(x, y)                                            // metros -> pixels (para camadas por cima)
 * Trabalho em metros, com o eixo y para baixo (igual ao layout.py).
 */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const COR = {
    grama: '#56783a', gramaEscura: '#4a6a31', asfalto: '#3b3f44', faixa: '#f1f2ef',
    calcada: '#c9c1af', telhado: '#e6e7e8', telhadoBorda: '#9aa1a8', sombra: 'rgba(0,0,0,.28)',
    idoso: '#e7b416', pcd: '#1f61c3', livre: '#1baf7a', reservada: '#f2b705', rota: '#f2b705',
  };
  const CARROS = ['#e9ebee', '#b8bec6', '#2b2f35', '#8d1f22', '#2a4f86', '#5f6670', '#d8d2c4'];

  function el(tag, attrs, pai) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (pai) pai.appendChild(e);
    return e;
  }
  function hash(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }

  // ---------------------------------------------------------------- pictogramas
  function iconeIdoso(g, x, y, s, cor) {
    const i = el('g', { transform: `translate(${x} ${y}) scale(${s})`, fill: 'none', stroke: cor, 'stroke-width': .16, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, g);
    el('circle', { cx: -.05, cy: -.78, r: .17, fill: cor, stroke: 'none' }, i);
    el('path', { d: 'M-.1 -.55 L-.22 .05 L-.05 .1 M-.22 .05 L-.35 .7 M-.17 -.2 L.08 0 M-.05 .1 L.05 .7 M.18 -.05 L.3 .7' }, i);
    return i;
  }
  function iconePcd(g, x, y, s, cor) {
    const i = el('g', { transform: `translate(${x} ${y}) scale(${s})`, fill: 'none', stroke: cor, 'stroke-width': .15, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, g);
    el('circle', { cx: -.12, cy: -.8, r: .16, fill: cor, stroke: 'none' }, i);
    el('path', { d: 'M-.15 -.55 L-.1 .02 L.32 .02 L.48 .55 M-.12 -.3 L.25 -.3' }, i);
    el('path', { d: 'M-.38 -.12 A.5 .5 0 1 0 .2 .42' }, i);
    return i;
  }

  function arvore(g, x, y, r) {
    el('circle', { cx: x + r * .15, cy: y + r * .2, r: r, fill: 'rgba(0,0,0,.22)' }, g);
    el('circle', { cx: x, cy: y, r: r, fill: '#3e6a2b' }, g);
    el('circle', { cx: x - r * .25, cy: y - r * .25, r: r * .62, fill: '#5d8f3e' }, g);
    el('circle', { cx: x - r * .4, cy: y - r * .4, r: r * .22, fill: '#7fae58' }, g);
  }

  // ---------------------------------------------------------------- geometria
  function eixoDaVaga(L, v) {
    const no = L._no, a = no[v.aresta[0]], b = no[v.aresta[1]];
    const c = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    return { ux: (b.x - a.x) / c, uy: (b.y - a.y) / c, ang: Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI };
  }

  let instancias = 0;
  function criar(alvo, L, opts = {}) {
    const uid = 'sp' + (++instancias);   // ids únicos: várias plantas na mesma página
    L._no = Object.fromEntries(L.nos.map(n => [n.id, n]));
    const [x0, y0, x1, y1] = L.limites || [-10, -10, 110, 50];
    const W = x1 - x0, H = y1 - y0;
    alvo.innerHTML = '';
    const svg = el('svg', { viewBox: `${x0} ${y0} ${W} ${H}`, preserveAspectRatio: 'xMidYMid meet', role: 'img',
      'aria-label': 'Planta do estacionamento', class: 'planta-svg' }, alvo);
    svg.style.display = 'block'; svg.style.width = '100%'; svg.style.height = '100%';

    const defs = el('defs', {}, svg);
    const hach = el('pattern', { id: uid + '-hachura', width: .7, height: .7, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
    el('rect', { width: .7, height: .7, fill: '#e7b416' }, hach);
    el('rect', { width: .35, height: .7, fill: '#2b2e33' }, hach);
    const grama = el('pattern', { id: uid + '-grama', width: 3, height: 3, patternUnits: 'userSpaceOnUse' }, defs);
    el('rect', { width: 3, height: 3, fill: COR.grama }, grama);
    el('circle', { cx: .7, cy: .9, r: .25, fill: COR.gramaEscura }, grama);
    el('circle', { cx: 2.2, cy: 2.1, r: .2, fill: '#62853f' }, grama);
    const est = el('style', {}, svg);
    est.textContent = `
      .sp-res { animation: sp-pulso 1.1s ease-in-out infinite; }
      .sp-dest { animation: sp-pulso .8s ease-in-out infinite; }
      .sp-rota { animation: sp-anda 1s linear infinite; }
      @keyframes sp-pulso { 50% { opacity: .35; } }
      @keyframes sp-anda { to { stroke-dashoffset: -4.4; } }
      @media (prefers-reduced-motion: reduce) { .sp-res, .sp-dest, .sp-rota { animation: none; } }
      .sp-vaga { cursor: ${opts.aoClicar ? 'pointer' : 'default'}; }
      .sp-txt { font-family: "Overpass", "Barlow", system-ui, sans-serif; }`;

    const camada = n => el('g', { class: 'sp-' + n }, svg);
    const gBase = camada('base'), gVias = camada('vias'), gVagas = camada('vagas'), gPred = camada('predios'),
      gDeco = camada('deco'), gArv = camada('arvores'), gEstado = camada('estado'), gRota = camada('rota'), gTopo = camada('topo');
    // a rota e o marcador de destino ficam por cima das vagas, mas não podem roubar o clique delas
    gRota.setAttribute('pointer-events', 'none'); gTopo.setAttribute('pointer-events', 'none');

    // ---------- terreno, canteiros e calçadas
    const deco = L.decoracao || [];
    if (!deco.some(d => d.tipo === 'canteiro' && d.w >= W * .9)) el('rect', { x: x0, y: y0, width: W, height: H, fill: `url(#${uid}-grama)` }, gBase);
    for (const d of deco) {
      if (d.tipo === 'canteiro') el('rect', { x: d.x, y: d.y, width: d.w, height: d.h, rx: d.w < 3 || d.h < 3 ? .8 : 1.2, fill: `url(#${uid}-grama)`, stroke: d.w < W * .9 ? '#e8e8e2' : 'none', 'stroke-width': .25 }, gBase);
      if (d.tipo === 'calcada') el('rect', { x: d.x, y: d.y, width: d.w, height: d.h, fill: COR.calcada }, gBase);
    }

    // ---------- vias (asfalto) e áreas de vaga
    for (const e of L.arestas) {
      const a = L._no[e.a], b = L._no[e.b];
      el('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: COR.asfalto, 'stroke-width': e.tipo === 'corredor' && !['A', 'B'].includes(e.zona) ? 6 : 7, 'stroke-linecap': 'square' }, gVias);
    }
    // bordas brancas das vias externas (meio-fio)
    // ---------- vagas
    const vagaEl = {};
    for (const v of L.vagas) {
      const { ux, uy, ang } = eixoDaVaga(L, v);
      const w = v.largura || 2.5, d = 5;
      const g = el('g', { class: 'sp-vaga', 'data-id': v.id }, gVagas);
      const r = el('g', { transform: `translate(${v.x} ${v.y}) rotate(${ang})` }, g);
      const fundo = v.tipo === 'pcd' ? COR.pcd : COR.asfalto;
      el('rect', { x: -w / 2, y: -d / 2, width: w, height: d, fill: fundo }, r);
      if (v.tipo === 'pcd') el('rect', { x: w / 2 - .7, y: -d / 2, width: .7, height: d, fill: `url(#${uid}-hachura)` }, r);
      el('rect', { x: -w / 2, y: -d / 2, width: w, height: d, fill: 'none', stroke: v.tipo === 'idoso' ? COR.idoso : COR.faixa, 'stroke-width': v.tipo === 'idoso' ? .22 : .13 }, r);
      const sobre = el('rect', { x: -w / 2 + .1, y: -d / 2 + .1, width: w - .2, height: d - .2, fill: 'transparent' }, r);
      // ícone e número (sempre em pé)
      const horizontal = Math.abs(uy) > Math.abs(ux);   // via vertical -> vaga deitada
      const tam = (v.id.length > 2 ? 1.05 : 1.2);
      if (v.tipo !== 'comum') {
        const ix = horizontal ? v.x - 1.15 : v.x, iy = horizontal ? v.y + .05 : v.y - .9;
        (v.tipo === 'pcd' ? iconePcd : iconeIdoso)(g, ix, iy, 1.05, v.tipo === 'pcd' ? '#fff' : COR.idoso);
        const t = el('text', { x: horizontal ? v.x + 1.05 : v.x, y: horizontal ? v.y + .42 : v.y + 1.75, 'text-anchor': 'middle', 'font-size': tam * .9, fill: '#fff', 'font-weight': 700, class: 'sp-txt' }, g);
        t.textContent = v.id;
      } else {
        const t = el('text', { x: v.x, y: v.y + tam * .36, 'text-anchor': 'middle', 'font-size': tam, fill: '#f1f2ef', 'font-weight': 600, class: 'sp-txt' }, g);
        t.textContent = v.id;
      }
      const tit = el('title', {}, g); tit.textContent = `Vaga ${v.id}` + (v.tipo !== 'comum' ? ` (${v.tipo === 'pcd' ? 'PcD' : 'idoso'})` : '') + ` · setor ${v.zona}`;
      vagaEl[v.id] = { g, r, sobre, w, d, ang, v, titulo: tit };
      if (opts.aoClicar) g.addEventListener('click', () => opts.aoClicar(v.id));
    }

    // ---------- prédios
    for (const d of deco) {
      if (d.tipo !== 'predio') continue;
      el('rect', { x: d.x + .7, y: d.y + .9, width: d.w, height: d.h, fill: COR.sombra }, gPred);
      el('rect', { x: d.x, y: d.y, width: d.w, height: d.h, fill: COR.telhado, stroke: COR.telhadoBorda, 'stroke-width': .35 }, gPred);
      el('rect', { x: d.x + 1.1, y: d.y + 1.1, width: d.w - 2.2, height: d.h - 2.2, fill: 'none', stroke: '#cfd2d5', 'stroke-width': .25 }, gPred);
      const t = el('text', { x: d.x + d.w / 2, y: d.y + d.h / 2 + 1, 'text-anchor': 'middle', 'font-size': d.w < 14 ? 1.7 : 2.8, 'font-weight': 800, fill: '#22262b', class: 'sp-txt', 'letter-spacing': .05 }, gPred);
      t.textContent = d.rotulo || '';
      if (d.w < 14) t.setAttribute('transform', `rotate(-90 ${d.x + d.w / 2} ${d.y + d.h / 2})`);
      if (d.porta) {
        el('rect', { x: d.porta[0] - 2.5, y: d.porta[1] - .9, width: 5, height: 1.3, fill: '#8b9097' }, gPred);
        el('rect', { x: d.porta[0] - 2.2, y: d.porta[1] - .7, width: 4.4, height: .9, fill: '#c4c8cc' }, gPred);
      }
    }

    // ---------- guarita, cancela, faixas, setas, rótulos
    for (const d of deco) {
      if (d.tipo === 'guarita') {
        el('rect', { x: d.x + .4, y: d.y + .5, width: d.w, height: d.h, fill: COR.sombra }, gDeco);
        el('rect', { x: d.x, y: d.y, width: d.w, height: d.h, fill: '#d8dbde', stroke: '#7d848c', 'stroke-width': .2 }, gDeco);
        el('rect', { x: d.x + .5, y: d.y + .6, width: d.w - 1, height: 1.1, fill: '#56606b' }, gDeco);
      } else if (d.tipo === 'cancela') {
        const n = 8, dx = (d.x2 - d.x1) / n;
        for (let i = 0; i < n; i++) el('line', { x1: d.x1 + i * dx, y1: d.y1, x2: d.x1 + (i + 1) * dx, y2: d.y2, stroke: i % 2 ? '#f1f2ef' : '#d9302f', 'stroke-width': .55 }, gDeco);
        el('circle', { cx: d.x1, cy: d.y1, r: .5, fill: '#2b2e33' }, gDeco);
      } else if (d.tipo === 'faixa') {
        for (let x = d.x + .3; x < d.x + d.w; x += 1.1) el('rect', { x, y: d.y, width: .55, height: d.h, fill: '#f1f2ef' }, gDeco);
      } else if (d.tipo === 'seta') {
        el('path', { d: 'M-2.2 -.22 H.9 V-.75 L2.2 0 L.9 .75 V.22 H-2.2 Z', fill: '#f1f2ef', transform: `translate(${d.x} ${d.y}) rotate(${d.ang})` }, gDeco);
      } else if (d.tipo === 'rotulo') {
        const t = el('text', { x: d.x, y: d.y, 'text-anchor': 'middle', 'font-size': d.pequeno ? 1.3 : 2.4, 'font-weight': 800,
          fill: '#f1f2ef', class: 'sp-txt', 'letter-spacing': d.pequeno ? .15 : .1 }, gDeco);
        t.textContent = d.texto;
      }
    }
    // letras dos setores no topo de cada corredor
    const zonasCor = {};
    for (const e of L.arestas) {
      if (e.tipo !== 'corredor' || ['A', 'B'].includes(e.zona)) continue;
      const a = L._no[e.a], b = L._no[e.b], top = a.y < b.y ? a : b;
      const vs = L.vagas.filter(v => v.zona === e.zona);
      const yMin = Math.min(...vs.map(v => v.y)) - 4.5;
      el('circle', { cx: top.x, cy: yMin, r: 2, fill: '#f1f2ef' }, gDeco);
      const t = el('text', { x: top.x, y: yMin + .85, 'text-anchor': 'middle', 'font-size': 2.4, 'font-weight': 800, fill: '#22262b', class: 'sp-txt' }, gDeco);
      t.textContent = e.zona;
      zonasCor[e.zona] = [top.x, yMin];
    }
    // porta da igreja
    const [px, py] = L.porta;
    el('circle', { cx: px, cy: py, r: .8, fill: '#f2b705', stroke: '#22262b', 'stroke-width': .25 }, gDeco);

    // ---------- árvores (posições fixas, sem sorteio)
    for (const d of deco) {
      if (d.tipo !== 'canteiro' || !d.arvores) continue;
      const n = d.arvores, vertical = d.h > d.w;
      if (vertical || d.h < 6) {
        for (let i = 0; i < n; i++) {
          const f = (i + .5) / n;
          arvore(gArv, vertical ? d.x + d.w / 2 : d.x + d.w * f, vertical ? d.y + d.h * f : d.y + d.h / 2, Math.min(2.2, Math.max(.9, Math.min(d.w, d.h) * .5)));
        }
      } else {
        const linhas = d.h > 18 ? 2 : 1;
        for (let l = 0; l < linhas; l++) for (let i = 0; i < n; i++) {
          const f = (i + .5 + (l % 2) * .5) / n;
          if (f >= 1) continue;
          arvore(gArv, d.x + d.w * f, d.y + d.h * (l + 1) / (linhas + 1), 2.3 - (hash(d.x + i + l) % 5) * .15);
        }
      }
    }

    // ---------------------------------------------------------------- API
    const api = {
      svg, L,
      paraTela(x, y) {
        const r = svg.getBoundingClientRect(), s = Math.min(r.width / W, r.height / H);
        const ox = (r.width - W * s) / 2, oy = (r.height - H * s) / 2;
        return [ox + (x - x0) * s, oy + (y - y0) * s, s];
      },
      _estado: {},
      estados(map, extras = {}) {
        for (const id in vagaEl) {
          const e = map[id] || 'livre';
          if (api._estado[id] === e && !extras[id]) continue;
          api._estado[id] = e;
          const ve = vagaEl[id];
          ve.carro && ve.carro.remove(); ve.carro = null;
          ve.marca && ve.marca.remove(); ve.marca = null;
          if (e === 'ocupada') {
            const c = CARROS[hash(id) % CARROS.length];
            const g = el('g', { transform: `translate(${ve.v.x} ${ve.v.y}) rotate(${ve.ang + 90})`, 'pointer-events': 'none' }, gEstado);
            el('rect', { x: -2.15, y: -.9, width: 4.3, height: 1.8, rx: .55, fill: 'rgba(0,0,0,.35)', transform: 'translate(.15 .2)' }, g);
            el('rect', { x: -2.1, y: -.88, width: 4.2, height: 1.76, rx: .55, fill: c, stroke: 'rgba(0,0,0,.4)', 'stroke-width': .08 }, g);
            el('rect', { x: .35, y: -.72, width: .85, height: 1.44, rx: .2, fill: 'rgba(25,30,38,.82)' }, g);
            el('rect', { x: -1.55, y: -.68, width: .55, height: 1.36, rx: .18, fill: 'rgba(25,30,38,.7)' }, g);
            ve.carro = g;
          } else if (e === 'reservada') {
            ve.marca = el('rect', { x: -ve.w / 2 + .15, y: -ve.d / 2 + .15, width: ve.w - .3, height: ve.d - .3, fill: 'rgba(242,183,5,.35)', stroke: COR.reservada, 'stroke-width': .35, class: 'sp-res' }, ve.r);
          } else if (opts.livresVerdes && ve.v.tipo === 'comum') {
            ve.marca = el('rect', { x: -ve.w / 2 + .35, y: -ve.d / 2 + .35, width: ve.w - .7, height: ve.d - .7, rx: .3, fill: 'rgba(27,175,122,.28)' }, ve.r);
            ve.r.insertBefore(ve.marca, ve.sobre);
          }
          if (extras[id]) ve.titulo.textContent = extras[id];
        }
      },
      rota(pontos, destino) {
        gRota.innerHTML = ''; gTopo.innerHTML = '';
        if (!pontos || pontos.length < 2) return;
        const d = pontos.map((p, i) => (i ? 'L' : 'M') + p[0] + ' ' + p[1]).join(' ');
        el('path', { d, fill: 'none', stroke: 'rgba(0,0,0,.45)', 'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, gRota);
        el('path', { d, fill: 'none', stroke: '#fff7d6', 'stroke-width': 1.7, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, gRota);
        el('path', { d, fill: 'none', stroke: COR.rota, 'stroke-width': 1.1, 'stroke-dasharray': '2.2 2.2', 'stroke-linejoin': 'round', class: 'sp-rota' }, gRota);
        const [sx, sy] = pontos[0];
        el('circle', { cx: sx, cy: sy, r: 1.6, fill: '#22262b', stroke: COR.rota, 'stroke-width': .5 }, gTopo);
        const t = el('text', { x: sx + 2.6, y: sy + .6, 'font-size': 1.8, 'font-weight': 800, fill: '#fff', class: 'sp-txt', stroke: '#22262b', 'stroke-width': .5, 'paint-order': 'stroke' }, gTopo);
        t.textContent = 'VOCÊ';
        if (destino && vagaEl[destino]) {
          const ve = vagaEl[destino];
          el('rect', { x: -ve.w / 2 - .4, y: -ve.d / 2 - .4, width: ve.w + .8, height: ve.d + .8, rx: .4, fill: 'none', stroke: COR.rota, 'stroke-width': .6, class: 'sp-dest',
            transform: `translate(${ve.v.x} ${ve.v.y}) rotate(${ve.ang})` }, gTopo);
          const pino = el('g', { transform: `translate(${ve.v.x} ${ve.v.y - 5.4})` }, gTopo);
          el('path', { d: 'M0 2.6 L-1.4 .9 A2.1 2.1 0 1 1 1.4 .9 Z', fill: COR.rota, stroke: '#22262b', 'stroke-width': .25 }, pino);
          el('circle', { cx: 0, cy: -.5, r: .75, fill: '#22262b' }, pino);
        }
      },
      calor(valores, rotulo = '') {
        // uso escala relativa (da vaga menos usada à mais usada) para a diferença aparecer no mapa
        api.limpar();
        const vs = Object.values(valores), mn = Math.min(...vs, 0), mx = Math.max(...vs, 1);
        for (const id in vagaEl) {
          const p = valores[id] ?? 0, ve = vagaEl[id], a = .08 + .87 * Math.max(0, Math.min(1, (p - mn) / ((mx - mn) || 1)));
          ve.marca = el('rect', { x: -ve.w / 2 + .12, y: -ve.d / 2 + .12, width: ve.w - .24, height: ve.d - .24, fill: `rgba(57,135,229,${a.toFixed(2)})` }, ve.r);
          ve.r.insertBefore(ve.marca, ve.sobre);
          ve.titulo.textContent = `Vaga ${id} · ${Math.round(p)}% ${rotulo}`;
        }
      },
      saude(mapa) {
        api.limpar();
        const cor = { atencao: 'rgba(237,161,0,.85)', falha: 'rgba(227,73,72,.9)' };
        for (const id in vagaEl) {
          const s = mapa[id] || 'ok', ve = vagaEl[id];
          if (s === 'ok') continue;
          ve.marca = el('rect', { x: -ve.w / 2 + .12, y: -ve.d / 2 + .12, width: ve.w - .24, height: ve.d - .24, fill: cor[s], class: 'sp-res' }, ve.r);
          ve.r.insertBefore(ve.marca, ve.sobre);
        }
      },
      limpar() {
        for (const id in vagaEl) {
          const ve = vagaEl[id];
          ve.carro && ve.carro.remove(); ve.carro = null;
          ve.marca && ve.marca.remove(); ve.marca = null;
        }
        api._estado = {};
        gRota.innerHTML = ''; gTopo.innerHTML = '';
      },
      contagem(map) {
        const r = { comum: [0, 0], idoso: [0, 0], pcd: [0, 0] };
        for (const v of L.vagas) { r[v.tipo][1]++; if ((map[v.id] || 'livre') === 'livre') r[v.tipo][0]++; }
        return r;
      },
    };
    return api;
  }

  window.SmartPlanta = { criar, COR };
})();
