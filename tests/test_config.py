from __future__ import annotations

import os
from typing import Any, Dict, Type

from netsquid.components.instructions import (
    INSTR_CNOT,
    INSTR_H,
    INSTR_X,
    INSTR_Y,
    INSTR_Z,
)
from netsquid.components.instructions import Instruction as NetSquidInstruction
from netsquid.components.models.qerrormodels import (
    DepolarNoiseModel,
    QuantumErrorModel,
    T1T2NoiseModel,
)

from qoala.lang.common import MultiQubit
from qoala.runtime.config import (
    BaseModel,
    GateConfig,
    GateConfigRegistry,
    GateDepolariseConfig,
    GateNoiseConfigInterface,
    InstrConfigRegistry,
    LatenciesConfig,
    MultiGateConfig,
    ProcNodeConfig,
    QubitConfig,
    QubitConfigRegistry,
    QubitIdConfig,
    QubitNoiseConfigInterface,
    QubitT1T2Config,
    SingleGateConfig,
    TopologyConfig,
)


def relative_path(path: str) -> str:
    return os.path.join(os.getcwd(), os.path.dirname(__file__), path)


def test_qubit_t1t2_config():
    cfg = QubitT1T2Config(T1=1e6, T2=3e6)

    assert cfg.T1 == 1e6
    assert cfg.T2 == 3e6


def test_qubit_t1t2_config_file():
    cfg = QubitT1T2Config.from_file(relative_path("configs/qubit_cfg_1.yaml"))

    assert cfg.T1 == 1e6
    assert cfg.T2 == 3e6


def test_qubit_config():
    noise_cfg = QubitT1T2Config(T1=1e6, T2=3e6)
    cfg = QubitConfig(
        is_communication=True,
        noise_config_cls="QubitT1T2Config",
        noise_config=noise_cfg,
    )

    assert cfg.is_communication
    assert cfg.to_is_communication()
    assert cfg.to_error_model() == T1T2NoiseModel
    assert cfg.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}


def test_qubit_config_perfect():
    for comm in [True, False]:
        cfg = QubitConfig.perfect_config(is_communication=comm)
        assert cfg.is_communication == comm
        assert cfg.to_is_communication() == comm
        assert cfg.to_error_model() == T1T2NoiseModel
        assert cfg.to_error_model_kwargs() == {"T1": 0, "T2": 0}


def test_qubit_config_file():
    cfg = QubitConfig.from_file(relative_path("configs/qubit_cfg_2.yaml"))

    assert cfg.is_communication
    assert cfg.to_is_communication()
    assert cfg.to_error_model() == T1T2NoiseModel
    assert cfg.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}


def test_gate_depolarise_config():
    cfg = GateDepolariseConfig(duration=4e3, depolarise_prob=0.2)

    assert cfg.duration == 4e3
    assert cfg.depolarise_prob == 0.2


def test_gate_depolarise_config_file():
    cfg = GateDepolariseConfig.from_file(relative_path("configs/gate_cfg_1.yaml"))

    assert cfg.duration == 4e3
    assert cfg.depolarise_prob == 0.2
    assert cfg.to_duration() == 4e3
    assert cfg.to_error_model() == DepolarNoiseModel
    assert cfg.to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_gate_config():
    noise_cfg = GateDepolariseConfig(duration=4e3, depolarise_prob=0.2)
    cfg = GateConfig(
        name="INSTR_X", noise_config_cls="GateDepolariseConfig", noise_config=noise_cfg
    )

    assert cfg.name == "INSTR_X"
    assert cfg.to_instruction() == INSTR_X
    assert cfg.to_duration() == 4e3
    assert cfg.to_error_model() == DepolarNoiseModel
    assert cfg.to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_gate_config_perfect():
    cfg = GateConfig.perfect_config(name="INSTR_X", duration=4e3)

    assert cfg.name == "INSTR_X"
    assert cfg.to_instruction() == INSTR_X
    assert cfg.to_duration() == 4e3
    assert cfg.to_error_model() == DepolarNoiseModel
    assert cfg.to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }


