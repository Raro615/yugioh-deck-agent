# Phase 6-S — 합법적 행동 후보 · 검증 · 실행 경로 정합성

작업 브랜치: `claude/pensive-goodall-te1egy`
시작 HEAD: `c362a0f` (Phase 6-R 마지막 commit) · 작업 트리 깨끗함
바꾼 생산 파일: **`engine/duel.py` 하나** (`_flow_actions` 한 함수)

> **먼저 §2 의 전제를 정정한다.** 지시문 §2 가 "`Duel._activation_actions`
> 가 … `legal_actions` 의 공용 계약과 **별도로 동작하는 경로**가 존재한다"
> 라고 적었다. **그런 경로는 없다.** AST 로 세면 `_activation_actions` 의
> 생산 호출은 **정확히 두 곳**이고 **둘 다 `legal_actions` 안**이다 — 별도
> 경로가 아니라 **사설 보조 함수**다. 그리고 후보 생성과 실제 실행은 **같은
> 관문 함수**(`_activation_gate`)를 부른다. 지시문 §2 가 스스로 요구한 대로
> ("이전 보고서의 해석을 사실로 전제하지 않는다") 재어서 정정한다. 근거는
> §2 · §3 에 있다.

---

## 1. 기존 `legal_actions` 구조

`Duel.legal_actions(seat=None)` → `LegalActions(seat, allowed, withheld)`.

```
seat = self.to_act if seat is None else seat
듀얼이 끝났으면            → LegalActions(seat)            빈 목록
step 이 DRAW_PENDING 이면  → LegalActions(seat, (), ())     드로우는 선택이 아니다
validator = ActionValidator(self.view(seat), definitions=self._activator.definitions)

창이 열렸고 이 자리가 쥐었으면   → _activation_actions
그렇지 않고 턴 플레이어 · 창 닫힘 → 패 × (소환 · 몬스터 세트 · 마법함정 세트)
                                 + _attack_actions + _activation_actions
그 밖                            → (판을 바꾸는 후보 없음)

+ _flow_actions            PASS · END_PHASE  (허가와 보류 둘 다)
+ _withheld_board_actions  activate_card 의 보류 한 줄
```

**세 가지가 설계로 들어 있다.**

* `UNKNOWN` 은 후보가 아니다 (docstring 이 적는다). 그래서 `activate_card` ·
  `special_summon` 은 후보로 나오지 않는다.
* 후보 생성은 **카드 종류를 미리 보고 거르지 않는다** — 패의 한 장이 세
  후보가 되고 어느 것이 되는지는 **검증기가** 말한다. 걸러 두면 규칙이 두
  곳에 적히고 둘이 갈라진다.
* 흐름 둘(`PASS` · `END_PHASE`)은 **검증기가 아니라 흐름 계층**이 답한다 —
  검증기는 `GameStateView` 만 보고 우선권과 진행은 판 밖에 산다 (ADR-007).

---

## 2. `_activation_actions` 와의 관계 — 🔴 **별도 경로가 아니다**

### 2-1. AST 실측

| 함수 | 생산 호출 | 어디서 |
|---|---|---|
| `_activation_actions` | **2** | `engine/duel.py` `legal_actions` ×2 |
| `_activation_gate` | **2** | `_activation_actions` · `_apply_activation` |
| `_attack_actions` | 1 | `legal_actions` |
| `_flow_actions` | 1 | `legal_actions` |
| `_withheld_board_actions` | 1 | `legal_actions` |
| `_activation_sources` | 1 | `_activation_actions` |
| `legal_actions` | **5** | `duel.apply` · `agent/runner.py` `step` · `agent/simulation.py` ×3 |

`_activation_actions` 를 부르는 **외부 호출자가 하나도 없다.** `agent` ·
`app` 어디에도 없다. 두 번 부르는 이유는 자리가 둘이기 때문이다 — 창이 열린
자리와 턴 플레이어의 자리. 그래서 §2 가 말한 "공용 계약과 별도로 동작하는
경로" 는 **없다.**

### 2-2. 후보 생성과 실행이 **같은 관문**을 부른다

`_activation_gate` 의 호출자가 둘이고, 하나는 후보 생성
(`_activation_actions`) 하나는 실행 (`_apply_activation`) 이다. 그 둘이
각자 관문을 세우고 **서로 다른 판을 읽던** 것이 STRUCTURAL-134 였고, Phase
3-E-13 에서 이미 합쳐졌다. `test_b01` 이 AST 로 고정한다.

### 2-3. `_activation_actions` 의 거름망 (코드 순서대로)

```
_activation_sources(seat)            패 + 세트해 둔 마법 · 함정
  × activatable_effects(card_id)     🔴 executable 인 것만 (ADR-006)
  × definition.cost.costs 가 없음    비용을 치른 뒤 되돌릴 방법이 없다 (ADR-008)
  × target_combinations(...)         대상 조합 하나하나가 **다른 후보**
  × selections_for(...)              선택 절차가 미지원이면 제외
  × _activation_gate(...) VALID      관문 셋
```

---

## 3. `ActionValidator` 및 `Duel.apply` 계약

### 3-1. `apply` 의 첫 관문

```python
legal = self.legal_actions(action.actor)
if action not in legal.allowed:
    return DuelStep(action, False, ValidationCode.RULE_NOT_IMPLEMENTED,
                    f"{action.kind.value} 는 지금 허가된 행위가 아닙니다.")
```

🔴 **후보 목록이 실행 가능 범위를 정한다.** 목록에 없으면 실행기에 닿지
못한다. 그래서 "후보에 없는데 실행된다" 는 자리가 `Duel` 경계에 존재할 수
없다 (Phase 3-F-21 이 세운 사실이고 6-S 가 다시 확인했다).

### 3-2. 그리고 **목록을 믿지 않는다**

`apply` 는 `legal_actions` 를 **다시 부른다** — 목록을 만든 뒤 판이 바뀌었을
수 있다. 관문은 읽기만 하므로 몇 번 불러도 같은 답이고, 그래서 중복이 아니라
**독립 검증**이다.

### 3-3. 실측 — 후보 전부가 `apply` 에서 접수된다

스물 자리의 후보 **44건**을 하나씩 `clone` 한 판에서 실제로 `apply` 했다.
**거절 0건** (`test_g03`). 그 중 판이 바뀐 것이 41건이고, 바뀌지 않은 셋은
체인 등록만 한 발동이다 (그것이 옳다 — Phase 6-R).

