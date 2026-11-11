"""
외부 Duel Simulator 에서 전개 하나를 **직접 조작하고 기록**한다 (Phase 6-AX).

하는 일
-------
1. 이 저장소의 엔진으로 전개를 실행한다 (고정 경로, 또는 이미 있는 기록).
2. 실행 기록을 **사이트 조작 계획**으로 바꾼다 (``deck.site_plan``).
3. 계획의 덱 자리를 그대로 그린 **자체 제작 자리표시 덱 시트**를 만든다.
4. 브라우저 자동 조작기(``scripts/duel_simulator_driver.js``) 를 불러
   사이트에서 덱을 올리고 조작하고 기록한다.
5. ``--share`` 를 줬을 때만 **공유 URL** 까지 만든다.

사용
----
::

    # 조작만 하고 공유하지 않는다 (기본)
    python3 -m scripts.duel_simulator_share --line orcust-skeleton-longirsu

    # 🔴 공유까지 — 되돌릴 수 없는 공개다
    python3 -m scripts.duel_simulator_share --line orcust-skeleton-longirsu \
        --share --title "オルフェゴール ロンギルス 展開"

    # 계획만 보고 브라우저는 열지 않는다
    python3 -m scripts.duel_simulator_share --line <경로> --plan-only

    # 등록한 덱 이미지 + 지정 패 — 🔴 레시피는 **등록에서 가져온다**
    python3 -m scripts.duel_simulator_share \
        --registration dk0123456789 --owner local \
        --hand "宵星の騎士ギルス, 灰流うらら, 増殖するＧ, 墓穴の指名者, 無限泡影"

필요한 것
---------
* 이 컨테이너에 설치된 Chromium 과 Playwright (Node). 추가 설치는 없다.
* 바깥 통신: ``duel-simulator.miyauchidp.dev`` 하나.

🔴 **공유는 되돌릴 수 없다.** 사이트의 공유 URL 은 접근 제어가 없는
미수록 형식이고, 이용자가 스스로 지우는 기능이 없다 (사이트 가이드라인
7절). 그래서 ``--share`` 는 기본으로 꺼져 있고, 켜면 아래 경고를 찍는다.

🔴 **덱 시트에 카드 그림을 넣지 않는다.** 카드 그림은 권리자의 저작물이고,
이용할 권한이 없는 이미지를 올려 공유로 공개하는 것은 그 사이트의
가이드라인 5절이 금지한다. 그래서 시트는 카드 이름과 패스코드만 담은
자리표시 카드이고, **공식 앱의 내보내기 이미지가 아니다.**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - 실행 편의
    sys.path.insert(0, str(ROOT))

DRIVER = ROOT / "scripts" / "duel_simulator_driver.js"

SHARE_WARNING = """\
🔴 공유(--share)를 켰습니다. 이 조작은 **외부 사이트에 리플레이를 공개**합니다.
   · 공유 URL 은 접근 제어가 없고, 링크를 아는 사람은 누구나 열 수 있습니다.
   · 올린 덱 시트 · 리플레이 · 미리보기 이미지가 운영 서버에 저장됩니다.
   · 이용자가 스스로 지우는 기능은 없습니다 (사이트 가이드라인 7절).
