# Phase 3-F-11 — `TimingEvent.actor` / `EventContext.actor` Semantic Contract

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-11 — Actor Semantic Contract 고정 |
| 모드 | **문서 계약 고정** — production 변경은 **docstring 둘뿐** |
| **실제 HEAD (측정)** | `51123f7 Phase 3-F-10 보고서: commit SHA · push 결과 기록` |
| Base (3-F-10) | `5d6d0a7` (작업) · `51123f7` (보고서) — **둘 다 실제로 존재한다** |
| 3-F-10 최종 판정 | **B. ACTOR_ROLES_NEED_DOCUMENTATION** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,299 passed / 4 skipped |

### 변경된 파일

| 파일 | 변경 | 성격 |
| --- | --- | --- |
| `engine/trigger.py` | **+18 / −1** | `TimingEvent.actor` **docstring 만** |
| `engine/event_pipeline.py` | **+13 / −1** | `EventContext.actor` **docstring 만** |
| `tests/test_actor_role_separation_audit.py` | `test_03` 재작성 | 3-F-10 의 낡은 가정을 고쳤다 (§13) |
| `tests/test_actor_semantic_contract.py` | 신규 **16건** | 계약을 못박는다 |
| `tests/test_event_relation_input_boundary_audit.py` | `test_15` 단정 방향 교체 | 3-F-8 이 **거짓 문장의 존재**를 pin 했다 (§13) |
| `tests/test_rule_not_implemented_code_audit.py` | 줄 번호 4개 갱신 | docstring 때문에 +17 밀렸다 (§13) |
| `tests/test_trigger_pipeline_dormant_audit.py` | 줄 수 snapshot 3건 갱신 | 같은 이유 (§13) |
| `docs/phase3f11-actor-semantic-contract.md` | 신규 | 이 문서 |

**docstring 만 바뀌었다는 것을 바이트가 아니라 AST 로 확인했다** — 두
파일에서 문자열 리터럴을 제거한 AST 가 수정 전후로 **동일**하다.

---

## 2. 🔴 먼저: 코드를 읽고 3-F-10 의 진단을 좁혔다

§2 가 "문서부터 고치지 말고 실제 코드를 먼저 검색한다" 고 요구했고, 그
검색이 **내 전 Phase 의 서술 하나를 바로잡았다.**

3-F-10 은 "두 docstring 이 똑같은 것을 약속한다 → 구분이 어디에도 없다" 고
적었다. 실제로 읽어 보니 **셋 중 둘은 이미 맞았다.**

| 자리 | 3-F-10 이 적은 것 | **실제** |
| --- | --- | --- |
| `TimingEvent.actor` | 틀렸다 | 🔴 **틀렸다** — "이 **사건을** 일으킨 플레이어" 라고 **행위자로 단정** |
| `EventContext.actor` | 같은 것을 약속한다 | 🟢 **맞았다** — "일으킨 **행위의 주체**" (= 행위자). 다만 `None` 이 되는 까닭이 **하나만** 적혀 있었다 |
| `ObservedEvent.actor` | (읽지 않았다) | 🟢 **이미 구분해 두었다** — 아래 |

`ObservedEvent.actor` 의 기존 docstring:

> 사건 자체가 밝히는 주체. 없으면 문맥의 행위자로 **떨어지지 않는다** —
> **"누가 이 행위를 했는가" 와 "이 사건이 누구의 것인가" 는 다른 질문이다.**

**이 문장이 두 actor 의 구분을 이미 적어 두고 있었다.** 3-F-10 은 그 property
의 **본문**(`return self.timing.actor`)만 보고 **자기 docstring 을 읽지
않았다.**

> 그러므로 결함은 "둘 다 틀렸다" 가 아니라 **"하나가 거짓이고, 구분은 세
> 번째 자리에만 적혀 있었다"** 다. 이번 Phase 가 고친 것도 그 하나다.

---

## 3. §2 전수 검색 결과

여덟 문자열을 9개 production 루트 · `tests/` · `docs/` 전체에서 셌다.