---

## 4. 후보 생성과 합법성 검증의 책임 구분 — 🔴 **판정자가 넷이다**

이 Phase 의 가장 중요한 발견이다. 관문이 셋이라고 적혀 있지만, 그 앞에
**네 번째 판정자**가 있다.

| # | 판정자 | 무엇에 답하는가 | 무엇을 읽는가 |
|---|---|---|---|
| **0** | `legal_actions` 의 분기 조건 | 🔴 **이 자리가 지금 무엇이든 고를 수 있는가** | `priority` · `turn_player` |
| 1 | `ActionValidator` | 규칙이 허락하는가 | `GameStateView` **만** (ADR-007) |
| 2 | `ActivationTimingChecker` | 스펠 스피드 · 세트한 턴 | `chain` · `rule_uses` (관측에 **없다**) |
| 3 | `EffectActivator.can_activate` | 우리가 할 수 있는가 | 정의 · 조건 · 비용 · 대상 (ADR-006) |
| — | `TurnProgressor` (`_flow_actions`) | 페이즈를 넘길 수 있는가 | 턴 진행 계층 |

### 4-1. 🔴 **이 구분을 몰라서 측정이 두 번 틀렸다**

정직하게 적는다. 6-S 의 첫 두 측정이 **둘 다** 판정자를 덜 셌다.

| 측정 | 비교 대상 | 결과 | 왜 틀렸나 |
|---|---|---|---|
| 1차 | `ActionValidator` **하나** | 거짓 양성 15 · 거짓 음성 4 | 흐름 둘을 검증기와 비교했고(15건), 관문 2·3 을 묻지 않았다(4건) |
| 2차 | 관문 **셋** | 거짓 양성 0 · 거짓 음성 1 | 네 번째 판정자를 묻지 않았다 |
| 3차 | 판정자 **넷** | 🔴 **거짓 양성 0 · 거짓 음성 0** | — |

1차의 "거짓 양성 15" 는 전부 `PASS` · `END_PHASE` 다. 검증기가 그 둘에
`UNKNOWN` 을 돌려주는 것은 **설계**이고 (ADR-007), 그것을 거짓 양성으로
센 것이 틀렸다 (`test_f04` 가 그 책임 구분을 재어서 남긴다).

### 4-2. 관문 셋이 **서로 다른 것을 막는다** (실측)

| 관문 | 막은 예 | 이유 코드 |
|---|---|---|
| 1 `ActionValidator` | 배틀 페이즈의 통상 마법 | `WRONG_PHASE` 계열 |
| 2 `ActivationTimingChecker` | **세트한 턴**의 함정 | `SET_TURN_*` |
| 3 `can_activate` | 덱이 1장일 때의 욕망의 항아리 | 카드 조건 거짓 |

🔴 **그래서 `ActionValidator` 가 `VALID` 라고 해서 후보가 되지 않는 것이
정상이다.** 검증기는 세트 기록(`GameState.rule_uses`)도 체인도 볼 수 없다 —
그것들은 관측에 없다. `test_d02` 가 세 자리에서 "관문 1 은 `VALID`, 그런데
다른 관문이 막는다" 를 하나씩 센다.

---

## 5. 발견한 거짓 양성 및 거짓 음성 사례

### 5-1. 측정 범위

§7 의 A~G 를 실제 엔진으로 만든 **상태 스물**. 각 상태에서

* `legal_actions(seat).allowed` 전부 (합 **44건**)
* 그 자리에서 **적어 볼 수 있는 모든** `PlayerAction` 열거 (합 3,500여 건)
* 판정자 넷 · 실행 구현 · `apply` (사본) · `GameState` · `EventJournal`

| 상태 | 내용 |
|---|---|
| A1 A2 A3 | 메인1 소환권 미사용 · 사용 뒤 · 상대 자리 |
| B1 B2 B3 | 통상 마법 가능 · 덱 1장 · 배틀 페이즈 |
| C1 C2 C3 | 세트한 턴 · 상대 턴 · 다음 내 턴 |
| D1 D2 D3 D4 | 체인 1 · 2 의 쥔 쪽과 안 쥔 쪽 |
| E1 E2 | 어니스트 MZONE · 패(잘못된 위치) |
| F1 F2 | 벌금 후보 3장 · 1장(부족) |
| G1 G2 G3 | 로스트(미지원) · 입문서(조건 거짓) · 강제 탈출 장치 |

### 5-2. 🔴 거짓 양성 — **0건**

| 검사 | 결과 |
|---|---|
| 후보로 나왔는데 관문 셋이 막는다 | **0** |
| 후보로 나왔는데 실행 구현이 없다 | **0** |
| `UNKNOWN` 인데 후보에 있다 | **0** (`activate_card` · `special_summon` 은 보류) |
| 비용 · 대상 선택이 불가능한데 후보에 있다 | **0** (`selections_for` 가 후보 생성에서 이미 걸린다) |
| 잘못된 위치에서 발동 허용 | **0** (E2 어니스트가 패에 있으면 후보가 아니다) |
| 스펠 스피드 · 우선권 위반 | **0** |
| 후보 전부를 사본에서 `apply` 했을 때 거절 | **0 / 44** |
| 같은 후보가 두 번 나온다 | **0** |
| 후보 생성이 판을 바꾼다 | **0 / 20** (`state_hash` 와 `randomness.draws` 둘 다) |
| 인스턴스 · `EffectRef` 연결 오류 | **0** |

### 5-3. 🔴 거짓 음성 — **0건**, 그리고 **룰북이 금지한 하나**

고를 수 있는 자리에서 "판정자 넷을 통과하고 실행 구현이 있는데 후보에 없는
행동" 은 **0건**이다.

🔴 **다만 네 번째 판정자가 막은 자리를 그냥 넘기지 않는다.** "상대 턴 · 창
닫힘" 에서 세트된 일반 함정은 **관문 셋을 전부 통과**하고 실행 구현도 있다.
그런데 후보가 아니다. 실측:

| 상대 턴 · 창 닫힘에서 P0 의 발동 | 관문 | 코드 | 실행 구현 | 후보 |
|---|---|---|---|---|
| 세트된 일반 함정 (욕망의 선물) | **통과** | `OK` | 있음 | **0** |
| 세트된 일반 함정 (벌금 · 대상 2장) | **통과** | `OK` | 있음 | **0** |
| 세트된 속공 마법 (리로드) | **통과** | `OK` | 있음 | **0** |
| 패의 통상 마법 (욕망의 항아리) | 1 | `NOT_TURN_PLAYER` | 있음 | 0 ✅ |
| 세트된 통상 마법 (욕망의 항아리) | 1 | `NOT_TURN_PLAYER` | 있음 | 0 ✅ |
| MZONE 의 기동 효과 (어니스트) | 1 | `NOT_TURN_PLAYER` | 있음 | 0 ✅ |

