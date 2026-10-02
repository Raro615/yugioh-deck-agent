# Phase 3-E-13 — STRUCTURAL-134 · `can_activate` / `activate` 일관성 감사와 해결

- 기준 커밋: `0120779` (Phase 3-E-12)
- 범위: 발동 관문의 **자리**와 **판**. 새 ActivationEngine 없음, 별도 response path 없음.
- 결과: **STRUCTURAL-134 RESOLVED.** 원인이 둘이었고 둘 다 고쳤다.

---

## §3 · §4 — 감사: 중복은 어디에 있었나

### 판정 로직은 **이미 한 벌**이었다

`EffectActivator.can_activate` 와 `EffectActivator.activate` 는 둘 다
`self._check(state, chain, action, selections, authorization)` 하나를 부른다
(`engine/activation.py:350`, `:389`, `:483`). 술어가 두 벌로 갈려 있는 것이
아니므로, §7 이 말한 "공통 validation predicate 를 추출" 은 **활성화 계층
안에서는 할 일이 없었다.**

### 어긋난 것은 **시점**이었다

| 부르는 곳 | 어느 판에서 | 카드는 어디에 |
|---|---|---|
| `Duel._activation_actions` → `can_activate` | 배치 **전** | 패 |
| `Duel._apply_activation` → `activate` | 배치 **뒤** | 마법 & 함정 존 |

`_check_condition` 은 `GameStateView.from_state(state, viewer=action.actor)` 를
새로 만들어 `definition.activation` 을 평가한다. 발동한 마법은
`NormalSpellPlacement.place()` 로 패를 떠나므로 (RULE-SPELLTRAP-002), **자기
패를 읽는 조건은 그 사이에 답이 뒤집힌다.**

§4 의 분류로는 **C/D** 다 — 후보가 넓은 것도 apply 가 좁은 것도 아니고, 같은
함수가 같은 종류의 정보를 **다른 시점에** 읽었고 그 사이에 판이 바뀌었다.

### 결정적 측정 — 배치 뒤의 판은 판정할 수 없는 판이다

| 카드 | 배치 전 `ActionValidator` | 배치 후 `ActionValidator` |
|---|---|---|
| 욕망의 항아리 (55144522) | `valid` | **`unknown`** |
| 리로드 (22589918) | `valid` | **`unknown`** |

이유는 `_activation_out_of_scope` 다 — 카드가 패에 없으면 "패가 아니라 … 에서의
발동이다" 로 범위 밖을 선언한다 (필드에서의 발동은 실제 규칙에서 적법하므로
`INVALID` 이 아니라 `UNKNOWN`). `can_activate(authorization=None)` 도 같다.

즉 **배치 뒤의 판에서는 지금 잘 되는 발동까지 전부 `UNKNOWN`** 이다. 그래서
Phase 3-E-3 은 `activate` 에 손으로 만든 허가를 넣어야 했다.

```python
authorization=ValidationResult.valid("legal_actions 가 허가한 발동입니다.")
```

이 문자열이 하는 일은 `EffectActivator._verdict` 가 **실제 검증기를 부르지
않게** 만드는 것이다. `apply` 는 그 뒤로 `ActionValidator` 를 한 번도 통과하지
않았고, 조건과 대상만 — 그것도 **바뀐 판에서** — 다시 보았다.

### 다른 관문은 이미 모두 배치 전이었다

`ActionValidator`, `ActivationTimingChecker`, `target_combinations`,
`selections_for` 전부 배치 전의 판을 읽는다. `activate` 안의 재검사 **하나만**
다른 판을 보고 있었다.

### 바깥 문이 하나 더 있다

`Duel.apply` 는 들어온 행위가 `legal_actions(action.actor)` 에 있는지부터
본다 (`engine/duel.py:622`). 그래서 후보가 아닌 행위는 발동 경로에 **닿지도
않는다.** STRUCTURAL-134 의 증상은 "후보였던 것이 그 뒤에서 거절되는" 경로
하나뿐이었다.

---

## §7 — 권위 있는 관문: 배치 **전**의 판

세 안을 재고 (iii) 을 골랐다.

| 안 | 내용 | 판단 |
|---|---|---|
| (i) | 후보 생성이 **배치한 클론**에서 `can_activate` 를 묻는다 | 기각. `legal_actions` 가 판을 바꿔 보게 되고, `apply` 는 여전히 검증기를 못 돌린다 |
| (ii) | `activate` 가 앞선 판정을 믿고 `_check` 를 건너뛴다 | 기각 — §5 금지 2 · 3 |
| (iii) | **관문을 배치 앞으로**, 그리고 한 함수로 | 채택 |

