"""
발동 조건의 부울 구조 검증.

목표는 더 많이 파싱하는 것이 아니라, 이미 읽고 있는 조건의 **논리 관계**를
정확히 보존하는 것이다. OR 를 AND 로 평탄화하면 성립하지 않는 콤보를
성립한다고 판단하게 된다.

모든 사례는 저장소에 실제로 있는 Lua 스크립트에서 가져왔다.
이 테스트는 구현보다 먼저 작성되었다.
"""

import pytest

from analysis import BoolOp, ConditionKind, EffectAnalyzer
from tests.conftest import requires_official_db

pytestmark = requires_official_db

# --- 실제 카드와 그 조건식 ---
PARALLEL_PORT = 879958
# return Duel.IsAbleToEnterBP() or Duel.IsBattlePhase()

ORBITAL = 44818
# return eg:IsExists(...) and not eg:IsContains(e:GetHandler())

CYBER_DRAGON_ZWEI = 5373478
# return (phase==PHASE_DAMAGE or phase==PHASE_DAMAGE_CAL)
#        and Duel.GetAttacker()==e:GetHandler() and Duel.GetAttackTarget()~=nil

ORCUST_CLIMAX = 703897
# if not Duel.IsExistingMatchingCard(...) then return false end
# return Duel.IsChainNegatable(ev) and (re:IsMonsterEffect() or re:IsHasType(...))

SUSANOWO = 494922
# return not Duel.IsExistingMatchingCard(Card.IsSpellTrap,tp,LOCATION_GRAVE,0,1,nil)

CYMBAL_SKELETON = 21441617
# e1: return not Duel.IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)

COOCLOCK = 2511
# if not (rp==tp and ... ) then return false end
# return eg:IsExists(...)
#        and ((re:IsTrapEffect() and re:IsHasType(...))
#             or (rc:IsSetCard(SET_LABRYNTH) and not rc:IsCode(id)))

REINFORCEMENT = 32807846  # 조건 함수 없음


@pytest.fixture(scope="module")
def analyzer(repository):
    return EffectAnalyzer(repository)


def tree_of(analyzer, repository, card_id, index=0):
    analysis = analyzer.analyze(repository.get(card_id))
    return analysis.effects[index].activation.tree


def first_tree(analyzer, repository, card_id):
    """조건 트리를 가진 첫 효과의 트리."""
    analysis = analyzer.analyze(repository.get(card_id))
    for effect in analysis.effects:
        if effect.activation.tree is not None:
            return effect.activation.tree
    raise AssertionError("조건 트리가 없다")


# ===================================================================
# OR — 가장 중요한 사례. AND 로 평탄화되면 안 된다.
# ===================================================================


def test_or_is_not_flattened_into_and(analyzer, repository):
    """패러렐포트 아머: A or B. 루트가 OR 여야 한다."""
    tree = first_tree(analyzer, repository, PARALLEL_PORT)
    assert tree.op is BoolOp.OR
    assert len(tree.children) == 2
    assert all(child.op is BoolOp.LEAF for child in tree.children)


def test_or_branches_are_alternatives_not_requirements(analyzer, repository):
    """
    OR 의 가지는 '둘 다 필요'가 아니라 '둘 중 하나'다.
    평면 목록만 보면 이 차이가 사라지므로 트리로 확인한다.
    """
    tree = first_tree(analyzer, repository, PARALLEL_PORT)
    assert tree.op is BoolOp.OR
    assert tree.is_alternative is True
    for child in tree.children:
        assert child.is_alternative is False


# ===================================================================
# AND + NOT
# ===================================================================


def test_and_with_not_child(analyzer, repository):
    """홀리나이츠 오르비타엘: A and not B."""
    tree = first_tree(analyzer, repository, ORBITAL)
    assert tree.op is BoolOp.AND
    assert any(child.op is BoolOp.NOT for child in tree.children)
    negated = next(c for c in tree.children if c.op is BoolOp.NOT)
    assert len(negated.children) == 1


def test_not_only_condition(analyzer, repository):
    """EM 해머맘모: 조건 전체가 부정 하나."""
    tree = first_tree(analyzer, repository, SUSANOWO)
    assert tree.op is BoolOp.NOT
    assert len(tree.children) == 1
    leaf = tree.children[0]
    assert leaf.op is BoolOp.LEAF
    assert leaf.requirement is not None
    assert leaf.requirement.kind is ConditionKind.REQUIRES_CARD


def test_not_is_marked_on_the_requirement_too(analyzer, repository):
    """
    평면 목록(requirements)을 쓰는 기존 코드가 깨지지 않아야 한다.
    NOT 아래의 leaf 는 negated 로 표시된다.
    """
    analysis = analyzer.analyze(repository.get(CYMBAL_SKELETON))
    first = analysis.effects[0]
    assert first.activation.tree.op is BoolOp.NOT
    requirement = next(
        r
        for r in first.activation.requirements
        if r.kind is ConditionKind.PLAYER_AFFECTED
    )
    assert requirement.negated is True


