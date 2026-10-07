# Phase 3-F-18 — `ChainResolution` 의 `link` / `result` 불변식 감사

## 0. Base 와 실제 HEAD

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-17 작업 commit | `6d9b40e` — *Phase 3-F-17: fix result actor provenance contract* | ✅ 존재 |
| Phase 3-F-17 보고서 commit | `3a98c49` — *Phase 3-F-17: document result actor provenance contract* | ✅ 존재 |
| 작업 시작 시 실제 HEAD | `3a98c49` | ✅ 지시받은 Base 와 **일치** |
| 작업 트리 | `tests/test_chain_resolution_link_result_invariant.py` 만 untracked | — |

Base 가 어긋나지 않았으므로 정정할 것이 없다. Phase 3-F-17 최종 판정
**A. PROVENANCE_CONTRACT_FIXED** 를 그대로 전제로 삼았다.

---

## 1. 이번 Phase 의 단 하나의 질문

> `ChainResolution` 에서 `link` 와 `result` 의 관계를 **runtime/type 수준에서 반드시
> 강제해야 하는가.**

그리고 지시대로 **두 방향을 하나로 묶지 않았다.**

| 방향 | 판정 | 근거 |
|---|---|---|
| **A.** `result` 가 있으면 `link` 도 있어야 하는가 | 🟢 **불변식이다.** 그리고 단순히 "지켜지고 있다" 가 아니라 **인과적으로 그렇게만 만들어진다** | §4 · §5 |
| **B.** `link` 가 있으면 `result` 도 있어야 하는가 | 🔴 **불변식이 아니고, 불변식으로 만들어서도 안 된다** | §6 |

두 방향이 **다른 계약**이라는 것이 이 Phase 의 핵심 결과다. 하나로 묶으면
"정의를 못 찾은 링크" 라는 **정상 보고가 불법**이 된다(§6).

---

## 2. `ChainResolution` 의 실제 구조 (AST 측정)

`engine/chain.py:435` — `@dataclass(frozen=True, slots=True)`

| 칸 | 타입 | 기본값 |
|---|---|---|
| `status` | `ChainResolutionStatus` | 없음 (필수) |
| `chain` | `Chain` | 없음 (필수) |
| `code` | `ValidationCode` | `RULE_NOT_IMPLEMENTED` |
| `reason` | `str` | `""` |
| **`link`** | `ChainLink \| None` | **`None`** |
| **`result`** | `EffectResult \| None` | **`None`** |

측정으로 확인한 것:

| 확인 항목 | 결과 |
|---|---|
| `frozen` | ✅ `True` — 만든 뒤 칸을 바꿀 수 없다 |
| `slots` | ✅ `True` — 칸을 몰래 더 붙일 수 없다 |
| `classmethod` / `staticmethod` | **0개** — `ChainResolution.of(...)` 같은 factory 가 **없다** |
| `to_dict` | 있다 |
| **`from_dict`** | **없다** — 역직렬화로 임의 조합을 되살릴 입구가 없다 |
| `__post_init__` | 있다. 그런데 `link`·`result` 를 **보지 않는다**(§8) |
| `replace` / `_replace` production 호출 | **0곳**(§9) |
| clone / copy 경로 | 없다. `GameState.clone()` 은 보고를 건드리지 않는다 |
| replay 경로 | **아직 없다** — `to_dict` 는 있으나 되읽는 코드가 저장소에 없다 |

### `ChainResolution` 은 "문맥" 이 아니라 "보고" 다

§5 가 요구한 의미 확정이다. 다섯 가지를 섞지 않고 각각 판단했다.

| §5 의 구분 | 이 엔진에서의 사실 |
|---|---|
| ① "아직 결과가 생성되지 않았다" | **`ChainResolution` 으로 표현되지 않는다.** 링크를 쌓아만 두면 `Chain.links` 에 `ChainLink` 가 있을 뿐이고 `ChainResolution` 객체는 **아예 존재하지 않는다**(`test_10`) |
| ② "결과는 생성됐는데 link 가 없다" | **production 에 그런 생성 자리가 0곳**이고, 애초에 **만들 수 없다**(§5) |
| ③ "link 없는 `ChainResolution` 이 허용되는 중간 상태다" | ✗ 아니다. 중간 상태라는 것이 없다 — 모든 생성이 `resolve_top` 의 `return` 문이다 |
| ④ "둘 다 `None` 인 것이 정상적인 초기 상태다" | "초기 상태" 로서는 ✗. 다만 **"해결할 것이 없었다" 는 정상 보고**로서 ○ 다(§7) |
| ⑤ "잘못된 객체가 실수로 생성됐다" | ✗ 저장소 어디에도 없다 |

즉 `ChainResolution` 은 **"특정 `ChainLink` 를 해결하려 한 결과를 적은 보고"** 이고,
"결과를 만들기 전의 resolution context" 가 **아니다**. 그래서 §8 의 선택지
**E(중간 lifecycle 때문에 일부 조합을 허용해야 한다)** 는 **해당하지 않는다** —
허용해야 할 중간 상태가 애초에 없다.

