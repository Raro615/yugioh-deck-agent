# Phase 3-F-23 — 공식 발동 용어 ↔ `PlayerActionKind` 대응 계약

## 0. 실제 HEAD / Base — `git` 으로 검증

| 항목 | 값 | 검증 |
|---|---|---|
| 전달받은 3-F-22 작업 commit | `9eb40b0` | ✅ `git log -1 9eb40b0` → `9eb40b0bc55d8078738483a09803fdfc9c94b1a5` *Phase 3-F-22: audit activation action semantic boundary* |
| 전달받은 3-F-22 보고서 commit | `d3f70e6` | ✅ `d3f70e68abb355e10e6411de8180ed4b66f7e43c` *Phase 3-F-22: document…* |
| 작업 시작 시 실제 HEAD | **`d3f70e6`** | ✅ 전달값과 일치 |
| `git diff d3f70e6 -- <production>` | **빈 출력** | ✅ base 대비 production 변경 0 에서 출발 |
| 작업 트리 | 깨끗함 | ✅ |

SHA 를 참고값으로만 받고 `git log` · `git diff` 로 **직접 검증**한 뒤 시작했다.

---

## 1. 조사 범위

| 대상 | 확인한 것 |
|---|---|
| `PlayerActionKind` | 🔴 지시서의 `analysis.PlayerActionKind` 는 **실제 위치가 아니다.** `engine/action.py:42` 에 있고 `analysis/` 에는 **전혀 없다**(grep 0건). 이 보고서는 실제 위치를 기준으로 썼다 |
| `PlayerAction` 세 표 | `_NEEDS_SOURCE` · `_NEEDS_EFFECT_REF` · `_ALLOWS_EFFECT_REF` |
| `Duel.legal_actions` | 후보 생성기 넷 (`_attack_actions` · `_activation_actions` · `_flow_actions` · `_withheld_board_actions`) |
| `Duel.apply` | 첫 관문(목록 대조) + dispatch 셋 |
| `EffectActivator.activate` | 입구의 종류 검사 · `effect_ref` 검사 |
| `ChainLink` 생성 | `(sequence, actor, effect_ref, …)` |
| activation timing 검증 | `_MISSING_RULE` · `_COMPLETE_RULES` · `_activate` / `_activate_effect` |
| 다른 `PlayerActionKind` | `special_summon` · `change_position` · `change_phase` · `end_phase` · `pass` |
| 공식 규칙 지식 | `data/rules/structured/sd-rulebook-en-v10.json` (저장소 자료) |
| 3-F-22 실제 카드 사례 | 재검증 + 두 장 추가 |
| AI/Search | `agent/` 7개 파일에서 enum 멤버 참조 전수 |

정적 조사는 전부 **문자열 리터럴을 지운 AST**(`code_only`)로 했다. 그리고
**"문서에 그렇게 적혀 있다" 와 "실제로 그렇게 동작한다" 를 분리**해서 §4 · §5 ·
§6 에 따로 적었다.

---

## 2. 공식 용어 (저장소의 공식 룰북에서 인용)

| 자리 | 원문 |
|---|---|
| 메인 페이즈 1 의 주요 행동 | **`"Activate a Card or Effect"`** — **한 항목**이다 |
| 체인 생성 조건 | *"You can only create a Chain by responding to the activation of **a card or effect**."* |
| 스펠 스피드 1 | `"Spells (Normal, Equip, Continuous, Field, Ritual)"` · `"Effect Monster's effects (Ignition, Trigger, and Flip)"` |
| 스펠 스피드 2 | `"Traps (Normal, Continuous)"` · `"Quick-Play Spells"` · `"Effect Monster's Quick Effects"` |
| 발동이 **아닌** 것 | `"Summoning a monster"` · `"Tributing"` · `"changing a monster's battle position"` · `"paying costs"` |
| 효과 종류 | `Continuous` · `Ignition` · `Quick` · `Trigger` · `Flip` Effect |

🔴 공식 분류에서 **마법 · 함정은 "카드"** 쪽으로 묶이고, **몬스터 쪽만 "효과"** 로
묶인다. 그리고 발동은 공식적으로 **하나의 행동**이다.

