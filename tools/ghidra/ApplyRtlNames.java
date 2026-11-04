// Name Watcom runtime functions from tools/ghidra/rtl_names.tsv, creating entries Ghidra missed.
// Low-confidence names get an rtl_ prefix unless already rtl_; confidence and evidence go in the plate comment.
// args: <rtl_names.tsv>
import java.io.File;
import java.nio.file.Files;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;

public class ApplyRtlNames extends GhidraScript {

	@Override
	public void run() throws Exception {
		int named = 0, created = 0, skipped = 0;
		AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
		for (String line : Files.readAllLines(new File(getScriptArgs()[0]).toPath())) {
			String[] p = line.split("\t", -1);
			if (p[0].equals("addr")) {
				continue;
			}
			Address a = space.getAddress(Long.parseLong(p[0], 16));
			String name = p[1], conf = p[2];
			Function f = currentProgram.getFunctionManager().getFunctionAt(a);
			if (f == null) {
				if (name.contains("region") || currentProgram.getFunctionManager().getFunctionContaining(a) != null) {
					println("RTL_SKIP " + a + " " + name);
					skipped++;
					continue;
				}
				if (currentProgram.getListing().getInstructionAt(a) == null) {
					new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
				}
				f = createFunction(a, null);
				if (f == null) {
					println("RTL_NOCREATE " + a + " " + name);
					skipped++;
					continue;
				}
				created++;
			}
			if (conf.equals("low") && !name.startsWith("rtl_")) {
				name = "rtl_" + name;
			}
			f.setName(name, SourceType.ANALYSIS);
			f.setComment("runtime: " + conf + " confidence. " + p[3] + " | " + p[4]);
			named++;
		}
		println("RTL_NAMES named=" + named + " created=" + created + " skipped=" + skipped);
	}
}
