# Phase 6-O — `OPERATION_RULINGS` 지식 범위 감사 및 실제 실행 차단 요인 개선

> **달성 수준: §17 수준 3 (실제 Duel 실행 능력 증가) 달성.**
>
> 🔴 **새로 실행되는 효과가 생겼다.** `강제 탈출 장치` (등재·실행 가능한
> **함정**)가 실제로 해결되고 대상 몬스터가 **주인의 패로 돌아간다** —
> 실측 `MZONE → HAND`, 상대 패 +1장. 6-O 전에는 해결 단계에서 멈췄다.
>
> 🔴 **규칙을 더한 것이 아니라 연결했다.** 룰북 한 줄과 그 귀결은 **이미
> 코드에 있었다.** 그 줄이 덮는 카드가 저장소에 **684장**인데 손으로 적힌
> 것이 **1장**이었다.

- 브랜치 `claude/pensive-goodall-te1egy` · 시작 HEAD `da93fc6`
- 작업 전 작업 트리 clean, 원격과 동일

---

## 1. 기존 `OPERATION_RULINGS` 의 실제 구조

### 1-1. 타입과 모양 (§4-A 1 · 2)

| 요소 | 위치 | 무엇 |
|---|---|---|
| `OperationRulingRegistry` | `engine/effect/ruling.py` | `card_id → CardRuleFacts` 표. `facts_for()` 가 없으면 **`None`** |
| `CardRuleFacts` | 같음 | 카드 한 장에 대해 **사람이 확인한 것들** |
| `RuleFact` | 같음 | 질문 하나의 답 — `UNKNOWN` 을 **담을 수 없다** |
| `RuleQuestion` | `engine/effect/semantics.py` | 질문 **일곱** |
| `RuleBasis` | `engine/effect/ruling.py` | 근거 **셋** (`rulebook` · `card_text` · `official_ruling`) |
| `OPERATION_RULINGS` | `engine/effect/library.py` | 그 표의 **인스턴스** — 손으로 적은 **18장** |

🔴 `RuleFact` 가 `UNKNOWN` 을 담을 수 없는 것이 이 계층의 설계다. "모른다"
는 사실이 아니라 **사실이 없는 것**이고, 그것은 표에 줄이 없는 것으로
표현된다.

### 1-2. 등록된 18장 (§4-A 2)

| 묶음 | 수 | 근거 |
|---|---|---|
| 통상 몬스터 (`normal_monster_facts`) | **1** | `RuleBasis.RULEBOOK` |
| 어니스트 (질문 하나만) | 1 | `RuleBasis.CARD_TEXT` |
| 마법 · 함정 (`restricts_others=False` 만) | 16 | `RuleBasis.CARD_TEXT` |

### 1-3. 호출 경로 (§4-A 4 · 5)

```
EffectExecutor._check_rule_gate          ← gated=True 조작만
  → ask_movement(ruling, question, instance)
      → BoardRuling.may → BoardRuling.explain
          ① 대상 카드 자신의 사실          ← facts_for(card_id)
          ② 판에 막는 것이 있는가           ← _interference (INTERFERENCE_ZONES 훑기)
      → TRUE 일 때만 이동한다
```

조립 자리는 `engine/spell_activation.duel_resolver` 하나다 (Phase 6-L 이
이었다). `build_executor` 는 이 지식을 **기본값으로 넣지 않는다** (ADR-006).

### 1-4. 미등록이 돌려주는 것 (§4-A 6)

| 상황 | 결과 |
|---|---|
| `facts_for` 가 `None` | `UNKNOWN` — "확인된 것이 없습니다" |
| 등록됐지만 그 질문은 없음 | `UNKNOWN` — "확인되지 않았습니다" |
| 판에 미등록 **앞면** 카드 | `UNKNOWN` — "그것이 막는지 알 수 없습니다" |
| 실행기 | `UNCHECKED_RULES` + `missing="return-to-hand-legality …"` |

---

## 2. 규칙 지식 출처 및 호출 경로

| 근거 | 무엇을 읽었는가 | 지금 쓰이는 곳 |
|---|---|---|
| `RULEBOOK` | `data/rules/structured/sd-rulebook-en-v10.json` 에서 뽑은 원문 두 줄 (`NORMAL_MONSTER_RULE` · `TOKEN_RULE`) | `normal_monster_facts` · `token_facts` |
| `CARD_TEXT` | 그 카드의 **공식 텍스트 전문** | 어니스트 + 마법·함정 16장 |
| `OFFICIAL_RULING` | `https://www.db.yugioh-card.com/yugiohdb/` | 🔴 **지금 쓰는 자리 0건** |

🔴 **`RuleBasis` 에 "짐작했다" 가 없다.** 적을 수 없으면 적지 않는다.

### 🔴 §4-A 7 — 규칙 데이터가 있는데 호출되지 않는 경로

**있다. 그것이 이 Phase 가 고친 것이다.**

`normal_monster_facts` 는 룰북 한 줄에서 **다섯 질문의 답과
`restricts_others=False` 를 전부 유도한다.** 그 유도는 2-AK 부터 코드에
있었다. 그런데 그것을 **부르는 자리가 손으로 적은 목록 하나**였고, 그
목록에 통상 몬스터가 **1장**뿐이었다.

---

## 3. 수집한 `UNKNOWN` 사례와 범주별 분류 (§5)

### 3-1. 측정 범위

- 저장소 카드 **14,127장 전수** 를 종류별로 세었다.
- 등재된 **실행 가능 효과 14건 전수** 를 "통상 몬스터만 깔린 판" 에서 돌렸다.
- 통상 몬스터 **표본 5장** 으로 어니스트 ① 의 판정·실행을 재었다.
- 🔴 **빈도를 추정하지 않았다** (§5 마지막 줄).

