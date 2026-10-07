# Phase 3-F-20 — `Duel.advance()` 규칙 걸음 기록 계약 감사

## 0. Base 와 실제 HEAD

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-19 작업 commit | `9989c0061a76f6a4be34f18e89b4de92325bf585` — *Phase 3-F-19: audit ChainResolution replay boundary* | ✅ 존재 |
| Phase 3-F-19 보고서 commit | `8ba752660ee9c88f0e6f213d572149647fc923e8` — *Phase 3-F-19: document ChainResolution replay boundary audit* | ✅ 존재 |
| 작업 시작 시 실제 HEAD | `8ba7526` | ✅ 지시받은 Base 와 **일치** |
| 작업 트리 | 깨끗함 | — |

Phase 3-F-19 최종 판정 **B. CHAIN_RESOLUTION_SERIALIZATION_BOUNDARY_DOCUMENT_ONLY**
를 전제로 삼았다.

---

## 1. 핵심 질문과 답

> `Transcript.rule_steps` 가 **단순한 카운터인지**, 아니면 듀얼의 진행을 **재현할 수
> 있을 만큼의 authoritative 기록인지.**

**카운터다.** 그런데 "의미 없는 값" 이라는 뜻은 **아니다** — `MatchResult.canonical_state()`
가 "같은 대국인가" 를 비교할 때 쓰는 **결과 검증 metadata** 다.

§2 가 요구한 다섯 갈래 분류:

| 갈래 | 판정 |
|---|---|
| **A.** 내부 rule step 실행 횟수 counter | 🟢 **이것이다** — 다만 "`advance()` 호출 횟수" 가 아니라 **비None 반환 횟수**다 |
| **B.** 각 rule step 의 상세 실행 기록 | 🔴 아니다 — `int` 하나다 |
| **C.** 재실행 가능한 authoritative execution trace | 🔴 아니다 — 스칼라로는 불가능하다 |
| **D.** 디버깅/관찰용 기록 | 🟡 부분적으로 맞다 — `describe_ko()` 표시에 쓴다 |
| **E.** 여러 의미가 섞여 있음 | 🔴 아니다 — consumer 두 곳 모두 **"센 값"** 으로만 쓴다 |

A 와 D 가 둘 다 걸리지만, 실측한 consumer 는 **표시 하나 + 비교 하나**이고 둘
모두 같은 의미("몇 걸음이었나")로 쓴다. 섞여 있지 않다.

---

## 2. `Duel.advance()` 실제 구조 (AST)

🔴 **이름보다 훨씬 좁다.** 조건이 **하나**다.

```python
if self.is_over or self.step is not TurnStep.DRAW_PENDING:
    return None
```

`AST` 로 측정한 것:

| 측정 | 결과 |
|---|---|
| 가드 조건 | `TurnStep.DRAW_PENDING` 하나 |
| 판에 대고 부르는 것 | `draw` · `set_result` · `player` — **셋** |
| 그중 판을 **바꾸는** 것 | `self.state.draw(seat, 1)` · `self.state.set_result(...)` — **둘** |
| 읽기만 하는 것 | `self.state.player(seat).deck` (덱이 남았나) |
| 반복문 | **없다** |
| `TurnProgressor` 호출 | **없다** (페이즈 전환은 `change_phase` **행위**가 한다) |
| 실행기 · 체인 · 해결 | **없다** (`executor` · `_resolver` · `Chain` · `resolve` 전부 0) |
| `return` 문 | **셋** — `None` · 덱아웃 패배 · 드로우 |
| 난수 사용 | **없다** (`rng` · `random` · `shuffle` 0) |

§3 의 여섯 질문에 대한 답:

