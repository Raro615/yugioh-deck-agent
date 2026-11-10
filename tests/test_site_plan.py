"""
Phase 6-AX — **외부 Duel Simulator 조작 계획** (``deck.site_plan`` ·
``deck.site_session`` · ``app.site_share``).

이 파일이 재는 것
-----------------
================================  ==========================================
정식 입력은 **실행 기록**이다       설명문이 아니라 사건 · 걸음에서 나온다
개체를 **자리로 묶는다**            같은 이름 두 장이 섞이지 않는다
대응 없는 사건은 **적힌다**         조용히 빠지지 않는다
덱 시트에 **카드 그림이 없다**      권리 없는 이미지를 올리지 않는다
공유는 **URL 이 생겼을 때만**       없는 링크를 적지 않는다
동시 요청은 **섞이지 않는다**       한 번에 하나만 돈다
================================  ==========================================

🔴 **이 파일은 사이트를 열지 않는다.** 실제 조작과 공유 URL 확인은
``docs/duel-simulator-automation.md`` 에 실측으로 적혀 있고, 여기 시험이
그것을 대신하지 않는다.
"""

from __future__ import annotations

import json

import pytest

from deck.site_plan import PLAN_FORMAT, build_site_plan, render_deck_sheet_html


def _toy(**over) -> dict:
    """합성 기록 하나 — 🔴 이 저장소의 어느 경로도 아니다."""
    record = {
        "format": "engine-replay/4",
        "source": {"mode": "line", "line": "toy", "seat": 0},
        "result": {"status": "completed"},
        "cards": {
            "1": {"passcode": 11, "owner": 0, "name": "합성 몬스터", "kind": "monster"},
            "2": {"passcode": 11, "owner": 0, "name": "합성 몬스터", "kind": "monster"},
            "3": {"passcode": 22, "owner": 0, "name": "합성 링크", "kind": "monster"},
        },
        "initial": {"zones": {"0": {"HAND": [1], "DECK": [2], "EXTRA": [3]}}},
        "steps": [
            {"order": 1, "actor": 0, "kind": "normal_summon", "accepted": True,
             "resolved": True, "state_changed": True, "events": [0]},
            {"order": 2, "actor": 0, "kind": "activate_effect", "accepted": True,
             "resolved": True, "state_changed": True, "events": [1],
             "card": {"passcode": 11, "name": "합성 몬스터"},
             "targets": ["#2"]},
        ],
        "events": [
            {"seq": 0, "type": "action", "actor": 0, "source": 1,
             "action_kind": "normal_summon", "changes": [
                 {"kind": "monster_summoned", "summon": "normal", "instance": 1,
                  "player": 0, "owner": 0, "from": {"zone": "HAND"},
                  "to": {"zone": "MZONE", "index": 2,
                         "position": "FACEUP_ATTACK"}}]},
            {"seq": 1, "type": "effect", "actor": 0, "source": 1, "changes": [
                {"kind": "zone_moved", "operation": "send_to_grave",
                 "instance": 2, "from": {"player": 0, "zone": "DECK"},
                 "to": {"player": 0, "zone": "GRAVE"}},
                {"kind": "zone_shuffled", "player": 0, "zone": "DECK",
                 "size": 1, "draw": 0}]},
        ],
        "final": {"zones": {"0": {"MZONE": [1], "GRAVE": [2], "EXTRA": [3]}}},
        "unsupported": [],
    }
    record.update(over)
    return record


# ======================================================================
# A. 기록에서 나온다 — 설명문에서 나오지 않는다
# ======================================================================
def test_a01_every_operation_names_the_record_line_it_came_from():
    """
    🔴 **조작마다 근거가 있다.** 이동은 사건의 delta 에서, 발동과 대상은
    걸음에서 나온다 — 사람이 읽으라고 쓴 ``reason`` 을 해석하지 않는다.
    """
    plan = build_site_plan(_toy())
    assert plan["format"] == PLAN_FORMAT
    assert plan["operations"], "조작이 하나도 나오지 않았습니다"
    for op in plan["operations"]:
        assert op["basis"].startswith("engine:"), op
    kinds = [op["op"] for op in plan["operations"]]
    assert kinds == ["move", "activate", "target", "move"]


def test_a02_the_slot_number_comes_from_the_record_not_from_a_guess():
    """칸 번호가 있는 소환은 **그 칸**으로, 없는 이동은 존으로만 간다."""
    plan = build_site_plan(_toy())
    summon = plan["operations"][0]
    assert summon["to"] == "Monster Zone3"      # index 2 → 3번 칸
    moved = plan["operations"][-1]
    assert moved["to"] == "Grave"
    #: 🔴 출발지의 칸 번호는 기록에 없다 — 번호를 지어내지 않는다.
    assert "?" not in moved["from"]


