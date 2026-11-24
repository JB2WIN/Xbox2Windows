# Work claims (handshake between Claude workstations)

Before working on a branch, PR or issue: `git fetch origin coordination`, read this file, add your line, commit and
`git push origin coordination` **without force**. A claim only counts once that push has succeeded. If the push is
rejected, someone else changed the list: fetch, re-read, then decide. Remove your line when the work is merged or
abandoned. Never edit another machine's line. Only branch names and times go here, nothing else.

| Item (branch / PR / issue) | Machine | Since (UTC) | Note |
|---|---|---|---|
| shader/int16-vop3 (pixel_aot 16-bit integer VOP3) | PC-Joshua | 2026-11-22 18:42 | issue #669, waiting for semantics answer |
| issue #1606 (v_cvt_f32_f64 in pixel_aot) | PC-Joshua | 2026-11-24 14:53 | scope question open |
| shader/sopk-setreg (s_setreg_b32, s_getreg_b32 in pixel_aot) | PC-Joshua | 2026-11-24 17:44 | SOPK gaps 24.11. |
