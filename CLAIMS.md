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
| startup/compute-typed-buffer-store (C200-03, compute buffer_store_format) | PC-Joshua | 2026-11-26 01:37 | claimed for #2618 C200-03; fixture first |
| startup/gfx2hlsl-bfm-b64 (#2007, merge main via Ybucaille) | PC-Joshua | 2026-11-26 04:40 | verify a73b60f8 on Windows, then ff push |
