import struct
import re
import json
import os
from binaryninja import *

# from https://gis.stackexchange.com/questions/130027/getting-a-plugin-path-using-python-in-qgis
def resolve(name, basepath=None):
    if not basepath:
      basepath = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(basepath, name)

class GB(Architecture):
    name = "GB"
    address_size = 2
    default_int_size = 1
    max_instr_length = 3
    regs = {
        'A': RegisterInfo('A', 1),
        'B': RegisterInfo('B', 1),
        'C': RegisterInfo('C', 1),
        'D': RegisterInfo('D', 1),
        'E': RegisterInfo('E', 1),
        'F': RegisterInfo('F', 1),
        'H': RegisterInfo('H', 1),
        'L': RegisterInfo('L', 1),
        'SP': RegisterInfo('SP', 2),
        'PC': RegisterInfo('PC', 2),
    }
    stack_pointer = 'sp'
    flags = ["Z","N","H","C"]
    flag_write_types = ["*", "CZN", "ZN"]
    flag_roles = {
        'Z': FlagRole.ZeroFlagRole,
        'N': FlagRole.NegativeSignFlagRole,
        'H': FlagRole.HalfCarryFlagRole,
        'C': FlagRole.CarryFlagRole,
    }
    flags_written_by_flag_write_type = {
        "*": ["C", "Z", "H", "N"],
        "CZN": ["C", "Z", "N"],
        "ZN": ["Z", "N"],
    }
    # game boy opcodes in json format from https://github.com/lmmendes/game-boy-opcodes
    with open(resolve("opcodes.json"),'rb') as f:
        opcodes = json.loads(f.read())["unprefixed"]

    def perform_get_instruction_info(self, data, addr):
        opcode = struct.unpack('<B', data[0])[0]
        # Get instruction size
        i_info = InstructionInfo()
        try:
            op_info = self.opcodes["0x%x" % opcode]
        except KeyError:
            return None
        i_info.length = op_info['length']
        # Emulate jump instruction
        if op_info is not None:
            if op_info['mnemonic'] == 'JR':
                arg = struct.unpack('<B', data[1:2])[0]
                if opcode == 0x28 or opcode == 0x38:
                    i_info.add_branch(BranchType.TrueBranch, addr+2+arg)
                    i_info.add_branch(BranchType.FalseBranch, addr+2)
                elif opcode == 0x20 or opcode == 0x30:
                    i_info.add_branch(BranchType.TrueBranch, addr+2)
                    i_info.add_branch(BranchType.FalseBranch, addr-(~arg&0xff)+1)
                else:
                    i_info.add_branch(BranchType.UnconditionalBranch, addr-(~arg&0xff)+1)
            elif op_info['mnemonic'] == 'JP':
                if opcode == 0xe9:
                    i_info.add_branch(BranchType.UnconditionalBranch, 0xdead)
                else:
                    arg = struct.unpack('<H', data[1:3])[0]
                    if opcode == 0xca or opcode == 0xda:
                        i_info.add_branch(BranchType.TrueBranch, arg)
                        i_info.add_branch(BranchType.FalseBranch, addr+3)
                    elif opcode == 0xc0 or opcode == 0xd0:
                        i_info.add_branch(BranchType.TrueBranch, addr+3)
                        i_info.add_branch(BranchType.FalseBranch, arg)
                    else:
                        i_info.add_branch(BranchType.UnconditionalBranch, arg)
            elif op_info['mnemonic'] == 'RET':
                i_info.add_branch(BranchType.FunctionReturn)
            elif op_info['mnemonic'] == 'CALL':
                i_info.add_branch(BranchType.CallDestination, struct.unpack("<H", data[1:3])[0])
        return i_info

    def get_token(self, operand, data):
        if re.search(r'(d|r|a)8', operand) is not None:
            value = struct.unpack('<B', data[1])[0]
            if re.match(r'(d|r|a)8', operand) is not None:
                token = InstructionTextToken(InstructionTextTokenType.IntegerToken, "0x%.2x" % value, value)
            else:
                token = InstructionTextToken(InstructionTextTokenType.PossibleAddressToken, "0x%.4x" % value, value)
        elif re.search(r'(d|r|a)16', operand) is not None:
            value = struct.unpack('<H', data[1:3])[0]
            if re.match(r'(d|r|a)16', operand) is not None:
                token = InstructionTextToken(InstructionTextTokenType.IntegerToken, "0x%.4x" % value, value)
            else:
                token = InstructionTextToken(InstructionTextTokenType.PossibleAddressToken, "0x%.4x" % value, value)
        elif re.search(r'A|B|C|D|E|F|H|L|(SP)|(PC)', operand) is not None:
            if re.match(r'A|B|C|D|E|F|H|L|(SP)|(PC)', operand) is not None:
                token = InstructionTextToken(InstructionTextTokenType.RegisterToken, operand.lower())
            else:
                token = InstructionTextToken(InstructionTextTokenType.RegisterToken, operand.lower())
        else:
            token = InstructionTextToken(InstructionTextTokenType.RegisterToken, operand.lower())
        return token

    def perform_get_instruction_text(self, data, addr):
        tokens = []
        opcode = struct.unpack('<B', data[0])[0]
        try:
            op_info = self.opcodes["0x%x" % opcode]
        except KeyError:
            return None
        if op_info is not None:
            tokens.append(InstructionTextToken(InstructionTextTokenType.InstructionToken, op_info['mnemonic'].lower()))
            if 'operand1' in op_info:
                tokens.append(InstructionTextToken(InstructionTextTokenType.OperandSeparatorToken,'    '))
                tokens.append(self.get_token(op_info['operand1'], data))
                if 'operand2' in op_info:
                    tokens.append(InstructionTextToken(InstructionTextTokenType.OperandSeparatorToken,', '))
                    tokens.append(self.get_token(op_info['operand2'], data))
        return tokens, op_info['length']

    def perform_get_instruction_low_level_il(self, data, addr, il):
        return None