| # | 질문 | 답 |
|---|---|---|
| ① | 한 번의 `advance()` 가 정확히 무엇인가 | **드로우 페이즈의 드로우 한 장.** 그 밖에서는 아무 일도 없이 `None` |
| ② | 내부적으로 여러 engine step 이 실행될 수 있는가 | 🔴 **아니다.** 반복문이 없고 조건마다 즉시 `return` — 언제나 0 또는 1 |
| ③ | `rule_steps` 는 `advance()` 호출 횟수와 같은가 | 🔴 **아니다.** 비None 반환 횟수다(§4) |
| ④ | 하나의 `PlayerAction` 이 여러 rule step 을 소비할 수 있는가 | **아니다.** 규칙 걸음은 행위 **사이**에서 일어난다. 다만 `change_phase`→DRAW 가 `step = DRAW_PENDING` 으로 **하나를 예약**한다 |
| ⑤ | rule step 하나가 여러 state mutation 을 포함할 수 있는가 | 드로우 한 장 + `self.step` 전환. 덱아웃 경로는 `set_result` + 전환. **논리적으로 하나** |
| ⑥ | 실패한 action 도 rule step 으로 기록되는가 | 🔴 **아니다**(§6) |

### 🔴 `advance()` 가 돌려주는 `DuelStep.action` 은 **합성 PASS** 다

```python
return DuelStep(PlayerAction.passing(actor=seat), True, ValidationCode.OK, ...)
```

`DuelStep.action` 은 필수 칸이라 무언가 들어가야 하는데, 규칙 걸음에는 **고른 사람이
없다.** 그래서 턴 플레이어의 패스가 들어간다. 그 패스는 **합법 후보에 들어 있지
않았다** — 고를 수 있는 것이 아니다.