---

## 3. 현재 Engine 용어

| 엔진 개념 | 뜻 |
|---|---|
| `PlayerActionKind` | 고르는 주체가 고를 수 있는 행위 **11종** |
| `EffectRef(card_id, ordinal)` | 카드의 **몇 번째 효과**인가 |
| `ChainLink(sequence, actor, effect_ref, …)` | 체인에 들어간 **효과** 하나. 🔴 `card_id` 칸이 **없다** |
| `_MISSING_RULE` | "허가까지 가려면 **무엇이 더 있어야 하는가**" |
| `_COMPLETE_RULES` | "이 종류의 적법성을 **끝까지 볼 수 있다**" |
| `withheld` | 후보에 못 넣은 종류 + 이유 + 빠진 규칙 |

엔진은 **모든 발동을 "카드 X 의 효과 #N"** 으로 모델링한다. 그래서 체인에 넣을 때
요구하는 것은 **카드가 아니라 `EffectRef`** 다.

---

## 4. `PlayerActionKind` 대응표

| # | 공식 개념/표현 | 현재 Engine 개념 | `PlayerActionKind` | 현재 실행 가능? | 비고 |
|---|---|---|---|---|---|
| 1 | **"Activate a Card or Effect"** (메인 페이즈 행동 **하나**) | `EffectRef` 를 지목한 체인 삽입 | **`ACTIVATE_EFFECT`** | 🟢 예 (통상 마법) | 🔴 공식 **1개** ↔ 엔진 **2종** — 1:1 아님 |
| 2 | **"the activation of a card or effect"** (체인 생성 조건) | `ChainLink` 생성 | **`ACTIVATE_EFFECT`** | 🟢 예 | `RESPONDABLE` 에 그쪽만 있다 |
| 3 | **"activate a Spell/Trap Card"** | **그 카드의 효과 #0 의 발동** | 🔴 **`ACTIVATE_EFFECT`** | 🟡 통상 마법만. 함정은 `UNKNOWN` | 🔴 **이름이 거꾸로다** — docstring 이 이것을 `ACTIVATE_CARD` 에 적어 두었고 이 Phase 가 정정했다 |
| 4 | **"activate a monster effect"** (Ignition/Trigger/Flip/Quick) | — | **대응 없음** | 🔴 아니오 | 등록된 효과 중 **몬스터 0장** |
| 5 | **"효과의 발동"** 일반 | `EffectDefinition` + 타이밍 | `ACTIVATE_EFFECT` 가 받을 자리 | 🟡 부분 | 함정은 `trap-activation-timing` 으로 막힘 |
| 6 | **"카드 자체의 발동"** (카드 수준 선언) | **미지원 경계** | **`ACTIVATE_CARD`** | 🔴 아니오 | `_MISSING_RULE` = `activation-timing (Phase 2-C/2-F)` |

### 🔴 §2 E — 1:1 이 아니다. 추상이 갈리는 자리

두 군데서 갈린다.

1. **개수**: 공식 문구 하나(`"Activate a Card or Effect"`)가 엔진에서 **두 종류**다.
2. **대상의 정체**: 공식은 **발동되는 것**(카드 또는 효과)을 이름으로 부르는데,
   엔진의 행위는 **체인에 넣을 구체적 `EffectRef`** 를 요구한다. 그래서 공식
   "마법 카드의 발동" 하나가 엔진에서는 **"그 카드의 효과 #0 의 발동"** 이 된다 —
   `ChainLink` 에 `card_id` 칸이 **없다**는 것이 그 증거다.

---

## 5. `ACTIVATE_EFFECT` 의 현재 계약

### 문서가 말하는 것

> ``effect_ref`` 로 **지목한 효과**를 발동한다. ``effect_ref`` 는 **필수**다.

### 실제로 동작하는 것 (측정)