def test_gate_config_file():
    cfg = GateConfig.from_file(relative_path("configs/gate_cfg_2.yaml"))

    assert cfg.name == "INSTR_X"
    assert cfg.to_instruction() == INSTR_X
    assert cfg.to_duration() == 4e3
    assert cfg.to_error_model() == DepolarNoiseModel
    assert cfg.to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_topology_config():
    qubit_noise_cfg = QubitT1T2Config(T1=1e6, T2=3e6)
    qubit_cfg = QubitConfig(
        is_communication=True,
        noise_config_cls="QubitT1T2Config",
        noise_config=qubit_noise_cfg,
    )
    gate_noise_cfg = GateDepolariseConfig(duration=4e3, depolarise_prob=0.2)
    gate_cfg = GateConfig(
        name="INSTR_X",
        noise_config_cls="GateDepolariseConfig",
        noise_config=gate_noise_cfg,
    )

    cfg = TopologyConfig(
        qubits=[QubitIdConfig(qubit_id=0, qubit_config=qubit_cfg)],
        single_gates=[SingleGateConfig(qubit_id=0, gate_configs=[gate_cfg])],
        multi_gates=[],
    )

    assert cfg.qubits[0].qubit_id == 0
    assert cfg.qubits[0].qubit_config.to_is_communication()
    assert cfg.qubits[0].qubit_config.to_error_model() == T1T2NoiseModel
    assert cfg.qubits[0].qubit_config.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert cfg.single_gates[0].qubit_id == 0
    assert cfg.single_gates[0].gate_configs[0].to_instruction() == INSTR_X
    assert cfg.single_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.single_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }

    # check interface
    assert cfg.get_qubit_configs()[0].to_is_communication()
    assert cfg.get_qubit_configs()[0].to_error_model() == T1T2NoiseModel
    assert cfg.get_qubit_configs()[0].to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert cfg.get_single_gate_configs()[0][0].to_instruction() == INSTR_X
    assert cfg.get_single_gate_configs()[0][0].to_duration() == 4e3
    assert cfg.get_single_gate_configs()[0][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[0][0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_topology_config_perfect_uniform():
    cfg = TopologyConfig.perfect_config_uniform(
        num_qubits=1,
        single_instructions=["INSTR_X"],
        single_duration=4e3,
        two_instructions=[],
        two_duration=0,
    )

    assert cfg.qubits[0].qubit_id == 0
    assert cfg.qubits[0].qubit_config.to_is_communication()
    assert cfg.qubits[0].qubit_config.to_error_model() == T1T2NoiseModel
    assert cfg.qubits[0].qubit_config.to_error_model_kwargs() == {"T1": 0, "T2": 0}
    assert cfg.single_gates[0].qubit_id == 0
    assert cfg.single_gates[0].gate_configs[0].to_instruction() == INSTR_X
    assert cfg.single_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.single_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }

    # check interface
    assert cfg.get_qubit_configs()[0].to_is_communication()
    assert cfg.get_qubit_configs()[0].to_error_model() == T1T2NoiseModel
    assert cfg.get_qubit_configs()[0].to_error_model_kwargs() == {"T1": 0, "T2": 0}
    assert cfg.get_single_gate_configs()[0][0].to_instruction() == INSTR_X
    assert cfg.get_single_gate_configs()[0][0].to_duration() == 4e3
    assert cfg.get_single_gate_configs()[0][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[0][0].to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }


def test_topology_config_file():
    cfg = TopologyConfig.from_file(relative_path("configs/topology_cfg_1.yaml"))

    assert cfg.qubits[0].qubit_id == 0
    assert cfg.qubits[0].qubit_config.to_is_communication()
    assert cfg.qubits[0].qubit_config.to_error_model() == T1T2NoiseModel
    assert cfg.qubits[0].qubit_config.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert cfg.single_gates[0].qubit_id == 0
    assert cfg.single_gates[0].gate_configs[0].to_instruction() == INSTR_X
    assert cfg.single_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.single_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }

    # check interface
    assert cfg.get_qubit_configs()[0].to_is_communication()
    assert cfg.get_qubit_configs()[0].to_error_model() == T1T2NoiseModel
    assert cfg.get_qubit_configs()[0].to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert cfg.get_single_gate_configs()[0][0].to_instruction() == INSTR_X
    assert cfg.get_single_gate_configs()[0][0].to_duration() == 4e3
    assert cfg.get_single_gate_configs()[0][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[0][0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_topology_config_file_2():
    cfg = TopologyConfig.from_file(relative_path("configs/topology_cfg_2.yaml"))

    assert cfg.qubits[0].qubit_id == 0
    assert cfg.qubits[0].qubit_config.to_is_communication()
    assert cfg.qubits[0].qubit_config.to_error_model() == T1T2NoiseModel
    assert cfg.qubits[0].qubit_config.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert cfg.qubits[1].qubit_id == 1
    assert not cfg.qubits[1].qubit_config.to_is_communication()
    assert cfg.qubits[1].qubit_config.to_error_model() == T1T2NoiseModel
    assert cfg.qubits[1].qubit_config.to_error_model_kwargs() == {"T1": 2e6, "T2": 4e6}
    assert cfg.single_gates[0].qubit_id == 0
    assert cfg.single_gates[0].gate_configs[0].to_instruction() == INSTR_X
    assert cfg.single_gates[0].gate_configs[0].to_duration() == 2e3
    assert cfg.single_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }
    assert cfg.single_gates[0].gate_configs[1].to_instruction() == INSTR_Y
    assert cfg.single_gates[0].gate_configs[1].to_duration() == 4e3
    assert cfg.single_gates[0].gate_configs[1].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[1].to_error_model_kwargs() == {
        "depolar_rate": 0.4,
        "time_independent": True,
    }
    assert cfg.single_gates[1].qubit_id == 1
    assert cfg.single_gates[1].gate_configs[0].to_instruction() == INSTR_Z
    assert cfg.single_gates[1].gate_configs[0].to_duration() == 6e3
    assert cfg.single_gates[1].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[1].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.6,
        "time_independent": True,
    }

    # check interface
    assert cfg.get_qubit_configs()[0].to_is_communication()
    assert cfg.get_qubit_configs()[0].to_error_model() == T1T2NoiseModel
    assert cfg.get_qubit_configs()[0].to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6}
    assert not cfg.get_qubit_configs()[1].to_is_communication()
    assert cfg.get_qubit_configs()[1].to_error_model() == T1T2NoiseModel
    assert cfg.get_qubit_configs()[1].to_error_model_kwargs() == {"T1": 2e6, "T2": 4e6}
    assert cfg.get_single_gate_configs()[0][0].to_instruction() == INSTR_X
    assert cfg.get_single_gate_configs()[0][0].to_duration() == 2e3
    assert cfg.get_single_gate_configs()[0][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[0][0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }
    assert cfg.get_single_gate_configs()[0][1].to_instruction() == INSTR_Y
    assert cfg.get_single_gate_configs()[0][1].to_duration() == 4e3
    assert cfg.get_single_gate_configs()[0][1].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[0][1].to_error_model_kwargs() == {
        "depolar_rate": 0.4,
        "time_independent": True,
    }
    assert cfg.get_single_gate_configs()[1][0].to_instruction() == INSTR_Z
    assert cfg.get_single_gate_configs()[1][0].to_duration() == 6e3
    assert cfg.get_single_gate_configs()[1][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_single_gate_configs()[1][0].to_error_model_kwargs() == {
        "depolar_rate": 0.6,
        "time_independent": True,
    }


def test_topology_config_multi_gate():
    qubit_noise_cfg = QubitT1T2Config(T1=1e6, T2=3e6)
    qubit_cfg = QubitConfig(
        is_communication=True,
        noise_config_cls="QubitT1T2Config",
        noise_config=qubit_noise_cfg,
    )
    gate_noise_cfg = GateDepolariseConfig(duration=4e3, depolarise_prob=0.2)
    gate_cfg = GateConfig(
        name="INSTR_CNOT",
        noise_config_cls="GateDepolariseConfig",
        noise_config=gate_noise_cfg,
    )

    cfg = TopologyConfig(
        qubits=[
            QubitIdConfig(qubit_id=0, qubit_config=qubit_cfg),
            QubitIdConfig(qubit_id=1, qubit_config=qubit_cfg),
        ],
        single_gates=[],
        multi_gates=[MultiGateConfig(qubit_ids=[0, 1], gate_configs=[gate_cfg])],
    )

    for i in [0, 1]:
        assert cfg.qubits[i].qubit_id == i
        assert cfg.qubits[i].qubit_config.to_is_communication()
        assert cfg.qubits[i].qubit_config.to_error_model() == T1T2NoiseModel
        assert cfg.qubits[i].qubit_config.to_error_model_kwargs() == {
            "T1": 1e6,
            "T2": 3e6,
        }

    assert cfg.multi_gates[0].qubit_ids == [0, 1]
    assert cfg.multi_gates[0].gate_configs[0].to_instruction() == INSTR_CNOT
    assert cfg.multi_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.multi_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.multi_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }

    # check interface
    for i in [0, 1]:
        assert cfg.get_qubit_configs()[i].to_is_communication()
        assert cfg.get_qubit_configs()[i].to_error_model() == T1T2NoiseModel
        assert cfg.get_qubit_configs()[i].to_error_model_kwargs() == {
            "T1": 1e6,
            "T2": 3e6,
        }
    q01 = MultiQubit([0, 1])
    assert cfg.get_multi_gate_configs()[q01][0].to_instruction() == INSTR_CNOT
    assert cfg.get_multi_gate_configs()[q01][0].to_duration() == 4e3
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_topology_config_multi_gate_perfect_uniform():
    cfg = TopologyConfig.perfect_config_uniform(
        num_qubits=2,
        single_instructions=[],
        single_duration=0,
        two_instructions=["INSTR_CNOT"],
        two_duration=4e3,
    )

    for i in [0, 1]:
        assert cfg.qubits[i].qubit_id == i
        assert cfg.qubits[i].qubit_config.to_is_communication()
        assert cfg.qubits[i].qubit_config.to_error_model() == T1T2NoiseModel
        assert cfg.qubits[i].qubit_config.to_error_model_kwargs() == {
            "T1": 0,
            "T2": 0,
        }

    assert cfg.multi_gates[0].qubit_ids == [0, 1]
    assert cfg.multi_gates[0].gate_configs[0].to_instruction() == INSTR_CNOT
    assert cfg.multi_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.multi_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.multi_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }

    # check interface
    for i in [0, 1]:
        assert cfg.get_qubit_configs()[i].to_is_communication()
        assert cfg.get_qubit_configs()[i].to_error_model() == T1T2NoiseModel
        assert cfg.get_qubit_configs()[i].to_error_model_kwargs() == {
            "T1": 0,
            "T2": 0,
        }
    q01 = MultiQubit([0, 1])
    assert cfg.get_multi_gate_configs()[q01][0].to_instruction() == INSTR_CNOT
    assert cfg.get_multi_gate_configs()[q01][0].to_duration() == 4e3
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }


