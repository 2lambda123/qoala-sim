import itertools
from typing import Dict, List, Tuple

from netsquid.components.models.qerrormodels import QuantumErrorModel
from netsquid.components.qprocessor import PhysicalInstruction, QuantumProcessor

from qoala.lang.ehi import EhiLinkInfo, EhiNetworkInfo, EhiNetworkSchedule

# Ignore type since whole 'config' module is ignored by mypy
from qoala.runtime.config import ProcNodeConfig, ProcNodeNetworkConfig  # type: ignore
from qoala.runtime.lhi import (
    INSTR_MEASURE_INSTANT,
    LhiLatencies,
    LhiLinkInfo,
    LhiNetworkInfo,
    LhiProcNodeInfo,
    LhiTopology,
    LhiTopologyBuilder,
)
from qoala.runtime.lhi_to_ehi import LhiConverter
from qoala.runtime.ntf import NtfInterface
from qoala.runtime.task import TaskExecutionMode
from qoala.sim.entdist.entdist import EntDist
from qoala.sim.entdist.entdistcomp import EntDistComponent
from qoala.sim.network import ProcNodeNetwork
from qoala.sim.procnode import ProcNode


def build_qprocessor_from_topology(
    name: str, topology: LhiTopology
) -> QuantumProcessor:
    num_qubits = len(topology.qubit_infos)

    mem_noise_models: List[QuantumErrorModel] = []
    for i in range(num_qubits):
        info = topology.qubit_infos[i]
        noise_model = info.error_model(**info.error_model_kwargs)
        mem_noise_models.append(noise_model)

    phys_instructions: List[PhysicalInstruction] = []
    # single-qubit gates
    for qubit_id, gate_infos in topology.single_gate_infos.items():
        for gate_info in gate_infos:
            # TODO: refactor this hack
            if gate_info.instruction == INSTR_MEASURE_INSTANT:
                duration = 0.0
            else:
                duration = gate_info.duration

            phys_instr = PhysicalInstruction(
                instruction=gate_info.instruction,
                duration=duration,
                topology=[qubit_id],
                quantum_noise_model=gate_info.error_model(
                    **gate_info.error_model_kwargs
                ),
            )
            phys_instructions.append(phys_instr)

    # multi-qubit gates
    for multi_qubit, gate_infos in topology.multi_gate_infos.items():
        qubit_ids = tuple(multi_qubit.qubit_ids)
        for gate_info in gate_infos:
            phys_instr = PhysicalInstruction(
                instruction=gate_info.instruction,
                duration=gate_info.duration,
                topology=[qubit_ids],
                quantum_noise_model=gate_info.error_model(
                    **gate_info.error_model_kwargs
                ),
            )
            phys_instructions.append(phys_instr)

    return QuantumProcessor(
        name=name,
        num_positions=num_qubits,
        mem_noise_models=mem_noise_models,
        phys_instructions=phys_instructions,
    )


def build_procnode_from_config(
    cfg: ProcNodeConfig, network_ehi: EhiNetworkInfo
) -> ProcNode:
    topology = LhiTopologyBuilder.from_config(cfg.topology)

    ntf_interface_cls = cfg.ntf.to_ntf_interface()
    ntf_interface = ntf_interface_cls()

    qprocessor = build_qprocessor_from_topology(name=cfg.node_name, topology=topology)
    latencies = LhiLatencies.from_config(cfg.latencies)
    if cfg.tem is None:
        tem = TaskExecutionMode.BLOCK
    else:
        tem = TaskExecutionMode[cfg.tem.upper()]
    procnode = ProcNode(
        cfg.node_name,
        qprocessor=qprocessor,
        qdevice_topology=topology,
        latencies=latencies,
        ntf_interface=ntf_interface,
        node_id=cfg.node_id,
        network_ehi=network_ehi,
        tem=tem,
    )

    # TODO: refactor this hack
    procnode.qnos.processor._latencies.qnos_instr_time = cfg.latencies.qnos_instr_time
    procnode.host.processor._latencies.host_instr_time = cfg.latencies.host_instr_time
    procnode.host.processor._latencies.host_peer_latency = (
        cfg.latencies.host_peer_latency
    )
    return procnode


