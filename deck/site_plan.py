"""
외부 Duel Simulator 조작 계획 — 실행 기록 하나를 **사이트에서 할 조작의
목록**으로 바꾼다 (Phase 6-AX).

무엇이고 무엇이 아닌가
----------------------
🔴 **정식 입력은 엔진의 실행 기록이다.** 사람이 읽으라고 쓴 설명문
(``reason`` · ``resolution_choices``) 을 해석해서 조작을 정하지 않는다.
조작 하나하나가 기록의 **사건(event) 또는 걸음(step)** 에서 나오고, 계획의
``basis`` 칸이 어느 것에서 나왔는지 적는다.

🔴 **사이트는 규칙 판정기가 아니다.** 여기서 만든 조작을 사이트가 그대로
수행한다고 해서 그 움직임이 공식 규칙에서 적법하다는 뜻이 아니다. 적법성은
이 저장소의 엔진이 판정한 것이고, 사이트는 그것을 **보여 줄 뿐**이다.

🔴 **이 경로 전용이 아니다.** 카드 이름도 전개 순서도 코드에 적지 않는다 —
기록에 있는 것만 읽는다. 다만 :func:`build_site_plan` 이 다루는 사건 종류는
아래 표가 전부이고, 그 밖의 사건은 **조용히 빠지지 않고**
``plan["unsupported"]`` 에 남는다.

================================  ==========================================
기록의 사건                        사이트 조작
================================  ==========================================
``monster_summoned``               끌어 놓기 (칸 번호가 있으므로 그 칸으로)
``zone_moved`` · ``card_drawn``    끌어 놓기 (칸 번호가 없으므로 존으로)
걸음 ``activate_effect``           우클릭 → Activate Effect
걸음의 ``targets``                 우클릭 → Target
``special_summon_limited`` 등      조작 없음 — 사이트에 그 개념이 없다
================================  ==========================================

덱 자리 배정
------------
사이트는 **덱 이미지에서 잘라낸 카드**만 판에 올릴 수 있다. 그래서 계획은
기록의 개체(instance) 하나하나를 덱 이미지의 **자리**(``main-0`` ·
``extra-2`` …) 에 미리 묶어 둔다. 자리는 기록의 시작 판에서 그대로 나온다 —

* ``main-0`` … ``main-4`` = 시작 패 5장 (기록의 ``initial.zones`` 순서)
* ``main-5`` 이후 = 시작 덱 (기록 순서)
* ``extra-0`` 이후 = 엑스트라 덱 (기록 순서)

그래서 사이트의 「왼쪽 위 5장을 패로」 가 **기록의 시작 패와 정확히 같다**.
🔴 같은 이름의 카드가 여러 장이어도 자리가 다르므로 섞이지 않는다.
"""

from __future__ import annotations

__all__ = [
    "PLAN_FORMAT", "SITE_ZONE", "build_site_plan", "plan_json",
    "render_deck_sheet_html",
]

import json

PLAN_FORMAT = "duel-simulator-plan/1"

#: 엔진 존 → 사이트 존 이름. 🔴 사이트가 History 줄에 쓰는 **그 글자**다
#: (실측으로 확인했다). 칸 번호가 있는 존은 번호를 뒤에 붙인다.
SITE_ZONE = {
    "HAND": "Hand",
    "DECK": "Deck",
    "EXTRA": "Extra Deck",
    "GRAVE": "Grave",
    "REMOVED": "Banish",
    "FZONE": "Field Zone",
    "MZONE": "Monster Zone{index}",
    "EMZONE": "Extra Monster Zone{index}",
    "SZONE": "Spell & Trap Zone{index}",
}

#: 🔴 **좌석별 EMZONE → 공유 2칸의 대응.** 엔진은 좌석마다 ``EMZONE`` 1칸을
#: 갖고, 사이트는 공유 2칸을 ``Extra Monster Zone1`` · ``2`` 로 부른다.
#: 자신(좌석 0) 을 1번 칸에 묶는다 — 같은 자리를 양쪽에 만들지 않는다.
EMZONE_SLOT_FOR_SEAT = {0: 1, 1: 2}

