"""
Phase 3-F-27 — Lua ``SetType`` + ``Clone`` 의 **effect 별 독립 상태** 감사 및 수정.

판정: **B. CONFIRMED_PARSER_ACCUMULATION_BUG**

🔴 aliasing 은 **없었다** — A 가 아니다
---------------------------------------
``Clone`` 분기는 ``spec.effect_types = list(parent.effect_types)`` 로 **새 리스트를
만든다.** 재현하면 ``id(e1.effect_types) != id(e2.effect_types)`` 이고, 자식의
``SetType`` 이 부모를 바꾸지도 않는다 (``test_05`` · ``test_20``). 공유된 가변
컨테이너는 없다.

문제는 ``"Type"`` 설정자가 **더하기**였다는 것이다::

    spec.effect_types = _strip_prefix(spec.effect_types + _RE_EFFECT_TYPE.findall(args))

그래서 ``Clone`` 이 물려준 목록 위에 자식이 분명히 다시 적은 type 이 **얹혔다.**
``Clone`` 이 없어도 같은 변수에 ``SetType`` 을 두 번 부르면 재현된다 —
즉 **Clone 오염이 아니라 설정자 누적**이다 (``test_09``).

🔴 교체가 맞다는 근거 — **저장소 내부 증거만** 쓴다
----------------------------------------------------
EDOPro ``SetType`` API 의 정확한 의미는 이 저장소에 문서화돼 있지 않다. 그래서
Lua 의미를 추측하지 않고 corpus 로만 판단했다.

1. **누적은 상호배타 조합을 만든다.** ``Clone`` 뒤 자기 ``SetType`` 이 있는
   77블록 중 **76블록**이 적용 범위(``SINGLE``/``FIELD``/``EQUIP``)를 둘 이상
   갖거나 발동 분류(``ACTIVATE``/``IGNITION``/``TRIGGER_O``/``QUICK_O``/
   ``TRIGGER_F``/``QUICK_F``/``CONTINUOUS``)를 둘 이상 갖게 된다
   (각 25 · 51 — ``test_12``).
2. **그 조합은 카드가 쓰지 않는다.** 한 ``SetType`` 호출 안에서 그런 조합을
   적는 호출은 **31,933건 중 0건**이다 (``test_13``).
3. **유지하려는 스크립트는 다시 적는다.** 77건 중 부모 플래그를 유지한 유일한
   블록(``c4928565`` ``e4``)이 ``SINGLE+TRIGGER_O`` 를 **그대로 다시 적는다**.
   더하기라면 다시 적을 이유가 없다 (``test_14``).
4. **같은 위험을 ``code`` 는 이미 고쳐 놓았다.** ``"Code"`` 분기에 Phase 3-E-18
   의 수정이 주석까지 달려 있고, 그 주석이 *"물려받은 값이 남은 채 스크립트가
   분명히 덮어쓴 코드를 계속 주장하게 된다"* 라고 적는다 (``test_15``).

수정 (최소)
-----------
``sources/lua_loader.py`` **한 곳**뿐이다.

* ``parse_lua_source`` 가 변수명 -> "이 블록의 ``effect_types`` 가 ``Clone`` 이
  물려준 것인가" 를 따라가고, **첫 ``SetType`` 이 물려받은 목록을 덮어쓴다.**
  두 번째 이후는 기존대로 더한다 (``test_10``).
* ``LuaScriptSource._signature`` 를 ``v4`` → ``v5`` 로 올렸다. 🔴 그 값에 파서
  버전이 없으면 **고친 파서가 옛 캐시를 계속 읽는다** — 스크립트 파일이 바뀌지
  않으면 signature 가 같기 때문이다. 실제로 고치기 전 캐시는 ``c324483`` ``e2``
  를 ``['IGNITION', 'QUICK_O']`` 로 들고 있었다 (``test_22``).

새 추상화 · 새 enum · 새 public field 는 없다. ``EffectSpec`` 의 칸도,
``EffectDefinition`` 도, engine 도 바뀌지 않았다.

수정 범위 밖 — **고치지 않고 적어 둔다**
-----------------------------------------
* 형제 칸(``categories`` 24 · ``properties`` 19 · ``target_ranges`` 9 ·
  ``ranges`` 12)에 **같은 유형**이 남아 있다 (``test_29``).
* ``local`` 없는 ``e1=Effect.CreateEffect(c)`` 가 **217곳 / 195파일** 있고, 파서가
  그것을 새 블록으로 보지 않아 **설정자가 이전 바인딩으로 흘러든다**. 이것이
  corpus 전체에서 교체 규칙과 production 이 아직 다른 **단 1블록**의 원인이고
  (``c9839115``), ``Clone`` 과 **다른 원인**이다 (``test_11`` · ``test_28``).

3-F-26 의 판정은 유지된다
-------------------------
``QUICK_O`` 블록 수(1,875)와 스크립트 수(1,712)는 **고치기 전과 같다** — 더하기만
했으므로 ``QUICK_O`` 가 추가되거나 사라진 블록은 **0건**이다 (``test_23``). 그래서
3-F-26 의 ``C. DATA_CLASSIFICATION_ONLY`` 와 3-F-25 의
``EVENT_FREE_CHAIN = C. LUA_INTERNAL_TAG`` 는 그대로다. 이 Phase 는 **의미를 새로
부여하지 않았다** (``test_25``).
"""

import ast
import collections
import dataclasses
import hashlib
import inspect
import json
import pathlib
import subprocess
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from core.card_model import EffectSpec
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.game_state_view import CardDefinitionView
import sources.lua_loader as lua_loader
from sources.lua_loader import LuaScriptSource, parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
    "engine",
    "agent",
    "app",
    "core",
    "analysis",
    "rules",
    "rulings",
    "sources",
    "scripts",
)
MYSELF = "tests/test_settype_clone_contamination_audit.py"

#: 적용 범위 축 — 한 블록에 둘 이상 올 수 없다 (corpus 전수).
SCOPE_FLAGS = frozenset({"SINGLE", "FIELD", "EQUIP"})
#: 발동 분류 축 — 한 블록에 둘 이상 올 수 없다 (``FLIP`` 은 예외라 제외).
ACTIVATION_FLAGS = frozenset(
    {"ACTIVATE", "IGNITION", "TRIGGER_O", "QUICK_O", "TRIGGER_F", "QUICK_F", "CONTINUOUS"}
)

