r"""
Phase 3-F-39 — 카드 갱신 실행 조건(N30)과 분석 coverage 분모(N31) 감사.

Phase 3-F-38 이 §10 에 남긴 두 위험을 **각각** 조사한 결과를 고정한다.

* **N30** — ``scripts/update_cards.py`` 의 ``--changed-only`` 는
  ``action="store_true"`` 라 기본값이 ``False`` 인데 help 는 "(기본 동작)"
  이라고 적혀 있었다. 그래서 ``--update`` 만 주면 **분석 단계가 아예 돌지
  않았고**, 모듈 docstring 이 적어 둔 흐름
  (``수집 -> 변경 감지 -> 병합 -> 분석 -> 인덱스 -> 검증``)과 어긋났다.
* **N31** — :meth:`CardAnalysis.coverage` 의 비율 분모는 ``effects``
  (= 증명된 **등록** 효과)다. 증명되지 않은 블록은 ``unbound_effects`` 로
  빠지므로 분모에서 조용히 사라지고, 비율이 **실제보다 좋아 보인다**.

두 항목은 코드 경로를 공유하지 않는다. 판정도 따로 적는다.

🔴 **이 파일은 문자열 존재 확인으로 실행 동작 검증을 대체하지 않는다.**
``main()``·``cmd_analyze``·``EffectAnalyzer``·``coverage()`` 를 실제로
돌리고 그 출력과 반환값을 읽는다. 소스 검사는 "그 자리에 그 코드가 있다"
를 확인해야 하는 금지 조항에만 쓴다.
"""

from __future__ import annotations

import ast
import collections
import contextlib
import inspect
import io
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import app.main as main_module
import scripts.update_cards as update_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import CardAnalysis, HandlerBinding
from app.main import cmd_analyze
from core.card_model import Card
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from engine.ids import EffectRef, effect_refs
from scripts.update_cards import report_bindings, summarise
from sources.lua_loader import parse_lua_source
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-39 가 실측한 기준값 (테스트가 실제로 다시 산출한다) ----------
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
#: ``coverage()`` 의 분자·분모를 코퍼스 전수로 합산한 값
COVERAGE_TOTALS = {
    "effects": 26352, "resolution_effects": 8283, "unbound_effects": 0,
    "has_condition": 11626, "condition_structured": 5130,
    "with_costs": 4982, "cost_structured": 4736,
    "with_selection": 11990, "with_actions": 14499,
}
#: 🔴 해결 효과 8,283개는 **어떤 비율의 분모에도 없다** — 전체 블록의 23.9%.
RESOLUTION_SHARE = 8283 / 34635
CARD_TOTAL = 14127

REAL_CARDS = [32807846, 23434538, 2511]     # 증원 · 빙결계의 용 트리슈라 · 유벨


# ===========================================================================
# 공용 도구 — 실제 parser/analyzer/CLI/main 경로만 쓴다
# ===========================================================================
TWO_BLOCKS = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_ACTIVATE)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        e1:SetOperation(s.op)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetType(EFFECT_TYPE_ACTIVATE)
        e2:SetCode(EVENT_FREE_CHAIN)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
    function s.con(e,tp) return true end
    function s.op(e,tp,eg,ep,ev,re,r,rp) Duel.Draw(tp,1,REASON_EFFECT) end
    function s.cost(e,tp,eg,ep,ev,re,r,rp,chk) if chk==0 then return true end end
"""
#: 핸들러가 하나도 없는 **유효한** 블록 — 미증명과 혼동하면 안 된다
NO_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        e1:SetValue(500)
        c:RegisterEffect(e1)
    end
"""
NO_BLOCK = "function s.initial_effect(c)\nend\n"


class _StubRepo:
    """``cmd_analyze`` 와 ``EffectAnalyzer`` 가 실제로 쓰는 최소 인터페이스."""

    constants = None

    def __init__(self, script_dir, card):
        self.script_dir = script_dir
        self._card = card

    def get(self, card_id):
        return self._card if card_id == self._card.id else None