_MOVE_KINDS = ("zone_moved", "card_drawn", "monster_summoned")
#: 판을 바꾸지만 사이트에 대응 조작이 **없는** 사건들. 조용히 빠뜨리지 않고
#: 계획의 ``unsupported`` 에 적는다.
_NO_SITE_OPERATION = {
    "special_summon_limited": "특수 소환 제한 등록 — 사이트에 그 표현이 없습니다",
    "zone_shuffled": "덱 섞기 — 사이트의 덱은 순서를 따로 다루지 않습니다",
    "life_changed": "라이프 변화 — 이 계획은 라이프를 건드리지 않습니다",
    "phase_changed": "페이즈 변화 — 이 계획은 페이즈를 건드리지 않습니다",
    "token_created": "토큰 생성 — 덱 이미지에 없는 카드라 자리를 묶을 수 없습니다",
    "token_vanished": "토큰 소멸 — 위와 같습니다",
}


def _zone_name(zone: str, index=None, seat: int = 0) -> str:
    """사이트가 쓰는 존 이름 한 줄. 칸 번호를 모르면 **지어내지 않는다**."""
    template = SITE_ZONE.get(zone)
    if template is None:
        return zone
    if "{index}" not in template:
        return template
    if zone == "EMZONE":
        return template.format(index=EMZONE_SLOT_FOR_SEAT.get(int(seat), 1))
    if index is None:
        #: 🔴 칸 번호가 기록에 없다 — 1번 칸으로 **확정하지 않는다**. 번호
        #: 없는 존 이름만 돌려주고, 확인은 **도착지**로만 한다.
        return template.format(index="").strip()
    return template.format(index=int(index) + 1)


# ======================================================================
# 덱 자리
# ======================================================================
def _deck_slots(record, registration=None):
    """
    기록의 시작 판 → 덱 이미지의 자리들.

    등록된 덱 이미지가 **없으면** (자리표시 시트 모드) 시작 패가 맨 앞에
    오도록 자리를 매긴다 — 시트를 우리가 굽기 때문에 그렇게 만들 수 있다.

    🔴 등록된 이미지가 **있으면** 그 순서를 그대로 쓴다. 사용자에게
    "이미지의 카드 순서를 바꿔 달라" 고 요구하지 않는다 —
    :func:`deck.deck_image_registry.assign_slots` 가 패스코드로 자리를
    찾는다.
    """
    cards = record.get("cards") or {}
    zones = ((record.get("initial") or {}).get("zones") or {}).get("0") or {}

    def _entry(instance, where: str, slot: str) -> dict:
        card = cards.get(str(instance)) or {}
        return {
            "instance": int(instance),
            "passcode": card.get("passcode"),
            "name": card.get("name"),
            "kind": card.get("kind"),
            "where": where,
            "slot": slot,
        }

    if registration is None:
        main = [_entry(i, "hand", f"main-{n}")
                for n, i in enumerate(zones.get("HAND") or ())]
        offset = len(main)
        main += [_entry(i, "deck", f"main-{offset + n}")
                 for n, i in enumerate(zones.get("DECK") or ())]
        extra = [_entry(i, "extra", f"extra-{n}")
                 for n, i in enumerate(zones.get("EXTRA") or ())]
        at = {entry["instance"]: entry["slot"] for entry in main + extra}
        return main, extra, at, (), ()

    from deck.deck_image_registry import assign_slots

    assignment = assign_slots(record, registration)
    at = dict(assignment.by_instance)
    main, extra = [], []
    for where, key in (("hand", "HAND"), ("deck", "DECK"), ("extra", "EXTRA")):
        for instance in zones.get(key) or ():
            slot = at.get(int(instance))
            if slot is None:
                continue
            (extra if slot.startswith("extra-") else main).append(
                _entry(instance, where, slot))
    return main, extra, at, assignment.problems, assignment.notes