### RULE-SPELLTRAP-002 를 거스르지 않는다

조항은 이렇게 적는다.

> "To use a Normal Spell Card, announce its activation to your opponent,
> **placing it face-up on the field.** If the activation succeeds, then you
> **resolve** the effect written on the card. After resolving the effect,
> **send the card to the Graveyard.**"

- 조항은 "발동할 수 있는 마법" 을 **전제하고 시작한다** ("To use a Normal Spell
  Card, …"). 적법한가를 묻는 자리는 그 문장 앞이고, 조항이 정하는 순서에
  들어 있지 않다.
- 조항이 정하는 순서(**놓기 → 해결 → 묘지**)는 **그대로다.** 배치는 여전히
  해결보다 앞이고, 상대가 응답 기회를 받는 시점에도 카드는 이미 앞면으로
  필드에 있다 (RULE-CHAIN-001).
- "If the activation succeeds" 는 **무효화 여부**를 말하는 자리이고, 발동 조건을
  다시 보라는 뜻이 아니다. 이 엔진에는 무효화 계층이 아직 없다.

### 지금의 다섯 걸음

```
⓪ selections_for                ActionTarget → TargetSelection
① Duel._activation_gate         세 관문 — 판을 바꾸기 전에
② EffectActivator.activate      비용 · 체인 링크 · 대상
③ NormalSpellPlacement.place    패 → 마법&함정 존 (앞면)
④ ChainResolver.resolve_all     효과 해결      (_resolve_chain)
⑤ NormalSpellPlacement.retire   → 묘지         (_retire_pending)
```

`Duel._activation_gate` 하나가 세 관문을 세우고, `_activation_actions` 와
`_apply_activation` 이 **둘 다 그것을 부른다.**

```python
verdict = validator.validate(action)                     # 1. 규칙
if verdict.validity is not ActionValidity.VALID: return verdict
timed = ActivationTimingChecker(validator.view).check(   # 2. 스펠 스피드
    ActivationTiming(self.chain, self.priority), action)
if timed.validity is not ActionValidity.VALID: return timed
return self._activator.can_activate(                     # 3. 구현 · 조건 · 대상
    self.state, self.chain, action,
    selections=selections, authorization=verdict)
```

### 되돌리기가 사라졌다

①이 거절하면 판은 **한 번도** 바뀌지 않는다. `NormalSpellPlacement.restore`
가 필요했던 경우가 production 경로에서 없어졌다. rollback 계층을 만든 것이
아니라 **만들 필요를 없앤 것**이고, ADR-008 은 그대로 미뤄져 있다.

### §22 — 판정 중복과 실행 중복

- **판정은 두 번 해도 된다.** `_activation_gate` 는 판을 읽기만 하므로 몇 번
  불러도 같은 답이다. `apply` 가 `legal_actions` 를 **다시 돌리고** 그 안의
  관문을 통과한 행위에 대해 `_apply_activation` 이 관문을 한 번 더 지나는 것은
  중복이 아니라 **독립 검증**이다 — `apply` 가 호출자를 믿지 않는다는 뜻이다.
  그리고 그 판정이 `activate` 에 넘길 **실제 허가**를 만든다.
- **실행은 한 번만 한다.** 비용 · 체인 링크 · 배치는 `_apply_activation` 한
  자리에서만 일어난다. 이 Phase 가 실행 경로를 늘리지 않았다.

---

## 원인 ② — 조건이 자기 자신을 셀지 적지 않았다

①만 고치면 리로드가 **패에 자신 하나뿐일 때도 발동 가능**해진다. 그것은 공식
스크립트가 금지하는 것이다.

```lua
-- c22589918.lua (리로드) · s.target
if chk==0 then return Duel.IsPlayerCanDraw(tp)
    and Duel.IsExistingMatchingCard(
        Card.IsAbleToDeck, tp, LOCATION_HAND, 0, 1, e:GetHandler()) end
```

마지막 `e:GetHandler()` 가 **제외 카드**다. 조건은 "자신 패에 1장 이상" 이
아니라 "**리로드 말고** 자신 패에 1장 이상" 이다. 엔진의 정의가 그 인자를
옮기지 않았다.

> 출처는 공식 스크립트 하나다. 리로드의 실제 재정을 **추측하지 않았다** —
> `data/rulings/ocg/5849.json` 의 공식 보충이 확인해 주는 것은 다른 쪽이다
> ("デッキが０枚の状況でも発動できます" → 막는 것은 덱 장수가 아니다).

### `ZoneCountAtLeast.excluding_source`

```python
ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.HAND, 1, excluding_source=True)
```

- 기본값 `False`. 켜지 않은 7개 정의의 `canonical_state()` 와 `to_dict()` 는
  **한 글자도 바뀌지 않는다** (켤 때만 키가 붙는다).
- `context.source` 가 없거나 그 카드가 관측에 보이지 않으면 **`UNKNOWN`** 이다.
  세는 수를 모르는 것이고, 모르는 것을 참으로 읽지 않는다.

### ②가 STRUCTURAL-134 의 일반형이다

> **배치 전과 후에 답이 뒤집히는 조건은, 자기 자신을 셀지 적지 않은 조건이다.**

제대로 옮긴 조건은 자리를 옮겨도 뒤집히지 않는다. 그래서 ②를 고친 뒤에는
"어느 판이 맞는가" 라는 질문 자체가 리로드에서 사라진다 — ①의 가치는 그
질문을 **다른 카드에서도** 생기지 않게 만드는 구조에 있다.

### 등재된 16개 정의 전수 확인

자기 쪽 패를 읽는 발동 조건은 **둘**뿐이다.

| 카드 | 조건 | 조치 |
|---|---|---|
| 리로드 (22589918) · 속공 마법 | 자신 HAND 1장 이상 | `excluding_source=True` **추가** |
| 벌금 (92595643) · **함정** | 자신 HAND 2장 이상 | 변경 없음 |

벌금은 **함정**이다. 세트가 앞서므로 (RULE-SPELLTRAP-009) 발동할 때 이미 마법 &
함정 존에 있고, `e:GetHandler()` 가 `LOCATION_HAND` 에 들어갈 일이 구조적으로
없다. 그 추론이 **카드 종류 때문**이고 배치 순서 때문이 아니라는 점을 주석에
적어 두었다 — 패에서 발동하는 카드에 그 추론을 옮기면 리로드의 버그를
반복한다. (벌금은 함정이므로 이번 Phase 의 후보 범위 밖이고, 실행으로 확인한
결과 어떤 패 구성에서도 후보가 되지 않는다.)

---

## 변경 목록

| 파일 | 변경 |
|---|---|
| `engine/duel.py` | `_activation_gate` 신설. `_activation_actions` · `_apply_activation` 이 둘 다 부른다. `_apply_activation` 이 **관문 → 발동 → 배치** 순서로. 손으로 만든 허가 제거. `place` 실패 처리 추가 |
| `engine/condition/model.py` | `ZoneCountAtLeast.excluding_source` |
| `engine/effect/library.py` | 리로드 `excluding_source=True` + 출처 기록. 벌금 주석 보강 |
| `tests/engine/test_activation_gate_parity.py` | **신규 22개** |
| `tests/engine/test_response_candidates.py` | `test_11` · `test_13` 가정 수정 |
| `tests/engine/test_activation_response_window.py` | `test_l` 설명 수정 |

### 기존 테스트를 고친 이유

| 테스트 | 잘못된 가정 |
|---|---|
| `test_response_candidates::test_11` | "리로드의 조건은 **자신 패에 1장 이상**이다." 공식 스크립트는 `e:GetHandler()` 를 적는다. 그 가정 위에서 "후보인데 거절된다" 를 **정상으로 고정**하고 있었다 |
| `test_response_candidates::test_13` | "스펠 스피드 비교는 `_activation_actions` 안에 적혀 있다." 관문이 거기 있었던 것이 STRUCTURAL-134 의 원인이었다. 주장(=`VALID` 만 통과)은 그대로 두고 **읽는 자리**를 공용 관문으로 옮겼다 |
| `test_activation_response_window::test_l` | "거절되면 놓았던 카드가 **패로 돌아간다**." 지금은 **떠나지 않는다.** 단정은 한 줄도 고치지 않았고 설명만 고쳤다 |

---

## 테스트

`tests/engine/test_activation_gate_parity.py` — 22개 (실제 카드로 측정)

1. `test_01` 관문은 **한 곳**에만 적혀 있다 (양쪽이 자기 관문을 세우지 않는다)
2. `test_02` `apply` 가 자기에게 허가를 써 주지 않는다 + 관문이 배치보다 앞
3. `test_03` **§10 파리티** — 후보 전부를 새 판에서 적용 (5가지 패 구성)
4. `test_04` 배치 뒤에는 판정이 불가능하다 (측정)
5. `test_05` **§11 부정 6경우** — 후보 아님 · 스스로 거절 · 판 그대로
6. `test_06` 체인이 쌓이면 스펠 스피드 1 은 후보도 적용도 아니다
7. `test_07` **§13 체인 링크 2** — 두 장이 필드에 · 해결 · 묘지 · 덱 변화
8. `test_08` 리로드가 자기를 세지 않는다
9. `test_09` 완전히 옮긴 조건은 카드가 움직여도 뒤집히지 않는다 (덜 옮긴 쪽과 대조)
10. `test_10` `excluding_source` + `source` 미지 → `UNKNOWN`
11. `test_11` 켜지 않은 조건의 직렬화는 그대로
12. `test_12` 평소의 발동 한 장이 처음부터 끝까지 그대로
13. `test_13` 관문은 **첫 거절을 그대로** 돌려준다 (`INVALID` · `UNKNOWN` 둘 다)

### 전체

```
3460 passed, 4 skipped in 177.44s
```

기준선 3438 (= 3436 + 가정이 틀렸던 2) + 신규 22 = 3460. 실패 0, skip 4 는
`cards.cdb` 와 무관한 기존 skip 그대로다.

### §18 — 고의 위반

| 위반 | 주입 | 잡은 시험 |
|---|---|---|
| A | 관문이 `ActionValidator` 의 거절을 무시한다 | `test_13` (처음엔 **못 잡았다** — 아래) |
| B | 배치를 발동 앞으로 되돌린다 | `test_02` |
| C | 리로드의 `excluding_source` 를 뺀다 | `test_05[조건 거짓]` · `test_08` · `test_09` · `test_response_candidates::test_11` |
| D | `apply` 가 손으로 만든 허가를 쓴다 | `test_02` |
| E | 타이밍 관문이 `UNKNOWN` 을 통과시킨다 | `test_response_candidates::test_13` · `test_effect_activation_path::test_11` |

**A 를 처음에 아무 테스트도 잡지 못했다.** 안쪽의 `EffectActivator._verdict`
가 같은 허가를 다시 보고 독립적으로 막기 때문이다 (`permits_execution` 이
아니면 `UNAUTHORIZED`). 결과만 보면 양쪽 다 거절이므로 구별되지 않았다.
구별되는 것은 **이유**이고 — 관문이 제대로 서 있으면 거절의 코드와 문장이
검증기의 것이다 — 그것을 재는 `test_13` 을 **새로 쓴 뒤** 재주입해서 잡았다.
숨기지 않고 적는다: 이중 방어였고, 지금은 "누가 막았는지" 까지 고정된다.

**B 는 소스 수준 불변식만 잡는다.** 원인 ②를 고친 뒤에는 등재된 16개 효과 중
배치 순서로 답이 달라지는 조건이 **하나도 없기 때문**이다. 순서를 되돌려도
오늘의 카드로는 결과가 같다. 즉 ①의 값은 오늘의 출력이 아니라 **`apply` 가
실제 검증기를 돌릴 수 있게 되었다는 구조**에 있고, 그것을 `test_02` 와
`test_04` 가 고정한다.

---

## §14 · §15 — 탐색 · 평가

- **평가는 건드리지 않았다.** `agent/evaluation.py` 변경 0건.
- **후보 집합의 변화는 한 자리뿐이다** — 패에 리로드 **하나뿐**일 때 후보
  1 → 0. 그 발동은 예전에도 `apply` 에서 거절되었으므로 **둘 수 있었던 수가
  줄어든 것이 아니라, 둘 수 없었던 수가 목록에서 빠진 것**이다.
- `agent/simulation.py` · `SearchPolicy` 변경 0건. AI 대 AI 포함 전체 녹색.

---

## 남은 것 (이번 범위 아님)

1. **세트한 턴 추적** — `SET_ACTIVATION_MISSING`. 세트한 속공 마법 · 함정의
   발동이 범위에 들어오면 필요하다 (RULE-SPELLTRAP-007 · 009).
2. **무효화 계층** — "If the activation succeeds" 의 나머지 절반.
3. **비용 뒤 실패** — `place` 가 실패하는 경로에 비용 되돌리기가 없다
   (ADR-008). 등재된 16개 효과 전부 비용이 없어 지금은 도달 불가이고,
   `_apply_activation` 이 그 사실을 적어 두고 이유를 그대로 전한다.
4. **벌금(함정)의 조건** — 함정의 발동이 범위에 들어오는 날 다시 읽어야 한다.
   지금은 함정이 발동할 때 패에 없으므로 결과가 같다.
