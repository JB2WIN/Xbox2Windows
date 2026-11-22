# Work claims (handshake between Claude workstations)

Before working on a branch, PR or issue: `git fetch origin coordination`, read this file, add your line, commit and
`git push origin coordination` **without force**. A claim only counts once that push has succeeded. If the push is
rejected, someone else changed the list: fetch, re-read, then decide. Remove your line when the work is merged or
abandoned. Never edit another machine's line. Only branch names and times go here, nothing else.

| Item (branch / PR / issue) | Machine | Since (UTC) | Note |
|---|---|---|---|
| shader/add-sub-nc (pixel_aot v_add/sub/subrev_nc forms) | PC-Joshua | 2026-11-22 14:06 | PR #582 |
| cpu/exe-start-termination (#281 follow-up) | PC-Joshua | 2026-11-22 14:28 | PR #589 |
| shader/madak-madmk (pixel_aot v_madak/madmk_f32) | PC-Joshua | 2026-11-22 14:49 | PR #595 |
| shader/s-bfm (pixel_aot s_bfm_b32/b64) | PC-Joshua | 2026-11-22 14:51 | issue #596 |
