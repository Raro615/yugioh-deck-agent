# Phase 3-E-31 완료 보고

> 가장 중요한 불변식: **`EVENT_*` 가 `EffectDefinition` 에 없다는 사실 자체를
> 버그로 취급하지 않는다.** 이 Phase 가 가린 것은 "사건 의미가 등록 계층
> (`TriggerSpec`) 의 것인가, 아니면 실제로 잃어버린 것인가" 다.

## 1. BLOCKER

**NO.**

## 2. Engine 변경

**NO.**

| 항목 | 값 |
|---|---|
| 실제 HEAD (감사 시작) | **`5be3709`** (Phase 3-E-30 보고서) |
| 작업 트리 | 깨끗 (`git status --short` 비어 있음) |
| 3-E-30 포함 확인 | `docs/phase3e30-...md` · `tests/test_activation_event_input_audit.py` 존재 |
| `a0316c4..5be3709` production diff | **0** (`engine/ agent/ core/ analysis/ sources/` 변경 없음) |
| 이번 Phase production diff | **0** |

변경 파일은 둘뿐이다.

- `tests/test_effectdefinition_trigger_boundary_audit.py` (신규)
- `docs/phase3e31-effectdefinition-trigger-boundary-audit.md` (신규)

## 3. 핵심 결론

**문제가 아니다.** `EVENT_*` 는 **파서 계층(`EffectSpec.code`)에 살아 있고**
(블록 16,381개 · 상수 70종), `EffectDefinition` 에 옮기지 않은 것은 ADR-006 의
"손으로 등록한다" 태도가 만든 **의도된 경계**다. 결정적 근거는 세 가지다.
첫째, `code` 칸을 가진 것은 `EffectSpec` **하나**이고 `EffectDefinition` 도
`TriggerSpec` 도 갖지 않는다 — 즉 "정의에 없다" 는 "`TriggerSpec` 이 가져갔다"
가 아니라 **"아직 아무도 engine 쪽으로 옮기지 않았다"** 다. 둘째, 그런데도
`engine` 안에는 그 값에 닿는 production 함수가 **이미 있다** —
`engine.ids.iter_effects(card)` 가 `(EffectRef, EffectSpec)` 을 돌려주고
`EffectSpec.code` 가 `'EVENT_FREE_CHAIN'` 을 그대로 싣는다. 값은 닿을 수 있는
곳에 있고 엔진이 **읽지 않기로** 한 것이므로 `ACTUALLY_LOST` 가 아니라
`INTENTIONALLY_DROPPED` 다. 셋째, `TriggerSpec.point` 는 `EVENT_*` 의 사본이
아니다 — `TimingPoint` 는 8개뿐이고 `StateDelta`/`JournalEvent` 에서 나오는
**엔진 자신의 어휘**이므로 Lua 의 70종과 1:1 사상이 아예 없다. 그래서
"옮기지 않았다" 가 아니라 **옮길 수 있는 모양이 아니다**. 그리고 이 간극은
새 ID 가 필요 없다 — **STRUCTURAL-7**(`analysis` → `EffectDefinition`
컴파일러)이 이미 같은 벽을 가리키고 있고 `engine/trigger.py` ·
`engine/effect/definition.py` · `engine/effect/library.py` 가 그것을 이름으로
부른다.

## 4. EffectDefinition 구조

`engine/effect/definition.py` — 칸 **10개**.

| 칸 | 뜻 | 성격 |
|---|---|---|
| `effect_ref` | `(card_id, ordinal)` — 파서 블록을 가리키는 신원 | 신원 |
| `source_card_id` | 출처 카드 | 신원 |
| `operations` | 무엇을 하는가 | **효과 의미** |
| `activation` | 발동 조건 (`Condition \| None`) | **효과 의미** |
| `cost` | 비용 | 효과 의미 |
| `targets` | 대상 묶음 | 효과 의미 |
| `declarations` | 선언 묶음 | 효과 의미 |
| `requirements` | 조작별 요구 | 효과 의미 |
| `guards` | 조작별 차단 | 효과 의미 |
| `provenance` | 어디서 왔는가 (ADR-004) | 출처 |

