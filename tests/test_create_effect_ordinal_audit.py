"""
Phase 3-F-28 — ``local`` 없는 ``Effect.CreateEffect`` 누락 감사 및
``EffectRef``/``ordinal`` 경계 검증.

판정: **A. CONFIRMED_CREATE_EFFECT_OMISSION + C. CONFIRMED_DOWNSTREAM_REFERENCE_BUG**

🔴 ``local`` 요구는 **버그가 아니라 대리 지표**였다
----------------------------------------------------
고치기 전 ``_RE_CREATE_EFFECT`` 는 ``\\blocal\\s+(e\\w*)\\s*=\\s*Effect\\.
CreateEffect`` 였다. ``local`` + ``e`` 로 시작하는 변수명을 요구한다. 그래서
``Effect.CreateEffect`` 호출 **32,157곳** 중 220곳, ``X=Y:Clone()`` **2,773곳**
(Group clone 54곳 제외) 중 29곳, 합 **249곳**을 세지 않았다.

그 249곳을 전수로 분류했더니 **249곳 전부가 이 카드의 효과가 아니다.**

* **245곳** — ``Duel.RegisterEffect`` 로 **듀얼에** 등록되는 전역 효과
  (create 216 · clone 29). 관례상 ``ge1`` ``ge2`` 처럼 쓴다.
* **4곳** — ``tc:RegisterEffect`` · ``token:RegisterEffect`` 로 **다른 카드에**
  부여하는 효과 (``local`` 있는 것 3 · 없는 것 1).

세면 ``ordinal`` 이 틀어지므로 **세지 않는 것이 맞다.** 그래서 이 Phase 는
``local`` 요구를 걷어내지 않았다 (``test_35``).

🔴 그러나 **두 곳**은 진짜 누락이었다 — 그래서 A 다
---------------------------------------------------
그 대리 지표가 놓친 자리 중 **둘**은 ``c:RegisterEffect(var)`` 로 **이 카드에**
등록된다. 즉 이 카드의 효과다.

* ``c9839115`` (월롱룡 바그나와) — ``s.lvop`` 안의 ``e1=Effect.CreateEffect(c)``
  에 ``local`` 이 없다. 세지 않으면 그 블록의 설정자가 **앞 블록으로 흘러들고**,
  앞 블록의 ``code`` 가 ``EVENT_SPSUMMON_SUCCESS`` → ``EFFECT_UPDATE_ATTACK``
  으로 덮인다 (``test_16``). 3-E-18 이 이 덮어쓰기를 적어 두었고
  (``test_setcode_provenance_audit.py::test_17``), 3-F-27 의 production ↔ 교체
  규칙 차이 **1건**도 이것이었다.
* ``c74506079`` — ``local ae=Effect.CreateEffect(c)`` 의 변수명이 ``e`` 로
  시작하지 않는다. 블록 하나가 아예 없었고, 그 뒤 세 블록의 ``ordinal`` 이
  **1씩 당겨져** 있었다 (``test_16``).

🔴 그리고 **블록 주석**을 세고 있었다
-------------------------------------
``c9409625`` 는 ``--[[ untested version ... --]]`` 안에 효과 블록 하나를 적어
둔다. 파서가 그것을 세어 ``e3`` 가 ordinal 3, ``e4`` 가 4 였다 — **각각 2 · 3 이
맞다.** 주석 안의 코드는 Lua 가 실행하지 않으므로 효과가 아니다 (``test_31``).

🔴 downstream — ``analysis`` 가 **같은 탐지를 따로 복사해** 갖고 있었다 (C)
---------------------------------------------------------------------------
``analysis/effect_analyzer.py`` 는 ``_RE_CREATE_EFFECT`` · ``_RE_CLONE_EFFECT``
· ``_RE_SETTER`` 를 **자기 모듈에 따로** 정의하고, ``_analyze_card`` 가
``entries[position]`` 과 ``card.script.effects[position]`` 을 **순번으로**
짝지었다 (*"lua_loader 와 같은 순서로 효과 블록이 만들어지므로 순번으로
짝짓는다"*). 두 복사본이 우연히 같아서 12,702 스크립트 **전부** 일치했고,
로더만 고친 순간 **3개가 어긋났다** — 그 3개에서 핸들러가 **다른 블록에**
붙는다. 그래서 탐지 규칙을 로더에서 ``import`` 하도록 바꿨다 (``test_32``).

수정 (최소)
-----------
``sources/lua_loader.py``

* ``_RE_BLOCK_COMMENT`` 로 ``--[[ … ]]`` 를 **탐지 전에** 지운다. 헤더의 카드명은
  그 전에 **원문**에서 읽고, 줄 주석(``--``)은 남긴다.
* ``_RE_CREATE_EFFECT`` · ``_RE_CLONE_EFFECT`` 에서 ``local`` 과 ``e`` 접두사를
  **필수에서 선택으로** 내리고, 받아들일지는 ``_is_card_effect`` 가 정한다 —
  기존 관례(``local`` + ``e*``)를 **그대로 유지**하고, 그것이 놓친 자리에서만
  ``c:RegisterEffect(var)`` 라는 명시적 증거로 보강한다.
* ``_RE_SETTER`` 의 변수명 범위를 같이 넓힌다 (``ae:SetCode`` 를 읽으려면 필요).
* ``_signature`` 를 ``v5`` → ``v6`` 으로 올린다 (``test_20``).

``analysis/effect_analyzer.py``

* 블록 탐지 정규식·주석 제거·``_is_card_effect`` 를 로더에서 ``import`` 한다.
  이제 두 모듈이 **같은 규칙을 공유**하므로 다시 어긋날 수 없다.

새 abstraction · 새 enum · 새 식별 체계는 없다. ``EffectRef(card_id, ordinal)``
그대로이고 ``EffectSpec`` · ``EffectDefinition`` · engine 은 바뀌지 않았다
(``test_36``).

영향 범위
---------
corpus 전수 비교 결과 ``effects`` 가 바뀐 스크립트는 **정확히 3개**이고
(34,680 → 34,681 블록), ``LuaScriptInfo`` 의 **다른 어떤 칸도 바뀌지 않았다**
(``test_33``). 등록된 **16개 ``EffectDefinition`` 은 전부 1블록 · ordinal 0 ·
수정 전후 완전히 동일**하다 — production 실행 경로는 닿지 않았다 (``test_17``).
"""

import ast
import collections
import dataclasses
import hashlib
import inspect
import json
import pathlib
import re
import subprocess
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from analysis.effect_analyzer import EffectAnalyzer
from core.card_model import EffectSpec, LuaScriptInfo
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardDefinitionView
from engine.ids import EffectRef, effect_refs, iter_effects
import sources.lua_loader as lua_loader
from sources.lua_loader import LuaScriptSource, parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MYSELF = "tests/test_create_effect_ordinal_audit.py"

# ======================================================================
# 측정값 — 전부 이 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: 스크립트 파일 수.
SCRIPTS = 12702
#: 블록 주석을 지운 뒤의 ``Effect.CreateEffect|GlobalEffect`` 호출 자리.
#: **전부 변수에 배정된다** (배정되지 않는 자리 0곳 — ``test_34``).
CREATE_SITES = 32157
#: ``X = Y:Clone()`` 자리 중 부모가 Effect 인 것. 나머지 54곳은 Group clone 이다.
CLONE_SITES_OF_EFFECT = 2773
CLONE_SITES_OF_GROUP = 54

