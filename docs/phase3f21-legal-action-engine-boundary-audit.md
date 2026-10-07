# Phase 3-F-21 — `Duel.legal_actions()` ↔ Engine 실행 가능 범위 경계 감사

## 0. Base 와 실제 HEAD

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-20 작업 commit | `637437cee3baf29738283f20abd9dedb29049ef0` — *Phase 3-F-20: audit Duel advance rule step contract* | ✅ `git log` 로 확인 |
| Phase 3-F-20 보고서 commit | `e42ec893d1cd49bbe17f6fa6d21c252184be3416` — *Phase 3-F-20: document Duel advance rule step contract audit* | ✅ |
| 작업 시작 시 실제 HEAD | `e42ec89` | ✅ |
| 작업 트리 | 깨끗함 | — |

SHA 를 추측하지 않고 `git log --format=%H` 로 읽었다.

---

## 1. 🔴 먼저 — 앞 Phase 두 개의 서술을 **정정한다**

Phase 3-F-19 와 3-F-20 보고서가 이렇게 적었다.

> `legal_actions` 가 `activate_*` · `special_summon` 을 허가하지 않는다 — Engine V1
> 범위의 사실

**`activate_effect` 에 대해서는 틀렸다.**

실측하면 `legal_actions` 는 `activate_effect` 를 **내놓고**, 고르면 **수락되고 체인
까지 쌓인다.**

| 덱 | `activate_effect` 후보 | 고르면 수락 |
|---|---|---|
| 통상 몬스터 12 + 주문 8 (digest 덱) | 26회 | — |
| 주문 16 + 통상 4 | **292회** | **81회 수락, 거부 0** |

앞 Phase 의 관측("실제 듀얼에서 `activate_*` 0회")은 **그 덱과 그 정책에서의
사실**이었다 — 통상 몬스터 위주 덱이라 탐색 정책이 발동을 **고르지 않았을** 뿐이다.
나는 그것을 **엔진의 제한**으로 일반화했고, 그것이 잘못이었다.

실제로 withheld 되는 것은 **`activate_card`** 와 **`special_summon`** 이다.

정정 내용은 `test_04` 가 못 박는다. 두 보고서 파일 머리에도 정정 노트를 달았다.

---

## 2. 조사 범위

`Duel.legal_actions` · `Duel.apply` · `ActionExecutor` · `ActionValidator` ·
`PlayerAction`/`PlayerActionKind` · `duel_executor()` · 활성화 경로
(`_activation_actions` → `_activation_gate` → `EffectActivator`) · 특수 소환 경로
(`SpecialSummonHandler` vs `SPECIAL_SUMMON_PROCEDURE`) · 흐름 계층
(`_flow_actions` → `TurnProgressor`) · AI (`agent/search.py` · `agent/heuristic.py` ·
`agent/policy.py` · `agent/simulation.py`).

문자열 리터럴을 지운 AST(`code_only`)로 쟀다 — 설명문의 낱말을 코드로 세지 않았다.

---

## 3. ActionKind 전체 분류표

| ActionKind | PlayerAction 생성 | `legal_actions` 가 냄 | `apply` 가 받음 | 실행 경로 | 실제 시나리오 | 분류 |
|---|---|---|---|---|---|---|
| `normal_summon` | ✅ | ✅ | ✅ | 실행기 `NormalSummonHandler` | 수락 확인 | **A** |
| `set_monster` | ✅ | ✅ | ✅ | 실행기 `SetMonsterHandler` | 후보 확인 | **A** |
| `set_spell_trap` | ✅ | ✅ | ✅ | 실행기 `SetSpellTrapHandler` | 수락 확인 | **A** |
| `attack` | ✅ | ✅ | ✅ | 실행기 `AttackHandler` | 수락 확인 | **A** |
| `activate_effect` | ✅ | ✅ | ✅ | **`Duel._apply_activation`** (실행기 아님) | **수락 + 체인 1** | **A** |
| `end_phase` | ✅ | ✅ | ✅ | **`Duel._apply_end_phase`** | 수락 확인 | **A** |
| `pass` | ✅ | ✅ | ✅ | **`Duel._apply_pass`** | 수락 확인 | **A** |
| **`special_summon`** | ✅ | ❌ | ❌ (관문이 막음) | **실행기에 등록됨** | 후보 0회 | **D** (🟡 글자 그대로는 C — §9) |
| `activate_card` | ✅ | ❌ (`withheld` 로 기록) | ❌ | 없음 | withheld 345회 | **D** |
| `change_position` | ✅ | ❌ | ❌ | 없음 | — | **D** |
| `change_phase` | ✅ | ❌ | ❌ | 없음 | — | **D** |

