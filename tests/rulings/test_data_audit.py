"""
데이터 정합성 감사 — 실제 데이터에 대한 불변식.

픽스처 파싱이 아니라 **저장소에 실제로 들어 있는 데이터**를 검사한다.
여기 있는 것은 전부 08871b9 감사에서 실제로 문제가 발견되었거나,
발견된 문제가 되돌아오는 것을 막기 위한 검사다.
"""

import json
from pathlib import Path

import pytest

from core.card_identity import CardIdentityMapping, LinkSource, LinkStatus
from core.provenance import AnalysisStatus
from rulings.ruling_model import RulingAvailability
from tests.rulings.conftest import (
    IDENTITY_PATH,
    PROJECT_ROOT,
    requires_identity,
    requires_samples,
)

CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"
requires_cards = pytest.mark.skipif(not CARDS_CDB.is_file(), reason="cards.cdb 없음")

FULLWIDTH_SPACE = "　"


@pytest.fixture(scope="module")
def card_repository():
    from core.card_repository import CardRepository

    if not CARDS_CDB.is_file():
        pytest.skip("cards.cdb 없음")
    return CardRepository.build(db_path=CARDS_CDB, script_dir=PROJECT_ROOT)


# ----------------------------------------------------------------------
# 원문 충실성  (감사에서 발견된 🔴)
# ----------------------------------------------------------------------
@requires_samples
def test_official_original_keeps_fullwidth_spaces(ruling_repository):
    """
    공식 카드명에는 전각 공백이 들어간다 (「魔弾の射手　カスパール」).
    이것을 반각으로 접으면 저장된 것은 공식 원문이 아니라 우리가 고쳐 쓴
    문자열이 된다. 08871b9 에서 실제로 전부 접혀 있었다.
    """
    entry = ruling_repository.ruling("OCG-QA-21330")
    assert entry is not None
    assert f"魔弾の射手{FULLWIDTH_SPACE}カスパール" in entry.answer_original

    total = sum(
        getattr(e, "question_original", "").count(FULLWIDTH_SPACE)
        + getattr(e, "answer_original", "").count(FULLWIDTH_SPACE)
        + getattr(e, "text_original", "").count(FULLWIDTH_SPACE)
        for e in ruling_repository
    )
    assert total > 0, "전각 공백이 하나도 없다면 다시 접히고 있는 것이다."


def test_text_conversion_collapses_only_html_whitespace():
    from sources.ocg_ruling_adapter import _to_text

    # HTML 이 접는 공백만 접는다.
    assert _to_text("a  \t b") == "a b"
    assert _to_text("  a  <br>  b  ") == "a\nb"
    # 전각 공백은 건드리지 않는다.
    assert _to_text(f"a{FULLWIDTH_SPACE}b") == f"a{FULLWIDTH_SPACE}b"
    assert _to_text(f"{FULLWIDTH_SPACE}a") == f"{FULLWIDTH_SPACE}a"
    assert _to_text(f"a{FULLWIDTH_SPACE}{FULLWIDTH_SPACE}b") == (
        f"a{FULLWIDTH_SPACE}{FULLWIDTH_SPACE}b"
    )


def test_content_hash_distinguishes_fullwidth_from_halfwidth_space():
    from rulings.ruling_model import CardRuling

    def make(answer: str) -> CardRuling:
        return CardRuling(
            ruling_id="OCG-QA-1", card_id=1, official_cid=1,
            question_original="q", answer_original=answer,
        )

    assert make(f"a{FULLWIDTH_SPACE}b").content_hash != make("a b").content_hash
    assert make("a  b").content_hash == make("a b").content_hash