#: 측정으로 확인한 실제 카드.
CLONE_IGNITION_TO_QUICK = 324483     # e1=IGNITION → Clone → e2=QUICK_O
CLONE_ACTIVATE_TO_QUICK = 6351147    # e1=ACTIVATE → Clone → e2=QUICK_O
CLONE_SCOPE_SWAP = 13708888          # SINGLE+TRIGGER_O → Clone → FIELD+TRIGGER_O
CLONE_SCOPE_SWAP2 = 20003027         # FIELD+TRIGGER_O → Clone → SINGLE+TRIGGER_O
CLONE_RESTATES_PARENT = 4928565      # 부모 플래그를 자식이 그대로 다시 적는다
CLONE_NO_SETTYPE = 39015             # Clone 후 자기 SetType 없음 (정상 상속)
NON_LOCAL_CREATE = 9839115           # 🔴 local 없는 CreateEffect (별개 버그)
FLIP_CARD = 759393                   # 화령사 히타 — SINGLE+FLIP
TRIGGER_F_CLONE = 102380             # Clone 상속 사례
MULTI_TYPE_ONE_CALL = 176392         # 한 호출 OR: CONTINUOUS+FIELD / FIELD+TRIGGER_O

#: 형제 칸의 corpus 총계 — 이 Phase 가 건드리지 않았다는 증거 (``test_34``).
#:
#: 🔴 Phase 3-F-28 이 블록 수를 34,680 → 34,681 로 바꾸면서
#: (``c9409625`` 가 블록 주석 안의 블록 하나를 잃고 −1, ``c9839115`` ·
#: ``c74506079`` 가 ``c:RegisterEffect`` 로 등록되는 블록 하나씩을 얻어 +2)
#: 블록에 **딸린** 총계도 그만큼 움직였다. 전수 비교로 확인한 내역:
#:
#: * ``ranges`` 15,076 → 15,075 — 사라진 ``c9409625`` 블록의 ``SZONE`` 1건.
#: * ``properties`` 23,909 → 23,907 — 같은 블록의 ``SINGLE_RANGE`` ·
#:   ``NO_TURN_RESET`` 2건.
#: * ``count_limit`` 11,188 → 11,187 — 같은 블록의 ``1`` 1건.
#: * ``code`` 30,126 → 30,127 — 그 블록의 ``EFFECT_INDESTRUCTABLE_COUNT``
#:   −1, 새 블록 둘의 ``EFFECT_SET_ATTACK`` · ``EFFECT_UPDATE_ATTACK`` +2.
#: * ``target_ranges`` · ``categories`` · ``cloned_from`` 은 **그대로다.**
#:
#: 🔴 **Phase 3-F-29 가 네 칸을 고쳤다.** ``Clone`` 이 물려준 값을 자식의 첫
#: 설정자가 덮어쓰도록 바꾸면서, 더하기가 남겨 놓았던 부모의 플래그가
#: 사라졌다 (59 스크립트 / 75 블록-칸 쌍).
#:
#: * ``ranges`` 15,075 → 15,063 (−12)
#: * ``target_ranges`` 2,072 → 2,062 (−10)
#: * ``categories`` 20,534 → 20,505 (−29)
#: * ``properties`` 23,907 → 23,884 (−23)
#: * ``code`` · ``count_limit`` · ``cloned_from`` 은 **그대로다** — 3-F-29 는
#:   목록 칸만 건드렸다.
#:
#: 🔴 이 테스트는 3-F-27 이 "범위 밖" 으로 **세어 두기만 한** 결함이고,
#: ``test_29`` 가 그 수(64)를 다음 Phase 후보의 근거로 고정해 두었다.
#: 3-F-29 가 그것을 고쳤으므로 숫자가 움직이는 것이 **설계된 신호**다.
RANGES_TOTAL = 15063
TARGET_RANGES_TOTAL = 2062
CATEGORIES_TOTAL = 20505
PROPERTIES_TOTAL = 23884
CODE_TOTAL = 30127
COUNT_LIMIT_TOTAL = 11187

LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522
GENEROUS_REWARD = 5915629
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4


# ======================================================================
# 측정 도구
# ======================================================================


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))
    yield from sorted(PROJECT_ROOT.glob("*.py"))


class _StripStrings(ast.NodeTransformer):
    def visit_Constant(self, node):  # noqa: N802 - ast 규약
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=""), node)
        return node


def code_only(source: str) -> str:
    return ast.unparse(_StripStrings().visit(ast.parse(source)))


def code_of(func) -> str:
    return ast.unparse(
        _StripStrings().visit(ast.parse(textwrap.dedent(inspect.getsource(func))))
    )


def lua(body: str) -> str:
    """``initial_effect`` 한 덩어리로 감싼 최소 Lua."""
    return "function s.initial_effect(c)\n" + textwrap.dedent(body) + "\nend\n"


def parse(body: str, card_id: int = 1):
    return parse_lua_source(card_id, f"c{card_id}.lua", lua(body))


def types_of(body: str) -> list[tuple[str, list[str]]]:
    return [(s.index, s.effect_types) for s in parse(body).effects]


def script_source(card_id: int) -> str:
    return (PROJECT_ROOT / f"c{card_id}.lua").read_text(encoding="utf-8", errors="replace")


def spec_map(card_id: int) -> dict[str, list]:
    """한 스크립트의 블록을 index 순서대로. index 는 고유하지 않으므로 리스트로."""
    out: dict[str, list] = collections.defaultdict(list)
    for spec in parse_lua_source(card_id, f"c{card_id}.lua", script_source(card_id)).effects:
        out[spec.index].append(spec)
    return out


