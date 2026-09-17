"""
듀얼 상태 계층 (Phase 1).

규칙은 담지 않는다. "지금 판이 어떤 모양인가"만 정확하게 표현한다.
"""

from engine.state.card_instance import AppliedEffect, CardInstance, PreviousState
from engine.state.game_state import DuelResult, GameState
from engine.state.player import PlayerState, TurnFlags, UseRegistry
from engine.state.turn import TurnState
from engine.state.zones import ZoneContainer

__all__ = [
    "AppliedEffect",
    "CardInstance",
    "PreviousState",
    "ZoneContainer",
    "PlayerState",
    "TurnFlags",
    "UseRegistry",
    "TurnState",
    "GameState",
    "DuelResult",
]
