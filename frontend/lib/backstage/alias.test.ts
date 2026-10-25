import { describe, expect, it } from "vitest";
import { doorTeam, doorUrl } from "./alias";

describe("which host is a door", () => {
  it("knows red. and blue. in front of any domain, with or without a port", () => {
    expect(doorTeam("red.redledger.us")).toBe("red");
    expect(doorTeam("blue.redledger.us")).toBe("blue");
    expect(doorTeam("RED.RedLedger.US:443")).toBe("red");
    expect(doorTeam("blue.localhost:3104")).toBe("blue");
    expect(doorTeam("red.app.example.com")).toBe("red");
  });

  it("is not fooled by lookalikes, the plain site, or a machine called red", () => {
    expect(doorTeam("app.redledger.us")).toBeNull();
    expect(doorTeam("redledger.us")).toBeNull();
    expect(doorTeam("red")).toBeNull();
    expect(doorTeam("redhat.com")).toBeNull();
    expect(doorTeam("notred.example.com")).toBeNull();
    expect(doorTeam("green.redledger.us")).toBeNull();
    expect(doorTeam("")).toBeNull();
    expect(doorTeam(null)).toBeNull();
    expect(doorTeam(undefined)).toBeNull();
  });
});

describe("where an admin opens a door from", () => {
  it("swaps app. for the team", () => {
    expect(doorUrl({ protocol: "https:", host: "app.redledger.us" }, "red")).toBe("https://red.redledger.us/");
    expect(doorUrl({ protocol: "https:", host: "www.redledger.us" }, "blue")).toBe("https://blue.redledger.us/");
    expect(doorUrl({ protocol: "https:", host: "redledger.us" }, "blue")).toBe("https://blue.redledger.us/");
  });

  it("works on localhost, keeping the port", () => {
    expect(doorUrl({ protocol: "http:", host: "localhost:3104" }, "red")).toBe("http://red.localhost:3104/");
  });

  it("goes from one door to the other", () => {
    expect(doorUrl({ protocol: "https:", host: "red.redledger.us" }, "blue")).toBe("https://blue.redledger.us/");
    expect(doorUrl({ protocol: "http:", host: "red.localhost:3104" }, "blue")).toBe("http://blue.localhost:3104/");
  });

  it("falls back to the plain path where a subdomain is impossible", () => {
    expect(doorUrl({ protocol: "http:", host: "192.168.1.20:3000" }, "red")).toBe("/backstage/red");
    expect(doorUrl({ protocol: "http:", host: "[::1]:3000" }, "blue")).toBe("/backstage/blue");
    expect(doorUrl({ protocol: "http:", host: "devbox:3000" }, "red")).toBe("/backstage/red");
  });
});