**없는 칸**: `code` · `point` · `event` · `trigger` · `timing` ·
`requirement`(강제/임의) · `wording` · `effect_types`.

소유: **"이 효과가 무엇을 하는가"**. 손으로 등록한다
(`EffectDefinitionRegistry` docstring: "`analysis` → `EffectDefinition`
컴파일러는 **아직 없다** (STRUCTURAL-7)").

## 5. TriggerSpec / Registration 구조

`engine/trigger.py` — 칸 **9개**.

| 칸 | 뜻 | 성격 |
|---|---|---|
| `effect_ref` | 어느 효과의 선언인가 | 신원 (ED 와 공통) |
| `operations` | 어떤 조작에 반응하는가 | ED 와 공통 |
| `point` | 어떤 **시점**의 사건인가 (`TimingPoint`) | **사건** |
| `condition` | 그때 무엇이 참이어야 하는가 | **사건 쪽 조건** |
| `requirement` | 강제/임의 (`MANDATORY`/`OPTIONAL`/`UNKNOWN`) | **규칙 성질** |
| `wording` | WHEN/IF (`WHEN`/`IF`/`UNKNOWN`) | 규칙 성질 |
| `from_zones` · `to_zones` | 어디서 어디로 움직였나 | 사건 |
| `activates_from` | 어느 자리에서 발동하나 | 발동 자리 |

소유: **"언제 이 효과가 후보가 되는가"**. 역시 손으로 등록한다
(`TriggerRegistry` docstring: "**자동 생성이 아니다.** … (STRUCTURAL-7)").

### 겹침 — 신원뿐이다

| 집합 | 값 |
|---|---|
| `ED ∩ TS` | **`{effect_ref, operations}`** |
| `TS` 만 | `point` · `condition` · `requirement` · `wording` · `from_zones` · `to_zones` · `activates_from` |
| `ED` 만 | `activation` · `cost` · `targets` · `declarations` · `guards` · `requirements` · `provenance` · `source_card_id` |

→ **`TriggerSpec` 은 `EffectDefinition` 을 고치지 않고도 사건을 적을 수 있다.**
그것이 §5 선택지 중 **B** 의 모습이다.

## 6. SetCode(EVENT_*) Data Flow

```
Lua  c92595643.lua :  e1:SetCode(EVENT_FREE_CHAIN)
  │
  ▼  sources/lua_loader.py:192   _RE_EVENT → f"EVENT_{...}"
EffectSpec.code = "EVENT_FREE_CHAIN"            ← **유일한 권위 있는 소유자**
  │  (effect_types = ['ACTIVATE'] — 접두어를 떼고 저장)
  ▼  core/card_model.py
Card.script.effects[i]                           ← 보존. 캐시에도 들어간다
  │   Card.script.trigger_events  ← **권위 없음** (파일 전체 정규식 긁기,
  │                                  "어느 효과에 붙었는지 모른다")
  ├──▶ analysis/effect_analyzer.py:374,474       spec.code.startswith("EVENT_") 를 읽는다
  │
  ├──▶ engine/ids.py:131  iter_effects(card) → (EffectRef, EffectSpec)
  │        ← **engine 안의 production 다리. code 가 그대로 나온다.**
  │           호출자는 지금 tests/engine/test_ids.py 뿐이다.
  │
  ▼  (손 등록 — 컴파일러 없음, STRUCTURAL-7)
EffectDefinition                                 ← code 칸 **없음** (의도)
TriggerSpec                                      ← code 칸 **없음**.
                                                    대신 point(TimingPoint) 를 갖는다
  ▲
  └── TimingPoint 는 Lua 가 아니라 StateDelta/JournalEvent 에서 나온다
      (TimingEvent.from_delta / from_journal_event) — **다른 어휘**
```

핵심: 흐름이 `EffectDefinition` 에서 **끊기지 않는다.** 애초에 그쪽으로 가는
간선이 없고, `engine` 쪽 간선은 `engine/ids.py` 에 **따로 있다.**

## 7. Cardinality

| 관계 | 가능한가 | 근거 (실측) |
|---|---|---|
| `EffectDefinition` 1 → `TriggerSpec` 0 | **그렇다. 지금이 그 상태다** | 등재 정의 16개, production `TriggerSpec` **0개** |
| `EffectDefinition` 1 → `TriggerSpec` 1 | 그렇다 | — |
| `EffectDefinition` 1 → `TriggerSpec` N | **그렇다** | 같은 `effect_ref` + 다른 `point` 두 선언이 등록된다 (`len == 2`) |
| 똑같은 선언 2개 | **아니다** | `TriggerRegistry.register` 가 `TriggerError` 로 거부 |
| `TriggerSpec` 1 → `EffectDefinition` N | **불가능** | `TriggerSpec` 은 `effect_ref` **하나**만 갖고 `effect_refs` 류 칸이 없다 |

→ **1 : 0..N.** `TriggerSpec` 은 정의의 **등록 시점 투영**이다 (§5 의 **B**).

## 8. Ordinary Activation vs Trigger Activation

| | A. 보통 발동 (production) | B. 유발 효과 (잠듦) |
|---|---|---|
| 출발 | 현재 판 | 사건 (`TimingEvent`) |
| 열거 | `Duel._activation_sources` → `activatable_effects` | `TriggerCollector.collect(event)` |
| 쓰는 정의 | `EffectDefinition` | `TriggerSpec` **+** `EffectDefinition.activation` |
| 적법성 | `ActionValidator` · `ActivationTimingChecker` · `can_activate` | 관문 5개 (`TriggerEligibilityJudge`) |
| 산출물 | `PlayerAction` → `ChainLink` | `TriggerCandidate` → (`TriggerChainEntry`) |
| 사건 필요 | **아니다** (3-E-30) | **그렇다** |

**같은 `EffectDefinition` 이 둘을 모두 섬긴다.** 측정 근거:
`TriggerEligibilityJudge._trigger_condition` 이 `spec.condition` 과
`definition.activation` 을 **둘 다** 모아 평가한다. 즉 공통분은
`EffectDefinition`(무엇을 하는가 · 조건 · 비용 · 대상)이고, 등록 전용분은
`TriggerSpec`(언제 · 강제/임의 · 자리)이다.

→ 분리 지점은 **등록**이다. 정의를 둘로 쪼갤 필요가 없다.

## 9. Optional / Mandatory / Timing

| 의미 | 어디에 있는가 | 측정 |
|---|---|---|
| 강제/임의 (원천) | **`EffectSpec.effect_types`** (파서) | `TRIGGER_O` **6,083** · `TRIGGER_F` **1,969** 블록 |
| 강제/임의 (등록) | `TriggerSpec.requirement` | `MANDATORY` / `OPTIONAL` / `UNKNOWN` |
| 강제/임의 (정의) | **없다** | `EffectDefinition` 에 칸 없음 |
| WHEN/IF | `TriggerSpec.wording` | `WHEN` / `IF` / `UNKNOWN` |
| 사건 시점 (원천) | `EffectSpec.code` | `EVENT_*` 70종 |
| 사건 시점 (등록) | `TriggerSpec.point` | `TimingPoint` 8종 (**다른 어휘**) |
| 스펠 스피드 | `ActivationTimingChecker` + 카드 종류 | `SpellSpeed` {NORMAL, FAST, COUNTER} |
| 세트한 턴 | `ActivationTiming.set_this_turn` (값으로 넘김) | — |

> **측정 함정**: 파서는 `EFFECT_TYPE_` 접두어를 **떼어** 저장한다
> (`effect_types = ['ACTIVATE']`). 접두어를 붙여 세면 전부 **0** 이 나온다.
> 처음 재었을 때 내가 그 함정에 빠졌고, 실제 값으로 다시 세어 고쳤다.

### "사건을 모르면 `EffectDefinition` 이 불완전한가?"

**아니다.** `EffectDefinition` 은 "무엇을 하는가" 를 완결한다 — 지금 등재된
13개 효과가 사건 없이 실제로 실행된다 (3-E-30 이 측정). 사건을 모르면 못하는
것은 **"언제 후보가 되는가"** 이고, 그 질문의 답은 `TriggerSpec` 이 들고 있다.

잃는 것이 있다면 그것은 **정의의 완결성이 아니라 등록의 범위**다 — 등재된
함정 5장이 전부 `EVENT_FREE_CHAIN`(유발 조건 없음)인데도 엔진이 **종류 단위로**
막는 것이 그 모습이다. 데이터가 없어서가 아니라 **옮기지 않아서**다.

## 10. Provenance / Data Loss

| 정보 | 분류 | 근거 |
|---|---|---|
| Lua `SetCode(EVENT_*)` → `EffectSpec.code` | **PRESERVED** | 16,381 블록 · 70종 |
| `SetCode(EFFECT_*)` → `EffectSpec.code` | **PRESERVED** | 13,703 블록 |
| 읽을 수 없는 `SetCode(id)` → `None` | **INTENTIONALLY DROPPED** | 3-E-18 이 `None` 으로 되돌리게 고쳤다 ("틀린 값을 남기는 것보다 모른다고 말하는 것이 맞다") |
| `EFFECT_TYPE_*` → `effect_types` | **TRANSFORMED** | 접두어를 떼고 저장 (`['ACTIVATE']`) |
| `Card.script.trigger_events` | **DERIVED (권위 없음)** | 파일 전체 정규식. "어느 효과에 붙었는지 모른다 — 그것은 `EffectSpec.code` 만 안다" |
| `EffectDefinition` 의 사건 정보 | **INTENTIONALLY DROPPED** | 컴파일러 없음 (ADR-006 · STRUCTURAL-7). 손으로 등록한다 |
| `TriggerSpec.point` | **DERIVED (다른 어휘)** | `StateDelta`/`JournalEvent` 에서 나온다. Lua `EVENT_*` 의 사본이 아니다 |
| `TriggerSpec.requirement` / `wording` | **DERIVED (등록 시점, 손)** | 원천은 `effect_types` 에 보존 |
| **어떤 것이든** | **ACTUALLY_LOST: 없음** | `engine.ids.iter_effects` 가 `EffectSpec` 을 그대로 돌려준다 (실측: `code='EVENT_FREE_CHAIN'`) |

**`ACTUALLY_LOST` 항목이 하나도 없다.** 새 provenance 칸을 만들지 않았다.

## 11. Production Reachability

| 질문 | 답 | 근거 (AST) |
|---|---|---|
| `EffectDefinition` 의 사건 정보 부재가 production 함수에 영향을 주는가 | **준다 — 단 `UNKNOWN` 으로만** | `TRAP_TRIGGER_MISSING` 이 함정 종류 전체를 `UNKNOWN` 으로 막는다 (3-E-30 측정). 허가가 아니므로 후보가 안 된다 |
| production `Duel` 이 `TriggerSpec` 을 만드는가 | **아니다** | `TriggerSpec(` 호출 자리 **production 0개** / test 19개 파일 |
| production 이 사건 `SetCode` 를 읽는가 | **`engine` 밖에서만** | `analysis/effect_analyzer.py` · `sources/lua_loader.py`. `engine/` **0곳** |
| `EffectActivator` 가 유발 사건 신원을 요구하는가 | **아니다** | `activate(state, chain, action, selections, cost_selections, authorization)` — 사건 인자 없음 |
| `legal_actions()` 가 트리거 등록을 요구하는가 | **아니다** | 3-E-30 이 AST 로 측정 |
| Search / Evaluation / Simulation 이 요구하는가 | **아니다** | `agent/` 에 트리거 이름 0건 |
| 트리거 파이프라인이 닿는가 | **아니다** | `duel.py` 전이 폐쇄에 `trigger_chain` · `trigger_order` · `timing` · `event_pipeline` **없음** |

> `engine/` 이 `core.card_model` 을 import 하는 것은 사실이다
> (`game_state_view.py` · `ids.py` · `state/card_instance.py`). 그래서 `engine`
> 은 `Card.script` 에 **닿을 수 있다** — 이것이 `ACTUALLY_LOST` 를 부정하는
> 근거다. 그런데 `CardView` 는 `definition` 만 노출하고 `script` 를 노출하지
> 않는다. **닿을 수 있지만 관측으로 내보내지 않는다.**

→ **트리거 경로 전체가 여전히 잠들어 있다.**

## 12. Hidden Information / RNG

**아무것도 바뀌지 않았다.**

| 점검 | 결과 |
|---|---|
| 상대 뒷면 카드 정체 노출 | **없음** — `CardView` 에 `script` · `code` · `effect_types` 칸이 없다 |
| "트리거로 등록되었다" 가 정의를 드러내는가 | **아니다** — 등록은 `TriggerRegistry`(판 밖)에 있고 관측에 실리지 않는다 |
| 감사가 RNG 를 소비했는가 | **아니다** — `state.rng.getstate()` 불변 (실측) |
| 감사가 판을 바꿨는가 | **아니다** — `state_hash()` 불변 (실측) |
| `GameStateView` 변경 필요 | **없음** |

## 13. AI / Search

| 항목 | 변화 |
|---|---|
| Evaluation | **없음** |
| Search ranking | **없음** |
| Candidate generation | **없음** |
| Simulation | **없음** |
| RNG 분리 | **없음** |
| `GameStateView` | **없음** |
| `LegalActions` | **없음** |

`agent/` 를 손대지 않았다. 트리거를 아는 Search 도, 사건을 아는 Evaluation 도
만들지 않았다.

## 14. Corpus Measurement

| 측정 | 값 |
|---|---|
| 카드 전체 | 14,127 |
| 스크립트가 붙은 카드 | 12,687 |
| **고유 스크립트(파일) 수** | **12,687** |
| **파싱된 효과 블록 총합** | **34,631** |
| `code` 가 `EVENT_*` | **16,381** (고유 상수 **70종**) |
| `code` 가 `EFFECT_*` | 13,703 |
| `code` 가 `None` | 4,547 |
| `EVENT_FREE_CHAIN` | **4,909** |
| `EVENT_PHASE` + `EVENT_PHASE_START` | **1,338** |
| `TRIGGER_O` (임의) | 6,083 |
| `TRIGGER_F` (강제) | 1,969 |
| production `TriggerSpec` 수 | **0** |
| 등재 `EffectDefinition` 수 | 16 (실행 가능 13) |
| 등재 정의 → `TriggerSpec` 사상 | **16 → 0** |

### 중복 제거 설명 (§13)

`(card_id, index)` 로 세면 **27,841** 이 나오는데, 블록 목록 길이는 **34,631**
이다. 6,790 의 차이를 추적했다.

| 원인 후보 | 측정 |
|---|---|
| alias 가 스크립트 객체를 공유 | **0건** — 공유 묶음 없음 |
| 한 스크립트 안에서 `index` 반복 | **6,790회** ← 원인 |

Lua 는 `local e1 = Effect.CreateEffect(c)` 를 여러 함수에서 다시 쓰므로 같은
변수명 `e1` 이 **서로 다른 효과 블록**으로 여러 번 나온다. 따라서
**`(card_id, index)` 는 고유 키가 아니다.** 정직한 단위는 블록의 **등장
순서**이고, 그것이 `EffectRef.ordinal` 의 정의다 (`engine/ids.py`: "``ordinal``
은 ``card.script.effects`` 안에서의 0-기반 위치다"). 위 표의 숫자는 전부
**고유 스크립트 12,687개를 한 번씩 훑은** 결과다.

## 15. Tests

`tests/test_effectdefinition_trigger_boundary_audit.py` — **16개 신규.
기존 테스트 수정 0.**

| # | 보는 것 | §14 범주 |
|---|---|---|
| 01 | `code` 를 가진 것은 `EffectSpec` 하나뿐이다 | 1 · 3 |
| 02 | ED ∩ TS = 신원뿐 — TS 가 정의를 안 고치고 사건을 적는다 | 2 |
| 03 | `TimingPoint` 는 `EVENT_*` 의 사본이 아니다 (8 vs 70, 다른 입구) | 3 |
| 04 | 코퍼스에 `EVENT_*` 가 보존되어 있다 (바닥값) | 3 · 4 |
| 05 | 등재 함정 5장이 전부 `EVENT_FREE_CHAIN` — **주석을 믿지 않고 읽는다** | 4 · 12 |
| 06 | `engine.ids.iter_effects` 가 사건 값을 돌려준다 → `ACTUALLY_LOST` 아님 | 4 · 12 |
| 07 | 강제/임의가 뭉개지지 않았다 (접두어 함정 포함) | 11 |
| 08 | `EVENT_FREE_CHAIN` ∩ `TRIGGER_O/F` = 0 (전수 재확인) | 12 |
| 09 | Cardinality 1:0..N, N:1 불가 | 2 |
| 10 | 등재 정의 16개 → `TriggerSpec` 0개 / production 생성 0곳 | 6 |
| 11 | 보통 발동은 사건을 요구하지 않는다 + 판·RNG 불변 | 5 · 8 · 9 |
| 12 | `CardView` 는 `definition` 만 노출 / `(card_id, index)` 비고유 설명 | 7 |
| 13 | 트리거 파이프라인이 production 에서 닿지 않는다 | 6 |
| 14 | `engine/` 이 `EffectSpec.code` 를 읽지 않는다 (읽는 곳은 2곳) | 6 · 12 |
| 15 | `TRAP_TRIGGER_MISSING` 이 경계를 이름으로 부른다 / STRUCTURAL-7 | 12 |
| 16 | 정의·선언·ActionKind 칸 수가 그대로다 (10 · 9 · 11) | 10 |

### 회귀

| 항목 | 값 |
|---|---|
| 3-E-30 기준선 | 3716 passed · 4 skipped · 0 failed |
| 이번 | **3732 passed · 4 skipped · 0 failed** (423s) |
| 차 | +16 = 신규 그대로. 잃은 테스트 0 · 새 skip 0 · **regression 0** |

### 고의 위반 검증 — 10개

| 주입 | 깨뜨린 계약 | 잡혔는가 |
|---|---|---|
| A | `EffectDefinition` 에 `code` 칸 추가 | 2개 실패 ✅ |
| B | `TriggerSpec` 에 `code` 칸 추가 | 2개 실패 ✅ |
| C | `engine/ids.py` 가 `spec.code` 를 읽게 함 | 1개 실패 ✅ |
| D | `CardView` 에 `script` 노출 | 1개 실패 ✅ |
| E | `TimingPoint` 값을 `event_*` 로 바꿈 | 1개 실패 ✅ |
| F | `TriggerRegistry` 가 1:N 을 거부하게 함 | 1개 실패 ✅ |
| G | `TRAP_TRIGGER_MISSING` 에서 `EffectDefinition` 삭제 | 1개 실패 ✅ |
| H | 새 `ActionKind` 추가 | 1개 실패 ✅ |
| I | 파서가 `EVENT_*` 를 버리게 함 | **처음엔 안 잡혔다** → 아래 |
| J | I + 캐시 시그니처 갱신 | 3개 실패 ✅ (04 · 05 · 06) |

#### 주입 I 가 처음에 안 잡힌 것 — 파싱 캐시가 가렸다

파서를 고쳐도 **캐시가 옛 결과를 내주므로** 코퍼스 테스트가 그대로 통과했다.
`sources/lua_loader.py` 의 `_signature()` 를 `v4` → `v99` 로 올려 재파싱을
강제하자 `test_04` · `test_05` · `test_06` 이 **셋 다** 잡았다 (실행 시간도
8초 → 18초로 늘었다 — 실제로 다시 파싱했다는 증거).

이것은 테스트의 결함이 아니라 **파싱 캐시의 성질**이고, 저장소는 이미 그
규약을 갖고 있다 — 3-E-18 이 파서를 고칠 때 `_signature` 를 올려야 했던 것이
같은 자리다. 감사 소견으로 적어 둔다: **파서 회귀는 캐시 시그니처를 올리지
않으면 코퍼스 테스트에 보이지 않는다.**

## 16. Structural TODO

- **신규 STRUCTURAL ID: 없음.**
- 기존 TODO 변경: **없음.** 번호를 다시 매기지 않았다.

§16 의 세 조건으로 따졌다.

| 조건 | 충족 |
|---|---|
| 1. 진짜 아키텍처 문제인가 | 부분적 — 등록 범위의 문제다 |
| 2. **기존 TODO 로 표현할 수 없는가** | **표현된다** — **STRUCTURAL-7** (`analysis` → `EffectDefinition` 컴파일러). `engine/trigger.py:429,540` · `engine/effect/definition.py:680` · `engine/effect/library.py:14` 가 이름으로 부른다. `STRUCTURAL-21` 도 같은 뿌리로 묶여 있다 |
| 3. "미래 구현이 없다" 가 아닌가 | **그것이다** — 컴파일러를 아직 안 만든 것이다 |

조건 2·3 불성립 → 새 ID 를 만들지 않는다.

### 감사 소견 (ID 없이 기록)

1. **`engine.ids.iter_effects` 는 production 함수인데 호출자가 테스트뿐이다.**
   사건 값을 engine 으로 들여올 때 가장 먼저 볼 다리다. 새로 만들 필요가 없다.
2. **`Card.script.trigger_events` 는 권위가 없다.** 파일 전체 정규식이고
   "어느 효과에 붙었는지 모른다". 나중에 이것으로 트리거를 세면 틀린다 —
   권위는 `EffectSpec.code` 다. (`core/card_model.py` 가 이미 경고한다.)
3. **파서 회귀는 캐시 시그니처를 올리지 않으면 보이지 않는다** (§15 의 주입 I).

## 17. Final Decision

**A. SAME ARCHITECTURE — AUDIT-ONLY**

사건 의미는 **의도적으로 등록 계층의 것**이고, 원천 값은 파서 계층에 보존되어
있으며, `engine` 쪽 다리(`iter_effects`)도 이미 있다. 정의에 칸이 없는 것은
설계이며 데이터 손실이 아니다. production 결함이 없으므로 production diff 는
**0** 이다.

§15 의 B(미래 아키텍처 간극)도 일부 해당하지만 — 함정 5장이 전부
`EVENT_FREE_CHAIN` 인데 종류 단위로 막힌다는 사실 — 그것은 **STRUCTURAL-7 이
이미 덮고 있는 미래 구현**이고 새 ID 대상이 아니다. C(데이터 손실)와
D(production blocker)는 **측정이 부정한다.**

## 18. Next Phase Candidate

### 등재 함정 5장의 `EVENT_FREE_CHAIN` 을 `EffectDefinition` 으로 옮길 수 있는가 감사 (Free-Chain Registration Narrowing Audit)

- 측정된 사실: 등재된 함정 5장이 **전부 `EVENT_FREE_CHAIN`**(유발 조건 없음)
  인데 엔진은 `TRAP` **종류 전체**를 `UNKNOWN` 으로 막는다. 즉 지금 막히는
  이유는 데이터가 없어서가 아니라 **그 사실을 engine 쪽으로 옮기지 않아서**다.
  그리고 옮길 다리(`engine.ids.iter_effects`)는 이미 있다.
- 볼 것: (a) "이 효과는 유발 조건이 없다" 를 `EffectDefinition` 의 **기존 칸**
  으로 표현할 수 있는가 — 예컨대 `activation=None` 과 `activation=Always()` 의
  차이가 그 뜻을 담을 수 있는가, 아니면 새 칸이 필요한가. (b) ADR-006 의 손
  등록 태도와 "파서 값을 읽어 쓰는 것" 이 충돌하는가 — `provenance` 가
  `OFFICIAL_LUA` 인 것과 같은 성질인가. (c) 종류 단위 `UNKNOWN` 을 효과 단위로
  좁히면 **어떤 카드가 새로 후보가 되는가**, 그리고 그것이 규칙상 옳은가
  (세트한 턴 · 스펠 스피드는 이미 있다 — 3-E-15 · 3-E-30).
- 왜 지금이 아닌가: 이번 Phase 는 "없는 것이 버그인가" 라는 닫힌 질문이었고
  답은 "아니다" 였다. (a) 는 `EffectDefinition` 의 칸 의미를 정하는 설계
  판단이므로 별도 감사가 필요하다.
- 왜 다음인가: 이 Phase 가 벽의 **정확한 모양**을 측정했다 — 값은 있고, 다리도
  있고, 막는 것은 종류 단위 보수성뿐이다. 그래서 다음 질문은 **"그 보수성을
  효과 단위로 좁히는 것이 안전한가"** 다. 트리거 파이프라인을 깨우지 않고도
  답할 수 있는 질문이다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
