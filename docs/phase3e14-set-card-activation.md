# Phase 3-E-14 — `SET_ACTIVATION_MISSING` 감사와, 그 옆에서 찾은 자리

- 기준 커밋: `a7396b5` (Phase 3-E-13, STRUCTURAL-134 RESOLVED)
- 결론 한 줄: **`SET_ACTIVATION_MISSING` 자체는 아직 열려 있다.** 그 옆에
  이름이 붙어 있지 않던 자리가 하나 있었고, 그쪽은 닫았다.

---

## §3 · §4 — 감사: 세트된 카드가 후보가 아니었던 이유는 **층마다 달랐다**

측정으로 적는다 (`Q1`~`Q8`).

| 층 | 세트된 카드에 대해 | 막고 있었는가 |
|---|---|---|
| Action Space (`_activation_actions`) | **패만** 훑었다 | **그렇다 (A)** — 어떤 관문도 판정할 기회를 얻지 못했다 |
| `ActivationTimingChecker` | **`VALID`** — 스펠 스피드를 정확히 본다 | **아니다** |
| `ActionValidator` | `UNKNOWN` | 그렇다, 그리고 **그것이 옳다** (`INVALID` 이 아니다) |
| `EffectActivator.can_activate` | `UNKNOWN` (허가를 못 받음) | 검증기의 판정을 그대로 전한 것 |
| 실행 (`NormalSpellPlacement.place`) | `SpellActivationError` | **그렇다 (E)** — `HAND` 에서만 꺼낸다 |
| Set 상태 | `zone=SZONE` · `position=FACEDOWN` · `previous=HAND` | 보존된다 |
| Set **턴** | **어디에도 없다** | **그렇다 (C)** |
| 숨은 정보 | 컨트롤러는 보고 상대는 못 본다 | 누출 없음 |

§4 분류: **G — 여러 조건의 조합.** 그중 **B(Timing Gate)는 원인이 아니다** —
이것을 틀리게 적으면 엉뚱한 곳을 고친다.

### Set 턴을 셀 **모양은 이미 있다**

`RuleUsageRegistry` 의 키가 턴 번호를 담는다.

```
RuleUseKey     = (turn_number, player, action)
RuleCardUseKey = (turn_number, player, instance_id, action)
```

그런데 마법 · 함정 세트는 **아무것도 적지 않는다** — 소환권을 쓰는 몬스터
세트만 적는다 (`engine/set_card.py`, RULE-SUMMON-009). 즉
`SET_ACTIVATION_MISSING` 은 "판정 계층이 없다" 가 아니라 **"기록이 없다"** 다.

### 그리고 기록해도 **검증기에게 보여줄 길이 막혀 있다**

`ActionValidator` 는 `GameStateView` 만 읽는다 (ADR-007). 그 관측이 노출하는
rule-usage 는 **둘뿐**이다 — `normal_summons_used` 와 `attacks_used`. 세 번째를
더하려면 `GameStateView` 를 바꿔야 하고, **§1 이 그것을 금지한다.**

---

## §5 — 규칙을 읽자 세트 카드가 **한 덩어리가 아니었다**

repository 의 공식 룰북을 읽어서 갈랐다. 그리고 **이번까지 엔진이 한 번도
인용하지 않은 조항**이 하나 있었다.

| | 조항 | 세트한 턴을 세야 하나 |
|---|---|---|
| 세트한 **통상 마법** | **RULE-SPELLTRAP-012** | **아니다** |
| 세트한 **속공 마법** | RULE-SPELLTRAP-007 | 그렇다 |
| 세트한 **함정** | RULE-SPELLTRAP-009 | 그렇다 (+ 더 있다) |

> **RULE-SPELLTRAP-012** — "The Difference between Set Spell Cards and Set Trap
> Cards": "Spell Cards can be activated during the Main Phases **even in the
> same turn that you Set them** (except for Quick-Play Spell Cards). Setting
> them does not allow you to use them on your opponent's turn; they still can
> only be activated during your Main Phase."

