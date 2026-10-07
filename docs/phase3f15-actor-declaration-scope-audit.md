# Phase 3-F-15 — Actor Declaration Scope / actor 없는 result 계약 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-15 — Actor Declaration Scope 감사 |
| 모드 | **AUDIT-ONLY** — production diff **0** |
| **실제 HEAD (측정)** | `b3601a4 Phase 3-F-14: document EventReader actor input contract` |
| Base (3-F-14) | `c016992` (작업) · `b3601a4` (보고서) — **둘 다 실존** (`git cat-file -t`) |
| 3-F-14 최종 판정 | **A. ACTOR_INPUT_CONTRACT_ENFORCED** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,384 passed / 4 skipped |
| 신규 테스트 | `tests/test_actor_declaration_scope_audit.py` — **28건** (함수 24, 하나가 ×5) |

---

## 2. Phase 3-F-14 계약 요약 (그대로 유지한다)

| 부르는 모양 | 뜻 | 결과 |
| --- | --- | --- |
| `read(r, actor=0\|1)` | ACTOR_DECLARED | 그 값 |
| `read(r, actor=None)` | INTENTIONAL_NONE | `None` |
| `read(r)` | ACTOR_OMITTED | **`TypeError`** |

`test_22` 가 이 셋을 다시 확인한다. `TimingEvent.actor`(귀속자) ·
`EventContext.actor`(행위자) · `ObservedEvent.actor`(사건 쪽) 계약도 그대로다.

---

## 3. 🔴 이 Phase 가 새로 찾은 것 셋

### ① `CostPaymentResult` 는 UNKNOWN 이 아니다 — **B 다**

3-F-14 는 이것을 "`UNKNOWN` 그대로" 로 남겼다. **그 분류가 너무 약했다.**

- 결과에 `actor` · `action` 칸이 없다 — 여기까지는 3-F-14 와 같다.
- 🔴 그런데 **`payments[*].player` 가 있다.** 결과 **안에** 사람 칸이 있다.
- 그리고 payer 는 상류 `PaymentContext.payer` 에 **있다.**

"정보가 없다"(C) 가 아니라 **"있는데 전달되지 않는다"**(B) 다. 3-F-14 가 C 로
적은 까닭은 **결과만 보고 상류를 보지 않았기** 때문이다 (`test_06`).

### ② 🔴 `CostPayment.player` 는 actor 가 아니라 **affected player** 다

`LifeCost(who=OPPONENT)` 로 재면 **한 판에서 둘이 갈린다.**

| 값 | 측정 | 뜻 |
| --- | --- | --- |
| `PaymentContext.payer` | **0** | 행위자 — 지불을 일으킨 쪽 |
| `CostPaymentEvent.actor` | **0** | 행위자 (payer 에서 온다) |
| `CostPayment.player` | **1** | 🔴 **affected** — LP 가 줄어든 쪽 |
| `LifeChanged.player` | **1** | 귀속자 |

LP 는 `P1` 이 8000 → 7000 이고 `P0` 은 8000 그대로다. 그러므로 **"결과 안에
사람 칸이 있으니 그것을 actor 로 쓰자" 는 §3 이 금지한 바로 그 혼동이다**
(`test_08`).

`CostPayment.player` 는 `cost.who.resolve(condition_context)` 로 정해진다 —
`PlayerRef.CONTROLLER` 면 payer, `OPPONENT` 면 그 상대다. 즉 **비용의 대상**이다.

### ③ 🟡 `controller == actor` 는 게임 규칙이 아니라 **대입** 때문이다

production 경로가 **한 줄씩** 잇는다.

```
PlayerAction.actor
   ├─→ PaymentContext(payer=action.actor)              engine/activation.py
   └─→ ChainLink(actor=action.actor)                   engine/activation.py
           └─→ ResolutionContext(controller=self.actor)  engine/chain.py
```

생성 자리가 **각각 하나**뿐이라 다른 값이 들어올 길이 없다 (`test_12`).

그래서 지금 `controller` 와 `payer` 가 행위자인 것은 **코드 구조** 때문이고,
"효과는 컨트롤러가 해결한다" 는 게임 규칙과 **결론만 같다.** 컨트롤 이동이
구현되면 "발동한 사람" 과 "해결 시점의 컨트롤러" 가 갈리는데, `ChainLink.actor`
하나로는 둘을 표현할 수 없다.

