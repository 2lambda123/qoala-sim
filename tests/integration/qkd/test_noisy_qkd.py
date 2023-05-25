from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

import netsquid as ns
import pytest

from qoala.lang.ehi import UnitModule
from qoala.lang.parse import QoalaParser
from qoala.lang.program import QoalaProgram
from qoala.runtime.config import (
    LatenciesConfig,
    LinkBetweenNodesConfig,
    LinkConfig,
    ProcNodeConfig,
    ProcNodeNetworkConfig,
    TopologyConfig,
)
from qoala.runtime.environment import StaticNetworkInfo
from qoala.runtime.program import BatchInfo, BatchResult, ProgramInput
from qoala.runtime.task import TaskGraphBuilder
from qoala.sim.build import build_network
from qoala.util.math import fidelity_to_prob_max_mixed


def create_network_info(names: List[str]) -> StaticNetworkInfo:
    env = StaticNetworkInfo.with_nodes({i: name for i, name in enumerate(names)})
    return env


def create_procnode_cfg(name: str, id: int, num_qubits: int) -> ProcNodeConfig:
    return ProcNodeConfig(
        node_name=name,
        node_id=id,
        topology=TopologyConfig.perfect_config_uniform_default_params(num_qubits),
        latencies=LatenciesConfig(qnos_instr_time=1000),
    )


def load_program(path: str) -> QoalaProgram:
    path = os.path.join(os.path.dirname(__file__), path)
    with open(path) as file:
        text = file.read()
    return QoalaParser(text).parse()


def create_batch(
    program: QoalaProgram,
    unit_module: UnitModule,
    inputs: List[ProgramInput],
    num_iterations: int,
) -> BatchInfo:
    return BatchInfo(
        program=program,
        unit_module=unit_module,
        inputs=inputs,
        num_iterations=num_iterations,
        deadline=0,
    )


@dataclass
class QkdResult:
    alice_result: BatchResult
    bob_result: BatchResult


def run_qkd(
    num_iterations: int,
    link_fidelity: float,
    alice_file: str,
    bob_file: str,
    num_pairs: Optional[int] = None,
):
    ns.sim_reset()

    num_qubits = 3
    network_info = create_network_info(names=["alice", "bob"])
    alice_id = network_info.get_node_id("alice")
    bob_id = network_info.get_node_id("bob")

    alice_node_cfg = create_procnode_cfg("alice", alice_id, num_qubits)
    bob_node_cfg = create_procnode_cfg("bob", bob_id, num_qubits)

    link_cfg = LinkConfig.depolarise_config(fidelity=link_fidelity, state_delay=1000)
    link_between_cfg = LinkBetweenNodesConfig(
        node_id1=alice_id, node_id2=bob_id, link_config=link_cfg
    )
    network_cfg = ProcNodeNetworkConfig(
        nodes=[alice_node_cfg, bob_node_cfg], links=[link_between_cfg]
    )
    network = build_network(network_cfg, network_info)
    alice_procnode = network.nodes["alice"]
    bob_procnode = network.nodes["bob"]

    alice_program = load_program(alice_file)
    if num_pairs is not None:
        alice_inputs = [
            ProgramInput({"bob_id": bob_id, "num_pairs": num_pairs})
            for _ in range(num_iterations)
        ]
    else:
        alice_inputs = [ProgramInput({"bob_id": bob_id}) for _ in range(num_iterations)]

    alice_unit_module = UnitModule.from_full_ehi(alice_procnode.memmgr.get_ehi())
    alice_batch = create_batch(
        alice_program, alice_unit_module, alice_inputs, num_iterations
    )
    alice_procnode.submit_batch(alice_batch)
    alice_procnode.initialize_processes()
    alice_tasks = alice_procnode.scheduler.get_tasks_to_schedule()
    alice_merged = TaskGraphBuilder.merge_linear(alice_tasks)
    alice_procnode.scheduler.upload_task_graph(alice_merged)

    bob_program = load_program(bob_file)
    if num_pairs is not None:
        bob_inputs = [
            ProgramInput({"alice_id": alice_id, "num_pairs": num_pairs})
            for _ in range(num_iterations)
        ]
    else:
        bob_inputs = [
            ProgramInput({"alice_id": alice_id}) for _ in range(num_iterations)
        ]

    bob_unit_module = UnitModule.from_full_ehi(bob_procnode.memmgr.get_ehi())
    bob_batch = create_batch(bob_program, bob_unit_module, bob_inputs, num_iterations)
    bob_procnode.submit_batch(bob_batch)
    bob_procnode.initialize_processes()
    bob_tasks = bob_procnode.scheduler.get_tasks_to_schedule()
    bob_merged = TaskGraphBuilder.merge_linear(bob_tasks)
    bob_procnode.scheduler.upload_task_graph(bob_merged)

    network.start()
    ns.sim_run()

    # only one batch (ID = 0), so get value at index 0
    alice_result = alice_procnode.scheduler.get_batch_results()[0]
    bob_result = bob_procnode.scheduler.get_batch_results()[0]

    return QkdResult(alice_result, bob_result)


def test_qkd_md_1pair():
    ns.sim_reset()

    num_iterations = 1000

    link_fidelity = 0.7

    alice_file = "qkd_md_1pair_alice.iqoala"
    bob_file = "qkd_md_1pair_bob.iqoala"

    qkd_result = run_qkd(num_iterations, link_fidelity, alice_file, bob_file)
    alice_results = qkd_result.alice_result.results
    bob_results = qkd_result.bob_result.results

    assert len(alice_results) == num_iterations
    assert len(bob_results) == num_iterations

    alice_outcomes = [alice_results[i].values for i in range(num_iterations)]
    bob_outcomes = [bob_results[i].values for i in range(num_iterations)]

    count_equal_outcomes = 0
    for alice, bob in zip(alice_outcomes, bob_outcomes):
        if alice["m0"] == bob["m0"]:
            count_equal_outcomes += 1

    # We used a link fidelity of 0.7 for a depolarising sampler.
    # This results in a produced state of 0.4 * <maximally mixed> + 0.6 * Phi+.
    assert fidelity_to_prob_max_mixed(0.7) == pytest.approx(0.4)
    # Hence we expect the ratio of pairs with equal outcomes to be
    # 0.5 * 0.4                     +    1.0 * 0.6                   = 0.8
    # (mixed state -> 50% success)       (Phi+ -> 100% success)
    assert (count_equal_outcomes / num_iterations) <= 0.85
    assert (count_equal_outcomes / num_iterations) >= 0.75


if __name__ == "__main__":
    test_qkd_md_1pair()