| 문자열 | 총 | A production | B 테스트 | D dormant | E 문서 |
| --- | --- | --- | --- | --- | --- |
| `TimingEvent.actor` | 32 | 0 | 9 | 0 | 23 |
| `EventContext.actor` | 30 | 0 | 7 | 0 | 23 |
| `timing.actor` | 33 | 0 | 18 | **1** (`event_pipeline.py`) | 14 |
| `context.actor` | 46 | 0 | 24 | 0 | 22 |
| `ObservedEvent.actor` | 16 | 0 | 4 | 0 | 12 |
| `event.actor` | 135 | **2** (`trigger.py`) | 89 | 0 | 44 |
| `_event_relation` | 153 | **2** (`trigger.py`) | 70 | 0 | 81 |
| `EVENT_RELATION` | 89 | **5** (`trigger.py`) | 41 | 0 | 43 |

**production 에서 사건의 actor 를 읽는 자리는 셋뿐이다.**

| 자리 | 무엇 |
| --- | --- |
| `engine/trigger.py` `from_journal_event` (`event.actor` ×2) | 저널 사건의 **행위자**를 옮긴다 — 맞는 사용 |
| `engine/event_pipeline.py` `ObservedEvent.actor` (`timing.actor` ×1) | 사건 쪽을 노출한다 — docstring 이 이미 그렇게 적어 두었다 |
| `_event_relation` / `EVENT_RELATION` (`trigger.py` ×7) | **actor 를 읽지 않는다** (AST 로 확인 — `test_12`) |

---

## 4. `TimingEvent.actor` contract

### 계약 (고친 뒤)

> **이 변화가 귀속되는 플레이어.** 알 수 없으면 `None`.
> **행위의 주체가 아니다.** 어느 칸에서 오는지는 사건군이 정하고, 그래서
> 뜻이 사건군마다 다르다.

| 사건군 | 어디서 오는가 | 뜻 |
| --- | --- | --- |
| `MonsterSummoned` | `delta.player` | 소환한 사람 |
| `CardDrawn` | `delta.player` | 뽑은 사람 |
| `LifeChanged` | `delta.player` | **LP 가 바뀐 쪽** |
| `ZoneMoved` | `delta.to_player` | **도착지 주인** |
| `PhaseChanged` | (적지 않는다) | `None` — 규칙이 하는 일 |

그리고 전투 반례를 **문장으로** 넣었다 — "P1 이 P0 을 공격해 P0 의 LP 가
줄면 이 값은 **P0** 이다 — 공격한 P1 이 아니다."

### 금지 표현을 제거했다

| 금지 | 전 | 후 |
| --- | --- | --- |
| 행동 주체로 단정 | "이 **사건을 일으킨** 플레이어" | "이 변화가 **귀속되는** 플레이어" + "**행위의 주체가 아니다**" |

`test_01` 이 `"이 사건을 일으킨 플레이어" not in doc` 과 `"일으킨" not in doc`
을 함께 못박는다.

---

## 5. `EventContext.actor` contract

### 계약 (고친 뒤)

> 이 변화를 일으킨 **행위의 주체**. 없으면 `None`.
> **부르는 쪽이 선언한다** — `read` 에 넘긴 값, 없으면 `result.action.actor`,
> 그것도 없으면 `None`.
> delta 와 **맞춰 보지 않는다** — 이 값이 사실인지는 넘기는 쪽의 책임이고,
> `TimingEvent.actor` 와 **같은 뜻이 아니다**.

### 보탠 것 둘 (의미는 바꾸지 않았다)

| 보탠 것 | 왜 |
| --- | --- |
| **선언**이라는 사실 | 3-F-10 이 측정했다 — delta 와 모순되는 값도 거절되지 않는다. 정확성이 **부르는 쪽 책임**인데 그 책임이 적혀 있지 않았다 |
| `None` 의 **두 번째 까닭** | 기존 문장은 "규칙이 스스로 한 일이면 `None`" 하나만 적었다. 실제로는 **행위를 들고 있지 않은 결과**(`EffectResult`·`ProgressionResult` 는 `action` 칸이 없다)를 넘겼을 때도 `None` 이다 |

`affected` 같은 혼동 표현은 쓰지 않았다 (`test_02` 가 확인한다).

---

## 6. `ObservedEvent.actor` contract — §5 의 답은 **A**

