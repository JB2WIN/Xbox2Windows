"""s_bfm_b64 in tools/startup/gfx2hlsl.py (census issue #1723).

usage: startup_gfx2hlsl_bfm_b64_check.py

`s_bfm_b64` had no lowering and was refused. RDNA 2 ISA (SOP2 opcode 37, `isa/rdna2_isa.txt` "S_BFM_B64"):
`D.u64 = ((1ULL << S0.u[5:0]) - 1) << S1.u[5:0]`. Both sources are 32-bit and only their low six bits count; a
width of 0 gives 0; the mask is truncated to 64 bits, so bits shifted past bit 63 are dropped. The ISA lists no SCC
write for this opcode (the bitwise ops print `SCC = (D != 0)`), so SCC is left alone.

The 64-bit scalar value is two words (s[d], s[d+1]) written together. The instruction bytes are constructed here
from the SOP2 layout the checked-in decoder reads (`tools/disasm_rdna2.py`: [31:30]=0b10, opcode [29:23], sdst
[22:16], ssrc1 [15:8], ssrc0 [7:0]).

The emitted HLSL, including the real `shl64` helper from the generated preamble, is evaluated by a small integer
evaluator that rejects any 32-bit shift count of 32 or more (undefined in HLSL), and compared with a reference built
from a bit loop over the ISA description, not from the lowering's expressions. Mutations (no width mask, 31 instead of
63, offset masked to five bits, width 0 reading all ones) must read a wrong word and are applied to the translated
text only.
"""
import os
import re
import struct
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, '..', 'tools'))
sys.path.insert(0, os.path.join(here, '..', 'tools', 'startup'))
import gfx2hlsl as G  # noqa: E402

MASK = 0xffffffff
failures = []


def check(label, condition, detail=''):
    print(f"{label}: {'ok' if condition else 'MISMATCH'}")
    if not condition:
        failures.append(label)
        if detail:
            print('  ' + detail)


def reference(width, offset):
    """The ISA mask as a bit loop: bit i is set when offset <= i < offset + width and i < 64."""
    width, offset = width & 63, offset & 63
    return sum(1 << i for i in range(64) if offset <= i < offset + width)


# ---- instruction construction ------------------------------------------------------------------------------
SOP2_BFM_B64 = 37


def encode(dst, src0, src1, literal=None):
    w0 = 0x80000000 | (SOP2_BFM_B64 << 23) | (dst << 16) | (src1 << 8) | src0
    out = struct.pack('<I', w0)
    return out + (struct.pack('<I', literal) if literal is not None else b'')


class Pipeline:
    def __init__(self):
        self.resources, self.notes, self.modified = {}, set(), set()


class Stage(G.Stage):
    def __init__(self):
        self.lines, self.sym, self.masks = [], {}, set()
        self.used_s, self.used_v, self.uniform_v = set(), set(), set()
        self.exec_known = True
        self.exports = {}
        self.pipe = Pipeline()


def translate(asm, sym=None):
    stage = Stage()
    stage.sym.update(sym or {})
    stage.one('s_bfm_b64', asm)
    return stage


def refused(asm, sym=None):
    try:
        translate(asm, sym)
    except G.Unsupported:
        return True
    return False


# ---- a small evaluator for the HLSL the lowering and the shl64 helper use ---------------------------------
TOKEN = re.compile(r'\s*(0x[0-9a-fA-F]+u?|\d+u?|[A-Za-z_]\w*|<<|>>|<=|>=|==|!=|\|\||&=|[-+*&|^~!<>?:(),.=])')
LEVELS = [['||'], ['|'], ['^'], ['&'], ['==', '!='], ['<', '>', '<=', '>='], ['<<', '>>'], ['+', '-'], ['*']]


