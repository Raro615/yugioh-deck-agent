r"""
Phase 3-F-37 — 파싱 시점 블록 식별자 보존 및 결합 실패의 UNKNOWN 처리
======================================================================

무엇을 바꿨나
-------------
Phase 3-F-36 은 ``IDENTITY_REQUIRES_DATA_MODEL_CHANGE`` 로 끝났다. 식별자
(블록을 만든 매치의 바이트 offset)는 두 경로에 **실재했지만 둘 다 버렸고**,
결합 자리에서 다시 계산하는 것은 순환이라 아무것도 잡지 못했다.

이 Phase 가 보존한 식별자는 **한 쌍**이다.

    (LuaScriptInfo.source_digest, LuaScriptInfo.effect_offsets[i])
     └ 어느 소스 버전인가            └ 그 안의 어느 자리인가

🔴 **offset 만으로는 부족하다.** offset 이 같다는 것은 두 파싱이 같은 바이트
자리를 봤다는 뜻이지 **같은 텍스트**를 봤다는 뜻이 아니다. 길이가 변하지 않는
제자리 수정(``s.con`` → ``s.XXX``)은 앞의 offset 을 밀지 않으므로 offset 만
비교하면 **우연히 일치**하고, analyzer 는 바뀐 텍스트의 핸들러를 붙이면서
"증명됐다" 고 말한다 — 그것이 §4 가 금지한 "서로 다른 block 을 같은 식별자로
잘못 합치는" 경우다 (``test_31``).

결합 실패를 어떻게 적는가
-------------------------
:class:`~analysis.effect_model.HandlerBinding` 네 값으로 구분한다.

====================  ====================================================
``MATCHED``           🟢 같은 소스에서, 같은 자리의 핸들러 항목을 찾았다.
                      핸들러가 비어 있어도 이 값이다 — "핸들러 없는 유효
                      블록" 은 정상이고 코퍼스에 9,887개 있다.
``MISMATCHED``        🔴 **틀렸다** — 두 목록이 서로 다른 텍스트에서 나왔다.
``UNPROVABLE``        🟠 **모른다** — 증명할 정보 자체가 없다 (낡은 캐시 등).
``SOURCE_MISSING``    🔴 분석 시점에 ``c*.lua`` 를 읽지 못했다.
====================  ====================================================

``MATCHED`` 가 아닌 블록은 ``effects`` 에도 ``resolution_effects`` 에도 넣지
않고 :attr:`~analysis.effect_model.CardAnalysis.unbound_effects` 에 모은다.
두 목록을 가르는 기준인 ``is_registered`` 가 **핸들러 항목의 함수 이름**에서
오기 때문이다 — 대응이 증명되지 않았으면 그 이름도 믿을 수 없고, 둘 중
하나를 고르는 순간 거짓을 지어낸다.

바뀌지 않은 것
--------------
🟢 정상 코퍼스 산출물 14개 항목 **전부 그대로**다. 34,635 블록이 모두
``MATCHED`` 이고 ``unbound_effects`` 는 언제나 비어 있다. 바뀐 것은 산출물이
아니라 **어긋났을 때의 행동**이다.

🔴 ``EffectSpec`` 9칸 · ``EffectRef(card_id, ordinal)`` 2칸 · append-only
ordinal 규칙은 건드리지 않았다 (§7 금지).
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import analysis.effect_analyzer as analyzer_module
import sources.lua_loader as loader_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import CardAnalysis, HandlerBinding
from core.card_model import Card, EffectSpec, LuaScriptInfo
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from engine.ids import EffectRef, effect_refs
from sources.lua_loader import (
    LuaScriptSource,
    _info_from_dict,
    _info_to_dict,
    parse_lua_source,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-36 이 보고한 기준값 (테스트가 실제로 다시 산출한다) ---------
SCRIPT_COUNT = 12702
BLOCK_TOTAL = 34684
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
ANALYSIS_TOTALS = {
    "registered": 26352, "resolution": 8283, "cond": 12438,
    "cost": 5007, "target": 5516, "action": 18280, "cat": 20484,
}
SEARCH_CATEGORIES = 31
SEARCH_LOCATIONS = 31
#: 🔴 Phase 3-F-37 이 올렸다 (``effect_offsets`` · ``source_digest`` 추가).
CACHE_PREFIX = "v10:"

#: Phase 3-F-32~36 의 대표 회귀 사례 — (블록 수, Clone 된 ordinal, code, 부모)
PHASE32_CARDS = {
    44887817: (5, 4, "EFFECT_CANNOT_MSET", "e1"),
    4997565: (5, 3, "EFFECT_DISABLE_EFFECT", "e1"),
    56410769: (3, 2, "EFFECT_CANNOT_ATTACK_ANNOUNCE", "e2"),
}
GROUP_CLONE_CARD = 63708033
LABEL_OBJECT_CARD = 52445243
C4997565_OFFSETS = [199, 542, 2703, 2911, 3516]


# ===========================================================================
# 공용 도구 — 실제 production 경로만 쓴다
# ===========================================================================
class _StubRepo:
    constants = None


def _analyze(parsed_text: str, disk_text: str, *, card_id: int = 1,
             drop_offsets: bool = False, drop_digest: bool = False,
             delete_file: bool = False):
    r"""``card.script`` 과 디스크 텍스트를 **따로** 두고 분석한다.

    인공적인 상황이 아니다 — 캐시가 낡거나 ``script_dir`` 이 어긋나면 정확히
    이 상태가 된다 (Phase 3-F-35 가 출하된 CLI 로 재현했다).
    """
    parsed_text = textwrap.dedent(parsed_text)
    disk_text = textwrap.dedent(disk_text)
    with tempfile.TemporaryDirectory() as directory:
        name = f"c{card_id}.lua"
        path = pathlib.Path(directory, name)
        path.write_text(disk_text, encoding="utf-8")
        card = Card(id=card_id, name=name)
        card.script = parse_lua_source(card_id, name, parsed_text)
        if drop_offsets:
            card.script.effect_offsets = []
        if drop_digest:
            card.script.source_digest = None
        if delete_file:
            path.unlink()
        analyzer = EffectAnalyzer(_StubRepo(), script_dir=directory)
        return card, analyzer.analyze(card)


def _bindings(analysis: CardAnalysis) -> list[tuple[str, str]]:
    out = []
    for group in (analysis.effects, analysis.resolution_effects,
                  analysis.unbound_effects):
        for effect in group:
            out.append((effect.index, effect.handler_binding.value))
    return out


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-37:"],
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


# --- §5 가 요구한 Lua 사례 -------------------------------------------------
TWO_COND_COST = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
"""
ONE_COND = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: 길이는 같고 **원문 순서만** 뒤바뀐 것
TWO_SWAPPED = """
    function s.initial_effect(c)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: 🔴 Phase 3-F-36 §4.5 — 길이도 2, **이름 순서도 ['e1','e2']** 인데 의미가
#: 뒤바뀐 것. 앞에 주석 두 줄이 늘어 offset 이 밀렸다.
SAME_ORDER_DIFFERENT_SEMANTICS = """
    --이 카드의 효과를 다시 쓴 버전
    --줄이 늘어 offset 이 밀린다
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCost(s.cost)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCondition(s.con)
        c:RegisterEffect(e2)
    end