# ======================================================================
# ======================================================================
# 조작
# ======================================================================
def build_site_plan(record, registration=None) -> dict:
    """
    실행 기록 하나 → 사이트 조작 계획 하나.

    🔴 **기록에 없는 조작을 만들지 않는다.** 발동은 걸음이
    ``activate_effect`` 일 때만, 대상 표시는 걸음에 ``targets`` 가 있을 때만
    나온다. 사이트에 대응이 없는 사건은 ``unsupported`` 에 남는다.
    """
    main, extra, slot_of, slot_problems, slot_notes = _deck_slots(
        record, registration)
    cards = record.get("cards") or {}
    events = {int(event["seq"]): event for event in (record.get("events") or ())}
    unsupported: list[str] = list(slot_problems)

    def _label(instance) -> str:
        card = cards.get(str(instance)) or {}
        return card.get("name") or f"[{card.get('passcode')}]"

    _missing_said = [False]

    def _slot(instance) -> "str | None":
        got = slot_of.get(int(instance))
        if got is None and not _missing_said[0]:
            #: 🔴 같은 말을 사건마다 되풀이하지 않는다 — 한 번만 적는다.
            _missing_said[0] = True
            unsupported.append(
                f"개체 #{instance} ({_label(instance)}) 에 줄 자리를 "
                + ("등록한 덱 이미지에서 찾지 못했습니다"
                   if registration is not None else "시작 판에서 찾지 못했습니다")
                + " — 이 개체가 나오는 조작은 계획에서 빠집니다."
            )
        return got

    setup = [
        {"op": "move", "card": entry["slot"], "from": "Deck", "to": "Hand",
         "why": f"시작 패 — {entry['name'] or entry['passcode']}",
         "basis": "engine:initial.zones[0].HAND"}
        for entry in main if entry["where"] == "hand"
    ]

    operations: list[dict] = []

    def _emit(**fields) -> None:
        fields["n"] = len(operations) + 1
        operations.append(fields)

    for step in record.get("steps") or ():
        step_events = [events[seq] for seq in (step.get("events") or ())
                       if seq in events]
        if not step_events:
            #: 🔴 사건이 없는 걸음은 판을 바꾸지 않았다 — 조작도 없다.
            continue
        order = step.get("order")

        if step.get("kind") == "activate_effect":
            source = step_events[0].get("source")
            slot = _slot(source) if source is not None else None
            if slot:
                _emit(op="activate", card=slot, step=order,
                      event=step_events[0].get("seq"),
                      why=f"효과 발동 — {_label(source)}",
                      expect="Activate Effect",
                      basis=f"engine:step#{order}.kind=activate_effect, "
                            f"event#{step_events[0].get('seq')}.source")
            for raw in step.get("targets") or ():
                digits = "".join(ch for ch in str(raw) if ch.isdigit())
                if not digits:
                    continue
                target_slot = _slot(int(digits))
                if target_slot:
                    _emit(op="target", card=target_slot, step=order,
                          why=f"대상 — {_label(int(digits))}",
                          expect="Target",
                          basis=f"engine:step#{order}.targets={raw!r}")

        for event in step_events:
            for change in event.get("changes") or ():
                kind = change.get("kind")
                if kind not in _MOVE_KINDS:
                    note = _NO_SITE_OPERATION.get(kind)
                    unsupported.append(
                        f"사건 #{event.get('seq')} 의 {kind}: "
                        + (note or "이 계획이 다루지 않는 사건입니다")
                    )
                    continue
                instance = change.get("instance")
                slot = _slot(instance)
                if not slot:
                    continue
                source = change.get("from") or {}
                target = change.get("to") or {}
                seat = target.get("player", change.get("player", 0))
                #: 🔴 **확인은 도착지로만 한다.** 출발지의 칸 번호는 기록에
                #: 없을 때가 있어서(``zone_moved``), 그것으로 맞추려 들면
                #: 없는 정보를 확정한 셈이 된다.
                to_zone = _zone_name(target.get("zone"), target.get("index"),
                                     seat=seat)
                from_zone = _zone_name(source.get("zone"),
                                       seat=source.get("player", 0))
                _emit(op="move", card=slot, step=order,
                      event=event.get("seq"),
                      **{"from": from_zone},
                      to=to_zone,
                      why=f"{_label(instance)} 이동",
                      expect=f"→ {to_zone}",
                      basis=f"engine:event#{event.get('seq')}.{kind}")

    #: 🔴 **엔진 행동 수와 재생 장면 수를 섞지 않는다** (요청 §3).
    counts = {
        "engine_steps": len(record.get("steps") or ()),
        "engine_events": len(record.get("events") or ()),
        "site_setup_operations": len(setup),
        "site_operations": len(operations),
    }

    expect_final, slots_known, unplaced = _expect_final(
        record, slot_of, _label)
    unsupported.extend(unplaced)

    #: 🔴 **어느 이미지로 도는가**를 계획이 들고 있다. 자리표시 시트와
    #: 등록된 실제 덱 이미지를 섞어 말하지 않는다.
    deck_image = {"mode": "placeholder-sheet", "registration_id": None,
                  "image_path": None, "verified": False}
    if registration is not None:
        deck_image = {
            "mode": "registered",
            "registration_id": registration.registration_id,
            "image_path": registration.image_path,
            "image_sha256": registration.image_sha256,
            "verified": bool(registration.verified),
            "recipe_sha256": registration.recipe_sha256,
        }
    return {
        "format": PLAN_FORMAT,
        "deck_image": deck_image,
        "slots_ok": not slot_problems,
        #: 막지는 않지만 **적어 두는** 사실 (예: 사이드 덱 미지원).
        "notes": list(slot_notes),
        "source": dict(record.get("source") or {}),
        "result": dict(record.get("result") or {}),
        "deck": {"main": main, "extra": extra},
        "setup": setup,
        "operations": operations,
        "counts": counts,
        "expect_final": expect_final,
        "final_slots_known": slots_known,
        "unsupported": unsupported,
    }


