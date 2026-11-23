# Work claims (handshake between Claude workstations)

Before working on a branch, PR or issue: `git fetch origin coordination`, read this file, add your line, commit and
`git push origin coordination` **without force**. A claim only counts once that push has succeeded. If the push is
rejected, someone else changed the list: fetch, re-read, then decide. Remove your line when the work is merged or
abandoned. Never edit another machine's line. Only branch names and times go here, nothing else.

| Item (branch / PR / issue) | Machine | Since (UTC) | Note |
|---|---|---|---|
| shader/int16-vop3 (pixel_aot 16-bit integer VOP3) | PC-Joshua | 2026-11-22 18:42 | issue #669, waiting for semantics answer |
| shader/int16-vop3 (16-bit integer VOP3, #669) | PC-Joshua | 2026-11-22 19:33 | design |
| shader/plain-bitscan (plain bfrev/ffbh/ffbl/xnor) | PC-Joshua | 2026-11-22 23:55 | design |
| shader/s-brev-b32 (s_brev_b32) | PC-Joshua | 2026-11-23 00:59 | impl |
