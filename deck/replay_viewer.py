"""
전개 뷰어 — 실행 기록 하나를 **브라우저에서 한 걸음씩** 보는 정적 HTML
(Phase 6-AU).

무엇이고 무엇이 아닌가
----------------------
🔴 **듀얼 엔진이 아니다.** 규칙을 판정하지 않고, 카드 효과를 모르고,
난수를 쓰지 않는다. 하는 일은 ``deck.replay_export`` 가 적어 둔 기록
(``engine-replay/1`` · ``/2``) 을 **읽어서 그리는 것** 하나다. 그래서
화면에 나오는 모든 이동은 **엔진이 실제로 적은 사건**이고, 기록에 없는
이동은 화면에도 없다.

🔴 **외부 Duel Simulator 연동과는 별개다.** 그 사이트는 덱 이미지를 올려
사람이 손으로 盤面을 만드는 도구이고 (``docs/
duel-simulator-replay-integration.md``), 이 뷰어는 이 저장소의 기록을
그대로 여는 자리다. 둘은 서로를 대신하지 않는다.

어떻게 그리는가
---------------
기록의 ``initial.zones`` 에서 출발해 ``events`` 를 **순서대로** 적용한다.
걸음(frame)은 **사건 하나**씩이다 — 그래야 「비용 지불」과 「효과 해결」이
서로 다른 화면이 된다. 0번 걸음은 아무 사건도 적용하지 않은 **시작 판**
이다.

🔴 **앞뒤로 움직여도 같은 상태가 나온다.** 걸음을 옮길 때마다 시작 판에서
다시 쌓는다 (되돌리기 연산을 만들지 않는다). 엔진을 다시 부르지도, 난수를
쓰지도 않는다.

🔴 **모르는 것은 모른다고 그린다.**

====================================  ================================
기록에 있는 것                         화면
====================================  ================================
``monster_summoned`` 의 칸 번호 ·      그 자리에 그린다
표시 형식
``zone_moved`` (칸 번호 없음)          존 안에 두되 칸을 확정하지 않는다
덱 섞기 뒤의 덱 순서                   「순서 미기록」 으로 적는다
``token_vanished``                     판에서 **사라진다** (묘지가 아니다)
수락되지 않은 걸음                     사건이 없으므로 **아무것도 움직이지
                                      않는다**
====================================  ================================

안전
----
🔴 **기록을 코드로 넣지 않는다.** JSON 은 ``<script
type="application/json">`` 안에 들어가고 (브라우저가 실행하지 않는다),
화면의 모든 글자는 ``textContent`` 로만 넣는다. 카드 이름 · 사유 문자열에
무엇이 들어 있든 HTML 로 해석되지 않는다.
"""

from __future__ import annotations

import json

from deck.replay_export import REPLAY_FORMATS_READ

__all__ = ["render_replay_html", "VIEWER_TITLE"]

VIEWER_TITLE = "갈라테아 전개 뷰어"


def _embed(record) -> str:
    """
    기록을 ``<script type="application/json">`` 에 넣을 수 있게 만든다.

    🔴 ``</`` 를 끊어 둔다 — 그 두 글자만이 스크립트 태그를 **밖에서**
    닫을 수 있고, 그것을 막으면 기록의 어떤 글자도 태그 구조를 바꾸지
    못한다. ``json.dumps`` 가 만든 문자열 안에서 ``<\\/`` 는 같은 값이다.
    """
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("</", "<\\/")