| 측정 | 결과 |
|---|---|
| `effect_ref` 필수성 | 🟢 팩토리 시그니처가 **위치 필수 인자**로 강제 (`_NEEDS_EFFECT_REF = {ACTIVATE_EFFECT}`) |
| `legal_actions` 후보 | 🟢 **나온다** (주문 덱에서 다수) |
| `Duel.apply` | 🟢 dispatch 가 이름으로 집어 `_apply_activation` |
| `EffectActivator` | 🟢 받는다 |
| `ChainLink` | 🟢 **생성된다** (체인 1) |
| `RESPONDABLE` | 🟢 포함 |
| 실제 카드 | 욕망의 항아리 `55144522` · 치료의 신 다이안 켓 `84257639` → `VALID` → `activated` → ChainLink 1 |

### 🟡 §2 C 의 답 — "효과를 발동" 인가 "특정 `effect_ref` 를 지목" 인가

**선언은 후자, 실제로 갈리는 것은 전자도 후자도 아니다.**

| 측정 | 값 |
|---|---|
| executable 효과를 가진 카드 | **13장** |
| 카드당 executable 효과 수 | **전부 1개** (분포 `{1: 13}`) |
| `EffectRef.ordinal` 분포 | **전부 `0`** |
| executable 효과를 둘 이상 가진 카드 | **없음** |
| 후보를 여럿으로 만드는 것 | **대상** (`target_combinations`) |

→ `effect_ref` 는 **모델이 요구하지만 값이 카드로 결정된다.** 즉 현재
`ACTIVATE_EFFECT` 의 실질은 **"카드 X 를 (대상 T 로) 발동"** 이다. "어느 효과인지"
라는 의미는 **선언되어 있으나 아직 쓰이지 않는다** — 몬스터 효과나 복수 효과
카드가 등록되는 날 비로소 갈린다.

이것이 §4 대응표 3줄의 역설을 설명한다 — 공식의 카드/효과 구분이 **아직 물리지
않기 때문에** 마법 카드 발동을 `ACTIVATE_EFFECT` 로 처리해도 모순이 드러나지
않는다.

---

## 6. `ACTIVATE_CARD` 의 현재 계약

### §2 D 의 네 질문

| 질문 | 답 |
|---|---|
| 실제 legal action 으로 생성되는가 | 🔴 **아니다.** 어떤 상태·어떤 덱에서도 후보 **0회** |
| `apply()` 까지 도달 가능한가 | 🔴 **아니다.** 첫 관문(목록 대조)에서 `RULE_NOT_IMPLEMENTED` |
| 특정 카드 발동을 표현하기 위한 **미래 경계**인가 | 🟢 **그렇다.** 빠진 규칙이 `activation-timing (Phase 2-C/2-F)` 로 **이름으로 지목**되어 있다 |
| 코드에서 **이름만** 존재하는가 | 🔴 **아니다.** `_withheld_board_actions` 가 이 종류로 **보류 사유를 만든다** — production 에서 `PlayerAction.activate_card` 를 만드는 자리가 `engine/duel.py` 한 곳 있다 |

### 거절이 **세 계층에서 각각** 일어난다

| 계층 | 결과 |
|---|---|
| `ActionValidator` | `UNKNOWN` + `missing_rule="activation-timing (Phase 2-C/2-F)"` |
| `Duel.apply` | 목록에 없으므로 `RULE_NOT_IMPLEMENTED`, 판 불변 |
| `EffectActivator` | 🔴 **종류만 보고** `INVALID_ACTION` — *"activate_card 는 효과 발동이 아닙니다"* |

🔴 그리고 `UNKNOWN` 은 `INVALID` 가 **아니다** — "규칙이 금지한다" 가 아니라
"판정할 규칙이 아직 없다" 다 (ADR-006).

→ 지시 §4 가 요구한 대로 **버그로 판정하지 않았다.** 의도된 범위이고, 그 사실을
계약으로 기록했다.

---

## 7. `legal_actions` / `apply` 경계

Phase 3-F-21 이 확정한 것이 그대로 성립한다 — **`apply()` 의 허용 범위 ==
`legal_actions().allowed`.**

| 종류 | 후보 | `apply` | 실행 경로 |
|---|---|---|---|
| `ACTIVATE_EFFECT` | 🟢 나온다 | 🟢 받는다 | `Duel._apply_activation` (실행기 아님) |
| `ACTIVATE_CARD` | 🔴 `withheld` 전용 | 🔴 거절 | 없음 |

