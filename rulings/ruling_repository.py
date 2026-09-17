"""
재정 저장소.

``data/rulings/ocg/<cid>.json`` 을 읽어 카드별 재정을 조회한다.

:class:`~core.card_repository.CardRepository` 와 **합치지 않는다.** 카드 검색은
비트마스크 필터를, 재정 검색은 일본어 문서를 다룬다. 갱신 주기도 다르고
(카드는 신제품 발매 시, 재정은 수시), 권위 판정도 다르다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    CardRulingSupplement,
    RulingAvailability,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULING_DIR = PROJECT_ROOT / "data" / "rulings" / "ocg"


class RulingDataError(RuntimeError):
    """재정 데이터가 스키마를 어겼을 때."""


class RulingRepository:
    """카드별 재정 적재 · 조회 계층."""

    def __init__(self, ruling_sets: list[CardRulingSet]):
        self._by_cid: dict[int, CardRulingSet] = {}
        self._by_card_id: dict[int, CardRulingSet] = {}
        # 하나의 공식 Q&A 가 여러 카드의 페이지에 실린다 — 두 카드의 상호작용을
        # 다루는 재정은 양쪽 카드 페이지에 모두 나온다 (실측: fid=21953 이
        # 青眼の白龍 과 サイクロン 양쪽에 있다). 그래서 ruling_id 는 카드가 아니라
        # **재정**의 식별자이고, 사본이 여럿 있을 수 있다.
        self._copies: dict[str, list[CardRuling | CardRulingSupplement]] = {}
        for ruling_set in sorted(ruling_sets, key=lambda s: s.official_cid):
            if ruling_set.official_cid in self._by_cid:
                raise RulingDataError(f"cid 중복: {ruling_set.official_cid}")
            self._by_cid[ruling_set.official_cid] = ruling_set
            if ruling_set.card_id is not None:
                self._by_card_id[ruling_set.card_id] = ruling_set
            for entry in ruling_set.all_entries():
                self._copies.setdefault(entry.ruling_id, []).append(entry)

    # ------------------------------------------------------------------
    # 적재 · 저장
    # ------------------------------------------------------------------
    @classmethod
    def load(
        cls,
        ruling_dir: str | os.PathLike[str] | None = None,
        missing_ok: bool = False,
    ) -> "RulingRepository":
        directory = Path(ruling_dir or DEFAULT_RULING_DIR)
        if not directory.is_dir():
            if missing_ok:
                return cls([])
            raise RulingDataError(
                f"재정 디렉터리가 없습니다: {directory}\n"
                "python -m scripts.fetch_ocg_rulings --sample 로 만드세요."
            )
        sets: list[CardRulingSet] = []
        for path in sorted(directory.glob("*.json")):
            try:
                sets.append(CardRulingSet.from_json(
                    json.loads(path.read_text(encoding="utf-8"))
                ))
            except (ValueError, KeyError) as error:
                raise RulingDataError(f"{path} 를 읽지 못했습니다: {error}") from error
        return cls(sets)

    @staticmethod
    def save_ruling_set(
        ruling_set: CardRulingSet, ruling_dir: str | os.PathLike[str] | None = None
    ) -> Path:
        directory = Path(ruling_dir or DEFAULT_RULING_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{ruling_set.official_cid}.json"
        path.write_text(
            json.dumps(ruling_set.to_json(), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        return path

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def ruling_set(self, cid: int) -> CardRulingSet | None:
        return self._by_cid.get(cid)

    def by_card_id(self, card_id: int) -> CardRulingSet | None:
        return self._by_card_id.get(card_id)

    def by_cid(self, cid: int) -> CardRulingSet | None:
        return self._by_cid.get(cid)

    def ruling(self, ruling_id: str) -> CardRuling | CardRulingSupplement | None:
        """대표 사본 하나. 사본끼리 본문은 같고 실린 카드만 다르다."""
        copies = self._copies.get(ruling_id)
        return copies[0] if copies else None

    def copies_of(self, ruling_id: str) -> list[CardRuling | CardRulingSupplement]:
        """이 재정이 실린 모든 카드 페이지의 사본."""
        return list(self._copies.get(ruling_id, ()))

    def cids_for_ruling(self, ruling_id: str) -> list[int]:
        """이 재정을 자기 페이지에 싣고 있는 카드들의 ``cid``."""
        return sorted({e.official_cid for e in self._copies.get(ruling_id, ())})

    def card_ids_for_ruling(self, ruling_id: str) -> list[int]:
        return sorted(
            {
                e.card_id
                for e in self._copies.get(ruling_id, ())
                if e.card_id is not None
            }
        )

    def availability_for_card(self, card_id: int) -> RulingAvailability:
        """
        이 카드의 재정 상태.

        기록이 없으면 ``NOT_CHECKED`` 다 — **"재정이 없다"도 아니고 "사이트가
        죽었다"도 아니다.** 그냥 아직 조회하지 않았다는 뜻이다.
        """
        ruling_set = self._by_card_id.get(card_id)
        return (
            ruling_set.availability
            if ruling_set is not None
            else RulingAvailability.NOT_CHECKED
        )

    def availability_for_cid(self, cid: int) -> RulingAvailability:
        ruling_set = self._by_cid.get(cid)
        return (
            ruling_set.availability
            if ruling_set is not None
            else RulingAvailability.NOT_CHECKED
        )

    def rulings_for_card(self, card_id: int) -> list[CardRuling]:
        ruling_set = self._by_card_id.get(card_id)
        return list(ruling_set.rulings) if ruling_set else []

    def supplement_for_card(self, card_id: int) -> CardRulingSupplement | None:
        ruling_set = self._by_card_id.get(card_id)
        return ruling_set.supplement if ruling_set else None

    def referencing(self, card_id: int) -> list[CardRuling | CardRulingSupplement]:
        """이 카드를 본문에서 언급한 다른 카드의 재정."""
        return [e for e in self if card_id in e.related_card_ids]

    def related_card_closure(self, card_id: int, depth: int = 1) -> set[int]:
        """
        이 카드에서 출발해 공식 링크를 ``depth`` 홉까지 따라간 카드 집합.

        **순환 보호가 필수다.** 공식 페이지는 본문에서 자기 자신을 링크하므로
        (실측 596건 중 525건) 방문 집합 없이 따라가면 즉시 무한 루프가 된다.
        서로를 링크하는 카드 쌍도 마찬가지다.

        결과에 출발 카드는 포함하지 않는다 — 자기 자신은 "관련 카드"가 아니다.
        """
        if depth < 1:
            return set()
        visited: set[int] = {card_id}
        frontier: set[int] = {card_id}
        for _ in range(depth):
            following: set[int] = set()
            for current in frontier:
                ruling_set = self._by_card_id.get(current)
                if ruling_set is None:
                    continue
                for entry in ruling_set.all_entries():
                    following.update(entry.related_card_ids)
            frontier = following - visited
            if not frontier:
                break
            visited |= frontier
        return visited - {card_id}

    def __contains__(self, cid: object) -> bool:
        return isinstance(cid, int) and cid in self._by_cid

    def __len__(self) -> int:
        """**서로 다른 재정**의 개수. 사본은 한 번만 센다."""
        return len(self._copies)

    def __iter__(self) -> Iterator[CardRuling | CardRulingSupplement]:
        """재정마다 대표 사본 하나씩. 같은 재정을 두 번 돌려주지 않는다."""
        for ruling_id in sorted(self._copies):
            yield self._copies[ruling_id][0]

    def ruling_ids(self) -> list[str]:
        return sorted(self._copies)

    @property
    def ruling_sets(self) -> list[CardRulingSet]:
        return [self._by_cid[cid] for cid in sorted(self._by_cid)]

    def qa_entries(self) -> list[CardRuling]:
        return [e for e in self if isinstance(e, CardRuling)]

    def supplements(self) -> list[CardRulingSupplement]:
        return [e for e in self if isinstance(e, CardRulingSupplement)]

    # ------------------------------------------------------------------
    def check_integrity(self) -> list[str]:
        problems: list[str] = []
        for ruling_set in self._by_cid.values():
            if ruling_set.availability is RulingAvailability.EXISTS and not ruling_set.has_rulings:
                problems.append(
                    f"cid={ruling_set.official_cid} 는 재정 있음인데 내용이 비었습니다."
                )
            if ruling_set.availability is RulingAvailability.NOT_FOUND and ruling_set.has_rulings:
                problems.append(
                    f"cid={ruling_set.official_cid} 는 재정 없음인데 내용이 있습니다."
                )
            if not ruling_set.complete:
                problems.append(
                    f"cid={ruling_set.official_cid}: 공식 {ruling_set.reported_total}건 중 "
                    f"{len(ruling_set.rulings)}건만 받았습니다."
                )
            for entry in ruling_set.all_entries():
                if entry.official_cid != ruling_set.official_cid:
                    problems.append(f"{entry.ruling_id} 의 cid 가 어긋납니다.")
                if entry.content_hash != entry.compute_hash():
                    problems.append(f"{entry.ruling_id} 의 content_hash 가 본문과 다릅니다.")
                if entry.provenance.language != "ja":
                    problems.append(f"{entry.ruling_id} 의 원문 언어가 ja 가 아닙니다.")
        # 같은 재정이 여러 카드 페이지에 실렸다면 본문은 같아야 한다.
        for ruling_id, copies in self._copies.items():
            digests = {c.content_hash for c in copies}
            if len(digests) > 1:
                problems.append(
                    f"{ruling_id} 의 사본들이 서로 다른 내용을 갖습니다: "
                    f"cid={self.cids_for_ruling(ruling_id)}"
                )
        return problems

    def stats(self) -> dict[str, int]:
        counts = {
            "cards_checked": len(self._by_cid),
            "qa": len(self.qa_entries()),
            "supplements": len(self.supplements()),
            "qa_listings": sum(
                len(c) for rid, c in self._copies.items() if rid.startswith("OCG-QA-")
            ),
        }
        for availability in RulingAvailability:
            counts[availability.value] = sum(
                1 for s in self._by_cid.values() if s.availability is availability
            )
        return counts