---

## 3. `link` / `result` 의 의미

| 칸 | 뜻 | 없을 때의 뜻 |
|---|---|---|
| `link` | 이 보고가 **어느 링크에 대한** 보고인지 | 가리킬 링크가 없었다 (체인이 비었거나 다 끝났다) |
| `result` | 실행기가 그 링크를 **실제로 돌려 본** 결과 | 실행기까지 **가지 못했다** |

그리고 Phase 3-F-17 이 고정한 provenance 가 여기에 얹힌다.

```
EffectResult (actor 를 들고 있지 않다)
    ← ChainResolution.link.actor      # 🔴 유일한 복원 경로
```

따라서 **`result` 가 있는데 `link` 가 없는 객체는 "누가 했는지 영원히 알 수 없는
결과"** 다. A 방향이 중요한 이유가 이것이다.

---

## 4. 실제 생성 경로 — 전수 (AST)

저장소 **전체** 에서 `ChainResolution(...)` 생성 자리는 **8곳**이고, 그중 감사 도구
자신의 시연 2곳을 빼면 감사 대상은 **6곳**이다.

| # | 자리 | `link` | `result` | 뜻 | 정상? |
|---|---|---|---|---|---|
| 1 | `engine/chain.py:609` | ✗ | ✗ | `EMPTY_CHAIN` — 쌓인 링크가 없다 | 🟢 |
| 2 | `engine/chain.py:616` | ✗ | ✗ | `CHAIN_COMPLETE` — 남은 링크가 없다 | 🟢 |
| 3 | `engine/chain.py:627` | **○** | ✗ | `INVALID_CHAIN_LINK` — **정의를 못 찾았다** | 🟢 |
| 4 | `engine/chain.py:642` | ○ | ○ | 실행기까지 갔고 **해결하지 못했다** | 🟢 |
| 5 | `engine/chain.py:650` | ○ | ○ | `RESOLVED` — 해결했다 | 🟢 |
| 6 | `tests/engine/test_chain.py:607` | ○ | ○ | 테스트가 직접 만든 보고 | 🟢 |
| — | `tests/test_chain_resolution_…:642` | ○ | ○ | 이 감사의 시연 (허용 조합) | 감사 도구 |
| — | `tests/test_chain_resolution_…:664` | ✗ | **○** | 이 감사의 시연 (**불법** 조합) | 감사 도구 |

* **production 5곳 전부 `engine/chain.py`** — 그것도 전부 `ChainResolver.resolve_top`
  **하나의 메서드 안**이다.
* `ChainResolution` 을 import 하는 production 파일은 **`engine/response.py` 하나**이고,
  거기서는 `ResponseResolution.steps: tuple[ChainResolution, ...]` 로 **담기만** 한다 —
  만들지도, 고치지도 않는다.
* 🔴 **`result` 만 주는 자리는 production 에 0곳, 테스트에 0곳이다.** 저장소에서 단
  하나 있는 것은 이 감사가 §8 증거로 **일부러 만든** 자리뿐이다.

---

## 5. A 방향 — `result` ⟹ `link` 는 **인과적으로** 성립한다

이것이 이번 Phase 에서 가장 중요한 측정이다. "쓰지 않아서 없다" 와 "만들 수 없다" 는
전혀 다른 말이다.

`resolve_top` 안에서 `result` 를 얻는 길이 **단 하나**다.

```python
definition = self.definition_for(link)
if definition is None:
    return ChainResolution(..., link=link)          # ← link-only 보고 (§6)

result = self._executor.execute(state, definition, link.resolution_context())
#                                                  ^^^^^^^^^^^^^^^^^^^^^^^^
```

측정 결과:

| 측정 | 값 |
|---|---|
| `self._executor.execute(` 등장 횟수 (문자열 리터럴 제거 후) | **1회** |
| 그 호출이 받는 문맥 | `link.resolution_context()` — **`link` 에서 만들어진다** |
| 그 앞을 막는 것 | `self.definition_for(link)` |

즉 **`result` 를 손에 넣으려면 그 시점에 `link` 가 이미 있어야 한다.** `link` 없이
`result` 를 만드는 것은 "안 하고 있는 일" 이 아니라 **할 수 없는 일**이다. 그래서
A 방향 불변식은 `__post_init__` 이 추가로 거는 규칙이 아니라 **생성 방식의 결과**다.

→ §8 분류 **B(생성 경로에서 이미 보장된다)**.

---

## 6. B 방향 — `link` ⟹ `result` 는 **불변식이 아니고, 만들어서도 안 된다**

`engine/chain.py:627` 의 보고가 바로 `link` 만 있는 정상 보고다.

