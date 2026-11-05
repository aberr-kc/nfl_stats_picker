// Served-page DOM check for the v2 picks page (no npm packages).
//   node tests/check_picks_dom.js http://127.0.0.1:8001
// Fetches / and /generate-picks from the running server, extracts the picks
// functions from the served index.html, runs them in a vm context on the
// served JSON, and asserts the A4 #13 items in both toggle states.
// Writes the first rendered page with the served CSS to
// %TEMP%\nfl_backtest\picks_render.html for a headless screenshot.
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const os = require('os');

const base = (process.argv[2] || 'http://127.0.0.1:8001').replace(/\/$/, '');
const FUNCS = ['escapeHtml', 'isV2', 'v2Cards', 'kZeroNoteHtml', 'toggleButtonHtml', 'zeroFlagMessage',
    'renderPicks', 'toggleUnflagged', 'formatPicksFromJSON', 'adjustmentComponents', 'adjustmentCellHtml',
    'formatPlayerStatSection', 'formatV2StatSection', 'displayPicksPage'];

const failures = [];
function check(cond, msg) {
    if (!cond) failures.push(msg);
}

function extractFunction(src, name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`function ${name} not found in served index.html`);
    let i = src.indexOf('{', start);
    let depth = 0;
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') {
            depth--;
            if (depth === 0) return src.slice(start, i + 1);
        }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

function unescapeHtml(s) {
    return s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

function parseCards(html) {
    const cards = [];
    const re = /<div id="player_[^"]*" class="v2-card" data-flagged="(true|false)" data-edge="([^"]*)"/g;
    let m;
    while ((m = re.exec(html)) !== null) {
        cards.push({ flagged: m[1] === 'true', edge: m[2] === '' ? null : parseFloat(m[2]) });
    }
    return cards;
}

function parseRows(html) {
    const rows = [];
    const re = /<tr class="v2-row" data-key="([^"]*)" data-flagged="(true|false)"[^>]*>([\s\S]*?)<\/tr>/g;
    let m;
    while ((m = re.exec(html)) !== null) {
        rows.push({ key: unescapeHtml(m[1]), flagged: m[2] === 'true', body: m[3] });
    }
    return rows;
}