분류 집계: **A 7종 · B 0종 · C 0종(유효) · D 4종 · E 0종 · F 0종.**

🔴 **B(합법인데 실행 불가)가 0종**인 것이 핵심이다. 후보로 나온 것은 **전부** 수락
되었고 거부가 **0건**이었다(세 seed × 두 덱).

---

## 4. `legal_actions()` 계약

docstring 이 직접 적는다 — *"지금 이 자리에서 **허가가 난** 행위들. `UNKNOWN` 은
후보가 아니다."*

§6 이 물은 것에 답하면: **"구현된 모든 종류를 반환하는 함수" 가 아니다.**

* `PlayerActionKind` 를 훑는 반복문이 **없다**(AST 확인). 종류를 열거하지 않는다.
* 후보를 만드는 곳은 넷뿐이다 — `_attack_actions` · `_activation_actions` ·
  `_flow_actions` · `_withheld_board_actions`.
* 판 위의 후보는 **검증기(`ActionValidator`)** 가, 흐름(`pass`/`end_phase`)은
  **흐름 계층(`TurnProgressor`)** 이 답한다. 검증기는 관측만 읽으므로 우선권과
  진행을 모르기 때문이다.
* `DRAW_PENDING` 이면 **아무것도** 돌려주지 않는다 (`allowed` 와 `withheld` 둘 다 빈
  튜플) — 드로우는 고르는 일이 아니다(Phase 3-F-20).
* 빈 칸을 남기지 않는다 — 못 내는 이유는 `withheld` 에 **종류 · 이유 · 빠진 규칙**
  으로 적는다. `withheld` 는 `PlayerAction` 이 아니라 **설명**이므로 고를 수 없다.

---

## 5. `Duel.apply()` 계약

```python
legal = self.legal_actions(action.actor)
if action not in legal.allowed:
    return DuelStep(action, False, ValidationCode.RULE_NOT_IMPLEMENTED, ...)
```

🟢 **`apply()` 의 허용 범위 == `legal_actions().allowed` 그 자체다.** 목록을 만든
뒤 판이 바뀌었을 수 있으므로 **다시 묻는다**.

→ 그래서 §2 가 "구조적 위험" 이라고 한 **C(실행 가능하지만 합법이 아님)는 `Duel`
경계에서 발생할 수 없다.** 합법이 아니면 실행기에 **닿지 못한다.**

관문을 통과한 뒤의 dispatch 는 셋 + 나머지다.

| 종류 | 처리 |
|---|---|
| `PASS` | `_apply_pass` |
| `END_PHASE` | `_apply_end_phase` |
| `ACTIVATE_EFFECT` | `_apply_activation` (발동의 결과물은 `StateDelta` 만이 아니라 `Chain` 이기도 해서 `ActionHandler` 에 끼울 수 없다) |
| 그 밖 | `_apply_board` → `ActionExecutor` |

---

## 6. Engine 실행 가능 범위

| 경로 | 종류 |
|---|---|
| `duel_executor().supported` | `normal_summon` · `special_summon` · `set_monster` · `set_spell_trap` · `attack` (**5**) |
| `Duel` 이 직접 처리 | `pass` · `end_phase` · `activate_effect` (**3**) |
| **합계 ①** | **8종** |
| 실행 경로가 **없는** 종류 | `activate_card` · `change_position` · `change_phase` (**3**) |