**그리고 그것이 옳다.** 룰북 `TURN PLAYER'S PRIORITY` 가 적는다.

> *"The turn player always starts with Priority, or the choice to activate
> a card first, in each phase or step of their turn. **As long as the turn
> player has Priority, the opponent cannot activate cards or effects**,
> except for effects that activate automatically, like Trigger or Flip
> effects."*

엔진의 `PriorityState.idle(turn_player=X)` 가 바로 그 자리다 — X 가 우선권을
쥐고 있고 아직 넘기지 않았다. Phase 6-Q 의
`test_f04_the_response_window_decides_who_may_activate` 가 이것을 이미 못
박았고 (*"함정이 빠르다는 이유로 우선권을 무시하지 않는다"*), **그 판단이
옳았다.** 6-S 는 되돌리지 않는다. `test_d03` 이 룰북 원문과 대조한다.

🔴 **그러면 무엇이 빠져 있는가** — §17-1 에 적는다 (같은 룰북 줄의 뒷부분).

### 5-4. 🔴 **실제로 찾은 결함 둘 — `_flow_actions` 의 묶인 조건**

거짓 양성·음성이 아니라 **보고의 결함**이다. 창 × 쥔 쪽의 네 자리를 전수로
재면 둘이 틀렸다.

| 자리 | 창 | 쥔 쪽 | 고치기 전 |
|---|---|---|---|
| ① 턴 플레이어 | 닫힘 | — | 정상 |
| ② 비턴 플레이어 | 닫힘 | — | 보류 `PASS` "우선권이 열려 있지 않습니다" — **사실** ✅ |
| ③ 쥔 쪽 (비턴) | 열림 | 본인 | 정상 ✅ |
| ④ 안 쥔 쪽 (**턴**) | 열림 | 상대 | 🔴 **후보 0 · 보류 0 — 침묵** |
| ⑤ 쥔 쪽 (턴) | 열림 | 본인 | 정상 ✅ |
| ⑥ 안 쥔 쪽 (비턴) | 열림 | 상대 | 🔴 "우선권이 열려 있지 않습니다" — **거짓 문장** |

고치기 전의 코드:

```python
if self.priority.is_open and self.priority.holds(seat):
    allowed.append(PlayerAction.passing(actor=seat))
elif seat != self.turn_player:          # ← 🔴 두 사실이 하나에 묶였다
    withheld.append(WithheldAction(
        PlayerActionKind.PASS,
        "우선권이 열려 있지 않습니다.",   # ← ⑥ 에서 **거짓**
        missing="우선권을 여는 규칙 (Phase 2-F)",
    ))
```

④ 의 침묵이 왜 위험한가: 읽는 쪽은 `allowed` 가 비고 `withheld` 도 비었을
때 **"할 것이 없다" 와 "상대를 기다린다" 와 "듀얼이 끝났다" 를 가를 수
없다.** `WithheldAction` 의 설계가 그 반대를 약속한다 — *"빈 목록은 '할 것이
없다' 로 읽힌다. 적어 두면 '아직' 으로 읽힌다."*

---

## 6. 실제 구조적 차단 원인

| | 원인 | 이번에 |
|---|---|---|
| ① | `_flow_actions` 가 "창이 닫혔다" 와 "창은 열렸고 상대가 쥐었다" 를 **한 조건에** 묶었다 | **고쳤다** |
| ② | 룰북 `TURN PLAYER'S PRIORITY` 의 **뒷절반**이 구현되지 않았다 — 페이즈 · 스텝의 끝에서 우선권이 넘어가지 않는다 | **재어서 남긴다** (§17-1) |
| ③ | 관문에서 걸린 발동 후보가 `withheld` 에 **이유를 남기지 않는다** (9건) | **재어서 남긴다** (§17-2) |

②가 6-Q 가 연 길의 **절반을 실제 듀얼 루프에서 막고 있다** — 상대 턴의 함정
발동은 "상대가 무언가 먼저 발동해 줄 때" 만 닿는다.

---

## 7. 채택한 최소 수정안과 대안 비교

### 7-1. §9 의 다섯 대안

| 대안 | 내용 | 판단 |
|---|---|---|
| **A** | 후보 생성 경로의 **잘못된 필터** 수정 | 🟢 **채택** — `_flow_actions` 의 묶인 조건을 갈랐다 |
| B | 이미 있는 `ActionValidator` 결과 재사용 | 불필요 — 관문 1 이 이미 그것이다 |
| C | 외부 호출자의 후보 목록 읽기 수정 | 불필요 — 호출자 다섯 곳 전부 `legal_actions` 만 읽는다 (§2-1) |
| D | `EffectRef` · 인스턴스 전달 오류 수정 | 불필요 — 실측 **0건** (§5-2) |
| E | 후보 생성과 실행 사이의 누락된 연결 보완 | 불필요 — **같은 관문 함수**를 이미 공유한다 (§2-2) |

### 7-2. 🔴 **고르지 않은 수정 하나** — 그리고 왜

"상대 턴 · 창 닫힘" 에서 `_activation_actions` 를 부르는 분기를 하나 더하면
세트된 함정이 후보가 된다. 관문 셋이 이미 통상 마법 · 기동 효과를
`NOT_TURN_PLAYER` 로 막으므로 (§5-3 의 아래 세 줄) **새지도 않는다.**

**그래도 하지 않았다.**

* 룰북이 그 자리를 **금지한다** (§5-3). 엔진이 구현하지 않은 타이밍을
  후보로 내는 것은 없는 권한을 만드는 일이다.
* 올바른 수정은 분기 하나가 아니라 **우선권 이양 절차**다 (페이즈 · 스텝의
  끝에서 창이 열려야 한다). 그것은 우선권 모델 확장이고 §16 이 범위 밖으로
  두었다.
* §17 이 적는다 — *"후보 생성 경로가 둘이라는 이유만으로 새로운 아키텍처를
  만들지 않는다."* 같은 규율을 반대 방향에도 적용했다.

### 7-3. 채택한 수정

