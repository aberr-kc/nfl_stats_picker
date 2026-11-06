// Served-page check for the refresh panel (no npm packages).
//   node tests/check_refresh_dom.js http://127.0.0.1:8011
// Fetches / from the running server, checks the three step buttons and status
// lines, then runs the panel functions from the served index.html in a vm with
// a stub DOM / fetch / confirm. Only GET /refresh/odds/preview (free) is ever
// forwarded to the real server; every POST is answered by a stub, so no Odds
// API credits can be spent.
'use strict';
const vm = require('vm');

const base = (process.argv[2] || 'http://127.0.0.1:8011').replace(/\/$/, '');
const FUNCS = ['escapeHtml', 'stepButtons', 'refreshHeaders', 'formatLastRun', 'renderRefreshStatus',
    'setRefreshButtonsDisabled', 'showRefreshError', 'clearRefreshError', 'describeHttpError',
    'buildOddsConfirmText', 'startRefresh', 'pollRefreshStatus', 'loadRefreshStatus', 'fetchOdds', 'refreshStats'];
const IDS = ['refreshStats', 'fetchOdds', 'generatePicks', 'status-stats', 'status-odds', 'status-picks', 'refresh-message'];
const LABELS = { refreshStats: '1. Refresh stats (free)', fetchOdds: '2. Fetch odds (uses credits)', generatePicks: '3. Generate picks' };

const failures = [];
function check(cond, msg) {
    if (!cond) failures.push(msg);
}

function extractFunction(src, name) {
    let start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`function ${name} not found in served index.html`);
    if (src.slice(start - 6, start) === 'async ') start -= 6;  // keep async functions async
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

function fakeRes(status, body) {
    return { status, ok: status >= 200 && status < 300, json: async () => body };
}

async function settle() {
    for (let i = 0; i < 100; i++) await new Promise(r => setImmediate(r));
}

function makeContext(code) {
    const els = {};
    for (const id of IDS) els[id] = { id, innerHTML: '', textContent: '', disabled: false, style: {} };
    const state = { calls: [], confirms: [], handler: null, timeouts: 0 };
    const ctx = {
        console, JSON, Date, Promise, String, Object,
        document: { getElementById: id => els[id] || null },
        window: { confirm: text => { state.confirms.push(text); return state.confirmAnswer; } },
        setTimeout: fn => { if (++state.timeouts < 200) Promise.resolve().then(fn); return 0; },
        fetch: async (url, opts = {}) => {
            const call = { url, method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body };
            state.calls.push(call);
            return state.handler(call);
        },
    };
    vm.createContext(ctx);
    vm.runInContext(`let refreshPollingJob = null;\n${code}`, ctx);
    return { ctx, els, state, run: src => vm.runInContext(src, ctx) };
}