_STYLE = """
:root {
  --bg: #11131a; --panel: #1a1d27; --line: #2c3040; --ink: #e8eaf2;
  --dim: #9aa0b5; --hot: #ffcc55; --move: #4fc3f7; --cost: #ff8a7a;
  --mat: #b388ff; --tgt: #7bdc9a;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font-family: system-ui, "Noto Sans KR", sans-serif; font-size: 14px; }
header { padding: 12px 16px; border-bottom: 1px solid var(--line);
         display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
h1 { font-size: 16px; margin: 0; font-weight: 700; }
.muted { color: var(--dim); }
button { background: var(--panel); color: var(--ink);
         border: 1px solid var(--line); border-radius: 6px;
         padding: 6px 12px; cursor: pointer; font-size: 14px; }
button:disabled { opacity: .4; cursor: default; }
button.primary { background: #2a3550; }
main { display: grid; grid-template-columns: 1fr 320px; gap: 14px;
       padding: 14px 16px; align-items: start; }
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
.board { display: grid; gap: 10px; }
.seat { border: 1px solid var(--line); border-radius: 8px; padding: 10px;
        background: var(--panel); }
.seat h2 { font-size: 13px; margin: 0 0 8px; color: var(--dim);
           font-weight: 600; }
.row { display: grid; gap: 6px; margin-bottom: 6px; }
.row.five { grid-template-columns: repeat(5, 1fr); }
.row.piles { grid-template-columns: repeat(5, 1fr); }
.slot { min-height: 74px; border: 1px dashed var(--line); border-radius: 6px;
        padding: 4px; }
.slot .label { font-size: 10px; color: var(--dim); }
.pile { min-height: 74px; border: 1px solid var(--line); border-radius: 6px;
        padding: 6px; background: #151822; }
.pile .label { font-size: 11px; color: var(--dim); margin-bottom: 4px; }
.cards { display: flex; flex-wrap: wrap; gap: 4px; }
.card { border: 1px solid var(--line); border-radius: 5px; padding: 4px 6px;
        background: #202536; min-width: 92px; max-width: 150px;
        cursor: pointer; line-height: 1.25; }
.card .nm { font-size: 11px; font-weight: 600; word-break: keep-all; }
.card .ty { font-size: 10px; color: var(--dim); }
.card.sel { outline: 2px solid var(--hot); }
.card.move { border-color: var(--move); box-shadow: 0 0 0 1px var(--move); }
.card.cost { border-color: var(--cost); box-shadow: 0 0 0 1px var(--cost); }
.card.mat  { border-color: var(--mat);  box-shadow: 0 0 0 1px var(--mat); }
.card.tgt  { border-color: var(--tgt);  box-shadow: 0 0 0 1px var(--tgt); }
.card .tag { font-size: 9px; border-radius: 3px; padding: 0 3px;
             margin-right: 3px; }
aside { display: grid; gap: 10px; }
.box { border: 1px solid var(--line); border-radius: 8px; padding: 10px;
       background: var(--panel); }
.box h3 { font-size: 12px; margin: 0 0 6px; color: var(--dim); }
.stepline { font-size: 15px; font-weight: 600; }
.legend span { margin-right: 10px; font-size: 11px; }
details { border: 1px solid var(--line); border-radius: 8px; padding: 8px;
          background: var(--panel); }
summary { cursor: pointer; font-size: 12px; color: var(--dim); }
pre { white-space: pre-wrap; word-break: break-all; font-size: 11px;
      color: var(--dim); margin: 8px 0 0; }
ul { margin: 6px 0 0; padding-left: 18px; }
li { margin-bottom: 4px; font-size: 12px; }
.warn { color: var(--hot); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
       margin-right: 4px; vertical-align: middle; }
"""

