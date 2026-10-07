# Phase 3-F-17 — result actor provenance 복원 경로 계약 고정

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-17 — 복원 경로 계약 **고정** (문서 + 테스트) |
| 모드 | **docstring 셋만** 변경 — 실행되는 코드 0 |
| **실제 HEAD (측정)** | `0227765 Phase 3-F-16: document result actor provenance design` |
| Base (3-F-16) | `57da2f6` (작업) · `0227765` (보고서) — **둘 다 실존** (`git cat-file -t`) |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,438 passed / 4 skipped |
| 신규 테스트 | `tests/test_result_actor_provenance_contract.py` — **24건** |

### 🟡 §1 이 요구한 정정 — 판정 이름이 다르다

지시문은 3-F-16 의 최종 판정을 **`A. PROVENANCE_AI_READY_SUFFICIENT`** 로 적었다.
실제로 기록된 판정은 **`A. PROVENANCE_ALREADY_SUFFICIENT`** 다
(`docs/phase3f16-result-actor-provenance-design.md:486`).

글자(**A**)는 같고 이름만 다르다 — `ALREADY` ↔ `AI_READY`. 이 Phase 는 **기록된
이름**(`PROVENANCE_ALREADY_SUFFICIENT`)을 기준으로 삼는다. SHA 는 둘 다 실제로
존재하므로 정정할 것이 없다.

---

## 2. 이번 Phase 가 고정하는 계약

```
EffectResult        의 actor provenance  →  ChainResolution.link.actor
CostPaymentResult   의 actor provenance  →  ActivationResult.action.actor
```

**"result 가 actor 를 소유한다" 라고 쓰지 않았다.** 정확한 표현은

> **"result 의 actor provenance 는 운반자(carrier)를 통해 복원된다."**

이고, 세 docstring 에 그대로 적었다. `test_21` 이 **소유를 주장하는 표현이
들어오면 깨지도록** 고정한다.

---

## 3. `EffectResult` provenance 경로 (§3)

```
PlayerAction.actor
   ▼  activation.py: ChainLink(actor=action.actor)
ChainLink.actor                         필수 int — 비어 있을 수 없다
   ▼  chain.py: ResolutionContext(controller=self.actor)
ResolutionContext.controller
   ▼  chain.py: self._executor.execute(...)
EffectResult                            🔴 사람 칸이 **없다**
   ▼  chain.py: ChainResolution(..., link=link, result=result)
ChainResolution{link, result}           🟢 **둘이 함께 있다**
```

| 질문 (§3) | 답 |
| --- | --- |
| 1. `ChainResolution` 이 **항상** `link` 를 갖고 생성되는가? | 🔴 **아니다** — 기본값이 `None` 이다 (§6) |
| 2. `result` 를 생성할 때 `link` 가 함께 존재하는가? | 🟢 **그렇다** — 생성 자리 **전수 6곳**에 위반 0 |
| 3. result 만 저장/전달하면 link 가 사라지는가? | 🟢 **그렇다** — 역참조 0, `to_dict()` 에 사람 0 |
| 4. 현재 production consumer 가 result 만 읽는가? | 🟢 **아니다** — `.link.actor` 를 읽는 production 파일 **0개** |
| 5. replay/clone 에서 link 가 유지되는가? | 🟢 **그렇다** — frozen 값 타입, 직렬화에 `actor` 가 남는다 |

### 🟢 생성 자리 전수 — 저장소 **전체** 6곳

| 자리 | `link` | `result` |
| --- | --- | --- |
| `engine/chain.py` × 2 | ✗ | ✗ |
| `engine/chain.py` × 1 | ○ | ✗ |
| `engine/chain.py` × 2 | **○** | **○** |
| `tests/engine/test_chain.py` × 1 | **○** | **○** |

**`result` 를 주면서 `link` 를 빼는 자리가 하나도 없다** (`test_02`).

그리고 **실패한 해결도 운반자를 들고 온다** — 싸이크론을 대상 없이 해결하면
`unchecked_target` 이 되는데, 그때도 `link` 와 `result` 가 **둘 다** 있다
(`test_02b`). 판이 바뀌지 않아 사건은 0개지만 **"누가 실패했는가" 는 말할 수
있다.**

### `ChainLink.actor` 의 의미 — **발동한 사람**