#: 파서가 만드는 블록 — 수정 후.
BLOCKS = 34681
BLOCKS_FROM_CREATE = 31937
BLOCKS_FROM_CLONE = 2744
#: 수정 전.
BLOCKS_BEFORE = 34680

#: 파서가 **일부러 세지 않는** 자리와 그 이유 (전수 분류 — ``test_34``).
SKIPPED_CREATE = 220
SKIPPED_CLONE = 29
SKIPPED_DUEL_GLOBAL = 245          # Duel.RegisterEffect (create 216 + clone 29)
SKIPPED_OTHER_CARD = 4             # tc:/token:RegisterEffect
#: 그 자리를 **아직도** 가진 스크립트 수. 🔴 고치기 전에는 199 였다 —
#: 새로 세기 시작한 두 자리가 있던 ``c9839115`` · ``c74506079`` 는 다른 건너뛸
#: 자리가 없어서 목록에서 빠진다.
SKIPPED_SCRIPTS = 197

#: 🔴 이 Phase 가 **새로 세기 시작한** 블록 — corpus 전체에 둘뿐이다.
NON_LOCAL_CARD_EFFECT = 9839115    # e1=Effect.CreateEffect(c) — local 없음
NON_E_NAME_CARD_EFFECT = 74506079  # local ae=Effect.CreateEffect(c) — e 로 시작 안 함
#: 🔴 블록 주석 안의 블록을 세고 있던 스크립트.
COMMENTED_BLOCK = 9409625
#: 🔴 ``local`` 이 없지만 **다른 카드**(``tc``) 에 주는 효과 — 세지 않는 것이 맞다.
NON_LOCAL_OTHER_CARD = 5795980

#: 전역 효과를 가진 실제 스크립트 (``Duel.RegisterEffect``) — 표본.
DUEL_GLOBAL_SAMPLE = (10113611, 10497636, 12275533, 12958919, 13076804,
                      13224603, 13567610, 13764602, 14318794, 15216188,
                      16832845, 1801154, 18114794, 18558867, 18969888)
#: ``ge1`` 을 ``Clone`` 해서 또 전역으로 등록하는 스크립트 — 표본.
DUEL_GLOBAL_CLONE_SAMPLE = (12275533, 13224603, 19974890, 21848500, 27204311,
                            28497830, 30432463, 3048768, 31149212, 33776734)

#: digest 용 덱 — 3-F-24 이후 모든 Phase 가 같은 것을 쓴다.
LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522
GENEROUS_REWARD = 5915629
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4

#: 수정 전 파서의 탐지 규칙 — ``test_14`` 가 "밀림" 을 **구성으로** 보여줄 때 쓴다.
#: production 을 호출하지 않으므로 production 이 바뀌어도 이 규칙은 그대로다.
LEGACY_CREATE = re.compile(
    r"\blocal\s+(e\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\("
)


# ======================================================================
# 측정 도구
# ======================================================================


def blocks_of(source: str) -> list[EffectSpec]:
    """Lua 조각 하나를 파서에 그대로 먹인다."""
    return parse_lua_source(0, "c0.lua", inspect.cleandoc(source)).effects


def shape(specs) -> list[tuple[str, list[str], str | None]]:
    """``(변수명, effect_types, code)`` — 블록의 모양만 본다."""
    return [(s.index, list(s.effect_types), s.code) for s in specs]


def script_text(card_id: int) -> str:
    return (PROJECT_ROOT / f"c{card_id}.lua").read_text(encoding="utf-8")


def parse_card(card_id: int) -> LuaScriptInfo:
    """🔴 캐시를 거치지 않고 **원문을 직접** 파싱한다 (3-E-17 의 교훈)."""
    path = PROJECT_ROOT / f"c{card_id}.lua"
    return parse_lua_source(card_id, path.name, path.read_text(encoding="utf-8"))


def analyzer_blocks(source: str) -> list[dict]:
    """``analysis`` 쪽이 세는 블록 — 로더와 **같은 수**여야 한다."""
    return EffectAnalyzer._collect_handlers(source, EffectAnalyzer._function_spans(source))


def opened_duel(repository, *, seed: int) -> Duel:
    duel = Duel.start(
        repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


@pytest.fixture(scope="module")
def scripts():
    """스크립트 전수 — 블록 통계의 기준."""
    return LuaScriptSource(PROJECT_ROOT).load()


@pytest.fixture(scope="module")
def sources():
    """``card_id -> 원문`` 전수. 정규식 재측정용."""
    out = {}
    for card_id, path in LuaScriptSource(PROJECT_ROOT).iter_script_files():
        out[card_id] = path.read_text(encoding="utf-8", errors="replace")
    return out


# ======================================================================
# A. §19-1~9 — 최소 사례 (파서에 Lua 조각을 직접 먹인다)
# ======================================================================


def test_01_a_local_create_effect_is_one_block():
    """🟢 §19-1 — ``local e1=Effect.CreateEffect(c)`` 는 블록 하나다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
    """)
    assert shape(specs) == [("e1", ["IGNITION"], "EVENT_FREE_CHAIN")]


def test_02_a_non_local_create_effect_needs_card_registration():
    """
    🔴 §19-2 · §5 — ``local`` 이 없는 생성은 **그 자체로는** 블록이 아니다.

    ``local`` 유무는 판정의 **전부가 아니다** — ``c:RegisterEffect(var)`` 라는
    증거가 있으면 ``local`` 없이도 블록이고, 없으면 (듀얼 전역이거나 다른
    카드의 효과이므로) 블록이 아니다. 같은 Lua 에서 그 한 줄만 다르다.
    """
    without = blocks_of("""
        e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        Duel.RegisterEffect(e1,tp)
    """)
    assert without == []

    with_registration = blocks_of("""
        e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        c:RegisterEffect(e1)
    """)
    assert shape(with_registration) == [("e1", ["SINGLE"], "EFFECT_UPDATE_ATTACK")]

    #: 다른 카드에 주는 것도 **이 카드의** 블록이 아니다.
    to_another = blocks_of("""
        e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        tc:RegisterEffect(e1)
    """)
    assert to_another == []


def test_03_a_single_create_effect_stands_alone():
    """🟢 §19-3 — 설정자가 하나도 없어도 블록은 하나다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
    """)
    assert shape(specs) == [("e1", [], None)]


def test_04_several_create_effects_keep_the_written_order():
    """🟢 §19-4 · **Invariant 1** — 원문 순서가 그대로 ``ordinal`` 이다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_GRAVE)
        local e3=Effect.CreateEffect(c)
        e3:SetCode(EVENT_SPSUMMON_SUCCESS)
    """)
    assert [s.index for s in specs] == ["e1", "e2", "e3"]
    assert [s.code for s in specs] == [
        "EVENT_FREE_CHAIN",
        "EVENT_TO_GRAVE",
        "EVENT_SPSUMMON_SUCCESS",
    ]