🔴 §3 이 구분하라고 한 그대로다 — **"실행기에 없다" ≠ "실행할 수 없다".**
`activate_effect` · `pass` · `end_phase` 는 실행기에 없지만 실행된다.

### 네 집합 (§6)

| 집합 | 크기 | 내용 |
|---|---|---|
| ① Engine 이 실행할 수 있는 모든 종류 | **8** | 위 표 |
| ② 지금 이 상태에서 합법인 종류 | 가변 | 상태가 정한다 (`DRAW_PENDING` 이면 **0**) |
| ③ `legal_actions` 가 **낼 수 있는** 종류 | **7** | ① − `special_summon` |
| ④ AI 가 고를 수 있는 종류 | **③** | `legal.allowed` 그대로 |

🟢 **③ ⊆ ①** — 후보로 나오는 것은 전부 실행 가능하다. **④ == ③** — AI 는 목록
밖을 보지 않는다(§7).

---

## 7. AI / Search 영향

```
GameStateView → legal_actions() → Policy/Search → PlayerAction → Duel.apply()
```

| 질문 | 답 |
|---|---|
| `RuleBasedPolicy` 가 특정 종류를 가정하는가 | 🟡 **그렇다** — `agent/heuristic.py` 가 `NORMAL_SUMMON` · `END_PHASE` · `PASS` 셋을 이름으로 집는다. **셋 다 실행 가능하고 후보로도 나온다.** 그리고 주석이 태도를 적는다 — *"나타나지 않는 행위에 점수를 매기면 … 규칙이 아니라 희망이다"* |
| Search 가 `legal_actions` 를 완전한 action space 로 가정하는가 | 🔴 **아니다.** `agent/search.py` 가 직접 적는다 — *"탐색하는 것은 `legal.allowed` 의 원소뿐이다"* |
| SearchCandidate 생성이 `legal_actions` 에 의존하는가 | 🟢 **그렇다** — 후보를 스스로 만들지 않는다 |
| Simulation 이 `legal_actions` 를 다시 부르는가 | 🟢 **그렇다** — 사본에서 다시 묻는다 |
| "선택할 수 없는 행동" 을 따로 처리하는가 | 🟢 `withheld` 로 **이유와 함께** 남긴다 |
| hidden information 경계가 깨지는가 | 🔴 **아니다** — 후보 생성이 `ActionValidator(self.view(seat))` 로 **관측**을 쓴다. 상대 손·덱은 `concealed=True`, `cards=()` 그대로 |
| deterministic tie-break 가 변하는가 | 🔴 **후보를 하나라도 늘리면 변한다**(아래) |
| RNG 소비가 변하는가 | 후보 생성은 난수를 쓰지 않는다. 같은 seed → 같은 후보 |
| `state_hash` 가 변하는가 | `legal_actions` 를 열 번 불러도 `state_hash` 와 RNG 가 그대로 |

### 🔴 후보를 늘리면 AI 의 결정이 바뀐다

`agent/search.py` 가 후보를 `canonical_state()` 로 정렬해 동점을 가른다
(`sorted(legal.allowed, key=lambda action: action.canonical_state())` — AST 로 확인).
**집합이 바뀌면 정렬 결과가 바뀌고, 그러면 pin 된 digest 가 깨진다.**

실제로 고의 위반 주입에서 공격 후보 생성을 끄거나 `AttackHandler` 등록을 빼자
`test_30`(611결정 digest)이 **즉시 깨졌다.** 즉 "AI 가 더 많은 행동을 고를 수 있으면
좋다" 는 이유만으로 `legal_actions` 를 건드릴 수 없다 — §7 · §8 이 금지한 그대로이고,
그 금지에는 **측정된 근거**가 있다.

---

## 8. 실제 카드 / 시나리오 검증

§4 가 요구한 다섯 질문에 실측으로 답한다.