링크를 만든 뒤 카드의 컨트롤러를 옮겨도 `actor` 는 그대로다.

| 값 | 옮기기 전 | 옮긴 뒤 |
| --- | --- | --- |
| `CardInstance.controller` | 0 | **1** |
| `ChainLink.actor` | 0 | **0** |
| `ResolutionContext.controller` | 0 | **0** |

→ `controller` 라는 **이름이 카드의 컨트롤러를 따라가지 않는다** (`test_04`).

---

## 4. `CostPaymentResult` provenance 경로 (§4)

```
PlayerAction.actor
   ▼  activation.py: PaymentContext(payer=action.actor)
PaymentContext.payer
   ▼  activation.py: self._payer.pay(...)
CostPaymentResult                       🔴 사람 칸이 **없다**
   ▼  activation.py: ActivationResult(status, action, chain, …, payment=payment)
ActivationResult{action, payment}       🟢 **action 은 필수 필드다**
```

| 질문 (§4) | 답 |
| --- | --- |
| 1. `ActivationResult.action` 은 필수인가? | 🟢 **그렇다** — 기본값 없음 |
| 2. `action.actor` 는 항상 존재하는가? | 🟢 **그렇다** — 필수 `int`, 0/1 검증 |
| 3. `CostPaymentResult` 생성 시 `ActivationResult` 가 함께 존재하는가? | 🟢 그렇다 — 유일한 production 호출자가 그것을 만든다 |
| 4. result 단독 소비자가 있는가? | 🟢 **없다** |
| 5. 비용 지불자와 효과 발동자를 혼동할 위험이 있는가? | 🔴 **있다** — 아래 |

### 🔴 "비용을 지불한 사람" 이 두 가지를 가리킨다

`LifeCost(who=OPPONENT)` 로 재면 한 판에서 갈린다.

| 값 | 측정 | 뜻 |
| --- | --- | --- |
| `ActivationResult.action.actor` | **0** | **actor** — 비용을 **지는** 쪽 = 발동한 사람 |
| `PaymentContext.payer` | **0** | 같다 (`payer=action.actor`) |
| `CostPayment.player` | **1** | **자원을 낸 쪽** |
| `LifeChanged.player` | **1** | 변화가 귀속되는 쪽 |

LP: `P1` 8000 → **7000**, `P0` 8000 그대로.

→ **actor 는 앞쪽이다.** `payments[*].player` 를 actor 로 쓰면 틀린다 — 그래서
`CostPaymentResult` 의 docstring 에 그 표를 그대로 적고, `test_21` 이 그 경고가
사라지면 깨지도록 고정했다 (`test_08`).

---

## 5. standalone result 정책 (§7)

### **C. standalone result 를 actor 판단의 입력으로 쓰는 것은 API 계약 위반이다.**

선택지 **A**(복원 불가)는 그 **사실적 근거**이고, **B**(result 안에 운반자가 남아
있다)는 **거짓**이다.

| 확인 | 결과 |
| --- | --- |
| `EffectResult` 에 운반자 역참조 | **0개** (`link`·`chain`·`context`·`action`·`actor`·`controller`·`player` 전부 없음) |
| `to_dict()` 에 사람 | **없음** |
| 그래서 복원 가능한가 | **아니다** (A) |
| 그 호출이 허용되는가 | **아니다** (C) |

### 🟢 그 정책은 **이미 강제되어 있다**

3-F-14 가 `read(result)` 를 `TypeError` 로 만들었다. 에러가 **까닭까지** 말한다 —
"부르는 쪽만 압니다 · 결과나 delta 에서 알아낼 수 없습니다". 이 Phase 가 새로
막을 것이 없다 (`test_10`).

🟡 다만 **틀리게 말하는 것**은 그대로 열려 있다 — 행위자가 P0 으로 존재하는데
`actor=None` 이라고 선언하면 통과한다 (`test_11`). 3-F-16 이 적은 그대로이고, 이
Phase 가 바꾸지 않았다.

---

## 6. `__post_init__` / constructor 분석 (§6)

🔴 **두 운반자의 강도가 다르다. 이것이 이 Phase 의 핵심 발견이다.**

