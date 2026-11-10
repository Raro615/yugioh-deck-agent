"""
덱 이미지 등록 — 사용자가 **Neuron 에서 내보낸 덱 이미지 한 장**을 한 번
등록해 두고, 같은 덱의 다른 패에도 다시 쓴다 (Phase 6-AZ).

무엇이고 무엇이 아닌가
----------------------
🔴 **Neuron 앱에 접속하지 않는다.** 자동 로그인도, 비공개 API 호출도
하지 않는다. 사용자가 **자기 손으로 저장한 이미지 파일 하나**를 받아
보관하는 것이 전부다.

🔴 **카드 그림을 바깥에서 긁어모으지 않는다.** 이 계층이 보관하는 것은
사용자가 준 **덱 이미지 한 장**뿐이고, 개별 카드 그림을 수집하지 않는다.

🔴 **디스코드 첨부 URL 이 계속 살아 있다고 가정하지 않는다.** 등록할 때
파일을 내려받아 :data:`REGISTRY_DIRNAME` 아래에 **복사해 둔다**. 그 뒤로는
그 사본만 읽는다.

🔴 **추측한 대응으로 외부 공유를 하지 않는다.** 자리마다 어느 카드인지가
확인된 등록만 :attr:`DeckRegistration.verified` 가 참이고, 확인되지 않은
등록으로는 사이트 조작을 시작하지 않는다.

무엇을 적어 두는가
------------------
========================  =================================================
등록 ID · 소유 사용자      같은 사용자가 다시 쓸 때 ID 로 고른다
보관한 이미지 경로 · 해시   첨부 URL 이 죽어도 계속 읽을 수 있다
정규화한 레시피 · 해시      레시피가 바뀌면 **불일치**로 처리한다
메인 · 엑스트라 · 사이드    사이트의 매수 칸에 그대로 넣는다
자리별 카드와 확인 상태     ``main-0`` … 가 어느 패스코드인가
확인 방법                   사이트 식별 / 사용자 확인
========================  =================================================

자리와 시작 패
--------------
🔴 **이미지 순서를 바꾸라고 요구하지 않는다.** 시작 패는 이미지 맨 앞에
있을 필요가 없다 — :func:`assign_slots` 가 등록된 **자리별 패스코드**에서
엔진 개체에 맞는 자리를 찾는다. 같은 이름의 카드가 여러 장이면 자리가
다르므로 섞이지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "REGISTRY_FORMAT", "REGISTRY_DIRNAME", "DeckRegistration", "SlotEntry",
    "normalize_recipe", "new_registration_id", "register_deck_image",
    "load_registration", "list_registrations", "find_by_recipe",
    "assign_slots", "SlotAssignment",
]

REGISTRY_FORMAT = "deck-image-registration/1"
REGISTRY_DIRNAME = Path("data") / "deck_images"

_ROOT = Path(__file__).resolve().parent.parent
_ALLOWED_SUFFIX = {".png", ".jpg", ".jpeg", ".webp"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_registration_id() -> str:
    """등록 하나를 가리키는 짧은 ID."""
    return "dk" + uuid.uuid4().hex[:10]


def _owner_key(owner: str) -> str:
    """
    🔴 **소유자를 폴더 이름으로 쓰지 않는다.** 디스코드 사용자 ID 를 그대로
    디렉터리 이름에 넣으면 저장소 밖으로 새어 나가기 쉽다. 해시로 가른다.
    """
    return _sha256(str(owner).encode("utf-8"))[:16]


# ======================================================================
# 레시피 정규화
# ======================================================================
def normalize_recipe(recipe_text: str, repository=None) -> tuple[dict, str]:
    """
    레시피 글자 → **정규화한 구성과 그 해시**.

    🔴 **순서와 표기에 흔들리지 않는다.** 카드 ID 와 매수만 남기고 정렬한다
    — 같은 덱을 다르게 적어도 같은 해시가 나오고, 한 장이라도 달라지면
    해시가 달라진다.
    """
    from deck.recipe import parse_recipe

    parsed = parse_recipe(recipe_text, repository)
    draft = parsed.draft
    if draft is None:
        raise ValueError("레시피를 읽지 못했습니다")

    def _counts(slots) -> list[list[int]]:
        tally: dict[int, int] = {}
        for slot in slots or ():
            tally[int(slot.card_id)] = tally.get(int(slot.card_id), 0) + int(
                slot.copies)
        return [[code, tally[code]] for code in sorted(tally)]

    norm = {"main": _counts(draft.main), "extra": _counts(draft.extra),
            "side": []}
    digest = _sha256(json.dumps(norm, sort_keys=True,
                                separators=(",", ":")).encode("utf-8"))
    return norm, digest


def recipe_totals(norm: dict) -> dict:
    return {part: sum(count for _code, count in rows)
            for part, rows in norm.items()}


def _expected_multiset(norm: dict) -> dict:
    """``{"main": {패스코드: 매수}, …}``."""
    return {part: {code: count for code, count in rows}
            for part, rows in norm.items()}


# ======================================================================
# 등록 기록
# ======================================================================
@dataclass(frozen=True)
class SlotEntry:
    """이미지의 한 자리. 🔴 **확인된 것과 아닌 것을 가른다.**"""

    slot: str
    passcode: "int | None" = None
    site_name: str = ""
    source: str = "site"
    confirmed: bool = False

    def to_dict(self) -> dict:
        return {"slot": self.slot, "passcode": self.passcode,
                "site_name": self.site_name, "source": self.source,
                "confirmed": self.confirmed}


@dataclass(frozen=True)
class DeckRegistration:
    registration_id: str
    owner: str
    image_path: str
    image_sha256: str
    image_bytes: int
    recipe_text: str
    recipe_norm: dict
    recipe_sha256: str
    counts: dict
    slots: tuple[SlotEntry, ...] = ()
    verified: bool = False
    verify_method: str = ""
    verified_at: str = ""
    notes: tuple[str, ...] = ()
    format: str = REGISTRY_FORMAT

    # ------------------------------------------------------------------
    @property
    def image_file(self) -> Path:
        return _ROOT / self.image_path

    def matches_recipe(self, recipe_sha: str) -> bool:
        """🔴 레시피가 달라지면 **이 등록과 불일치**다."""
        return self.recipe_sha256 == recipe_sha

    def by_slot(self) -> dict:
        return {entry.slot: entry for entry in self.slots}

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "registration_id": self.registration_id, "owner": self.owner,
            "image_path": self.image_path, "image_sha256": self.image_sha256,
            "image_bytes": self.image_bytes,
            "recipe_text": self.recipe_text, "recipe_norm": self.recipe_norm,
            "recipe_sha256": self.recipe_sha256, "counts": self.counts,
            "slots": [entry.to_dict() for entry in self.slots],
            "verified": self.verified, "verify_method": self.verify_method,
            "verified_at": self.verified_at, "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "DeckRegistration":
        return cls(
            registration_id=raw["registration_id"], owner=raw["owner"],
            image_path=raw["image_path"], image_sha256=raw["image_sha256"],
            image_bytes=int(raw.get("image_bytes") or 0),
            recipe_text=raw.get("recipe_text", ""),
            recipe_norm=raw.get("recipe_norm") or {},
            recipe_sha256=raw.get("recipe_sha256", ""),
            counts=raw.get("counts") or {},
            slots=tuple(SlotEntry(**entry) for entry in raw.get("slots") or ()),
            verified=bool(raw.get("verified")),
            verify_method=raw.get("verify_method", ""),
            verified_at=raw.get("verified_at", ""),
            notes=tuple(raw.get("notes") or ()),
            format=raw.get("format", REGISTRY_FORMAT),
        )


# ======================================================================
# 보관
# ======================================================================
def _registry_dir(owner: str, registration_id: str,
                  root: "Path | None" = None) -> Path:
    base = (Path(root) if root is not None else _ROOT) / REGISTRY_DIRNAME
    return base / _owner_key(owner) / registration_id


def register_deck_image(*, owner: str, image: "str | Path | bytes",
                        image_name: str, recipe_text: str,
                        repository=None, slots=(), verified: bool = False,
                        verify_method: str = "", notes=(),
                        registration_id: "str | None" = None,
                        root: "Path | None" = None) -> DeckRegistration:
    """
    덱 이미지 한 장을 **복사해 보관하고** 등록 기록을 쓴다.

    🔴 **첨부 URL 을 들고 있지 않는다** — 바이트를 받아 파일로 둔다.
    """
    rid = registration_id or new_registration_id()
    data = (image if isinstance(image, bytes)
            else Path(image).read_bytes())
    suffix = Path(image_name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise ValueError(
            f"덱 이미지는 {', '.join(sorted(_ALLOWED_SUFFIX))} 만 받습니다 "
            f"(받은 것: {suffix or '확장자 없음'})")

    norm, digest = normalize_recipe(recipe_text, repository)
    folder = _registry_dir(owner, rid, root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"image{suffix}"
    target.write_bytes(data)

    base = Path(root) if root is not None else _ROOT
    registration = DeckRegistration(
        registration_id=rid, owner=str(owner),
        image_path=str(target.relative_to(base)),
        image_sha256=_sha256(data), image_bytes=len(data),
        recipe_text=recipe_text, recipe_norm=norm, recipe_sha256=digest,
        counts=recipe_totals(norm),
        slots=tuple(slots), verified=bool(verified),
        verify_method=verify_method,
        verified_at=(datetime.now(timezone.utc).isoformat(timespec="seconds")
                     if verified else ""),
        notes=tuple(notes),
    )
    (folder / "registration.json").write_text(
        json.dumps(registration.to_dict(), ensure_ascii=False, indent=1),
        encoding="utf-8")
    return registration


def load_registration(owner: str, registration_id: str,
                      root: "Path | None" = None) -> "DeckRegistration | None":
    """
    🔴 **다른 사용자의 등록을 꺼내 주지 않는다** — 소유자 폴더 아래만 본다.
    """
    if not re.fullmatch(r"dk[0-9a-f]{10}", str(registration_id or "")):
        return None
    path = _registry_dir(owner, registration_id, root) / "registration.json"
    if not path.exists():
        return None
    try:
        return DeckRegistration.from_dict(
            json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError):
        return None


def list_registrations(owner: str,
                       root: "Path | None" = None) -> tuple[DeckRegistration, ...]:
    base = ((Path(root) if root is not None else _ROOT) / REGISTRY_DIRNAME
            / _owner_key(owner))
    if not base.exists():
        return ()
    found = []
    for folder in sorted(base.iterdir()):
        got = load_registration(owner, folder.name, root)
        if got is not None:
            found.append(got)
    return tuple(found)


def find_by_recipe(owner: str, recipe_sha: str,
                   root: "Path | None" = None) -> "DeckRegistration | None":
    """같은 레시피로 **이미 등록해 둔** 이미지가 있으면 그것을 쓴다."""
    for registration in list_registrations(owner, root):
        if registration.matches_recipe(recipe_sha) and registration.verified:
            return registration
    return None


# ======================================================================
# 자리 배정 — 이미지 순서를 바꾸라고 하지 않는다
# ======================================================================
@dataclass(frozen=True)
class SlotAssignment:
    """엔진 개체 ↔ 이미지 자리. 🔴 **매 실행마다 새로 만든다.**"""

    by_instance: dict = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


def assign_slots(record, registration: DeckRegistration) -> SlotAssignment:
    """
    기록의 시작 판에 있는 개체마다 **등록된 자리**를 찾는다.

    🔴 **이미지 순서에 기대지 않는다.** 패스코드가 맞는 자리를 **그 구역
    안에서** 고른다 (패와 덱은 ``main-*``, 엑스트라는 ``extra-*``). 같은
    이름의 카드가 여러 장이면 자리를 하나씩 나눠 가지므로 섞이지 않는다.

    🔴 **이전 세션의 임시 DOM ID 를 쓰지 않는다** — 자리 이름(``main-7``)
    은 이미지 안의 위치이지 브라우저가 만든 값이 아니다.
    """
    cards = record.get("cards") or {}
    zones = ((record.get("initial") or {}).get("zones") or {}).get("0") or {}
    by_slot = registration.by_slot()

    pools: dict[str, dict[int, list[str]]] = {"main": {}, "extra": {}}
    for slot, entry in sorted(by_slot.items(), key=_slot_order):
        part = slot.split("-")[0]
        if part not in pools or entry.passcode is None:
            continue
        pools[part].setdefault(int(entry.passcode), []).append(slot)

    taken: dict[str, set[str]] = {"main": set(), "extra": set()}
    by_instance: dict[int, str] = {}
    problems: list[str] = []

    def _take(instance: int, part: str) -> None:
        card = cards.get(str(instance)) or {}
        passcode = card.get("passcode")
        name = card.get("name") or f"[{passcode}]"
        free = [slot for slot in pools[part].get(int(passcode or 0), ())
                if slot not in taken[part]]
        if not free:
            problems.append(
                f"{name} ({passcode}) 를 놓을 자리가 등록된 "
                f"{'메인' if part == 'main' else '엑스트라'} 덱에 "
                f"모자랍니다 — 등록한 이미지와 이번 레시피가 다릅니다."
            )
            return
        taken[part].add(free[0])
        by_instance[int(instance)] = free[0]

    #: 🔴 **패를 먼저** 배정한다 — 어느 자리를 꺼낼지가 여기서 정해진다.
    for instance in zones.get("HAND") or ():
        _take(instance, "main")
    for instance in zones.get("DECK") or ():
        _take(instance, "main")
    for instance in zones.get("EXTRA") or ():
        _take(instance, "extra")
    return SlotAssignment(by_instance=by_instance, problems=tuple(problems))


def _slot_order(item) -> tuple:
    slot = item[0]
    part, _, number = slot.partition("-")
    try:
        return (part, int(number))
    except ValueError:
        return (part, 0)


# ======================================================================
# 사이트 식별 결과 대조
# ======================================================================
def compare_identification(identified, norm: dict, repository=None) -> dict:
    """
    사이트가 읽은 **자리별 카드**를 레시피와 맞춰 본다.

    ``identified`` 는 ``[{"slot": "main-0", "name": "宵星の騎士ギルス"}, …]``
    이다. 🔴 **이름이 아니라 카드 ID 로 맞춘다** — 일본어 이름을 저장소의
    ``name_ja`` 로 되짚어 패스코드를 얻고, 그 다중집합을 레시피와 비교한다.
    """
    want = _expected_multiset(norm)
    lookup: dict[str, int] = {}
    if repository is not None:
        for part in ("main", "extra"):
            for code, _count in norm.get(part) or ():
                card = repository.get(int(code))
                if card is None:
                    continue
                for name in (getattr(card, "name_ja", None),
                             getattr(card, "name", None),
                             getattr(card, "name_en", None)):
                    if name:
                        lookup[_tidy(name)] = int(code)

    slots: list[SlotEntry] = []
    seen = {"main": {}, "extra": {}}
    unknown: list[str] = []
    for row in identified or ():
        slot = str(row.get("slot") or "")
        part = slot.split("-")[0]
        name = str(row.get("name") or "")
        code = lookup.get(_tidy(name))
        slots.append(SlotEntry(slot=slot, passcode=code, site_name=name,
                               source="site", confirmed=code is not None))
        if code is None:
            unknown.append(f"{slot}: {name or '미식별'}")
        elif part in seen:
            seen[part][code] = seen[part].get(code, 0) + 1

    mismatches: list[str] = []
    for part in ("main", "extra"):
        for code, count in sorted(want.get(part, {}).items()):
            got = seen[part].get(code, 0)
            if got != count:
                mismatches.append(
                    f"{part}: 카드 {code} 가 레시피에는 {count}장인데 "
                    f"이미지에서는 {got}장 읽혔습니다")
        for code, got in sorted(seen[part].items()):
            if code not in want.get(part, {}):
                mismatches.append(
                    f"{part}: 카드 {code} 는 레시피에 없는데 이미지에서 "
                    f"{got}장 읽혔습니다")
    return {"slots": slots, "unknown": unknown, "mismatches": mismatches,
            "ok": not unknown and not mismatches}


def _tidy(name: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", str(name)).replace(" ", "").strip()
