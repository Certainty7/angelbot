# Secret scan record

Date: 2026-11-20. Scope: the working tree and every commit reachable from any ref on the
recovery branch (`git rev-list --all`, 46 commits, 276 tracked files).

## Method

`gitleaks` and `trufflehog` are not installed on this machine, so a targeted scanner was used
instead. For each commit and for the working tree, `git grep -I -l` matched these categories
without printing the matched text:

| Category | Pattern shape |
|---|---|
| Discord bot token | `id.timestamp.hmac` three-part token |
| Google API key | `AIza` + 35 characters |
| GitHub token / PAT | `ghp_/gho_/ghu_/ghs_/ghr_` and `github_pat_` |
| AWS access key id | `AKIA` + 16 uppercase/digits |
| Slack token | `xox[baprs]-` |
| Private key | `-----BEGIN ... PRIVATE KEY-----` |
| Discord webhook | `discord(app).com/api/webhooks/<id>/<token>` |

Only file paths and categories were logged; no candidate value was printed.

## Result

| Category | Matches |
|---|---|
| Discord bot token | 0 |
| Google API key | 0 |
| GitHub token / PAT | 0 |
| Slack token | 0 |
| Private key | 0 |
| Discord webhook | 0 |
| AWS access key id | 92 path hits, **one distinct value**, verified to be `AKIA` + 16 `A` characters |

The single AWS-shaped value is a placeholder inside two committed Lighthouse JSON reports
(`docs/QA/lighthouse/prod-en.report.json`, `prod-home-2.report.json`). It is not a valid key
(the suffix is a run of `A`), it appears in generated audit output rather than code, and it
grants nothing. It is recorded here rather than "fixed" because editing generated audit
artefacts would falsify them.

## Limitations

- This is a pattern scan, not an entropy scan. A credential in an unusual format would not be
  caught.
- `.env` files are not tracked (`git ls-files` confirms), so a real deployment secret was never
  in scope for this scan.
- No value is asserted to be absent from any private service: only from this repository's
  history and working tree.

## Conclusion

No real credential is present in the repository or its history. The only match is a documented
placeholder. Nothing in the recovery work added a secret: the new files are documentation, tests
and code, and every test credential is an obvious fixture (`test-key`, `42`).
