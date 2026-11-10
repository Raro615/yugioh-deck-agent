"""
Phase 6-AR — **전개 기록 내보내기와 디스코드 요약 단축.**

이 파일이 재는 것
-----------------
``deck.replay_export`` 가 **실행한 것만** 값으로 옮기는가, 그리고 그 값만으로
최종 판이 나오는가.

=========================================  ===============================
기록으로 계산한 최종 판                     실제 ``GameState`` 의 최종 판
한 걸음이 만든 사건 구간                    ``EventJournal`` 의 그 구간
비용 지불                                  해결과 **다른 사건 종류**
토큰이 필드를 떠남                          ``token_vanished`` — 묘지가 아니다
=========================================  ===============================

실제와 합성
-----------
====================================================  ==================
``orcust-skeleton-longirsu`` · ``orcust-girsu-token``  🔴 실제 실행
대조 함수(:func:`verify_replay`) 의 어긋남 갈래         **합성 기록**
====================================================  ==================

🔴 **이 파일은 "사이트에서 재생된다" 를 재지 않는다.** 재는 것은 *기록이
실행과 맞는가* 하나이고, 외부 사이트에서의 재생은 이 저장소가 확인하지
못했다 (``docs/duel-simulator-replay-integration.md``).
"""

from __future__ import annotations

import json

import pytest

from deck.combo_policy import (
    COMBO_LINES,
    ORCUST_VERIFICATION_RECIPE,
    line_progress,
)
from deck.opening import build_opening, execute_opening
from deck.recipe import parse_recipe
from deck.replay_export import (
    EVENT_COST,
    EVENT_EFFECT,
    REPLAY_FORMAT,
    export_opening_replay,
    replay_json,
    replay_membership,
    verify_replay,
)

from tests.conftest import requires_official_db

LONGIRSU_LINE = "orcust-skeleton-longirsu"
TOKEN_LINE = "orcust-girsu-token"

GIRSU = 69811710
DIBER = 57835716
SKELETON = 21441617
GALATEA = 30741503
LONGIRSU = 76145142
WORLD_LEGACY_TOKEN = 46647145


# ======================================================================
# 도구 — 실제 실행 한 번
# ======================================================================
def _run(repository, name: str):
    """경로 하나를 **실제로** 돌리고 ``(line, setup, run, progress)``."""
    from app.main import opening_wiring

    line = COMBO_LINES[name]
    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(repository, draft, list(line.hand),
                          chooser=chooser, triggers=triggers)
    run = execute_opening(setup, repository, choose=line.policy())
    return line, setup, run, line_progress(run, line)


@pytest.fixture(scope="module")
def longirsu(repository):
    line, setup, run, progress = _run(repository, LONGIRSU_LINE)
    record = export_opening_replay(setup, run, repository,
                                   line=line, progress=progress)
    return setup, run, progress, record


@pytest.fixture(scope="module")
def token_line(repository):
    line, setup, run, progress = _run(repository, TOKEN_LINE)
    record = export_opening_replay(setup, run, repository,
                                   line=line, progress=progress)
    return setup, run, progress, record


# ======================================================================
# A. 형식 — 번호가 있고, 값만 들어 있다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_a01_the_record_carries_a_format_version(longirsu):
    """🔴 **형식에 번호가 있다.** 칸이 바뀌면 읽는 쪽이 알 수 있어야 한다."""
    _setup, _run, _progress, record = longirsu
    assert record["format"] == REPLAY_FORMAT
    assert REPLAY_FORMAT.startswith("engine-replay/")


@requires_official_db
@pytest.mark.real_card
def test_a02_the_record_is_plain_json(longirsu):
    """
    🔴 **값 타입만** 들어 있다 — 객체 주소도 ``repr`` 도 없다. 그러지
    않으면 같은 실행이 돌릴 때마다 다른 파일이 된다.
    """
    _setup, _run, _progress, record = longirsu
    text = replay_json(record)
    again = json.loads(text)
    assert again == record
    assert "object at 0x" not in text


# ======================================================================
# B. 실제 전개 하나 — 기록이 실행과 맞는가
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_b01_the_known_line_still_runs_end_to_end(longirsu):
    """🔴 **기존 전개가 그대로다** — 이 작업은 기록만 더했다."""
    _setup, run, progress, record = longirsu
    assert progress.completed is True
    assert progress.done == 6
    assert record["result"]["status"] == "completed"
    assert record["result"]["line_done"] == 6
    assert record["result"]["line_total"] == 6
    assert len(run.steps) == 6


