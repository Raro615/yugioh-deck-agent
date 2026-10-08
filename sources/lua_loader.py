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
_RE_CREATE_EFFECT = re.compile(
    r"\blocal\s+(e\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\("
)
_RE_CLONE_EFFECT = re.compile(r"\blocal\s+(e\w*)\s*=\s*(e\w*)\s*:\s*Clone\s*\(\s*\)")
_RE_SETTER = re.compile(r"\b(e\w*)\s*:\s*Set(\w+)\s*\(")
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
    #: 변수명 -> 그 변수에 묶인 spec 의 ``effect_types`` 가 **Clone 이 물려준
    #: 것인지** (``True``). ``SetType`` 을 처음 만나면 물려받은 목록을 **덮어쓰고**
    #: ``False`` 로 내린다 (Phase 3-F-27 — 아래 ``setter == "Type"`` 참고).
    inherited_types: dict[str, bool] = {}
    events: list[tuple[int, str, str]] = []  # (위치, 종류, 페이로드)

    for m in _RE_CREATE_EFFECT.finditer(source):
        events.append((m.start(), "create", m.group(1)))
    for m in _RE_CLONE_EFFECT.finditer(source):
        events.append((m.start(), "clone", f"{m.group(1)}={m.group(2)}"))
    for m in _RE_SETTER.finditer(source):
        payload = f"{m.group(1)}|{m.group(2)}|{m.end() - 1}"
        events.append((m.start(), "set", payload))
    events.sort(key=lambda e: e[0])

    for _pos, kind, payload in events:
        if kind == "create":
            var = payload
            spec = EffectSpec(index=var)
            bindings[var] = spec
            inherited_types[var] = False
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
            inherited_types[dst] = bool(spec.effect_types)
            info.effects.append(spec)
        else:  # set
            var, setter, idx_s = payload.split("|", 2)
            spec = bindings.get(var)
            if spec is None:
                continue
            args = _extract_call_args(source, int(idx_s))
            if setter == "Type":
                found = _RE_EFFECT_TYPE.findall(args)
                if inherited_types.get(var):
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
                    inherited_types[var] = False
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
                spec.ranges = _strip_prefix(spec.ranges + _RE_LOCATION.findall(args))
            elif setter == "TargetRange":
                spec.target_ranges = _strip_prefix(
                    spec.target_ranges + _RE_LOCATION.findall(args)
                )
            elif setter == "Category":
                spec.categories = _strip_prefix(
                    spec.categories + _RE_CATEGORY.findall(args)
                )
            elif setter == "Property":
                spec.properties = _strip_prefix(
                    spec.properties + _RE_EFFECT_FLAG.findall(args)
                )
            elif setter == "CountLimit":
                spec.count_limit = args.strip()

    # --- 파일 전체 단위 수집 ---------------------------------------------
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
        # ``v5`` — Phase 3-F-27 이 ``SetType`` 의 Clone 노후값을 고쳤다. 이 값에
        # 파서 버전이 들어 있지 않으면 **고친 파서가 옛 캐시를 계속 읽는다**
        # (스크립트 파일이 바뀌지 않으면 signature 가 같기 때문이다). 파서가
        # 같은 입력에서 다른 결과를 내게 되면 이 숫자를 올린다.
        return f"v5:{count}:{newest:.0f}"


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