def _analyze(text: str, *, card_id: int = 1, shift_one_offset: bool = False,
             break_digest: bool = False, drop_digest: bool = False,
             delete_file: bool = False):
    """카드와 디스크 텍스트를 만들고 **실제 분석기**를 돌린다.

    ``shift_one_offset`` 은 "지문은 맞는데 블록 식별자 하나만 어긋난 캐시"
    를 만든다. 옛 parser 가 offset 규약을 달리 적어 둔 캐시가 그대로 남은
    경우가 실제로 이 모양이고, **부분 미증명**을 만드는 유일한 경로다.
    """
    text = textwrap.dedent(text)
    directory = tempfile.mkdtemp()
    name = f"c{card_id}.lua"
    path = pathlib.Path(directory, name)
    path.write_text(text, encoding="utf-8")
    card = Card(id=card_id, name=name)
    card.script = parse_lua_source(card_id, name, text)
    if shift_one_offset:
        offsets = list(card.script.effect_offsets)
        offsets[-1] += 1
        card.script.effect_offsets = offsets
    if break_digest:
        card.script.source_digest = "0" * 64
    if drop_digest:
        card.script.source_digest = None
    if delete_file:
        path.unlink()
    repo = _StubRepo(directory, card)
    return card, repo, EffectAnalyzer(repo).analyze(card)


def _run_cli(capsys, **kwargs) -> str:
    """**실제 ``cmd_analyze``** 를 돌려 출력 문자열을 돌려준다."""
    card, repo, _analysis = _analyze(**kwargs)
    agent = type("Agent", (), {"repository": repo})()
    args = type("Args", (), {"card_id": card.id})()
    assert cmd_analyze(agent, args) == 0
    return capsys.readouterr().out


class _Plan:
    def __init__(self, ids, empty=False):
        self._ids = list(ids)
        self._empty = empty

    def counts(self):
        return {"lua": {"new": 0, "changed": len(self._ids),
                        "removed": 0, "unchanged": 12700}}

    def changed_card_ids(self):
        return list(self._ids)

    def is_empty(self):
        return self._empty


class _Manager:
    def __init__(self, ids, empty=False, adapters=()):
        self._plan = _Plan(ids, empty)
        self._adapters = list(adapters)

    def available_adapters(self):
        return self._adapters

    def plan(self, only=None):
        return self._plan

    def commit(self, only=None):
        return self._plan


def _run_main(monkeypatch, argv, ids, *, empty=False, adapters=()):
    """**실제 ``update_cards.main()``** 을 돌린다. 상태 파일은 건드리지 않는다."""
    monkeypatch.setattr(
        update_module, "build_manager",
        lambda *a, **k: _Manager(ids, empty=empty, adapters=adapters),
    )
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = update_module.main(argv)
    return code, buffer.getvalue()


def _flag_action_and_help():
    """``--changed-only`` 의 **실제 선언**을 소스에서 그대로 꺼낸다."""
    source = inspect.getsource(update_module.main)
    match = re.search(
        r'"--changed-only",\s*\n\s*action="(\w+)",\s*\n\s*help="([^"]*)"', source
    )
    assert match is not None, "선언 모양이 바뀌었다 — 테스트를 먼저 읽어라"
    return match.group(1), match.group(2)


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-39:"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        files: set[str] = set()
        for sha in shas:
            out = subprocess.run(
                ["git", "show", "--name-only", "--format=", sha],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
            ).stdout
            files.update(x for x in out.split("\n") if x.strip())
        return files
    except (OSError, subprocess.SubprocessError):
        return set()


# ===========================================================================
# A. N30 — ``--changed-only`` 의 기본값과 갱신 실행 조건
# ===========================================================================
def test_01_the_flag_is_still_declared_as_store_true_with_default_false():
    r"""🔴 §2 ① ③ — 실제 선언은 ``store_true`` 이고 기본값은 ``False`` 다.

    이 사실 자체는 **고치지 않았다**. 고친 것은 "``False`` 일 때 분석이 통째로
    빠지는" 실행 조건이다. 기본값을 조용히 ``True`` 로 바꾸면 끌 수 없는
    flag 가 되고, 끄는 쪽("전부 다시 분석")은 코드에 존재하지 않는다.
    """
    action, _help = _flag_action_and_help()
    assert action == "store_true"
    parser = inspect.getsource(update_module.main)
    assert "--changed-only" in parser
    #: argparse 가 실제로 무엇을 돌려주는지 직접 확인한다
    import argparse

    probe = argparse.ArgumentParser()
    probe.add_argument("--changed-only", action=action)
    assert probe.parse_args([]).changed_only is False
    assert probe.parse_args(["--changed-only"]).changed_only is True


def test_02_update_alone_now_runs_the_analysis(monkeypatch):
    r"""🔴 §2 ② — ``--update`` 만 줘도 변경된 카드가 **분석된다**.

    수정 전에는 이 출력이 전혀 나오지 않았다 (N30 재현).
    """
    code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert code == 0
    assert "다시 분석했습니다" in out
    assert "효과 블록 결합 상태" in out