이것을 재현 입력으로 기록하면 **일어나지 않은 패스를 재생**하게 된다. `DuelRunner` 는
그 걸음을 `entries` 에 **넣지 않으므로** 실제로는 새지 않는다. (이 사실은 기존
`tests/test_trigger_ownership_audit.py` 가 이미 못 박고 있었다 — "영수증의 행위
종류는 `PASS` 다 — 누가 고른 것이 아니다".)

---

## 3. `Transcript` 구조

| 칸 | 타입 | 뜻 |
|---|---|---|
| `entries` | `tuple[TranscriptEntry, ...]` | 정책이 **고른** 결정들 (거부 포함) |
| `result` | `DuelResult \| None` | 승패 |
| `steps` | `int` | 결정 횟수 |
| **`rule_steps`** | **`int`** (기본값 0) | "고르지 않아도 일어난 일의 수 (드로우 따위)" |

칸은 **넷뿐**이고, `TranscriptEntry` 에는 규칙 걸음을 적을 칸이 **없다.**
`rule_steps` 는 구조화된 기록이 아니라 **스칼라**다.

---

## 4. 🟢 결정적 불변식 — `advance()` 호출 == `steps` + `rule_steps`

`DuelRunner._step` 은 **고를 것을 묻기 전에 먼저 `advance()`** 를 한다.

* 비None → `rule_steps += 1`, 결정은 **기록하지 않고** 즉시 돌아간다
* None → 정책에게 묻고 그 결정을 `entries` 에 **기록한다**

실측 (세 seed):

| seed | 비None | None | `rule_steps` | `steps` | 일치 |
|---|---|---|---|---|---|
| 51 | 6 | 57 | 6 | 57 | 🟢 |
| 52 | 10 | 93 | 10 | 93 | 🟢 |
| 53 | 10 | 91 | 10 | 91 | 🟢 |

즉 **`rule_steps` 는 호출 횟수가 아니다.** 한 판에서 `advance()` 는 197번 불릴 수
있는데 `rule_steps` 는 21 이었다 — 176번은 `None` 이었다. 둘을 섞으면 "규칙 걸음이
전체 진행량이다" 로 잘못 읽는다.

---

## 5. consumer 전수 조사

| 자리 | 읽기/쓰기 | 용도 |
|---|---|---|
| `agent/runner.py:187` | **쓰기 (유일)** | `self._rule_steps += 1` |
| `agent/runner.py:150` | 읽기 | `describe_ko()` — **표시 문자열** |
| `agent/arena.py:444` | 읽기 | `MatchResult` 로 옮긴다 |
| `agent/arena.py:206` | 읽기 | `MatchResult.canonical_state()` — **"같은 대국인가" 비교** |

* **쓰는 자리는 하나**다. 그래서 `rule_steps` 가 생기는 길도 하나다.
* 🔴 **`engine/` 계층에는 읽는 자리도 쓰는 자리도 없다.** 엔진은 `rule_steps` 를 모른다.
* 인자 없는 `Duel.advance()` 를 부르는 **production 자리도 하나**(`agent/runner.py:186`)다.
  `TurnProgressor.advance(state[, phase])` 는 **다른 메서드**이고 전부 `engine/` 안에서 쓴다.

replay · search · simulator · AI · evaluation · state_hash 가운데 `rule_steps` 를
**authoritative 정보로 쓰는 곳은 없다.**

---

## 6. 실패 · 거부 · INVALID · UNKNOWN · FORBIDDEN

| 경우 | `advance` 진행 | `rule_steps` | `Transcript` | `state_hash` | 재실행 |
|---|---|---|---|---|---|
| 정상 수락 행위 | 해당 없음 | 변화 없음 | `entries` 에 `accepted=True` | 바뀜 | 동일 |
| 거부된 행위 | 열리지 않음 (`None`) | **0 그대로** | `entries` 에 `accepted=False` | **안 바뀜** | 동일 |
| INVALID (없는 인스턴스 소환) | `None` | 변화 없음 | 거부로 기록 | **안 바뀜** | 동일 |
| UNKNOWN 계열 | 해당 없음 (해결 계층) | 변화 없음 | 해당 없음 | — | 동일 |
| FORBIDDEN | 해당 없음 (해결 계층) | 변화 없음 | 해당 없음 | — | 동일 |
| Engine 실행 오류 | 해당 없음 | 변화 없음 | 해당 없음 | — | 동일 |

측정으로 확인한 것:

* 불법 행위만 고르는 정책으로 한 판을 돌리면 **거부 1, `rule_steps` 0** 이다.
* `Duel.apply` 가 허가하지 않는 종류(normal_summon · pass · activate_card · attack ·
  change_position)는 모두 `rule_not_implemented` 로 거부되고 `state_hash` 가 **그대로**다.
* 🔴 **UNKNOWN ≠ INVALID 가 유지된다.** `STATUS_MAP` 이 두 묶음을 **다른 체인 상태**로
  보낸다.

| 묶음 | 멤버 | 가는 곳 |
|---|---|---|
| UNKNOWN | `CONDITION_UNKNOWN` · `UNCHECKED_TARGET` · `UNCHECKED_RULES` · `UNKNOWN` | `EFFECT_NOT_APPLIED` |
| INVALID | `INVALID_TARGET` · `INVALID_CONTEXT` | `INVALID_CHAIN_LINK` |
| FORBIDDEN | `FORBIDDEN` | `FORBIDDEN_EFFECT` |
| 실행 오류 | `EXECUTION_ERROR` | `EFFECT_RESOLUTION_ERROR` |

네 묶음이 **겹치지 않는다.** 실제 카드로도 확인했다 — 싸이크론(`5318639`)은 대상이
없어 `ResolutionStatus.INVALID_TARGET` / `ValidationCode.TOO_FEW_SELECTED` 로 멈춘다.

그리고 **어느 경우도 `rule_steps` 에 닿을 수 없다** — `advance()` 안에 실행기도
체인도 해결도 없기 때문이다(§2). 구조적으로 샐 길이 없다.

---

## 7. 🔴 `rule_steps` 만으로는 재현할 수 없다

두 질문을 구분한다.

| 질문 | 답 |
|---|---|
| `rule_steps` 가 deterministic replay **input** 인가 | 🔴 **아니다** |
| deterministic execution **결과를 검증하는 metric** 인가 | 🟢 **그렇다** |

근거:

1. **스칼라다.** `rule_steps = 151` 은 "151 걸음이 있었다" 를 말할 수 있지만 "어떤
   행위를 어떤 순서로" 를 담지 못한다.
2. **판을 고유하게 가리키지 못한다.** seed 230–243 을 돌려 보면 **같은 `rule_steps`
   를 가진 서로 다른 `state_hash`** 가 실제로 나온다.
3. `Transcript.canonical_state()` 는 **2-튜플**(받아들여진 (좌석, 행위) 줄, 승패)이고
   진행량이 들어갈 자리가 **없다.**

---

## 8. `PlayerAction` 과의 관계

Phase 3-F-19 가 증명한 재현 입력은 **(seed, 덱, 받아들여진 `PlayerAction` 순서,
`advance()` 끼워 넣기)** 다. 이 Phase 가 그 넷 중 마지막의 정체를 밝혔다.

| 질문 | 답 |
|---|---|
| replay input 은 `PlayerAction` 인가 | 🟢 **그렇다** |
| `rule_steps` 는 검증용 metadata 인가 | 🟢 **그렇다** (`MatchResult.canonical_state()`) |
| 둘 다 필요한가 | **재현에는 `PlayerAction` 만** 필요하다. `rule_steps` 는 "같은 대국이었나" 를 **보강 비교**할 때 쓴다 |
| `rule_steps` 만으로는 부족한가 | 🔴 **부족한 정도가 아니라 불가능하다**(§7) |

🔴 그리고 `advance()` 끼워 넣기는 **기록이 아니라 절차**다. 규칙 걸음이 무엇이었는지는
적히지 않고 **횟수만** 적히지만, 재현 때 `advance()` 를 **같은 자리에서 다시
돌리면** 같은 결과가 나온다 — 규칙 걸음이 결정론적이기 때문이다(§2: 난수를 쓰지
않고, 조건이 `step` 하나다).

### 🟡 그래서 `rule_steps` 는 재현의 **검산**이 된다

재현한 판의 규칙 걸음 수가 원본과 다르면 **절차를 잘못 밟은 것**이다. Phase 3-F-19
의 `test_24` 가 실제로 그 검산을 쓴다(`counts["rule_steps"] == transcript.rule_steps`).
이것이 "input 은 아니지만 의미 없는 값도 아니다" 의 구체적 내용이다.

---

## 9. `state_hash` 와의 관계

| 측정 | 결과 |
|---|---|
| `GameState.__slots__` 에 `rule_steps` | **없다** |
| `GameState` 인스턴스에 `rule_steps` 속성 | **없다** |
| `engine/state/game_state.py` 코드에 `rule_steps` | **0회** |
| 규칙 걸음 하나가 `state_hash` 를 바꾸는가 | 🟢 **바꾼다** — 손이 정확히 **한 장** 늘어난다 |

즉 **`rule_steps` 는 `state_hash` 밖에 있지만, 규칙 걸음의 *효과* 는 안에 있다.**
이 둘을 섞지 않는 이유는 `canonical_state` 가 적은 그대로다 — "역사도 체인도
우선권도 판의 모양이 아니고, 넣으면 같은 판이 경로에 따라 다른 해시를 갖게 된다"
(Phase 2-D-3 · 2-F-1 · 2-F-2). `state_hash` 계산 방식은 **건드리지 않았다.**

---

## 10. Simulator / Search 와의 관계

| 질문 | 답 |
|---|---|
| 시뮬레이션이 원본의 `rule_steps` 에 영향을 주는가 | 🔴 **아니다** |
| 사본이 독립적인가 | 🟢 **그렇다** — `GameState.clone()` |
| 시뮬레이션 실패가 `rule_steps` 에 영향을 주는가 | 🔴 **아니다** |
| Search ranking 이 `rule_steps` 에 의존하는가 | 🔴 **아니다** |

🔴 가장 뚜렷한 측정: **`Simulator` 는 `Duel.advance()` 를 한 번도 부르지 않는다.**
시뮬레이션 3회 중 호출 **0회**였다. 고를 것이 없는 응답 창은
`_settle_forced_passes` 가 **`fork.apply(PASS)`** 로 닫는다 — `advance()` 가 아니다.

그래서 사본에서는 **규칙 걸음이라는 개념 자체가 생기지 않는다.** `SimulationResult`
에 `rule_steps` 도 `steps` 도 없다. 원본의 `state_hash` 와 `step` 도 그대로였다.

AI/Search 코드는 **한 줄도** 고치지 않았다.

---

## 11. RNG 결정성

| 측정 | 결과 |
|---|---|
| 같은 seed 두 판의 `state_hash` | 동일 |
| 같은 seed 두 판에서 꺼낸 값 5개 | 동일 |
| `advance()` 안에 `rng`/`random`/`shuffle` | **없다** |
| `rule_steps` 가 난수 소비량을 뜻하는가 | 🔴 **아니다** |

규칙 걸음은 드로우이고, 드로우는 이미 셔플된 덱을 **순서대로** 가져간다. 그래서
`rule_steps` 와 난수 소비량이 혼동되는 구조가 **없다.**

.. note::
   🔴 측정 중 한 번 틀렸다. 서로 다른 두 판의 RNG 를 `repr(state.rng)` 로
   비교하려 했는데, 그 문자열에는 **객체 주소**가 들어가서 같은 seed 여도 다르게
   나온다. 비교할 수 있는 것은 **꺼낸 값의 순서**다. (`repr` 비교는 *같은* 판의
   전후에만 쓸 수 있다.)

RNG 구조는 **변경하지 않았다.**

---

## 12. 실제 카드 · 듀얼 시나리오

| # | §13 항목 | 측정 결과 |
|---|---|---|
| 1 | Normal Summon | 🟢 실제 듀얼에서 일어난다. **고르는 일**이므로 `entries` 에 남고 `rule_steps` 와 다른 칸으로 센다 |
| 2 | Special Summon | 🟡 **실제 듀얼에서 0회** — `legal_actions` 가 허가하지 않는다 |
| 3 | Effect Activation | 🟡 **실제 듀얼에서 0회.** 부품 수준(`ChainResolver.resolve_top`)에서는 된다 — 그 경로에 `rule_steps` 칸이 **없다** |
| 4 | Chain Resolution | 🟡 같다. `link.actor` 는 읽히지만 `rule_steps` 는 등장하지 않는다 |
| 5 | Cost Payment | 🟡 `CostPaymentResult` 에 `rule_steps` 없음. `engine/payment.py` 코드에도 0회 |
| 6 | 실패하는 Action | 🟢 거부로 기록되고 `rule_steps` 0, `state_hash` 불변 |
| 7 | 두 플레이어 실제 Duel | 🟢 두 수치가 각자의 일을 한다 |

실제 듀얼 세 판(seed 211–213)에서 **수락된 행위 종류 전수**:

```
end_phase 177 · normal_summon 30 · set_spell_trap 24 · attack 28
special_summon 0 · activate_card 0 · activate_effect 0
```

🟡 Phase 3-F-19 가 측정한 사실과 같다 — 실제 듀얼에서는 체인이 쌓이지 않으므로
효과 발동·체인 해결·비용 지불은 `Duel` 경로로 **닿지 않는다.** Engine V1 범위의
사실이고 이 Phase 가 고칠 일이 아니다. **없는 것을 있다고 적지 않는다.**

---

## 13. 결정성 실험 (§6)

같은 seed 로 두 번 돌려 **여덟 수치**를 비교했다. 세 seed 모두 전부 동일하고, 다른
seed 와는 다르다 (상수를 재는 것이 아님을 확인).

| seed | `state_hash` | `rule_steps` | `steps` | 거부 | 수락 | 턴 | 결과 |
|---|---|---|---|---|---|---|---|
| 31 | `19a98348…` | 21 | 176 | 0 | 176 | 22 | P1 승 (LP 0) |
| 32 | `6f3877c7…` | 9 | 81 | 0 | 81 | 10 | P1 승 (LP 0) |
| 33 | `9d122bfd…` | 10 | 89 | 0 | 89 | 11 | P0 승 (LP 0) |

---

## 14. 테스트 결과

새 파일: `tests/test_duel_advance_rule_step_contract.py` — **29개** (요구 최소 20개)

| # | 테스트 | §14 요구 항목 |
|---|---|---|
| 01 | `advance()` 는 드로우 페이즈의 드로우 하나뿐 | 1 |
| 02 | 규칙 걸음 하나가 한 장 뽑고 `state_hash` 를 바꾼다 | 2 |
| 03 | 🔴 돌려주는 `DuelStep.action` 은 **합성 PASS** | 3 |
| 04 | 🟢 `advance()` 호출 == `steps` + `rule_steps` | 4 |
| 05 | 한 호출에 engine step 하나 이하 | 5 |
| 06 | 🔴 거부는 `rule_steps` 를 늘리지 않는다 | 6 |
| 07 | INVALID — 판도 `step` 도 안 바뀐다 | 7 |
| 08 | 🔴 UNKNOWN ≠ INVALID, 둘 다 `rule_steps` 와 무관 | 8 |
| 09 | FORBIDDEN 은 독자 결과 | 9 |
| 10 | 실행 오류는 해결 상태이고 규칙 걸음이 아니다 | 10 |
| 11 | 통상 소환은 고르는 일 | 11 |
| 12 | 🟡 실제 듀얼이 닿는 행위 종류 실측 | 12 |
| 13 | 효과 발동은 `Transcript` 아래에 산다 | 13 |
| 14 | 체인 해결은 규칙 걸음을 만들지 않는다 | 14 |
| 15 | 비용 지불도 밖에 있다 | 15 |
| 16 | 🟢 같은 seed 가 모든 수치를 재현한다 | 16 |
| 17 | 🔴 `rule_steps` 는 `state_hash` 안에 없다 | 17 |
| 18 | 🟢 탐색 사본은 `advance()` 를 **0회** 부른다 | 18 |
| 19 | RNG 는 seed 가 정한다 | — |
| 20 | 실제 듀얼이 두 수치를 분리해 둔다 | 20 |
| 21 | 🔴 consumer 전수 분류 | §5 |
| 22 | `Duel.advance()` production 호출자 하나 | §5 |
| 23 | 🔴 스칼라는 replay input 이 될 수 없다 | §7 |
| 24 | 🟢 `rule_steps` 는 **검증 필드**다 | §8 |
| 25 | `Transcript` 칸은 넷 | §4 |
| 26 | production 변경 0 (AUDIT-ONLY) | §15 |
| 27 | 새 칸·새 추상 없음 | §15 |
| 28 | `state_hash`·RNG·숨은 정보 불변 | §15 |
| 29 | 검색 ranking digest 불변 (611결정) | 19 |

기존 테스트를 **삭제하지 않았고, skip 을 넣지 않았고, assertion 을 약화하지
않았다.** 기존 테스트를 고친 것도 **없다.**

### 전체 회귀

```
4548 passed, 4 skipped in 648.15s (0:10:48)
```

| | 개수 |
|---|---|
| Phase 3-F-19 (base `8ba7526`) | 4519 |
| 이 Phase 가 추가한 테스트 | **+29** |
| **합계 (실측)** | **4548** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음**) |

삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 테스트 수정 0.

---

## 15. 🔴 고의 위반 주입 9건 — 둘을 놓쳤고 **둘 다 내 잘못이었다**

`engine/duel.py` · `agent/runner.py` · `agent/arena.py` · `agent/simulation.py` ·
`engine/chain.py` 를 md5 로 백업하고 하나씩 심었다 되돌렸다. 마지막 복원을 md5 로
확인했다.

| # | 심은 위반 | 걸린 테스트 | 결과 |
|---|---|---|---|
| 1 | 거부된 행위도 `rule_steps` 를 늘린다 | `test_06` `test_21` | ✅ |
| 2 | `advance()` 가 `None` 이어도 올린다 | `test_04` `test_06` `test_11` `test_21` | ✅ |
| 3 | `advance()` 가 드로우를 반복한다 | `test_05` | ✅ |
| 4 | 합성 PASS 대신 END_PHASE 를 담는다 | `test_03` | ✅ |
| 5 | `advance()` 가 `TurnProgressor` 까지 돌린다 | `test_05` | ✅ |
| 6 | `Transcript.canonical_state` 에 `rule_steps` 를 넣는다 | `test_21` `test_23` `test_24` | ⚠️ **놓쳤다 → 단정을 고쳐 잡았다** |
| 7 | `MatchResult.canonical_state` 에서 뺀다 | `test_21` `test_24` | ✅ |
| 8 | engine 계층이 `rule_steps` 를 알게 한다 | `test_08` `test_14` | ⚠️ **probe 가 틀렸다 → 바로잡아 잡았다** |
| 9 | `Simulator` 가 사본에서 `advance()` 를 돌린다 | `test_04` `test_18` `test_22` | ✅ |

