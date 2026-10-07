# Phase 3-F-16 — `EffectResult` / `CostPaymentResult` actor provenance 설계 결정

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-16 — result actor provenance **설계 결정** 감사 |
| 모드 | **AUDIT-ONLY** — production diff **0** |
| **실제 HEAD (측정)** | `dd65514 Phase 3-F-15: document actor declaration scope audit` |
| Base (3-F-15) | `6ae89e8` (작업) · `dd65514` (보고서) — **둘 다 실존** (`git cat-file -t`) |
| 3-F-15 최종 판정 | **B. ACTOR_LESS_RESULT_CONTRACT_GAP** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,412 passed / 4 skipped |
| 신규 테스트 | `tests/test_result_actor_provenance_design_audit.py` — **26건** |

---

## 2. 🔴 먼저: 3-F-15 의 B 판정이 너무 강했다

3-F-15 는 두 result 를 **따로 떼어 놓고** 보고 "actor 가 존재하지만 전달되지
않는다" 고 적었다. **그때 보지 않은 것이 운반자(carrier)다.**

| result | production 에서 **함께 오는 것** | actor 복원 |
| --- | --- | --- |
| `EffectResult` | `ChainResolution.link` (= `ChainLink`) | `link.actor` |
| `CostPaymentResult` | `ActivationResult.action` (= `PlayerAction`) | `action.actor` |

둘 다 **한 객체 안에** 결과와 행위자가 같이 있다. **외부 context 도, 저장소도,
직렬화도 필요 없다.**

내가 3-F-15 에서 "상류가 안다" 고 적은 것은 맞지만, **"상류로 돌아가야 한다"**
는 암시가 틀렸다. 돌아갈 필요가 없다 — 결과를 받는 그 객체가 이미 들고 있다.

---

## 3. `EffectResult` call graph

```
PlayerAction(actor=N)                        engine/duel.py — seat 에서 확정
    │
    ▼  activation.py:  ChainLink(actor=action.actor)
ChainLink(actor=N)                           **필수 int** — 비어 있을 수 없다
    │
    ▼  chain.py:  ResolutionContext(controller=self.actor)
ResolutionContext(controller=N)
    │
    ▼  chain.py:  self._executor.execute(state, definition, link.resolution_context())
EffectResult                                 🔴 actor 칸이 **없다**
    │
    ▼  chain.py:  ChainResolution(status, chain, code, reason, link=link, result=result)
ChainResolution{link, result}                🟢 **둘이 함께 있다**
```

| 단계 | actor source | actor 보존 | 복원 가능 | 외부 context 필요 |
| --- | --- | --- | --- | --- |
| `PlayerAction` | 자기 칸 (필수 int) | ○ | — | — |
| `ActivationResult` | `action` (필수) | ○ | ○ | ✗ |
| `ChainLink` | `action.actor` | ○ (필수 int) | ○ | ✗ |
| `ResolutionContext` | `link.actor` | ○ | ○ | ✗ |
| `EffectResult` | **없다** | ✗ | **✗ (단독)** | — |
| **`ChainResolution`** | `link.actor` | **○** | **○** | **✗** |

### 생산자가 하나다

- `EffectResult` 를 만드는 것은 `EffectExecutor.execute` 하나.
- production 에서 그것을 부르는 것은 `ChainResolver.resolve_top` **하나**.
- production 에서 `EffectExecutor` 를 만드는 것은 `engine/effect/library.py` **하나**
  (`build_executor`), 그것을 부르는 것은 `duel_resolver()` **하나**.

→ 그래서 **운반자가 하나로 정해진다** (`test_01` · `test_04`).

### 🟢 불변식: `result` 가 있으면 `link` 도 있다

`ChainResolution` 생성 자리 **다섯**을 AST 로 전수 조사했다.

| 자리 | `link` | `result` | 상황 |
| --- | --- | --- | --- |
| 2곳 | ✗ | ✗ | 빈 체인 · 체인 완료 |
| 1곳 | ○ | ✗ | 정의를 못 찾은 링크 |
| **2곳** | **○** | **○** | 해결 성공 · 해결 실패 |

**`result` 만 있고 `link` 가 없는 `ChainResolution` 은 만들어질 수 없다.**