"""
#: 🔴 **길이가 한 글자도 바뀌지 않는 제자리 수정** — offset 이 그대로다.
IN_PLACE_EDIT = TWO_COND_COST.replace("e1:SetCondition(s.con)",
                                      "e1:SetCondition(s.XYZ)")
NO_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        e1:SetValue(500)
        c:RegisterEffect(e1)
    end
"""
UNRECOGNISED_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        e1=e:GetLabelObject()
        e1:SetCost(s.lost)
    end
"""
SHARED_HANDLER_NAME = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.shared)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCondition(s.shared)
        c:RegisterEffect(e2)
    end
"""
CLONE_THEN_REBIND = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
        e2=e:GetLabelObject()
        e2:SetTarget(s.lost)
    end
"""
HELPER_CREATES = """
    function s.initial_effect(c)
        local e0=Fusion.CreateSummonEff(c,s.ffilter)
        e0:SetOperation(s.fop)
        c:RegisterEffect(e0)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
APPENDED = TWO_COND_COST.rstrip() + """
    function s.extra(c)
        local e9=Effect.CreateEffect(c)
        e9:SetCost(s.cost)
        c:RegisterEffect(e9)
    end
"""


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


# ===========================================================================
# A. 파싱 시점 식별자가 실제로 보존되는가
# ===========================================================================
def test_01_the_parse_result_now_carries_both_halves_of_the_identifier():
    r"""🟢 ``LuaScriptInfo`` 가 소스 지문과 블록 offset 을 **둘 다** 들고 있다."""
    names = [f.name for f in dataclasses.fields(LuaScriptInfo)]
    assert "source_digest" in names
    assert "effect_offsets" in names
    assert len(names) == 16          # 14 (3-F-36) + 2
    #: 🔴 ``effects`` 바로 뒤에 둔다 — 평행 목록이라는 것이 읽히도록
    assert names.index("effect_offsets") == names.index("effects") + 1


def test_02_effect_spec_api_is_untouched():
    r"""🟢 §7 금지 — ``EffectSpec`` 공개 API 는 9칸 그대로다."""
    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]


def test_03_effect_ref_api_and_ordinal_rule_are_untouched():
    r"""🟢 §7 금지 — ``EffectRef(card_id, ordinal)`` 그대로다."""
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    info = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    card = Card(id=1, name="c1.lua")
    card.script = info
    assert [r.ordinal for r in effect_refs(card)] == [0, 1]


def test_04_offsets_are_parallel_to_the_block_list():
    r"""🟢 길이와 순서가 ``effects`` 와 같다 — 그것이 이 목록의 계약이다."""
    info = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    assert len(info.effect_offsets) == len(info.effects) == 2
    assert info.effect_offsets == sorted(info.effect_offsets)
    assert len(set(info.effect_offsets)) == 2


def test_05_the_same_source_parses_to_the_same_identifier_every_time():
    r"""🟢 §4 조건 — **반복 분석 시 같은 식별 정보**를 얻는다."""
    text = textwrap.dedent(TWO_COND_COST)
    first = parse_lua_source(1, "c1.lua", text)
    second = parse_lua_source(1, "c1.lua", text)
    assert first.source_digest == second.source_digest
    assert first.effect_offsets == second.effect_offsets
    #: 카드 ID 나 파일 이름이 달라도 **소스가 같으면** 지문이 같다 —
    #: 지문은 소스의 성질이지 파일 경로의 성질이 아니다
    third = parse_lua_source(999, "c999.lua", text)
    assert third.source_digest == first.source_digest


