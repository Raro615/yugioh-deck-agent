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
 * 이력의 한 줄이 **이 카드의 줄인가**.
 *
 * 판 위 카드의 그림(``src``)과 이력 줄의 썸네일이 같은지로 본다 — 실측에서
 * 둘은 바이트 단위로 같다. 🔴 같은 그림이 둘 이상이면 **모호하다고
 * 적는다**: 맞았다고 하지 않고, 부르는 쪽이 그 사실을 결과에 남긴다.
 */
function identityOf(row, wantSrc, srcOf) {
  if (!row || !row.srcs || !row.srcs.length) {
    return { ok: false, how: '이력 줄에 썸네일이 없습니다' };
  }
  if (!wantSrc) { return { ok: false, how: '카드 그림을 읽지 못했습니다' }; }
  if (!row.srcs.includes(wantSrc)) {
    return { ok: false, how: '이력의 썸네일이 이 카드의 그림과 다릅니다' };
  }
  const same = Object.keys(srcOf || {}).filter(s => srcOf[s] === wantSrc);
  return same.length > 1
    ? { ok: true, how: `그림이 같은 자리 ${same.length}개 (모호)` }
    : { ok: true, how: '썸네일 일치' };
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
 */
function compareFinal(expectFinal, observed, counts) {
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
  return {
    checks, crossCheck, problems,
    allOk: checks.every(c => c.ok) && crossCheck.every(c => c.ok)
           && problems.length === 0,
  };
}

module.exports = { normalizeZone, identityOf, compareFinal };
