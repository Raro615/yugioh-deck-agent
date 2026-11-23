"""
Phase 6-BL — 리플레이의 **선택 근거**.

이 파일이 지키는 것
-------------------
A. 고르는 자리의 **다른 후보와 보류**를 그 자리의 ``legal`` 에서 그대로
   읽는다 — 지어내지 않고, 자른 것은 **총 수를 함께** 적는다.
B. 기록에 **칸이 없으면** 화면이 「당시 선택지 기록 없음」 이라고 적을 수
   있어야 한다 — 그래서 칸은 **있을 때만** 실린다.
C. 걸음에 반쯤 붙은 표를 내보내지 않는다 (``matched``).
D. 해결 중 후보는 **허가되지 않은 것도 사유와 함께** 적는다.
E. 추천 근거는 평가기가 **실제로 쓴 글자**이고, 점수를 만들지 않으며,
   🔴 **걸음의 동기로 소급하지 않는다** (칸이 따로 있다).
F. 디스코드 요약에는 **한 줄만** 더한다.
"""

from pathlib import Path

import pytest

CARDS_CDB = Path(__file__).resolve().parent.parent / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="cards.cdb 없음"
)


# ======================================================================
# 작은 가짜들 — 판을 만들지 않고 **모양**만 본다
# ======================================================================
class _Inst:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, _Inst) and other.value == self.value

    def __hash__(self):
        return hash(("inst", self.value))


class _Kind:
    def __init__(self, value):
        self.value = value


class _Card:
    def __init__(self, card_id):
        self.card_id = card_id


class _State:
    def __init__(self, table):
        self._table = table

    def find_instance(self, instance):
        return self._table.get(instance.value)


class _Duel:
    def __init__(self, table):
        self.state = _State(table)


class _Action:
    def __init__(self, kind, source=None, key=None, materials=(), cost=(),
                 effect_ref=None):
        self.kind = _Kind(kind)
        self.source = source
        self.materials = tuple(materials)
        self.cost_cards = tuple(cost)
        self.targets = ()
        self.effect_ref = effect_ref
        self._key = key or (kind, source.value if source else None)

    def canonical_state(self):
        return self._key


class _Held:
    def __init__(self, kind, code, reason, missing=None):
        self.kind = _Kind(kind)
        self.code = _Kind(code)
        self.reason = reason
        self.missing = missing


class _Legal:
    def __init__(self, allowed, withheld=(), seat=0):
        self.seat = seat
        self.allowed = tuple(allowed)
        self.withheld = tuple(withheld)


def _duel():
    return _Duel({
        1: _Card(69811710), 2: _Card(14558127), 3: _Card(48835607),
        4: _Card(30741503),
    })


# ======================================================================
# A. 고르는 자리의 다른 후보와 보류
# ======================================================================


def test_a01_the_snapshot_reads_siblings_and_withheld_from_legal():
    """🔴 **그 자리의 ``legal`` 에서 그대로 읽는다.**"""
    from app.main import _decision_snapshot

    duel = _duel()
    chosen = _Action("normal_summon", _Inst(1), key=("ns", 1))
    other = _Action("set_monster", _Inst(2), key=("sm", 2))
    legal = _Legal(
        [chosen, other],
        [_Held("activate_effect", "wrong_phase", "메인 페이즈가 아닙니다."),
         _Held("link_summon", "rule_not_implemented", "읽지 않았습니다.",
               missing="link-material")],
    )
    got = _decision_snapshot(duel, legal, chosen)
    assert got["source"] == "rerun"
    assert got["chosen"]["kind"] == "normal_summon"
    assert got["chosen"]["card"] == 69811710
    assert got["allowed_total"] == 2
    #: 🔴 **고른 것은 다른 후보 목록에 없다.**
    assert [one["kind"] for one in got["allowed"]] == ["set_monster"]
    assert got["allowed"][0]["card"] == 14558127
    assert got["withheld_total"] == 2
    #: 🔴 **미지원과 규칙이 막은 것을 가른다.**
    assert [one["missing"] for one in got["withheld"]] == [False, True]


