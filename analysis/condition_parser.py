"""
Lua 조건식의 부울 구조 파서.

조건 함수의 본문을 읽어 ``and`` / ``or`` / ``not`` 관계를 트리로 보존한다.
평탄화하면 "둘 중 하나면 된다"가 "둘 다 필요하다"로 바뀌므로 구조가 중요하다.

다루는 형태
-----------
- ``return A and B``
- ``return A or B``
- ``return not A``
- ``return (A or B) and C``        괄호가 우선순위를 바꾸는 경우
- ``return A and (B or C)``
- 중첩 ``AND(가드, X, OR(AND(...), AND(..., NOT(...))))``
- 가드 절 ``if not (X) then return false end`` -> X 를 AND 가지로 편입

Lua 연산자 우선순위는 ``not`` > ``and`` > ``or`` 이며 그대로 따른다.

읽지 못한 부분은 지어내지 않는다. 분류하지 못한 항목은 leaf 의 ``raw`` 에
원문 그대로 남고, 조건식 자체를 파싱하지 못하면 ``None`` 을 돌려준다.
"""

from __future__ import annotations

import copy
import re

from analysis.effect_model import BoolOp, ConditionNode

# ``if <표현식> then return false end`` 형태의 가드 절
_RE_GUARD = re.compile(
    r"\bif\s+(?P<expr>.+?)\s+then\s+return\s+false\s+end", re.S
)
# ``if X then return A else return B end`` — 분기에 따라 조건이 갈린다.
# 중첩 if 는 다루지 않는다 (안쪽에 if 가 없는 경우만).
_RE_IF_ELSE = re.compile(
    r"\bif\s+(?P<cond>(?:(?!\bif\b).)+?)\s+then\s+"
    r"return\s+(?P<then>(?:(?!\bif\b).)+?)\s+"
    r"else\s+return\s+(?P<else>(?:(?!\bif\b).)+?)\s+end",
    re.S,
)
# ``if <표현식> then return true end`` — 그것만으로 충분한 조건
_RE_SUFFICIENT = re.compile(
    r"\bif\s+(?P<expr>.+?)\s+then\s+return\s+true\s+end", re.S
)
# ``return <표현식>`` (한 문장). ``end`` 를 넘어가지 않는다.
_RE_RETURN = re.compile(r"\breturn\s+(?P<expr>[^\n]+?)\s*(?:\bend\b|$)", re.S)
# ``local name=expr`` — 지역 변수를 조건식에서 되살리기 위해 모은다
_RE_LOCAL = re.compile(r"\blocal\s+(\w+)\s*=\s*([^\n]+)")

_TOKEN = re.compile(r"\(|\)|\bnot\b|\band\b|\bor\b")


