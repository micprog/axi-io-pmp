import os
import logging
import pytest

import cocotb
import cocotb_test.simulator

from cocotb.clock import Clock
from cocotb.regression import TestFactory
from cocotb.triggers import RisingEdge
from cocotbext.axi import AxiBus, AxiMaster, AxiRam

import math
from enum import Enum
from bitarray import bitarray
from bitarray.util import int2ba, ba2int


class TB:

    def __init__(self, dut):
        # activate for remote debugging
        if "REMOTE" in os.environ:
            import pydevd_pycharm
            pydevd_pycharm.settrace('localhost', port=8080, stdoutToServer=True, stderrToServer=True)

        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

        # connect simulation axi master
        self.axi_master = AxiMaster(AxiBus.from_prefix(dut, "s_axi"), dut.clk, dut.rst)

        # connect a simulation axi ram (slave)
        self.axi_ram = AxiRam(AxiBus.from_prefix(dut, "m_axi"), dut.clk, dut.rst, size=2 ** 16)

    async def cycle_reset(self):
        self.dut.rst.setimmediatevalue(0)
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        self.dut.rst.value = 1
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        self.dut.rst.value = 0
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)


class PMPMode(Enum):
    OFF = bitarray("00")
    TOR = bitarray("01")
    NA4 = bitarray("10")
    NAPOT = bitarray("11")


class PMPAccess(Enum):
    ACCESS_NONE = bitarray("000")
    ACCESS_READ = bitarray("001")
    ACCESS_WRITE = bitarray("010")
    ACCESS_EXEC = bitarray("100")


def set_pmp_napot(base: int, range: int, access: bitarray, PMP_LEN=54):
    # config
    locked = bitarray("0")
    reserved = bitarray("00")
    mode = PMPMode.NAPOT.value
    conf: bitarray = locked + reserved + mode + access

    # address (NAPOT)
    assert (2 ** math.log2(range) == range)  # check range is 2**X
    address: bitarray = int2ba(int(base + (range / 2 - 1)) >> 2, PMP_LEN)

    # return (conf, addr) tuple
    return conf, address


async def run_test(dut):
    # get testbed instance
    tb = TB(dut)

    # reset dut
    await tb.cycle_reset()

    ##################
    # write data to RAM (in order to have a deterministic value to read)
    ##################
    addr = 0x0000_0000  # allowed range with address below: 0000_0000 - 0000_000f
    length = 1
    test_data = bytearray([x % 2 ** 8 for x in range(length)])
    tb.log.info("TEST: addr %d, length %d, data %s", addr, length, test_data.hex())  # ("_", 1))
    tb.axi_ram.write(addr, test_data)

    ###################
    # setup pmp entry
    ###################
    tb.log.info("Before setting new conf reg: %s", tb.dut.axi_io_pmp0.cfg_reg[0].value)
    tb.log.info("Before setting new add_reg: %s", tb.dut.axi_io_pmp0.cfg_addr_reg[0].value)

    # config
    locked = bitarray("0")
    reserved = bitarray("00")
    mode = PMPMode.NAPOT.value
    access = PMPAccess.ACCESS_READ.value | PMPAccess.ACCESS_WRITE.value | PMPAccess.ACCESS_EXEC.value
    conf: bitarray = locked + reserved + mode + access
    dut.axi_io_pmp0.cfg_reg[0].value = ba2int(conf)
    # address
    PMP_LEN = tb.dut.axi_io_pmp0.PMP_LEN.value
    napot_addr = int2ba(int(addr + (32 / 2 - 1)) >> 2, PMP_LEN)
    tb.log.info("NAPOT addr: %s", napot_addr.to01())

    dut.axi_io_pmp0.cfg_addr_reg[0].value = ba2int(napot_addr)

    await RisingEdge(dut.clk)

    tb.log.info("After setting new conf reg:  %s", tb.dut.axi_io_pmp0.cfg_reg[0].value)
    tb.log.info("After setting new add_reg:  %s", tb.dut.axi_io_pmp0.cfg_addr_reg[0].value)

    ##########################
    # read data through the IO-PMP
    ###########################
    data = await tb.axi_master.read(addr, length)
    tb.log.info("PMP allow: %s", dut.axi_io_pmp0.pmp0.allow_o.value)

    ###################
    # check result
    ###################
    assert data.data == test_data


if cocotb.SIM_NAME:

    data_width = len(cocotb.top.s_axi_wdata)
    byte_lanes = data_width // 8
    max_burst_size = (byte_lanes - 1).bit_length()

    for test in [run_test]:
        factory = TestFactory(test)
        # factory.add_option("size", [None] + list(range(max_burst_size)))
        factory.generate_tests()


