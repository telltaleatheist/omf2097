// Apply the Watcom register convention measured by tools/verify_convention.py.
// Adds per-arity prototype models as a program specification extension (the Ghidra
// install is not touched), assigns a model to each function, re-derives parameters
// callees-first with the decompiler, and sets call-site overrides on indirect calls.
//
// Watcom saves every register except EAX and those carrying arguments, so what a call
// preserves depends on its argument count; hence one model per arity:
//   __watcall1..4  args EAX,EDX,EBX,ECX then stack, callee pops its stack args
//   __watdbl       as __watcall4, returning a double or long long in EDX:EAX
//   __watstack     stack only, callee pops, keeps ESI,EDI,EBP only
//   __watcdecl     stack only, caller pops, keeps everything but EAX
// args: <models.tsv>
import java.io.File;
import java.nio.file.Files;
import java.util.*;

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.database.SpecExtension;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.listing.Function.FunctionUpdateType;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.*;
import ghidra.program.model.pcode.HighFunctionDBUtil.ReturnCommitOption;
import ghidra.program.model.symbol.SourceType;

public class ApplyWatcom extends GhidraScript {

	private static final String[] ARGS = { "EAX", "EDX", "EBX", "ECX" };
	private static final String[] KEPT = { "ESP", "EBP", "ESI", "EDI" };
	private static final String EAX_ENTRY = "<pentry minsize=\"1\" maxsize=\"4\"><register name=\"EAX\"/></pentry>";
	private static final String JOIN_ENTRY = "<pentry minsize=\"5\" maxsize=\"8\">" +
		"<addr space=\"join\" piece1=\"EDX\" piece2=\"EAX\"/></pentry>";
	private static final String STACK_ENTRY = "<pentry minsize=\"1\" maxsize=\"500\" align=\"4\">" +
		"<addr offset=\"4\" space=\"stack\"/></pentry>";

	private static String regList(String tag, List<String> regs) {
		StringBuilder s = new StringBuilder("<" + tag + ">");
		for (String r : regs) {
			s.append("<register name=\"").append(r).append("\"/>");
		}
		return s.append("</").append(tag).append(">").toString();
	}

	private static String model(String name, String extrapop, int regArgs, List<String> kept, List<String> killed) {
		return model(name, extrapop, regArgs, kept, killed, false);
	}

	private static String model(String name, String extrapop, int regArgs, List<String> kept, List<String> killed,
			boolean join) {
		StringBuilder s = new StringBuilder("<prototype name=\"" + name + "\" extrapop=\"" + extrapop +
			"\" stackshift=\"4\"><input>");
		for (int i = 0; i < regArgs; i++) {
			s.append("<pentry minsize=\"1\" maxsize=\"4\"><register name=\"").append(ARGS[i]).append("\"/></pentry>");
		}
		s.append(STACK_ENTRY).append("</input><output killedbycall=\"true\">")
			.append(EAX_ENTRY).append(join ? JOIN_ENTRY : "").append("</output>").append(regList("unaffected", kept));
		if (!killed.isEmpty()) {
			s.append(regList("killedbycall", killed));
		}
		s.append("<likelytrash><register name=\"EAX\"/></likelytrash></prototype>");
		return s.toString();
	}

	private void installModels() throws Exception {
		SpecExtension ext = new SpecExtension(currentProgram);
		for (int n = 1; n <= 4; n++) {
			List<String> kept = new ArrayList<>(List.of(KEPT));
			List<String> killed = new ArrayList<>();
			for (int i = 1; i < 4; i++) {
				(i < n ? killed : kept).add(ARGS[i]);
			}
			ext.addReplaceCompilerSpecExtension(model("__watcall" + n, "unknown", n, kept, killed), monitor);
		}
		// Returns a 64-bit value in EDX:EAX, seen at call sites as EDX read after the call.
		ext.addReplaceCompilerSpecExtension(
			model("__watdbl", "unknown", 4, List.of(KEPT), List.of("EDX", "EBX", "ECX"), true), monitor);
		ext.addReplaceCompilerSpecExtension(
			model("__watstack", "unknown", 0, List.of(KEPT), List.of("EDX", "EBX", "ECX")), monitor);
		List<String> all = new ArrayList<>(List.of(KEPT));
		all.addAll(List.of("EDX", "EBX", "ECX"));
		ext.addReplaceCompilerSpecExtension(model("__watcdecl", "4", 0, all, List.of()), monitor);
	}