```python
if self.priority.is_open and self.priority.holds(seat):
    allowed.append(PlayerAction.passing(actor=seat))
elif self.priority.is_open:
    # 🔴 **창은 열려 있다** — 다만 상대가 쥐고 있다. missing 이 없는
    # 유일한 보류 자리다: 빠진 규칙이 아니라 **순서**다.
    holder = self.priority.holder.seat
    withheld.append(WithheldAction(
        PlayerActionKind.PASS,
        f"응답 기회가 열려 있지만 지금은 P{holder} 의 차례입니다.",
    ))
elif seat != self.turn_player:
    withheld.append(WithheldAction(
        PlayerActionKind.PASS,
        "우선권이 열려 있지 않습니다.",
        missing="우선권을 여는 규칙 (Phase 2-F)",
    ))
```

`missing` 을 **채우지 않는 것이 의도다.** 그 자리에서 빠진 규칙은 없다 —
지금은 상대의 차례일 뿐이다. 없는 것을 빈 값으로 채우지 않는다.

---

## 8. 공유 계약 변경 여부

### 8-1. 변경한 것 / 변경하지 않은 것

| | 변경? |
|---|---|
| `LegalActions` 의 필드 · 타입 | **아니다** |
| `WithheldAction` 의 필드 · 타입 | **아니다** |
| `PlayerAction` · `PlayerActionKind` | **아니다** |
| `Duel.legal_actions` · `apply` · `advance` 의 서명 | **아니다** |
| `ActionValidator` · 관문 셋 | **아니다** |
| `GameState` · `EventJournal` · `EffectDefinition` · `EffectRef` 의미론 | **아니다** |
| 체인 · 우선권 · 타이밍 모델 | **아니다** |
| 새 enum · 새 모델 | **없다** (§5 의 여섯 단계를 기존 자리로 센다) |
| 🔴 **`allowed` 가 돌려주는 후보** | **아니다 — 한 건도 바뀌지 않았다** |
| 🔴 `withheld` 의 내용 | **그렇다** — 한 자리에서 항목이 하나 늘고 (11→12), 다른 자리의 **거짓 문장**이 사실로 바뀌었다 |
| `WithheldAction` 생성 자리 수 | 3 → **4** (`missing` 을 주는 것은 여전히 **셋**) |

### 8-2. 승인이 필요한가 — **아니다**

§9 가 승인을 요구하는 것은 "**공유 `PlayerAction` 계약이나 `Duel` API 를
변경해야 한다면**" 이다. 이번 수정은 어느 쪽도 바꾸지 않았다. 바뀐 것은
`withheld` 라는 **정보 칸의 내용**이고, 그 칸은 설계상 "읽는 쪽이 엔진이
무엇을 아직 못 하는가를 알아야 할 때 본다" 는 자리다.

🔴 **그리고 후보 목록은 한 건도 바뀌지 않았다** — §14 의 전후 비교에서 움직인
수가 **둘뿐**이다 (보류 11→12 · 침묵 1→0). `test_f03` 이 네 자리의
`allowed` 를 종류 집합으로 못 박는다.

---

## 9. 변경한 파일 및 함수

### `engine/duel.py` (+42 −0) — 생산 파일은 이것뿐이다

`git diff --stat` 실측: `engine/duel.py | 42 ++++++++`. 42줄 중 분기와
보류 생성이 **9줄**이고 나머지는 설명이다.

| 자리 | 변경 |
|---|---|
| `Duel._flow_actions` | 🔴 묶인 조건을 갈랐다 (`elif self.priority.is_open:` 분기 추가) · docstring 에 룰북 두 줄과 실측을 적었다 |

바꾸지 않은 것: `legal_actions` · `_activation_actions` · `_activation_gate` ·
`_withheld_board_actions` · `_attack_actions` · `apply` · `advance` — **한
줄도** 손대지 않았다.

### 바꾼 테스트 파일

| 파일 | 변경 |
|---|---|
| `tests/engine/test_legal_action_candidate_consistency.py` | **새 파일** — 39개 |
| `tests/test_duelstep_withheld_validation_audit.py` | `test_09` — 보류 자리 3 → **4** (이유 기록) |
| `tests/test_rule_not_implemented_code_audit.py` | 산문 자리 하나가 868 → **910** 으로 밀렸다 |

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0.

### 움직인 기존 핀 둘 — 그리고 왜

**① `test_duelstep_withheld_validation_audit.py::test_09`** — `engine/duel.py`
의 `WithheldAction` 생성 자리를 **셋**으로 못 박고 있었다. 6-S 가 묶인 조건을
가르면서 **넷**이 되었다.

이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 그 시점에 실제로 셋이었다.
🔴 **그리고 넷째 자리는 이 시험이 지적한 느슨함을 늘리지 않는다**: 그 시험이
세는 것은 "같은 칸(`missing`)이 자리마다 다른 출처에서 채워진다" 이고, 넷째
자리는 그 칸을 **채우지 않는다.** 그래서 `missing` 의 출처는 여전히 **셋**
이다. 갱신한 단언이 그 둘을 따로 센다 (자리 4 · `missing` 을 주는 자리 3).

**② `test_rule_not_implemented_code_audit.py::test_02`** — 산문 자리 하나의
**줄 번호**가 868 → 910 으로 밀렸다. `_flow_actions` 의 설명 42줄이 그 자리
**위**에 들어갔기 때문이다. 🔴 **산문 15 · 문자열 87 · 코드 자리는 하나도
바뀌지 않았다** — 바뀐 것이 줄 번호뿐이라는 것이 그 증거다. 이 핀이 줄 번호를
세는 이상 그런 이동은 **반드시 드러나야 하고**, 그것이 번호를 적어 둔 이유다
(3-F-11 · 6-K · 6-M 과 같은 결).

---

## 10. `GameState` 기반 행동 후보 전후 비교

→ §14 의 표.

---

## 11. 실제 `Duel.apply` 수직 실행 결과

§11 의 경로를 **한 자리에서 여섯 단계로** 센다 (`test_g01`). 🔴 후보는 손으로
만들지 않고 **생산 후보 목록에서** 가져온다.

