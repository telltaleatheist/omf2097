// Dump every instruction with register inputs/outputs and flows, one JSON object per line, for convention analysis.
// args: <output file>
import java.io.*;
import java.util.*;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;

public class DumpInsns extends GhidraScript {

	private static String q(String s) {
		return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
	}

	private static String regs(Object[] objs) {
		StringJoiner j = new StringJoiner(",", "[", "]");
		for (Object o : objs) {
			if (o instanceof Register) {
				j.add(q(((Register) o).getName()));
			}
		}
		return j.toString();
	}

	@Override
	public void run() throws Exception {
		Listing listing = currentProgram.getListing();
		try (PrintWriter out = new PrintWriter(new File(getScriptArgs()[0]), "UTF-8")) {
			InstructionIterator it = listing.getInstructions(true);
			while (it.hasNext()) {
				Instruction ins = it.next();
				StringJoiner flows = new StringJoiner(",", "[", "]");
				for (Address a : ins.getFlows()) {
					flows.add(q(a.toString()));
				}
				Function f = listing.getFunctionContaining(ins.getAddress());
				out.println("{\"a\":" + q(ins.getAddress().toString()) + ",\"n\":" + ins.getLength() +
					",\"t\":" + q(ins.toString()) + ",\"in\":" + regs(ins.getInputObjects()) +
					",\"out\":" + regs(ins.getResultObjects()) + ",\"flow\":" + q(ins.getFlowType().toString()) +
					",\"to\":" + flows + ",\"fall\":" + (ins.getFallThrough() != null) +
					",\"f\":" + (f == null ? "null" : q(f.getEntryPoint().toString())) + "}");
			}
		}
		println("DUMP done");
	}
}