### 3-2. 카드 종류 분포 (전수)

| 종류 | 수 | 등록 |
|---|---|---|
| 통상 몬스터 전체 (`TYPE_MONSTER & TYPE_NORMAL`) | **722** | 1 |
| ├ 메인 덱 · 비펜듈럼 | **684** | **1** |
| ├ 펜듈럼 (메인 덱) | **38** | 0 |
| └ 엑스트라 덱 | **0** | — |
| `NORMAL` 을 가진 **비몬스터** | **0** | — |

### 3-3. 범주별 분류 (§5 A~G)

| 범주 | 사례 수 | 대표 근거 |
|---|---|---|
| **A** 공통 규칙 지식 누락 | **0** | 룰북 줄이 **이미 있었다** |
| **B** 공식 카드 재정 · 카드별 조건 누락 | 다수 (측정 안 함) | 효과 몬스터·마법·함정은 텍스트를 읽어야 한다 |
| **C** 🔴 **규칙 데이터는 있는데 실행 경로와 연결되지 않음** | **683장** | `normal_monster_facts` 가 1장에만 불린다 |
| **D** 규칙 판정은 가능한데 실행 구현이 없음 | **1** | 벌금 — `target_combinations` 가 `minimum>1` 을 열거하지 못한다 |
| **E** 행동 자체가 불법 | 0 | — |
| **F** 판단에 필요한 상태 정보 부족 | 1 | 가려진 카드 (`card_id=None`) — 올바른 동작 |
| **G** 기존 코드·테스트의 잘못된 전제 | **10** | §16-2 |

🔴 **선정한 것은 C 하나다.**

### 3-4. 구현 전 실측 — 통상 몬스터가 막는다

표본 5장. 상대 필드에 **앞면 통상 몬스터** 한 장:

| 카드 | 종류 | `BoardRuling` | 어니스트 ① | 위치 |
|---|---|---|---|---|
| 13번째 매장자 (32864) | `MONSTER·NORMAL` | `UNKNOWN` | `UNCHECKED_RULES` | MZONE |
| 워터 스피릿 (487395) | `MONSTER·NORMAL·TUNER` | `UNKNOWN` | `UNCHECKED_RULES` | MZONE |
| 갑옷 쥐 (549481) | `MONSTER·NORMAL` | `UNKNOWN` | `UNCHECKED_RULES` | MZONE |
| Temple of Skulls (732302) | `MONSTER·NORMAL` | `UNKNOWN` | `UNCHECKED_RULES` | MZONE |
| Doron (756652) | `MONSTER·NORMAL` | `UNKNOWN` | `UNCHECKED_RULES` | MZONE |

**5/5 전부 막혔다.**

---

## 4. 실제 실행 차단의 근본 원인

**룰북 한 줄이 코드에 있는데, 그 줄이 덮는 카드 집합에 연결되어 있지
않았다.**

> "Yellow Normal Monster Cards do not have effects, and have a description
> of them written here that does not affect the game."

이 줄에서 나오는 결론은 둘이고 **둘 다 이미 코드에 적혀 있었다.**

1. 스스로를 지키지 않는다 → 다섯 이동 질문에 `TRUE`.
2. 남을 막지 않는다 → `restricts_others=False`.

막던 것은 **지식의 부재가 아니라 연결의 부재**였다. 손으로 적은 목록에
이름이 없으면 그 카드가 "모르는 카드" 가 되었고, 통상 몬스터 683장이
거기 있었다.

---

## 5. 선정한 단일 최소 수정 대상

**"룰북이 통상 몬스터에 대해 답하는 것을 그 줄이 덮는 카드 전체에
적용한다."**

§6 의 열 조건 대조:

| # | 조건 | 판정 |
|---|---|---|
| 1 | 실제 Duel 실행을 차단한다 | 🟢 표본 5/5, 그리고 강제 탈출 장치 |
| 2 | 행동 실행 구현이 이미 있다 | 🟢 `return_to_hand` 는 6-L·6-M 이 완성했다 |
| 3 | 공식 규칙 근거가 명확하다 | 🟢 룰북 한 줄, 이미 인용되어 있다 |
| 4 | 특정 카드 예외가 아니다 | 🟢 카드 **종류**로 결정된다 (684장) |
| 5 | 기존 규칙 계층으로 표현된다 | 🟢 `CardRuleFacts` · `RuleBasis.RULEBOOK` 그대로 |
| 6 | 최소 변경으로 해결된다 | 🟢 **한 파일**, 함수 둘 |
| 7 | Engine V1 계약을 유지한다 | 🟢 공개 타입·결과 종류 변경 0 |
| 8 | GameState 전후 검증 가능 | 🟢 §11 |
| 9 | 잘못 허용하는 반례를 테스트할 수 있다 | 🟢 §10 |
| 10 | 콤보 플래너 연결에 도움 | 🟢 통상 몬스터가 깔린 판에서 탐색이 멈추지 않는다 |

---

## 6. 선택 이유 및 다른 후보와의 비교

| 후보 | 실행 영향 | 정확성 위험 | 변경 범위 | 선정 |
|---|---|---|---|---|
| **룰북 통상 몬스터 줄 연결** | **큼** (684장 · 효과 2건) | **낮음** (근거가 룰북 한 줄) | 1파일 | ✅ |
| 마법·함정 텍스트를 더 읽어 등록 | 중간 | 중간 (카드마다 전문을 읽어야 한다) | 데이터 확장 — §14 금지 | ❌ |
| 효과 몬스터에 답을 더함 | 중간 | **높음** (텍스트마다 다르다) | 데이터 확장 — §14 금지 | ❌ |
| 벌금의 다중 대상 (`minimum>1`) | 작음 (1건) | 낮음 | `target_bridge` — **규칙이 아니라 실행 구현**이다 | ❌ (§18) |
| 파괴 판정기 (`DestructionRuling`) | 큼 | **매우 높음** (내성·대체 효과) | 새 계층 — §14 금지 | ❌ |
| `restricts_others` 기본값 뒤집기 | 매우 큼 | **매우 높음** — 모르는 것을 허가로 바꾼다 | 1줄 | ❌ (§3-6) |

