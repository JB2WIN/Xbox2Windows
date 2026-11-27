"""GPU-selected global SRV heap slot: native recording and offline request replay (issue #2908).

usage: native_global_srv_heap_replay_check.py FIXTURE COMPILE_DXIL SDK ADAPTER

A source-built compute container picks a descriptor heap slot from a GPU buffer (t0), reads 64 words through
ResourceDescriptorHeap[slot] and stores them to u0. Slots 0 and 1 are raw buffers with different data, slot 2 is a
texture, slot 3 a typed buffer. The fixture's `record` mode captures the GPU selector and the slot view types into a
req_<key>.views file and refuses the incompatible slots before the dispatch; `compile_dxil` and the fixture's `replay`
mode consume the same file offline. Exit 77 when the fixture reports a capability skip.
"""
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

fixture, compile_dxil, sdk, adapter = sys.argv[1:5]
RAW = "global SRV slot {n} has view type {t}, the shader needs raw_buffer"
HEAP_REFUSAL = "direct resource-heap load requires the selected GPU slot and its view type"


def words(*values):
    return struct.pack(f"<{len(values)}I", *values)


def pack(body, extra=()):
    raw = b"FSSM" + struct.pack("<IQ", 0x101, len(body)) + body
    compressed = zlib.compress(raw)
    blob = b"XBCH" + struct.pack("<IQQ", 3, len(compressed), len(raw)) + compressed
    part = bytes(24) + b"XDAT" + words(1, 0, 13, 48, len(blob)) + blob
    chunks = [(b"DXIL", part), *extra]
    table = []
    data = b""
    for name, payload in chunks:
        table.append(32 + 4 * len(chunks) + len(data))
        data += name + words(len(payload)) + payload
        data += bytes(-len(data) % 4)
    return b"DXBC" + bytes(16) + words(1, 32 + 4 * len(chunks) + len(data), len(chunks), *table) + data


def compute_two_inputs(code, threads=64):
    """compute() of native_direct_container_check.py with both root inputs in one list: an SRV/UAV descriptor table
    in s[0:1] (type 3) and the descriptor heap in s[2:3] (type 5). Four user SGPRs: rsrc2 0x8400 | 0x1008."""
    body = bytearray(256)
    struct.pack_into("<Q", body, 0, 6)
    for offset in (8, 16, 24, 32, 40, 48, 72):
        struct.pack_into("<Q", body, offset, 0xDEADBEEFDEADBEEF)
    record = 112
    struct.pack_into("<Q", body, 96, record)
    struct.pack_into("<Q", body, record + 40, len(body))
    struct.pack_into("<I", body, record + 56, 2)
    body.extend(struct.pack("<IIIIBBH", 3, 0, 1, 0, 0, 0, 0))  # A: table of root parameter 0 at user SGPR 0
    body.extend(struct.pack("<IIIIBBH", 5, 0, 1, 0, 2, 0, 0))  # B: descriptor heap at user SGPR 2
    struct.pack_into("<QQ", body, record, len(body), len(code))
    struct.pack_into("<I", body, record + 20, 32)
    struct.pack_into("<II", body, record + 76, 512, 4)
    struct.pack_into("<IIII", body, record + 120, 0x8400 | 0x1008, threads, 1, 1)
    body.extend(code)
    return pack(body)


# Assembled with LLVM 15: clang -cc1as -triple amdgcn-amd-amdhsa -target-cpu gfx1013 -show-encoding.
PROGRAM = words(
    0xbe810380,  # s_mov_b32 s1, 0
    0xbe830380,  # s_mov_b32 s3, 0
    0xf4080200, 0xfa000000,  # s_load_dwordx4 s[8:11], s[0:1], 0x0        (t0: the selector)
    0xf4080300, 0xfa000020,  # s_load_dwordx4 s[12:15], s[0:1], 0x20      (u0: the output)
    0xf4200404, 0xfa000000,  # s_buffer_load_dword s16, s[8:11], 0x0      (the selected slot)
    0xbf8cc07f,  # s_waitcnt lgkmcnt(0)
    0x8f118510,  # s_lshl_b32 s17, s16, 5
    0xf4080501, 0x22000000,  # s_load_dwordx4 s[20:23], s[2:3], s17       (heap descriptor of the slot)
    0xbf8cc07f,  # s_waitcnt lgkmcnt(0)
    0x34020082,  # v_lshlrev_b32_e32 v1, 2, v0
    0xe0301000, 0x80050201,  # buffer_load_dword v2, v1, s[20:23], 0 offen
    0xbf8c3f70,  # s_waitcnt vmcnt(0)
    0xe0701000, 0x80030201,  # buffer_store_dword v2, v1, s[12:15], 0 offen
    0xbf810000,  # s_endpgm
)


