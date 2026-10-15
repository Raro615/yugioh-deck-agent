"""
카드 데이터 → :class:`~engine.trigger.TriggerRegistry` (Phase 6-I).

    GameStateView (지금 판에 **보이는** 카드)
        ↓  view.find(instance).card_id        ← 가려진 카드는 ``None``
    CardRepository.get(card_id)
        ↓  EffectAnalyzer.analyze(card).effects
    EffectAnalysis  (effect_types · code · ranges · event_subject_claim)
        ↓  compile_trigger_spec(EffectRef(card_id, ordinal), …)
    TriggerSpec
        ↓  TriggerRegistry.register
    등록소 — :class:`~engine.trigger_observation.TriggerObserver` 가 받는다

🔴 **정의별 등록이고 인스턴스별 등록이 아니다.**
:class:`~engine.trigger.TriggerSpec` 은 ``EffectRef(card_id, ordinal)`` 로
식별되고 인스턴스를 들고 있지 않다. "어느 인스턴스의 사건인가" 는 등록이 아니라
**판정**이 답한다 (Phase 6-F 의 :func:`~engine.trigger.subject_relation` 이
``TimingEvent.instance`` 와 후보의 ``source`` 를 맞춰 본다). 그래서 같은 카드가
두 장 있어도 등록은 하나이고, 그것이 두 장을 **섞지 않는다** — 수집기가 보이는
사본마다 후보를 따로 만들고 각 후보가 자기 ``source`` 로 판정된다.

이 구분을 흐리면 "등록을 인스턴스마다 복제해야 한다" 는 잘못된 결론이 나오고,
그 복제는 같은 선언을 여러 번 등록해 후보를 **중복**시킨다.
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.effect_analyzer import EffectAnalyzer
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.trigger import TriggerRegistry
from engine.trigger_compiler import TriggerCompilation, compile_trigger_spec


@dataclass(frozen=True, slots=True)
class RegistryBuild:
    """
    등록소 하나와 **그것을 어떻게 얻었는지**.

    수를 함께 돌려주는 이유: "등록이 0건이다" 가 **왜** 0건인지 부르는 쪽이
    알아야 한다. 카드가 안 보였는가, 트리거가 아니었는가, 사건을 옮길 이름이
    없었는가 — 세 가지는 다른 사실이고 빈 등록소는 그 셋을 구별하지 못한다.
    """

    registry: TriggerRegistry
    card_ids: tuple[int, ...] = ()
    """등록을 꺼낸 카드들. **보이는 카드만** 들어간다."""
    registered: int = 0
    """실제로 등록된 선언 수."""
    not_a_trigger: int = 0
    """효과 블록이지만 트리거 등록이 아니었다 (``TRIGGER_O`` · ``TRIGGER_F`` 없음)."""
    unsupported: int = 0
    """트리거인데 옮길 시점 이름이 없거나 사건 코드를 읽지 못했다."""
    concealed: int = 0
    """정체가 보이지 않아 건너뛴 카드 인스턴스 수 (§6-7)."""
    no_script: int = 0
    """카드는 보이는데 Lua 스크립트가 없다 (통상 몬스터 등)."""
    unplaceable: int = 0
    """
    분석 결과의 블록을 ``card.script.effects`` 안에서 찾지 못한 수.

    🔴 **0 이 아니면 식별이 깨진 것이다.** 자리를 모르면 ``EffectRef`` 를
    지어낼 수 없으므로 등록하지 않는다 (실측: 전 corpus 0건).
    """

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return (
            f"등록 {self.registered}건 (카드 {len(self.card_ids)}장) · "
            f"트리거 아님 {self.not_a_trigger} · 미지원 {self.unsupported} · "
            f"가려짐 {self.concealed} · 스크립트 없음 {self.no_script} · "
            f"자리 미확인 {self.unplaceable}"
        )


@dataclass(frozen=True, slots=True)
class CardTriggers:
    """카드 한 장에서 꺼낸 트리거 등록과 **무엇을 봤는지**."""

    compilations: tuple[TriggerCompilation, ...] = ()
    examined: int = 0
    """살펴본 등록 효과 블록 수 (``analysis.effects`` 의 길이)."""
    not_a_trigger: int = 0
    """그중 트리거 등록이 아니었던 블록 수."""
    unplaceable: int = 0
    """분석 결과의 블록을 ``card.script.effects`` 안에서 찾지 못한 수."""


def compiled_triggers(
    repository, card_id: int, *, analyzer: EffectAnalyzer | None = None
) -> CardTriggers:
    """
    카드 한 장의 **등록 효과마다** 컴파일 결과 하나. 트리거가 아니면 뺀다.

    🔴 ``ordinal`` 은 ``card.script.effects`` 안의 자리다. ``analysis.effects``
    는 그중 ``initial_effect`` 에서 만들어진 것만 담으므로 두 목록의 길이가
    다를 수 있고, 그때 ``enumerate`` 의 순번을 ``ordinal`` 로 쓰면 **다른
    블록의 선언**이 된다. 그래서 순번을 세지 않고 **원본 블록의 자리를 직접
    찾는다.**

    (실측: 전 corpus 12,472장에서 두 값이 어긋나는 카드는 0장이다 — 등록
    효과가 언제나 앞에 모여 있기 때문이다. 그래도 순번에 기대지 않는다.
    0건인 것은 **지금 데이터의 성질**이고 계약이 아니며, 그 가정이 깨지는
    날 조용히 틀리는 쪽이 아니라 그냥 맞는 쪽을 택한다.)
    """
    card = repository.get(card_id)
    if card is None or card.script is None:
        return CardTriggers()
    analyzer = analyzer or EffectAnalyzer(repository)
    ordinal_of = {id(spec): index for index, spec in enumerate(card.script.effects)}
    out: list[TriggerCompilation] = []
    examined = not_a_trigger = unplaceable = 0
    for effect in analyzer.analyze(card).effects:
        examined += 1
        ordinal = ordinal_of.get(id(effect.raw))
        if ordinal is None:
            #: 분석 결과의 블록이 원본 목록에 없다. 자리를 모르면
            #: ``EffectRef`` 를 지어낼 수 없으므로 **등록하지 않는다.**
            unplaceable += 1
            continue
        compilation = compile_trigger_spec(
            EffectRef(card_id, ordinal),
            declared_types=effect.effect_types,
            event_code=effect.raw.code,
            ranges=effect.raw.ranges,
            event_subject_claim=effect.event_subject_claim,
        )
        if compilation is None:
            #: 트리거 등록이 **아니다** (``TRIGGER_O`` · ``TRIGGER_F`` 없음).
            #: "트리거인데 옮기지 못했다" 와 다른 사실이므로 따로 센다.
            not_a_trigger += 1
            continue
        out.append(compilation)
    return CardTriggers(
        compilations=tuple(out),
        examined=examined,
        not_a_trigger=not_a_trigger,
        unplaceable=unplaceable,
    )


def registry_for_view(
    view: GameStateView, repository, *, analyzer: EffectAnalyzer | None = None
) -> RegistryBuild:
    """
    **이 관측에 보이는 카드들**의 트리거 등록소.

    왜 관측에서 뽑는가 (§6-6 · §6-7):

    * 판에 **없는 카드**의 효과가 근거 없이 등록되지 않는다. 덱 · 엑스트라
      덱의 카드는 ``visible_instances`` 에 들어오지 않는다.
    * **가려진 카드의 정체가 새지 않는다.** 뒷면 카드의 ``CardView`` 는
      ``card_id`` 를 ``None`` 으로 준다 (실측: 유출 0건). 그 카드는
      ``concealed`` 로 세고 **등록하지 않는다** — 등록하면 그 사실만으로
      상대가 무엇을 놓았는지 알려 주게 된다.

    🔴 **등록소는 관측 시점의 사진이다.** 사건이 카드를 움직이면 보이는
    카드가 달라지므로, 사건을 관찰할 때는 **그 사건 뒤의** 관측에서 만든
    등록소를 써야 한다. 예: "이 카드를 드로우했을 때" 는 뽑힌 뒤에야 패에서
    보인다.
    """
    analyzer = analyzer or EffectAnalyzer(repository)
    registry = TriggerRegistry()
    card_ids: list[int] = []
    concealed = no_script = registered = not_a_trigger = unsupported = 0
    seen: set[int] = set()

    unplaceable = 0
    for instance in view.visible_instances():
        card = view.find(instance)
        if card is None or card.card_id is None:
            #: 🔴 정체가 보이지 않는다. **세고 넘어간다** — 등록하면 그
            #: 사실만으로 무엇이 놓였는지 알려 주게 된다 (§6-7).
            concealed += 1
            continue
        if card.card_id in seen:
            #: 같은 카드가 두 장이어도 **등록은 한 번**이다 (모듈 머리말).
            continue
        seen.add(card.card_id)
        definition = repository.get(card.card_id)
        if definition is None or definition.script is None:
            #: Lua 스크립트가 없는 카드 (통상 몬스터 등). 효과가 없는 것과
            #: 읽지 못한 것을 섞지 않으려고 따로 센다.
            no_script += 1
            continue
        card_ids.append(card.card_id)
        found = compiled_triggers(repository, card.card_id, analyzer=analyzer)
        not_a_trigger += found.not_a_trigger
        unplaceable += found.unplaceable
        for compilation in found.compilations:
            if compilation.is_registered:
                registry.register(compilation.spec)
                registered += 1
            else:
                unsupported += 1

    return RegistryBuild(
        registry=registry,
        card_ids=tuple(sorted(card_ids)),
        registered=registered,
        not_a_trigger=not_a_trigger,
        unsupported=unsupported,
        concealed=concealed,
        no_script=no_script,
        unplaceable=unplaceable,
    )


__all__ = [
    "CardTriggers",
    "RegistryBuild",
    "compiled_triggers",
    "registry_for_view",
]