🔴 마지막 후보가 가장 작고 가장 위험하다. 그것을 하면 지금 막는 모든
UNKNOWN 이 사라지지만, **모든 지속 효과를 "없다" 로 선언하는 것**이다.
§3-6 · §9 · §18 이 금지한다.

---

## 7. 공식 규칙 및 카드 효과 근거

§7 의 일곱 질문:

| 질문 | 답 |
|---|---|
| 1. 공식 룰북의 일반 규칙인가 | 🟢 **그렇다** — 구조화 룰북의 원문 한 줄 |
| 2. 카드 텍스트에서 결정되는 조건인가 | 아니다 — 카드 **종류**가 결정한다 |
| 3. 공식 재정이 필요한 특수 상황인가 | 아니다 |
| 4. 게임 상태에 따라 달라지는가 | 🔴 **부분** — 카드 자신의 답은 상태와 무관하지만, 판의 간섭은 `_interference` 가 따로 본다. 둘을 섞지 않았다 |
| 5. 종류·영역 예외가 있는가 | 🟢 **있다** — 펜듈럼(38장)과 엑스트라 덱(0장)은 제외했다 (§7-1) |
| 6. 어느 단계인가 | 🟢 **효과 해결** (조작 관문). 발동 조건·비용이 아니다 |
| 7. 다른 규칙과 충돌하는가 | 아니다 — 손으로 적은 사실이 **앞선다** (§9-2) |

### 7-1. 펜듈럼을 제외한 근거

🔴 **추측이 아니라 이 저장소가 이미 적어 둔 사실이다.**
`core/card_model.py` 의 `Card.has_printed_effect` docstring:

> "통상 몬스터와 토큰은 아니다 (**통상 펜듈럼 몬스터는 펜듈럼 효과가
> 있으므로 예외**)."

실측으로도 맞는다 — 메탈포제 실버드는 `TYPE_NORMAL` 인데
`has_printed_effect is True` 이고, 13번째 매장자는 `False` 다. 룰북 줄의
"do not have effects" 가 펜듈럼에 성립하지 않으므로 **모른다로 남긴다.**

### 7-2. 엑스트라 덱을 제외한 근거

지금 **0장**이지만 조건을 적어 두었다. 엑스트라 덱 통상 몬스터가 생기는
날, "패로 되돌릴 수 있다" 를 룰북 한 줄에서 끌어내면 틀린다 (Phase 6-M
§4-2 가 룰북의 침묵을 근거로 그 반대를 적었다).

### 7-3. 토큰

`token_facts` 가 **다른 룰북 줄**로 따로 답한다. 6-O 가 건드리지 않았고,
`NOT_PLAIN_NORMAL` 이 `TOKEN` 도 막는다. (저장소에 토큰은 0장 — 6-M §4-3.)

---

## 8. 변경한 파일 · 함수 · 규칙 데이터

| 파일 | +/− | 무엇 |
|---|---|---|
| `engine/effect/ruling.py` | **+85 −3** | `NOT_PLAIN_NORMAL` · `rulebook_facts()` · `BoardRuling._facts_of()` |