class Interp:
    def __init__(self, common):
        self.funcs = {}
        m = re.search(r'uint2 shl64\(([^)]*)\) \{(.*?)\}\s*(?=\'|uint2 shr64u|$)', common)
        assert m, 'shl64 not found in the preamble'
        self.funcs['shl64'] = ([p.split()[-1] for p in m.group(1).split(',')], m.group(2))

    def tokens(self, text):
        toks = TOKEN.findall(text)
        assert ''.join(toks) == re.sub(r'\s+', '', text), text
        return toks

    def expr(self, text, env):
        self.t, self.p, self.env = self.tokens(text), 0, env
        value = self.ternary()
        assert self.p == len(self.t), text
        return value

    def peek(self):
        return self.t[self.p] if self.p < len(self.t) else None

    def take(self):
        self.p += 1
        return self.t[self.p - 1]

    def ternary(self):
        cond = self.binary(0)
        if self.peek() != '?':
            return cond
        self.take()
        yes = self.ternary()
        assert self.take() == ':'
        no = self.ternary()
        return yes if cond else no

    def binary(self, level):
        if level == len(LEVELS):
            return self.unary()
        node = self.binary(level + 1)
        while self.peek() in LEVELS[level]:
            op = self.take()
            b = self.binary(level + 1)
            a = node
            if op in ('<<', '>>'):
                assert 0 <= b < 32, 'HLSL shift count %d is not below 32' % b
                node = (a << b) & MASK if op == '<<' else a >> b
            elif op == '||':
                node = int(bool(a or b))
            else:
                node = {'|': a | b, '^': a ^ b, '&': a & b, '+': a + b, '-': a - b, '*': a * b, '==': int(a == b),
                        '!=': int(a != b), '<': int(a < b), '>': int(a > b), '<=': int(a <= b),
                        '>=': int(a >= b)}[op]
                node &= MASK
        return node

    def unary(self):
        tok = self.take()
        if tok == '~':
            return ~self.unary() & MASK
        if tok == '(':
            v = self.ternary()
            assert self.take() == ')'
            return self.member(v)
        if tok[0].isdigit():
            return int(tok.rstrip('u'), 0)
        if self.peek() == '(':
            self.take()
            args = [self.ternary()]
            while self.peek() == ',':
                self.take()
                args.append(self.ternary())
            assert self.take() == ')'
            return self.member(self.call(tok, args))
        return self.member(self.env[tok])

    def member(self, v):
        while self.peek() == '.':
            self.take()
            v = v['xy'.index(self.take())]
        return v

    def call(self, name, args):
        if name == 'uint2':
            return tuple(args)
        params, body = self.funcs[name]
        saved = (self.t, self.p, self.env)
        env = dict(zip(params, args))
        result = self.run(body, env)
        self.t, self.p, self.env = saved
        return result

    def run(self, text, env):
        """Run statements; returns the value of a `return`."""
        for stmt in [s.strip() for s in text.split(';') if s.strip()]:
            stmt = stmt.strip('{} ')
            if not stmt:
                continue
            if stmt.startswith('return '):
                return self.expr(stmt[7:], env)
            m = re.match(r'(uint2|uint)\s+(.*)$', stmt)
            if m:
                for part in re.split(r',\s*(?=\w+\s*=)', m.group(2)):
                    name, _, rhs = part.partition('=')
                    env[name.strip()] = self.expr(rhs, env)
                continue
            m = re.match(r'(\w+)\s*(&=|=)\s*(.*)$', stmt)
            assert m, stmt
            value = self.expr(m.group(3), env)
            env[m.group(1)] = (env[m.group(1)] & value) if m.group(2) == '&=' else value
        return None


def preamble():
    pipe = object.__new__(G.Pipeline)
    pipe.uds, pipe.resources, pipe.samplers, pipe.uses_sampler_heap = [], {}, {}, False
    return ' '.join(pipe.common())


COMMON = preamble()


def evaluate(stage, env, common=COMMON):
    """Run the emitted lines of `stage` and return the (s20, s21) words."""
    interp = Interp(common)
    env = dict(env)
    for line in stage.lines:
        # one block of statements: '{ ...; s20 = t.x; s21 = t.y; }'
        interp.run(line, env)
    return env['s20'], env['s21']


def pair(value):
    return value & MASK, value >> 32


# ---- 1. the encoder produces the form the decoder reads -----------------------------------------------------
decoded = G.decode(encode(20, 2, 3))
check('encodes and decodes the register form', [a for _o, _s, _n, a in decoded] == ['s_bfm_b64 s[20:21], s2, s3'],
      repr(decoded))
decoded = G.decode(encode(20, 128 + 33, 128 + 5))
check('encodes and decodes inline constants', [a for _o, _s, _n, a in decoded] == ['s_bfm_b64 s[20:21], 33, 5'],
      repr(decoded))