| # | 질문 | 답 |
|---|---|---|
| 1 | 소환 가능한 몬스터가 있으면 `NORMAL_SUMMON` 이 나오는가 | 🟢 **나온다.** 후보도 수락도 확인 |
| 2 | 특수 소환 실행 경로가 있는데 왜 후보가 없는가 | 검증기가 **`UNKNOWN` + `special-summon-condition (카드마다 다르다)`** 를 돌려준다. `legal_actions` 는 `UNKNOWN` 을 후보로 넣지 않는다(계약). **조건이 카드마다 다르고 그 규칙이 아직 없다** — 기록된 제한이다 |
| 3 | 발동 실행 경로가 있는데 왜 후보가 없는가 | 🔴 **전제가 틀렸다.** `activate_effect` 는 **후보로 나오고 실행된다**(§1). `activate_card` 만 없고, 그 이유는 **`activation-timing (Phase 2-C/2-F)`** 로 기록되어 있다 |
| 4 | 공격 실행 코드가 없어서 `ATTACK` 이 없는 것인가 | 🔴 **아니다.** `AttackHandler` 가 등록되어 있고 `_attack_actions` 가 후보를 만든다. `ATTACK` 은 **A 분류**다 |
| 5 | `SET_MONSTER` / `SET_SPELL_TRAP` / `CHANGE_POSITION` | 세트 둘은 **A**. `change_position` 은 생성기도 수행기도 없고, 이유가 **`position-change-legality (Phase 2-G)`** 로 기록되어 있다 → **D** |

사용한 실제 카드: 홍옥의 사령(`11091375`) · 욕망의 항아리(`55144522`) ·
천사의 자비(`84257639`) · 강욕의 보은(`5915629`).

### 발동 한 건의 끝까지

```
고른 발동: kind=activate_effect source=0 ref=55144522:e[0]
결과:     accepted=True  code=ok
          "55144522:e[0] 를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
state_hash 바뀜=True   체인=1   완료=False
```

---

## 9. 발견된 structural risk

### 🟡 `special_summon` — 등록되어 있으나 후보가 아니다

글자 그대로는 §2 의 **C(EXECUTABLE_BUT_NOT_LEGAL)** 에 들어맞는다.

| 측정 | 결과 |
|---|---|
| `duel_executor().supported` 에 `SPECIAL_SUMMON` | **있다** |
| `legal_actions` 가 후보로 냄 | **0회** |
| production 에서 `PlayerAction.special_summon` 생성 | **0곳** |
| 효과 쪽 특수 소환 | `SPECIAL_SUMMON_PROCEDURE` (**다른 객체**). `engine/effect/executor.py` 는 `SpecialSummonHandler` 를 **쓰지 않는다** |

**그런데 위험이 되지 않는다.** `apply()` 가 목록과 대조한 뒤에야 실행기로 가므로
(§5) 그 수행기에 **닿을 길이 없다.** 실제로 `special_summon` 을 `apply` 에 넣으면
`RULE_NOT_IMPLEMENTED` 로 거부되고 판이 한 글자도 바뀌지 않는다(`test_02` ③).

그리고 기존 감사가 이미 같은 말을 적어 두었다 —
`tests/test_special_summon_event_foundation_audit.py`: *"막는 것은 실행기가 아니라
관문"*.

→ **FUTURE WORK 로 기록**한다. 고치지 않는다.

### 🟡 그 밖

| 항목 | 내용 |
|---|---|
| `activate_card` vs `activate_effect` | 이름이 비슷한데 운명이 다르다. 전자는 영원히 `withheld`, 후자는 A 분류. 섞어 읽으면 §1 의 오독이 다시 난다 |
| `withheld` 는 종류당 하나만 남긴다 | `_withheld_board_actions` 가 같은 이유를 손패마다 반복하지 않으려고 `break` 한다 — 이유는 알 수 있지만 **몇 장이 막혔는지는 모른다** |
| 후보 집합이 digest 를 정한다 | 후보를 늘리는 어떤 변경도 AI 회귀를 깨뜨린다(§7) |

---

## 10. production 변경 여부 — **0줄**

§8 이 허용한 두 조건을 확인했고 **둘 다 성립하지 않는다.**

