"""
외부 Duel Simulator 세션 한 번 — 계획을 만들고 브라우저 조작기를 돌린다
(Phase 6-AX).

CLI(``scripts/duel_simulator_share.py``) 와 디스코드 입구(``app.site_share``)
가 **같은 이 함수**를 부른다. 그래서 두 자리의 동작이 갈라지지 않는다.

🔴 **공유는 되돌릴 수 없는 공개다.** ``share=True`` 일 때만 공유 URL 을
만들고, 그때도 조작기가 **최종 상태 확인에 성공했을 때만** 만든다
(조작기 쪽 규율). URL 이 실제로 만들어지지 않으면 :attr:`SiteRunResult.
share_url` 은 ``None`` 이고, 부르는 쪽은 성공 링크를 적지 않는다.

🔴 **브라우저는 오래 걸린다** (실측 1~2분). 부르는 쪽이 이벤트 루프를 막지
않게 스레드나 작업 큐로 보내야 한다 — 이 함수는 동기다.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["SiteRunResult", "SITE_URL", "prepare_run_dir", "run_site_session"]

SITE_URL = "https://duel-simulator.miyauchidp.dev/"

_ROOT = Path(__file__).resolve().parent.parent
_DRIVER = _ROOT / "scripts" / "duel_simulator_driver.js"
#: 실측 1~2분. 넉넉히 두되 **끝없이 기다리지 않는다**.
DEFAULT_TIMEOUT = 420.0


@dataclass(frozen=True)
class SiteRunResult:
    """사이트에서 실제로 일어난 일. 🔴 **일어나지 않은 것은 비어 있다.**"""

    ok: bool = False
    share_url: "str | None" = None
    share_requested: bool = False
    stopped_at: "str | None" = None
    stopped_reason: "str | None" = None
    operations_ok: int = 0
    operations_total: int = 0
    final_ok: bool = False
    workdir: "Path | None" = None
    notes: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)

    @property
    def shared(self) -> bool:
        """🔴 **URL 이 실제로 생겼을 때만** 참이다."""
        return bool(self.share_url)


def prepare_run_dir(record, workdir, *, title: str) -> dict:
    """작업 디렉터리에 계획 · 기록 · 덱 시트를 쓰고 계획을 돌려준다."""
    from deck.site_plan import build_site_plan, plan_json, render_deck_sheet_html

    plan = build_site_plan(record)
    path = Path(workdir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "plan.json").write_text(plan_json(plan), encoding="utf-8")
    (path / "replay.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (path / "deck-sheet.html").write_text(
        render_deck_sheet_html(plan, title=title), encoding="utf-8")
    return plan


def run_site_session(record, *, workdir, title: str, share: bool = False,
                     timeout: float = DEFAULT_TIMEOUT,
                     runner=None) -> SiteRunResult:
    """
    계획을 만들고 브라우저 조작기를 한 번 돌린다.

    ``runner`` 를 주면 그것을 대신 부른다 (시험용 — 브라우저를 열지 않는다).
    """
    path = Path(workdir)
    prepare_run_dir(record, path, title=title)
    command = ["node", str(_DRIVER), str(path), "--title", title]
    if share:
        command.append("--share")

    if runner is not None:
        done = runner(command, path)
    else:
        try:
            done = subprocess.run(command, cwd=str(_ROOT), capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return SiteRunResult(
                ok=False, share_requested=share, workdir=path,
                stopped_at="timeout",
                stopped_reason=f"브라우저 조작이 {int(timeout)}초 안에 "
                               f"끝나지 않았습니다.")
        except OSError as error:
            return SiteRunResult(
                ok=False, share_requested=share, workdir=path,
                stopped_at="launch",
                stopped_reason=f"조작기를 실행하지 못했습니다: {error}")

    result_path = path / "result.json"
    if not result_path.exists():
        tail = (getattr(done, "stderr", "") or "").strip()[-300:]
        return SiteRunResult(
            ok=False, share_requested=share, workdir=path,
            stopped_at="no-result",
            stopped_reason="조작기가 결과를 남기지 못했습니다."
                           + (f" ({tail})" if tail else ""))
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    operations = raw.get("operations") or []
    final = (raw.get("stages") or {}).get("final") or {}
    return SiteRunResult(
        ok=raw.get("stopped_at") is None,
        share_url=raw.get("share_url") or None,
        share_requested=bool(raw.get("share_requested")),
        stopped_at=raw.get("stopped_at"),
        stopped_reason=raw.get("stopped_reason"),
        operations_ok=sum(1 for op in operations if op.get("ok")),
        operations_total=len(operations),
        final_ok=bool(final.get("all_ok")),
        workdir=path,
        notes=tuple(raw.get("notes") or ()),
        raw=raw,
    )