| 운반자 | `actor` 운반 칸 | 타입 수준 강제 | `__post_init__` 검사 |
| --- | --- | --- | --- |
| `ChainResolution` | `link: ChainLink \| None = None` | 🔴 **없다** | 🔴 `link`·`result` 를 **보지 않는다** (`deltas` 만 본다) |
| `ActivationResult` | `action: PlayerAction` | 🟢 **있다** (필수) | 🟢 `link` 불변식을 **실제로 거부한다** |

`ActivationResult.__post_init__` 는 이렇게 막는다.

```python
if self.status is ActivationStatus.ACTIVATED:
    if self.link is None:
        raise ActivationError("발동했다면서 링크가 없습니다. …")
elif self.link is not None:
    raise ActivationError("… 발동하지 못한 시도는 체인을 늘리지 않습니다.")
```

실제로 거부하는 것을 테스트로 확인했다 (`test_06`).

### §6 이 요구한 구분

> "현재 production 호출 경로에서는 보장된다" 와 "타입 수준에서 강제된다" 는 다르다.

| 운반자 | 어느 쪽인가 |
| --- | --- |
| `CostPaymentResult` ← `ActivationResult` | **타입 수준에서 강제된다** |
| `EffectResult` ← `ChainResolution` | **호출 경로가 지킬 뿐이다** |

그래서 `dataclasses.replace(resolution, link=None)` 로 **actor 를 복원할 수 없는
객체를 만들 수 있다** — 그런 자리가 저장소에 없을 뿐이다 (`test_07`).

**행동은 바꾸지 않았다** (§6 마지막 줄 · §11). 그 대신 `ChainResolution` 의
docstring 에 `.. warning::` 로 적었다.

---

## 7. production consumer 조사 (§8)

| 묻는 것 | 답 |
| --- | --- |
| `.link.actor` 를 읽는 **production** 파일 | **0개** (읽는 곳은 테스트 3파일뿐) |
| `EffectResult` 를 **코드로** 쓰는 production 파일 | 4개 — `chain.py`(운반) · `effect/executor.py`(생성) · `effect/resolution.py`(선언) · `effect/__init__.py`(re-export) |
| `CostPaymentResult` 를 코드로 쓰는 production 파일 | 2개 — `payment.py`(생성) · `activation.py`(운반) |
| AI/Search 가 아는가 | **모른다** — `agent/` 에 세 타입이 **코드로** 0회 |

> 문자열 리터럴을 지운 AST 로 쟀다. 3-F-14 가 `read()` 설명에 **일곱 타입
> 목록**을 적어 두어서, 단순 문자열 검색으로는 `engine/event_pipeline.py` 가
> 보유자로 잡힌다. 3-F-13 · 3-F-16 이 그 함정에 빠졌으므로 이번에는 처음부터
> `code_only` 로 쟀다.

### 🟢 운반자가 듀얼 경계까지 간다

```
ChainResolver.resolve_all → tuple[ChainResolution]      (link + result 짝)
  → ResponseResolution.steps: tuple[ChainResolution,…]  (운반자 **전체**를 보관)
    → Duel._resolve_chain  — resolution.steps 를 **읽는다**
      → DuelStep(action, accepted, code, reason)        (link·result 는 떨어진다)
```

🟡 `DuelStep` 에서 `link`·`result` 가 떨어지지만 **`DuelStep.action` 이 남아
행위자는 거기서도 살아 있다.** 떨어지는 것은 **deltas** 다 — 3-F-5 가 찾은 그
자리이고, **actor provenance 의 공백이 아니다** (`test_13`).

---

## 8. 실제 카드 시나리오 (§9)

| # | Scenario | Result | Actor source | Carrier | Affected player | Controller |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 일반 효과 발동 (욕망의 항아리) | `ActivationResult` | `action.actor` | 자기 자신 (필수 `action`) | — | 0 (효과) |
| 2 | 효과 해결 — 내가 2장 뽑는다 | `EffectResult` | `link.actor` = **0** | `ChainResolution` | 0 · 0 | 0 |
| 3 | 효과 해결 — **상대가** 2장 뽑는다 (강욕의 보은) | `EffectResult` | `link.actor` = **0** | `ChainResolution` | 🔴 **1 · 1** | 0 |
| 4 | 자기 LP 비용 (`who=CONTROLLER`) | `CostPaymentResult` | `action.actor` = **0** | `ActivationResult` | 0 | 0 |
| 5 | 🔴 상대 LP 비용 (`who=OPPONENT`) | `CostPaymentResult` | `action.actor` = **0** | `ActivationResult` | 🔴 **1** | 0 |
| 6 | 해결 실패 (싸이크론, 대상 없음) | `EffectResult` | `link.actor` = **1** | `ChainResolution` | — (delta 0) | 1 |
| 7 | 🟡 컨트롤 변경 개입 (가상) | `EffectResult` | `link.actor` = **0** (그대로) | `ChainResolution` | — | 🔴 **카드는 1 · 효과는 0** |