실제 듀얼 측정(주문 덱):

```
offered : activate_effect 다수 · activate_card 0
withheld: activate_card 다수 · activate_effect 0
accepted: activate_effect 다수 (거부 0)
```

---

## 8. `EffectActivator` / `ChainLink` 연결

```
PlayerAction.activate_effect(actor, source, effect_ref)
    ↓   kind 검사 통과 (ACTIVATE_EFFECT 만)
    ↓   effect_ref 검사 통과 (None 이면 EFFECT_REF_REQUIRED)
    ↓   source 검사
EffectActivator.activate
    ↓
ActivationResult(status=ACTIVATED, code=OK)
    ↓
ChainLink(sequence=1, actor, effect_ref=EffectRef(card_id, 0))
    ↓
ResponseLoop (RESPONDABLE) → ChainResolver → EffectResult
```

`ACTIVATE_CARD` 는 **첫 줄에서 끊긴다.**

---

## 9. AI / Search 영향

| 질문 | 답 |
|---|---|
| AI 가 `ACTIVATE_EFFECT` 를 어떤 의미로 보는가 | **의미를 보지 않는다.** 후보로 받은 `PlayerAction` 을 그대로 평가한다 |
| Search 가 두 종류를 이름만으로 동일 취급하는가 | 🔴 **아니다.** 이름으로 집는 코드가 **없다** |
| `canonical_state` / digest 반영 | 종류 값이 **첫 칸**이고 digest 에 `kind.value` 가 그대로 들어간다. 그래서 둘이 섞이면 **숨지 않고 드러난다** |
| 후보 집합과 문서상 개념이 일치하는가 | 🟢 일치한다 — 발동 쪽 후보는 `ACTIVATE_EFFECT` 하나뿐 |
| `ACTIVATE_CARD` 가 candidate 로 안 나오는 것이 AI 계약과 충돌하는가 | 🔴 **아니다.** 탐색은 "지금 엔진이 내놓는 것" 만 본다고 스스로 적는다 |

### `agent/` 가 enum 멤버를 이름으로 집는 자리 — 전수

| 파일 | enum import | 이름으로 집는 멤버 |
|---|---|---|
| `agent/search.py` | ✅ | **없음** (형 표기용) |
| `agent/policy.py` | ✅ | **없음** |
| `agent/simulation.py` | ✅ | `PASS` |
| `agent/heuristic.py` | ✅ | `NORMAL_SUMMON` · `END_PHASE` · `PASS` |
| `runner` · `arena` · `evaluation` | ✗ | 없음 |

🔴 **발동 종류는 어느 파일에서도 이름으로 집히지 않는다.** 그래서 공식 용어를
AI 가 잘못 읽을 자리가 production 에 **없다**.

.. note::
   측정 중 한 번 틀렸다. `test_18` 에 `"PlayerActionKind" not in search_code` 라고
   썼는데 `agent/search.py` 는 그 enum 을 **import 한다.** "import 하지 않는다" 와
   "멤버를 이름으로 집지 않는다" 는 다른 말이다 — 후자를 세도록 고쳤다.

---

## 10. 공식 개념과 엔진 구현의 차이

| 차이 | 내용 |
|---|---|
| **개수** | 공식은 발동을 **한 행동**으로, 엔진은 **두 종류**로 적는다 |
| **대상의 정체** | 공식은 카드 또는 효과를 부르고, 엔진은 언제나 **`EffectRef`** 를 요구한다 |
| 🔴 **이름의 방향** | 공식으로 "카드의 발동" 인 마법·함정 발동을 엔진은 **`ACTIVATE_EFFECT`** 로 처리한다. `ACTIVATE_CARD` 라는 **이름**을 가진 쪽이 미지원이다 |
| **범위** | 공식은 몬스터 효과 네 종류를 적지만 엔진에 등록된 몬스터 효과는 **0장** |
| **거절의 결** | 공식에는 "판정할 규칙이 없다" 는 상태가 없다. 엔진은 `UNKNOWN` + `missing_rule` 로 그것을 **값으로** 적는다 |