def test_a02_cost_and_materials_are_recorded_as_passcodes():
    """비용 · 소재를 **패스코드**로 적는다 — 이름은 내보내기가 붙인다."""
    from app.main import _decision_snapshot

    duel = _duel()
    chosen = _Action("activate_effect", _Inst(3), key=("ae", 3),
                     cost=[_Inst(1)], effect_ref="48835607:e[4]")
    link = _Action("link_summon", _Inst(4), key=("ls", 4),
                   materials=[_Inst(3), _Inst(1)])
    got = _decision_snapshot(duel, _Legal([chosen, link]), chosen)
    assert got["chosen"]["cost"] == [69811710]
    assert got["chosen"]["effect_ref"] == "48835607:e[4]"
    assert got["allowed"][0]["materials"] == [48835607, 69811710]


def test_a03_truncation_keeps_the_total_so_the_screen_can_say_it():
    """
    🔴 **자른 것을 숨기지 않는다** — 목록은 짧아지고 ``allowed_total`` 은
    그대로이므로 화면이 "N개 중 M개 표시" 를 적을 수 있다.
    """
    from app.main import DECISION_SIBLING_LIMIT, _decision_snapshot

    duel = _duel()
    chosen = _Action("normal_summon", _Inst(1), key=("ns", 1))
    many = [chosen] + [
        _Action("set_monster", _Inst(2), key=("sm", n))
        for n in range(DECISION_SIBLING_LIMIT + 4)
    ]
    got = _decision_snapshot(duel, _Legal(many), chosen)
    assert len(got["allowed"]) == DECISION_SIBLING_LIMIT
    assert got["allowed_total"] == len(many)
    assert got["allowed_total"] - 1 > len(got["allowed"])


def test_a04_the_policy_records_one_decision_per_chosen_action():
    """고르는 함수가 **고를 때마다** 한 줄씩 적는다."""
    from app.main import ScriptedActionPolicy

    duel = _duel()
    first = _Action("normal_summon", _Inst(1), key=("ns", 1))
    second = _Action("activate_effect", _Inst(3), key=("ae", 3))
    policy = ScriptedActionPolicy([("ns", 1), ("ae", 3)])
    assert policy(duel, _Legal([first, second])) is first
    assert policy(duel, _Legal([second])) is second
    assert policy.done
    assert [one["chosen"]["kind"] for one in policy.decisions] == [
        "normal_summon", "activate_effect"
    ]
    #: 🔴 **후보 밖을 고르지 않았을 때는 적지 않는다** (고른 것이 없다).
    policy2 = ScriptedActionPolicy([("nope", 9)])
    assert policy2(duel, _Legal([first])) is None
    assert policy2.decisions == []


# ======================================================================
# B · C. 기록에 실리는 방식
# ======================================================================
class _Step:
    def __init__(self, order, kind, card_id=None, offers=()):
        self.order = order
        self.kind = kind
        self.card_id = card_id
        self.resolution_offers = tuple(offers)


class _Run:
    def __init__(self, steps):
        self.steps = tuple(steps)


def test_b01_decisions_attach_to_steps_by_kind_and_card():
    from deck.replay_export import _decision_blocks

    rows = [
        {"chosen": {"kind": "normal_summon", "card": 69811710}},
        {"chosen": {"kind": "link_summon", "card": 48835607}},
    ]
    run = _Run([
        _Step(1, "normal_summon", 69811710),
        _Step(2, "pass", None),
        _Step(3, "link_summon", 48835607),
    ])
    got = _decision_blocks(rows, run)
    assert got["matched"] is True
    assert sorted(got["steps"]) == ["1", "3"]
    assert got["steps"]["3"]["step"] == 3


def test_c01_a_half_matched_table_is_discarded_whole():
    """
    🔴 **반쯤 붙은 표를 내보내지 않는다** — 그러면 이 장면의 다른 후보를
    **다른 장면의 것**으로 보여 줄 수 있다.
    """
    from deck.replay_export import _decision_blocks

    rows = [
        {"chosen": {"kind": "normal_summon", "card": 69811710}},
        {"chosen": {"kind": "link_summon", "card": 48835607}},
    ]
    run = _Run([_Step(1, "normal_summon", 69811710)])
    got = _decision_blocks(rows, run)
    assert got["matched"] is False
    assert got["steps"] == {}
    assert got["count"] == 2


