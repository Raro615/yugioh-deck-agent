# Phase 2-F-2 — Chain 최소 실행 구조

기준 커밋: `bc445d8` (Phase 2-F-1)

```
ChainLink (발동하기로 결정된 효과 하나)
    ↓  chain.push(link)
Chain     [L1, L2, L3]          발동 순서
    ↓  ChainResolver.resolve_top(state, chain)
L3 → L2 → L1                    해결 순서 (LIFO)
    ↓  EffectExecutor.execute(...)
GameState 변경 + StateDelta + EventJournal
```

이 단계가 만드는 것은 **"무엇을 언제 해결하는가"** 뿐이다.

---

## 1. 작업 전 검수 결과

| 읽은 것 | 확인한 사실 |
|---|---|
| `engine/priority.py` | `PriorityState` 는 체인을 모른다. `both_passed` 는 사실만 말한다 |
| `engine/effect/resolution.py` | `ResolutionContext(effect_ref, controller, source, selections, cost_selections)` — 링크 하나를 해결하는 데 필요한 것이 **이미 다 있다** |
| `engine/effect/executor.py` | `execute(state, definition, context)` — 계획 후 적용, Delta 생성, journal 기록까지 전부 한다 |
| `engine/effect/definition.py` | `EffectImplementationLookup`(실행 허가)은 있는데 **정의를 찾는 수단은 없었다** |
| `engine/effect/journal.py` | `EventKind.EFFECT` / `COST_PAYMENT`, `sequence` 기반 identity |
| `engine/payment.py` | `CostPayment` 영수증이 이미 있다 |
| `engine/cost/`, `engine/effect/target.py` | `ChoiceSpec`/`CandidateSet`/`Selection`/`TargetSelection` |

**체인 구조는 없었다.** `ResolutionContext` 는 그대로 쓸 수 있어서
`resolution.py` 는 **한 줄도 바꾸지 않았다.**

새로 필요했던 것은 하나뿐이다: 링크가 `EffectRef` 만 들고 있으므로 거기서
정의로 가는 길. `EffectDefinitionSource` Protocol + `EffectDefinitionRegistry`
를 `definition.py` 에 추가했다 (`EffectImplementationLookup` 옆).

> 정의를 찾을 수 있는 것과 실행할 수 있는 것은 **다른 질문**이다 (ADR-006).
> 그래서 인터페이스를 두 개로 둔다.

---

## 2. 세 가지를 한 곳에 몰아넣지 않는다

| | 답하는 질문 | 어디 |
|---|---|---|
| `PriorityState` | 누가 다음 응답 기회를 갖는가 | Phase 2-F-1 |
| `Chain` | 지금 어떤 효과들이 연결되어 있는가 | 여기 |
| `ChainResolver` | 연결된 효과를 어떤 순서로 해결하는가 | 여기 |

`PriorityState.resolve_chain()` 같은 것은 **만들지 않았다.** 두 모듈이 서로를
import 하지 않는지 테스트가 소스를 읽어 확인한다.

패스가 체인을 해결하지 않고, 체인 해결이 우선권을 돌리지 않는다. 둘을 잇는
것은 이후 단계의 몫이다.

---

## 3. `ChainLink` — 이미 발동하기로 결정된 효과 하나

```python
ChainLink(sequence, actor, effect_ref, source, selections, payments)
```

발동해도 되는지는 **여기서 판정하지 않는다.** 링크가 만들어졌다는 것은 그
결정이 이미 끝났다는 뜻이다 (발동 합법성 계층은 아직 없다).

- **정의를 복사해 넣지 않는다.** `EffectRef(card_id, ordinal)` 만 들고 있고
  정의는 등록소에서 찾는다. 박아 두면 링크가 낡은 정의를 영구히 들고 다닌다.
- `EffectSpec.index` (Lua 변수명 `"e1"`, 한 카드 안에서 중복 — 실측 4,884장)
  를 실행 identity 로 쓰지 않는다.
- `sequence` 는 0부터. `chain_number` 가 사람이 부르는 "체인 1" 이다.
- `GameState` · `GameStateView` · `CardInstance` 를 담지 않는다 (테스트가
  필드 타입을 직접 확인한다).

### 선택 결과는 보존하고 다시 계산하지 않는다

후보(`CandidateSet`)와 고른 결과(`Selection`)는 다른 것이다. 링크가 담는
것은 결과뿐이고, `candidates` 도 `resolve_candidates` 도 없다.

