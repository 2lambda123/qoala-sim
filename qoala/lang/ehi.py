from dataclasses import dataclass
from typing import Dict, List, Tuple, Type

from netqasm.lang.instr.base import NetQASMInstruction
from netqasm.lang.instr.flavour import Flavour


@dataclass(eq=True, frozen=True)
class ExposedQubitInfo:
    is_communication: bool
    decoherence_rate: float  # rate per second


@dataclass(eq=True, frozen=True)
class ExposedGateInfo:
    instruction: Type[NetQASMInstruction]
    duration: int  # ns
    decoherence: List[int]  # rate per second, per qubit ID (same order as `ids`)


@dataclass(eq=True, frozen=True)
class ExposedHardwareInfo:
    """Hardware made available to offline compiler."""

    qubit_infos: Dict[int, ExposedQubitInfo]  # qubit ID -> info

    flavour: Type[
        Flavour
    ]  # set of NetQASM instrs, no info about which qubits can do what instr
    single_gate_infos: Dict[int, List[ExposedGateInfo]]  # qubit ID -> gates
    multi_gate_infos: Dict[
        Tuple[int, ...], List[ExposedGateInfo]
    ]  # ordered qubit ID list -> gates


@dataclass(eq=True, frozen=True)
class UnitModule:
    """Virtual memory space for programs. Target for a compiler.

    Simply wraps around a ExposedHardwareInfo object and provides convenience methods.

    Unit Modules should be used as the interface for compilers and schedulers,
    as well as the program itself.
    Only the Memory Manager should use an ExposedHardwareInfo object itself,
    namely the object that represents the full quantum memory space of the node."""

    info: ExposedHardwareInfo

    def is_communication(self, qubit_id: int) -> bool:
        return self.info.qubit_infos[qubit_id].is_communication