### 주입 6 — 🔴 **절대 실패할 수 없는 단정**을 적어 두었다

`test_23` 에 이렇게 써 두었다.

```python
assert "rule_steps" not in str(transcript.canonical_state())
```

`canonical_state()` 는 **값**을 돌려주고, 그 값 안에 칸 **이름**은 들어 있지 않다.
그래서 튜플에 `self.rule_steps` 를 끼워 넣어도 문자열 `"rule_steps"` 는 나타나지
않는다 — **이 단정은 어떤 변경으로도 깨질 수 없었다.** 이름이 아니라 **모양**을
세도록 고쳤다: 2-튜플인지, 첫째가 (좌석, 행위) 짝의 줄인지, 그 길이가 수락된 결정
수와 같은지, 둘째가 승패뿐인지.

(`test_24` 는 같은 주입을 **잡았다** — 그쪽은 소스를 본다. 그래서 전체가 무너지지는
않았지만, 죽은 단정을 남겨 두면 다음에 비슷한 것을 또 쓴다.)

### 주입 8 — 🔴 **probe 가 자기가 주장한 일을 하지 않았다**

`engine/chain.py` 에 `RULE_STEPS_HINT = 0  # rule_steps` 를 심었다. 그런데
`code_only()` 는 **주석을 버리고**(AST 라서) 이름은 **대문자**였다. 즉 소문자
`rule_steps` 라는 식별자가 **실제로 들어오지 않았다.** 테스트가 약한 것이 아니라
**주입이 가짜**였다. `rule_steps = 0` 으로 바로잡자 `test_08` · `test_14` 가 잡았다.