def test_topology_config_multi_gate_perfect_star():
    cfg = TopologyConfig.perfect_config_star(
        num_qubits=3,
        comm_instructions=["INSTR_X"],
        comm_duration=5e3,
        mem_instructions=["INSTR_Y", "INSTR_Z"],
        mem_duration=10e3,
        two_instructions=["INSTR_CNOT"],
        two_duration=200e3,
    )

    for i, comm in zip([0, 1, 2], [True, False, False]):
        assert cfg.qubits[i].qubit_id == i
        assert cfg.qubits[i].qubit_config.to_is_communication() == comm
        assert cfg.qubits[i].qubit_config.to_error_model() == T1T2NoiseModel
        assert cfg.qubits[i].qubit_config.to_error_model_kwargs() == {
            "T1": 0,
            "T2": 0,
        }

    assert cfg.single_gates[0].qubit_id == 0
    assert len(cfg.single_gates[0].gate_configs) == 1
    assert cfg.single_gates[0].gate_configs[0].to_instruction() == INSTR_X
    assert cfg.single_gates[0].gate_configs[0].to_duration() == 5e3
    assert cfg.single_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.single_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0,
        "time_independent": True,
    }

    for i in [1, 2]:
        assert cfg.single_gates[i].qubit_id == i
        assert len(cfg.single_gates[i].gate_configs) == 2
        assert cfg.single_gates[i].gate_configs[0].to_instruction() == INSTR_Y
        assert cfg.single_gates[i].gate_configs[1].to_instruction() == INSTR_Z
        for j in [0, 1]:
            assert cfg.single_gates[i].gate_configs[j].to_duration() == 10e3
            assert (
                cfg.single_gates[i].gate_configs[j].to_error_model()
                == DepolarNoiseModel
            )
            assert cfg.single_gates[i].gate_configs[j].to_error_model_kwargs() == {
                "depolar_rate": 0,
                "time_independent": True,
            }

    assert len(cfg.multi_gates) == 2
    for i in [1, 2]:
        assert cfg.multi_gates[i - 1].qubit_ids == [0, i]
        assert len(cfg.multi_gates[i - 1].gate_configs) == 1
        assert len(cfg.multi_gates[i - 1].gate_configs) == 1
        assert cfg.multi_gates[i - 1].gate_configs[0].to_instruction() == INSTR_CNOT
        assert cfg.multi_gates[i - 1].gate_configs[0].to_duration() == 200e3
        assert (
            cfg.multi_gates[i - 1].gate_configs[0].to_error_model() == DepolarNoiseModel
        )
        assert cfg.multi_gates[i - 1].gate_configs[0].to_error_model_kwargs() == {
            "depolar_rate": 0,
            "time_independent": True,
        }


