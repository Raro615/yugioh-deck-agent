"""
공동 추천 후보를 **요청 단위로 들고 있는 자리** (Phase 6-BH).

왜 필요한가
-----------
자율 탐색은 여러 후보를 **공동 추천**으로 내놓는데 (우열을 가리지 못한
서로 다른 최종 상태들), 첨부와 사이트 재생은 기록 **하나**만 담을 수 있다.
6-BG 까지 그 하나는 늘 "표시 순서가 가장 앞선 추천" 이었고, 사용자가 다른
후보를 고를 길이 없었다.

🔴 **고르는 것이 탐색을 다시 돌리는 일이 되면 안 된다.** 같은 입력으로 다시
돌려도 예산 · 시간 상한에 걸리는 자리가 달라질 수 있고, 그러면 **후보 번호와
경로가 바뀐다** — 사용자가 본 번호가 다른 전개를 가리키게 된다. 그래서 이
모듈이 **그때 그 탐색 결과를** 들고 있다가 고른 후보만 다시 실행한다.

지키는 것
---------
🔴 **요청과 후보를 묶어 둔다.** 번호만으로 찾지 않는다 — 요청 ID 와 **그
요청을 만든 사람**이 함께 맞아야 한다. 그래서 다른 요청(다른 패 · 다른 덱)의
후보 번호가 섞이지 않는다.

🔴 **오래된 것은 사라진다.** 탐색 결과는 무겁고 (후보 수십 개의 경로와 자원
요약), 봇은 오래 돈다. 그래서 수명과 개수에 **상한**을 두고, 사라진 것을
고르면 **"없다" 가 아니라 "만료됐다"** 고 말한다.

🔴 **여기서 판정하지 않는다.** 어느 후보가 추천인지, 재실행이 되는지는 이
모듈이 모른다 — 받은 값을 그대로 보관하고 그대로 돌려준다.

🔴 **값만 보관한다.** ``Duel`` 도 ``GameState`` 도 담지 않는다 — 담으면 지난
요청의 판이 살아 있게 되고, 그것을 뒤의 실행이 건드릴 수 있다. 담는 것은
초안(``DeckDraft``) · 패 번호 · 탐색 결과 객체(경로와 자원 **요약**)다.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "PickProblem", "StoredRequest", "CandidateStore", "CandidateStoreError",
    "DEFAULT_TTL", "DEFAULT_CAPACITY",
]

#: 보관 수명 (초). 🔴 **짧게 둔다** — 탐색 결과는 무겁다.
DEFAULT_TTL: float = 1800.0

#: 동시에 들고 있는 요청 수. 넘으면 **가장 오래된 것**부터 버린다.
DEFAULT_CAPACITY: int = 8

#: 요청 ID 의 길이 (바이트). 사람이 복사할 만큼 짧고, 추측하기는 어렵다.
_ID_BYTES: int = 4

#: 버린 ID 를 **몇 개까지** 기억할 것인가. 🔴 끝없이 쌓지 않는다 — 기억은
#: "만료됐다" 를 정확히 말하기 위한 것이고, 그 말이 필요한 기간은 짧다.
_GONE_MEMORY: int = 64


class CandidateStoreError(RuntimeError):
    """보관소를 쓰는 방법이 틀렸을 때."""


class PickProblem(str, Enum):
    """
    고르기가 **왜** 안 됐는가. 🔴 **뭉치지 않는다** — 사용자가 할 일이 다르다.
    """

    UNKNOWN_REQUEST = "unknown_request"
    EXPIRED = "expired"
    NOT_MINE = "not_mine"
    NO_SUCH_RESULT = "no_such_result"

    @property
    def detail(self) -> str:
        return {
            PickProblem.UNKNOWN_REQUEST:
                "그 요청 ID 를 찾지 못했습니다 — `/combo` 응답에 적힌 ID 를"
                " 그대로 넣어 주십시오.",
            PickProblem.EXPIRED:
                "그 요청은 만료됐습니다 — 탐색 결과는 일정 시간만 보관합니다."
                " `/combo` 를 다시 돌려 주십시오.",
            PickProblem.NOT_MINE:
                "그 요청은 다른 사람의 것입니다 — 자기 `/combo` 응답의 ID 만"
                " 쓸 수 있습니다.",
            PickProblem.NO_SUCH_RESULT:
                "그 번호의 후보가 그 요청에 없습니다 — `/combo` 응답의 결과"
                " 번호를 그대로 넣어 주십시오.",
        }[self]


@dataclass(frozen=True)
class StoredRequest:
    """
    한 번의 자율 탐색이 남긴 것. 🔴 **값이고, 판이 아니다.**
    """

    request_id: str
    owner: str
    hand_ids: tuple[int, ...]
    draft: object
    results: tuple
    recommended: tuple[int, ...]
    created: float
    picked: int = -1
    """``/combo`` 가 기본으로 고른 후보 번호. -1 은 고르지 못했다는 뜻이다."""

    @property
    def indexes(self) -> tuple[int, ...]:
        """보관한 후보 번호 전부, 적힌 순서대로."""
        return tuple(int(getattr(one, "index")) for one in self.results)

    def result(self, index: int):
        """그 번호의 후보. 없으면 ``None``."""
        for one in self.results:
            if int(getattr(one, "index")) == int(index):
                return one
        return None

    def describe_ko(self) -> str:
        return (f"요청 `{self.request_id}` — 후보 {len(self.results)}개 ·"
                f" 추천 {', '.join(str(i) for i in self.recommended) or '없음'}")


class CandidateStore:
    """
    요청 ID → :class:`StoredRequest`. **스레드 안전**하다.

    🔴 봇은 여러 요청을 동시에 처리하고 (``asyncio.to_thread``), 보관과
    조회가 다른 스레드에서 일어난다. 그래서 자물쇠를 들고 있다 — 자물쇠
    없이 쓰면 버리는 중에 읽어 **반쯤 지워진 목록**을 보게 된다.
    """

    __slots__ = ("_ttl", "_capacity", "_rows", "_lock", "_clock", "_gone")

    def __init__(self, ttl: float = DEFAULT_TTL,
                 capacity: int = DEFAULT_CAPACITY, *, clock=None):
        if ttl <= 0:
            raise CandidateStoreError(f"수명은 0 보다 커야 합니다: {ttl}")
        if capacity <= 0:
            raise CandidateStoreError(f"상한은 0 보다 커야 합니다: {capacity}")
        self._ttl = float(ttl)
        self._capacity = int(capacity)
        self._rows: "dict[str, StoredRequest]" = {}
        #: 🔴 **우리가 버린 ID 들** (최근 것만). 왜 필요한가 — "만료됐다" 와
        #: "그런 ID 를 낸 적이 없다" 는 사용자가 할 일이 다르다. 모양만 보고
        #: 만료라고 **추측하지 않기** 위해 버린 것을 적어 둔다.
        self._gone: "list[str]" = []
        self._lock = threading.Lock()
        #: 🔴 **시계를 주입받는다** — 시험이 만료를 재려고 기다리지 않게.
        self._clock = clock if clock is not None else time.monotonic

    # ------------------------------------------------------------------
    def remember(self, *, owner: str, hand_ids, draft, results,
                 recommended, picked: int = -1) -> StoredRequest:
        """
        그 탐색 결과를 보관하고 **요청 ID 를 돌려준다.**

        🔴 **빈 결과도 보관한다.** 그러면 "없는 요청" 과 "후보가 없는 요청"
        을 사용자에게 가려 말할 수 있다.
        """
        now = float(self._clock())
        row = StoredRequest(
            request_id=secrets.token_hex(_ID_BYTES),
            owner=str(owner),
            hand_ids=tuple(int(card) for card in hand_ids),
            draft=draft,
            results=tuple(results),
            recommended=tuple(int(i) for i in recommended),
            created=now,
            picked=int(picked),
        )
        with self._lock:
            self._evict(now)
            #: 🔴 **상한을 넘으면 가장 오래된 것부터 버린다.**
            while len(self._rows) >= self._capacity:
                oldest = min(self._rows.values(), key=lambda one: one.created)
                self._rows.pop(oldest.request_id, None)
                self._remember_gone(oldest.request_id)
            self._rows[row.request_id] = row
        return row

    def take(self, request_id: str, *, owner: str,
             index=None) -> "tuple[StoredRequest | None, object, PickProblem | None]":
        """
        그 요청의 후보를 꺼낸다 — ``(요청, 후보 | None, 문제 | None)``.

        ``index`` 를 주지 않으면 후보를 찾지 않고 요청만 돌려준다.

        🔴 **세 사실을 가른다.** 요청이 없는 것 · 만료된 것 · 그 번호가 없는
        것이 **다른 답**이다 (:class:`PickProblem`).
        """
        wanted = str(request_id or "").strip()
        now = float(self._clock())
        with self._lock:
            self._evict(now)
            row = self._rows.get(wanted)
        if row is None:
            #: 🔴 **만료와 오타를 가른다 — 추측하지 않고 기록으로.** 우리가
            #: 실제로 버린 ID 면 "만료", 그렇지 않으면 "그런 ID 가 없다" 다.
            with self._lock:
                dropped = wanted in self._gone
            problem = (PickProblem.EXPIRED if dropped
                       else PickProblem.UNKNOWN_REQUEST)
            return None, None, problem
        if row.owner != str(owner):
            return None, None, PickProblem.NOT_MINE
        if index is None:
            return row, None, None
        found = row.result(index)
        if found is None:
            return row, None, PickProblem.NO_SUCH_RESULT
        return row, found, None

    # ------------------------------------------------------------------
    def _evict(self, now: float) -> None:
        """🔴 자물쇠를 **들고 있는 동안** 부른다."""
        dead = [key for key, row in self._rows.items()
                if now - row.created > self._ttl]
        for key in dead:
            self._rows.pop(key, None)
            self._remember_gone(key)

    def _remember_gone(self, request_id: str) -> None:
        """🔴 자물쇠를 **들고 있는 동안** 부른다. 최근 것만 들고 있는다."""
        self._gone.append(request_id)
        if len(self._gone) > _GONE_MEMORY:
            del self._gone[:-_GONE_MEMORY]

    def __len__(self) -> int:
        with self._lock:
            self._evict(float(self._clock()))
            return len(self._rows)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (f"<CandidateStore {len(self._rows)}건 수명 {self._ttl:g}초 "
                f"상한 {self._capacity}>")