def walk_replace_rule(source: str) -> list[dict]:
    """
    ``SetType`` 을 **항상 교체**로 처리하는 독립 구현.

    production 과 비교하는 **외부 기준**이다. production 을 호출하지 않으므로
    같은 버그를 같이 갖지 않는다.

    🔴 Phase 3-F-28 정정 — 이 함수도 production 정규식을 **그룹 번호로** 읽고
    있었다. 3-F-28 이 ``local`` 포획 그룹을 추가해 번호가 밀렸으므로 맞추고,
    production 과 같은 흐름이 되도록 블록 주석 제거와 ``_is_card_effect``
    판정을 함께 반영한다.
    """
    events: list[tuple[int, str, str]] = []
    source = lua_loader._RE_BLOCK_COMMENT.sub("", source)
    for match in lua_loader._RE_CREATE_EFFECT.finditer(source):
        if not lua_loader._is_card_effect(source, match.group(1), match.group(2), None):
            continue
        events.append((match.start(), "create", match.group(2)))
    for match in lua_loader._RE_CLONE_EFFECT.finditer(source):
        if not lua_loader._is_card_effect(
            source, match.group(1), match.group(2), match.group(3)
        ):
            continue
        events.append((match.start(), "clone", f"{match.group(2)}={match.group(3)}"))
    for match in lua_loader._RE_SETTER.finditer(source):
        events.append(
            (match.start(), "set", f"{match.group(1)}|{match.group(2)}|{match.end() - 1}")
        )
    events.sort(key=lambda item: item[0])

    bindings: dict[str, dict] = {}
    out: list[dict] = []
    for _position, kind, payload in events:
        if kind == "create":
            current = {"index": payload, "types": [], "cloned_from": None, "calls": []}
            bindings[payload] = current
            out.append(current)
        elif kind == "clone":
            destination, origin = payload.split("=", 1)
            parent = bindings.get(origin)
            current = {
                "index": destination,
                "types": list(parent["types"]) if parent else [],
                "cloned_from": origin,
                "calls": [],
            }
            bindings[destination] = current
            out.append(current)
        else:
            variable, setter, index = payload.split("|", 2)
            current = bindings.get(variable)
            if current is None:
                continue
            if setter == "Type":
                arguments = lua_loader._extract_call_args(source, int(index))
                flags = lua_loader._strip_prefix(
                    lua_loader._RE_EFFECT_TYPE.findall(arguments)
                )
                current["calls"].append(flags)
                current["types"] = flags
    return out


def contradictory(flags) -> bool:
    chosen = set(flags)
    return len(chosen & SCOPE_FLAGS) > 1 or len(chosen & ACTIVATION_FLAGS) > 1


@pytest.fixture(scope="module")
def corpus():
    """(card_id, source, production blocks, 교체 규칙 blocks) 전수."""
    source = LuaScriptSource(PROJECT_ROOT)
    rows = []
    for card_id, path in source.iter_script_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append(
            (
                card_id,
                text,
                parse_lua_source(card_id, path.name, text).effects,
                walk_replace_rule(text),
            )
        )
    return rows


def opened_duel(repository, *, seed: int) -> Duel:
    duel = Duel.start(
        repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


# ======================================================================
# A. §2 — 최소 사례 재현
# ======================================================================


def test_01_plain_settype():
    """🟢 §16-1 — 기본 ``SetType``."""
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
    """) == [("e1", ["IGNITION"])]


def test_02_clone_without_settype_inherits():
    """🟢 §16-2 — ``Clone`` 만 하면 부모 type 을 **그대로 물려받는다.**"""
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
    """) == [("e1", ["IGNITION"]), ("e2", ["IGNITION"])]


def test_03_clone_then_settype_replaces():
    """
    🔴 §16-3 — **핵심 사례.** ``Clone`` 뒤 ``SetType`` 은 물려받은 목록을
    **덮어쓴다.**

    고치기 전에는 ``e2`` 가 ``['IGNITION', 'QUICK_O']`` 였다.
    """
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
    """) == [("e1", ["IGNITION"]), ("e2", ["QUICK_O"])]


def test_04_clone_type_isolation():
    """🔴 §16-4 — 두 자식이 서로의 type 을 보지 않는다."""
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        local e3=e1:Clone()
        e3:SetType(EFFECT_TYPE_TRIGGER_F)
    """) == [
        ("e1", ["IGNITION"]),
        ("e2", ["QUICK_O"]),
        ("e3", ["TRIGGER_F"]),
    ]


def test_05_the_parent_is_never_modified():
    """
    🔴 §16-5 · **Invariant 1** — 자식의 type 변경이 **부모를 바꾸지 않는다.**

    그리고 가변 컨테이너가 **공유되지 않는다** — ``id()`` 로 직접 본다.
    """
    info = parse("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
    """)
    first, second = info.effects
    assert first.effect_types == ["IGNITION"]
    assert second.effect_types == ["QUICK_O"]

    #: 🔴 aliasing 이 아니다 — 서로 다른 리스트 객체다.
    assert id(first.effect_types) != id(second.effect_types)
    assert first.effect_types is not second.effect_types

    #: 사후에 하나를 건드려도 다른 쪽이 따라오지 않는다.
    second.effect_types.append("SENTINEL")
    assert "SENTINEL" not in first.effect_types

    #: 🔴 ``SetType`` 이 **없는** Clone 쌍도 컨테이너를 공유하지 않는다.
    #:
    #: .. warning::
    #:    위의 Clone + SetType 쌍만 보면 **공유를 놓친다** — 교체가 새 리스트를
    #:    돌려주므로 공유가 그 자리에서 끊긴다. 주입으로 확인했다
    #:    (``spec.effect_types = parent.effect_types`` 로 바꿔도 위 단정은
    #:    통과했고 ``test_20`` 만 잡았다). 공유가 드러나는 자리는 **상속만 하는
    #:    쌍**이다.
    plain = parse("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
    """)
    parent, child = plain.effects
    assert parent.effect_types == child.effect_types == ["IGNITION"]
    assert parent.effect_types is not child.effect_types
    child.effect_types.append("SENTINEL")
    assert "SENTINEL" not in parent.effect_types


def test_06_two_stage_clone():
    """🟢 §16-6 — 2단 ``Clone``."""
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_FIELD)
    """) == [("e1", ["SINGLE"]), ("e2", ["FIELD"])]


def test_07_three_stage_clone():
    """
    🔴 §16-7 — 3단 ``Clone``. 고치기 전에는
    ``['IGNITION', 'QUICK_O', 'TRIGGER_F']`` — **상호배타 분류 셋**이 한 블록에
    들어갔다.
    """
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        local e3=e2:Clone()
        e3:SetType(EFFECT_TYPE_TRIGGER_F)
    """) == [
        ("e1", ["IGNITION"]),
        ("e2", ["QUICK_O"]),
        ("e3", ["TRIGGER_F"]),
    ]


def test_08_one_call_with_or_is_preserved():
    """🟢 §16-8 · **Invariant 3** — 한 호출 안의 OR 는 **보존된다.**"""
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O)
    """) == [("e1", ["FIELD", "TRIGGER_O"])]

    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_CONTINUOUS)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_CONTINUOUS)
    """) == [("e1", ["SINGLE", "CONTINUOUS"]), ("e2", ["FIELD", "CONTINUOUS"])]