> 🟡 다만 `__post_init__` 이 이것을 **강제하지는 않는다** — 지금은 생성 자리가
> 지키고 있을 뿐이다 (`test_06`). 그 사실을 테스트로 고정했다.

---

## 4. `CostPaymentResult` call graph — 더 강하다

```
PlayerAction(actor=N)
    │
    ▼  activation.py:  PaymentContext(payer=action.actor)
PaymentContext(payer=N)
    │
    ▼  activation.py:  self._payer.pay(state, definition.cost, PaymentContext(...))
CostPaymentResult                            🔴 actor 칸이 **없다**
    │
    ▼  activation.py:  ActivationResult(status, action, chain, …, payment=payment)
ActivationResult{action, payment}            🟢 **`action` 은 필수 필드다**
```

`ActivationResult.action` 은 **기본값이 없는 필수 `PlayerAction`** 이므로,
`payment` 가 있으면 `action.actor` 가 **언제나** 있다. 체인 쪽보다 **조건이
약하지 않다** — 조건부가 아니다 (`test_07`).

그리고 production 에서 `CostPaymentResult` 를 **코드로** 쓰는 파일은
`engine/payment.py`(만든다) · `engine/activation.py`(운반한다) **둘뿐**이다.

> `engine/event_pipeline.py` 에도 이름이 나오지만 그것은 3-F-14 가 `read()`
> 설명에 적은 **일곱 타입 목록**이고 코드가 아니다. 문자열 리터럴을 지운 AST 로
> 갈라 확인했다.

---

## 5. 🔴 journal 은 production 에서 비어 있다

`EffectEvent.actor` · `CostPaymentEvent.actor` 는 actor 를 **제대로** 들고 있다.
그런데:

| 측정 | 값 |
| --- | --- |
| `duel_resolver().executor._journal` | **`None`** |
| `build_executor` 의 `journal` 기본값 | `None` |
| `duel_resolver()` 가 journal 을 주는가 | **아니다** (`build_executor()`) |
| `EffectActivator` 가 `CostPayer` 에 주는가 | **아니다** (`CostPayer()`) |
| production 에서 `EventJournal()` 을 만드는 자리 | **0곳** |

→ **그 두 사건은 production 에서 한 번도 기록되지 않는다** (`test_09`).

**그래서 "journal 이 provenance 를 들고 있다" 는 production 에서 거짓이고,
actor 의 유일한 production 집은 운반자다.** 이것이 B 안(기존 provenance 를
쓴다)을 고를 때 **journal 을 근거로 삼을 수 없는** 까닭이다.

journal 을 **주면** actor 가 올바르게 기록되고 직렬화에도 남는다 (`test_10`) —
구조가 틀린 것이 아니라 production 이 쓰지 않는 것이다. 그래서 이 Phase 는
journal 을 고치자고 말하지 않는다.

---

## 6. `ChainLink.actor` vs `EffectEvent.actor` (§3)

| # | 질문 | 답 |
| --- | --- | --- |
| 1 | 둘은 항상 같은 의미인가? | **한 뿌리 두 가지**다 — 둘 다 `PlayerAction.actor` 에서 온다 |
| 2 | 항상 같은 player 인가? | **그렇다** (실측: `journal.events[0].actor == link.actor`) |
| 3 | 실제 카드 효과에서 달라질 수 있는가? | **지금은 아니다** — 대입 경로가 하나다 |
| 4 | 하나는 "발동한 사람", 다른 하나는 "해결의 주체" 가 될 수 있는가? | 🟡 **뜻은 이미 다르다.** 값만 같다 |
| 5 | control change 가 개입하면 달라지는가? | 🔴 **그렇다** — 아래 측정 |
| 6 | copy / lingering / triggered effect 에서도 같은가? | **답할 수 없다** — production 경로가 없다 |

### 🟡 `ChainLink.actor` 는 "발동한 사람" 이다 — 측정으로 확인

링크를 만든 뒤 카드의 컨트롤러를 상대 쪽으로 옮겼다.

| 값 | 옮기기 전 | 옮긴 뒤 |
| --- | --- | --- |
| `CardInstance.controller` | 0 | **1** |
| `ChainLink.actor` | 0 | **0** (그대로) |
| `ResolutionContext.controller` | 0 | **0** (그대로) |