decoded = G.decode(encode(20, 255, 3, literal=0x12345681))
check('encodes and decodes a literal', [a for _o, _s, _n, a in decoded] == ['s_bfm_b64 s[20:21], 0x12345681, s3'],
      repr(decoded))

# ---- 2. run-time sources: the whole width x offset grid, evaluated against the bit-loop reference -----------
asm = 's_bfm_b64 s[20:21], s2, s3'
stage = translate(asm)
text = ' '.join(stage.lines)
check('run-time form writes both words and no SCC',
      's20 = t.x;' in text and 's21 = t.y;' in text and 'scc' not in text and 'shl64(' in text, text)
bad = []
for w in range(64):
    for o in range(64):
        got = evaluate(stage, {'s2': w, 's3': o})
        if got != pair(reference(w, o)):
            bad.append((w, o, got))
check('all 64 x 64 width/offset pairs match the reference', not bad, repr(bad[:3]))
key = [(0, 0), (0, 63), (1, 0), (1, 63), (31, 0), (31, 31), (31, 32), (32, 0), (32, 31), (32, 32), (33, 0),
       (33, 31), (33, 32), (33, 63), (63, 0), (63, 1), (63, 31), (63, 32), (63, 63), (0, 31), (1, 31), (1, 32)]
bad = [(w, o) for w, o in key if evaluate(stage, {'s2': w, 's3': o}) != pair(reference(w, o))]
check('named widths 0/1/31/32/33/63 against offsets 0/31/32/63', not bad, repr(bad))
# hand-written anchors, so the reference is not the only witness
anchors = {(0, 0): 0, (0, 63): 0, (1, 63): 1 << 63, (63, 1): (1 << 64) - 2, (32, 32): 0xffffffff00000000,
           (33, 31): 0xffffffff80000000, (63, 63): 1 << 63, (31, 32): 0x7fffffff00000000}
check('hand-computed anchors', all(reference(*k) == v and evaluate(stage, {'s2': k[0], 's3': k[1]}) == pair(v)
                                   for k, v in anchors.items()))
# source bits above [5:0] are ignored
junk = [(w | hi, o | hj) for w in (0, 1, 31, 32, 33, 63) for o in (0, 31, 32, 63)
        for hi, hj in ((0x40, 0), (0, 0x40), (0xffffffc0, 0xffffff80), (0x80000000, 0x80000040), (0x12345640, 0xabcdef00))]
bad = [(w, o) for w, o in junk if evaluate(stage, {'s2': w, 's3': o}) != pair(reference(w, o))]
check('bits above [5:0] of either source are ignored (%d inputs)' % len(junk), not bad, repr(bad[:3]))

# ---- 3. inline and literal sources ---------------------------------------------------------------------------
stage = translate('s_bfm_b64 s[20:21], 33, s3')
check('an inline width with a run-time offset reads the constant',
      '0x00000021u' in ' '.join(stage.lines) and all(
          evaluate(stage, {'s3': o}) == pair(reference(33, o)) for o in range(64)))
stage = translate('s_bfm_b64 s[20:21], s2, 32')
check('a run-time width with an inline offset reads the constant',
      all(evaluate(stage, {'s2': w}) == pair(reference(w, 32)) for w in range(64)))
stage = translate('s_bfm_b64 s[20:21], 0x12345681, s3')
check('a literal width keeps only its low six bits (0x81 & 63 = 1)',
      all(evaluate(stage, {'s3': o}) == pair(reference(1, o)) for o in range(64)))

# ---- 4. fully constant sources fold, with the same result ----------------------------------------------------
bad = []
for w, o in [(0, 0), (1, 0), (31, 0), (32, 0), (33, 0), (63, 0), (1, 63), (63, 63), (33, 32), (32, 31), (0, 63), (5, 3)]:
    stage = translate('s_bfm_b64 s[20:21], %d, %d' % (w, o))
    if stage.sym.get(20) != ('const', pair(reference(w, o))[0]) or stage.sym.get(21) != ('const', pair(reference(w, o))[1]):
        bad.append((w, o, stage.sym))
check('inline constants fold to the reference words', not bad, repr(bad[:2]))
stage = translate('s_bfm_b64 s[20:21], 0x12345681, 0x7f')
check('literals fold and mask both sources',
      (stage.sym.get(20), stage.sym.get(21)) == tuple(('const', x) for x in pair(reference(1, 63))))