**고치지 않았다.** 그 자리는 이미 두 질문을 구분해 두었고 (§2),
"문맥의 행위자로 **떨어지지 않는다**" 까지 적어 두었다. 즉 §5 의 B 가
요구하는 내용("이 값은 `TimingEvent.actor` 를 의미하며 행동 주체가 아니다")이
**이미 그 문장에 들어 있다.**

여기에 문장을 더하면 같은 말을 두 번 적는 것이 되므로, **A(문서화만 —
이미 되어 있으므로 그대로 둔다)** 를 골랐다. `test_03` 이 그 문장을
**고정**하므로, 누가 약하게 고치면 걸린다 (고의 위반 3번으로 확인).

이름은 바꾸지 않았다 (§11).

### 🟡 남은 위험은 기록해 둔다

`event.actor` 라고 **짧게** 쓰면 사건 쪽(귀속)이 오고, 행위자를 받으려면
`event.context.actor` 라고 **길게** 써야 한다. 자연스러운 쪽이 덜 안전한
쪽이라는 3-F-10 의 측정은 그대로 남아 있다. 이름 변경은 이번 Phase 의
범위가 아니다.

---

## 7. EVENT_RELATION contract

> **행동 주체가 필요한 관계 판단에서는 `EventContext.actor` 를 기준으로
> 한다.**

§6 의 네 사례를 테스트로 고정했다 (`test_04` · `test_05` · `test_06`).

| # | 사례 | `context.actor` | `timing.actor` |
| --- | --- | --- | --- |
| 1 | 내가 소환 | 나 | 나 |
| 2 | 상대가 소환 | 상대 | 상대 |
| 3 | 내가 상대를 공격 | **나** | **피해를 받은 상대** |
| 4 | 상대가 나를 공격 | **상대** | **피해를 받은 나** |

### "상대가 나를 공격했다" 를 판정하면

```
context.actor == 상대  →  OPPONENT      ← 계약대로. 맞다
timing.actor  == 나    →  SELF          ← 다른 질문의 답
```

`test_06` 이 **같은 사건을 두 기준으로 판정해 답이 갈리는 것**을 고정한다.

### 🔴 그리고 두 actor 를 비교해서 행위자를 추론하지 않는다

`test_07` 이 그것을 못박는다. 소환에서는 둘이 같고 전투에서는 다르지만,
**행위자를 읽는 방법은 두 경우 모두 하나**다 — `context.actor`. 일치 여부가
행위자를 정하지 않는다.

---

## 8. Battle 반례

실제 듀얼에서 양방향으로 돌렸다 (`test_05`, parametrize).

| | P1 → P0 공격 | P0 → P1 공격 |
| --- | --- | --- |
| `action.actor` | P1 | P0 |
| `EventContext.actor` | **P1** | **P0** |
| `TimingEvent.actor` | **P0** | **P1** |
| `delta.player` | P0 | P1 |
| LP 가 줄어든 쪽 | P0 | P1 |

**두 방향 모두 `timing` 쪽이 "공격자" 와 어긋난다.** 그리고 양쪽에서
`context.actor == action.actor` 가 성립한다.

---

## 9. LifeChanged

| 개념 | 어디에 있는가 |
| --- | --- |
| **affected player** (LP 가 변한 쪽) | `TimingEvent.actor` = `delta.player` |
| **cause player** (변화를 일으킨 쪽) | **전투에서는** `EventContext.actor`. **효과에서는 선언되지 않으면 없다** |

`LifeChanged` 의 필드는 `player`·`before`·`after` **셋뿐**이고 원인 칸이
없다. **새 field 를 더하지 않았다** (§10 · `test_11`).

효과 경로의 원인은 저널의 `EffectEvent.actor` 에 있고 그것이
`EFFECT_RESOLVED` 라는 **형제 사건**의 actor 로 나온다 (3-F-10 §7 이 측정).
이번 Phase 는 그 배선을 만들지 않았다.

---

## 10. ZoneMoved 주의점

`TimingEvent.actor` 는 **도착지 주인**이다 (`test_10`).

```
delta.source_player      = 0 (나)
delta.destination_player = 1 (상대)
timing.actor             = 1 (상대)     ← "옮긴 사람" 이 아니다
```