### 비용은 이미 치러진 것으로 본다

```
Cost → CostSelection → CostPayer.pay() → CostPayment (영수증)
                                              ↓
                                        ChainLink 생성
```

`resolution_context()` 는 `cost_selections` 를 **비운다.** 비용은 링크가
만들어지기 전에 치러졌고, 무엇을 냈는지는 `payments` 에 있다. 문맥에 다시
넣으면 실행기가 두 번 치를 길이 생긴다.

`CostPaymentEvent.effect_ref` 연결이 아직 선택적이므로 (STRUCTURAL-16) 그것을
우회하는 구조를 만들지 않고, 링크가 자기 `effect_ref` 를 따로 갖는다.

---

## 4. `Chain` — 쌓인 것과 어디까지 해결했는가

```python
Chain(links: tuple[ChainLink, ...], resolved_count: int)
```

`links` 는 **발동 순서**(체인 1 이 앞), 해결은 뒤에서부터 (LIFO).
`resolved_count` 가 뒤에서 몇 개를 해결했는지 말한다.

| 조회 | |
|---|---|
| `is_empty` | 쌓인 것이 없다 |
| `is_complete` | 남은 것이 없다 — **`is_empty` 와 다른 사실** |
| `top` | 다음에 해결할 링크 (LIFO) |
| `pending` / `resolved` / `remaining` | 남은 것 / 해결한 것 / 남은 수 |
| `resolution_order` | 해결될 순서 전체 (발동 역순) |

전이는 전부 새 체인을 돌려준다: `push(link)` · `activate(...)` ·
`advanced()`. `append`/`pop`/`insert` 는 **없고**, `links` 는 tuple 이다.

번호가 어긋난 링크는 **거부한다** — 조용히 다시 매기면 기록과 실제 발동
순서가 달라진 것을 아무도 모르게 된다 (`EventJournal.append` 와 같은 태도).

### 해결이 시작된 체인에는 쌓을 수 없다

규칙상 가능한지의 문제가 아니라 **LIFO 순서와 번호를 구조적으로 표현할 수
없기** 때문이다. 해결 중 발동을 다루는 것은 타이밍 계층의 몫이다.

### 판 밖에 산다

`GameState` 안에 넣지 않는다. 체인은 판의 *모양*이 아니라 흐름의 위치이고,
`state_hash()` 에 섞으면 "같은 판" 의 뜻이 달라진다 (`EventJournal` ·
`PriorityState` 와 같은 이유). `GameState.journal` 자리표시도 여전히 비어
있다.

---

## 5. `EffectExecutor` 와의 경계

```
ChainResolver     무엇을 언제 해결할 것인가
EffectExecutor    주어진 EffectDefinition 을 실제로 적용하는 방법
```

`ChainResolver` 는 `EffectExecutor` 를 **받는다**. `move` · `draw` ·
`change_life` · `_plan` · `_apply` 를 갖고 있지 않고, 테스트가 그 부재를
확인한다. Delta 도 Journal 도 실행기가 하던 그대로 만들어진다 — 체인이 따로
적으면 같은 사건이 두 번 남는다.

이 경계가 지켜졌다는 **증거**:
`test_resolving_through_a_chain_leaves_the_same_trace_as_resolving_directly`
가 체인을 거친 해결과 직접 해결의 `state_hash` · `EffectResult` ·
`journal_hash` 를 **세 개 모두** 비교한다. 다르면 체인이 실행기를 흉내 내고
있다는 뜻이다.

### 실패한 링크를 건너뛰지 않는다

"해결할 수 없는 링크는 불발된다" 는 유희왕 규칙이 있지만 **그것은 규칙**이고
이 단계에 없다. 지어내지 않고 멈춘 뒤 부르는 쪽에 알린다. `resolve_all` 은
첫 실패에서 멈추고, `resolved_count` 는 늘어나지 않는다.

### 실패 분류