@requires_official_db
@pytest.mark.real_card
def test_b02_the_record_alone_reproduces_the_final_board(longirsu):
    """
    🔴 **이 파일의 본문.** 시작 판에 사건을 순서대로 적용하면 최종 판이
    나온다 — 그리는 쪽이 기록만 보고도 같은 판에 닿는다는 뜻이다.
    """
    _setup, _run, _progress, record = longirsu
    assert verify_replay(record) == ()


@requires_official_db
@pytest.mark.real_card
def test_b03_the_final_board_is_the_one_the_engine_has(longirsu, repository):
    """기록의 최종 판이 **실제 ``GameState``** 와 같은 자리를 말한다."""
    setup, _run, _progress, record = longirsu
    from engine.vocabulary import Zone

    state = setup.duel.state
    for zone in (Zone.EMZONE, Zone.GRAVE, Zone.REMOVED, Zone.MZONE):
        mine = sorted(
            card.instance_id.value
            for card in state.player(0).zone(zone) if card
        )
        said = sorted(record["final"]["zones"].get("0", {}).get(zone.value, []))
        assert mine == said, zone

    passcodes = [
        record["cards"][str(instance)]["passcode"]
        for instance in record["final"]["zones"]["0"]["EMZONE"]
    ]
    assert passcodes == [LONGIRSU]


@requires_official_db
@pytest.mark.real_card
def test_b04_two_copies_of_one_name_are_different_keys(longirsu):
    """
    🔴 **같은 이름의 여러 장을 구분한다.** 열쇠는 개체 번호이고, 패스코드는
    값이다 — 덱에 기르수가 3장이면 표에 기르수가 3개 있다.
    """
    _setup, _run, _progress, record = longirsu
    girsu = [key for key, card in record["cards"].items()
             if card["passcode"] == GIRSU]
    assert len(girsu) >= 2
    assert len(set(girsu)) == len(girsu)
    #: 그리고 **소환된 그 한 장**만 필드를 밟았다.
    moved = {
        change["instance"]
        for event in record["events"] for change in event["changes"]
        if change.get("kind") == "monster_summoned"
    }
    assert len(moved & {int(key) for key in girsu}) == 1


@requires_official_db
@pytest.mark.real_card
def test_b05_the_cost_is_not_the_resolution(longirsu):
    """
    🔴 **비용 지불과 효과 해결을 합치지 않는다.** 스켈레촌의 자기 제외는
    **비용**이고, 묘지의 기르수 소생이 해결이다.
    """
    _setup, _run, _progress, record = longirsu
    costs = [event for event in record["events"]
             if event["type"] == EVENT_COST]
    assert len(costs) == 2, "디베르와 스켈레촌이 각각 자기를 제외했다"

    banished = {
        change["instance"]
        for event in costs for change in event["changes"]
        if change["kind"] == "zone_moved" and change["to"]["zone"] == "REMOVED"
    }
    assert len(banished) == 2

    effects = [event for event in record["events"]
               if event["type"] == EVENT_EFFECT]
    #: 🔴 해결 사건에는 그 제외가 **없다**.
    for event in effects:
        for change in event["changes"]:
            if change.get("kind") == "zone_moved":
                assert change["to"]["zone"] != "REMOVED"

    skeleton = [event for event in costs
                if event.get("effect_ref", "").startswith(str(SKELETON))]
    assert len(skeleton) == 1
    assert skeleton[0]["payments"], "비용은 사람이 읽는 한 줄로도 남는다"


@requires_official_db
@pytest.mark.real_card
def test_b06_link_materials_are_their_own_field(longirsu):
    """
    🔴 **소재는 대상이 아니다.** 링크 걸음은 ``materials`` 를 들고 있고
    ``targets`` 는 비어 있다 — 합치면 보고가 "대상 2개" 로 적는다.
    """
    _setup, _run, _progress, record = longirsu
    links = [step for step in record["steps"] if step["kind"] == "link_summon"]
    assert len(links) == 2
    for step in links:
        assert step["materials"]
        assert "targets" not in step
    assert links[-1]["material_passcodes"] == [GALATEA, GIRSU]