#: 🔴 **스크립트는 기록을 데이터로만 읽는다.** 화면의 글자는 전부
#: ``textContent`` 로 들어가므로, 기록 안의 어떤 글자도 HTML 이 되지 않는다.
_SCRIPT = r"""
'use strict';
var FORMATS = __FORMATS__;
var ZONES_MAIN = ['MZONE', 'EMZONE', 'SZONE'];
var PILES = [['HAND', '패'], ['DECK', '덱'], ['EXTRA', '엑스트라 덱'],
             ['GRAVE', '묘지'], ['REMOVED', '제외']];
var ZONE_KO = {MZONE: '몬스터 존', EMZONE: '엑스트라 몬스터 존',
               SZONE: '마법·함정 존', HAND: '패', DECK: '덱',
               EXTRA: '엑스트라 덱', GRAVE: '묘지', REMOVED: '제외',
               FZONE: '필드 존'};
var POS_KO = {FACEUP_ATTACK: '앞면 공격', FACEUP_DEFENSE: '앞면 수비',
              FACEDOWN_DEFENSE: '뒷면 수비', FACEDOWN: '뒷면'};
var KIND_KO = {monster: '몬스터', spell: '마법', trap: '함정'};
var STEP_KO = {normal_summon: '일반 소환', link_summon: '링크 소환',
               special_summon: '특수 소환', activate_effect: '효과 발동',
               set_spell_trap: '마법·함정 세트', end_phase: '턴 종료',
               pass: '패스'};

var state = {record: null, frames: [], at: 0, selected: null};

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

function cardName(rec, id) {
  var c = rec.cards[String(id)];
  if (!c) { return '#' + id; }
  return c.name || ('[' + c.passcode + ']');
}
function cardType(rec, id) {
  var c = rec.cards[String(id)];
  if (!c) { return '미기록'; }
  if (c.type_ko) { return c.type_ko; }
  if (c.kind) { return KIND_KO[c.kind] || c.kind; }
  return '종류 미기록';
}

/* ---------- 기록 → 걸음들 --------------------------------------- */
function buildFrames(rec) {
  var where = {};        /* instance -> {seat, zone, index, position} */
  var order = [];        /* 화면에 그릴 때 쓰는 등장 순서 */
  function place(id, seat, zone, index, position) {
    if (!where[id]) { order.push(id); }
    where[id] = {seat: String(seat), zone: zone,
                 index: (index === undefined ? null : index),
                 position: (position === undefined ? null : position)};
  }
  var zones = (rec.initial && rec.initial.zones) || {};
  Object.keys(zones).forEach(function (seat) {
    Object.keys(zones[seat]).forEach(function (zone) {
      zones[seat][zone].forEach(function (id) { place(id, seat, zone, null, null); });
    });
  });

  function snapshot() {
    var copy = {};
    Object.keys(where).forEach(function (k) {
      copy[k] = {seat: where[k].seat, zone: where[k].zone,
                 index: where[k].index, position: where[k].position};
    });
    return copy;
  }

  /* 걸음 ↔ 사건: 사건 번호로 되돌려 찾는다 */
  var stepOf = {};
  (rec.steps || []).forEach(function (st) {
    (st.events || []).forEach(function (seq) { stepOf[seq] = st; });
  });

  var frames = [{seq: -1, step: null, kind: 'start', title: '시작 상태',
                 text: '아직 아무 행동도 하지 않았습니다.',
                 where: snapshot(), roles: {}, notes: [], shuffled: {}}];
  /* 🔴 섞인 자리만 「순서 미기록」 이다 — 상대 덱까지 싸잡지 않는다 */
  var shuffled = {};

  (rec.events || []).forEach(function (ev) {
    var roles = {}, notes = [];
    var role = ev.type === 'cost_payment' ? 'cost'
             : ev.type === 'effect' ? 'move' : 'move';
    var st = stepOf[ev.seq] || null;
    if (st && st.kind === 'link_summon') { role = 'mat'; }

    (ev.changes || []).forEach(function (ch) {
      if (ch.kind === 'zone_moved' || ch.kind === 'card_drawn') {
        place(ch.instance, (ch.to.player === undefined ? 0 : ch.to.player),
              ch.to.zone, null, null);
        roles[ch.instance] = role;
      } else if (ch.kind === 'monster_summoned') {
        place(ch.instance, ch.player, ch.to.zone, ch.to.index, ch.to.position);
        roles[ch.instance] = (role === 'mat') ? 'move' : role;
      } else if (ch.kind === 'token_created') {
        notes.push('토큰이 생겼습니다 — ' + cardName(rec, ch.instance));
        roles[ch.instance] = 'move';
      } else if (ch.kind === 'token_vanished') {
        if (where[ch.instance]) { delete where[ch.instance]; }
        notes.push('토큰이 판에서 사라졌습니다 (묘지로 가지 않습니다) — '
                   + cardName(rec, ch.instance));
      } else if (ch.kind === 'zone_shuffled') {
        shuffled[String(ch.player) + '/' + ch.zone] = true;
        notes.push('P' + ch.player + ' 의 ' + (ZONE_KO[ch.zone] || ch.zone)
                   + ' 를 섞었습니다 (' + ch.size
                   + '장) — 섞은 뒤의 순서는 기록에 없습니다.');
      } else if (ch.kind === 'special_summon_limited') {
        notes.push('특수 소환 제한이 걸렸습니다 — ' + ch.attribute
                   + ' 속성만 (출처 ' + ch.source_card_id + ')');
      } else if (ch.kind === 'life_changed') {
        notes.push('라이프가 바뀌었습니다.');
      } else if (ch.kind === 'phase_changed') {
        notes.push('페이즈가 바뀌었습니다.');
      }
    });

    /* 효과의 대상은 걸음이 들고 있다 */
    if (st && st.targets) {
      st.targets.forEach(function (t) {
        var m = /#(\d+)/.exec(String(t));
        if (m) { var id = Number(m[1]); if (!roles[id]) { roles[id] = 'tgt'; } }
      });
    }
    frames.push({seq: ev.seq, step: st, kind: ev.type,
                 title: frameTitle(rec, ev, st),
                 text: frameText(rec, ev, st),
                 where: snapshot(), roles: roles, notes: notes,
                 shuffled: Object.assign({}, shuffled)});
  });
  return frames;
}

function frameTitle(rec, ev, st) {
  var head = ev.type === 'cost_payment' ? '비용 지불'
           : ev.type === 'effect' ? '효과 해결' : '행동';
  if (st) {
    var k = STEP_KO[st.kind] || st.kind;
    var nm = st.card ? (st.card.name || ('[' + st.card.passcode + ']')) : '';
    return '걸음 ' + st.order + ' · ' + k + (nm ? ' — ' + nm : '')
           + ' · ' + head;
  }
  return head;
}

function frameText(rec, ev, st) {
  var bits = [];
  (ev.changes || []).forEach(function (ch) {
    if (ch.kind === 'zone_moved' || ch.kind === 'card_drawn') {
      bits.push(cardName(rec, ch.instance) + ' 를 '
                + (ZONE_KO[ch.from.zone] || ch.from.zone) + ' 에서 '
                + (ZONE_KO[ch.to.zone] || ch.to.zone) + ' 로 옮겼습니다.');
    } else if (ch.kind === 'monster_summoned') {
      bits.push(cardName(rec, ch.instance) + ' 를 '
                + (ZONE_KO[ch.to.zone] || ch.to.zone) + ' 에 놓았습니다 ('
                + (POS_KO[ch.to.position] || ch.to.position) + ').');
    }
  });
  if (!bits.length) { bits.push('판의 자리는 바뀌지 않았습니다.'); }
  if (st && st.effect_ref && ev.type !== 'action') {
    bits.push('효과: ' + st.effect_ref);
  }
  if (ev.payments && ev.payments.length) {
    bits.push('비용 기록: ' + ev.payments.join(' · '));
  }
  if (st && st.materials && st.materials.length && ev.type === 'action') {
    bits.push('링크 소재: ' + st.materials.join(' · '));
  }
  return bits.join(' ');
}

/* ---------- 그리기 ------------------------------------------------ */
function cardNode(rec, id, role, frame) {
  var n = el('div', 'card');
  if (role) { n.classList.add(role); }
  if (state.selected === id) { n.classList.add('sel'); }
  var nm = el('div', 'nm', cardName(rec, id));
  var ty = el('div', 'ty', cardType(rec, id) + ' · #' + id);
  n.appendChild(nm); n.appendChild(ty);
  var w = frame.where[id];
  if (w && w.position) {
    n.appendChild(el('div', 'ty', POS_KO[w.position] || w.position));
  }
  n.addEventListener('click', function () {
    state.selected = (state.selected === id) ? null : id;
    render();
  });
  return n;
}

function seatNode(rec, frame, seat, label) {
  var box = el('div', 'seat');
  box.appendChild(el('h2', null, label));
  var byZone = {};
  Object.keys(frame.where).forEach(function (id) {
    var w = frame.where[id];
    if (w.seat !== String(seat)) { return; }
    (byZone[w.zone] = byZone[w.zone] || []).push(Number(id));
  });

  ZONES_MAIN.forEach(function (zone) {
    var row = el('div', 'row five');
    var here = byZone[zone] || [];
    var slots = zone === 'EMZONE' ? 2 : 5;
    for (var i = 0; i < slots; i++) {
      var slot = el('div', 'slot');
      slot.appendChild(el('div', 'label',
        (ZONE_KO[zone] || zone) + ' ' + (i + 1)));
      here.forEach(function (id) {
        var w = frame.where[id];
        if (w.index === i) { slot.appendChild(cardNode(rec, id, frame.roles[id], frame)); }
      });
      row.appendChild(slot);
    }
    var loose = here.filter(function (id) { return frame.where[id].index === null; });
    box.appendChild(row);
    if (loose.length) {
      var p = el('div', 'pile');
      p.appendChild(el('div', 'label',
        (ZONE_KO[zone] || zone) + ' — 칸 번호 미기록 ' + loose.length + '장'));
      var cs = el('div', 'cards');
      loose.forEach(function (id) { cs.appendChild(cardNode(rec, id, frame.roles[id], frame)); });
      p.appendChild(cs); box.appendChild(p);
    }
  });

  var piles = el('div', 'row piles');
  PILES.forEach(function (pair) {
    var zone = pair[0], name = pair[1];
    var here = byZone[zone] || [];
    var p = el('div', 'pile');
    var label = name + ' ' + here.length + '장';
    if (frame.shuffled[String(seat) + '/' + zone]) {
      label += ' · 섞은 뒤 순서 미기록';
    }
    p.appendChild(el('div', 'label', label));
    var cs = el('div', 'cards');
    if (zone === 'DECK') {
      /* 덱은 가려진 자리다 — 장수만 적는다 */
      cs.appendChild(el('div', 'ty', '뒷면 ' + here.length + '장'));
    } else {
      here.forEach(function (id) { cs.appendChild(cardNode(rec, id, frame.roles[id], frame)); });
    }
    p.appendChild(cs); piles.appendChild(p);
  });
  box.appendChild(piles);
  return box;
}

function render() {
  var rec = state.record;
  var board = document.getElementById('board');
  clear(board);
  if (!rec) {
    board.appendChild(el('div', 'box', '전개 기록(JSON)을 열면 여기에 판이 '
      + '그려집니다. 위의 “기록 열기” 를 누르세요.'));
    document.getElementById('stepline').textContent = '';
    document.getElementById('stepsub').textContent = '';
    return;
  }
  var frame = state.frames[state.at];
  board.appendChild(seatNode(rec, frame, 1, '상대 (P1)'));
  board.appendChild(seatNode(rec, frame, 0, '자신 (P0)'));

  document.getElementById('stepline').textContent =
    '걸음 ' + state.at + ' / ' + (state.frames.length - 1) + ' — ' + frame.title;
  document.getElementById('stepsub').textContent = frame.text;

  var notes = document.getElementById('notes');
  clear(notes);
  frame.notes.forEach(function (t) { notes.appendChild(el('li', null, t)); });

  var sel = document.getElementById('selected');
  clear(sel);
  if (state.selected !== null && rec.cards[String(state.selected)]) {
    var c = rec.cards[String(state.selected)];
    sel.appendChild(el('div', 'stepline', c.name || ('[' + c.passcode + ']')));
    sel.appendChild(el('div', 'muted', '패스코드 ' + c.passcode
      + ' · 개체 #' + state.selected));
    sel.appendChild(el('div', 'muted', cardType(rec, state.selected)
      + (c.token ? ' · 토큰' : '')));
    var w = frame.where[state.selected];
    sel.appendChild(el('div', 'muted', w
      ? ('지금: P' + w.seat + ' ' + (ZONE_KO[w.zone] || w.zone)
         + (w.index === null ? ' (칸 번호 미기록)' : ' ' + (w.index + 1) + '칸')
         + (w.position ? ' · ' + (POS_KO[w.position] || w.position) : ''))
      : '지금: 판에 없습니다'));
  } else {
    sel.appendChild(el('div', 'muted', '카드를 누르면 이름과 패스코드를 봅니다.'));
  }

  document.getElementById('first').disabled = state.at === 0;
  document.getElementById('prev').disabled = state.at === 0;
  document.getElementById('next').disabled = state.at >= state.frames.length - 1;
}

function summarize(rec) {
  var r = rec.result || {};
  var head = document.getElementById('result');
  clear(head);
  var status = r.status === 'completed' ? '✅ 전개 완료'
             : r.status === 'stopped' ? '⏹ 중단'
             : r.status === 'not_run' ? '❌ 실행하지 않음' : '▶ 실행함';
  var src = rec.source || {};
  var way = src.mode === 'line' ? ('고정 경로 ' + (src.line || '')) : '자율 실행';
  head.appendChild(el('div', 'stepline', status + ' · ' + way));
  if (r.line_total) {
    head.appendChild(el('div', 'muted',
      (r.line_done || 0) + ' / ' + r.line_total + '단계'));
  }
  if (r.stopped_reason && r.status !== 'completed') {
    head.appendChild(el('div', 'warn', '중단 사유: ' + r.stopped_reason));
  }
  var limits = (rec.final && rec.final.summon_limits) || [];
  if (limits.length) {
    head.appendChild(el('div', 'muted', '특수 소환 제한 ' + limits.length
      + '건 — ' + limits.map(function (l) {
          return l.attribute + ' (출처 ' + l.source + ')'; }).join(' · ')));
  }
  var un = document.getElementById('unsupported');
  clear(un);
  (rec.unsupported || []).forEach(function (t) {
    un.appendChild(el('li', null, t));
  });
  document.getElementById('unsupported-count').textContent =
    '미지원 ' + ((rec.unsupported || []).length) + '건 — 규칙이 막은 것이 '
    + '아니라 이 저장소에 그 규칙이 없다는 뜻입니다 (펼쳐 보기)';
  document.getElementById('rawjson').textContent =
    JSON.stringify(rec, null, 1);
}

function load(rec) {
  if (!rec || FORMATS.indexOf(rec.format) < 0) {
    alert('읽을 수 있는 전개 기록이 아닙니다 (format: '
          + (rec && rec.format) + ').');
    return;
  }
  state.record = rec;
  state.frames = buildFrames(rec);
  state.at = 0;
  state.selected = null;
  summarize(rec);
  render();
}

window.addEventListener('DOMContentLoaded', function () {
  document.getElementById('first').addEventListener('click', function () {
    state.at = 0; render(); });
  document.getElementById('prev').addEventListener('click', function () {
    if (state.at > 0) { state.at--; render(); } });
  document.getElementById('next').addEventListener('click', function () {
    if (state.at < state.frames.length - 1) { state.at++; render(); } });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') { document.getElementById('prev').click(); }
    if (e.key === 'ArrowRight') { document.getElementById('next').click(); }
  });
  document.getElementById('file').addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0];
    if (!f) { return; }
    var reader = new FileReader();
    reader.onload = function () {
      try { load(JSON.parse(String(reader.result))); }
      catch (err) { alert('JSON 을 읽지 못했습니다: ' + err.message); }
    };
    reader.readAsText(f);
  });
  var node = document.getElementById('replay-data');
  if (node && node.textContent.trim()) {
    try { load(JSON.parse(node.textContent)); }
    catch (err) { alert('담아 둔 기록을 읽지 못했습니다: ' + err.message); }
  } else {
    render();
  }
});
"""