| `ChainResolutionStatus` | 뜻 |
|---|---|
| `RESOLVED` | 적용되었다 |
| `EMPTY_CHAIN` | 쌓인 것이 없다 |
| `CHAIN_COMPLETE` | 남은 것이 없다 |
| `INVALID_CHAIN_LINK` | 정의를 찾을 수 없음 · 문맥 불일치 · 대상 문제 |
| `FORBIDDEN_EFFECT` | 출처가 실행을 금지한다 (`TEXT_DERIVED`, ADR-004) |
| `UNSUPPORTED_EFFECT` | 실행기가 다루지 못한다 |
| `EFFECT_NOT_APPLIED` | 적용하지 않았다 — 이유는 `result` 에 |
| `EFFECT_RESOLUTION_ERROR` | 적용 중 오류 |

`FORBIDDEN_EFFECT` 를 `UNSUPPORTED_EFFECT` 와 **합치지 않았다.** "이 엔진이
못 한다" 와 "이 근거로는 절대 실행하지 않는다" 는 전혀 다른 말이다.

`STATUS_MAP` 이 `ResolutionStatus` **전부**를 덮는지 테스트가 확인한다 —
하나라도 빠지면 그 결과가 조용히 기본값으로 분류된다. 그리고 거친 분류가
무엇을 뭉개든 **정확한 이유는 언제나 `ChainResolution.result` 에** 그대로
남는다.

---

## 6. StateDelta · EventJournal 연결

```
ChainLink resolved → EffectResult → deltas → journal
```

`ChainResolution.deltas` 는 실행기의 기록을 그대로 내보낸다. `RESOLVED` 가
아닌데 변화 기록이 붙어 있으면 **생성 자체가 거부된다.**

기록은 해결 순서대로 쌓인다 — 3-링크 체인은 journal 에 체인 3 → 2 → 1 순으로
남고, 각 `EffectEvent.deltas` 가 그 단계의 `ChainResolution.deltas` 와 같다.

실패하면 `state_hash` 도 journal 도 그대로다. 7가지 실패 전부에서 확인한다.

---

## 7. 구현하지 않은 것

Trigger · Timing engine · when/if · 임의/강제 · SEGOC · trigger ordering ·
Damage Step timing · Spell Speed · 발동 합법성 · 자동 우선권 계산 ·
ActionExecutor · Summon · Battle · Damage · Turn progression · 승패 판정 ·
AI · search/planning · 카드별 체인 처리 · 정의 자동 생성 (STRUCTURAL-7) ·
`TEXT_DERIVED` 실행 허용 · 불발(fizzle) 규칙.

`resolution.py` · `executor.py` · `payment.py` · `priority.py` ·
`game_state.py` 는 **한 줄도 바꾸지 않았다.**

---

## 8. 테스트

`tests/engine/test_chain.py` — 58개.

| 묶음 | 보는 것 |
|---|---|
| ChainLink | 생성 · 불변 · **정의/판 미보유** · `EffectRef` 사용 · 선택 보존(재계산 없음) · 영수증 보유(재지불 없음) · 문맥 생성 · 잘못된 링크 · 이름 중복 |
| Chain 쌓기 | 원본 불변 · 순서 보존 · mutable 목록 미노출 · 번호 어긋남 · 구멍 · **해결 중 push 거부** · 타입 |
| LIFO | 역순 · 빈 체인 · **빈 것 ≠ 다 한 것** · 1/2/3 링크 · 진행 추적 · 완료 후 advance · 조회가 해결하지 않음 |
| 실패 | 정의 없음 · unsupported · **`TEXT_DERIVED` ≠ unsupported** · 구현 미등록 · 조건 거짓/모름 · `resolve_all` 정지 · 변화 사칭 거부 · `bool()` 거부 · **`STATUS_MAP` 전수** |
| Delta · Journal | Delta 전달 · 해결 순서대로 기록 · 체인이 따로 적지 않음 · **직접 해결과 동일한 흔적** · 적용 메서드 부재 · 관측 거부 |
| 결정론 | 평문 직렬화 · 값 비교 · 같은 입력 → 같은 결과 · **`PYTHONHASHSEED` 3종 별도 프로세스** |
| 우선권 분리 | 상호 import 부재 · 패스가 체인을 안 건드림 · 양쪽 패스가 체인을 결정하지 않음 |
| 가려진 정보 | 체인이 판을 읽지 않음 · 링크는 발동자가 준 것만 담음 · **상대 패가 달라도 같은 해결** |
| Mutation safety | 조회가 판을 안 건드림 · `clone()` 독립 · 체인은 판 해시에 없음 · 내부 선택 미노출 |

전체 회귀: **1315 passed, 4 skipped** (Phase 2-F-1 기준 1257 + 58).
