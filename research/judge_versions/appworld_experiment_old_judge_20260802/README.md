# Frozen AppWorld experiment judge

This manifest freezes the active seven-type judge used for the
`batch_C_teammate` AppWorld run started on 2026-08-02 at repository commit
`58ae2f500f98`.

The files themselves remain in their normal active package paths. The Stage-2
launcher verifies `SHA256SUMS` immediately before starting; any drift stops the
run. The inactive `action_request` draft is stored separately in
`../action_request_v2_draft_20260802/` and is never imported by this experiment.

