/*
 * 사이트 조작의 **판정부** (Phase 6-AY) — 순수 함수만 둔다.
 *
 * 왜 따로 빼는가: 조작기(`duel_simulator_driver.js`) 는 브라우저를 열어야
 * 돌릴 수 있어서, "장수는 같지만 카드가 서로 바뀐 경우" 같은 실패를 시험이
 * 재현하기 어렵다. 판정을 여기로 빼면 **같은 코드**를 값만 넣어 돌릴 수
 * 있다 (`tests/test_site_verify.py` 가 그렇게 센다).
 *
 * 🔴 여기 있는 것은 전부 입력 → 출력이다. DOM 도 네트워크도 건드리지
 *    않는다.
 */
'use strict';

/** 사이트가 History 줄에 쓰는 이름으로 맞춘다 (``Banish1`` → ``Banish``). */
function normalizeZone(name) {
  return String(name || '')
    .replace(/^(Grave|Banish|Free|Hand|Deck)\d+$/, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * 이력의 한 줄에 **이 카드의 그림**이 붙어 있는가 — 🔴 **보조 근거다**.
 *
 * 실측에서 이력 줄의 썸네일 ``src`` 는 판 위 그 카드의 ``src`` 와 바이트
 * 단위로 같다. 그런데 실제 덱 이미지에서는 **같은 카드가 여러 장** 있는
 * 것이 정상이고, 그때 그림만으로는 어느 장인지 가릴 수 없다.
 *
 * 그래서 이 함수는 "그림이 맞는가"(`match`) 와 "그 그림이 판에서
 * 유일한가"(`unique`) 를 **사실 그대로** 돌려준다. 통과 여부를 여기서
 * 정하지 않는다 — 개체 확정은 :func:`decideMove` · :func:`decideMenu` 가
 * **안정 ID(`data-card-id`)와 클릭 지점, 판의 변화**로 한다.
 */
function identityOf(row, wantSrc, srcOf) {
  if (!row || !row.srcs || !row.srcs.length) {
    return { match: false, unique: false, how: '이력 줄에 썸네일이 없습니다' };
  }
  if (!wantSrc) {
    return { match: false, unique: false, how: '카드 그림을 읽지 못했습니다' };
  }
  if (!row.srcs.includes(wantSrc)) {
    return { match: false, unique: false,
             how: '이력의 썸네일이 이 카드의 그림과 다릅니다' };
  }
  const same = Object.keys(srcOf || {}).filter(s => srcOf[s] === wantSrc);
  if (same.length > 1) {
    return { match: true, unique: false,
             how: `그림이 같은 자리 ${same.length}개 — 보조 근거로만 씁니다` };
  }
  return { match: true, unique: true, how: '썸네일 일치 (판에서 유일)' };
}

/** 칸 이름의 표기 차이를 지운다 (`Extra Monster Zone 1` → `…Zone1`). */
function sameZone(a, b) {
  const tidy = v => normalizeZone(v).replace(/\s+(\d+)$/, '$1');
  return !!a && !!b && tidy(a) === tidy(b);
}

/**
 * **이동 하나**가 제대로 됐는가 (순수 함수).
 *
 * 🔴 개체 확정의 **1차 근거는 안정 ID** 다:
 *   ① 끌기를 시작한 지점에 있던 카드가 `data-card-id` 로 그 개체였고
 *      (`ev.clickHit`),
 *   ② 판에서 **자리를 옮긴 개체가 정확히 그 하나**이며 (`ev.moved`),
 *   ③ 그 개체가 지금 목적지 칸에 있다 (`ev.where`).
 * 이력 줄과 썸네일은 **보조 근거**로만 쓴다 — 같은 그림이 여러 장이어도
 * ①~③ 이 서면 통과하고, ①~③ 중 하나라도 못 세우면 통과하지 않는다.
 */
function decideMove(op, ev) {
  const why = [];
  if (ev.clickHit !== op.card) {
    why.push(`끌기 지점의 개체가 ${ev.clickHit || '없음'} 입니다`);
  }
  const moved = ev.moved || [];
  if (moved.length !== 1 || moved[0].slot !== op.card) {
    why.push(`자리를 옮긴 개체가 ${JSON.stringify(moved)} 입니다`);
  } else if (!sameZone(moved[0].to, op.to)) {
    why.push(`옮겨 간 칸이 ${moved[0].to} 입니다`);
  }
  if (!sameZone(ev.where, op.to)) {
    why.push(`카드가 지금 ${ev.where || '어디인지 모르는 곳'} 에 있습니다`);
  }
  if (!ev.historyGrew) { why.push('조작 이력이 한 줄 늘지 않았습니다'); }
  if ((ev.problems || []).length) { why.push('판을 읽지 못한 자리가 있습니다'); }
  return { ok: why.length === 0, why };
}

/**
 * **발동 · 대상 지정**이 제대로 됐는가 (순수 함수).
 *
 * 판이 바뀌지 않는 조작이라 "무엇이 움직였나" 로는 가릴 수 없다. 그래서
 *   ① 우클릭한 지점에 있던 카드가 `data-card-id` 로 그 개체였고,
 *   ② 메뉴 항목을 실제로 골랐고,
 *   ③ 이력이 한 줄 늘었고 그 줄의 **종류**가 맞고,
 *   ④ 그 줄에 적힌 칸이 **그 개체가 지금 있는 칸**과 같고,
 *   ⑤ 판에서 **아무것도 움직이지 않았다**
 * 를 함께 본다. 카드 상세 패널의 칸(`ev.panelZone`) 은 읽혔을 때만 보는
 * 보조 근거다.
 */
function decideMenu(op, ev) {
  const kind = op.op === 'activate' ? 'Activate Effect' : 'Target';
  const why = [];
  if (ev.clickHit !== op.card) {
    why.push(`우클릭 지점의 개체가 ${ev.clickHit || '없음'} 입니다`);
  }
  if (!ev.picked) { why.push(`메뉴에서 ${kind} 을 고르지 못했습니다`); }
  if (!ev.historyGrew) { why.push('조작 이력이 한 줄 늘지 않았습니다'); }
  const said = String(ev.historyText || '');
  if (!said.includes(`${kind} · `)) {
    why.push(`이력 줄이 ${kind} 이 아닙니다`);
  } else {
    const zone = said.slice(said.lastIndexOf('· ') + 2).trim();
    if (!sameZone(zone, ev.where)) {
      why.push(`이력의 칸(${zone})과 카드의 칸(${ev.where})이 다릅니다`);
    }
  }
  if ((ev.moved || []).length) {
    why.push(`판이 움직였습니다: ${JSON.stringify(ev.moved)}`);
  }
  if (ev.panelZone && !sameZone(ev.panelZone, ev.where)) {
    why.push(`카드 상세의 칸(${ev.panelZone})이 카드의 칸과 다릅니다`);
  }
  if ((ev.problems || []).length) { why.push('판을 읽지 못한 자리가 있습니다'); }
  return { ok: why.length === 0, why };
}

/** 두 판 읽기를 견줘 **자리를 옮긴 개체**만 뽑는다. */
function movedBetween(before, after) {
  const out = [];
  const from = (before && before.bySlot) || {};
  const to = (after && after.bySlot) || {};
  for (const slot of new Set([...Object.keys(from), ...Object.keys(to)])) {
    if (from[slot] !== to[slot]) {
      out.push({ slot, from: from[slot] || null, to: to[slot] || null });
    }
  }
  return out.sort((a, b) => a.slot.localeCompare(b.slot));
}

/**
 * 카드 메뉴의 항목 이름으로 **표시 형식을 읽는다** (Phase 6-BH).
 *
 * 🔴 **사이트가 스스로 말하는 것만 읽는다.** 실측한 두 모양이 근거다:
 *
 *   앞면 마법·함정 (Spell & Trap Zone)
 *     Activate Effect | Negate | Target | Highlight | **Set Face-down**
 *     | Add Counter | Card details
 *   뒷면 카드
 *     Target | Highlight | **Set Face-up** | Add Counter | Card details
 *
 * 즉 `Set Face-up` 이 보이면 **지금 뒷면**이고, `Set Face-down` 이 보이면
 * **지금 앞면**이다. 🔴 **둘 다 없으면 `unknown`** — 그 자리에서 사이트가
 * 표시 형식을 말하지 않는다는 뜻이고, 추측하지 않는다.
 *
 * 🔴 **그림(카드 뒷면 이미지)으로 판정하지 않는다.** 같은 뒷면 그림이
 * 여러 자리에 쓰이고, 덱 이미지에서 잘라낸 그림은 카드마다 다르다 —
 * 사이트의 **메뉴**가 그 상태를 직접 말하는 유일한 자리다.
 */
function decidePosition(menuItems) {
  const names = (menuItems || []).map(t => String(t).trim());
  const up = names.includes('Set Face-up');
  const down = names.includes('Set Face-down');
  if (up && down) { return 'unknown'; }
  if (up) { return 'face_down'; }
  if (down) { return 'face_up'; }
  return 'unknown';
}

/**
 * 선언한 자리의 **표시 형식을 견준다** (Phase 6-BH).
 *
 * `declared` 는 계획이 넘긴 `[{slot, zone, position}]` 이고 `observed` 는
 * 조작기가 사이트에서 읽은 `{slot: 'face_down'|'face_up'|'unknown'}` 다.
 *
 * 🔴 **셋을 가른다.** 어긋남(`mismatched`) 과 못 읽음(`not_observed`) 과
 * 맞음(`matched`) 이 다른 사실이다.
 *
 * 🔴 **「필수」 는 뒷면 기대뿐이다.** 뒷면은 이 조작기가 **직접 만드는**
 * 상태이므로 읽지 못하면 재현을 주장할 수 없다. 앞면 자리를 못 읽은 것은
 * 재현을 깨뜨리지 않지만 **`compared` 를 거짓으로** 만든다 — "뒷면 기대가
 * 없으니 표시 형식은 다 맞았다" 고 말하지 않기 위해서다.
 */
function comparePositions(declared, observed) {
  const rows = declared || [];
  const seen = observed || {};
  const matched = [], mismatched = [], notObserved = [];
  for (const row of rows) {
    const want = row.position;
    const got = seen[row.slot];
    if (got === undefined || got === null || got === 'unknown') {
      notObserved.push({ slot: row.slot, zone: row.zone, want });
      continue;
    }
    if (got === want) { matched.push({ slot: row.slot, zone: row.zone, want }); }
    else { mismatched.push({ slot: row.slot, zone: row.zone, want, got }); }
  }
  const requiredMissing = notObserved.filter(r => r.want === 'face_down');
  return {
    declared: rows.length,
    matched, mismatched,
    not_observed: notObserved,
    required_not_observed: requiredMissing,
    //: 🔴 **전부 읽었는가** — 하나라도 못 읽었으면 거짓이다.
    compared: rows.length > 0 && notObserved.length === 0,
    //: 🔴 **표시 형식이 맞았는가** — 어긋남이 없고 **뒷면은 전부 읽었다**.
    ok: mismatched.length === 0 && requiredMissing.length === 0,
  };
}

/**
 * 최종 판 대조.
 *
 * 🔴 **장수만 세지 않는다.** 존마다 **카드 자리의 집합**을 맞춘다 —
 *    있어야 할 카드가 빠졌는지(`missing`) 와 **예상 밖 카드가 있는지**
 *    (`unexpected`) 를 둘 다 본다.
 * 🔴 **빈 존은 실제로 비어 있으면 통과한다.** 기대가 빈 집합이고 화면도
 *    비어 있으면 ok 다.
 * 🔴 **읽을 수 없는 상태는 성공이 아니다.** `observed.problems` 가 비어
 *    있지 않으면 전체가 실패다.
 * 🔴 **좌표만 믿지 않는다.** 화면의 장수 표시(`counts`) 와 좌표로 읽은
 *    수를 교차 확인한다.
 * 🔴 **표시 형식은 조작기가 읽어서 넘긴다** (6-BH). `expectPositions` 는
 *    계획이 선언한 자리들이고 `observedPositions` 는 그 자리에서 **사이트의
 *    카드 메뉴로 읽은** 값이다 (:func:`decidePosition`). 둘을
 *    :func:`comparePositions` 가 견주고, 결과가 `positions` 에 들어간다.
 *    🔴 `allOk` 는 **자리 대조 하나**다 — 표시 형식 때문에 거짓으로 만들지
 *    않는다 (그러면 "자리도 틀렸다" 로 읽힌다).
 *
 * 🔴 **다섯 상태를 따로 돌려준다** (6-BH). ① 조작 실행은 부르는 쪽이
 *    세고, ② 자리 일치는 `allOk`, ③ 표시 형식 일치는 `positions.ok`,
 *    ④ **이 전개를 재현했는가**는 `fullyReproduced` (②·③ 과 **필수 미지원
 *    없음**을 함께 본다), ⑤ 공유 가능 여부는 부르는 쪽이 ④ 와 실행 상태로
 *    정한다. 🔴 하나로 뭉치면 "자리가 맞았으니 공유해도 된다" 가 된다.
 */
function compareFinal(expectFinal, observed, counts, expectPositions,
                      observedPositions, requiredUnsupported) {
  const byZone = (observed && observed.byZone) || {};
  const problems = (observed && observed.problems) || [];
  const checks = [];
  for (const zone of Object.keys(expectFinal || {})) {
    const want = ((expectFinal[zone] || {}).slots || []).slice().sort();
    const got = (byZone[zone] || []).slice().sort();
    const missing = want.filter(s => !got.includes(s));
    const unexpected = got.filter(s => !want.includes(s));
    checks.push({ zone, want: want.length, saw: got.length,
                  missing, unexpected,
                  ok: missing.length === 0 && unexpected.length === 0 });
  }
  //: 계획이 모르는 칸에 카드가 있으면 그것도 예상 밖이다.
  for (const zone of Object.keys(byZone)) {
    if (expectFinal && Object.prototype.hasOwnProperty.call(expectFinal, zone)) {
      continue;
    }
    checks.push({ zone, want: 0, saw: byZone[zone].length,
                  missing: [], unexpected: byZone[zone].slice(), ok: false });
  }
  const crossCheck = Object.keys(counts || {}).map(zone => {
    const geometry = (byZone[zone] || []).length;
    return { zone, label: counts[zone], geometry,
             ok: counts[zone] === geometry };
  });
  const faceDown = (expectPositions && expectPositions.face_down) || [];
  const declared = (expectPositions && expectPositions.declared) || [];
  const positions = Object.assign(
    comparePositions(declared, observedPositions),
    {
      face_down: faceDown,
      scope: (expectPositions && expectPositions.scope) || 'face_up_or_down',
      why: (expectPositions && expectPositions.why) || '',
    });
  //: 🔴 **재현을 깨뜨리는 미지원** (6-BH) — 계획이 "이 기록을 재현하려면
  //: 반드시 해야 하는데 못 한다" 고 적어 둔 것들이다. 비어 있지 않으면
  //: 자리와 표시 형식이 다 맞아도 **재현이 끝난 것이 아니다.**
  const missingSupport = (requiredUnsupported || []).slice();
  const allOk = checks.every(c => c.ok) && crossCheck.every(c => c.ok)
                && problems.length === 0;
  return {
    checks, crossCheck, problems, positions,
    missing_support: missingSupport,
    allOk,
    //: 🔴 **자리가 맞았다 ≠ 그대로 재현됐다.**
    fullyReproduced: allOk && positions.ok && missingSupport.length === 0,
  };
}

module.exports = { normalizeZone, sameZone, identityOf, compareFinal,
                   decideMove, decideMenu, movedBetween,
                   decidePosition, comparePositions };