→ `controller` 라는 **이름이 카드의 컨트롤러를 따라가지 않는다.** 그것이
"발동한 사람" 이라는 증거이고, 동시에 **컨트롤 이동이 구현되면 "발동한 사람" 과
"해결 시점의 컨트롤러" 를 한 칸으로 표현할 수 없게 되는** 자리다 (`test_12`).

그리고 `OperationKind` 전수에 **컨트롤을 바꾸는 종류가 없다** — 그래서 지금
production 경로로는 이 분기가 일어나지 않는다.

### §3 의 문장 판정

> "`EffectResult` 의 actor 를 `ChainLink.actor` 로 복원해도 안전하다."

**참이다.** 근거 셋:

1. production 에서 `EffectResult` 는 **언제나** `ChainResolution.link` 와 함께
   온다 (§3 의 불변식).
2. `link.actor` 는 필수 `int` 이고 `PlayerAction.actor` 에서 왔다.
3. 복원한 값으로 사건을 읽으면 3-F-14 계약이 그대로 맞는다 — 강욕의 보은에서
   `context.actor = {0}` · `timing.actor = {1, 1}` (`test_05`).

🟡 **조건**: 컨트롤 이동이 구현되기 전까지. 그 뒤에는 "`link.actor` 가 무엇인가"
를 먼저 다시 정해야 한다.

---

## 7. `CostPaymentResult` — 네 주체를 한 판에서 갈랐다 (§5 · §6)

`LifeCost(who=OPPONENT)` 를 붙인 발동 (synthetic 비용 — 실제 카드 16장 전부
비용이 비어 있다, 3-F-15 `test_21`).

| # | 개념 | 어디서 읽나 | 측정 |
| --- | --- | --- | --- |
| ① | **effect actor** | `ActivationResult.action.actor` | **0** |
| ② | `PaymentContext.payer` | 생성: `payer=action.actor` | **0** |
| ③ | `CostPayment.player` | `result.payments[0].player` | **1** |
| ④ | **affected player** | `result.deltas[0].player` | **1** |

실제 LP: `P1` 8000 → **7000**, `P0` 8000 그대로.

### 🔴 "cost payer" 라는 말 자체가 두 가지를 가리킨다

- `PaymentContext.payer` (=①) — **비용을 지는 사람** = 발동한 사람
- `CostPayment.player` (=③) — **자원이 줄어든 쪽**

3-F-15 가 ③을 affected 로 판정한 것이 맞고, 이 Phase 는 **②가 ①과 같다**는 것을
더했다 — 생성 자리가 `payer=action.actor` 한 줄이다 (`test_14`).

### §5 의 답: `CostPaymentResult.actor` 를 정의한다면 **"효과를 발동한 사람"** 이다

후보 넷 중 셋이 탈락한다.

| 후보 | 판정 |
| --- | --- |
| 비용을 지불한 사람 | ✗ ③은 자원이 줄어든 쪽이다. `who=OPPONENT` 면 상대다 |
| controller | ✗ 카드의 컨트롤러와 효과의 컨트롤러가 다르다 (3-F-15) |
| affected player | ✗ ④다. 행위가 아니다 |
| **효과를 발동한 사람** | **○** `PaymentContext.payer` = `action.actor` |
| actor 없음 | ✗ 존재한다 |

**그리고 그 값은 운반자에 이미 있다.** 그래서 칸을 만들지 않는다 (`test_16`).

### §6 의 "하나의 actor 로 모두 표현할 수 있는가"

**그럴 필요가 없다.** 네 개를 한 칸에 넣으려는 것이 잘못된 질문이다 — 세 가지가
**서로 다른 기수(cardinality)** 를 갖기 때문이다.

| 개념 | 단위 |
| --- | --- |
| ①② effect actor | **운반자마다 하나** |
| ③ `CostPayment.player` | **payment 마다** |
| ④ affected player | **delta 마다** |

그리고 네 칸이 **이미 따로 있다** (`test_15`).

---

## 8. result standalone 문제 (§4 Case B)

**결과만 떼어 놓으면 복원할 수 없다. 그것은 사실이다.**

- `EffectResult` 에 운반자로 돌아갈 **역참조가 하나도 없다**
  (`link`·`chain`·`context`·`action`·`actor`·`controller` 전부 없음).
- `to_dict()` 직렬화에도 `actor`·`controller` 가 나오지 않는다.
- 🟢 **그래서 3-F-14 계약이 거부한다** — `read(orphan)` 이 `TypeError` 를 내고,
  조용히 틀린 actor 를 만들지 않는다 (`test_08`).