def test_topology_config_file_multi_gate():
    cfg = TopologyConfig.from_file(relative_path("configs/topology_cfg_3.yaml"))

    for i in [0, 1]:
        assert cfg.qubits[i].qubit_id == i
        assert cfg.qubits[i].qubit_config.to_is_communication()
        assert cfg.qubits[i].qubit_config.to_error_model() == T1T2NoiseModel
        assert cfg.qubits[i].qubit_config.to_error_model_kwargs() == {
            "T1": 1e6,
            "T2": 3e6,
        }

    assert cfg.multi_gates[0].qubit_ids == [0, 1]
    assert cfg.multi_gates[0].gate_configs[0].to_instruction() == INSTR_CNOT
    assert cfg.multi_gates[0].gate_configs[0].to_duration() == 4e3
    assert cfg.multi_gates[0].gate_configs[0].to_error_model() == DepolarNoiseModel
    assert cfg.multi_gates[0].gate_configs[0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }

    # check interface
    for i in [0, 1]:
        assert cfg.get_qubit_configs()[i].to_is_communication()
        assert cfg.get_qubit_configs()[i].to_error_model() == T1T2NoiseModel
        assert cfg.get_qubit_configs()[i].to_error_model_kwargs() == {
            "T1": 1e6,
            "T2": 3e6,
        }
    q01 = MultiQubit([0, 1])
    assert cfg.get_multi_gate_configs()[q01][0].to_instruction() == INSTR_CNOT
    assert cfg.get_multi_gate_configs()[q01][0].to_duration() == 4e3
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model() == DepolarNoiseModel
    assert cfg.get_multi_gate_configs()[q01][0].to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_topology_config_file_reuse_gate_def():
    cfg = TopologyConfig.from_file(relative_path("configs/topology_cfg_5.yaml"))

    assert cfg.get_single_gate_configs()[0][0].to_instruction() == INSTR_X
    assert cfg.get_single_gate_configs()[0][1].to_instruction() == INSTR_Y
    assert cfg.get_single_gate_configs()[1][0].to_instruction() == INSTR_X


