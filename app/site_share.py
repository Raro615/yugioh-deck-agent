"""
디스코드에서 외부 Duel Simulator 공유를 부르는 입구 (Phase 6-AX).

규율 넷
-------
🔴 **봇의 응답 처리를 막지 않는다.** 브라우저 조작은 실측 1~2분이다. 부르는
쪽이 ``asyncio.to_thread`` 로 보내고, 디스코드에는 ``defer()`` 로 먼저
응답을 연다 (``/combo`` 와 같은 구조).

🔴 **동시 요청이 브라우저 상태를 섞지 않는다.** 한 번에 하나만 돈다
(:class:`SiteShareRunner` 의 한 칸짜리 자물쇠). 돌고 있는 중에 들어온 요청은
기다리지 않고 **바쁘다고 답한다** — 두 세션이 같은 사이트에서 동시에
조작하면 어느 쪽 기록인지 알 수 없게 된다.

🔴 **URL 하나로 성공을 판정하지 않는다** (6-AY). 이번 실행이 끝까지 갔고,
조작이 모두 확인됐고, 최종 판 검증을 통과했고, 그러고도 URL 이 있을 때만
성공이다 (``SiteRunResult.shared``). 실패하면 짧은 이유와 함께, 기존 HTML
리플레이로 계속 볼 수 있다고 적는다.

🔴 **요청마다 다른 폴더에서 돈다** (6-AY). 전에는 고정 폴더를 써서, 새
실행이 결과를 쓰기 전에 죽으면 지난번 성공 URL 이 이번 요청의 성공으로
돌아올 수 있었다. 이제 실행 ID 로 폴더를 가르고 결과의 ID 를 맞춘다.

🔴 **외부 공유가 일어나는 조작임을 입구에서 알린다.** 공유 URL 은 접근
제어가 없고, 올린 것을 이용자가 스스로 지울 수 없다 (사이트 가이드라인
7절).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "ShareState", "SiteShareOutcome", "SiteShareRunner",
    "SITE_SHARE_WARNING", "site_share_lines",
]

#: 🔴 입구에서 **먼저** 보여 주는 경고. 누르면 바깥에 공개된다.
SITE_SHARE_WARNING = (
    "🌐 **외부 사이트(Duel Simulator)에 리플레이를 공개합니다.**"
    " 공유 URL 은 접근 제어가 없어 링크를 아는 누구나 열 수 있고,"
    " 올라간 덱 시트·리플레이를 나중에 스스로 지울 수 없습니다."
)

#: 실패했을 때 — 🔴 **기존 길이 그대로 살아 있다고 적는다.**
SITE_SHARE_FALLBACK = (
    "첨부된 `combo-replay.html` 로는 그대로 재생할 수 있습니다."
)


class ShareState(str, Enum):
    """한 번의 시도가 어디서 끝났는가."""

    NO_RECORD = "no_record"
    BUSY = "busy"
    FAILED = "failed"
    SHARED = "shared"

    @property
    def notice(self) -> str:
        return {
            ShareState.NO_RECORD:
                "🔴 **전개 기록이 없어 외부 공유를 하지 않았습니다.**",
            ShareState.BUSY:
                "⏳ **다른 공유 작업이 돌고 있습니다** — 한 번에 하나만"
                " 처리합니다. 잠시 뒤 다시 시도해 주세요.",
            ShareState.FAILED:
                "🔴 **외부 공유를 만들지 못했습니다.**",
            ShareState.SHARED:
                "🌐 **외부 리플레이 공유 완료**",
        }[self]


@dataclass(frozen=True)
class SiteShareOutcome:
    """한 번의 시도 결과. 🔴 ``url`` 은 **실제로 생겼을 때만** 들어간다."""

    state: ShareState
    url: "str | None" = None
    reason: "str | None" = None
    run_id: str = ""
    operations_ok: int = 0
    operations_total: int = 0


class SiteShareRunner:
    """
    사이트 공유를 **한 번에 하나만** 돌린다.

    ``session`` 을 주면 그것을 대신 부른다 (시험용 — 브라우저를 열지 않는다).
    """

    def __init__(self, base_dir="docs/viewer/local/duel-simulator-discord",
                 *, session=None):
        #: 🔴 **기준 폴더**다. 실제 실행은 그 아래의 새 폴더에서 돈다.
        self._base = Path(base_dir)
        self._lock = threading.Lock()
        self._session = session

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def share(self, record, *, title: str,
              registration=None) -> SiteShareOutcome:
        """🔴 동기다 — 부르는 쪽이 스레드로 보낸다."""
        if not record:
            return SiteShareOutcome(ShareState.NO_RECORD)
        #: 🔴 기다리지 않는다 — 기다리면 디스코드 쪽이 먼저 끊긴다.
        if not self._lock.acquire(blocking=False):
            return SiteShareOutcome(ShareState.BUSY)
        try:
            #: 🔴 **브라우저가 없으면 바로 말한다** — 1~2분 기다리게 하지
            #: 않는다 (사용자 PC 에 node·playwright 가 없을 수 있다).
            if self._session is None:
                from deck.site_session import preflight

                ready = preflight()
                if not ready.ready:
                    return SiteShareOutcome(
                        ShareState.FAILED,
                        reason="이 서버에 브라우저가 준비되지 않았습니다")
            run = self._run(record, title=title,
                            registration=registration)
        except Exception as error:  # pragma: no cover - 방어용
            logger.warning("외부 공유 중 예외: %s: %s",
                           type(error).__name__, error)
            return SiteShareOutcome(
                ShareState.FAILED, reason="조작 중 오류가 났습니다")
        finally:
            self._lock.release()

        if run.shared:
            return SiteShareOutcome(
                ShareState.SHARED, url=run.share_url,
                run_id=run.run_id,
                operations_ok=run.operations_ok,
                operations_total=run.operations_total)
        #: 🔴 **URL 이 있어도** 검증을 통과하지 못했으면 성공이 아니다.
        return SiteShareOutcome(
            ShareState.FAILED, reason=run.reason or "확인하지 못했습니다",
            run_id=run.run_id,
            operations_ok=run.operations_ok,
            operations_total=run.operations_total)

    def _run(self, record, *, title: str, registration=None):
        if self._session is not None:
            return self._session(record, base_dir=self._base, title=title,
                                 share=True, registration=registration)
        from deck.site_session import run_site_session

        #: 🔴 ``base_dir`` 이라서 **이번 실행만의 새 폴더**가 만들어진다.
        return run_site_session(record, base_dir=self._base, title=title,
                                share=True, registration=registration)


def site_share_lines(outcome: SiteShareOutcome) -> list[str]:
    """사용자에게 보일 줄들. 🔴 **없는 링크를 적지 않는다.**"""
    head = outcome.state.notice
    if outcome.state is ShareState.SHARED:
        progress = (f" (사이트 조작 {outcome.operations_ok}/"
                    f"{outcome.operations_total}건 확인)"
                    if outcome.operations_total else "")
        return [f"{head}{progress}", str(outcome.url)]
    lines = [head]
    if outcome.reason:
        lines[0] = f"{head} — {outcome.reason}"
    if outcome.state in (ShareState.FAILED, ShareState.BUSY):
        lines.append(SITE_SHARE_FALLBACK)
    return lines