이것은 "주입이 아무것도 깨뜨리지 않았다" 를 곧바로 "테스트가 약하다" 로 읽으면
안 된다는 사례다 — **먼저 주입이 정말 그 일을 했는지 확인해야 한다.**

### 같이 정리한 것 — `cleandoc` 함정을 한 곳으로 모았다

`inspect.cleandoc(getsource(...).lstrip())` 은 **본문 줄까지 함께 당겨서** 함수
몸통의 들여쓰기를 깨뜨리고 `IndentationError` 를 낸다. Phase 3-F-18 에서 한 번
겪었는데 이 Phase 에서 **네 군데가 또** 걸렸다. 그래서 되풀이하지 않도록
`method_tree()` 헬퍼 **한 곳**으로 모았다 (맞는 도구는 `textwrap.dedent`).

---

## 16. production 변경 — **0줄**

§15 가 허용한 세 조건을 하나씩 확인했고 **하나도 성립하지 않는다.**

| 조건 | 판정 |
|---|---|
| ① `rule_steps` 의 의미와 실제 코드가 모순된다 | 🔴 **모순 없다.** docstring 이 "고르지 않아도 일어난 일의 수 (드로우 따위)" 라고 적고, 실제로 그것만 센다 |
| ② `Duel.advance()` 가 기록 계약을 깨뜨리는 경로가 존재한다 | 🔴 **없다.** 호출자 하나, 쓰는 자리 하나, 불변식 `호출 == steps + rule_steps` 성립 |
| ③ 문서/코드가 replay 제공을 주장하는데 정보가 부족하다 | 🔴 **주장하지 않는다.** `MatchResult.canonical_state` 는 "**비교**하는 모양" 이라고 적고, Phase 3-F-19 가 넣은 `Transcript` docstring 은 "`rule_steps` 는 **횟수만** 센다" 라고 이미 적는다 |