### 가상의 단독 소비자를 실제로 만들어 봤다 (§9 7)

```python
def consume_badly(result):          # 운반자를 버린 소비자
    return reader.read(result)      # 🔴 TypeError

def consume_well(step):             # 운반자를 함께 받는 소비자 — 올바른 모양
    return reader.read(step.result, actor=step.link.actor)   # 🟢 통과
```

자비의 비로 확인했다 — `consume_well` 이 귀속자 둘(`{0, 1}`)과 행위자 하나(`{0}`)
를 정확히 낸다 (`test_21`).

→ **"지금 consumer 가 없다" 가 근거가 아니다.** 근거는 **"들어와도 안전하다"** 다.

### clone · 직렬화 (§2 · §14)

| 항목 | 결과 |
| --- | --- |
| clone 후 복원 | **된다** — 운반자는 판을 들고 있지 않은 frozen 값 타입이다 (`test_22`) |
| `ChainLink` 가 몰래 바뀌는가 | **아니다** — `FrozenInstanceError` |
| `EffectResult.to_dict()` 에 사람 | **없다** |
| `ChainLink.to_dict()` 에 사람 | **있다** (`actor`) — replay 는 **운반자를 저장해야 한다** (`test_23`) |

---

## 9. 실제 시나리오 (§9)

| # | Scenario | Effect actor | Cost payer | Controller | Affected | `ChainLink.actor` | `EffectEvent.actor` | Result actor 필요? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 일반 효과 발동 (욕망의 항아리) | 1 | — | 1 (효과) | 1·1 | **1** | 1 (journal 줄 때) | **아니다** |
| 2 | 효과로 상대가 드로우 (강욕의 보은) | 0 | — | 0 | **1·1** | **0** | 0 | **아니다** |
| 3 | 양쪽 LP 변화 (자비의 비) | 0 | — | 0 | **0·1** | **0** | 0 | **아니다** |
| 4 | 자기 LP 비용 (`who=CONTROLLER`) | 0 | **0** | 0 | 0 | — | — (`CostPaymentEvent`) | **아니다** |
| 5 | 🔴 상대 LP 비용 (`who=OPPONENT`) | 0 | **0** | 0 | **1** | — | — | **아니다** |
| 6 | 컨트롤 변경 후 효과 해결 | 0 | — | **카드는 1 · 효과는 0** | — | **0** (그대로) | — | **아니다** (🟡 조건부) |
| 7 | 전투 (P1 → P0) | 1 | — | — | 0 | — | — | **아니다** (`ActionExecution`) |
| 8 | **가상 단독 소비자** | 복원 불가 | — | — | — | — | — | 🟢 **거부된다** |

### 🟢 선언 하나가 전부를 옳게 적는다

2 · 3 · 5 에서 affected 가 `{1}` · `{0,1}` · `{1}` 로 다 다른데, 운반자의 actor
하나(`0`)가 전부 맞는다. **actor 는 invocation 의 속성**이기 때문이다.

### 🟡 5 · 6 은 synthetic 이다

- 5: 라이브러리 16장 전부 비용이 비어 있으므로 실제 카드 경로가 없다. 공식
  규칙에서 그런 비용이 가능한지는 **이 감사가 권위 있는 출처로 확인할 수 없는
  문제**이므로 주장하지 않는다. 엔진이 **표현할 수 있다**는 사실만 적는다.
- 6: 컨트롤을 바꾸는 `OperationKind` 가 없으므로, `state.move(to_player=)` 로
  판을 직접 옮겨 **엔진이 지금 어떻게 행동하는가**만 쟀다.

---

## 10. API 문제인가 data model 문제인가 (§10)

### **둘 다 아니다 — 문서 문제다.**

| 선택지 | 판정 |
| --- | --- |
| **A. Result 에 actor field 가 없어서 정보가 손실된다** (data model) | ✗ **손실되지 않는다.** 운반자가 같은 객체 안에 들고 있다 |
| **B. Result 에는 필요 없지만 호출자가 context 를 제공해야 한다** (API contract) | △ **맞지만 이미 되어 있다.** 3-F-14 가 `read(result)` 를 `TypeError` 로 만들었다 |
| **C. (이 Phase 가 더하는 것) 복원 경로가 어디에도 적혀 있지 않다** | **○** |