function checkState(label, html, allHtml, data, dataRows, expectAll) {
    const model = data.model;
    const cards = parseCards(allHtml);
    const rows = parseRows(allHtml);
    const allCards = (() => {
        const seen = new Set();
        for (const p of data.players) for (const r of p.stats) seen.add(`${p.player}|${r.stat}`);
        return seen.size;
    })();
    const flaggedCards = new Set();
    for (const p of data.players) for (const r of p.stats) if (r.flagged) flaggedCards.add(`${p.player}|${r.stat}`);

    if (cards.length) {
        const nonTd = parseRows(html).some(r => r.key.split('|')[1] !== 'anytime_td');
        const hasTd = parseRows(html).some(r => r.key.split('|')[1] === 'anytime_td');
        if (hasTd) check(html.includes('<th>TD rate (λ/game)</th>'), `${label}: TD header missing`);
        const avgLabel = model.window_n ? `Avg (last ${model.window_n} played)` : 'Weighted avg (games played)';
        if (nonTd) check(html.includes(`<th>${avgLabel}</th>`), `${label}: header "${avgLabel}" missing`);
        check(!html.includes('Player Avg (3)'), `${label}: old "Player Avg (3)" header present`);
        for (const h of ['Model %', 'Market %', 'Final %', 'Price (book)', 'Edge (pts)']) {
            check(html.includes(`<th>${h}</th>`), `${label}: header "${h}" missing`);
        }
    }
    // no (player, stat, line) twice
    const keys = rows.map(r => r.key);
    check(new Set(keys).size === keys.length, `${label}: duplicate (player, stat, line) rows`);
    // flagged cards first, then non-increasing edge (nulls last) within each group
    let seenUnflagged = false;
    let prev = { flagged: true, edge: Infinity };
    for (const c of cards) {
        if (!c.flagged) seenUnflagged = true;
        check(!(c.flagged && seenUnflagged), `${label}: flagged card after an unflagged card`);
        if (c.flagged === prev.flagged) {
            const a = prev.edge === null ? -Infinity : prev.edge;
            const b = c.edge === null ? -Infinity : c.edge;
            check(b <= a, `${label}: card edges not in non-increasing order (${prev.edge} then ${c.edge})`);
        }
        prev = c;
    }
    // rows with no side price show "no price" and are never flagged
    const byKey = new Map(dataRows.map(r => [r._key, r]));
    for (const r of rows) {
        const d = byKey.get(r.key);
        check(!!d, `${label}: rendered row ${r.key} not in the served data`);
        if (!d) continue;
        if (d.price === null || d.marketSource === 'none') {
            check(!d.flagged && !r.flagged, `${label}: unpriced row ${r.key} is flagged`);
            check(r.body.includes('no price'), `${label}: unpriced row ${r.key} does not show "no price"`);
        }
        check(r.flagged === d.flagged, `${label}: row ${r.key} flag mismatch`);
        if (model.ou_k_all_zero && d.edgeSource === 'price only' && d.edgePts !== null) {
            check(r.body.includes('(price only)'), `${label}: price-only row ${r.key} lacks "(price only)"`);
        }
    }
    const pageCards = parseCards(html).length;
    if (expectAll) {
        check(cards.length === allCards, `${label}: expected all ${allCards} cards, got ${cards.length}`);
    } else {
        check(cards.every(c => c.flagged), `${label}: unflagged-only card rendered with showUnflagged=false`);
        check(cards.length === flaggedCards.size, `${label}: expected ${flaggedCards.size} flagged cards, got ${cards.length}`);
    }
    check(pageCards === Math.min(cards.length, 10), `${label}: page 1 shows ${pageCards} cards`);
    check(!html.includes('Page 1 of 0'), `${label}: "Page 1 of 0" shown`);
    check(html.includes('id="toggle-unflagged"'), `${label}: toggle button missing`);
    if (model.ou_k_all_zero) {
        check(html.includes('Over/Under probabilities follow the market'), `${label}: k = 0 note missing`);
    }
    return { cards: cards.length, rows: rows.length, pageCards };
}

// Split rendered HTML into cards and report, per card, whether the Adjusted
// Stat / Adjustments columns are shown and whether every row has as many
// cells as the header has columns.
function cardTables(html) {
    return html.split(/<div id="player_/).slice(1).map(chunk => {
        const thead = (chunk.match(/<thead>([\s\S]*?)<\/thead>/) || [, ''])[1];
        const nTh = (thead.match(/<th>/g) || []).length;
        const tbody = (chunk.match(/<tbody>([\s\S]*?)<\/tbody>/) || [, ''])[1];
        const rows = [...tbody.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)].map(m => m[1]);
        return {
            showsAdj: thead.includes('<th>Adjusted Stat</th>') && thead.includes('<th>Adjustments</th>'),
            anyAdjHeader: thead.includes('Adjusted Stat') || thead.includes('Adjustments'),
            aligned: rows.every(r => (r.match(/<td[\s>]/g) || []).length === nTh),
            nTh, rows, chunk,
        };
    });
}

function fixtureRow(stat, line, adj) {
    const row = {
        stat, line, side: 'Over', price: -110, bookmaker: 'book', bookmakers: ['book'], probModel: 55,
        probMarket: 52, marketSource: 'no-vig (cross-book)', overround: null, probFinal: 53, edgePts: 1,
        edgeSource: 'blend', flagged: false, noFlagReason: 'below margin', player_value: 60, gamesUsed: 4,
        adjustmentDetails: adj,
    };
    const key = { rushing_yards: 'adjustedRushingYards', receiving_yards: 'adjustedReceivingYards' }[stat];
    if (adj && key) row[key] = adj.adjusted;
    return row;
}

const NEUTRAL_WEATHER = { label: 'Weather', pct: 0, text: 'No weather data (adjustment disabled)' };
const RUSH_MATCHUP = { label: 'Matchup', pct: 0, text: 'rushing matchup adjustment disabled (beta=0)' };

