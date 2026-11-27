# Work claims (handshake between Claude workstations)

Before working on a branch, PR or issue: `git fetch origin coordination`, read this file, add your line, commit and
`git push origin coordination` **without force**. A claim only counts once that push has succeeded. If the push is
rejected, someone else changed the list: fetch, re-read, then decide. Remove your line when the work is merged or
abandoned. Never edit another machine's line. Only branch names and times go here, nothing else.

| Item (branch / PR / issue) | Machine | Since (UTC) | Note |
|---|---|---|---|
| shader/int16-vop3 (pixel_aot 16-bit integer VOP3) | PC-Joshua | 2026-11-22 18:42 | issue #669, waiting for semantics answer |
| issue #1606 (v_cvt_f32_f64 in pixel_aot) | PC-Joshua | 2026-11-24 14:53 | scope question open |
| issue #1786 (s_call_b64, s_subvector_loop_* in pixel_aot) | PC-Joshua | 2026-11-24 18:38 | scope question open |
| startup/gfx2hlsl-bfm-b64 (s_bfm_b64 in gfx2hlsl, #1723) | PC-Joshua | 2026-11-24 22:45 | claimed in #1723 |
| startup/gfx2hlsl-cmp-class-f16 (v_cmp_class_f16 in gfx2hlsl, #1723) | PC-Joshua | 2026-11-24 22:58 | claimed in #1723 |
| startup/gfx2hlsl-subrev-dpp (v_subrev_f32 DPP in gfx2hlsl, #1996 B) | PC-Joshua | 2026-11-24 23:04 | claimed in #1996 |
| startup/gfx2hlsl-sopk-addk-mulk (s_addk_i32, s_mulk_i32 in gfx2hlsl, #1723) | PC-Joshua | 2026-11-25 00:08 | claimed in #1723 |
| startup/release-retained-textures (#2379 deferred release) | PC-Joshua | 2026-11-25 14:23 | local prototype, issue opened |
| startup/compute-manifest-retry (compute manifest retry under draw_lock) | PC-Joshua | 2026-11-26 20:39 | local diagnosis, fix in prep |
| tests/native-wave-request-refusal (cpp-migration wave_request refusal message) | PC-Joshua | 2026-11-26 21:36 | fix in prep |
| native/global-srv-heap-replay (#2908 capture+replay fixture) | PC-Joshua | 2026-11-26 21:53 | taken over from tedin7 #2912 |
| native/compute-heap-view-contract (#3023 heap views on in-runtime compute) | PC-Joshua | 2026-11-27 06:16 | design |
| native/heap-typed-load (#3023 stage 2 typed heap loads) | PC-Joshua | 2026-11-27 08:28 | probing, builds on #3025 |
| native/heap-typed-dword-load (#3023 typed heap loads) | PC-Joshua | 2026-11-27 09:56 | design round 2 |