```python
if definition is None:
    return ChainResolution(
        ChainResolutionStatus.INVALID_CHAIN_LINK,
        chain,
        ValidationCode.CHAIN_DEFINITION_UNAVAILABLE,
        f"{link.effect_ref} 의 정의가 등록되어 있지 않아 해결할 수 없습니다.",
        link=link,
    )
```

이 보고는 **반드시 `link` 를 들고 있어야 한다** — "어느 링크의 정의가 없었는지" 가
이 보고의 알맹이다. 그런데 실행기까지 가지 않았으므로 `result` 는 **있을 수가 없다.**

실제 카드로 확인했다. 홍옥의 사령(`11091375`)은 **통상 몬스터**라서 효과 라이브러리에
정의가 없다. 그 링크를 해결하려 하면:

```
status=invalid_chain_link   link=있다(actor=1)   result=None   deltas=()
```

🔴 만약 B 방향을 `__post_init__` 에서 강제하면 **이 보고 자체가 예외를 던진다** —
주입 2번이 실제로 그것을 증명했다(§12). 지시 §13 의 "기존 lifecycle 을 깨뜨릴 수 있는
강제 검증은 금지한다" 에 정확히 걸리는 경우다.

### `status` 만으로는 구분되지 않는다 (측정으로 드러난 사실)

| 경우 | `status` | `link` | `result` |
|---|---|---|---|
| 정의를 못 찾았다 | `invalid_chain_link` | ○ | **✗** |
| 실행기까지 갔는데 대상 판정에서 막혔다 (싸이크론 `5318639`) | `invalid_chain_link` | ○ | **○** |

**같은 `status` 인데 `result` 유무가 다르다.** 그래서 "status 를 보고 result 가 있는지
판단" 하는 코드를 쓰면 틀린다. 지시 §5 의 ①과 ③을 섞지 않아야 하는 이유가 여기서
구체적으로 드러난다.

---

## 7. both-`None` 분석

두 가지 서로 다른 사실이 같은 모양을 쓴다. 그리고 그 둘은 `status` 로 **정확히**
구분된다.

| `status` | 뜻 |
|---|---|
| `EMPTY_CHAIN` | 쌓인 링크가 **하나도 없다** |
| `CHAIN_COMPLETE` | 쌓였던 링크를 **다 해결했다** |

둘 다 "가리킬 링크가 없다" 이므로 `link=None` 이 **맞다.** 이것은 "초기 상태" 가
아니라 **"해결할 것이 없었다" 는 완결된 보고**다. 그리고 이 보고에는 **행위자를 물을
자리가 없다** — 아무도 아무 일도 하지 않았다.

---

## 8. `__post_init__` 분석 — §8 분류는 **B**

현재 `__post_init__` 이 보는 것은 **`status` / `deltas` 짝 하나뿐**이다.

```python
def __post_init__(self) -> None:
    if self.status is not ChainResolutionStatus.RESOLVED and self.deltas:
        raise ChainError(...)        # 해결되지 않은 링크는 판을 바꾸지 않는다
```

`link` 도 `result` 도 **보지 않는다.** 그 이유를 §8 의 다섯 선택지로 분류하면:

| 선택지 | 판정 |
|---|---|
| A. runtime 에서 강제할 필요가 없다 | 결론은 맞지만 **왜 필요 없는지를 말하지 않는다** |
| **B. 생성 경로에서 이미 보장된다** | ✅ **이것이다.** `result` 는 `link.resolution_context()` 로만 만들어진다(§5) |
| C. 테스트/호출 관례로만 보장된다 | ✗ **관례가 아니다.** 관례라면 다른 호출을 쓸 수 있다는 뜻인데, 쓸 다른 호출이 없다 |
| D. production 에서 violation 가능성이 있다 | ✗ production 생성 자리 5곳 전부 합법이고, `replace` 호출자가 0곳이다 |
| E. 중간 lifecycle 때문에 일부 조합을 허용해야 한다 | ✗ 중간 상태가 없다 — `frozen` · factory 없음 · 전부 `return` 문 |

### 🟡 기록해 두는 비대칭 (고치지 않는다)

같은 저장소의 `ActivationResult` 는 **같은 종류의 불변식을 runtime 에서 거부한다.**

| | `ChainResolution` | `ActivationResult` |
|---|---|---|
| carrier 칸 | `link`, 기본값 `None` | `action`, **필수** (기본값 없음) |
| `__post_init__` 에서 carrier 검사 | **없음** | **있음** (`self.link is None` → `ActivationError`) |

즉 `ChainResolution` 이 이 저장소 안에서 **느슨한 쪽**이다. 그런데 지시 §13 은
"단순히 더 엄격하게 만들 수 있다는 이유로 `__post_init__` 에 예외를 추가하지 않는다"
라고 못 박았고, §13 이 허용한 세 조건 ①②③ 중 **하나도 성립하지 않는다**:

* ① *production 에서 result 가 있는데 link 가 사라지는 경로* → **없다**(§4 · §5 · §9)
* ② *constructor 가 명백히 잘못된 객체를 허용하고 그것이 production 경로에서 생성될
  수 있다* → 허용은 하지만(타입이 느슨하다) **production 경로에서 생성되지 않는다**