async function main() {
    const page = await (await fetch(`${base}/`)).text();
    for (const [id, label] of Object.entries(LABELS)) {
        const m = page.match(new RegExp(`<button id="${id}"[^>]*>([^<]*)</button>`));
        check(!!m, `button #${id} missing`);
        if (m) check(m[1] === label, `button #${id} label is "${m[1]}", expected "${label}"`);
    }
    for (const id of ['status-stats', 'status-odds', 'status-picks', 'refresh-message']) {
        check(page.includes(`id="${id}"`), `#${id} missing`);
    }
    const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
    const code = FUNCS.map(n => extractFunction(scripts, n)).join('\n\n');

    // (a) real free preview; user cancels the confirm -> no POST
    {
        const t = makeContext(code);
        t.state.confirmAnswer = false;
        let preview = null;
        t.state.handler = async call => {
            if (call.url === '/refresh/odds/preview' && call.method === 'GET') {
                const res = await fetch(`${base}${call.url}`, { headers: call.headers });
                preview = await res.clone().json();
                return res;
            }
            return fakeRes(500, { error: 'unexpected call in scenario a' });
        };
        await t.run('fetchOdds()');
        await settle();
        const posts = t.state.calls.filter(c => c.method === 'POST');
        check(posts.length === 0, `(a) ${posts.length} POST(s) sent after cancelling`);
        const noKeys = !!(preview && preview.error === 'no_api_keys');  // fresh clone without .env
        check(noKeys || (preview && typeof preview.game_count === 'number'), `(a) preview failed: ${JSON.stringify(preview)}`);
        if (noKeys) {
            check(t.state.confirms.length === 0, '(a) confirm shown without API keys');
            check(t.els['refresh-message'].textContent.includes('No Odds API keys configured'),
                `(a) no-keys message missing: ${JSON.stringify(t.els['refresh-message'].textContent)}`);
            console.log(`(a) no API keys: page shows ${JSON.stringify(t.els['refresh-message'].textContent)}`);
        } else if (preview && preview.game_count > 0) {
            check(t.state.confirms.length === 1, `(a) confirm shown ${t.state.confirms.length} times`);
            const text = t.state.confirms[0] || '';
            check(text.includes(`${preview.game_count} upcoming games`), '(a) confirm lacks the game count');
            check(text.includes(`up to ${preview.estimated_credits} credits`), '(a) confirm lacks the estimated credits');
            check(text.includes('Remaining quota'), '(a) confirm lacks the remaining quota line');
        } else if (preview) {
            check(t.state.confirms.length === 0, '(a) confirm shown with zero games');
            check(t.els['refresh-message'].textContent.includes('nothing to fetch'), '(a) zero-games message missing');
        }
        check(!t.els.fetchOdds.disabled && !t.els.refreshStats.disabled && !t.els.generatePicks.disabled,
            '(a) buttons not re-enabled');
        console.log(`(a) real preview: ${preview ? preview.game_count : '?'} games, ` +
            `${preview ? preview.estimated_credits : '?'} est. credits, quota ${JSON.stringify(preview && preview.quota && preview.quota.total_remaining)}; ` +
            `confirm shown ${t.state.confirms.length}x; POSTs ${posts.length}`);
        if (t.state.confirms[0]) console.log('    confirm text: ' + JSON.stringify(t.state.confirms[0]));
    }

    // (b) fake preview, user confirms, fake POST 202, status running -> succeeded
    {
        const t = makeContext(code);
        t.state.confirmAnswer = true;
        const preview = { game_count: 2, days_ahead: 4, estimated_credits: 18, markets: 9, regions: 1,
            games: [], quota: { total_remaining: 10, source: 'live' }, enough_quota: false };
        let statusCalls = 0;
        let disabledDuringPoll = null;
        t.state.handler = async call => {
            if (call.url === '/refresh/odds/preview') return fakeRes(200, preview);
            if (call.url === '/refresh/odds' && call.method === 'POST') return fakeRes(202, { job_id: 'j1', step: 'odds', status: 'running' });
            if (call.url === '/refresh/status') {
                statusCalls++;
                if (statusCalls === 2) disabledDuringPoll = t.els.fetchOdds.disabled && t.els.refreshStats.disabled && t.els.generatePicks.disabled;
                if (statusCalls < 3) return fakeRes(200, { running: true, job: { job_id: 'j1', step: 'odds', status: 'running' }, last_runs: {} });
                return fakeRes(200, { running: false, job: { job_id: 'j1', step: 'odds', status: 'succeeded' },
                    last_runs: { odds: { finished_at: '2026-11-05T12:00:00+00:00', status: 'succeeded', summary: '2/2 games, 18 credits, 0 left', warnings: [] } } });
            }
            return fakeRes(500, {});
        };
        await t.run('fetchOdds()');
        await settle();
        const post = t.state.calls.find(c => c.method === 'POST');
        check(!!post && post.url === '/refresh/odds', '(b) POST /refresh/odds not sent');
        if (post) {
            check(post.headers['X-NFL-Refresh'] === '1', '(b) POST lacks X-NFL-Refresh: 1');
            check(post.body === '{"confirm_games":2}', `(b) POST body ${post.body}`);
        }
        check((t.state.confirms[0] || '').includes('WARNING: estimate exceeds remaining quota.'), '(b) quota WARNING line missing');
        check((t.state.confirms[0] || '').includes('Remaining quota: 10 credits (live).'), '(b) remaining quota line wrong');
        const preIdx = t.state.calls.findIndex(c => c.url === '/refresh/odds/preview');
        const postIdx = t.state.calls.findIndex(c => c.method === 'POST');
        check(preIdx >= 0 && postIdx > preIdx, '(b) POST not after preview');
        check(disabledDuringPoll === true, `(b) buttons not disabled while polling (${disabledDuringPoll})`);
        check(!t.els.fetchOdds.disabled && t.els.fetchOdds.textContent === LABELS.fetchOdds, '(b) odds button not reset after job');
        check(t.els['status-odds'].innerHTML.includes('2/2 games, 18 credits, 0 left'), '(b) status-odds lacks the summary');
        check(t.els['refresh-message'].textContent === '', '(b) error shown after success');
        console.log(`(b) confirmed fake flow: POST ${post && post.body}, ${statusCalls} status polls, status-odds="${t.els['status-odds'].innerHTML}"`);
    }

    // (c) 409 and 403 messages
    {
        const t = makeContext(code);
        t.state.handler = async call => {
            if (call.method === 'POST') return fakeRes(409, { error: 'busy', running_step: 'stats', job_id: 'j9' });
            return fakeRes(200, { running: true, job: { job_id: 'j9', step: 'stats', status: 'running' }, last_runs: {} });
        };
        await t.run('startRefresh("stats", "/refresh/stats")');
        check(t.els['refresh-message'].textContent.includes('already running'), `(c) 409 message: "${t.els['refresh-message'].textContent}"`);
        check(t.els['refresh-message'].textContent.includes('stats'), '(c) 409 message lacks the running step');
        await settle();
        const t2 = makeContext(code);
        t2.state.handler = async () => fakeRes(403, { error: 'forbidden', message: 'x' });
        await t2.run('refreshStats()');
        await settle();
        check(t2.els['refresh-message'].textContent.includes('only allowed from the computer running the server'),
            `(c) 403 message: "${t2.els['refresh-message'].textContent}"`);
        check(!t2.els.refreshStats.disabled, '(c) buttons not re-enabled after 403');
        console.log(`(c) 409 -> "${t.els['refresh-message'].textContent}"; 403 -> "${t2.els['refresh-message'].textContent}"`);
    }

    // (d) formatLastRun
    {
        const t = makeContext(code);
        check(t.run('formatLastRun(null)') === 'Never run', '(d) formatLastRun(null)');
        const html = t.run(`formatLastRun({finished_at: '2026-11-05T12:00:00+00:00', status: 'failed', error: '<script>x</script>', warnings: []})`);
        check(html.includes('✗') && html.includes('&lt;script&gt;') && !html.includes('<script>'), `(d) failed run html: ${html}`);
    }

    if (failures.length) {
        for (const f of failures) console.log(`FAIL: ${f}`);
        process.exit(1);
    }
    console.log('REFRESH DOM CHECK PASSED');
}

main().catch(e => { console.log(`FAIL: ${e.message}`); process.exit(1); });
