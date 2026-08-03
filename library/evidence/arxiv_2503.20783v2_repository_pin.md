# Dr. GRPO: author-linked repository revision pin

## Record

- Paper stable ID: `arxiv_2503.20783v2`
- Repository stable ID: `github_sail-sg_understand-r1-zero_commit_dfca49dd460ee7cc8e4a5a162c876a7fd6993b87`
- Repository: `https://github.com/sail-sg/understand-r1-zero.git`
- Immutable revision: `dfca49dd460ee7cc8e4a5a162c876a7fd6993b87`
- Legacy abbreviated revision: `dfca49d`
- Retrieval date: 2026-07-16 (Asia/Shanghai)

## Primary evidence

Canonical captured `git ls-remote` output is retained beside this record at
`library/evidence/arxiv_2503.20783v2_github_ls_remote_2026-07-16.txt`, lines
1-2. It was copied without modification from the archived 2026-07-16
foundations-worker capture during the architecture migration and reports:

```text
dfca49dd460ee7cc8e4a5a162c876a7fd6993b87  HEAD
dfca49dd460ee7cc8e4a5a162c876a7fd6993b87  refs/heads/main
```

## Evidence-bounded conclusion

On the retrieval date, the official remote advertised the same full Git
object ID for `HEAD` and `refs/heads/main`. This record therefore pins the
repository reference as
`github:sail-sg/understand-r1-zero@dfca49dd460ee7cc8e4a5a162c876a7fd6993b87`,
rather than relying on the mutable branch name or truncated SHA. The paper to
repository association is carried forward from the parent-approved prior
scope record and is not independently proven by the remote-reference output.

## Non-claims and follow-up

This pin does not establish the license or SPDX identifier of the pinned tree,
the availability or identity of model/data assets, or whether the code
implements Dr. GRPO as described in the paper. Those claims require separate
evidence collected against this exact commit.