* ③ *문서만으로는 안전하게 유지할 수 없다* → 3-F-17 이 이미 `.. warning::` 으로 적었고,
  이 Phase 가 26개 테스트로 **계약을 실행 가능한 형태로** 고정했다

그래서 **production 을 한 줄도 바꾸지 않았다.** 이 비대칭은 🟡 로 기록만 한다.

---

## 9. `dataclasses.replace` 분석

| 측정 | 값 |
|---|---|
| `ChainResolution` 에 `replace` 를 쓰는 **production** 호출 | **0곳** |
| 쓰는 곳 | 감사 테스트 **6곳**뿐 — 3-F-16 2곳(`…design_audit.py:766,767`) · 3-F-17 2곳(`…contract.py:435,529`) · 이 Phase 2곳(`…invariant.py:557,582`). 전부 **위험을 보이려고** 쓴다 |
| production 의 `replace` 대상 타입 | `Duel`, `CostContext`, `_Step`, `SelectionCount` — `ChainResolution` 은 없다 |

그래서 지시 §9 가 요구한 구분을 그대로 적는다.

* **구조적으로 가능한 위험** — `dataclasses.replace(resolution, link=None)` 은 동작한다.
  `frozen=True` 가 막아 주지 않는다 (`replace` 는 새 객체를 만든다).
* **실제 production bug** — **아니다.** 호출자가 0곳이다.

그리고 한 가지를 더 측정했다: **그 객체를 만들어도 조용히 틀리지 않는다.**

```python
orphaned = dataclasses.replace(report, link=None)
EventReader(view).read(orphaned.result)      # → TypeError
#   "actor 를 말해야 합니다. … 부르는 쪽만 압니다"
```

Phase 3-F-14 가 세운 `read()` 입력 계약이 **마지막 방어선**으로 실제로 작동한다.
`orphaned.result` 에는 `actor`·`controller`·`action` 중 **아무 칸도 없으므로**
복원할 길이 없는데, 그 상태로 사건을 읽으려 하면 **거부당한다.** 즉 provenance 소실이
침묵으로 이어지지 않는다.

반대 방향 `replace(result=None)` 은 **불변식을 깨지 않는다** — link-only 는 정상
모양이고(§6), production 의 "정의 없음" 보고와 **같은 조합**이 된다.

---

## 10. actor provenance 영향 — §10 금지 항목 준수

| 금지 항목 | 상태 |
|---|---|
| `EffectResult.actor` 추가 | ✅ 추가하지 않았다 (`fields(EffectResult)` 에 `actor` 없음) |
| `CostPaymentResult.actor` 추가 | ✅ 추가하지 않았다 |
| `ActorProvenance` 추가 | ✅ 세 파일 어디에도 없다 |
| 새 enum 추가 | ✅ `ChainResolutionStatus` 8개 그대로, `ChainResolution` 칸 6개 그대로 |

그리고 두 carrier 계약을 **섞지 않았다.**

```
EffectResult        ← ChainResolution.link.actor      (이 Phase 가 감사한 것)
CostPaymentResult   ← ActivationResult.action.actor   (다른 계약 — 건드리지 않았다)
```

**`ChainResolution.link` 의 lifecycle 이 안전한가** 가 이 Phase 의 질문이었고, 답은
**안전하다** 다 — 그 carrier 는 `result` 를 담는 **모든** 자리에서 함께 담긴다.

---

## 11. 실제 카드 · 듀얼 시나리오 (§11)

전부 공식 DB 의 실제 카드로 측정했다. 추측한 값이 없다.

| # | §11 항목 | 사용한 카드 | `ChainResolution` | `link` | `result` | actor 복원 |
|---|---|---|---|---|---|---|
| 1 | 일반 링크 생성 → 해결 → `EffectResult` | 욕망의 항아리 `55144522` | 있다 `resolved` | ○ | ○ (deltas 2개) | ✅ `link.actor=0` |
| 2 | 링크 생성, 아직 result 없음 | 욕망의 항아리 | **없다** — `Chain.links` 에만 있다 | — | — | `chain.top.actor` |
| 3 | 정상 `EffectResult` | 욕망의 항아리 | 있다 | ○ | ○ | ✅ |
| 3' | 실행기까지 갔으나 해결 실패 | 싸이크론 `5318639` | 있다 `invalid_chain_link` | ○ | ○ (deltas 0개) | ✅ `link.actor=1` |
| 3'' | 정의를 못 찾았다 | 홍옥의 사령 `11091375` (통상 몬스터) | 있다 `invalid_chain_link` | ○ | **✗** | ✅ `link.actor=1` |
| 4 | 비용 지불 결과 | — | **다른 계약** — `ActivationResult.action.actor` | — | — | ✅ (§10) |
| 5 | clone | 욕망의 항아리 | `GameState.clone()` 이 보고를 **건드리지 않는다** | 그대로 | 그대로 | ✅ |
| 6 | replay | — | **replay 경로가 아직 없다.** `to_dict` 는 있고 `from_dict` 는 없다 | — | — | 🟡 replay 를 만들면 입구가 하나 더 생긴다 |
| 7 | 실제 duel | 홍옥의 사령 덱 | 네 조합 중 하나만 나온다 | — | — | ✅ |

