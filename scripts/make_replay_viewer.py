"""
전개 뷰어 HTML 을 만든다 (Phase 6-AU).

사용
----
::

    # 고정 경로를 돌려서 기록 + 뷰어를 한 번에
    python3 -m scripts.make_replay_viewer --line orcust-skeleton-longirsu \
        --out docs/viewer/orcust-skeleton-longirsu.html

    # 이미 있는 combo-replay.json 으로 뷰어만
    python3 -m scripts.make_replay_viewer --json combo-replay.json --out 전개.html

    # 기록 없이 여는 빈 뷰어 (화면에서 JSON 을 고른다)
    python3 -m scripts.make_replay_viewer --empty --out docs/viewer/replay-viewer.html

🔴 **새 엔진이 아니다.** ``--line`` 은 디스코드 ``/combo`` 가 부르는 것과
같은 생산 경로(``deck.opening``)를 그대로 부르고, 뷰어는 그 기록을 읽어
그린다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - 실행 편의
    sys.path.insert(0, str(ROOT))


def _run_line(name: str) -> dict:
    """고정 경로를 돌려 기록을 만든다 — 생산 경로 그대로."""
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


def main(argv: "list[str] | None" = None) -> int:
    from deck.replay_viewer import render_replay_html

    parser = argparse.ArgumentParser(description="전개 뷰어 HTML 생성")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--line", help="고정 경로 이름 (예: orcust-skeleton-longirsu)")
    group.add_argument("--json", help="이미 있는 전개 기록 JSON")
    group.add_argument("--empty", action="store_true",
                       help="기록 없이 여는 빈 뷰어")
    parser.add_argument("--out", required=True, help="쓸 HTML 경로")
    parser.add_argument(
        "--images", dest="images", action="store_true", default=True,
        help="카드 그림을 담는다 (기본). 없는 그림만 한 번 받아 "
             "data/cache/card_images 에 보관한다.")
    parser.add_argument(
        "--no-images", dest="images", action="store_false",
        help="그림 없이 만든다 — 카드를 이름으로 그린다. 🔴 카드 그림은 "
             "저작물이라, 저장소에 커밋하는 파일은 이 쪽으로 만든다.")
    parser.add_argument(
        "--offline", action="store_true",
        help="받아 둔 그림만 쓴다 (네트워크를 쓰지 않는다).")
    args = parser.parse_args(argv)

    if args.empty:
        record = None
    elif args.json:
        record = json.loads(Path(args.json).read_text(encoding="utf-8"))
    else:
        record = _run_line(args.line)

    images = None
    said_images = "그림 없음 (이름으로 표시)"
    if record is not None and args.images:
        from deck.card_images import prepare_images, record_passcodes

        codes = record_passcodes(record)
        image_set = prepare_images(codes, root=ROOT,
                                   allow_download=not args.offline)
        images = image_set.to_payload()
        said_images = (
            f"그림 {len(image_set.uris)}/{len(codes)}장"
            f" (새로 받음 {image_set.downloaded})"
            + (f" · 없음 {list(image_set.missing)}" if image_set.missing else "")
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_replay_html(record, images=images), encoding="utf-8")
    said = "빈 뷰어" if record is None else (
        f"{record['result'].get('status')} · "
        f"걸음 {len(record.get('steps', []))} · 사건 {len(record.get('events', []))}"
    )
    print(f"{out} ({out.stat().st_size:,} bytes) — {said} — {said_images}")
    return 0


if __name__ == "__main__":  # pragma: no cover - 실행 편의
    raise SystemExit(main())
