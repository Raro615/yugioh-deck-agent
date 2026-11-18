/*
 * 외부 Duel Simulator 자동 조작기 (Phase 6-AX · 6-AY 에서 검증 강화).
 *
 * 하는 일: 조작 계획(plan.json) 과 덱 시트(deck-sheet.html) 를 받아
 *   1) 덱 시트를 PNG 로 굽고
 *   2) 사이트에 올려 메인/엑스트라 장수를 맞춰 판에 적용하고
 *   3) 시작 패를 꺼낸 뒤 기록을 시작하고
 *   4) 계획의 조작을 하나씩 수행하며 **매번 카드 개체까지 확인**하고
 *   5) 최종 판을 **존별 카드 집합**으로 대조하고
 *   6) 기록을 끝내고, (--share 일 때만, 그리고 검증을 통과했을 때만)
 *      공유 URL 을 만든다.
 *
 * 🔴 사람이 쓰는 UI 그대로만 조작한다. 내부 엔드포인트를 부르지 않는다.
 * 🔴 조작이 기대한 결과를 내지 않으면 **그 자리에서 멈춘다.** 확인 없이
 *    다시 시도해 두 번 움직이거나 두 번 공유하는 일을 만들지 않는다.
 * 🔴 --share 는 **되돌릴 수 없는 공개**다. 기본값은 꺼져 있다.
 *
 * 개체를 어떻게 묶는가 (6-AY)
 * ---------------------------
 * 판의 카드는 ``data-card-id``(``main-11-…``) 로 식별한다 — 이동해도
 * 바뀌지 않는다. 조작 이력(History) 의 각 줄에는 **그 조작에 쓰인 카드의
 * 썸네일**이 붙고, 그 ``src`` 는 판 위 카드의 ``src`` 와 **바이트 단위로
 * 같다**(실측). 그래서 "이 줄이 그 카드의 줄인가" 를 확인할 수 있다.
 * 같은 그림이 둘 이상이면 **모호하다고 적고** 넘어가지, 맞았다고 하지
 * 않는다.
 *
 * 사용: node scripts/duel_simulator_driver.js <작업디렉터리>
 *          [--run-id <id>] [--share] [--title "..."] [--headed]
 * 결과: <작업디렉터리>/result.json  (stdout 에도 같은 JSON 한 줄)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
//: 🔴 **판정부는 따로 있다** (6-AY) — 브라우저 없이도 시험이 돌릴 수 있게.
const { identityOf, compareFinal, decideMove, decideMenu,
        movedBetween } =
  require(path.join(__dirname, 'duel_simulator_verify.js'));
//: 🔴 **손가락은 따로 산다** (Phase 6-BH) — 실제 사이트에서 조작 하나를
//: 확인하는 스크립트가 **이 함수들을 그대로** 쓴다.
const { drag, cardMenu, armFaceDown, readPosition } =
  require(path.join(__dirname, 'duel_simulator_ops.js'));

const SITE = 'https://duel-simulator.miyauchidp.dev/';
const STEP_PAUSE = 700;

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const DIR = process.argv[2];
const WANT_SHARE = process.argv.includes('--share');
const TITLE = arg('--title', 'galatea opening line');
const RUN_ID = arg('--run-id', '');
//: 🔴 **실제 덱 이미지 모드** — 등록해 둔 사용자의 Neuron 이미지를 올린다.
//: 주지 않으면 글자 자리표시 시트를 구워서 올린다 (기존 모드).
const DECK_IMAGE = arg('--deck-image', '');
const HEADLESS = !process.argv.includes('--headed');

if (!DIR || !fs.existsSync(path.join(DIR, 'plan.json'))) {
  console.error('사용: node scripts/duel_simulator_driver.js <작업디렉터리> [--run-id <id>] [--share]');
  process.exit(2);
}
const plan = JSON.parse(fs.readFileSync(path.join(DIR, 'plan.json'), 'utf8'));
const shot = n => path.join(DIR, `shot-${n}.png`);

const result = {
  //: 🔴 **이 결과가 어느 요청의 것인가.** 부르는 쪽이 자기 실행 ID 와
  //: 맞춰 보고, 다르면 남아 있던 옛 결과로 보고 버린다.
  run_id: RUN_ID,
  plan_run_id: plan.run_id || null,
  //: 🔴 **계획한 조작 수**. 중간에 멈추면 실제로 한 수와 달라지고,
  //: 부르는 쪽이 둘을 맞춰 "다 했는가" 를 판정한다 (6-AZ).
  operations_planned: (plan.operations || []).length,
  deck_image_mode: DECK_IMAGE ? 'registered' : 'placeholder-sheet',
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

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ------------------------------------------------------------ 입력 보조
async function setCount(page, id, value) {
  const el = page.locator('#' + id);
  await el.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.type(String(value), { delay: 60 });
  await page.keyboard.press('Tab');
  await sleep(350);
}

/** 판의 드롭 존을 **이름**으로 묶는다. 이름은 History 줄의 글자와 같다. */
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
  const named = ['Free', 'Grave', 'Banish', 'Hand', 'Extra Deck', 'Deck'];
  const rest = [];
  for (const z of zones) {
    const name = named.find(k => z.label.startsWith(k + ' ('));
    if (name) { map[name] = z; } else { rest.push(z); }
  }
  const rows = {};
  rest.forEach(z => { (rows[z.top] = rows[z.top] || []).push(z); });
  Object.keys(rows).map(Number).sort((a, b) => a - b).forEach((top, ri) => {
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

// ------------------------------------------------------- 판을 **읽는다**
/**
 * 지금 판에 있는 모든 카드를 **자리별로** 읽는다.
 *
 * 🔴 **읽을 수 없는 상태를 성공으로 치지 않는다.** 크기가 0이거나 어느
 *    칸에도 들어가지 않거나 같은 자리가 두 번 나오면 ``problems`` 에
 *    남고, 부르는 쪽이 그것만으로 실패 처리한다.
 */
async function observeBoard(page, zones) {
  const rects = Object.fromEntries(Object.entries(zones).map(
    ([k, z]) => [k, { x: z.left, y: z.top, w: z.w, h: z.h }]));
  return page.evaluate(rects => {
    const bySlot = {}, byZone = {}, problems = [], srcOf = {};
    const seen = {};
    document.querySelectorAll('[data-card-id]').forEach(e => {
      const id = e.getAttribute('data-card-id');
      const slot = id.split('-').slice(0, 2).join('-');
      // 같은 자리가 여러 요소로 그려진다 (감싸는 div 들) — 가장 안쪽 하나만.
      if (e.querySelector('[data-card-id]')) { return; }
      const r = e.getBoundingClientRect();
      if (seen[slot]) {
        problems.push(`${slot}: 같은 자리가 화면에 두 번 있습니다`);
        return;
      }
      seen[slot] = true;
      if (r.width < 2 || r.height < 2) {
        problems.push(`${slot}: 크기가 0 입니다 (가려졌거나 그려지지 않았습니다)`);
        return;
      }
      const img = e.querySelector('img');
      if (img) { srcOf[slot] = img.src; }
      const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
      const hits = Object.entries(rects).filter(([, z]) =>
        cx >= z.x && cx <= z.x + z.w && cy >= z.y && cy <= z.y + z.h);
      if (!hits.length) {
        problems.push(`${slot}: 어느 칸에도 들어가지 않습니다`);
        return;
      }
      hits.sort((a, b) => a[1].w * a[1].h - b[1].w * b[1].h);
      const zone = hits[0][0];
      bySlot[slot] = zone;
      (byZone[zone] = byZone[zone] || []).push(slot);
    });
    return { bySlot, byZone, problems, srcOf };
  }, rects);
}

/** 화면의 장수 표시 — 좌표로 읽은 집합과 **교차 확인**하는 데 쓴다. */
async function zoneCounts(page) {
  return page.evaluate(() => {
    const out = {};
    ((document.body.innerText || '')
      .match(/(Free|Grave|Banish|Hand|Extra Deck|Deck) \(\d+\)/g) || [])
      .forEach(s => { const m = s.match(/^(.*) \((\d+)\)$/); out[m[1]] = Number(m[2]); });
    return out;
  });
}

/** 조작 이력의 줄들 — 각 줄의 **썸네일 src** 까지 읽는다. */
async function historyRows(page) {
  return page.evaluate(() => {
    const all = [...document.querySelectorAll('*')].filter(
      e => /#\d+ · /.test(e.innerText || '') && e.querySelector('img'));
    // 가장 안쪽(자식 중에 같은 모양이 없는) 요소만 남긴다.
    const leaves = all.filter(e => !all.some(o => o !== e && e.contains(o)));
    return leaves.map(e => ({
      text: (e.innerText || '').replace(/\n/g, ' ').trim(),
      srcs: [...e.querySelectorAll('img')].map(i => i.src),
    }));
  });
}

// ------------------------------------------------------------- 조작
async function cardBox(page, slot) {
  return page.evaluate(slot => {
    const nodes = [...document.querySelectorAll(`[data-card-id^="${slot}-"]`)]
      .filter(e => !e.querySelector('[data-card-id]'));
    const e = nodes[0];
    if (!e) { return null; }
    const r = e.getBoundingClientRect();
    return { id: e.getAttribute('data-card-id'),
             x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
             w: Math.round(r.width), h: Math.round(r.height),
             src: (e.querySelector('img') || {}).src || null };
  }, slot);
}

/** 🔴 **그 지점에 있는 카드가 누구인가** — 개체 확정의 1차 근거다. */
async function cardAtPoint(page, x, y) {
  return page.evaluate(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    if (!el) { return null; }
    const card = el.closest('[data-card-id]');
    if (!card) { return null; }
    return card.getAttribute('data-card-id').split('-').slice(0, 2).join('-');
  }, [x, y]);
}

/** 카드 상세 패널이 말하는 칸 (읽히면 보조 근거로 쓴다). */
async function panelZone(page) {
  return page.evaluate(() => {
    const text = document.body.innerText || '';
    const m = text.match(/Card details\s+([^\n]*)/);
    if (!m) { return null; }
    const said = m[1].trim();
    return /Operate a card/.test(said) ? null : said;
  });
}







/** 관측한 자리 이름을 **계획의 이름**으로 되돌린다 (토큰, Phase 6-BH). */
function relabelBoard(board, reverse) {
  const name = slot => reverse[slot] || slot;
  const bySlot = {}, byZone = {}, srcOf = {};
  Object.entries(board.bySlot || {}).forEach(([slot, zone]) => {
    bySlot[name(slot)] = zone;
  });
  Object.entries(board.byZone || {}).forEach(([zone, slots]) => {
    byZone[zone] = slots.map(name);
  });
  Object.entries(board.srcOf || {}).forEach(([slot, src]) => {
    srcOf[name(slot)] = src;
  });
  return { bySlot, byZone, srcOf, problems: (board.problems || []).slice() };
}

async function expandPileIfNeeded(page, slot) {
  const box = await cardBox(page, slot);
  if (box && box.w > 1 && box.h > 1) { return box; }
  for (const label of ['Grave', 'Banish']) {
    const btn = page.locator(`button:has-text("${label} (")`);
    if (await btn.count()) { await btn.first().click(); await sleep(600); }
    const again = await cardBox(page, slot);
    if (again && again.w > 1) { return again; }
  }
  return await cardBox(page, slot);
}

// ---------------------------------------------------------------- 본체
(async () => {
  const browser = await chromium.launch({ headless: HEADLESS });
  let sheetPng;
  if (DECK_IMAGE) {
    //: 🔴 **사용자가 등록한 이미지를 그대로 올린다.** 굽지 않는다.
    if (!fs.existsSync(DECK_IMAGE)) {
      stop('deck-image', `등록된 덱 이미지를 찾지 못했습니다: ${DECK_IMAGE}`);
      await browser.close(); finish(1);
    }
    sheetPng = DECK_IMAGE;
    result.stages.deck_sheet = { file: sheetPng, source: 'registered',
      main: plan.deck.main.length, extra: plan.deck.extra.length };
  } else {
    const sheetPage = await browser.newPage({
      viewport: { width: 1169, height: 600 }, deviceScaleFactor: 1 });
    await sheetPage.setContent(
      fs.readFileSync(path.join(DIR, 'deck-sheet.html'), 'utf8'),
      { waitUntil: 'load' });
    await sleep(400);
    sheetPng = path.join(DIR, 'deck-sheet.png');
    await sheetPage.screenshot({ path: sheetPng, fullPage: true });
    await sheetPage.close();
    result.stages.deck_sheet = { file: sheetPng, source: 'placeholder-sheet',
      main: plan.deck.main.length, extra: plan.deck.extra.length };
  }

  const context = await browser.newContext({
    viewport: { width: 1560, height: 1100 }, deviceScaleFactor: 1,
    recordVideo: { dir: path.join(DIR, 'video'), size: { width: 1560, height: 1100 } },
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e.message).slice(0, 160)));

  try {
    await page.goto(SITE, { waitUntil: 'networkidle', timeout: 90000 });
    await sleep(2500);
    await page.setInputFiles('input[type=file]', sheetPng);
    await sleep(9000);
    result.stages.upload = { auto_detected: await page.evaluate(() => {
      const m = (document.body.innerText).match(/Detected Deck Configuration\n([^\n]*)/);
      return m ? m[1] : '';
    }) };

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
    const missingZone = Object.keys(plan.expect_final)
      .filter(name => !zones[name]);
    if (missingZone.length) {
      stop('zones', `판에서 칸을 찾지 못했습니다: ${missingZone.join(', ')}`);
      await context.close(); await browser.close(); finish(1);
    }

    for (const op of plan.setup) {
      const box = await cardBox(page, op.card);
      if (!box) { stop('setup', `${op.card} 를 판에서 찾지 못했습니다`); break; }
      await drag(page, box, zones['Hand']);
    }
    if (!result.stopped_at) {
      counts = await zoneCounts(page);
      result.stages.opening = counts;
      const seen = await observeBoard(page, zones);
      const hand = (seen.byZone['Hand'] || []).slice().sort();
      const want = plan.setup.map(op => op.card).slice().sort();
      if (JSON.stringify(hand) !== JSON.stringify(want)) {
        stop('setup', `시작 패가 다릅니다 — 기대 ${JSON.stringify(want)} / `
                      + `화면 ${JSON.stringify(hand)}`);
      }
    }
    if (result.stopped_at) {
      await page.screenshot({ path: shot('setup-fail') });
      await context.close(); await browser.close(); finish(1);
    }
    await page.screenshot({ path: shot('02-opening') });

    await page.getByRole('button', { name: /Start Recording/i }).click();
    await sleep(1500);
    result.stages.recording_started =
      await page.evaluate(() => /Recording/.test(document.body.innerText));

    let rows = await historyRows(page);
    //: 🔴 **토큰은 계획의 이름과 사이트의 이름이 다르다** (Phase 6-BH).
    //: 계획은 ``token-<개체번호>`` 를 쓰고 사이트는 ``Generate Token`` 이
    //: 만든 **제 id** 를 쓴다. 둘을 이 두 표로 잇고, 관측은 **계획의
    //: 이름으로 되돌려** 본다 — 그래야 ``expect_final`` 과 맞춰진다.
    const alias = {};      // 계획 이름 → 사이트 이름
    const reverse = {};    // 사이트 이름 → 계획 이름
    const siteName = slot => alias[slot] || slot;
    const look = async () => relabelBoard(await observeBoard(page, zones), reverse);
    let board = await look();
    for (const op of plan.operations) {
      const entry = { n: op.n, op: op.op, card: op.card, expect: op.expect,
                      why: op.why, basis: op.basis };
      if (op.op === 'generate_token') {
        //: 🔴 **집을 카드가 아직 없다** — 만드는 조작이다.
        const before = await look();
        await page.getByRole('button', { name: /^More$/i }).first().click();
        await sleep(800);
        const item = page.getByRole('menuitem', { name: 'Generate Token', exact: true });
        const offered = await item.count();
        if (offered) { await item.first().click(); } else { await page.keyboard.press('Escape'); }
        await sleep(1600);
        const after = await look();
        const fresh = Object.keys(after.bySlot)
          .filter(slot => !(slot in before.bySlot));
        entry.saw = `Generate Token (메뉴 ${offered}건) → 새 개체 `
                    + JSON.stringify(fresh);
        if (!offered) {
          entry.ok = false;
          entry.reasons = ['조작 바 More 메뉴에 Generate Token 이 없습니다'];
        } else if (fresh.length !== 1) {
          entry.ok = false;
          entry.reasons = [`토큰 하나가 생겨야 하는데 ${fresh.length}개가 `
                           + '늘었습니다'];
        } else {
          alias[op.card] = fresh[0];
          reverse[fresh[0]] = op.card;
          entry.ok = true;
          entry.reasons = [];
          entry.where = after.bySlot[fresh[0]] || null;
          board = await look();
          rows = await historyRows(page);
        }
        result.operations.push(entry);
        if (!entry.ok) {
          stop(`operation#${op.n}`,
               `${op.op} ${op.card} — ${(entry.reasons || []).join(' / ')}`);
          await page.screenshot({ path: shot(`op-${op.n}-fail`) });
          break;
        }
        continue;
      }
      const box = await expandPileIfNeeded(page, siteName(op.card));
      if (!box || !box.w) {
        entry.ok = false;
        entry.saw = '카드를 찾지 못했거나 읽을 수 없습니다';
        entry.reasons = ['판에서 이 개체를 집지 못했습니다'];
      } else {
        //: 🔴 **1차 근거**: 건드릴 지점에 정말 그 개체가 있는가.
        const clickHit = await cardAtPoint(page, box.x, box.y);
        if (op.op === 'move') {
          const target = zones[op.to];
          if (!target) {
            entry.ok = false; entry.saw = `존 ${op.to} 을 찾지 못했습니다`;
            entry.reasons = [entry.saw];
          } else {
            //: 🔴 **뒷면 세트는 끌어 놓기 전에 선언한다** (Phase 6-BH).
            //: 조작 바의 `Face-down` 을 켜면 그 드롭이 뒷면으로 놓인다
            //: (실측). 🔴 **끈적하므로 놓은 뒤 반드시 끈다.**
            const wantFaceDown = op.face_down === true;
            entry.armed = await armFaceDown(page, wantFaceDown);
            await drag(page, box, target);
            if (wantFaceDown) { entry.disarmed = await armFaceDown(page, false); }
            const after = await historyRows(page);
            const seen = await look();
            const row = after[after.length - 1];
            const evidence = {
              clickHit,
              moved: movedBetween(board, seen),
              where: seen.bySlot[op.card] || null,
              historyGrew: after.length === rows.length + 1,
              historyText: row ? row.text : '',
              problems: seen.problems,
            };
            const verdict = decideMove(op, evidence);
            entry.saw = evidence.historyText || '(이력 없음)';
            entry.where = evidence.where;
            entry.moved = evidence.moved;
            entry.click_hit = clickHit;
            //: 그림은 **보조 근거**로만 적는다 — 판정에 쓰지 않는다.
            entry.thumbnail = identityOf(row, box.src, seen.srcOf).how;
            entry.ok = verdict.ok;
            entry.reasons = verdict.why;
            rows = after; board = seen;
            //: 🔴 **놓았다는 사실로 끝내지 않는다** (Phase 6-BH). 뒷면이어야
            //: 하는 자리면 **사이트에게 물어** 확인하고, 앞면이면 그 카드의
            //: 메뉴로 뒤집은 뒤 **다시 물어** 확인한다. 🔴 이미 뒷면이면
            //: 다시 뒤집지 않는다.
            if (entry.ok && wantFaceDown) {
              const at = await cardBox(page, siteName(op.card));
              let told = at ? await readPosition(page, at) : null;
              entry.position_menu = told ? told.items : null;
              entry.position_seen = told ? told.position : 'unknown';
              if (told && told.position === 'face_up') {
                entry.flipped = await cardMenu(page, at, 'Set Face-down');
                told = await readPosition(page, at);
                entry.position_menu = told.items;
                entry.position_seen = told.position;
              } else if (told && told.position === 'face_down') {
                entry.flipped = 'not-needed';
              }
              if (entry.position_seen !== 'face_down') {
                entry.ok = false;
                entry.reasons = (entry.reasons || []).concat([
                  `뒷면으로 만들지 못했습니다 (사이트가 말한 상태: `
                  + `${entry.position_seen})`]);
              }
              rows = await historyRows(page);
              board = await look();
            }
          }
        } else if (op.op === 'activate' || op.op === 'target') {
          const item = op.op === 'activate' ? 'Activate Effect' : 'Target';
          const picked = await cardMenu(page, box, item);
          const after = await historyRows(page);
          const seen = await look();
          const row = after[after.length - 1];
          const evidence = {
            clickHit, picked,
            moved: movedBetween(board, seen),
            where: seen.bySlot[op.card] || null,
            historyGrew: after.length === rows.length + 1,
            historyText: row ? row.text : '',
            panelZone: await panelZone(page),
            problems: seen.problems,
          };
          const verdict = decideMenu(op, evidence);
          entry.saw = evidence.historyText || '(이력 없음)';
          entry.where = evidence.where;
          entry.click_hit = clickHit;
          entry.panel = evidence.panelZone;
          entry.thumbnail = identityOf(row, box.src, seen.srcOf).how;
          entry.ok = verdict.ok;
          entry.reasons = verdict.why;
          rows = after; board = seen;
        } else if (op.op === 'delete_token') {
          //: 🔴 **토큰만 지울 수 있다** (실측) — 그 메뉴 항목은 토큰에만
          //: 생기므로, 눌리지 않았다는 사실이 곧 "이것은 토큰이 아니다" 다.
          const picked = await cardMenu(page, box, 'Delete Token');
          await sleep(400);
          const seen = await look();
          entry.saw = `Delete Token (${picked ? '눌렀다' : '항목이 없다'})`;
          entry.where = seen.bySlot[op.card] || null;
          entry.click_hit = clickHit;
          //: 🔴 **사라졌는지 판으로 확인한다** — 누른 것으로 끝내지 않는다.
          entry.ok = Boolean(picked) && !(op.card in seen.bySlot);
          entry.reasons = entry.ok ? [] : [
            picked ? '토큰이 판에서 사라지지 않았습니다'
                   : '카드 메뉴에 Delete Token 이 없습니다 (토큰이 아닙니다)'];
          rows = await historyRows(page); board = seen;
        } else {
          entry.ok = false; entry.saw = `모르는 조작 ${op.op}`;
          entry.reasons = [entry.saw];
        }
      }
      result.operations.push(entry);
      if (!entry.ok) {
        stop(`operation#${op.n}`,
             `${op.op} ${op.card} — 기대 "${op.expect}" · `
             + (entry.reasons || []).join(' / '));
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

    // ------------------------------------------------- 최종 판 대조
    counts = await zoneCounts(page);
    const seen = await look();
    //: 🔴 **선언한 자리의 표시 형식을 사이트에게 묻는다** (Phase 6-BH).
    //: 6-BG 는 기대만 적고 묻지 않았다 — 그래서 "자리가 맞았다" 를
    //: "재현됐다" 로 읽을 길이 남아 있었다.
    //:
    //: 🔴 **읽지 못한 자리를 맞은 것으로 만들지 않는다.** 집을 수 없거나
    //: 메뉴가 표시 형식을 말하지 않으면 ``unknown`` 이고,
    //: ``comparePositions`` 가 그것을 **미확인**으로 남긴다.
    const observedPositions = {};
    const positionMenus = {};
    for (const row of (plan.expect_positions || {}).declared || []) {
      const at = await cardBox(page, siteName(row.slot));
      if (!at || !at.w) { observedPositions[row.slot] = 'unknown'; continue; }
      const told = await readPosition(page, at);
      observedPositions[row.slot] = told.position;
      positionMenus[row.slot] = told.items;
    }
    const verdict = compareFinal(plan.expect_final, seen, counts,
                                 plan.expect_positions, observedPositions,
                                 plan.required_unsupported);
    result.stages.final = {
      counts,
      checks: verdict.checks,
      cross_check: verdict.crossCheck,
      problems: verdict.problems,
      card_zones: seen.bySlot,
      all_ok: verdict.allOk,
      //: 🔴 **자리가 맞았다 ≠ 그대로 재현됐다** (6-BG). 뒷면으로 끝나야
      //: 하는 자리가 있으면 이 칸이 거짓이고, 어느 자리인지도 함께 남는다.
      positions: verdict.positions,
      position_menus: positionMenus,
      missing_support: verdict.missing_support,
      fully_reproduced: verdict.fullyReproduced,
    };
    if (!verdict.fullyReproduced && verdict.allOk) {
      //: 🔴 **왜 "재현됐다" 가 아닌지를 갈라 적는다** (Phase 6-BH) — 표시
      //: 형식이 어긋났는가 · 못 읽었는가 · 필수 조작을 못 했는가.
      const said = [];
      const pos = verdict.positions || {};
      for (const row of pos.mismatched || []) {
        said.push(`${row.slot}→${row.zone}: ${row.want} 이어야 하는데 `
                  + `${row.got} 입니다`);
      }
      for (const row of pos.required_not_observed || []) {
        said.push(`${row.slot}→${row.zone}: 뒷면이어야 하는데 표시 형식을 `
                  + '읽지 못했습니다');
      }
      for (const line of verdict.missing_support || []) {
        said.push('필수 미지원: ' + line);
      }
      result.notes.push('🔴 자리는 맞았지만 **그대로 재현된 것은 아닙니다** — '
                        + (said.join(' / ') || '사유를 적지 못했습니다'));
    }
    if ((verdict.positions || {}).not_observed &&
        verdict.positions.not_observed.length) {
      //: 🔴 **미확인은 「맞았다」 도 「틀렸다」 도 아니다.** 그 사실만 적는다.
      result.notes.push('표시 형식을 읽지 못한 자리: '
        + verdict.positions.not_observed
            .map(r => `${r.slot}(${r.want})`).join(' · '));
    }
    //: 🔴 **계획이 못 한다고 적어 둔 것을 결과에도 적는다** (6-BG). 전에는
    //: ``plan.unsupported`` 가 계획 파일에만 있었고, 자동 조작의 결과만
    //: 읽는 쪽에는 **그 한계가 전해지지 않았다.**
    for (const line of (plan.unsupported || []).slice(0, 20)) {
      result.notes.push('계획이 적어 둔 한계: ' + line);
    }

    await page.getByRole('button', { name: /Stop Recording/i }).click();
    await sleep(2500);
    result.stages.recording_stopped = true;
    await page.screenshot({ path: shot('05-recorded') });

    // ------------------------------------------------------- 공유
    if (!WANT_SHARE) {
      result.notes.push('공유하지 않았습니다 (--share 를 주지 않았습니다). '
                        + '기록은 이 브라우저 세션에만 있습니다.');
    } else if (!result.stages.final.fully_reproduced) {
      //: 🔴 **재현되지 않았으면 공유하지 않는다** (Phase 6-BH).
      //:
      //: 6-BG 는 이 분기에서 `all_ok` **하나만** 보았다 — 자리만 맞으면
      //: 표시 형식이 어긋나도, 필수 조작을 못 했어도 공유했다. 지금은
      //: ② 자리 · ③ 표시 형식 · 필수 미지원을 **함께** 본 판정을 읽는다.
      const bad = result.stages.final.checks.filter(c => !c.ok);
      const pos = result.stages.final.positions || {};
      const why = !result.stages.final.all_ok
        ? '최종 판이 기록과 다릅니다: ' + JSON.stringify(bad).slice(0, 300)
        : (pos.mismatched || []).length
          ? '표시 형식이 기록과 다릅니다: ' + JSON.stringify(pos.mismatched).slice(0, 300)
          : (pos.required_not_observed || []).length
            ? '뒷면이어야 하는 자리의 표시 형식을 확인하지 못했습니다: '
              + JSON.stringify(pos.required_not_observed).slice(0, 300)
            : '이 기록을 재현하는 데 필요한 조작을 하지 못했습니다: '
              + JSON.stringify(result.stages.final.missing_support).slice(0, 300);
      stop('verify', why);
      result.notes.push('🔴 재현을 확인하지 못해서 공유하지 않았습니다.');
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
      if (!url) {
        //: 🔴 **다시 누르지 않는다** — 두 번 공개할 수 있다.
        result.notes.push('🔴 공유 URL 을 화면에서 읽지 못했습니다. '
                          + '자동으로 다시 시도하지 않았습니다 (중복 공개를 '
                          + '막기 위해서입니다). 사이트에 리플레이가 '
                          + '만들어졌을 수 있습니다.');
      }
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
