/*
 * 외부 Duel Simulator 자동 조작기 (Phase 6-AX).
 *
 * 하는 일: 조작 계획(plan.json) 과 덱 시트(deck-sheet.html) 를 받아
 *   1) 덱 시트를 PNG 로 굽고
 *   2) 사이트에 올려 메인/엑스트라 장수를 맞춰 판에 적용하고
 *   3) 시작 패를 꺼낸 뒤 기록을 시작하고
 *   4) 계획의 조작을 하나씩 수행하며 **매번 화면의 History 줄로 확인**하고
 *   5) 기록을 끝내고, (--share 일 때만) 공유 URL 을 만든다.
 *
 * 🔴 사람이 쓰는 UI 그대로만 조작한다. 내부 엔드포인트를 부르지 않고,
 *    자바스크립트 번들을 뜯어보지 않는다.
 * 🔴 조작이 기대한 결과를 내지 않으면 **그 자리에서 멈춘다.** 확인 없이
 *    다시 시도해 두 번 움직이는 일을 만들지 않는다.
 * 🔴 --share 는 **되돌릴 수 없는 공개**다. 기본값은 꺼져 있다.
 *
 * 사용: node scripts/duel_simulator_driver.js <작업디렉터리> [--share] [--title "..."]
 * 결과: <작업디렉터리>/result.json  (stdout 에도 같은 JSON 한 줄)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const SITE = 'https://duel-simulator.miyauchidp.dev/';
const STEP_PAUSE = 700;          // 조작 사이의 틈 (사람 속도에 가깝게)

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const DIR = process.argv[2];
const WANT_SHARE = process.argv.includes('--share');
const TITLE = arg('--title', 'galatea opening line');
const HEADLESS = !process.argv.includes('--headed');

if (!DIR || !fs.existsSync(path.join(DIR, 'plan.json'))) {
  console.error('사용: node scripts/duel_simulator_driver.js <작업디렉터리> [--share]');
  process.exit(2);
}
const plan = JSON.parse(fs.readFileSync(path.join(DIR, 'plan.json'), 'utf8'));
const shot = n => path.join(DIR, `shot-${n}.png`);

const result = {
  site: SITE, share_requested: WANT_SHARE,
  stages: {}, operations: [], share_url: null,
  stopped_at: null, stopped_reason: null, notes: [],
};
function finish(code) {
  fs.writeFileSync(path.join(DIR, 'result.json'),
                   JSON.stringify(result, null, 1), 'utf8');
  console.log(JSON.stringify(result));
  process.exit(code);
}
function stop(where, why) { result.stopped_at = where; result.stopped_reason = why; }

// ---------------------------------------------------------------- 도구
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function setCount(page, id, value) {
  const el = page.locator('#' + id);
  await el.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.type(String(value), { delay: 60 });
  await page.keyboard.press('Tab');
  await sleep(350);
}

/** 판의 드롭 존들을 이름으로 묶는다. 🔴 이름은 사이트의 History 줄이 쓰는
 *  글자와 같아야 하고, 조작마다 그 줄로 다시 확인한다. */
async function zoneMap(page) {
  const zones = await page.evaluate(() =>
    [...document.querySelectorAll('[data-droppable]')].map(e => {
      const r = e.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               top: Math.round(r.y), left: Math.round(r.x),
               w: Math.round(r.width), h: Math.round(r.height),
               label: (e.innerText || '').trim() };
    }));
  const map = {};
  const labelled = { 'Free': 'Free', 'Grave': 'Grave', 'Banish': 'Banish',
                     'Hand': 'Hand', 'Extra Deck': 'Extra Deck', 'Deck': 'Deck' };
  const rest = [];
  for (const z of zones) {
    const name = Object.keys(labelled).find(k => z.label.startsWith(k + ' ('));
    if (name) { map[name] = z; } else { rest.push(z); }
  }
  // 이름표가 없는 칸들: 윗줄부터 EM 2칸 / 필드존+몬스터존 5 / ?+마함존 5
  const rows = {};
  rest.forEach(z => { (rows[z.top] = rows[z.top] || []).push(z); });
  const tops = Object.keys(rows).map(Number).sort((a, b) => a - b);
  tops.forEach((top, ri) => {
    const row = rows[top].sort((a, b) => a.left - b.left);
    if (ri === 0 && row.length === 2) {
      map['Extra Monster Zone1'] = row[0];
      map['Extra Monster Zone2'] = row[1];
    } else if (ri === 1) {
      if (row.length === 6) { map['Field Zone'] = row[0]; }
      row.slice(row.length === 6 ? 1 : 0).forEach((z, i) =>
        { map[`Monster Zone${i + 1}`] = z; });
    } else if (ri === 2) {
      row.slice(row.length === 6 ? 1 : 0).forEach((z, i) =>
        { map[`Spell & Trap Zone${i + 1}`] = z; });
    }
  });
  return map;
}