| 조건 | 판정 |
|---|---|
| **A.** 반드시 legal 해야 하는 action 인데 연결이 누락되었다 | 🔴 **근거 없다.** 후보에서 빠진 네 종류 전부 검증기가 `UNKNOWN` 과 **빠진 규칙의 이름**을 돌려준다. "향후 구현 예정" 같은 문구가 아니라 **코드가 그 자리에서** 무엇이 없는지 적는다 |
| **B.** `legal_actions` 와 `apply` 의 허용 범위가 명백히 모순된다 | 🔴 **모순이 없다.** `apply` 의 허용 범위가 **곧 목록**이다(§5). 그리고 후보로 나온 것은 전부 수락되었다 — 거부 **0건** |

§7 의 금지 항목도 전부 지켰다 — `activate_*` 추가 ✗ · 특수 소환 추가 ✗ ·
`ATTACK` 추가 ✗ · freeze 해제 ✗ · 새 `ActionKind` ✗ · AI/Search 재설계 ✗ ·
MCTS/RL/LLM ✗ · 새 action graph ✗.

---

## 11. 테스트 결과

새 파일: `tests/test_legal_action_engine_boundary_audit.py` — **30개**
(요구 최소 20개)

| # | 테스트 | §9 요구 |
|---|---|---|
| 01 | `legal_actions` 는 VALID 만 받는다 (종류 열거가 아니다) | 계약 |
| 02 | 🟢 `apply` 의 허용 범위 == 목록 (AST + 행동) | 일관성 |
| 03 | 🟢 후보로 나온 것은 전부 수락된다 (거부 0) | 누락 검사 |
| 04 | 🔴 **정정**: `legal_actions` 는 발동을 내놓는다 | 분류 |
| 05 | 발동을 고르면 수락되고 체인이 쌓인다 | 실행 |
| 06 | 발동은 실행기가 아니라 `Duel` 이 처리한다 | 분류 |
| 07 | 실행 가능 집합은 정확히 8종 | 분류 |
| 08 | 후보 집합은 정확히 7종, ③ ⊆ ① | 분류 |
| 09 | 🟢 withheld 가 **빠진 규칙 이름**을 말한다 | UNKNOWN 구분 |
| 10 | 🟡 `special_summon` 등록되었으나 후보 아님 | 유입 검사 |
| 11 | `activate_card` 는 이유와 함께 withheld | 유입 검사 |
| 12 | 🟢 "합법인데 실행 불가" 0종 | 일관성 |
| 13 | 통상 소환 실제 시나리오 | 실제 카드 |
| 14 | 세트 둘 다 도달 | 실제 카드 |
| 15 | `ATTACK` 은 생성기 + 수행기 둘 다 | 실제 카드 |
| 16 | `change_position` 은 둘 다 없음 | 분류 |
| 17 | 드로우 단계는 후보 0 | 상태 의존 |
| 18 | 탐색은 목록 밖을 안 본다 | AI 연결 |
| 19 | 🔴 후보 집합이 tie-break 를 정한다 | AI 연결 |
| 20 | 휴리스틱은 실제로 나오는 종류만 전제 | AI 연결 |
| 21 | 시뮬레이션은 사본에서 다시 묻는다 | Search 연결 |
| 22 | 후보 생성이 숨은 정보를 넓히지 않는다 | hidden-info |
| 23 | 후보 생성이 `state_hash`·RNG 를 안 건드림 | 불변 |
| 24 | clone 독립성 — 사본의 후보가 같다 | clone |
| 25 | 같은 seed → 같은 후보 | RNG |
| 26 | production 변경 0 (AUDIT-ONLY) | — |
| 27 | 새 `ActionKind` · 새 생성기 없음 | §7 |
| 28 | `LegalActions` 가 허가/보류를 분리 | 구조 |
| 29 | 등록 안 된 종류는 실행기가 거부 (ADR-006) | invalid 처리 |
| 30 | 검색 digest 불변 (611결정) | 회귀 |

기존 테스트를 **삭제·skip·약화하지 않았고, 고친 것도 없다.**

### 전체 회귀

```
4578 passed, 4 skipped in 602.11s (0:10:02)
```