**빈 체인 / 체인 완료** 도 실측했다.

| 경우 | `status` | `link` | `result` | `deltas` |
|---|---|---|---|---|
| 빈 체인 | `empty_chain` | ✗ | ✗ | 0 |
| 체인 완료 | `chain_complete` | ✗ | ✗ | 0 |
| 정의 없는 링크 | `invalid_chain_link` | **○** | ✗ | 0 |
| 해결 성공 | `resolved` | ○ | ○ | 2 |
| 해결 실패 | `invalid_chain_link` | ○ | ○ | 0 |
| **result only** | — | ✗ | ○ | — → **production 에서 만들 수 없다** |

🟡 §11 6 (replay) 는 **지금 존재하지 않는 기능**이다. 없는 것을 있다고 적지 않는다.
replay 를 구현하는 Phase 가 `from_dict` 를 만들면 **생성 입구가 두 개**가 되므로,
그때 A 방향 보장이 다시 측정되어야 한다.

---

## 12. 일부러 깨 보기 — 주입 8건

측정이 **정말로 재고 있는지** 확인하려고, `engine/chain.py` 를 백업(md5 고정) 한 뒤
8가지 위반을 하나씩 심고 되돌렸다. 마지막 md5 가 원본과 일치함을 확인했다
(`5af77e7d3b7e3008e4d9157b27c47ef0`).

| # | 심은 위반 | 걸린 테스트 | 결과 |
|---|---|---|---|
| 1 | A 방향을 `__post_init__` 에서 강제 (result 면 link 필수) | `test_11` `test_13` `test_15` | ✅ 잡았다 |
| 2 | **B 방향을 강제** (link 면 result 필수) | `test_06` `test_12` `test_13` `test_19` `test_20` | ✅ 잡았다 — **정상 보고가 깨진다는 증거** |
| 3 | "정의 없음" 보고에서 `link=link` 를 뗀다 | `test_02` `test_04` `test_06` `test_12` `test_19` | ✅ 잡았다 |
| 4 | 성공 보고에서 `link=link` 를 뗀다 → **production 에 result-only 가 생긴다** | `test_02` `test_02b` `test_04` `test_07` `test_11` `test_12` `test_18` `test_19` `test_20` `test_23` | ✅ 잡았다 |
| 5 | `result` 를 `link` 가 아닌 곳에서 만든다 | `test_03` 외 10개 | ✅ 잡았다 |
| 6 | `result` 를 얻는 경로를 하나 더 만든다 | `test_03` | ✅ 잡았다 |
| 7 | `frozen` 을 뗀다 | `test_01` `test_18` | ✅ 잡았다 |
| 8 | `from_dict` 역직렬화 입구를 만든다 | `test_01` `test_17` | ✅ 잡았다 |

주입 2번과 4번이 이 Phase 의 두 판정을 각각 뒷받침한다. 2번은 **B 방향을 강제하면
안 되는 이유**를, 4번은 **A 방향이 깨지면 무엇이 무너지는지**를 보여 준다.

---

## 13. 🔴 감사 도구가 자기 자신을 세어 틀렸다 — 네 번째

이 Phase 에서 테스트를 처음 돌렸을 때 **3개가 실패했다.** 원인은 production 이 아니라
**측정 도구**였다.

`test_02` · `test_04` 는 "저장소에 result-only 생성 자리는 0곳이다" 를 센다. 그런데
`test_15` 는 **타입이 그 조합을 막지 않는다는 §8 증거로 그 조합을 일부러 만든다.**
구분 없이 세니 도구가 **자기 증거를 위반으로 신고**해서 스스로를 반증했다.

| Phase | 자기측정 함정 |
|---|---|
| 3-F-8 | 정규식이 자기 파일의 패턴을 셌다 |
| 3-F-13 | 호출 자리 측정이 자기 "거부 시험" 호출을 셌다 |
| 3-F-16 | 중첩 함수 탐색이 자기 주입 코드를 셌다 |
| **3-F-18** | **"불법 조합 0곳" 을 세는 도구가 자기 시연을 셌다** |

고친 방향은 **"자기 코드를 지우기" 가 아니다.** 그 시연은 §8 판정의 증거이므로 남아야
한다. 측정을 **감사 대상(저장소)** 과 **감사 도구(이 파일)** 로 갈라서 **둘 다** 세고,
새 `test_02b` 가 뺀 것이 정확히 무엇인지 못 박는다.