def test_qubit_config_file_registry():
    class QubitT1T2T3Config(QubitT1T2Config):
        T3: int

        @classmethod
        def from_dict(cls, dict: Any) -> QubitT1T2T3Config:
            return QubitT1T2T3Config(**dict)

        def to_error_model_kwargs(self) -> Dict[str, Any]:
            return {"T1": self.T1, "T2": self.T2, "T3": self.T3}

    class CustomQubitConfigRegistry(QubitConfigRegistry):
        @classmethod
        def map(cls) -> Dict[str, QubitNoiseConfigInterface]:
            return {"QubitT1T2T3Config": QubitT1T2T3Config}

    cfg = QubitConfig.from_file(
        relative_path("configs/qubit_cfg_2_custom_cls.yaml"),
        registry=[CustomQubitConfigRegistry],
    )

    assert cfg.is_communication
    assert cfg.to_is_communication()
    assert cfg.to_error_model() == T1T2NoiseModel
    assert cfg.to_error_model_kwargs() == {"T1": 1e6, "T2": 3e6, "T3": 5e6}


def test_gate_config_file_registry():
    class MyLeetNoise(GateNoiseConfigInterface, BaseModel):
        my_noise_param: int

        @classmethod
        def from_dict(cls, dict: Any) -> MyLeetNoise:
            return MyLeetNoise(**dict)

        def to_duration(self) -> int:
            return 42

        def to_error_model(self) -> Type[QuantumErrorModel]:
            return QuantumErrorModel

        def to_error_model_kwargs(self) -> Dict[str, Any]:
            return {"my_noise_param": self.my_noise_param}

    class CustomGateConfigRegistry(GateConfigRegistry):
        @classmethod
        def map(cls) -> Dict[str, GateNoiseConfigInterface]:
            return {"MyLeetNoise": MyLeetNoise}

    cfg = GateConfig.from_file(
        relative_path("configs/gate_cfg_2_custom_cls.yaml"),
        registry=[CustomGateConfigRegistry],
    )

    assert cfg.name == "INSTR_X"
    assert cfg.to_instruction() == INSTR_X
    assert cfg.to_duration() == 42
    assert cfg.to_error_model() == QuantumErrorModel
    assert cfg.to_error_model_kwargs() == {
        "my_noise_param": 1337,
    }


