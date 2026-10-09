"""
EDOPro / ygopro 카드 스크립트(``c<id>.lua``) 로더.

이 저장소 루트에 있는 12,000여 개의 ``c*.lua`` 파일을 읽어 효과의 '기계적 의미'를
추출한다. 스크립트에는 레벨/속성/종족/공수/카드 텍스트가 들어 있지 않으므로,
이 소스는 :mod:`sources.official_db` 와 반드시 함께 사용해야 한다.

핵심 설계: 상수를 파일 단위로 뭉뚱그려 수집하지 않고 **효과 블록 단위**로 묶는다.

    local e2=Effect.CreateEffect(c)
    e2:SetCategory(CATEGORY_TOHAND+CATEGORY_SPECIAL_SUMMON)
    e2:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O)
    e2:SetCode(EVENT_TO_GRAVE)
    e2:SetRange(LOCATION_GRAVE)

위 블록은 "묘지에서 발동하여 패로 넣거나 특수 소환하는 효과" 하나로 해석된다.
파일 전체에서 LOCATION_GRAVE 와 CATEGORY_SPECIAL_SUMMON 이 등장했다는 사실만으로는
같은 효과인지 알 수 없기 때문에, 이 구분이 의미 기반 검색의 정확도를 좌우한다.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

from core.card_model import EffectSpec, LuaScriptInfo

# ---------------------------------------------------------------------------
# 정규식
# ---------------------------------------------------------------------------
_RE_SCRIPT_FILE = re.compile(r"^c(\d+)\.lua$")
#: ``--[[ ... ]]`` 블록 주석. **효과 블록 탐지 전에 지운다** (Phase 3-F-28).
#: 지우지 않으면 주석 안에 적힌 효과를 세고, 그만큼 뒤쪽 ``ordinal`` 이 밀린다
#: (``c9409625`` 가 ``--[[ untested version ... --]]`` 안에 블록 하나를 갖고
#: 있어서 ``e3`` 가 ordinal 3, ``e4`` 가 4 로 밀려 있었다 — 각각 2 · 3 이 맞다).
#: 줄 주석(``--``)은 **남긴다** — 헤더의 카드명을 그것으로 읽는다.
_RE_BLOCK_COMMENT = re.compile(r"--\[\[.*?(?:--\]\]|\]\])", re.S)

#: ``local`` 과 변수명 접두사를 **요구하지 않는다** (Phase 3-F-28). 받아들일지는
#: 아래 ``_is_card_effect`` 가 정한다.
_RE_CREATE_EFFECT = re.compile(
    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\("
)
#: 🔴 ``Clone`` 의 **세 가지 호출 형태**를 받는다 (Phase 3-F-32).
#:
#: 코퍼스의 ``Clone(`` 토큰 2,831개를 정규화해 보면 서로 다른 형태가 **4개**뿐이다.
#:
#: ===================================== ======= =========== ===================
#: 형태                                   호출    스크립트     이 정규식
#: ===================================== ======= =========== ===================
#: ``V=V:V()``                             2,827       2,213  받는다 (예전부터)
#: ``V=V:V(V)``                                2           2  🔴 받는다 (3-F-32)
#: ``V=V.V(V)`` (``Effect.Clone(e1)``)         1           1  🔴 받는다 (3-F-32)
#: ``V=V.V(0,V):V()``                          1           1  **배제한다**
#: ===================================== ======= =========== ===================
#:
#: 마지막 것은 ``c63708033`` 의
#: ``local tg=Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS):Clone()`` 이고
#: **Effect 가 아니라 Group 의 Clone** 이다. 그래서 **받는 쪽을 맨 식별자로
#: 묶어 둔다** — 식(expression) receiver 를 허용하면 Group clone 에 가짜 효과
#: 블록이 생긴다. 이것이 이 정규식을 "인자만" 넓히는 이유다.
#:
#: ``Effect.Clone(e1)`` 이 ``e1:Clone()`` 과 같은 함수라는 근거도 **코퍼스
#: 안에** 있다 — 점 형태 ``Class.Method`` 상위 40개 가운데 **37개**가 같은
#: 이름으로 콜론 메서드로도 쓰인다 (``Card.IsFaceup`` 은 점 1,219 · 콜론
#: 7,732). 그렇지 않은 셋(``Effect.CreateEffect`` · ``Group.FromCards`` ·
#: ``Group.CreateGroup``)은 진짜 정적 생성자다. ``Clone`` 은 콜론 2,829 ·
#: 점 1 이므로 메서드 쪽이다.
#:
#: 🔴 ``[^()\n]*`` 은 **한 줄 안**으로 제한한다. 여러 줄에 걸친 인자나 중첩
#: 괄호는 받지 않는다 — 코퍼스에 그런 ``Clone`` 은 없고, 넓히면 어디서
#: 끝나는지 모르는 호출을 받게 된다.
#:
#: 🔴 이 정규식을 바꿀 때는 **``_RE_REBIND`` 의 선읽기도 같이** 바꿔야 한다.
#: 그러지 않으면 블록은 생기지만 뒤따르는 설정자가 계속 버려져서, 파서가
#: **부모의 값을 자식의 값처럼 주장**하게 된다 (지금 없는 것보다 나쁘다).
_RE_CLONE_EFFECT = re.compile(
    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*"
    r"(?:([A-Za-z_]\w*)\s*:\s*Clone\s*\([^()\n]*\)"
    r"|Effect\s*\.\s*Clone\s*\(\s*([A-Za-z_]\w*)\s*\))"
)


def _clone_source(match: "re.Match[str]") -> str:
    """``_RE_CLONE_EFFECT`` 매치에서 **원본 변수 이름**을 돌려준다.

    콜론 형태(``e2=e1:Clone(...)``)는 3번 그룹, 점 형태
    (``e2=Effect.Clone(e1)``)는 4번 그룹에 들어 있다. 두 군데(이 모듈과
    :mod:`analysis.effect_analyzer`)에서 같은 규칙을 써야 하므로 여기 한
    곳에만 둔다 — Phase 3-F-28 이 탐지 정규식의 복사본 때문에 블록이
    어긋났던 것과 같은 이유다.
    """
    return match.group(3) or match.group(4)
_RE_SETTER = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*Set(\w+)\s*\(")

#: 🔴 변수에 **파서가 모르는 값**이 대입되는 자리 (Phase 3-F-31).
#:
#: ``bindings`` 의 계약은 "변수명 -> **지금** 그 변수가 가리키는 효과" 다
#: (아래 ``bindings`` 주석 참고). 파서는 ``Effect.CreateEffect`` 와
#: ``X:Clone()`` 두 형태에서만 그 매핑을 갱신했고, Lua 가 같은 변수에 **다른
#: 것**을 대입해도 **옛 매핑을 그대로 들고 있었다.** 그러면 그 뒤의
#: ``var:SetX(...)`` 가 **엉뚱한 블록에 붙는다.**
#:
#: corpus 전수로 그렇게 잘못 붙는 설정자가 **5건 / 3장** 있었다.
#:
#: * ``c52445243`` — ``local e1=e:GetLabelObject()`` 뒤의 ``SetCategory`` 3건이
#:   다른 함수에서 생성된 블록에 붙었다.
#: * ``c44887817`` — ``local e2=e1:Clone(e1)`` (``Clone()`` 의 **빈 괄호**를
#:   요구하는 위 정규식이 못 잡는다) 뒤의 ``SetCode`` 가 앞 블록의 code 를 덮었다.
#: * ``c4997565`` — ``local e2=Effect.Clone(e1)`` (다른 API 형태) 도 같다.
#:
#: 그래서 **모르는 대입을 만나면 그 변수의 바인딩을 푼다.** 이후 설정자는
#: 엉뚱한 블록에 붙는 대신 **버려진다** — Phase 3-E-18 이 ``code`` 에서
#: "읽지 못한 것은 ``None``(모른다)" 으로 되돌린 것과 같은 원칙이다. 틀린 값을
#: 만드는 것보다 모른다고 말하는 것이 맞다.
#:
#: 🔴 **Lua dataflow 를 구현하지 않는다.** 이 정규식은 "이 변수가 더 이상
#: 아는 효과를 가리키지 않는다" 만 판단하고, 무엇을 가리키는지는 **추측하지
#: 않는다.** 다중 대입(``local sme,soe=Spirit.AddProcedure(c,...)``)도 왼쪽
#: 이름 전부를 풀기만 한다.
#:
#: 음의 선읽기로 **파서가 아는 두 형태는 제외**한다 — 그 자리는 위의
#: ``create``/``clone`` 이벤트가 이미 처리한다.
_RE_REBIND = re.compile(
    r"(?:(?<=^)|(?<=[;\s\)])) *(?:local\s+)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*=(?!=)"
    #: 🔴 아래 세 형태는 ``_RE_CLONE_EFFECT`` 와 **반드시 같아야 한다**
    #: (Phase 3-F-32). 한쪽만 넓히면 블록은 생기지만 뒤따르는 설정자가
    #: 계속 버려져서, 파서가 **부모의 값을 자식의 값처럼 주장**한다 —
    #: 블록이 아예 없는 지금보다 나쁘다.
    r"(?!\s*(?:Effect\.(?:CreateEffect|GlobalEffect)\s*\("
    r"|[A-Za-z_]\w*\s*:\s*Clone\s*\([^()\n]*\)"
    r"|Effect\s*\.\s*Clone\s*\(\s*[A-Za-z_]\w*\s*\)))",
    re.M,
)
_RE_FUNCTION = re.compile(r"\bfunction\s+s\.(\w+)")
_RE_LISTED_NAMES = re.compile(r"s\.listed_names\s*=\s*\{([^}]*)\}")
_RE_LISTED_SERIES = re.compile(r"s\.listed_series\s*=\s*\{([^}]*)\}")
_RE_SET_CONST = re.compile(r"\bSET_(\w+)")
_RE_CARD_CONST = re.compile(r"\bCARD_\w+")
_RE_LOCATION = re.compile(r"\bLOCATION_(\w+)")
_RE_CATEGORY = re.compile(r"\bCATEGORY_(\w+)")
_RE_EVENT = re.compile(r"\bEVENT_(\w+)")
_RE_EFFECT_TYPE = re.compile(r"\bEFFECT_TYPE_(\w+)")
_RE_EFFECT_FLAG = re.compile(r"\bEFFECT_FLAG_(\w+)")
_RE_EFFECT_CODE = re.compile(r"\bEFFECT_(?!TYPE_|FLAG_)(\w+)")

# 소환 절차 헬퍼 (aux/Fusion/Synchro/Xyz/Link/Ritual 계열)
_RE_PROCEDURE = re.compile(
    r"\b(?:aux|Auxiliary|Fusion|Synchro|Xyz|Link|Ritual|Pendulum|Maximum)\."
    r"((?:Add|Create)\w*Proc\w*|EnablePendulumAttribute|"
    r"AddContactFusionProcedure|AddMaximumProcedure|AddProcedure)"
)


def _extract_call_args(text: str, open_paren_index: int) -> str:
    """``(`` 위치에서 시작해 괄호 균형을 맞춰 인자 문자열을 잘라낸다."""
    depth = 0
    for i in range(open_paren_index, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_index + 1 : i]
    # 괄호가 닫히지 않은 경우(문법 오류 파일) 남은 부분을 그대로 반환
    return text[open_paren_index + 1 :]


def _strip_prefix(matches: list[str]) -> list[str]:
    """정규식 그룹 결과에서 중복을 제거하고 등장 순서를 유지한다."""
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _strip_prefix_int(values: list[int]) -> list[int]:
    """정수 목록에서 중복을 제거하고 등장 순서를 유지한다."""
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _parse_header_comments(source: str) -> tuple[str | None, str | None, str | None]:
    """
    스크립트 선두 주석에서 일본어명 / 영어명 / 제작자를 추출한다.

        --白銀の城の狂時計      <- 일본어명
        --Labrynth Cooclock    <- 영어명
        --Scripted by Hatter   <- 제작자

    이 이름들은 스크립트 원문 그대로이며 번역하지 않는다.
    """
    name_ja: str | None = None
    name_en: str | None = None
    scripted_by: str | None = None

    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("--"):
            break  # 주석 블록 종료 (보통 local s,id=GetID())
        text = line.lstrip("-").strip()
        if not text:
            continue
        low = text.lower()
        if low.startswith("scripted by") or low.startswith("script by"):
            scripted_by = text.split("by", 1)[1].strip()
            continue
        if name_ja is None:
            name_ja = text
        elif name_en is None:
            name_en = text
    return name_ja, name_en, scripted_by


def _registers_on_card(source: str, var: str) -> bool:
    """스크립트가 ``c:RegisterEffect(var)`` 로 **이 카드에** 등록하는가."""
    pattern = r"(?<![\w.])c\s*:\s*RegisterEffect\s*\(\s*" + re.escape(var) + r"\b"
    return re.search(pattern, source) is not None


#: ``Clone()`` 이 부모에게서 물려주는 **목록 칸**들. 이 칸에 자식이 자기
#: 설정자를 부르면 물려받은 값을 **덮어쓴다** (더하지 않는다).
#:
#: 🔴 근거는 corpus 전수 측정이다 (Phase 3-F-29). EDOPro 의 ``SetCategory`` ·
#: ``SetProperty`` · ``SetRange`` · ``SetTargetRange`` API 가 대입인지 OR 인지는
#: 이 저장소에 문서화돼 있지 않으므로 **Lua 의미를 추측하지 않고** 스크립트가
#: 실제로 쓰는 모양으로만 판단했다.
#:
#: 1. **자식이 물려받은 플래그를 자기 호출 안에 다시 적는 블록이 43개 있다.**
#:    ``target_ranges`` 11 · ``properties`` 23 · ``categories`` 8 ·
#:    ``ranges`` 1. 더하기라면 다시 적는 것은 **아무 효과도 없는 죽은 코드**다 —
#:    서로 다른 43개 스크립트가 그럴 이유가 없다. 덮어쓰기라면 **유지하려는
#:    플래그를 반드시 다시 적어야 한다.** 실제 모양이 정확히 그렇다 —
#:    ``c13708888`` ``e2`` 는 부모의 ``CARD_TARGET+DELAY`` 를 다시 적고
#:    ``DAMAGE_STEP`` 을 더해 ``CARD_TARGET+DELAY+DAMAGE_STEP`` 을 쓴다.
#: 2. **명시적으로 비우는 스크립트가 있다.** ``c55262310`` ``e2`` 가
#:    ``e2:SetProperty(0)`` 을 부른다. 대입이 아니면 의미가 없는 줄이다.
#: 3. **더하기는 그 카드가 쓰지 않는 조합을 만든다.** ``c93473606`` ``e2`` 는
#:    ATK/DEF 를 바꾸는 효과인데 더하기로는 부모의 ``TODECK+DRAW`` 가 남아
#:    ``TODECK+DRAW+ATKCHANGE+DEFCHANGE`` 가 된다 — corpus 의 어떤 카드도 한
#:    호출로 적지 않는 조합이다. ``c55262310`` ``e2`` 도 같다.
#: 4. **``effect_types`` 가 같은 결론을 이미 받았다** (Phase 3-F-27). 같은
#:    ``Clone`` 분기가 물려주는 칸인데 규칙이 서로 달랐다.
#:
#: 반대 방향 증거도 측정했고 **기각했다**: 한 블록이 같은 설정자를 순차로 두 번
#: 부르며 서로 다른 값을 쓰는 사례가 ``properties`` 에 5건 있다. 그러나 그중 4건은
#: ``SetDescription(...)`` + ``SetProperty(EFFECT_FLAG_CLIENT_HINT)`` 라는 **같은
#: 복사-붙여넣기 관용구**이고 (``c49460512`` · ``c50619462`` · ``c64867422`` ·
#: ``c73899015``), 1건(``c76685519``)은 ``e2`` 를 쓸 자리에 ``e1`` 을 쓴 **스크립트
#: 오타**다. 독립 증거 1건은 위 1~4 를 뒤집지 못한다. ``categories`` ·
#: ``ranges`` · ``target_ranges`` 에는 그런 사례가 **0건**이다.
#:
#: 🔴 ``code`` 와 ``count_limit`` 은 애초에 대입이라 여기 없다. ``Clone`` 이
#: 물려주지 않는 칸도 없다 — 이 집합이 ``clone`` 분기가 복사하는 목록 칸 전부다.
_CLONE_INHERITED_LISTS = (
    "effect_types",
    "ranges",
    "target_ranges",
    "categories",
    "properties",
)


#: ``SetX(0)`` · ``SetX(0,0)`` — 스크립트가 그 칸을 **명시적으로 비운다**.
#: 읽을 수 없는 인자와 **구별해야 한다** (아래 :func:`_write_list` 참고).
_RE_LITERAL_ZERO = re.compile(r"0(?:\s*,\s*0)*\s*\Z")


def _write_list(
    spec: EffectSpec,
    inherited: dict[str, set[str]],
    var: str,
    field: str,
    regex: "re.Pattern[str]",
    args: str,
) -> None:
    """
    목록 칸 하나에 설정자 결과를 쓴다.

    그 칸의 현재 값이 ``Clone`` 이 물려준 것이면 **덮어쓰고**, 아니면
    **더한다**. :data:`_CLONE_INHERITED_LISTS` 가 왜 덮어쓰기인지 적는다.

    두 번째 이후 호출은 물려받은 값이 아니므로 **더하기로 돌아간다** — 한
    블록이 같은 설정자를 두 번 부르는 경우의 기존 동작을 바꾸지 않는다.

    🔴 **읽을 수 없는 인자로는 덮어쓰지 않는다.** 상수를 하나도 읽지 못한
    호출은 두 가지일 수 있다.

    * ``SetProperty(0)`` · ``SetCategory(0)`` — 스크립트가 **비운다**.
      corpus 에 11건 있고, 덮어써서 ``[]`` 로 만드는 것이 맞다.
    * ``SetTargetRange(0,1)`` — 플레이어 대상 형식이라 ``LOCATION_*`` 이
      **애초에 없다.** corpus 에 16건 있다. 이것을 "대상 범위가 없다" 로 읽으면
      **읽지 못한 것을 빈 값으로 단정**하는 것이다.

    그래서 플래그를 하나도 못 읽었고 인자가 리터럴 0 도 아니면 **물려받은 값을
    그대로 두고 칸을 상속 상태로 남긴다** — 뒤에 읽을 수 있는 호출이 오면 그때
    덮어쓴다. Phase 3-E-18 이 :attr:`EffectSpec.code` 에서 "읽지 못한 것은
    ``None``(모른다)" 으로 되돌린 것과 같은 원칙이다. 목록 칸에는 "모른다" 를
    표현할 값이 없으므로, 틀린 단정을 만들지 않는 쪽을 고른다.

    🔴 현재 corpus 에서는 이 분기가 **동작을 바꾸지 않는다** — 읽을 수 없는
    16건은 전부 물려받은 값이 비어 있다. 즉 이 분기는 **지금의 숫자를 위한 것이
    아니라, 나중에 그런 스크립트가 들어와도 틀리지 않기 위한 것**이다.
    """
    found = regex.findall(args)
    if field in inherited.get(var, ()):
        if not found and not _RE_LITERAL_ZERO.match(args.strip()):
            return                      # 읽지 못했다 — 단정하지 않는다
        setattr(spec, field, _strip_prefix(found))
        inherited[var].discard(field)
    else:
        setattr(spec, field, _strip_prefix(getattr(spec, field) + found))


def _is_card_effect(source: str, local: str | None, var: str, parent: str | None) -> bool:
    """
    이 ``CreateEffect`` / ``Clone`` 을 **이 카드의 효과 블록**으로 셀 것인가.

    기존 규칙은 ``local`` + ``e`` 로 시작하는 변수명이었다. 그것은 **"카드 자신의
    효과" 의 대리 지표**이고, corpus 전수로 보면 251건을 걸러 내는데 그중
    **249건이 옳다** (Phase 3-F-28 측정):

    * ``Duel.RegisterEffect`` 로 **듀얼에** 등록되는 전역 효과 245건
      (213건은 ``aux.GlobalCheck`` 안이다). 관례상 ``ge1`` 처럼 쓴다.
    * ``tc:RegisterEffect`` · ``token:RegisterEffect`` 로 **다른 카드에** 부여하는
      효과 4건.

    둘 다 이 카드의 효과가 아니므로 세면 ``ordinal`` 이 틀어진다. 그래서 대리
    지표를 **버리지 않고**, 그것이 놓친 자리에서만 **명시적 증거**로 보강한다 —
    스크립트가 ``c:RegisterEffect(var)`` 로 직접 등록하면 카드의 효과다.

    그렇게 보강되는 블록은 corpus 전체에 **둘**이다.

    * ``c9839115`` — ``e1=Effect.CreateEffect(c)`` 에 ``local`` 이 없다.
    * ``c74506079`` — ``local ae=Effect.CreateEffect(c)`` 의 변수명이 ``e`` 로
      시작하지 않는다.
    """
    if local and var.startswith("e") and (parent is None or parent.startswith("e")):
        return True
    return _registers_on_card(source, var)


#: 같은 byte offset 에 이벤트가 겹칠 때의 우선순위 (Phase 3-F-31).
#: ``create``/``clone`` 이 먼저 묶고, ``rebind`` 가 풀고, ``set`` 이 마지막이다.
_EVENT_ORDER = {"create": 0, "clone": 0, "rebind": 1, "set": 2}


def parse_lua_source(card_id: int, file_name: str, source: str) -> LuaScriptInfo:
    """Lua 스크립트 원문 하나를 :class:`LuaScriptInfo` 로 파싱한다."""
    name_ja, name_en, scripted_by = _parse_header_comments(source)

    info = LuaScriptInfo(
        card_id=card_id,
        file_name=file_name,
        name_ja=name_ja,
        name_en=name_en,
        scripted_by=scripted_by,
    )

    # --- 효과 블록 단위 파싱 ---------------------------------------------
    # 변수명 -> 현재 바인딩된 EffectSpec. 같은 변수(e1)가 여러 함수에서
    # 재사용되므로, 새 CreateEffect 를 만나면 바인딩을 교체한다.
    bindings: dict[str, EffectSpec] = {}
    #: 변수명 -> 그 변수에 묶인 spec 의 **어느 목록 칸이 ``Clone`` 이 물려준
    #: 값인지**. 그 칸에 자기 설정자가 처음 오면 물려받은 목록을 **덮어쓰고**
    #: 칸을 집합에서 뺀다. 두 번째 이후 호출은 기존대로 더한다.
    #:
    #: Phase 3-F-27 이 ``effect_types`` 에만 이 추적을 넣었고, Phase 3-F-29 가
    #: 나머지 네 칸(``ranges`` · ``target_ranges`` · ``categories`` ·
    #: ``properties``)으로 넓혔다. 근거는 ``_CLONE_INHERITED_LISTS`` 참고.
    inherited: dict[str, set[str]] = {}
    events: list[tuple[int, str, str]] = []  # (위치, 종류, 페이로드)

    #: 🔴 블록 주석을 먼저 지운다 — 주석 안의 효과를 세면 ``ordinal`` 이 밀린다.
    #: 헤더의 카드명은 위에서 **원문**으로 이미 읽었고, 줄 주석은 남아 있다.
    body = _RE_BLOCK_COMMENT.sub("", source)

    for m in _RE_CREATE_EFFECT.finditer(body):
        if not _is_card_effect(body, m.group(1), m.group(2), None):
            continue
        events.append((m.start(), "create", m.group(2)))
    for m in _RE_CLONE_EFFECT.finditer(body):
        #: 원본 변수는 형태에 따라 3번/4번 그룹에 있다 — ``_clone_source`` 참고.
        src_var = _clone_source(m)
        if not _is_card_effect(body, m.group(1), m.group(2), src_var):
            continue
        events.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
    #: 🔴 파서가 모르는 대입은 바인딩을 **푼다** (Phase 3-F-31 — 위
    #: ``_RE_REBIND`` 참고). ``create``/``clone`` 과 같은 자리에서 겹치지
    #: 않도록 정규식이 그 두 형태를 선읽기로 제외한다.
    for m in _RE_REBIND.finditer(body):
        events.append((m.start(), "rebind", m.group(1)))
    for m in _RE_SETTER.finditer(body):
        payload = f"{m.group(1)}|{m.group(2)}|{m.end() - 1}"
        events.append((m.start(), "set", payload))
    #: 같은 위치에서는 ``create``/``clone`` → ``rebind`` → ``set`` 순으로 본다.
    events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))

    for _pos, kind, payload in events:
        if kind == "rebind":
            #: 이 변수는 더 이상 **아는** 효과를 가리키지 않는다. 무엇을
            #: 가리키는지는 추측하지 않고, 그냥 모른다고 둔다.
            for name in payload.split(","):
                bindings.pop(name.strip(), None)
                inherited.pop(name.strip(), None)
        elif kind == "create":
            var = payload
            spec = EffectSpec(index=var)
            bindings[var] = spec
            inherited[var] = set()
            info.effects.append(spec)
        elif kind == "clone":
            dst, src = payload.split("=", 1)
            parent = bindings.get(src)
            spec = EffectSpec(index=dst, cloned_from=src)
            if parent is not None:
                # Clone() 은 원본 속성을 물려받은 뒤 일부만 덮어쓴다.
                spec.effect_types = list(parent.effect_types)
                spec.code = parent.code
                spec.ranges = list(parent.ranges)
                spec.target_ranges = list(parent.target_ranges)
                spec.categories = list(parent.categories)
                spec.properties = list(parent.properties)
                spec.count_limit = parent.count_limit
            bindings[dst] = spec
            #: 물려받아 **비어 있지 않은** 칸만 추적한다 — 빈 목록을 덮어쓰는
            #: 것은 더하기와 결과가 같으므로 추적할 필요가 없다.
            inherited[dst] = {
                field
                for field in _CLONE_INHERITED_LISTS
                if getattr(spec, field)
            }
            info.effects.append(spec)
        else:  # set
            var, setter, idx_s = payload.split("|", 2)
            spec = bindings.get(var)
            if spec is None:
                continue
            #: 🔴 ``body`` 기준 offset 이므로 ``body`` 에서 잘라야 한다 —
            #: ``source`` 에 쓰면 블록 주석을 지운 만큼 자리가 밀린다.
            args = _extract_call_args(body, int(idx_s))
            if setter == "Type":
                found = _RE_EFFECT_TYPE.findall(args)
                if "effect_types" in inherited.get(var, ()):
                    # **Clone 이 물려준 목록을 그대로 두면 안 된다** (Phase 3-F-27).
                    #
                    # ``SetType`` 을 더하기로 처리하면, 스크립트가 분명히 다시
                    # 적은 type 위에 부모의 type 이 남는다. 그 결과는 **어떤
                    # 카드도 적지 않은 조합**이 된다 — corpus 전수로 측정하면
                    # 한 ``SetType`` 호출 안에서 적용 범위
                    # (``SINGLE``/``FIELD``/``EQUIP``)를 둘 이상 적거나 발동 분류
                    # (``ACTIVATE``/``IGNITION``/``TRIGGER_O``/``QUICK_O``/
                    # ``TRIGGER_F``/``QUICK_F``/``CONTINUOUS``)를 둘 이상 적는
                    # 호출이 **31,933건 중 0건**인데, 더하기는 77건 가운데 76건에서
                    # 바로 그 조합을 만든다 (적용 범위 25 · 발동 분류 51).
                    #
                    # 실제 카드로: ``c324483`` 은
                    # ``e1:SetType(EFFECT_TYPE_IGNITION)`` →
                    # ``local e2=e1:Clone()`` →
                    # ``e2:SetType(EFFECT_TYPE_QUICK_O)`` 인데 ``e2`` 가
                    # ``['IGNITION', 'QUICK_O']`` 가 됐다.
                    #
                    # 부모의 type 을 **유지하려는** 스크립트는 자식에서 그것을
                    # 다시 적는다 — 77건 중 그렇게 한 유일한 블록
                    # (``c4928565`` ``e4``)이 ``SINGLE+TRIGGER_O`` 를 그대로
                    # 다시 적는다. 더하기였다면 다시 적을 이유가 없다.
                    #
                    # :attr:`EffectSpec.code` 는 같은 위험을 Phase 3-E-18 이
                    # 이미 고쳐 두었다 (아래 ``setter == "Code"`` 참고). 이 칸은
                    # 그때 함께 고쳐지지 않았다.
                    spec.effect_types = _strip_prefix(found)
                    inherited[var].discard("effect_types")
                else:
                    spec.effect_types = _strip_prefix(spec.effect_types + found)
            elif setter == "Code":
                event = _RE_EVENT.search(args)
                if event:
                    spec.code = f"EVENT_{event.group(1)}"
                else:
                    code = _RE_EFFECT_CODE.search(args)
                    if code:
                        spec.code = f"EFFECT_{code.group(1)}"
                    else:
                        # 이름을 붙일 수 없는 인자다 (``SetCode(id)`` ·
                        # ``SetCode(1082946)`` · ``SetCode(CARD_*)``).
                        #
                        # 여기서 **앞 값을 그대로 두면 안 된다.** Clone 은 부모의
                        # ``code`` 를 물려받으므로, 물려받은 값이 남은 채 스크립트가
                        # 분명히 덮어쓴 코드를 계속 주장하게 된다 (Phase 3-E-18 이
                        # corpus 전체에서 3개 블록을 찾았다 — ``c4179255`` 는
                        # ``e1:SetCode(EVENT_CHAINING)`` → ``local e2=e1:Clone()``
                        # → ``e2:SetCode(id)`` 인데 ``e2.code`` 가
                        # ``EVENT_CHAINING`` 으로 남았다).
                        #
                        # 읽지 못한 것은 **모른다**(``None``)로 되돌린다. 틀린 값을
                        # 남기는 것보다 모른다고 말하는 것이 맞다.
                        spec.code = None
            elif setter == "Range":
                _write_list(spec, inherited, var, "ranges", _RE_LOCATION, args)
            elif setter == "TargetRange":
                _write_list(spec, inherited, var, "target_ranges", _RE_LOCATION, args)
            elif setter == "Category":
                _write_list(spec, inherited, var, "categories", _RE_CATEGORY, args)
            elif setter == "Property":
                _write_list(spec, inherited, var, "properties", _RE_EFFECT_FLAG, args)
            elif setter == "CountLimit":
                spec.count_limit = args.strip()

    # --- 파일 전체 단위 수집 ---------------------------------------------
    #: 🔴 아래 '파일 전체 긁기' 들은 **``source``** 를 그대로 쓴다 (Phase 3-F-28).
    #: 이 값들은 설계상 블록에 귀속되지 않는 "스크립트에 등장한 상수" 목록이고,
    #: ``body`` 로 바꾸면 블록 주석이 있는 5개 스크립트의 숫자가 움직인다 —
    #: 이번 Phase 의 범위(``CreateEffect`` 탐지 · ``ordinal`` · ``EffectRef``)가
    #: 아니므로 건드리지 않는다.
    info.functions = _strip_prefix(_RE_FUNCTION.findall(source))
    info.trigger_events = [f"EVENT_{e}" for e in _strip_prefix(_RE_EVENT.findall(source))]
    info.locations = _strip_prefix(_RE_LOCATION.findall(source))
    info.categories = _strip_prefix(_RE_CATEGORY.findall(source))
    info.effect_codes = [
        f"EFFECT_{e}" for e in _strip_prefix(_RE_EFFECT_CODE.findall(source))
    ]

    # 소환 절차 헬퍼도 효과 코드처럼 취급한다 (엑시즈/싱크로/융합/링크 소환법).
    for proc in _strip_prefix(_RE_PROCEDURE.findall(source)):
        token = f"PROC_{proc.upper()}"
        if token not in info.effect_codes:
            info.effect_codes.append(token)

    # --- 참조 카드 / 카드군 ----------------------------------------------
    m = _RE_LISTED_NAMES.search(source)
    if m:
        body = m.group(1)
        names = [int(x) for x in re.findall(r"\d{3,}", body)]
        # ``s.listed_names={id}`` 는 자기 자신을 참조한다는 뜻이다.
        if re.search(r"(?<![\w.])id(?![\w])", body):
            names.insert(0, card_id)
        info.listed_names = _strip_prefix_int(names)
        # CARD_DARK_MAGICIAN 같은 명명 상수는 여기서 해석하지 않고 그대로 보관한다.
        # 실제 ID 해석은 상수 테이블을 가진 리포지토리 단계에서 수행한다.
        info.listed_name_constants = _strip_prefix(_RE_CARD_CONST.findall(body))
    m = _RE_LISTED_SERIES.search(source)
    if m:
        info.listed_series = _strip_prefix(_RE_SET_CONST.findall(m.group(1)))

    return info


# ---------------------------------------------------------------------------
# 디렉터리 로더
# ---------------------------------------------------------------------------
class LuaScriptSource:
    """
    ``c*.lua`` 스크립트 디렉터리를 읽는 소스.

    스크립트 파일은 원본 데이터이므로 이 클래스는 **읽기만 한다**.
    파싱 결과는 별도 캐시 파일(JSON)에 저장해 재실행 시간을 줄인다.
    """

    def __init__(self, script_dir: str | os.PathLike[str]):
        self.script_dir = Path(script_dir)

    def iter_script_files(self) -> Iterator[tuple[int, Path]]:
        """(카드 ID, 파일 경로) 를 카드 ID 순으로 내보낸다."""
        if not self.script_dir.is_dir():
            return
        entries: list[tuple[int, Path]] = []
        for entry in os.scandir(self.script_dir):
            if not entry.is_file():
                continue
            m = _RE_SCRIPT_FILE.match(entry.name)
            if m:
                entries.append((int(m.group(1)), Path(entry.path)))
        entries.sort()
        yield from entries

    def load(self) -> dict[int, LuaScriptInfo]:
        """디렉터리 전체를 파싱한다."""
        result: dict[int, LuaScriptInfo] = {}
        for card_id, path in self.iter_script_files():
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            result[card_id] = parse_lua_source(card_id, path.name, source)
        return result

    # --- 캐시 -----------------------------------------------------------
    def load_cached(self, cache_path: str | os.PathLike[str]) -> dict[int, LuaScriptInfo]:
        """
        캐시가 최신이면 캐시를 쓰고, 아니면 다시 파싱해 캐시를 갱신한다.
        최신 여부는 스크립트 파일 개수와 최신 수정 시각으로 판단한다.
        """
        cache_file = Path(cache_path)
        signature = self._signature()
        if cache_file.is_file():
            try:
                with cache_file.open(encoding="utf-8") as fh:
                    blob = json.load(fh)
                if blob.get("signature") == signature:
                    return {
                        int(k): _info_from_dict(v) for k, v in blob["scripts"].items()
                    }
            except (OSError, ValueError, KeyError):
                pass  # 캐시가 깨졌으면 조용히 재파싱한다

        scripts = self.load()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "signature": signature,
            "scripts": {str(k): _info_to_dict(v) for k, v in scripts.items()},
        }
        tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(cache_file)
        return scripts

    def _signature(self) -> str:
        count = 0
        newest = 0.0
        if self.script_dir.is_dir():
            for entry in os.scandir(self.script_dir):
                if entry.is_file() and _RE_SCRIPT_FILE.match(entry.name):
                    count += 1
                    newest = max(newest, entry.stat().st_mtime)
        # ``v9`` — Phase 3-F-32 가 ``Clone`` 의 **인자 있는 형태**
        # (``e1:Clone(e1)`` · ``e2:Clone(c)``)와 **점 형태**
        # (``Effect.Clone(e1)``)를 블록으로 인정했다 — 3개 스크립트에
        # 효과 블록 3개가 생기고 그중 한 장(``c4997565``)은 뒤 블록의
        # ``ordinal`` 이 하나 밀린다.
        # ``v8`` — Phase 3-F-31 이 "파서가 모르는 대입은 바인딩을 푼다" 를
        # 넣었다 (설정자 5건이 엉뚱한 블록에 붙던 것을 버리도록).
        # ``v7`` — Phase 3-F-29 가 ``Clone`` 이 물려준 네 목록 칸
        # (``ranges`` · ``target_ranges`` · ``categories`` · ``properties``)을
        # 자식의 첫 설정자가 **덮어쓰도록** 고쳤다. ``v6`` 은 Phase 3-F-28 의
        # ``CreateEffect`` 탐지 수정(블록 주석 제거 + ``c:RegisterEffect`` 보강),
        # ``v5`` 는 Phase 3-F-27 의 ``SetType`` 수정이었다. 이 값에
        # 파서 버전이 들어 있지 않으면 **고친 파서가 옛 캐시를 계속 읽는다**
        # (스크립트 파일이 바뀌지 않으면 signature 가 같기 때문이다). 파서가
        # 같은 입력에서 다른 결과를 내게 되면 이 숫자를 올린다.
        return f"v9:{count}:{newest:.0f}"


def _info_to_dict(info: LuaScriptInfo) -> dict:
    return {
        "card_id": info.card_id,
        "file_name": info.file_name,
        "name_ja": info.name_ja,
        "name_en": info.name_en,
        "scripted_by": info.scripted_by,
        "effects": [
            {
                "index": e.index,
                "effect_types": e.effect_types,
                "code": e.code,
                "ranges": e.ranges,
                "target_ranges": e.target_ranges,
                "categories": e.categories,
                "properties": e.properties,
                "count_limit": e.count_limit,
                "cloned_from": e.cloned_from,
            }
            for e in info.effects
        ],
        "listed_names": info.listed_names,
        "listed_name_constants": info.listed_name_constants,
        "listed_series": info.listed_series,
        "functions": info.functions,
        "trigger_events": info.trigger_events,
        "locations": info.locations,
        "categories": info.categories,
        "effect_codes": info.effect_codes,
    }


def _info_from_dict(data: dict) -> LuaScriptInfo:
    info = LuaScriptInfo(
        card_id=data["card_id"],
        file_name=data["file_name"],
        name_ja=data.get("name_ja"),
        name_en=data.get("name_en"),
        scripted_by=data.get("scripted_by"),
        listed_names=data.get("listed_names", []),
        listed_name_constants=data.get("listed_name_constants", []),
        listed_series=data.get("listed_series", []),
        functions=data.get("functions", []),
        trigger_events=data.get("trigger_events", []),
        locations=data.get("locations", []),
        categories=data.get("categories", []),
        effect_codes=data.get("effect_codes", []),
    )
    info.effects = [EffectSpec(**e) for e in data.get("effects", [])]
    return info