```python
MYSELF = "tests/test_chain_resolution_link_result_invariant.py"

def audited_constructions(name):   # 감사 대상
    return [s for s in every_construction(name) if s[0] != MYSELF]

def my_own_constructions(name):    # 일부러 만든 시연 — 숨기지 않는다
    return [s for s in every_construction(name) if s[0] == MYSELF]
```

`test_02b` 가 단정하는 것:

* 둘로 나눈 합이 전체와 같다 (흘린 자리가 없다)
* 내 시연은 **정확히 2곳**이고 조합은 `(link, result)` 와 `(result,)` 다
* 🔴 저장소 전체에서 **불법 조합은 이 파일 안에만** 있다
* **production 에는 0곳** — 이것이 §8 B 판정의 근거다

### 같이 고친 두 가지

* `test_01` 이 `inspect.cleandoc()` 으로 메서드 소스를 정리하다 **본문 들여쓰기를
  깨뜨려** `IndentationError` 로 실패했다. `textwrap.dedent()` 가 맞는 도구다.
* `test_20` 에 `if False else` 로 남은 **죽은 코드**가 있었다. 지웠다.

### `test_24` 의 측정 기준도 고쳤다

`git diff HEAD` 로 재면 commit 뒤에 **자기와 자기를 비교**해서 언제나 통과한다 —
3-F-12 · 3-F-13 · 3-F-15 · 3-F-16 이 그 함정에 빠졌고 3-F-14 · 3-F-17 이 고쳤다.
그렇다고 "base SHA ↔ 작업 트리" 로 재면 **뒤의 Phase 가 production 을 바꿀 때 그
Phase 때문에 깨진다.** 그래서 **이 테스트 파일을 추가한 commit**(= 3-F-18 작업 commit)
을 `git log --diff-filter=A` 로 찾아서 그 commit 하나만 본다. 영구히 안정적이고,
재는 대상도 정확히 이 Phase 다.

### digest 를 네 번째로 베껴 적지 않았다

검색 ranking digest 는 3-F-5 이후 **일곱 감사 파일**이 같은 값을 못 박고 있다 (측정값).
복사본을 더 만들면 "어느 쪽이 기준인가" 가 흐려지므로, `test_25` 는 기존 pin 들을
**AST 로 읽어** 전부 같은 값인지 확인하고 이번에 돌린 digest 를 그 값과 비교한다.
digest 불변과 **pin 들의 일치**를 함께 재는 셈이다.

---

## 14. 테스트 결과

새 파일: `tests/test_chain_resolution_link_result_invariant.py` — **26개** (요구 최소 20개)

| # | 테스트 | §12 요구 항목 |
|---|---|---|
| 01 | 보고이지 문맥이 아니다 (`frozen` · factory 없음 · 전부 `return`) | 10, 11 |
| 02 | 생성 자리 전수 6곳 분류 | 15 |
| **02b** | **감사 도구가 자기 시연을 세지 않는다** | §13 |
| 03 | 🟢 `result` 는 `link` 에서 만들어진다 → result-only 는 **불가능** | 5, 7 |
| 04 | 🔴 두 방향은 같은 계약이 아니다 | 1~4 |
| 05 | 빈 체인 → 둘 다 `None` | 4 |
| 06 | 정의 없는 링크 → **link only** | 2 |
| 07 | 해결 성공 → 둘 다 | 1 |
| 08 | 해결 실패도 둘 다 (같은 `status`, 다른 `result` 유무) | 1 |
| 09 | 체인 완료 → 둘 다 `None` | 4 |
| 10 | 체인 위의 링크에는 `ChainResolution` 이 **아예 없다** | 2 |
| 11 | link 없는 result 는 provenance 를 잃고, **읽으면 거부된다** | 3, 7, 8 |
| 12 | `replace(result=None)` 은 무해하다 | 9 |
| 13 | `__post_init__` 은 `deltas` 만 본다 → 분류 **B** | 10 |
| 14 | `ActivationResult` 는 더 엄격하다 — 비대칭은 실재한다 | 11 |
| 15 | 타입 계약 < 호출 경로 보장 | 11 |
| 16 | 🟢 production `replace` 호출 **0곳** | 8, 9 |
| 17 | 역직렬화 입구 없음 (`from_dict` 없음) | 13, 14 |
| 18 | clone 이 보고를 건드리지 않는다 | 12 |
| 19 | 직렬화 왕복 | 14 |
| 20 | 실제 듀얼이 네 정상 조합만 낸다 | 15 |
| 21 | `CostPaymentResult` 는 **다른 carrier** 를 쓴다 | 17 |
| 22 | 새 field · enum · provenance 추상 없음 | §10 |
| 23 | `state_hash` · RNG · hidden-information · AI 불변 | 18, 19 |
| 24 | AUDIT-ONLY — production 변경 0줄 | §13 |
| 25 | 검색 ranking digest 불변 (611결정) | 20 |

기존 테스트를 **삭제하지 않았고, skip 을 넣지 않았고, assertion 을 약화하지 않았다.**