@pytest.mark.parametrize("reg_type", [1])  # [None, 0, 1, 2]
@pytest.mark.parametrize("data_width", [64])  # [8, 16, 32, 64, 128]
@pytest.mark.parametrize("addr_width", [64])  # [32, 64]
@pytest.mark.parametrize("simulator", ["questa"])  # ["verilator", "questa"]
def test_axi_io_pmp(request, simulator, addr_width, data_width, reg_type):
    # extract & setup relevant information
    dut = "dut"
    module = os.path.splitext(os.path.basename(__file__))[0]
    toplevel = dut
    tests_dir = os.path.abspath(os.path.dirname(__file__))
    src_dir = os.path.abspath(os.path.join(tests_dir, '..', 'src'))

    # verilog source list
    verilog_sources = [
        # pulp-platform common_cells
        "common_cells/src/cf_math_pkg.sv",
        "common_cells/src/lzc.sv",
        "common_cells/src/spill_register_flushable.sv",
        "common_cells/src/spill_register.sv",

        # pulp-platform axi
        "axi/src/axi_pkg.sv",
        "axi/src/axi_intf.sv",
        "axi/src/axi_cut.sv",

        # axi connector
        "connector/axi_conf.sv",
        "connector/axi_master_connector.sv",
        "connector/axi_slave_connector.sv",

        # pmp sources
        "pmp/include/riscv.sv",
        "pmp/pmp_entry.sv",
        "pmp/pmp.sv",

        # toplevel
        "axi_io_pmp.sv",
        f"{dut}.sv",
    ]
    verilog_sources = list(map(lambda x: os.path.join(src_dir, x), verilog_sources))

    # alternatively add sources recursive
    # verilog_sources = list()
    # for root, dirs, files in os.walk(src_dir):
    #     for file in files:
    #         if os.path.splitext(file)[1] in [".v", ".sv", ".svh"]:
    #             verilog_sources.append(os.path.join(root, file))

    # AXI parameters
    parameters = {
        'DATA_WIDTH': data_width,
        'ADDR_WIDTH': addr_width,
        'STRB_WIDTH': data_width // 8,
        'ID_WIDTH': 8,
        'AWUSER_ENABLE': 0,
        'AWUSER_WIDTH': 1,
        'WUSER_ENABLE': 0,
        'WUSER_WIDTH': 1,
        'BUSER_ENABLE': 0,
        'BUSER_WIDTH': 1,
        'ARUSER_ENABLE': 0,
        'ARUSER_WIDTH': 1,
        'RUSER_ENABLE': 0,
        'RUSER_WIDTH': 1,
        'REG_TYPE': reg_type
    }
    extra_env = {f'PARAM_{k}': str(v) for k, v in parameters.items()}

    sim_build = os.path.join(tests_dir, "sim_build", request.node.name.replace('[', '-').replace(']', ''))

    if simulator == "verilator":
        sim = cocotb_test.simulator.Verilator(
            toplevel=toplevel,
            module=module
        )
        # suppress some verilator specific warnings (i.e. missing timescale information, ..)
        sim.compile_args += ["-Wno-UNOPT", "-Wno-TIMESCALEMOD",  "-Wno-CASEINCOMPLETE", "-Wno-WIDTH",  "-Wno-SELRANGE"]

    elif simulator == "questa":
        sim = cocotb_test.simulator.Questa(
            toplevel=toplevel,
            module=module
        )
        sim.compile_args += [
            f"+define+DATA_WIDTH={parameters['DATA_WIDTH']}",
            f"+define+ADDR_WIDTH={parameters['ADDR_WIDTH']}", 
            f"+define+STRB_WIDTH={parameters['STRB_WIDTH']}", 
            f"+define+ID_WIDTH={parameters['ID_WIDTH']}"
            f"+define+USER_WIDTH={parameters['AWUSER_WIDTH']}"]

    else:
        sim = cocotb_test.simulator.Simulator(
            toplevel=toplevel,
            module=module
        )

    # add wave generation
    parameters["WAVES"] = 1

    sim.python_search = [tests_dir]
    sim.verilog_sources = verilog_sources
    sim.toplevel = toplevel
    sim.module = module
    sim.parameters = parameters
    sim.sim_build = sim_build
    sim.extra_env = extra_env
    sim.includes = list(map(lambda x: os.path.abspath(os.path.join(src_dir, x)), ["pmp/include/",  "axi/include/"]))
    sim.run()
