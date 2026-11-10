"""
전개 기록 내보내기 — **실행한 것만** 값으로 옮긴다 (Phase 6-AR).

왜 필요했나
-----------
디스코드의 긴 전개 로그를 **시각적인 재생**으로 바꾸려면, 재생하는 쪽이
"무엇이 어디에서 어디로 갔는가" 를 알아야 한다. 지금 그 사실은 두 곳에
나뉘어 있다 — :class:`~deck.opening.ExecutedStep` 은 **행동**을 들고 있고
(무엇을 선언했고 수락됐는가), :class:`~engine.effect.journal.EventJournal` 은
**판이 실제로 바뀐 사건**을 들고 있다 (어느 개체가 어느 존으로 갔는가).

이 모듈은 그 둘을 **한 장의 값**으로 붙인다. 🔴 **새 사실을 만들지
않는다** — 기록에 없는 이동을 지어내지 않고, 거절된 행동을 성공한 이동으로
바꾸지 않으며, 무효 · 불발 · 미지원을 카드 이동으로 적지 않는다. 기록이
비어 있으면 비어 있는 그대로 내보낸다.

무엇을 구분해서 적는가
----------------------
=====================================  ======================================
같은 이름의 카드 여러 장                ``instance`` (개체 번호) 가 열쇠다.
                                       카드 이름 · 패스코드는 ``cards`` 표에
                                       따로 있고, 이동은 개체 번호로만 적는다
비용 지불과 효과 해결                   사건 종류가 다르다 (``cost_payment`` ·
                                       ``effect``). 합치지 않는다 — 스켈레촌의
                                       자기 제외는 **비용**이고 소생은 해결이다
링크 소재와 대상                        ``materials`` 와 ``targets`` 가 다른
                                       칸이다 (소재는 대상으로 지정되지 않는다)
토큰의 생성과 소멸                      ``token_created`` · ``token_vanished``
                                       가 제 종류로 남는다. 🔴 토큰이 필드를
                                       떠난 것을 **묘지로 간 일반 카드처럼**
                                       적지 않는다
판을 바꾸지 않은 걸음                   ``events`` 가 빈 목록이다. 그것을
                                       "일을 했다" 로 바꾸지 않는다
=====================================  ======================================

🔴 **적법성을 주장하지 않는다.** 이 기록은 *이 엔진이 실행한 것* 이고,
어딘가에서 재생된다고 해서 실제 게임 규칙의 적법성이 검증된 것이 아니다.
엔진이 보지 못한 규칙은 ``unsupported`` 에 그대로 실린다.

형식에 번호를 둔다
------------------
:data:`REPLAY_FORMAT` 하나다. 🔴 **범용 플랫폼으로 설계하지 않았다** — 이
저장소의 한 전개를 그리는 데 필요한 칸만 있고, 칸이 바뀌면 번호를 올린다.

무엇을 대조하는가 — **좁게 적는다**
-----------------------------------
:func:`verify_replay` 가 **시작 판에 사건을 순서대로 적용해** 최종 판과
맞는지 센다. 🔴 **그러나 그것은 전체 ``GameState`` 대조도, 시각 재현이
같다는 보증도 아니다** (Phase 6-AS 정정).

================================================  =======================
대조한다                                           대조하지 않는다
================================================  =======================
좌석 · 존마다 **어느 개체가 있는가** (구성원)       같은 존 안의 **순서**
토큰이 사라졌는가 (어느 존에도 없다)               덱 · 묘지의 순서
                                                  칸 번호 (``to.index``)
                                                  표시 형식 (``position``)
                                                  특수 소환 제한 전체
                                                  라이프 · 페이즈 · 턴
================================================  =======================

오른쪽 칸의 값들이 **기록에 없다는 뜻이 아니다** — 칸 번호와 표시 형식은
소환 사건 안에 그대로 있고(``monster_summoned``), 제한은 ``final.
summon_limits`` 에 있다. 다만 :func:`verify_replay` 가 그것들을 **같은
수준으로 맞춰 보지는 않는다**. 섞기(``zone_shuffled``)가 바꾼 새 순서는
기록에 없으므로 순서는 애초에 맞출 수 없다.

🔴 그래서 이 대조를 통과했다고 "그린 그림이 엔진과 같다" 고 말할 수 없다.
말할 수 있는 것은 **"기록만으로 각 존의 카드 구성이 최종 판과 같아진다"**
하나다.
"""

