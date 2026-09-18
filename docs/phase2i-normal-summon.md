# Phase 2-I — Normal Summon

기준 커밋: `13fb0b1` (Phase 2-H)

```
PlayerAction(NORMAL_SUMMON)
    ↓  ActionValidator            ← 여기서 이 프로젝트 최초의 VALID 가 난다
ValidationResult(VALID)
    ↓  ActionExecutor             permits_execution 만 통과
    ↓  NormalSummonHandler        규칙을 갖지 않는 껍데기
    ↓  NormalSummonExecutor       계획 → 적용 → 확인
GameState 변경  +  MonsterSummoned
```

---

## 1. 룰북에서 확인한 것

`data/rules/documents/sd-rulebook-en-v10.json` · `data/rules/structured/`

| 규칙 | 내용 |
|---|---|
| **RULE-SUMMON-009** | "Simply play a Monster Card from your hand onto the field in **face-up Attack Position**. **All Normal Monsters, and most Effect Monsters (unless they have a specific restriction)**, can be Summoned in this way." |
| **RULE-SUMMON-009** (restrictions) | "You can only Normal Summon **OR Normal Set** once per turn." |
| **RULE-SUMMON-011** | 레벨 5 이상은 제물이 필요하다. **레벨 5·6 은 1장, 레벨 7 이상은 2장.** |
| **RULE-SUMMON-010** | Normal Set 은 뒷면 수비 표시이고, **세트된 몬스터는 소환된 것으로 치지 않는다.** |
| **RULE-TURN-004 / -006** | 메인 페이즈 1 · 2 의 행위: "Summon or Set a Monster". |

룰북은 **기준점**이지 실행 시 의존성이 아니다. `engine/summon_rules.py` 는
규칙 JSON 을 읽지 않고 근거만 인용한다 (테스트가 AST 로 확인한다) — 엔진이
데이터를 읽기 시작하면 규칙 파일이 없는 환경에서 판정이 달라진다.

---

## 2. 이번 단계에서 구현한 규칙

| 확인하는 것 | 결과 |
|---|---|
| 자신의 턴인가 | 아니면 `INVALID(NOT_TURN_PLAYER)` |
| 메인 페이즈 1 · 2 인가 | 아니면 `INVALID(WRONG_PHASE)` |
| 자신이 쥔 카드인가 | 아니면 `INVALID(SOURCE_NOT_CONTROLLED)` |
| 패에 있는가 | 아니면 `INVALID(SOURCE_WRONG_ZONE)` |
| 몬스터인가 | 아니면 `INVALID(SOURCE_WRONG_CARD_TYPE)` |
| 몬스터 존에 빈 칸이 있는가 | 아니면 `INVALID(ZONE_FULL)` |
| 이번 턴 소환권이 남아 있는가 | 아니면 `INVALID(NORMAL_SUMMON_ALREADY_USED)` |
| 일반 소환 절차를 밟을 수 있는가 | 아래 §3 |

전부 통과하면 **`VALID`** 다. `ActionValidator._COMPLETE_RULES` 에
`NORMAL_SUMMON` 하나가 들어갔고, 그것이 "이 종류의 적법성은 끝까지 볼 수
있다" 는 선언이다.

실행은 `HAND → MZONE`, **앞면 공격 표시**, 가장 작은 빈 칸.

---

## 3. 왜 통상 몬스터만 허가가 나는가

`assess_normal_summon` 이 네 갈래로 답한다.

| 판정 | 대상 | 검증 결과 |
|---|---|---|
| `ORDINARY` | **레벨 4 이하 통상 몬스터** | `TRUE` → 허가 |
| `FORBIDDEN` | 엑스트라 덱 · 의식 · 토큰 · 비몬스터 | `FALSE` → `INVALID(CANNOT_NORMAL_SUMMON)` |
| `NEEDS_TRIBUTE` | 레벨 5 이상 | `UNKNOWN` → `missing_rule="tribute-summon"` |
| `UNDETERMINED` | **효과 몬스터** · 정의를 못 읽음 | `UNKNOWN` |