def test_06_the_digest_is_of_the_raw_source_not_the_comment_stripped_body():
    r"""🟢 로더와 analyzer 가 **같은 것**을 해시한다 — 원문 그대로."""
    text = textwrap.dedent(SAME_ORDER_DIFFERENT_SEMANTICS)
    info = parse_lua_source(1, "c1.lua", text)
    assert info.source_digest == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_07_a_different_source_gets_a_different_digest():
    r"""🟢 길이가 같은 제자리 수정도 지문은 달라진다."""
    a = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    b = parse_lua_source(1, "c1.lua", textwrap.dedent(IN_PLACE_EDIT))
    assert len(textwrap.dedent(TWO_COND_COST)) == len(textwrap.dedent(IN_PLACE_EDIT))
    assert a.effect_offsets == b.effect_offsets       # 🔴 offset 은 같다
    assert a.source_digest != b.source_digest         # 🟢 지문이 가른다


def test_08_offsets_survive_the_cache_round_trip():
    r"""🟢 캐시에서 복원한 블록도 자기 자리와 출처를 안다."""
    info = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    back = _info_from_dict(json.loads(json.dumps(_info_to_dict(info))))
    assert back.effect_offsets == info.effect_offsets
    assert back.source_digest == info.source_digest
    assert [s.index for s in back.effects] == [s.index for s in info.effects]


def test_09_an_old_cache_restores_to_unknown_not_to_zero():
    r"""🔴 **"모른다" 를 "offset 0" 으로 바꾸지 않는다.**

    ``v10`` 이전 캐시에는 두 칸이 없다. 0 이나 빈 문자열로 채우면 모든
    블록이 같은 식별자를 갖게 되어 위치 기반 결합보다 **더 나쁘게**
    합쳐진다.
    """
    payload = _info_to_dict(parse_lua_source(1, "c1.lua",
                                             textwrap.dedent(TWO_COND_COST)))
    del payload["effect_offsets"]
    del payload["source_digest"]
    old = _info_from_dict(payload)
    assert old.effect_offsets == []
    assert old.source_digest is None
    assert len(old.effects) == 2          # 블록 자체는 그대로 복원된다


def test_10_the_cache_signature_was_bumped():
    r"""🟢 자료구조가 바뀌었으므로 캐시를 무효화한다 — ``v9:`` → ``v10:``."""
    source = inspect.getsource(loader_module)
    assert CACHE_PREFIX in source
    assert 'f"v9:' not in source


def test_11_a_real_cache_round_trip_preserves_every_script(tmp_path):
    r"""🟢 실제 ``load_cached`` 왕복 — 디렉터리 하나로 끝까지 돌려 본다."""
    directory = tmp_path / "scripts"
    directory.mkdir()
    (directory / "c1.lua").write_text(textwrap.dedent(TWO_COND_COST),
                                      encoding="utf-8")
    (directory / "c2.lua").write_text(textwrap.dedent(ONE_COND), encoding="utf-8")
    source = LuaScriptSource(directory)
    cache = tmp_path / "cache.json"
    fresh = source.load_cached(cache)
    assert cache.is_file()
    cached = source.load_cached(cache)        # 이번에는 캐시에서 읽는다
    assert json.loads(cache.read_text(encoding="utf-8"))["signature"].startswith(
        CACHE_PREFIX)
    for card_id in (1, 2):
        assert cached[card_id].effect_offsets == fresh[card_id].effect_offsets
        assert cached[card_id].source_digest == fresh[card_id].source_digest


def test_12_analysis_is_identical_with_and_without_the_cache(tmp_path):
    r"""🟢 §5 ⑪ — 캐시가 있을 때와 없을 때의 **분석 결과가 같다**."""
    directory = tmp_path / "scripts"
    directory.mkdir()
    (directory / "c1.lua").write_text(textwrap.dedent(TWO_COND_COST),
                                      encoding="utf-8")
    source = LuaScriptSource(directory)
    cache = tmp_path / "cache.json"
    source.load_cached(cache)                 # 캐시를 만든다
    from_cache = source.load_cached(cache)[1]
    from_disk = source.load()[1]

    results = []
    for info in (from_disk, from_cache):
        card = Card(id=1, name="c1.lua")
        card.script = info
        analysis = EffectAnalyzer(_StubRepo(), script_dir=directory).analyze(card)
        results.append((
            analysis.handler_binding.value,
            _bindings(analysis),
            [(e.index, e.has_condition, bool(e.costs)) for e in analysis.effects],
            len(analysis.unbound_effects),
        ))
    assert results[0] == results[1]
    assert results[0][0] == HandlerBinding.MATCHED.value
    assert results[0][3] == 0


# ===========================================================================
# B. 결합 상태를 실제로 구분하는가 (§6)
# ===========================================================================
def test_13_the_normal_case_is_matched_and_joins_correctly():
    r"""🟢 §5 ① 정상 — ``e1`` 이 조건을, ``e2`` 가 비용을 받는다."""
    _card, analysis = _analyze(TWO_COND_COST, TWO_COND_COST)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.unbound_effects == []
    assert [(e.index, e.has_condition, bool(e.costs)) for e in analysis.effects] == [
        ("e1", True, False), ("e2", False, True),
    ]
    assert all(e.handler_binding is HandlerBinding.MATCHED for e in analysis.effects)


def test_14_a_length_mismatch_is_not_silently_joined():
    r"""🔴 §5 ② 길이가 다르면 **조용히 붙지 않는다**.

    3-F-36 까지는 ``e2`` 가 빈 dict 를 받아 ``is_registered=False`` 로
    **해결 중 생성 효과로 오분류**됐다. 이제는 어느 목록에도 들어가지 않는다.
    """
    _card, analysis = _analyze(TWO_COND_COST, ONE_COND)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert len(analysis.unbound_effects) == 2
    assert analysis.effects == []
    assert analysis.resolution_effects == []
    assert {e.handler_binding for e in analysis.unbound_effects} == {
        HandlerBinding.MISMATCHED}