function checkFixtures(ctx) {
    const model = { version: 'v2', window_n: 6 };
    const render = (statType, rows, m = model) => {
        ctx.__args = [statType, rows, m];
        return cardTables(vm.runInContext("formatPlayerStatSection('Fixture Player', 'A @ B', __args[0], __args[1], __args[2])", ctx))[0];
    };
    const allAligned = (label, c) => check(c && c.aligned, `${label}: row cell count does not match the header`);

    // (a) rushing, all neutral (served payload still lists them; frontend must drop them)
    let c = render('rushing_yards', [fixtureRow('rushing_yards', 59.5,
        { original: 60, adjusted: 60, changePct: 0, explanation: '', components: [NEUTRAL_WEATHER, RUSH_MATCHUP] })]);
    check(c && !c.anyAdjHeader, '(a) neutral rushing card shows adjustment columns');
    check(c && !c.chunk.includes('beta=0') && !c.chunk.includes('No weather data'), '(a) neutral text rendered');
    allAligned('(a)', c);

    // (b) receiving, matchup -1.8% only
    c = render('receiving_yards', [fixtureRow('receiving_yards', 49.5,
        { original: 50, adjusted: 49.1, changePct: -1.8, explanation: '',
          components: [NEUTRAL_WEATHER, { label: 'Matchup', pct: -1.8, text: 'vs CHI defense <scaled x0.5>' }] })]);
    check(c && c.showsAdj, '(b) receiving matchup card hides adjustment columns');
    check(c && c.chunk.includes('Matchup -1.8%'), '(b) matchup line missing');
    check(c && !c.chunk.includes('Weather'), '(b) neutral weather line shown');
    check(c && c.chunk.includes('vs CHI defense &lt;scaled x0.5&gt;'), '(b) component text not escaped');
    allAligned('(b)', c);

    // (c) rushing, weather +2.0%, matchup line must not show
    c = render('rushing_yards', [fixtureRow('rushing_yards', 59.5,
        { original: 60, adjusted: 61.2, changePct: 2.0, explanation: '',
          components: [{ label: 'Weather', pct: 2.0, text: 'Dome-like conditions' }, RUSH_MATCHUP] })]);
    check(c && c.showsAdj, '(c) rushing weather card hides adjustment columns');
    check(c && c.chunk.includes('Weather +2.0%'), '(c) weather line missing');
    check(c && !c.chunk.includes('Matchup') && !c.chunk.includes('beta=0'), '(c) rushing matchup line shown');
    allAligned('(c)', c);

    // (d) mixed card: one bookmaker row adjusted, one neutral -> columns on all rows
    c = render('receiving_yards', [
        fixtureRow('receiving_yards', 49.5, { original: 50, adjusted: 49.1, changePct: -1.8, explanation: '',
            components: [{ label: 'Matchup', pct: -1.8, text: 'vs CHI defense' }] }),
        fixtureRow('receiving_yards', 52.5, { original: 50, adjusted: 50, changePct: 0, explanation: '', components: [] }),
    ]);
    check(c && c.showsAdj, '(d) mixed card hides adjustment columns');
    check(c && c.rows.length === 2, '(d) expected 2 rows');
    allAligned('(d)', c);

    // v1 render follows the same rule
    const v1 = { version: 'v1' };
    const v1Row = adj => Object.assign(fixtureRow('rushing_yards', 59.5, adj), { probabilityOver: 55, probabilityUnder: 45 });
    c = render('rushing_yards', [v1Row({ original: 60, adjusted: 60, changePct: 0, explanation: '', components: [NEUTRAL_WEATHER, RUSH_MATCHUP] })], v1);
    check(c && !c.anyAdjHeader, '(v1 a) neutral card shows adjustment columns');
    allAligned('(v1 a)', c);
    c = render('rushing_yards', [v1Row({ original: 60, adjusted: 61.2, changePct: 2.0, explanation: '',
        components: [{ label: 'Weather', pct: 2.0, text: 'cold' }, RUSH_MATCHUP] })], v1);
    check(c && c.showsAdj && !c.chunk.includes('Matchup'), '(v1 c) weather card wrong');
    allAligned('(v1 c)', c);
}

