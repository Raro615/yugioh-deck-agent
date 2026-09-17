"""
규칙 문서 저장소.

``data/rules/documents/*.json`` 을 읽어 :class:`~rules.rule_model.RuleDocument`
로 만들고, Rule ID 로 찾을 수 있게 한다.

:class:`~core.card_repository.CardRepository` 와 **섞지 않는다.** 둘은 다루는
대상도, 갱신 주기도, 권위 판정 방식도 다르다. 엔진은 두 저장소를 각각
읽는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator

from rules.rule_model import (
    RuleCategory,
    RuleDocument,
    RuleProvenance,
    RuleRef,
    RuleSection,
    SourceReference,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCUMENT_DIR = PROJECT_ROOT / "data" / "rules" / "documents"

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class RuleDataError(RuntimeError):
    """규칙 데이터가 스키마를 어겼을 때."""


def _section_from_json(raw: dict) -> RuleSection:
    reference = raw["source_reference"]
    return RuleSection(
        rule_id=raw["rule_id"],
        title=raw["title"],
        category=RuleCategory(raw["category"]),
        chapter=raw["chapter"],
        chapter_title=raw["chapter_title"],
        level=raw["level"],
        text=raw["text"],
        source_reference=SourceReference(
            document=reference["document"],
            printed_pages=tuple(reference.get("printed_pages", ())),
            pdf_pages=tuple(reference.get("pdf_pages", ())),
        ),
        anchor=raw.get("anchor", ""),
        title_source=raw.get("title_source", "heading"),
        parent=raw.get("parent"),
        subsections=list(raw.get("subsections", ())),
    )


def load_document(path: str | os.PathLike[str]) -> RuleDocument:
    """문서 JSON 하나를 읽는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RuleDataError(
            f"모르는 schema_version 입니다: {version!r} "
            f"(지원: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
        )
    meta = raw["document"]
    return RuleDocument(
        doc_id=meta["doc_id"],
        title=meta["title"],
        provenance=RuleProvenance(
            source=meta["source"],
            version=meta["version"],
            retrieved_at=meta["retrieved_at"],
            document_hash=meta["document_hash"],
            language=meta.get("language", "en"),
            source_file=meta.get("source_file"),
            extractor=meta.get("extractor"),
        ),
        sections=[_section_from_json(s) for s in raw["sections"]],
    )


class RuleRepository:
    """규칙 문서 적재 · 조회 계층."""

    def __init__(self, documents: Iterable[RuleDocument]):
        self.documents: list[RuleDocument] = list(documents)
        self._by_id: dict[str, RuleSection] = {}
        self._document_of: dict[str, str] = {}
        self._by_category: dict[RuleCategory, list[str]] = {}
        for document in self.documents:
            for section in document.sections:
                if section.rule_id in self._by_id:
                    raise RuleDataError(f"Rule ID 가 중복됩니다: {section.rule_id}")
                self._by_id[section.rule_id] = section
                self._document_of[section.rule_id] = document.doc_id
                self._by_category.setdefault(section.category, []).append(
                    section.rule_id
                )

    # ------------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------------
    @classmethod
    def load(
        cls, document_dir: str | os.PathLike[str] | None = None
    ) -> "RuleRepository":
        directory = Path(document_dir or DEFAULT_DOCUMENT_DIR)
        if not directory.is_dir():
            raise RuleDataError(
                f"규칙 문서 디렉터리가 없습니다: {directory}\n"
                "python -m scripts.extract_rulebook <룰북.pdf> 로 만드세요."
            )
        paths = sorted(directory.glob("*.json"))
        if not paths:
            raise RuleDataError(f"{directory} 에 규칙 문서가 없습니다.")
        return cls(load_document(path) for path in paths)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get(self, rule_id: str | RuleRef) -> RuleSection | None:
        return self._by_id.get(str(rule_id))

    def require(self, rule_id: str | RuleRef) -> RuleSection:
        """없으면 조용히 ``None`` 을 돌려주지 않고 실패한다."""
        section = self.get(rule_id)
        if section is None:
            raise KeyError(f"그런 규칙이 없습니다: {rule_id}")
        return section

    def __contains__(self, rule_id: object) -> bool:
        return isinstance(rule_id, (str, RuleRef)) and str(rule_id) in self._by_id

    def __getitem__(self, rule_id: str | RuleRef) -> RuleSection:
        return self.require(rule_id)

    def __iter__(self) -> Iterator[RuleSection]:
        for document in self.documents:
            yield from document.sections

    def __len__(self) -> int:
        return len(self._by_id)

    def rule_ids(self) -> list[str]:
        return sorted(self._by_id)

    def by_category(self, category: RuleCategory | str) -> list[RuleSection]:
        key = RuleCategory(category) if isinstance(category, str) else category
        return [self._by_id[rid] for rid in self._by_category.get(key, ())]

    def document_of(self, rule_id: str | RuleRef) -> RuleDocument | None:
        doc_id = self._document_of.get(str(rule_id))
        return next((d for d in self.documents if d.doc_id == doc_id), None)

    def children(self, rule_id: str | RuleRef) -> list[RuleSection]:
        return [self.require(child) for child in self.require(rule_id).subsections]

    def path_to(self, rule_id: str | RuleRef) -> list[RuleSection]:
        """최상위 절부터 이 절까지의 경로."""
        chain: list[RuleSection] = []
        current: RuleSection | None = self.require(rule_id)
        while current is not None:
            chain.append(current)
            current = self.get(current.parent) if current.parent else None
        return list(reversed(chain))

    # ------------------------------------------------------------------
    # 무결성
    # ------------------------------------------------------------------
    def check_integrity(self) -> list[str]:
        """문제 목록. 비어 있어야 정상이다."""
        problems: list[str] = []
        for section in self:
            try:
                RuleRef(section.rule_id)
            except ValueError as error:
                problems.append(str(error))
            if not section.text.strip():
                problems.append(f"{section.rule_id} 의 본문이 비어 있습니다.")
            if section.parent and section.parent not in self._by_id:
                problems.append(
                    f"{section.rule_id} 의 부모 {section.parent} 가 없습니다."
                )
            for child in section.subsections:
                if child not in self._by_id:
                    problems.append(f"{section.rule_id} 의 자식 {child} 가 없습니다.")
                elif self._by_id[child].parent != section.rule_id:
                    problems.append(
                        f"{child} 의 부모가 {section.rule_id} 를 가리키지 않습니다."
                    )
        return problems

    def stats(self) -> dict[str, int]:
        counts = {"documents": len(self.documents), "sections": len(self._by_id)}
        for category, ids in sorted(self._by_category.items()):
            counts[category.value] = len(ids)
        return counts
