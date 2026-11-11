"""
Phase 6-AZ — **덱 이미지 등록과 재사용**, 그리고 세 오류의 수정.

이 파일이 재는 것
-----------------
=========================================  ================================
이미지 **순서**에 기대지 않는다             ``assign_slots`` · 계획
같은 카드 **여러 장**이 섞이지 않는다       자리별 배정
같은 등록으로 **패만 바꿔** 돈다            등록 재사용
레시피가 **달라지면** 불일치다              ``matches_recipe``
**확인되지 않은 등록**으로 시작하지 않는다   ``run_site_session``
**비정상 종료**는 성공이 아니다             ``RunStatus.BAD_EXIT``
**일부만 끝난 실행**은 완료가 아니다         ``RunStatus.INCOMPLETE``
타임아웃의 **자식 정리**를 확인한다          ``_kill_tree``
=========================================  ================================

🔴 **사이트를 열지 않는다.** 실제 조작과 공유는
``docs/duel-simulator-automation.md`` 에 실측으로 적혀 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deck.deck_image_registry import (
    DeckRegistration,
    SlotEntry,
    assign_slots,
    load_registration,
    normalize_recipe,
)
from deck.site_plan import build_site_plan


# ----------------------------------------------------------------------
def _record(hand, deck, extra, names=None) -> dict:
    """합성 기록 — 🔴 이 저장소의 어느 경로도 아니다."""
    cards, number = {}, 1
    zones = {"HAND": [], "DECK": [], "EXTRA": []}
    for key, codes in (("HAND", hand), ("DECK", deck), ("EXTRA", extra)):
        for code in codes:
            cards[str(number)] = {"passcode": code, "owner": 0,
                                  "name": (names or {}).get(code, f"카드{code}"),
                                  "kind": "monster"}
            zones[key].append(number)
            number += 1
    return {
        "format": "engine-replay/5",
        "cards": cards,
        "initial": {"zones": {"0": zones}},
        "steps": [], "events": [],
        "final": {"zones": {"0": {"HAND": zones["HAND"]}}, "slots": []},
        "unsupported": [],
    }


def _registration(main_codes, extra_codes, *, verified=True,
                  recipe_sha="r") -> DeckRegistration:
    slots = tuple(SlotEntry(f"main-{n}", code, "", "site", True)
                  for n, code in enumerate(main_codes))
    slots += tuple(SlotEntry(f"extra-{n}", code, "", "site", True)
                   for n, code in enumerate(extra_codes))
    return DeckRegistration(
        registration_id="dk0123456789", owner="u", image_path="x.png",
        image_sha256="h", image_bytes=1, recipe_text="", recipe_norm={},
        recipe_sha256=recipe_sha,
        counts={"main": len(main_codes), "extra": len(extra_codes), "side": 0},
        slots=slots, verified=verified, verify_method="시험")


# ======================================================================
# A. 이미지 순서 · 같은 카드 여러 장
# ======================================================================
def test_a01_the_hand_does_not_have_to_sit_at_the_front_of_the_image():
    """
    🔴 **사용자에게 이미지 순서를 바꾸라고 하지 않는다.** 시작 패가
    이미지 뒤쪽에 흩어져 있어도 그 자리를 찾아 꺼낸다.
    """
    record = _record(hand=[11, 22], deck=[33, 44], extra=[55])
    #: 이미지에는 덱 카드가 먼저, 패가 뒤에 있다.
    registration = _registration([33, 44, 11, 22], [55])
    plan = build_site_plan(record, registration)
    assert plan["slots_ok"]
    assert [op["card"] for op in plan["setup"]] == ["main-2", "main-3"]


def test_a02_two_copies_of_one_card_take_two_different_slots():
    """🔴 같은 카드가 여러 장이어도 **자리가 다르므로** 섞이지 않는다."""
    record = _record(hand=[11, 11], deck=[11], extra=[])
    registration = _registration([11, 11, 11], [])
    plan = build_site_plan(record, registration)
    picked = [op["card"] for op in plan["setup"]]
    assert len(set(picked)) == 2, picked
    #: 덱에 남는 자리는 패가 가져가지 않은 그 하나다.
    rest = {entry["slot"] for entry in plan["deck"]["main"]
            if entry["where"] == "deck"}
    assert rest and not rest & set(picked)


def test_a03_the_same_registration_runs_a_different_hand():
    """같은 등록 덱에서 **패만 바꿔도** 이미지를 다시 등록하지 않는다."""
    registration = _registration([11, 22, 33, 44], [55])
    first = build_site_plan(_record([11, 22], [33, 44], [55]), registration)
    second = build_site_plan(_record([33, 44], [11, 22], [55]), registration)
    assert first["slots_ok"] and second["slots_ok"]
    assert [op["card"] for op in first["setup"]] == ["main-0", "main-1"]
    assert [op["card"] for op in second["setup"]] == ["main-2", "main-3"]


def test_a04_a_card_the_image_does_not_have_is_a_mismatch():
    """이미지에 없는 카드를 쓰라고 하면 **불일치**다 — 지어내지 않는다."""
    record = _record(hand=[99], deck=[], extra=[])
    plan = build_site_plan(record, _registration([11, 22], []))
    assert not plan["slots_ok"]
    assert any("99" in line and "없습니다" in line
               for line in plan["unsupported"])


def test_a05_assignment_is_rebuilt_for_every_record():
    """🔴 **매 실행마다 새로 묶는다** — 이전 세션의 대응을 들고 있지 않다."""
    registration = _registration([11, 22], [])
    one = assign_slots(_record([11], [22], []), registration)
    two = assign_slots(_record([22], [11], []), registration)
    assert one.by_instance is not two.by_instance
    assert one.ok and two.ok


def test_a06_without_a_registration_the_old_sheet_mode_still_works():
    """글자 자리표시 시트 모드는 **별도 모드로 보존**된다."""
    plan = build_site_plan(_record([11], [22], [33]))
    assert plan["deck_image"]["mode"] == "placeholder-sheet"
    assert [op["card"] for op in plan["setup"]] == ["main-0"]


# ======================================================================
# B. 레시피 대조와 확인 상태
# ======================================================================
def test_b01_a_changed_recipe_no_longer_matches_the_registration():
    registration = _registration([11], [], recipe_sha="aaa")
    assert registration.matches_recipe("aaa")
    assert not registration.matches_recipe("bbb")


@pytest.mark.real_card
def test_b02_the_recipe_hash_ignores_order_and_spelling(repository):
    """🔴 같은 덱을 다르게 적어도 **같은 해시**, 한 장만 달라도 다른 해시."""
    one, first = normalize_recipe("11091375 x3\n55144522 x1", repository)
    two, second = normalize_recipe("55144522 x1\n11091375 x3", repository)
    assert one == two and first == second
    _three, third = normalize_recipe("11091375 x2\n55144522 x1", repository)
    assert third != first


def test_b03_an_unverified_registration_never_starts_the_site(tmp_path):
    """🔴 **추측한 자리 대응으로 외부 사이트를 조작하지 않는다.**"""
    from deck.site_session import RunStatus, run_site_session

    called = []
    run = run_site_session(
        _record([11], [], []), base_dir=tmp_path, title="t", share=True,
        registration=_registration([11], [], verified=False),
        runner=lambda command, path: called.append(command))
    assert run.status is RunStatus.NOT_VERIFIED
    assert not called, "브라우저를 열었습니다"
    assert not run.shared


def test_b04_a_registration_whose_slots_do_not_fit_is_refused(tmp_path):
    from deck.site_session import RunStatus, run_site_session

    called = []
    run = run_site_session(
        _record([99], [], []), base_dir=tmp_path, title="t", share=True,
        registration=_registration([11], [], verified=True),
        runner=lambda command, path: called.append(command))
    assert run.status is RunStatus.NOT_VERIFIED
    assert not called


@pytest.mark.real_card
def test_b05_only_the_owner_can_load_a_registration(tmp_path, repository):
    """🔴 **다른 사용자의 등록을 꺼내 주지 않는다.**"""
    from deck.deck_image_registry import register_deck_image

    got = register_deck_image(
        owner="alice", image=b"\x89PNG-fake", image_name="deck.png",
        recipe_text="11091375 x1", repository=repository, root=tmp_path)
    assert load_registration("alice", got.registration_id, tmp_path) is not None
    assert load_registration("bob", got.registration_id, tmp_path) is None
    #: 🔴 이미지를 **복사해 둔다** — 첨부 URL 에 기대지 않는다.
    assert (tmp_path / got.image_path).read_bytes() == b"\x89PNG-fake"


# ======================================================================
# C. 사이트 식별 결과 대조
# ======================================================================
@pytest.mark.real_card
def test_c01_unidentified_slots_leave_the_registration_unverified(tmp_path, repository):
    """이미지 식별이 **미완료**면 확인 완료로 치지 않는다."""
    from deck.deck_register import run_registration

    def runner(command, workdir):
        (Path(workdir) / "identify.json").write_text(json.dumps({
            "slots": [{"slot": "main-0", "name": ""},
                      {"slot": "main-1", "name": ""}],
            "counts_read": {"main": 2, "extra": 0},
            "uncertain": 2, "unreadable": [],
        }), encoding="utf-8")

    outcome = run_registration(
        owner="u", image=b"\x89PNG", image_name="d.png",
        recipe_text="11091375 x2", repository=repository,
        base_dir=tmp_path / "work", runner=runner, root=tmp_path)
    assert outcome.ok and not outcome.verified
    assert any("확정하지 못한 자리" in line for line in outcome.problems)
    assert not outcome.registration.verified


@pytest.mark.real_card
def test_c02_user_confirmation_can_settle_the_slots(tmp_path, repository):
    """사이트가 못 읽은 자리를 **필요한 자리만** 직접 확정할 수 있다."""
    from deck.deck_register import run_registration

    def runner(command, workdir):
        (Path(workdir) / "identify.json").write_text(json.dumps({
            "slots": [{"slot": "main-0", "name": ""},
                      {"slot": "main-1", "name": ""}],
            "counts_read": {"main": 2, "extra": 0},
            "uncertain": 2, "unreadable": [],
        }), encoding="utf-8")

    outcome = run_registration(
        owner="u", image=b"\x89PNG", image_name="d.png",
        recipe_text="11091375 x2", repository=repository,
        confirms=["main-0=11091375", "main-1=11091375"],
        base_dir=tmp_path / "work", runner=runner, root=tmp_path)
    assert outcome.verified, outcome.problems
    assert "사용자 확정" in outcome.registration.verify_method


@pytest.mark.real_card
def test_c03_a_count_that_differs_from_the_recipe_is_reported(tmp_path, repository):
    """이미지와 레시피의 **카드별 매수**가 다르면 확인되지 않는다."""
    from deck.deck_register import run_registration

    def runner(command, workdir):
        (Path(workdir) / "identify.json").write_text(json.dumps({
            "slots": [{"slot": "main-0", "name": ""},
                      {"slot": "main-1", "name": ""}],
            "counts_read": {"main": 2, "extra": 0},
            "uncertain": 2, "unreadable": [],
        }), encoding="utf-8")

    outcome = run_registration(
        owner="u", image=b"\x89PNG", image_name="d.png",
        recipe_text="11091375 x2", repository=repository,
        confirms=["main-0=11091375", "main-1=55144522"],
        base_dir=tmp_path / "work", runner=runner, root=tmp_path)
    assert not outcome.verified
    assert any("55144522" in line for line in outcome.problems)


# ======================================================================
# D. 세 오류 — 종료 코드 · 완료 여부 · 자식 정리
# ======================================================================
def _payload(run_id, **over):
    payload = {"run_id": run_id, "stopped_at": None, "share_requested": True,
               "share_url": "https://example.test/replay/x",
               "operations": [{"ok": True}, {"ok": True}],
               "operations_planned": 2,
               "stages": {"final": {"all_ok": True}}, "notes": []}
    payload.update(over)
    return payload


def _runner(payload, returncode=0):
    def run(command, path):
        rid = command[command.index("--run-id") + 1]
        (Path(path) / "result.json").write_text(
            json.dumps(payload(rid)), encoding="utf-8")

        class _Done:
            pass
        _Done.returncode = returncode
        _Done.stderr = ""
        _Done.timed_out = False
        _Done.cleanup = None
        return _Done
    return run


def test_d01_a_bad_exit_code_is_not_a_success(tmp_path):
    """🔴 **비정상 종료인데 결과에 성공 URL** 이 있어도 공유 성공이 아니다."""
    from deck.site_session import RunStatus, run_site_session

    run = run_site_session(_record([11], [], []), base_dir=tmp_path, title="t",
                           share=True, runner=_runner(_payload, returncode=3))
    assert run.status is RunStatus.BAD_EXIT
    assert run.share_url and not run.shared


def test_d02_only_some_of_the_planned_operations_is_not_complete(tmp_path):
    """🔴 **계획보다 일부만** 끝났으면 완료가 아니다."""
    from deck.site_session import RunStatus, run_site_session

    def payload(rid):
        return _payload(rid, operations=[{"ok": True}], operations_planned=16)

    run = run_site_session(_record([11], [], []), base_dir=tmp_path, title="t",
                           share=True, runner=_runner(payload))
    assert run.status is RunStatus.INCOMPLETE
    assert not run.completed and not run.shared
    assert "1/16" in run.reason


def test_d03_equal_counts_among_executed_operations_is_not_enough(tmp_path):
    """
    🔴 **실행된 조작끼리만 세지 않는다.** 1건 계획 중 1건 성공처럼 보여도
    계획이 16건이면 완료가 아니다.
    """
    from deck.site_session import run_site_session

    def payload(rid):
        return _payload(rid, operations=[{"ok": True}, {"ok": True}],
                        operations_planned=16)

    run = run_site_session(_record([11], [], []), base_dir=tmp_path, title="t",
                           share=True, runner=_runner(payload))
    assert run.operations_ok == run.operations_total == 2
    assert not run.completed


def test_d04_the_posix_cleanup_confirms_the_group_is_gone():
    """타임아웃 정리가 **정말 끝났는지 확인**한다 (POSIX 실측)."""
    import os
    import subprocess

    from deck.site_session import _kill_tree

    process = subprocess.Popen(
        [os.sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    cleanup = _kill_tree(process)
    process.wait(timeout=10)
    assert cleanup.attempted and cleanup.ok is True, cleanup
    assert cleanup.method == "killpg"


def test_d05_the_windows_cleanup_kills_the_tree(monkeypatch):
    """
    🔴 **윈도우는 ``taskkill /T`` 로 자식 브라우저까지 끝낸다.**
    ``CREATE_NEW_PROCESS_GROUP`` 만으로는 남는다. 🔴 이 시험은 호출을
    확인할 뿐 **실제 윈도우에서 돌려 본 것이 아니다**.
    """
    import deck.site_session as session

    seen = {}

    class _Done:
        returncode = 0
        stdout = "SUCCESS: 프로세스 트리를 종료했습니다"
        stderr = ""

    def _fake_run(command, **kwargs):
        seen["command"] = command
        return _Done()

    monkeypatch.setattr(session.os, "name", "nt")
    monkeypatch.setattr(session.subprocess, "run", _fake_run)

    class _Process:
        pid = 4242

        def kill(self):
            seen["killed"] = True

    cleanup = session._kill_tree(_Process())
    assert seen["command"] == ["taskkill", "/F", "/T", "/PID", "4242"]
    assert cleanup.ok is True and cleanup.method == "taskkill /T"
    assert "killed" not in seen


def test_d06_an_unconfirmed_cleanup_is_said_out_loud(monkeypatch, tmp_path):
    """🔴 **정리가 확인되지 않았는데 정상처럼 적지 않는다.**"""
    from deck.site_session import Cleanup, RunStatus, run_site_session

    class _Done:
        returncode = -9
        stderr = ""
        timed_out = True
        cleanup = Cleanup(True, "taskkill /T", False, "코드 1")

    run = run_site_session(_record([11], [], []), base_dir=tmp_path, title="t",
                           share=True, runner=lambda command, path: _Done)
    assert run.status is RunStatus.TIMEOUT
    assert "정리 미확인" in run.reason
    assert not run.shared


# ======================================================================
# E. 레시피 완전 일치 — 남는 카드도 불일치다 (Phase 6-BA)
# ======================================================================
def test_e01_a_card_left_over_in_the_registered_image_is_a_mismatch():
    """
    🔴 **필요한 카드가 다 있다고 통과시키지 않는다.** 등록한 이미지 쪽에
    쓰이지 않고 **남는 카드**가 있으면 그것도 다른 덱이다 — 이것이 6-AZ 의
    구멍이었다 (있는지만 보고 남는지를 보지 않았다).
    """
    record = _record(hand=[11], deck=[22], extra=[])
    plan = build_site_plan(record, _registration([11, 22, 33], []))
    assert not plan["slots_ok"]
    assert any("33" in line and "남습니다" in line
               for line in plan["unsupported"])


def test_e02_a_count_difference_is_named_on_both_sides():
    """매수가 다르면 **몇 장 대 몇 장인지** 적는다."""
    record = _record(hand=[11, 11, 11], deck=[], extra=[])
    assignment = assign_slots(record, _registration([11, 11], []))
    assert not assignment.ok
    assert any("이번 기록 3장" in line and "등록 이미지 2장" in line
               for line in assignment.problems)


def test_e03_the_extra_deck_is_compared_too():
    """엑스트라도 같은 잣대로 센다 — 메인만 보고 넘기지 않는다."""
    record = _record(hand=[11], deck=[], extra=[55])
    assignment = assign_slots(record, _registration([11], [55, 66]))
    assert not assignment.ok
    assert any("엑스트라" in line and "66" in line
               for line in assignment.problems)


def test_e04_an_unconfirmed_slot_blocks_the_run():
    """🔴 확인되지 않은 자리가 남아 있으면 **시작하지 않는다.**"""
    from deck.deck_image_registry import DeckRegistration, SlotEntry

    registration = DeckRegistration(
        registration_id="dk0123456789", owner="u", image_path="x.png",
        image_sha256="h", image_bytes=1, recipe_text="", recipe_norm={},
        recipe_sha256="r", counts={"main": 2, "extra": 0, "side": 0},
        slots=(SlotEntry("main-0", 11, "", "site", True),
               SlotEntry("main-1", None, "", "site", False)),
        verified=True, verify_method="시험")
    assignment = assign_slots(_record([11], [22], []), registration)
    assert not assignment.ok
    assert any("확인되지 않은 자리" in line for line in assignment.problems)


def test_e05_a_side_deck_is_said_out_loud_not_dropped_silently():
    """사이드는 아직 쓰지 않는다 — **조용히 버리지 않고** 적는다."""
    from deck.deck_image_registry import DeckRegistration, SIDE_UNSUPPORTED
    from deck.deck_image_registry import SlotEntry

    registration = DeckRegistration(
        registration_id="dk0123456789", owner="u", image_path="x.png",
        image_sha256="h", image_bytes=1, recipe_text="", recipe_norm={},
        recipe_sha256="r", counts={"main": 1, "extra": 0, "side": 1},
        slots=(SlotEntry("main-0", 11, "", "site", True),
               SlotEntry("side-0", 77, "", "site", True)),
        verified=True, verify_method="시험")
    assignment = assign_slots(_record([11], [], []), registration)
    assert assignment.ok, assignment.problems
    assert any(SIDE_UNSUPPORTED in note for note in assignment.notes)


def test_e06_the_record_entry_cannot_bypass_the_comparison(tmp_path):
    """
    🔴 **실행 기록을 직접 넣는 입구도 같은 관문을 지난다** — 레시피를
    거치지 않는다고 검사가 비켜 가지 않는다.
    """
    from deck.site_session import RunStatus, run_site_session

    called = []
    run = run_site_session(
        _record([11], [], []), base_dir=tmp_path, title="t", share=True,
        registration=_registration([11, 22], []),
        runner=lambda command, path: called.append(command))
    assert run.status is RunStatus.NOT_VERIFIED
    assert not called, "불일치인데 브라우저를 띄웠습니다"


# ======================================================================
# F. 등록 이미지 파일 자체 확인 (Phase 6-BA)
# ======================================================================
def test_f01_the_stored_image_hash_is_checked_before_use(tmp_path, repository):
    """🔴 보관한 파일이 바뀌었으면 **등록된 실제 덱 이미지라고 적지 않는다.**"""
    from deck.deck_image_registry import (register_deck_image,
                                          registration_image_problem)

    registration = register_deck_image(
        owner="u", image=b"\x89PNG-one", image_name="d.png",
        recipe_text="11091375 x1", repository=repository, root=tmp_path)
    assert registration_image_problem(registration, tmp_path) is None
    (tmp_path / registration.image_path).write_bytes(b"\x89PNG-two!")
    said = registration_image_problem(registration, tmp_path)
    assert said and ("해시" in said or "크기" in said)


def test_f02_a_spoiled_image_stops_the_site_run(tmp_path):
    """해시가 다르면 브라우저를 **띄우지 않는다.**"""
    from deck.deck_image_registry import DeckRegistration, SlotEntry
    from deck.site_session import RunStatus, run_site_session

    registration = DeckRegistration(
        registration_id="dk0123456789", owner="u",
        image_path="no/such/image.png", image_sha256="h", image_bytes=1,
        recipe_text="", recipe_norm={}, recipe_sha256="r",
        counts={"main": 1, "extra": 0, "side": 0},
        slots=(SlotEntry("main-0", 11, "", "site", True),),
        verified=True, verify_method="시험")
    called = []
    run = run_site_session(
        _record([11], [], []), base_dir=tmp_path, title="t", share=True,
        registration=registration,
        runner=lambda command, path: called.append(command))
    assert run.status is RunStatus.NOT_VERIFIED
    assert "이미지 파일이" in run.reason
    assert not called
