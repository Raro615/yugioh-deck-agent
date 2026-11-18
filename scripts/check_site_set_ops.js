/*
 * 실제 사이트에서 **세트 조작 하나하나를 확인한다** (Phase 6-BH).
 *
 * 🔴 **새 이미지를 올리지 않는다.** 이미 만들어 둔 공유 리플레이를 열고
 *    `Manual` 로 바꿔 그 판에서 조작한다 — 올린 것을 이용자가 지울 수 없는
 *    사이트이므로, 확인하려고 올리는 일을 만들지 않는다.
 * 🔴 **기록도 공유도 하지 않는다.** 조작과 **관측**만 한다.
 * 🔴 **조작기가 쓰는 그 함수를 쓴다** (``duel_simulator_ops.js``) — 확인한
 *    것과 도는 것이 같은 코드여야 한다.
 *
 * 사용: node scripts/check_site_set_ops.js [리플레이 URL] [--headed]
 * 결과: stdout 에 JSON 한 줄 (checks 마다 ok 와 관측값).
 */
'use strict';

const path = require('path');
const { chromium } = require('playwright');
const { drag, cardMenu, armFaceDown, readPosition, sleep } =
  require(path.join(__dirname, 'duel_simulator_ops.js'));

const URL = process.argv[2] && !process.argv[2].startsWith('--')
  ? process.argv[2]
  : 'https://duel-simulator.miyauchidp.dev/replay/6ZdmBQec';
const HEADLESS = !process.argv.includes('--headed');
const out = { url: URL, checks: [], notes: [] };
const add = (name, ok, saw) => out.checks.push({ name, ok, saw });

async function zones(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('[data-droppable]')].map(e => {
      const r = e.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               top: Math.round(r.y), left: Math.round(r.x),
               label: (e.innerText || '').trim().slice(0, 24) };
    }));
}
async function cards(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('[data-card-id]')]
      .filter(e => !e.querySelector('[data-card-id]'))
      .map(e => { const r = e.getBoundingClientRect();
        return { id: e.getAttribute('data-card-id'),
                 x: Math.round(r.x + r.width / 2),
                 y: Math.round(r.y + r.height / 2),
                 w: Math.round(r.width) }; })
      .filter(c => c.w > 2));
}
const at = (list, zone) => list.find(
  c => Math.abs(c.x - zone.x) < 9 && Math.abs(c.y - zone.y) < 9) || null;

