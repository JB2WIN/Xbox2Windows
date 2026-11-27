# GPU-selected global SRV heap slots: capture and replay of view types

Issue #2908, branch `cpp-migration`. Builds on the heap read in the direct C++ DXIL path from #2912
(`ResourceDescriptorHeap[slot]` for a raw buffer read, `src/gfx1013_direct_compute.inl` `heap_resource`).

## What changed

- The direct compute translation takes a view contract for a GPU-selected heap slot (`x2w::HeapViewContract`:
  `none`, `raw_buffer`, `other`). An SMEM descriptor load from the resource heap is refused unless the contract is
  `raw_buffer`; without a contract the existing text stays: "direct resource-heap load requires the selected GPU slot and
  its view type". A scalar buffer load from the heap base, a heap descriptor load with an immediate offset or a constant
  index (both could address another slot than the captured selection), and a stride read of a GPU-selected slot in the
  direct path are refused with their own texts. The contract is part of the frontend cache key when it is not `none`.
- Modules that read `ResourceDescriptorHeap` now also set shader flag `0x40000000`, as DXC does for the HLSL reference.
  Without it the validator refuses the module ("Flags must match usage. Validation failed."), measured by removing the
  flag and running the hardware test.
- `src/startup_stubs/native_global_srv.h` writes and reads version 2 of the view metadata, which adds the buffer size:

  ```
  x2w-global-srv-views 2
  select <slot>
  need <type>
  slot <n> <type> <stride> <bytes>
  ```

- `compile_dxil ... gfx1013-container-cs` reads an optional `req_<key>.views` next to the `.cdx` (single file and
  `--requests`). It decodes the file, refuses a selection whose slot holds another view type than `need`, refuses a `need`
  other than `raw_buffer`, translates with the `raw_buffer` contract and prints `global_srv select=<n> need=<type>`. Every
  refusal happens before the `.cso` is published. Without the file a heap-reading shader is refused as before. The
  `.views` file is not part of the `.cdx`/`.root` content key: it describes one captured dispatch.

## Meaning of "native recording" and "runtime path" here

The issue's reproduction names `native_recording_check` and `native_dispatch_states_warp`, which test
`x2w_startup::NativeRecording` (descriptor-table pages) and `x2w_startup::NativeDispatchStates` (dispatch barriers). On
`cpp-migration` only tests use these classes. The D3D12 stand-in translates slot 67 requests natively since #2958
(opt-in `X2W_NATIVE_SHADERS`) through `translate_compute` without a heap view contract, so a GPU-selected heap read is
still refused there; passing captured views into that path is follow-up work. The fixture's `record`
mode records the dispatch with both classes and applies the view guard before `Dispatch`; that is the native recording
path checked here, and its unchanged UAV sentinels are the "runtime path" sentinels of the issue. The startup runtime
itself is not covered.

The slot is selected by GPU data. The `record` mode reads the selector back from its GPU buffer before recording the
dispatch (one copy to a readback buffer and one fence per recorded dispatch) and uses that value as the captured
selection, so the guard checks the slot the GPU input actually selects, before the shader runs.

## Fixture

`tests/native_global_srv_heap_replay.cpp` with `tests/native_global_srv_heap_replay_check.py`. A source-built compute
container (two root inputs: a descriptor table in s[0:1], the descriptor heap in s[2:3]; instruction words assembled with
LLVM 15 `clang -cc1as -triple amdgcn-amd-amdhsa -target-cpu gfx1013 -show-encoding`) loads the selector from t0, loads
the descriptor of `ResourceDescriptorHeap[selector]`, reads 64 words through it and stores them to u0. Heap slots: 0 and
1 raw buffers with different data, 2 a Texture2D, 3 a typed buffer. u0 holds 72 words; the last 8 and, on a refused
selection, all 72 must keep the sentinel `0x69696969`.

The check runs, in order:

1. `compile_dxil --requests` on the request without `.views`: refused with the heap text, no `.cso`.
2. `record` for selections 0 and 1: fenced output equals the selected slot's data, sentinels intact, `.views` captured.
   Selections 2 and 3: "global SRV slot 2 has view type texture, the shader needs raw_buffer" (and `typed_buffer` for 3)
   before the dispatch, nothing dispatched, sentinels intact.
3. Discrimination control: `record --no-guard` on slot 0 expecting a refusal sees the changed sentinels (exit 3). A
   texture slot is not dispatched without the guard: reading a texture descriptor as a raw buffer is undefined in D3D12.
4. `compile_dxil --requests` on each captured selection: 0 and 1 compile, 2 and 3 are refused with the slot/type text
   and publish no `.cso`.
5. `replay` of the compiled `.cso` for 0 and 1 matches the CPU reference; the `.views` of 2 and 3 are refused before the
   dispatch with sentinels intact.
6. Mutation control: replaying selection 0 against the slot 1 reference reports a mismatch.
7. Negative controls on both `compile_dxil` and `replay`: slot 0 rewritten to `texture`, no `need` line, no `select`
   line, no line for the selected slot, `select 7`, and (replay) a missing `.views` file. Each gives an explicit
   diagnostic, no `.cso`, and intact sentinels.
8. Shader shapes refused by `compile_dxil` even with valid metadata: a constant heap index, a heap descriptor load with
   an immediate offset, and a stride read of the selected slot.

## Result

```
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --no-tests=error -R "^native_global_srv_heap_replay(_warp|_hardware)?$" -V
```

- `native_global_srv_heap_replay_hardware`: passed, 70 assertions (NVIDIA GeForce RTX 3080, driver 32.0.16.2124,
  Windows 11 build 26200, MSVC toolset 14.51.36231, Windows SDK 10.0.26100 DXC, D3D12 debug layer not enabled).
- `native_global_srv_heap_replay_warp`: skipped (77), "adapter has no 32-lane waves (4..4)". The native module declares
  `WaveSize=32`; WARP offers 4-lane waves only. The skip is not evidence for the fixture.
- `ctest --preset dev --no-tests=error -R ^native_ -j 1`: same result as before the change apart from the two new tests
  (one known failure, `native_wave_request_hardware`, #2915, addressed by #2928).
- Revert control: with the heap refusal restored for every contract, `record` for selection 0 exits 4 with "direct
  resource-heap load requires the selected GPU slot and its view type".

## Limits

- Only raw buffer heap reads are translated; other view classes are refused with a named diagnostic.
- The selected slot's index is per-lane VGPR data in general; reads stay inside the raw buffer view, which returns 0
  out of bounds. No static index bound is checked.
- Replay regenerates the slot contents deterministically from the slot index; `.views` captures type, stride and size,
  not contents.
- In the direct DXIL path a stride read of a GPU-selected heap slot is refused. The HLSL path's `heap_stride_srv`
  (`src/gfx1013_compute_native.cpp`, used by `tests/native_compute_grid.cpp`) is unchanged.
- The captured `select` must be the slot index the dispatch addresses; producing it from a title capture is outside this
  fixture.