# ----------------------------------------------------------------------
# 수집 상태  (감사에서 발견된 🟠)
# ----------------------------------------------------------------------
@requires_samples
def test_four_availability_states_are_all_distinguishable(ruling_repository):
    """
    확인함 / 없음 / 시도했다 실패 / 시도 안 함 — 넷이 서로 다른 값이어야 한다.
    """
    values = {a.value for a in RulingAvailability}
    assert len(values) == 4

    # 실제 데이터에서 두 가지가 나타난다.
    stored = {s.availability for s in ruling_repository.ruling_sets}
    assert RulingAvailability.EXISTS in stored
    assert RulingAvailability.NOT_FOUND in stored

    # 수집한 적 없는 카드는 '시도 안 함' 이다 — 실패도, 없음도 아니다.
    never = ruling_repository.availability_for_card(99999999)
    assert never is RulingAvailability.NOT_CHECKED


@requires_samples
def test_stored_sets_never_claim_a_failure_they_did_not_have(ruling_repository):
    for ruling_set in ruling_repository.ruling_sets:
        if ruling_set.availability is RulingAvailability.SOURCE_UNAVAILABLE:
            assert ruling_set.error, "실패라면 무엇이 실패했는지 남아야 한다."
        else:
            assert not ruling_set.error


# ----------------------------------------------------------------------
# 식별자  (감사에서 발견된 🟠)
# ----------------------------------------------------------------------
@requires_identity
@requires_cards
def test_every_repository_card_can_reach_a_cid(card_repository, identity):
    """
    엔진이 든 패스코드로 재정을 못 찾으면 그 카드는 재정이 없는 것처럼 보인다.
    08871b9 에서는 다른 일러스트 판본 228장이 여기 걸렸다.
    """
    unreachable = sorted(
        card.id for card in card_repository if identity.cid_for(card.id) is None
    )
    assert len(unreachable) <= 10, (
        f"cid 를 못 얻는 카드가 {len(unreachable)}장입니다: {unreachable[:10]}"
    )


@requires_identity
@requires_cards
def test_alias_column_has_two_different_meanings(card_repository, identity):
    """
    ``cards.cdb`` 의 ``alias`` 는 "같은 카드의 다른 일러스트" 이기도 하고
    "룰상 저 카드명으로 취급" 이기도 하다. 후자는 **전혀 다른 카드**다::

        伝説の都 アトランティス -> 海
        ハーピィ・レディ2       -> ハーピィ・レディ

    둘을 구분하지 않고 cid 를 물려주면 엉뚱한 카드의 공식 재정이 붙는다.
    """
    rule_aliases = []
    for card in card_repository:
        if not card.alias:
            continue
        original = card_repository.get(card.alias)
        variant_cid, original_cid = identity.cid_for(card.id), identity.cid_for(card.alias)
        if original is None or variant_cid is None or original_cid is None:
            continue
        if variant_cid != original_cid:
            rule_aliases.append(card.id)
    assert rule_aliases, "alias 가 전부 같은 카드라면 전제가 바뀐 것이다."
    # 전설의 도시 아틀란티스는 「海」로 취급되지만 별개의 카드다.
    assert identity.cid_for(295517) != identity.cid_for(22702055)


@requires_identity
@requires_cards
def test_alias_derived_links_only_exist_where_the_name_is_identical(
    card_repository, identity
):
    """
    alias 로 물려받은 링크는 **카드명이 같을 때만** 만들어져야 한다.
    이름이 다르면 룰상 취급일 뿐 다른 카드이므로 재정을 공유하면 안 된다.
    """
    from core.card_identity import same_card_name

    alias_entries = [e for e in identity if e.link_source is LinkSource.CARD_ALIAS]
    assert len(alias_entries) > 100
    for entry in alias_entries:
        card = card_repository.get(entry.card_id)
        original = card_repository.get(card.alias)
        assert original is not None
        assert identity.cid_for(card.alias) == entry.cid
        variant_ja = card.script.name_ja if card.script else None
        original_ja = original.script.name_ja if original.script else None
        if variant_ja and original_ja:
            assert same_card_name(variant_ja, original_ja), entry.card_id
        else:
            assert card.name_en == original.name_en, entry.card_id


@requires_identity
def test_alias_links_declare_their_source(identity):
    """
    alias 로 물려받은 링크는 공식 DB 가 밝힌 동일성이지 추론이 아니다.
    그 사실이 데이터에 남아야 한다.
    """
    alias_entries = [e for e in identity if e.link_source is LinkSource.CARD_ALIAS]
    assert alias_entries
    for entry in alias_entries:
        assert entry.note.startswith("cards.cdb alias ->")
        assert entry.status is not LinkStatus.CONFLICT


