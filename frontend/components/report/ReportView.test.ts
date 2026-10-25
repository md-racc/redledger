// Download JSON and Print are for the final assessment only.
import { describe, expect, it } from "vitest";
import { reportExportable } from "./ReportView";

describe("report actions", () => {
  it("are enabled only once the report is final", () => {
    expect(reportExportable({ kind: "ready", report: { final: true } })).toBe(true);
    expect(reportExportable({ kind: "ready", report: { final: false } })).toBe(false); // an admin's draft of a running episode
    expect(reportExportable({ kind: "pending" })).toBe(false); // a viewer: "Available when the run ends"
    expect(reportExportable({ kind: "loading" })).toBe(false);
    expect(reportExportable({ kind: "error" })).toBe(false);
  });
});