→ **그래서 이 Phase 는 `controller` 를 actor 로 쓰는 계약을 만들지 않았다.**

---

## 4. actor / controller / player / affected player 구분 (§3)

| 개념 | 어디에 있나 | 측정 |
| --- | --- | --- |
| **actor** | `PlayerAction.actor` · `ChainLink.actor` · `EffectEvent.actor` · `CostPaymentEvent.actor` · `EventContext.actor` | 사건을 **일으킨** 쪽 |
| **controller** — ① 효과의 | `ResolutionContext.controller` | = actor (대입) |
| **controller** — ② **카드의** | `CardInstance.controller` | 🔴 **≠ actor** |
| **player** | `CostPayment.player` · `delta.player` · `TimingEvent.actor` | 귀속·대상 |
| **affected player** | 전용 칸이 **없다** — `delta` 의 사람 칸이 사실상 그것이다 | 영향을 받은 쪽 |

### 🔴 `controller` 라는 말이 두 가지를 가리킨다

상대 몬스터를 건드리는 효과에서 측정하면:

- 대상 카드의 `CardInstance.controller` = **1** (당한 쪽)
- `ResolutionContext.controller` = **0** (행위자)

두 클래스에 **같은 이름의 칸이 둘 다 있다.** 그래서 "controller 를 actor 로
쓴다" 는 문장은 **어느 controller 인지** 말하지 않으면 뜻이 없다 (`test_09`).

### 금지된 네 가지를 실측으로 확인했다

| 금지 | 반례 | 측정 |
| --- | --- | --- |
| `result.controller` → actor | 위의 두 가지 뜻 | `test_09` |
| `result.player` → actor | `LifeCost(who=OPPONENT)` | `test_08` |
| `timing.actor` → actor | Battle (귀속 0 · 행위 1) | `test_11` |
| `delta.player` → actor | 강욕의 보은 (사람 칸 전부 1 · 행위자 0) | `test_10` |

---

## 5. Result 타입별 actor 계약 (§4)

**타입 이름으로 판정하지 않고 생성 경로를 따라갔다.**

| Result | action | actor 직접 | actor 파생 | controller/player | semantic actor | **read actor 계약** |
| --- | --- | --- | --- | --- | --- | --- |
| `ActionExecution` | ○ `PlayerAction` | ✗ | ○ `action.actor` (필수 int) | ✗ | **존재** | **REQUIRED_ACTOR** |
| `ActivationResult` | ○ `PlayerAction` | ✗ | ○ `action.actor` | ✗ | **존재** | **REQUIRED_ACTOR** |
| `EffectEvent` | ✗ | **○ 필수 int** | — | (actor 가 `controller` 에서 온다) | **존재** | **REQUIRED_ACTOR** |
| `CostPaymentEvent` | ✗ | **○ 필수 int** | — | (actor 가 `payer` 에서 온다) | **존재** | **REQUIRED_ACTOR** |
| `EffectResult` | ✗ | ✗ | ✗ | 상류 `ResolutionContext.controller` | **존재** | **CONTEXT_DEPENDENT** |
| `CostPaymentResult` | ✗ | ✗ | 🔴 **아니다** — `payments[*].player` 는 affected | 상류 `PaymentContext.payer` | **존재** | **CONTEXT_DEPENDENT** |
| `ProgressionResult` | ✗ | ✗ | ✗ | **없다** (상류도 사람을 받지 않는다) | **없다** | **EXPLICIT_NONE** |

### `ProgressionResult` 가 A 인 구조적 증거

`TurnProgressor.advance(state)` 의 매개변수에 `actor` 도 `player` 도 **없다.**
결과도, `TransitionPlan` 도, `PhaseTransition` 도 사람 칸이 없다. 즉 "행위자가
없다" 가 **데이터 부재가 아니라 개념 부재**다 (`test_07`).

### `UNKNOWN` 은 **하나도 없다**

일곱 중 어느 것도 "현재 데이터로 결정할 수 없는" 것이 없다. 상류가 전부 안다.

---

## 6. `CostPaymentResult` 정밀 분석 (§5 의 여덟 질문)