### 🟡 §9 가 물은 "미래 상황에서 현재 contract 가 깨지는가"

**지금 계약은 깨지지 않는다.** `link.actor` 가 발동 시점을 기억하므로 컨트롤이
바뀌어도 그대로다.

**깨지는 것은 "해결 시점의 컨트롤러" 를 알아야 할 때**다. 그 값을 담는 칸이
어디에도 없고, `ChainLink` 에 `resolving_controller` 같은 칸이 **없다**는 것이
증거다. 컨트롤 이동이 구현되면 **먼저 그것을 정해야** 한다 (`test_16`).

> 5 와 7 은 synthetic 이다. 실제 카드 16장 전부 비용이 비어 있고(3-F-15), 컨트롤을
> 바꾸는 `OperationKind` 가 없다. 공식 규칙에서 그런 비용이 가능한지는 이 감사가
> **권위 있는 출처로 확인할 수 없는 문제**이므로 주장하지 않는다 — 엔진이
> **표현할 수 있다**는 사실만 적는다.

---

## 9. production 변경 — docstring 셋 (§11)

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
 engine/chain.py             | 40 +++++++++++++++++++++++++++++++++++++++-
 engine/effect/resolution.py | 21 +++++++++++++++++++++
 engine/payment.py           | 30 ++++++++++++++++++++++++++++++
 3 files changed, 90 insertions(+), 1 deletion(-)
