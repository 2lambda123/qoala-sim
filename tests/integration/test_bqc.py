from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

import netsquid as ns
from netsquid.nodes import Node
from netsquid.qubits import ketstates, qubitapi
from netsquid_magic.link_layer import (
    MagicLinkLayerProtocolWithSignaling,
    SingleClickTranslationUnit,
)
from netsquid_magic.magic_distributor import PerfectStateMagicDistributor
from netsquid_magic.state_delivery_sampler import PerfectStateSamplerFactory

from qoala.lang.parse import IqoalaParser
from qoala.lang.program import IqoalaProgram
from qoala.runtime.config import (
    LatenciesConfig,
    LinkConfig,
    ProcNodeConfig,
    ProcNodeNetworkConfig,
    TopologyConfig,
)
from qoala.runtime.environment import GlobalEnvironment, GlobalNodeInfo
from qoala.runtime.program import BatchInfo, BatchResult, ProgramInput
from qoala.runtime.schedule import (
    ProgramTaskList,
    SchedulerInput,
    SchedulerOutput,
    SchedulerOutputEntry,
    ScheduleSolver,
    TaskBuilder,
)
from qoala.sim.build import build_network
from qoala.sim.egp import EgpProtocol
from qoala.sim.entdist.entdist import EntDist
from qoala.sim.entdist.entdistcomp import EntDistComponent


def create_global_env(
    num_qubits: int, names: List[str] = ["alice", "bob", "charlie"]
) -> GlobalEnvironment:
    env = GlobalEnvironment()
    for i, name in enumerate(names):
        env.add_node(i, GlobalNodeInfo(name, i))
    env.set_global_schedule([0, 1, 2])
    env.set_timeslot_len(1e6)
    return env


def create_egp_protocols(node1: Node, node2: Node) -> Tuple[EgpProtocol, EgpProtocol]:
    link_dist = PerfectStateMagicDistributor(nodes=[node1, node2], state_delay=0)
    link_prot = MagicLinkLayerProtocolWithSignaling(
        nodes=[node1, node2],
        magic_distributor=link_dist,
        translation_unit=SingleClickTranslationUnit(),
    )
    return EgpProtocol(node1, link_prot), EgpProtocol(node2, link_prot)


def create_server_tasks(
    server_program: IqoalaProgram, cfg: ProcNodeConfig
) -> ProgramTaskList:
    tasks = []

    cl_dur = 1e3
    cc_dur = 10e6
    # ql_dur = 1e4
    qc_dur = 1e6

    topology_cfg: TopologyConfig = cfg.topology

    single_qubit_gate_time = topology_cfg.get_single_gate_configs()[0][0].to_duration()
    two_qubit_gate_time = list(topology_cfg.get_multi_gate_configs().values())[0][
        0
    ].to_duration()

    set_dur = cfg.latencies.qnos_instr_time
    rot_dur = single_qubit_gate_time
    h_dur = single_qubit_gate_time
    meas_dur = single_qubit_gate_time
    free_dur = cfg.latencies.qnos_instr_time
    cphase_dur = two_qubit_gate_time

    # csocket = assign_cval() : 0
    tasks.append(TaskBuilder.CL(cl_dur, 0))

    # OLD:
    # run_subroutine(vec<client_id>) : create_epr_0
    # tasks.append(TaskBuilder.CL(cl_dur, 1))
    # tasks.append(TaskBuilder.QC(qc_dur, "create_epr_0"))

    # NEW:
    # run_subroutine(vec<client_id>) : create_epr_0
    tasks.append(TaskBuilder.QC(qc_dur, "req0"))

    # OLD:
    # run_subroutine(vec<client_id>) : create_epr_1
    # tasks.append(TaskBuilder.CL(cl_dur, 2))
    # tasks.append(TaskBuilder.QC(qc_dur, "create_epr_1"))

    # NEW:
    # run_subroutine(vec<client_id>) : create_epr_1
    tasks.append(TaskBuilder.QC(qc_dur, "req1"))

    # run_subroutine(vec<client_id>) : local_cphase
    tasks.append(TaskBuilder.CL(cl_dur, 3))
    tasks.append(TaskBuilder.QL(set_dur, "local_cphase", 0))
    tasks.append(TaskBuilder.QL(set_dur, "local_cphase", 1))
    tasks.append(TaskBuilder.QL(cphase_dur, "local_cphase", 2))
    # delta1 = recv_cmsg(client_id)
    tasks.append(TaskBuilder.CC(cc_dur, 4))
    # vec<m1> = run_subroutine(vec<delta1>) : meas_qubit_1
    tasks.append(TaskBuilder.CL(cl_dur, 5))
    tasks.append(TaskBuilder.QL(set_dur, "meas_qubit_1", 0))
    tasks.append(TaskBuilder.QL(rot_dur, "meas_qubit_1", 1))
    tasks.append(TaskBuilder.QL(h_dur, "meas_qubit_1", 2))
    tasks.append(TaskBuilder.QL(meas_dur, "meas_qubit_1", 3))
    tasks.append(TaskBuilder.QL(free_dur, "meas_qubit_1", 4))
    # send_cmsg(csocket, m1)
    tasks.append(TaskBuilder.CC(cc_dur, 6))
    # delta2 = recv_cmsg(csocket)
    tasks.append(TaskBuilder.CC(cc_dur, 7))
    # vec<m2> = run_subroutine(vec<delta2>) : meas_qubit_0
    tasks.append(TaskBuilder.CL(cl_dur, 8))
    tasks.append(TaskBuilder.QL(set_dur, "meas_qubit_0", 0))
    tasks.append(TaskBuilder.QL(rot_dur, "meas_qubit_0", 1))
    tasks.append(TaskBuilder.QL(h_dur, "meas_qubit_0", 2))
    tasks.append(TaskBuilder.QL(meas_dur, "meas_qubit_0", 3))
    tasks.append(TaskBuilder.QL(free_dur, "meas_qubit_0", 4))
    # return_result(m1)
    tasks.append(TaskBuilder.CL(cl_dur, 9))
    # return_result(m2)
    tasks.append(TaskBuilder.CL(cl_dur, 10))

    return ProgramTaskList(server_program, {i: task for i, task in enumerate(tasks)})