| # | 질문 | 답 |
| --- | --- | --- |
| 1 | actor 가 없는가? | **없다** (`actor` · `action` 칸이 모두 없다) |
| 2 | 지불한 player/controller 를 다른 필드에서 알 수 있는가? | 🔴 **`payments[*].player` 가 있다** |
| 3 | 그 값이 실제 semantic actor 인가? | 🔴 **아니다 — affected player 다** (`who=OPPONENT` 로 측정) |
| 4 | cost payment 를 "행위" 로 봐야 하는가? | **그렇다** — 발동 절차의 일부이고 행위자는 발동한 쪽이다. 다만 **무엇이 줄어드는가**는 별개다 |
| 5 | event 와 result 의 actor 의미가 같은가? | **event 쪽만 actor 다.** `CostPaymentEvent.actor` = `payer` (행위자) · `CostPaymentResult.payments[*].player` = 대상 |
| 6 | `actor=None` 이 INTENTIONAL_NONE 인가? | **아니다** — 행위자가 존재한다 |
| 7 | 정보 부족 때문에 UNKNOWN 인가? | **아니다** — 상류 `PaymentContext.payer` 가 안다 → **B** |
| 8 | 향후 Trigger/EventRelation 이 읽을 가능성이 있는가? | **지금은 없다** — 아래 참조 |

### 🔴 실제 카드 16장 전부 `CostGroup(costs=())` 다

라이브러리 전수를 세면 **16장 모두 비용이 비어 있다.** 그래서
`CostPaymentResult` 가 delta 를 들고 나오는 경로가 production 에 **없다.**

이것이 두 가지를 뜻한다.

1. 이 Phase 가 synthetic 비용(`LifeCost`)을 쓴 까닭이다 — 어떤 실제 카드의
   재정도 주장하지 않는다.
2. **지금 틀린 값이 production 판단을 오염시키고 있지 않다.** 비용 있는 카드가
   들어오면 `test_21` 이 **깨진다** — 그때가 §5 8 이 물은 "Trigger/EventRelation
   이 이 값을 읽을 가능성" 이 실제가 되는 시점이고, 깨지는 것이 신호다.

---

## 7. actor 없는 result 의 삼분 (§7)

| 분류 | 해당 result | 근거 |
| --- | --- | --- |
| **A. NO_ACTOR_BY_SEMANTICS** | `ProgressionResult` | 상류조차 사람을 받지 않는다 → `actor=None` 이 **정당** |
| **B. ACTOR_EXISTS_BUT_NOT_CARRIED** | `EffectResult` · `CostPaymentResult` | 상류(`controller`/`payer`)가 안다. 결과가 들고 나오지 않는다 → **구조적 provenance gap** |
| **C. ACTOR_NOT_DETERMINABLE** | **없다** | 일곱 중 결정 불가인 것이 하나도 없다 |

🔴 **C 가 비어 있다는 것이 이 Phase 의 결론 하나다.** B 와 C 를 섞지 말라는 §7 의
요구가, 실제로는 **"C 라고 적어 둔 것이 B 였다"** 로 판명됐다.

> 🟡 다만 `read_deltas(deltas, …)` 로 **delta 만** 넘기는 경로는 C 에 해당할 수
> 있다 — 부르는 쪽이 출처를 모르는 delta 를 들고 있을 수 있기 때문이다. 그것은
> result 타입의 성질이 아니라 **호출 방식**의 성질이므로 위 표에 넣지 않았다.

---

## 8. 실제 듀얼 시나리오 (§8)

실제 카드 **다섯 장**과 전투 · 소환 · synthetic 비용 · synthetic 이동을 합쳐
**아홉 경우**를 쟀다.