`ChainResolution` 의 docstring 도, `EffectResult` 의 docstring 도 **"이 결과의
행위자는 `resolution.link.actor` 다" 라고 말하지 않는다.** 구조는 맞고 계약도
서 있는데, **읽는 사람이 그것을 알 길이 없다.**

→ 그래서 §12 의 조건 **1("actor 정보가 실제로 소실된다")이 깨진다.** 소실되지
않으므로 production 을 바꾸지 않는다.

---

## 11. 설계안 비교 (§1)

| 기준 | **A. result 에 actor 추가** | **B. 기존 provenance 사용** | **C. 일부만 추가** | **D. 새 provenance 경계** |
| --- | --- | --- | --- | --- |
| semantic correctness | 🟡 값은 맞다 | 🟢 **출처가 하나** | 🔴 두 result 의 계약이 갈린다 | 🟡 과하다 |
| 중복 저장 | 🔴 **그렇다** — 운반자와 같은 사실 | 🟢 없음 | 🔴 절반만 | 🔴 세 번째 사본 |
| 값이 갈릴 수 있나 | 🔴 **그렇다** (아래 §12) | 🟢 갈릴 곳이 없다 | 🔴 그렇다 | 🔴 그렇다 |
| authoritative 가 명확한가 | 🔴 **코드가 말하지 않는다** | 🟢 운반자 하나 | 🔴 아니다 | 🟡 새로 정의해야 한다 |
| `state_hash` | 영향 없음 (result 를 보지 않는다) | 영향 없음 | 영향 없음 | 영향 없음 |
| 직렬화 · 동등성 | 🔴 **바뀐다** — 기존 replay 비호환 | 🟢 그대로 | 🔴 바뀐다 | 🔴 바뀐다 |
| 새 field 금지(§10 of 3-F-15) | 🔴 어긴다 | 🟢 지킨다 | 🔴 어긴다 | 🔴 어긴다 |
| 단독 소비자 안전성 | 🟡 안전해지지만 **틀린 값도 담길 수 있다** | 🟢 **거부된다** (3-F-14) | 🟡 절반 | 🟡 |

**B 를 고른다.**

---

## 12. 🔴 중복 provenance 위험 — 측정으로 확인

`EffectResult.actor` 를 더하면 `ChainResolution.link.actor` 와 **같은 사실이 두
곳**에 저장된다. 그리고 **갈릴 수 있다** — 운반자가 frozen dataclass 라서
`dataclasses.replace` 로 바꿀 수 있기 때문이다.

```python
relinked = dataclasses.replace(resolution, link=replace(resolution.link, actor=0))
relinked.link.actor      # 0
resolution.link.actor    # 1
relinked.result is resolution.result    # True — 같은 객체다
```

`result` 에 actor 칸이 있었다면 **어느 쪽이 맞는지 코드가 말해 주지 않는다**
(`test_17`). `CostPaymentResult` 쪽도 `ActivationResult.action` 을 바꿔 같은
모순을 만들 수 있다.

그리고 두 result 의 `canonical_state()` · `to_dict()` 에 사람이 **없다.** 칸을
더하면 **직렬화와 동등성이 둘 다** 바뀌고 기존 replay 기록이 호환되지 않는다
(`test_18`). `state_hash` 는 result 를 보지 않으므로 판 해시는 그대로지만,
**그것이 안전하다는 뜻은 아니다** (`test_19`).

---

## 13. production 변경 여부 (§12)

