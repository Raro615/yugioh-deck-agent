"""
조립 층 — **분석이 읽어 둔 것을 엔진이 쓸 수 있게 놓는 자리** (Phase 6-I).

왜 새 자리가 필요했는가
-----------------------
부품은 전부 있었다. ``analysis`` 가 Lua 등록을 읽고, ``engine.trigger_compiler``
가 그것을 :class:`~engine.trigger.TriggerSpec` 으로 옮기고,
``engine.event_pipeline`` 이 실제 사건에서 후보를 모으고,
``engine.trigger.TriggerEligibilityJudge`` 가 다섯 관문으로 판정한다.

없던 것은 **그 넷을 한 줄로 잇는 자리**였다. 측정:

* :class:`~engine.trigger.TriggerRegistry` 를 만드는 production 자리 —
  **0곳** (6-I 가 이 패키지에 그 자리를 만들었다)
* ``engine.event_pipeline`` 을 import 하는 production 파일 — **0곳**

그래서 모든 연결이 시험 코드 안에서만 일어났고, 실제 듀얼은 후보를 하나도
모으지 않았다.

🔴 **왜 ``engine`` 안에 둘 수 없었는가** — 두 감사가 막는다.

* ADR-007 — ``engine`` 이 ``analysis`` 에서 가져올 수 있는 이름은
  ``LimitScope`` **하나**다 (``tests/engine/test_phase2_contracts.py`` 의
  ``test_contract_h``).
* ``EffectSpec`` 전용 칸(``effect_types`` · ``ranges`` 등)을 ``engine`` ·
  ``agent`` 가 읽지 않는다 (``tests/test_binding_rule_alignment.py`` 의
  ``test_37``). 등록 정보를 꺼내려면 그 칸을 읽어야 한다.

두 규칙이 지키려는 것은 **"엔진은 카드 데이터의 모양을 모른다"** 이고, 그
규칙에 예외를 파는 대신 **두 층 위에 자리를 만들었다.** 이 패키지는
``core`` · ``analysis`` · ``engine`` 을 전부 import 하는 **유일한** 자리이고,
아래 두 층은 서로를 여전히 모른다 (``analysis`` 는 ``engine`` 을 import 하지
않는다 — 측정: 0곳).
"""

from integration.trigger_registry import (
    CardTriggers,
    RegistryBuild,
    compiled_triggers,
    registry_for_view,
)

__all__ = [
    "CardTriggers",
    "RegistryBuild",
    "compiled_triggers",
    "registry_for_view",
]