(async () => {
  const browser = await chromium.launch({ headless: HEADLESS });
  const page = await browser.newPage({ viewport: { width: 1560, height: 1100 } });
  page.on('pageerror', e => out.notes.push('pageerror: ' + String(e.message).slice(0, 120)));
  try {
    await page.goto(URL, { waitUntil: 'networkidle', timeout: 90000 });
    await sleep(4000);
    const start = page.getByRole('button', { name: /^Start Replay$/i });
    if (await start.count()) { await start.first().click(); }
    await sleep(9000);
    const manual = page.getByRole('button', { name: /^Manual$/i });
    add('manual-mode', await manual.count() > 0, await manual.count());
    if (await manual.count()) { await manual.first().click(); await sleep(2500); }

    const zs = await zones(page);
    const deck = zs.find(z => /^Deck \(/.test(z.label));
    const rows = {};
    zs.filter(z => !/^(Free|Grave|Banish|Hand|Extra Deck|Deck) \(/.test(z.label))
      .forEach(z => { (rows[z.top] = rows[z.top] || []).push(z); });
    const tops = Object.keys(rows).map(Number).sort((a, b) => a - b);
    const st = (rows[tops[2]] || []).sort((a, b) => a.left - b.left);
    const field = (rows[tops[1]] || []).sort((a, b) => a.left - b.left);
    const st1 = st.length === 6 ? st[1] : st[0];
    const st2 = st.length === 6 ? st[2] : st[1];
    const fzone = field.length === 6 ? field[0] : null;
    add('zones-found', Boolean(deck && st1 && st2 && fzone),
        { deck: Boolean(deck), st1: Boolean(st1), st2: Boolean(st2),
          field_zone: Boolean(fzone) });
    if (!deck || !st1 || !st2 || !fzone) { throw new Error('칸을 찾지 못했습니다'); }

    // ① 토글이 눌리고 **읽힌다**
    const armed = await armFaceDown(page, true);
    add('face-down-armed', armed.found && armed.pressed === 'true', armed);

    // ② 덱 → 마법·함정 존 (뒷면)
    await drag(page, deck, st1);
    const off = await armFaceDown(page, false);
    add('face-down-disarmed', off.pressed === 'false', off);
    let landed = at(await cards(page), st1);
    add('set-landed-in-spell-zone', Boolean(landed), landed && landed.id);
    let told = landed ? await readPosition(page, landed) : null;
    add('set-is-face-down', Boolean(told) && told.position === 'face_down',
        told && { position: told.position, menu: told.items });

    // ③ 이미 뒷면이면 **다시 뒤집지 않는다** (같은 답이 두 번 나온다)
    const again = landed ? await readPosition(page, landed) : null;
    add('face-down-is-idempotent',
        Boolean(again) && again.position === 'face_down',
        again && again.position);

    // ④ 앞면으로 놓고 **메뉴로 고치는 길**
    await drag(page, deck, st2);
    let other = at(await cards(page), st2);
    let before = other ? await readPosition(page, other) : null;
    add('control-drop-is-face-up',
        Boolean(before) && before.position === 'face_up',
        before && before.position);
    if (other) {
      const picked = await cardMenu(page, other, 'Set Face-down');
      other = at(await cards(page), st2);
      const after = other ? await readPosition(page, other) : null;
      add('menu-flips-to-face-down',
          Boolean(picked) && Boolean(after) && after.position === 'face_down',
          { picked, position: after && after.position });
    }

    // ⑤ 덱 → 필드 존 (뒷면)
    const armed2 = await armFaceDown(page, true);
    await drag(page, deck, fzone);
    await armFaceDown(page, false);
    const onField = at(await cards(page), fzone);
    const fieldTold = onField ? await readPosition(page, onField) : null;
    add('field-zone-set-is-face-down',
        armed2.pressed === 'true' && Boolean(fieldTold)
        && fieldTold.position === 'face_down',
        fieldTold && { position: fieldTold.position, id: onField.id });

    // ⑥ 토큰 — 만들고, 그 메뉴를 읽고, 지운다
    const seenBefore = (await cards(page)).map(c => c.id);
    await page.getByRole('button', { name: /^More$/i }).first().click();
    await sleep(800);
    const item = page.getByRole('menuitem', { name: 'Generate Token', exact: true });
    const offered = await item.count();
    if (offered) { await item.first().click(); } else { await page.keyboard.press('Escape'); }
    await sleep(1600);
    const fresh = (await cards(page)).filter(c => !seenBefore.includes(c.id));
    add('generate-token', offered > 0 && fresh.length === 1,
        { offered, fresh: fresh.map(c => c.id) });
    if (fresh.length === 1) {
      const menu = await readPosition(page, fresh[0]);
      add('token-menu-has-delete', menu.items.includes('Delete Token'),
          menu.items);
      const removed = await cardMenu(page, fresh[0], 'Delete Token');
      await sleep(600);
      const left = (await cards(page)).some(c => c.id === fresh[0].id);
      add('delete-token', Boolean(removed) && !left, { removed, left });
    }
    await page.screenshot({ path: path.join(__dirname, '..',
      'docs', 'viewer', 'local', 'site-set-ops.png') }).catch(() => {});
  } catch (error) {
    out.notes.push('실패: ' + String(error.message).slice(0, 220));
  }
  await browser.close();
  out.all_ok = out.checks.length > 0 && out.checks.every(c => c.ok);
  console.log(JSON.stringify(out, null, 1));
  process.exit(out.all_ok ? 0 : 1);
})();