from __future__ import annotations

import json

#: 내보내기 형식의 번호. 칸이 바뀌면 올린다.
#:
#: 🔴 ``/1`` → ``/2`` (Phase 6-AU): ``cards`` 의 각 칸에 **보여 주기 위한
#: 두 값**을 더했다 — ``kind`` (몬스터 · 마법 · 함정) 과 ``type_ko``
#: (「몬스터/효과/링크」 같은 한국어 종류). 뷰어가 카드를 직사각형으로
#: 그릴 때 이름만으로는 종류를 알 수 없었다. 🔴 **더한 것이 전부이고**,
#: ``/1`` 을 읽던 쪽은 그대로 읽을 수 있다.
#:
#: 🔴 ``/2`` → ``/3`` (Phase 6-AV): ``initial`` 에 **시작 시점의 특수 소환
#: 제한**(``summon_limits``) 을 더했다. 제한은 등록 **사건**으로만 남아
#: 있어서, 읽는 쪽이 「지금 걸려 있는 제한」 을 세려면 시작값이 있어야
#: 한다 — 없으면 「시작 시점 제한 정보 미기록」 과 「제한 없음」 을 구분할
#: 수 없다. 🔴 **더한 것이 전부이고**, 옛 형식도 그대로 읽는다.
#:
#: 🔴 ``/3`` → ``/4`` (Phase 6-AW): 카드 표에 **확대 화면이 읽는 값들**을
#: 더했다 — ``desc`` (한국어 효과 텍스트) · ``atk`` · ``def`` · ``level``
#: (링크면 ``link``) · ``attribute_ko`` · ``race_ko`` · ``link_markers``.
#: 저장소가 읽은 것만 싣고, 없으면 **싣지 않는다** (읽는 쪽이 "미기록" 으로
#: 그린다). 🔴 **더한 것이 전부이고**, 옛 형식도 그대로 읽는다.
#:
#: 🔴 ``/4`` → ``/5`` (Phase 6-AY): ``final`` 에 **마지막 판의 칸 번호**
#: (``slots``) 를 더했다. 최종 존 구성(``zones``) 에는 칸 번호가 없어서,
#: 바깥에서 "롱기르수가 **몇 번** 엑스트라 몬스터 존에 있는가" 를 맞춰
#: 보려면 번호를 지어내는 수밖에 없었다. 칸이 있는 존만 싣는다 — 묘지처럼
#: 칸이 없는 자리는 나오지 않는다. 🔴 **더한 것이 전부이고**, 옛 형식도
#: 그대로 읽는다.
REPLAY_FORMAT = "engine-replay/5"

#: 이 저장소가 읽을 수 있는 형식들. 뷰어가 쓴다.
REPLAY_FORMATS_READ = ("engine-replay/1", "engine-replay/2",
                       "engine-replay/3", "engine-replay/4",
                       "engine-replay/5")

#: 사건 종류 — ``EventJournal`` 의 세 가지를 그대로 옮긴 이름이다.
EVENT_ACTION = "action"
EVENT_EFFECT = "effect"
EVENT_COST = "cost_payment"

#: 판의 **구성원**이 바뀌는 delta 종류. 나머지(제한 · 라이프 · 페이즈 ·
#: 섞기)는 자리를 옮기지 않으므로 :func:`replay_membership` 이 건너뛴다.
_MOVE_KINDS = frozenset(
    {"zone_moved", "card_drawn", "monster_summoned", "token_created",
     "token_vanished"}
)

__all__ = [
    "REPLAY_FORMAT",
    "REPLAY_FORMATS_READ",
    "EVENT_ACTION",
    "EVENT_EFFECT",
    "EVENT_COST",
    "export_opening_replay",
    "replay_membership",
    "verify_replay",
    "replay_json",
]


# ======================================================================
# 도구 — 기록에서 값만 꺼낸다
# ======================================================================
def _event_type(event) -> str:
    """``EventJournal`` 의 사건을 세 이름 가운데 하나로."""
    name = getattr(getattr(event, "kind", None), "name", "")
    if name == "EFFECT":
        return EVENT_EFFECT
    if name == "COST_PAYMENT":
        return EVENT_COST
    if name == "ACTION":
        return EVENT_ACTION
    #: 🔴 모르는 종류를 아는 것으로 바꾸지 않는다.
    return name.lower() or "unknown"