@requires_official_db
@pytest.mark.real_card
def test_b07_the_designated_target_is_recorded(longirsu):
    """스켈레촌 걸음은 **발동 시점에 지정한 대상**을 들고 있다."""
    _setup, _run, _progress, record = longirsu
    skeleton = [step for step in record["steps"]
                if step.get("effect_ref", "").startswith(str(SKELETON))]
    assert len(skeleton) == 1
    assert skeleton[0]["targets"]


@requires_official_db
@pytest.mark.real_card
def test_b08_the_summon_restriction_rides_along(longirsu):
    """
    🔴 **뒤에 할 수 있는 일을 바꾸는 기록**도 함께 간다 (6-AO) — 어둠 속성
    제한 두 건이다. 빼면 그리는 쪽이 "왜 이 소환만 되는가" 를 말할 수 없다.
    """
    _setup, _run, _progress, record = longirsu
    limits = record["final"]["summon_limits"]
    assert [(item["attribute"], item["source"]) for item in limits] == [
        ("DARK", SKELETON), ("DARK", DIBER),
    ] or [(item["attribute"], item["source"]) for item in limits] == [
        ("DARK", DIBER), ("DARK", SKELETON),
    ]


# ======================================================================
# C. 토큰 — 사라지는 것은 사라진 것으로 적는다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_c01_tokens_are_marked_as_tokens(token_line):
    """필드에 **남아 있는** 토큰도 토큰으로 적힌다 (자리로는 알 수 없다)."""
    _setup, _run, _progress, record = token_line
    tokens = {key: card for key, card in record["cards"].items()
              if card.get("token")}
    assert len(tokens) == 2
    assert {card["passcode"] for card in tokens.values()} == {
        WORLD_LEGACY_TOKEN
    }
    #: 🔴 **상대 필드의 토큰도 기록된다** — 기르수 ③ 은 서로에게 1장씩 준다.
    assert {card["owner"] for card in tokens.values()} == {0, 1}


@requires_official_db
@pytest.mark.real_card
def test_c02_a_token_that_left_the_field_is_nowhere(token_line):
    """
    🔴 **토큰의 필드 이탈을 묘지에 남는 일반 카드처럼 적지 않는다.**
    소재가 된 토큰은 어느 존에도 없다.
    """
    _setup, _run, _progress, record = token_line
    vanished = [
        change["instance"]
        for event in record["events"] for change in event["changes"]
        if change["kind"] == "token_vanished"
    ]
    assert len(vanished) == 1
    membership = replay_membership(record)
    everywhere = {
        instance
        for zones in membership.values()
        for ids in zones.values() for instance in ids
    }
    assert vanished[0] not in everywhere
    #: 그리고 최종 판에도 없다 — 기록과 판이 같은 말을 한다.
    assert verify_replay(record) == ()


@requires_official_db
@pytest.mark.real_card
def test_c03_a_token_used_as_material_is_not_a_grave_move(token_line):
    """사라진 토큰에 대해 ``zone_moved … GRAVE`` 가 적히지 않는다."""
    _setup, _run, _progress, record = token_line
    vanished = {
        change["instance"]
        for event in record["events"] for change in event["changes"]
        if change["kind"] == "token_vanished"
    }
    for event in record["events"]:
        for change in event["changes"]:
            if change.get("kind") == "zone_moved":
                assert change["instance"] not in vanished


# ======================================================================
# D. 기록이 실행에 없는 것을 만들지 않는가
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_d01_every_event_came_from_the_journal(longirsu):
    """사건 수가 ``EventJournal`` 과 **같다** — 더하지도 빼지도 않았다."""
    setup, _run, _progress, record = longirsu
    assert len(record["events"]) == len(list(setup.journal))
    assert [event["seq"] for event in record["events"]] == list(
        range(len(record["events"]))
    )


@requires_official_db
@pytest.mark.real_card
def test_d02_the_steps_partition_the_events(longirsu):
    """
    걸음들이 사건 구간을 **겹치지 않고 전부** 덮는다. 어느 이동이 어느
    걸음의 것인지 말할 수 있어야 한 걸음씩 그릴 수 있다.
    """
    _setup, _run, _progress, record = longirsu
    seen: list[int] = []
    for step in record["steps"]:
        seen.extend(step["events"])
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))
    assert set(seen) == {event["seq"] for event in record["events"]}