def create_client_tasks(
    client_program: IqoalaProgram, cfg: ProcNodeConfig
) -> ProgramTaskList:
    tasks = []

    cl_dur = 1e3
    cc_dur = 10e6
    # ql_dur = 1e3
    qc_dur = 1e6

    topology_cfg: TopologyConfig = cfg.topology

    single_qubit_gate_time = topology_cfg.get_single_gate_configs()[0][0].to_duration()

    set_dur = cfg.latencies.qnos_instr_time
    rot_dur = single_qubit_gate_time
    h_dur = single_qubit_gate_time
    meas_dur = single_qubit_gate_time
    free_dur = cfg.latencies.qnos_instr_time

    tasks.append(TaskBuilder.CL(cl_dur, 0))

    # OLD
    # tasks.append(TaskBuilder.CL(cl_dur, 1))
    # tasks.append(TaskBuilder.QC(qc_dur, "create_epr_0"))

    # NEW
    tasks.append(TaskBuilder.QC(qc_dur, "req0"))

    tasks.append(TaskBuilder.CL(cl_dur, 2))
    tasks.append(TaskBuilder.QL(set_dur, "post_epr_0", 0))
    tasks.append(TaskBuilder.QL(rot_dur, "post_epr_0", 1))
    tasks.append(TaskBuilder.QL(h_dur, "post_epr_0", 2))
    tasks.append(TaskBuilder.QL(meas_dur, "post_epr_0", 3))
    tasks.append(TaskBuilder.QL(free_dur, "post_epr_0", 4))

    # OLD
    # tasks.append(TaskBuilder.CL(cl_dur, 3))
    # tasks.append(TaskBuilder.QC(qc_dur, "create_epr_1"))

    # NEW
    tasks.append(TaskBuilder.QC(qc_dur, "req1"))

    tasks.append(TaskBuilder.CL(cl_dur, 4))
    tasks.append(TaskBuilder.QL(set_dur, "post_epr_1", 0))
    tasks.append(TaskBuilder.QL(rot_dur, "post_epr_1", 1))
    tasks.append(TaskBuilder.QL(h_dur, "post_epr_1", 2))
    tasks.append(TaskBuilder.QL(meas_dur, "post_epr_1", 3))
    tasks.append(TaskBuilder.QL(free_dur, "post_epr_1", 4))

    tasks.append(TaskBuilder.CL(cl_dur, 5))
    tasks.append(TaskBuilder.CL(cl_dur, 6))
    tasks.append(TaskBuilder.CL(cl_dur, 7))
    tasks.append(TaskBuilder.CL(cl_dur, 8))
    tasks.append(TaskBuilder.CC(cc_dur, 9))
    tasks.append(TaskBuilder.CC(cc_dur, 10))
    tasks.append(TaskBuilder.CL(cl_dur, 11))
    tasks.append(TaskBuilder.CL(cl_dur, 12))
    tasks.append(TaskBuilder.CL(cl_dur, 13))
    tasks.append(TaskBuilder.CL(cl_dur, 14))
    tasks.append(TaskBuilder.CL(cl_dur, 15))
    tasks.append(TaskBuilder.CC(cc_dur, 16))
    tasks.append(TaskBuilder.CL(cl_dur, 17))
    tasks.append(TaskBuilder.CL(cl_dur, 18))

    return ProgramTaskList(client_program, {i: task for i, task in enumerate(tasks)})