@requires_identity
def test_mapping_is_a_function_from_passcode_to_cid(identity):
    seen: dict[int, int] = {}
    for entry in identity:
        assert entry.card_id not in seen
        seen[entry.card_id] = entry.cid
    assert len(seen) == len(identity)


@requires_identity
def test_verified_and_unverified_are_never_conflated(identity):
    """
    검증하지 않았다는 것은 틀렸다는 뜻이 아니지만, 검증했다는 뜻도 아니다.
    """
    stats = identity.stats()
    assert stats["verified"] + stats["unverified"] + stats["conflict"] == len(identity)
    for entry in identity.by_status(LinkStatus.UNVERIFIED):
        assert entry.name_ja is None      # 대조한 적 없으면 공식 이름도 없다
        assert entry.verified_at is None
    for entry in identity.by_status(LinkStatus.VERIFIED):
        assert entry.name_ja and entry.verified_at


def test_no_similarity_matching_anywhere_in_the_identity_pipeline():
    """
    링크는 언제나 **숫자**에서 온다 (공식 cid, cards.cdb 의 alias 컬럼).
    이름 유사도로 카드를 이어붙이는 코드가 있으면 안 된다.
    """
    sources = [
        PROJECT_ROOT / "scripts" / "build_card_identity.py",
        PROJECT_ROOT / "core" / "card_identity.py",
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("difflib", "SequenceMatcher", "fuzz", "ratio(", "startswith("):
            assert forbidden not in text, f"{path.name}: {forbidden}"


def test_name_comparison_is_only_ever_a_rejection_guard():
    """
    이름 비교가 등장하는 곳은 두 군데뿐이고, 둘 다 **링크를 거부**하는 데만
    쓴다. 이름이 같다고 없던 링크를 만들어내지 않는다.

    - ``verify()``       : 이름이 다르면 CONFLICT 로 찍어 조회에서 뺀다
    - ``expand_aliases()``: 이름이 다르면 alias 링크를 넣지 않는다

    두 경우 모두 링크의 출처는 이름이 아니라 숫자다 (공식 cid / alias 컬럼).
    """
    import inspect

    from core.card_identity import same_card_name
    from scripts.build_card_identity import expand_aliases, verify

    # same_card_name 은 NFKC 정규화 후 완전 일치만 인정한다.
    assert same_card_name("ＡＢＣ", "ABC")
    assert not same_card_name("ABC", "ABCD")

    expand = inspect.getsource(expand_aliases)
    # cid 는 언제나 매핑(숫자)에서 온다.
    assert "mapping.cid_for(card.alias)" in expand
    # 이름 비교 결과는 continue(거부)로만 이어진다.
    assert "if not identical:" in expand and "continue" in expand
    assert "identical = False" in expand          # 판단 불가면 넣지 않는다

    verification = inspect.getsource(verify)
    assert "LinkStatus.CONFLICT" in verification
    assert "same_card_name(" in verification


# ----------------------------------------------------------------------
# Lua 부재  (감사에서 발견된 🟠)
# ----------------------------------------------------------------------
@requires_cards
def test_no_lua_is_not_reported_as_no_effect(card_repository):
    """
    Lua 가 없는 이유가 '효과가 없어서' 인지 '스크립트가 아직 없어서' 인지에
    따라 듀얼 엔진의 판단이 정반대가 된다. 08871b9 에서는 둘 다
    ``text_derived`` 여서, 설계대로 text_derived 를 차단하면 푸른 눈의 백룡이
    함께 막혔다.
    """
    blue_eyes = card_repository.get(89631139)
    assert blue_eyes.script is None                       # Lua 없음
    assert not blue_eyes.has_printed_effect               # 효과도 없음
    assert blue_eyes.provenance.analysis_status is AnalysisStatus.NO_EFFECT

    parallel_teleport = card_repository.get(483)
    assert parallel_teleport.script is None               # Lua 없음
    assert parallel_teleport.has_printed_effect           # 그러나 효과는 있다
    assert parallel_teleport.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED


@requires_cards
def test_text_derived_population_contains_only_cards_with_effects(card_repository):
    for card in card_repository:
        if card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED:
            assert card.has_printed_effect, card.id
        if card.provenance.analysis_status is AnalysisStatus.NO_EFFECT:
            assert not card.has_printed_effect, card.id


@requires_cards
def test_normal_pendulum_monsters_still_count_as_having_effects(card_repository):
    """통상 펜듈럼 몬스터는 통상 몬스터지만 펜듈럼 효과가 있다."""
    import core.constants as C

    pendulum_normals = [
        c for c in card_repository
        if (c.type_mask & C.TYPE_NORMAL) and (c.type_mask & C.TYPE_PENDULUM)
    ]
    if not pendulum_normals:
        pytest.skip("통상 펜듈럼 몬스터가 없습니다.")
    for card in pendulum_normals:
        assert card.has_printed_effect


# ----------------------------------------------------------------------
# 자기참조 · 순환  (감사에서 발견된 🟡)
# ----------------------------------------------------------------------
@requires_samples
def test_self_reference_exists_in_real_data(ruling_repository):
    """공식 페이지는 본문에서 자기 자신을 링크한다. 오류가 아니라 사실이다."""
    selfref = [
        e for e in ruling_repository
        if e.card_id is not None and e.card_id in e.related_card_ids
    ]
    assert selfref, "자기참조가 사라졌다면 링크 수집이 달라진 것이다."


@requires_samples
def test_traversal_terminates_despite_self_reference(ruling_repository):
    """방문 집합 없이 따라가면 즉시 무한 루프가 된다."""
    near = ruling_repository.related_card_closure(89631139, depth=1)
    far = ruling_repository.related_card_closure(89631139, depth=20)
    assert near and far
    assert near <= far
    assert 89631139 not in far           # 출발 카드는 결과에 없다
    assert ruling_repository.related_card_closure(89631139, depth=0) == set()


def test_traversal_handles_a_two_card_cycle():
    from rulings.ruling_model import CardRuling, CardRulingSet

    def ruling_set(cid, card_id, points_to):
        return CardRulingSet(
            official_cid=cid, card_id=card_id,
            availability=RulingAvailability.EXISTS, reported_total=1,
            rulings=[CardRuling(
                ruling_id=f"OCG-QA-{cid}", card_id=card_id, official_cid=cid,
                question_original="q", answer_original="a",
                related_card_ids=points_to,
            )],
        )

    from rulings.ruling_repository import RulingRepository

    # A -> B, B -> A, 그리고 둘 다 자기 자신도 링크한다.
    repository = RulingRepository([
        ruling_set(1, 100, [100, 200]),
        ruling_set(2, 200, [200, 100]),
    ])
    assert repository.related_card_closure(100, depth=50) == {200}
    assert repository.related_card_closure(200, depth=50) == {100}


# ----------------------------------------------------------------------
# 태그  (감사 결과 🟢)
# ----------------------------------------------------------------------
@requires_samples
def test_tags_are_richer_than_three_coarse_buckets(ruling_repository):
    """
    이전 보고서는 태그가 モンスター/魔法/罠 뿐이라고 적었지만 실제로는
    チェーン · ダメージステップ · 巻き戻し 등이 있다.
    """
    tags = {e.ruling_category for e in ruling_repository.qa_entries()}
    assert len(tags) > 5
    assert "チェーン" in tags


def test_tags_are_used_only_as_a_filter():
    """
    태그로 의미를 추론하지 않는다. 태그가 등장하는 곳은 필터 비교뿐이어야
    한다 — 태그만 보고 "대상 지정 효과인가" 를 답하면 안 된다.
    """
    search_source = (PROJECT_ROOT / "rulings" / "ruling_search.py").read_text(
        encoding="utf-8"
    )
    uses = [
        line.strip()
        for line in search_source.splitlines()
        if "ruling_category" in line
    ]
    assert uses
    for line in uses:
        assert "normalize(" in line and "==" in line or "!=" in line


# ----------------------------------------------------------------------
# 번역  (감사 결과 🟢)
# ----------------------------------------------------------------------
@requires_samples
def test_no_translation_is_stored_as_official(ruling_repository):
    for entry in ruling_repository:
        assert entry.provenance.language == "ja"
        assert entry.provenance.authority == "official"
        for translation in entry.translations.values():
            assert translation.authoritative is False


def test_no_api_returns_a_translation_where_the_original_belongs():
    """
    번역문이 원문 자리에 들어갈 수 있는 경로가 없어야 한다.
    ``*_original`` 필드는 어떤 코드에서도 번역으로 덮이지 않는다.
    """
    model_source = (PROJECT_ROOT / "rulings" / "ruling_model.py").read_text(
        encoding="utf-8"
    )
    for field in ("question_original", "answer_original", "text_original"):
        assignments = [
            line for line in model_source.splitlines()
            if f"{field} =" in line and "self." in line
        ]
        assert not assignments, f"{field} 에 대입하는 코드가 있습니다: {assignments}"


# ----------------------------------------------------------------------
# 개체 수 감사
# ----------------------------------------------------------------------
@requires_identity
@requires_samples
def test_population_numbers_reconcile(identity, ruling_repository):
    """
    각 숫자가 서로 다른 모집단이라는 것을 명시적으로 고정한다.
    """
    identity_total = len(identity)                       # 패스코드
    ruling_target = len(identity.cids)                   # 조회 대상 = cid
    checked = len(ruling_repository.ruling_sets)
    not_checked = ruling_target - checked

    assert identity_total >= ruling_target               # cid 하나에 패스코드 여럿
    assert checked > 0
    assert not_checked == ruling_target - checked
    assert checked + not_checked == ruling_target

    raw = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    assert len(raw["entries"]) == identity_total


# ----------------------------------------------------------------------
# provenance 시각의 정확성
# ----------------------------------------------------------------------
def test_retrieved_at_is_the_fetch_time_not_the_parse_time(tmp_path):
    """
    캐시에서 다시 파싱한 시각을 ``retrieved_at`` 으로 적으면 "공식 사이트에서
    그때 확인했다"는 거짓 기록이 된다. 실제로는 네트워크를 타지 않았다.
    """
    import os
    import time

    from sources.ocg_ruling_adapter import OfficialOcgRulingAdapter

    page = (
        '<meta name="keywords" content="テストカード,Q&A">'
        '<div id="card_text">テキスト</div>'
    )
    adapter = OfficialOcgRulingAdapter(
        cache_dir=tmp_path, delay=0, opener=lambda url: page
    )
    url = adapter.list_url(1)
    _, fresh = adapter.fetch_with_time(url)

    # 캐시 파일을 과거로 돌려놓는다.
    cached = next(tmp_path.glob("*.html"))
    past = time.time() - 86_400
    os.utime(cached, (past, past))

    _, from_cache = adapter.fetch_with_time(url)
    assert from_cache < fresh, "캐시에서 읽었는데 방금 받은 것처럼 기록되었습니다."
    assert adapter.request_count == 1


@requires_samples
def test_reparsing_from_cache_is_idempotent():
    """
    같은 캐시를 다시 파싱하면 같은 레코드가 나와야 한다. 매번 시각이 바뀌면
    변경 감지가 의미를 잃고 diff 가 소음으로 가득 찬다.
    """
    import json

    from rulings.ruling_model import CardRulingSet

    path = PROJECT_ROOT / "data" / "rulings" / "ocg" / "4007.json"
    first = json.loads(path.read_text(encoding="utf-8"))
    restored = CardRulingSet.from_json(first)
    assert restored.to_json() == first

    stamps = {r["provenance"]["retrieved_at"] for r in first["rulings"]}
    assert stamps, "재정이 하나도 없습니다."
    for stamp in stamps:
        assert stamp.endswith("Z") and len(stamp) == 20