**production 한 파일.** 그리고 🔴 **규칙 데이터는 한 줄도 더하지
않았다** — `OPERATION_RULINGS` 는 **18장 그대로**다 (§14 "모든
OPERATION_RULINGS 데이터 확장" 금지).

```python
def rulebook_facts(definition) -> "CardRuleFacts | None":
    if definition is None or definition.card_id <= 0:
        return None
    if not definition.is_monster:
        return None                      # 룰북 줄은 "Monster Cards" 라고 적는다
    if "NORMAL" not in definition.type_names:
        return None
    if NOT_PLAIN_NORMAL & set(definition.type_names):
        return None                      # 펜듈럼 · 토큰
    if definition.is_extra_deck:
        return None                      # 지금 0장이지만 적어 둔다
    return normal_monster_facts(definition.card_id, definition.name)


class BoardRuling:
    def _facts_of(self, card):
        if card.card_id is None:
            return None
        declared = self._registry.facts_for(card.card_id)
        if declared is not None:
            return declared              # 🔴 손으로 적은 것이 **먼저**
        return rulebook_facts(card.definition)
```

- 찾는 자리를 **하나로 모았다** — `explain` 과 `_interference` 가 둘 다
  `_facts_of` 를 부른다 (AST 로 센다). 6-N 이 같은 함정을 밟았다.
- 🔴 **새 모듈·새 타입·새 결과 종류 0개.** `RuleBasis` 셋 ·
  `ConditionResult` 셋 · `RuleQuestion` 일곱 그대로다.
- 🔴 **카드 ID 로 분기하지 않는다** — 읽는 것은 관측이 실어 준 카드
  **종류**뿐이다 (AST 로 센다).

---

## 9. 기존 판정 결과와 수정 후 결과

### 9-1. 전후 표

| 판에 있는 앞면 카드 | 전 | 후 |
|---|---|---|
| 통상 몬스터 (미등록) | `UNKNOWN` → `UNCHECKED_RULES` | **`TRUE` → `RESOLVED`** |
| 통상 몬스터 (등록, 페더맨) | `TRUE` → `RESOLVED` | 같음 |
| 통상 **펜듈럼** 몬스터 | `UNKNOWN` | **`UNKNOWN` (그대로)** |
| 효과 몬스터 (미등록) | `UNKNOWN` | **`UNKNOWN` (그대로)** |
| 마법 · 함정 (미등록) | `UNKNOWN` | **`UNKNOWN` (그대로)** |
| 필드의 **세트** 카드 | 건너뛴다 (6-N) | 같음 |
| 가려진 카드 | `UNKNOWN` | 같음 |

### 9-2. 🔴 하나라도 모르면 여전히 멈춘다

통상 몬스터 셋 + 효과 몬스터 하나를 함께 두면 답은 `UNKNOWN` 이다.
"아무도 안 막는다" 는 판 전체를 읽었을 때만 할 수 있는 말이다.

---

## 10. 잘못된 VALID 승격 방지 검증 (§9)

| 원칙 | 확인 |
|---|---|
| 실제 불법 행동은 `INVALID` | 🟢 6-M 의 `origin_zones` 가 그대로 `SOURCE_WRONG_ZONE` 을 낸다 |
| 확인 가능한 합법만 `VALID` | 🟢 근거가 룰북 한 줄이고 `RuleBasis.RULEBOOK` 으로 실린다 |
| 근거 부족은 `UNKNOWN` 유지 | 🟢 펜듈럼 · 효과 몬스터 · 마법 · 함정 · 가려진 카드 전부 |
| 실행 구현이 없으면 미지원 | 🟢 벌금은 여전히 `target_bridge` 에서 0 조합 |
| `UNKNOWN` 이 결합에서 `VALID` 로 안 바뀐다 | 🟢 §9-2 |
| `INVALID` 가 덮이지 않는다 | 🟢 손으로 적은 `FALSE` 가 룰북 유도를 **이긴다** (실측) |
| 비용·선택 절차를 우회하지 않는다 | 🟢 `_check_rule_gate` 는 관문뿐 — 조건·비용은 앞 단계가 본다 |
| 해결 불가면 성공으로 기록하지 않는다 | 🟢 §12 |

🔴 **순서가 핵심이다.** 손으로 적은 등록소가 **먼저**다. 뒤바뀌면 룰북
유도(더 넓은 근거)가 사람이 공식 재정을 읽고 적은 것(더 좁은 근거)을
덮는다. mutation R2 가 그 뒤바뀜을 넣었고 테스트가 잡았다.

---

## 11. 실제 Duel 실행 전후 GameState

### 11-1. 🔴 강제 탈출 장치 — 새로 실행되는 효과

실제 `Duel` 경로 (`duel_at` → `set_down` → `next_own_turn` → 실행 계층):

| 대상 | 전 | 후 |
|---|---|---|
| **통상 몬스터** (취옥의 비룡) | `stage=resolve`, "IsAbleToHand 를 판정할 수 없습니다", 카드 `MZONE` | 🔴 **`stage=resolved`**, 카드 **`HAND`**, 상대 패 **0 → 1** |
| **효과 몬스터** (사이버 드래곤) | `stage=resolve` | **`stage=resolve` (그대로)**, 카드 `MZONE`, 상대 패 **0 → 0** |

🔴 **함정을 하나도 건드리지 않고 규칙 지식만 넣었더니 풀렸다.** 그것이
`test_08` 이 원래 주장한 것("막히는 이유가 함정과 무관하다")의 증명이다.

### 11-2. 어니스트 ① — 통상 몬스터가 깔린 판

실제 `Duel`: `legal_actions` 후보 1 → `apply` (체인 1, 카드 `MZONE`) →
`settle_chain` → 카드 **`HAND`**, 내 패 +1장. 6-O 전에는 이 판에서
해결이 멈췄다.

### 11-3. 거절되는 판은 비트 단위로 그대로

효과 몬스터가 있는 판: `state_hash()` 가 **같고** `deltas == ()` 이며
journal 이 **비어 있다.**

---

## 12. EventJournal 정합성

| 사례 | 기록 |
|---|---|
| 어니스트 ① 해결 (통상 몬스터 있음) | **1건** — `#N P0/MZONE → P0/HAND (return_to_hand)` |
| 강제 탈출 장치 해결 | 대상이 `MZONE → HAND`, 상대 패 +1 |
| 효과 몬스터가 막음 | **0건** |
| 통상 펜듈럼이 막음 | **0건** |
| 6-M 의 출발 자리 위반 | **0건** |

🔴 **기록과 상태 변경이 어긋난 사례 0건.** 기록 의미론은 바뀌지 않았다
(§3-13) — `ZoneMoved` 의 칸도 뜻도 그대로다.

---

## 13. 어니스트 및 기존 ACTIVATE 효과 회귀

| 확인 | 결과 |
|---|---|
| 어니스트 ① 단독 (구경꾼 없음) | 🟢 `TRUE` → `RESOLVED` → `HAND`, journal 1건 |
| 어니스트 ① 실제 `Duel` 수직 경로 | 🟢 후보 1 → 체인 1 → 해결 |
| 뒷면 어니스트의 발동 | 🟢 후보 0, `apply` 거절 (6-K 의 관문) |
| 등재 효과 / 실행 가능 | 🟢 **17 / 14** (변동 없음) |
| 욕망의 항아리 | 🟢 `RESOLVED`, 패 +2장 |
| 욕망의 선물 · 의적의 입문서 (함정) | 🟢 `resolved` (6-O 전과 같다) |

---

## 14. Phase 6-M · 6-N 회귀

| Phase | 확인 | 결과 |
|---|---|---|
| **6-M** | 어니스트 ① 의 `origin_zones == FIELD_ZONES` | 🟢 유지 |
| 6-M | `GRAVE` · `DECK` · `HAND` 에서 `INVALID_TARGET` / `SOURCE_WRONG_ZONE` | 🟢 유지, journal 0건 |
| 6-M | 상태 변화 없는 이동 거절 | 🟢 유지 |
| **6-N** | 묘지 판정이 `position` 에 의존하지 않는다 | 🟢 유지 (표본 카드만 교체 — §16-2) |
| 6-N | 필드의 **세트** 카드는 건너뛴다 | 🟢 유지 |
| 6-N | `FACE_SENSITIVE_ZONES` 를 두 호출자가 공유 | 🟢 유지 |

---

## 15. 실제 실행 가능성 전후 비교 (§12)

§12 의 열 항목. **늘지 않은 것은 0건으로 적는다.**

| # | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | 조사한 `PlayerAction` · 효과 사례 수 | — | 등재 실행 가능 **14건 전수** + 통상 몬스터 표본 5장 + 강제 탈출 장치 2판 |
| 2 | **규칙 지식 부족**으로 `UNKNOWN` 이던 사례 | 표본 **5/5** + 강제 탈출 장치 | **0** (같은 판에서) |
| 3 | **실행 구현 부재**로 차단된 사례 | **1** (벌금, `minimum>1`) | **1 (그대로)** |
| 4 | 새로 정확히 판정되는 합법 행동 | — | 🔴 **통상 몬스터 684장**이 관련된 판정 |
| 5 | 잘못 `VALID` 로 처리한 불법 행동 | — | **0건** (§10) |
| 6 | 🔴 **실제 Duel 실행에 성공한 효과** | 어니스트 ① (깨끗한 판만) | **어니스트 ① (통상 몬스터 있는 판 포함) + 강제 탈출 장치** |
| 7 | GameState 변경이 검증된 사례 | 1 | **3** (어니스트 · 강제 탈출 장치 · 거절 시 불변) |
| 8 | journal 과 상태 변경이 일치 | 전부 | **전부** (어긋남 0건) |
| 9 | 어니스트 실행 성공 | 성공 | **성공 (유지)** |
| 10 | 남아 있는 실행 차단 요인 | — | §17 에 넷 |
| — | 등재 / 실행 가능 효과 | 17 / 14 | **17 / 14 (같다)** |
| — | `OPERATION_RULINGS` 손으로 적은 줄 | 18 | **18 (같다)** |

### 🔴 규칙 판정 개선과 실행 증가를 나눠 적는다 (§12 마지막)

- **규칙 판정 개선**: 통상 몬스터 **683장**이 "모르는 카드" 에서 "룰북이
  답하는 카드" 로 바뀌었다. 정적 범위이고, 그 자체로는 실행이 아니다.
- **실제 실행 증가**: 등재된 효과 중 **강제 탈출 장치 1건**이 새로
  해결된다 (전에는 0건). 어니스트 ① 은 전에도 해결됐지만 **깨끗한 판에
  한해서**였고, 지금은 통상 몬스터가 깔린 판에서도 해결된다.
- 🔴 **실행 가능 효과의 총수(14)는 늘지 않았다.** `executable` 은 "구현이
  있다" 는 뜻이고 6-O 는 그 플래그를 건드리지 않았다. 바뀐 것은 **실제
  판에서 해결까지 가는 비율**이다.

### 표본 범위 (§12 · §18)

- **전수**: 저장소 카드 14,127장의 종류 분류, 등재 실행 가능 효과 14건,
  `Position` 값과 `RuleBasis`·`RuleQuestion` 목록.
- **표본**: 통상 몬스터 5장, 효과 몬스터 1장, 통상 펜듈럼 1장,
  마법 1장, 함정 1장. **전수가 아니다.**
- 🔴 **정적 범위(684장)와 실행 성공(효과 2건)을 섞지 않았다.**

---

## 16. 타깃 · 통합 · 최종 회귀 테스트 결과

### 16-1. 새 파일 — `tests/engine/test_rulebook_derived_facts.py` (39개)

| 절 | 무엇 | 개수 |
|---|---|---|
| A | 감사 — 등록소 18장, 룰북 줄이 덮는 684장, 규칙과 유도가 **이미** 있었다 | 3 |
| B | 유도가 답하는 것과 **답하지 않는 것** (펜듈럼 · 효과 · 마법 · 함정 · 가려진 카드 · 지어낸 조합) | 12 |
| C | 손으로 적은 것이 앞선다 · 찾는 자리가 하나 (AST) · 카드 ID 를 안 본다 (AST) | 3 |
| D | 🔴 실제 실행 전후 — 통상 몬스터는 풀리고 나머지는 막힌다 | 11 |
| E | 실제 `Duel` 수직 통합 (풀리는 판 · 막히는 판) | 2 |
| F | 6-L 어니스트 · 6-M 이동 · 6-N 표시 형식 · 기존 `ACTIVATE` 회귀 | 4 |
| G | 금지 사항 — 새 룰 엔진 0 · 데이터 확장 0 · 한 파일 | 3 |

### 16-2. 움직인 기존 테스트 — **여섯 파일 / 열한 개**

🔴 **다섯 파일 열 개는 "표본 카드가 더 이상 모르는 카드가 아니다" 였고,
여섯 번째 하나는 6-O 와 무관한 핀의 비교 대상 결함이었다** (§16-2-2).
지운 테스트 · 추가한 skip · 약화한 단언 · 완화한 threshold 는 **없다.**

| 테스트 | 무엇이 틀린 전제였나 | 어떻게 고쳤나 |
|---|---|---|
| `test_card_position_visibility.py` d01[×4] · d02 · d04 | `UNREGISTERED = 11091375` (사파이어 드래곤)을 "모르는 카드" 로 썼는데 그 카드는 **통상 몬스터**다 | 표본을 **효과 몬스터**(사이버 드래곤)로 바꿨다. 재는 사실(표시 형식 독립성)은 그대로 |
| `test_self_reference_target.py::test_g02` | 같음 (`LUSTER_DRAGON`) | 같음 |
| `test_operation_ruling.py::test_d_an_unregistered_card_is_unknown` | "등록소가 비면 **어떤** 카드든 `UNKNOWN`" — 이제 룰북이 답하는 카드가 있다 | 두 축을 갈라서 **더** 센다: 함정은 `UNKNOWN`, 통상 몬스터는 근거를 들고 `TRUE` |
| `test_operation_ruling.py::test_d_one_unknown_card_on_the_board_is_enough_to_stop_it` | 페더맨을 등록에서 빼는 것으로 "모르는 카드" 를 만들었다 | 모르는 카드를 **판에 놓는다** (효과 몬스터). 재는 사실은 그대로 |
| `test_set_trap_timing_audit.py::test_08` | 🔴 **"강제 탈출 장치는 `IsAbleToHand` 공백으로 막힌다"** — 그 공백이 닫혔다 | **양쪽을 다 센다**: 통상 몬스터 대상은 `resolved`(카드가 `HAND`), 효과 몬스터 대상은 **같은 자리에서** 멈춘다. 원래 주장("막히는 이유가 함정과 무관하다")이 더 분명해졌다 |

🔴 **`test_08` 이 가장 중요한 수정이다.** 그 시험의 **결론**(함정이 원인이
아니다)은 틀리지 않았고, 틀린 것은 **그 공백이 아직 열려 있다**는 사실
진술이었다. 규칙 지식만 넣어서 풀렸으므로 결론이 증명된 셈이다.

#### 16-2-2. 🔴 6-O 와 무관한 여섯 번째 — 핀이 `HEAD` 를 보고 있었다

루트 회귀(44파일)에서 **단 한 건**이 깨졌다.

```
FAILED tests/test_card_detail_provenance_display_audit.py
       ::test_37_no_existing_test_was_modified_or_deleted
AssertionError: ('tests/engine/test_random_selection.py', 37, 38)
```

**이 실패는 6-O 의 변경 때문이 아니다.** 측정한 경위:

| ref | `test_random_selection.py` 의 테스트 수 |
|---|---|
| `329a2b1^`(Phase 3-F-43 의 base) | 37 |
| `6eb1c4a`(Phase 3-F-43 의 마지막 commit) | 37 |
| `4f13655`(**Phase 6-M** 테스트 commit) | **38** |
| `HEAD`(`da93fc6`) | 38 |

즉 Phase 3-F-43 은 그 파일을 건드리지 않았고, 테스트 한 개
(`test_a_a_move_that_changes_nothing_is_refused`)를 더한 것은 **Phase 6-M**
이다. 그런데 이 핀은 `counts(base)` 를 `counts("HEAD")` 와 비교했으므로,
단언하는 내용이 "3-F-43 이 기존 테스트를 수정·삭제했는가" 가 아니라
"**그 뒤에 온 어떤 Phase 도** 당시 존재했던 파일에 테스트를 더하지 않았다"
였다. 뒤에 올 작업은 그 Phase 가 책임질 수 없다.

고친 내용은 Phase 6-N 이 같은 결함을 가진 두 핀에 적용한 것과 **동일**하다:

```python
#: 🔴 이 Phase 의 **마지막 commit** 과 비교한다 (Phase 6-O).
#: ``HEAD`` 와 비교하면 뒤에 온 모든 작업까지 이 핀이 책임지게 된다.
before, after = counts(base), counts(shas[0])
```

마지막 단언(`{p for p in _changed_files() if p in before} == set()`)은
`_changed_files()` 가 이미 **그 Phase 의 commit 만** 모으므로 그대로 두었다.
단언의 세기는 바뀌지 않았다 — 느슨하게 만든 것이 아니라 **재던 것을 정확히
재게** 했다. 고친 뒤 그 파일 단독: **38 passed, 종료 코드 0** (39.06s).

🔴 **이것은 Phase 6-M 의 회귀 범위 공백이기도 하다.** 6-M 은 52파일을
돌렸지만 이 파일은 거기에 없었다 (6-N 이 같은 이유로 두 건을 고쳤고, 이것이
세 번째다). 숨기지 않고 적는다.

### 16-3. Mutation 테스트 — 10개

**내가 바꾼 코드와 그것이 부르는 유도만** 대상으로 했다. `git checkout` 을
쓰지 않았고 원본을 메모리에 들고 있다가 되돌리고 `assert` 로 확인했다
(`scratchpad/mutate6.py`). 판정 테스트는 새 파일 + 6-L · 6-N · 함정 ·
판정기 네 파일이고 **pytest 의 실제 종료 코드**로 판정했다.

| # | 고의 결함 | 결과 |
|---|---|---|
| R1 | 유도를 아예 쓰지 않는다 (6-O 전으로) | killed (15 failed) |
| R2 | 유도가 손으로 적은 것을 덮는다 (순서 뒤집기) | killed (4) |
| R3 | 통상 펜듈럼도 답한다 | killed (2) |
| R4 | 몬스터가 아닌 카드도 답한다 | 🔴 **처음에 생존** → 아래 |
| R5 | 효과 몬스터도 통상 몬스터로 읽는다 | killed (14) |
| R6 | 엑스트라 덱 통상 몬스터도 답한다 | 🔴 **처음에 생존** → 아래 |
| R7 | 정의가 없어도 답한다 | killed (1) |
| R8 | 유도가 "남을 막는다" 로 답한다 | killed (31) |
| R9 | 유도가 패 되돌림에 거짓으로 답한다 | killed (25) |
| R10 | 근거를 룰북이 아니라 재정으로 적는다 | killed (6) |

#### 🔴 R4 · R6 이 생존했다 — 이유를 측정하고 테스트를 더했다

둘 다 **지금 데이터에서 밟을 수 없는 가지**였다.

| 생존 | 왜 | 실측 |
|---|---|---|
| R4 (`is_monster` 가드) | `NORMAL` 을 가진 **비몬스터**가 없다 | 14,127장 중 **0장** |
| R6 (`is_extra_deck` 가드) | **엑스트라 덱 통상 몬스터**가 없다 | 722장 중 **0장** |

즉 실제 카드로는 그 조건을 지워도 아무 시험이 깨지지 않는다. **테스트의
구멍이기도 하고 데이터의 사실이기도 하다** — 숨기지 않고 둘 다 적는다.

**지어낸 관측**(`CardDefinitionView` 를 손으로 만든다)으로 그 가지를 직접
재는 시험 둘(`test_b06` · `test_b07`)과, 그 조합이 저장소에 0장이라는
수치를 못박는 시험(`test_b08`)을 더했다. 재측정에서 **R4 · R6 둘 다
killed** 다.

**최종: 10개 중 10개 killed, 생존 0.**

### 16-4. 실행 기록

(§19 에 명령 · 시간 · 종료 코드와 함께 적었다.)

---

## 17. 남아 있는 구조적 차단 문제

### 17-1. 🔴 지식의 공백이 곧 실행의 공백이다 (가장 큼)

6-O 가 통상 몬스터 684장을 덮었지만, 저장소 **14,127장** 중 나머지는
그대로다. 실제 듀얼에서 **효과 몬스터 한 장이 앞면으로 있으면** 모든
`gated=True` 이동이 멈춘다.

- **위치**: `OPERATION_RULINGS` (손으로 적은 18장) + `rulebook_facts`
  (룰북 한 줄)
- **다음으로 가능한 묶음**: 🔴 **룰북이 또 한 줄로 답하는 집합이 있는지
  먼저 조사해야 한다.** 6-O 는 그런 줄이 **하나**임을 확인했다
  (`NORMAL_MONSTER_RULE`). 다른 줄이 없으면 그다음은 **카드 텍스트를
  읽는 일**이고, 그것은 묶음이 아니라 카드마다의 일이다 (§14 가 금지한
  "전면 재구축" 과 구분해야 한다).
- **승인 필요**: 어떤 범위를 어떤 근거로 읽을지 정해야 한다.

### 17-2. 벌금 — 실행 구현의 공백 (규칙이 아니다)

`target_bridge.target_combinations` 가 `minimum != 1` 이면 **빈 목록**을
돌려준다. 벌금은 `minimum=maximum=2` 이고, 등재된 효과 중 `minimum>1` 인
것은 **이 한 장뿐**이다.

- 🔴 **규칙 지식 문제가 아니다** — §15-"규칙 지식이 아니라 실행 구현 부재가
  문제라면 이를 명확하게 보고한다" 에 해당한다.
- **최소 수정안**: 다리가 여러 장 조합을 열거하게 한다. 조합 폭발을
  어떻게 끊을지 정해야 하므로 범위를 먼저 합의해야 한다.

### 17-3. 파괴 판정기가 없다

`UnknownDestructionRuling` 이 기본값이어서 **어떤 파괴도 일어나지
않는다.** 블랙홀 · 싸이크론이 `executable=False` 인 이유다.

- 🔴 내성 · 대체 효과 · 동시 파괴 처리를 카드 텍스트 한 줄로 환원할 수
  없다. **새 계층**이 필요하므로 §14 가 금지한 범위다.

### 17-4. `OFFICIAL_RULING` 근거를 쓰는 자리가 0건

`RuleBasis.OFFICIAL_RULING` 이 있고 `rulings/` 계층과 수집기도 있는데,
`OPERATION_RULINGS` 에서 그 근거로 적힌 줄이 **하나도 없다.**

- 🔴 그 수집은 `scripts/fetch_ocg_rulings.py` 이고 **전체 크롤은 금지**
  되어 있다. 어떤 카드를 어떤 기준으로 수집할지 정해야 한다 — 승인 대기.

### 17-5. 수정하지 않은 것 (§14)

새 룰 엔진 · `OPERATION_RULINGS` 전체 확장 · 룰북 전체 재처리 ·
Official Card Ruling Layer 재구축 · 모든 소환 방식 · 체인·우선권 재설계 ·
TRIGGER 자동 발동 · 사용 횟수 제한 · 콤보 플래너 · Discord · 덱 빌더 ·
금지·제한 리스트 · Duel Simulator · EDOPro · AI 전략 · 카드 데이터 재생성 ·
Lua 파일 이동 — **하나도 건드리지 않았다.** `STRUCTURAL-15 · 34 · 35 ·
36 · 77` 도 건드리지 않았다 (§11 — 선정한 문제와 직접 연결되지 않는다).

---

## 18. 다음 단계에서 해결할 최소 실행 BLOCKER

🔴 **§17-2 (벌금의 다중 대상)** 을 권한다.

| 기준 | 판정 |
|---|---|
| 실제 Duel 실행을 차단하는가 | 🟢 등재·실행 가능 효과 1건이 `target_bridge` 에서 0 조합 |
| 규칙 지식이 아니라 **실행 구현**인가 | 🟢 공식 근거를 새로 읽을 필요가 없다 — 이미 정의에 `minimum=2` 가 적혀 있다 |
| 범위가 작은가 | 🟢 `target_bridge` 한 함수 |
| 정확성 위험 | 🟡 조합 폭발 — 상한을 어디에 둘지 정해야 한다 |
| 승인 필요 | 🟡 상한 정책만 |

§17-1 (지식 범위)이 **영향은 더 크지만** 다음 단계로 권하지 않는다 —
룰북이 또 한 줄로 답하는 집합이 **없음**을 6-O 가 확인했으므로, 그다음은
카드마다 공식 텍스트를 읽는 일이고 **범위와 근거 기준을 먼저 합의해야
한다** (§14 가 "전면 재구축" 을 금지하므로 더욱 그렇다).

🔴 **이 Phase 는 위 둘 중 아무것도 진행하지 않았다.**

---

## 19. 테스트 실행 기록 및 Git 커밋 · 푸시 결과

### 19-1. 실행한 테스트 명령어 · 시간 · 결과 · 🔴 **실제 종료 코드**

모두 `YGO_CARDS_CDB=data/cards.cdb` 를 설정하고 `-p no:randomly` 로 돌렸다
(§13). 종료 코드는 `| tail` 이 가리지 않도록 **pytest 자신의 종료 코드**를
따로 읽었다.

| # | 단계 | 명령어 | 시간 | 통과 | 실패 | skip | 종료 코드 |
|---|---|---|---|---|---|---|---|
| 1 | 2단계 — 타깃 | `pytest tests/engine/test_rulebook_derived_facts.py -q -p no:randomly --no-header` | 4.81s | **39** | 0 | 0 | 🟢 **0** |
| 2 | 3단계 — 엔진 (1차) | `pytest tests/engine -q -p no:randomly --no-header --tb=short` | 336.94s (5:36) | 3,271 | 🔴 **10** | 0 | 🔴 **1** |
| 3 | 3단계 — 엔진 (수정 후) | 같음 | 342.34s (5:42) | **3,317** | 0 | 0 | 🟢 **0** |
| 4 | 4단계 — 루트 44파일 (1차) | `pytest <44 files> -q -p no:randomly --no-header --tb=short` | 1871.34s (31:11) | 1,341 | 🔴 **1** | 0 | 🔴 **1** |
| 5 | 움직인 핀 단독 | `pytest tests/test_card_detail_provenance_display_audit.py -q -p no:randomly --no-header --tb=short` | 39.06s | **38** | 0 | 0 | 🟢 **0** |
| 6 | 4단계 — 루트 44파일 (**처음부터 재실행**) | #4 와 동일 | 1942.30s (32:22) | **1,342** | 0 | 0 | 🟢 **0** |
| 7 | Mutation 10건 | `scratchpad/mutate6.py` (판정은 pytest 종료 코드) | — | killed **10/10** | 생존 **0** | — | — |

🔴 **#2 의 10건과 #4 의 1건을 숨기지 않는다.** 각각 §16-2 · §16-2-2 에
"왜 그 테스트가 틀린 전제를 갖고 있었는지" 를 적었다. #4 를 고친 뒤에는
중간에서 이어 돌리지 않고 **44파일 전부를 처음부터 다시** 돌렸다(#6).

44파일 선정 기준(§13 4단계): `OPERATION_RULINGS`, `BoardRuling`,
`effect/ruling`, `CardRuleFacts`, `RuleBasis`, `RuleQuestion`,
`normal_monster_facts`, `rulebook_facts`, `UNCHECKED_RULES`,
`RULE_NOT_IMPLEMENTED`, `unregistered`, `test_random_selection`,
`def test_37` 중 하나라도 언급하는 루트 테스트 파일 전부.

🔴 **돌리지 않은 것**: `scripts/fetch_ocg_rulings.py --all`(14,000장 크롤링)
은 금지되어 있어 실행하지 않았다. 공식 사이트에 새로 접속한 적이 없다 —
이 Phase 가 쓴 규칙 근거는 **이미 저장소에 있는 룰북**
(`data/rules/structured/sd-rulebook-en-v10.json`) 한 줄이다.

### 19-2. 변경한 파일 (최종)

| 종류 | 파일 | 증감 |
|---|---|---|
| production | `engine/effect/ruling.py` | +85 −3 |
| 테스트(신규) | `tests/engine/test_rulebook_derived_facts.py` | +39 테스트 |
| 테스트(수정) | `tests/engine/test_operation_ruling.py` | +62 −3 |
| 테스트(수정) | `tests/engine/test_set_trap_timing_audit.py` | +38 −0 |
| 테스트(수정) | `tests/engine/test_card_position_visibility.py` | +9 −2 |
| 테스트(수정) | `tests/engine/test_self_reference_target.py` | +10 −3 |
| 테스트(수정) | `tests/test_card_detail_provenance_display_audit.py` | 핀 비교 대상 1줄 (§16-2-2) |
| 보고서 | `docs/phase6o-operation-rulings-execution-audit.md` | 신규 |

🔴 **production 은 한 파일**이다. 규칙 데이터(`OPERATION_RULINGS`)는 **18장
그대로**이고, 효과 라이브러리도 **17개 정의 / 14개 실행 가능 그대로**다 —
이 Phase 는 규칙을 **더 적지 않고 이미 있던 룰북 유도를 연결**했다 (§8).

### 19-3. 커밋

작업 브랜치: `claude/pensive-goodall-te1egy`.
기존 commit 을 rewrite · amend 하지 않았고 force push 하지 않았다.
새 브랜치와 PR 을 만들지 않았다.

| 순서 | commit | 내용 |
|---|---|---|
| 1 | (아래 19-4) | production — 룰북 유도를 판정기에 연결한다 |
| 2 | (아래 19-4) | 테스트 — 신규 39개와 전제가 틀린 기존 핀 열하나 |
| 3 | (아래 19-4) | 보고서 19절 |

### 19-4. 푸시 결과

(커밋 직후 실제 SHA 와 푸시 출력을 아래에 기록한다.)

---

## 20. 다음 Phase

🔴 **다음 Phase 는 자동으로 시작하지 않는다** (§16).

§18 이 권하는 후보(벌금의 다중 대상 조합)와 §17-1(지식의 공백)은 **둘 다
이 Phase 에서 진행하지 않았다.** 어느 쪽을 할지, 그리고 §17-1 을 한다면
"공식 근거를 어디까지 읽을지" 의 범위와 기준은 **지시를 받은 뒤에** 정한다.
