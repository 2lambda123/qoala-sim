from __future__ import annotations

import logging
from typing import Dict, Generator, List, Optional, Tuple, Type

import netsquid as ns
from netsquid.protocols import Protocol
from numpy import block

from pydynaa import EventExpression
from qoala.lang.ehi import ExposedHardwareInfo, NetworkEhi
from qoala.lang.hostlang import RunRequestOp, RunSubroutineOp
from qoala.runtime.environment import LocalEnvironment
from qoala.runtime.memory import ProgramMemory
from qoala.runtime.program import (
    BatchInfo,
    BatchResult,
    ProgramBatch,
    ProgramInstance,
    ProgramResult,
)
from qoala.runtime.schedule import (
    CombinedProgramTask,
    HostTask,
    NetstackTask,
    ProcessorType,
    ProgramTask,
    ProgramTaskList,
    QnosTask,
    Schedule,
    ScheduleEntry,
    SchedulerInput,
    SchedulerOutput,
    ScheduleSolver,
    ScheduleTime,
    SingleProgramTask,
)
from qoala.runtime.taskcreator import (
    BlockTask,
    QcSlotInfo,
    TaskCreator,
    TaskExecutionMode,
    TaskSchedule,
)
from qoala.sim.driver import CpuDriver, QpuDriver
from qoala.sim.eprsocket import EprSocket
from qoala.sim.events import EVENT_WAIT
from qoala.sim.host.csocket import ClassicalSocket
from qoala.sim.host.host import Host
from qoala.sim.memmgr import MemoryManager
from qoala.sim.netstack import Netstack
from qoala.sim.process import IqoalaProcess
from qoala.sim.qnos import Qnos
from qoala.util.logging import LogManager