@requires_official_db
@pytest.mark.real_card
def test_d03_every_step_was_accepted_in_this_line(longirsu):
    """
    이 경로는 여섯 걸음이 모두 수락되었다. 🔴 **수락을 "효과가 적용됐다" 로
    바꾸지 않는다** — 그 둘은 기록에서 따로 적힌다 (``accepted`` ·
    ``events``).
    """
    _setup, _run, _progress, record = longirsu
    assert all(step["accepted"] for step in record["steps"])
    #: 효과 발동 걸음 셋 가운데 하나(스켈레촌)는 비용 + 해결 두 사건이다.
    activations = [step for step in record["steps"]
                   if step["kind"] == "activate_effect"]
    assert len(activations) == 3
    assert [len(step["events"]) for step in activations] == [1, 2, 2]


@requires_official_db
@pytest.mark.real_card
def test_d04_the_record_keeps_the_unsupported_notes(longirsu):
    """
    🔴 **미지원을 지우지 않는다.** 기록을 보는 쪽이 "이 엔진이 규칙을 다
    안다" 로 읽으면 안 된다.
    """
    _setup, run, _progress, record = longirsu
    assert record["unsupported"] == list(run.unsupported)
    assert record["unsupported"], "이 경로에는 미지원 사유가 있다"


# ======================================================================
# E. 대조 함수 — 합성 기록으로 어긋남 갈래를 센다 (엔진을 돌리지 않는다)
# ======================================================================
def _toy(initial, events, final) -> dict:
    return {
        "format": REPLAY_FORMAT,
        "initial": {"zones": initial},
        "events": events,
        "final": {"zones": final},
    }


def test_e01_a_matching_record_has_no_complaint():
    """맞으면 빈 tuple 이다."""
    record = _toy(
        {"0": {"HAND": [1]}},
        [{"seq": 0, "type": "action", "actor": 0, "changes": [
            {"kind": "zone_moved", "instance": 1,
             "from": {"player": 0, "zone": "HAND"},
             "to": {"player": 0, "zone": "GRAVE"}},
        ]}],
        {"0": {"GRAVE": [1]}},
    )
    assert verify_replay(record) == ()


def test_e02_a_missing_move_is_reported_not_repaired():
    """
    🔴 **고치지 않는다.** 기록에 없는 이동이 최종 판에 있으면 그 사실을
    문장으로 돌려준다 — 기록을 판에 맞춰 손보면 대조가 아무것도 재지 않는다.
    """
    record = _toy({"0": {"HAND": [1]}}, [], {"0": {"GRAVE": [1]}})
    problems = verify_replay(record)
    assert len(problems) == 2
    assert any("GRAVE" in said for said in problems)
    assert any("HAND" in said for said in problems)


def test_e03_a_token_without_a_summon_is_not_placed_by_guesswork():
    """
    🔴 **자리를 지어내지 않는다.** ``token_created`` 만 있고 소환 사건이
    없으면 그 토큰은 어디에도 놓이지 않고, 대조가 어긋남으로 잡는다.
    """
    record = _toy(
        {"0": {}},
        [{"seq": 0, "type": "effect", "actor": 0, "changes": [
            {"kind": "token_created", "instance": 9, "card_id": 46647145,
             "owner": 0, "controller": 0, "summoner": 0,
             "creator": None, "creator_card_id": None},
        ]}],
        {"0": {"MZONE": [9]}},
    )
    assert replay_membership(record) == {}
    assert verify_replay(record) != ()


def test_e04_a_vanished_token_is_removed_not_moved():
    """사라진 토큰은 어느 존에도 남지 않는다."""
    record = _toy(
        {"0": {}},
        [
            {"seq": 0, "type": "effect", "actor": 0, "changes": [
                {"kind": "token_created", "instance": 9, "card_id": 1,
                 "owner": 0, "controller": 0},
                {"kind": "monster_summoned", "summon": "special",
                 "instance": 9, "player": 0, "owner": 0,
                 "from": {"zone": None},
                 "to": {"zone": "MZONE", "index": 0,
                        "position": "FACEUP_ATTACK"}},
            ]},
            {"seq": 1, "type": "action", "actor": 0, "changes": [
                {"kind": "token_vanished", "instance": 9, "card_id": 1,
                 "owner": 0, "controller": 0,
                 "from": {"zone": "MZONE"}, "reason": "material"},
            ]},
        ],
        {"0": {}},
    )
    assert verify_replay(record) == ()