	/** Functions in non-executable blocks are false: nothing decodes there. Report and remove them. */
	private void removeFalseFunctions() throws Exception {
		List<Function> bad = new ArrayList<>();
		for (Function f : currentProgram.getListing().getFunctions(true)) {
			MemoryBlock b = currentProgram.getMemory().getBlock(f.getEntryPoint());
			if (b == null || !b.isExecute()) {
				bad.add(f);
			}
		}
		for (Function f : bad) {
			println("FALSE_FUNCTION " + f.getEntryPoint() + " body=" + f.getBody().getNumAddresses());
			Address a = f.getEntryPoint();
			AddressSetView body = f.getBody();
			currentProgram.getFunctionManager().removeFunction(a);
			currentProgram.getListing().clearCodeUnits(body.getMinAddress(), body.getMaxAddress(), false);
		}
	}

	private Address addr(String s) {
		return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(Long.parseLong(s, 16));
	}

	/** Callees first, so callers decompile against settled signatures. */
	private List<Function> calleesFirst() throws Exception {
		List<Function> order = new ArrayList<>();
		Set<Function> seen = new HashSet<>();
		for (Function root : currentProgram.getListing().getFunctions(true)) {
			Deque<Function> stack = new ArrayDeque<>();
			Deque<Iterator<Function>> iters = new ArrayDeque<>();
			if (!seen.add(root)) {
				continue;
			}
			stack.push(root);
			iters.push(root.getCalledFunctions(monitor).iterator());
			while (!stack.isEmpty()) {
				Iterator<Function> it = iters.peek();
				if (it.hasNext()) {
					Function c = it.next();
					if (seen.add(c)) {
						stack.push(c);
						iters.push(c.getCalledFunctions(monitor).iterator());
					}
				}
				else {
					order.add(stack.pop());
					iters.pop();
				}
			}
		}
		return order;
	}

	@Override
	public void run() throws Exception {
		installModels();
		removeFalseFunctions();

		Map<Address, Integer> indirect = new TreeMap<>();
		Map<Address, Integer> stackCalls = new TreeMap<>();
		Map<Address, Integer> minRegs = new TreeMap<>();
		int assigned = 0;
		for (String line : Files.readAllLines(new File(getScriptArgs()[0]).toPath())) {
			String[] p = line.split("\t");
			Address a = addr(p[1]);
			if (p[0].equals("I")) {
				indirect.put(a, Integer.parseInt(p[3]));
				continue;
			}
			if (p[0].equals("V")) {
				stackCalls.put(a, Integer.parseInt(p[3]));
				continue;
			}
			Function f = currentProgram.getFunctionManager().getFunctionAt(a);
			if (f == null) {
				println("NO_FUNCTION " + a);
				continue;
			}
			String m = p[2].startsWith("a") ? "__watcall" + p[2].substring(1)
				: p[2].equals("dbl") ? "__watdbl" : p[2].equals("stdstack") ? "__watstack" : "__watcdecl";
			f.updateFunction(m, new ReturnParameterImpl(Undefined.getUndefinedDataType(4), currentProgram),
				List.of(), FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.DEFAULT);
			f.setCustomVariableStorage(false);
			f.setStackPurgeSize(Integer.parseInt(p[3]));
			f.setNoReturn(p[4].equals("1"));
			minRegs.put(a, Integer.parseInt(p[5]));
			assigned++;
		}
		applyHelperSignatures();
		println("ASSIGNED " + assigned);

		DecompInterface dec = new DecompInterface();
		DecompileOptions opts = new DecompileOptions();
		dec.setOptions(opts);
		dec.setSimplificationStyle("decompile");
		dec.openProgram(currentProgram);
		List<Function> order = calleesFirst();
		for (int pass = 1; pass <= 2; pass++) {
			int ok = 0, failed = 0;
			for (Function f : order) {
				monitor.checkCancelled();
				if (HELPERS.containsKey(f.getEntryPoint().getOffset())) {
					continue;
				}
				DecompileResults r = dec.decompileFunction(f, 60, monitor);
				HighFunction h = r == null ? null : r.getHighFunction();
				if (h == null) {
					failed++;
					continue;
				}
				try {
					HighFunctionDBUtil.commitParamsToDatabase(h, true, ReturnCommitOption.NO_COMMIT, SourceType.ANALYSIS);
					ok++;
				}
				catch (Exception e) {
					println("COMMIT_FAILED " + f.getEntryPoint() + " " + e.getMessage());
					failed++;
				}
			}
			println("PARAM_PASS " + pass + " ok=" + ok + " failed=" + failed);
		}
		dec.dispose();

		// Registers read only by an INT (close's fd, say) look unused to the decompiler, which
		// has no p-code for the service. Restore the parameters the instruction walk measured.
		int restored = 0;
		for (Map.Entry<Address, Integer> e : minRegs.entrySet()) {
			Function f = currentProgram.getFunctionManager().getFunctionAt(e.getKey());
			if (f == null || HELPERS.containsKey(e.getKey().getOffset()) ||
				f.getParameterCount() >= e.getValue() || f.getCallingConventionName().equals("__watstack") ||
				f.getCallingConventionName().equals("__watcdecl")) {
				continue;
			}
			boolean onStack = false;
			for (Parameter p : f.getParameters()) {
				onStack |= p.isStackVariable();
			}
			if (onStack) {
				continue;
			}
			List<Parameter> ps = new ArrayList<>(List.of(f.getParameters()));
			for (int i = ps.size(); i < e.getValue(); i++) {
				ps.add(new ParameterImpl("param_" + (i + 1), Undefined.getUndefinedDataType(4), currentProgram));
			}
			f.updateFunction(f.getCallingConventionName(), f.getReturn(), ps,
				FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.ANALYSIS);
			restored++;
		}
		println("PARAMS_RESTORED " + restored);

		int overrides = 0;
		for (Map.Entry<Address, Integer> e : indirect.entrySet()) {
			overrides += override(e.getKey(), e.getValue(), "__watcall" + Math.max(1, e.getValue()));
		}
		for (Map.Entry<Address, Integer> e : stackCalls.entrySet()) {
			overrides += override(e.getKey(), e.getValue(), "__watcdecl");
		}
		println("CALLSITE_OVERRIDES " + overrides);
	}

