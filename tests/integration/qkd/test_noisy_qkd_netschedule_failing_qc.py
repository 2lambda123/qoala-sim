from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import netsquid as ns

from rich import print as rprint

from qoala.lang.parse import QoalaParser
from qoala.lang.ehi import EhiNetworkSchedule, EhiNetworkTimebin
from qoala.lang.program import QoalaProgram
from qoala.runtime.config import (
    LatenciesConfig,
    NetworkScheduleConfig,
    NtfConfig,
    ProcNodeConfig,
    ProcNodeNetworkConfig,
    TopologyConfig,
)
from qoala.runtime.program import BatchResult, ProgramInput
from qoala.util.logging import LogManager
from qoala.util.runner import run_two_node_app


def create_procnode_cfg(name: str, id: int, num_qubits: int) -> ProcNodeConfig:
    return ProcNodeConfig(
        node_name=name,
        node_id=id,
        topology=TopologyConfig.perfect_config_uniform_default_params(num_qubits),
        latencies=LatenciesConfig(qnos_instr_time=1000),
        ntf=NtfConfig.from_cls_name("GenericNtf"),
    )


def load_program(path: str) -> QoalaProgram:
    path = os.path.join(os.path.dirname(__file__), path)
    with open(path) as file:
        text = file.read()
    return QoalaParser(text).parse()


@dataclass
class QkdResult:
    alice_result: BatchResult
    bob_result: BatchResult


def run_qkd(
    num_iterations: int,
    alice_file: str,
    bob_file: str,
    num_pairs: Optional[int] = None,
):
    num_qubits = 3
    alice_id = 0
    bob_id = 1

    alice_node_cfg = create_procnode_cfg("alice", alice_id, num_qubits)
    bob_node_cfg = create_procnode_cfg("bob", bob_id, num_qubits)

    # network_cfg = ProcNodeNetworkConfig.from_nodes_perfect_links(
    #     nodes=[alice_node_cfg, bob_node_cfg], link_duration=1000
    # )

    network_cfg = ProcNodeNetworkConfig.from_nodes_depolarising_noise(
        nodes=[alice_node_cfg,bob_node_cfg],
        prob_max_mixed=0.4,
        attempt_success_prob=0.001,
        attempt_duration=1000.0,
        state_delay=0.0
    )

    pattern = [(alice_id, i, bob_id, i) for i in range(num_iterations)]
    pattern.insert(1, (-1,-1,-1,-1))
    network_cfg.netschedule = NetworkScheduleConfig(
        bin_length=800_000, first_bin=0, bin_pattern=pattern, repeat_period=8_800_000
    )

    alice_program = load_program(alice_file)
    bob_program = load_program(bob_file)

    if num_pairs is not None:
        alice_input = ProgramInput({"bob_id": bob_id, "N": num_pairs})
        bob_input = ProgramInput({"alice_id": alice_id, "N": num_pairs})
    else:
        alice_input = ProgramInput({"bob_id": bob_id})
        bob_input = ProgramInput({"alice_id": alice_id})

    netschedule = EhiNetworkSchedule(
        first_bin=network_cfg.netschedule.first_bin, bin_pattern=[EhiNetworkTimebin(nodes=L.nodes, pids = L.pids) for L in network_cfg.netschedule.to_bin_pattern()], bin_length=network_cfg.netschedule.bin_length, repeat_period=network_cfg.netschedule.repeat_period, length_of_QC_blocks={(alice_id, i, bob_id, i):800_000.0 for i in range(num_iterations)}
    )

    rprint(netschedule.bin_pattern)

    app_result = run_two_node_app(
        num_iterations=num_iterations,
        programs={"alice": alice_program, "bob": bob_program},
        program_inputs={"alice": alice_input, "bob": bob_input},
        network_cfg=network_cfg,
        linear=False,
        netschedule=netschedule,
    )

    alice_result = app_result.batch_results["alice"]
    bob_result = app_result.batch_results["bob"]

    return QkdResult(alice_result, bob_result)


def qkd_1pair_md():
    ns.sim_reset()
    # LogManager.enable_task_logger(True)
    LogManager.set_log_level("WARNING")

    num_iterations = 10
    alice_file = "qkd_1pair_MD_alice.iqoala"
    bob_file = "qkd_1pair_MD_bob.iqoala"

    qkd_result = run_qkd(num_iterations, alice_file, bob_file)
    alice_results = qkd_result.alice_result.results
    bob_results = qkd_result.bob_result.results

    assert len(alice_results) == num_iterations
    assert len(bob_results) == num_iterations

    alice_outcomes = [alice_results[i].values for i in range(num_iterations)]
    bob_outcomes = [bob_results[i].values for i in range(num_iterations)]

    print(alice_outcomes)
    print(bob_outcomes)

    # for alice, bob in zip(alice_outcomes, bob_outcomes):
    #     assert alice["m0"] == bob["m0"]


def qkd_1pair_ck():
    ns.sim_reset()

    num_iterations = 10
    alice_file = "qkd_1pair_CK_alice.iqoala"
    bob_file = "qkd_1pair_CK_bob.iqoala"

    qkd_result = run_qkd(num_iterations, alice_file, bob_file)
    alice_results = qkd_result.alice_result.results
    bob_results = qkd_result.bob_result.results

    assert len(alice_results) == num_iterations
    assert len(bob_results) == num_iterations

    alice_outcomes = [alice_results[i].values for i in range(num_iterations)]
    bob_outcomes = [bob_results[i].values for i in range(num_iterations)]

    for alice, bob in zip(alice_outcomes, bob_outcomes):
        assert alice["m0"] == bob["m0"]


def test_qkd_1pair_md():
    qkd_1pair_md()


def test_qkd_1pair_ck():
    qkd_1pair_ck()


if __name__ == "__main__":
    test_qkd_1pair_md()
    # test_qkd_1pair_ck()