async function main() {
    const t0 = Date.now();
    const page = await (await fetch(`${base}/`)).text();
    const data = await (await fetch(`${base}/generate-picks`)).json();
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    if (!data.success) throw new Error(`/generate-picks failed: ${data.error}`);
    if (!data.model || data.model.version !== 'v2') throw new Error(`served model is not v2: ${JSON.stringify(data.model)}`);
    const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
    const code = FUNCS.map(n => extractFunction(scripts, n)).join('\n\n');

    const container = { innerHTML: '' };
    const ctx = {
        console,
        document: {
            getElementById: id => (id === 'picks-container' ? container : null),
            querySelector: () => null,
            createElement: () => ({ innerHTML: '', querySelector: () => null }),
        },
        setTimeout: () => 0,
        renderPlayerGameInfo: () => {},
        __data: data,
    };
    vm.createContext(ctx);
    vm.runInContext(`
        var showUnflagged = false, lastPlayers = [], lastModel = null, allPicks = [], currentPage = 0;
        var dismissedPlayers = new Set();
        var PICKS_PER_PAGE = 10;
        ${code}
        lastPlayers = __data.players; lastModel = __data.model;
    `, ctx);

    const dataRows = [];
    for (const p of data.players) for (const r of p.stats) dataRows.push(Object.assign({ _key: `${p.player}|${r.stat}|${r.line}` }, r));
    const nFlagged = dataRows.filter(r => r.flagged).length;

    vm.runInContext('showUnflagged = false; renderPicks();', ctx);
    const htmlA = container.innerHTML;
    if (nFlagged === 0) {
        check(htmlA.includes(`No picks with an edge above ${data.model.edge_margin_pts} pts.`), 'zero-flag message with the margin missing');
    }
    const a = checkState('showUnflagged=false', htmlA, vm.runInContext("allPicks.join('')", ctx), data, dataRows, false);

    vm.runInContext('toggleUnflagged();', ctx);
    const htmlB = container.innerHTML;
    check(vm.runInContext('showUnflagged', ctx) === true, 'toggle did not switch showUnflagged');
    check(htmlB.includes('Hide unflagged markets'), 'toggle label not "Hide unflagged markets"');
    const b = checkState('showUnflagged=true', htmlB, vm.runInContext("allPicks.join('')", ctx), data, dataRows, true);

    // Adjustment columns on the served data (all cards)
    const realCards = cardTables(vm.runInContext("allPicks.join('')", ctx));
    const shown = realCards.filter(c => c.showsAdj).length;
    realCards.forEach((c, i) => {
        check(c.aligned, `served card ${i}: row cell count does not match the header`);
        check(c.showsAdj || !c.anyAdjHeader, `served card ${i}: only one adjustment column shown`);
        check(!c.chunk.includes('beta=0'), `served card ${i}: rushing beta=0 matchup line shown`);
        check(!c.chunk.includes('No weather data'), `served card ${i}: neutral weather line shown`);
    });
    checkFixtures(ctx);

    const styles = [...page.matchAll(/<style[^>]*>[\s\S]*?<\/style>/g)].map(m => m[0]).join('\n');
    const shot = a.cards ? htmlA : htmlB;
    const outDir = path.join(os.tmpdir(), 'nfl_backtest');
    fs.mkdirSync(outDir, { recursive: true });
    const outFile = path.join(outDir, 'picks_render.html');
    fs.writeFileSync(outFile, `<!DOCTYPE html><html><head><meta charset="utf-8">${styles}</head><body><div class="picks-section"><div id="picks-container">${(nFlagged === 0 ? htmlA : '') + shot}</div></div></body></html>`);

    console.log(`/generate-picks ${secs}s: ${data.players.length} players, ${dataRows.length} rows, ${nFlagged} flagged, model ${JSON.stringify(data.model)}`);
    console.log(`showUnflagged=false: ${a.cards} cards (${a.pageCards} on page 1), ${a.rows} rows; showUnflagged=true: ${b.cards} cards (${b.pageCards} on page 1), ${b.rows} rows`);
    console.log(`adjustment columns: shown on ${shown} of ${realCards.length} cards, hidden on ${realCards.length - shown}`);
    console.log(`render written to ${outFile}`);
    if (failures.length) {
        for (const f of failures) console.log(`FAIL: ${f}`);
        process.exit(1);
    }
    console.log('DOM CHECK PASSED');
}

main().catch(e => { console.log(`FAIL: ${e.message}`); process.exit(1); });
