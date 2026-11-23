"""
Phase 6-BH — **공동 추천 가운데 고른 후보**가 끝까지 같은 후보로 간다.

이 파일이 재는 것
-----------------
=========================================  ================================
요청과 후보를 **묶어** 둔다                   다른 요청의 번호가 섞이지 않는다
**탐색을 다시 돌리지 않는다**                 번호와 경로가 바뀌지 않는다
없는 번호 · 만료 · 남의 요청을 **가른다**      사용자가 할 일이 다르다
재실행이 어긋나면 **다른 후보로 바꾸지 않는다**  실패를 성공으로 내보내지 않는다
고른 후보가 **첨부와 사이트 입력**까지 간다      한 기록 하나를 쓴다
=========================================  ================================

🔴 **후보 번호를 코드에 적지 않는다.** 아래 시험들은 그때 그 탐색이 낸
번호를 **읽어서** 쓴다 — 17 · 24 같은 수를 적어 두면 탐색이 조금 달라질 때
시험이 거짓으로 통과하거나 거짓으로 깨진다.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_official_db

HAND = "69811710,14558127,23434538,10045474,24224830"


# ======================================================================
# A. 보관소 — 값과 경계
# ======================================================================
class _Result:
    """``SearchResult`` 의 자리만 흉내 낸다 — 🔴 값 하나뿐이다."""

    def __init__(self, index: int):
        self.index = index


def _store(**kw):
    from app.candidate_store import CandidateStore

    kw.setdefault("clock", lambda: 0.0)
    return CandidateStore(**kw)


def test_a01_a_request_is_bound_to_its_owner():
    """🔴 **남의 요청 ID 로 후보를 꺼낼 수 없다.**"""
    from app.candidate_store import PickProblem

    store = _store()
    kept = store.remember(owner="u-1", hand_ids=[1, 2], draft=object(),
                          results=[_Result(3), _Result(9)],
                          recommended=[3, 9], picked=3)
    row, found, problem = store.take(kept.request_id, owner="u-1", index=9)
    assert problem is None and found.index == 9 and row is kept
    _row, _found, problem = store.take(kept.request_id, owner="u-2", index=9)
    assert problem is PickProblem.NOT_MINE


def test_a02_three_failures_are_told_apart():
    """
    🔴 **없는 요청 · 만료 · 없는 번호를 가른다.** 사용자가 할 일이 다르다 —
    ID 를 고쳐 넣는 것, `/combo` 를 다시 돌리는 것, 번호를 고치는 것.

    🔴 **만료를 모양으로 추측하지 않는다.** 우리가 **실제로 버린** ID 만
    "만료" 라고 말한다 — 낸 적 없는 ID 는 그대로 "없다" 다.
    """
    from app.candidate_store import PickProblem

    now = [0.0]
    store = _store(ttl=10, capacity=4, clock=lambda: now[0])
    kept = store.remember(owner="u", hand_ids=[], draft=None,
                          results=[_Result(1)], recommended=[1])
    assert store.take("nope", owner="u")[2] is PickProblem.UNKNOWN_REQUEST
    #: 🔴 모양이 같아도 **낸 적이 없으면** "없다" 다.
    assert store.take("deadbeef", owner="u")[2] is PickProblem.UNKNOWN_REQUEST
    assert store.take(kept.request_id, owner="u", index=2)[2] \
        is PickProblem.NO_SUCH_RESULT
    now[0] = 100.0
    assert store.take(kept.request_id, owner="u")[2] is PickProblem.EXPIRED


def test_a03_the_oldest_request_is_dropped_first():
    """🔴 **끝없이 쌓지 않는다** — 탐색 결과는 무겁다."""
    from app.candidate_store import PickProblem

    now = [0.0]
    store = _store(ttl=1000, capacity=2, clock=lambda: now[0])
    rows = []
    for _ in range(3):
        now[0] += 1.0
        rows.append(store.remember(owner="u", hand_ids=[], draft=None,
                                   results=[_Result(1)], recommended=[1]))
    assert len(store) == 2
    #: 🔴 가장 오래된 것이 **만료로** 보고된다 (버린 것을 기억한다).
    assert store.take(rows[0].request_id, owner="u")[2] is PickProblem.EXPIRED
    assert store.take(rows[2].request_id, owner="u")[2] is None


def test_a04_the_store_holds_values_not_a_duel():
    """
    🔴 **판을 담지 않는다.** 담으면 지난 요청의 판이 살아 있게 되고, 뒤의
    실행이 그것을 건드릴 수 있다. 칸 이름으로 그 사실을 고정한다.
    """
    import dataclasses

    from app.candidate_store import StoredRequest

    names = {field.name for field in dataclasses.fields(StoredRequest)}
    #: 🔴 ``rationales`` 가 늘었다 (Phase 6-BM) — 후보 번호마다의 **추천
    #: 근거**이고, ``/combo-pick`` 이 탐색을 다시 돌리지 않기 때문에 여기
    #: 보관한다. 🔴 **값이다** (사전) — 판도 평가기도 담지 않는다.
    assert names == {"request_id", "owner", "hand_ids", "draft", "results",
                     "recommended", "created", "picked", "rationales"}
    for forbidden in ("duel", "state", "board", "chain", "executor"):
        assert forbidden not in names, forbidden


# ======================================================================
# B. ``/combo-pick`` — 고른 후보가 끝까지 간다
# ======================================================================
class _Repo:
    """``agent.repository`` 자리 — 이 시험들은 카드 이름을 쓰지 않는다."""

    def get(self, card_id):
        return None


class _Agent:
    repository = _Repo()


def _candidate(index: int, steps: int = 2):
    """``render_open_candidate`` 가 읽는 모양만 갖춘 후보 하나."""
    class _Ask:
        chosen_card_ids = ()

    class _Step:
        def __init__(self, order):
            self.order = order
            self.kind = "normal_summon"
            self.choices = (_Ask(),)

    class _Meta:
        stop = None

    class _One:
        def __init__(self):
            self.index = index
            self.path = tuple(_Step(n + 1) for n in range(steps))
            self.rerun_state = "verified"
            self.verified = True
            self.duplicates = 0
            self.resources = None
            self.meta = _Meta()

    return _One()


def test_b01_picking_a_missing_number_names_what_is_there(monkeypatch):
    """🔴 **없는 번호를 고르면 보관한 번호를 적어 준다.**"""
    from app import discord_bot as bot

    store = _store()
    kept = store.remember(owner="u", hand_ids=[1], draft=None,
                          results=[_candidate(4), _candidate(7)],
                          recommended=[4], picked=4)
    out = bot.pick_response(_Agent(), kept.request_id, "99", owner="u",
                            store=store)
    assert out.failed is True
    said = "\n".join(out.messages)
    assert "그 번호의 후보가 그 요청에 없습니다" in said
    assert "`4`" in said and "`7`" in said


def test_b02_a_bad_number_is_not_a_missing_request():
    """🔴 **숫자가 아닌 입력**은 "요청이 없다" 가 아니다."""
    from app import discord_bot as bot

    store = _store()
    kept = store.remember(owner="u", hand_ids=[1], draft=None,
                          results=[_candidate(4)], recommended=[4], picked=4)
    out = bot.pick_response(_Agent(), kept.request_id, "열일곱", owner="u",
                            store=store)
    assert out.failed is True
    assert "후보 번호를 읽지 못했습니다" in out.messages[0]


def test_b03_a_broken_rerun_is_not_swapped_for_another_candidate(monkeypatch):
    """
    🔴 **재실행이 어긋나면 다른 후보로 조용히 바꾸지 않는다.**

    그때 첨부도 만들지 않는다 — 어긋난 재실행을 "성공한 전개" 로 내보내는
    길을 남기지 않는다.
    """
    from app import discord_bot as bot
    from app import main as app_main

    store = _store()
    kept = store.remember(owner="u", hand_ids=[1], draft=None,
                          results=[_candidate(4), _candidate(7)],
                          recommended=[4, 7], picked=4)
    monkeypatch.setattr(
        app_main, "autonomous_rerun_record",
        lambda *a, **k: (None, "마지막 판이 달랐습니다"))
    out = bot.pick_response(_Agent(), kept.request_id, "7", owner="u",
                            store=store)
    said = "\n".join(out.messages)
    assert "결과 7" in said
    assert "다시 실행한 기록을 만들지 못했습니다" in said
    assert "마지막 판이 달랐습니다" in said
    assert out.attachments == ()
    #: 🔴 **다른 후보의 번호가 나타나지 않는다.**
    assert "결과 4" not in said


def test_b04_the_pick_never_runs_a_new_search(monkeypatch):
    """
    🔴 **고르는 것이 탐색을 다시 돌리는 일이 되면 안 된다.**

    다시 돌리면 예산에 걸리는 자리가 달라져 **번호와 경로가 바뀔 수 있고**,
    그러면 사용자가 본 번호가 다른 전개를 가리킨다. 이 시험은 탐색 함수를
    **터지게** 바꿔 두고 고르기가 그것을 부르지 않는다는 사실을 센다.
    """
    from app import discord_bot as bot
    from app import main as app_main

    def _boom(*args, **kwargs):
        raise AssertionError("고르기가 탐색을 다시 돌렸습니다")

    monkeypatch.setattr(app_main, "autonomous_search_opening", _boom)
    monkeypatch.setattr(app_main, "autonomous_rerun_record",
                        lambda *a, **k: ({"format": "x", "events": [],
                                          "steps": []}, ""))
    monkeypatch.setattr(bot, "replay_attachment",
                        lambda record: (None, bot.ReplayState.NOT_RUN))
    monkeypatch.setattr(bot, "viewer_attachment",
                        lambda record: (None, bot.ReplayState.NOT_RUN))
    store = _store()
    kept = store.remember(owner="u", hand_ids=[1], draft=None,
                          results=[_candidate(4)], recommended=[4], picked=4)
    out = bot.pick_response(_Agent(), kept.request_id, "4", owner="u",
                            store=store)
    assert "결과 4" in "\n".join(out.messages)


def test_b05_picking_an_unrecommended_candidate_says_so():
    """🔴 **추천이 아닌 후보를 골랐으면 그렇게 적는다** (막지는 않는다)."""
    from app import discord_bot as bot
    from app import main as app_main
    import pytest as _pytest

    store = _store()
    kept = store.remember(owner="u", hand_ids=[1], draft=None,
                          results=[_candidate(4), _candidate(7)],
                          recommended=[4], picked=4)
    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(app_main, "autonomous_rerun_record",
                      lambda *a, **k: (None, "확인용"))
        out = bot.pick_response(_Agent(), kept.request_id, "7", owner="u",
                                store=store)
    assert "추천 후보가 아닙니다" in "\n".join(out.messages)


# ======================================================================
# C. 실제 엔진 — 두 추천이 **서로 다른 올바른 기록**을 준다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_c01_each_recommendation_gives_its_own_record(repository):
    """
    🔴 **고른 후보마다 다른 기록**이고, 그 기록이 **그 후보의 최종 판**을
    담는다 (Phase 6-BH).

    🔴 **번호를 적어 두지 않는다** — 그때 그 탐색이 낸 추천 번호를 읽어 쓴다.
    """
    from pathlib import Path

    from app.candidate_store import CandidateStore
    from app.discord_bot import combo_response, pick_response
    from deck.site_plan import build_site_plan

    class _Holder:
        pass

    agent = _Holder()
    agent.repository = repository
    recipe = (Path(__file__).resolve().parent.parent
              / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    store = CandidateStore()
    said = combo_response(agent, HAND, recipe_text=recipe, search_text="auto",
                          owner="u-1", store=store)
    invite = [line for message in said.messages
              for line in message.splitlines() if line.startswith("🎞")]
    assert invite, "요청 ID 를 적은 줄이 없습니다"
    import re

    found = re.search(r"request:([0-9a-f]+)", invite[0])
    assert found, invite[0]
    request_id = found.group(1)
    kept, _one, problem = store.take(request_id, owner="u-1")
    assert problem is None, problem
    assert len(kept.recommended) >= 1

    seen = {}
    for index in kept.recommended:
        out = pick_response(agent, request_id, str(index), owner="u-1",
                            store=store)
        assert not out.failed, out.messages
        text = "\n".join(out.messages)
        assert f"결과 {index}" in text
        #: 🔴 **다른 추천 번호가 이 응답의 주체로 나타나지 않는다.**
        for other in kept.recommended:
            if other != index:
                assert f"**결과 {other}** 를 골랐습니다" not in text
        payload = next((a for a in out.attachments
                        if a.filename.endswith(".json")), None)
        assert payload is not None, out.messages
        seen[index] = payload.text

    assert len(set(seen.values())) == len(seen), "두 후보가 같은 기록을 냈습니다"

    #: 🔴 **사이트 입력까지 그 기록 하나로 간다.**
    import json

    for index, text in seen.items():
        record = json.loads(text)
        plan = build_site_plan(record)
        assert plan["operations"], index
        sets = [change for event in record["events"]
                for change in event.get("changes") or ()
                if change.get("kind") == "card_set"]
        #: 세트가 있는 후보면 뒷면 기대가 **그 기록에서** 나온다.
        assert bool(plan["expect_positions"]["face_down"]) == bool(sets)