| 단계 | 어디에 묻는가 | 실측 |
|---|---|---|
| ① `DISCOVERED` | `legal_actions(P0).allowed` | 발동 후보 **1건** |
| ② `VALIDATED` | 관문 셋 | **통과** |
| ③ `EXECUTION_READY` | 정의 · 조작 · `selections_for` | 조작 1개 |
| ④ `ACCEPTED` | `DuelStep.accepted` · `code` | `True` · `OK` · 체인 링크 **1** · `resolved_count` **0** |
| — | 🔴 이 자리에서 `EffectEvent` **0건** · 덱 그대로 | 접수 ≠ 해결 |
| ⑤ `RESOLVED` | 양쪽 패스 | `True` · `OK` · "해결했습니다" · 체인 **비워짐** (6-R) |
| ⑥ `STATE_VERIFIED` | `GameState` · `EventJournal` | 덱 −2 · 패 2 · `EffectEvent` `['55144522:e[0]']` (`applied` · `deltas` 둘 다 있음) |

### 11-1. 거절되면 판이 움직이지 않는다

세트한 턴의 함정을 직접 `apply` 에 넣으면 (`test_g02`):

```
accepted=False  code=RULE_NOT_IMPLEMENTED  "activate_effect 는 지금 허가된 행위가 아닙니다."
state_hash 변화 없음 · 체인 링크 변화 없음
```

### 11-2. 후보 전부를 실제로 적용했다

스물 자리의 후보 **44건**을 사본에서 `apply` 했다 — **거절 0건**
(`test_g03`). 후보 목록이 거짓말을 하지 않는다는 가장 강한 검사다.

---

## 12. `GameState` 및 `EventJournal` 결과

| 측정 | 결과 |
|---|---|
| 후보 생성이 판을 바꾼 상태 | **0 / 20** (`state_hash` + `randomness.draws`) |
| 후보를 20번 만들었을 때 기록이 자란 건수 | **0** (`test_e06`) |
| 접수만 된 발동이 남긴 `EffectEvent` | **0** |
| 해결된 발동이 남긴 `EffectEvent` | 정확히 하나, `applied` · `deltas` 둘 다 있음 |
| 역순 해결 기록 (체인 2 → 체인 1) | `['5915629:e[0]', '55144522:e[0]']` |
| 불발된 링크의 `EffectEvent` | **없음** (6-R 유지) |

---

## 13. 기존 어니스트 · 6-O · 6-P · 6-Q · 6-R 회귀

🔴 전부 **생산 후보 목록에서 후보를 가져와** 끝까지 해결한다 — 손으로 만든
행위가 아니다.

| § | 기능 | Phase | 실측 |
|---|---|---|---|
| A | 어니스트 기동 효과 | 6-L | 후보 1건 → 해결 `OK` · MZONE → 패 · `EffectEvent` 1 |
| B | 강제 탈출 장치의 `MZONE → HAND` | 6-O | 후보 1건 (대상이 상대 몬스터) → 해결 `OK` · 상대 패 +1 · MZONE 비었다 |
| C | 벌금의 패 2장 | 6-P | 후보 **3건** · 각 대상 **2장** · 세 조합이 서로 다르다 → 해결 `OK` · 패 −2 |
| D | 세트된 일반 함정 | 6-Q | 세트한 턴 후보 **0** → 다음 내 턴 후보 1건 → 해결 `OK` · 상대 패 +2 |
| D | 상대 턴 체인 2 · 역순 해결 | 6-Q · 6-R | 체인 2 를 **상대의 후보 목록에서** 가져온다 → 링크 2 → 역순 기록 → 체인 비워짐 |
| E | 불발된 체인의 정리 | 6-R | 패스 `accepted=True` · `code=CANDIDATE_NOT_ELIGIBLE` · 체인 비워짐 |

기존 기능을 비활성화해 새 테스트를 통과시킨 자리는 **없다.**

---

## 14. 실행 가능성 전후 비교 (§14 의 열네 지표)

같은 측정 스크립트를 HEAD `c362a0f` 의 `engine/duel.py` 와 고친 판에서 각각
돌렸다. 🔴 `git checkout` 을 쓰지 않았다 — 작업 트리의 파일을 **메모리에
들고** HEAD 판을 잠깐 써 넣은 다음 되돌리고 바이트가 같은지 `assert` 했다.

측정 범위: §7 의 상태 **스물** (A~G), 후보 **44건**, 열거 3,500여 건.

| § | 지표 | 전 | 후 | 차이 |
|---|---|---|---|---|
| 1 | 생성된 전체 행동 후보 수 | 44 | 44 | **0** |
| 2 | 판정을 통과한 후보 수 | 44 | 44 | 0 |
| 3 | `UNKNOWN` 인 후보 수 | **0** | **0** | 0 |
| 4 | `INVALID` 인 후보 수 | **0** | **0** | 0 |
| 5 | 실행 구현이 존재하는 후보 수 | 44 | 44 | 0 |
| 6 | `apply` 에서 접수된 후보 수 | 44 | 44 | 0 |
| 7 | `GameState` 변경이 검증된 행동 수 | 41 | 41 | 0 |
| 8 | 후보 생성의 거짓 양성 사례 수 | **0** | **0** | 0 |
| 9 | 후보 누락의 거짓 음성 사례 수 | **0** | **0** | 0 |
| 10 | `EffectRef` · 인스턴스 연결 오류 수 | **0** | **0** | 0 |
| 11 | 체인 접수와 해결 결과 불일치 수 | **0** | **0** | 0 |
| 12 | 기존 실제 효과 실행 | 5/5 성공 | 5/5 성공 | 0 |
| 13 | 6-T 에 사용 가능한 최소 행동 수 | **14장** | **14장** | 0 |
| 14 | 남아 있는 구조적 BLOCKER | §17 | §17 | — |
| — | 🔴 **보류(withheld) 항목 수** | **11** | **12** | **+1** |
| — | 🔴 **침묵 상태 수** | **1** (`D2`) | **0** | **−1** |
| — | 관문이 막은 발동 (고를 수 있는 자리) | 9 (1:5 · 2:1 · 3:3) | 9 | 0 |
| — | 네 번째 판정자가 막은 발동 | 3 | 3 | 0 |

### 🔴 실제 실행 가능한 행동 수의 증가 — **0건**

§14 가 적은 대로 그렇게 기록한다. 이 Phase 는 새 효과도 새 조작도 추가하지
않았고, 후보 목록을 **한 건도** 넓히거나 좁히지 않았다. 줄어든 것은
**이유를 말하지 않는 자리**다 (침묵 1 → 0, 거짓 문장 1 → 0).

🔴 **테스트 수의 증가(39개)를 듀얼 능력 증가로 읽지 않는다.** 늘어난 것은
측정이고, 그 측정이 말하는 결론은 "후보 생성 경로가 이미 정합하다" 다.