def build_network_from_config(config: ProcNodeNetworkConfig) -> ProcNodeNetwork:
    procnodes: Dict[str, ProcNode] = {}

    ehi_links: Dict[Tuple[int, int], EhiLinkInfo] = {}
    for link_between_nodes in config.links:
        lhi_link = LhiLinkInfo.from_config(link_between_nodes.link_config)
        ehi_link = LhiConverter.link_info_to_ehi(lhi_link)
        ids = (link_between_nodes.node_id1, link_between_nodes.node_id2)
        ehi_links[ids] = ehi_link
    nodes = {cfg.node_id: cfg.node_name for cfg in config.nodes}
    if config.netschedule is not None:
        netschedule = EhiNetworkSchedule.from_config(config.netschedule)
        network_ehi = EhiNetworkInfo(nodes, ehi_links, netschedule)
    else:
        network_ehi = EhiNetworkInfo(nodes, ehi_links)

    for cfg in config.nodes:
        procnodes[cfg.node_name] = build_procnode_from_config(cfg, network_ehi)

    ns_nodes = [procnode.node for procnode in procnodes.values()]
    entdistcomp = EntDistComponent(network_ehi)
    entdist = EntDist(nodes=ns_nodes, ehi_network=network_ehi, comp=entdistcomp)

    for link_between_nodes in config.links:
        link = LhiLinkInfo.from_config(link_between_nodes.link_config)
        n1 = link_between_nodes.node_id1
        n2 = link_between_nodes.node_id2
        entdist.add_sampler(n1, n2, link)

    for (_, s1), (_, s2) in itertools.combinations(procnodes.items(), 2):
        s1.connect_to(s2)

    for name, procnode in procnodes.items():
        procnode.node.entdist_out_port.connect(entdistcomp.node_in_port(name))
        procnode.node.entdist_in_port.connect(entdistcomp.node_out_port(name))

    return ProcNodeNetwork(procnodes, entdist)


def build_procnode_from_lhi(
    id: int,
    name: str,
    topology: LhiTopology,
    latencies: LhiLatencies,
    network_lhi: LhiNetworkInfo,
    ntf: NtfInterface,
) -> ProcNode:
    qprocessor = build_qprocessor_from_topology(f"{name}_processor", topology)
    network_ehi = LhiConverter.network_to_ehi(network_lhi)
    return ProcNode(
        name=name,
        node_id=id,
        qprocessor=qprocessor,
        qdevice_topology=topology,
        latencies=latencies,
        ntf_interface=ntf,
        network_ehi=network_ehi,
    )


def build_network_from_lhi(
    procnode_infos: List[LhiProcNodeInfo],
    ntfs: List[NtfInterface],
    network_lhi: LhiNetworkInfo,
) -> ProcNodeNetwork:
    procnodes: Dict[str, ProcNode] = {}

    # TODO: refactor two separate lists (infos and ntfs)
    for info, ntf in zip(procnode_infos, ntfs):
        procnode = build_procnode_from_lhi(
            info.id, info.name, info.topology, info.latencies, network_lhi, ntf
        )
        procnodes[info.name] = procnode

    ns_nodes = [procnode.node for procnode in procnodes.values()]
    network_ehi = LhiConverter.network_to_ehi(network_lhi)
    entdistcomp = EntDistComponent(network_ehi)
    entdist = EntDist(nodes=ns_nodes, ehi_network=network_ehi, comp=entdistcomp)

    for ([n1, n2], link_info) in network_lhi.links.items():
        entdist.add_sampler(n1, n2, link_info)

    for (_, s1), (_, s2) in itertools.combinations(procnodes.items(), 2):
        s1.connect_to(s2)

    for name, procnode in procnodes.items():
        procnode.node.entdist_out_port.connect(entdistcomp.node_in_port(name))
        procnode.node.entdist_in_port.connect(entdistcomp.node_out_port(name))

    return ProcNodeNetwork(procnodes, entdist)