**효과 몬스터를 `UNKNOWN` 으로 두는 것이 이 단계의 가장 큰 제한이다.**
이유는 룰북이 직접 말한다 — 통상 몬스터는 *전부* 이 방법으로 소환되지만,
효과 몬스터는 "**특정 제약이 없는 한**" 이다. 그 제약은 카드 텍스트에 있고
이 엔진은 아직 읽지 못한다. 대부분은 소환할 수 있겠지만, **확인하지 못한
것을 허가로 바꾸지 않는다.**

제물이 필요한 몬스터도 `INVALID` 가 **아니다.** 실제 규칙에서는 제물을
바치면 소환할 수 있고, 없는 것은 그 절차뿐이다. 그래서 `UNKNOWN` 이고,
룰북이 말하는 제물 수(`tributes_required`)를 **적어만 둔다** — 제물 절차가
생기면 그 값이 그대로 입력이 된다.

---

## 4. "모른다" 의 두 원인을 나눴다

`_check_requirements` 는 지금까지 모든 `UNKNOWN` 을
`INFORMATION_UNAVAILABLE` 로 묶었다. 그런데 이번 단계에서 두 가지가 한
요구 안에 들어왔다.

- 카드 정의를 **못 읽어서** 모른다 → 정보의 문제. 판이 바뀌면 풀린다.
- 제물 절차가 **없어서** 모른다 → 규칙의 문제. 코드가 생겨야 풀린다.

그래서 `Condition.missing_rules(view, context)` 를 조건 계층에 더했다.
기본값은 빈 튜플("정보가 없다")이고, `UnimplementedRule` 과 새 조건만
채운다. `And` · `Or` · `Not` 은 `unknown_reasons` 와 같은 방식으로 자식의
것을 모은다. 검증기는 **추측하지 않고** 조건이 말하는 것을 그대로 전한다.

---

## 5. 소환권

`RuleUsageRegistry` — `engine/state/rule_usage.py`, `GameState.rule_uses`.

**카드 효과의 "1턴에 1번"(`UseRegistry`)과 다른 표다.** 후자의 키는 카드 ·
카드명 · 효과이고, 이쪽은 `(턴 번호, 플레이어, 규칙 행위)` 다. 한 표에
넣으면 "이 카드의 1턴 1회" 와 "이 플레이어의 소환권" 이 섞인다.

**턴 번호가 키에 들어간다.** 그래서 턴이 바뀔 때 **지울 것이 없다** —
Phase 2-H 가 "규칙 없이 지우지 않는다" 며 남겨 둔 `TURN_BOUNDARY_RESETS`
의 첫 줄이 이 방식으로는 아예 필요 없어진다. 지난 턴의 기록이 남아 있는
것은 새는 것이 아니라 역사다.

소환권은 `GameStateView.normal_summons_used` 로 **양쪽 다 본다** — 소환은
공개된 자리에서 일어나므로 가릴 것이 없다. 효과 쪽 `UseRegistry` 는 여전히
관측에 나가지 않는다.

`SET_MONSTER` 도 같은 권리를 쓴다 (RULE-SUMMON-009). 세트 절차가 구현되면
**같은 이름으로** 기록해야 한다 — 이름을 나누면 한 턴에 둘 다 하게 된다.
지금은 세트가 실행되지 않으므로 기록하지 않는다.

---

## 6. 판정과 실행이 겹치지 않는가 (§28-A)

**겹치지 않는다.** 실행기는 적법성을 다시 판정하지 않는다.

| | 무엇을 보는가 |
|---|---|
| `ActionValidator` | 페이즈 · 턴 플레이어 · 자리 · 카드 종류 · 소환권 · 절차 |
| `NormalSummonExecutor.plan` | **그 카드가 있는가 · 패에 있는가 · 놓을 칸이 있는가** |

뒤의 셋은 "지시를 수행할 수 있는가" 이지 "해도 되는가" 가 아니다. 계획을
만들려면 어느 칸에 놓을지 알아야 하고, 그걸 알 수 없으면 애초에 수행이
불가능하다. 하나라도 아니면 **판에 손대기 전에** `NormalSummonError` 로
멈춘다.

절차 판정(`assess_normal_summon`)은 실행기가 **부르지 않는다** — 테스트가
`normal_summon.py` 에 그 이름이 없음을 확인한다.

---

## 7. Mutation Safety

- 순서는 **이동 → 확인 → 소환권 기록**이다. 반대로 하면 이동이 실패했을 때
  권리만 사라진 판이 남는다.