프로젝트 내부 기준으로는 **모순이 없다.** 공식 용어로 읽는 사람에게만 이름이
거꾸로 보인다 — 그래서 이 Phase 가 **docstring 으로 그 사실을 고정**했다.

---

## 11. production 변경 여부 — **`engine/action.py` docstring 둘**

§6 의 기본값은 0 이지만, **첫째 조건이 실제로 성립했다.**

> `PlayerActionKind` 의 docstring 이 현재 실제 계약과 명백히 모순됨

**이전:**

```python
ACTIVATE_CARD = "activate_card"
"""카드 자체를 발동한다 (마법 · 함정의 발동)."""
```

🔴 괄호 안의 **"(마법 · 함정의 발동)"** 이 어긋났다. 마법 · 함정의 발동을 실제로
수행하는 것은 `ACTIVATE_EFFECT` 이고(§5), `ACTIVATE_CARD` 로는 어떤 카드로도
`invalid_action` 이다(§6). 그 문장이 남아 있으면 읽는 사람 — 또는 다음 Phase 가 —
**어느 종류를 넓혀야 하는지 틀리게 판단한다.** 이것은 3-F-22 §11 에서 🟡 로
기록해 둔 위험이 **문서 안에서 실제로 실현되어 있던 것**이다.

**이후:** `ACTIVATE_CARD` 에는 (가) 카드 수준 선언이라는 뜻, (나) Engine V1 에서
**유효하지 않다**는 것과 세 계층의 거절, (다) 빠진 규칙의 이름, (라) 🔴 마법 ·
함정의 발동을 이 종류로 적지 말라는 경고와 정정 이력, (마) 공식 문구와 1:1 이
아니라는 사실을 적었다. `ACTIVATE_EFFECT` 에는 (가) 지금 마법 · 함정 카드 발동까지
맡는다는 것, (나) 등록 효과가 카드마다 하나씩 전부 `ordinal=0` 이라 지목이 아직
갈리지 않는다는 측정값을 더했다.

### 🟢 실행되는 코드는 한 글자도 바뀌지 않았다

문자열 리터럴을 지운 AST 가 base(`d3f70e6`)와 **동일**하다 — `test_24` 가 이 Phase
작업 commit 의 앞뒤를 비교해 증명한다.

§6 의 금지 항목도 전부 지켰다 — `ACTIVATE_CARD` 구현 ✗ · activation timing 구현 ✗ ·
`legal_actions` 확장 ✗ · Chain 변경 ✗ · `EffectActivator` 변경 ✗ · enum 추가/삭제 ✗ ·
AI/Search 변경 ✗ · freeze 해제 ✗ · 공식 규칙을 근거로 한 새 게임 규칙 ✗.

---

## 12. 향후 `ACTIVATE_CARD` 를 구현한다면 필요한 선행 계약

측정된 사실에서 **그대로 따라오는 것만** 적는다. 새 규칙을 설계하지 않는다.

| # | 선행 계약 | 근거 |
|---|---|---|
| 1 | **`activation-timing` 규칙 계층** | `_MISSING_RULE` 이 그것을 지목한다. 그것이 없으면 `_COMPLETE_RULES` 에 올릴 수 없고, 올리면 모듈의 자기 `assert` 가 import 를 막는다 |
| 2 | **함정의 유발 조건 모델** | 함정은 더 아래 계층에서 막힌다 — `trap-activation-timing`: 공식 스크립트의 `SetCode(EVENT_*)` 가 `EffectDefinition` 에 **없다** |
| 3 | **`ACTIVATE_CARD` 와 `ACTIVATE_EFFECT` 의 역할 재배분 결정** | 지금은 후자가 마법·함정 발동을 맡는다. 전자를 켜면 **같은 카드에 두 경로**가 생긴다 — 어느 쪽이 정본인지 먼저 정해야 한다 |
| 4 | **복수 효과 카드 또는 몬스터 효과의 등록** | 그때까지는 `effect_ref` 지목이 갈리지 않으므로(§5) 두 종류를 구분할 **실증적 필요가 없다** |
| 5 | **`EffectActivator` 입구의 종류 검사 변경 범위** | 지금은 종류만 보고 거절한다. 받게 하려면 `effect_ref` 없는 입력을 어떻게 체인에 넣을지 정해야 한다 — `ChainLink` 에는 `card_id` 칸이 없다 |
| 6 | **AI/Search 회귀 재측정** | 후보 집합이 늘면 `canonical_state` 정렬이 바뀌고 **611결정 digest 가 깨진다** |