#: 🔴 **사이트에서 관측할 수 있는 칸 전부.** 기대 집합을 이 목록 위에
#: 펼쳐 두어야 "여기 있어야 한다" 뿐 아니라 **"여기 있으면 안 된다"** 까지
#: 비교할 수 있다. 빈 칸은 빈 집합으로 남고, 실제로 비어 있으면 통과한다.
SITE_ZONES_ALL: tuple[str, ...] = (
    "Free", "Grave", "Banish", "Hand", "Extra Deck", "Deck", "Field Zone",
    "Monster Zone1", "Monster Zone2", "Monster Zone3", "Monster Zone4",
    "Monster Zone5", "Extra Monster Zone1", "Extra Monster Zone2",
    "Spell & Trap Zone1", "Spell & Trap Zone2", "Spell & Trap Zone3",
    "Spell & Trap Zone4", "Spell & Trap Zone5",
)


def _expect_final(record, slot_of, label):
    """
    최종 판의 **존별 카드 집합**. 🔴 장수만 세지 않는다.

    칸이 있는 존(몬스터 존 · 엑스트라 몬스터 존 · 마법함정 존 · 필드 존)은
    기록의 ``final.slots`` 가 주는 **칸 번호**로 나눈다. 그 칸이 없는 옛
    기록에서는 번호를 **지어내지 않고**, 그 개체를 ``unplaced`` 로 돌려
    보내 계획이 "칸까지는 맞출 수 없다" 고 적게 한다.
    """
    final = record.get("final") or {}
    zones = (final.get("zones") or {}).get("0") or {}
    raw_slots = final.get("slots")
    slots_known = raw_slots is not None
    placed: dict[int, str] = {}
    for row in raw_slots or ():
        if int(row.get("seat", 0)) != 0:
            continue
        placed[int(row["instance"])] = _zone_name(
            row.get("zone"), row.get("index"), seat=0)

    expect = {name: {"slots": [], "names": []} for name in SITE_ZONES_ALL}
    unplaced: list[str] = []
    for zone, instances in zones.items():
        for instance in instances:
            slot = slot_of.get(int(instance))
            if not slot:
                continue
            where = placed.get(int(instance)) or _zone_name(zone)
            if where not in expect:
                #: 🔴 칸이 있는 존인데 번호를 모른다 — 지어내지 않는다.
                unplaced.append(
                    f"최종 판의 {zone} 에 있는 #{instance} "
                    f"({label(instance)}) 의 칸 번호가 기록에 없어 "
                    f"칸까지는 맞춰 보지 않습니다."
                )
                continue
            expect[where]["slots"].append(slot)
            expect[where]["names"].append(label(instance))
    for value in expect.values():
        value["count"] = len(value["slots"])
    return expect, slots_known, unplaced