이 한 문단이 세 가지를 **직접** 답한다.

1. 같은 턴 — **허락한다.** 그래서 세트한 턴을 셀 필요가 없다.
2. 상대 턴 — **금지한다.** `UNKNOWN` 이 아니라 `INVALID` 다.
3. 페이즈 — **메인 페이즈만.**

즉 세트한 통상 마법의 발동은 **패에서 발동하는 통상 마법과 판정에 필요한
정보가 똑같다.** 엔진은 그것을 `UNKNOWN` ("패가 아니라 SZONE 에서의
발동이다") 으로 적고 있었고, **그것이 거짓이었다.**

`grep` 으로 확인했다 — `RULE-SPELLTRAP-012` 는 `scripts/extract_rulebook.py`
의 목차에만 있었고 `engine/` 어디에도 인용된 적이 없다.

---

## §19 — 변경: 출발지가 둘이 되었다

| 파일 | 변경 |
|---|---|
| `engine/duel.py` | `_activation_sources` 신설 (패 + 마법 & 함정 존). `_place_activated` 신설 — 출발지가 배치 모양을 정한다 |
| `engine/spell_activation.py` | `SpellRevealed` 델타, `NormalSpellPlacement.reveal`, `REVEAL_FROM_ZONE` |
| `engine/action_validation.py` | `_is_set_normal_spell` · `_NOT_A_SET_NORMAL_SPELL` · `activation_is_set_card`. 세트 카드는 `ZoneHasFreeSlot(SZONE)` 를 지지 않는다. `IsTurnPlayer` 의 이유 문장이 두 갈래 |

새 엔진 0개, 새 `ActionKind` 0개, `GameStateView` 변경 0개, `agent/` 변경 0개.

### `reveal` 은 `place` 의 대칭이 아니다

`place` 는 `state.move` 로 존을 옮긴다. `reveal` 은 **옮기지 않는다** —
`CardInstance.set_position(FACEUP)` 하나다. 칸을 다시 잡으면 세트했던 자리가
달라져서 칸 번호를 읽는 카드가 거짓을 보게 된다. 실행으로 확인했다: 발동 뒤
`sequence` 가 그대로다.

해결 뒤 가는 길은 **공유한다** (`retire`: SZONE → 묘지). RULE-SPELLTRAP-002 의
마지막 문장이 출발지를 따지지 않기 때문이다.

### 출발지에서는 **거르지 않는다**

세트된 속공 마법과 함정도 `_activation_sources` 에 나온다. 관문이 그것을
`UNKNOWN` 으로 막는다. "보지도 않는 것" 과 "막혔다는 기록이 남는 것" 은 다른
사실이고, 뒤쪽이어야 다음 단계가 무엇인지 알 수 있다.

---

## §23 — 여덟 시나리오 (전부 실행으로 측정)

| # | 상황 | 후보 | validator | apply | 근거 |
|---|---|---|---|---|---|
| 1 | 패에서의 발동 (회귀) | O | `valid` | O | RULE-SPELLTRAP-001 · 002 |
| 2 | 세트한 통상 마법, **같은 턴** | **O** | **`valid`** | **O** | RULE-SPELLTRAP-012 |
| 3 | 세트한 통상 마법, 다음 턴 | O | `valid` | O | 같음 |
| 3b | 세트한 통상 마법, 엔드 페이즈 | X | `invalid` | X | RULE-SPELLTRAP-012 ("only during your Main Phase") |
| 4 | 세트한 통상 마법, **상대 턴** | X | `invalid` | X | RULE-SPELLTRAP-012 ("Setting them does not allow …") |
| 5 | 상대 턴 응답 창 | X | `invalid` | X | 같음 |
| 6 | 자기 턴, 체인 위, SS1 | X | `valid` | X (스펠 스피드) | RULE-CHAIN-004 |
| 7 | 잘못된 actor | X | `invalid` | X | 컨트롤러 |
| 8 | 세트 속공 마법 · 세트 함정 | X | **`unknown`** | X | RULE-SPELLTRAP-007 · 009 |

### §9 실제 Trace — 세트한 턴에 발동해서 끝까지

```
[SET]      zone=SZONE position=FACEDOWN turn=2   (칸 0)
[LEGAL]    ACTIVATE_EFFECT 후보 1개  source=#40
[ACTIVATE] zone=SZONE  seq=0 (그대로)  position=FACEUP   ← 옮기지 않았다
[CHAIN]    길이 1 · 창=response · 쥔 자리=P1            (RULE-CHAIN-001)
[RESOLVE]  체인1 P0 55144522:e[0] 해결
[AFTER]    묘지=[55144522]  SZONE=0  덱 20→18  패=2
```

### 세트한 **턴**을 요구하는 둘은 이유가 **서로 다르다**

| 카드 | `missing_rule` |
|---|---|
| 세트한 속공 마법 | `set-card-activation-timing (세트한 턴에는 …)` ← `SET_ACTIVATION_MISSING` |
| 세트한 함정 | `non-spell-activation-timing (함정 · 몬스터 효과의 발동 타이밍)` |

함정은 **더 넓은 이유**로 범위 밖이다. "세트한 턴만 세면 함정이 열린다" 는
거짓이고, 그 구분을 `test_10` 이 고정한다.

---

## §10 · §15 · §17 — 계약과 경계

- **파리티 유지** (Phase 3-E-13): 세트 장수 0 · 1 · 2 · 3 네 판에서 후보
  전부를 새 판에서 적용해 전부 수락 (`test_11`).
- **숨은 정보 누출 0**: 컨트롤러는 자기 세트 카드의 정의를 보고, 상대는
  `card_id=None` · `name=None` · `definition=None` 이고 **장수만** 본다.
  상대 자리에서는 후보도 되지 않는다 (`test_12`).
- **Evaluation 변경 0** · `agent/` 변경 0.

---

## §18 — Search: 순위 로직은 그대로, **행동 공간은 넓어졌다**

이것을 숨기지 않고 적는다. 세트한 통상 마법이 합법 후보가 되었으므로
"세트 → 발동" 이 **실제로 둘 수 있는 수**가 되었고, 그래서 궤적이 바뀐다.

| 측정 | 전 | 후 |
|---|---|---|
| 규칙 기반 정책의 최종 공격력 합 (16 씨앗) | 70,700 | **70,700 (한 점도 안 변했다)** |
| 붕괴 씨앗 (합 0) | 10 · 15 | **10 · 15 (그대로)** |
| 무작위 정책의 같은 합 | 9,600 | **13,300** |
| 전체 테스트 시간 | 177s | **366s** (대부분 `tests/agent`: ≈100s → 249s) |

**규칙 기반이 한 점도 안 움직인 것이 "순위 로직을 건드리지 않았다" 의
증거**다. 움직인 것은 아무 수나 고르는 정책의 궤적이고, 그 원인은 고를 수 있는
수가 늘었다는 것이다. `agent/` 에는 한 줄도 손대지 않았다.

**시간이 두 배가 된 것은 비용이다.** 세트한 마법을 다시 발동하는 길이 생겨
듀얼이 길어졌다 (욕망의 항아리가 더 자주 해결되어 덱이 더 돈다). 병리적
반복은 아니다 — 발동한 마법은 해결 뒤 묘지로 가므로 순환이 없다. 범위를 좁힐
필요가 있다면 그 판단은 사용자의 것이다.

---

## §24 · §25 — 테스트

### 전체

```
3480 passed, 4 skipped in 365.90s
```

기준선 3460 + 신규 20 = 3480. 실패 0, skip 4 는 기존 그대로.

신규 `tests/engine/test_set_card_activation.py` — **20개**

1. `test_01` 세트 상태는 보존되고 **세트한 턴은 적혀 있지 않다**
2. `test_02` Action Space 누락 — 출발지에 세트된 카드가 들어왔다
3. `test_03` **타이밍 관문은 막고 있던 쪽이 아니었다**
4. `test_04` `place` 는 패만 안다 / `reveal` 은 앞면을 다시 돌리지 않는다
5. `test_05` 세트한 턴의 발동 — 칸 번호 보존 · 체인 · 해결 · 묘지 · 덱
6. `test_06` 다음 턴도 같다
7. `test_07` 상대 턴 · 메인 페이즈 아님 → **`INVALID`** (2 경우)
8. `test_08` 응답 창에서도 SS1 은 올라가지 못한다 (turn_player ≠ 응답 자리)
9. `test_09` 꽉 찬 마법 & 함정 존이 **자기 칸의 카드**를 막지 않는다
10. `test_10` `UNKNOWN` 승격 없음 — 속공 마법과 함정의 **이유가 다르다**
11. `test_11` **파리티** (세트 장수 4가지)
12. `test_12` 숨은 정보 경계
13. `test_13` 패에서의 발동 회귀
14. `test_14` 새 ActionKind · 새 엔진 없음
15. `test_15` "세트된 카드" 의 정의를 직접 잰다

### 고의 위반 6건

| 위반 | 잡은 시험 |
|---|---|
| A 출발지에서 세트 카드를 다시 숨긴다 | 6개 |
| B 세트 카드의 정의에서 아이콘 검사를 뺀다 | `test_15` (처음엔 **못 잡았다**) |
| C 세트 카드에서 `IsTurnPlayer` 를 뺀다 | `test_07[상대 턴]` · `test_08` |
| D 세트 카드를 **옮겨서** 발동한다 | `test_05` (칸 번호) |
| E 앞면인 카드도 다시 돌린다 | `test_04` |
| F 세트 카드에서 메인 페이즈 요구를 뺀다 | `test_07[엔드 페이즈]` |

**B 가 내 코드의 실제 결함을 찾아냈다.** `_is_set_normal_spell` 이 처음에
"마법인가" 만 보았고, **속공 마법도 마법이므로 `True`** 를 냈다. 앞선 관문이
속공 마법을 따로 걸러내므로 결과로는 보이지 않았다 — 이중 방어다. 그래도
틀린 것은 틀렸다: 그 술어가 느슨하면 `ZoneHasFreeSlot` 면제와 `IsTurnPlayer`
이유 문장이 **엉뚱한 카드에** 붙고, 그것은 규칙을 거짓으로 적는 것이다.
`test_15` 로 술어를 직접 재서 잡고, `_NOT_A_SET_NORMAL_SPELL` 로 고쳤다.

### 수정한 기존 테스트 6건 (삭제 0 · skip 0)

| 테스트 | 틀렸던 가정 |
|---|---|
| `test_activation_gate_parity::test_02` | "판을 바꾸는 걸음의 이름은 `_placement.place(` 다." 출발지가 둘이 되어 `_place_activated(` 가 되었다. **주장(관문이 앞에 있다)은 그대로다** |
| `test_effect_action_space_audit::test_05c` | "**뒷면으로 세트한 통상 마법**의 발동은 모르는 것이다." RULE-SPELLTRAP-012 가 직접 답한다. 예를 **앞면** 마법으로 바꿨고 주장은 그대로다 |
| `test_priority_response_audit::test_04` | "실제 대국에서 창이 **한 번도** 열리지 않는다." 이 가정은 **Phase 3-E-11 부터 틀렸고**, `play` 의 궤적이 발동에 닿지 않아 살아 있었다. 지금 참인 더 강한 불변식(`to_act` = 창을 쥔 자리 / 없으면 턴 플레이어)으로 바꾸고 **두 분기가 모두 돌았는지까지** 센다 |
| `test_priority_response_audit::test_05` | 같은 이유. "언제나 반대쪽은 비어 있다" 를 "창이 닫혀 있는 동안" 으로 좁히고, 열린 걸음에서는 쥔 자리만 받는다를 센다 |
| `test_rule_based_ai::test_f_the_winner_now_depends_on_the_policy` | "9번의 대국이 **모두** LP 0 으로 끝난다." 8번은 그렇고 한 번(씨앗 4 · 무작위)이 덱아웃이다. 그 판도 LP 가 (4800, 400) 로 **움직였다** — 전투가 없어서가 아니다. 주장을 "LP 가 움직인다" 로 옮기고 덱아웃 횟수를 **세어서 고정**했다. 증인 씨앗도 4 → {1, 8} 로 다시 측정 |
| `test_rule_based_ai::test_f_greedy_is_not_the_best_play` | 무작위 쪽 합 9,600 → **13,300** 재측정. 규칙 기반 70,700 과 붕괴 씨앗은 그대로 |

---

## §14 · §20 — STRUCTURAL 상태

- **`SET_ACTIVATION_MISSING` — 여전히 열려 있다.** 이번 Phase 가 닫지 않았고,
  닫았다고 적지 않는다. 막는 이유가 바뀌지도 않았다.
- **새 STRUCTURAL ID 를 만들지 않았다.** repository 의 최대 번호는 134 이고,
  이번에 고친 것은 "조항이 답하는데 엔진이 모른다고 말하고 있었다" 는
  누락이다. `SET_ACTIVATION_MISSING` 이라는 이름이 이미 그 이웃을 가리키고
  있으므로 번호를 하나 더 만들 이유가 없다 (§20: 단순 누락에 ID 를 붙이지
  않는다).
- 기존 TODO 전부 유지: STRUCTURAL-34 · 124 · 128 · 131 · 133. 134 는 RESOLVED.

---

## §16 — 남은 SET 관련 문제 (이번 범위 밖)

| 이름 | 무엇이 모자라나 | 어디까지 왔나 |
|---|---|---|
| `SET_ACTIVATION_MISSING` | 세트한 **턴**의 기록 | 담을 그릇(`RuleUsageRegistry`)은 있고 쓰는 쪽이 없다. 그리고 검증기에게 보일 길이 `GameStateView` 에 없다 |
| `SET_ACTIVATION_TIMING` | 상대 턴에 창이 열리는 자리 (STRUCTURAL-34 의 나머지) | Phase Change · AFTER_CHAIN 우선권이 없다 |
| `SET_ACTIVATION_EXECUTION` | 함정 · 지속 · 필드의 발동 뒤 **필드에 남는** 모양 | `reveal` 은 "해결 뒤 묘지" 하나만 안다 |
| `SET_CARD_EFFECT_EXECUTION` | 함정 효과의 유발 타이밍 | 트리거 계층 없음 |
| 비용 | 비용 뒤 배치 실패의 되돌리기 | ADR-008 (등재 16개 전부 비용 없음 — 도달 불가) |

---

## §17 — 다음 Phase 후보 (하나)

**세트한 턴의 기록** — `RuleActionKind.SET_SPELL_TRAP` 을 `RuleUsageRegistry`
에 per-card 로 적고, "이 카드를 이번 턴에 세웠는가" 를 판정하는 자리를 만든다.

이번 감사가 그 설계를 **좁혀 두었다.**

- 담을 그릇은 이미 있다 — 키가 턴 번호를 담으므로 턴마다 지울 필요가 없다.
- `ActionValidator` 는 `GameStateView` 만 읽으므로 (ADR-007), 노출하지 않으려면
  판정하는 자리는 `Duel` 이어야 한다 — 체인과 스펠 스피드가 이미 그렇게
  처리되는 것과 같은 모양이다. `GameStateView` 를 바꿀지 말지가 그 Phase 의
  첫 질문이다.
- 그것이 열리면 **세트한 속공 마법의 자기 턴 발동**까지 간다. 상대 턴은
  STRUCTURAL-34 (창을 여는 자리) 가 남아 있으므로 그 다음이다.

그리고 함께 결정할 것: 이번 Phase 가 치른 **테스트 시간 2배**를 받아들일지,
아니면 탐색 쪽에서 좁힐지.