출발지와 도착지가 **둘 다 delta 에 남아 있으므로**, 필요하면 delta 를 직접
보면 된다. 사건의 `actor` 를 "옮긴 사람" 으로 읽지 않는다 — 그 주의가
`TimingEvent.actor` 의 docstring 표에 `delta.to_player` 로 적혀 있다.

---

## 11. `None` 이 될 수 있는 경로

### `TimingEvent.actor` = `None` (`test_08`)

| 경로 | 왜 |
| --- | --- |
| `PhaseChanged` | **일부러** 적지 않는다 — 규칙이 하는 일이다 |
| 옮길 시점 이름이 없는 변화 (`ZoneShuffled` · `BattleDestruction` · `CardSet` · `Spell*`) | `UNIMPLEMENTED` 로 남는다 |
| `TimingEvent.unimplemented(note)` | 기본값 |

### `EventContext.actor` = `None` (`test_09`)

| 경로 | 왜 |
| --- | --- |
| 규칙이 스스로 한 일 | 행위가 없다 |
| **행위를 들고 있지 않은 결과** (`EffectResult` · `ProgressionResult`) 를 넘겼고 부르는 쪽이 말해 주지 않았다 | `action` 칸이 없어 자동 충전이 안 된다 |

**두 까닭을 구분하는 것이 계약의 일부다.** `EventContext.__str__` 가 `None` 을
**"규칙"** 으로 읽는 것이 이 필드가 행위자를 뜻한다는 증거이고, 그 어휘를
그대로 두었다.

그리고 **`None` 을 "상대가 아니다" 로 읽지 않는다** — 3-F-8 이 설계 요구로
고정한 것이 그대로 유효하다.

---

## 12. 실제 consumer 현황

**아직 아무도 읽지 않는다** (`test_12`).

| 확인 | 결과 |
| --- | --- |
| `event_pipeline.py`·`trigger.py` **밖에서** 사건의 actor 를 읽는 production 코드 | **0곳** |
| `engine/duel.py` 가 `TriggerRegistry`·`TriggerCollector`·`engine.timing`·`engine.event_pipeline` 를 아는가 | **모른다** |
| `_event_relation` 이 `actor` 를 읽는가 | **아니다** (AST 로 함수 본문 확인) |
| `event_pipeline` 의 production importer | **0** |

> **"현재 consumer 가 없으므로 안전하다"** — 이 계약은 지금 틀린 것을
> 고치는 것이 아니라, **앞으로 틀리지 않게 적어 두는 것**이다. 새 consumer
> 를 더하지 않았고 dormant 파이프라인도 연결하지 않았다 (§7).

---

## 13. 테스트 변경 이유

### `tests/test_actor_role_separation_audit.py::test_03` 을 재작성했다

**삭제하지 않았다.** 이름과 본문을 고쳤고, 그 이유를 테스트 docstring 과
여기에 적는다.

| | |
| --- | --- |
| 전 이름 | `test_03_both_docstrings_promise_the_same_thing` |
| 후 이름 | `test_03_the_two_contracts_are_written_down_and_differ` |

#### 왜 기존 테스트가 잘못된 가정을 갖고 있었는가

그 테스트는 두 설명에 **"일으킨" 이 둘 다 들어 있다**는 것을 근거로 "두
설명이 똑같은 것을 약속한다" 고 단정했다. **그 결론은 그때도 너무
강했다.**

1. `EventContext.actor` 는 "일으킨 **행위의 주체**" 라고 적혀 있었고 그것은
   **맞는 설명**이었다 (행위자). 틀린 것은 `TimingEvent.actor` 쪽
   **하나**였다.
2. 그리고 그 테스트는 `ObservedEvent.actor` 의 **자기 docstring 을 읽지
   않았다** — 그 자리가 이미 두 질문을 구분해 두고 있었다.

즉 "같은 단어가 들어 있다" 를 "같은 것을 약속한다" 로 읽은 것이 잘못된
가정이었다. **단어가 아니라 문장이 무엇을 주장하는지를 봐야 했다.**

#### 지금은 무엇을 검증하는가 (§8)

