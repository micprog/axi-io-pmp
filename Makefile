# Copyright 2022 ETH Zurich and University of Bologna.
# Copyright and related rights are licensed under the Solderpad Hardware
# License, Version 0.51 (the "License"); you may not use this file except in
# compliance with the License.  You may obtain a copy of the License at
# http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
# or agreed to in writing, software, hardware and materials distributed under
# this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# Author:      Andreas Kuster, <kustera@ethz.ch>
# Description: General targets from setup to simulation and cleanup

SHELL := /bin/bash

.PHONY: clean

all: bender_install bender_dl bender_gen_src sim wave questa_coverage_report

sim:
	pytest tests/ 

sim_mt:
	pytest tests/ -n $(shell nproc)

wave:
	gtkwave sim_build/axi_io_pmp.vcd

questa_coverage_report:
	vcover report -details -html sim_build/axi_io_pmp.ucdb

bender: bender_install bender_dl bender_gen_src

bender_dl:
	./bender

bender_install:
	curl --proto '=https' https://pulp-platform.github.io/bender/init -sSf | /bin/sh

bender_gen_src:
	./bender script flist --relative-path --exclude axi --exclude common_cells --exclude register_interface > src.list

clean:
	rm -rf bender Bender.lock
	rm -rf sim_build .pytest_cache transcript tb/sim_build
	rm -rf covhtmlreport
	rm -rf cmdfile
	rm -rf extras/iopmp.v extras/sv2v-Linux.zip
