## 2026-10-24 — M — blue: threshold_split gate rule

New baseline rule `threshold_split` closes the split-evasion gap: same-day,
same-category expenses from one employee are aggregated from the gate context's
`employee_expense_history`; a combined total at/over the approval threshold blocks,
and three or more parts within five percent under it escalate to review.
