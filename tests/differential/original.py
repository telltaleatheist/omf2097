"""Runs functions of the original program in Unicorn, from the analysis image.

The image (tools/build_analysis.sh) holds both objects at their load addresses with
fixups applied. Nothing else is set up, so a function that needs DOS needs stubs.
"""
import struct

from unicorn import UC_ARCH_X86, UC_MODE_32, UC_PROT_ALL, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP)

SKIP = 77  # the exit code CTest reports as skipped

IMAGE_BASE, IMAGE_SIZE = 0x10000, 0x1f0000
STACK_TOP = 0x1e0000
RETURN_TO = 0x1f0000
REGS = dict(eax=UC_X86_REG_EAX, ebx=UC_X86_REG_EBX, ecx=UC_X86_REG_ECX, edx=UC_X86_REG_EDX,
            esi=UC_X86_REG_ESI, edi=UC_X86_REG_EDI, ebp=UC_X86_REG_EBP)


def image_sections(path):
    data = open(path, 'rb').read()
    table = struct.unpack_from('<I', data, 32)[0]
    entry_size, count = struct.unpack_from('<HH', data, 46)
    for i in range(count):
        _, kind, _, addr, offset, size = struct.unpack_from('<6I', data, table + i * entry_size)
        if addr and kind == 1:
            yield addr, data[offset:offset + size]


class Original:
    def __init__(self, elf):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(IMAGE_BASE, IMAGE_SIZE, UC_PROT_ALL)
        for addr, body in image_sections(elf):
            self.uc.mem_write(addr, body)
        self.uc.mem_write(RETURN_TO, b'\xf4')

    def call(self, addr, **regs):
        """Calls with the given registers; returns EAX. Other registers start from a fixed junk value."""
        for name, reg in REGS.items():
            self.uc.reg_write(reg, regs.get(name, 0xdead0000) & 0xffffffff)
        self.uc.reg_write(UC_X86_REG_EFLAGS, 2)
        self.uc.reg_write(UC_X86_REG_ESP, STACK_TOP)
        self.uc.mem_write(STACK_TOP, struct.pack('<I', RETURN_TO))
        self.uc.emu_start(addr, RETURN_TO, count=200000)
        return self.uc.reg_read(UC_X86_REG_EAX)

    def read(self, addr, size):
        return bytes(self.uc.mem_read(addr, size))

    def write(self, addr, data):
        self.uc.mem_write(addr, bytes(data))

    def u32(self, addr):
        return struct.unpack('<I', self.read(addr, 4))[0]