| | 검증 |
| --- | --- |
| A | 두 actor 가 **같을 수 있다** — 소환 |
| B | 두 actor 가 **다를 수 있다** — P1 이 P0 을 공격 |
| C | 달라도 **각자의 계약을 만족하면 정상이다** — `context.actor == action.actor` · `timing.actor == 피해를 받은 쪽` |

그리고 §9 가 금지한 단정을 쓰지 않았다 — `assert timing.actor == context.actor`
도 `assert event.actor == action.actor` 도 **없다**. 두 값을 각자의 계약으로
따로 확인한다.

### 신규 `tests/test_actor_semantic_contract.py` — 16건

| # | 이름 | §16 |
| --- | --- | --- |
| 01 | the timing actor contract is written and forbids the agent claim | 3 |
| 02 | the context actor contract is written with both none reasons | 4 |
| 03 | the observed actor already distinguished the two questions | 5 |
| 04 | a summon pins both actors to the summoner (×2) | 6 1·2 |
| 05 | a battle pins the two actors to different players (×2) | 6 3·4 |
| 06 | **the relation uses the context actor** | 7 |
| 07 | **the two actors must not be compared to infer the agent** | 6 |
| 08 | the timing actor is none only where the delta has no player | 9 |
| 09 | the context actor is none for two different reasons | 9 |
| 10 | a zone move keeps source and destination separate | 6 |
| 11 | **only docstrings changed** | 10 · 11 · 13 |
| 12 | **no production consumer was added** | 7 · 10 |
| 13 | the board and the rng are untouched | 14 |
| 14 | the search ranking is untouched | 14 |

```
$ python3 -m pytest tests/test_actor_semantic_contract.py -p no:randomly -q
16 passed in 9.10s
```

### 고의 위반 검증 — 6건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `TimingEvent.actor` docstring 을 **거짓 문장으로 되돌린다** | 신규 `test_01` · `test_10` · 수정된 `test_03` |
| 2 | `EventContext.actor` 에서 "선언" 문장을 뺀다 | 신규 `test_02` · 수정된 `test_03` |
| 3 | `ObservedEvent.actor` docstring 을 약하게 고친다 | 신규 `test_03` · 수정된 `test_03` |
| 4 | `ObservedEvent.actor` 가 context 쪽을 돌려준다 | 14건 (3-F-10 쪽 포함) |
| 5 | `LifeChanged` 에 `cause_player` 를 더한다 | 신규 `test_11` · 3-F-10 의 `test_11`·`test_22` |
| 6 | `duel.py` 가 `context.actor` 를 읽는다 | 신규 `test_12` · 3-F-10 의 `test_18` |

1·2·3 이 **문서 계약이 실제로 고정되었다**는 증거다 — 되돌리면 걸린다.

주입 파일 4개는 전부 백업에서 복원하고 md5 로 확인했다 (모두 `OK`).

### 🔴 회귀가 5건 깨졌고, 전부 "줄 번호 · 줄 수" snapshot 이었다

처음 전체 회귀는 **`5 failed, 4310 passed, 4 skipped`** 였다. §14 는
"production behavior 가 바뀌면 즉시 중단하고 왜 바뀌었는지 보고한다" 를
요구한다. 그래서 먼저 **바뀐 것이 behavior 인지 줄 번호인지** 를 갈랐다.

| # | 깨진 테스트 | 무엇을 고정하고 있었나 | 왜 깨졌나 |
| --- | --- | --- | --- |
| 1 | `test_event_relation_input_boundary_audit.py::test_15` | `engine/trigger.py` 안에 `"이 사건을 일으킨 플레이어"` 라는 **거짓 문장이 있다** | 이 Phase 가 그 문장을 **지웠다** |
| 2 | `test_rule_not_implemented_code_audit.py::test_02` | `PROSE_OCCURRENCES` = `(파일, 줄번호)` 12쌍 | `trigger.py` 네 자리가 **+17 줄 밀렸다** |
| 3 | `test_trigger_pipeline_dormant_audit.py::test_01` | 부품 층 3모듈의 줄 수 합 2,681 | `trigger.py` 1,644 → **1,661** |
| 4 | `test_trigger_pipeline_dormant_audit.py::test_02` | 조립 층 2모듈의 줄 수 합 853 | `event_pipeline.py` 417 → **429** |
| 5 | `test_trigger_pipeline_dormant_audit.py::test_25` | 6모듈 줄 수 snapshot | 위 둘과 같은 두 모듈 |