```

**문자열 리터럴을 지운 AST 가 세 파일 모두 base(`0227765`)와 동일하다** —
실행되는 코드가 한 글자도 바뀌지 않았다 (`test_20`).

| 파일 | 무엇을 적었나 |
| --- | --- |
| `engine/chain.py` | `ChainResolution` 이 `result` 의 **actor 운반자**라는 것 · `resolution.link.actor` 가 복원 경로라는 것 · 🔴 **타입이 강제하지 않는다는 `.. warning::`** · result 를 혼자 떼어 내지 말라는 것 · actor 를 controller·player 와 섞지 말라는 것. `link`·`result` 칸 설명에도 한 줄씩 |
| `engine/effect/resolution.py` | `EffectResult` 가 **행위자를 들고 있지 않다** — 일부러 그렇다 · 복원 경로 · **같은 사실을 두 곳에 적지 않기 위해서**라는 까닭 · `controller` 를 베껴 넣지 않는다 · 혼자 떼어 내면 되찾을 수 없다는 `.. warning::` |
| `engine/payment.py` | `CostPaymentResult` 가 행위자를 들고 있지 않다 · `activation.action.actor` 가 복원 경로이고 **필수 필드**라는 것 · 🔴 **`payments[*].player` 를 actor 로 쓰지 말라는 표** |

§5 의 금지 항목 전부 미실행 — `EffectResult.actor` · `CostPaymentResult.actor` 추가
**없음**, `controller`/`affected player`/`PaymentContext.player`/`CostPayment.player`
→ actor 복사 **없음**, `ActorProvenance` · 새 enum **없음** (`test_20`).

---

## 10. 테스트

### 신규 `tests/test_result_actor_provenance_contract.py` — 24건

| # | 무엇을 고정하나 | §10 항목 |
| --- | --- | --- |
| 01 | `EffectResult` → `ChainResolution.link.actor` | 1 |
| 02 | 생성 자리 **전수 6곳** — `result` 를 주면서 `link` 를 빼는 자리 0 | 7 |
| 02b | 🔴 **실패한 해결도 운반자를 들고 온다** | 7 |
| 03 | result 에 역참조 0 · 직렬화에 사람 0 | 15 |
| 04 | `ChainLink.actor` 는 **발동한 사람** — 컨트롤러를 따라가지 않는다 | 7 |
| 05 | `CostPaymentResult` → `ActivationResult.action.actor` | 2 |
| 06 | 🟢 `ActivationResult` 는 **타입 수준에서 강제**한다 | 8 · 17 · 18 |
| 07 | 🔴 `ChainResolution` 은 **강제하지 않는다** | 16 · 17 · 18 |
| 08 | 🔴 "비용을 지불한 사람" 이 두 가지를 가리킨다 | 5 · 6 |
| 09 | actor ≠ controller ≠ affected | 3 · 4 |
| 10 | **standalone 정책 C** — 거부된다 | 15 |
| 11 | 운반자가 없으면 추측하지 않는다 · 🟡 거짓 선언은 열려 있다 | 16 |
| 12 | `.link.actor` 를 읽는 production 코드 **0개** | 19 |
| 13 | 🟢 운반자가 **듀얼 경계까지** 간다 | 19 |
| 14 | 실제 카드 2장 (parametrize) — actor 하나, affected 다름 | 20 |
| 15 | 비용 2가지 (parametrize) — 자원 주인이 바뀌어도 actor 는 발동자 | 6 |
| 16 | 🟡 컨트롤 변경이 계약을 깨지 않는다 — 깨지는 자리를 지목 | 20 |
| 17 | clone · frozen | 9 |
| 18 | 직렬화 왕복 — 운반자에 남는다 | 10 |
| 19 | `state_hash` · RNG · hidden-information · AI 불변 | 11 ~ 14 |
| 20 | **docstring 셋만** 바뀌었다 (base SHA 와 AST 비교) | 17 · 18 |
| 21 | "result 가 actor 를 소유한다" 라고 적지 않는다 | 20 |

### 고의 위반 검증 — 8건, 전부 잡혔다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `ChainResolution` docstring 에서 복원 경로를 지운다 | `test_20` |
| 2 | `EffectResult` docstring 이 **소유를 주장한다** | `test_21` |
| 3 | `CostPaymentResult` docstring 에서 `payments` 경고를 지운다 | `test_21` |
| 4 | 한 생성 자리가 `link` 를 뺀다 | 3건 — `test_02` · **`test_02b`** · `test_20` |
| 5 | `ActivationResult.action` 을 Optional 로 | `test_06` |
| 6 | `__post_init__` 의 `link` 검사를 없앤다 | `test_06` |
| 7 | `ChainLink.actor` 가 카드 컨트롤러를 따라간다 | **5건** — 04 · 09 · 14 · 20 |
| 8 | production 이 `.link.actor` 를 읽는다 (consumer 등장) | `test_12` |

> 🔴 **주입 4 가 테스트의 사각을 찾아냈다.** 처음에는 구조 단정(`test_02`)이
> **먼저 터져서** 같은 함수 안의 의미 단정이 **실행되지 않았다.** 그래서 실패
> 경로를 **별도 테스트(`test_02b`)로 떼어 냈고**, 이제 둘이 독립적으로 잡는다.

주입 파일 5개(`chain.py` · `activation.py` · `payment.py` ·
`effect/resolution.py` · `duel.py`)는 전부 백업에서 복원하고 md5 로 확인했다
(전부 `OK`).

### 전체 회귀

| 실행 | 결과 |
| --- | --- |
| 1회차 (docstring 만 고친 직후) | `3 failed, 4459 passed, 4 skipped` |
| **2회차 (최종)** | **`4462 passed, 4 skipped in 431.15s`** |

`4,438` (3-F-16) `+ 24` (신규) `= 4,462`. 실패 0 · skip 그대로 4건.

**1회차의 3건이 이 Phase 가 고친 것들이다** (아래 표). 3-F-16 §17 이 "docstring 만
고쳐도 snapshot 이 깨질 것" 이라 예상한 그대로이고, 그중 둘은 snapshot 이 아니라
**측정 방법 자체의 결함**이었다.

`-p no:randomly` 로 돌렸다.

### 🔴 기존 테스트 3건을 고쳤다 — 전부 **낡은 측정 방법** 때문이다

**삭제 0건 · skip 추가 0건 · assertion 약화 0건.**

| 테스트 | 왜 깨졌나 | 어떻게 고쳤나 |
| --- | --- | --- |
| `test_rule_not_implemented_code_audit::test_05` | `resolution.py` 499 → **520**, `payment.py` 372 → **402** — class docstring 이 그 위에 있어 아래가 밀렸다 | 줄 번호를 실측값으로 갱신 + 까닭을 `note` 에 적었다. **자리 수 13 · 짝지은 상태는 그대로** |
| `test_actor_declaration_scope_audit::test_23` (3-F-15) | 🔴 `git diff HEAD` 로 "이 Phase 가 production 을 안 바꿨다" 를 쟀다 | **자기 작업 commit**(`6ae89e8`)을 보도록 고쳤다 |
| `test_result_actor_provenance_design_audit::test_26` (3-F-16) | 같다 | **자기 작업 commit**(`57da2f6`)을 보도록 고쳤다 |

#### 🔴 같은 실수를 세 번째로 고쳤다 — 이번에는 패턴으로 적는다

`git diff HEAD -- engine …` 은 **"지금 작업 나무가 깨끗한가"** 이지 **"이 Phase 가
무엇을 바꿨는가"** 가 아니다. 뒤의 Phase 가 production 을 바꾸면 **그 Phase 때문에**
깨진다.

3-F-14 가 3-F-12 · 3-F-13 의 같은 단정을 고쳤는데, **그 뒤에 쓴 3-F-15 · 3-F-16 이
낡은 모양을 다시 썼다.** 교훈을 한 번 적용하고 **패턴으로 만들지 않은** 탓이다.

그리고 이 Phase 의 `test_20` 을 쓸 때 **같은 실수를 또 하려 했다** — `git show
HEAD:` 로 비교하면 commit 한 뒤에는 "자기와 자기를 비교" 하는 꼴이 되어 **언제나
통과한다.** 커밋 전에 잡아서 **고정된 base SHA**(`0227765`)와 비교하도록 바꿨다.

**앞으로 AUDIT-ONLY 단정은 `HEAD` 가 아니라 고정된 SHA 나 자기 commit 을 본다.**

---

## 11. state_hash / RNG / Search / AI 영향 (§12)

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 결과를 세 번 읽어도 동일 · `game_state.py` 가 result 타입을 모른다 |
| RNG | **불변** | `repr(state.rng)` 동일 · 같은 seed 두 번 → 같은 hash |
| hidden-information | **불변** | 상대 패·덱은 `concealed` |
| Search ranking | **불변** | digest `30fa3597…402c4175` (6 duel · 611 decision) — 기존 3개 파일이 고정하고 전체 회귀에서 통과. **3-F-16 과 동일** |
| AI behavior | **불변** | `agent/` 가 세 타입을 **코드로** 모른다 |
| `GameStateView` · `LegalActions` · `PlayerAction` | **불변** | 건드리지 않았다 |
| Engine V1 freeze | **유지** | 실행되는 코드 0 변경 |
| Trigger pipeline | **dormant 유지** | `event_pipeline` production importer 0 |

---

## 12. 최종 판정

### **A. PROVENANCE_CONTRACT_FIXED**

**기존 운반자가 충분하고, 복원 경로가 문서와 테스트로 명확하게 고정되었다.**

근거 넷.

1. **복원 경로가 세 docstring 에 적혔다** — `ChainResolution` · `EffectResult` ·
   `CostPaymentResult`. 3-F-16 이 "어디에도 적혀 있지 않다" 고 지목한 공백이
   메워졌다.
2. **전수 측정으로 고정했다** — 생성 자리 6곳 위반 0, 실패 경로까지 운반자 보존,
   역참조 0, production consumer 0.
3. **두 운반자의 강도 차이를 명시했다** — `ActivationResult` 는 타입 강제,
   `ChainResolution` 은 호출 경로 보장. 후자는 `.. warning::` 으로 적었다.
4. **되돌리면 깨진다** — 고의 위반 8건이 전부 잡히고, 그중 셋이 docstring 변경만
   으로 걸린다.

### 왜 B(CARRIER_CONTRACT_MISSING)가 아닌가

B 는 "생성/전달 계약이 **불명확**하여 최소한의 계약 **보강**이 필요하다" 다.
계약은 이제 **명확하다** — 문서에 적히고 테스트로 고정되었다.

🟡 **`ChainResolution` 이 타입 수준에서 강제하지 않는 것은 사실이고, 그것을
B 의 근거로 삼지 않은 이유를 적는다.** §13 이 "더 깔끔하게 만들 수 있다" 는 이유로
B 를 고르지 말라고 했고, **실제 semantic 문제가 없다** — 저장소 전체에서 위반이
0곳이고, 위반을 만들면 `read()` 가 **거부**한다 (조용히 틀리지 않는다). 강제를
더하는 것은 **runtime behavior 변경**이므로 §11 이 금지한다. 그래서 다음 Phase 의
판단거리로 넘긴다.

### 왜 C(STANDALONE_RESULT_FORBIDDEN)가 아닌가

C 가 **참이지만 §7 의 답**이고 (§5 에 그렇게 적었다), **이미 강제되어 있다** —
3-F-14 가 `TypeError` 로 만들었다. 이 Phase 가 새로 금지할 것이 없으므로 **최종
판정이 될 수 없다.**

### 왜 D(PROVENANCE_GAP_FOUND)가 아닌가

**production 경로에서 actor 가 소실되는 자리가 없다.** 운반자가 듀얼 경계까지
가고, 거기서도 `DuelStep.action.actor` 로 남는다. 떨어지는 것은 **deltas** 이고
그것은 3-F-5 가 이미 기록한 다른 문제다.

### 🟡 남는 것 하나

**`ChainResolution` 이 `link`/`result` 불변식을 강제하지 않는다.**
`ActivationResult` 는 같은 종류의 불변식을 `__post_init__` 에서 **거부**하므로,
`ChainResolution` 이 이 저장소 안에서 **예외**다. 이 Phase 는 `.. warning::` 으로
적어 두었고 **행동은 바꾸지 않았다**.

---

## 13. 다음 Phase 후보 (1개)

### `ChainResolution` 의 `link`/`result` 불변식을 **강제할 것인가** — 판단 하나

이 Phase 가 계약을 **적었다**. 남은 것은 **그것을 타입이 막게 할 것인가** 하나다.

| | 강제한다 | 강제하지 않는다 (현재) |
| --- | --- | --- |
| 얻는 것 | `result` 만 있고 `link` 가 없는 객체를 **만들 수 없다** | — |
| 잃는 것 | 🔴 **runtime behavior 변경** — 지금 조용히 만들어지는 것이 예외가 된다 | 위반을 만들 수 있다 (저장소에 0곳) |
| 일관성 | 🟢 `ActivationResult` 와 **같은 태도**가 된다 | `ChainResolution` 이 예외로 남는다 |
| 범위 | `engine/chain.py` `__post_init__` 한 곳 | — |

**먼저 확인할 것**: 지금 `result` 없이 `link` 만 주는 자리(정의를 못 찾은 링크)가
있으므로, 강제는 **한 방향만**이어야 한다 — "`result` 가 있으면 `link` 도 있다".
반대 방향을 함께 막으면 그 자리가 깨진다.

> 🔴 그 Phase 도 **줄 수·줄 번호 snapshot 이 깨질 것**을 예상해야 한다. 이번에
> docstring 셋만 고쳤는데도 세 건이 깨졌다.

**시작하지 않는다.** 다음 Phase 는 임의로 진행하지 않는다.

---

## 14. Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`6d9b40e`** `Phase 3-F-17: fix result actor provenance contract` |
| production | `engine/chain.py` +40 · `engine/effect/resolution.py` +21 · `engine/payment.py` +30 — **전부 docstring** |
| 테스트 | 신규 1 · 수정 3 |
| push | `0227765..6d9b40e` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-17: document result actor provenance contract` |

작업 직전 HEAD 는 `0227765` (3-F-16 보고서) 였고, push 결과가 그 SHA 에서 이어진
것으로 확인된다.

> 🟡 이 Phase 는 production 을 바꿨으므로 "작업 commit 이 테스트 파일 하나" 라는
> 증거를 쓸 수 없다. 대신 **문자열 리터럴을 지운 AST 가 base 와 동일**한 것이
> 범위의 증거이고, `test_20` 이 그것을 고정된 SHA 와 비교해 지킨다.