@requires_official_db
@pytest.mark.real_card
def test_b02_names_cover_the_resolution_candidates_too(repository):
    """
    🔴 **해결 중 후보의 이름도 붙인다** — 그 카드들은 덱에 있던 것이어서
    ``cards`` 표에 없을 수 있다.
    """
    from deck.replay_export import _decision_blocks

    offers = [{
        "effect_ref": "48835607:e[2]",
        "candidates": [
            {"instance": 10, "passcode": 27918365, "permitted": True,
             "verdict": "true", "reason": ""},
            {"instance": 11, "passcode": 90351981, "permitted": True,
             "verdict": "true", "reason": ""},
        ],
    }]
    run = _Run([_Step(1, "activate_effect", 48835607, offers)])
    got = _decision_blocks((), run, repository)
    assert got["names"]["27918365"]
    assert got["names"]["90351981"]


def test_b03_the_key_is_absent_when_nothing_was_recorded():
    """
    🔴 **칸이 없는 기록**이 "당시 선택지 기록 없음" 이다. 빈 칸을 실어
    "다른 후보가 없었다" 로 보이게 하지 않는다.
    """
    import inspect

    from deck import replay_export

    src = inspect.getsource(replay_export.export_opening_replay)
    assert 'record["decisions"]' in src
    #: 조건 없이 싣지 않는다.
    assert "if decisions or has_offers:" in src


# ======================================================================
# D. 해결 중 후보 — 거절된 것도 사유와 함께
# ======================================================================
class _Cand:
    def __init__(self, instance, card_id, permitted, reason):
        self.instance = _Inst(instance)
        self.card_id = card_id
        self.permitted = permitted
        self.verdict = _Kind("true" if permitted else "false")
        self.reason = reason


class _Offer:
    def __init__(self, candidates, minimum=1, maximum=1, declinable=False):
        self.effect_ref = "48835607:e[2]"
        self.target_ref = None
        self.candidates = tuple(candidates)
        self.minimum = minimum
        self.maximum = maximum
        self.declinable = declinable

    @property
    def permitted(self):
        return tuple(c for c in self.candidates if c.permitted)


class _Record:
    def __init__(self, offer, chosen):
        self.effect_ref = offer.effect_ref
        self.offer = offer
        self.chosen = tuple(_Inst(c) for c in chosen)


def test_d01_denied_candidates_keep_their_reason():
    from deck.opening import _resolution_offers

    offer = _Offer([
        _Cand(10, 27918365, True, ""),
        _Cand(11, 90351981, True, ""),
        _Cand(12, 69811710, False, "「성유물」 몬스터가 아닙니다."),
    ])
    rows = _resolution_offers([_Record(offer, [10])])
    assert len(rows) == 1
    row = rows[0]
    assert row["permitted_total"] == 2
    assert row["chosen"] == [10]
    assert row["minimum"] == 1 and row["maximum"] == 1
    denied = [c for c in row["candidates"] if not c["permitted"]]
    assert len(denied) == 1
    #: 🔴 **사유가 남아야 "왜 저 카드는 고를 수 없었나" 에 답할 수 있다.**
    assert "「성유물」" in denied[0]["reason"]


def test_d02_declinable_is_a_separate_axis_from_the_count():
    from deck.opening import _resolution_offers

    offer = _Offer([_Cand(10, 27918365, True, "")], declinable=True)
    rows = _resolution_offers([_Record(offer, [])])
    assert rows[0]["declinable"] is True
    assert rows[0]["chosen"] == []


# ======================================================================
# E. 추천 근거 — 평가기가 쓴 글자만
# ======================================================================
class _One:
    def __init__(self, index):
        self.index = index
        self.dominated_by = ()


class _Ranking:
    policy_label = "open-development v2"
    note = "🔴 **공동 추천 2개**"
    unjudged = ("전투는 보지 않습니다.",)

    def __init__(self, best):
        self._best = best
        self.criteria = ()

    @property
    def recommended(self):
        return tuple(_One(i) for i in self._best)

    def candidate(self, index):
        return _One(index)

    def reason_ko(self, index):
        return f"결과 {index} 는 어느 축에서도 지지 않았습니다."

    def stop_note_ko(self, index):
        return "⏹ 후속 행동 상한에 닿아 멈췄습니다."


class _Outcome:
    choice_branches = 92
    choice_plans = 92
    choice_offers_truncated = 3
    budget_hit = ("nodes",)
    nodes_expanded = 330
    deepest = 9