| # | Scenario | actor | controller | affected player | `timing.actor` | result | 계약 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 일반 소환 (실제) | **P0** | — | P0 | P0 | `ActionExecution` | REQUIRED_ACTOR |
| 2 | 효과 발동 (욕망의 항아리) | **P0** | P0 (효과) | — | — | `ActivationResult` | REQUIRED_ACTOR |
| 3 | 욕망의 항아리 해결 | **P0** | P0 | P0 · P0 | P0 · P0 | `EffectResult` | CONTEXT_DEPENDENT |
| 4 | 천사의 자비 (내 LP +1000) | **P0** | P0 | P0 | P0 | `EffectResult` | CONTEXT_DEPENDENT |
| 5 | **자비의 비** (양쪽 LP +1000) | **P0** | P0 | 🔴 **P0 · P1** | P0 · P1 | `EffectResult` | CONTEXT_DEPENDENT |
| 6 | **강욕의 보은** (상대가 2장 뽑는다) | **P0** | P0 | 🔴 **P1 · P1** | P1 · P1 | `EffectResult` | CONTEXT_DEPENDENT |
| 7 | **졸부 고블린** (내가 뽑고 상대 LP +1000) | **P0** | P0 | 🔴 **P0 · P1** | P0 · P1 | `EffectResult` | CONTEXT_DEPENDENT |
| 8 | 전투 (P1 이 P0 공격) | **P1** | — | P0 | P0 | `ActionExecution` | REQUIRED_ACTOR |
| 9 | 비용 지불 `who=OPPONENT` (synthetic) | **P0** | — | 🔴 **P1** | P1 | `CostPaymentResult` | CONTEXT_DEPENDENT |

### 🟢 선언 하나가 아홉 경우를 전부 옳게 적는다

`actor=P0` 라는 **같은 선언 하나**가 3 · 4 · 5 · 6 · 7 · 9 를 전부 맞춘다. 그
여섯에서 affected 는 `{P0}` · `{P0}` · `{P0,P1}` · `{P1}` · `{P0,P1}` · `{P1}`
로 **다 다르다.** 즉 **actor 는 invocation 의 속성**이고 delta 의 속성이 아니다.

**졸부 고블린**이 가장 또렷하다 — 한 번의 발동이 **종류가 다른 두 사건**
(`card_drawn` · `life_changed`)을 내고 affected 가 서로 다른데, 행위자는 하나다
(`test_17`).

### 🟡 "상대 카드 파괴" 는 실제 카드로 delta 를 얻지 못했다

싸이크론은 `unchecked_target`(가려진 정보로 대상 적법성 판정 불가), 강제 탈출
장치는 관문(`IsAbleToHand` = UNKNOWN)에서 멈춘다. 그래서 이동의 **의미만**
synthetic `ZoneMoved(DESTROY)` 로 봤고, 어떤 실제 카드의 재정도 주장하지 않는다
(`test_18`). 두 사람 칸이 **모두 주인**이라 가해자 칸이 없다는 사실은 그대로다.

---

## 9. 현재 API 적합성 (§9)

### **A. 모든 호출자가 actor 또는 explicit None 을 선언하는 것이 맞다.**

일곱 타입이 **두 모양**으로 전부 표현된다 — `actor=<값>` 과 `actor=None`. 타입별
API 가 필요하다는 증거가 **없다** (`test_19`).

그리고 `read()` 는 **타입을 보지 않는다** — `getattr(result, "deltas", …)` 뿐이고
`isinstance(result, …)` 가 없다. 타입별 계약을 만들면 **그 분기가 곧 갈라질
자리**가 된다 (`_timing_for` 가 Phase 2-AJ 에서 두 벌로 갈려 실제 카드가 한쪽만
죽은 그 일이다) (`test_20`).

### 🔴 다만 API 가 막지 **못하는** 것이 하나 있다

```python
read(gift_of_greed_result, actor=None)   # 통과한다
```

강욕의 보은의 행위자는 **P0 으로 존재한다.** 그런데 `actor=None` 이라고 선언하면
그대로 들어가고, 받는 쪽에서는 **페이즈 전환의 `None` 과 구별되지 않는다.**

3-F-14 가 막은 것은 **말하지 않는 것**이고, **틀리게 말하는 것**은 그대로 열려
있다 (`test_15`). 이것이 B 분류를 "해결됨" 으로 적지 않는 까닭이다.

---

## 10. production 변경 여부

