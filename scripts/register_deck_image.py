"""
덱 이미지 등록 — 사용자의 **Neuron 덱 이미지 한 장**을 한 번 등록한다
(Phase 6-AZ).

하는 일
-------
1. 이미지를 사이트에 올려 판에 적용하고, **자리마다 사이트가 어느 카드로
   읽는지**를 읽는다 (``scripts/duel_simulator_register.js``).
2. 그 결과를 레시피와 **카드별 매수까지** 맞춰 본다.
3. 맞으면 이미지를 ``data/deck_images/`` 아래에 **복사해 두고** 등록을
   남긴다. 맞지 않으면 무엇이 다른지 적고 **확인되지 않은 등록**으로 둔다.

사용
----
::

    # 등록 (레시피는 파일이나 글자로)
    python3 -m scripts.register_deck_image --image ./내덱.png \\
        --recipe-file ./recipe.txt --owner local

    # 자리를 직접 확정해 주기 (사이트가 못 읽은 자리만)
    python3 -m scripts.register_deck_image --image ./내덱.png \\
        --recipe-file ./recipe.txt --confirm main-7=57835716 \\
        --confirm main-8=57835716

    # 등록 목록
    python3 -m scripts.register_deck_image --list --owner local

🔴 **Neuron 앱에 접속하지 않는다.** 사용자가 저장한 파일을 받을 뿐이다.
🔴 **확인되지 않은 등록으로는 외부 공유를 시작하지 않는다.**
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - 실행 편의
    sys.path.insert(0, str(ROOT))

DRIVER = ROOT / "scripts" / "duel_simulator_register.js"


def _repository():
    from core.card_repository import CardRepository

    return CardRepository.build(db_path=ROOT / "data" / "cards.cdb",
                                script_dir=ROOT)


def main(argv: "list[str] | None" = None) -> int:
    from deck.deck_image_registry import (
        list_registrations,
        normalize_recipe,
        recipe_totals,
    )
    from deck.deck_register import run_registration
    from deck.site_session import preflight

    parser = argparse.ArgumentParser(description="덱 이미지 등록")
    parser.add_argument("--owner", default="local",
                        help="등록 소유자 (디스코드 사용자 ID 또는 local)")
    parser.add_argument("--list", action="store_true",
                        help="이 소유자의 등록 목록만 보여 준다")
    parser.add_argument("--image", help="Neuron 에서 저장한 덱 이미지 파일")
    parser.add_argument("--recipe", default="", help="레시피 글자")
    parser.add_argument("--recipe-file", help="레시피가 든 파일")
    parser.add_argument("--confirm", action="append", default=[],
                        metavar="자리=패스코드",
                        help="사이트가 못 읽은 자리를 직접 확정한다 "
                             "(예: main-7=57835716). 여러 번 줄 수 있다")
    parser.add_argument("--out", default="docs/viewer/local/deck-register",
                        help="작업 디렉터리")
    args = parser.parse_args(argv)

    if args.list:
        found = list_registrations(args.owner)
        if not found:
            print("등록된 덱 이미지가 없습니다.")
            return 0
        for registration in found:
            mark = "✅ 확인됨" if registration.verified else "⚠ 미확인"
            print(f"{registration.registration_id}  {mark}  "
                  f"메인 {registration.counts.get('main')} · 엑스트라 "
                  f"{registration.counts.get('extra')}  "
                  f"레시피 {registration.recipe_sha256[:12]}  "
                  f"{registration.verify_method or '-'}")
        return 0

    if not args.image:
        parser.error("--image 가 필요합니다")
    recipe_text = (Path(args.recipe_file).read_text(encoding="utf-8")
                   if args.recipe_file else args.recipe)
    if not recipe_text.strip():
        parser.error("--recipe 또는 --recipe-file 이 필요합니다")

    image = Path(args.image)
    if not image.exists():
        print(f"🔴 덱 이미지를 찾지 못했습니다: {image}", file=sys.stderr)
        return 2

    repository = _repository()
    norm, digest = normalize_recipe(recipe_text, repository)
    totals = recipe_totals(norm)
    print(f"레시피: 메인 {totals['main']} · 엑스트라 {totals['extra']} "
          f"· 해시 {digest[:12]}")

    ready = preflight()
    print(ready.message())
    if not ready.ready:
        return 2

    print("사이트에서 자리별 카드를 읽는 중… (실측 30~60초)")
    outcome = run_registration(
        owner=args.owner, image=image, image_name=image.name,
        recipe_text=recipe_text, repository=repository,
        confirms=args.confirm, base_dir=args.out)

    if not outcome.ok:
        print(f"🔴 {outcome.reason}", file=sys.stderr)
        return 1
    print(f"자리 {outcome.read_slots}개 읽음 · 식별 못 한 자리 "
          f"{outcome.uncertain}개 · 자리를 묶지 못한 줄 {outcome.unreadable}개")
    print()
    if outcome.verified:
        print(f"✅ 등록 완료 — 등록 ID **{outcome.registration_id}** "
              f"(확인 방법: {outcome.registration.verify_method})")
        print("   다음 실행:")
        print(f"   python3 -m scripts.duel_simulator_share --line <경로> "
              f"--registration {outcome.registration_id} "
              f"--owner {args.owner}")
    else:
        print(f"⚠ **확인되지 않은 등록** — 등록 ID {outcome.registration_id}")
        print("   이 등록으로는 외부 공유를 시작하지 않습니다. 무엇이 다른지:")
        for line in outcome.problems[:10]:
            print("   -", line)
        print("   못 읽은 자리는 --confirm 자리=패스코드 로 확정해 주십시오.")
    return 0 if outcome.verified else 1


if __name__ == "__main__":  # pragma: no cover - 실행 편의
    raise SystemExit(main())