2 ~ 5 는 **behavior 를 전혀 재지 않는다.** 재는 것은 줄 수와 줄 번호뿐이고,
docstring 을 늘리면 반드시 움직인다. 그리고 §14 가 요구하는 증거 — 모든
문자열 리터럴을 `"<str>"` 로 바꾼 뒤 비교한 AST 가 **두 파일 모두 전후
동일** — 이 이미 있다 (`test_13` · `test_14`). 즉 **production behavior 는
바뀌지 않았고, 중단 조건에 해당하지 않는다.**

#### 어떻게 고쳤는가 (assertion 을 약화하지 않았다)

- **2**: 네 줄 번호를 `978 → 995` · `1318 → 1335` · `1324 → 1341` ·
  `1347 → 1364` 으로 **실측값으로 갱신**했다. 밀린 자리가 전부 같은 +17 이고,
  **산문 12 · 코드 67 · 문자열 79 라는 세 숫자는 하나도 바뀌지 않았다** — 그
  세 단정은 그대로 두었다. 바뀐 것이 줄 번호뿐이라는 것 자체가 증거다.
- **3 · 4 · 5**: 줄 수를 실측값 (`trigger.py` 1,661 · `event_pipeline.py` 429)
  으로 갱신하고, **왜 늘었는지 (docstring 뿐이고 AST 가 동일하다)** 를 각
  테스트의 `.. note::` 에 적었다. 다른 네 모듈의 숫자는 **건드리지 않았다** —
  그것이 "이 Phase 가 dormant 구조를 활성화하지 않았다" 의 증거다.
- **1 은 성격이 다르다.** 아래에 따로 적는다.

#### 왜 기존 `test_15` 가 잘못된 가정을 갖고 있었는가

3-F-8 이 `event.actor` 의 polysemy 를 처음 찾았을 때, 그 결함의 증거로
**"설명이 틀렸다"** 를 골랐다 — `assert "이 사건을 일으킨 플레이어" in
trigger_source`. 이 모양은 **결함을 고치면 반드시 깨진다.** 거짓 문장이 있는
것을 pin 했기 때문에, 거짓 문장을 지우는 것이 테스트를 깨뜨린다.

**결함 자체는 사라지지 않았다.** 같은 테스트의 나머지 실측 — `from_delta` 가
사건군마다 다른 칸에서 가져온다 · `LifeChanged` 는 **당한 쪽** 이다 ·
컨트롤이 넘어가는 `ZoneMoved` 의 `actor` 는 **도착지 주인** 이다 — 은 한 줄도
바뀌지 않았고 전부 그대로 통과한다. 그래서 이 테스트는 **삭제하지 않았다.**

바꾼 것은 증거의 방향뿐이다:

```python
#: 전 (3-F-8)
assert "이 사건을 일으킨 플레이어" in trigger_source

#: 후 (3-F-11)
assert "이 사건을 일으킨 플레이어" not in trigger_source
assert "**행위의 주체가 아니다**" in trigger_source
assert "사건군마다 다르다" in trigger_source
```

단정 수는 1 → 3 으로 **늘었다.** 거짓 문장이 **없다** 는 것과, 사건군별 뜻을
밝힌 표가 **있다** 는 것을 동시에 고정한다 — 되돌리면 걸린다 (고의 위반 1번이
이것을 쓴다).

### 전체 회귀

| 실행 | 결과 |
| --- | --- |
| 1회차 (snapshot 갱신 전) | `5 failed, 4310 passed, 4 skipped in 376.25s` |
| **2회차 (최종)** | **`4315 passed, 4 skipped in 379.24s`** |

`4,299` (3-F-10 baseline) `+ 16` (신규) `= 4,315`. **실패 0 · skip 은 그대로 4
건**이고, 늘어난 수가 신규 테스트 수와 정확히 맞는다 — 즉 **갱신된 5건은
사라지지도, 늘어나지도 않았다.**

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리

**삭제 0건 · skip 추가 0건 · assertion 약화 0건.**