```
$ git diff --stat HEAD -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**AUDIT-ONLY.** §11 의 일곱 조건 중 **조건 2 가 깨진다.**

| # | 조건 | 판정 |
| --- | --- | --- |
| 1 | 현재 계약이 실제 semantic 오류를 일으킬 수 있음 | **○** — `actor=None` 이 알려진 행위자를 숨길 수 있다 (§9) |
| 2 | 올바른 계약이 코드/게임 규칙으로 **명확히 증명**됨 | 🔴 **✗** |
| 3 | 변경 범위가 actor 입력 경계에 한정 | ○ |
| 4 ~ 7 | freeze · EventRelation · pipeline · AI/Search | 전부 ○ (건드리지 않았다) |

### 조건 2 가 깨지는 이유

B 를 메우는 방법이 둘인데 **어느 쪽이 옳은지 이 Phase 가 증명하지 못했다.**

1. **result 가 자기 actor 를 밝힌다** — `EffectResult`/`CostPaymentResult` 에
   actor 를 담는다. 🔴 그런데 그러면 §10 이 금지한 **새 field** 가 된다.
2. **`read()` 가 `controller`/`payer` 를 읽는다** — 🔴 그런데 §3 의 ③ 이 말한
   대로 `controller == actor` 는 **대입 때문에** 참이고 게임 규칙으로 증명된 것이
   아니다. 컨트롤 이동이 들어오면 깨진다.

→ 둘 다 **증거가 모자라다.** 그래서 고치지 않고 다음 Phase 후보로만 적는다.

§10 의 금지 field/enum — `actor_type` · `actor_source` · `actor_kind` ·
`cause_player` · `affected_player` · `controller_player` · `ActorOrigin` ·
`ActorRequirement` — **하나도 추가하지 않았다** (`test_23`).

---

## 11. 테스트

### 신규 `tests/test_actor_declaration_scope_audit.py` — 28건

| # | 무엇을 고정하나 | §12 항목 |
| --- | --- | --- |
| 01 | `ActionExecution` — `action.actor` 필수 int | 1 |
| 02 | `ActivationResult` — 같은 모양 | 2 |
| 03 | `EffectEvent` — actor 직접 보유 (= 효과 controller) | 3 |
| 04 | `CostPaymentEvent` — actor = payer. **상대가 내도 actor 는 나** | 4 |
| 05 | `EffectResult` — 칸 없음, 상류가 안다 | 5 |
| 06 | 🔴 `CostPaymentResult` 는 **UNKNOWN 이 아니라 B** | 6 |
| 07 | `ProgressionResult` — 상류조차 사람을 받지 않는다 | 7 |
| 08 | 🔴 `CostPayment.player` 는 **affected player** | 11 |
| 09 | 🔴 `controller` 가 두 가지를 가리킨다 | 10 |
| 10 | `delta.player` ≠ actor (강욕의 보은) | 12 |
| 11 | `timing.actor` ≠ actor (Battle) | 13 |
| 12 | 🟡 `controller` 는 `action.actor` 에서 **대입**된다 | 10 |
| 13 | 일곱 result 의 **A · B · C 삼분** — C 는 비어 있다 | — |
| 14 | `actor=None` 이 **정당한** 경우 | 8 |
| 15 | 🔴 `actor=None` 이 **알려진 actor 를 숨기는** 경우 | 9 |
| 16 | **실제 카드 5장** (parametrize ×5) — actor 하나 · affected 다섯 가지 | 14 · 15 |
| 17 | **졸부 고블린** — 한 발동, 두 사건, 서로 다른 affected | 15 |
| 18 | 카드 이동 — 가해자 칸 없음 (synthetic, 근거 명시) | — |
| 19 | **한 API 가 일곱 계약을 표현한다** (§9 답 A) | — |
| 20 | `read()` 가 result 타입을 보지 않는다 | — |
| 21 | 🔴 실제 카드 16장 전부 **비용이 비어 있다** | §5 8 |
| 22 | 3-F-14 계약 불변 | §13 |
| 23 | production diff 0 · 금지 field 없음 · dormant 유지 | §11 |
| 24 | `state_hash` · RNG · hidden-information 불변 | §14 |

**금지 사항 전부 준수**: assertion 삭제 0 · skip 추가 0 · `UNKNOWN → None` 강제
변환 0 · `controller`/`player → actor` 일괄 치환 0.

### 고의 위반 검증 — 8건, 전부 잡혔다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `ResolutionContext.controller` 를 상수로 바꾼다 | 2건 — `test_12` · `test_23` |
| 2 | `PaymentContext.payer` 를 action 에서 떼어낸다 | 2건 — `test_12` · `test_23` |
| 3 | 🔴 `CostPayment.player` 를 payer 로 **"고친다"** (§3 혼동) | **5건** — 04 · 06 · 08 · 19 · 23 |
| 4 | `read()` 가 result 타입마다 분기한다 | 3건 — 19 · 20 · 23 |
| 5 | `EffectEvent.actor` 를 `None` 허용으로 | 2건 — `test_03` · `test_23` |
| 6 | `TurnProgressor.advance` 가 actor 를 받는다 (A 분류 파괴) | 3건 — 07 · 13 · 23 |
| 7 | 실제 카드 하나에 **비용을 붙인다** | 2건 — `test_21` · `test_23` |
| 8 | `EventContext` 에 `actor_source` 칸을 더한다 (§10 위반) | 3건 — 15 · 17 · 23 |

**3번이 가장 중요하다.** `CostPayment.player` 를 payer 로 바꾸면 "결과가 actor 를
들고 있게" 되어 편리해 보이는데, 그것이 §3 이 금지한 혼동이고 **5건이 걸린다.**
7번은 "비용 있는 카드가 들어오면 알게 된다" 는 장치가 실제로 작동함을 보인다.

주입 파일 7개(`chain.py` · `activation.py` · `payment.py` · `event_pipeline.py` ·
`turn_progression.py` · `effect/journal.py` · `effect/library.py`)는 전부 백업에서
복원하고 md5 로 확인했다 (8회 전부 `OK`).

### 전체 회귀

```
4412 passed, 4 skipped in 444.97s (0:07:24)
```

`4,384` (3-F-14) `+ 28` (신규) `= 4,412`. **첫 실행에서 실패 0** 이고 skip 은
그대로 4건이다. production diff 가 0 이므로 기존 테스트가 움직일 이유가 없었고,
실제로 움직이지 않았다 — 3-F-14 가 48건을 깨뜨린 것과 대비된다.

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리

**삭제 0건 · skip 추가 0건 · assertion 약화 0건 · 수정 0건.**

production 을 한 줄도 바꾸지 않았으므로 기존 테스트가 움직일 이유가 없었다.

---

## 12. state_hash / RNG / Search / AI 영향 (§14)

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 선언해 읽든, "없다" 고 읽든, **거부당해도** 동일 (`test_24`) |
| RNG | **불변** | `repr(state.rng)` 동일 · 같은 seed 두 번 → 같은 `state_hash` |
| hidden-information | **불변** | 상대 패·덱은 `concealed` |
| Search ranking | **불변** | digest `30fa3597…402c4175` (6 duel · 611 decision) — 기존 3개 파일이 고정하고 전체 회귀에서 통과. **네 번째 사본을 만들지 않았다** |
| AI behavior | **불변** | production diff 0 · `agent/` 는 `event_pipeline` 을 import 하지 않는다 |
| Engine V1 freeze | **유지** | production diff 0 |
| §11 4~7 금지 | **전부 미실행** | EventRelation 연결 ✗ · pipeline 활성화 ✗ · AI/Search ✗ |

---

## 13. 최종 판정

### **B. ACTOR_LESS_RESULT_CONTRACT_GAP**

**actor 없는 result 중 둘이 "실제로 actor 는 존재하지만 전달되지 않는" 구조적
공백을 가진다.**

| result | 행위자가 있는 곳 | 결과가 들고 있는가 |
| --- | --- | --- |
| `EffectResult` | `ResolutionContext.controller` | **아니다** |
| `CostPaymentResult` | `PaymentContext.payer` | **아니다** — 들고 있는 `payments[*].player` 는 **affected** 다 |

### 왜 A 가 아닌가

A 는 "계약이 명확하며 현재 API 로 **안전하게** 표현 가능" 이다. 계약은
명확해졌고(§5 의 표) API 도 표현할 수 있다(§9). 그러나 **안전하지 않다** —
두 result 에서 호출자가 **결과가 버린 문맥을 따로 들고 있어야** 하고, 그러지
못하면 `actor=None` 으로 **알려진 행위자를 숨긴 채** 통과한다 (§9 · `test_15`).
"표현 가능" 과 "안전" 은 다르다.

### 왜 C 가 아닌가

C 는 "`controller`/`player`/`actor` 관계가 현재 구조만으로 **확정되지 않는다**"
이다. **확정했다.** `controller` 의 두 뜻을 갈랐고(`test_09`), `payer` 와
`CostPayment.player` 가 다르다는 것을 실측했고(`test_08`), 대입 경로를 한 줄씩
짚었다(`test_12`). 모호한 것이 아니라 **빠진 것**이다.

### 왜 D 가 아닌가

D 는 "현재 `read()` 하나로는 안전하게 표현하기 어렵다" 이다. 일곱 타입이
`actor=<값>` 과 `actor=None` **두 모양**으로 전부 표현된다(`test_19`), 그리고
타입별 분기를 넣으면 그 자리가 곧 갈라진다(`test_20`). **API 가 거친 것이 아니라
result 가 덜 담은 것이다.**

### 왜 E 가 아닌가

남은 공백이 둘이고, 비용 있는 카드가 들어오는 순간 `CostPaymentResult` 쪽이
실제 경로가 된다 (`test_21` 이 그때 깨진다).

### 🟡 다만 지금 고장난 것은 없다

`engine.event_pipeline` 의 production importer 는 **0개**이고, 실제 카드 16장
전부 비용이 비어 있다. 그래서 틀린 actor 가 production 판단을 오염시키고 있지
않다. §15 대로 **즉시 리팩터링하지 않고** 무엇이 부족한지만 특정했다.

---

## 14. 다음 Phase 후보 (1개)

### `EffectResult` · `CostPaymentResult` 가 actor 를 들고 나오게 할 것인가 — **설계 결정 Phase**

이 Phase 가 공백을 **특정**했다. 남은 것은 **메울 방법을 고르는 것**이고, 그것은
§10 의 "새 field 금지" 와 정면으로 맞닿아 있으므로 **사용자 결정이 먼저다.**

두 길과 각각의 대가:

| 길 | 무엇을 하나 | 대가 |
| --- | --- | --- |
| **① result 가 밝힌다** | `EffectResult`·`CostPaymentResult` 에 행위자 칸을 둔다 | 🔴 **새 field** — §10 금지를 풀어야 한다. 다만 `EffectEvent`·`CostPaymentEvent` 가 **이미 `actor` 칸을 갖고 있으므로** 새 개념이 아니라 **같은 칸을 result 쪽에도 두는 것**이다 |
| **② `read()` 가 상류를 읽는다** | `controller`/`payer` 를 actor 로 받아들인다 | 🔴 §3 위반 위험 — `controller == actor` 는 **대입** 때문에 참이다. 컨트롤 이동이 구현되면 깨진다. 그리고 §7(3-F-13)의 자동 추론 금지와도 충돌한다 |

**먼저 감사할 것** (고르기 전에):

1. `ChainLink.actor` 가 "발동한 사람" 인가 "해결 시점의 컨트롤러" 인가 — 컨트롤
   이동이 구현될 때 **둘이 갈리는지**를 규칙 문서로 확인한다.
2. ① 을 고르면 `EffectEvent.actor` 와 이름·뜻을 맞출 수 있는지 — 같은 이름을 쓰면
   **한 개념**이 되고, 다르게 쓰면 또 하나의 polysemy 가 생긴다.
3. `CostPaymentResult` 는 `payments[*].player` 라는 **혼동의 씨앗**을 이미 들고
   있다. actor 칸을 더하면 한 클래스에 사람 칸이 둘이 되는데, 그것이 읽는 쪽에
안전한지.

**시작하지 않는다.** 다음 Phase 는 임의로 진행하지 않는다.

---

## 15. Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`6ae89e8`** `Phase 3-F-15: audit actor declaration scope` |
| 포함 파일 | `tests/test_actor_declaration_scope_audit.py` **하나뿐** — production 0 |
| push | `b3601a4..6ae89e8` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-15: document actor declaration scope audit` |

작업 직전 HEAD 는 `b3601a4` (3-F-14 보고서) 였고, push 결과가 그 SHA 에서 이어진
것으로 확인된다. 작업 commit 이 **테스트 파일 하나만** 담고 있는 것이 AUDIT-ONLY
의 직접 증거다 (3-F-14 는 production 을 바꾼 Phase 였으므로 이 증거를 쓸 수 없었다).
