"""
공식 카드별 재정(Card Ruling) 모델.

네 계층 중 세 번째다.

=========================  ======================================
계층                        권위 있는 출처
=========================  ======================================
General Rules              공식 룰북           (``rules/``)
Card Data                  공식 카드 텍스트     (``core/``, ``sources/``)
**Card Rulings**           **공식 카드별 Q&A**  (여기)
Card Implementation        Lua                (``analysis/``)
=========================  ======================================

계층을 섞지 않는다. 룰북은 "체인이 어떻게 굴러가는가"를, 재정은 "이 카드에서는
어떻게 되는가"를 말한다. 하나의 레코드에 합치면 둘 중 어느 쪽 권위로 판단해야
하는지 알 수 없게 된다.

두 가지 원칙
------------
**원문이 authoritative 다.** 공식 일본어 원문만 권위를 갖는다. 번역은
:class:`RulingTranslation` 으로 따로 붙고 **절대 원문 자리에 들어가지 않는다.**

**"재정 없음"과 "확인 실패"는 다르다.** :class:`RulingAvailability` 가 셋을
구분한다. 사이트에 못 갔다는 이유로 "이 카드에는 재정이 없다"고 말하지
않기 위해서다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum

SCHEMA_VERSION = 1


class RulingSource(str, Enum):
    """재정이 어디서 왔는가. **공식 출처만 있다.**"""

    KONAMI_OCG_DATABASE = "konami_ocg_database"
    """https://www.db.yugioh-card.com/yugiohdb/ (遊戯王ニューロン)"""


class RulingGame(str, Enum):
    """어느 규칙 체계의 재정인가. OCG 와 TCG 를 한 레코드에 섞지 않는다."""

    OCG = "ocg"
    TCG = "tcg"
    """이번 구현에서는 수집하지 않는다. 형식만 분리해 둔다."""


class RulingKind(str, Enum):
    """재정의 종류. Q&A 와 補足情報 는 성격이 다르므로 합치지 않는다."""

    QA = "qa"
    """카드별 Q&A. 질문과 답이 짝을 이룬다."""
    SUPPLEMENT = "supplement"
    """카드 페이지의 補足情報. 질문이 없는 보충 설명이다."""


class RulingAvailability(str, Enum):
    """
    이 카드의 재정을 확인한 결과. 네 가지를 **절대 뭉뚱그리지 않는다.**

    =====================  ==================================================
    상태                    뜻
    =====================  ==================================================
    ``EXISTS``             공식 사이트에서 재정을 실제로 확인했다
    ``NOT_FOUND``          정상 조회했고, 이 카드에는 재정이 없다
    ``SOURCE_UNAVAILABLE`` 조회를 **시도했으나** 실패했다 (접근·파싱·네트워크)
    ``NOT_CHECKED``        아직 **조회를 시도한 적이 없다**
    =====================  ==================================================

    뒤의 둘을 합치면 "아직 손도 안 댄 14,353장"이 "사이트가 죽어서 못 봤다"로
    둔갑한다. 재시도 대상인지 최초 수집 대상인지도 구분할 수 없게 된다.
    앞의 둘과 뒤의 둘을 섞으면 "확인 안 했다"가 "재정이 없다"가 된다.
    """

    EXISTS = "ruling_exists"
    """공식 사이트에서 재정을 실제로 확인했다."""
    NOT_FOUND = "ruling_not_found"
    """정상적으로 조회했고, 이 카드에는 재정이 없었다."""
    SOURCE_UNAVAILABLE = "source_unavailable"
    """조회를 시도했으나 실패했다. **아무것도 결론 내리지 않는다.**"""
    NOT_CHECKED = "not_checked"
    """조회를 시도한 적이 없다. 실패한 것과 다르다 — 그냥 아직 안 했다."""


class TranslationSource(str, Enum):
    """번역이 어디서 왔는가. 공식 출처와 **같은 값을 쓰지 않는다.**"""

    MACHINE_TRANSLATION = "machine_translation"
    HUMAN_TRANSLATION = "human_translation"
    OFFICIAL_TRANSLATION = "official_translation"
    """공식이 직접 낸 번역본이 생기면 쓴다. 지금은 존재하지 않는다."""


class TranslationStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