수정 **6개 테스트 함수**, 전부 이유를 적었다. 그중 **5개는 회귀가 깨져서**
고친 것이고, `test_03` 하나는 **§8 이 요구해서** 고친 것이다 (깨지지 않았다).

| 테스트 | 수정 | 단정 수 |
| --- | --- | --- |
| `test_actor_role_separation_audit.py::test_03` | 재작성 (§13 위) | 5 → **13** |
| `test_event_relation_input_boundary_audit.py::test_15` | 단정 방향 교체 | 1 → **3** (나머지 실측은 그대로) |
| `test_rule_not_implemented_code_audit.py::test_02` | 줄 번호 4개 | 그대로 (79 · 67 · 12 유지) |
| `test_trigger_pipeline_dormant_audit.py::test_01` | 줄 수 1개 | 그대로 |
| `test_trigger_pipeline_dormant_audit.py::test_02` | 줄 수 1개 | 그대로 |
| `test_trigger_pipeline_dormant_audit.py::test_25` | 줄 수 2개 | 그대로 |

**어느 수정도 production 을 건드려 통과시킨 것이 아니다.** 반대로 production
쪽은 이 Phase 가 고친 거짓 docstring 하나뿐이고, 그것 때문에 **테스트가
깨지는 것이 정상**이었다 — 깨진 쪽이 거짓을 고정하고 있었기 때문이다.

---

## 14. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
 engine/event_pipeline.py | 14 +++++++++++++-
 engine/trigger.py        | 19 ++++++++++++++++++-
 2 files changed, 31 insertions(+), 2 deletions(-)