def test_15_an_order_difference_is_detected():
    r"""🔴 §5 ③ 길이는 같고 순서만 달라도 잡는다."""
    _card, analysis = _analyze(TWO_COND_COST, TWO_SWAPPED)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert analysis.effects == [] and analysis.resolution_effects == []
    assert len(analysis.unbound_effects) == 2


def test_16_the_phase_3f36_inversion_no_longer_happens():
    r"""🔴 **3-F-36 의 결정적 사례가 더는 조용히 뒤집히지 않는다.**

    길이 2=2, 이름 순서 ``['e1','e2']`` 까지 같은데 조건/비용이 뒤바뀌던
    입력이다. 그때는 ``e1`` 이 ``cond=False/cost=True`` 로 **뒤집힌 값을
    주장**했다. 이제는 아무 값도 주장하지 않는다.
    """
    card, analysis = _analyze(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    assert [s.index for s in card.script.effects] == ["e1", "e2"]
    assert len(card.script.effects) == 2
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert analysis.effects == []
    #: 🔴 뒤집힌 주장이 **없다**
    assert all(not e.has_condition and not e.costs
               for e in analysis.unbound_effects)


def test_17_source_missing_is_its_own_state():
    r"""🔴 §6 ④ 입력 소스가 없다 — 블록이 0개인 카드와 **구별된다**."""
    _card, analysis = _analyze(TWO_COND_COST, TWO_COND_COST, delete_file=True)
    assert analysis.handler_binding is HandlerBinding.SOURCE_MISSING
    assert analysis.has_script is True
    assert analysis.effects == [] and analysis.resolution_effects == []
    #: 🟢 블록을 **버리지 않는다** — 명세는 파싱 시점에 이미 읽었다
    assert [e.index for e in analysis.unbound_effects] == ["e1", "e2"]
    assert {e.handler_binding for e in analysis.unbound_effects} == {
        HandlerBinding.SOURCE_MISSING}


def test_18_a_card_with_no_blocks_is_not_source_missing():
    r"""🟢 "블록이 없다" 와 "소스를 못 읽었다" 가 서로 다른 결과를 낸다."""
    _card, empty = _analyze("function s.initial_effect(c)\nend\n",
                            "function s.initial_effect(c)\nend\n")
    assert empty.handler_binding is HandlerBinding.MATCHED
    assert empty.unbound_effects == []
    _card2, missing = _analyze(TWO_COND_COST, TWO_COND_COST, delete_file=True)
    assert missing.handler_binding is HandlerBinding.SOURCE_MISSING
    assert empty.handler_binding is not missing.handler_binding


def test_19_a_missing_digest_is_unprovable_not_mismatched():
    r"""🟠 §6 ③ 증명할 정보가 없다 — **"모른다" 와 "틀렸다" 를 구분한다**.

    낡은 캐시에서 복원한 상태를 그대로 만든다. 소스는 멀쩡하고 내용도
    같은데, 그것이 같다는 것을 **증명할 수단이 없다**.
    """
    _card, analysis = _analyze(TWO_COND_COST, TWO_COND_COST, drop_digest=True)
    assert analysis.handler_binding is HandlerBinding.UNPROVABLE
    assert len(analysis.unbound_effects) == 2
    assert analysis.effects == []


def test_20_missing_offsets_are_unprovable_too():
    r"""🟠 평행 목록의 길이가 맞지 않으면 쓰지 않는다."""
    _card, analysis = _analyze(TWO_COND_COST, TWO_COND_COST, drop_offsets=True)
    assert analysis.handler_binding is HandlerBinding.UNPROVABLE
    assert {e.handler_binding for e in analysis.unbound_effects} == {
        HandlerBinding.UNPROVABLE}


def test_21_unprovable_and_mismatched_are_different_values():
    r"""🔴 두 상태를 하나로 뭉개지 않는다 — 대응이 다르다.

    ``UNPROVABLE`` 은 "캐시를 다시 만들면 풀린다", ``MISMATCHED`` 는
    "두 소스가 실제로 다르다" 다. 같은 값으로 적으면 어느 쪽인지 알 수 없다.
    """
    _c1, unprovable = _analyze(TWO_COND_COST, TWO_COND_COST, drop_digest=True)
    _c2, mismatched = _analyze(TWO_COND_COST, TWO_SWAPPED)
    assert unprovable.handler_binding is HandlerBinding.UNPROVABLE
    assert mismatched.handler_binding is HandlerBinding.MISMATCHED
    assert unprovable.handler_binding is not mismatched.handler_binding
    assert len({v.value for v in HandlerBinding}) == 4


def test_22_an_unbound_block_never_enters_the_two_normal_lists():
    r"""🔴 §6 — 증명되지 않은 블록으로 ``is_registered`` 를 **지어내지 않는다**."""
    for parsed, disk, kwargs in (
        (TWO_COND_COST, TWO_SWAPPED, {}),
        (TWO_COND_COST, TWO_COND_COST, {"drop_digest": True}),
        (TWO_COND_COST, TWO_COND_COST, {"delete_file": True}),
    ):
        _card, analysis = _analyze(parsed, disk, **kwargs)
        assert analysis.effects == []
        assert analysis.resolution_effects == []
        assert len(analysis.unbound_effects) == 2
        for effect in analysis.unbound_effects:
            assert effect.handler_binding is not HandlerBinding.MATCHED


def test_23_a_mismatched_block_never_receives_another_blocks_handlers():
    r"""🔴 §6 — 짝이 없으면 **남의 핸들러를 대신 붙이지 않는다**.

    3-F-36 이 재현한 피해가 정확히 이것이었다 — ``e1`` 이 다른 블록의
    ``Operation``/``Target`` 을 받아 ``actions=1`` 을 주장했다.
    """
    _card, analysis = _analyze(TWO_COND_COST, TWO_SWAPPED)
    for effect in analysis.unbound_effects:
        assert effect.actions == []
        assert effect.costs == []
        assert effect.has_condition is False
        assert effect.condition_raw is None


def test_24_the_card_summary_takes_the_most_severe_block():
    r"""🟢 카드 요약은 **가장 심각한** 블록을 따른다."""
    #: 길이 2 vs 1 — 앞 블록은 같은 자리·같은 소스가 아니므로 둘 다 어긋난다
    _card, analysis = _analyze(TWO_COND_COST, ONE_COND)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    severity = analyzer_module._BINDING_SEVERITY
    assert severity[HandlerBinding.MATCHED] == 0
    assert (severity[HandlerBinding.SOURCE_MISSING]
            > severity[HandlerBinding.MISMATCHED]
            > severity[HandlerBinding.UNPROVABLE]
            > severity[HandlerBinding.MATCHED])


# ===========================================================================
# C. §5 의 나머지 사례
# ===========================================================================
def test_25_a_valid_block_with_no_handler_is_matched():
    r"""🟢 §5 ⑤ — **핸들러가 없는 유효한 블록은 정상이다**.

    §6 이 물은 것이 이것이다. 네 핸들러 슬롯이 비는 것이 정답이고,
    증명된 것은 핸들러의 존재가 아니라 **대응 관계**다.
    """
    _card, analysis = _analyze(NO_HANDLER, NO_HANDLER)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.unbound_effects == []
    assert len(analysis.effects) == 1
    effect = analysis.effects[0]
    assert effect.handler_binding is HandlerBinding.MATCHED
    assert effect.has_condition is False and effect.costs == []


def test_26_an_unrecognised_handler_is_dropped_by_both_sides():
    r"""🟢 §5 ⑥ — parser 가 모르는 대입 뒤의 설정자는 **양쪽이 똑같이 버린다**."""
    _card, analysis = _analyze(UNRECOGNISED_HANDLER, UNRECOGNISED_HANDLER)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert len(analysis.effects) == 1
    assert analysis.effects[0].has_condition is True
    assert analysis.effects[0].costs == []       # SetCost(s.lost) 는 버려졌다


def test_27_the_same_handler_name_on_two_blocks_stays_separate():
    r"""🟢 §5 ④ — 핸들러 이름이 같아도 offset 이 두 블록을 구별한다."""
    card, analysis = _analyze(SHARED_HANDLER_NAME, SHARED_HANDLER_NAME)
    assert len(set(card.script.effect_offsets)) == 2
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert [e.condition_raw for e in analysis.effects] == ["s.shared", "s.shared"]


def test_28_clone_then_rebind_keeps_block_identity():
    r"""🟢 §5 ⑦ — Clone 뒤 재바인딩.

    근거: ``e2=e1:Clone()`` 이 블록을 하나 더 만들고, 그 뒤
    ``e2=e:GetLabelObject()`` 은 **블록을 만들지 않는다**. 따라서 블록도
    offset 도 2개이고, 재바인딩 이후의 ``SetTarget`` 은 버려진다.
    """
    card, analysis = _analyze(CLONE_THEN_REBIND, CLONE_THEN_REBIND)
    assert [s.index for s in card.script.effects] == ["e1", "e2"]
    assert [s.cloned_from for s in card.script.effects] == [None, "e1"]
    assert len(card.script.effect_offsets) == 2
    assert card.script.effect_offsets[0] != card.script.effect_offsets[1]
    assert analysis.handler_binding is HandlerBinding.MATCHED
    #: Clone 자식은 부모의 조건을 물려받고 자기 비용을 더한다. 재바인딩
    #: 이후의 ``SetTarget`` 은 어느 블록에도 붙지 않는다.
    assert [(e.index, e.has_condition, bool(e.costs), e.selection is None)
            for e in analysis.effects] == [
        ("e1", True, False, True), ("e2", True, True, True)]


def test_29_a_helper_function_creates_no_block_and_no_offset():
    r"""🟢 §5 ⑧ — 보조 함수가 만든 Effect 는 **양쪽이 똑같이 세지 않는다**."""
    card, analysis = _analyze(HELPER_CREATES, HELPER_CREATES)
    assert [s.index for s in card.script.effects] == ["e1"]
    assert len(card.script.effect_offsets) == 1
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.unbound_effects == []


def test_30_the_same_card_id_in_two_script_dirs_is_judged_by_content():
    r"""🔴 §5 ⑨ — 같은 카드 ID, 다른 디렉터리.

    판정 기준은 **디렉터리가 아니라 내용**이다. 같은 내용이면 다른
    디렉터리에서도 ``MATCHED`` 이고, 내용이 다르면 같은 ID 라도
    ``MISMATCHED`` 다.
    """
    _same_card, same = _analyze(TWO_COND_COST, TWO_COND_COST, card_id=55144522)
    assert same.handler_binding is HandlerBinding.MATCHED
    _other_card, other = _analyze(TWO_COND_COST, ONE_COND, card_id=55144522)
    assert other.handler_binding is HandlerBinding.MISMATCHED


def test_31_an_in_place_edit_is_caught_although_the_offsets_agree():
    r"""🔴 §5 ⑩ 의 가장 어려운 모양 — **offset 만으로는 못 잡는 수정**.

    길이가 한 글자도 바뀌지 않아 블록 offset 이 **완전히 같다**. offset 만
    비교했다면 "증명됐다" 고 말하며 바뀐 텍스트의 핸들러를 붙였을 것이다.
    소스 지문이 그것을 가른다 — 이것이 식별자가 **한 쌍**인 이유다.
    """
    parsed = textwrap.dedent(TWO_COND_COST)
    disk = textwrap.dedent(IN_PLACE_EDIT)
    assert len(parsed) == len(disk) and parsed != disk
    assert (parse_lua_source(1, "c1.lua", parsed).effect_offsets
            == parse_lua_source(1, "c1.lua", disk).effect_offsets)
    _card, analysis = _analyze(TWO_COND_COST, IN_PLACE_EDIT)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert analysis.effects == []


def test_32_appending_a_later_block_does_not_move_earlier_offsets():
    r"""🟢 §5 ⑩ — 뒤에 블록이 붙어도 앞 블록의 offset 은 그대로다.

    ``ordinal`` 과 다른 점이다. 다만 **소스가 달라졌으므로** 결합은
    여전히 ``MISMATCHED`` 다 — offset 이 같다고 같은 텍스트인 것은 아니다.
    """
    base = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    more = parse_lua_source(1, "c1.lua", textwrap.dedent(APPENDED))
    assert more.effect_offsets[:2] == base.effect_offsets
    assert len(more.effect_offsets) == 3
    _card, analysis = _analyze(TWO_COND_COST, APPENDED)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED


def test_33_the_identifier_is_not_claimed_to_be_a_cross_version_id():
    r"""🔴 **정직하게 적는다** — 앞에 글자가 들어가면 offset 이 전부 밀린다.

    이 값은 '한 소스 버전 안의 자리' 이고 '버전 간 영구 ID' 가 아니다.
    문서도 그렇게 적혀 있어야 한다.
    """
    base = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    shifted = parse_lua_source(
        1, "c1.lua", "--주석 한 줄\n" + textwrap.dedent(TWO_COND_COST))
    assert base.effect_offsets != shifted.effect_offsets
    #: 이름과 길이는 그대로다 — 그래서 이름·길이 검사는 이 차이를 못 본다
    assert [s.index for s in base.effects] == [s.index for s in shifted.effects]
    #: 🔴 그리고 그 한계가 **모델에 적혀 있다**. 적어 두지 않으면 다음
    #: 사람이 이 값을 버전 간 ID 로 쓴다.
    import core.card_model as card_model_module

    model_source = inspect.getsource(card_model_module)
    assert "영구 ID 가 아니다" in model_source


# ===========================================================================
# D. 금지된 결합 근거를 실제로 쓰지 않는가 (§6)
# ===========================================================================
def test_34_length_equality_alone_does_not_pass():
    r"""🔴 §6 금지 — "길이가 같다" 는 이유만으로 통과시키지 않는다."""
    card, analysis = _analyze(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    disk = textwrap.dedent(SAME_ORDER_DIFFERENT_SEMANTICS)
    entries = EffectAnalyzer._collect_handlers(
        disk, EffectAnalyzer._function_spans(disk))
    #: 🔴 두 목록의 길이가 **실제로 같다** — 그런데도 통과하지 않는다
    assert len(card.script.effects) == len(entries) == 2
    assert analysis.handler_binding is HandlerBinding.MISMATCHED


def test_35_name_equality_alone_does_not_pass():
    r"""🔴 §6 금지 — "이름이 같다" 는 이유만으로 통과시키지 않는다."""
    card, analysis = _analyze(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    assert [s.index for s in card.script.effects] == ["e1", "e2"]
    assert analysis.handler_binding is HandlerBinding.MISMATCHED


def test_36_the_join_no_longer_indexes_by_position():
    r"""🔴 결합 자리에서 **위치 색인이 사라졌다** (AST 로 확인).

    3-F-36 의 ``entries[position] if position < len(entries) else {}`` 가
    그 Phase 의 핵심 증거였다. 이제 ``entries`` 를 숫자로 색인하는 구문이
    하나도 없다.
    """
    func = next(
        node for node in ast.walk(ast.parse(textwrap.dedent(
            inspect.getsource(EffectAnalyzer._analyze_card))))
        if isinstance(node, ast.FunctionDef) and node.name == "_analyze_card"
    )
    subscripts = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name) and node.value.id == "entries"
    ]
    assert subscripts == []
    text = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    assert "entries[position]" not in text
    assert "source_digest" in text
    assert "effect_offsets" in text


def test_37_the_loader_now_reads_the_offset_it_used_to_discard():
    r"""🔴 로더의 재생 루프가 ``pos`` 를 **읽는다** — 3-F-36 은 ``_pos`` 였다."""
    func = next(
        node for node in ast.walk(ast.parse(inspect.getsource(loader_module)))
        if isinstance(node, ast.FunctionDef) and node.name == "parse_lua_source"
    )
    loops = [
        node for node in ast.walk(func)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
        and len(node.target.elts) == 3
    ]
    assert len(loops) == 1
    names = {e.id for e in loops[0].target.elts if isinstance(e, ast.Name)}
    assert names == {"pos", "kind", "payload"}
    loaded = {
        node.id for node in ast.walk(loops[0])
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert "pos" in loaded


def test_38_handler_entries_carry_their_own_offset():
    r"""🟢 핸들러 항목도 자기 자리를 들고 있다 — 그래야 맞춰 볼 수 있다."""
    text = textwrap.dedent(TWO_COND_COST)
    entries = EffectAnalyzer._collect_handlers(
        text, EffectAnalyzer._function_spans(text))
    assert [sorted(e) for e in entries] == [["function", "handlers", "offset"]] * 2
    assert [e["offset"] for e in entries] == parse_lua_source(
        1, "c1.lua", text).effect_offsets


def test_39_no_interpreter_or_graph_engine_was_added():
    r"""🔴 §7 금지 — Lua 인터프리터·graph engine·dataflow framework 없음.

    🔴 문자열 검색으로 판정하지 않는다. 로더 주석에는 "Lua dataflow 를
    **구현하지 않는다**" 가 실제로 있고, 그것을 금지 증거로 읽으면 정반대
    결론이 난다 (Phase 3-F-36 이 겪었다). import 와 정의된 이름을 본다.
    """
    banned = {"lupa", "networkx", "lua", "antlr4", "lark", "luaparser",
              "pydot", "igraph", "graphviz"}
    for module in (loader_module, analyzer_module):
        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (imported & banned)
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        assert not {n for n in defined
                    if re.search(r"Interpreter|GraphEngine|DataFlow|CFG", n)}


# ===========================================================================
# E. 산출물 불변성 (§8) — 14개 항목을 다시 산출한다
# ===========================================================================
def test_40_corpus_wide_every_block_is_matched(repo):
    r"""🟢 **정상 코퍼스에서는 전부 증명된다** — 34,635 블록, unbound 0."""
    analyzer = EffectAnalyzer(repo)
    per_block: dict[str, int] = {}
    unbound = 0
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
    for card in cards:
        analysis = analyzer.analyze(card)
        unbound += len(analysis.unbound_effects)
        assert analysis.handler_binding is HandlerBinding.MATCHED, card.id
        for effect in list(analysis.effects) + list(analysis.resolution_effects):
            key = effect.handler_binding.value
            per_block[key] = per_block.get(key, 0) + 1
    assert per_block == {HandlerBinding.MATCHED.value: ATTACHED_BLOCKS}
    assert unbound == 0


def test_41_corpus_wide_every_script_carries_a_usable_identifier():
    r"""🟢 전수 — 12,702 스크립트에서 지문이 있고 offset 이 1:1·중복 0 이다."""
    scripts = sorted(PROJECT_ROOT.glob("c*.lua"))
    assert len(scripts) == SCRIPT_COUNT
    blocks = 0
    bad = []
    for path in scripts:
        card_id = int(re.match(r"c(\d+)", path.name).group(1))
        text = path.read_text(encoding="utf-8", errors="replace")
        info = parse_lua_source(card_id, path.name, text)
        blocks += len(info.effects)
        if (info.source_digest is None
                or len(info.effect_offsets) != len(info.effects)
                or len(set(info.effect_offsets)) != len(info.effect_offsets)
                or info.effect_offsets != sorted(info.effect_offsets)):
            bad.append(path.name)
    assert blocks == BLOCK_TOTAL
    assert bad == []


def test_42_analysis_totals_match_the_baseline(repo):
    r"""🟢 등록/해결 효과 수와 조건·비용·대상·행동·분류 집계가 기준 그대로다."""
    analyzer = EffectAnalyzer(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert sum(len(c.script.effects) for c in cards) == ATTACHED_BLOCKS
    totals = dict.fromkeys(ANALYSIS_TOTALS, 0)
    for card in cards:
        analysis = analyzer.analyze(card)
        totals["registered"] += len(analysis.effects)
        totals["resolution"] += len(analysis.resolution_effects)
        for effect in list(analysis.effects) + list(analysis.resolution_effects):
            totals["cond"] += bool(effect.has_condition)
            totals["cost"] += bool(effect.costs)
            totals["target"] += bool(effect.targets_card)
            totals["action"] += len(effect.actions)
            totals["cat"] += len(effect.categories)
    assert totals == ANALYSIS_TOTALS


def test_43_search_results_and_ranking_match_the_baseline(repo):
    r"""🟢 검색 결과와 순위가 기준 그대로다.

    🔴 64자리 지문 리터럴을 적지 않는다 — Phase 3-F-33 의 ``test_36`` 이
    ``tests/`` 전체의 64자 16진수 상수를 세기 때문이다 (위험 N15).
    분류·위치별 **결과 개수**로 못 박는다.
    """
    engine = CardSearchEngine(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert len(categories) == SEARCH_CATEGORIES
    assert len(locations) == SEARCH_LOCATIONS
    category_counts = [
        len(engine.search(SearchFilters(effect_categories=(name,))).cards)
        for name in categories
    ]
    assert sum(category_counts) == 19372
    location_counts = []
    for name in locations:
        try:
            result = engine.search(SearchFilters(
                effect_locations=(EffectLocationFilter(location=name),)))
        except Exception:
            location_counts.append(-1)
            continue
        location_counts.append(len(result.cards))
    assert sum(location_counts) == 10612
    mzone = [c.id for c in engine.search(SearchFilters(
        effect_locations=(EffectLocationFilter(location="MZONE"),))).cards]
    assert 56410769 in mzone


def test_44_effect_ref_resolution_is_unchanged_corpus_wide(repo):
    r"""🟢 ``EffectRef(card_id, ordinal)`` 이 전수에서 그대로 해석된다."""
    bad = 0
    total = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        refs = effect_refs(card)
        total += len(refs)
        if len(refs) != len(card.script.effects):
            bad += 1
            continue
        for ordinal, ref in enumerate(refs):
            if ref != EffectRef(card.id, ordinal):
                bad += 1
            elif ref.resolve(card) is not card.script.effects[ordinal]:
                bad += 1
    assert total == ATTACHED_BLOCKS
    assert bad == 0


def test_45_ordinal_is_still_append_only_relative_to_offsets(repo):
    r"""🟢 ``ordinal`` 과 offset 이 **같은 순서**다 — 규칙을 바꾸지 않았다."""
    checked = 0
    for card in repo.all_cards():
        if card.script is None or not card.script.effect_offsets:
            continue
        offsets = card.script.effect_offsets
        assert offsets == sorted(offsets), card.id
        assert len(offsets) == len(card.script.effects), card.id
        checked += 1
    assert checked > 12000


# ===========================================================================
# F. Phase 3-F-27~36 회귀
# ===========================================================================
def test_46_phase_3f32_three_cases_are_preserved():
    r"""🟢 3-F-32 의 세 ``Clone`` 사례가 그대로이고 offset 도 1:1 이다."""
    for card_id, (count, ordinal, code, parent) in PHASE32_CARDS.items():
        path = PROJECT_ROOT / f"c{card_id}.lua"
        info = parse_lua_source(card_id, path.name,
                                path.read_text(encoding="utf-8"))
        assert len(info.effects) == count, card_id
        assert info.effects[ordinal].code == code, card_id
        assert info.effects[ordinal].cloned_from == parent, card_id
        assert len(info.effect_offsets) == count, card_id
        assert info.effect_offsets[ordinal] != info.effect_offsets[ordinal - 1]


def test_47_phase_3f32_offsets_for_c4997565_are_the_measured_ones():
    r"""🟢 실제 카드의 블록 자리를 못 박는다 — 추측하지 않고 측정값이다."""
    path = PROJECT_ROOT / "c4997565.lua"
    info = parse_lua_source(4997565, path.name, path.read_text(encoding="utf-8"))
    assert info.effect_offsets == C4997565_OFFSETS


def test_48_phase_3f32_group_clone_counter_example_is_preserved():
    r"""🟢 ``Group`` 에 대한 ``Clone`` 은 여전히 블록이 아니다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    info = parse_lua_source(GROUP_CLONE_CARD, path.name,
                            path.read_text(encoding="utf-8"))
    assert [s.index for s in info.effects] == ["e1"]
    assert len(info.effect_offsets) == 1


def test_49_phase_3f31_label_object_card_is_preserved(repo):
    r"""🟢 ``GetLabelObject`` 카드가 그대로 분석되고 전부 증명된다."""
    card = repo.get(LABEL_OBJECT_CARD)
    assert card is not None and card.script is not None
    analysis = EffectAnalyzer(repo).analyze(card)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.unbound_effects == []
    assert len(card.script.effect_offsets) == len(card.script.effects)


def test_50_state_hash_is_still_structurally_independent():
    r"""🟢 ``state_hash`` 가 효과 블록을 보지 않는다 (AST)."""
    import engine.state.game_state as game_state_module

    func = next(
        node for node in ast.walk(ast.parse(inspect.getsource(game_state_module)))
        if isinstance(node, ast.FunctionDef) and node.name == "canonical_state"
    )
    text = ast.dump(func)
    for token in ("script", "effects", "EffectSpec", "ordinal",
                  "handler_binding", "source_digest"):
        assert token not in text


def test_51_engine_v1_library_is_untouched():
    r"""🟢 Engine V1 freeze — 16개 정의, 전부 ``ordinal 0``."""
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 16
    assert {entry.effect_ref.ordinal for entry in EFFECT_LIBRARY} == {0}


# ===========================================================================
# G. 변경 범위 (§7 / §11)
# ===========================================================================
def test_52_production_change_is_confined_to_five_files():
    r"""🟢 §7 — parser 자료구조 · 모델 · 결합 자리만 건드렸다.

    다섯 번째인 ``core/card_repository.py`` 는 **주석만** 바뀌었다 —
    3-F-35 가 적어 둔 설명이 결합 방식이 바뀌면서 사실과 어긋나게 됐다.
    """
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    production = {p for p in changed
                  if not p.startswith(("tests/", "docs/"))}
    assert production <= {
        "core/card_model.py",
        "core/card_repository.py",
        "sources/lua_loader.py",
        "analysis/effect_model.py",
        "analysis/effect_analyzer.py",
    }, production
    #: 🟢 ``card_repository`` 는 주석만 — 실행되는 줄이 하나도 바뀌지 않았다.
    diff = subprocess.run(
        ["git", "log", "-p", "--format=", "--grep=^Phase 3-F-37:",
         "--", "core/card_repository.py"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    ).stdout
    changed_code = [
        line for line in diff.split("\n")
        if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
        and line[1:].strip()
        and not line[1:].lstrip().startswith("#")
    ]
    assert changed_code == [], changed_code


def test_53_no_forbidden_path_was_touched():
    r"""🟢 §7 금지 — ``engine/``·``agent/``·Lua·README 를 건드리지 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert not [p for p in changed if p.endswith(".lua")]
    assert not [p for p in changed if p.endswith("README.md")]
    assert not [p for p in changed if p.startswith(("engine/", "agent/"))]


def test_54_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다."""
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-37:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    added_skips = 0
    removed_tests = 0
    for sha in shas:
        diff = subprocess.run(
            ["git", "show", "--format=", "--unified=0", sha, "--", "tests/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        ).stdout
        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(r"@pytest\.mark\.skip|pytest\.skip\(", line):
                    if "commit 이 아직 없다" not in line:
                        added_skips += 1
            if line.startswith("-def test_"):
                removed_tests += 1
    assert added_skips == 0
    assert removed_tests == 0