def test_a03_two_copies_of_one_card_get_two_slots():
    """
    🔴 **같은 이름의 두 장이 섞이지 않는다.** 개체마다 덱 자리가 다르고,
    조작은 자리를 가리킨다.
    """
    plan = build_site_plan(_toy())
    slots = {entry["instance"]: entry["slot"] for entry in plan["deck"]["main"]}
    assert slots[1] != slots[2]
    assert slots[1] == "main-0"          # 시작 패가 맨 앞
    assert slots[2] == "main-1"
    #: 대상(#2) 조작이 그 자리를 가리킨다.
    target = [op for op in plan["operations"] if op["op"] == "target"][0]
    assert target["card"] == "main-1"


def test_a04_the_opening_hand_sits_at_the_front_of_the_sheet():
    """사이트의 「왼쪽 위 N장을 패로」 가 **기록의 시작 패와 같아진다**."""
    plan = build_site_plan(_toy())
    assert [op["card"] for op in plan["setup"]] == ["main-0"]
    assert plan["deck"]["main"][0]["where"] == "hand"


def test_a05_an_event_the_site_cannot_show_is_written_down():
    """
    🔴 **조용히 빠뜨리지 않는다.** 덱 섞기처럼 사이트에 대응이 없는 사건은
    ``unsupported`` 에 남는다.
    """
    plan = build_site_plan(_toy())
    assert any("zone_shuffled" in line for line in plan["unsupported"])


def test_a06_engine_actions_and_site_operations_are_counted_apart():
    """🔴 **엔진 행동 수와 사이트 조작 수를 섞지 않는다.**"""
    counts = build_site_plan(_toy())["counts"]
    assert counts["engine_steps"] == 2
    assert counts["engine_events"] == 2
    assert counts["site_operations"] == 4
    assert counts["site_setup_operations"] == 1


def test_a07_a_card_outside_the_opening_board_is_reported_not_invented():
    """시작 판에 없는 개체는 자리를 묶을 수 없다 — 그렇다고 적는다."""
    record = _toy()
    record["events"][1]["changes"][0]["instance"] = 99
    record["cards"]["99"] = {"passcode": 33, "owner": 0, "name": "토큰"}
    plan = build_site_plan(record)
    assert any("#99" in line for line in plan["unsupported"])
    assert all(op["card"] != "main-99" for op in plan["operations"])


def test_a08_the_shared_extra_monster_zone_is_one_physical_pair():
    """
    🔴 좌석 0 의 ``EMZONE`` 은 공유 2칸의 **1번 칸**이다. 같은 자리를 양쪽에
    만들지 않는다.
    """
    record = _toy()
    record["events"][0]["changes"][0]["to"] = {
        "zone": "EMZONE", "index": 0, "position": "FACEUP_ATTACK"}
    plan = build_site_plan(record)
    assert plan["operations"][0]["to"] == "Extra Monster Zone1"


# ======================================================================
# B. 덱 시트 — 권리 없는 이미지를 올리지 않는다
# ======================================================================
def test_b01_the_deck_sheet_carries_no_card_artwork():
    """
    🔴 **카드 그림을 넣지 않는다.** 권리 없는 이미지를 올려 공유로 공개하는
    것은 그 사이트의 가이드라인 5절이 금지한다. 시트는 글자만 담는다.
    """
    html = render_deck_sheet_html(build_site_plan(_toy()))
    assert "<img" not in html
    assert "data:image" not in html
    assert "http://" not in html and "https://" not in html
    #: 🔴 공식 앱의 내보내기라고 **부르지 않는다** — 그 반대를 적는다.
    assert "公式アプリの出力ではありません" in html


def test_b02_every_slot_is_drawn_once():
    """자리 수가 그대로 칸 수다 — 빠지거나 겹치지 않는다."""
    plan = build_site_plan(_toy())
    html = render_deck_sheet_html(plan)
    assert html.count('class="c ') == (len(plan["deck"]["main"])
                                       + len(plan["deck"]["extra"]))
    assert f"メインデッキ：{len(plan['deck']['main'])}枚" in html
    assert f"エクストラデッキ：{len(plan['deck']['extra'])}枚" in html


def test_b03_a_card_name_cannot_inject_markup():
    """카드 이름에 태그가 들어 있어도 HTML 이 되지 않는다."""
    record = _toy()
    record["cards"]["1"]["name"] = '<script>window.__owned=1</script>'
    html = render_deck_sheet_html(build_site_plan(record))
    assert "<script>window.__owned" not in html
    assert "&lt;script&gt;" in html


# ======================================================================
# C. 세션 — 공유는 URL 이 생겼을 때만이다
# ======================================================================
def _fake_runner(result: dict):
    def run(command, path):
        (path / "result.json").write_text(json.dumps(result), encoding="utf-8")
        class _Done:
            returncode = 0
            stderr = ""
        return _Done()
    return run