class Scheduler(Protocol):
    def __init__(
        self,
        node_name: str,
        host: Host,
        qnos: Qnos,
        netstack: Netstack,
        memmgr: MemoryManager,
        local_env: LocalEnvironment,
        local_ehi: ExposedHardwareInfo,
        network_ehi: NetworkEhi,
    ) -> None:
        super().__init__(name=f"{node_name}_scheduler")

        self._node_name = node_name

        self._logger: logging.Logger = LogManager.get_stack_logger(  # type: ignore
            f"{self.__class__.__name__}({node_name})"
        )

        self._host = host
        self._qnos = qnos
        self._netstack = netstack
        self._memmgr = memmgr
        self._local_env = local_env
        self._local_ehi = local_ehi
        self._network_ehi = network_ehi

        self._prog_instance_counter: int = 0
        self._batch_counter: int = 0
        self._batches: Dict[int, ProgramBatch] = {}  # batch ID -> batch
        self._prog_results: Dict[int, ProgramResult] = {}  # program ID -> result
        self._batch_results: Dict[int, BatchResult] = {}  # batch ID -> result

        self._schedule: Optional[Schedule] = None
        self._block_schedule: Optional[Schedule] = None

        self._cpudriver = CpuDriver(node_name, host.processor, memmgr)
        self._qpudriver = QpuDriver(
            node_name, host.processor, qnos.processor, netstack.processor, memmgr
        )

        self._cpudriver.set_other_driver(self._qpudriver)
        self._qpudriver.set_other_driver(self._cpudriver)

    @property
    def host(self) -> Host:
        return self._host

    @property
    def qnos(self) -> Qnos:
        return self._qnos

    @property
    def netstack(self) -> Netstack:
        return self._netstack

    @property
    def memmgr(self) -> MemoryManager:
        return self._memmgr

    @property
    def block_schedule(self) -> TaskSchedule:
        return self._block_schedule

    def submit_batch(self, batch_info: BatchInfo) -> None:
        prog_instances: List[ProgramInstance] = []

        for i in range(batch_info.num_iterations):
            pid = self._prog_instance_counter
            task_creator = TaskCreator(mode=TaskExecutionMode.ROUTINE_ATOMIC)
            block_tasks = task_creator.from_program(
                batch_info.program, pid, self._local_ehi, self._network_ehi
            )

            instance = ProgramInstance(
                pid=pid,
                program=batch_info.program,
                inputs=batch_info.inputs[i],
                tasks=batch_info.tasks,
                unit_module=batch_info.unit_module,
                block_tasks=block_tasks,
            )
            self._prog_instance_counter += 1
            prog_instances.append(instance)

        batch = ProgramBatch(
            batch_id=self._batch_counter, info=batch_info, instances=prog_instances
        )
        self._batches[batch.batch_id] = batch
        self._batch_counter += 1

    def get_batches(self) -> Dict[int, ProgramBatch]:
        return self._batches

    def get_tasks_to_schedule(self) -> SchedulerInput:
        num_programs = len(self._batches)
        deadlines = [b.info.deadline for b in self._batches.values()]
        num_executions = [b.info.num_iterations for b in self._batches.values()]
        tasks: Dict[int, ProgramTaskList]  # batch ID -> task list
        tasks = {i: b.info.tasks for i, b in self._batches.items()}
        num_instructions = [len(task.tasks) for _, task in tasks.items()]
        instr_durations = [
            [t.duration for t in task.tasks.values()] for _, task in tasks.items()
        ]
        instr_types = [
            [t.instr_type for t in task.tasks.values()] for _, task in tasks.items()
        ]

        global_schedule = self._local_env.get_network_info().get_global_schedule()
        timeslot_len = self._local_env.get_network_info().get_timeslot_len()

        return SchedulerInput(
            global_schedule=global_schedule,
            timeslot_len=timeslot_len,
            num_programs=num_programs,
            deadlines=deadlines,
            num_executions=num_executions,
            num_instructions=num_instructions,
            instr_durations=instr_durations,
            instr_types=instr_types,
        )

    def solver_output_to_schedule(self, output: SchedulerOutput) -> Schedule:
        schedule_entries: List[Tuple[ScheduleTime, ScheduleEntry]] = []
        for entry in output.entries:
            batch_id = entry.app_index
            batch = self._batches[batch_id]
            instance_idx = entry.ex_index
            prog_instance = batch.instances[instance_idx]
            pid = prog_instance.pid
            task_index = entry.instr_index
            time = entry.start_time  # note: may be None!
            schedule_entries.append(
                (ScheduleTime(time), ScheduleEntry(pid, task_index))
            )
        return Schedule(schedule_entries)

    def solve_and_install_schedule(self, solver: Type[ScheduleSolver]) -> None:
        solver_input = self.get_tasks_to_schedule()
        solver_output = solver.solve(solver_input)
        schedule = self.solver_output_to_schedule(solver_output)
        self.install_schedule(schedule)

    def create_process(self, prog_instance: ProgramInstance) -> IqoalaProcess:
        prog_memory = ProgramMemory(prog_instance.pid)
        meta = prog_instance.program.meta

        csockets: Dict[int, ClassicalSocket] = {}
        for i, remote_name in meta.csockets.items():
            # TODO: check for already existing epr sockets
            csockets[i] = self.host.create_csocket(remote_name)

        epr_sockets: Dict[int, EprSocket] = {}
        for i, remote_name in meta.epr_sockets.items():
            network_info = self._local_env.get_network_info()
            remote_id = network_info.get_node_id(remote_name)
            # TODO: check for already existing epr sockets
            # TODO: fidelity
            epr_sockets[i] = EprSocket(i, remote_id, 1.0)

        result = ProgramResult(values={})

        return IqoalaProcess(
            prog_instance=prog_instance,
            prog_memory=prog_memory,
            csockets=csockets,
            epr_sockets=epr_sockets,
            result=result,
        )

    def create_processes_for_batches(self) -> None:
        for batch in self._batches.values():
            for prog_instance in batch.instances:
                process = self.create_process(prog_instance)

                self.memmgr.add_process(process)
                self.initialize_process(process)

    def collect_batch_results(self) -> None:
        for batch_id, batch in self._batches.items():
            results: List[ProgramResult] = []
            for prog_instance in batch.instances:
                process = self.memmgr.get_process(prog_instance.pid)
                results.append(process.result)
            self._batch_results[batch_id] = BatchResult(batch_id, results)

    def get_batch_results(self) -> Dict[int, BatchResult]:
        self.collect_batch_results()
        return self._batch_results

    def execute_host_task(
        self, process: IqoalaProcess, task: HostTask
    ) -> Generator[EventExpression, None, None]:
        yield from self.host.processor.assign_instr_index(process, task.instr_index)

    def execute_qnos_task(
        self, process: IqoalaProcess, task: QnosTask
    ) -> Generator[EventExpression, None, None]:
        host_instr = process.program.instructions[task.instr_index]
        assert isinstance(host_instr, RunSubroutineOp)

        # Let Host setup shared memory.
        lrcall = self.host.processor.prepare_lr_call(process, host_instr)
        # Allocate required qubits.
        self.allocate_qubits_for_routine(process, lrcall.routine_name)
        # Execute the routine on Qnos.
        yield from self.qnos.processor.assign_local_routine(
            process, lrcall.routine_name, lrcall.input_addr, lrcall.result_addr
        )
        # Free qubits that do not need to be kept.
        self.free_qubits_after_routine(process, lrcall.routine_name)
        # Let Host get results from shared memory.
        self.host.processor.post_lr_call(process, host_instr, lrcall)

    def execute_netstack_task(
        self, process: IqoalaProcess, task: NetstackTask
    ) -> Generator[EventExpression, None, None]:
        host_instr = process.program.instructions[task.instr_index]
        assert isinstance(host_instr, RunRequestOp)

        # Let Host setup shared memory.
        rrcall = self.host.processor.prepare_rr_call(process, host_instr)
        assert rrcall.routine_name == task.request_routine_name
        # TODO: refactor this. Bit of a hack to just pass the QnosProcessor around like this!
        yield from self.netstack.processor.assign_request_routine(
            process, rrcall, self.qnos.processor
        )
        self.host.processor.post_rr_call(process, host_instr, rrcall)

    def execute_single_task(
        self, process: IqoalaProcess, task: SingleProgramTask
    ) -> Generator[EventExpression, None, None]:
        if task.processor_type == ProcessorType.HOST:
            yield from self.execute_host_task(process, task.as_host_task())
        elif task.processor_type == ProcessorType.QNOS:
            yield from self.execute_qnos_task(process, task.as_qnos_task())
        elif task.processor_type == ProcessorType.NETSTACK:
            yield from self.execute_netstack_task(process, task.as_netstack_task())
        else:
            raise RuntimeError

    def execute_task(
        self, process: IqoalaProcess, task: ProgramTask
    ) -> Generator[EventExpression, None, None]:
        if isinstance(task, SingleProgramTask):
            yield from self.execute_single_task(process, task)
        elif isinstance(task, CombinedProgramTask):
            for task in task.tasks:
                yield from self.execute_single_task(process, task)
        else:
            raise RuntimeError

    def initialize_process(self, process: IqoalaProcess) -> None:
        # Write program inputs to host memory.
        self.host.processor.initialize(process)

        # TODO: rethink how and when Requests are instantiated
        # inputs = process.prog_instance.inputs
        # for req in process.get_all_requests().values():
        #     # TODO: support for other request parameters being templates?
        #     remote_id = req.request.remote_id
        #     if isinstance(remote_id, Template):
        #         req.request.remote_id = inputs.values[remote_id.name]

    def install_schedule(self, schedule: Schedule) -> None:
        self._schedule = schedule

    def wait(self, delta_time: float) -> Generator[EventExpression, None, None]:
        self._schedule_after(delta_time, EVENT_WAIT)
        event_expr = EventExpression(source=self, event_type=EVENT_WAIT)
        yield event_expr

    def allocate_qubits_for_routine(
        self, process: IqoalaProcess, routine_name: str
    ) -> None:
        routine = process.get_local_routine(routine_name)
        for virt_id in routine.metadata.qubit_use:
            if self.memmgr.phys_id_for(process.pid, virt_id) is None:
                self.memmgr.allocate(process.pid, virt_id)

    def free_qubits_after_routine(
        self, process: IqoalaProcess, routine_name: str
    ) -> None:
        routine = process.get_local_routine(routine_name)
        for virt_id in routine.metadata.qubit_use:
            if virt_id not in routine.metadata.qubit_keep:
                self.memmgr.free(process.pid, virt_id)

    def upload_cpu_schedule(self, schedule: TaskSchedule) -> None:
        self._cpudriver.upload_schedule(schedule)

    def upload_qpu_schedule(self, schedule: TaskSchedule) -> None:
        self._qpudriver.upload_schedule(schedule)

    def upload_schedule(self, schedule: TaskSchedule) -> None:
        self._block_schedule = schedule
        self._cpudriver.upload_schedule(schedule.cpu_schedule)
        self._qpudriver.upload_schedule(schedule.qpu_schedule)

    def start(self) -> None:
        super().start()
        self._cpudriver.start()
        self._qpudriver.start()

    def stop(self) -> None:
        self._qpudriver.stop()
        self._cpudriver.stop()
        super().stop()

    def run(self) -> Generator[EventExpression, None, None]:
        if self._schedule is None:
            return

        for schedule_time, entry in self._schedule.entries:
            process = self.memmgr.get_process(entry.pid)
            task_list = process.prog_instance.tasks
            task = task_list.tasks[entry.task_index]

            if schedule_time.time is None:  # no time constraint
                # print(f"{self.name} executing task {task}")
                yield from self.execute_task(process, task)
            else:
                ns_time = ns.sim_time()
                delta = schedule_time.time - ns.sim_time()
                self._logger.debug(
                    f"{self.name} next scheduled time = {schedule_time.time}, delta = {delta}"
                )
                yield from self.wait(delta)
                ns_time = ns.sim_time()
                self._logger.debug(
                    f"{self.name} ns_time: {ns_time}, executing task {task}"
                )
                yield from self.execute_task(process, task)
                ns_time = ns.sim_time()
                self._logger.debug(
                    f"{self.name} ns_time: {ns_time}, finished task {task}"
                )

        self._logger.debug(f"{self.name} finished with schedule\n\n")
        self.collect_batch_results()

    def submit_program_instance(self, prog_instance: ProgramInstance) -> None:
        process = self.create_process(prog_instance)
        self.memmgr.add_process(process)
        self.initialize_process(process)

    def initialize_block_schedule(self, qc_slot_info: QcSlotInfo) -> None:
        all_tasks: List[BlockTask] = []

        for batch in self._batches.values():
            for inst in batch.instances:
                all_tasks.extend(inst.block_tasks)

        schedule = TaskSchedule.consecutive(all_tasks, qc_slot_info)
        self.upload_schedule(schedule)