| | 개수 |
|---|---|
| Phase 3-F-20 (base `e42ec89`) | 4548 |
| 이 Phase 가 추가한 테스트 | **+30** |
| **합계 (실측)** | **4578** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음**) |

삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 테스트 수정 0.
앞 두 보고서 파일에는 §1 의 정정 노트를 달았다 (문서만, 코드 아님).

---

## 12. 🔴 고의 위반 주입 9건 — 둘을 놓쳤다

`engine/duel.py` · `engine/summon.py` · `agent/heuristic.py` · `agent/search.py` ·
`engine/action_execution.py` 를 md5 로 백업하고 하나씩 심었다 되돌렸다. 마지막
복원을 md5 로 확인했다.

| # | 심은 위반 | 걸린 테스트 | 결과 |
|---|---|---|---|
| 1 | **`apply` 가 목록 대조를 건너뛴다** | `test_02` | ⚠️ **놓쳤다 → 고쳐 잡았다** |
| 2 | 발동 후보 생성을 끈다 | `test_04` `test_05` `test_08` | ✅ |
| 3 | 공격 후보 생성을 끈다 | `test_08` `test_15` `test_30` | ✅ |
| 4 | 실행기에서 `SPECIAL_SUMMON` 등록을 뺀다 | `test_07` `test_08` `test_10` | ✅ |
| 5 | 실행기에서 `ATTACK` 등록을 뺀다 | `test_03` `test_07` `test_08` `test_12` `test_13` `test_15` `test_30` | ✅ |
| 6 | `withheld` 를 비운다 | `test_11` | ✅ |
| 7 | 휴리스틱이 실행 불가 종류를 전제한다 | `test_20` | ✅ |
| 8 | 탐색이 후보를 정렬하지 않는다 | `test_19` | ⚠️ **놓쳤다 → 고쳐 잡았다** |
| 9 | 드로우 단계에서도 후보를 낸다 | `test_17` | ✅ |

### 주입 1 — 🔴 **이 파일에서 가장 중요한 단정이 부분 문자열 비교였다**

`test_02` 가 이렇게 쟀다.

```python
assert "action not in legal.allowed" in source
```

주입은 그 줄을 `if False and action not in legal.allowed:` 로 바꿨다 — **문자열이
그대로 남아 있으니 통과한다.** 행동 쪽도 `change_phase` 로 찔렀는데, 관문이 꺼져도
그 종류는 실행기에 수행기가 없어 여전히 거부되었다. 즉 **찔러보기도 틀린 것을
골랐다.**

고친 방향:
* **구조** — AST 로 `legal.allowed` 를 보는 `if` 가 **정확히 하나**이고, 그 조건이
  `action not in legal.allowed` **그 자체**이며, 몸통에 `return` 이 있고, 그 줄이
  dispatch 보다 **앞**임을 단정한다.
* **행동** — 🔴 `special_summon` 으로 찌른다. 그것은 **실행기에 등록되어 있는데
  후보가 아닌** 유일한 종류이므로, 관문이 없으면 수행기까지 가 버린다. 거부
  코드와 `state_hash` 불변까지 확인한다.

### 주입 8 — 🔴 **낱말만 센 단정 (3-F-20 에서 같은 실수를 했는데 또 했다)**

`test_19` 가 `"sorted" in search_code` 로 쟀다. 주입은 `ordered = sorted(...)` 한
줄만 바꿨는데, `sorted` 가 같은 파일의 다른 줄(`ordering_key`)에도 있어서 통과했다.

고친 방향: AST 로 **`legal.allowed` 를 첫 인자로 받는 `sorted(...)` 호출이 정확히
하나**이고 그 `key` 가 `canonical_state` 임을 단정한다.

두 번 다 **"주입이 아무것도 깨뜨리지 않았다" 를 테스트가 옳다는 뜻으로 읽지
않은 것**이 수확이다.

---

## 13. 최종 판정

> ## **B. INTENTIONALLY_LIMITED**

행동 공간은 **의도적으로 제한되어 있고, 그 제한이 코드에 기록되어 있다.**