합성 PASS 를 `advance()` 의 docstring 에 적는 것도 검토했는데, (가) 그 docstring 이
이미 "**고르는 일이 아니기 때문**" 이라고 적어 성격을 밝히고 있고, (나) 기존
`tests/test_trigger_ownership_audit.py` 가 그 사실을 이미 못 박고 있으며, (다) 그
걸음이 `entries` 로 새는 경로가 **없다** — 그래서 **고치지 않았다.** 할 일이 없는
곳에 변경을 만들지 않는다.

---

## 17. 최종 판정

> ## **E. REPLAY_INPUT_IS_PLAYER_ACTION_SEQUENCE**

실제 재현의 authoritative input 은 **`PlayerAction` 순서**이며, `rule_steps` 는
**결과 검증 metadata** 다.

### 🔴 왜 A 가 아닌가 (지시가 가장 중요하다고 한 구분)

A(`RULE_STEPS_ARE_EXECUTION_METADATA`)의 내용 — "진행량 metadata 이며 replay input
이 아니다" — 는 **참이다.** 그리고 E 는 그 문장을 **포함한다.** 차이는 두 가지다.

1. **A 는 `rule_steps` 가 무엇에 쓰이는지 말하지 않는다.** 실측한 production
   consumer 는 표시 하나와 **`MatchResult.canonical_state()` 의 비교 필드**다. 그
   비교는 docstring 이 직접 "재현 시험이 이것을 쓴다" 라고 적는 자리다 — 즉 단순한
   "진행량 readout" 이 아니라 **검증에 쓰이는 값**이다. E 가 그것을 명시한다.