def _instance(value) -> "int | None":
    """``InstanceId`` 든 정수든 번호로. 없으면 ``None``."""
    if value is None:
        return None
    return getattr(value, "value", value)


def _zone_rows(state) -> "tuple[tuple[int, str, int, int], ...]":
    """지금의 판을 ``(좌석, 존, 개체, 카드 ID)`` 줄로. 시작 판과 같은 모양."""
    from engine.vocabulary import Zone

    rows: list[tuple[int, str, int, int]] = []
    for seat, player in enumerate(state.players):
        for zone in Zone:
            try:
                cards = [card for card in player.zone(zone) if card]
            except (KeyError, ValueError, AttributeError):
                continue
            for card in cards:
                rows.append(
                    (seat, zone.value, card.instance_id.value, card.card_id)
                )
    return tuple(rows)


def _grouped(rows) -> dict:
    """``(좌석, 존, 개체, 카드)`` 줄들을 ``{좌석: {존: [개체…]}}`` 로."""
    out: dict[str, dict[str, list[int]]] = {}
    for seat, zone, instance, _card_id in rows:
        out.setdefault(str(seat), {}).setdefault(zone, []).append(instance)
    return out


#: 수치 자리에 쓰이는 두 센티넬 (``core.constants``). ``-2`` 는 「?」 이고
#: ``-1`` 은 「수치 없음」 (링크 몬스터의 수비력) 이다. 🔴 **둘 다 0 이
#: 아니다** — 0 으로 바꿔 싣지 않는다.
_STAT_UNKNOWN = -2
_STAT_NONE = -1


def _stat(value) -> "int | str | None":
    """공격력 · 수비력 한 칸. 모르는 값은 ``"?"``, 없는 값은 ``None``."""
    if not isinstance(value, int):
        return None
    if value == _STAT_UNKNOWN:
        return "?"
    if value == _STAT_NONE:
        return None
    return value


def _put_detail(entry: dict, found) -> None:
    """
    카드 확대 화면이 읽는 값들 (Phase 6-AW).

    🔴 **저장소가 읽은 것만 싣는다.** 효과 텍스트가 없으면 ``desc`` 칸이
    아예 없고, 화면은 "효과 텍스트 미기록" 이라고 적는다 — 지어내지 않는다.
    """
    desc = getattr(found, "desc", "") or ""
    if desc.strip():
        entry["desc"] = desc.strip()
    for key, value in (("attribute_ko", getattr(found, "attribute_ko", None)),
                       ("race_ko", getattr(found, "race_ko", None))):
        if value:
            entry[key] = value
    if not getattr(found, "is_monster", False):
        return
    atk = _stat(getattr(found, "atk", None))
    if atk is not None:
        entry["atk"] = atk
    link_rating = getattr(found, "link_rating", None)
    if link_rating:
        entry["link"] = link_rating
        markers = list(getattr(found, "link_markers", ()) or ())
        if markers:
            entry["link_markers"] = markers
        return
    #: 🔴 링크 몬스터는 수비력도 레벨도 없다 — 위에서 돌아갔다.
    defense = _stat(getattr(found, "defense", None))
    if defense is not None:
        entry["def"] = defense
    level = getattr(found, "monster_level", None)
    if level:
        entry["rank" if getattr(found, "is_xyz", False) else "level"] = level