async function cardBox(page, slot) {
  return page.evaluate(slot => {
    const e = document.querySelector(`[data-card-id^="${slot}-"]`);
    if (!e) { return null; }
    const r = e.getBoundingClientRect();
    return { id: e.getAttribute('data-card-id'),
             x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
             w: Math.round(r.width), h: Math.round(r.height) };
  }, slot);
}

async function drag(page, from, to) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  for (let i = 1; i <= 16; i++) {
    await page.mouse.move(from.x + (to.x - from.x) * i / 16,
                          from.y + (to.y - from.y) * i / 16);
    await sleep(20);
  }
  await sleep(140);
  await page.mouse.up();
  await sleep(STEP_PAUSE);
}

/** 마지막 조작 이력 한 줄. 사이트가 "#n · You\n<출발> → <도착>" 으로 적는다. */
async function lastHistory(page) {
  return page.evaluate(() => {
    const m = (document.body.innerText || '').match(/#\d+ · [^\n]*\n[^\n]*/g);
    return m ? m[m.length - 1].replace(/\n/g, ' ') : '';
  });
}
async function historyCount(page) {
  return page.evaluate(() =>
    ((document.body.innerText || '').match(/#\d+ · /g) || []).length);
}
async function zoneCounts(page) {
  return page.evaluate(() => {
    const out = {};
    ((document.body.innerText || '')
      .match(/(Free|Grave|Banish|Hand|Extra Deck|Deck) \(\d+\)/g) || [])
      .forEach(s => { const m = s.match(/^(.*) \((\d+)\)$/); out[m[1]] = Number(m[2]); });
    return out;
  });
}

/** 우클릭 메뉴에서 항목 하나를 고른다. */
async function cardMenu(page, box, item) {
  await page.mouse.click(box.x, box.y, { button: 'right' });
  await sleep(600);
  const entry = page.getByRole('menuitem', { name: item, exact: true });
  if (await entry.count() === 0) {
    const any = page.locator(`[role=menuitem]:text-is("${item}")`);
    if (await any.count() === 0) { return false; }
    await any.first().click();
  } else {
    await entry.first().click();
  }
  await sleep(STEP_PAUSE);
  return true;
}

/** 묘지·제외는 쌓이는 자리라, 카드가 가려져 있으면 펼친다. */
async function expandPileIfNeeded(page, slot) {
  const box = await cardBox(page, slot);
  if (box && box.w > 0 && box.h > 0) { return box; }
  for (const label of ['Grave', 'Banish']) {
    const btn = page.locator(`button:has-text("${label} (")`);
    if (await btn.count()) { await btn.first().click(); await sleep(600); }
    const again = await cardBox(page, slot);
    if (again && again.w > 0) { return again; }
  }
  return await cardBox(page, slot);
}

// ---------------------------------------------------------------- 본체
(async () => {
  // 1) 덱 시트를 PNG 로
  const browser = await chromium.launch({ headless: HEADLESS });
  const sheetPage = await browser.newPage({ viewport: { width: 1169, height: 600 },
                                            deviceScaleFactor: 1 });
  await sheetPage.setContent(
    fs.readFileSync(path.join(DIR, 'deck-sheet.html'), 'utf8'), { waitUntil: 'load' });
  await sleep(400);
  const sheetPng = path.join(DIR, 'deck-sheet.png');
  await sheetPage.screenshot({ path: sheetPng, fullPage: true });
  await sheetPage.close();
  result.stages.deck_sheet = { file: sheetPng,
    main: plan.deck.main.length, extra: plan.deck.extra.length };

  const context = await browser.newContext({
    viewport: { width: 1560, height: 1100 }, deviceScaleFactor: 1,
    recordVideo: { dir: path.join(DIR, 'video'), size: { width: 1560, height: 1100 } },
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e.message).slice(0, 160)));

  try {
    // 2) 덱 이미지 올리기
    await page.goto(SITE, { waitUntil: 'networkidle', timeout: 90000 });
    await sleep(2500);
    await page.setInputFiles('input[type=file]', sheetPng);
    await sleep(9000);
    const detected = await page.evaluate(() => {
      const t = document.body.innerText;
      const m = t.match(/Detected Deck Configuration\n([^\n]*)/);
      return m ? m[1] : '';
    });
    result.stages.upload = { auto_detected: detected };

    await page.locator('input[type=checkbox]').first().check();
    await sleep(600);
    await setCount(page, 'mainDeck', plan.deck.main.length);
    await setCount(page, 'extraDeck', plan.deck.extra.length);
    await setCount(page, 'sideDeck', 0);
    await page.getByRole('button', { name: /Apply deck to field/i }).click();
    await sleep(8000);

    let counts = await zoneCounts(page);
    result.stages.applied = counts;
    if (counts['Deck'] !== plan.deck.main.length ||
        counts['Extra Deck'] !== plan.deck.extra.length) {
      stop('apply', `판에 들어간 장수가 다릅니다: ${JSON.stringify(counts)}`);
      await page.screenshot({ path: shot('apply-fail') });
      await context.close(); await browser.close(); finish(1);
    }
    await page.screenshot({ path: shot('01-applied') });

    const zones = await zoneMap(page);
    result.stages.zones = Object.fromEntries(
      Object.entries(zones).map(([k, v]) => [k, { x: v.x, y: v.y }]));
    for (const need of ['Hand', 'Grave', 'Banish', 'Deck', 'Extra Deck']) {
      if (!zones[need]) {
        stop('zones', `판에서 ${need} 칸을 찾지 못했습니다`);
        await context.close(); await browser.close(); finish(1);
      }
    }

    // 3) 시작 패 — 기록 전에 끝낸다
    for (const op of plan.setup) {
      const box = await cardBox(page, op.card);
      if (!box) { stop('setup', `${op.card} 를 판에서 찾지 못했습니다`); break; }
      await drag(page, box, zones['Hand']);
    }
    if (result.stopped_at) {
      await page.screenshot({ path: shot('setup-fail') });
      await context.close(); await browser.close(); finish(1);
    }
    counts = await zoneCounts(page);
    result.stages.opening = counts;
    if (counts['Hand'] !== plan.setup.length) {
      stop('setup', `시작 패가 ${counts['Hand']}장입니다 (기대 ${plan.setup.length})`);
      await page.screenshot({ path: shot('setup-fail') });
      await context.close(); await browser.close(); finish(1);
    }
    await page.screenshot({ path: shot('02-opening') });

    // 4) 기록 시작
    await page.getByRole('button', { name: /Start Recording/i }).click();
    await sleep(1500);
    result.stages.recording_started =
      await page.evaluate(() => /Recording/.test(document.body.innerText));

    // 5) 조작
    let before = await historyCount(page);
    for (const op of plan.operations) {
      const entry = { n: op.n, op: op.op, card: op.card, expect: op.expect,
                      why: op.why, basis: op.basis };
      let box = await expandPileIfNeeded(page, op.card);
      if (!box) { entry.ok = false; entry.saw = '카드를 찾지 못했습니다'; }
      else if (op.op === 'move') {
        const target = zones[op.to];
        if (!target) { entry.ok = false; entry.saw = `존 ${op.to} 을 찾지 못했습니다`; }
        else {
          await drag(page, box, target);
          const line = await lastHistory(page);
          const after = await historyCount(page);
          entry.saw = line;
          // 🔴 **도착지로만 확인한다** — 출발지 칸 번호는 기록에 없을 수 있다.
          entry.ok = after > before && line.includes('→ ' + op.to);
          before = after;
        }
      } else if (op.op === 'activate' || op.op === 'target') {
        const item = op.op === 'activate' ? 'Activate Effect' : 'Target';
        const picked = await cardMenu(page, box, item);
        const line = await lastHistory(page);
        const after = await historyCount(page);
        entry.saw = picked ? line : `메뉴에 ${item} 이 없습니다`;
        entry.ok = picked && after > before;
        before = after;
      } else { entry.ok = false; entry.saw = `모르는 조작 ${op.op}`; }
      result.operations.push(entry);
      if (!entry.ok) {
        stop(`operation#${op.n}`,
             `${op.op} ${op.card} — 기대 "${op.expect}", 화면 "${entry.saw}"`);
        await page.screenshot({ path: shot(`op-${op.n}-fail`) });
        break;
      }
      if (op.n === Math.ceil(plan.operations.length / 2)) {
        await page.screenshot({ path: shot('03-midway') });
      }
    }
    if (result.stopped_at) {
      result.notes.push('🔴 중간에 멈췄습니다 — 기록을 끝내지 않았고 공유도 하지 않았습니다.');
      await context.close(); await browser.close(); finish(1);
    }
    await page.screenshot({ path: shot('04-final-board') });

    // 6) 최종 상태 확인 — 계획의 기대와 맞춘다
    counts = await zoneCounts(page);
    const whereIs = await page.evaluate((named) => {
      const zs = [...document.querySelectorAll('[data-droppable]')].map(e => {
        const r = e.getBoundingClientRect();
        const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
        // 🔴 이름표가 없는 칸은 앞서 만든 이름 지도에서 **좌표로** 찾는다.
        const hit = Object.entries(named).find(([, p]) =>
          Math.abs(p.x - cx) < 4 && Math.abs(p.y - cy) < 4);
        return { label: hit ? hit[0] : (e.innerText || '').trim(),
                 x: r.x, y: r.y, w: r.width, h: r.height };
      });
      const out = {};
      document.querySelectorAll('[data-card-id]').forEach(e => {
        const r = e.getBoundingClientRect();
        const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
        const hit = zs.filter(z => cx >= z.x && cx <= z.x + z.w && cy >= z.y && cy <= z.y + z.h)
                      .sort((a, b) => a.w * a.h - b.w * b.h)[0];
        const slot = e.getAttribute('data-card-id').split('-').slice(0, 2).join('-');
        out[slot] = hit ? (hit.label.split(' (')[0] || 'zone@' + Math.round(hit.x) + ',' + Math.round(hit.y))
                        : 'off-board';
      });
      return out;
    }, result.stages.zones);
    const checks = [];
    for (const [zone, want] of Object.entries(plan.expect_final)) {
      if (counts[zone] !== undefined) {
        checks.push({ zone, want: want.count, saw: counts[zone],
                      ok: counts[zone] === want.count });
      } else {
        const saw = want.slots.map(s => whereIs[s]);
        checks.push({ zone, want: want.slots, saw,
                      ok: want.slots.length > 0 && saw.every(v => v !== undefined) });
      }
    }
    result.stages.final = { counts, checks, card_zones: whereIs };
    result.stages.final.all_ok = checks.every(c => c.ok);

    // 7) 기록 종료
    await page.getByRole('button', { name: /Stop Recording/i }).click();
    await sleep(2500);
    result.stages.recording_stopped = true;
    await page.screenshot({ path: shot('05-recorded') });

    // 8) 공유 — 🔴 **되돌릴 수 없는 공개**. 요청했을 때만 한다.
    if (!WANT_SHARE) {
      result.notes.push('공유하지 않았습니다 (--share 를 주지 않았습니다). '
                        + '기록은 이 브라우저 세션에만 있습니다.');
    } else if (!result.stages.final.all_ok) {
      result.notes.push('🔴 최종 상태가 기대와 달라서 공유하지 않았습니다.');
    } else {
      await page.getByRole('button', { name: /^Share$/i }).first().click();
      await sleep(1800);
      const titleBox = page.locator('input[type=text]').first();
      if (await titleBox.count()) {
        await titleBox.click();
        await page.keyboard.type(TITLE, { delay: 25 });
        await sleep(400);
      }
      await page.getByRole('button', { name: /Create share URL/i }).click();
      await sleep(9000);
      const url = await page.evaluate(() => {
        const m = (document.body.innerText || '')
          .match(/https?:\/\/[^\s"']*\/replay\/[A-Za-z0-9_-]+/);
        if (m) { return m[0]; }
        const input = [...document.querySelectorAll('input')]
          .map(e => e.value).find(v => v && v.includes('/replay/'));
        return input || null;
      });
      result.share_url = url;
      await page.screenshot({ path: shot('06-share') });
      if (!url) { result.notes.push('🔴 공유 URL 을 화면에서 읽지 못했습니다.'); }
    }
  } catch (error) {
    stop(result.stopped_at || 'exception', String(error.message).slice(0, 300));
    try { await page.screenshot({ path: shot('exception') }); } catch (_) {}
  }

  if (pageErrors.length) { result.notes.push('페이지 오류: ' + pageErrors.slice(0, 3).join(' / ')); }
  await context.close();
  await browser.close();
  finish(result.stopped_at ? 1 : 0);
})();