# ===================================================================
# (A OR B) AND C — 괄호가 우선순위를 바꾸는 경우
# ===================================================================


def test_parenthesised_or_inside_and(analyzer, repository):
    """
    사이버 드래곤 츠바이: (A or B) and C and D.
    루트는 AND 이고, 첫 가지가 OR 로 남아야 한다.
    괄호를 무시하면 A or (B and C and D) 가 되어 의미가 달라진다.
    """
    tree = first_tree(analyzer, repository, CYBER_DRAGON_ZWEI)
    assert tree.op is BoolOp.AND
    assert any(child.op is BoolOp.OR for child in tree.children)
    or_branch = next(c for c in tree.children if c.op is BoolOp.OR)
    assert len(or_branch.children) == 2


# ===================================================================
# A AND (B OR C) — 가드 절 포함
# ===================================================================


def test_and_with_nested_or(analyzer, repository):
    """
    오르페골 클리막스:
        if not X then return false end   -> X 는 반드시 참
        return A and (B or C)
    전체는 AND(X, A, OR(B, C)) 가 되어야 한다.
    """
    tree = first_tree(analyzer, repository, ORCUST_CLIMAX)
    assert tree.op is BoolOp.AND
    assert any(child.op is BoolOp.OR for child in tree.children)

    # 가드 절이 AND 가지로 들어왔는지 (부정이 두 번 뒤집혀 긍정이 된다)
    leaves = [n for n in tree.leaves() if n.requirement]
    kinds = {leaf.requirement.kind for leaf in leaves}
    assert ConditionKind.REQUIRES_CARD in kinds
    assert ConditionKind.CHAIN in kinds
    guard = next(
        leaf
        for leaf in leaves
        if leaf.requirement.kind is ConditionKind.REQUIRES_CARD
    )
    assert guard.requirement.negated is False


# ===================================================================
# 중첩 — AND > OR > AND > NOT
# ===================================================================


def test_deeply_nested_condition(analyzer, repository):
    """
    라뷰린스 쿠클락의 묘지 조건:
        AND(
            가드,
            eg:IsExists(...),
            OR(
                AND(re:IsTrapEffect(), re:IsHasType(...)),
                AND(rc:IsSetCard(SET_LABRYNTH), NOT(rc:IsCode(id)))
            )
        )
    """
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    tree = grave.activation.tree
    assert tree is not None
    assert tree.op is BoolOp.AND

    or_branch = next((c for c in tree.children if c.op is BoolOp.OR), None)
    assert or_branch is not None, "OR 가지가 평탄화되면 안 된다"
    assert len(or_branch.children) == 2

    # OR 의 각 가지는 다시 AND 다.
    assert all(child.op is BoolOp.AND for child in or_branch.children)
    # 그중 한 가지에는 NOT 이 들어 있다.
    assert any(
        any(gc.op is BoolOp.NOT for gc in child.children)
        for child in or_branch.children
    )


def test_tree_depth_is_preserved(analyzer, repository):
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    assert grave.activation.tree.depth() >= 3


# ===================================================================
# 읽지 못한 조건 보존
# ===================================================================


def test_unreadable_leaf_keeps_its_raw_text(analyzer, repository):
    """
    분류하지 못한 leaf 도 원문을 보존한다. 논리 구조는 살리되
    의미를 지어내지 않는다.
    """
    analysis = analyzer.analyze(repository.get(COOCLOCK))
    grave = next(e for e in analysis.effects if e.activation_locations == ["GRAVE"])
    unknown = [
        leaf
        for leaf in grave.activation.tree.leaves()
        if leaf.requirement is None
    ]
    assert unknown, "쿠클락 조건에는 분류하지 못한 항목이 있다"
    for leaf in unknown:
        assert leaf.raw.strip()


def test_no_condition_means_no_tree(analyzer, repository):
    """증원에는 조건 함수가 없다. 빈 트리를 지어내면 안 된다."""
    effect = analyzer.analyze(repository.get(REINFORCEMENT)).effects[0]
    assert effect.activation.tree is None
    assert effect.activation.has_condition_function is False


def test_flat_requirements_match_tree_leaves(analyzer, repository):
    """평면 목록은 트리 leaf 에서 유도되어야 한다 (둘이 어긋나면 안 된다)."""
    for card_id in (PARALLEL_PORT, ORBITAL, CYBER_DRAGON_ZWEI, SUSANOWO):
        analysis = analyzer.analyze(repository.get(card_id))
        for effect in analysis.effects:
            tree = effect.activation.tree
            if tree is None:
                continue
            from_tree = [
                leaf.requirement
                for leaf in tree.leaves()
                if leaf.requirement is not None
            ]
            assert effect.activation.requirements == from_tree


def test_tree_describes_itself_in_korean(analyzer, repository):
    tree = first_tree(analyzer, repository, PARALLEL_PORT)
    text = tree.describe_ko()
    assert "또는" in text
    tree = first_tree(analyzer, repository, ORBITAL)
    assert "그리고" in tree.describe_ko()