def _card_table(rows, repository=None, tokens=()) -> dict:
    """
    개체 번호 → 카드. 🔴 **같은 이름의 두 장이 다른 열쇠를 갖는다.**

    이름은 저장소가 있을 때만 적는다 — 없으면 패스코드만 남는다 (없는
    이름을 지어내지 않는다).
    """
    table: dict[str, dict] = {}
    #: 🔴 **토큰 여부는 자리로 알 수 없다.** 필드에 남아 있는 토큰은 최종
    #: 판에도 보이므로, 어느 개체가 토큰인지는 **사건**이 말한다. 그래서
    #: 먼저 모으고, 표를 채울 때 그 집합을 본다.
    token_ids = {instance for instance, _card_id, _owner in tokens}

    def _put(instance: int, card_id: int, owner: int) -> None:
        key = str(instance)
        if key in table:
            return
        entry: dict = {"passcode": card_id, "owner": owner}
        if instance in token_ids:
            entry["token"] = True
        found = repository.get(card_id) if repository is not None else None
        if found is not None:
            entry["name"] = found.display_name()
            #: 🔴 **보여 주기 위한 값 둘** (Phase 6-AU). 그림 없이 직사각형
            #: 으로 그리는 화면은 이름만으로 종류를 알 수 없다. 저장소가
            #: 읽은 것을 그대로 싣고, 없으면 **싣지 않는다** (지어내지
            #: 않는다 — 읽는 쪽이 "미기록" 으로 그린다).
            kind = ("monster" if found.is_monster else
                    "spell" if found.is_spell else
                    "trap" if found.is_trap else None)
            if kind is not None:
                entry["kind"] = kind
            if found.type_ko:
                entry["type_ko"] = found.type_ko
            #: 🔴 **확대 화면이 읽는 값들** (Phase 6-AW). 카드를 눌렀을 때
            #: 한국어 이름 · 효과 텍스트 · 수치를 보여 준다. 저장소가 읽은
            #: 것만 싣는다 — 없는 값은 칸 자체가 없고, 읽는 쪽이 그것을
            #: "미기록" 으로 적는다 (0 이나 빈 글자로 채우지 않는다).
            _put_detail(entry, found)
        table[key] = entry

    for seat, _zone, instance, card_id in rows:
        _put(instance, card_id, seat)
    for instance, card_id, owner in tokens:
        _put(instance, card_id, owner)
    return table


# ======================================================================
# 내보내기
# ======================================================================
def export_opening_replay(setup, run, repository=None, *,
                          line=None, progress=None) -> dict:
    """
    한 번의 전개 실행을 **값 한 장**으로 (Phase 6-AR).

    🔴 **엔진을 다시 돌리지 않는다.** 이미 끝난 ``setup`` · ``run`` 과 그
    ``EventJournal`` 만 읽는다. ``line`` · ``progress`` 는 부르는 쪽이 이미
    만든 값이고, 여기서 다시 계산하면 두 계층의 답이 달라질 수 있다
    (:func:`~deck.report.render_opening_brief` 와 같은 규율).
    """
    journal = getattr(setup, "journal", None)
    events = list(journal) if journal is not None else []

    #: 토큰은 시작 판에도 최종 판에도 없을 수 있다 (만들어졌다 사라진다).
    #: 그래서 사건에서 따로 모은다.
    tokens: list[tuple[int, int, int]] = []
    for event in events:
        for delta in getattr(event, "deltas", ()):
            raw = delta.to_dict()
            if raw.get("kind") == "token_created":
                tokens.append(
                    (raw["instance"], raw["card_id"], raw.get("owner", 0))
                )

    state = getattr(setup.duel, "state", None) if setup.duel is not None else None
    final_rows = _zone_rows(state) if state is not None else ()
    initial_rows = tuple(run.initial_board)

    record: dict = {
        "format": REPLAY_FORMAT,
        "source": _source_block(setup, line),
        "result": _result_block(run, progress),
        "cards": _card_table(
            tuple(initial_rows) + tuple(final_rows), repository, tokens
        ),
        "initial": {
            "zones": _grouped(initial_rows),
            #: 🔴 **시작 시점의 제한** (6-AV). 빈 목록은 "그때 걸린 제한이
            #: 없었다" 이고, 이 칸이 **없는** 기록은 "모른다" 다 — 읽는
            #: 쪽이 둘을 다르게 적는다.
            "summon_limits": [
                {"seat": seat, "attribute": attribute, "source": source}
                for seat, attribute, source in getattr(
                    run, "initial_limits", ()
                )
            ],
        },
        "steps": [_step_block(step) for step in run.steps],
        "events": [_event_block(event) for event in events],
        "final": _final_block(state, final_rows,
                              getattr(run, "final_slots", ())),
        "unsupported": list(run.unsupported),
    }
    return record


def _source_block(setup, line) -> dict:
    """무엇을 돌렸는가. 🔴 고정 경로와 자율 실행을 구분해서 적는다."""
    block: dict = {
        "mode": "line" if line is not None else "autonomous",
        "seat": 0,
        "hand": list(setup.hand),
    }
    if line is not None:
        block["line"] = line.name
        block["title"] = line.title_ko
    return block