def test_05_local_and_non_local_do_not_merge():
    """
    🔴 §19-5 · **Invariant 2** — 섞여 있어도 ``CreateEffect`` 하나당 블록 하나다.

    고치기 전에는 두 번째 ``e1`` 이 새 블록이 되지 않아 그 설정자가 **첫
    블록으로 흘러들었다.** 그 결과 첫 블록의 ``code`` 가 덮였다. 이것이
    ``c9839115`` 에서 실제로 일어난 일이다 (``test_16``).
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
        e1:SetCode(EVENT_SPSUMMON_SUCCESS)
        c:RegisterEffect(e1)
        e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        c:RegisterEffect(e1)
    """)
    assert shape(specs) == [
        ("e1", ["SINGLE", "TRIGGER_O"], "EVENT_SPSUMMON_SUCCESS"),
        ("e1", ["SINGLE"], "EFFECT_UPDATE_ATTACK"),
    ]
    #: 🔴 ``index`` 가 같아도 **다른 블록**이다 — 식별자는 ``ordinal`` 이다.
    assert specs[0] is not specs[1]
    assert specs[0].index == specs[1].index == "e1"


def test_06_create_effect_with_settype():
    """🟢 §19-6 — ``local`` 없는 블록의 ``SetType`` 도 자기 블록에 붙는다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_CONTINUOUS)
        c:RegisterEffect(e1)
        ae=Effect.CreateEffect(c)
        ae:SetType(EFFECT_TYPE_EQUIP)
        c:RegisterEffect(ae)
    """)
    #: 플래그 순서는 **한 호출 안의 등장 순서**다 — 파서가 정렬하지 않는다.
    assert shape(specs) == [
        ("e1", ["FIELD", "CONTINUOUS"], None),
        ("ae", ["EQUIP"], None),
    ]


def test_07_create_effect_with_setcode():
    """🔴 §19-7 — ``SetCode`` 가 **앞 블록으로 새지 않는다.**"""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_SPSUMMON_SUCCESS)
        c:RegisterEffect(e1)
        local ae=Effect.CreateEffect(c)
        ae:SetCode(EFFECT_SET_ATTACK)
        c:RegisterEffect(ae)
    """)
    assert [s.code for s in specs] == ["EVENT_SPSUMMON_SUCCESS", "EFFECT_SET_ATTACK"]


def test_08_create_effect_with_clone():
    """🟢 §19-8 · **Invariant 6** — ``Clone`` 과 ``CreateEffect`` 가 충돌하지 않는다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        c:RegisterEffect(e2)
    """)
    assert shape(specs) == [
        ("e1", ["IGNITION"], "EVENT_FREE_CHAIN"),
        ("e2", ["QUICK_O"], "EVENT_FREE_CHAIN"),
    ]
    assert [s.cloned_from for s in specs] == [None, "e1"]


def test_09_several_clones_each_become_their_own_block():
    """🟢 §19-9 — ``Clone`` 을 여러 번 해도 자리마다 블록 하나다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        c:RegisterEffect(e2)
        local e3=e1:Clone()
        c:RegisterEffect(e3)
        local e4=e2:Clone()
        c:RegisterEffect(e4)
    """)
    assert [s.index for s in specs] == ["e1", "e2", "e3", "e4"]
    assert [s.cloned_from for s in specs] == [None, "e1", "e1", "e2"]
    assert all(s.code == "EVENT_FREE_CHAIN" for s in specs)
    #: 🔴 네 블록이 같은 리스트 객체를 공유하지 않는다.
    assert len({id(s.effect_types) for s in specs}) == 4


# ======================================================================
# B. §19-10~14 — ordinal · EffectRef · 밀림
# ======================================================================


def test_10_initial_effect_separates_registered_from_resolution_blocks():
    """
    🔴 §19-10 · **Invariant 7** — ``initial_effect`` 안의 블록만 "등록된" 것이다.

    ``analysis`` 가 블록이 **어느 함수 안에서** 만들어졌는지로 그것을 가린다.
    ``local`` 없는 생성은 대개 해결 함수 안에 있으므로 이 구분이 중요하다.
    """
    source = inspect.cleandoc("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
        end
        function s.operation(e,tp)
            e1=Effect.CreateEffect(c)
            e1:SetCode(EFFECT_UPDATE_ATTACK)
            c:RegisterEffect(e1)
        end
    """)
    entries = analyzer_blocks(source)
    assert [entry["function"] for entry in entries] == ["initial_effect", "operation"]
    #: 로더도 같은 두 블록을 센다 — 짝이 맞는다.
    assert len(parse_lua_source(0, "c0.lua", source).effects) == len(entries) == 2


def test_11_ordinal_is_the_position_in_the_effects_list(repository):
    """🟢 §19-11 — ``ordinal`` 은 ``card.script.effects`` 안의 0-기반 위치다."""
    card = repository.get(NON_E_NAME_CARD_EFFECT)
    assert card is not None and card.script is not None
    refs = effect_refs(card)
    assert [ref.ordinal for ref in refs] == list(range(len(card.script.effects)))
    for position, (ref, spec) in enumerate(iter_effects(card)):
        assert ref.ordinal == position
        assert spec is card.script.effects[position]
    #: 새로 센 블록 때문에 다섯 자리다 (고치기 전에는 넷이었다).
    assert len(refs) == 5


def test_12_effect_ref_resolves_to_exactly_that_position(repository):
    """🟢 §19-12 · **Invariant 5** — ``EffectRef(card_id, n)`` 이 n번째를 가리킨다."""
    card = repository.get(NON_LOCAL_CARD_EFFECT)
    assert card is not None
    for position in range(len(card.script.effects)):
        assert EffectRef(card.id, position).resolve(card) is card.script.effects[position]
    #: 범위를 벗어나면 ``None`` 이고, 다른 카드로는 풀리지 않는다.
    assert EffectRef(card.id, len(card.script.effects)).resolve(card) is None
    assert EffectRef(card.id + 1, 0).resolve(card) is None


def test_13_no_block_is_dropped_in_the_middle(scripts):
    """
    🔴 §19-13 · **Invariant 3** — 중간 블록이 빠지지 않는다.

    ``Clone`` 의 부모가 **그 전에 이미 블록으로 있어야** 한다. 중간 블록이
    빠지면 부모를 못 찾아 ``Clone`` 이 빈 목록을 물려받는다. corpus 전수에서
    부모를 못 찾는 ``Clone`` 블록을 센다.

    .. warning::
       🔴 **예외가 정확히 1건 있고, 이 Phase 가 고치지 않았다.**
       ``c39114494`` 의 ``e3`` 는 ``Effect.CreateEffect`` 가 아니라
       ``Ritual.CreateProc({...})`` 가 만든다. 파서는 ``Effect.CreateEffect``
       와 ``:Clone()`` 만 블록으로 보므로 ``e3`` 가 블록이 아니고, 그래서
       ``e4=e3:Clone()`` 이 부모를 못 찾는다.

       이것은 ``local`` 과 무관한 **별개의 구조적 한계**다 — 효과를 만드는
       보조 함수(``Fusion.CreateSummonEff`` 45 · ``Ritual.CreateProc`` 20 ·
       ``Ritual.AddProcGreater`` 5)를 파서가 모른다. 이 Phase 의 범위
       (``CreateEffect`` 탐지 · ``ordinal`` · ``EffectRef``) 밖이므로
       **추측해서 구조화하지 않고 숫자로 고정만 한다.** 보고서 §22 참고.
    """
    orphans = []
    for card_id, info in scripts.items():
        seen: set[str] = set()
        for position, spec in enumerate(info.effects):
            if spec.cloned_from is not None and spec.cloned_from not in seen:
                orphans.append((card_id, position, spec.index, spec.cloned_from))
            seen.add(spec.index)
    #: 🔴 전수에서 **이 1건뿐**이다. 늘어나면 그것이 신호다.
    assert orphans == [(39114494, 2, "e4", "e3")], orphans[:20]
    #: 원인이 ``local`` 이 아니라 **보조 함수**임을 원문으로 못 박는다.
    text = script_text(39114494)
    assert "local e3=Ritual.CreateProc(" in text
    assert "local e3=Effect.CreateEffect" not in text
    assert "local e4=e3:Clone()" in text