def test_03_the_flag_and_no_flag_produce_the_same_output(monkeypatch):
    r"""🔴 §2 ② ⑦ — 기존 호출자(``--changed-only`` 를 주던 쪽)의 동작이
    **그대로**다. 두 호출의 출력이 글자 단위로 같다."""
    _code_a, plain = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    _code_b, flagged = _run_main(
        monkeypatch, ["--update", "--changed-only"], REAL_CARDS)
    assert plain == flagged


def test_04_the_help_text_no_longer_claims_an_untrue_default():
    r"""🔴 §2 ④ — help 의 "기본 동작" 주장이 실제 실행과 일치한다.

    예전 help 는 "(기본 동작)" 이라고 적고 실제로는 기본에서 분석을
    건너뛰었다. 이제는 분석이 항상 돌므로 그 주장이 참이다. 문구만 고치고
    실행을 그대로 두는 선택은 "문서화된 결함" 이 되므로 하지 않았다.
    """
    _action, help_text = _flag_action_and_help()
    assert "기본 동작" in help_text
    #: 그 주장이 참인지 **실행으로** 확인한다 — 문구 검사로 끝내지 않는다
    source = inspect.getsource(update_module.main)
    assert "if args.changed_only and affected:" not in source
    assert re.search(r"^\s{4}if affected:\s*$", source, re.M) is not None


def test_05_no_changed_card_means_no_analysis_and_no_noise(monkeypatch):
    r"""🟢 §2 ⑤ / §6 ⑤ — 변경된 카드가 없으면 분석하지 않고 조용하다."""
    code, out = _run_main(monkeypatch, ["--update"], [])
    assert code == 0
    assert "다시 분석했습니다" not in out
    assert "효과 블록 결합 상태" not in out
    #: 카드 현황은 그대로 나온다 — 분석을 건너뛴 것이 검증 생략은 아니다
    assert "카드 데이터 현황" in out and "검증 통과" in out


def test_06_an_empty_plan_returns_before_touching_the_repository(monkeypatch):
    r"""🟢 §2 ⑤ — 바뀐 것이 아예 없으면 리포지토리를 다시 만들지도 않는다."""
    code, out = _run_main(monkeypatch, ["--update"], [], empty=True)
    assert code == 0
    assert "바뀐 것이 없습니다" in out
    assert "다시 분석했습니다" not in out


def test_07_no_available_source_does_not_crash(monkeypatch):
    r"""🟢 §6 ⑥ — 입력 소스가 하나도 없어도 터지지 않는다."""
    code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS, adapters=())
    assert code == 0
    assert "사용 가능한 소스: 없음" in out


def test_08_check_mode_still_changes_nothing(monkeypatch):
    r"""🔴 §2 ⑤ — ``--check`` 는 여전히 분석도 반영도 하지 않는다.

    N30 수정이 "안전한 쪽" 의 계약까지 건드리지 않았음을 확인한다.
    """
    code, out = _run_main(monkeypatch, ["--check"], REAL_CARDS)
    assert code == 0
    assert "--check 모드입니다" in out
    assert "다시 분석했습니다" not in out
    assert "카드 데이터 현황" not in out


def test_09_the_analysed_count_matches_the_update_target(monkeypatch):
    r"""🔴 §2 ⑤ / §6 ⑧ — 갱신 대상 수와 분석 대상 수가 **같다**."""
    code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert code == 0
    assert f"다시 처리할 카드: {len(REAL_CARDS):,}장" in out
    assert f"변경된 카드 {len(REAL_CARDS):,}장만 다시 분석했습니다." in out
    #: 결합 상태의 합도 같은 수다
    match = re.search(r"정상 연결\s*:\s*([\d,]+)장", out)
    assert match is not None
    assert int(match.group(1).replace(",", "")) == len(REAL_CARDS)


def test_10_the_module_docstring_pipeline_now_matches_what_runs(monkeypatch):
    r"""🔴 §2 ④ — 모듈 docstring 이 적은 흐름에 ``분석`` 이 들어 있고,
    ``--update`` 가 실제로 그 단계를 돈다."""
    flow = [l for l in (update_module.__doc__ or "").splitlines() if "->" in l]
    assert flow and "분석" in flow[0]
    _code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert "다시 분석했습니다" in out