### 전체 회귀 — 1차

```
1 failed, 4487 passed, 4 skipped in 415.86s
FAILED tests/test_result_actor_provenance_contract.py::test_02_every_site_that_carries_a_result_carries_the_link
```

수집 **4488개** = 3-F-17 의 4462개 + 이 Phase 의 26개. 숫자는 정확히 맞았고,
실패 1건은 **production 때문이 아니라 Phase 3-F-17 테스트의 잘못된 가정** 때문이었다.

---

## 14-B. 🔴 기존 테스트 하나를 고쳤다 — 왜 그 가정이 틀렸는가

고친 테스트: `tests/test_result_actor_provenance_contract.py::test_02_every_site_that_carries_a_result_carries_the_link` (Phase 3-F-17 작성)

### 무엇이 깨졌나

```
assert len(sites) == 6, sites
E  assert 8 == 6
```

### 왜 그 가정이 틀렸나 — 두 겹이다

**① 총수는 계약이 아니다.**
그 테스트가 지키려던 계약은 *"`result` 를 담는 자리는 `link` 도 담는다"* 다. 그런데
그것을 **"저장소 전체의 생성 자리는 6곳"** 이라는 총수 snapshot 으로 재고 있었다.
총수는 계약을 재는 여러 방법 중 **가장 부서지기 쉬운** 것이고, 계약과 무관한 변화에도
반응한다. 실제로 이번에 깨진 이유는 계약 위반이 아니라 **감사 파일이 하나 늘었다**
는 것뿐이었다.

**② 고의 시연을 위반과 같이 셌다.**
Phase 3-F-18 은 "타입이 불법 조합을 막지 않는다" 를 증명하려고 **그 조합을 일부러
만드는** 감사다(`test_15`). 감사 파일이 반례를 만들어 보이는 것은 **위반이 아니라
증거**다. 둘을 구분하지 않으면 **뒤의 감사가 반례를 만들 때마다 앞의 감사가 깨진다.**

이것은 이 프로젝트에서 반복된 자기측정 함정의 **감사 사이(cross-audit) 판본**이다.

| Phase | 함정 |
|---|---|
| 3-F-8 | 정규식이 **자기 파일**의 패턴을 셌다 |
| 3-F-13 | 호출 자리 측정이 **자기** "거부 시험" 호출을 셌다 |
| 3-F-16 | 중첩 함수 탐색이 **자기** 주입 코드를 셌다 |
| 3-F-18 (§13) | "불법 조합 0곳" 도구가 **자기** 시연을 셌다 |
| **3-F-17 ← 3-F-18** | **앞 Phase 의 도구가 뒤 Phase 의 시연을 셌다** |

### 어떻게 고쳤나 — 숫자를 올리지 않았다

`6` 을 `8` 로 바꾸는 것은 **고치는 것이 아니다.** 다음 감사가 또 `ChainResolution` 을
만들면 똑같이 깨진다. 계약을 그대로 두고 **시연 파일을 이름으로 명시해서 따로 센다.**

```python
DEMONSTRATION = "tests/test_chain_resolution_link_result_invariant.py"
audited       = [s for s in sites if s[0] != DEMONSTRATION]
demonstration = [s for s in sites if s[0] == DEMONSTRATION]
```

**단정은 약해지지 않고 늘어났다.**

| 원래 | 고친 뒤 |
|---|---|
| 총수 6 (부서지기 쉬움) | 감사 **대상** 6 + 나눈 합이 전체와 일치 |
| 전체에 위반 0곳 | 시연 파일 **밖에** 위반 0곳 **＋** 시연은 정확히 1곳 **＋** production 에 위반 0곳 (새로 추가) |
| production 5곳 | 그대로 |

assertion 을 **삭제하지도, skip 하지도, 약화하지도 않았다.** production 은 여전히
**0줄** 변경이다 — 고친 것은 테스트 파일이다.

### 전체 회귀 — 2차 (수정 후) 🟢

```
4488 passed, 4 skipped in 436.03s (0:07:16)
```

| | 개수 |
|---|---|
| Phase 3-F-17 (base `3a98c49`) | 4462 |
| 이 Phase 가 추가한 테스트 | **+26** |
| **합계 (실측)** | **4488** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음** — 기존과 같다) |

삭제한 테스트 0개. 추가한 skip 0개. 약화한 assertion 0개. 고친 기존 테스트 1개 —
이유는 §14-B 에 적었다.

---

## 15. state_hash / RNG / Search / AI 영향

