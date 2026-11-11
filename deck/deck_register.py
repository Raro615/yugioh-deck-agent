"""
덱 이미지 등록 한 번 — 사이트에서 자리별 카드를 읽고 레시피와 맞춰
등록까지 (Phase 6-AZ).

CLI(``scripts/register_deck_image.py``) 와 디스코드(``/register-deck``) 가
**같은 이 함수**를 부른다. 그래서 두 자리의 판정이 갈라지지 않는다.

🔴 **확인된 것과 아닌 것을 가른다.** 자리마다 어느 카드인지가 전부 정해지고
그 다중집합이 레시피와 같을 때만 :attr:`RegistrationOutcome.verified` 가
참이다. 확인되지 않은 등록으로는 사이트 조작을 시작하지 않는다.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["RegistrationOutcome", "run_registration", "DEFAULT_TIMEOUT"]

_ROOT = Path(__file__).resolve().parent.parent
_DRIVER = _ROOT / "scripts" / "duel_simulator_register.js"
DEFAULT_TIMEOUT = 300.0


@dataclass(frozen=True)
class RegistrationOutcome:
    ok: bool = False
    verified: bool = False
    registration: object = None
    reason: str = ""
    problems: tuple[str, ...] = ()
    read_slots: int = 0
    uncertain: int = 0
    unreadable: int = 0
    workdir: "Path | None" = None
    raw: dict = field(default_factory=dict)

    @property
    def registration_id(self) -> str:
        return getattr(self.registration, "registration_id", "")


def _identify(image: Path, *, main: int, extra: int, workdir: Path,
              run_id: str, timeout: float, runner=None) -> dict:
    command = ["node", str(_DRIVER), str(workdir), "--image", str(image),
               "--main", str(main), "--extra", str(extra), "--side", "0",
               "--run-id", run_id]
    if runner is not None:
        runner(command, workdir)
    else:
        try:
            subprocess.run(command, cwd=str(_ROOT), capture_output=True,
                           text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"stopped_reason": f"사이트 읽기가 {int(timeout)}초 안에 "
                                      f"끝나지 않았습니다"}
        except OSError as error:
            return {"stopped_reason": f"읽기 도구를 실행하지 못했습니다: {error}"}
    path = workdir / "identify.json"
    if not path.exists():
        return {"stopped_reason": "사이트 읽기 결과가 없습니다"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return {"stopped_reason": f"읽기 결과를 읽지 못했습니다: {error}"}


def run_registration(*, owner: str, image: "Path | bytes", image_name: str,
                     recipe_text: str, repository=None, confirms=(),
                     notes=(),
                     base_dir="docs/viewer/local/deck-register",
                     timeout: float = DEFAULT_TIMEOUT,
                     runner=None, root: "Path | None" = None
                     ) -> RegistrationOutcome:
    """덱 이미지 한 장을 읽고 맞춰 보고 등록한다."""
    from deck.deck_image_registry import (
        SlotEntry,
        compare_identification,
        new_registration_id,
        normalize_recipe,
        recipe_totals,
        register_deck_image,
    )

    try:
        norm, _digest = normalize_recipe(recipe_text, repository)
    except ValueError as error:
        return RegistrationOutcome(reason=f"레시피를 읽지 못했습니다: {error}")
    totals = recipe_totals(norm)
    if not totals.get("main"):
        return RegistrationOutcome(reason="레시피의 메인 덱이 비어 있습니다")

    rid = new_registration_id()
    workdir = Path(base_dir) / rid
    workdir.mkdir(parents=True, exist_ok=True)
    if isinstance(image, bytes):
        suffix = Path(image_name).suffix.lower() or ".png"
        source = workdir / f"uploaded{suffix}"
        source.write_bytes(image)
    else:
        source = Path(image)
        if not source.exists():
            return RegistrationOutcome(
                reason=f"덱 이미지를 찾지 못했습니다: {source}")

    read = _identify(source, main=totals["main"], extra=totals["extra"],
                     workdir=workdir, run_id=rid, timeout=timeout,
                     runner=runner)
    if read.get("stopped_reason"):
        return RegistrationOutcome(reason=read["stopped_reason"],
                                   workdir=workdir, raw=read)

    site_slots = read.get("slots") or []
    verdict = compare_identification(site_slots, norm, repository)
    slots = {entry.slot: entry for entry in verdict["slots"]}

    #: 🔴 사용자가 직접 확정한 자리를 얹는다 (사이트가 못 읽은 자리).
    user_fixed = 0
    for pair in confirms or ():
        slot, _, code = str(pair).partition("=")
        slot, code = slot.strip(), code.strip()
        if not slot or not code.isdigit():
            return RegistrationOutcome(
                reason=f"자리 확정 형식이 틀렸습니다: {pair} "
                       f"(예: main-7=57835716)", workdir=workdir, raw=read)
        slots[slot] = SlotEntry(
            slot=slot, passcode=int(code),
            site_name=getattr(slots.get(slot), "site_name", ""),
            source="user", confirmed=True)
        user_fixed += 1

    def _order(name: str):
        part, _, number = name.partition("-")
        try:
            return (part, int(number))
        except ValueError:
            return (part, 0)

    ordered = tuple(slots[key] for key in sorted(slots, key=_order))

    problems: list[str] = []
    missing = [entry.slot for entry in ordered
               if entry.passcode is None or not entry.confirmed]
    if missing:
        problems.append(
            f"어느 카드인지 확정하지 못한 자리 {len(missing)}개: "
            + ", ".join(missing[:8]) + (" …" if len(missing) > 8 else ""))
    unreadable = len(read.get("unreadable") or ())
    if unreadable:
        problems.append(f"목록 줄과 자리를 묶지 못한 것 {unreadable}개")
    counts_read = read.get("counts_read") or {}
    if counts_read.get("main") != totals["main"] or \
            counts_read.get("extra") != totals["extra"]:
        problems.append(
            f"읽은 자리 수가 레시피와 다릅니다 (읽음 {counts_read} / "
            f"레시피 {totals})")

    if not missing:
        #: 🔴 전부 확정됐을 때만 **카드별 매수**를 맞춰 본다.
        tally: dict[tuple[str, int], int] = {}
        for entry in ordered:
            part = "extra" if entry.slot.startswith("extra-") else "main"
            key = (part, int(entry.passcode))
            tally[key] = tally.get(key, 0) + 1
        for part in ("main", "extra"):
            want = {code: count for code, count in norm.get(part) or ()}
            for code, count in sorted(want.items()):
                got = tally.get((part, code), 0)
                if got != count:
                    problems.append(f"{part}: 카드 {code} 가 레시피 {count}장 "
                                    f"/ 이미지 {got}장")
            for (seen_part, code), got in sorted(tally.items()):
                if seen_part == part and code not in want:
                    problems.append(f"{part}: 카드 {code} 는 레시피에 없는데 "
                                    f"이미지에 {got}장")
    else:
        problems.extend(verdict["mismatches"][:6])

    verified = not problems
    method = ("사이트 식별" if not user_fixed
              else f"사이트 식별 + 사용자 확정 {user_fixed}자리")
    registration = register_deck_image(
        owner=owner, image=source.read_bytes(), image_name=image_name,
        recipe_text=recipe_text, repository=repository, slots=ordered,
        verified=verified, verify_method=method if verified else "",
        #: 🔴 **출처를 등록에 남긴다** (Phase 6-BA) — 이 이미지가 어디서
        #: 왔는지가 기록에 없으면 나중에 되짚을 길이 없다. 남은 문제도
        #: 함께 적는다.
        notes=tuple(notes) + tuple(problems),
        registration_id=rid, root=root)
    return RegistrationOutcome(
        ok=True, verified=verified, registration=registration,
        reason="" if verified else "확인되지 않았습니다",
        problems=tuple(problems), read_slots=len(site_slots),
        uncertain=int(read.get("uncertain") or 0), unreadable=unreadable,
        workdir=workdir, raw=read)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
