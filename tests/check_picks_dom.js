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
    'renderPicks', 'toggleUnflagged', 'formatPicksFromJSON', 'formatPlayerStatSection', 'formatV2StatSection',
    'displayPicksPage'];

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

    const styles = [...page.matchAll(/<style[^>]*>[\s\S]*?<\/style>/g)].map(m => m[0]).join('\n');
    const shot = a.cards ? htmlA : htmlB;
    const outDir = path.join(os.tmpdir(), 'nfl_backtest');
    fs.mkdirSync(outDir, { recursive: true });
    const outFile = path.join(outDir, 'picks_render.html');
    fs.writeFileSync(outFile, `<!DOCTYPE html><html><head><meta charset="utf-8">${styles}</head><body><div class="picks-section"><div id="picks-container">${(nFlagged === 0 ? htmlA : '') + shot}</div></div></body></html>`);

    console.log(`/generate-picks ${secs}s: ${data.players.length} players, ${dataRows.length} rows, ${nFlagged} flagged, model ${JSON.stringify(data.model)}`);
    console.log(`showUnflagged=false: ${a.cards} cards (${a.pageCards} on page 1), ${a.rows} rows; showUnflagged=true: ${b.cards} cards (${b.pageCards} on page 1), ${b.rows} rows`);
    console.log(`render written to ${outFile}`);
    if (failures.length) {
        for (const f of failures) console.log(`FAIL: ${f}`);
        process.exit(1);
    }
    console.log('DOM CHECK PASSED');
}

main().catch(e => { console.log(`FAIL: ${e.message}`); process.exit(1); });