def test_c01_a_session_reports_what_the_site_actually_did(tmp_path):
    from deck.site_session import run_site_session

    run = run_site_session(
        _toy(), workdir=tmp_path, title="t",
        runner=_fake_runner({"stopped_at": None, "share_requested": True,
                             "share_url": "https://example.test/replay/abc",
                             "operations": [{"ok": True}, {"ok": True}],
                             "stages": {"final": {"all_ok": True}}, "notes": []}))
    assert run.ok and run.shared
    assert run.share_url == "https://example.test/replay/abc"
    assert (run.operations_ok, run.operations_total) == (2, 2)


def test_c02_without_a_url_the_session_is_not_shared(tmp_path):
    """🔴 **생기지 않은 링크를 성공이라고 적지 않는다.**"""
    from deck.site_session import run_site_session

    run = run_site_session(
        _toy(), workdir=tmp_path, title="t",
        runner=_fake_runner({"stopped_at": "operation#7",
                             "stopped_reason": "화면이 기대와 달랐습니다",
                             "share_requested": True, "share_url": None,
                             "operations": [{"ok": True}, {"ok": False}],
                             "stages": {}, "notes": []}))
    assert not run.ok and not run.shared
    assert run.stopped_at == "operation#7"


def test_c03_the_plan_and_sheet_land_in_the_work_directory(tmp_path):
    from deck.site_session import prepare_run_dir

    prepare_run_dir(_toy(), tmp_path, title="t")
    for name in ("plan.json", "replay.json", "deck-sheet.html"):
        assert (tmp_path / name).exists(), name


# ======================================================================
# D. 디스코드 입구
# ======================================================================
def test_d01_the_entrance_says_it_publishes_outside():
    """🔴 **외부 공유가 일어나는 조작임을 입구에서 알린다.**"""
    from app.site_share import SITE_SHARE_WARNING, ShareState, site_share_lines
    from app.site_share import SiteShareOutcome

    assert "외부 사이트" in SITE_SHARE_WARNING
    assert "접근 제어가 없어" in SITE_SHARE_WARNING
    lines = site_share_lines(SiteShareOutcome(
        ShareState.SHARED, url="https://example.test/replay/x",
        operations_ok=16, operations_total=16))
    assert lines[-1] == "https://example.test/replay/x"


def test_d02_a_failure_keeps_the_existing_html_replay_usable():
    from app.site_share import ShareState, SiteShareOutcome, site_share_lines

    lines = site_share_lines(SiteShareOutcome(
        ShareState.FAILED, reason="화면이 기대와 달랐습니다"))
    assert "화면이 기대와 달랐습니다" in lines[0]
    assert any("combo-replay.html" in line for line in lines)
    assert not any("http" in line for line in lines)


def test_d03_two_requests_do_not_share_one_browser(tmp_path):
    """
    🔴 **한 번에 하나만 돈다.** 돌고 있는 중에 들어온 요청은 기다리지 않고
    바쁘다고 답한다 — 두 세션이 같은 사이트를 동시에 조작하면 어느 쪽
    기록인지 알 수 없다.
    """
    import threading

    from app.site_share import ShareState, SiteShareRunner

    started = threading.Event()
    release = threading.Event()

    def _slow(record, *, workdir, title, share):
        started.set()
        release.wait(5)
        class _Run:
            shared = True
            share_url = "https://example.test/replay/one"
            operations_ok = operations_total = 1
            stopped_reason = None
            final_ok = True
        return _Run()

    runner = SiteShareRunner(tmp_path, session=_slow)
    out: list = []
    worker = threading.Thread(target=lambda: out.append(
        runner.share({"any": "record"}, title="t")))
    worker.start()
    assert started.wait(5)
    busy = runner.share({"any": "record"}, title="t")
    assert busy.state is ShareState.BUSY
    release.set()
    worker.join(10)
    assert out[0].state is ShareState.SHARED


def test_d04_no_record_means_no_share(tmp_path):
    from app.site_share import ShareState, SiteShareRunner

    runner = SiteShareRunner(tmp_path, session=lambda *a, **k: None)
    assert runner.share(None, title="t").state is ShareState.NO_RECORD


def test_d05_the_bot_entrance_refuses_without_a_recipe():
    """레시피가 없으면 엔진을 돌릴 수 없다 — 브라우저를 열지 않는다."""
    import app.discord_bot as bot

    class _Agent:
        repository = None

    calls = []

    class _Runner:
        def share(self, record, *, title):
            calls.append(title)
            raise AssertionError("레시피 없이 브라우저를 열었습니다")

    lines = bot.share_replay_response(_Agent(), "11", recipe_text="",
                                      runner=_Runner())
    assert lines[0] == bot.SITE_SHARE_WARNING
    assert any("레시피" in line for line in lines[1:])
    assert not calls


@pytest.mark.parametrize("name", ["site_plan", "site_session"])
def test_d06_the_modules_do_not_hardcode_this_line(name):
    """🔴 이 경로의 카드도 순서도 코드에 적지 않았다."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(f"deck.{name}"))
    for needle in ("69811710", "21441617", "57835716", "30741503",
                   "76145142", "기르수", "스켈레촌", "orcust", "longirsu"):
        assert needle not in source, needle