class LuaConditionParser:
    """조건 함수 본문 -> :class:`ConditionNode`."""

    def __init__(self, classify_leaf=None, analyze_predicate=None):
        """
        Args:
            classify_leaf: leaf 원문을 받아 :class:`ActivationRequirement` 또는
                ``None`` 을 돌려주는 함수. 분류는 호출자(분석기)가 맡는다.
            analyze_predicate: leaf 원문을 받아 세부 술어를 돌려주는 함수.
        """
        self.classify_leaf = classify_leaf or (lambda _text: None)
        self.analyze_predicate = analyze_predicate or (lambda _text: None)

    # ------------------------------------------------------------------
    def parse_function(self, body: str) -> ConditionNode | None:
        """
        조건 함수 전체를 트리로 만든다.

        가드 절과 최종 ``return`` 을 모두 AND 로 묶는다. 가드는
        "이 조건이 아니면 발동할 수 없다"는 뜻이므로 부정이 한 번 뒤집힌다.
        """
        if not body or not body.strip():
            return None
        locals_map = self._collect_locals(body)
        body = _join_continuations(body)

        # if/else 분기는 그 자체로 완결된 조건이다.
        #     if X then return A else return B end
        #   = (X 이고 A) 또는 (X 가 아니고 B)
        # 마지막 return 만 보면 분기 하나를 통째로 잃는다.
        branch = _RE_IF_ELSE.search(body)
        if branch is not None:
            resolved = self._parse_if_else(branch, locals_map)
            if resolved is not None:
                return resolved

        branches: list[ConditionNode] = []
        for match in _RE_GUARD.finditer(body):
            guard = self._parse_guard(match.group("expr"), locals_map)
            if guard is not None:
                branches.append(guard)

        # ``if X then return true end`` 은 X 만으로 충분하다는 뜻이므로
        # 나머지 전체와 OR 로 묶인다. AND 로 합치면 의미가 반대가 된다.
        sufficient: list[ConditionNode] = []
        stripped = _RE_GUARD.sub(" ", body)
        for match in _RE_SUFFICIENT.finditer(stripped):
            node = self.parse_expression(match.group("expr"), locals_map)
            if node is not None:
                sufficient.append(node)
        stripped = _RE_SUFFICIENT.sub(" ", stripped)

        # 조건식으로 쓰이는 마지막 return 문
        returns = [m.group("expr") for m in _RE_RETURN.finditer(stripped)]
        for expression in reversed(returns):
            if expression.strip() in ("true", "false"):
                continue
            node = self.parse_expression(expression, locals_map)
            if node is not None:
                branches.append(node)
            break

        required = self._combine(branches, BoolOp.AND, body)
        if required is None:
            return self._combine(sufficient, BoolOp.OR, body)
        if not sufficient:
            return required
        return self._combine([*sufficient, required], BoolOp.OR, body)

    def _combine(self, nodes, op, raw) -> ConditionNode | None:
        nodes = [n for n in nodes if n is not None]
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
        return ConditionNode(op=op, children=nodes, raw=raw.strip()[:200])

    def _parse_if_else(self, match, locals_map) -> ConditionNode | None:
        """``if X then return A else return B end`` 을 OR 로 펼친다."""
        condition = self.parse_expression(match.group("cond"), locals_map)
        if condition is None:
            return None

        def side(expression: str, negate: bool) -> ConditionNode | None:
            text = expression.strip()
            # 두 가지가 같은 노드를 공유하면 부정 표시가 서로 덮어쓴다.
            # 가지마다 별도의 사본을 쓴다.
            branch_condition = copy.deepcopy(condition)
            guard = (
                ConditionNode(
                    op=BoolOp.NOT, children=[branch_condition], raw=text[:200]
                )
                if negate
                else branch_condition
            )
            if text == "false":
                return None  # 이 가지로는 발동할 수 없다
            if text == "true":
                return guard
            value = self.parse_expression(text, locals_map)
            if value is None:
                return guard
            return ConditionNode(
                op=BoolOp.AND, children=[guard, value], raw=text[:200]
            )

        sides = [
            side(match.group("then"), False),
            side(match.group("else"), True),
        ]
        return self._combine(sides, BoolOp.OR, match.group(0))

    def _parse_guard(self, expression: str, locals_map) -> ConditionNode | None:
        """
        ``if X then return false end`` 은 "X 이면 발동 못 함" 이므로 NOT(X) 가
        발동 조건이 된다. ``if not X then ...`` 이면 이중 부정이 풀려 X 가 된다.
        """
        text = expression.strip()
        inner = self._strip_leading_not(text)
        if inner is not None:
            return self.parse_expression(inner, locals_map)
        node = self.parse_expression(text, locals_map)
        if node is None:
            return None
        return ConditionNode(op=BoolOp.NOT, children=[node], raw=text[:200])

    @staticmethod
    def _strip_leading_not(text: str) -> str | None:
        """맨 앞의 ``not`` 을 벗겨낸다. 없으면 ``None``."""
        stripped = text.strip()
        if not re.match(r"^not\b", stripped):
            return None
        rest = stripped[3:].strip()
        # ``not (X)`` 처럼 전체가 괄호면 그 안이 대상이다.
        if rest.startswith("(") and _matching_paren(rest, 0) == len(rest) - 1:
            return rest[1:-1]
        return rest

    # ------------------------------------------------------------------
    def parse_expression(self, expression: str, locals_map=None) -> ConditionNode | None:
        text = " ".join((expression or "").split())
        if not text:
            return None
        return self._parse_or(text, locals_map or {})

    def _parse_or(self, text: str, locals_map) -> ConditionNode | None:
        parts = _split_operator(text, "or")
        if len(parts) > 1:
            children = [self._parse_and(p, locals_map) for p in parts]
            children = [c for c in children if c is not None]
            if not children:
                return None
            if len(children) == 1:
                return children[0]
            return ConditionNode(op=BoolOp.OR, children=children, raw=text[:200])
        return self._parse_and(text, locals_map)

    def _parse_and(self, text: str, locals_map) -> ConditionNode | None:
        parts = _split_operator(text, "and")
        if len(parts) > 1:
            children = [self._parse_not(p, locals_map) for p in parts]
            children = [c for c in children if c is not None]
            if not children:
                return None
            if len(children) == 1:
                return children[0]
            return ConditionNode(op=BoolOp.AND, children=children, raw=text[:200])
        return self._parse_not(text, locals_map)

    def _parse_not(self, text: str, locals_map) -> ConditionNode | None:
        stripped = text.strip()
        inner = self._strip_leading_not(stripped)
        if inner is not None:
            child = self._parse_or(inner, locals_map)
            if child is None:
                return None
            # NOT(NOT(x)) 는 x 로 접는다.
            if child.op is BoolOp.NOT and len(child.children) == 1:
                return child.children[0]
            return ConditionNode(op=BoolOp.NOT, children=[child], raw=stripped[:200])
        return self._parse_primary(stripped, locals_map)

    def _parse_primary(self, text: str, locals_map) -> ConditionNode | None:
        stripped = text.strip()
        if not stripped:
            return None
        # 표현식 전체를 감싼 괄호는 벗겨내고 다시 본다.
        if stripped.startswith("(") and _matching_paren(stripped, 0) == len(stripped) - 1:
            return self._parse_or(stripped[1:-1], locals_map)
        # 지역 변수를 되돌린 표현으로 해석하되, raw 는 원문 그대로 남긴다.
        expanded = _expand_locals(stripped, locals_map)
        return ConditionNode(
            op=BoolOp.LEAF,
            requirement=self.classify_leaf(expanded),
            predicate=self.analyze_predicate(expanded),
            raw=stripped[:200],
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _collect_locals(body: str) -> dict[str, str]:
        """
        ``local phase=Duel.GetCurrentPhase()`` 같은 대입을 모은다.

        조건식이 지역 변수를 거쳐 호출 결과를 비교하는 일이 흔하다. 이걸 되살리지
        않으면 ``phase==PHASE_DAMAGE`` 가 분류 불가로 남는다.
        """
        found: dict[str, str] = {}
        for name, value in _RE_LOCAL.findall(body):
            found[name] = value.strip()
        return found


def _join_continuations(body: str) -> str:
    """
    여러 줄에 걸친 문장을 한 줄로 잇는다.

    조건식은 ``and`` / ``or`` 뒤에서 줄바꿈되는 일이 흔하다. 줄 단위로 읽으면
    뒤쪽 가지를 통째로 잃어버려 중첩 OR 가 사라진다.
    """
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    joined: list[str] = []
    buffer = ""
    for index, line in enumerate(lines):
        buffer = f"{buffer} {line}".strip() if buffer else line
        # 괄호가 닫히지 않았거나 연결 연산자로 끝나면 다음 줄과 이어진다.
        unbalanced = buffer.count("(") > buffer.count(")")
        trailing = bool(re.search(r"\b(and|or|not)$", buffer)) or buffer.endswith(
            (",", "(")
        )
        # 다음 줄이 연결 연산자로 시작하는 경우도 이어진다.
        # 조건식은 줄 끝이 아니라 줄 머리에 and/or 를 두는 쪽이 더 흔하다.
        following = (
            bool(re.match(r"^(and|or)\b", lines[index + 1]))
            if index + 1 < len(lines)
            else False
        )
        if unbalanced or trailing or following:
            continue
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return "\n".join(joined)


def _expand_locals(text: str, locals_map: dict[str, str]) -> str:
    """leaf 분류 전에 지역 변수를 원래 표현식으로 되돌린다."""
    if not locals_map:
        return text
    expanded = text
    for name, value in locals_map.items():
        expanded = re.sub(rf"\b{re.escape(name)}\b", f"({value})", expanded)
    return expanded


def _matching_paren(text: str, index: int) -> int:
    """``text[index]`` 의 여는 괄호에 대응하는 닫는 괄호 위치. 없으면 -1."""
    depth = 0
    for i in range(index, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_operator(text: str, operator: str) -> list[str]:
    """
    괄호 밖에 있는 ``operator`` 로만 나눈다.

    괄호 안의 연산자로 나누면 ``(A or B) and C`` 가 ``A`` / ``B) and C`` 로
    잘려 구조가 무너진다.
    """
    parts: list[str] = []
    depth = 0
    last = 0
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif token == operator and depth == 0:
            parts.append(text[last : match.start()])
            last = match.end()
    parts.append(text[last:])
    return [p.strip() for p in parts if p.strip()]
