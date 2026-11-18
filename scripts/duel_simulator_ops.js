/*
 * 사이트 조작의 **손가락** (Phase 6-BH).
 *
 * 왜 따로 두는가 — 조작기(``duel_simulator_driver.js``)는 브라우저를 열고
 * 덱 이미지를 올리고 기록까지 만드는 **한 덩어리**라서, 조작 하나하나를
 * 실제 사이트에서 확인하려면 그 전부를 돌려야 했다. 올리는 일은 되돌릴 수
 * 없으므로 (올린 이미지를 이용자가 지울 수 없다) **확인하려고 올리는 일**이
 * 생긴다.
 *
 * 그래서 끌어 놓기 · 카드 메뉴 · 표시 형식 토글 · 표시 형식 읽기를 이 파일로
 * 옮겼다. 조작기가 이것을 그대로 쓰고
 * (``scripts/duel_simulator_ops.js``), 확인 스크립트도 **같은 함수**를
 * 쓴다 — 그래서 "확인한 것" 과 "도는 것" 이 같은 코드다.
 *
 * 🔴 **판정하지 않는다.** 여기 있는 것은 손가락이고, 무엇이 맞았는지는
 * ``duel_simulator_verify.js`` 가 값으로 판정한다.
 */
'use strict';

const path = require('path');
const { decidePosition } = require(path.join(__dirname,
                                             'duel_simulator_verify.js'));

const STEP_PAUSE = 700;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

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

async function cardMenu(page, box, item) {
  await page.mouse.click(box.x, box.y, { button: 'right' });
  await sleep(600);
  const entry = page.getByRole('menuitem', { name: item, exact: true });
  if (await entry.count() === 0) { return false; }
  await entry.first().click();
  await sleep(STEP_PAUSE);
  return true;
}

/**
 * 조작 바의 **`Face-down` 토글**을 원하는 상태로 맞춘다 (Phase 6-BH).
 *
 * 🔴 **끈적하다** (실측). 한 번 켜면 **다음 드롭에도 계속 켜져 있다** —
 * 그래서 세트 뒤에 반드시 끈다. 그러지 않으면 뒤의 앞면 이동이 전부
 * 뒷면으로 놓인다.
 *
 * 🔴 **눌렀다는 사실로 끝내지 않는다.** `aria-pressed` 를 **읽어서**
 * 돌려주고, 부르는 쪽이 그 값으로 판정한다.
 */
async function armFaceDown(page, on) {
  const button = page.getByRole('button', { name: /^Face-down$/i });
  if (await button.count() === 0) { return { found: false, pressed: null }; }
  const first = button.first();
  const before = await first.getAttribute('aria-pressed');
  if ((before === 'true') !== on) {
    await first.click();
    await sleep(450);
  }
  return { found: true, pressed: await first.getAttribute('aria-pressed') };
}

/**
 * 그 카드의 **지금 표시 형식**을 사이트에게 묻는다 (Phase 6-BH).
 *
 * 🔴 **카드 메뉴가 그 상태를 말한다** (:func:`decidePosition` 의 실측).
 * 메뉴를 열고 항목 이름을 읽은 뒤 **반드시 닫는다** — 열어 둔 메뉴가
 * 다음 조작의 클릭을 먹는다.
 */
async function readPosition(page, box) {
  await page.mouse.click(box.x, box.y, { button: 'right' });
  await sleep(550);
  const items = await page.evaluate(() =>
    [...document.querySelectorAll('[role=menuitem]')].map(e => (e.innerText || '').trim()));
  await page.keyboard.press('Escape');
  await sleep(250);
  return { items, position: decidePosition(items) };
}

module.exports = { drag, cardMenu, armFaceDown, readPosition,
                   STEP_PAUSE, sleep };
