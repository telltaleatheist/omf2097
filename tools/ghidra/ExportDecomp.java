// Export per-function decompilation plus a JSON index of calls, strings and hardware access.
// args: <output dir>
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.scalar.Scalar;

public class ExportDecomp extends GhidraScript {

	private String cString(Address a) {
		Memory mem = currentProgram.getMemory();
		StringBuilder s = new StringBuilder();
		try {
			for (int i = 0; i < 200; i++) {
				int b = mem.getByte(a.add(i)) & 0xff;
				if (b == 0) {
					break;
				}
				if (b == '\n' || b == '\r' || b == '\t') {
					s.append(' ');
				}
				else if (b < 0x20 || b > 0x7e) {
					return null;
				}
				else {
					s.append((char) b);
				}
			}
		}
		catch (Exception e) {
			return null;
		}
		return s.length() >= 4 ? s.toString() : null;
	}

	private static String q(String s) {
		return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
	}

	private static String arr(Collection<String> items) {
		StringJoiner j = new StringJoiner(",", "[", "]");
		for (String i : items) {
			j.add(q(i));
		}
		return j.toString();
	}

	@Override
	public void run() throws Exception {
		File out = new File(getScriptArgs()[0]);
		File cdir = new File(out, "c");
		cdir.mkdirs();

		DecompInterface dec = new DecompInterface();
		dec.openProgram(currentProgram);

		Listing listing = currentProgram.getListing();
		AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
		int ok = 0, failed = 0;
		long covered = 0;

		try (PrintWriter idx = new PrintWriter(new File(out, "index.jsonl"), "UTF-8")) {
			for (Function f : listing.getFunctions(true)) {
				monitor.checkCancelled();
				long size = f.getBody().getNumAddresses();
				covered += size;

				Set<String> strings = new LinkedHashSet<>();
				Set<String> hw = new TreeSet<>();
				int insns = 0;
				InstructionIterator it = listing.getInstructions(f.getBody(), true);
				while (it.hasNext()) {
					Instruction ins = it.next();
					insns++;
					String m = ins.getMnemonicString().toUpperCase();
					if (m.startsWith("IN") && !m.equals("INC") || m.startsWith("OUT")) {
						hw.add(ins.toString());
					}
					for (int op = 0; op < ins.getNumOperands(); op++) {
						for (Object o : ins.getOpObjects(op)) {
							if (o instanceof Scalar) {
								long v = ((Scalar) o).getUnsignedValue();
								if (v >= 0x10000 && v < 0x9a000) {
									String s = cString(space.getAddress(v));
									if (s != null) {
										strings.add(s);
									}
								}
							}
						}
					}
				}

				List<String> callers = new ArrayList<>();
				for (Function c : f.getCallingFunctions(monitor)) {
					callers.add(c.getEntryPoint().toString());
				}
				List<String> callees = new ArrayList<>();
				for (Function c : f.getCalledFunctions(monitor)) {
					callees.add(c.getEntryPoint().toString());
				}
				Collections.sort(callers);
				Collections.sort(callees);

				String addr = f.getEntryPoint().toString();
				DecompileResults r = dec.decompileFunction(f, 120, monitor);
				boolean good = r != null && r.decompileCompleted() && r.getDecompiledFunction() != null;
				if (good) {
					ok++;
					try (Writer w = new OutputStreamWriter(
						new FileOutputStream(new File(cdir, addr + ".c")), StandardCharsets.UTF_8)) {
						w.write(r.getDecompiledFunction().getC());
					}
				}
				else {
					failed++;
				}
				idx.println("{\"addr\":" + q(addr) + ",\"name\":" + q(f.getName()) + ",\"size\":" + size +
					",\"insns\":" + insns + ",\"decompiled\":" + good + ",\"callers\":" + arr(callers) +
					",\"callees\":" + arr(callees) + ",\"strings\":" + arr(strings) +
					",\"hw\":" + arr(hw) + "}");
			}
		}
		dec.dispose();

		long text = currentProgram.getMemory().getBlock(".text1").getSize();
		println("EXPORT functions_ok=" + ok + " failed=" + failed + " bytes_in_functions=" + covered +
			" text_bytes=" + text + " compiler=" + currentProgram.getCompilerSpec().getCompilerSpecID());
	}
}