---

## 13. 이번 Phase 에서 **의도적으로 하지 않은 것**

* `ACTIVATE_CARD` 를 구현하지 않았다 — 후보 생성기도, 수행기도, 타이밍 규칙도.
* 두 enum 을 합치지도, 지우지도, 더하지도 않았다 (11종 그대로).
* `legal_actions` 를 넓히지 않았다 (생성기 넷 그대로).
* `EffectActivator` · `Chain` · AI/Search 를 건드리지 않았다.
* 공식 룰북을 근거로 **새 게임 규칙을 구현하지 않았다** — 용어 대응만 적었다.
* 이름이 거꾸로라는 이유로 **enum 을 바꾸지 않았다.** 이름 변경은 직렬화 값
  (`"activate_card"`)과 digest 에 영향을 주므로 freeze 범위다.
* 함정의 `trap-activation-timing` 을 해결하지 않았다.
* 🟡 `docs/phase2a-player-action.md` 의 **남은 설계 문제 #2**("`ACTIVATE_CARD` 와
  `ACTIVATE_EFFECT` 가 정말 다른 행위인가")를 **그 파일에서 고치지 않았다.** 답은
  3-F-22(**D. ONE_SIDED_CONTRACT**)와 이 보고서에 있다 — 과거 보고서를 소급
  편집하기보다 현재 계약 문서를 정본으로 둔다.

---

## 14. 테스트 결과

새 파일: `tests/test_official_activation_player_action_contract.py` — **25개**
(요구 최소 20개)

| # | 테스트 | §8 요구 |
|---|---|---|
| 01 | 🔴 공식은 한 행동, 엔진은 두 종류 (1:1 아님) | 11 |
| 02 | 체인은 `ACTIVATE_EFFECT` 로만 쌓인다 | 8 |
| 03 | 🔴 마법 **카드**의 발동이 `ACTIVATE_EFFECT` 로 간다 | 11 |
| 04 | 🔴 몬스터 효과 발동에 대응할 것이 없다 | 11 |
| 05 | `ACTIVATE_CARD` = 공식 개념의 **빈 자리** | 3 |
| 06 | 🔴 1:1 이 아니고 대상의 정체가 다르다 | 11 |
| 07 | 🔴 정정한 문장이 사라졌다 | §6 |
| 08 | `ACTIVATE_EFFECT` docstring 이 맡은 일을 적는다 | §6 |
| 09 | 두 docstring 이 둘을 같다고 말하지 않는다 | §6 |
| 10 | `effect_ref` 필수 여부 | 4 |
| 11 | 🟡 "어느 효과인지" 가 아직 갈리지 않는다 | 2 |
| 12 | `ACTIVATE_CARD` 는 `apply` 도 활성기도 못 통과 | 6, 7 |
| 13 | 이름만 있는 것이 아니라 보류 사유로 쓰인다 | 3 |
| 14 | **실제 마법 두 장**이 같은 종류로 체인까지 | 실제 카드 |
| 15 | 🟡 함정은 더 아래 계층에서 막힌다 | 실제 카드 |
| 16 | 실제 듀얼에서 대응표가 그대로 보인다 | 5 |
| 17 | 🟢 AI 는 발동 용어를 해석하지 않는다 | 9 |
| 18 | 탐색이 둘을 하나로 묶지 않는다 | 9 |
| 19 | digest 가 종류 이름을 담는다 | 10 |
| 20 | 후보 집합이 문서의 대응과 일치한다 | 5 |
| 21 | `state_hash` · RNG · 숨은 정보 불변 | §9 |
| 22 | 같은 seed 재현 | §9 |
| 23 | Engine V1 을 넓히지 않았다 | 12 |
| 24 | production 변경은 docstring 둘뿐 (AST) | §6 |
| 25 | 검색 digest 불변 (611결정) | §9 |