2. **A 는 input 이 무엇인지 말하지 않는다.** 이 Phase 의 질문은 "`rule_steps` 가
   authoritative 한가" 였고, 답은 "아니다 — **`PlayerAction` 순서가 그것이다**" 다.
   앞 Phase(3-F-19)가 실측으로 세운 결론과 이 Phase 의 측정이 같은 문장으로 모인다.

지시가 적은 그대로다 — "`rule_steps` 가 replay input 이 아니라고 해서 `rule_steps`
가 의미 없는 값이라는 뜻은 아니다." A 는 그 오독을 열어 두고, E 는 닫는다.

### 왜 B · C · D 가 아닌가

| 선택지 | 고르지 않은 이유 |
|---|---|
| B. `…REPLAY_AUTHORITATIVE` | 🔴 스칼라로는 불가능하다. 서로 다른 판이 같은 값을 갖는 것을 실제로 찾았다(§7) |
| C. `…CONTRACT_UNCLEAR` | 전제가 **거짓**이다. consumer 가 **서로 다른 의미로 쓰고 있지 않다** — 둘 다 "몇 걸음이었나" 로 쓴다(§5). 그리고 docstring 이 이미 정확하다 |
| D. `…CONTRACT_BROKEN` | 🔴 불일치가 **없다.** 불변식 `advance() 호출 == steps + rule_steps` 가 세 seed 에서 정확히 성립한다(§4) |

### 🟡 고치지 않고 기록만 하는 것

| 항목 | 내용 |
|---|---|
| 합성 PASS | `advance()` 의 `DuelStep.action` 은 아무도 고르지 않은 패스다. 지금은 `entries` 로 새지 않지만, 규칙 걸음을 기록하게 되는 Phase 는 **그 action 을 그대로 적어서는 안 된다** |
| `rule_steps` 는 무엇이었는지 적지 않는다 | 횟수만 센다. 지금은 `advance()` 가 결정론적(난수 없음, 조건 하나)이어서 재실행으로 메울 수 있다 |
| 실제 듀얼이 발동에 닿지 않는다 | `legal_actions` 가 `activate_*` · `special_summon` 을 허가하지 않는다 — Engine V1 범위 |
| `Transcript` vs `MatchResult` 비대칭 | 진행량이 후자의 비교에는 들어가고 전자에는 안 들어간다. 서로 다른 것을 묻기 때문이다 ("같은 수를 뒀나" vs "같은 대국이었나") |

---

## 18. 다음 Phase 후보 (최대 1개)

**`Duel.legal_actions` 가 `activate_*` · `special_summon` 을 허가하지 않는 경계 감사.**

이유: 지난 두 Phase 가 같은 벽에 세 번 부딪혔다 — 3-F-19 는 실제 듀얼에서
`_resolve_chain` 이 **한 번도** 불리지 않는다는 것을, 이 Phase 는 수락되는 행위가
네 종류뿐이라는 것을 측정했다. 그래서 효과 발동·체인·비용의 감사는 전부 **부품
수준**에서만 가능하고, "실제 듀얼로 확인했다" 라고 쓸 수 없는 항목이 계속 쌓인다.
그 경계가 **의도된 미구현인지**(그렇다면 어디에 어떻게 적혀 있는지) 아니면
**연결이 빠진 것인지**를 먼저 재는 것이 순서상 맞다 — 그것이 정해지지 않으면 뒤의
어떤 Phase 도 "실제 듀얼" 시나리오를 요구할 수 없다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