def plan_json(plan) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=1)


# ======================================================================
# 덱 시트 — 사이트에 넣을 **자체 제작 자리표시 이미지**
# ======================================================================
#: 실측한 격자 치수. 사이트의 덱 이미지 해석기가 이 비율에서 카드를 제대로
#: 잘라낸다 (한 줄 10장 · 카드 116×169 · 폭 1169).
SHEET = {"width": 1169, "cols": 10, "card_height": 169,
         "title": 82, "header": 44, "footer": 98}

#: 🔴 **공식 앱의 내보내기 이미지가 아니다.** 카드 그림을 담지 않고, 카드
#: 이름과 패스코드만 적은 자리표시 카드다. 공식 출력이라고 부르지 않는다.
SHEET_NOTICE = "自作プレースホルダー画像（公式アプリの出力ではありません／カード画像は含みません）"


def render_deck_sheet_html(plan, *, title: str = "galatea deck sheet") -> str:
    """
    계획의 덱 자리를 그대로 그린 **덱 시트 HTML**.

    🔴 **카드 그림을 넣지 않는다.** 카드 그림은 권리자의 저작물이고, 그것을
    외부 서비스에 올려 공개하는 것은 그 사이트의 가이드라인 5절이 금지하는
    「이용할 권한이 없는 이미지를 올려 공개하는 행위」 에 해당한다. 그래서
    이 시트는 **글자만** 담고, 그림이 있어야 하는 자리는 비워 둔다.
    """
    width = SHEET["width"]
    cols = SHEET["cols"]
    card_w = width / cols
    card_h = SHEET["card_height"]

    def _cell(entry) -> str:
        kind = entry.get("kind") or "monster"
        name = _escape(entry.get("name") or "")
        return (f'<div class="c {kind}"><div class="nm">{name}</div>'
                f'<div class="art"></div>'
                f'<div class="pc">{int(entry.get("passcode") or 0)}</div></div>')

    main = "".join(_cell(e) for e in plan["deck"]["main"])
    extra = "".join(_cell(e) for e in plan["deck"]["extra"])
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{width}px;background:#001324;
     font-family:"Noto Sans CJK JP","Noto Sans JP",system-ui,sans-serif}}
.title{{height:{SHEET['title']}px;background:#0d3a66;color:#fff;font-size:26px;
       font-weight:700;display:flex;align-items:center;padding:0 18px}}
.head{{height:{SHEET['header']}px;background:#062a4a;color:#fff;font-size:20px;
      font-weight:700;display:flex;align-items:center;padding:0 14px}}
.grid{{display:flex;flex-wrap:wrap;width:{width}px}}
.c{{width:{card_w}px;height:{card_h}px;position:relative;background:#c9a86a}}
.c.spell{{background:#3fa795}}.c.trap{{background:#a4548a}}
.art{{position:absolute;left:8%;right:8%;top:22%;height:46%;background:#242b38}}
.nm{{position:absolute;top:4px;left:4px;right:4px;font-size:11px;font-weight:700;
    color:#1d1403;line-height:1.1;text-align:center}}
.pc{{position:absolute;bottom:4px;left:0;right:0;text-align:center;font-size:10px;
    color:#1d1403}}
.foot{{height:{SHEET['footer']}px;color:#7d93ad;font-size:13px;display:flex;
      align-items:center;padding:0 18px}}
</style></head><body>
<div class="title">{_escape(title)}</div>
<div class="head">■ メインデッキ：{len(plan['deck']['main'])}枚</div>
<div class="grid">{main}</div>
<div class="head">■ エクストラデッキ：{len(plan['deck']['extra'])}枚</div>
<div class="grid">{extra}</div>
<div class="foot">{SHEET_NOTICE}</div>
</body></html>
"""


def _escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