def test_e01_the_block_quotes_the_evaluator_and_invents_no_score():
    from app.main import autonomous_recommendation_block

    got = autonomous_recommendation_block(_Outcome(), _Ranking([69, 107]), 69)
    assert got["recommended"] is True
    assert got["reason"] == "결과 69 는 어느 축에서도 지지 않았습니다."
    assert got["co_recommended"] == [107]
    assert got["stop_note"].startswith("⏹")
    #: 🔴 **점수를 만들지 않는다.**
    assert "score" not in got and "점수" not in str(got)


def test_e02_the_search_counters_say_their_scope_and_mark_unexplored():
    """🔴 **탐색 한 번의 수치**다 — 걸음마다의 것이 아니다."""
    from app.main import autonomous_recommendation_block

    got = autonomous_recommendation_block(_Outcome(), _Ranking([69]), 69)
    search = got["search"]
    assert search["scope"] == "탐색 한 번 전체"
    assert search["choice_offers_truncated"] == 3
    assert search["budget_hit"] == ["nodes"]


def test_e03_a_not_recommended_candidate_says_so():
    from app.main import autonomous_recommendation_block

    got = autonomous_recommendation_block(_Outcome(), _Ranking([107]), 69)
    assert got["recommended"] is False
    assert got["co_recommended"] == [107]


def test_e04_no_ranking_means_no_block():
    """🔴 평가가 없으면 **칸을 만들지 않는다** (지어내지 않는다)."""
    from app.main import autonomous_recommendation_block

    assert autonomous_recommendation_block(_Outcome(), None, 1) is None


# ======================================================================
# F. 디스코드 한 줄
# ======================================================================


def test_f01_the_discord_line_is_one_line_and_points_at_the_replay():
    from app.discord_bot import _recommend_line

    line = _recommend_line(_Ranking([69, 107]), 69)
    assert line.count("\n") == 0
    assert line.startswith("🧭")
    assert "공동 추천" in line
    #: 🔴 **상세는 리플레이가 보여 준다** — 요약에 축 설명을 쏟지 않는다.
    assert "마지막 장면" in line
    assert "점수" not in line


def test_f02_no_ranking_means_no_line():
    from app.discord_bot import _recommend_line

    assert _recommend_line(None, None) == ""
    assert _recommend_line(_Ranking([69]), None) == ""


# ======================================================================
# G. 화면이 **엔진이 내린 판단만** 적는다
# ======================================================================


def test_g01_the_viewer_never_claims_the_search_preferred_this_action():
    """
    🔴 **최종 추천을 걸음의 동기로 소급하지 않는다** — 화면의 글자가
    "가능한 선택지 중 하나로 탐색했다" 여야 하고, "더 좋아서 골랐다" 가
    **없어야** 한다.
    """
    from deck.replay_viewer import render_replay_html

    html = render_replay_html({"format": "x", "cards": {}, "steps": [],
                               "events": []})
    assert "가능한 선택지 중 하나로 탐색했습니다" in html
    assert "이 행동을 더 높게 평가했다는 기록은 없습니다" in html
    assert "당시 선택지 기록 없음" in html
    for banned in ("더 좋아서", "최선의 수", "가장 좋은 행동"):
        assert banned not in html, banned


def test_g02_the_viewer_marks_unexplored_choices():
    from deck.replay_viewer import render_replay_html

    html = render_replay_html({"format": "x", "cards": {}, "steps": [],
                               "events": []})
    assert "미탐색" in html
    assert "확인하지 않은 대안이 남은 물음" in html
    #: 🔴 상한에 닿은 것을 "더 할 수 없다" 로 적지 않는다.
    assert "더 할 수 없다는 뜻이 아닙니다" in html


def test_g03_an_old_record_without_decisions_still_renders():
    """🔴 **기존 재생 기능을 유지한다** — 칸이 없는 기록도 그려진다."""
    from deck.replay_viewer import render_replay_html

    html = render_replay_html({
        "format": "x",
        "cards": {"1": {"passcode": 69811710, "name": "기르수", "owner": 0}},
        "steps": [{"order": 1, "kind": "normal_summon", "events": [0]}],
        "events": [{"seq": 0, "type": "monster_summoned", "actor": 0,
                    "changes": [{"kind": "monster_summoned", "instance": 1,
                                 "from": {"zone": "HAND"},
                                 "to": {"zone": "MZONE", "index": 0}}]}],
    })
    assert "decisions" not in html.split("<script id=\"replay-data\"")[0]
    assert len(html) > 10000