def test_09_repeated_settype_without_clone_still_accumulates():
    """
    🔴 §16-9 — ``Clone`` 이 **없으면** 기존 동작(더하기)을 **그대로 둔다.**

    이것이 "Clone 오염" 과 "설정자 누적" 을 가르는 자리다. 고친 것은 **물려받은
    목록을 첫 ``SetType`` 이 덮어쓰는 것**뿐이고, 같은 변수에 두 번 부르는 경우의
    의미는 이 Phase 가 정하지 않았다 (corpus 에 1건뿐이고 그 1건은 다른 원인이다
    — ``test_11``).
    """
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        e1:SetType(EFFECT_TYPE_QUICK_O)
    """) == [("e1", ["IGNITION", "QUICK_O"])]


def test_10_second_settype_after_clone_accumulates():
    """
    🟢 §16-9 — ``Clone`` 뒤 ``SetType`` 이 **두 번**이면 첫 번째만 덮어쓰고
    두 번째는 더한다. 최소 수정의 범위를 정확히 못 박는다.
    """
    assert types_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        e2:SetType(EFFECT_TYPE_FIELD)
    """) == [("e1", ["IGNITION"]), ("e2", ["QUICK_O", "FIELD"])]


def test_11_a_create_without_local_is_not_seen():
    """
    🔴 §6-D · 범위 밖 — ``local`` 없는 ``CreateEffect`` 는 **새 블록으로 보이지
    않고**, 그 뒤 설정자가 **이전 바인딩으로 흘러든다.**

    ``Clone`` 과 **다른 원인**이고 3-F-27 이 고치지 않았다.
    """
    info = parse("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
        e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_FIELD)
    """)
    #: 블록이 **하나**다 — 두 번째 CreateEffect 를 못 봤다.
    assert len(info.effects) == 1
    #: 그래서 두 번째 SetType 이 첫 블록에 더해졌다.
    assert info.effects[0].effect_types == ["SINGLE", "TRIGGER_O", "FIELD"]
    #: 🔴 그 결과는 적용 범위가 둘인 **모순 조합**이다.
    assert contradictory(info.effects[0].effect_types)

    #: 정규식이 ``local`` 을 요구한다 — 원인이 여기다.
    assert "local" in lua_loader._RE_CREATE_EFFECT.pattern


# ======================================================================
# B. §6 · §7 — 교체가 맞다는 corpus 근거
# ======================================================================


def test_12_accumulation_would_create_contradictions(corpus):
    """
    🔴 §6 — ``Clone`` 뒤 자기 ``SetType`` 이 있는 **77블록** 가운데 **76블록**이
    더하기였다면 **상호배타 조합**이 됐다 (적용 범위 25 · 발동 분류 51).
    """
    clone_with_settype = 0
    bad_scope = 0
    bad_activation = 0
    clean = 0
    for _card_id, _text, _production, replaced in corpus:
        parents: dict[str, list[str]] = {}
        for block in replaced:
            if block["cloned_from"] is not None and block["calls"]:
                clone_with_settype += 1
                inherited = parents.get(block["cloned_from"], [])
                merged = set(inherited) | set(block["calls"][0])
                scope = len(merged & SCOPE_FLAGS)
                activation = len(merged & ACTIVATION_FLAGS)
                if scope > 1:
                    bad_scope += 1
                if activation > 1:
                    bad_activation += 1
                if scope <= 1 and activation <= 1:
                    clean += 1
            parents[block["index"]] = list(block["types"])

    assert clone_with_settype == 77
    assert bad_scope == 25
    assert bad_activation == 51
    assert bad_scope + bad_activation == 76
    assert clean == 1


def test_13_no_single_call_ever_writes_such_a_combination(corpus):
    r"""
    🔴 §6 — 그 조합을 **한 ``SetType`` 호출 안에서 적는 카드는 0장**이다.

    32,153건 전수. 이것이 교체가 맞다는 가장 강한 내부 증거다.

    .. note::
       🔴 Phase 3-F-28 에서 31,933 → 32,153 (+220). 이 테스트는 production
       의 ``_RE_SETTER`` 를 그대로 쓰는데, 3-F-28 이 그 변수명 범위를
       ``e\w*`` 에서 ``[A-Za-z_]\w*`` 로 넓혔다. 늘어난 220건은 ``ge1`` ·
       ``g`` · ``ae`` 같은 이름의 ``SetType`` 호출이다 — **위반 수는 둘 다
       0 으로 그대로다.** 즉 넓힌 범위에서도 모순 조합을 한 호출에 적는
       카드는 없다. 판정이 약해진 것이 아니라 표본이 커졌다.
    """
    calls = 0
    scope_violations = 0
    activation_violations = 0
    for _card_id, text, _production, _replaced in corpus:
        for match in lua_loader._RE_SETTER.finditer(text):
            if match.group(2) != "Type":
                continue
            calls += 1
            flags = set(
                lua_loader._strip_prefix(
                    lua_loader._RE_EFFECT_TYPE.findall(
                        lua_loader._extract_call_args(text, match.end() - 1)
                    )
                )
            )
            if len(flags & SCOPE_FLAGS) > 1:
                scope_violations += 1
            if len(flags & ACTIVATION_FLAGS) > 1:
                activation_violations += 1

    assert calls == 32153
    assert scope_violations == 0
    assert activation_violations == 0


def test_14_the_only_script_that_keeps_parent_flags_restates_them():
    """
    🔴 §6 — 부모 플래그를 **유지하는** 유일한 블록이 그것을 **다시 적는다.**

    더하기였다면 다시 적을 이유가 없다. ``c4928565`` ``e4`` ← ``e2``.
    """
    text = script_source(CLONE_RESTATES_PARENT)
    blocks = {b["index"]: b for b in walk_replace_rule(text)}
    assert "e4" in blocks
    assert blocks["e4"]["cloned_from"] == "e2"
    #: 자식이 부모와 **같은** 플래그를 스스로 적는다.
    assert blocks["e4"]["calls"] == [["SINGLE", "TRIGGER_O"]]
    assert blocks["e2"]["types"] == ["SINGLE", "TRIGGER_O"]

    #: 그래서 교체해도 **잃는 것이 없다.**
    produced = spec_map(CLONE_RESTATES_PARENT)["e4"]
    assert [p.effect_types for p in produced] == [["SINGLE", "TRIGGER_O"]]


def test_15_the_code_field_already_had_this_fix():
    """
    🔴 §6 · §10 — 같은 위험을 ``code`` 는 Phase 3-E-18 이 **이미 고쳤다.**

    그 주석이 이 Phase 의 근거를 그대로 적고 있다.
    """
    source = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8")
    assert "Phase 3-E-18" in source
    assert "앞 값을 그대로 두면 안 된다" in source
    assert "계속 주장하게 된다" in source

    #: 그리고 이 Phase 의 수정이 같은 자리에 같은 이유로 들어갔다.
    assert "Phase 3-F-27" in source
    assert "Clone 이 물려준 목록을 그대로 두면 안 된다" in source


# ======================================================================
# C. §12 · §19 — 실제 카드와 corpus diff
# ======================================================================


@pytest.mark.parametrize(
    "card_id, index, expected",
    [
        (CLONE_IGNITION_TO_QUICK, "e2", ["QUICK_O"]),
        (CLONE_ACTIVATE_TO_QUICK, "e2", ["QUICK_O"]),
        (CLONE_SCOPE_SWAP, "e2", ["FIELD", "TRIGGER_O"]),
        (CLONE_SCOPE_SWAP2, "e3", ["SINGLE", "TRIGGER_O"]),
        (CLONE_RESTATES_PARENT, "e4", ["SINGLE", "TRIGGER_O"]),
    ],
)
def test_16_real_clone_cards_are_clean(card_id, index, expected):
    """
    🔴 §12 — 실제 카드 5장. ``Clone`` 뒤 ``SetType`` 이 **자기 type 만** 갖는다.

    고치기 전에는 전부 부모 플래그가 섞여 있었다.
    """
    produced = spec_map(card_id)[index]
    assert len(produced) == 1, [p.effect_types for p in produced]
    assert produced[0].effect_types == expected
    assert produced[0].cloned_from is not None
    #: 🔴 모순 조합이 아니다.
    assert not contradictory(produced[0].effect_types)


def test_17_real_inheritance_cards_are_untouched(corpus):
    """
    🟢 §12 · **Invariant 7** — ``Clone`` 후 자기 ``SetType`` 이 **없으면** 물려받은
    type 이 그대로 남는다. corpus 전체(2,667블록)로 센다.

    .. warning::
       🔴 처음에는 ``next(b for b in blocks if b.index == block.cloned_from)`` 로
       부모를 찾았다. **``index`` 는 스크립트 안에서 고유하지 않다** (3-F-25 가
       측정했다 — 4,795 스크립트 / 6,802 중복). 그래서 엉뚱한 블록을 부모로
       집었다. 부모를 정확히 아는 것은 바인딩을 따라가는 ``walk_replace_rule``
       뿐이므로 그것과 대조한다.
    """
    inherited_only = 0
    for card_id, _text, production, replaced in corpus:
        for spec, fixed in zip(production, replaced):
            if fixed["cloned_from"] is None or fixed["calls"]:
                continue
            inherited_only += 1
            #: 자기 SetType 이 없으면 production 과 교체 규칙이 **같아야** 한다.
            assert spec.effect_types == fixed["types"], (card_id, spec.index)

    assert inherited_only == 2667

    #: 실제 카드 둘로 값까지 확인한다. 🔴 ``index`` 가 겹치므로 **``Clone`` 인
    #: 블록만** 골라 본다 — ``c39015`` 에는 ``e2`` 가 둘, ``c102380`` 에도 둘이다.
    for card_id, expected in ((CLONE_NO_SETTYPE, ["SINGLE"]), (TRIGGER_F_CLONE, ["FIELD"])):
        blocks = parse_lua_source(
            card_id, f"c{card_id}.lua", script_source(card_id)
        ).effects
        cloned = [b for b in blocks if b.cloned_from is not None]
        assert len(cloned) == 1, (card_id, [b.index for b in cloned])
        assert cloned[0].effect_types == expected, (card_id, cloned[0].effect_types)
        #: 같은 이름의 다른 블록은 **건드려지지 않았다.**
        same_name = [b for b in blocks if b.index == cloned[0].index]
        assert len(same_name) == 2, (card_id, [b.effect_types for b in same_name])


def test_18_multi_type_and_flip_cards_are_untouched():
    """🟢 §12 — 한 호출 OR 와 ``FLIP`` 사례는 바뀌지 않는다."""
    blocks = [b.effect_types for b in parse_lua_source(
        MULTI_TYPE_ONE_CALL, "x.lua", script_source(MULTI_TYPE_ONE_CALL)
    ).effects]
    assert ["CONTINUOUS", "FIELD"] in blocks
    assert ["FIELD", "TRIGGER_O"] in blocks

    flip = [b.effect_types for b in parse_lua_source(
        FLIP_CARD, "x.lua", script_source(FLIP_CARD)
    ).effects]
    assert ["SINGLE", "FLIP"] in flip


def test_19_corpus_wide_diff_is_only_clone_flag_removal(corpus):
    """
    🔴 §19 — **이 Phase 의 가장 중요한 검증.** corpus 전체에서 production 과
    교체 규칙이 다른 블록은 **단 1개**이고, 그것은 ``Clone`` 이 아니다.

    즉 ``Clone`` 오염은 **전부 사라졌고**, 남은 1건은 ``local`` 없는
    ``CreateEffect`` 라는 **다른 원인**이다 (``test_11``).
    """
    differing = []
    blocks = 0
    for card_id, _text, production, replaced in corpus:
        assert len(production) == len(replaced), card_id
        for spec, fixed in zip(production, replaced):
            blocks += 1
            if spec.effect_types != fixed["types"]:
                differing.append((card_id, spec.index, spec.cloned_from,
                                  spec.effect_types, fixed["types"]))

    #: 🔴 Phase 3-F-28 에서 34,680 → 34,681.
    assert blocks == 34681

    #: 🔴 Phase 3-F-28 에서 1 → 0. 3-F-27 때 남아 있던 그 1건은
    #: ``c9839115`` 의 ``local`` 없는 ``e1=Effect.CreateEffect(c)`` 가
    #: 자기 설정자를 앞 블록에 흘린 것이었고, 3-F-28 이 그 블록을 **따로
    #: 세기 시작하면서 사라졌다.** 그래서 이제 production 과 교체 규칙은
    #: corpus 전체에서 **완전히 같다** — 더 강한 결론이다.
    assert differing == [], differing


def test_20_no_two_specs_share_a_mutable_container(corpus):
    """
    🔴 §4 B · §16-20 — corpus 전체에서 **어떤 두 블록도 같은 리스트 객체를
    공유하지 않는다.** aliasing 이 아니었다는 것을 전수로 못 박는다.
    """
    checked = 0
    for _card_id, _text, production, _replaced in corpus:
        seen: set[int] = set()
        for spec in production:
            for container in (
                spec.effect_types,
                spec.ranges,
                spec.target_ranges,
                spec.categories,
                spec.properties,
            ):
                assert id(container) not in seen
                seen.add(id(container))
                checked += 1
    #: 🔴 Phase 3-F-28 에서 34,680 → 34,681.
    assert checked == 34681 * 5


def test_21_parsing_is_deterministic(corpus):
    """🟢 §16-21 — 같은 입력을 두 번 파싱하면 **같은 결과**다."""
    sample = [row for row in corpus[:400]]
    for card_id, text, production, _replaced in sample:
        again = parse_lua_source(card_id, f"c{card_id}.lua", text).effects
        assert [s.effect_types for s in again] == [
            s.effect_types for s in production
        ], card_id
        assert [s.index for s in again] == [s.index for s in production]
        assert [s.cloned_from for s in again] == [s.cloned_from for s in production]


def test_22_the_cache_signature_was_bumped():
    """
    🔴 §10 — ``_signature`` 가 파서를 고칠 때마다 올라간다.

    그 값에 파서 버전이 없으면 **고친 파서가 옛 캐시를 계속 읽는다** —
    signature 는 스크립트 파일 개수와 최신 mtime 만 보기 때문이다.

    .. note::
       🔴 Phase 3-F-28 에서 ``v5`` → ``v6``, Phase 3-F-29 에서 ``v6`` → ``v7``.
       이 테스트는 **두 번 다 설계대로 걸렸다** — 두 Phase 가 모두 파서를
       고쳤으므로 prefix 가 올라가야 한다. 되돌아가지 않았음도 함께 못 박는다.
    """
    source = inspect.getsource(LuaScriptSource._signature)
    assert "v7:" in source
    assert "v6:" not in source
    assert "v5:" not in source
    assert "v4:" not in source

    signature = LuaScriptSource(PROJECT_ROOT)._signature()
    assert signature.startswith("v7:")

    #: 캐시가 있다면 새 signature 로 쓰여 있어야 한다 (없으면 건너뛰지 않고
    #: 그냥 signature 형식만 확인한다).
    cache = PROJECT_ROOT / "data" / "cache" / "lua_scripts.json"
    if cache.is_file():
        with cache.open(encoding="utf-8") as handle:
            blob = json.load(handle)
        assert blob["signature"].startswith("v7:"), blob["signature"]


# ======================================================================
# D. §13 · §14 — 3-F-26 / 3-F-25 의 판정이 유지되는가
# ======================================================================


def test_23_quick_o_counts_are_unchanged(corpus):
    """
    🔴 §13 — ``QUICK_O`` 블록 수와 스크립트 수가 **고치기 전과 같다.**

    더하기만 했으므로 ``QUICK_O`` 가 추가되거나 사라진 블록은 **0건**이다.
    그래서 3-F-26 의 통계와 판정이 그대로 성립한다.
    """
    blocks = 0
    scripts = set()
    combinations: collections.Counter = collections.Counter()
    for card_id, _text, production, _replaced in corpus:
        for spec in production:
            if "QUICK_O" in spec.effect_types:
                blocks += 1
                scripts.add(card_id)
                combinations[tuple(sorted(spec.effect_types))] += 1

    #: 3-F-26 이 측정한 값과 같다.
    assert blocks == 1875
    assert len(scripts) == 1712

    #: 🔴 오염 조합은 사라지고 단독이 늘었다 — **합계는 같다.**
    assert combinations[("QUICK_O",)] == 1867
    assert combinations[("IGNITION", "QUICK_O")] == 0
    assert combinations[("ACTIVATE", "QUICK_O")] == 0
    assert combinations[("FIELD", "QUICK_O")] == 4
    assert combinations[("QUICK_O", "XMATERIAL")] == 4
    assert sum(combinations.values()) == 1875


def test_24_quick_o_cards_still_span_three_official_spell_speeds(repository):
    """
    🟢 §13 — 3-F-26 의 결정적 반례가 **그대로 성립한다.**

    오염이 사라졌어도 ``QUICK_O`` 를 가진 카드의 공식 스펠 스피드 분포는
    변하지 않는다 (카드 종류로 정해지는 것만).
    """
    from core import constants as C

    def category(card):
        mask = card.type_mask
        if mask & C.TYPE_SPELL:
            for bit, speed in (
                (C.TYPE_QUICKPLAY, 2),
                (C.TYPE_FIELD, 1),
                (C.TYPE_CONTINUOUS, 1),
                (C.TYPE_EQUIP, 1),
                (C.TYPE_RITUAL, 1),
            ):
                if mask & bit:
                    return speed
            return 1
        if mask & C.TYPE_TRAP:
            return 3 if mask & C.TYPE_COUNTER else 2
        return None

    table: collections.Counter = collections.Counter()
    carriers = 0
    for card in repository._cards.values():
        if not card.script:
            continue
        if any("QUICK_O" in s.effect_types for s in card.script.effects):
            carriers += 1
            table[category(card)] += 1

    assert carriers == 1781
    assert table[1] == 13
    assert table[2] == 414
    assert table[3] == 16
    assert table[None] == 1338


def test_25_this_phase_defined_no_new_semantics():
    """
    🔴 §8 · §18 — 의미를 **새로 부여하지 않았다.**

    ``QUICK_O`` → 스펠 스피드, ``EVENT_FREE_CHAIN`` → Free Chain 같은 매핑을
    만들지 않았고, 새 enum · 새 public field · 새 추상화도 없다.
    """
    source = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8")
    stripped = code_only(source)

    #: 특정 플래그 이름을 **코드에서** 분기 조건으로 쓰지 않는다.
    for name in ("QUICK_O", "IGNITION", "TRIGGER_F", "SpellSpeed", "FREE_CHAIN"):
        assert name not in stripped, name

    #: 새 enum · 새 클래스가 없다.
    tree = ast.parse(source)
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert classes == {"LuaScriptSource"}, classes

    #: ``EffectSpec`` 의 칸이 그대로다 (9칸).
    assert len(dataclasses.fields(EffectSpec)) == 9
    #: ``EffectDefinition`` 도 그대로다 (10칸, effect_types 없음).
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert len(definition) == 10
    assert "effect_types" not in definition


def test_26_production_change_is_confined_to_the_parser():
    """
    🔴 §18 — production 변경이 **``sources/lua_loader.py`` 와 docstring 한 건**
    뿐이다.

    끝점은 **이 Phase 의 commit** 이다 — ``HEAD`` 로 쓰면 뒤 Phase 가 섞인다
    (3-F-26 이 그렇게 깨졌다).
    """

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    PHASE_3F27_BASE = "9b34c20"
    added = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    base = f"{added[-1]}^" if added else PHASE_3F27_BASE
    tip = [added[-1]] if added else []

    changed = git("diff", "--name-only", base, *tip, "--", *PRODUCTION_ROOTS).split()
    assert set(changed) == {
        "sources/lua_loader.py",
        "core/card_model.py",
    }, changed

    #: ``core/card_model.py`` 는 **docstring 만** 바뀐다.
    before = git("show", f"{base}:core/card_model.py")
    after = (
        git("show", f"{tip[0]}:core/card_model.py")
        if tip
        else (PROJECT_ROOT / "core" / "card_model.py").read_text(encoding="utf-8")
    )
    assert code_only(before) == code_only(after)

    #: ``engine/`` 과 ``agent/`` 는 **한 파일도** 바뀌지 않는다.
    assert not [c for c in changed if c.startswith(("engine/", "agent/"))], changed


def test_27_the_engine_still_does_not_read_effect_types():
    """
    🟢 §14 — 3-F-26 이 확정한 것이 **그대로 유지된다.** engine/agent 코드에
    ``effect_types`` 등장 0회이고 ``CardDefinitionView`` 에 칸이 없다.

    그러므로 이 수정은 **duel 동작을 바꿀 수 없다.**
    """
    for directory in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            source = code_only(path.read_text(encoding="utf-8"))
            assert "effect_types" not in source, path
            assert "QUICK_O" not in source, path

    assert "effect_types" not in {
        f.name for f in dataclasses.fields(CardDefinitionView)
    }

    #: ``legal_actions`` · ``apply`` 도 그대로다.
    for func in (Duel.legal_actions, Duel.apply, Duel._activation_gate):
        body = code_of(func)
        assert "effect_types" not in body, func.__name__


# ======================================================================
# E. §11 · §15 — 불변 조건
# ======================================================================


def test_28_block_count_index_and_identity_are_unchanged(corpus):
    """
    🔴 **Invariant 5 · 6** — 블록 개수 · ``index`` · ``cloned_from`` · card
    identity 가 바뀌지 않았다.
    """
    blocks = 0
    cloned = 0
    for card_id, text, production, replaced in corpus:
        blocks += len(production)
        cloned += sum(1 for s in production if s.cloned_from is not None)
        #: 교체 규칙과 **구조**가 같다 — 수정은 값만 건드렸다.
        assert [s.index for s in production] == [b["index"] for b in replaced], card_id
        assert [s.cloned_from for s in production] == [
            b["cloned_from"] for b in replaced
        ], card_id

    #: 🔴 Phase 3-F-28 에서 34,680 → 34,681. ``Clone`` 블록 수 2,744 는
    #: 그대로다 — 새로 세는 두 블록과 사라진 한 블록 모두 ``Clone`` 이 아니다.
    assert blocks == 34681
    assert cloned == 2744


def test_29_the_sibling_fields_still_have_the_same_defect(corpus):
    """
    🔴 §18 범위 밖 — 형제 칸에 **같은 유형이 남아 있다.** 고치지 않고 **센다.**

    이 숫자가 다음 Phase 후보의 근거다.
    """
    counts: dict[str, int] = {}
    for setter, regex, field in (
        ("Range", lua_loader._RE_LOCATION, "ranges"),
        ("TargetRange", lua_loader._RE_LOCATION, "target_ranges"),
        ("Category", lua_loader._RE_CATEGORY, "categories"),
        ("Property", lua_loader._RE_EFFECT_FLAG, "properties"),
    ):
        lost = 0
        for _card_id, text, _production, _replaced in corpus:
            if ":Clone()" not in text:
                continue
            #: 🔴 Phase 3-F-28 — 그룹 번호 정정 + production 과 같은 전처리.
            text = lua_loader._RE_BLOCK_COMMENT.sub("", text)
            events: list[tuple[int, str, str]] = []
            for match in lua_loader._RE_CREATE_EFFECT.finditer(text):
                if not lua_loader._is_card_effect(
                    text, match.group(1), match.group(2), None
                ):
                    continue
                events.append((match.start(), "create", match.group(2)))
            for match in lua_loader._RE_CLONE_EFFECT.finditer(text):
                if not lua_loader._is_card_effect(
                    text, match.group(1), match.group(2), match.group(3)
                ):
                    continue
                events.append(
                    (match.start(), "clone", f"{match.group(2)}={match.group(3)}")
                )
            for match in lua_loader._RE_SETTER.finditer(text):
                events.append(
                    (
                        match.start(),
                        "set",
                        f"{match.group(1)}|{match.group(2)}|{match.end() - 1}",
                    )
                )
            events.sort(key=lambda item: item[0])
            bindings: dict[str, dict] = {}
            for _position, kind, payload in events:
                if kind == "create":
                    bindings[payload] = {"inherited": [], "own": None}
                elif kind == "clone":
                    destination, origin = payload.split("=", 1)
                    parent = bindings.get(origin)
                    carried = (
                        list(parent["own"])
                        if parent and parent["own"] is not None
                        else (list(parent["inherited"]) if parent else [])
                    )
                    bindings[destination] = {"inherited": carried, "own": None}
                else:
                    variable, name, index = payload.split("|", 2)
                    current = bindings.get(variable)
                    if current is None or name != setter:
                        continue
                    flags = lua_loader._strip_prefix(
                        regex.findall(
                            lua_loader._extract_call_args(text, int(index))
                        )
                    )
                    if current["own"] is None and current["inherited"]:
                        if not set(current["inherited"]) <= set(flags):
                            lost += 1
                    current["own"] = flags
        counts[field] = lost

    assert counts == {
        "ranges": 12,
        "target_ranges": 9,
        "categories": 24,
        "properties": 19,
    }, counts


def test_30_state_hash_and_rng_are_unchanged(repository):
    """🟢 §15 — ``state_hash`` · RNG 불변."""
    first = opened_duel(repository, seed=31)
    second = opened_duel(repository, seed=31)
    assert first.state.state_hash() == second.state.state_hash()
    assert opened_duel(repository, seed=32).state.state_hash() != first.state.state_hash()

    left = [first.state.rng.randrange(1000) for _ in range(8)]
    right = [second.state.rng.randrange(1000) for _ in range(8)]
    assert left == right


def test_31_hidden_information_and_view_are_unchanged(repository):
    """🟢 §15 — hidden-information · ``GameStateView`` 불변."""
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert len(fields) == 26
    assert "effect_types" not in fields
    assert "script" not in fields
    assert "code" not in fields
    assert "effect_count" in fields

    duel = opened_duel(repository, seed=33)
    view = duel.view(0)
    assert not hasattr(view, "effect_types")


def test_32_the_search_ranking_digest_is_unchanged(repository):
    """
    🟢 §15 — 검색/AI digest 불변: 6판 611결정.

    🔴 이것이 "파서 데이터 수정이 duel 동작을 바꾸지 않는다" 의 **행동 증거**다.
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
                and all(c in "0123456789abcdef" for c in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: dict[str, int] = {}
    for values in pinned.values():
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    expected, pins = max(counts.items(), key=lambda item: item[1])
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
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


def test_33_no_block_carries_a_contradictory_combination(corpus):
    """
    🔴 §11 **Invariant 4** — 수정 후 corpus 전체에 **모순 조합을 가진 블록이
    하나도 없다.**

    고치기 전에는 ``Clone`` 뒤 ``SetType`` 이 있는 77블록 중 **76블록**이
    모순이었다 (``test_12``).

    .. warning::
       🔴 처음에는 "1건 남는다" 고 적었다. 남는 1블록(``c9839115`` ``e1``)은
       ``['SINGLE', 'TRIGGER_O']`` 인데 적용 범위 1개 · 발동 분류 1개라 **모순이
       아니다.** 그 카드에서 ``local`` 없는 ``CreateEffect`` 가 흘린 ``SetType``
       은 ``SINGLE`` 이었고, 이미 있던 ``SINGLE`` 과 합쳐져 **우연히 같은 집합**이
       됐다. 그 카드에서 실제로 틀린 것은 :attr:`EffectSpec.code` 다 —
       ``EVENT_SPSUMMON_SUCCESS`` 가 ``EFFECT_UPDATE_ATTACK`` 으로 덮였다.

    .. note::
       🔴 **Phase 3-F-28 이 그 흘림 자체를 없앴다.** 이제 ``c9839115`` 는
       ``e1`` 이름을 쓰는 블록이 **둘**이고, 각자 자기 ``SetType`` 과
       ``code`` 를 갖는다. 그래서 아래 두 번째 묶음의 기대값이 "1개 · 흘린
       값" 에서 "2개 · 각자 제 값" 으로 바뀐다 — 모순 0건이라는 이 테스트의
       **주장은 그대로이고 오히려 강해졌다** (``test_19`` 의 production ↔
       교체 규칙 차이도 1 → 0 이 됐다).
    """
    offenders = []
    for card_id, _text, production, _replaced in corpus:
        for spec in production:
            if contradictory(spec.effect_types):
                offenders.append((card_id, spec.index, spec.effect_types))

    assert offenders == [], offenders

    #: 🔴 그 카드의 ``e1`` 은 이제 **두 블록**이고 둘 다 모순이 아니다.
    produced = spec_map(NON_LOCAL_CREATE)["e1"]
    assert len(produced) == 2
    assert [spec.cloned_from for spec in produced] == [None, None]
    assert [spec.effect_types for spec in produced] == [["SINGLE", "TRIGGER_O"], ["SINGLE"]]
    assert not any(contradictory(spec.effect_types) for spec in produced)
    #: 🔴 ``code`` 의 흘림도 사라졌다 — 유발 코드가 제 블록으로 돌아왔다.
    assert [spec.code for spec in produced] == [
        "EVENT_SPSUMMON_SUCCESS",
        "EFFECT_UPDATE_ATTACK",
    ]
    assert "EVENT_SPSUMMON_SUCCESS" in script_source(NON_LOCAL_CREATE)


def test_34_the_sibling_fields_were_not_touched(corpus):
    """
    🔴 §18 — 이 Phase 가 ``effect_types`` **만** 건드렸다는 것을 형제 칸의
    corpus 총계로 못 박는다.

    .. warning::
       🔴 주입으로 공백을 찾았다. ``Clone`` 분기에서 ``spec.categories`` 복사를
       지워도 ``test_29`` 가 잡지 못했다 — 그 테스트는 **Lua 원문**을 다시 걸어
       세기 때문에 production 을 보지 않는다. 그래서 production 출력의 총계를
       따로 고정한다.
    """
    totals = collections.Counter()
    blocks = 0
    for _card_id, _text, production, _replaced in corpus:
        for spec in production:
            blocks += 1
            totals["ranges"] += len(spec.ranges)
            totals["target_ranges"] += len(spec.target_ranges)
            totals["categories"] += len(spec.categories)
            totals["properties"] += len(spec.properties)
            totals["code"] += 1 if spec.code is not None else 0
            totals["count_limit"] += 1 if spec.count_limit is not None else 0
            totals["cloned_from"] += 1 if spec.cloned_from is not None else 0

    #: 🔴 Phase 3-F-28 에서 34,680 → 34,681 (위 ``*_TOTAL`` 주석 참고).
    assert blocks == 34681
    assert dict(totals) == {
        "ranges": RANGES_TOTAL,
        "target_ranges": TARGET_RANGES_TOTAL,
        "categories": CATEGORIES_TOTAL,
        "properties": PROPERTIES_TOTAL,
        "code": CODE_TOTAL,
        "count_limit": COUNT_LIMIT_TOTAL,
        "cloned_from": 2744,
    }, dict(totals)

    #: ``Clone`` 분기가 여섯 칸을 **전부** 복사한다는 것을 구문으로도 본다.
    clone_branch = inspect.getsource(parse_lua_source)
    for field in (
        "effect_types",
        "code",
        "ranges",
        "target_ranges",
        "categories",
        "properties",
        "count_limit",
    ):
        assert f"spec.{field} = " in clone_branch, field