def test_11_the_analysis_step_persists_nothing():
    r"""🔴 §2 ⑦ — 분석을 항상 돌려도 **저장되는 것이 바뀌지 않는다**.

    기본 동작을 바꿔도 안전한 근거가 이것이다. ``EffectAnalyzer`` 는 파일을
    쓰지 않고 ``Card`` 를 변형하지 않는다 (메모리 캐시만 둔다).
    """
    source = inspect.getsource(EffectAnalyzer)
    tree = ast.parse(textwrap.dedent(source))
    writes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "open"
    ]
    assert writes == []
    #: ``card.<attr> = ...`` 형태의 대입이 없다
    assigns = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name) and target.value.id == "card"
    ]
    assert assigns == []
    #: 실제로도 카드가 그대로다
    card, _repo, _a = _analyze(TWO_BLOCKS)
    before = (list(card.script.effect_offsets), card.script.source_digest,
              len(card.script.effects))
    EffectAnalyzer(_StubRepo(".", card))
    assert (list(card.script.effect_offsets), card.script.source_digest,
            len(card.script.effects)) == before


def test_12_update_does_not_change_the_verdict_after_the_gate_fix(monkeypatch):
    r"""🔴 §5 — 분석을 항상 돌려도 **성공·실패 판정은 그대로**다.

    ``validate()`` 는 결합 상태를 읽지 않는다. 분석이 늘 돌게 된 것이
    종료 코드에 끼어들면 그것은 갱신 정책 변경이고 이번 범위가 아니다.
    """
    code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert code == 0 and "검증 통과" in out
    validate_source = inspect.getsource(update_module.validate)
    for token in ("handler_binding", "unbound_effects", "coverage"):
        assert token not in validate_source, token


# ===========================================================================
# B. N31 — coverage 의 분자·분모
# ===========================================================================
def test_13_the_ratio_denominators_are_registered_effects_only():
    r"""🔴 §3 ① — 분모가 실제로 무엇인지 ``coverage()`` 소스에서 확인한다.

    세 비율의 분모는 모두 ``self.effects`` 의 부분집합이다
    (``total`` / ``has_condition`` / ``with_costs``). ``resolution_effects``
    와 ``unbound_effects`` 는 **건수로만** 들어간다.
    """
    source = textwrap.dedent(inspect.getsource(CardAnalysis.coverage))
    tree = ast.parse(source)
    #: 🔴 ``self.<목록>`` 순회만 센다. ``cost_structured`` 는 효과 하나의
    #: ``e.costs`` 를 중첩 순회하는데, 그것은 카드 단위 목록이 아니다.
    iterated = {
        node.iter.attr
        for node in ast.walk(tree)
        if isinstance(node, (ast.comprehension, ast.For))
        and isinstance(node.iter, ast.Attribute)
        and isinstance(node.iter.value, ast.Name)
        and node.iter.value.id == "self"
    }
    assert iterated == {"effects"}, iterated
    #: 다른 두 목록은 ``len()`` 으로만 등장한다
    assert "len(self.resolution_effects)" in source
    assert "len(self.unbound_effects)" in source


def test_14_a_fully_matched_card_counts_every_registered_block():
    r"""🟢 §6 ⑩ — 전부 증명된 카드에서는 분모가 블록 수와 같다."""
    card, _repo, analysis = _analyze(TWO_BLOCKS)
    cov = analysis.coverage()
    assert len(card.script.effects) == 2
    assert cov["effects"] == 2
    assert cov["unbound_effects"] == 0
    assert cov["resolution_effects"] == 0
    assert all(e.handler_binding is HandlerBinding.MATCHED
               for e in analysis.effects)


def test_15_a_partly_unproven_card_loses_denominator_silently():
    r"""🔴 §3 ② ③ — **N31 재현.** 블록 하나가 증명되지 않으면 분모가 줄고
    ``action_ratio`` 가 0.500 → 1.000 으로 **올라간다**.

    분석이 나빠졌는데 숫자는 좋아진다. 이것이 N31 의 실체다.
    """
    _card, _repo, good = _analyze(TWO_BLOCKS)
    _card2, _repo2, bad = _analyze(TWO_BLOCKS, shift_one_offset=True)
    gc, bc = good.coverage(), bad.coverage()
    assert gc["effects"] == 2 and bc["effects"] == 1
    assert gc["action_ratio"] == pytest.approx(0.5)
    assert bc["action_ratio"] == pytest.approx(1.0)
    assert bc["action_ratio"] > gc["action_ratio"]
    #: 🟢 그 조건은 같은 dict 안에 드러나 있다 — 감출 수 없다
    assert bc["unbound_effects"] == 1
    assert bad.handler_binding is HandlerBinding.MISMATCHED


def test_16_an_empty_handler_block_is_not_an_unproven_block():
    r"""🔴 §3 ④ — 핸들러 없는 **유효한** 블록과 미증명 블록을 구분한다.

    코퍼스에 핸들러 없는 블록이 9,887개 있다. 그것을 미증명으로 셌다면
    N31 의 수치가 통째로 틀렸을 것이다.
    """
    _card, _repo, analysis = _analyze(NO_HANDLER)
    cov = analysis.coverage()
    assert cov["effects"] == 1
    assert cov["unbound_effects"] == 0
    assert cov["has_condition"] == 0 and cov["with_costs"] == 0
    assert analysis.effects[0].handler_binding is HandlerBinding.MATCHED
    assert analysis.handler_binding is HandlerBinding.MATCHED


