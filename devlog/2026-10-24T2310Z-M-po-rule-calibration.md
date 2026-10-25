# 2026-10-24T2310Z — M — Calibrate no_po_from_po_vendor; baseline retirement (#133)

blue: `no_po_from_po_vendor` now requires >=5 paid invoices, all with POs, and an amount
beyond every prior paid amount (was: >=3 paid, all-PO): prod lineage ln_f6e3b2a3a6d0 showed
28 fires, all on legit ad-hoc invoices. Reflection now retires a baseline rule for the
lineage when a generation review shows on_legit >= 3 with on_red == 0, recorded as
`retired_baseline` playbook data; the gate skips retired baseline rules for later
generations via `Playbooks.retired` (same cached, version-scoped snapshot; an unavailable
version retires nothing). The reflect rationale names retired rules so the evolution report
shows the learning. 400 blue tests green.
