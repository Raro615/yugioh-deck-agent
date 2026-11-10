"""
외부 Duel Simulator 세션 한 번 — 계획을 만들고 브라우저 조작기를 돌린다
(Phase 6-AX · 6-AY 에서 실행 격리).

CLI(``scripts/duel_simulator_share.py``) 와 디스코드 입구(``app.site_share``)
가 **같은 이 함수**를 부른다. 그래서 두 자리의 동작이 갈라지지 않는다.

🔴 **요청마다 다른 자리에서 돈다** (6-AY). 전에는 고정된 작업 폴더를 쓰고
거기 남아 있는 ``result.json`` 을 읽었다. 새 실행이 **결과를 쓰기 전에**
죽으면 지난번 성공 결과를 이번 요청의 성공으로 돌려줄 수 있었다. 이제

* 요청마다 **실행 ID**(:func:`new_run_id`) 를 만들고,
* ``<기준 폴더>/<시각>-<실행 ID>/`` 라는 **빈 폴더**에서 돌리고,
* 계획과 결과에 그 ID 를 넣어 **돌아온 결과가 이번 것인지** 확인한다.

그래서 옛 결과가 이번 요청의 성공으로 돌아오는 길이 없다. 지난 실행의
산출물은 자기 폴더에 **그대로 남는다** (지우지 않는다).

🔴 **실패를 한 덩어리로 뭉치지 않는다.** :class:`RunStatus` 가 실행 실패 ·
시간 초과 · 결과 파일 없음 · JSON 깨짐 · 실행 ID 불일치 · 조작 중단을
가른다.

🔴 **브라우저는 오래 걸린다** (실측 1~2분). 부르는 쪽이 이벤트 루프를 막지
않게 스레드나 작업 큐로 보내야 한다 — 이 함수는 동기다. 시간이 초과되면
자식 **프로세스 그룹 전체**를 끝낸다 (node 만 죽이면 크로뮴이 남는다).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

__all__ = [
    "SiteRunResult", "RunStatus", "SITE_URL", "DEFAULT_TIMEOUT",
    "new_run_id", "prepare_run_dir", "run_site_session", "preflight",
    "BrowserReadiness",
]

SITE_URL = "https://duel-simulator.miyauchidp.dev/"

_ROOT = Path(__file__).resolve().parent.parent
_DRIVER = _ROOT / "scripts" / "duel_simulator_driver.js"
#: 실측 1~2분. 넉넉히 두되 **끝없이 기다리지 않는다**.
DEFAULT_TIMEOUT = 420.0


class RunStatus(str, Enum):
    """한 번의 실행이 어디서 끝났는가. 🔴 **실패를 뭉치지 않는다.**"""

    OK = "ok"
    STOPPED = "stopped"
    TIMEOUT = "timeout"
    LAUNCH_FAILED = "launch_failed"
    MISSING_RESULT = "missing_result"
    BAD_JSON = "bad_json"
    RUN_ID_MISMATCH = "run_id_mismatch"

    @property
    def detail(self) -> str:
        return {
            RunStatus.OK: "조작과 검증을 끝냈습니다",
            RunStatus.STOPPED: "조작 도중 멈췄습니다",
            RunStatus.TIMEOUT: "브라우저 조작이 시간 안에 끝나지 않았습니다",
            RunStatus.LAUNCH_FAILED: "조작기를 실행하지 못했습니다",
            RunStatus.MISSING_RESULT: "조작기가 결과 파일을 남기지 못했습니다",
            RunStatus.BAD_JSON: "결과 파일을 읽지 못했습니다 (JSON 이 깨졌습니다)",
            RunStatus.RUN_ID_MISMATCH:
                "결과 파일이 이번 요청의 것이 아닙니다 (실행 ID 불일치)",
        }[self]


@dataclass(frozen=True)
class BrowserReadiness:
    """
    브라우저를 **돌리기 전에** 확인한 결과 (Phase 6-AY).

    🔴 이 컨테이너에 깔려 있다는 이유로 사용자 PC 에도 있다고 가정하지
    않는다. 없으면 무엇을 어떻게 깔아야 하는지 :attr:`hints` 가 적는다.
    """

    ready: bool = False
    node: str = ""
    playwright: str = ""
    chromium: str = ""
    problems: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()

    def message(self) -> str:
        if self.ready:
            return (f"브라우저 준비됨 (node {self.node} · playwright "
                    f"{self.playwright})")
        lines = ["🔴 브라우저를 돌릴 수 없습니다:"]
        lines += [f"  - {line}" for line in self.problems]
        if self.hints:
            lines.append("  설치 명령 (저장소 폴더에서):")
            lines += [f"    {line}" for line in self.hints]
        return "\n".join(lines)


def preflight(node: str = "node") -> BrowserReadiness:
    """``node`` · ``playwright`` · 크로뮴이 **지금 여기** 있는지 확인한다."""
    checker = _ROOT / "scripts" / "check_browser.js"
    if not checker.exists():  # pragma: no cover - 저장소 손상
        return BrowserReadiness(problems=("확인 스크립트가 없습니다",))
    try:
        done = subprocess.run([node, str(checker)], cwd=str(_ROOT),
                              capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return BrowserReadiness(
            problems=(f"{node} 를 찾지 못했습니다 (Node.js 가 없습니다)",),
            hints=("https://nodejs.org 에서 LTS 를 설치한 뒤 새 터미널에서"
                   " node -v 로 확인하십시오",))
    except (OSError, subprocess.TimeoutExpired) as error:
        return BrowserReadiness(problems=(f"확인 중 오류: {error}",))
    try:
        got = json.loads((done.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return BrowserReadiness(
            problems=("브라우저 확인 결과를 읽지 못했습니다",
                      (done.stderr or "").strip()[-200:] or "출력이 없습니다"),
            hints=("npm install", "npx playwright install chromium"))
    return BrowserReadiness(
        ready=bool(got.get("ready")), node=str(got.get("node") or ""),
        playwright=str(got.get("playwright") or ""),
        chromium=str(got.get("chromium") or ""),
        problems=tuple(got.get("problems") or ()),
        hints=tuple(got.get("hints") or ()))


def new_run_id() -> str:
    """요청 하나를 가리키는 짧은 ID."""
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class SiteRunResult:
    """사이트에서 실제로 일어난 일. 🔴 **일어나지 않은 것은 비어 있다.**"""

    run_id: str = ""
    status: RunStatus = RunStatus.LAUNCH_FAILED
    share_url: "str | None" = None
    share_requested: bool = False
    stopped_at: "str | None" = None
    stopped_reason: "str | None" = None
    operations_ok: int = 0
    operations_total: int = 0
    final_ok: bool = False
    exit_code: "int | None" = None
    workdir: "Path | None" = None
    notes: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.OK

    @property
    def shared(self) -> bool:
        """
        🔴 **공유 성공은 URL 하나로 판정하지 않는다.**

        이번 실행이 끝까지 갔고(``status is OK``), 모든 조작이 확인됐고,
        최종 판 검증을 통과했고, 그러고도 URL 이 있을 때만 참이다.
        """
        return bool(
            self.share_url
            and self.status is RunStatus.OK
            and self.final_ok
            and self.operations_total > 0
            and self.operations_ok == self.operations_total
        )

    @property
    def reason(self) -> str:
        """사람에게 보일 한 줄."""
        if self.stopped_reason:
            return self.stopped_reason
        if self.status is not RunStatus.OK:
            return self.status.detail
        if not self.final_ok:
            return "최종 판이 기록과 달라 공유하지 않았습니다"
        if self.share_requested and not self.share_url:
            return "공유 URL 을 받지 못했습니다"
        return ""


def _run_dir(base: "str | Path", run_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(base) / f"{stamp}-{run_id}"
    #: 🔴 **빈 폴더에서 시작한다** — 남아 있던 결과를 읽을 길이 없다.
    path.mkdir(parents=True, exist_ok=False)
    return path


def prepare_run_dir(record, workdir, *, title: str, run_id: str = "") -> dict:
    """작업 폴더에 계획 · 기록 · 덱 시트를 쓰고 계획을 돌려준다."""
    from deck.site_plan import build_site_plan, plan_json, render_deck_sheet_html

    plan = build_site_plan(record)
    #: 🔴 계획에도 실행 ID 를 적는다 — 조작기가 결과에 그대로 옮긴다.
    plan["run_id"] = run_id
    path = Path(workdir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "plan.json").write_text(plan_json(plan), encoding="utf-8")
    (path / "replay.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (path / "deck-sheet.html").write_text(
        render_deck_sheet_html(plan, title=title), encoding="utf-8")
    return plan


def _spawn(command, timeout: float):
    """
    조작기를 돌린다. 🔴 시간이 초과되면 **프로세스 그룹 전체**를 끝낸다 —
    node 만 죽이면 크로뮴이 남아 다음 요청과 겹친다.
    """
    popen_kwargs = {"cwd": str(_ROOT), "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE, "text": True}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    else:  # pragma: no cover - 윈도우
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        _out, err = process.communicate(timeout=timeout)
        return process.returncode, err or "", False
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            _out, err = process.communicate(timeout=20)
        except Exception:  # pragma: no cover - 방어용
            err = ""
        return process.returncode, err or "", True


def _kill_tree(process) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:  # pragma: no cover - 윈도우
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover
        try:
            process.kill()
        except Exception:
            pass


def run_site_session(record, *, workdir=None, base_dir=None, title: str,
                     share: bool = False, timeout: float = DEFAULT_TIMEOUT,
                     run_id: "str | None" = None, runner=None) -> SiteRunResult:
    """
    계획을 만들고 브라우저 조작기를 **한 번** 돌린다.

    ``base_dir`` 을 주면 그 아래에 이번 실행만의 폴더를 새로 만든다 (권장).
    ``workdir`` 을 직접 주면 그 폴더를 쓴다 — 그때도 실행 ID 로 결과가
    이번 것인지 확인한다.

    ``runner`` 를 주면 그것을 대신 부른다 (시험용 — 브라우저를 열지 않는다).
    🔴 **자동으로 다시 시도하지 않는다** — 공유가 두 번 생길 수 있다.
    """
    rid = run_id or new_run_id()
    if base_dir is not None:
        path = _run_dir(base_dir, rid)
    elif workdir is not None:
        path = Path(workdir)
        path.mkdir(parents=True, exist_ok=True)
    else:  # pragma: no cover - 부르는 쪽 실수
        raise TypeError("base_dir 또는 workdir 중 하나는 주어야 합니다")

    prepare_run_dir(record, path, title=title, run_id=rid)
    command = ["node", str(_DRIVER), str(path), "--run-id", rid,
               "--title", title]
    if share:
        command.append("--share")

    def _fail(status: RunStatus, extra: str = "") -> SiteRunResult:
        return SiteRunResult(run_id=rid, status=status, share_requested=share,
                             workdir=path, exit_code=code,
                             stopped_reason=status.detail
                             + (f" ({extra})" if extra else ""))

    code: "int | None" = None
    if runner is not None:
        done = runner(command, path)
        code = getattr(done, "returncode", 0)
        timed_out = bool(getattr(done, "timed_out", False))
        stderr = getattr(done, "stderr", "") or ""
    else:
        try:
            code, stderr, timed_out = _spawn(command, timeout)
        except OSError as error:
            code = None
            return _fail(RunStatus.LAUNCH_FAILED, str(error)[:160])

    if timed_out:
        return _fail(RunStatus.TIMEOUT, f"{int(timeout)}초")

    result_path = path / "result.json"
    if not result_path.exists():
        return _fail(RunStatus.MISSING_RESULT, stderr.strip()[-200:])
    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        return _fail(RunStatus.BAD_JSON, str(error)[:160])
    if not isinstance(raw, dict):
        return _fail(RunStatus.BAD_JSON, "최상위가 객체가 아닙니다")
    #: 🔴 **이번 요청의 결과인가.** 다르면 남아 있던 옛 결과다.
    if str(raw.get("run_id") or "") != rid:
        return _fail(RunStatus.RUN_ID_MISMATCH,
                     f"결과의 ID {raw.get('run_id')!r}")

    operations = raw.get("operations") or []
    final = (raw.get("stages") or {}).get("final") or {}
    stopped_at = raw.get("stopped_at")
    return SiteRunResult(
        run_id=rid,
        status=RunStatus.OK if stopped_at is None else RunStatus.STOPPED,
        share_url=raw.get("share_url") or None,
        share_requested=bool(raw.get("share_requested")),
        stopped_at=stopped_at,
        stopped_reason=raw.get("stopped_reason"),
        operations_ok=sum(1 for op in operations if op.get("ok")),
        operations_total=len(operations),
        final_ok=bool(final.get("all_ok")),
        exit_code=code,
        workdir=path,
        notes=tuple(raw.get("notes") or ()),
        raw=raw,
    )
