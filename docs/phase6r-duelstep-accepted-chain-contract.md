# Phase 6-R — `DuelStep` 행동 접수 및 체인 해결 결과 계약 정합성 개선

작업 브랜치: `claude/pensive-goodall-te1egy`
시작 HEAD: `7cc351d` (Phase 6-Q 마지막 commit)
바꾼 생산 파일: **`engine/duel.py` 하나**

> **먼저 §2 의 전제를 정정한다.** 지시문 §2 가 "체인 링크가 생성됐는데
> `DuelStep.accepted=False` 가 반환된다" 라고 적었다. **그 현상은 재현되지
> 않는다** — 체인 링크를 만든 걸음은 체인 1 이든 체인 2 든 언제나
> `accepted=True` 다. 거짓 실패는 **발동이 아니라 그 체인을 푸는 패스**에서
> 났고, 그 자리에 **더 깊은 상태 오염**이 같이 있었다. 지시문 §2 가 스스로
> 요구한 대로 ("먼저 실제 코드를 분석하고 해당 현상을 독립적으로 재현해야
> 한다") 재어서 정정한다. 근거는 §3 · §4 에 있다.

---

## 1. 기존 `DuelStep` 과 `accepted` 의 정의

`engine/duel.py` 의 `DuelStep` 은 **다섯 칸**짜리 불변 dataclass 다.

```python
@dataclass(frozen=True, slots=True)
class DuelStep:
    """행위 하나를 적용한 결과. **불변**이다."""
    action: PlayerAction
    accepted: bool
    code: ValidationCode
    reason: str
    result: "DuelResult | None" = None

    def __bool__(self) -> bool:
        return self.accepted
```

🔴 **6-R 전까지 `accepted` 에 설명이 한 줄도 없었다.** 클래스 docstring 의
"행위 하나를 적용한 결과" 가 전부였고, `code` 에도 설명이 없었다. 그 공백이
이 Phase 가 고친 혼동의 직접 원인이다 — 뜻이 적혀 있지 않으면 자리마다 다른
뜻으로 쓰이고, 실제로 그렇게 되어 있었다.

### `accepted` 를 **설정하는** 자리 (실측, 변경 전 HEAD `7cc351d`)

| 자리 | 값 | 무엇을 뜻했는가 |
|---|---|---|
| `Duel.apply` 첫 관문 | `False` | `action not in legal.allowed` — 후보가 아니다 |
| `Duel.apply` dispatch 없음 | `False` | 그 종류를 `Duel` 이 처리하지 않는다 |
| `_apply_activation` (관문 거절) | `False` | 발동 관문 셋 중 하나가 거절했다 |
| `_apply_activation` (체인 등록) | **`True`** | 체인 링크를 만들었다 |
| `_apply_pass` → 기회만 넘김 | `True` | 우선권을 넘겼다 |
| `_apply_pass` → `_resolve_chain`, 전부 해결 | `True` | 체인이 다 풀렸다 |
| 🔴 `_apply_pass` → `_resolve_chain`, 링크 불발 | **`False`** | **링크 하나가 안 풀렸다** |
| 실행기 경로 | 실행 상태 | `ActionStatus` 를 따른다 |

마지막 줄 하나가 **다른 질문에 답하고 있었다.** 다른 일곱 줄은 전부 "이
행위를 수락했는가" 인데, 그 줄만 "해결 결과가 전부 성공이었는가" 다.

### 6-R 이 적어 넣은 뜻

`accepted` 는 **"이 행위를 수락했는가"** 하나만 말한다. 세 가지가 서로 다른
사실이고, 각각 자기 자리가 있다.

| 사실 | 어디가 말하는가 |
|---|---|
| 행위 수락 | `DuelStep.accepted` |
| 체인 등록 | `Duel.chain` (`links` · `resolved_count`) |
| 효과 해결 · 상태 변경 | `EventJournal` 의 `EffectEvent` · `GameState` |

`code` 는 그 걸음의 **이유 코드**다. `accepted` 가 참이면 보통
`ValidationCode.OK` 이지만, **체인을 푼 패스에서 링크가 불발되면 그 사유
코드**가 온다 — 두 사실을 함께 전하는 자리다.

---

## 2. `accepted` 를 사용하는 모든 주요 호출자 (실측)

`grep -rn "\.accepted\b"` 를 생산 코드 전체(`engine` `agent` `app` `core`
`analysis` `rules` `rulings` `sources` `scripts`)에 돌린 결과다.

| 파일:줄 | 코드 | 거짓 실패가 무엇을 하는가 |
|---|---|---|
| `engine/duel.py:225` | `return self.accepted` | `bool(step)` 이 거짓이 된다 |
| `agent/runner.py:201` | `if not decision.accepted:` | 정책 판정 쪽 (적용 전) |
| `agent/runner.py:210` | `applied.accepted` 를 기록에 적는다 | 기록에 ✘ 가 남는다 |
| `agent/runner.py:283` | `if entry is not None and not entry.accepted: break` | 🔴 **`DuelRunner.run` 이 듀얼을 중단한다** |
| `agent/runner.py:124` | `refusals()` | 거부 목록에 들어간다 |
| `agent/simulation.py:285` | `if step.accepted:` → `SUPPORTED` | 🔴 적법한 수가 `REFUSED` 로 분류된다 |
| `agent/simulation.py:327` | `fork_after` → `if not step.accepted: return None` | 🔴 탐색 깊이가 끊긴다 |
| `agent/simulation.py:242` | `_settle_forced_passes` → `if not last.accepted: break` | 🔴 강제 패스 정산이 멈춘다 |
| `agent/arena.py:218 · 365` | 기록 전달 | 기록에 그대로 실린다 |
| `agent/policy.py:82` | `PolicyDecision.__bool__` | 정책 쪽 (다른 모델) |

### `/combo` 는 `accepted` 를 쓰지 않는다 (§4-E-1)

`app/` 전체에 `.accepted` 가 **0회**다. `/combo` 는 아직 `ComboPlanner` 쪽에
있고 실제 `Duel` 에 연결되어 있지 않다 — 그래서 이번 거짓 실패가 Discord
표시에 닿지는 않았다. 🔴 **그러나 Phase 6-S 가 연결하는 순간 닿는다**, 그리고
그것이 이 Phase 를 6-S 앞에 둔 이유다.

---

## 3. Phase 6-Q 체인 2 재현 결과

### 3-1. 결정적 구성 — 공식 규칙 그대로의 불발 하나

6-Q 의 관측은 임의 씨앗 산책에서 나왔으므로, 먼저 **손으로 구성한 결정적
판**으로 같은 현상을 재현했다 (`fizzling_chain` 헬퍼).

1. P0 의 덱을 **3장**으로 둔다.
2. P1 이 욕망의 선물(일반 함정, 5915629)을 **세트한다** (앞 턴).
3. P0 의 턴 — 욕망의 항아리(55144522)를 발동한다 → **체인 1**.
   이 시점 P0 덱은 3장이므로 발동은 적법하다.
4. P1 이 세트된 욕망의 선물을 발동한다 → **체인 2**.
5. 양쪽 패스 → **역순 해결**: 체인 2 가 먼저 풀려 P0 이 2장 뽑는다 (덱 1장).
6. 그래서 체인 1 의 "자신 DECK 에 2장 이상" 이 **거짓**이 된다 → 불발.

이것은 엔진의 결함이 아니라 **규칙대로의 불발**이다. 결함은 그 다음에 있다.

### 3-2. 단계별 실측 (고치기 전, HEAD `7cc351d`)

| 걸음 | 행위 | `ActionValidator` | `accepted` | `code` | 체인 링크 | 우선권 | 해결 | `GameState` | `EventJournal` |
|---|---|---|---|---|---|---|---|---|---|
| ① | `set_spell_trap` P1 | `OK` | `True` | `OK` | 0 | 닫힘 | — | SZONE +1 | `ACTION` |
| ② | `activate_effect` P0 욕망의 항아리 | `OK` | **`True`** | `OK` | **1** | 열림 | 아직 | 배치뿐 | `ACTION` |
| ③ | `activate_effect` P1 욕망의 선물 | `OK` | **`True`** | `OK` | **2** | 열림 | 아직 | 배치뿐 | `ACTION` |
| ④ | `PASS` P0 | — | `True` | `OK` | 2 | 열림 | 아직 | 없음 | 없음 |
| ⑤ | `PASS` P1 → 해결 | — | 🔴 **`False`** | `CANDIDATE_NOT_ELIGIBLE` | — | 닫힘 | 체인 2 만 | 드로우 2 · 묘지 2 | `EFFECT` ×1 |

② 와 ③ 이 **둘 다 `True`** 다. 그래서 §2 의 "체인 링크가 생성됐는데
`accepted=False`" 는 **이 엔진에서 일어나지 않는다.**

⑤ 의 이유 문자열 (실측 그대로):

```
체인1 P0 55144522:e[0] 를 해결하지 못했습니다: 발동 조건이 거짓입니다: 자신 DECK 에 2장 이상
```

### 3-3. 임의 씨앗 산책에서의 재현 (6-Q 가 본 자리)

`seed=303` · DIGEST 덱 (`통상몬스터×12 + 욕망의 항아리×4 + 욕망의 선물×4`),
`ACTIVATE_EFFECT` 를 우선 고르는 산책에서 **67번째 걸음**에 같은 현상이 난다.
그 자리의 체인은 링크 **3개**이고 (체인 1 · 2 · 3), 먼저 풀린 두 링크가 덱을
비워 체인 1 이 불발된다.

---

## 4. 실제 거짓 실패 발생 위치 — 그리고 🔴 **그 원인**

### 4-1. 두 결함, 그리고 어느 쪽이 원인인가

| | 결함 | 자리 |
|---|---|---|
| ① | **보고의 혼동** — `accepted` 하나가 "행위를 수락했는가" 와 "링크가 전부 해결되었는가" 를 함께 담았다 | `Duel._resolve_chain` 의 불발 분기 |
| ② | 🔴 **상태 오염 (원인)** — 체인을 `is_complete` 일 때만 비웠다 | `Duel._resolve_chain` 의 체인 갱신 |

고치기 전의 코드:

```python
resolution = loop.resolve(self.state, response, self._resolver)
self.chain = resolution.state.chain
self.priority = resolution.state.priority
if self.chain.is_complete:
    # 다음 발동이 체인 1 부터 시작하도록 비운다.
    self.chain = Chain()

self._retire_pending()

steps = resolution.steps
if not resolution.fully_resolved:
    last = steps[-1]
    return DuelStep(action, False, last.code, last.reason)   # ← ①
```

`ChainResolver.resolve_all` 은 **첫 번째 비해결 링크에서 멈추고 그 링크를
건너뛰지 않는다.** 그래서 링크 하나가 불발되면 `is_complete` 가 거짓이고,
**반쯤 풀린 체인이 영구히 남는다.**

### 4-2. ② 가 ① 을 낳는다 — 잠금의 정확한 자리 (실측)

남은 체인이 `ActivationTiming.chain_is_open` 을 참으로 고정한다. 그 뒤로
`Duel._activation_gate` 의 **둘째 관문**이 모든 스펠 스피드 1 발동을 거절한다.

`seed=303` · DIGEST 덱, 불발 직후의 자리에서 관문을 하나씩 물어본 결과:

| 측정 | 고치기 전 | 고친 뒤 |
|---|---|---|
| 체인 | `links=3 resolved=2 is_complete=False` | `links=0 resolved=0 is_complete=True` |
| `ActivationTiming.chain_is_open` | **`True`** | `False` |
| 관문 1 `ActionValidator` | `OK` ← **규칙은 허락한다** | `OK` |
| 관문 2 `ActivationTimingChecker` | 🔴 **`SPELL_SPEED_TOO_LOW`** | `OK` |
| 관문 합계 | `SPELL_SPEED_TOO_LOW` | `OK` |
| 이후 남은 턴 수 | 4 (턴 5 → 8) | 3 (턴 5 → 7) |
| 🔴 **이후 발동 후보 수** | **0건** | **4건** |
| 산책 끝 남은 체인 | 3 | 0 |

관문 2 의 이유 문자열 (실측):

```
스펠 스피드 1 로는 스펠 스피드 2 에 응수할 수 없습니다
(스펠 스피드 1 은 어떤 효과에도 응수할 수 없습니다).
```

🔴 **그리고 그 거절은 보류 목록에도 남지 않았다.** `_activation_actions` 가
관문에서 걸린 후보를 그냥 버리므로 `legal_actions().withheld` 에
`ACTIVATE_EFFECT` 항목이 **0건**이다. 호출자가 `apply` 로 직접 넣으면
`RULE_NOT_IMPLEMENTED` ("activate_effect 는 지금 허가된 행위가 아닙니다") 를
받는다 — 규칙이 금지하지 않는 것을 금지하고, 이유조차 말하지 않았다.

### 4-3. ①의 원인 분류 (§7)

§7 의 여덟 범주 중 **1번 (`accepted` 값 자체의 잘못된 계산)** 이다.
호출자는 `accepted` 를 "그 행위가 일어났는가" 로 **정확히** 읽고 있었다
(§2 의 표) — 틀린 것은 값이다. 2번(호출자의 오해)도 6번(변환 과정의 정보
손실)도 아니다: `code` 와 `reason` 은 불발 사유를 이미 정확히 들고 있었다.

②는 §7 의 **5번 (체인 링크 등록과 상태 동기화 문제)** 이고, 이쪽이 근본
원인이다.

---

## 5. 체인 등록과 체인 해결의 구분

### 5-1. 세 가지를 **같은 자리에서 따로** 물을 수 있다

| 질문 | 어디에 묻는가 | 실측 (불발 시나리오) |
|---|---|---|
| 행위 요청이 유효했는가 | `ActionValidator.validate(...).code` | `OK` |
| 행위가 접수되었는가 | `DuelStep.accepted` | `True` (다섯 걸음 전부) |
| 체인 링크가 등록되었는가 | `len(Duel.chain.links)` | 1 → 2 |
| 체인이 해결되었는가 | `Chain.resolved_count` · `is_complete` | 2 중 1 (체인 2 만) |
| 그 효과가 적용되었는가 | `EventJournal` 의 `EffectEvent` | **`5915629:e[0]` 하나** |
| 상태가 바뀌었는가 | `GameState` | P0 덱 3→1 · 패 1→2 |

### 5-2. 기록이 그 셋을 가른다 (실측, 불발 시나리오 · `my_deck=3`)

```
 0 ACTION set_spell_trap    actor 1  []                      deltas 1
 1 ACTION activate_effect   actor 0  []                      deltas 1   ← 체인 1 등록
 2 ACTION activate_effect   actor 1  []                      deltas 1   ← 체인 2 등록
 3 EFFECT 5915629:e[0]      actor 1  [OperationKind.DRAW]    deltas 2   ← 체인 2 적용
 4 ACTION activate_effect   actor 0  []                      deltas 1   ← 놓인 마법 묘지로
 5 ACTION activate_effect   actor 1  []                      deltas 1   ← 놓인 함정 묘지로
```

🔴 **체인 1 (`55144522:e[0]`) 의 `EffectEvent` 가 없다.** "해결했다" 고
적지 않는 규율은 이 기록이 지킨다 — `accepted` 가 아니다.

### 5-3. 등록만으로 적용을 주장하지 않는다

발동만 하고 멈춘 자리에서 P0 의 덱은 **한 장도 줄지 않는다**
(`test_c02`). 욕망의 항아리는 2장 뽑는 카드이므로, 이 자리에서 패가 늘면
그것이 거짓 성공이다.

---

## 6. `PASS` 와 우선권 처리 결과

### 6-1. 🔴 `PASS` 는 **열린 응답 창에서만** 후보가 된다 (실측)

빈 메인 페이즈에서 `legal_actions` 가 내놓는 "넘기기" 는 `END_PHASE` 이고
`PASS` 는 **없다** (`test_b02`). `PASS` 는 `priority.is_open and
priority.holds(seat)` 일 때만 나온다 (`Duel._flow_actions`).

이 사실이 이번 수정의 안전 근거의 절반이다 — 체인을 푸는 자리에 **창 없이
닿을 수 없다.**

### 6-2. 같은 체인에 패스가 둘 나고, 둘은 다른 일을 한다

| | 행위 | `accepted` | `code` | `reason` | 체인 |
|---|---|---|---|---|---|
| 첫 패스 | `PASS` (상대) | `True` | `OK` | `우선권을 넘겼습니다.` | 그대로 2 |
| 둘째 패스 | `PASS` (발동한 쪽) | `True` | `OK` 또는 불발 코드 | `체인1 … 해결…` | **비워진다** |

둘을 가르는 것은 `reason` 과 체인 상태이고 **`accepted` 가 아니다** —
`accepted` 는 둘 다 참이다 (§3-13 "반대로 합법적인 PASS 행동을 무조건
실패로 처리하지 않는다").

### 6-3. 역순 해결 (덱 5장 — 둘 다 해결되는 판)

기록의 순서가 사실이다 (`test_g01`):

```
['5915629:e[0]', '55144522:e[0]']     ← 체인 2 → 체인 1
```

P0 은 **네 장** 뽑는다 (덱 5 → 1, 패 0 → 4).

---

## 7. `GameStack` 및 `Outcome` 일관성 (§10 · STRUCTURAL-36)

### 7-1. 🔴 이 저장소에 `GameStack` 이라는 이름은 **없다**

지시문의 `GameStack` 에 해당하는 것은 `engine/chain.py` 의 `Chain` 이고,
`Duel.chain` 한 칸이 그것을 들고 있다. `Outcome` 에 해당하는 것은
`engine/timing.py` 의 `TimingOutcome` 이다.

### 7-2. STRUCTURAL-36 은 **이 경로에 없다**

| 측정 | 결과 |
|---|---|
| `TimingOutcome` 을 쓰는 생산 파일 | **`engine/timing.py` 하나** |
| `engine/duel.py` 가 `engine.timing` 을 import 하는가 | **아니다** |
| `Duel` 이 `TimingOutcome.chain` 을 채택하는가 | **아니다** |

`Duel` 은 `ResponseLoop` → `ChainResolver` 를 직접 쓴다. 그래서 **두 구조가
어긋날 자리가 없다** — 진실 원천은 `Duel.chain` 하나이고, STRUCTURAL-36
(TRIGGER 타이밍 계층의 준비된 체인에 채택 주체가 없다) 은 그대로 남는다.
§10 이 "두 구조가 다르다면 무조건 하나로 덮어쓰지 않는다" 라고 적었고,
**덮어쓸 두 구조가 애초에 없었으므로** 이 Phase 는 STRUCTURAL-36 을
건드리지 않았다.

### 7-3. §10 의 여섯 상황별 체인 상태 (실측)

| 상황 | `links` | `resolved_count` | `is_complete` | 우선권 |
|---|---|---|---|---|
| 1 링크 등록 직후 | 1 | 0 | 거짓 | 열림 |
| 2 링크 둘 등록 | 2 | 0 | 거짓 | 열림 |
| 3 한쪽 패스 | 2 | 0 | 거짓 | 열림 |
| 4 양쪽 패스 → 해결 | **0** | 0 | 참 (빈 체인) | 닫힘 |
| 5 해결 직후 (전부 성공) | **0** | 0 | 참 | 닫힘 |
| 6 해결 직후 (링크 불발) | **0** | 0 | 참 | 닫힘 |

5 와 6 이 같은 모양인 것은 의도다 — **그 체인은 끝났다.** 무엇이
적용되었는지의 차이는 `EventJournal` 과 `GameState` 에 있다 (§5-2).

---

## 8. 선택한 최소 수정 방식과 다른 대안

### 8-1. 네 대안 비교 (§8)

| 대안 | 내용 | 판단 |
|---|---|---|
| **A** | `accepted` 값의 계산 오류 수정 | 🟢 **채택** — ②(상태 오염)와 ①(값)이 둘 다 계산 오류다 |
| **B** | 결과 모델의 정보를 올바르게 전달 | 불필요 — `code`·`reason` 이 이미 불발 사유를 정확히 들고 있었다 (§4-3) |
| **C** | 외부 호출자의 해석 수정 | 불필요 — 호출자 열 자리가 `accepted` 를 "그 행위가 일어났는가" 로 **정확히** 읽고 있었다 (§2) |
| **D** | 별도 결과 정보 추가 (새 칸·새 enum) | ❌ **쓰지 않았다** — §8 이 "공유 계약 변경이므로 즉시 구현하지 않는다" 고 적었고, A 로 해결되었으므로 필요가 없다 |

### 8-2. 왜 A 인가 — ②가 ①의 원인이기 때문이다

①만 고치면 (`accepted` 를 참으로 바꾸면) 남은 체인이 그대로 남아 **발동
후보가 계속 0건**이다. ②를 고치면 ①은 "링크 불발을 어떻게 보고하는가" 의
문제로 줄어든다. 그래서 ②를 먼저 고치고, ①은 그 결과를 `code`·`reason` 으로
옮기는 것으로 끝난다.

### 8-3. 🔴 §16 이 금지한 패치가 **아니라는** 근거

> §16: "단순히 `accepted=True` 를 반환하도록 바꾸는 패치는 금지한다."

| 금지된 것 | 이번 수정 |
|---|---|
| `accepted=True` 만 돌려주고 끝 | `code` 가 `ValidationCode.OK` 가 **아니다** (`CANDIDATE_NOT_ELIGIBLE`) |
| 불발을 숨긴다 | `reason` 이 "해결하지 못했습니다: 발동 조건이 거짓입니다" 를 그대로 들고 간다 |
| "해결했다" 고 적는다 | `EventJournal` 에 불발 링크의 `EffectEvent` 가 **없다** |
| 원인을 안 고친다 | 근본 원인(②)을 고쳤고 그쪽이 주된 수정이다 |

`test_s04` 가 이것을 **AST 로** 센다 — 불발 분기 안에 `ValidationCode` 라는
이름이 **0회**다.

---

## 9. 공유 계약 변경 여부

### 9-1. 변경한 것 / 변경하지 않은 것

| | 변경? |
|---|---|
| `DuelStep` 의 필드 수와 이름 | **아니다** (`action` `accepted` `code` `reason` `result` 그대로 — `test_s01`) |
| `DuelStep.__bool__` | **아니다** (`return self.accepted`) |
| 새 enum · 새 모델 | **없다** (§5 "새로운 enum 이나 모델을 무조건 추가하지 않는다") |
| `ChainResolution.__bool__` | **아니다** (손대지 않았다) |
| `EventJournal` 의미론 | **아니다** (§3-11) |
| `PlayerAction` · `GameState` 의미론 | **아니다** (§3-2) |
| `Duel.apply` · `Duel.advance` 호출 계약 (시그니처) | **아니다** (§3-8) |
| 체인 · 우선권 계층 | **아니다** (`ResponseLoop` · `ChainResolver` 그대로) |
| `Chain` · `ChainLink` | **아니다** |
| 🔴 **한 경로에서 `accepted` 가 돌려주는 값** | **그렇다** — 체인을 푼 패스에서 링크가 불발된 경우 `False` → `True` |
| 🔴 `accepted` · `code` 의 **문서화된 뜻** | **그렇다** — 6-R 전까지 **적혀 있지 않았다.** 처음 적었다 |

### 9-2. 승인이 필요한가 — **아니다**

§8-D 가 승인을 요구하는 것은 "**명시적인 별도 결과 정보가 필요한 경우**",
즉 기존 공유 계약만으로 필수 상태를 구분할 수 없어 **칸이나 enum 을 더해야
하는 경우**다. 이번 수정은 칸을 더하지 않았고 (`test_s01`), 기존 세 칸
(`accepted` · `code` · `reason`) 과 기존 두 진실 원천 (`Duel.chain` ·
`EventJournal`) 으로 §5 의 여섯 상태(A~F)를 전부 구분한다 (§5-1 의 표).
그래서 이것은 대안 **A** 이고, 승인 대기 상태가 아니다.

🔴 **다만 숨기지 않고 적는다**: `accepted` 가 한 경로에서 돌려주는 **값**이
바뀌었고, 그것을 읽는 호출자가 열 자리 있다. 그 열 자리를 §2 에서 전부
열거했고, 각각이 새 값으로 무엇을 하는지 §15 에서 실측으로 검증했다. 이 변경
범위가 사용자의 판단과 다르다면 알려 주시면 되돌리거나 다시 설계한다.

---

## 10. 변경한 파일과 함수

### `engine/duel.py` (+92 −7) — **생산 파일은 이것뿐이다**

| 자리 | 변경 |
|---|---|
| `DuelStep.accepted` | 🔴 설명 추가 — 세 사실의 구분, "적법한 `PASS` 는 언제나 수락" |
| `DuelStep.code` | 설명 추가 — 불발 사유가 오는 자리 |
| `Duel._resolve_chain` | 🔴 **체인을 조건 없이 비운다** · 불발 분기가 `accepted=True` · `result=self._check_end()` 추가 |
| `Duel._apply_pass` | docstring 에 "적법한 패스는 언제나 수락이다" 추가 |
| `Duel._apply_activation` | ④ docstring 정정 — "해결했다고 적지 않는다" 를 `accepted=False` 로 적으면 패스를 거절한 것이 된다 |

고친 뒤의 `_resolve_chain` 핵심:

```python
resolution = loop.resolve(self.state, response, self._resolver)
self.priority = resolution.state.priority

self.chain = Chain()          # 🔴 조건 없이. 그 체인은 끝났다
self._retire_pending()

steps = resolution.steps
last = steps[-1]
if not resolution.fully_resolved:
    return DuelStep(
        action, True, last.code, last.reason, result=self._check_end()
    )
return DuelStep(
    action, True, ValidationCode.OK, last.reason, result=self._check_end(),
)
```

### 비우기가 안전한 두 근거 (코드로 센다)

1. **`_resolve_chain` 의 호출자가 하나뿐**이고 (`_apply_pass` — `test_s05` 가
   AST 로 센다), 그것은 **열린 창**을 요구한다 (§6-1).
2. `ResponseLoop.resolve` 가 `AFTER_CHAIN_RULE` 로 기회를 **닫는다** — 그
   체인은 다시 풀릴 수 없다.

### 바꾼 테스트 파일 (생산 파일이 아니다)

| 파일 | 변경 |
|---|---|
| `tests/engine/test_duelstep_accepted_contract.py` | **새 파일** — 45개 |
| `tests/test_legal_action_engine_boundary_audit.py` | `test_03` 재작성 (§17-2단계) |
| `tests/test_rule_not_implemented_code_audit.py` | 산문 등장 수 86→87 · 산문 자리 14→15 |
| `tests/test_unimplemented_rule_semantics_audit.py` | 산문 등장 수 86→87 |

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0.

### ADR 약속 유지

`engine/duel.py` 의 import 를 AST 로 세어 `engine.effect` 와 `rules` 가
**0회**임을 확인했다 (`test_s06`) — ADR-007 이 그대로다.

---

## 11. 정상 행동 · 거절 행동 테스트

`tests/engine/test_duelstep_accepted_contract.py` — **45개, 전부 통과**.
§11 의 시나리오 A~Q 를 절로 나눠 담았다.

| 절 | §11 | 수 | 내용 |
|---|---|---|---|
| A | A | 2 | 불법 행동 — 거절이 거절로 남고 판도 체인도 기록도 안 움직인다 |
| B | B | 2 | 비체인 행동 — 세트는 `OK`·체인 없음·`ACTION` 만 기록 / 🔴 `PASS` 는 창에서만 후보 |
| C | C | 2 | 체인 1 — 수락 · 링크 1 · `EffectEvent` 0 · 덱 그대로 |
| D | D | 2 | 체인 2 — 양쪽 발동 수락 · 링크 둘이 쌓인다 |
| E | E | 2 | 체인 대기 — 한쪽 패스에 체인이 남는다 · 창에서는 응답만 나온다 |
| F | F | 2 | 패스 둘이 모두 수락 · 체인 없는 패스는 "해결" 을 말하지 않는다 |
| G | G | 1 | 역순 해결 — 기록 순서 `[체인2, 체인1]` · 네 장 드로우 |
| H | H | 6 | 🔴 불발 — 수락 · 코드 ≠ `OK` · `EffectEvent` 없음 · 체인 비워짐 · 다음 발동 가능 · 관문 2 가 `OK` · `result` 가 끝을 들고 온다 |
| I | I | 1 | 미지원 효과 (`executable=False`) — 후보 0 · 직접 넣으면 거절 · 기록 없음 |
| J | J | 2 | `GameState` — 덱 3장/5장의 차이가 정확히 체인 1 의 적용 여부뿐 |
| K | K | 3 | `EventJournal` — `ACTION` 5 · `EFFECT` 1 · 전부 delta 있음 · 중복 0 |
| L | L | 1 | 기존 마법 — 욕망의 항아리 단독 해결 |
| M | M | 2 | 기존 함정 — 6-Q 의 일반 함정 유지 · **세운 턴 제약도 유지** |
| N | N | 1 | 어니스트 — 6-L 기동 효과가 MZONE 에서 발동·해결 |
| O | O | 1 | 다중 대상 — 6-P 의 벌금, 조합 3개 · 정확히 2장 |
| P | P | 4 | 호출자 — `Simulator` · `fork_after` · `DuelRunner` · 발동 우선 산책 |
| Q | Q | 2 | 복수 `Duel` — 체인과 기록이 섞이지 않는다 |
| R | §12 | 3 | 거짓 성공·거짓 실패를 둘 다 센다 |
| S | — | 6 | 계약의 자리 — 칸 수 · 설명 · AST · 호출자 수 · import |

---

## 12. 체인 1 · 체인 2 및 역순 해결 테스트

| 시험 | 측정 |
|---|---|
| `test_c01` | 체인 1 등록 → `accepted=True` `code=OK`, `links=1` `resolved_count=0`, `EffectEvent` 0건 |
| `test_d01` · `test_d02` | 체인 2 등록 → 양쪽 `accepted=True`, `links=2` `resolved_count=0` |
| `test_e01` | 한쪽 패스 후 `links=1` 유지 · 창 열림 |
| `test_f01` | 패스 둘 모두 `accepted=True`, 하나는 `우선권을 넘겼습니다.`, 하나는 `해결했습니다` |
| `test_g01` | 기록 순서 `['5915629:e[0]', '55144522:e[0]']` — 체인 2 먼저 |
| `test_h01` | 불발 → `accepted=True` `code=CANDIDATE_NOT_ELIGIBLE` |
| `test_h03` | 불발 후 `chain.is_empty` · `resolved_count=0` |
| `test_h04` · `test_h05` | 불발 후 스펠 스피드 1 발동이 다시 후보가 되고 관문 2 가 `OK` |

---

## 13. `GameState` 및 `EventJournal` 결과

| 측정 | 덱 3장 (불발) | 덱 5장 (전부 해결) |
|---|---|---|
| P0 덱 | 3 → **1** | 5 → **1** |
| P0 패 | 1 → **2** | 1 → **4** |
| P0 묘지 | `[55144522]` | `[55144522]` |
| P1 묘지 | `[5915629]` | `[5915629]` |
| `EffectEvent` | `['5915629:e[0]']` | `['5915629:e[0]', '55144522:e[0]']` |
| `ACTION` 사건 | 5 | 5 |

🔴 **불발이어도 놓인 마법은 묘지로 간다** (RULE-SPELLTRAP-002) — 발동은
성립했고, 해결되지 않은 효과의 카드가 묘지로 가는 것이 규칙이다. 그래서 두
칼럼의 묘지가 같고, 다른 것은 드로우뿐이다.

`EffectEvent` 는 전부 `applied` 와 `deltas` 를 들고 있고 (`test_k02`),
같은 참조가 두 번 나오지 않는다 (`test_k03`).

---

## 14. 기존 마법 · 함정 · 몬스터 효과 회귀

| 기능 | Phase | 측정 |
|---|---|---|
| 통상 마법 (욕망의 항아리) | 3-E | 발동 → 패스 둘 → 해결, 덱 −2 · 패 +2 |
| 일반 함정 (욕망의 선물) | **6-Q** | 세트 → 다음 턴 → 발동 → 해결, 상대 패 +2 |
| 세운 턴 제약 | 6-Q | 세운 턴에는 발동 후보 **0건** (느슨해지지 않았다) |
| 기동 효과 (어니스트) | **6-L** | MZONE 에서 발동 → 해결, 자기 자신이 패로 |
| 다중 대상 (벌금) | **6-P** | 조합 **3개** · 각 **2장** · 패 −2 · 묘지에 통상 몬스터 2 + 함정 1 |
| 미지원 효과 (로스트) | — | `executable=False` → 후보 0 · 직접 넣으면 `accepted=False` |

`tests/engine` **전체 재실행**이 이 회귀의 본체다 (§17).

---

## 15. Agent / Runner 호출자 회귀

| 호출자 | 고치기 전 | 고친 뒤 |
|---|---|---|
| `Simulator.simulate` (불발 패스) | `REFUSED` · `future=None` | 🔴 `SUPPORTED` · `future` 있음 · `code=CANDIDATE_NOT_ELIGIBLE` |
| `Simulator.fork_after` (불발 패스) | `None` | 🔴 `Simulator` |
| `DuelRunner.run` 6판 (seed 401~406) | 결정 **585** · 거부 **1건** → 듀얼 중단 | 결정 **595** · 거부 **0건** |
| 발동 우선 산책 6판 (seed 303~305 × 2덱) | 거부 **2건** (전부 `PASS`) | 거부 **0건** |

🔴 `DuelRunner` 의 거부 1건이 이 결함의 실제 피해다 — `run` 이
`if entry is not None and not entry.accepted: break` 로 **듀얼을 중단**했다.

`Simulator` 쪽은 `SUPPORTED` 로 분류되지만 `code` 가 `OK` 가 아니므로
불발이 숨겨지지 않는다 (`test_p01`).

---

## 16. 거짓 성공 · 거짓 실패의 전후 비교

### 16-1. §13 의 열세 지표 (실측)

같은 측정 스크립트를 HEAD `7cc351d` 의 `engine/duel.py` 와 고친 판에서 각각
돌렸다. 🔴 `git checkout` 을 쓰지 않았다 — 작업 트리의 파일을 **메모리에
들고** HEAD 판을 잠깐 써 넣은 다음 되돌리고 바이트가 같은지 `assert` 했다.

측정 범위: `walk_duel` 6판 (seed 303·304·305 × DIGEST·SPELL 덱,
`ACTIVATE_EFFECT` 우선) + `DuelRunner` 6판 (seed 401~406, `search_policy`).

| § | 지표 | 전 | 후 | 차이 |
|---|---|---|---|---|
| 1 | 합법적 발동 요청 수 (후보) | 343 | **347** | +4 |
| 2 | 정상 접수된 행동 수 | 642 | 642 | 0 |
| 3 | 체인에 등록된 링크 수 | 120 | **123** | +3 |
| 4 | 🔴 `accepted=False` 로 잘못 보고된 접수 행동 | **2** | **0** | **−2** |
| 5 | `accepted=True` 로 잘못 보고된 거절 행동 | 0 | 0 | 0 |
| 6 | 정상 체인 해결 사례 수 | 101 | 101 | 0 |
| 7 | 불발 걸음 수 | 2 | **3** | +1 |
| 8 | 🔴 산책 끝 남은 체인 | **6** | **0** | **−6** |
| 9 | 기존 어니스트 실행 | 유지 | 유지 | — |
| 10 | 기존 일반 함정 발동 | 유지 | 유지 | — |
| 11 | 기존 다중 대상 처리 | 유지 | 유지 | — |
| 12 | 🔴 Agent/Runner 가 결과를 잘못 해석한 사례 | **1** (듀얼 중단) | **0** | **−1** |
| 13 | 남아 있는 구조적 BLOCKER | §18 | §18 | — |

**지표 7 이 늘어난 것이 결함이 아니다** — 고치기 전에는 첫 불발이 체인을
잠가서 **그 뒤로 체인이 더 만들어지지 않았다.** 잠금이 풀리니 체인이 3개 더
생기고 (지표 3) 그 중 하나가 또 불발된다. 불발은 규칙대로의 일이다.

### 16-2. 🔴 실제 실행 가능한 카드 효과 수의 증가

**0건이다.** 이 Phase 는 새 효과를 등재하지 않았고, 새 조작도 새 조건도
만들지 않았다. 늘어난 것은 **같은 효과를 실제로 발동할 수 있는 자리**이고
(지표 1: +4, 지표 3: +3), 줄어든 것은 **잘못된 판정**이다 (지표 4·8·12).

§13 이 적은 대로 이것을 "증가 0건" 으로 기록한다.

### 16-3. §12 의 열두 가지 오류 검사 (전부 실측)

| 오류 | 측정 | 결과 |
|---|---|---|
| 체인 링크가 생성됐는데 거절로 반환 | `test_c01` · `test_d01` · `test_r01` | 🔴 **0건** (전 2건) |
| 불법 행동이 체인 링크로 등록 | `test_a01` | 0건 |
| 발동 접수만 됐는데 해결 성공 표시 | `test_c01` · `test_c02` | 0건 |
| 효과가 불발됐는데 상태 변경 성공 표시 | `test_h02` | 0건 |
| `PASS` 를 실패한 행동으로 처리 | `test_f01` · `test_h01` · `test_p04` | 🔴 **0건** (전 2건) |
| `PASS` 만으로 해결됐다고 표시 | `test_f02` | 0건 |
| 체인에 없는 링크를 해결한 것으로 보고 | `test_r03` | 0건 |
| 체인 링크 중복 등록 | `test_r03` (`Chain.push` 가 `ChainError`) | 0건 |
| 동일 효과 중복 해결 | `test_k03` | 0건 |
| 실제 delta 없는데 적용 이벤트 기록 | `test_k02` | 0건 |
| `GameState` 와 `EventJournal` 불일치 | `test_j01` · §13 의 표 | 0건 |
| 외부 AI 가 거짓 실패로 같은 행동을 반복 | `test_p03` (`DuelRunner` 3판 거부 0) | 🔴 **0건** (전 1건 중단) |

### 16-4. 변이 시험 — **내 코드에 변이를 넣고 내 시험이 잡는지**

`engine/duel.py` 의 6-R 변경에 변이 **11개**를 하나씩 넣고
`tests/engine/test_duelstep_accepted_contract.py` 를 돌렸다. 변이가 적용된
동안 다른 테스트를 돌리지 않았고, 끝나고 원본과 바이트가 같은지 `assert`
했다.

| 변이 | 결과 |
|---|---|
| M1 체인을 예전처럼 해결 결과에서 받아온다 | 죽었다 |
| M2 체인을 아예 비우지 않는다 | 죽었다 |
| M3 체인을 `is_complete` 일 때만 비운다 (**6-Q 의 코드 그대로**) | 죽었다 |
| M4 불발 분기가 `accepted=False` 를 돌려준다 (**예전 코드**) | 죽었다 |
| M5 불발 분기가 `code` 를 `OK` 로 덮어쓴다 | 죽었다 |
| M6 불발 분기가 이유를 버린다 | 죽었다 |
| M7 불발 분기가 끝을 보지 않는다 (**예전 코드**) | 죽었다 |
| M8 불발 조건을 뒤집는다 | 죽었다 |
| M9 `accepted` 설명에서 "체인 등록" 을 지운다 | 죽었다 |
| M10 체인을 비우는 자리를 불발 분기 안으로 옮긴다 | 죽었다 |
| M11 우선권을 갱신하지 않는다 | 죽었다 |

**11개 중 11개를 잡았다.** M3·M4·M7 은 고치기 전의 실제 코드이므로,
이 시험이 **되돌림을 막는다**.

---

## 17. 타깃 · 통합 · 최종 회귀 테스트 결과

(실행 명령과 수는 §19 의 실행 기록에 그대로 있다)

### 1단계 — 타깃 · 통합

```
python3 -m pytest tests/engine/test_duelstep_accepted_contract.py -q -p no:randomly
45 passed in 12.54s                                        exit 0
```

이 파일이 타깃(§14-1단계: `DuelStep` · `accepted` · `apply` · `advance` ·
`PASS` · 체인 등록 · `ActionValidator`)과 통합(§14-2단계: 체인 1·2 · 발동 후
대기 · 양쪽 패스 · 역순 해결 · `GameState` · `EventJournal` · 기존 마법·함정·
몬스터)을 같이 담는다 — 같은 판 위에서 재야 세 사실의 구분이 의미를 갖기
때문이다.

### 2단계 — 움직인 기존 핀 **하나**

`tests/test_legal_action_engine_boundary_audit.py::test_03_everything_offered_is_actually_executed`

🔴 **이 핀은 6-Q 가 결함을 "재어서 남긴" 자리다.** 6-Q 의 주석이 이렇게
적었다.

> "6-Q 는 이것을 고치지 않았고 (공유 계약 변경), **재어서 남긴다.**
> 고쳐지면 이 단언이 깨지고 그때 §19-4 를 다시 읽게 된다."

**왜 기존 테스트가 잘못된 가정을 갖고 있었는가** (§14 가 요구한 기록):

6-Q 는 두 가지를 전제했고 **둘 다 이 자리에는 해당하지 않았다.**

1. "`DuelStep.accepted` 의 의미를 바꾸는 것이 공유 계약 변경이다" —
   돌아가는 걸음의 행위는 **`PASS`** 이고, `accepted` 가 답하는 질문은 "그
   패스가 일어났는가" 다. 그 패스는 일어났다. 의미를 **바꾼** 것이 아니라,
   그 자리의 값이 **다른 질문에 답하고 있던 것**을 고쳤다 (§1 의 표).
2. "`ChainResolution.__bool__` 이 참·거짓을 거부하므로 뒤집을 수 없다" —
   `ChainResolution` 은 손대지 않았다. 불발 사유는 `code`·`reason` 에 그대로
   남으므로 "해결되지 않은 것이 조용히 성공으로 읽히는" 일이 없다.

그리고 6-Q 가 ④로 남긴 체인 잔존이 **그 거짓 실패의 원인**이었다 (§4-2).

**바꾼 단언** (약화가 아니라 강화다):

| | 6-Q | 6-R |
|---|---|---|
| ① | `PASS` 를 뺀 거부가 0건 | **모든 종류의 거부가 0건** |
| ② | 거부된 `PASS` 의 이유가 불발을 가리킨다 | 수락된 `PASS` 의 `code` 가 `OK` 가 **아니다** |
| ③ | 그 자리에서 행위가 실제로 일어났다 | 같다 (유지) |
| ④ | 🔴 풀리지 못한 체인이 **남는다** | 🔴 체인이 **비워진다** + 스펠 스피드 1 발동이 다시 가능하다 |
| — | — | **추가**: 여섯 산책 끝 남은 체인 합계 `0` (전 `6`) |

삭제 0 · skip 0 · assertion 약화 0 · threshold 완화 0.

```
python3 -m pytest tests/test_legal_action_engine_boundary_audit.py -q -p no:randomly
30 passed in 38.22s                                        exit 0
```

### 2단계 — 움직인 기존 핀 **둘 더** (산문 등장 수)

루트 회귀가 두 파일을 더 깨뜨렸고, **둘 다 같은 원인**이다.

| 파일 | 단언 | 전 | 후 |
|---|---|---|---|
| `tests/test_rule_not_implemented_code_audit.py::test_02` | `STRING_OCCURRENCES` | 86 | **87** |
| 같은 파일 `test_02` | `len(PROSE_OCCURRENCES) == 14` | 14 | **15** |
| `tests/test_unimplemented_rule_semantics_audit.py::test_03` | `RULE_NOT_IMPLEMENTED_MENTIONS` | 86 | **87** |

**왜 늘었는가**: §4-2 의 실측을 `Duel._resolve_chain` 의 주석에 적으면서
`RULE_NOT_IMPLEMENTED` 라는 이름을 **인용했다** (`engine/duel.py:868`).
🔴 **코드 자리는 하나도 늘지 않았다** — 두 파일이 코드 수와 산문 수를 따로
세고 있고, 늘어난 쪽은 산문이다. `CODE_OCCURRENCES` 는 그대로다.

**이 두 핀이 틀린 가정을 갖고 있었던 것이 아니다** — 그 시점에 실제로
86개였다. 숫자 핀이 산문 하나에도 반응하도록 설계된 것이 의도이고
(6-E · 6-F · 6-H · 6-M 이 같은 이유로 갱신했다), 늘어난 자리에 **왜 그
이름이 거기 있는가**를 주석으로 적었다.

🔴 **그리고 그 인용은 이 두 감사가 지키는 구분의 증거이기도 하다.** 그
자리에서 돌아오던 `RULE_NOT_IMPLEMENTED` 는 "규칙 계층이 없다" 를 뜻하지
않았다 — 같은 자리에서 `ActionValidator` 는 `OK` 를 돌려주고 있었다 (§4-2 의
표). 즉 **그 코드가 거짓이었고**, 6-R 이 그 원인을 고쳤다.

### 3단계 — `tests/engine` 전체

부록의 실행 기록 참조.

### 4단계 — 관련 루트 회귀

`engine.duel` · `agent.runner` · `agent.simulation` · `agent.search` ·
`agent.arena` 중 하나라도 import 하는 루트 테스트 파일 **49개**를 전부
돌렸다. 부록의 실행 기록 참조.

---

## 18. 남아 있는 구조적 BLOCKER

이 Phase 가 **고친** 것:

- 🔴 **불발 링크가 든 체인이 영구히 남아 스펠 스피드 1 발동을 전부 막는
  결함** (6-Q 보고서 §19-4 의 깊은 쪽) — 고쳤다
- 🔴 **적법한 `PASS` 가 거짓 실패로 보고되는 결함** (6-Q §19-4 의 얕은 쪽) —
  고쳤다

이 Phase 가 **건드리지 않은** 것 (§15 가 범위 밖으로 둔 것들):

| BLOCKER | 상태 |
|---|---|
| STRUCTURAL-36 (`TimingOutcome.chain` 의 채택 주체 없음) | 그대로 — 🔴 **이 경로에 없다** (§7-2) |
| STRUCTURAL-34 의 나머지 (응답 창이 **누구에게** 가는가) | 그대로 |
| STRUCTURAL-35 (`TimingWindow` 가 사건 하나만 담는다) | 그대로 |
| TRIGGER 자동 발동 | 그대로 |
| `activate_card` · `special_summon` 의 규칙 계층 없음 | 그대로 (`withheld` 가 이유를 댄다) |
| 지속 함정의 필드 잔존 · 카운터 함정의 응답 타이밍 | 그대로 (`_OUT_OF_SCOPE_TYPES`) |
| 효과 사용 횟수 제한 · 전체 소환 조건 | 그대로 |
| 🔴 **관문에서 걸린 발동 후보가 `withheld` 에 남지 않는다** | **새로 기록한다** (§4-2) |

### 새로 기록하는 결함 — 조용한 보류

`Duel._activation_actions` 가 `_activation_gate` 에서 걸린 후보를 **이유 없이
버린다.** 그래서 `legal_actions().withheld` 에 `ACTIVATE_EFFECT` 항목이
0건이고, 호출자는 "발동할 것이 없다" 와 "발동이 지금 규칙상 안 된다" 를
가를 수 없다. 이번 결함을 진단하는 데 그 침묵이 직접 방해가 되었다 (실측:
잠긴 동안 `withheld` 에 아무것도 없었고 `apply` 는 `RULE_NOT_IMPLEMENTED` 를
돌려주었다 — 둘 다 거짓이다).

🔴 **이번에 고치지 않았다** — `withheld` 를 채우는 일은 `legal_actions` 의
공유 계약을 늘리는 일이고 (후보마다 보류 항목이 생기면 목록 크기가 바뀐다),
§15 가 "직접 차단 요인이 아닌 한 수정하지 않는다" 라고 적었다. 이번 결함은
그것 없이도 고쳤으므로 직접 차단 요인이 아니다. 다음 Phase 의 후보로 남긴다.

---

## 19. Phase 6-S `/combo` 연결의 최소 선행 조건

### 충족된 것

| 조건 | 상태 |
|---|---|
| 행동 결과를 신뢰할 수 있다 (거짓 실패 0) | 🟢 §16-1 지표 4 · 12 |
| 체인이 걸음 사이에 오염되지 않는다 | 🟢 §16-1 지표 8 |
| 접수 · 등록 · 해결 · 적용을 따로 물을 수 있다 | 🟢 §5-1 |
| 불발을 성공으로 읽지 않는다 | 🟢 §5-2 · §16-3 |
| `DuelRunner` 가 적법한 수에서 멈추지 않는다 | 🟢 §15 |
| 역순 해결이 기록에 남는다 | 🟢 §6-3 |

### 아직 충족되지 않은 것 — 🔴 **6-S 를 시작하기 전에 결정해야 한다**

1. **`/combo` 는 아직 `Duel` 에 연결되어 있지 않다.** `app/` 에 `.accepted`
   가 0회이고 `ComboPlanner` 는 `GameState` 를 만들지 않는다. 연결 자체가
   6-S 의 일이다.
2. **발동 후보의 조용한 보류** (§18) — `/combo` 가 "이 전개가 왜 막혔는가"
   를 말해야 하는데, 지금은 막힌 이유가 어디에도 없다. 6-S 가 이유를
   표시하려면 이것이 선행 조건이 된다.
3. **TRIGGER 자동 발동이 없다** — 전개 중간의 유발 효과가 체인에 올라가지
   않으므로 긴 콤보는 아직 현실과 다르다.
4. **등재된 효과가 다섯 장(함정) + 소수의 마법·몬스터뿐이다** — 전개를 보일
   수 있는 범위가 좁다. 6-S 는 "지원하지 않는 소환이나 효과는 UNKNOWN 또는
   UNSUPPORTED 로 표시한다" (§19) 를 지켜야 한다.

**평가**: 6-R 의 목표(§1-6, "6-S 에서 신뢰할 수 있는 행동 결과를 제공")는
달성되었다. 그러나 6-S 를 **그대로** 시작할 수는 없고, 위 2번(보류 이유)을
먼저 할지 1번(연결)부터 할지는 사용자의 판단이 필요하다.

---

## 20. 완료 수준

### 수준 3 — 실제 수직 실행 검증 **달성**

| §18 수준 3 항목 | 근거 |
|---|---|
| 실제 `Duel` 에서 적법한 체인 1 · 체인 2 를 생성한다 | §3-2 ② ③ · `test_d02` |
| 발동 요청 접수 결과를 정확하게 관찰한다 | §1 의 표 · §3-2 의 단계별 실측 |
| 두 플레이어의 `PASS` 와 체인 해결을 검증한다 | §6-2 · `test_f01` |
| 기존 `EffectExecutor` 를 통해 효과를 해결한다 | §5-2 의 `EffectEvent` |
| `GameState` 변경과 `EventJournal` 기록을 확인한다 | §13 |
| 기존 어니스트 및 일반 함정 실행이 유지된다 | §14 |
| 외부 호출자가 결과를 잘못 해석하지 않는다 | §15 |

**공유 계약 변경으로 승인을 기다리는 상태가 아니다** (§9-2) — 칸을 더하지
않았고 대안 A 로 해결했다. 다만 `accepted` 가 한 경로에서 돌려주는 **값**이
바뀌었다는 사실은 §9-1 에 숨기지 않고 적었다.

**다음 Phase 는 자동으로 시작하지 않는다.**

---

## 부록 — 실행 기록

모든 수는 `pytest` 의 **실제 종료 코드**와 마지막 줄을 그대로 적은 것이다
(§14 "pytest 의 실제 종료 코드를 사용한다").

### 1 · 2단계 — 타깃 · 통합

```
$ python3 -m pytest tests/engine/test_duelstep_accepted_contract.py -q -p no:randomly
45 passed in 12.54s
exit 0
```

```
$ python3 -m pytest tests/test_legal_action_engine_boundary_audit.py -q -p no:randomly
30 passed in 38.22s
exit 0
```

```
$ python3 -m pytest tests/test_rule_not_implemented_code_audit.py \
                   tests/test_unimplemented_rule_semantics_audit.py -q -p no:randomly
43 passed in 18.86s
exit 0
```

### 3단계 — `tests/engine` 전체

```
$ python3 -m pytest tests/engine -q -p no:randomly
3458 passed in 411.43s (0:06:51)
exit 0
```

| | 6-Q | 6-R |
|---|---|---|
| `tests/engine` | 3,413 | **3,458** (+45) |

늘어난 45개가 이 Phase 의 새 파일이다. 기존 3,413개 중 **하나도 깨지지
않았다** — 생산 변경은 `engine/duel.py` 한 파일이고, `tests/engine` 의 어떤
핀도 그 두 결함을 가정하고 있지 않았다.

### 4단계 — 관련 루트 회귀 (49파일)

`engine.duel` · `agent.runner` · `agent.simulation` · `agent.search` ·
`agent.arena` 중 하나라도 import 하는 루트 테스트 파일 전부다.

**첫 실행** (산문 핀 둘을 고치기 전):

```
$ python3 -m pytest $(cat rootset.txt) -q -p no:randomly
2 failed, 1203 passed in 1703.74s (0:28:23)
exit 1

FAILED tests/test_rule_not_implemented_code_audit.py::test_02_…
FAILED tests/test_unimplemented_rule_semantics_audit.py::test_03_…
```

둘 다 산문 등장 수 (86 → 87) 때문이다 — §17-2단계에 까닭을 적었다.
🔴 **먼저 단독으로 재실행해서 원인을 확인하고** (§14 의 실패 절차 1·2),
수를 정확한 값으로 고쳤다 (3·4), 그 다음 최종 회귀를 돌렸다 (5·6).

**최종 실행**:

```
$ python3 -m pytest $(cat rootset.txt) -q -p no:randomly
1205 passed in 1597.40s (0:26:37)
exit 0
```

**실패 0건.**

### 변이 시험

```
$ python3 scratchpad/mutate.py
=== 변이 11개 중 11개를 잡았다 ===
되돌림 확인: engine/duel.py 가 원본과 같다
```

### 전후 측정

```
$ python3 scratchpad/beforeafter.py
----- BEFORE (HEAD 7cc351d) -----   ----- AFTER (6-R) -----
METRIC 4  거짓실패_PASS = 2           METRIC 4  거짓실패_PASS = 0
METRIC 8  남은_체인   = 6            METRIC 8  남은_체인   = 0
METRIC 11 Runner_거부 = 1            METRIC 11 Runner_거부 = 0
되돌림 확인: engine/duel.py 가 작업 트리 판과 바이트가 같다
```

🔴 `git checkout` 을 쓰지 않았다 — 작업 트리의 파일을 메모리에 들고 HEAD
판을 잠깐 써 넣은 다음 되돌리고 바이트가 같은지 `assert` 했다. 변이가
적용된 동안 다른 테스트를 돌리지 않았다.

### 측정 환경

- 측정 날짜: 2026-10-16
- 시작 HEAD: `7cc351d` (Phase 6-Q 마지막 commit)
- 브랜치: `claude/pensive-goodall-te1egy`
- 무작위 순서 끄기: `-p no:randomly` (전 실행 공통)

---

## 부록 — Git 커밋

| commit | 내용 |
|---|---|
| `d2e8da9` | `engine/duel.py` — 끝난 체인을 비우고 적법한 패스를 수락으로 보고한다 |
| `65dacc5` | 테스트 — 새 파일 45개 + 움직인 기존 핀 셋 |
| (이 보고서) | `docs/phase6r-duelstep-accepted-chain-contract.md` |