	private int override(Address site, int args, String cc) throws Exception {
		Function f = currentProgram.getFunctionManager().getFunctionContaining(site);
		if (f == null) {
			return 0;
		}
		FunctionDefinitionDataType sig = new FunctionDefinitionDataType("callsite_" + site,
			currentProgram.getDataTypeManager());
		ParameterDefinition[] defs = new ParameterDefinition[args];
		for (int i = 0; i < args; i++) {
			defs[i] = new ParameterDefinitionImpl("a" + (i + 1), Undefined.getUndefinedDataType(4), null);
		}
		sig.setArguments(defs);
		sig.setReturnType(Undefined.getUndefinedDataType(4));
		sig.setCallingConvention(cc);
		HighFunctionDBUtil.writeOverride(f, site, sig);
		return 1;
	}

	// Watcom -fpc helpers: float in a GPR, double in EDX:EAX, second double in ECX:EBX.
	private static final Map<Long, String> HELPERS = new HashMap<>();
	static {
		HELPERS.put(0x6ae22L, "double __FDA(double a /*EDX:EAX*/, double b /*ECX:EBX*/)");
		HELPERS.put(0x6ae1cL, "double __FDS(double a, double b)");
		HELPERS.put(0x6afd9L, "double __FDM(double a, double b)");
		HELPERS.put(0x6addcL, "double __I4FD(int a /*EAX*/)");
		HELPERS.put(0x6ade9L, "double __U4FD(uint a /*EAX*/)");
		HELPERS.put(0x6b42cL, "float __FDFS(double a) -> EAX");
		HELPERS.put(0x6b478L, "double __FSFD(float a /*EAX*/)");
		HELPERS.put(0x6b4d6L, "int __FDI4(double a) -> EAX");
		HELPERS.put(0x6b4daL, "uint __FDU4(double a) -> EAX");
		HELPERS.put(0x6b605L, "float __I4FS(int a) -> EAX");
		HELPERS.put(0x6b5daL, "float __U4FS(uint a) -> EAX");
		HELPERS.put(0x6b878L, "int __FSI4(float a) -> EAX");
		HELPERS.put(0x6b882L, "uint __FSU4(float a) -> EAX");
		HELPERS.put(0x6c3c2L, "double __FDD(double a, double b)");
		HELPERS.put(0x6b9c2L, "int __FDC(double a, double b) -> EAX and flags");
		HELPERS.put(0x6cd16L, "int __FSC(float a /*EAX*/, float b /*EDX*/) -> EAX and flags");
		HELPERS.put(0x6b620L, "float __FSA(float a /*EAX*/, float b /*EDX*/)");
		HELPERS.put(0x6b616L, "float __FSS(float a, float b)");
		HELPERS.put(0x6b6f1L, "float __FSM(float a, float b)");
		HELPERS.put(0x6b778L, "float __FSD(float a, float b)");
	}

