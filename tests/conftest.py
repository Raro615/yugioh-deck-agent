"""테스트 공용 픽스처."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(),
    reason="cards.cdb 가 없습니다. python -m scripts.fetch_official_db 로 내려받으세요.",
)


@pytest.fixture(scope="session")
def repository():
    """전체 데이터로 만든 리포지토리 (세션 동안 한 번만 만든다)."""
    from core.card_repository import CardRepository

    if not CARDS_CDB.is_file():
        pytest.skip("cards.cdb 없음")
    return CardRepository.build(db_path=CARDS_CDB, script_dir=PROJECT_ROOT)


@pytest.fixture(scope="session")
def engine(repository):
    from core.card_search import CardSearchEngine

    return CardSearchEngine(repository)


@pytest.fixture(scope="session")
def parser():
    from core.query_parser import KoreanQueryParser

    return KoreanQueryParser(default_limit=None)


def read_script(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def pytest_configure(config):
    """
    ``real_card`` 표식을 등록한다.

    **실제 카드 테스트와 synthetic 테스트를 구분하기 위한 것이다**
    (Phase 2-W §6). synthetic 은 실행 경로의 *모양*만 시험하므로 아무 카드의
    의미도 주장하지 않지만, ``real_card`` 가 붙은 것은 공식 스크립트에서
    읽은 실제 카드의 의미를 주장한다 — 그것이 깨지면 카드를 잘못 옮긴
    것이므로 다르게 읽어야 한다.

        pytest -m real_card        실제 카드만
        pytest -m "not real_card"  나머지만
    """
    config.addinivalue_line(
        "markers", "real_card: 공식 스크립트에서 읽은 실제 카드를 실행하는 테스트"
    )


def settle_chain(duel):
    """
    발동 뒤 열린 **응답 창을 닫고 체인을 해결한다** (Phase 3-E-11).

    ``RULE-CHAIN-001`` 이 적는다 — "Both players continue to add effects to
    the Chain until **they both wish to add nothing else**, then you resolve
    the outcome in reverse order." 그래서 패스가 **두 번** 필요하다. 한 번은
    상대가, 한 번은 발동한 쪽이 "그만하겠다" 고 말하는 것이다.

    예전에는 ``Duel.apply`` 하나가 발동과 해결을 함께 끝냈다. 응답 기회가
    없었기 때문이고, 그것이 STRUCTURAL-34 였다. 지금은 해결 **결과**를 보려면
    이 걸음을 거쳐야 한다.

    마지막 패스의 :class:`DuelStep` 을 돌려준다 — 그것이 해결의 결과다.
    열린 창이 없으면 ``None`` 이다.
    """
    from engine.action import PlayerActionKind

    last = None
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        legal = duel.legal_actions()
        passing = [a for a in legal.allowed if a.kind is PlayerActionKind.PASS]
        if not passing:
            break
        last = duel.apply(passing[0])
    return last


def activate_and_settle(duel, action):
    """발동 하나를 끝까지 — 발동, 양쪽 패스, 해결. 해결의 결과를 돌려준다."""
    activation = duel.apply(action)
    if not activation.accepted:
        return activation
    return settle_chain(duel) or activation