def render_replay_html(record=None, *, title: str = VIEWER_TITLE) -> str:
    """
    뷰어 HTML 한 장. ``record`` 를 주면 **그 기록을 담은 단일 파일**이다.

    🔴 **서버가 필요 없다.** 바깥에서 받아 오는 자원이 하나도 없으므로
    파일을 그대로 브라우저에서 열면 된다. ``record`` 를 주지 않으면 화면에서
    JSON 파일을 골라 여는 뷰어가 된다.
    """
    data = _embed(record) if record else ""
    script = _SCRIPT.replace("__FORMATS__", json.dumps(list(REPLAY_FORMATS_READ)))
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_text(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
  <h1>{_text(title)}</h1>
  <span class="muted">엔진이 적은 실행 기록을 그대로 그립니다 —
    규칙을 판정하지 않습니다.</span>
  <label class="muted">기록 열기
    <input id="file" type="file" accept="application/json,.json">
  </label>
</header>
<main>
  <section>
    <div class="box">
      <div id="stepline" class="stepline"></div>
      <div id="stepsub" class="muted"></div>
      <div style="margin-top:8px">
        <button id="first">처음으로</button>
        <button id="prev">← 이전 단계</button>
        <button id="next" class="primary">다음 단계 →</button>
      </div>
      <ul id="notes"></ul>
    </div>
    <div id="board" class="board" style="margin-top:12px"></div>
  </section>
  <aside>
    <div class="box" id="result"></div>
    <div class="box">
      <h3>선택한 카드</h3>
      <div id="selected"></div>
    </div>
    <div class="box legend">
      <h3>강조 표시</h3>
      <span><i class="dot" style="background:#4fc3f7"></i>이동</span>
      <span><i class="dot" style="background:#ff8a7a"></i>비용</span>
      <span><i class="dot" style="background:#b388ff"></i>링크 소재</span>
      <span><i class="dot" style="background:#7bdc9a"></i>효과 대상</span>
    </div>
    <details>
      <summary id="unsupported-count">미지원</summary>
      <ul id="unsupported"></ul>
    </details>
    <details>
      <summary>전개 기록 원본 (JSON)</summary>
      <pre id="rawjson"></pre>
    </details>
  </aside>
</main>
<script id="replay-data" type="application/json">{data}</script>
<script>{script}</script>
</body>
</html>
"""


def _text(value: str) -> str:
    """제목처럼 HTML 안에 직접 들어가는 짧은 글자만 쓰는 최소 이스케이프."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