"""


def _run_line(name: str) -> dict:
    """고정 경로를 돌려 기록을 만든다 — 디스코드 ``/combo`` 와 같은 생산 경로."""
    from app.main import opening_wiring
    from core.card_repository import CardRepository
    from deck.combo_policy import (
        COMBO_LINES,
        ORCUST_VERIFICATION_RECIPE,
        line_progress,
    )
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe
    from deck.replay_export import export_opening_replay

    repository = CardRepository.build(
        db_path=ROOT / "data" / "cards.cdb", script_dir=ROOT
    )
    line = COMBO_LINES[name]
    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(repository, draft, list(line.hand),
                          chooser=chooser, triggers=triggers)
    run = execute_opening(setup, repository, choose=line.policy())
    progress = line_progress(run, line)
    return export_opening_replay(setup, run, repository,
                                 line=line, progress=progress)


class _RepositoryOnly:
    """``_run_opening`` 이 쓰는 것은 ``.repository`` 하나뿐이다."""

    def __init__(self, repository):
        self.repository = repository


def _recipe_text_for(args, registration) -> "str | None":
    """
    **어느 레시피로 도는가**를 한 곳에서 정한다 (Phase 6-BA).

    🔴 등록과 레시피를 **둘 다** 줬으면 같은 덱인지 먼저 센다 — 다르면
    돌리지 않는다. 레시피만 빼면 **등록에 저장된 레시피**를 쓴다.
    """
    from core.card_repository import CardRepository
    from deck.deck_image_registry import normalize_recipe

    text = args.recipe or ""
    if text:
        maybe = Path(text)
        try:
            if maybe.exists() and maybe.is_file():
                text = maybe.read_text(encoding="utf-8")
        except OSError:
            pass
    if registration is None:
        if not text.strip():
            print("🔴 --hand 로 돌리려면 --recipe 또는 --registration 이 "
                  "있어야 합니다", file=sys.stderr)
            return None
        return text
    if not text.strip():
        print(f"레시피: 등록 {registration.registration_id} 에 저장된 것을 "
              f"씁니다 (메인 {registration.counts.get('main', 0)} · "
              f"엑스트라 {registration.counts.get('extra', 0)})")
        return registration.recipe_text
    repository = CardRepository.build(db_path=ROOT / "data" / "cards.cdb",
                                      script_dir=ROOT)
    try:
        _norm, digest = normalize_recipe(text, repository)
    except ValueError as error:
        print(f"🔴 레시피를 읽지 못했습니다: {error}", file=sys.stderr)
        return None
    if not registration.matches_recipe(digest):
        print("🔴 적어 주신 레시피가 등록과 다릅니다 — 같은 덱일 때만 "
              "등록한 이미지를 씁니다. --recipe 를 빼면 등록에 저장된 "
              "레시피로 돕니다.", file=sys.stderr)
        return None
    print("레시피: 적어 주신 것과 등록이 같은 덱입니다.")
    return text


def _run_from_hand(args, registration) -> "dict | None":
    """지정한 시작 패로 **디스코드와 같은 생산 경로**를 돌린다."""
    from app.discord_bot import _run_opening
    from app.main import _parse_card_ids
    from core.card_repository import CardRepository

    text = _recipe_text_for(args, registration)
    if text is None:
        return None
    repository = CardRepository.build(db_path=ROOT / "data" / "cards.cdb",
                                      script_dir=ROOT)
    agent = _RepositoryOnly(repository)
    hand_ids, unresolved = _parse_card_ids(args.hand, agent)
    if unresolved:
        print("🔴 패를 읽지 못했습니다: " + ", ".join(unresolved),
              file=sys.stderr)
        return None
    report = _run_opening(agent, text, list(hand_ids), args.line_name)
    if not report.ran or not report.replay:
        for line in report.brief:
            print(line, file=sys.stderr)
        return None
    return report.replay


def main(argv: "list[str] | None" = None) -> int:
    from deck.site_plan import build_site_plan, plan_json, render_deck_sheet_html

    parser = argparse.ArgumentParser(
        description="외부 Duel Simulator 에서 전개를 조작하고 기록한다")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--line", help="고정 경로 이름")
    group.add_argument("--json", help="이미 있는 전개 기록 JSON")
    group.add_argument("--hand",
                       help="시작 패 — 카드 이름이나 ID 를 쉼표로. "
                            "레시피는 --recipe 로 주거나, "
                            "--registration 의 저장된 레시피를 씁니다")
    parser.add_argument("--recipe",
                        help="덱 레시피 글 (또는 파일 경로). "
                             "--registration 을 주면 빼도 됩니다")
    parser.add_argument("--line-name", default="",
                        help="(선택) --hand 와 함께 쓸 검증용 전개 경로 이름")
    parser.add_argument("--out", default="docs/viewer/local/duel-simulator",
                        help="작업 디렉터리 (기본: docs/viewer/local/duel-simulator)")
    parser.add_argument("--plan-only", action="store_true",
                        help="계획과 덱 시트만 만들고 브라우저를 열지 않는다")
    parser.add_argument("--share", action="store_true",
                        help="🔴 공유 URL 까지 만든다 — 되돌릴 수 없는 공개다")
    parser.add_argument("--registration",
                        help="등록해 둔 덱 이미지의 등록 ID "
                             "(scripts.register_deck_image 로 만듭니다)")
    parser.add_argument("--owner", default="local",
                        help="등록 소유자 (기본 local)")
    parser.add_argument("--title", default="galatea opening line",
                        help="공유 리플레이의 제목")
    args = parser.parse_args(argv)

    #: 🔴 **등록을 먼저 읽는다** — 레시피를 등록에서 가져올 수 있으므로
    #: 순서를 바꾸면 "레시피가 없다" 고 먼저 거절해 버린다 (Phase 6-BA).
    registration = None
    if args.registration:
        from deck.deck_image_registry import (load_registration,
                                              registration_image_problem)

        registration = load_registration(args.owner, args.registration)
        if registration is None:
            print(f"🔴 등록을 찾지 못했습니다: {args.registration} "
                  f"(소유자 {args.owner})", file=sys.stderr)
            return 2
        spoiled = registration_image_problem(registration)
        if spoiled:
            print("🔴 " + spoiled, file=sys.stderr)
            return 2
        mark = "확인됨" if registration.verified else "🔴 미확인"
        print(f"덱 이미지 등록 {registration.registration_id} — {mark} · "
              f"{registration.image_path}")

    if args.hand:
        record = _run_from_hand(args, registration)
        if record is None:
            return 2
    elif args.json:
        record = json.loads(Path(args.json).read_text(encoding="utf-8"))
    else:
        record = _run_line(args.line)

    from deck.site_session import (
        new_run_id,
        preflight,
        prepare_run_dir,
        run_site_session,
    )

    #: 🔴 **요청마다 다른 실행 ID 와 폴더.** 남아 있던 옛 결과를 이번
    #: 요청의 성공으로 읽을 길을 없앤다 (6-AY).
    run_id = new_run_id()
    base = Path(args.out)
    out = base if args.plan_only else None
    if out is None:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = base / f"{stamp}-{run_id}"
    plan = prepare_run_dir(record, out, title=args.title, run_id=run_id,
                           registration=registration)

    counts = plan["counts"]
    print(f"계획: 엔진 걸음 {counts['engine_steps']} · 엔진 사건 "
          f"{counts['engine_events']} → 사이트 조작 "
          f"{counts['site_operations']} (+ 시작 패 "
          f"{counts['site_setup_operations']})")
    mode = plan["deck_image"]["mode"]
    print(f"덱 이미지 모드: {mode} · 메인 {len(plan['deck']['main'])} · "
          f"엑스트라 {len(plan['deck']['extra'])}")
    if plan["unsupported"]:
        #: 🔴 **조용히 빠뜨리지 않는다** — 실행 전에 적는다.
        print("사이트에 대응 조작이 없는 사건:")
        for line in plan["unsupported"]:
            print("  -", line)
    if args.plan_only:
        return 0

    #: 🔴 **브라우저가 있는지 먼저 본다.** 없는 채로 띄우면 사용자는
    #: 알 수 없는 오류만 본다.
    ready = preflight()
    print(ready.message())
    if not ready.ready:
        return 2

    if args.share:
        print(SHARE_WARNING)
    print(f"조작기 실행 중… (실행 ID {run_id} · 실측 1~2분)")
    run = run_site_session(record, workdir=out, title=args.title,
                           share=args.share, run_id=run_id,
                           registration=registration)
    if not run.raw:
        print(f"🔴 {run.status.value}: {run.reason}", file=sys.stderr)
        return 1
    _report(run.raw)
    print(f"\n  실행 상태: {run.status.value}"
          f" · 공유 성공 판정: {'예' if run.shared else '아니오'}")
    return 0 if run.ok else 1


def _report(result: dict) -> None:
    stages = result.get("stages") or {}
    print("\n--- 사이트에서 실제로 일어난 일 ---")
    if stages.get("applied"):
        print("  판에 적용:", stages["applied"])
    if stages.get("opening"):
        print("  시작 패 꺼낸 뒤:", stages["opening"])
    ok = sum(1 for op in result.get("operations") or () if op.get("ok"))
    print(f"  조작 {ok} / {len(result.get('operations') or ())} 건 확인됨")
    for op in result.get("operations") or ():
        mark = "✅" if op.get("ok") else "❌"
        print(f"   {mark} {op['n']:2d} {op['op']:8s} {op['card']:9s} "
              f"기대 {op.get('expect','')!r} ← 화면 {op.get('saw','')!r}"
              f" · 카드가 있는 칸 {op.get('where','?')!r}")
        #: 🔴 **개체를 무엇으로 확정했는지** 적는다 (6-AZ).
        print(f"      ↳ 클릭 지점의 개체 {op.get('click_hit','?')}"
              + (f" · 자리 이동 {op['moved']}" if op.get("moved") else "")
              + (f" · 상세 패널 {op['panel']}" if op.get("panel") else "")
              + (f" · (보조) {op['thumbnail']}" if op.get("thumbnail") else ""))
        for line in op.get("reasons") or ():
            print(f"      ↳ 🔴 {line}")
        for line in op.get("problems") or ():
            print(f"      ↳ 판 읽기 문제: {line}")
    final = stages.get("final") or {}
    if final:
        print("  최종 상태 확인:", "✅ 기대와 같음" if final.get("all_ok")
              else "❌ 기대와 다름")
        for check in final.get("checks") or ():
            mark = "✅" if check.get("ok") else "❌"
            extra = ""
            if check.get("missing"):
                extra += f" · 빠진 카드 {check['missing']}"
            if check.get("unexpected"):
                extra += f" · 예상 밖 카드 {check['unexpected']}"
            print(f"   {mark} {check['zone']}: 기대 {check['want']}장 / "
                  f"화면 {check['saw']}장{extra}")
        #: 🔴 좌표로 읽은 것과 **화면의 장수 표시**를 맞춰 본다.
        for cross in final.get("cross_check") or ():
            if not cross.get("ok"):
                print(f"   ❌ {cross['zone']}: 화면 표시 {cross['label']} / "
                      f"좌표로 읽은 수 {cross['geometry']}")
        for line in final.get("problems") or ():
            print(f"   ❌ 판 읽기 문제: {line}")
    if result.get("share_url"):
        print("\n  공유 URL:", result["share_url"])
    elif result.get("share_requested"):
        print("\n  🔴 공유 URL 을 만들지 못했습니다.")
    if result.get("stopped_at"):
        print(f"\n  🔴 멈춤 — {result['stopped_at']}: {result['stopped_reason']}")
    for note in result.get("notes") or ():
        print("  ·", note)


if __name__ == "__main__":  # pragma: no cover - 실행 편의
    raise SystemExit(main())