def test_14_a_missed_block_shifts_every_later_ordinal():
    """
    🔴 §19-14 — "놓침" 은 통계가 아니라 **``ordinal`` 밀림**이다.

    고치기 전 규칙(``local`` + ``e*`` 필수)을 이 테스트 안에서 다시 세워
    **같은 Lua** 에 두 규칙을 돌린다. 세 블록 중 가운데를 놓치면 세 번째의
    ``ordinal`` 이 2 → 1 로 당겨지고, ``EffectRef(card, 2)`` 는 **아무것도**
    가리키지 않는다. ``c74506079`` 에서 실제로 그랬다.
    """
    source = inspect.cleandoc("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        local ae=Effect.CreateEffect(c)
        ae:SetCode(EFFECT_SET_ATTACK)
        c:RegisterEffect(ae)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_GRAVE)
        c:RegisterEffect(e2)
    """)
    legacy = [m.group(1) for m in LEGACY_CREATE.finditer(source)]
    fixed = [spec.index for spec in parse_lua_source(0, "c0.lua", source).effects]

    assert legacy == ["e1", "e2"]                  # 가운데를 놓친다
    assert fixed == ["e1", "ae", "e2"]             # 고친 뒤
    #: 🔴 밀림의 정체 — 같은 ``ordinal`` 2 가 다른 것을 가리킨다.
    assert legacy.index("e2") == 1
    assert fixed.index("e2") == 2
    assert len(legacy) < len(fixed)


# ======================================================================
# C. §19-15~17 — 실제 corpus · 실제 카드 · 16개 EffectDefinition
# ======================================================================


def test_15_the_real_non_local_sites_in_the_corpus(sources):
    r"""
    🔴 §19-15 · §8 — ``local`` 없는 ``CreateEffect`` 는 corpus 전체에 **3곳**이다.

    3-F-27 은 "약 217곳 / 195파일" 이라고 적었다. 🔴 그 숫자는 **``local`` 이
    없는 자리** 가 아니라 ``_RE_CREATE_EFFECT`` 가 세지 않는 자리 전체였다 —
    대부분은 ``local`` 이 있고 **변수명이 ``e`` 로 시작하지 않는다**
    (``ge1`` 등). 이 Phase 가 셋으로 분해했다.
    """
    create_nonlocal, clone_nonlocal, local_non_e = [], [], []
    for card_id, text in sources.items():
        body = lua_loader._RE_BLOCK_COMMENT.sub("", text)
        for match in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if not match.group(1):
                create_nonlocal.append((card_id, match.group(2)))
            elif not match.group(2).startswith("e"):
                local_non_e.append((card_id, match.group(2)))
        for match in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if not match.group(1):
                clone_nonlocal.append((card_id, match.group(2)))

    #: 🔴 ``local`` 이 **진짜로 없는** 자리 — create 2 · clone 1.
    assert sorted(create_nonlocal) == [
        (NON_LOCAL_OTHER_CARD, "e3"),
        (NON_LOCAL_CARD_EFFECT, "e1"),
    ], create_nonlocal
    assert clone_nonlocal == [(42237854, "tg")], clone_nonlocal

    #: 🔴 나머지는 ``local`` 이 **있고** 이름이 ``e`` 로 시작하지 않는다.
    assert len(local_non_e) == 220
    names = collections.Counter(name for _, name in local_non_e)
    assert names["ge1"] == 180, names.most_common(8)
    assert names["ae"] == 2
    #: 그중 하나만 이 카드의 효과다 — 나머지는 전역/다른 카드 (``test_34``).
    assert (NON_E_NAME_CARD_EFFECT, "ae") in local_non_e


def test_16_the_three_real_cards_are_exactly_what_changed():
    """
    🔴 §19-16 · §8 · §12 — 실제 카드 세 장의 **수정 전/후 전체 블록**.

    1. ``c9839115`` — 흘러들던 ``code`` 가 제자리로 돌아오고 블록이 하나 늘었다.
    2. ``c74506079`` — 없던 블록이 생기고 **뒤 세 블록의 ordinal 이 1씩 밀렸다.**
    3. ``c9409625`` — 주석 안의 블록이 사라지고 **뒤 두 블록이 1씩 당겨졌다.**
    """
    # 1 — 귀속 오류가 사라졌다.
    poisoned = parse_card(NON_LOCAL_CARD_EFFECT)
    assert shape(poisoned.effects) == [
        ("e0", ["SINGLE"], "EFFECT_MATERIAL_CHECK"),
        ("e1", ["SINGLE", "TRIGGER_O"], "EVENT_SPSUMMON_SUCCESS"),
        ("e1", ["SINGLE"], "EFFECT_UPDATE_ATTACK"),
    ]
    #: Lua 원문은 손대지 않았다 — 고친 것은 파서다.
    assert "\n\t\te1=Effect.CreateEffect(c)" in script_text(NON_LOCAL_CARD_EFFECT)

    # 2 — 없던 블록이 ordinal 1 로 들어가고 뒤가 밀렸다.
    renamed = parse_card(NON_E_NAME_CARD_EFFECT)
    assert shape(renamed.effects) == [
        ("e2", ["SINGLE"], "EFFECT_MATERIAL_CHECK"),
        ("ae", ["SINGLE"], "EFFECT_SET_ATTACK"),
        ("e1", ["IGNITION"], None),
        ("e1", ["IGNITION"], None),
        ("e1", ["IGNITION"], None),
    ]
    #: 🔴 밀린 세 블록은 ``categories`` 로 서로 구별된다 — 서로 다른 효과다.
    assert [list(s.categories) for s in renamed.effects[2:]] == [
        ["SPECIAL_SUMMON"], ["TOGRAVE"], ["DRAW"],
    ]

    # 3 — 주석 안의 블록이 사라지고 뒤가 당겨졌다.
    commented = parse_card(COMMENTED_BLOCK)
    assert shape(commented.effects) == [
        ("e1", ["ACTIVATE"], "EVENT_FREE_CHAIN"),
        ("e2", ["CONTINUOUS", "SINGLE"], "EFFECT_DESTROY_REPLACE"),
        ("e3", ["QUICK_O"], "EVENT_FREE_CHAIN"),
        ("e4", ["QUICK_O"], "EVENT_FREE_CHAIN"),
    ]
    #: 사라진 블록의 코드는 **주석 안에만** 있다.
    text = script_text(COMMENTED_BLOCK)
    assert "EFFECT_INDESTRUCTABLE_COUNT" in text
    assert "EFFECT_INDESTRUCTABLE_COUNT" not in lua_loader._RE_BLOCK_COMMENT.sub("", text)
    assert "EFFECT_INDESTRUCTABLE_COUNT" not in [s.code for s in commented.effects]


def test_17_all_sixteen_effect_definitions_are_untouched(repository):
    """
    🔴 §19-17 · §9 · §13 — 등록된 16개 ``EffectDefinition`` 전부 검증.

    각자 블록이 **하나**, ``ordinal`` 이 **0**, ``resolve()`` 가 성공하고
    ``code`` 가 ``EVENT_FREE_CHAIN`` 이다. 그 16장 중 ``local`` 없는
    ``CreateEffect`` 를 가진 스크립트는 **하나도 없다.** 그래서 이 수정은
    ``EffectDefinition → TriggerSpec → ChainLink → EffectRef`` 경로에
    **닿지 않는다.**
    """
    assert len(EFFECT_LIBRARY) == 16
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        assert card is not None and card.script is not None, ref
        assert ref.ordinal == 0, ref
        assert len(card.script.effects) == 1, (ref, len(card.script.effects))
        resolved = ref.resolve(card)
        assert resolved is not None, ref
        assert resolved.code == "EVENT_FREE_CHAIN", (ref, resolved.code)
        #: 그 카드의 ``EffectRef`` 는 **0번 하나**뿐이다.
        assert effect_refs(card) == [EffectRef(ref.card_id, 0)], ref

        #: 🔴 이 16장의 스크립트에는 이 Phase 가 건드린 패턴이 전혀 없다.
        text = script_text(ref.card_id)
        body = lua_loader._RE_BLOCK_COMMENT.sub("", text)
        assert body == text, ref                      # 블록 주석 없음
        for match in lua_loader._RE_CREATE_EFFECT.finditer(body):
            assert match.group(1) == "local", ref
            assert match.group(2).startswith("e"), ref

    #: 세 바뀐 카드는 등록된 16장에 **들어 있지 않다.**
    registered = {entry.definition.effect_ref.card_id for entry in EFFECT_LIBRARY}
    assert registered.isdisjoint(
        {NON_LOCAL_CARD_EFFECT, NON_E_NAME_CARD_EFFECT, COMMENTED_BLOCK}
    )


# ======================================================================
# D. §19-18~21 — 결정성 · 캐시
# ======================================================================


def test_18_parsing_is_deterministic(sources):
    """🟢 §19-18 — 같은 입력을 두 번 파싱하면 **완전히 같다**."""
    sample = sorted(sources)[:500]
    for card_id in sample:
        text = sources[card_id]
        first = parse_lua_source(card_id, f"c{card_id}.lua", text)
        second = parse_lua_source(card_id, f"c{card_id}.lua", text)
        assert [dataclasses.asdict(s) for s in first.effects] == [
            dataclasses.asdict(s) for s in second.effects
        ], card_id
    #: 세 바뀐 카드도 같이 본다.
    for card_id in (NON_LOCAL_CARD_EFFECT, NON_E_NAME_CARD_EFFECT, COMMENTED_BLOCK):
        assert shape(parse_card(card_id).effects) == shape(parse_card(card_id).effects)


def test_19_the_cache_round_trip_returns_the_same_blocks(scripts, tmp_path):
    """
    🔴 §19-19 — 캐시가 **방금 고친 파서의 결과**를 돌려준다.

    두 번 부른다. 첫 번째는 캐시를 쓰고, 두 번째는 캐시를 읽는다 (cache hit).
    세 바뀐 카드가 **두 경로에서 같아야** 한다 — 다르면 캐시가 옛 결과다.
    """
    cache = tmp_path / "lua_scripts.json"
    source = LuaScriptSource(PROJECT_ROOT)
    written = source.load_cached(cache)
    assert cache.is_file()
    read_back = source.load_cached(cache)

    for card_id in (NON_LOCAL_CARD_EFFECT, NON_E_NAME_CARD_EFFECT, COMMENTED_BLOCK):
        direct = shape(scripts[card_id].effects)
        assert shape(written[card_id].effects) == direct, card_id
        assert shape(read_back[card_id].effects) == direct, card_id

    #: 블록 총수도 세 경로가 같다.
    for table in (scripts, written, read_back):
        assert sum(len(info.effects) for info in table.values()) == BLOCKS

    #: 캐시 파일에 적힌 서명이 지금 파서의 것이다.
    blob = json.loads(cache.read_text(encoding="utf-8"))
    assert blob["signature"] == source._signature()
    assert blob["signature"].startswith("v6:")


def test_20_the_cache_signature_was_bumped_for_this_parser_change():
    """
    🔴 §19-20 · §11 — ``_signature`` 접두사가 ``v5`` → ``v6`` 으로 올랐다.

    3-E-18 이 설치한 ``test_setcode_provenance_audit.py::test_19`` 가
    **설계대로 걸려서** 이 상승을 요구했다. 3-F-27 (``v4``→``v5``) 에 이어
    **두 번째**다.
    """
    body = inspect.getsource(LuaScriptSource._signature)
    assert 'f"v6:{count}:{newest:.0f}"' in body
    #: 되돌아가지 않았는지도 본다.
    for old in ("v5:", "v4:", "v3:"):
        assert f'f"{old}' not in body, old
    assert LuaScriptSource(PROJECT_ROOT)._signature().startswith("v6:")

    #: 🔴 서명에 파서 버전·코드 해시가 **들어 있지 않다** — 그래서 손으로 올린다.
    for token in ("parse_lua_source", "__version__", "md5", "sha", "_is_card_effect"):
        assert token not in body, token


def test_21_a_stale_cache_is_rejected(tmp_path):
    """
    🔴 §19-21 — 옛 서명을 가진 캐시는 **쓰이지 않는다.**

    고친 파서가 옛 캐시를 계속 읽는 것이 3-F-27 에서 실제로 일어났다.
    고의로 ``v5`` 서명과 **틀린 내용**을 심어 놓고, 그것이 무시되는지 본다.
    """
    cache = tmp_path / "lua_scripts.json"
    cache.write_text(
        json.dumps(
            {
                "signature": "v5:12702:0",
                "scripts": {str(NON_LOCAL_CARD_EFFECT): {"file_name": "poisoned.lua"}},
            }
        ),
        encoding="utf-8",
    )
    source = LuaScriptSource(PROJECT_ROOT)
    assert source._signature() != "v5:12702:0"

    loaded = source.load_cached(cache)
    #: 심은 거짓 내용이 **하나도** 살아남지 않았다.
    assert loaded[NON_LOCAL_CARD_EFFECT].file_name == f"c{NON_LOCAL_CARD_EFFECT}.lua"
    assert shape(loaded[NON_LOCAL_CARD_EFFECT].effects) == shape(
        parse_card(NON_LOCAL_CARD_EFFECT).effects
    )
    #: 캐시 파일이 새 서명으로 다시 쓰였다.
    assert json.loads(cache.read_text(encoding="utf-8"))["signature"].startswith("v6:")

    #: 깨진 캐시도 조용히 재파싱된다 (예외를 던지지 않는다).
    cache.write_text("{ not json", encoding="utf-8")
    assert len(source.load_cached(cache)) == SCRIPTS


# ======================================================================
# E. §19-22~23 — 식별자
# ======================================================================


def test_22_card_identity_is_unchanged(repository):
    """
    🟢 §19-22 — 카드 식별자는 패스코드다. 이 Phase 는 **한 장도 더하거나
    빼지 않았다** — 바뀐 것은 세 장의 **블록 목록**뿐이다.
    """
    for card_id in (NON_LOCAL_CARD_EFFECT, NON_E_NAME_CARD_EFFECT, COMMENTED_BLOCK):
        card = repository.get(card_id)
        assert card is not None and card.id == card_id
        assert card.script is not None
        assert card.script.file_name == f"c{card_id}.lua"
        assert card.script.card_id == card_id

    #: 스크립트를 가진 카드 수와 스크립트 파일 수는 그대로다.
    assert len(list(LuaScriptSource(PROJECT_ROOT).iter_script_files())) == SCRIPTS


def test_23_effect_identity_is_still_card_id_plus_ordinal():
    """
    🔴 §19-23 · §10 — 식별 체계를 **바꾸지 않았다.**

    ``EffectRef`` 는 ``(card_id, ordinal)`` 두 칸짜리 frozen dataclass 그대로다.
    UUID · 객체 identity · Lua 변수명 중 **어느 것도** 식별자가 되지 않았다.
    """
    fields = [f.name for f in dataclasses.fields(EffectRef)]
    assert fields == ["card_id", "ordinal"]
    assert EffectRef.__dataclass_params__.frozen is True

    #: 같은 ``(card_id, ordinal)`` 이면 같은 값이고, 해시도 같다.
    assert EffectRef(1, 2) == EffectRef(1, 2)
    assert hash(EffectRef(1, 2)) == hash(EffectRef(1, 2))
    assert EffectRef(1, 2) != EffectRef(1, 3)
    assert str(EffectRef(1, 2)) == "1:e[2]"

    #: 🔴 ``EffectRef`` 에 ``index`` (Lua 변수명) 칸이 **없다.**
    assert "index" not in fields
    for banned in ("uuid", "uid", "name", "var", "token"):
        assert banned not in fields

    #: 음수는 거부한다 — 계약이 그대로다.
    with pytest.raises(ValueError):
        EffectRef(1, -1)

    #: ``ids`` · ``ids`` 를 쓰는 production 에 새 식별자 모듈이 생기지 않았다.
    ids_source = (PROJECT_ROOT / "engine" / "ids.py").read_text(encoding="utf-8")
    for banned in ("import uuid", "uuid4", "id(self)", "EffectId"):
        assert banned not in ids_source, banned


# ======================================================================
# F. §19-24~30 — 불변 조건 (engine · AI · Search)
# ======================================================================


def test_24_state_hash_is_unchanged(repository):
    """🟢 §19-24 — ``state_hash`` 가 같은 seed 에서 같고 다른 seed 에서 다르다."""
    first = opened_duel(repository, seed=41)
    second = opened_duel(repository, seed=41)
    assert first.state.state_hash() == second.state.state_hash()
    assert opened_duel(repository, seed=42).state.state_hash() != first.state.state_hash()


def test_25_the_rng_is_unchanged(repository):
    """🟢 §19-25 — 같은 seed 에서 난수열이 같다."""
    left = opened_duel(repository, seed=43)
    right = opened_duel(repository, seed=43)
    assert [left.state.rng.randrange(10_000) for _ in range(12)] == [
        right.state.rng.randrange(10_000) for _ in range(12)
    ]


def test_26_the_search_ranking_digest_is_unchanged(repository):
    """
    🔴 §19-26 · §15~19 — 6판 **611결정** digest 불변.

    🔴 이것이 "파서 데이터 수정이 duel 동작을 바꾸지 않는다" 의 **행동 증거**다.
    기대값을 손으로 적지 않는다 — 다른 테스트 파일들이 이미 고정해 둔 값을
    AST 로 읽어서 **가장 많이 고정된 것**을 쓴다.
    """
    pinned: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative == MYSELF:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(ch in "0123456789abcdef" for ch in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: collections.Counter = collections.Counter()
    for values in pinned.values():
        counts.update(values)
    expected, pins = counts.most_common(1)[0]
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == expected


def test_27_hidden_information_and_the_view_are_unchanged(repository):
    """🟢 §19-27 — ``CardDefinitionView`` 가 블록 내용을 **여전히 내보내지 않는다.**"""
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert len(fields) == 26
    assert "effect_count" in fields
    for banned in ("effect_types", "code", "script", "effects", "index", "cloned_from"):
        assert banned not in fields, banned

    duel = opened_duel(repository, seed=44)
    view = duel.view(0)
    assert not hasattr(view, "effects")


def test_28_search_was_not_touched():
    """
    🔴 §19-28 — ``core/card_search.py`` · ``core/query_parser.py`` ·
    ``agent/search.py`` 가 이 Phase 의 diff 에 **없다.**
    """
    changed = _changed_files()
    for path in (
        "core/card_search.py",
        "core/query_parser.py",
        "core/card_repository.py",
        "agent/search.py",
    ):
        assert path not in changed, (path, sorted(changed))


def test_29_the_ai_layer_was_not_touched():
    """🔴 §19-29 — ``agent/`` 전체가 diff 에 **없다.**"""
    changed = _changed_files()
    assert not [path for path in changed if path.startswith("agent/")], sorted(changed)


def test_30_engine_v1_was_not_touched():
    """
    🔴 §19-30 — ``engine/`` 전체가 diff 에 **없다.** Engine V1 freeze 유지.

    그리고 engine 은 애초에 블록의 **내용**을 읽지 않는다 — 3-F-26 · 3-F-27 이
    확정한 것이 그대로다.

    .. note::
       🔴 처음에는 "``code`` 도 ``engine/`` 에 0회" 라고 적었다. **틀렸다** —
       ``engine/`` 에 ``.code`` 속성 접근이 59곳 있고, 그것들은
       ``EffectSpec.code`` 가 아니라 거부 사유 코드(``RejectionCode``) 등
       **다른 것의 ``code``** 다. 이름이 겹친다는 것은 사용의 증거가 아니다.
       그래서 **``EffectSpec`` 에서만 오는 이름**으로 다시 측정한다 —
       ``effect_types`` · ``cloned_from`` · ``count_limit`` · ``target_ranges``.
    """
    changed = _changed_files()
    assert not [path for path in changed if path.startswith("engine/")], sorted(changed)

    spec_only = ("effect_types", "cloned_from", "count_limit", "target_ranges")
    hits = []
    for directory in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in spec_only:
                    hits.append(f"{path.name}:{node.lineno}:{node.attr}")
    assert hits == [], hits

    #: 🔴 ``engine`` 이 블록을 **세기만** 한다 — 내용 칸이 view 에 없다.
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert "effect_count" in fields
    assert fields.isdisjoint(spec_only)


# ======================================================================
# G. 이 Phase 가 고친 것 자체 — 범위 · 원인 · downstream
# ======================================================================


def test_31_block_comments_are_stripped_before_counting():
    """
    🔴 §19-31 · §5 — ``--[[ … ]]`` 안의 효과는 **세지 않는다.**

    주석 안의 코드는 Lua 가 실행하지 않으므로 효과가 아니다. 세면 그만큼
    뒤쪽 ``ordinal`` 이 밀린다 (``c9409625``).
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        --[[ untested
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EFFECT_INDESTRUCTABLE_COUNT)
        c:RegisterEffect(e2)
        --]]
        local e3=Effect.CreateEffect(c)
        e3:SetCode(EVENT_TO_GRAVE)
        c:RegisterEffect(e3)
    """)
    assert shape(specs) == [
        ("e1", [], "EVENT_FREE_CHAIN"),
        ("e3", [], "EVENT_TO_GRAVE"),
    ]
    #: 🔴 ``e3`` 의 ``ordinal`` 이 1 이다 — 세었다면 2 로 밀렸다.
    assert [s.index for s in specs].index("e3") == 1

    #: 🔴 줄 주석은 **남긴다** — 헤더의 카드명을 그것으로 읽는다.
    info = parse_lua_source(0, "c0.lua", inspect.cleandoc("""
        --月朧龍ヴァグナワ
        --Vagnawa the Moon-Eating Dragon
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
    """))
    assert info.name_ja == "月朧龍ヴァグナワ"
    assert info.name_en == "Vagnawa the Moon-Eating Dragon"
    assert len(info.effects) == 1

    #: ``]]`` 로만 닫는 형태도 지운다.
    assert blocks_of("""
        --[[
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        ]]
        local e2=Effect.CreateEffect(c)
        c:RegisterEffect(e2)
    """) == blocks_of("""
        local e2=Effect.CreateEffect(c)
        c:RegisterEffect(e2)
    """)


def test_32_the_analyzer_and_the_loader_count_the_same_blocks(sources):
    """
    🔴 §19-32 · §4 · 판정 **C** — ``analysis`` 와 ``sources`` 가 **같은 수**를 센다.

    ``EffectAnalyzer._analyze_card`` 는 ``entries[position]`` 과
    ``card.script.effects[position]`` 을 **순번으로** 짝짓는다. 두 모듈의 블록
    탐지가 다르면 핸들러가 **다른 블록에** 붙는다.

    고치기 전에는 ``analysis`` 가 탐지 정규식을 **자기 모듈에 따로 복사해**
    갖고 있었고, 우연히 로더와 같아서 12,702 전부 일치했다. 로더만 고친
    순간 **3개가 어긋났다.** 그래서 로더에서 ``import`` 하도록 바꿨다.
    """
    mismatched = []
    for card_id, text in sources.items():
        loader = len(parse_lua_source(card_id, f"c{card_id}.lua", text).effects)
        analyzer = len(analyzer_blocks(text))
        if loader != analyzer:
            mismatched.append((card_id, loader, analyzer))
    assert mismatched == [], mismatched[:20]

    #: 🔴 ``analysis`` 가 탐지 정규식을 **다시 정의하지 않는다** — import 한다.
    analyzer_source = (PROJECT_ROOT / "analysis" / "effect_analyzer.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(analyzer_source)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_RE_CREATE_EFFECT" not in assigned
    assert "_RE_CLONE_EFFECT" not in assigned
    assert "_RE_BLOCK_COMMENT" not in assigned

    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "sources.lua_loader":
            imported.update(alias.name for alias in node.names)
    assert {"_RE_CREATE_EFFECT", "_RE_CLONE_EFFECT", "_RE_BLOCK_COMMENT",
            "_is_card_effect", "_extract_call_args"} <= imported, imported

    #: ``_RE_SETTER`` 는 **설정자 종류만** 좁다 — 변수명 범위는 로더와 같다.
    import analysis.effect_analyzer as analyzer_module
    assert analyzer_module._RE_SETTER.pattern.startswith(r"\b([A-Za-z_]\w*)")
    assert "Cost|Condition|Target|Operation" in analyzer_module._RE_SETTER.pattern


def test_33_the_corpus_diff_is_exactly_three_scripts(scripts, sources):
    """
    🔴 §19-33 · §12 — 바뀐 스크립트는 **정확히 3개**이고 다른 칸은 **0개**다.

    기대값을 "고치기 전 파서" 와 비교해서 얻지 않는다 (그 모듈은 커밋되면
    사라진다). 세 스크립트의 **최종 블록 목록을 글자 그대로 고정**하고
    (``test_16``), 여기서는 **총계와 다른 칸의 불변**을 본다.
    """
    assert len(scripts) == SCRIPTS
    blocks = sum(len(info.effects) for info in scripts.values())
    from_clone = sum(
        1 for info in scripts.values() for s in info.effects if s.cloned_from
    )
    assert blocks == BLOCKS
    assert blocks - from_clone == BLOCKS_FROM_CREATE
    assert from_clone == BLOCKS_FROM_CLONE
    #: 수정 전보다 **정확히 하나** 많다 (+2 −1).
    assert blocks == BLOCKS_BEFORE + 1

    #: 🔴 세 스크립트 말고는 블록 수가 그대로다 — 다른 칸은 **원문 전체**에서
    #: 긁으므로 블록 주석 제거에 영향받지 않는다는 것도 함께 본다.
    changed = {NON_LOCAL_CARD_EFFECT, NON_E_NAME_CARD_EFFECT, COMMENTED_BLOCK}
    for card_id in changed:
        text = sources[card_id]
        info = scripts[card_id]
        #: ``trigger_events`` 는 **원문**에서 긁는다 — 주석 안의 코드도 남는다.
        assert "EVENT_SPSUMMON_SUCCESS" in text or card_id != NON_LOCAL_CARD_EFFECT
        assert info.trigger_events == parse_card(card_id).trigger_events

    #: ``c9409625`` 의 주석 안 코드가 **파일 단위 목록에는 남아 있다** —
    #: 그 칸들은 이 Phase 의 범위가 아니므로 일부러 ``source`` 를 쓴다.
    commented = scripts[COMMENTED_BLOCK]
    assert "EFFECT_INDESTRUCTABLE_COUNT" in commented.effect_codes
    assert "EFFECT_INDESTRUCTABLE_COUNT" not in [s.code for s in commented.effects]
    #: 그 사실을 production 주석이 **명시**한다.
    loader_source = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(
        encoding="utf-8"
    )
    tail = loader_source.split("--- 파일 전체 단위 수집", 1)[1]
    assert "``source``" in tail
    assert "범위" in tail


def test_34_every_skipped_site_is_a_duel_global_or_another_cards_effect(sources):
    """
    🔴 §19-34 · §6 · §7 — 파서가 **세지 않는 249곳 전부**를 분류한다.

    §6 은 각 분류의 사례를 10개 이상 요구한다. 🔴 실제 모집단이 그보다 작은
    분류가 있으므로 **없는 사례를 만들지 않고 실제 수를 적는다.**

    * **A/B** ``local`` 없음 + 정상 인식 + ordinal 정상 — ``1`` (``c9839115``).
      ``local`` 은 있고 이름이 ``e`` 가 아닌 것까지 합치면 ``2``.
    * **C** 놓침 — 고치기 **전** ``2``, 고친 **후** ``0``.
    * **D** 발견되지만 ordinal 이 틀림 — ``0`` (``test_11`` · ``test_16``).
    * **E** 기존 effect 와 잘못 연결 — 고치기 **전** ``1`` (``c9839115`` 의
      ``code`` 흘림), 고친 **후** ``0``.
    * **F** 이후 setter/Clone 추적 실패 — ``0`` (``test_13`` 의 1건은 ``local``
      이 아니라 보조 함수가 원인이다).
    * **G** Lua semantics 상 특별 — ``249`` (전역 ``245`` · 다른 카드 ``4``).
      **이 분류가 모집단의 전부다.**
    * **H** false positive — 3-F-27 의 "217곳" 추정. 실제로는 ``local`` 이 없는
      자리가 ``3`` 곳이고 나머지는 변수명 문제였다 (``test_15``).
    """
    create_site = re.compile(r"Effect\.(?:CreateEffect|GlobalEffect)\s*\(")
    duel_global = create_other = counted = 0
    skipped_create = skipped_clone = 0
    sites = assigned = 0
    scripts_with_skips: set[int] = set()

    for card_id, text in sources.items():
        body = lua_loader._RE_BLOCK_COMMENT.sub("", text)
        sites += len(create_site.findall(body))
        matches = list(lua_loader._RE_CREATE_EFFECT.finditer(body))
        assigned += len(matches)
        for kind, match in (
            [("create", m) for m in matches]
            + [("clone", m) for m in lua_loader._RE_CLONE_EFFECT.finditer(body)]
        ):
            parent = match.group(3) if kind == "clone" else None
            if kind == "clone" and not (
                parent.startswith("e")
                or any(m.group(2) == parent for m in matches)
            ):
                continue                      # Group 의 Clone — effect 가 아니다
            if lua_loader._is_card_effect(body, match.group(1), match.group(2), parent):
                if not (match.group(1) and match.group(2).startswith("e")
                        and (parent is None or parent.startswith("e"))):
                    counted += 1              # 보강으로 새로 센 자리
                continue
            scripts_with_skips.add(card_id)
            if kind == "create":
                skipped_create += 1
            else:
                skipped_clone += 1
            variable = re.escape(match.group(2))
            if re.search(r"Duel\.RegisterEffect\s*\(\s*" + variable + r"\b", body):
                duel_global += 1
            elif re.search(
                r"(?<![\w.])(?!c\s*:)\w+\s*:\s*RegisterEffect\s*\(\s*" + variable + r"\b",
                body,
            ):
                create_other += 1

    #: 🔴 모든 ``CreateEffect`` 자리가 변수에 배정된다 — 배정 없는 자리 0곳.
    assert sites == assigned == CREATE_SITES

    #: 🔴 세지 않는 249곳의 **전부**가 전역이거나 다른 카드의 효과다 (G).
    assert skipped_create == SKIPPED_CREATE
    assert skipped_clone == SKIPPED_CLONE
    assert duel_global == SKIPPED_DUEL_GLOBAL
    assert create_other == SKIPPED_OTHER_CARD
    assert duel_global + create_other == skipped_create + skipped_clone
    assert len(scripts_with_skips) == SKIPPED_SCRIPTS

    #: 🔴 보강으로 새로 센 자리는 **둘**뿐이다 (A/B).
    assert counted == 2

    #: 그 둘이 어느 카드인지도 고정한다.
    assert len(parse_card(NON_LOCAL_CARD_EFFECT).effects) == 3
    assert len(parse_card(NON_E_NAME_CARD_EFFECT).effects) == 5
    #: ``local`` 이 없지만 **다른 카드**에 주는 것은 여전히 세지 않는다 (G).
    other = parse_card(NON_LOCAL_OTHER_CARD)
    assert "e3=Effect.CreateEffect" in script_text(NON_LOCAL_OTHER_CARD)
    assert "e3" not in [s.index for s in other.effects]


def test_35_the_local_convention_was_not_abandoned():
    """
    🔴 §19-35 · §6 — ``local`` + ``e*`` 관례를 **버리지 않았다.**

    버렸다면 전역 효과 245건과 다른 카드에 주는 효과 4건을 세어 ``ordinal`` 이
    **249곳에서 틀어졌을 것**이다. ``_is_card_effect`` 는 그 관례를 **먼저**
    보고, 통과하지 못한 자리에서만 ``c:RegisterEffect`` 를 본다.
    """
    body = inspect.getsource(lua_loader._is_card_effect)
    assert 'if local and var.startswith("e")' in body
    assert "_registers_on_card(source, var)" in body

    #: 🔴 순서가 중요하다 — 관례가 **먼저** 돌아야 한다.
    #: ``inspect.cleandoc`` 이 아니라 ``textwrap.dedent`` 다 — cleandoc 은
    #: 첫 줄(``def`` 줄)의 들여쓰기를 따로 처리해서 본문만 들여쓰게 만든다.
    tree = ast.parse(textwrap.dedent(body))
    function = tree.body[0]
    statements = [node for node in function.body if not isinstance(node, ast.Expr)]
    assert isinstance(statements[0], ast.If)
    assert isinstance(statements[-1], ast.Return)

    #: ``c:RegisterEffect`` 판정은 ``c`` **그 자신**만 받는다 — ``tc`` 는 아니다.
    assert lua_loader._registers_on_card("c:RegisterEffect(e1)", "e1") is True
    assert lua_loader._registers_on_card("tc:RegisterEffect(e1)", "e1") is False
    assert lua_loader._registers_on_card("token:RegisterEffect(e1)", "e1") is False
    assert lua_loader._registers_on_card("Duel.RegisterEffect(e1,tp)", "e1") is False
    assert lua_loader._registers_on_card("sc:RegisterEffect(e1)", "e1") is False
    #: 접두사가 겹치는 변수에 속지 않는다.
    assert lua_loader._registers_on_card("c:RegisterEffect(e11)", "e1") is False


def test_36_the_production_change_is_confined_to_the_parser_and_the_analyzer():
    """
    🔴 §19-36 · §16~18 — production diff 가 **두 파일**뿐이다.

    새 abstraction · 새 enum · 새 public field 는 없다.
    """
    changed = _changed_files()
    production = {
        path
        for path in changed
        if not path.startswith(("tests/", "docs/")) and path.endswith(".py")
    }
    assert production == {"sources/lua_loader.py", "analysis/effect_analyzer.py"}, production

    #: ``EffectSpec`` · ``EffectDefinition`` 의 칸이 그대로다.
    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]
    assert len(dataclasses.fields(EffectDefinition)) == 10
    assert "code" not in {f.name for f in dataclasses.fields(EffectDefinition)}

    #: ``LuaScriptInfo`` 의 칸도 그대로다.
    assert "effects" in {f.name for f in dataclasses.fields(LuaScriptInfo)}

    #: 🔴 새로 생긴 production 이름은 **둘**뿐이고 둘 다 private 이다.
    tree = ast.parse((PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8"))
    public = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")
    ]
    assert public == ["parse_lua_source", "LuaScriptSource"], public
    assert "_is_card_effect" in [
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    ]
    #: 새 enum 이 없다.
    assert not [
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Name) and base.id.endswith("Enum") for base in node.bases
        )
    ]


def _changed_files() -> set[str]:
    """
    이 Phase 의 worktree/commit diff 에 등장하는 파일.

    🔴 ``HEAD`` 가 아니라 **이 파일을 추가한 commit 의 부모**를 기준으로 잡는다.
    ``HEAD`` 로 잡으면 **다음 Phase 가 production 을 건드릴 때 이 테스트가
    엉뚱하게 깨진다** (3-F-25 의 ``test_30`` 이 3-F-26 에서 그렇게 깨졌다).
    아직 commit 되지 않았으면 worktree diff 를 쓴다.
    """
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        ).stdout

    added = run("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    if added:
        base = added[-1] + "~1"
        head = added[-1]
        #: 이 Phase 는 작업/테스트/보고서를 나눠 커밋하므로 **추가 commit 까지**
        #: 가 아니라 그 commit 을 포함한 범위를 본다.
        out = run("diff", "--name-only", base, head)
        out += run("diff", "--name-only", head)
    else:
        out = run("diff", "--name-only", "HEAD")
        out += run("diff", "--name-only", "--cached", "HEAD")
    return {line for line in out.splitlines() if line}
