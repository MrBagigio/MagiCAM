"""maya_bridge fuori da Maya: solo la forma (import, unita', comandi accodati). L'esecuzione in Maya e' F1.8."""

import math

import pytest

from magicam import maya_bridge
from magicam.protocol import Command, CommandMessage
from magicam.receiver import Receiver
from magicam.session import Session


def test_units_table_is_consistent():
    assert maya_bridge.UNITS_PER_METER["cm"] == 100.0
    assert abs(maya_bridge.UNITS_PER_METER["in"] * 0.0254 - 1.0) < 1e-12
    assert abs(maya_bridge.UNITS_PER_METER["ft"] * 0.3048 - 1.0) < 1e-12


def test_commands_are_queued_not_executed_in_network_thread():
    r = Receiver(port=0, host="127.0.0.1")
    b = maya_bridge.MayaCameraBridge(Session(), r, "camera1")
    r.on_command(CommandMessage(1, 0.0, Command.FREEZE), ("127.0.0.1", 1))
    assert len(b._commands) == 1 and not b.session.state().frozen
    b._drain_commands()
    assert b.session.state().frozen


def test_tick_without_maya_and_without_poses_costs_nothing_and_does_not_raise():
    r = Receiver(port=0, host="127.0.0.1")
    b = maya_bridge.MayaCameraBridge(Session(), r, "camera1")
    b.tick()
    assert b.stats.ticks == 1 and b.stats.applied == 0 and math.isfinite(b.stats.last_cost_ms)


def test_units_per_meter_needs_maya():
    with pytest.raises(ImportError):
        maya_bridge.units_per_meter()