- 사용권을 적을 키는 **계획 단계에서 미리 만든다.** 적는 순간에 실패할
  이유를 없앤다.
- 이동 뒤에 계획한 칸 · 표시 형식 · "패를 떠났는가" 를 확인한다. 어긋나면
  기록을 남기지 않고 멈춘다.
- 같은 카드가 두 존에 동시에 있는 상태는 `ZoneContainer.place` 가 이미
  거부한다 (Phase 1). 그래도 확인은 한다.
- 거절된 시도는 `state_hash()` 를 바꾸지 않는다 — 여덟 가지 실패 경로
  전부에 대해 테스트가 확인한다.

---

## 8. 계층 경계

| | |
|---|---|
| `ActionExecutor` | 소환을 **모른다.** `engine.normal_summon` 을 import 하지 않고, `NORMAL_SUMMON` 을 비교하는 분기가 없다 (AST 확인) |
| `EffectExecutor` · `CostPayer` | 부르지 않는다 — 소환은 효과가 아니다 (ADR-001) |
| `Chain` · `Trigger` · `Timing` · `Priority` | import 하지 않는다. 소환 성공 뒤의 응답 기회는 이 계층의 일이 아니다 |
| `TurnProgressor` | 소환이 시간을 옮기지 않는다 |
| 기본 `ActionExecutor()` | **여전히 비어 있다.** `summoning_executor()` 를 부르거나 직접 등록해야 한다 (ADR-006) |

`SpecialSummonHandler` · `AttackHandler` 는 같은 모양으로 붙는다 —
`action_execution.py` 는 바뀌지 않는다.

---

## 9. Event / Delta

`MonsterSummoned` — 기존 `StateDelta` 하나를 더했다.

`CardMovement` 로 **만들지 않았다.** `CardMovement.operation` 은
`OperationKind` — *효과가 하는 일*의 어휘이고 `REASON_NAMES` 가 전부
`EFFECT` 를 달고 있다. 소환을 거기 끼워 넣으면 "효과로 묘지에 보내졌다" 와
"일반 소환되었다" 가 같은 표를 쓴다. 움직임의 정보(출발 · 도착 · 칸)는
그대로 들고, 의미는 `summon` 이 말한다.

**제물 칸을 미리 만들지 않았다.** 제물은 *다른 카드들이 필드를 떠나는*
별개의 변화다. 빈 `tributes` 칸을 두면 그 칸이 "이 소환이 제물을 소유한다"
고 말하게 된다.

`EventJournal` 연결과 `TimingPoint.SUMMONED` 는 만들지 않았다 (§13).
`TimingEvent.from_delta` 는 모르는 Delta 를 만나면 **예외를 던진다** —
지어내지 않는다는 뜻이고, 소환을 사건으로 읽으려면 그 계층이 자기 이름을
정해야 한다.

---

## 10. 구현하지 않은 것

§4 가 금지한 것 전부. 추가로 스스로 남긴 것:

- **제물 소환** — 판정만 하고 절차는 없다 (`NEEDS_TRIBUTE`)
- **소환 조건 파싱** — 효과 몬스터가 `UNKNOWN` 인 이유
- **Normal Set** — 소환권을 함께 쓰는 규칙도 세트가 실행될 수 있을 때 잇는다
- **`SET_MONSTER` 의 페이즈 요구** — `_summon_like` 를 건드리지 않았다.
  세트도 메인 페이즈의 행위지만, 실행되지 않는 종류의 판정을 지금 바꿀
  이유가 없다
- **소환 성공 → 유발 효과 → 체인** — Delta 만 남긴다
- **칸 선택** — 가장 작은 빈 칸에 놓는다. 고르는 주체가 아직 없다

---

## 11. 앞으로 만들면 좋은 것

1. `TimingPoint.SUMMONED` 와 `MonsterSummoned` → `TimingEvent` 연결.
2. 제물 선택과 릴리스 — `tributes_required` 가 입력이 된다.
3. 소환 조건 파싱 — 효과 몬스터를 `UNKNOWN` 에서 꺼내는 유일한 길.
4. Normal Set — 소환권을 같은 이름으로 기록해야 한다.
5. 칸 선택을 플레이어가 하는 경로.
