"""
카드 식별자 매핑 — 저장소의 ``card_id`` <-> 코나미 공식 ``cid``.

왜 필요한가
-----------
한국어 카드명과 일본어 카드명은 **문자열이 전혀 다르다.**

===========  ==========  ===================
passcode     한국어       일본어
===========  ==========  ===================
2511         라뷰린스 쿠클락  白銀の城の狂時計
24224830     무덤의 지명자    墓穴の指名者
===========  ==========  ===================

앞의 예는 음차와 의역이 섞여 있어 어떤 문자열 유사도로도 이어지지 않는다.
그래서 카드명으로 매칭하지 않고 **숫자 식별자로만** 잇는다.

세 가지 식별자
--------------
``card_id`` (passcode)
    ``cards.cdb`` 와 Lua 스크립트, 한국어 데이터가 모두 쓰는 저장소의 기본 키.
    **새로 만들지 않는다.**
``cid``
    코나미 공식 데이터베이스의 카드 ID. 공식 사이트 URL 파라미터다.
    일러스트 판본이 여러 개여도 ``cid`` 는 하나이므로 ``cid`` 하나에
    패스코드가 여럿 달릴 수 있다 (실측 14,362개 중 120개).
``fid``
    공식 Q&A 하나의 ID. 카드가 아니라 재정을 가리킨다
    (:mod:`rulings.ruling_model` 참고).

출처와 검증
-----------
``cid`` 값 자체는 공식 사이트에서 왔다. 하지만 **``cid`` 와 패스코드를 잇는
링크는 보조 출처(YGOPRODeck ``misc_info.konami_id``)에서 온 추론**이다.
이 사실을 숨기지 않고 :class:`CardIdentityMapping` 이 그대로 들고 있다.

추론을 그대로 믿지 않기 위해 **독립된 두 출처의 일본어 카드명을 대조**한다.

- 패스코드 -> 일본어 카드명 : Lua 스크립트 주석 (``LuaScriptInfo.name_ja``)
- ``cid``  -> 일본어 카드명 : 코나미 공식 페이지

둘이 일치하면 그 항목은 ``verified`` 다. 유사도 점수를 쓰지 않는다 —
**NFKC 정규화 후 완전 일치**만 인정한다 (:func:`same_card_name`).

NFKC 를 거치는 이유는 실측 때문이다. Lua 주석은 전각 라틴 문자를 쓰고
공식 페이지는 반각을 쓰는 카드가 있다::

    Lua  : ＳＰＹＲＡＬ－ボルテックス
    공식 : SPYRAL－ボルテックス

같은 카드인데 바이트가 달라서, 그냥 ``==`` 로 비교하면 **멀쩡한 링크가
충돌로 찍혀 조회에서 빠진다.** NFKC 는 유사도가 아니라 유니코드가 정한
결정론적 정규형이므로, 이것을 쓴다고 해서 "문자열 유사도로 매칭"하는 것이
되지는 않는다.
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IDENTITY_PATH = PROJECT_ROOT / "data" / "identity" / "cid_map.json"

SCHEMA_VERSION = 1


def same_card_name(left: str | None, right: str | None) -> bool:
    """
    두 일본어 카드명이 같은 카드를 가리키는가.

    NFKC 정규화 후 **완전 일치**. 유사도 계산은 하지 않는다.
    """
    if not left or not right:
        return False
    return unicodedata.normalize("NFKC", left) == unicodedata.normalize("NFKC", right)


class LinkSource(str, Enum):
    """``cid`` <-> 패스코드 링크가 어디서 왔는가."""

    YGOPRODECK_KONAMI_ID = "ygoprodeck_konami_id"
    """보조 출처의 ``misc_info.konami_id``. **공식 출처가 아니다.**"""
    CARD_ALIAS = "card_alias"
    """
    같은 카드의 다른 일러스트 판본. ``cards.cdb`` 의 ``alias`` 컬럼이 원본
    패스코드를 가리키므로, 원본의 ``cid`` 를 그대로 물려받는다.

    추론이 아니라 **공식 DB 가 직접 밝힌 동일성**이다. 이것을 넣지 않으면
    엔진이 다른 일러스트 패스코드를 들고 있을 때 재정을 조용히 못 찾는다.
    """
    MANUAL = "manual"
    """사람이 직접 확인해 넣은 링크."""


class LinkStatus(str, Enum):
    """링크를 얼마나 믿을 수 있는가."""

    VERIFIED = "verified"
    """공식 페이지의 일본어 카드명이 Lua 의 일본어 카드명과 정확히 일치했다."""
    UNVERIFIED = "unverified"
    """아직 대조하지 않았다. 틀렸다는 뜻이 아니라 확인하지 않았다는 뜻이다."""
    CONFLICT = "conflict"
    """대조했더니 이름이 달랐다. **이 링크는 쓰면 안 된다.**"""


@dataclass(slots=True)
class CardIdentity:
    """카드 한 장의 식별자 묶음."""

    card_id: int
    """저장소의 패스코드."""
    cid: int
    """코나미 공식 카드 ID."""
    link_source: LinkSource = LinkSource.YGOPRODECK_KONAMI_ID
    status: LinkStatus = LinkStatus.UNVERIFIED
    name_ja: str | None = None
    """공식 페이지에서 읽은 일본어 카드명 (검증했을 때만 채워진다)."""
    verified_at: str | None = None
    note: str = ""

    @property
    def trusted(self) -> bool:
        """
        **공식 재정 조회에 써도 되는 링크인가.**

        ``VERIFIED`` 일 때만 참이다. ``UNVERIFIED`` 는 틀렸다는 뜻이 아니지만
        맞다는 뜻도 아니므로, 공식 출처에 "이 카드의 재정을 달라" 고 물을
        근거가 되지 못한다. 엉뚱한 ``cid`` 로 물으면 **다른 카드의 공식 재정이
        이 카드의 것으로 저장된다.**
        """
        return self.status is LinkStatus.VERIFIED

    @property
    def is_candidate(self) -> bool:
        """
        링크 후보로 볼 수 있는가 (충돌로 판명나지 않았는가).

        :attr:`trusted` 와 **다른 질문이다.** 후보가 있다는 것과 그 후보를
        공식 조회에 써도 된다는 것은 별개다.
        """
        return self.status is not LinkStatus.CONFLICT

    @property
    def from_alias(self) -> bool:
        """공식 DB 의 alias 를 따라 물려받은 링크인가."""
        return self.link_source is LinkSource.CARD_ALIAS

    def to_json(self) -> dict:
        data = {
            "card_id": self.card_id,
            "cid": self.cid,
            "link_source": self.link_source.value,
            "status": self.status.value,
        }
        if self.name_ja:
            data["name_ja"] = self.name_ja
        if self.verified_at:
            data["verified_at"] = self.verified_at
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_json(cls, raw: dict) -> "CardIdentity":
        return cls(
            card_id=int(raw["card_id"]),
            cid=int(raw["cid"]),
            link_source=LinkSource(raw.get("link_source", "ygoprodeck_konami_id")),
            status=LinkStatus(raw.get("status", "unverified")),
            name_ja=raw.get("name_ja"),
            verified_at=raw.get("verified_at"),
            note=raw.get("note", ""),
        )


class IdentityError(RuntimeError):
    """매핑이 일관되지 않을 때."""


class CardIdentityMapping:
    """
    ``card_id`` <-> ``cid`` 양방향 조회.

    한 패스코드는 정확히 하나의 ``cid`` 를 갖는다. 반대는 1:N 이다
    (같은 카드의 다른 일러스트 판본).
    """

    def __init__(self, entries: list[CardIdentity], built_at: str = "", note: str = ""):
        self.built_at = built_at
        self.note = note
        self._by_card_id: dict[int, CardIdentity] = {}
        self._by_cid: dict[int, list[CardIdentity]] = {}
        for entry in entries:
            if entry.card_id in self._by_card_id:
                existing = self._by_card_id[entry.card_id]
                if existing.cid != entry.cid:
                    raise IdentityError(
                        f"패스코드 {entry.card_id} 에 cid 가 둘입니다: "
                        f"{existing.cid} / {entry.cid}"
                    )
                continue
            self._by_card_id[entry.card_id] = entry
            self._by_cid.setdefault(entry.cid, []).append(entry)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def cid_for(self, card_id: int) -> int | None:
        """
        패스코드 -> **``cid`` 후보.** 충돌로 판명난 링크는 돌려주지 않는다.

        .. warning::
           돌려준 값이 **검증되었다는 뜻이 아니다.** 공식 사이트에 재정을
           물으려면 :meth:`verified_cid_for` 를 쓴다. 이 메서드는
           "후보가 존재하는가" 에만 답한다.
        """
        entry = self._by_card_id.get(card_id)
        return entry.cid if entry is not None and entry.is_candidate else None

    def verified_cid_for(self, card_id: int) -> int | None:
        """
        패스코드 -> **공식 재정 조회에 써도 되는 ``cid``.**

        대조를 마친 링크에서만 값이 나온다. 대조하지 않았으면 ``None`` 이다 —
        틀렸다는 뜻이 아니라, 이 값으로 공식 출처에 물을 근거가 아직 없다는
        뜻이다.
        """
        entry = self._by_card_id.get(card_id)
        return entry.cid if entry is not None and entry.trusted else None

    def status_for(self, card_id: int) -> LinkStatus | None:
        """이 패스코드의 링크 상태. 매핑 자체가 없으면 ``None``."""
        entry = self._by_card_id.get(card_id)
        return entry.status if entry is not None else None

    def identity(self, card_id: int) -> CardIdentity | None:
        return self._by_card_id.get(card_id)

    def card_ids_for(self, cid: int) -> list[int]:
        """
        ``cid`` -> 패스코드 **후보** 목록 (일러스트 판본이 여럿일 수 있다).

        검증 여부를 묻지 않는다. 이 방향은 "공식 재정을 달라" 는 요청이 아니라
        "공식이 링크한 이 ``cid`` 가 우리 쪽 어느 카드인가" 라는 표시용
        조회이기 때문이다. 충돌 링크만 제외한다.
        """
        return sorted(e.card_id for e in self._by_cid.get(cid, ()) if e.is_candidate)

    def primary_card_id(self, cid: int) -> int | None:
        """``cid`` 를 대표하는 패스코드 후보 하나 (가장 작은 값으로 고정한다)."""
        card_ids = self.card_ids_for(cid)
        return card_ids[0] if card_ids else None

    def verified_card_ids(self) -> list[int]:
        """공식 재정 조회에 쓸 수 있는 패스코드 전부."""
        return sorted(e.card_id for e in self._by_card_id.values() if e.trusted)

    def __contains__(self, card_id: object) -> bool:
        return isinstance(card_id, int) and card_id in self._by_card_id

    def __len__(self) -> int:
        return len(self._by_card_id)

    def __iter__(self) -> Iterator[CardIdentity]:
        return iter(self._by_card_id.values())

    @property
    def cids(self) -> list[int]:
        return sorted(self._by_cid)

    def by_status(self, status: LinkStatus) -> list[CardIdentity]:
        return [e for e in self._by_card_id.values() if e.status is status]

    def stats(self) -> dict[str, int]:
        counts = {"card_ids": len(self._by_card_id), "cids": len(self._by_cid)}
        for status in LinkStatus:
            counts[status.value] = len(self.by_status(status))
        return counts

    # ------------------------------------------------------------------
    # 적재 · 저장
    # ------------------------------------------------------------------
    @classmethod
    def load(
        cls, path: str | os.PathLike[str] | None = None
    ) -> "CardIdentityMapping":
        file_path = Path(path or DEFAULT_IDENTITY_PATH)
        if not file_path.is_file():
            raise IdentityError(
                f"식별자 매핑이 없습니다: {file_path}\n"
                "python -m scripts.build_card_identity 로 만드세요."
            )
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise IdentityError(
                f"모르는 schema_version: {raw.get('schema_version')!r}"
            )
        return cls(
            entries=[CardIdentity.from_json(e) for e in raw["entries"]],
            built_at=raw.get("built_at", ""),
            note=raw.get("note", ""),
        )

    @classmethod
    def try_load(
        cls, path: str | os.PathLike[str] | None = None
    ) -> "CardIdentityMapping | None":
        try:
            return cls.load(path)
        except IdentityError:
            return None

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "built_at": self.built_at,
            "note": self.note,
            "entries": [
                e.to_json()
                for e in sorted(self._by_card_id.values(), key=lambda x: x.card_id)
            ],
        }

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        file_path = Path(path or DEFAULT_IDENTITY_PATH)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        return file_path