class NaiveSolver(ScheduleSolver):
    @classmethod
    def solve(cls, input: SchedulerInput) -> SchedulerOutput:
        output_entries: List[SchedulerOutputEntry] = []

        assert len(input.num_executions) == input.num_programs
        assert len(input.num_instructions) == input.num_programs
        assert len(input.instr_durations) == input.num_programs

        current_time = 0

        for i in range(input.num_programs):
            num_executions = input.num_executions[i]
            num_instructions = input.num_instructions[i]
            instr_durations = input.instr_durations[i]
            for j in range(num_executions):
                for k in range(num_instructions):
                    duration = instr_durations[k]
                    entry = SchedulerOutputEntry(
                        app_index=i,
                        ex_index=j,
                        instr_index=k,
                        start_time=current_time,
                    )
                    current_time += duration
                    output_entries.append(entry)

        return SchedulerOutput(output_entries)


class NoTimeSolver(ScheduleSolver):
    @classmethod
    def solve(cls, input: SchedulerInput) -> SchedulerOutput:
        output_entries: List[SchedulerOutputEntry] = []

        assert len(input.num_executions) == input.num_programs
        assert len(input.num_instructions) == input.num_programs
        assert len(input.instr_durations) == input.num_programs

        current_time = 0

        for i in range(input.num_programs):
            num_executions = input.num_executions[i]
            num_instructions = input.num_instructions[i]
            instr_durations = input.instr_durations[i]
            for j in range(num_executions):
                for k in range(num_instructions):
                    duration = instr_durations[k]
                    entry = SchedulerOutputEntry(
                        app_index=i,
                        ex_index=j,
                        instr_index=k,
                        start_time=None,
                    )
                    current_time += duration
                    output_entries.append(entry)

        return SchedulerOutput(output_entries)


@dataclass
class BqcResult:
    client_results: Dict[int, BatchResult]
    server_results: Dict[int, BatchResult]


def run_bqc(alpha, beta, theta1, theta2, num_iterations: int):
    ns.sim_reset()

    num_qubits = 3
    global_env = create_global_env(num_qubits, names=["client", "server"])
    server_id = global_env.get_node_id("server")
    client_id = global_env.get_node_id("client")

    server_node_cfg = ProcNodeConfig(
        node_name="server",
        node_id=server_id,
        topology=TopologyConfig.perfect_config_uniform_default_params(num_qubits),
        latencies=LatenciesConfig(qnos_instr_time=1000),
    )
    client_node_cfg = ProcNodeConfig(
        node_name="client",
        node_id=client_id,
        topology=TopologyConfig.perfect_config_uniform_default_params(num_qubits),
        latencies=LatenciesConfig(qnos_instr_time=1000),
    )
    link_cfg = LinkConfig.perfect_config("server", "client")

    network_cfg = ProcNodeNetworkConfig(
        nodes=[server_node_cfg, client_node_cfg], links=[link_cfg]
    )
    network = build_network(network_cfg, global_env)
    server_procnode = network.nodes["server"]
    client_procnode = network.nodes["client"]

    path = os.path.join(os.path.dirname(__file__), "test_bqc_server.iqoala")
    with open(path) as file:
        server_text = file.read()
    server_program = IqoalaParser(server_text).parse()
    server_tasks = create_server_tasks(server_program, server_node_cfg)
    server_inputs = [
        ProgramInput({"client_id": client_id}) for _ in range(num_iterations)
    ]
    server_batch_info = BatchInfo(
        program=server_program,
        inputs=server_inputs,
        num_iterations=num_iterations,
        deadline=0,
        tasks=server_tasks,
        num_qubits=3,
    )
    server_procnode.submit_batch(server_batch_info)
    server_procnode.initialize_processes()
    server_procnode.initialize_schedule(NoTimeSolver)

    path = os.path.join(os.path.dirname(__file__), "test_bqc_client.iqoala")
    with open(path) as file:
        client_text = file.read()
    client_program = IqoalaParser(client_text).parse()
    client_tasks = create_client_tasks(client_program, client_node_cfg)
    client_inputs = [
        ProgramInput(
            {
                "server_id": server_id,
                "alpha": alpha,
                "beta": beta,
                "theta1": theta1,
                "theta2": theta2,
            }
        )
        for _ in range(num_iterations)
    ]

    client_batch_info = BatchInfo(
        program=client_program,
        inputs=client_inputs,
        num_iterations=num_iterations,
        deadline=0,
        tasks=client_tasks,
        num_qubits=3,
    )
    client_procnode.submit_batch(client_batch_info)
    client_procnode.initialize_processes()
    client_procnode.initialize_schedule(NoTimeSolver)

    nodes = [client_procnode.node, server_procnode.node]
    gedcomp = EntDistComponent(global_env)
    client_procnode.node.entdist_out_port.connect(gedcomp.node_in_port("client"))
    client_procnode.node.entdist_in_port.connect(gedcomp.node_out_port("client"))
    server_procnode.node.entdist_out_port.connect(gedcomp.node_in_port("server"))
    server_procnode.node.entdist_in_port.connect(gedcomp.node_out_port("server"))
    ged = EntDist(nodes=nodes, global_env=global_env, comp=gedcomp)
    factory = PerfectStateSamplerFactory()
    kwargs = {"cycle_time": 1000}
    ged.add_sampler(
        client_procnode.node.ID, server_procnode.node.ID, factory, kwargs=kwargs
    )

    server_procnode.start()
    client_procnode.start()
    ged.start()
    ns.sim_run()

    client_results = client_procnode.scheduler.get_batch_results()
    server_results = server_procnode.scheduler.get_batch_results()

    return BqcResult(client_results, server_results)


