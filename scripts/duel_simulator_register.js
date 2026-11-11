/*
 * 덱 이미지 등록 — 사이트가 **자리마다 어느 카드로 읽는지** 확인한다
 * (Phase 6-AZ).
 *
 * 하는 일: 사용자가 준 덱 이미지를 올려 판에 적용하고, **판의 카드를
 * 자리마다 눌러 「Card details」 칸을 읽어** JSON 으로 적는다. 조작도 녹화도
 * 공유도 하지 않는다.
 *
 * 🔴 **이미지상의 순서나 OCR 만으로 "확인됐다" 고 적지 않는다.** 사이트의
 *    식별 UI 가 말한 이름을 그대로 옮기고, 못 읽은 자리는 못 읽었다고
 *    적는다. 레시피와의 대조는 파이썬 쪽이 한다.
 * 🔴 **`Deck` 탭 목록을 쓰지 않는다 (Phase 6-BA 정정).** 그 목록은 보이는
 *    만큼만 DOM 에 두는 **가상 스크롤**이라 자리가 많으면(실측 55자리)
 *    끝까지 읽히지 않았다 — 한 번에 약 20줄, 스크롤해 모아도 25줄에서
 *    멈췄다. 판의 카드는 **전부 DOM 에 있고**, 누르면 상세 칸이 **그
 *    카드**를 가리키므로 자리와 이름이 어긋날 수 없다.
 * 🔴 **누르기는 상세를 띄울 뿐 판을 바꾸지 않는다.**
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

    //: 🔴 **자리마다 카드를 눌러 「카드 상세」를 읽는다.** 목록 탭은 보이는
    //: 만큼만 DOM 에 두는 가상 스크롤이라 끝까지 읽히지 않았다. 판의 카드는
    //: 전부 DOM 에 있고, 누르면 상세 칸이 **그 카드**를 가리킨다 — 자리와
    //: 이름이 어긋날 수 없다. 🔴 누르기는 상세를 띄울 뿐 판을 바꾸지 않는다.
    const slotsOnBoard = await page.evaluate(() =>
      [...document.querySelectorAll('[data-card-id]')]
        .filter(e => !e.querySelector('[data-card-id]'))
        .map(e => e.getAttribute('data-card-id').split('-').slice(0, 2).join('-'))
        .filter((v, i, all) => all.indexOf(v) === i));

    const readPanel = () => page.evaluate(() => {
      const text = document.body.innerText || '';
      const at = text.indexOf('Card details');
      if (at < 0) { return null; }
      const lines = text.slice(at).split('\n').map(s => s.trim()).filter(Boolean);
      // ['Card details', '<존>', 'Details'|'Unrecognized', '<이름>' …]
      const zone = lines[1] || '';
      const mark = lines[2] || '';
      if (/Unrecognized/.test(mark)) { return { zone, name: '', state: 'unrecognized' }; }
      if (/Processing/.test(mark) || /Processing/.test(lines[3] || '')) {
        return { zone, name: '', state: 'processing' };
      }
      if (!/Details/.test(mark)) { return { zone, name: '', state: 'unreadable' }; }
      return { zone, name: lines[3] || '', state: (lines[3] ? 'identified' : 'unreadable') };
    });

    for (const slot of slotsOnBoard) {
      const box = await page.evaluate(slot => {
        const node = [...document.querySelectorAll(`[data-card-id^="${slot}-"]`)]
          .filter(e => !e.querySelector('[data-card-id]'))[0];
        if (!node) { return null; }
        const r = node.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) { return null; }
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
      }, slot);
      if (!box) {
        out.unreadable.push({ slot, how: '판에서 누를 수 없었습니다', said: '' });
        continue;
      }
      await page.mouse.click(box.x, box.y);
      await sleep(260);
      let panel = await readPanel();
      //: 아직 맞춰 보는 중이면 조금 더 기다렸다 다시 읽는다.
      for (let i = 0; panel && panel.state === 'processing' && i < 8; i++) {
        await sleep(900);
        panel = await readPanel();
      }
      if (!panel) {
        out.unreadable.push({ slot, how: '카드 상세를 읽지 못했습니다', said: '' });
        continue;
      }
      out.slots.push({
        slot, label: panel.zone, name: panel.name,
        state: panel.state === 'identified' ? 'identified' : 'unrecognized',
        matched_by: 'card-details-panel',
      });
    }
    out.identify_wait = `자리 ${out.slots.length}/${MAIN + EXTRA + SIDE} 를 `
      + `카드 상세로 읽었습니다`;

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
