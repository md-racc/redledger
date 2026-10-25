import { describe, expect, it } from "vitest";
import { dashboardFor, hostName } from "./host";

describe("dashboardFor", () => {
  it("maps the team hosts at / to their dashboards", () => {
    expect(dashboardFor("red.redledger.us", "/")).toBe("/backstage/red");
    expect(dashboardFor("blue.redledger.us", "/")).toBe("/backstage/blue");
    expect(dashboardFor("RED.RedLedger.US", "/")).toBe("/backstage/red");
  });

  it("works on localhost with a port, for trying it out", () => {
    expect(dashboardFor("red.localhost:3110", "/")).toBe("/backstage/red");
    expect(dashboardFor("blue.localhost:3110", "/")).toBe("/backstage/blue");
    expect(dashboardFor("blue.localhost.", "/")).toBe("/backstage/blue");
  });

  it("takes the first entry of a forwarded host list", () => {
    expect(dashboardFor("blue.redledger.us, proxy.internal", "/")).toBe("/backstage/blue");
  });

  it("passes every other path through", () => {
    for (const path of ["/_next/static/chunks/a.js", "/api/bf/health", "/api/ws", "/admin", "/report/ep_1", "/backstage/blue", "/backstage", "/ops", "/x/"]) {
      expect(dashboardFor("red.redledger.us", path)).toBeNull();
    }
  });

  it("leaves other hosts alone", () => {
    for (const host of ["redledger.us", "app.redledger.us", "localhost:3000", "red", "red.", "redteam.redledger.us", "green.redledger.us", "my.red.redledger.us", "[::1]:3000", "", null, undefined]) {
      expect(dashboardFor(host, "/")).toBeNull();
    }
  });
});

describe("hostName", () => {
  it("drops the port and lower-cases", () => {
    expect(hostName("Red.Localhost:3110")).toBe("red.localhost");
    expect(hostName("[::1]:3000")).toBe("[::1]");
  });
});