	private Parameter dparam(String name, String hi, String lo) throws Exception {
		Register h = currentProgram.getRegister(hi), l = currentProgram.getRegister(lo);
		return new ParameterImpl(name, DoubleDataType.dataType, new VariableStorage(currentProgram, h, l), currentProgram);
	}

	private Parameter rparam(String name, DataType t, String r) throws Exception {
		return new ParameterImpl(name, t, new VariableStorage(currentProgram, currentProgram.getRegister(r)), currentProgram);
	}

	private void helper(long a, String cc, DataType ret, Parameter... ps) throws Exception {
		Function f = currentProgram.getFunctionManager().getFunctionAt(addr(Long.toHexString(a)));
		if (f == null) {
			println("NO_HELPER " + Long.toHexString(a));
			return;
		}
		Variable rv = ret instanceof DoubleDataType
				? new ReturnParameterImpl(ret, new VariableStorage(currentProgram,
					currentProgram.getRegister("EDX"), currentProgram.getRegister("EAX")), currentProgram)
				: new ReturnParameterImpl(ret, new VariableStorage(currentProgram, currentProgram.getRegister("EAX")),
					currentProgram);
		f.updateFunction(cc, (ReturnParameterImpl) rv, List.of(ps), FunctionUpdateType.CUSTOM_STORAGE, true,
			SourceType.ANALYSIS);
		f.setStackPurgeSize(0);
	}

	private void applyHelperSignatures() throws Exception {
		DataType d = DoubleDataType.dataType, s = FloatDataType.dataType;
		DataType i = IntegerDataType.dataType, u = UnsignedIntegerDataType.dataType;
		for (long a : new long[] { 0x6ae22L, 0x6ae1cL, 0x6afd9L }) {
			helper(a, "__watcall4", d, dparam("a", "EDX", "EAX"), dparam("b", "ECX", "EBX"));
		}
		// __FDC only compares and __FDD keeps ECX:EBX (read in the disassembly), so EBX,ECX survive.
		helper(0x6c3c2L, "__watcall2", d, dparam("a", "EDX", "EAX"), dparam("b", "ECX", "EBX"));
		helper(0x6b9c2L, "__watcall2", i, dparam("a", "EDX", "EAX"), dparam("b", "ECX", "EBX"));
		for (long a : new long[] { 0x6b620L, 0x6b616L, 0x6b6f1L, 0x6b778L }) {
			helper(a, "__watcall2", s, rparam("a", s, "EAX"), rparam("b", s, "EDX"));
		}
		helper(0x6cd16L, "__watcall2", i, rparam("a", s, "EAX"), rparam("b", s, "EDX"));
		helper(0x6addcL, "__watcall2", d, rparam("a", i, "EAX"));
		helper(0x6ade9L, "__watcall2", d, rparam("a", u, "EAX"));
		helper(0x6b42cL, "__watcall2", s, dparam("a", "EDX", "EAX"));
		helper(0x6b478L, "__watcall2", d, rparam("a", s, "EAX"));
		helper(0x6b4d6L, "__watcall2", i, dparam("a", "EDX", "EAX"));
		helper(0x6b4daL, "__watcall2", u, dparam("a", "EDX", "EAX"));
		helper(0x6b605L, "__watcall1", s, rparam("a", i, "EAX"));
		helper(0x6b5daL, "__watcall1", s, rparam("a", u, "EAX"));
		helper(0x6b878L, "__watcall1", i, rparam("a", s, "EAX"));
		helper(0x6b882L, "__watcall1", u, rparam("a", s, "EAX"));
	}
}
