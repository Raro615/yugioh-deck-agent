"""
재정의 증분 갱신.

카드 데이터 쪽 :mod:`sources.source_manager` 와 같은 철학이다 — 전부 다시
받지 않고 **바뀐 것만** 다시 처리한다. 다만 비교 단위가 다르다. 카드 데이터는
카드 하나가 단위지만, 재정은 카드 하나 안에 Q&A 가 여럿이고 각각 따로 생기고
사라지므로 **재정 하나가 단위**다. 그래서 별도 모듈로 둔다.

판단 근거는 ``content_hash`` 다. 공식 사이트의 更新日 은 있을 때도 없을 때도
있어서 그것만으로는 변경을 놓친다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rulings.ruling_model import CardRuling, CardRulingSet, CardRulingSupplement


class RulingChange(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


@dataclass(slots=True)
class RulingUpdatePlan:
    """이번 수집에서 무엇이 달라졌는가."""

    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    unavailable: list[int] = field(default_factory=list)
    """조회를 시도했으나 실패한 카드의 ``cid``. **재정이 없는 것과 다르다.**"""
    identity_blocked: list[int] = field(default_factory=list)
    """
    식별자가 검증되지 않아 **조회하지 않은** 카드의 ``cid``.

    ``unavailable`` 과 합치면 "사이트가 죽었다" 와 "물어볼 근거가 없다" 가
    같아 보인다. 전자는 재시도 대상이고 후자는 대조 대상이다.
    """
    skipped: list[int] = field(default_factory=list)

    def record_unchanged(self, cid: int) -> None:
        self.skipped.append(cid)

    def merge(self, other: "RulingUpdatePlan") -> "RulingUpdatePlan":
        self.new.extend(other.new)
        self.changed.extend(other.changed)
        self.removed.extend(other.removed)
        self.unchanged.extend(other.unchanged)
        self.unavailable.extend(other.unavailable)
        self.identity_blocked.extend(other.identity_blocked)
        self.skipped.extend(other.skipped)
        return self

    def counts(self) -> dict[str, int]:
        return {
            "new": len(self.new),
            "changed": len(self.changed),
            "removed": len(self.removed),
            "unchanged": len(self.unchanged),
            "unavailable": len(self.unavailable),
            "identity_blocked": len(self.identity_blocked),
            "skipped": len(self.skipped),
        }

    @property
    def is_empty(self) -> bool:
        return not (self.new or self.changed or self.removed)

    def describe(self) -> list[str]:
        counts = self.counts()
        lines = [
            f"재정  new={counts['new']}  changed={counts['changed']}  "
            f"removed={counts['removed']}  unchanged={counts['unchanged']}"
        ]
        if counts["skipped"]:
            lines.append(f"건너뜀(이미 수집): 카드 {counts['skipped']}장")
        if counts["unavailable"]:
            lines.append(
                f"확인 실패: 카드 {counts['unavailable']}장 "
                "— 재정이 없다는 뜻이 아니다"
            )
        if counts["identity_blocked"]:
            lines.append(
                f"식별자 미검증으로 조회 안 함: 카드 {counts['identity_blocked']}장 "
                "— 재정이 없다는 뜻도, 조회에 실패했다는 뜻도 아니다"
            )
        return lines


def _entry_hashes(
    ruling_set: CardRulingSet | None,
) -> dict[str, str]:
    if ruling_set is None:
        return {}
    return {e.ruling_id: e.content_hash for e in ruling_set.all_entries()}


def diff_ruling_set(
    before: CardRulingSet | None, after: CardRulingSet
) -> RulingUpdatePlan:
    """
    한 카드에 대한 이전 결과와 이번 결과를 비교한다.

    **확인에 실패했으면 아무 판단도 하지 않는다.** 그때 ``removed`` 를 매기면
    사이트가 잠깐 죽었을 뿐인데 재정이 사라졌다고 기록하게 된다.
    """
    plan = RulingUpdatePlan()
    if after.blocked_by_identity:
        # 물어볼 근거가 없어 묻지 않았다. 재시도 대상이 아니라 대조 대상이다.
        plan.identity_blocked.append(after.official_cid)
        return plan
    if not after.confirmed:
        # 실패했든 아예 시도하지 않았든, 둘 다 판단 근거가 없다.
        plan.unavailable.append(after.official_cid)
        return plan

    old = _entry_hashes(before)
    new = _entry_hashes(after)
    for ruling_id, digest in new.items():
        if ruling_id not in old:
            plan.new.append(ruling_id)
        elif old[ruling_id] != digest:
            plan.changed.append(ruling_id)
        else:
            plan.unchanged.append(ruling_id)
    if before is not None and before.confirmed:
        for ruling_id in old:
            if ruling_id not in new:
                plan.removed.append(ruling_id)
    return plan


def merge_translations(
    before: CardRulingSet | None, after: CardRulingSet
) -> CardRulingSet:
    """
    다시 수집한 결과에 기존 번역을 옮겨 붙인다.

    번역은 공식 사이트에서 오지 않으므로 재수집하면 사라진다. 원문이 그대로면
    번역도 그대로 유지하고, 원문이 바뀌었으면 번역은 옮기되
    ``is_stale()`` 이 참이 되어 낡았다는 것이 드러난다.
    """
    if before is None:
        return after
    previous: dict[str, CardRuling | CardRulingSupplement] = {
        e.ruling_id: e for e in before.all_entries()
    }
    for entry in after.all_entries():
        old = previous.get(entry.ruling_id)
        if old is None:
            continue
        for language, translation in old.translations.items():
            entry.translations.setdefault(language, translation)
    return after
