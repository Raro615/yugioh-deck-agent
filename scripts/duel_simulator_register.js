/*
 * 덱 이미지 등록 — 사이트가 **자리마다 어느 카드로 읽는지** 확인한다
 * (Phase 6-AZ).
 *
 * 하는 일: 사용자가 준 덱 이미지를 올려 판에 적용하고, `Deck` 탭의 카드
 * 목록에서 **자리별 식별 결과**를 읽어 JSON 으로 적는다. 조작도 녹화도
 * 공유도 하지 않는다.
 *
 * 🔴 **이미지상의 순서나 OCR 만으로 "확인됐다" 고 적지 않는다.** 사이트의
 *    식별 UI 가 말한 이름을 그대로 옮기고, 못 읽은 자리는 못 읽었다고
 *    적는다. 레시피와의 대조는 파이썬 쪽이 한다.
 * 🔴 **자리 대응은 썸네일 그림으로 맞춘다.** 목록의 각 줄에는 그 자리에서
 *    잘라낸 그림이 붙고, 그 `src` 는 판 위 카드의 `src` 와 같다 (실측).
 *    잘라낸 위치가 다르면 그림도 다르므로, 같은 카드가 여러 장이어도
 *    줄과 자리가 일대일로 묶인다. 묶이지 않으면 **순서로 때우지 않고**
 *    그렇다고 적는다.
 *
 * 사용: node scripts/duel_simulator_register.js <작업디렉터리>
 *          --image <덱이미지> --main <수> --extra <수> [--side <수>]
 *          [--run-id <id>] [--headed]
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const SITE = 'https://duel-simulator.miyauchidp.dev/';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const DIR = process.argv[2];
const IMAGE = arg('--image', '');
const MAIN = Number(arg('--main', '0'));
const EXTRA = Number(arg('--extra', '0'));
const SIDE = Number(arg('--side', '0'));
const RUN_ID = arg('--run-id', '');
const HEADLESS = !process.argv.includes('--headed');

if (!DIR || !IMAGE || !MAIN) {
  console.error('사용: node scripts/duel_simulator_register.js <작업디렉터리> '
                + '--image <덱이미지> --main <수> --extra <수>');
  process.exit(2);
}

const out = { run_id: RUN_ID, image: IMAGE, site: SITE,
              counts: { main: MAIN, extra: EXTRA, side: SIDE },
              applied: null, slots: [], unreadable: [], problems: [],
              stopped_reason: null };
function finish(code) {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(path.join(DIR, 'identify.json'),
                   JSON.stringify(out, null, 1), 'utf8');
  console.log(JSON.stringify(out));
  process.exit(code);
}

async function setCount(page, id, value) {
  const el = page.locator('#' + id);
  await el.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.type(String(value), { delay: 60 });
  await page.keyboard.press('Tab');
  await sleep(350);
}

(async () => {
  if (!fs.existsSync(IMAGE)) {
    out.stopped_reason = `덱 이미지를 찾지 못했습니다: ${IMAGE}`;
    finish(1);
  }
  const browser = await chromium.launch({ headless: HEADLESS });
  const page = await browser.newPage({
    viewport: { width: 1560, height: 1100 }, deviceScaleFactor: 1 });
  try {
    await page.goto(SITE, { waitUntil: 'networkidle', timeout: 90000 });
    await sleep(2500);
    await page.setInputFiles('input[type=file]', IMAGE);
    await sleep(9000);
    out.auto_detected = await page.evaluate(() => {
      const m = (document.body.innerText).match(/Detected Deck Configuration\n([^\n]*)/);
      return m ? m[1] : '';
    });
    await page.locator('input[type=checkbox]').first().check();
    await sleep(600);
    await setCount(page, 'mainDeck', MAIN);
    await setCount(page, 'extraDeck', EXTRA);
    await setCount(page, 'sideDeck', SIDE);
    await page.getByRole('button', { name: /Apply deck to field/i }).click();
    await sleep(8000);

    out.applied = await page.evaluate(() => {
      const o = {};
      ((document.body.innerText || '')
        .match(/(Hand|Extra Deck|Deck) \(\d+\)/g) || [])
        .forEach(s => { const m = s.match(/^(.*) \((\d+)\)$/); o[m[1]] = Number(m[2]); });
      return o;
    });
    if (out.applied['Deck'] !== MAIN || out.applied['Extra Deck'] !== EXTRA) {
      out.stopped_reason =
        `판에 들어간 장수가 다릅니다: ${JSON.stringify(out.applied)} `
        + `(기대 메인 ${MAIN} · 엑스트라 ${EXTRA})`;
      await page.screenshot({ path: path.join(DIR, 'register-apply-fail.png') });
      await browser.close(); finish(1);
    }
    await page.screenshot({ path: path.join(DIR, 'register-01-applied.png') });

    //: 판 위 카드의 그림 — 줄과 자리를 묶는 열쇠다.
    const boardSrc = await page.evaluate(() => {
      const o = {};
      document.querySelectorAll('[data-card-id]').forEach(e => {
        if (e.querySelector('[data-card-id]')) { return; }
        const img = e.querySelector('img');
        if (!img) { return; }
        o[e.getAttribute('data-card-id').split('-').slice(0, 2).join('-')] = img.src;
      });
      return o;
    });

    //: Deck 탭을 열어 자리별 식별 결과를 읽는다.
    const deckTab = page.getByRole('button', { name: /^Deck/ });
    if (await deckTab.count()) { await deckTab.first().click(); await sleep(2000); }
    const rows = await page.evaluate(() => {
      const all = [...document.querySelectorAll('*')].filter(e =>
        /^(Main deck|Extra Deck|Side deck)\s+\d+/.test((e.innerText || '').trim())
        && e.querySelector('img'));
      const leaves = all.filter(e => !all.some(o => o !== e && e.contains(o)));
      return leaves.map(e => {
        const text = (e.innerText || '').replace(/\n+/g, ' | ').trim();
        const m = text.match(/^(Main deck|Extra Deck|Side deck)\s+(\d+)\s*\|?\s*(.*)$/);
        return {
          part: m ? m[1] : '', index: m ? Number(m[2]) : 0,
          said: m ? m[3].trim() : text,
          src: (e.querySelector('img') || {}).src || null,
        };
      });
    });
    if (!rows.length) {
      out.stopped_reason = 'Deck 탭에서 카드 목록을 읽지 못했습니다';
      await page.screenshot({ path: path.join(DIR, 'register-deck-tab.png') });
      await browser.close(); finish(1);
    }
    await page.screenshot({ path: path.join(DIR, 'register-02-deck-tab.png'),
                            fullPage: true });

    //: 🔴 그림으로 자리를 묶는다. 같은 그림이 둘 이상이면 **순서로 때우지
    //:    않고** 묶지 못했다고 적는다.
    const bySrc = {};
    Object.entries(boardSrc).forEach(([slot, src]) => {
      (bySrc[src] = bySrc[src] || []).push(slot);
    });
    const prefix = { 'Main deck': 'main', 'Extra Deck': 'extra',
                     'Side deck': 'side' };
    for (const row of rows) {
      const part = prefix[row.part] || 'main';
      const fallback = `${part}-${row.index - 1}`;
      const hit = row.src ? bySrc[row.src] : null;
      let slot = null, how = '';
      if (hit && hit.length === 1) { slot = hit[0]; how = 'thumbnail'; }
      else if (hit && hit.length > 1) {
        how = `그림이 같은 자리 ${hit.length}개 — 자리를 묶지 못했습니다`;
      } else { how = '목록 줄의 그림을 판에서 찾지 못했습니다'; }
      const said = row.said || '';
      const unrecognized = /Unrecognized|Select a card|未識別/.test(said);
      if (!slot) {
        out.unreadable.push({ slot: fallback, how, said });
        continue;
      }
      out.slots.push({
        slot, label: `${row.part} ${row.index}`,
        name: unrecognized ? '' : said.split(' | ')[0].trim(),
        state: unrecognized ? 'unrecognized' : 'identified',
        matched_by: how,
      });
    }
    out.counts_read = {
      main: out.slots.filter(s => s.slot.startsWith('main-')).length,
      extra: out.slots.filter(s => s.slot.startsWith('extra-')).length,
    };
    out.uncertain = out.slots.filter(s => s.state !== 'identified').length;
  } catch (error) {
    out.stopped_reason = String(error.message).slice(0, 300);
    try { await page.screenshot({ path: path.join(DIR, 'register-error.png') }); }
    catch (_) {}
  }
  await browser.close();
  finish(out.stopped_reason ? 1 : 0);
})();