def test_custom_instruction():
    class CustomInstrRegistry(InstrConfigRegistry):
        @classmethod
        def map(cls) -> Dict[str, NetSquidInstruction]:
            return {"MY_CUSTOM_INSTR": INSTR_H}

    cfg = GateConfig.from_file(relative_path("configs/gate_cfg_2_custom_instr.yaml"))

    assert cfg.name == "MY_CUSTOM_INSTR"
    assert cfg.to_instruction(registry=[CustomInstrRegistry]) == INSTR_H
    assert cfg.to_duration() == 4e3
    assert cfg.to_error_model() == DepolarNoiseModel
    assert cfg.to_error_model_kwargs() == {
        "depolar_rate": 0.2,
        "time_independent": True,
    }


def test_latencies_config_file():
    cfg = LatenciesConfig.from_file(relative_path("configs/latencies_cfg_1.yaml"))

    assert cfg.host_qnos_latency == 10e3
    assert cfg.host_instr_time == 500
    assert cfg.qnos_instr_time == 2000
    assert cfg.host_peer_latency == 2e6
    assert cfg.netstack_peer_latency == 1e6

    # check interface
    assert cfg.get_host_qnos_latency() == 10e3
    assert cfg.get_host_instr_time() == 500
    assert cfg.get_qnos_instr_time() == 2000
    assert cfg.get_host_peer_latency() == 2e6
    assert cfg.get_netstack_peer_latency() == 1e6


def test_latencies_config_file_default_values():
    cfg = LatenciesConfig.from_file(relative_path("configs/latencies_cfg_2.yaml"))

    # explicitly given by cfg file
    assert cfg.host_qnos_latency == 10e3

    # not given in the cfg file, so they should default to 0
    assert cfg.host_instr_time == 0
    assert cfg.qnos_instr_time == 0
    assert cfg.host_peer_latency == 0
    assert cfg.netstack_peer_latency == 0

    # check interface
    assert cfg.get_host_qnos_latency() == 10e3
    assert cfg.get_host_instr_time() == 0
    assert cfg.get_qnos_instr_time() == 0
    assert cfg.get_host_peer_latency() == 0
    assert cfg.get_netstack_peer_latency() == 0


def test_procnode_config_file():
    cfg = ProcNodeConfig.from_file(relative_path("configs/procnode_cfg_1.yaml"))

    # the topology used in this file is the same as in configs/topology_cfg_1.yaml
    expected_topology = TopologyConfig.from_file(
        relative_path("configs/topology_cfg_1.yaml")
    )

    assert cfg.node_name == "client_node"
    assert cfg.node_id == 2
    assert cfg.topology == expected_topology
    assert cfg.latencies.host_qnos_latency == 10e3
    assert cfg.latencies.host_instr_time == 500
    assert cfg.latencies.qnos_instr_time == 2000
    assert cfg.latencies.host_peer_latency == 2e6
    assert cfg.latencies.netstack_peer_latency == 1e6


def test_procnode_config_file_default_values():
    cfg = ProcNodeConfig.from_file(relative_path("configs/procnode_cfg_2.yaml"))

    # following 3 items are not given in the cfg file, so they should default to 0
    assert cfg.latencies.host_qnos_latency == 0
    assert cfg.latencies.host_instr_time == 0
    assert cfg.latencies.qnos_instr_time == 0

    # explicitly given by cfg file
    assert cfg.latencies.host_peer_latency == 2e6
    assert cfg.latencies.netstack_peer_latency == 1e6


if __name__ == "__main__":
    test_qubit_t1t2_config()
    test_qubit_t1t2_config_file()
    test_qubit_config()
    test_qubit_config_perfect()
    test_qubit_config_file()
    test_gate_depolarise_config()
    test_gate_depolarise_config_file()
    test_gate_config()
    test_gate_config_perfect()
    test_gate_config_file()
    test_topology_config()
    test_topology_config_perfect_uniform()
    test_topology_config_file()
    test_topology_config_file_2()
    test_topology_config_multi_gate()
    test_topology_config_file_multi_gate()
    test_topology_config_multi_gate_perfect_uniform()
    test_topology_config_multi_gate_perfect_star()
    test_topology_config_file_reuse_gate_def()
    test_qubit_config_file_registry()
    test_gate_config_file_registry()
    test_custom_instruction()
    test_latencies_config_file()
    test_latencies_config_file_default_values()
    test_procnode_config_file()
    test_procnode_config_file_default_values()