def expected_rsp_qubit(theta: int, p: int, dummy: bool):
    expected = qubitapi.create_qubits(1)[0]

    if dummy:
        if p == 0:
            qubitapi.assign_qstate(expected, ketstates.s0)
        elif p == 1:
            qubitapi.assign_qstate(expected, ketstates.s1)
    else:
        if (theta, p) == (0, 0):
            qubitapi.assign_qstate(expected, ketstates.h0)
        elif (theta, p) == (0, 1):
            qubitapi.assign_qstate(expected, ketstates.h1)
        if (theta, p) == (8, 0):
            qubitapi.assign_qstate(expected, ketstates.y0)
        elif (theta, p) == (8, 1):
            qubitapi.assign_qstate(expected, ketstates.y1)
        if (theta, p) == (16, 0):
            qubitapi.assign_qstate(expected, ketstates.h1)
        elif (theta, p) == (16, 1):
            qubitapi.assign_qstate(expected, ketstates.h0)
        if (theta, p) == (-8, 0):
            qubitapi.assign_qstate(expected, ketstates.y1)
        elif (theta, p) == (-8, 1):
            qubitapi.assign_qstate(expected, ketstates.y0)

    return expected


def expected_rsp_state(theta: int, p: int, dummy: bool):
    expected = qubitapi.create_qubits(1)[0]

    if dummy:
        if p == 0:
            return ketstates.s0
        elif p == 1:
            return ketstates.s1
    else:
        if (theta, p) == (0, 0):
            return ketstates.h0
        elif (theta, p) == (0, 1):
            return ketstates.h1
        if (theta, p) == (8, 0):
            return ketstates.y0
        elif (theta, p) == (8, 1):
            return ketstates.y1
        if (theta, p) == (16, 0):
            return ketstates.h1
        elif (theta, p) == (16, 1):
            return ketstates.h0
        if (theta, p) == (-8, 0):
            return ketstates.y1
        elif (theta, p) == (-8, 1):
            return ketstates.y0

    return expected.qstate


def test_bqc():
    # Effective computation: measure in Z the following state:
    # H Rz(beta) H Rz(alpha) |+>
    # m2 should be this outcome

    # angles are in multiples of pi/16

    # LogManager.set_log_level("DEBUG")
    # LogManager.log_to_file("test_run.log")

    def check(alpha, beta, theta1, theta2, expected):
        ns.sim_reset()
        bqc_result = run_bqc(
            alpha=alpha, beta=beta, theta1=theta1, theta2=theta2, num_iterations=20
        )
        assert len(bqc_result.client_results) > 0
        assert len(bqc_result.server_results) > 0

        server_batch_results = bqc_result.server_results
        for batch_id, batch_results in server_batch_results.items():
            program_results = batch_results.results
            m2s = [result.values["m2"] for result in program_results]
            assert all(m2 == expected for m2 in m2s)

    check(alpha=8, beta=8, theta1=0, theta2=0, expected=0)
    check(alpha=8, beta=24, theta1=0, theta2=0, expected=1)
    check(alpha=8, beta=8, theta1=13, theta2=27, expected=0)
    check(alpha=8, beta=24, theta1=2, theta2=22, expected=1)


if __name__ == "__main__":
    test_bqc()