### 코드 근거

1. **제한의 메커니즘이 명시적이다.** `legal_actions` 는 `VALID` 만 받는다고
   docstring 에 적고, `UNKNOWN` 은 후보가 아니다. 후보에서 빠진 네 종류 전부
   검증기가 `UNKNOWN` + **빠진 규칙의 이름**을 돌려준다 —
   `activation-timing (Phase 2-C/2-F)` · `special-summon-condition (카드마다 다르다)` ·
   `position-change-legality (Phase 2-G)` · `turn-progression (Phase 2-G)`.
2. **제한의 태도가 ADR 로 적혀 있다.** ADR-006 — *"등록하지 않은 것은 실행되지
   않는다"*, 그리고 `UNKNOWN` 을 `INVALID` 와 섞지 않는다 (*"합치면 구현이 없는
   카드가 규칙 위반으로 읽히고, 그것은 거짓이다"*).
3. **빈 칸을 남기지 않는다.** 못 내는 이유를 `withheld` 에 종류 · 이유 · 빠진 규칙
   으로 적는다.
4. **AI 가 그 제한을 전제로 설계되어 있다.** 탐색은 목록 밖을 보지 않고, 휴리스틱은
   실제로 나오는 종류만 집는다.

### 왜 A 가 아닌가

A(`LEGAL_ACTION_SPACE_ALIGNED`)는 "정렬되어 있다" 인데, **① 과 ③ 이 정확히 같지
않다** — `special_summon` 하나가 실행 가능하지만 후보가 아니다(§9). 그 차이를
"정렬됨" 으로 덮으면 §9 의 구조 관찰이 사라진다.

### 왜 C · D 가 아닌가

| 선택지 | 고르지 않은 이유 |
|---|---|
| C. `LEGAL_ACTION_ENGINE_GAP` | **gap 이 없다.** 후보로 나온 7종이 전부 실행되고(거부 0건), 빠진 4종은 전부 "빠진 규칙" 이 기록되어 있다. 증거 없이 누락을 버그라고 판정하지 않는다(§7) |
| D. `EXECUTION_LEGALITY_CONTRACT_GAP` | **계약이 어긋나지 않는다.** `apply` 의 허용 범위가 **곧** `legal.allowed` 다 — 모순이 생길 구조가 아니다 |
| E. `AUDIT_ONLY_SUFFICIENT` | 과정에 대한 답이지 **계약에 대한 답이 아니다.** 이 Phase 의 질문은 "계약이 무엇인가" 였고 B 가 그것을 말한다 |
| F. `UNKNOWN` | 네 집합을 전부 실측했다. 모르는 것이 없다 |

### 🔴 다만 이 판정은 §1 의 정정 **뒤에** 성립한다

앞 두 Phase 의 서술대로였다면 "발동이 아예 불가능" 이므로 훨씬 좁은 제한이었다.
실제 제한은 **`activate_card` · `special_summon` · `change_position` ·
`change_phase` 넷**이고, 발동은 **열려 있다.**

---

## 14. 다음 Phase 후보 (최대 1개)

**`activate_card` ↔ `activate_effect` 의 의미 경계 감사.**

이유: 이 Phase 가 "`activate_*` 가 막혀 있다" 는 **내 잘못된 일반화**를 걷어 냈고,
그 자리에 더 좁고 정확한 사실이 남았다 — `activate_effect` 는 A, `activate_card` 는
D 다. 그런데 **두 종류가 무엇이 다른지**는 아직 어디에도 정리되어 있지 않다.
`_withheld_board_actions` 가 `activate_card` 로만 이유를 적고, `_activation_actions`
는 `activate_effect` 만 만든다. 둘 중 하나가 **다른 하나의 특수한 경우인지**, 아니면
**서로 다른 개념인지**(카드의 발동 vs 효과의 발동 — 공식 규칙에서도 다른 말이다)를
확정하지 않으면, 앞으로 발동 규칙을 넓힐 때 어느 쪽을 넓히는지가 흐려진다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
