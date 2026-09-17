"""
데이터 소스 관리와 증분 업데이트.

새로운 카드가 나오거나 기존 카드가 바뀌어도 ``core/`` 와 ``analysis/`` 를
고치지 않고 데이터만 갱신할 수 있게 한다.

각 소스는 :class:`SourceAdapter` 만 만족하면 된다. 어댑터는 자기 소스의 수집과
변환만 맡고, 병합 순서와 변경 감지는 :class:`SourceManager` 가 처리한다.
``core/`` 와 ``analysis/`` 는 어느 웹사이트가 어떤 모양인지 알지 못한다.

변경 감지는 카드별 지문(fingerprint)을 이전 실행과 비교하는 방식이다.
전체를 다시 파싱하지 않고 바뀐 카드만 골라낸다.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from core.provenance import SourceKind

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "state" / "sources.json"


class ChangeKind(str, Enum):
    """이전 실행과 비교한 카드 상태."""

    NEW = "new"
    CHANGED = "changed"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


@dataclass(slots=True)
class SourceRecord:
    """
    한 소스가 카드 하나에 대해 제공하는 내용.

    값의 형태는 소스마다 다르므로 그대로 담고, 해석은 병합 단계에서 한다.
    """

    card_id: int
    source: SourceKind
    fields: dict[str, object] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """내용이 바뀌었는지 비교하기 위한 지문."""
        blob = json.dumps(self.fields, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


class SourceAdapter(Protocol):
    """
    데이터 소스 어댑터가 지켜야 할 최소 약속.

    새 소스를 붙일 때 이것만 만족하면 ``CardRepository`` 를 고치지 않아도 된다.
    """

    kind: SourceKind

    def is_available(self) -> bool:
        """이 소스를 지금 읽을 수 있는가."""

    def load_records(self) -> dict[int, SourceRecord]:
        """카드 ID -> 이 소스가 제공하는 내용."""


@dataclass(slots=True)
class SourceSnapshot:
    """한 소스의 카드별 지문. 다음 실행과 비교하는 데 쓴다."""

    source: str
    fingerprints: dict[str, str] = field(default_factory=dict)

    def diff(self, current: dict[int, SourceRecord]) -> dict[ChangeKind, list[int]]:
        result: dict[ChangeKind, list[int]] = {kind: [] for kind in ChangeKind}
        seen: set[str] = set()
        for card_id, record in current.items():
            key = str(card_id)
            seen.add(key)
            previous = self.fingerprints.get(key)
            if previous is None:
                result[ChangeKind.NEW].append(card_id)
            elif previous != record.fingerprint():
                result[ChangeKind.CHANGED].append(card_id)
            else:
                result[ChangeKind.UNCHANGED].append(card_id)
        for key in self.fingerprints:
            if key not in seen:
                result[ChangeKind.REMOVED].append(int(key))
        return result

    def update(self, current: dict[int, SourceRecord]) -> None:
        self.fingerprints = {
            str(card_id): record.fingerprint() for card_id, record in current.items()
        }


@dataclass(slots=True)
class UpdatePlan:
    """무엇이 바뀌었고 무엇을 다시 처리해야 하는가."""

    per_source: dict[str, dict[ChangeKind, list[int]]] = field(default_factory=dict)

    def changed_card_ids(self) -> set[int]:
        """신규·변경·삭제된 카드 ID. 이 카드들만 다시 처리하면 된다."""
        affected: set[int] = set()
        for changes in self.per_source.values():
            for kind in (ChangeKind.NEW, ChangeKind.CHANGED, ChangeKind.REMOVED):
                affected.update(changes.get(kind, []))
        return affected

    def counts(self) -> dict[str, dict[str, int]]:
        return {
            source: {kind.value: len(ids) for kind, ids in changes.items()}
            for source, changes in self.per_source.items()
        }

    def is_empty(self) -> bool:
        return not self.changed_card_ids()


class SourceManager:
    """
    등록된 어댑터를 모아 변경을 감지한다.

    소스마다 갱신 시점이 다르므로 각자의 지문을 따로 보관한다. 한 소스만
    바뀌어도 그 소스가 건드린 카드만 다시 처리하면 된다.
    """

    def __init__(
        self,
        adapters: list[SourceAdapter] | None = None,
        state_path: str | os.PathLike[str] | None = None,
    ):
        self.adapters: list[SourceAdapter] = list(adapters or [])
        self.state_path = Path(state_path or DEFAULT_STATE_PATH)
        self._snapshots: dict[str, SourceSnapshot] = {}

    # ------------------------------------------------------------------
    def register(self, adapter: SourceAdapter) -> None:
        self.adapters.append(adapter)

    def available_adapters(self) -> list[SourceAdapter]:
        return [a for a in self.adapters if a.is_available()]

    # ------------------------------------------------------------------
    def load_state(self) -> None:
        self._snapshots = {}
        if not self.state_path.is_file():
            return
        try:
            with self.state_path.open(encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return  # 상태 파일이 깨졌으면 전체를 신규로 본다
        for name, entry in blob.get("sources", {}).items():
            self._snapshots[name] = SourceSnapshot(
                source=name, fingerprints=entry.get("fingerprints", {})
            )

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "sources": {
                name: {"fingerprints": snapshot.fingerprints}
                for name, snapshot in self._snapshots.items()
            },
        }
        tmp = self.state_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(self.state_path)

    # ------------------------------------------------------------------
    def plan(self, only: list[SourceKind] | None = None) -> UpdatePlan:
        """
        읽을 수 있는 소스를 훑어 변경 내역을 만든다. 상태는 바꾸지 않는다
        (``--check`` 가 이 결과만 보고한다).
        """
        self.load_state()
        plan = UpdatePlan()
        for adapter in self.available_adapters():
            if only and adapter.kind not in only:
                continue
            records = adapter.load_records()
            snapshot = self._snapshots.get(
                adapter.kind.value, SourceSnapshot(source=adapter.kind.value)
            )
            plan.per_source[adapter.kind.value] = snapshot.diff(records)
        return plan

    def commit(self, only: list[SourceKind] | None = None) -> UpdatePlan:
        """변경을 반영하고 지문을 갱신한다."""
        plan = self.plan(only=only)
        for adapter in self.available_adapters():
            if only and adapter.kind not in only:
                continue
            records = adapter.load_records()
            snapshot = self._snapshots.setdefault(
                adapter.kind.value, SourceSnapshot(source=adapter.kind.value)
            )
            snapshot.update(records)
        self.save_state()
        return plan

    # ------------------------------------------------------------------
    def collect(self, only: list[SourceKind] | None = None) -> dict[int, list[SourceRecord]]:
        """카드 ID -> 그 카드에 대해 각 소스가 제공한 기록들."""
        collected: dict[int, list[SourceRecord]] = {}
        for adapter in self.available_adapters():
            if only and adapter.kind not in only:
                continue
            for card_id, record in adapter.load_records().items():
                collected.setdefault(card_id, []).append(record)
        return collected