def content_hash(*parts: str) -> str:
    """내용 지문. 공식 사이트에서 문구가 바뀌었는지 판단하는 유일한 근거다."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8"))
        digest.update(b"\x00")
    return f"sha256:{digest.hexdigest()}"


# HTML 이 접어주는 공백만. 전각 공백(U+3000)은 접지 않는다 —
# 공식 카드명에 들어가므로(「魔弾の射手　カスパール」) 접으면 서로 다른
# 문구가 같은 지문을 갖게 되어 변경을 놓친다.
_HASH_SPACE = " \t\r\f"
_RE_HASH_SPACE = re.compile(f"[{_HASH_SPACE}]+")


def normalize_text(text: str) -> str:
    """지문 계산용으로 HTML 공백만 정리한다. **원문 자체는 바꾸지 않는다.**"""
    return _RE_HASH_SPACE.sub(" ", text).strip(_HASH_SPACE)


@dataclass(frozen=True, slots=True)
class RulingProvenance:
    """
    재정 하나의 출처.

    카드 provenance(:mod:`core.provenance`) 와도, 룰북 provenance
    (:mod:`rules.rule_model`) 와도 별개다. 갱신 주기와 권위 판정 방식이 다르다.
    """

    source: RulingSource = RulingSource.KONAMI_OCG_DATABASE
    language: str = "ja"
    authority: str = "official"
    data_type: str = "card_ruling"
    game: RulingGame = RulingGame.OCG
    source_url: str = ""
    retrieved_at: str = ""

    def to_json(self) -> dict:
        return {
            "source": self.source.value,
            "language": self.language,
            "authority": self.authority,
            "data_type": self.data_type,
            "game": self.game.value,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_json(cls, raw: dict) -> "RulingProvenance":
        return cls(
            source=RulingSource(raw.get("source", "konami_ocg_database")),
            language=raw.get("language", "ja"),
            authority=raw.get("authority", "official"),
            data_type=raw.get("data_type", "card_ruling"),
            game=RulingGame(raw.get("game", "ocg")),
            source_url=raw.get("source_url", ""),
            retrieved_at=raw.get("retrieved_at", ""),
        )


@dataclass(slots=True)
class RulingTranslation:
    """
    번역. **원문과 같은 provenance 를 갖지 못한다.**

    ``source`` 가 :class:`TranslationSource` 이지 :class:`RulingSource` 가
    아닌 것이 그 장치다. 타입이 달라서 공식 출처 자리에 들어갈 수 없다.

    이번 단계에서 번역기를 구현하지 않는다. 자리만 만들어 둔다.
    """

    language: str
    source: TranslationSource
    status: TranslationStatus = TranslationStatus.DRAFT
    question: str = ""
    answer: str = ""
    text: str = ""
    """補足情報 번역. Q&A 면 비어 있다."""
    translator: str = ""
    translated_at: str = ""
    source_content_hash: str = ""
    """번역할 때 본 원문의 지문. 원문이 바뀌면 번역이 낡았다는 것을 알 수 있다."""

    @property
    def authoritative(self) -> bool:
        """번역은 **언제나** 권위를 갖지 않는다."""
        return False

    def is_stale(self, current_hash: str) -> bool:
        return bool(self.source_content_hash) and self.source_content_hash != current_hash

    def to_json(self) -> dict:
        return {
            "language": self.language,
            "source": self.source.value,
            "status": self.status.value,
            "question": self.question,
            "answer": self.answer,
            "text": self.text,
            "translator": self.translator,
            "translated_at": self.translated_at,
            "source_content_hash": self.source_content_hash,
        }

    @classmethod
    def from_json(cls, raw: dict) -> "RulingTranslation":
        return cls(
            language=raw["language"],
            source=TranslationSource(raw["source"]),
            status=TranslationStatus(raw.get("status", "draft")),
            question=raw.get("question", ""),
            answer=raw.get("answer", ""),
            text=raw.get("text", ""),
            translator=raw.get("translator", ""),
            translated_at=raw.get("translated_at", ""),
            source_content_hash=raw.get("source_content_hash", ""),
        )


@dataclass(slots=True)
class CardRuling:
    """
    공식 카드별 Q&A 하나.

    ``question_original`` / ``answer_original`` 이 권위 있는 본문이고,
    **일본어 그대로다.** 한국어는 :attr:`translations` 에만 들어간다.
    """

    ruling_id: str
    """``OCG-QA-<fid>``. ``fid`` 는 공식 사이트의 Q&A ID 다."""
    card_id: int | None
    """저장소 패스코드. 매핑이 없으면 ``None`` 이고, ``official_cid`` 는 남는다."""
    official_cid: int
    kind: RulingKind = RulingKind.QA
    question_original: str = ""
    answer_original: str = ""
    published_or_updated_at: str = ""
    """공식 페이지의 更新日 (YYYY-MM-DD). 없으면 빈 문자열."""
    ruling_category: str = ""
    """공식 페이지가 붙인 태그 (モンスター · 魔法 · 罠 등). 만들어 내지 않는다."""
    related_card_cids: list[int] = field(default_factory=list)
    """본문 안에서 공식 사이트가 직접 링크한 카드들의 ``cid``."""
    related_card_ids: list[int] = field(default_factory=list)
    """위 ``cid`` 를 매핑으로 옮긴 패스코드."""
    provenance: RulingProvenance = field(default_factory=RulingProvenance)
    content_hash: str = ""
    translations: dict[str, RulingTranslation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = self.compute_hash()

    def compute_hash(self) -> str:
        return content_hash(
            normalize_text(self.question_original),
            normalize_text(self.answer_original),
            self.published_or_updated_at,
            self.ruling_category,
        )

    @property
    def fid(self) -> int:
        return int(self.ruling_id.rsplit("-", 1)[1])

    @property
    def source_url(self) -> str:
        return self.provenance.source_url

    def translation(self, language: str) -> RulingTranslation | None:
        return self.translations.get(language)

    def add_translation(self, translation: RulingTranslation) -> None:
        """번역을 붙인다. 원문은 건드리지 않는다."""
        translation.source_content_hash = translation.source_content_hash or self.content_hash
        self.translations[translation.language] = translation

    def to_json(self) -> dict:
        return {
            "ruling_id": self.ruling_id,
            "card_id": self.card_id,
            "official_cid": self.official_cid,
            "kind": self.kind.value,
            "question_original": self.question_original,
            "answer_original": self.answer_original,
            "published_or_updated_at": self.published_or_updated_at,
            "ruling_category": self.ruling_category,
            "related_card_cids": self.related_card_cids,
            "related_card_ids": self.related_card_ids,
            "provenance": self.provenance.to_json(),
            "content_hash": self.content_hash,
            "translations": {
                k: v.to_json() for k, v in sorted(self.translations.items())
            },
        }

    @classmethod
    def from_json(cls, raw: dict) -> "CardRuling":
        return cls(
            ruling_id=raw["ruling_id"],
            card_id=raw.get("card_id"),
            official_cid=int(raw["official_cid"]),
            kind=RulingKind(raw.get("kind", "qa")),
            question_original=raw.get("question_original", ""),
            answer_original=raw.get("answer_original", ""),
            published_or_updated_at=raw.get("published_or_updated_at", ""),
            ruling_category=raw.get("ruling_category", ""),
            related_card_cids=list(raw.get("related_card_cids", ())),
            related_card_ids=list(raw.get("related_card_ids", ())),
            provenance=RulingProvenance.from_json(raw.get("provenance", {})),
            content_hash=raw.get("content_hash", ""),
            translations={
                k: RulingTranslation.from_json(v)
                for k, v in (raw.get("translations") or {}).items()
            },
        )

    def __str__(self) -> str:
        return f"{self.ruling_id} cid={self.official_cid}"


@dataclass(slots=True)
class CardRulingSupplement:
    """
    카드 페이지의 補足情報.

    **Q&A 와 같은 타입이 아니다.** 질문이 없고, 카드당 하나이며, 자기 갱신
    날짜를 따로 갖는다. 하나의 텍스트 필드로 합치면 "이것이 질문에 대한 답인지
    카드에 대한 보충인지"를 구분할 수 없게 된다.
    """

    ruling_id: str
    """``OCG-SUP-<cid>``."""
    card_id: int | None
    official_cid: int
    kind: RulingKind = RulingKind.SUPPLEMENT
    text_original: str = ""
    published_or_updated_at: str = ""
    related_card_cids: list[int] = field(default_factory=list)
    related_card_ids: list[int] = field(default_factory=list)
    provenance: RulingProvenance = field(
        default_factory=lambda: RulingProvenance(data_type="card_supplement")
    )
    content_hash: str = ""
    translations: dict[str, RulingTranslation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = self.compute_hash()

    def compute_hash(self) -> str:
        return content_hash(
            normalize_text(self.text_original), self.published_or_updated_at
        )

    @property
    def source_url(self) -> str:
        return self.provenance.source_url

    def translation(self, language: str) -> RulingTranslation | None:
        return self.translations.get(language)

    def add_translation(self, translation: RulingTranslation) -> None:
        translation.source_content_hash = translation.source_content_hash or self.content_hash
        self.translations[translation.language] = translation

    def to_json(self) -> dict:
        return {
            "ruling_id": self.ruling_id,
            "card_id": self.card_id,
            "official_cid": self.official_cid,
            "kind": self.kind.value,
            "text_original": self.text_original,
            "published_or_updated_at": self.published_or_updated_at,
            "related_card_cids": self.related_card_cids,
            "related_card_ids": self.related_card_ids,
            "provenance": self.provenance.to_json(),
            "content_hash": self.content_hash,
            "translations": {
                k: v.to_json() for k, v in sorted(self.translations.items())
            },
        }

    @classmethod
    def from_json(cls, raw: dict) -> "CardRulingSupplement":
        return cls(
            ruling_id=raw["ruling_id"],
            card_id=raw.get("card_id"),
            official_cid=int(raw["official_cid"]),
            text_original=raw.get("text_original", ""),
            published_or_updated_at=raw.get("published_or_updated_at", ""),
            related_card_cids=list(raw.get("related_card_cids", ())),
            related_card_ids=list(raw.get("related_card_ids", ())),
            provenance=RulingProvenance.from_json(raw.get("provenance", {})),
            content_hash=raw.get("content_hash", ""),
            translations={
                k: RulingTranslation.from_json(v)
                for k, v in (raw.get("translations") or {}).items()
            },
        )

    def __str__(self) -> str:
        return f"{self.ruling_id} cid={self.official_cid}"


@dataclass(slots=True)
class CardRulingSet:
    """
    카드 한 장에 대해 확인한 결과 전부.

    재정이 하나도 없어도 이 레코드는 남는다. **"없다"는 것도 확인 결과이기
    때문이다.** 확인하지 못한 경우와 구분하려면 둘 다 기록해야 한다.
    """

    official_cid: int
    card_id: int | None = None
    availability: RulingAvailability = RulingAvailability.NOT_CHECKED
    """기본값은 '아직 안 함' 이다. 채우지 않은 레코드가 '실패' 를 주장하지 않도록."""
    name_ja: str | None = None
    """공식 페이지가 보여준 일본어 카드명. 식별자 검증에 쓴다."""
    card_text_ja: str = ""
    rulings: list[CardRuling] = field(default_factory=list)
    supplement: CardRulingSupplement | None = None
    reported_total: int | None = None
    """공식 페이지가 밝힌 "全N件". 실제로 받은 개수와 대조한다."""
    checked_at: str = ""
    source_url: str = ""
    error: str = ""
    """``SOURCE_UNAVAILABLE`` 일 때 무엇이 실패했는지."""

    @property
    def has_rulings(self) -> bool:
        return bool(self.rulings) or self.supplement is not None

    @property
    def confirmed(self) -> bool:
        """조회 자체가 정상이었는가 (재정 유무와는 별개)."""
        return self.availability in (
            RulingAvailability.EXISTS,
            RulingAvailability.NOT_FOUND,
        )

    @property
    def attempted(self) -> bool:
        """조회를 시도라도 해 봤는가. 재시도 대상과 최초 수집 대상을 가른다."""
        return self.availability is not RulingAvailability.NOT_CHECKED

    @property
    def complete(self) -> bool:
        """공식이 밝힌 개수를 다 받았는가."""
        return self.reported_total is None or len(self.rulings) >= self.reported_total

    def all_entries(self) -> list[CardRuling | CardRulingSupplement]:
        entries: list[CardRuling | CardRulingSupplement] = list(self.rulings)
        if self.supplement is not None:
            entries.append(self.supplement)
        return entries

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "official_cid": self.official_cid,
            "card_id": self.card_id,
            "availability": self.availability.value,
            "name_ja": self.name_ja,
            "card_text_ja": self.card_text_ja,
            "reported_total": self.reported_total,
            "checked_at": self.checked_at,
            "source_url": self.source_url,
            "error": self.error,
            "supplement": self.supplement.to_json() if self.supplement else None,
            "rulings": [r.to_json() for r in self.rulings],
        }

    @classmethod
    def from_json(cls, raw: dict) -> "CardRulingSet":
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"모르는 schema_version: {raw.get('schema_version')!r}")
        supplement = raw.get("supplement")
        return cls(
            official_cid=int(raw["official_cid"]),
            card_id=raw.get("card_id"),
            availability=RulingAvailability(raw["availability"]),
            name_ja=raw.get("name_ja"),
            card_text_ja=raw.get("card_text_ja", ""),
            rulings=[CardRuling.from_json(r) for r in raw.get("rulings", ())],
            supplement=CardRulingSupplement.from_json(supplement) if supplement else None,
            reported_total=raw.get("reported_total"),
            checked_at=raw.get("checked_at", ""),
            source_url=raw.get("source_url", ""),
            error=raw.get("error", ""),
        )

    def __str__(self) -> str:
        return (
            f"cid={self.official_cid} {self.availability.value} "
            f"qa={len(self.rulings)} supplement={'있음' if self.supplement else '없음'}"
        )