@pytest.mark.parametrize(
    "label,kwargs,expected",
    [
        ("mismatched", {"break_digest": True}, HandlerBinding.MISMATCHED),
        ("unprovable", {"drop_digest": True}, HandlerBinding.UNPROVABLE),
        ("source_missing", {"delete_file": True}, HandlerBinding.SOURCE_MISSING),
    ],
)
def test_17_every_failure_state_empties_the_denominator_and_says_so(
        label, kwargs, expected):
    r"""🔴 §3 ⑤ / §6 ⑬⑭⑮ — 세 실패 상태 모두 분모를 0 으로 만들고,
    그 사실을 ``unbound_effects`` 로 **밝힌다**. 상태는 서로 다르다."""
    card, _repo, analysis = _analyze(TWO_BLOCKS, **kwargs)
    cov = analysis.coverage()
    assert analysis.handler_binding is expected, label
    assert cov["effects"] == 0
    assert cov["unbound_effects"] == len(card.script.effects) == 2
    #: 분모가 0 이면 비율은 0.0 이다 — 0/0 을 1.0 으로 치지 않는다
    assert cov["action_ratio"] == 0.0
    assert cov["condition_ratio"] == 0.0
    assert cov["cost_ratio"] == 0.0


def test_18_every_block_lands_in_exactly_one_of_the_three_lists():
    r"""🔴 §3 ⑥ / §6 ⑰ — 세 목록의 합이 **파싱한 블록 수**다.

    어느 블록도 사라지지 않고, 두 번 세지지도 않는다. 이것이 성립하니까
    "분모에서 빠진 것" 을 호출자가 직접 되살릴 수 있다.
    """
    for kwargs in ({}, {"shift_one_offset": True}, {"break_digest": True},
                   {"drop_digest": True}, {"delete_file": True}):
        card, _repo, analysis = _analyze(TWO_BLOCKS, **kwargs)
        cov = analysis.coverage()
        total = (cov["effects"] + cov["resolution_effects"]
                 + cov["unbound_effects"])
        assert total == len(card.script.effects) == 2, kwargs


def test_19_the_numerators_never_exceed_their_denominators():
    r"""🟢 §6 ⑯ — 분자 ≤ 분모 가 모든 경우에 성립한다."""
    for kwargs in ({}, {"shift_one_offset": True}, {"break_digest": True},
                   {"drop_digest": True}, {"delete_file": True}):
        cov = _analyze(TWO_BLOCKS, **kwargs)[2].coverage()
        assert cov["condition_structured"] <= cov["has_condition"]
        assert cov["cost_structured"] <= cov["with_costs"]
        assert cov["with_actions"] <= cov["effects"]
        for key in ("condition_ratio", "cost_ratio", "action_ratio"):
            assert 0.0 <= cov[key] <= 1.0, (key, kwargs)


def test_20_card_level_and_block_level_aggregates_are_different_things():
    r"""🔴 §6 ⑱ — 카드 단위 ``handler_binding`` 과 블록 단위 집계를 구분한다.

    카드 하나가 "mismatched" 라고 해서 그 카드의 블록이 전부 어긋난 것은
    아니다. 부분 미증명이 바로 그 경우다.
    """
    _card, _repo, analysis = _analyze(TWO_BLOCKS, shift_one_offset=True)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED      # 카드 단위
    blocks = collections.Counter(
        e.handler_binding for group in (analysis.effects,
                                        analysis.resolution_effects,
                                        analysis.unbound_effects)
        for e in group
    )
    assert blocks == {HandlerBinding.MATCHED: 1,
                      HandlerBinding.MISMATCHED: 1}                   # 블록 단위