실제 카드 **네 장** 사용 — 욕망의 항아리 `55144522` · 치료의 신 다이안 켓
`84257639` · 강제 탈출 장치 `94192409` · 홍옥의 사령 `11091375`.

기존 테스트를 **삭제·skip·약화하지 않았고, 고친 것도 없다.**

### 전체 회귀

```
4633 passed, 4 skipped in 626.35s (0:10:26)
```

| | 개수 |
|---|---|
| Phase 3-F-22 (base `d3f70e6`) | 4608 |
| 이 Phase 가 추가한 테스트 | **+25** |
| **합계 (실측)** | **4633** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음**) |

삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 테스트 수정 0.

### 🟢 고의 위반 주입 9건 — **전부 첫 시도에 잡혔다**

`engine/action.py` · `engine/action_validation.py` · `engine/activation.py` ·
`engine/duel.py` · `engine/response.py` · `agent/heuristic.py` 를 md5 로 백업하고
하나씩 심었다 되돌렸다. 마지막 복원을 md5 로 확인했다.

| # | 심은 위반 | 걸린 테스트 |
|---|---|---|
| 1 | **정정한 문장을 되돌린다** | `test_07` `test_09` `test_23` `test_24` |
| 2 | `ACTIVATE_EFFECT` docstring 의 마법·함정 언급 삭제 | `test_08` |
| 3 | `effect_ref` 를 `ACTIVATE_CARD` 에도 필수로 | `test_03` `test_05` `test_10` `test_13` `test_24` |
| 4 | 활성기가 `activate_card` 도 받게 | `test_12` `test_23` |
| 5 | 응답 루프가 `activate_card` 도 다루게 | `test_02` |
| 6 | 빠진 규칙 지목 삭제 | 10개 테스트 |
| 7 | 발동 후보를 `activate_card` 로 | `test_13` `test_16` `test_20` |
| 8 | `withheld` 에서 `activate_card` 제거 | `test_13` `test_16` |
| 9 | AI 가 `activate_effect` 를 이름으로 집게 | `test_17` `test_18` |

주입 1번이 중요하다 — **이 Phase 가 고친 바로 그 문장을 되돌리면 깨진다.** 정정이
문서가 아니라 **계약으로 고정**되었다는 뜻이다.

---

## 15. 불변 조건 확인 (§9)

| 항목 | 결과 |
|---|---|
| `state_hash` | **불변** — 후보 생성·검증을 반복해도 그대로 |
| RNG | **불변** — `repr(state.rng)` 그대로, 같은 seed 재현 |
| hidden-information | **불변** — 상대 손·덱 `concealed=True`, `cards=()` |
| `GameStateView` | **불변** |
| Search 동작 | **불변** — 후보 집합·정렬 그대로 |
| AI 동작 | **불변** — 이름으로 집는 멤버 셋 그대로 |
| Engine V1 freeze | **유지** — enum 11종 · 실행기 등록 5종 · 생성기 넷 · 활성기 입구 |
| 검색 digest | **불변** — 6판 **611결정** |
| 기존 테스트 의미 | **변화 없음** — 수정 0건 |

---

## 16. 최종 판정

> ## **A. ACTIVATION_TERMINOLOGY_CONTRACT_FIXED**

공식 발동 용어와 `PlayerActionKind` 의 대응이 **확정되었고, 어긋나 있던 계약
문장이 고쳐졌다.**

### 근거

1. **대응표가 완성되었다**(§4). 여섯 줄 전부 실제 코드와 공식 룰북 원문으로 채웠고,
   1:1 이 아니라는 사실과 **갈리는 자리 두 곳**(개수 · 대상의 정체)을 적었다.
2. **어긋난 문장이 실제로 있었고 고쳤다**(§11). `ACTIVATE_CARD` 의
   "(마법 · 함정의 발동)" 은 §6 의 첫째 조건에 정확히 해당했다. 고친 뒤
   **그 되돌림을 주입으로 검증**했다(주입 1번 → `test_07`).