def _result_block(run, progress) -> dict:
    """
    끝까지 갔는가. 🔴 **"완료" 를 최선 전개나 모든 가능한 행동의 완료로
    적지 않는다** — 사람이 적어 둔 경로를 끝까지 밟았다는 뜻뿐이다.
    """
    if run.stopped_kind == "not_run":
        status = "not_run"
    elif progress is not None and progress.completed:
        status = "completed"
    elif run.stopped_kind in ("rejected", "limit"):
        status = "stopped"
    else:
        status = "ran"
    block: dict = {
        "status": status,
        "executed": run.executed,
        "state_changes": run.state_changes,
        "effects_resolved": run.effects_resolved,
    }
    if run.stopped_kind:
        block["stopped_kind"] = run.stopped_kind
    if run.stopped_reason:
        block["stopped_reason"] = run.stopped_reason
    if progress is not None:
        block["line_done"] = progress.done
        block["line_total"] = len(progress.line.steps)
        block["line_completed"] = bool(progress.completed)
        if progress.blocked_at is not None:
            block["line_blocked_at"] = progress.blocked_at
    return block


def _step_block(step) -> dict:
    """
    행동 하나. 🔴 **수락 · 해결 · 조작 수행을 합치지 않는다** (6-R 의 표).

    ``events`` 는 이 걸음이 늘린 기록의 번호들이다. 비어 있으면 판을 바꾸는
    사건이 하나도 없었다는 뜻이고, 그것을 성공한 이동으로 바꾸지 않는다.
    """
    block: dict = {
        "order": step.order,
        "actor": step.actor,
        "kind": step.kind,
        "accepted": bool(step.accepted),
        "resolved": bool(step.resolved),
        "state_changed": bool(step.state_changed),
        "events": list(range(step.journal_from, step.journal_to)),
    }
    if step.card_id is not None:
        block["card"] = {"passcode": step.card_id, "name": step.card_name}
    if step.effect_ref:
        block["effect_ref"] = step.effect_ref
    if step.targets:
        block["targets"] = list(step.targets)
    if step.materials:
        block["materials"] = list(step.materials)
    if step.material_card_ids:
        block["material_passcodes"] = list(step.material_card_ids)
    if step.resolution_choice_text:
        block["resolution_choices"] = list(step.resolution_choice_text)
    if step.resolved_without_operation:
        #: 🔴 **미지원도 오류도 아니다** — 규칙대로 해결되고 할 일이 없었다.
        block["resolved_without_operation"] = True
    if step.reason:
        block["reason"] = step.reason
    if step.unsupported:
        block["unsupported"] = list(step.unsupported)
    if step.unsupported_during:
        block["unsupported_during"] = list(step.unsupported_during)
    return block


def _event_block(event) -> dict:
    """판이 바뀐 사건 하나. delta 는 엔진이 쓴 ``to_dict`` 를 그대로 싣는다."""
    block: dict = {
        "seq": event.sequence,
        "type": _event_type(event),
        "actor": event.actor,
        "changes": [delta.to_dict() for delta in getattr(event, "deltas", ())],
    }
    source = _instance(getattr(event, "source", None))
    if source is not None:
        block["source"] = source
    ref = getattr(event, "effect_ref", None)
    if ref is not None:
        block["effect_ref"] = str(ref)
    kind = getattr(event, "action_kind", None)
    if kind:
        block["action_kind"] = kind
    payments = getattr(event, "payments", ())
    if payments:
        #: 🔴 **비용은 해결이 아니다.** 사람이 읽는 한 줄로 남긴다.
        block["payments"] = [str(payment) for payment in payments]
    return block


def _final_block(state, rows, slots=()) -> dict:
    """최종 판 — 존 구성 · **칸 번호** · 특수 소환 제한 · 상태 해시."""
    block: dict = {"zones": _grouped(rows)}
    #: 🔴 **칸이 있는 존만** 번호가 있다 (Phase 6-AY). 이 칸이 비어 있는
    #: 것과 **없는 것**은 다르다 — 옛 형식의 기록에는 칸 자체가 없고,
    #: 읽는 쪽이 그것을 "칸 번호 미기록" 으로 적는다.
    block["slots"] = [
        {"seat": seat, "zone": zone, "index": index, "instance": instance}
        for seat, zone, index, instance in slots
    ]
    if state is None:
        return block
    limits = getattr(state, "summon_limits", None)
    if limits is not None:
        active = limits.active(state.turn.turn_number, 0)
        block["summon_limits"] = [
            {"attribute": limit.attribute, "source": limit.source_card_id}
            for limit in active
        ]
    try:
        block["state_hash"] = state.state_hash()
    except Exception:  # pragma: no cover - 방어용
        pass
    return block