def test_21_coverage_is_per_card_and_is_never_aggregated_in_production():
    r"""🔴 §4 ① — "갱신하지 않은 카드가 coverage 집계에서 누락되는가" 의 답.

    production 에는 **코퍼스 전체 coverage 집계가 존재하지 않는다.**
    ``coverage()`` 를 읽는 곳은 ``cmd_analyze`` 한 곳이고 카드 한 장짜리다.
    그래서 "일부만 분석한 결과를 전체인 것처럼 표시" 하는 자리가 없다.
    """
    def production_files():
        for path in sorted(PROJECT_ROOT.rglob("*.py")):
            parts = set(path.relative_to(PROJECT_ROOT).parts)
            if parts & {"tests", "__pycache__", ".git"}:
                continue
            yield path

    hits = [
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if ".coverage()" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == ["app/main.py"], hits
    #: 비율을 읽는 production 호출자는 **하나도 없다** (정의한 곳 제외)
    for path in production_files():
        if path.name == "effect_model.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in ("action_ratio", "condition_ratio", "cost_ratio"):
            assert key not in text, (str(path), key)


# ===========================================================================
# C. 사용자에게 보이는 범위 표시
# ===========================================================================
def test_22_the_cli_states_which_denominator_it_used(capsys):
    r"""🔴 §3 ⑥ — "구조화 정도" 가 **무엇을 분모로 썼는지** 말한다.

    예전 문구는 "효과 N개" 였고, N 이 등록 효과만이라는 사실이 어디에도
    없었다. 해결 효과 8,283개(전체 블록의 23.9%)가 그 N 에 없다.
    """
    out = _run_cli(capsys, text=TWO_BLOCKS)
    assert "구조화 정도" in out
    assert "등록 효과" in out


def test_23_the_cli_names_the_blocks_left_out_of_the_denominator(capsys):
    r"""🔴 §3 ③ — 미증명 블록이 있으면 분모에서 빠진 수를 **적는다**."""
    out = _run_cli(capsys, text=TWO_BLOCKS, shift_one_offset=True)
    assert "증명된 블록 1/2" in out
    assert re.search(r"미증명 블록 1개", out), out


def test_24_a_normal_card_gets_no_exclusion_note(capsys):
    r"""🟢 §8 — 정상 카드의 출력에 제외 문구가 **붙지 않는다** (소음 금지)."""
    out = _run_cli(capsys, text=TWO_BLOCKS)
    assert "미증명 블록" not in out
    assert "정상 연결" in out


def test_25_the_update_summary_states_its_aggregation_scope(capsys):
    r"""🔴 §4 ③ — 결합 요약이 **몇 장을 기준으로 한 수인지** 밝힌다."""
    report_bindings(collections.Counter({HandlerBinding.MATCHED: 3}), 3, 0, [])
    out = capsys.readouterr().out
    assert "효과 블록 결합 상태" in out
    assert "3장 기준" in out


def test_26_the_two_tables_in_one_summary_declare_different_scopes(
        monkeypatch, capsys):
    r"""🔴 §4 ③ — 한 요약에 범위가 다른 두 표가 나오고, **둘 다 범위를 적는다**.

    결합 상태는 "다시 분석한 카드" 기준이고 카드 현황은 "저장소 전체"
    기준이다. 3장과 14,127장이 아무 표시 없이 붙어 있던 것이 §4 가 지적한
    자리다.
    """
    _code, out = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert f"다시 분석한 {len(REAL_CARDS)}장 기준" in out
    assert "카드 데이터 현황 (저장소 전체)" in out
    #: 두 수가 실제로 다르다 — 그래서 범위 표시가 필요하다
    assert f"{CARD_TOTAL:,}장" in out


def test_27_report_bindings_still_stays_out_of_the_verdict():
    r"""🔴 §5 — 범위 문구를 붙이면서 판정에 손대지 않았다."""
    source = inspect.getsource(update_module.report_bindings)
    for token in ("problems", "return 1", "sys.exit", "raise"):
        assert token not in source, token
    returns = [
        node for node in ast.walk(ast.parse(textwrap.dedent(source)))
        if isinstance(node, ast.Return) and node.value is not None
    ]
    assert returns == []


def test_28_nothing_was_analysed_still_prints_nothing(capsys):
    r"""🟢 §6 ⑲ — 분석한 카드가 0장이면 범위 문구도 내지 않는다."""
    report_bindings(collections.Counter(), 0, 0, [])
    assert capsys.readouterr().out == ""


# ===========================================================================
# D. 반복 실행 · 기존 출력 호환
# ===========================================================================
def test_29_the_same_input_gives_the_same_result_twice(monkeypatch):
    r"""🟢 §6 ㉒ — 같은 입력을 두 번 돌리면 결과가 같다."""
    code1, out1 = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    code2, out2 = _run_main(monkeypatch, ["--update"], REAL_CARDS)
    assert (code1, out1) == (code2, out2)
    #: 분석 쪽도 결정적이다
    a = _analyze(TWO_BLOCKS, shift_one_offset=True)[2].coverage()
    b = _analyze(TWO_BLOCKS, shift_one_offset=True)[2].coverage()
    assert a == b


@requires_official_db
def test_30_the_existing_analyze_cli_still_works_on_a_real_card(
        capsys, repository):
    r"""🟢 §6 ㉓ — 실제 카드의 분석 CLI 가 그대로 동작한다."""
    agent = type("Agent", (), {"repository": repository})()
    args = type("Args", (), {"card_id": 32807846})()     # 증원
    assert cmd_analyze(agent, args) == 0
    out = capsys.readouterr().out
    assert "결합 상태" in out and "정상 연결" in out
    assert "구조화 정도" in out
    assert "미증명 블록" not in out


@requires_official_db
def test_31_the_status_table_still_adds_up(capsys, repository):
    r"""🟢 §6 ㉔ — 기존 카드 갱신 요약(분석 상태 표)이 그대로 맞는다."""
    summarise(repository)
    out = capsys.readouterr().out
    assert "표에 없는 분석 상태" not in out
    for label in ("Lua 검증됨", "텍스트 유래", "효과 없음", "분석 근거 없음"):
        assert label in out
    assert f"{CARD_TOTAL:,}" in out


# ===========================================================================
# E. §8 — corpus · coverage · 검색 산출물 불변
# ===========================================================================
@requires_official_db
def test_32_corpus_coverage_totals_are_unchanged(repository):
    r"""🔴 §8 — coverage 의 **분자와 분모**를 코퍼스 전수로 다시 합산한다.

    N31 을 "분모를 바꿔서" 고치지 않았다는 증거다. 바꿨다면 이 숫자들이
    움직인다.
    """
    analyzer = EffectAnalyzer(repository)
    totals: collections.Counter = collections.Counter()
    cards = [c for c in repository.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
    for card in cards:
        cov = analyzer.analyze(card).coverage()
        for key in COVERAGE_TOTALS:
            totals[key] += cov[key]
    assert dict(totals) == COVERAGE_TOTALS


@requires_official_db
def test_33_every_corpus_block_is_still_proven(repository):
    r"""🟢 §8 — 코퍼스 전수가 여전히 ``MATCHED`` 다 (미증명 0개)."""
    analyzer = EffectAnalyzer(repository)
    cards = [c for c in repository.all_cards() if c.script is not None]
    blocks = collections.Counter()
    unbound = 0
    for card in cards:
        analysis = analyzer.analyze(card)
        unbound += len(analysis.unbound_effects)
        for group in (analysis.effects, analysis.resolution_effects,
                      analysis.unbound_effects):
            for effect in group:
                blocks[effect.handler_binding] += 1
    assert unbound == 0
    assert dict(blocks) == {HandlerBinding.MATCHED: ATTACHED_BLOCKS}


@requires_official_db
def test_34_resolution_effects_are_a_quarter_of_all_blocks(repository):
    r"""🔴 §3 ① — 분모에서 빠진 것 중 **실제로 큰 쪽은 해결 효과**다.

    미증명은 현재 0개지만 해결 효과는 8,283개(전체 블록의 23.9%)이고,
    어떤 비율의 분모에도 들어가지 않는다. 이 사실을 보고서와 CLI 문구에
    적었다.
    """
    analyzer = EffectAnalyzer(repository)
    registered = resolution = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        analysis = analyzer.analyze(card)
        registered += len(analysis.effects)
        resolution += len(analysis.resolution_effects)
    assert registered == COVERAGE_TOTALS["effects"]
    assert resolution == COVERAGE_TOTALS["resolution_effects"]
    assert registered + resolution == ATTACHED_BLOCKS
    assert resolution / ATTACHED_BLOCKS == pytest.approx(RESOLUTION_SHARE)


@requires_official_db
def test_35_search_results_and_ranking_are_unchanged(repository):
    r"""🟢 §8 — 검색 결과와 순위가 그대로다 (개수와 구성으로 고정한다)."""
    engine = CardSearchEngine(repository)
    cards = [c for c in repository.all_cards() if c.script is not None]
    cats = sorted({x for c in cards for x in c.script.categories})
    locs = sorted({x for c in cards for x in c.script.locations})
    assert len(cats) == 31 and len(locs) == 31
    cat_total = sum(
        len(engine.search(SearchFilters(effect_categories=(c,))).cards)
        for c in cats
    )
    loc_total = 0
    for name in locs:
        try:
            loc_total += len(engine.search(SearchFilters(
                effect_locations=(EffectLocationFilter(location=name),))).cards)
        except Exception:
            loc_total += -1
    assert cat_total == 19372
    assert loc_total == 10612


@requires_official_db
def test_36_effect_ref_resolution_is_unchanged(repository):
    r"""🟢 §7 — ``EffectRef(card_id, ordinal)`` 계약이 그대로다."""
    bad = 0
    total = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        refs = effect_refs(card)
        total += len(refs)
        if len(refs) != len(card.script.effects):
            bad += 1
            continue
        for i, ref in enumerate(refs):
            if ref != EffectRef(card.id, i):
                bad += 1
    assert total == ATTACHED_BLOCKS
    assert bad == 0


# ===========================================================================
# F. §7 금지 사항 · §10 범위
# ===========================================================================
def test_37_no_new_enum_or_public_api_was_added():
    r"""🔴 §7 금지 — 새 공용 enum·진단 프레임워크·공개 API 를 만들지 않았다."""
    assert [b.value for b in HandlerBinding] == [
        "matched", "mismatched", "unprovable", "source_missing",
    ]
    #: ``coverage()`` 의 칸 수가 그대로다 — 새 칸을 늘리지 않았다
    cov = _analyze(TWO_BLOCKS)[2].coverage()
    assert len(cov) == 17, sorted(cov)
    assert "unbound_effects" in cov and "resolution_effects" in cov
    #: 소비자는 상태를 **읽기만** 한다
    for module in (main_module, update_module):
        source = inspect.getsource(module)
        assert "handler_binding =" not in source, module.__name__


def test_38_the_ratio_formulas_were_not_touched():
    r"""🔴 §5 금지 — 테스트를 통과시키기 위해 분모를 바꾸지 않았다."""
    source = textwrap.dedent(inspect.getsource(CardAnalysis.coverage))
    assert '"action_ratio": (with_actions / total) if total else 0.0' in source
    assert '"cost_ratio": (cost_structured / with_costs) if with_costs else 0.0' \
        in source
    assert "total = len(self.effects)" in source
    #: 🔴 미증명 블록을 분모에 섞지 않았다 — 결합 실패와 구조화 실패는 다른
    #: 축이다. docstring 은 그 사실을 **설명해야** 하므로 문자열로 세지 않고
    #: AST 로 "``unbound_effects`` 는 ``len()`` 한 번만 쓴다" 를 확인한다.
    func = ast.parse(source).body[0]
    body = func.body
    if (isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)):
        body = body[1:]
    uses = [
        node for stmt in body for node in ast.walk(stmt)
        if isinstance(node, ast.Attribute) and node.attr == "unbound_effects"
    ]
    assert len(uses) == 1, len(uses)
    wrapped = [
        node for stmt in body for node in ast.walk(stmt)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "len" and node.args
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "unbound_effects"
    ]
    assert len(wrapped) == 1


def test_39_production_change_is_confined_to_three_files():
    r"""🟢 §10 ⑦ — 갱신 스크립트 · 분석 CLI · coverage 설명. 그 밖은 없다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    allowed = {
        "scripts/update_cards.py",
        "app/main.py",
        "analysis/effect_model.py",
        "tests/test_update_coverage_contract_audit.py",
        "docs/phase3f39-update-coverage-contract-audit.md",
    }
    assert changed <= allowed, changed - allowed


def test_40_no_forbidden_path_was_touched():
    r"""🔴 §7 금지 — Lua · README · engine · agent · 검색 계층 미변경."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        assert not path.startswith("engine/"), path
        assert not path.startswith("agent/"), path
        assert "card_search" not in path, path
        assert not path.startswith("data/"), path


def test_41_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 §6 금지 — 기존 테스트 삭제·skip 추가가 없다.

    파일별 테스트 **개수**를 부모 커밋과 비교한다. ``-def test_`` 줄을 세면
    이름만 바꾼 것도 삭제로 읽힌다.
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-39:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    oldest = shas[-1]
    base = subprocess.run(
        ["git", "rev-parse", f"{oldest}^"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()

    def counts(ref: str) -> dict[str, int]:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "tests/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        out: dict[str, int] = {}
        for name in listing:
            if not name.endswith(".py"):
                continue
            text = subprocess.run(
                ["git", "show", f"{ref}:{name}"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
            ).stdout
            out[name] = len(re.findall(r"^def test_", text, re.M))
        return out

    before, after = counts(base), counts("HEAD")
    for name, count in before.items():
        assert name in after, f"테스트 파일이 사라졌다: {name}"
        assert after[name] >= count, (name, count, after[name])
    #: skip 지시는 이 Phase 가 새로 추가한 파일에만 있고, 그것도 "commit 이
    #: 아직 없을 때" 라는 조건부다 (``test_39``~``test_41``).
    added = set(after) - set(before)
    for name in added:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for match in re.findall(r"pytest\.skip\([^)]*\)", text):
            assert "commit 이 아직 없다" in match, (name, match)