def key_of(root, cdx):
    """FNV-1a 64 as read_compute_container (src/shader_compute_request.cpp)."""
    key = 1469598103934665603
    for byte in b"native-container-1" + struct.pack("<Q", len(root)) + root + cdx:
        key = ((key ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return key


def run(command):
    result = subprocess.run([str(part) for part in command], capture_output=True, timeout=100)
    out = result.stdout.decode("utf-8", "replace")
    err = result.stderr.decode("utf-8", "replace")
    print("$ " + " ".join(pathlib.Path(str(c)).name if i == 0 else str(c) for i, c in enumerate(command)))
    for text in (out, err):
        for line in text.strip().splitlines():
            print("    " + line)
    print(f"    -> exit {result.returncode}")
    if result.returncode == 77 and str(command[0]) == fixture:
        print("fixture capability skip (77)")
        sys.exit(77)
    return result.returncode, out, err


def require(condition, message):
    if not condition:
        print("FAIL: " + message)
        sys.exit(1)
    print("ok: " + message)


with tempfile.TemporaryDirectory(prefix="x2w_global_srv_") as scratch:
    base = pathlib.Path(scratch)
    cache = base / "cache"
    cache.mkdir()

    # Fixture root signature, container, key (B6).
    root_path = base / "fixture.root"
    code, out, err = run([fixture, "root", root_path])
    require(code == 0 and root_path.stat().st_size > 0, "fixture wrote the root signature")
    root = root_path.read_bytes()
    cdx = compute_two_inputs(PROGRAM)
    stem = "req_%016x" % key_of(root, cdx)

    def request_dir(name):
        directory = base / name
        directory.mkdir()
        (directory / (stem + ".cdx")).write_bytes(cdx)
        (directory / (stem + ".root")).write_bytes(root)
        return directory

    def compile_directory(directory):
        out_dir = base / (directory.name + "_out")
        result = run([compile_dxil, sdk, cache, "gfx1013-container-cs", "--requests", directory, out_dir])
        # compile_dxil --requests publishes <key>.cs.cso (the req_ prefix stripped) for a compute request.
        return result, out_dir / (stem[len("req_"):] + ".cs.cso")

    selections = [request_dir(f"sel{n}") for n in range(4)]
    nometa = request_dir("nometa")

    # 1. Missing metadata, offline: a heap shader without .views is refused before any output exists.
    (code, out, err), cso = compile_directory(nometa)
    require(code == 1 and HEAP_REFUSAL in err, "compile_dxil without .views refuses the heap read with the slot/type text")
    require(not cso.exists(), "no .cso is published for the request without .views")

    # 2. Native recording path: accepted and refused selections.
    for n in (0, 1):
        views = selections[n] / (stem + ".views")
        code, out, err = run([fixture, "record", sdk, cache, selections[n] / (stem + ".cdx"), adapter, n, "ok"])
        require(code == 0, f"record select {n}: fenced output equals the slot {n} data and u0 sentinels are intact")
        require("output matches slot %d data" % n in out, f"record select {n} compared 64 words with the CPU reference")
        text = views.read_text()
        require(text.startswith("x2w-global-srv-views 2\nselect %d\nneed raw_buffer\n" % n),
                f"record select {n} captured the GPU selector and the view type")
        for line in ("slot 0 raw_buffer 1 256", "slot 1 raw_buffer 1 256", "slot 2 texture 0 0", "slot 3 typed_buffer 4 256"):
            require(line + "\n" in text, f"captured view line '{line}'")
    for n, type_name in ((2, "texture"), (3, "typed_buffer")):
        code, out, err = run([fixture, "record", sdk, cache, selections[n] / (stem + ".cdx"), adapter, n, "refused"])
        require(code == 0, f"record select {n}: refused with unchanged u0 sentinels")
        require(RAW.format(n=n, t=type_name) in out, f"record select {n}: slot/type diagnostic before the dispatch")
        require("no dispatch submitted" in out and "sentinels intact" in out, f"record select {n}: nothing was dispatched")

    # 3. Discrimination control: without the guard a valid slot runs and changes u0, which the check must see.
    code, out, err = run([fixture, "record", sdk, cache, selections[0] / (stem + ".cdx"), adapter, 0, "refused", "--no-guard"])
    require(code == 3 and "sentinels changed" in out, "record --no-guard expecting a refusal sees the changed sentinels (exit 3)")

    # 4. Offline replay compilation of the captured requests.
    outputs = {}
    for n in range(4):
        (code, out, err), cso = compile_directory(selections[n])
        outputs[n] = cso
        if n < 2:
            require(code == 0 and "requests=1 compiled=1 refused=0" in out, f"compile_dxil select {n}: compiled")
            require("global_srv select=%d need=raw_buffer" % n in out, f"compile_dxil select {n}: reports the captured selection")
            require(cso.exists(), f"compile_dxil select {n}: published a .cso")
        else:
            type_name = "texture" if n == 2 else "typed_buffer"
            require(code == 1 and "refused=1" in out, f"compile_dxil select {n}: refused")
            require(RAW.format(n=n, t=type_name) in err, f"compile_dxil select {n}: slot/type diagnostic")
            require(not cso.exists(), f"compile_dxil select {n}: no .cso")

    # 5. Fixture replay of the compiled shader and of the refusals.
    def replay(directory, cso, views, expect, reference):
        return run([fixture, "replay", sdk, cache, directory / (stem + ".cdx"), cso, views, adapter, expect, reference])

    for n in (0, 1):
        code, out, err = replay(selections[n], outputs[n], selections[n] / (stem + ".views"), "ok", n)
        require(code == 0 and "output matches slot %d data" % n in out, f"replay select {n}: compiled shader output equals slot {n} data")
    for n, type_name in ((2, "texture"), (3, "typed_buffer")):
        code, out, err = replay(selections[0], outputs[0], selections[n] / (stem + ".views"), "refused", 0)
        require(code == 0 and RAW.format(n=n, t=type_name) in out and "sentinels intact" in out,
                f"replay select {n}: refused with the slot/type diagnostic, u0 sentinels intact")

    # 6. Mutation control: the slot 1 data is not the slot 0 reference.
    code, out, err = replay(selections[0], outputs[0], selections[0] / (stem + ".views"), "ok", 1)
    require(code == 1 and "mismatch word 0" in out, "replay select 0 compared with slot 1 data reports a mismatch (exit 1)")

    # 7. Negative controls on both paths: metadata that cannot reconstruct the binding.
    good = (selections[0] / (stem + ".views")).read_text()
    lines = good.splitlines()

    def variant(name, text, expected):
        directory = request_dir("neg_" + name)
        views = directory / (stem + ".views")
        views.write_text(text, newline="\n")
        (code, out, err), cso = compile_directory(directory)
        require(code == 1 and expected in err, f"compile_dxil '{name}': refused with '{expected}'")
        require(not cso.exists() and not any(cso.parent.glob("*.cso")), f"compile_dxil '{name}': no .cso")
        code, out, err = replay(selections[0], outputs[0], views, "refused", 0)
        require(code == 0 and expected in out and "sentinels intact" in out,
                f"replay '{name}': refused with the same diagnostic, u0 sentinels intact")

    def without(prefix):
        kept = [line for line in lines if not line.startswith(prefix)]
        require(len(kept) == len(lines) - 1, f"control input drops exactly one '{prefix}' line")
        return "\n".join(kept) + "\n"

    variant("mismatched_type", good.replace("slot 0 raw_buffer 1 256", "slot 0 texture 0 0"), RAW.format(n=0, t="texture"))
    require("slot 0 texture 0 0" in (base / "neg_mismatched_type" / (stem + ".views")).read_text(), "mismatch input rewrote slot 0")
    variant("no_need", without("need "), "global SRV view metadata lacks the needed view type")
    variant("no_select", without("select "), "global SRV view metadata lacks the selected slot")
    variant("no_slot_line", without("slot 0 "), "global SRV slot 0 has no captured view type")
    variant("select_7", good.replace("select 0", "select 7"), "global SRV slot 7 has no captured view type")

    # 8. Shader shapes whose heap read could address another slot than the captured selection, or read the slot's
    #    stride: refused by compile_dxil even with valid metadata, no .cso.
    words_list = list(struct.unpack(f"<{len(PROGRAM) // 4}I", PROGRAM))
    lshl = words_list.index(0x8f118510)
    heap_load = words_list.index(0xf4080501)
    shapes = {
        # s_mov_b32 s17, 64 instead of the GPU-derived s_lshl_b32 s17, s16, 5
        "constant_index": (words_list[:lshl] + [0xbe9103c0] + words_list[lshl + 1:],
                           "heap descriptor index is a constant; the captured selection must come from GPU data"),
        # s_load_dwordx4 s[20:23], s[2:3], s17 offset:0x20
        "immediate_offset": (words_list[:heap_load] + [0xf4080501, 0x22000020] + words_list[heap_load + 2:],
                             "heap descriptor load with an immediate offset addresses another slot than the captured selection"),
        # s_bfe_u32 s24, s21, 0xe0010 after the heap descriptor load (stride field of the selected slot)
        "stride_read": (words_list[:heap_load + 3] + [0x9398ff15, 0x000e0010] + words_list[heap_load + 3:],
                        "a GPU-selected heap slot stride read is not translated with a view contract"),
    }
    for name, (program, expected) in shapes.items():
        directory = base / ("shape_" + name)
        directory.mkdir()
        shape_cdx = compute_two_inputs(words(*program))
        shape_stem = "req_%016x" % key_of(root, shape_cdx)
        (directory / (shape_stem + ".cdx")).write_bytes(shape_cdx)
        (directory / (shape_stem + ".root")).write_bytes(root)
        (directory / (shape_stem + ".views")).write_text(good, newline="\n")
        out_dir = base / (directory.name + "_out")
        code, out, err = run([compile_dxil, sdk, cache, "gfx1013-container-cs", "--requests", directory, out_dir])
        require(code == 1 and expected in err, f"compile_dxil shape '{name}': refused with '{expected}'")
        require(not any(out_dir.glob("*.cso")), f"compile_dxil shape '{name}': no .cso")

    missing = base / "missing" / (stem + ".views")
    code, out, err = replay(selections[0], outputs[0], missing, "refused", 0)
    require(code == 0 and "global SRV view metadata file missing: " + str(missing) in out and "sentinels intact" in out,
            "replay with a missing .views path refuses with the file diagnostic, u0 sentinels intact")

print("native_global_srv_heap_replay: all checks passed")