| 항목 | 결과 | 확인 방법 |
|---|---|---|
| `state_hash` | **불변** | 보고를 세 번 읽어도 해시가 그대로 (`test_23`) |
| RNG | **불변** | `repr(state.rng)` 가 그대로. 같은 seed → 같은 `state_hash` |
| Search ranking digest | **불변** — 6판 **611결정** | `test_25`, 기존 7개 pin 과 일치 |
| AI | **불변** | `agent/` 코드에 `ChainResolution`·`EffectResult`·`CostPaymentResult` 가 **한 번도 나오지 않는다** |
| `GameStateView` | **불변** | 상대 손·덱이 `concealed=True`, `cards=()` |
| `LegalActions` · `PlayerAction` | **불변** | production 변경 0줄 |
| Engine V1 freeze | **유지** | `git show --stat aa3772f -- engine agent app core analysis rules rulings sources scripts` 가 **빈 출력** (작업 commit 이 건드린 것은 테스트 2개뿐) |

---

## 16. 최종 판정

> ## **A. CHAIN_RESOLUTION_INVARIANT_ALREADY_SUFFICIENT**

현재 생성 lifecycle 로 **충분히 보장되며 추가 runtime 강제가 필요 없다.**

근거를 요약한다.

1. **A 방향(`result` ⟹ `link`)은 인과적으로 성립한다.** `result` 는
   `link.resolution_context()` 를 넘기는 **단 하나의 호출**에서만 나온다. 쓰지 않아서
   없는 것이 아니라 **만들 수 없다**(§5).
2. **B 방향(`link` ⟹ `result`)은 성립하지 않고, 강제하면 정상 보고가 깨진다.**
   "정의를 못 찾은 링크" 는 `link` 만 들고 있어야 하는 합법 보고다. 주입 2번이 이를
   실증했다(§6 · §12).
3. **production 에 위반 경로가 없다.** 생성 자리 5곳 전부 합법, `replace` 호출자 0곳,
   factory 0개, `from_dict` 없음(§4 · §9).
4. **중간 상태가 없다.** `frozen=True` · 모든 생성이 `return` 문 → §8 **E 는 해당하지
   않는다**(§2).
5. **깨진 객체를 억지로 만들어도 침묵하지 않는다.** 3-F-14 의 `read()` 입력 계약이
   `TypeError` 로 거부한다(§9).

다른 선택지를 **왜** 고르지 않았는지:

| 선택지 | 고르지 않은 이유 |
|---|---|
| B. `…DOCUMENT_ONLY` | "문서로만 표현되어 있다" 가 **사실이 아니다.** 3-F-17 이 `.. warning::` 까지 적었고, 보장의 본체는 문서가 아니라 **생성 방식**이다 |
| C. `…NEEDS_RUNTIME_GUARD` | 지시 §15 가 "단순한 코드 스타일이나 잠재적 가능성만으로 C/E 를 선택하지 않는다" 라고 못 박았다. 실제 violation 경로가 **0곳**이다 |
| D. `…REQUIRES_PARTIAL_STATE` | 가까웠지만 **틀리다.** link-only 는 "부분 상태(partial state)" 가 아니라 **완결된 보고**다. "아직 결과가 없다" 는 `ChainResolution` 이 아니라 `Chain` 이 표현한다(`test_10`). 다만 D 가 경고하는 "단일 invariant 로 묶으면 안 된다" 는 **맞고**, 그것을 §1 의 두 방향 분리로 반영했다 |
| E. `PROVENANCE_GAP_FOUND` | provenance 가 소실되는 **production 경로가 없다.** 3-F-17 에서 고친 그대로다 |

### production 변경

**0줄.** 지시 §13 이 허용한 세 조건 ①②③ 중 하나도 성립하지 않았다(§8).

### 🟡 고치지 않고 기록만 하는 것

| 항목 | 내용 |
|---|---|
| 타입 비대칭 | `ActivationResult` 는 carrier 를 필수로 두고 `__post_init__` 에서 검사하는데, `ChainResolution` 은 둘 다 하지 않는다. 지금은 생성 자리가 지킨다 |
| `dataclasses.replace` | `frozen=True` 가 막아 주지 않는다. production 호출자는 0곳 |
| replay 가 없다 | `from_dict` 가 생기면 **생성 입구가 두 개**가 되어 A 방향 보장이 다시 측정되어야 한다 |
| `status` 로 `result` 유무를 판단할 수 없다 | `invalid_chain_link` 가 두 경우에 모두 쓰인다(§6) |

---

## 17. 다음 Phase 후보 (최대 1개)

**`ChainResolution` 직렬화 ↔ replay 입구 계약 감사.**

이유: 이 Phase 가 A 방향 보장의 근거를 **"생성 입구가 `resolve_top` 하나뿐"** 이라는
사실 위에 세웠다. `to_dict()` 는 이미 있고 `from_dict()` 는 없다 — 즉 지금은 입구가
하나다. replay 나 기록 재생을 구현하는 Phase 가 역직렬화 입구를 만들면 **그 근거가
그날 무효가 된다.** 그래서 "기록에 무엇을 남겨야 보고를 안전하게 되살릴 수 있는가"
(특히 `link.actor` 를 포함한 provenance 가 왕복하는가) 를 **replay 를 만들기 전에**
고정해 두는 것이 순서상 맞다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