# ======================================================================
# 대조 — 기록만으로 최종 판이 나오는가
# ======================================================================
def replay_membership(record) -> dict:
    """
    시작 판에 사건을 **순서대로** 적용한 결과 ``{좌석: {존: [개체…]}}``.

    🔴 **자리 번호와 순서를 주장하지 않는다.** 섞기(``zone_shuffled``)가
    덱의 순서를 바꾸고 그 새 순서는 기록에 없으므로, 이 함수가 세는 것은
    **어느 존에 어느 개체가 있는가**이다 (칸 번호 · 표시 형식은 사건 안에
    그대로 남아 있고 그리는 쪽이 읽는다).
    """
    where: dict[int, tuple[str, str]] = {}
    for seat, zones in record["initial"]["zones"].items():
        for zone, instances in zones.items():
            for instance in instances:
                where[instance] = (seat, zone)

    for event in record["events"]:
        for change in event["changes"]:
            kind = change.get("kind")
            if kind not in _MOVE_KINDS:
                continue
            instance = change["instance"]
            if kind == "token_vanished":
                #: 🔴 **토큰은 묘지로 가지 않는다** — 판에서 사라진다.
                where.pop(instance, None)
                continue
            if kind == "token_created":
                #: 🔴 **자리를 지어내지 않는다.** ``token_created`` 는 토큰이
                #: *생겼다* 는 사실만 적고 어느 존인지는 말하지 않는다 —
                #: 자리를 정하는 것은 뒤따르는 ``monster_summoned`` 다. 여기서
                #: 임의로 몬스터 존에 놓으면 기록에 없는 자리를 만들게 되고,
                #: 소환 사건이 없는 토큰은 :func:`verify_replay` 가 어긋남으로
                #: 잡아야 한다.
                continue
            if kind == "monster_summoned":
                seat = str(change["player"])
                where[instance] = (seat, change["to"]["zone"])
                continue
            to = change["to"]
            where[instance] = (str(to.get("player", 0)), to["zone"])

    out: dict[str, dict[str, list[int]]] = {}
    for instance, (seat, zone) in where.items():
        out.setdefault(seat, {}).setdefault(zone, []).append(instance)
    for zones in out.values():
        for zone in zones:
            zones[zone] = sorted(zones[zone])
    return out


def verify_replay(record) -> "tuple[str, ...]":
    """
    기록만으로 **각 존의 카드 구성**이 최종 판과 같아지는지 대조한다.
    맞으면 빈 tuple.

    🔴 **전체 ``GameState`` 대조가 아니다** (6-AS). 무엇을 맞춰 보고 무엇을
    맞춰 보지 않는지는 이 모듈 머리말의 표에 있다 — 순서 · 칸 번호 · 표시
    형식 · 제한 · 라이프는 이 함수가 **같은 수준으로 재지 않는다.**

    🔴 **고치지 않는다.** 어긋나면 어긋난 자리를 문장으로 돌려줄 뿐이고,
    기록을 최종 판에 맞춰 손보지 않는다 — 그러면 대조가 아무것도 재지
    않게 된다.
    """
    computed = replay_membership(record)
    actual: dict[str, dict[str, list[int]]] = {}
    for seat, zones in record["final"]["zones"].items():
        actual[seat] = {zone: sorted(ids) for zone, ids in zones.items()}

    problems: list[str] = []
    seats = sorted(set(computed) | set(actual))
    for seat in seats:
        left = computed.get(seat, {})
        right = actual.get(seat, {})
        for zone in sorted(set(left) | set(right)):
            mine = left.get(zone, [])
            theirs = right.get(zone, [])
            if mine != theirs:
                problems.append(
                    f"P{seat} {zone}: 기록으로 계산한 {mine} 과 "
                    f"최종 판의 {theirs} 가 다릅니다"
                )
    return tuple(problems)


def replay_json(record) -> str:
    """사람이 읽을 수 있게 들여쓴 JSON 한 덩어리."""
    return json.dumps(record, ensure_ascii=False, indent=1, sort_keys=False)