stage = translate('s_bfm_b64 s[20:21], s2, s3', {2: ('const', 33), 3: ('const', 31)})
check('SGPRs holding known constants fold',
      (stage.sym.get(20), stage.sym.get(21)) == tuple(('const', x) for x in pair(reference(33, 31))))
stage = translate('s_bfm_b64 s[20:21], s2, s3', {2: ('const', 0x1000), 3: ('const', 0)})
check('a known width whose low six bits are 0 folds to a zero pair',
      (stage.sym.get(20), stage.sym.get(21)) == (('const', 0), ('const', 0)))

# ---- 5. an in-place destination reads the original sources ----------------------------------------------------
stage = translate('s_bfm_b64 s[2:3], s2, s3')
env = {'s2': 33, 's3': 31}
interp = Interp(COMMON)
for line in stage.lines:
    interp.run(line, env)
check('the destination may be the source registers', (env['s2'], env['s3']) == pair(reference(33, 31)), repr(env))

# ---- 6. refusals ---------------------------------------------------------------------------------------------
check('odd, single, vector and mask destinations are refused', all(refused(a) for a in (
    's_bfm_b64 s[21:22], s2, s3', 's_bfm_b64 s20, s2, s3', 's_bfm_b64 v[20:21], s2, s3', 's_bfm_b64 exec, s2, s3',
    's_bfm_b64 vcc, s2, s3', 's_bfm_b64 s[20:23], s2, s3', 's_bfm_b64 s[106:107], s2, s3', 's_bfm_b64 m0, s2, s3')))
check('pair, vector and mask sources are refused', all(refused(a) for a in (
    's_bfm_b64 s[20:21], s[2:3], s3', 's_bfm_b64 s[20:21], s2, s[4:5]', 's_bfm_b64 s[20:21], v2, s3',
    's_bfm_b64 s[20:21], s2, vcc', 's_bfm_b64 s[20:21], exec, s3', 's_bfm_b64 s[20:21], vcc_lo, s3')))
check('wrong operand counts and modifiers are refused', all(refused(a) for a in (
    's_bfm_b64 s[20:21], s2', 's_bfm_b64 s[20:21], s2, s3, s4', 's_bfm_b64 s[20:21]', 's_bfm_b64 s[20:21], s2, s3 clamp')))
check('a source holding descriptor data is refused',
      refused('s_bfm_b64 s[20:21], s2, s3', {2: ('desc', 0, 0, 0)}))
check('a well-formed pair is accepted (control for the refusals)', not refused('s_bfm_b64 s[20:21], s2, s3'))

# ---- 7. mutations must read a wrong word -------------------------------------------------------------------------
GRID = [(w, o) for w in (0, 1, 31, 32, 33, 63) for o in (0, 31, 32, 63)] + \
       [(0x40, 0), (0x41, 5), (0xffffffa1, 3), (32, 0x80), (3, 0x7f)]
base = translate('s_bfm_b64 s[20:21], s2, s3')


def mutated_wrong(stage_lines, common):
    class S:
        lines = stage_lines
    return [(w, o) for w, o in GRID if evaluate(S, {'s2': w, 's3': o}, common) != pair(reference(w, o))]


line = base.lines[0]
check('control: the unmutated text has no wrong word on the mutation grid', not mutated_wrong(base.lines, COMMON))
mutations = {
    'no mask on the width': ([re.sub(r'(uint bw = s2) & 63u', r'\1', line)], COMMON),
    'width masked with 31': ([line.replace('s2 & 63u', 's2 & 31u')], COMMON),
    'offset masked to five bits': (base.lines, COMMON.replace('sh &= 63u;', 'sh &= 31u;')),
    'width 0 reads all ones': ([line.replace('bw >= 32u ?', 'bw >= 32u || bw == 0u ?', 1)], COMMON),
}
for name, (lines, common) in mutations.items():
    changed = lines != base.lines or common != COMMON
    wrong = mutated_wrong(lines, common) if changed else []
    check('mutation "%s" changes the text and reads a wrong word %s' % (name, wrong[:1]), changed and bool(wrong))

if failures:
    print('FAIL')
    for item in failures:
        print('  ' + item)
    sys.exit(1)
print('PASS')