class GBView(BinaryView):
    name = "GB ROM"
    long_name = "Nintendo GB ROM"
    ROM_SIG_OFFSET = 0x104
    ROM_SIG_LEN = 0x30
    ROM_SIG = "\xCE\xED\x66\x66\xCC\x0D\x00\x0B\x03\x73\x00\x83\x00\x0C\x00\x0D\x00\x08\x11\x1F\x88\x89\x00\x0E\xDC\xCC\x6E\xE6\xDD\xDD\xD9\x99\xBB\xBB\x67\x63\x6E\x0E\xEC\xCC\xDD\xDC\x99\x9F\xBB\xB9\x33\x3E"
    HDR_OFFSET = 0x134
    HDR_SIZE = 0x1C
    START_ADDR = 0x100
    ROM0_SIZE = 0x4000
    ROM0_OFFSET = 0
    ROM1_SIZE = 0x4000
    ROM1_OFFSET = 0x4000

    def __init__(self, data):
        BinaryView.__init__(self, parent_view = data, file_metadata = data.file)
        self.platform = Architecture[GB.name].standalone_platform
        self.raw = data

    @classmethod
    def is_valid_for_data(self, data):
        rom_sig = data.read(self.ROM_SIG_OFFSET, self.ROM_SIG_LEN)
        if rom_sig != self.ROM_SIG:
            return False
        hdr = data.read(self.HDR_OFFSET, self.HDR_SIZE)
        if len(hdr) != self.HDR_SIZE:
            return False
        return True

    def init(self):
        try:
            hdr = self.parent_view.read(self.HDR_OFFSET, self.HDR_SIZE)
            self.rom_title = hdr[0:15]
            self.color = struct.unpack("B", hdr[15])[0]
            self.licensee_code = struct.unpack("H", hdr[16:18])[0]
            self.gb_type = struct.unpack("B", hdr[18])[0]
            self.cart_type = struct.unpack("B", hdr[19])[0]
            self.rom_banks = struct.unpack("B", hdr[20])[0]
            self.ram_banks = struct.unpack("B", hdr[21])[0]
            self.destination_code = struct.unpack("B", hdr[22])[0]
            self.old_licensee_code = struct.unpack("B", hdr[23])[0]
            self.mask_rom_version = struct.unpack("B", hdr[24])[0]
            self.complement_check = struct.unpack("B", hdr[25])[0]
            self.checksum = struct.unpack("H", hdr[26:])[0]
            
            # Add ROM mappings
            # ROM0
            self.add_auto_segment(self.ROM0_OFFSET, self.ROM0_SIZE, self.ROM0_OFFSET, self.ROM0_SIZE, SegmentFlag.SegmentReadable | SegmentFlag.SegmentExecutable)
            self.add_auto_section("ROM0", self.ROM0_OFFSET, self.ROM0_SIZE, SectionSemantics.ReadOnlyCodeSectionSemantics)
            # ROM1
            self.add_auto_segment(self.ROM1_OFFSET, self.ROM1_SIZE, self.ROM1_OFFSET, self.ROM1_SIZE, SegmentFlag.SegmentReadable | SegmentFlag.SegmentExecutable)
            self.add_auto_section("ROM1", self.ROM1_OFFSET, self.ROM1_SIZE, SectionSemantics.ReadWriteDataSectionSemantics)
            
            # Add RAM mappings
            # VRAM
            self.add_auto_segment(0x8000, 0x2000, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # RAM1
            self.add_auto_segment(0xA000, 0x2000, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # RAM0
            self.add_auto_segment(0xC000, 0x2000, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # ECHO
            self.add_auto_segment(0xE000, 0x1E00, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # OAM
            self.add_auto_segment(0xFE00, 0xA0, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # IO
            self.add_auto_segment(0xFEA0, 0xE0, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)
            # HRAM
            self.add_auto_segment(0xFF80, 0x80, 0, 0, SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable | SegmentFlag.SegmentExecutable)

            # Add special registers
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF00, "P1"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF01, "SB"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF02, "SC"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF04, "DIV"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF05, "TIMA"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF06, "TMA"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF07, "TAC"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF0F, "IF"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF10, "NR10"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF11, "NR11"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF12, "NR12"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xff13, "NR13"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF14, "NR14"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF16, "NR21"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF17, "NR22"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF18, "NR23"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF19, "NR24"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF1A, "NR30"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF1B, "NR31"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF1C, "NR32"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF1D, "NR33"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF1E, "NR34"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF20, "NR41"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF21, "NR42"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF22, "NR43"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF23, "NR44"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF24, "NR50"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF25, "NR51"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF26, "NR52"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF40, "LCDC"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF41, "STAT"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF42, "SCY"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF43, "SCX"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF44, "LY"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF45, "LYC"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF46, "DMA"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF47, "BGP"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF48, "OBP0"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF49, "OBP1"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF4A, "WY"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF4B, "WX"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF4D, "KEY1"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF4F, "VBK"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF51, "HDMA1"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF52, "HDMA2"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF53, "HDMA3"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF54, "HDMA4"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF55, "HDMA5"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF56, "RP"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF68, "BCPS"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF69, "BCPD"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF6A, "OCPS"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF6B, "OCPD"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFF70, "SVBK"))
            self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0xFFFF, "IE"))

            # Define entrypoint
            self.define_auto_symbol(Symbol(SymbolType.FunctionSymbol, self.START_ADDR, "_start"))
            self.add_entry_point(Architecture[GB.name].standalone_platform, self.START_ADDR)

            return True
        except:
            log_error(traceback.format_exc())
            return False
    
    def perform_is_valid_offset(self, addr):
        # valid ROM addresses are the upper-half of the address space
        if (addr >= 0) and (addr < 0x8000):
            return True
        return False

    def perform_get_start(self):
        return 0

    def perform_get_length(self):
        return 0x10000

    def perform_is_executable(self):
	    return True

    def perform_get_entry_point(self):
	    return self.START_ADDR

GB.register()
GBView.register()