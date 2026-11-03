# QualityOps AI — 3-minute demo

Use one synthetic case throughout. Prepare its intake, investigation and approval stages before recording. Record clips separately if needed, then trim loading and navigation. Use English captions or narration over the existing UI.

| Time | Screen and action | English caption |
|---|---|---|
| 0:00–0:15 | Show the customer complaint, inspection sheet and case overview. | One manufacturing quality case, from complaint to approved report. |
| 0:15–0:40 | Upload the synthetic customer PDF or DOCX. Show extracted part, LOT and quantity. Open one source location and link the intake to the case. | Muse Spark extracts customer-reported facts with source references. |
| 0:40–1:10 | Upload an unregistered inspection XLSX. Show the mapping proposal, inspect its source cell and confirm it. Upload a second file with the same structure and different values. Show the reused mapping and the second file's own values. | Verify the mapping once. Reuse it on new inspection data. |
| 1:10–1:45 | Open the investigation. Show one customer claim alongside internal evidence, one server calculation with its input rows, and one applicable precedent or warning. | Compare reported claims with checked evidence and trace every calculation. |
| 1:45–2:20 | Cut to a prepared later stage of the same case. Show the D0 decision and D1–D8 timeline. Pause on D4 cause evidence and D6 effectiveness verification. | Follow the case from triage to verified corrective action. |
| 2:20–2:45 | Open Requests / Responses / Responsibility and the review queue. Show the action owner, executor and verifier. Open the pending decision and confirm the evidence and version before recording the authorized demo approval. | See who acted, who verified, and who approved which version. |
| 2:45–3:00 | Open the approved 8D report and download it. Show the output and approval history. Use a customer DOCX export only after rehearsing its actual path. | Export the approved 8D report with its decision history. |

## Rehearsal

- Use authorized demo accounts and synthetic files. Note the case ID, the two XLSX files, the reviewer and the report to export.
- Check the actual model response and second upload before recording. If mapping is unavailable, show XLSX preview, source cells and quantity reconciliation instead.
- Verify the review and export on screen. If a case cannot be approved in the recording session, show its actual status or use a prepared approved snapshot of the same synthetic case.
- Use the refusal explanation or approved operating-limit proposal as an optional insert only if it fits. Capture the actual result and keep the final edit within 3:00.
- Code reviewed at `262eb2540bc250648cd8591e8e858cbc232fc6b5`. [CI passed](https://github.com/homilpat/meta_Hackathon/actions/runs/41675443654). Browser rehearsal is a separate check.