3. **실행되는 코드는 바뀌지 않았다.** 문자열을 지운 AST 가 base 와 동일하다.
4. **25개 계약 테스트로 고정**했다. 실제 카드 네 장, 공식 룰북 원문 인용, AI 계층
   전수 조사를 포함한다.

### 왜 B 가 아닌가

B(`ACTIVATION_TERMINOLOGY_DOCUMENTATION_ONLY`)는 **문서만** 손댔을 때의 판정이다.
이 Phase 는 **production 파일(`engine/action.py`)의 계약 문장**을 고쳤다 — 그것이
읽는 사람에게 계약을 선언하는 **1차 표면**이고, 거기 적힌 내용이 틀려 있었다.
"문서만" 으로 적으면 **production 에 잘못된 계약이 있었다는 사실**이 사라진다.

### 왜 C · D 가 아닌가

| 선택지 | 고르지 않은 이유 |
|---|---|
| C. `ACTIVATION_CONTRACT_GAP` | **계약에 빈 구멍이 없다.** 지원되지 않는 네 종류 전부 빠진 규칙이 이름으로 지목되어 있고, 지원되는 한 종류는 끝까지 간다. "아직 구현되지 않음" 은 gap 이 아니라 **기록된 경계**다 |
| D. `PRODUCTION_BEHAVIOR_CONFLICT` | 🔴 **behavior 충돌이 아니다.** 어긋난 것은 **docstring 한 문장**이었고, 실행 경로는 세 계층에서 일관되게 `ACTIVATE_CARD` 를 거절한다. 실제 동작과 동작이 충돌한 자리는 **없다** |

---

## 17. 남은 structural risk

| 항목 | 내용 | 등급 |
|---|---|---|
| **이름이 공식과 거꾸로** | `ACTIVATE_CARD` 가 가리키는 공식 개념을 `ACTIVATE_EFFECT` 가 수행한다. 이제 docstring 에 적혀 있지만 **이름 자체는 그대로**다 — 이름 변경은 직렬화 값과 digest 에 걸리는 freeze 범위 | 🟡 |
| `effect_ref` 지목이 미사용 | 카드마다 효과 하나, 전부 `ordinal=0`. 구분의 필요성이 **현재 카드로는 실증되지 않는다** | 🟡 |
| 함정이 더 아래에서 막힘 | `trap-activation-timing` 은 `EffectDefinition` 에 `SetCode(EVENT_*)` 가 없다는 **데이터 모델** 문제다 | 🟡 |
| 두 경로가 생길 위험 | `ACTIVATE_CARD` 를 켜면 같은 마법에 두 발동 경로가 생긴다 — §12 3번 | 🟡 |
| 과거 보고서의 미해결 질문 | `docs/phase2a-player-action.md` 의 남은 설계 문제 #2 가 그 파일에는 여전히 열린 채로 있다 | 🟡 |

전부 **FUTURE WORK 로 기록**한다. 고치지 않았다.

---

## 18. 다음 Phase 후보 (최대 1개)

**함정 발동의 선행 계약 — `EffectDefinition` 의 유발 조건(`SetCode(EVENT_*)`)
누락 범위 감사 (조사 전용).**

이유: 이 Phase 가 대응표를 채우면서, 발동 쪽에서 **가장 아래에 있는 빠진 조각**이
`activation-timing` 이 아니라 **함정의 유발 조건 데이터**라는 것이 드러났다
(`trap-activation-timing`: *"공식 스크립트의 `SetCode(EVENT_*)` 가
`EffectDefinition` 에 없다"*). 등록된 효과 16개 중 **6개가 함정**인데 전부 이
이유로 막혀 있다. `ACTIVATE_CARD` 든 몬스터 효과든 그 위에 올리려면 **먼저 이
데이터 경계가 어디까지인지** 재야 한다 — 공식 스크립트에 무엇이 있고
`EffectDefinition` 이 무엇을 버리는지는 **측정으로 알 수 있는 사실**이고, 새 규칙
설계가 필요하지 않다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