---

## 15. Agent 및 `DuelRunner` 결과

| 호출자 | 어떤 목록을 쓰는가 | 실측 |
|---|---|---|
| `DuelRunner.step` | `duel.legal_actions(duel.to_act)` | 실제 듀얼 3판 · 거부 **0건** |
| `Simulator` (3자리) | `legal_actions` (후보에 있는지 먼저 본다) | 6-R 그대로 |
| `ComboPlanner` | 🔴 **엔진 후보를 쓰지 않는다** | §16 |
| `/combo` | `ComboPlanner` | §16 |

`to_act` 는 창이 열렸으면 쥔 사람, 아니면 턴 플레이어다. 그래서 창이 닫혀
있을 때 `to_act` 는 **언제나 턴 플레이어**이고, 네 번째 판정자가 막는 자리를
`DuelRunner` · `Simulator` 는 애초에 묻지 않는다.

---

## 16. 🔴 §12 — Phase 6-T 를 위한 최소 인터페이스 (실측)

**이번 Phase 는 `/combo` 를 한 줄도 바꾸지 않았다.**

### 16-A. 실제 `GameState` 생성 — **된다**

`GameState.create` 의 서명을 실측하면 **필수 인수가 하나도 없다**
(`decks` 의 기본값이 `((), ())` 다). 패만 있어도 판을 만들 수 있다.

```
repository  기본값 None      decks       기본값 ((), ())
extra_decks 기본값 None      life_points 기본값 8000
turn_player 기본값 0         seed        기본값 None
shuffle     기본값 False
```

🔴 다만 `decks=None` 을 주면 `TypeError` 다 — "주지 않았다" 와 "비었다" 를
가르지 않는다. 6-T 가 `decks` 를 **명시**해야 한다.

### 16-B. 패만 주어졌을 때 부족한 정보

| 칸 | 지금 | 6-T 가 결정해야 하는 것 |
|---|---|---|
| 덱 구성 | 빈 덱으로도 판이 선다 | 🔴 드로우하는 효과가 **덱 장수를 조건으로 본다** (욕망의 항아리: 2장 이상). 임의의 덱을 꾸미면 **거짓 성공**이 된다 |
| 턴 플레이어 · 페이즈 | 기본값 있음 | 메인1 · 선공으로 둘 것인지 명시 |
| 필드 · 묘지 · 제외 | 비어 있음 | `/combo` 의 `board:` 입력을 어디까지 받을 것인지 |
| 효과 사용 이력 | `rule_uses` 비어 있음 | 세트한 턴 제약이 "세트 기록" 을 보므로 **첫 턴 세트는 그 턴에 발동 불가** |
| 상대 상태 | 비어 있음 | 상대 패 장수를 조건으로 보는 카드가 있다 (의적의 입문서) |

### 16-C. 행동 후보 — **얻을 수 있다** (실측)

패 `[욕망의 항아리, 욕망의 선물]` · 덱 40장 · 메인1 · 턴 1:

```
후보 4건: ACTIVATE_EFFECT · END_PHASE · SET_SPELL_TRAP
발동 후보 1건
```

### 16-D · 16-E. 실행과 상태 전이 — **된다** (실측)

```
apply  -> accepted=True  code=OK
해결   -> accepted=True  code=OK  "체인1 P0 55144522:e[0] 를 해결했습니다."
P0 패 3장 · 덱 38장 · 효과 기록 ['55144522:e[0]']
🔴 다음 행동 탐색 가능: 후보 6건
```

### 16-F. 탐색 재사용

`DuelRunner` 와 `Simulator` 가 **그대로 쓸 수 있다** (`Simulator.fork_after`
가 사본에 묶인 새 시뮬레이터를 돌려준다). `ComboPlanner` 는 쓸 수 없다 —
아래.

### 16-G. 🔴 `ComboPlanner` 는 **엔진을 부르지 않는다** (실측)

| 측정 | 결과 |
|---|---|
| `deck/planner.py` 가 import 한 `engine` 모듈 | **`engine.effect.library` 하나** |
| `legal_actions` · `apply` · `validate` · `create` · `start` 호출 | **전부 없음** |
| `deck/` 전체에서 `Duel` · `GameState` · `PlayerAction` 의 **코드** 사용 | **0회** (산문에만 나온다) |
| `app/` 의 `.accepted` 사용 | **0회** (6-R 실측) |