# ======================================================================
# F. 디스코드 출력 — 짧아졌는가, 없는 링크를 약속하지 않는가
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_f01_the_default_answer_is_short_and_points_at_the_files(repository):
    """
    🔴 **기본 응답이 한눈에 읽힌다.** 6-AE 의 긴 요약은 **지운 것이 아니라**
    첨부의 첫 절로 내려갔다 — 아래가 둘 다를 센다.
    """
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repo):
            self.repository = repo

    response = bot.combo_response(
        _Agent(repository),
        ",".join(str(card) for card in COMBO_LINES[LONGIRSU_LINE].hand),
        recipe_text=ORCUST_VERIFICATION_RECIPE,
        line_text=LONGIRSU_LINE,
    )
    summary = "\n".join(response.messages)
    #: 6-AQ 후속까지의 실측은 2메시지 · 2,198자였다.
    assert len(response.messages) == 1
    assert len(summary) < 1400

    #: 지우면 뜻이 달라지는 것들은 남아 있다.
    assert "전개 완료" in summary
    assert "고정 경로" in summary
    assert "롱기르수" in summary
    assert "최선 전개" in summary
    assert "미지원" in summary

    #: 긴 요약은 첨부에 그대로 있다.
    detail = "\n".join(item.text for item in response.attachments
                       if item.filename == bot.COMBO_DETAIL_FILENAME)
    assert "전개 실행 요약" in detail
    assert "지원 범위" in detail


@requires_official_db
@pytest.mark.real_card
def test_f02_the_replay_file_rides_along(repository):
    """전개 기록이 **두 번째 첨부**로 간다."""
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repo):
            self.repository = repo

    response = bot.combo_response(
        _Agent(repository),
        ",".join(str(card) for card in COMBO_LINES[LONGIRSU_LINE].hand),
        recipe_text=ORCUST_VERIFICATION_RECIPE,
        line_text=LONGIRSU_LINE,
    )
    names = [item.filename for item in response.attachments]
    assert bot.COMBO_DETAIL_FILENAME in names
    assert bot.COMBO_REPLAY_FILENAME in names

    raw = [item.text for item in response.attachments
           if item.filename == bot.COMBO_REPLAY_FILENAME][0]
    record = json.loads(raw)
    assert record["format"] == REPLAY_FORMAT
    #: 🔴 첨부된 그 기록으로 최종 판이 나온다.
    assert verify_replay(record) == ()


@requires_official_db
@pytest.mark.real_card
def test_f03_no_replay_link_is_promised(repository):
    """
    🔴 **없는 링크를 약속하지 않는다.** 실제로 공유 가능한 리플레이를 만든
    적이 없으므로 "전개 보기" 는 **없다고** 적힌다. 사이트 첫 화면 주소를
    이 전개의 재생 링크처럼 적지도 않는다.
    """
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repo):
            self.repository = repo

    response = bot.combo_response(
        _Agent(repository),
        ",".join(str(card) for card in COMBO_LINES[LONGIRSU_LINE].hand),
        recipe_text=ORCUST_VERIFICATION_RECIPE,
        line_text=LONGIRSU_LINE,
    )
    summary = "\n".join(response.messages)
    assert "전개 보기: 아직 없습니다" in summary
    assert "엔진 실행은 정상" in summary
    assert "duel-simulator" not in summary
    assert "http" not in summary


def test_f04_a_failed_export_does_not_erase_the_run():
    """
    🔴 **외부 연동 실패와 엔진 실행 실패는 다른 사실이다.** 기록을 만들지
    못해도 요약과 상세는 그대로 간다.

    엔진을 돌리지 않는다 — ``OpeningReport`` 의 모양만 센다.
    """
    import app.discord_bot as bot

    report = bot.OpeningReport(brief=("요약",), detail=("상세",), ran=True,
                               replay=None)
    assert bot.replay_attachment(report.replay) is None
    assert report.brief and report.detail
