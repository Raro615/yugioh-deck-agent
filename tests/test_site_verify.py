"""
Phase 6-AY — **사이트 조작의 판정부와 실행 격리**.

이 파일이 재는 것
-----------------
=========================================  ================================
장수가 같아도 **카드가 바뀌면** 실패         ``compareFinal``
**예상 밖 카드**가 있으면 실패               ``compareFinal``
**빈 존**은 비어 있으면 통과                 ``compareFinal``
**읽을 수 없는 판**은 성공이 아니다          ``observed.problems``
좌표와 **화면 표시**가 다르면 실패           ``crossCheck``
옛 결과가 **이번 성공으로 돌아오지 않는다**   ``run_site_session``
=========================================  ================================

🔴 판정부는 조작기와 **같은 JavaScript 코드**다 (``scripts/
duel_simulator_verify.js``). 브라우저를 열지 않고 값만 넣어 돌린다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "scripts" / "duel_simulator_verify.js"


def _compare(expect, observed, counts) -> dict:
    """조작기가 쓰는 그 함수를 그대로 부른다."""
    script = (
        f"const v=require({str(VERIFY)!r});"
        "const a=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(v.compareFinal(a[0],a[1],a[2])));"
    )
    done = subprocess.run(
        ["node", "-e", script, json.dumps([expect, observed, counts])],
        capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def _identity(row, want_src, src_of) -> dict:
    script = (
        f"const v=require({str(VERIFY)!r});"
        "const a=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(v.identityOf(a[0],a[1],a[2])));"
    )
    done = subprocess.run(
        ["node", "-e", script, json.dumps([row, want_src, src_of])],
        capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


_EXPECT = {
    "Grave": {"slots": ["main-0", "extra-1"]},
    "Banish": {"slots": ["main-11", "main-24"]},
    "Extra Monster Zone1": {"slots": ["extra-4"]},
    "Extra Monster Zone2": {"slots": []},
    "Monster Zone1": {"slots": []},
    "Hand": {"slots": ["main-1"]},
}


def _observed(by_zone, problems=()):
    return {"byZone": by_zone, "bySlot": {}, "problems": list(problems),
            "srcOf": {}}


_GOOD = {"Grave": ["extra-1", "main-0"], "Banish": ["main-24", "main-11"],
         "Extra Monster Zone1": ["extra-4"], "Hand": ["main-1"]}
_COUNTS = {"Grave": 2, "Banish": 2, "Hand": 1}


# ======================================================================
# A. 최종 대조
# ======================================================================
def test_a01_the_matching_board_passes():
    verdict = _compare(_EXPECT, _observed(_GOOD), _COUNTS)
    assert verdict["allOk"], verdict["checks"]


def test_a02_same_counts_but_swapped_cards_fails():
    """
    🔴 **장수만 세면 통과하던 경우.** 묘지와 제외의 카드가 서로 바뀌었다 —
    두 존 다 2장이지만 들어 있는 개체가 다르다.
    """
    swapped = dict(_GOOD)
    swapped["Grave"] = ["main-24", "main-11"]
    swapped["Banish"] = ["extra-1", "main-0"]
    verdict = _compare(_EXPECT, _observed(swapped), _COUNTS)
    assert not verdict["allOk"]
    grave = [c for c in verdict["checks"] if c["zone"] == "Grave"][0]
    assert grave["saw"] == grave["want"] == 2      # 장수는 같다
    assert sorted(grave["missing"]) == ["extra-1", "main-0"]
    assert sorted(grave["unexpected"]) == ["main-11", "main-24"]


def test_a03_a_field_card_in_the_wrong_slot_fails():
    """🔴 **롱기르수가 다른 칸에 있으면** 통과하지 않는다."""
    moved = dict(_GOOD)
    del moved["Extra Monster Zone1"]
    moved["Extra Monster Zone2"] = ["extra-4"]
    verdict = _compare(_EXPECT, _observed(moved), _COUNTS)
    assert not verdict["allOk"]
    first = [c for c in verdict["checks"] if c["zone"] == "Extra Monster Zone1"][0]
    second = [c for c in verdict["checks"] if c["zone"] == "Extra Monster Zone2"][0]
    assert first["missing"] == ["extra-4"]
    assert second["unexpected"] == ["extra-4"]


def test_a04_an_empty_zone_that_is_empty_passes():
    """🔴 **정상적으로 빈 존**은 통과한다 — 빈 것을 실패로 세지 않는다."""
    verdict = _compare(_EXPECT, _observed(_GOOD), _COUNTS)
    empty = [c for c in verdict["checks"] if c["zone"] == "Monster Zone1"][0]
    assert empty["want"] == empty["saw"] == 0
    assert empty["ok"]


def test_a05_a_card_in_a_zone_the_plan_never_mentions_fails():
    """계획이 모르는 칸에 카드가 있으면 **예상 밖**이다."""
    stray = dict(_GOOD)
    stray["Spell & Trap Zone3"] = ["main-2"]
    verdict = _compare(_EXPECT, _observed(stray), _COUNTS)
    assert not verdict["allOk"]
    hit = [c for c in verdict["checks"] if c["zone"] == "Spell & Trap Zone3"][0]
    assert hit["unexpected"] == ["main-2"]


def test_a06_an_unreadable_board_is_not_a_pass():
    """🔴 가려졌거나 크기가 0 인 카드가 있으면 **성공이 아니다**."""
    verdict = _compare(_EXPECT, _observed(_GOOD, ["main-7: 크기가 0 입니다"]),
                       _COUNTS)
    assert not verdict["allOk"]
    assert verdict["problems"] == ["main-7: 크기가 0 입니다"]


def test_a07_the_screen_count_cross_check_catches_a_hidden_card():
    """
    🔴 **좌표만 믿지 않는다.** 화면은 묘지 3장이라는데 좌표로는 2장만
    읽혔다면 한 장을 못 읽은 것이다.
    """
    verdict = _compare(_EXPECT, _observed(_GOOD), {**_COUNTS, "Grave": 3})
    assert not verdict["allOk"]
    cross = [c for c in verdict["crossCheck"] if c["zone"] == "Grave"][0]
    assert cross["label"] == 3 and cross["geometry"] == 2 and not cross["ok"]


# ======================================================================
# B. 개체 확인 — 이력이 늘었다는 사실만으로는 모자란다
# ======================================================================
def test_b01_a_history_row_without_this_cards_thumbnail_is_not_identity():
    got = _identity({"text": "Activate Effect · Grave", "srcs": ["data:x"]},
                    "data:y", {"main-0": "data:y"})
    assert not got["ok"]


def test_b02_a_matching_thumbnail_is_identity():
    got = _identity({"text": "Grave → Banish1", "srcs": ["data:y"]},
                    "data:y", {"main-0": "data:y"})
    assert got["ok"] and got["how"] == "썸네일 일치"


def test_b03_two_cards_with_the_same_picture_are_called_ambiguous():
    """🔴 같은 그림이 둘이면 **맞았다고 하지 않고 모호하다고 적는다**."""
    got = _identity({"text": "Deck → Grave", "srcs": ["data:y"]}, "data:y",
                    {"main-0": "data:y", "main-5": "data:y"})
    assert got["ok"] and "모호" in got["how"]


def test_b04_a_row_with_no_thumbnail_is_not_identity():
    assert not _identity({"text": "x", "srcs": []}, "data:y", {})["ok"]


# ======================================================================
# C. 실행 격리 — 옛 결과가 이번 성공으로 돌아오지 않는다
# ======================================================================
def _toy_record() -> dict:
    return {
        "format": "engine-replay/5",
        "cards": {"1": {"passcode": 11, "owner": 0, "name": "합성", "kind": "monster"}},
        "initial": {"zones": {"0": {"HAND": [1]}}},
        "steps": [], "events": [],
        "final": {"zones": {"0": {"HAND": [1]}}, "slots": []},
        "unsupported": [],
    }


class _Done:
    def __init__(self, returncode=0, stderr="", timed_out=False):
        self.returncode = returncode
        self.stderr = stderr
        self.timed_out = timed_out


def _writer(payload, *, returncode=0, timed_out=False):
    def run(command, path):
        if payload is not None:
            (Path(path) / "result.json").write_text(
                payload if isinstance(payload, str)
                else json.dumps(payload), encoding="utf-8")
        return _Done(returncode, "", timed_out)
    return run


def _ok_payload(run_id, **over):
    payload = {
        "run_id": run_id, "stopped_at": None, "share_requested": True,
        "share_url": "https://example.test/replay/new",
        "operations": [{"ok": True}, {"ok": True}],
        "stages": {"final": {"all_ok": True}}, "notes": [],
    }
    payload.update(over)
    return payload


def test_c01_each_request_runs_in_its_own_folder(tmp_path):
    from deck.site_session import run_site_session

    seen = []

    def runner(command, path):
        seen.append(Path(path))
        rid = command[command.index("--run-id") + 1]
        (Path(path) / "result.json").write_text(
            json.dumps(_ok_payload(rid)), encoding="utf-8")
        return _Done()

    first = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                             share=True, runner=runner)
    second = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                              share=True, runner=runner)
    assert first.workdir != second.workdir
    assert first.run_id != second.run_id
    assert first.shared and second.shared


def test_c02_a_leftover_result_is_not_this_requests_success(tmp_path):
    """
    🔴 **이번 작업의 핵심 수정.** 지난 실행의 성공 결과가 남아 있는 폴더에
    이번 실행이 **결과를 쓰기 전에** 죽어도, 그 URL 이 이번 요청의 성공으로
    돌아오지 않는다.
    """
    from deck.site_session import RunStatus, run_site_session

    workdir = tmp_path / "fixed"
    workdir.mkdir()
    (workdir / "result.json").write_text(json.dumps(_ok_payload("OLDRUN")),
                                         encoding="utf-8")
    run = run_site_session(_toy_record(), workdir=workdir, title="t",
                           share=True, runner=_writer(None, returncode=1))
    assert run.status is RunStatus.RUN_ID_MISMATCH
    assert run.share_url is None and not run.shared
    #: 옛 산출물은 지우지 않는다 — 그대로 남아 있다.
    assert json.loads((workdir / "result.json").read_text())["run_id"] == "OLDRUN"


def test_c03_a_url_without_verification_is_not_a_share(tmp_path):
    """🔴 **URL 이 있다는 이유만으로** 공유 성공으로 치지 않는다."""
    from deck.site_session import RunStatus, run_site_session

    def runner(command, path):
        rid = command[command.index("--run-id") + 1]
        return _writer(_ok_payload(rid, stages={"final": {"all_ok": False}}))(
            command, path)

    run = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                           share=True, runner=runner)
    assert run.status is RunStatus.OK
    assert run.share_url and not run.shared
    assert "최종 판" in run.reason


def test_c04_a_half_finished_run_is_not_a_share(tmp_path):
    """조작이 하나라도 확인되지 않았으면 공유 성공이 아니다."""
    from deck.site_session import run_site_session

    def runner(command, path):
        rid = command[command.index("--run-id") + 1]
        return _writer(_ok_payload(
            rid, operations=[{"ok": True}, {"ok": False}]))(command, path)

    run = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                           share=True, runner=runner)
    assert not run.shared


@pytest.mark.parametrize("payload, status", [
    (None, "missing_result"),
    ("{이건 JSON 이 아니다", "bad_json"),
])
def test_c05_missing_or_broken_results_are_told_apart(tmp_path, payload, status):
    from deck.site_session import run_site_session

    run = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                           share=True, runner=_writer(payload, returncode=1))
    assert run.status.value == status
    assert not run.shared and run.share_url is None


def test_c06_a_timeout_is_its_own_outcome(tmp_path):
    from deck.site_session import RunStatus, run_site_session

    run = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                           share=True,
                           runner=_writer(None, returncode=-9, timed_out=True))
    assert run.status is RunStatus.TIMEOUT
    assert not run.shared


def test_c07_a_request_after_a_timeout_still_succeeds(tmp_path):
    """🔴 시간 초과 뒤의 **다음 요청**이 앞 실행에 걸려 넘어지지 않는다."""
    from deck.site_session import RunStatus, run_site_session

    first = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                             share=True,
                             runner=_writer(None, timed_out=True))
    assert first.status is RunStatus.TIMEOUT

    def runner(command, path):
        rid = command[command.index("--run-id") + 1]
        return _writer(_ok_payload(rid))(command, path)

    second = run_site_session(_toy_record(), base_dir=tmp_path, title="t",
                              share=True, runner=runner)
    assert second.status is RunStatus.OK and second.shared
    assert second.workdir != first.workdir


def test_c08_the_plan_carries_the_run_id(tmp_path):
    from deck.site_session import new_run_id, prepare_run_dir

    rid = new_run_id()
    plan = prepare_run_dir(_toy_record(), tmp_path, title="t", run_id=rid)
    assert plan["run_id"] == rid
    assert json.loads((tmp_path / "plan.json").read_text(
        encoding="utf-8"))["run_id"] == rid


def test_c09_the_discord_runner_gets_a_fresh_folder_each_time(tmp_path):
    """디스코드 입구도 **요청마다 다른 자리**에서 돈다."""
    from app.site_share import SiteShareRunner

    bases = []

    class _Run:
        shared = True
        share_url = "https://example.test/replay/x"
        operations_ok = operations_total = 1
        final_ok = True
        reason = ""
        run_id = "rid"

    def session(record, *, base_dir, title, share):
        bases.append(Path(base_dir))
        return _Run()

    runner = SiteShareRunner(tmp_path, session=session)
    runner.share({"a": 1}, title="t")
    runner.share({"a": 1}, title="t")
    assert bases == [tmp_path, tmp_path]        # 기준 폴더는 같고
    #: 실제 실행 폴더는 ``run_site_session`` 이 그 아래에 새로 만든다.
    assert len(bases) == 2