🔴 **그리고 그 사실이 이미 표시에 정직하게 적혀 있다.** `app/discord_bot.py`
의 `ComboVerdict` 는 최고 판정이 `GROUNDED_UNEXECUTED` ("근거 있음 · 🔴 실행
검증 안 됨") 이고, docstring 이 *"`VERIFIED` 와 `PARTIALLY_VERIFIED` 가
없는 것이 의도다 — `ComboPlanner` 는 엔진을 실행하지 않는다"* 라고 적는다.
§20 이 요구한 "검증된 행동과 미지원 행동 구분" 은 **표시 계층에 이미 있다.**

### 16-H. 등재 범위

| 측정 | 수 |
|---|---|
| `EFFECT_LIBRARY` 등재 카드 | **17장** |
| 그 중 `executable` | **14장** |

---

## 17. 남아 있는 구조적 BLOCKER

### 17-1. 🔴 **새로 이름을 붙인 BLOCKER — 우선권 이양의 뒷절반**

룰북 `TURN PLAYER'S PRIORITY` 의 마지막 줄이 **둘**을 적는다.

> *"After a card's activation, **and at the end of each phase or step**,
> Priority passes to the opponent."*

엔진은 **앞쪽만** 구현했다.

| 룰북 | 엔진 | 실측 |
|---|---|---|
| 카드 발동 뒤에 우선권이 넘어간다 | 🟢 `ResponseWindow` 가 열린다 | 발동 뒤 `priority.is_open` 참 |
| **페이즈 · 스텝의 끝에** 우선권이 넘어간다 | 🔴 **없다** | 상대가 `END_PHASE` 를 해도 `priority.is_open` 거짓 · 후보 0 |

**결과**: 상대 턴에 세트된 함정은 "상대가 무언가 먼저 발동해 줄 때" 만 닿는다.
6-Q 가 연 길의 절반이 실제 듀얼 루프에서 막혀 있다.

🔴 **6-S 는 고치지 않는다** — 우선권 모델 확장이고 §16 이 범위 밖으로 두었다.
`test_i01` 이 룰북 원문과 엔진의 실제 동작을 **둘 다** 재어서 남긴다 (그
단언이 깨지면 이 BLOCKER 가 풀렸다는 뜻이다).

### 17-2. 🔴 조용한 보류 — 관문이 막은 발동의 이유가 없다

`_activation_actions` 가 관문에서 걸린 후보를 **이유 없이 버린다.** 실측:
고를 수 있는 자리에서 관문이 막은 발동이 **9건** (관문 1 이 다섯 · 관문 2 가
하나 · 관문 3 이 셋) 이고, `withheld` 에 `ACTIVATE_EFFECT` 로 남은 것은
**0건**이다.

Phase 6-R 이 처음 기록했고, 6-S 가 **수를 셌다** (`test_i02`).

🔴 **고치지 않는다** — `withheld` 에 후보마다 항목을 넣는 일은 `legal_actions`
의 공유 계약을 늘린다 (목록 크기가 바뀐다). §16 이 직접 차단이 아닌 한
수정하지 않는다고 적었고, 이번 결함은 그것 없이도 전부 측정할 수 있었다.

### 17-3. 그대로 남은 것

| BLOCKER | 상태 |
|---|---|
| STRUCTURAL-34 의 나머지 (응답 창이 **누구에게** 가는가) | 그대로 — §17-1 과 같은 뿌리 |
| STRUCTURAL-35 (`TimingWindow` 가 사건 하나만 담는다) | 그대로 |
| STRUCTURAL-36 (`TimingOutcome.chain` 의 채택 주체 없음) | 그대로 — 🔴 이 경로에 **없다** (6-R §7-2 가 확인) |
| STRUCTURAL-15 | 이번 경로에 닿지 않는다 |
| TRIGGER 자동 발동 | 그대로 |
| `activate_card` · `special_summon` 의 규칙 계층 | 그대로 (`withheld` 가 이유를 댄다) |
| 효과 사용 횟수 제한 · 전체 소환 조건 | 그대로 |

---

## 18. 타깃 · 통합 · 관련 회귀 테스트 결과

→ 부록의 실행 기록.

### 변이 시험 — 내 수정에 변이를 넣고 내 시험이 잡는지

변이 **8개**를 하나씩 `engine/duel.py` 에 넣고
`tests/engine/test_legal_action_candidate_consistency.py` 와
`tests/test_duelstep_withheld_validation_audit.py` 를 돌렸다. 변이가 적용된
동안 다른 테스트를 돌리지 않았고, 끝나고 원본과 바이트가 같은지 `assert`
했다.

| 변이 | 결과 |
|---|---|
| M1 갈랐던 조건을 다시 묶는다 (**6-S 전의 코드**) | 죽었다 |
| M2 새 분기가 창이 **닫힐** 때 쓰인다 | 죽었다 |
| M3 새 분기의 이유에 쥔 사람을 적지 않는다 | 죽었다 |
| M4 새 분기가 "열려 있지 않다" 고 적는다 (**거짓 문장 복원**) | 죽었다 |
| M5 새 분기가 `missing` 을 채운다 | 죽었다 |
| M6 새 분기가 보류 대신 **허가**를 낸다 (거짓 양성) | 죽었다 |
| M7 옛 분기의 `missing` 을 지운다 | 죽었다 |
| M8 창을 쥔 쪽에게도 보류를 더한다 | 죽었다 |

**8개 중 8개를 잡았다.** M1·M4 는 고치기 전의 실제 코드이므로 이 시험이
**되돌림을 막는다.**

---

## 19. 완료 수준

### 수준 3 — 실제 행동 실행 경로 검증 **달성**

| §19 수준 3 항목 | 근거 |
|---|---|
| 실제 `legal_actions` 후보를 선택한다 | §11 ① · §13 (전부 생산 목록에서) |
| 기존 `ActionValidator` 를 통과한다 | §11 ② · §4-2 |
| `Duel.apply` 에서 행동이 정상 접수된다 | §11 ④ · §11-2 (44/44) |
| 필요한 체인 절차를 진행한다 | §11 ⑤ · §13-D |
| 지원되는 효과나 행동을 실제로 해결한다 | §11 ⑤ · §13 |
| `GameState` 와 `EventJournal` 을 검증한다 | §11 ⑥ · §12 |
| 기존 마법 · 함정 · 몬스터 효과 회귀를 통과한다 | §13 (5/5) |
| 6-T 에서 재사용 가능한 최소 경로를 확인한다 | §16 |

### 수준 2 — 후보 생성 및 판정 정합성 개선 **달성**

확인된 최소 결함(침묵 · 거짓 문장)을 고쳤고, 불법 행동을 실행 가능으로
표시하지 않으며 (거짓 양성 0), 합법적 행동을 부당하게 누락시키지 않는다
(거짓 음성 0). `PlayerAction` 계약과 체인 · 우선권 · 타이밍 의미론은 그대로다.

### 수준 1 — 행동 후보 계약 감사 **달성**

§2 · §3 · §4 · §5 · §16.

🔴 **그리고 §19 의 마지막 두 줄을 그대로 적용한다.**

> *"실제 코드 변경 없이 이미 정상적인 실행 경로가 확인됐다면 그 사실을
> 그대로 보고한다. 코드를 변경하지 않았다는 이유만으로 불필요하게 성공
> 수준을 낮추지 않는다. 다만 실제로 검증하지 않은 항목을 달성했다고
> 주장하지 않는다."*

후보 생성 → 판정 → 실행 경로는 **이미 정합했다.** 거짓 양성 0 · 거짓 음성 0 ·
연결 오류 0 · 중복 0 · 부작용 0 이고, 후보 44건 전부가 `apply` 에서 접수된다.
6-S 가 고친 것은 그 경로가 **자기 침묵을 설명하지 못하던 두 자리**다.

**공유 계약 변경으로 승인을 기다리는 상태가 아니다** (§8-2).

**다음 Phase 는 자동으로 시작하지 않는다.**

---

## 부록 — 실행 기록

모든 수는 `pytest` 의 **실제 종료 코드**와 마지막 줄을 그대로 적은 것이다
(§15 "pytest 의 실제 종료 코드를 확인한다").

### 1 · 2단계 — 타깃 · 통합

```
$ python3 -m pytest tests/engine/test_legal_action_candidate_consistency.py -q -p no:randomly
39 passed in 11.50s
exit 0
```

이 한 파일이 §15 의 1단계(타깃: `legal_actions` · `_activation_actions` ·
`ActionValidator` · `PlayerAction` · `EffectRef` · `UNKNOWN`·`INVALID` 전파 ·
중복·누락)와 2단계(통합: 후보 생성 → 선택 → `apply` → `DuelStep.accepted` →
체인 등록 → 해결 → `GameState` → `EventJournal`)를 같이 담는다 — 같은 판
위에서 재야 "후보로 생성됐다 / 합법이다 / 실행됐다" 의 구분이 의미를 갖기
때문이다.

절별 구성 (39개):

| 절 | 수 | 내용 |
|---|---|---|
| A | 3 | §2 정정 — 사설 보조 함수 · 외부 호출자 없음 |
| B | 3 | 관문 셋이 후보 생성과 실행에서 **공유**된다 · 셋이 서로 다른 것을 막는다 |
| C | 3 | 거짓 양성 **0** · 실행 구현 없는 후보 **0** · ADR-006 의 구분 |
| D | 5 | 거짓 음성 **0** · 측정 정정 둘 · 🔴 룰북 §82 대조 · 상대 턴 누수 없음 · 네 번째 판정자 대조 |
| E | 8 | §10 의 열 가지 안전성 |
| F | 4 | 🔴 고친 자리 — 침묵 0 · 거짓 문장 0 · `allowed` 불변 · 흐름의 책임 구분 |
| G | 3 | §11 수직 경로 여섯 단계 · 거절은 판을 바꾸지 않는다 · 후보 **44/44** 접수 |
| H | 7 | §13 회귀 — 어니스트 · 6-O · 6-P · 6-Q ×2 · 6-R · `DuelRunner` |
| I | 3 | 🔴 BLOCKER 를 재어서 남긴다 — 우선권 이양의 뒷절반 · 조용한 보류 · 보류 자리 넷 |

### 2단계 — 움직인 기존 핀 둘 (단독 실행)

```
$ python3 -m pytest tests/test_duelstep_withheld_validation_audit.py -q -p no:randomly
32 passed in 7.13s
exit 0

$ python3 -m pytest tests/test_rule_not_implemented_code_audit.py \
                   tests/test_unimplemented_rule_semantics_audit.py -q -p no:randomly
43 passed in 18.36s
exit 0
```

🔴 §15 의 실패 절차를 그대로 밟았다 — 실패 테스트를 **단독 실행**하고 (1),
원인을 분석하고 (2), 최소 수정하고 (3), 타깃을 재실행하고 (4), 관련 회귀를
돌렸다 (5).

### 3단계 — `tests/engine` 전체

```
$ python3 -m pytest tests/engine -q -p no:randomly
3497 passed in 370.35s (0:06:10)
exit 0
```

| | 6-R | 6-S |
|---|---|---|
| `tests/engine` | 3,458 | **3,497** (+39) |

🔴 그리고 **수정 전에도 한 번 돌렸다** — `_flow_actions` 를 고친 직후, 새
파일을 쓰기 **전**에 `3458 passed` (364.12s, exit 0). 즉 기존 3,458개 중
**하나도 깨지지 않았다.**

### 4단계 — 관련 루트 회귀 (50파일)

`legal_actions` · `WithheldAction` · `_flow_actions` 를 참조하거나
`engine.duel` · `agent.runner` · `agent.simulation` · `agent.search` ·
`agent.arena` 를 import 하는 루트 테스트 파일 전부다.

**첫 실행** (줄 번호 핀을 고치기 전):

```
$ python3 -m pytest $(cat s_rootset.txt) -q -p no:randomly
1 failed, 1204 passed in 1572.07s (0:26:12)
exit 1

FAILED tests/test_rule_not_implemented_code_audit.py::test_02_…
  ('engine/duel.py', 910)  ← 실제
  ('engine/duel.py', 868)  ← 핀
```

줄 번호가 밀린 것뿐이다 (§9 의 "움직인 기존 핀 둘 — 그리고 왜").

**최종 실행**:

```
$ python3 -m pytest $(cat s_rootset.txt) -q -p no:randomly
1205 passed in 1546.62s (0:25:46)
exit 0
```

**실패 0건.**

### 변이 시험

```
$ python3 scratchpad/s_mutate.py
=== 변이 8개 중 8개를 잡았다 ===
되돌림 확인: engine/duel.py 가 원본과 같다
```

### 전후 측정

```
$ python3 scratchpad/s_ba.py
----- BEFORE (HEAD c362a0f) -----     ----- AFTER (6-S) -----
METRIC 1 후보 = 44                     METRIC 1 후보 = 44
METRIC 8 거짓양성 = 0                   METRIC 8 거짓양성 = 0
METRIC 9 거짓음성 = 0                   METRIC 9 거짓음성 = 0
METRIC 보류 = 11                       METRIC 보류 = 12
METRIC 침묵 = 1 ['D2']                 METRIC 침묵 = 0 []
되돌림 확인: engine/duel.py 가 작업 트리 판과 바이트가 같다
```

🔴 움직인 수가 **둘뿐**이다. `git checkout` 을 쓰지 않았다 — 작업 트리의
파일을 메모리에 들고 HEAD 판을 잠깐 써 넣은 다음 되돌리고 바이트가 같은지
`assert` 했다. 변이가 적용된 동안 다른 테스트를 돌리지 않았다.

### 측정 환경

- 측정 날짜: 2026-10-16 ~ 17
- 시작 HEAD: `c362a0f` (Phase 6-R 마지막 commit) · 작업 트리 깨끗함
- 브랜치: `claude/pensive-goodall-te1egy`
- 무작위 순서 끄기: `-p no:randomly` (전 실행 공통)
- 같은 대규모 묶음을 반복하지 않았다 — 루트 회귀는 **원인을 고친 뒤 한 번**
  다시 돌렸고 (§15 "이미 통과한 장시간 테스트를 근거 없이 반복하지 않는다"),
  `tests/engine` 은 수정 직후와 새 파일 추가 뒤로 **두 번**이다 (각각 다른
  것을 증명한다).

---

## 부록 — Git 커밋

| commit | 내용 |
|---|---|
| `2ef071e` | `engine/duel.py` — 패스할 수 없는 두 이유를 가른다 |
| `47a9286` | 테스트 — 새 파일 39개 + 움직인 기존 핀 둘 |
| (이 보고서) | `docs/phase6s-legal-action-execution-consistency.md` |