```
$ git diff --stat HEAD -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**AUDIT-ONLY.** §12 의 일곱 조건 중 **조건 1 이 깨진다.**

| # | 조건 | 판정 |
| --- | --- | --- |
| 1 | actor 정보가 **실제로 소실된다** | 🔴 **✗ — 소실되지 않는다** (§3 · §4) |
| 2 | 미래 consumer 에서 semantic 오류 | ✗ — 거부된다 (§8) |
| 3 | actor 의 의미가 하나로 명확 | ○ (= 발동한 사람) |
| 4 ~ 7 | 기존 provenance 충돌 · hash/RNG/AI · freeze · pipeline | 전부 ○ |

§13 의 금지 항목 전부 미실행 — 두 result 에 `actor` · `controller` · `player` ·
`affected_player` 칸이 **하나도 없고**, `ActorProvenance` · `ActorOrigin` ·
`ActorRequirement` · 새 `EventBus` 도 없다 (`test_26`).

---

## 14. 테스트

### 신규 `tests/test_result_actor_provenance_design_audit.py` — 26건

| # | 무엇을 고정하나 | §14 항목 |
| --- | --- | --- |
| 01 | `EffectResult` 의 production 생산자가 하나 | 1 |
| 02 | `CostPaymentResult` 의 production 생산자가 하나 | 2 |
| 03 | `ChainLink.actor` 가 `action.actor` 에서 온다 · 필수 int | 3 |
| 04 | 단계마다 actor 보존 — result 만 빠지고 운반자가 메운다 | 1 · 2 |
| 05 | 🟢 **`ChainResolution` 이 `{link, result}` 를 함께 들고 있다** | 1 |
| 06 | 🟢 **불변식: `result` 가 있으면 `link` 도 있다** (AST 전수) | 1 |
| 07 | 🟢 `ActivationResult.action` 은 **필수** — 더 강하다 | 2 |
| 08 | 결과만 떼면 복원 불가 · 역참조 0 · 거부된다 | 11 |
| 09 | 🔴 **production 은 journal 을 넘기지 않는다** | 4 |
| 10 | journal 을 주면 actor 가 올바르게 기록된다 | 4 |
| 11 | 두 actor 가 **한 뿌리**에서 온다 | 3 · 4 |
| 12 | 🟡 컨트롤 이동 시 갈린다 — `link.actor` 는 **발동한 사람** | 10 |
| 13 | copy / lingering / triggered 경로가 **없다** | — |
| 14 | 🔴 **네 주체를 한 판에서 갈랐다** | 5 · 6 · 7 · 8 · 9 |
| 15 | 세 가지가 **기수**가 달라 한 칸에 못 들어간다 | 25 |
| 16 | `CostPaymentResult.actor` 는 "발동한 사람" 이다 | 5 · 9 |
| 17 | 🔴 **중복 provenance** — 두 result 모두 | 25 |
| 18 | `canonical_state` · `to_dict` 가 바뀐다 | 14 |
| 19 | `state_hash` 는 result 를 보지 않는다 | 16 |
| 20 | 단독 소비자가 production 에 없다 · AI 가 모른다 | 18 · 19 |
| 21 | 🟢 **가상 단독 소비자** — 거부되거나 통과한다 | 24 |
| 22 | clone 후에도 복원된다 · frozen | 12 |
| 23 | 직렬화 — 운반자에 남고 result 에 안 남는다 | 13 · 14 |
| 24 | 3-F-14 계약 불변 | 20 · 21 · 22 |
| 25 | hidden-information · `state_hash` · RNG 불변 | 15 ~ 17 |
| 26 | production diff 0 · 금지 항목 없음 | — |

### 고의 위반 검증 — 8건, 전부 잡혔다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `EffectResult` 에 actor 칸을 더한다 | 4건 — 04 · 08 · 17 · 26 |
| 2 | `CostPaymentResult` 에 actor 칸을 더한다 | 2건 — `test_17` · `test_26` |
| 3 | `ChainResolution` 이 `link` 를 버린다 | 2건 — `test_06` · `test_26` |
| 4 | `ChainLink.actor` 를 뒤집는다 | **6건** — 03 · 04 · 05 · 11 · 12 · 26 |
| 5 | production 이 journal 을 넘긴다 | 3건 — 01 · 09 · 26 |
| 6 | journal actor 를 **비용 대상**으로 바꾼다 (§6 혼동) | 2건 — `test_16` · `test_26` |
| 7 | `EffectExecutor` 가 journal actor 를 뒤집는다 | 3건 — 10 · 11 · 26 |
| 8 | `ActivationResult.action` 을 Optional 로 (운반자 약화) | 2건 — `test_07` · `test_26` |

주입 파일 6개(`chain.py` · `activation.py` · `payment.py` ·
`spell_activation.py` · `effect/resolution.py` · `effect/executor.py`)는 전부
백업에서 복원하고 md5 로 확인했다 (전부 `OK`).

> 🔴 **주입 2 가 처음에 포괄 테스트에만 걸렸다.** `test_17` 이 `EffectResult`
> 쪽만 보고 있었기 때문이다 — `CostPaymentResult` 쪽 중복 위험을 같은
> 테스트에 더해 **강화**했다. 주입이 테스트의 사각을 찾아낸 것이다.
>
> 🔴 **주입 8 의 첫 시도는 유효한 Python 이 아니었다.** `action` 에 기본값을
> 주자 dataclass 필드 순서가 깨져 **테스트가 한 건도 실행되지 않았고**, 출력이
> 비어 있었다. "아무도 실패하지 않았다" 로 읽지 않고 **다시 작성**해서
> (`PlayerAction | None`, 기본값 없이) 잡히는 것을 확인했다.

### 전체 회귀

| 실행 | 결과 |
| --- | --- |
| 1회차 | `1 failed, 4437 passed, 4 skipped` |
| **2회차 (최종)** | **`4438 passed, 4 skipped in 453.01s`** |

`4,412` (3-F-15) `+ 26` (신규) `= 4,438`. 실패 0 · skip 그대로 4건.

🔴 **1회차의 실패 1건은 내 새 테스트가 다른 Phase 의 감사에 걸린 것이다.**
3-F-13 의 `test_04`("계약을 지키지 않은 생략이 0곳") 가 이 파일의
`test_21` 안 **중첩 함수** 속 `reader.read(result)` 를 생략으로 셌다. 그
테스트는 ``with pytest.raises`` **블록의 줄 범위**로 거부 시험 자리를 가리므로,
중첩 함수 안에 둔 호출은 가려지지 않는다.

고친 방법: 그 호출을 ``with`` 블록 **안으로** 옮겼다. 좋은 소비자는 이름 붙은
함수로 남겼으므로 대조는 그대로다. **3-F-13 의 테스트를 약화시키지 않았다** —
오히려 그 테스트가 제 역할을 했다.

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리

**삭제 0건 · skip 추가 0건 · assertion 약화 0건 · 수정 0건.**

---

## 15. state_hash / RNG / Search / AI 영향

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 결과를 여러 번 읽어도 동일. `game_state.py` 가 result 타입을 **모른다** |
| RNG | **불변** | `repr(state.rng)` 동일 · 같은 seed 두 번 → 같은 hash |
| hidden-information | **불변** | 상대 패·덱은 `concealed` |
| Search ranking | **불변** | digest `30fa3597…402c4175` — 기존 3개 파일이 고정하고 전체 회귀에서 통과 |
| AI behavior | **불변** | `agent/` 가 `EffectResult`·`CostPaymentResult`·`ChainResolution` 을 **코드로 모른다** (문자열 리터럴 제거 AST 로 확인) |
| Engine V1 freeze | **유지** | production diff 0 |
| Trigger pipeline | **dormant 유지** | `event_pipeline` production importer 0 |

---

## 16. 최종 설계 판정

### **A. PROVENANCE_ALREADY_SUFFICIENT**

**두 result 에 actor field 가 필요 없다. 기존 운반자로 안전하게 복원 가능하다.**

근거 넷.

1. **운반자가 결과와 행위자를 한 객체에 담는다** — `ChainResolution{link, result}`
   와 `ActivationResult{action, payment}`. 외부 context 가 필요하지 않다.
2. **불변식이 성립한다** — `result` 가 있으면 `link` 도 있다 (생성 자리 전수).
   `ActivationResult.action` 은 아예 필수 필드다.
3. **단독 소비자는 거부된다** — 3-F-14 의 계약이 조용한 오류를 막는다. 가상
   소비자를 실제로 만들어 확인했다.
4. **칸을 더하면 중복 provenance 가 되고 갈릴 수 있다** — 어느 쪽이
   authoritative 인지 코드가 말하지 않게 된다. 직렬화·동등성도 바뀐다.

### 🔴 3-F-15 의 B 판정을 정정한다

3-F-15 는 result 를 **고립시켜** 보고 "구조적 공백" 이라 적었다. 운반자를 보면
공백이 아니다. **고립시킨 것이 측정의 잘못이었다.**

다만 3-F-15 가 찾은 사실 자체는 전부 유효하다 — `CostPayment.player` 가 affected
라는 것, `controller` 가 두 뜻이라는 것, `controller == actor` 가 대입 때문이라는
것. 틀린 것은 **그 사실들로부터 내린 결론**이다.

### 왜 B(RESULT_ACTOR_REQUIRED)가 아닌가

"기존 context 만으로 안전하게 복원할 수 없다" 가 **거짓**이다. 복원 경로가
운반자 **안에** 있고, 그것이 production 의 유일한 경로다.

### 왜 C(MIXED_PROVENANCE_CONTRACT)가 아닌가

두 result 의 계약이 **같다** — 둘 다 "운반자의 행위자" 이고, 둘 다
`PlayerAction.actor` 에서 한 줄씩 대입된 값이다. 의미가 달라서 따로 처리해야 하는
것이 아니다.

### 왜 D(API_CONTEXT_CONTRACT_REQUIRED)가 아닌가

API 계약이 **필요한 것이 아니라 이미 있다.** 3-F-14 가 `read(result)` 를
`TypeError` 로 만들었다. 더 세울 계약이 없다.

### 왜 E(SEMANTIC_ACTOR_NOT_SINGLE_CONCEPT)가 아닌가

**한 result 안에서는 단일 actor 가 모호하지 않다.** `CostPaymentResult` 의 행위자
는 `action.actor` 하나이고, ③④는 payment 마다 / delta 마다 있는 **별개 정보로
이미 각자의 칸에 있다.** E 의 전제("서로 다른 주체이므로 단일 actor 가 틀렸다")는
**칸을 하나로 합치려 할 때만** 참이고, 그것은 아무도 제안하지 않았다.

### 🟡 남는 것 셋 — 정직하게 적는다

1. **복원 경로가 어디에도 적혀 있지 않다.** `ChainResolution` 도 `EffectResult`
   도 "이 결과의 행위자는 `link.actor` 다" 라고 말하지 않는다. 구조는 맞고 계약도
   서 있는데 **읽는 사람이 알 길이 없다** (§10).
2. **불변식이 강제되지 않는다.** `ChainResolution.__post_init__` 은 `deltas` 만
   본다. 지금은 생성 자리가 지킬 뿐이다.
3. 🟡 **컨트롤 이동이 들어오면 `link.actor` 의 뜻을 먼저 다시 정해야 한다.**
   "발동한 사람" 과 "해결 시점의 컨트롤러" 가 갈리고, 한 칸으로는 표현할 수 없다.

---

## 17. 다음 Phase 후보 (1개)

### 복원 경로를 **문서와 테스트로 고정**한다 — 최소 변경

이 Phase 가 "칸을 더하지 않는다" 를 확정했다. 남은 것은 §16 의 1 · 2 다 — **구조가
아니라 적어 두는 일**이다.

| 할 일 | 범위 |
| --- | --- |
| `ChainResolution` docstring 에 "이 `result` 의 행위자는 `link.actor` 다" 를 적는다 | 1파일, docstring |
| `EffectResult` · `CostPaymentResult` docstring 에 "행위자를 들고 있지 않다 — 운반자에서 읽는다" 를 적는다 | 2파일, docstring |
| `ChainResolution.__post_init__` 에 **불변식을 강제**할지 결정한다 | 🟡 **behavior 변경** — 판단 필요 |

세 번째가 유일한 판단거리다. 강제하면 `result` 만 있고 `link` 가 없는
`ChainResolution` 을 만들려는 시도가 즉시 실패한다 — 지금은 조용히 만들어진다.
그것이 **지킬 가치가 있는 불변식인지**, 아니면 생성 자리가 지키는 것으로 충분한지
먼저 정해야 한다.

> 🔴 **주의**: 3-F-11 이 docstring 만 고쳤는데도 줄 수 snapshot 5건이 깨졌다.
> 그 Phase 도 같은 일이 생길 것이므로 미리 예상해 두어야 한다.

**시작하지 않는다.** 다음 Phase 는 임의로 진행하지 않는다.

---

## 18. Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`57da2f6`** `Phase 3-F-16: audit result actor provenance design` |
| 포함 파일 | `tests/test_result_actor_provenance_design_audit.py` **하나뿐** — production 0 |
| push | `dd65514..57da2f6` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-16: document result actor provenance design` |

작업 직전 HEAD 는 `dd65514` (3-F-15 보고서) 였고, push 결과가 그 SHA 에서 이어진
것으로 확인된다. 작업 commit 이 **테스트 파일 하나만** 담고 있는 것이 AUDIT-ONLY
의 직접 증거다.