```

**docstring 둘뿐이다.** 문자열 리터럴을 제거한 AST 가 수정 전후로 동일함을
확인했다 — 즉 **실행되는 코드가 한 글자도 바뀌지 않았다.**

그래서 줄 수만 움직였다: `engine/trigger.py` 1,644 → **1,661** ·
`engine/event_pipeline.py` 417 → **429**. 이 두 숫자를 snapshot 으로 들고 있던
기존 테스트 5건이 깨졌고, 그것이 §14 가 말하는 "production behavior 변경" 이
**아님**을 위 AST 동일성으로 확인한 뒤 숫자를 갱신했다 (§13). 중단 조건에
해당하지 않는다.

§13 의 금지 항목 전부 미실행: engine behavior · Event/Delta/TimingEvent/
EventContext 구조 · `TriggerSpec` · `EVENT_RELATION` 연결 · `TriggerRegistry`
연결 · `legal_actions` · Search/Evaluation/AI · Engine V1 **전부 변경
없음**.

---

## 15. state_hash / RNG / Search / AI 영향

| 확인 | 결과 |
| --- | --- |
| `state_hash` | **불변** (`test_13` — 세 번 반복) |
| `canonical_state` | 변경 없음 |
| RNG | **불변** |
| clone 동작 | 변경 없음 |
| Search ranking | **digest 동일** `30fa3597…` (6판 611결정 — 3-F-5 ~ 3-F-10 과 같은 값) |
| Evaluation / AI | 변경 없음 |
| hidden information 경계 | 변경 없음 (`test_13`) |
| Engine V1 freeze | **유지** |

**production behavior 가 바뀐 흔적이 없다** — docstring 변경이므로 당연하지만,
§14 가 요구한 대로 측정으로 확인했다.

---

## 16. 최종 판정

### **A. ACTOR_SEMANTIC_CONTRACT_FIXED**

> 문서/테스트 수준에서 두 actor 의 의미가 명확하게 고정되었고 production
> 변경이 필요 없다.

판정 기준("값이 같으냐가 아니라 **각 값이 무엇을 의미하는지가 명확하게
고정되었는가**")에 답한다.

| 항목 | 상태 |
| --- | --- |
| `TimingEvent.actor` 의 뜻이 적혀 있는가 | 🟢 **그렇다** — 귀속 대상이고 행위자가 아니라고 못박았고, 사건군별 출처표와 전투 반례가 들어 있다 |
| `EventContext.actor` 의 뜻이 적혀 있는가 | 🟢 **그렇다** — 행위의 주체 · 선언 · `None` 두 까닭 · 검증 없음(책임) |
| 둘이 다르다는 것이 적혀 있는가 | 🟢 **세 자리에** — 두 필드의 docstring 이 서로를 가리키고, `ObservedEvent.actor` 가 두 질문을 구분한다 |
| 관계 판정이 어느 값을 쓰는지 정해졌는가 | 🟢 **`EventContext.actor`** (§7, `test_06`) |
| 그 계약이 되돌려지면 알 수 있는가 | 🟢 **그렇다** — 고의 위반 1·2·3 이 전부 걸린다 |
| production 실행 변경이 필요했는가 | 🟢 **아니다** — AST 동일 |

### 왜 B 가 아닌가

B 는 "현재 코드 구조상 **추가 문서화가 필요하다**" 다. §12 가 요구한 열한
항목을 이 문서가 다 담았고, 그 가운데 **production 에 적혀야 하는 것**
(두 actor 의 뜻, 서로 다르다는 사실, `None` 의 까닭)은 docstring 으로
들어갔다. 남은 것은 **이름 위험**(§6)인데 그것은 문서화가 아니라
naming migration 이고 §11 이 금지했다.

### 왜 C 가 아닌가

C 는 "기존 production 코드/테스트/문서 사이에 **실제 semantic 충돌**이
발견되었다" 다. 충돌이 아니라 **한 문장의 거짓**이었고, 그것을 읽는
consumer 가 **하나도 없었다**(§12). 기존 테스트 가운데 잘못된 계약을
단정하던 것도 **내가 전 Phase 에 쓴 `test_03` 하나**였고, 고쳤다.

### 왜 D 가 아닌가

예상보다 큰 구조 문제는 없었다. 오히려 **이미 맞게 적혀 있던 것이 더
많았다** — `EventContext.actor` 의 뜻과 `ObservedEvent.actor` 의 구분이
그렇다.

### 🟡 다만 "계약이 고정되었다" 가 "관계 판정이 가능해졌다" 는 뜻은 아니다

이 Phase 가 정한 것은 **어느 값을 읽어야 하는가**다. 그 값을 실제로
`EVENT_RELATION` 에 넘기는 일은 하지 않았고(§7 금지), 효과 경로에서
`context.actor` 를 채우는 배선도 없다(3-F-10 §12 가 유보로 남긴 것).

---

## 17. 다음 Phase 후보 (1개)

**Phase 3-F-12 — 효과 경로에서 `EventContext.actor` 를 채우는 호출 규약 감사**

§11 이 적은 `None` 의 **두 번째 까닭**만 본다. 계약은 "행위 주체가 필요하면
`context.actor`" 로 정해졌는데, **효과 경로에서는 그 값이 비어 있다** —
그래서 지금 계약대로 쓰면 카드 효과로 일어난 일은 전부 `UNKNOWN` 이 된다.

그 Phase 가 답해야 할 것:

1. 효과 경로에서 **무엇이 행위자인가** — `ResolutionContext.controller` 인가
   `EffectEvent.actor` 인가. 둘이 늘 같은지 측정한다.
2. 그 값을 **누가** 넘겨야 하는가 — `EventReader.read(result, actor=…)` 의
   부르는 쪽은 지금 production 에 **없다**(importer 0). 그러면 규약을
   적을 자리가 docstring 인가, 아니면 부르는 쪽이 생길 때까지 미루는
   것이 맞는가.
3. 비용 지불(`CostPaymentEvent`)과 체인 해결도 같은 규약을 쓰는가 —
   `actor` 칸이 있지만 그 뜻이 효과와 같은지 확인한다.
4. 규약을 적으면 이 Phase 의 `test_09`(두 까닭 구분)가 **여전히 맞는가** —
   두 번째 까닭이 사라지면 그 테스트도 함께 갱신해야 한다.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**

---

## Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`a6087bc`** `Phase 3-F-11: fix actor semantic contract` |
| 포함 파일 | `engine/trigger.py` · `engine/event_pipeline.py` · 테스트 5파일 (신규 1 · 수정 4) |
| push | `51123f7..a6087bc` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-11: document actor semantic contract` |

작업 직전 HEAD 는 `51123f7` (3-F-10 보고서) 였고, push 결과가 그 SHA 에서
이어진 것으로 확인된다.
