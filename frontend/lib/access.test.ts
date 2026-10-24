import { SignJWT, exportJWK, generateKeyPair, type JWK } from "jose";
import { beforeAll, describe, expect, it, vi } from "vitest";
import {
  ACCESS_HEADER,
  accessSettings,
  accessToken,
  checkAccess,
  isJwksFailure,
  remoteJwks,
  verifyAccessToken,
  type AccessConfig,
  type FetchLike,
} from "./access";

const TEAM = "team.cloudflareaccess.com";
const AUD = "aud-tag-1234";
const ENV = { CF_ACCESS_TEAM_DOMAIN: TEAM, CF_ACCESS_AUD: AUD };
const CONFIG: AccessConfig = {
  teamDomain: TEAM,
  audience: AUD,
  issuer: `https://${TEAM}`,
  certsUrl: `https://${TEAM}/cdn-cgi/access/certs`,
};
const KID = "kid-1";

type Key = Awaited<ReturnType<typeof generateKeyPair>>["privateKey"];
let signingKey: Key;
let otherKey: Key;
let jwks: { keys: JWK[] };

beforeAll(async () => {
  const pair = await generateKeyPair("RS256", { extractable: true });
  signingKey = pair.privateKey;
  otherKey = (await generateKeyPair("RS256")).privateKey;
  jwks = { keys: [{ ...(await exportJWK(pair.publicKey)), kid: KID, alg: "RS256", use: "sig" }] };
});

/** A local JWKS endpoint: what Cloudflare serves at /cdn-cgi/access/certs. */
function mockFetch(): FetchLike & ReturnType<typeof vi.fn> {
  return vi.fn(async () => Response.json(jwks)) as unknown as FetchLike & ReturnType<typeof vi.fn>;
}

interface Claims {
  aud?: string | string[];
  iss?: string;
  exp?: number | null;
  nbf?: number;
  key?: Key;
}

async function token(c: Claims = {}): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const jwt = new SignJWT({ email: "op@example.com", type: "app" })
    .setProtectedHeader({ alg: "RS256", kid: KID })
    .setIssuer(c.iss ?? CONFIG.issuer)
    .setAudience(c.aud ?? [AUD])
    .setIssuedAt(now)
    .setNotBefore(c.nbf ?? now)
    .setSubject("user-1");
  if (c.exp !== null) jwt.setExpirationTime(c.exp ?? now + 3600);
  return jwt.sign(c.key ?? signingKey);
}

const verify = async (t: string | null) => verifyAccessToken(t, CONFIG, remoteJwks(CONFIG.certsUrl, mockFetch()));

describe("verifyAccessToken", () => {
  it("accepts a valid token and fetches the team JWKS", async () => {
    const f = mockFetch();
    const res = await verifyAccessToken(await token(), CONFIG, remoteJwks(CONFIG.certsUrl, f));
    expect(res).toEqual({ ok: true });
    expect(f).toHaveBeenCalledTimes(1);
    expect(String(f.mock.calls[0]![0])).toBe(`https://${TEAM}/cdn-cgi/access/certs`);
  });

  it("accepts aud as a string or an array containing the AUD", async () => {
    expect(await verify(await token({ aud: AUD }))).toEqual({ ok: true });
    expect(await verify(await token({ aud: ["other", AUD] }))).toEqual({ ok: true });
  });

  it("tolerates small clock skew", async () => {
    const now = Math.floor(Date.now() / 1000);
    expect(await verify(await token({ exp: now - 30 }))).toEqual({ ok: true });
    expect(await verify(await token({ nbf: now + 30 }))).toEqual({ ok: true });
  });

  it("rejects a missing token", async () => {
    expect(await verify(null)).toEqual({ ok: false, reason: "missing" });
    expect(await verify("")).toEqual({ ok: false, reason: "missing" });
  });

  it("rejects the wrong audience", async () => {
    expect(await verify(await token({ aud: "someone-elses-app" }))).toMatchObject({
      ok: false,
      reason: "ERR_JWT_CLAIM_VALIDATION_FAILED",
    });
  });

  it("rejects the wrong issuer", async () => {
    expect(await verify(await token({ iss: "https://evil.cloudflareaccess.com" }))).toMatchObject({
      ok: false,
      reason: "ERR_JWT_CLAIM_VALIDATION_FAILED",
    });
  });

  it("rejects an expired token, a not-yet-valid token, and a token without exp", async () => {
    const now = Math.floor(Date.now() / 1000);
    expect(await verify(await token({ exp: now - 600 }))).toMatchObject({ ok: false, reason: "ERR_JWT_EXPIRED" });
    expect(await verify(await token({ nbf: now + 600 }))).toMatchObject({ ok: false });
    expect(await verify(await token({ exp: null }))).toMatchObject({ ok: false });
  });

  it("rejects a bad signature", async () => {
    expect(await verify(await token({ key: otherKey }))).toMatchObject({
      ok: false,
      reason: "ERR_JWS_SIGNATURE_VERIFICATION_FAILED",
    });
    const [h, p, s] = (await token()).split(".");
    const tampered = `${h}.${p}.${s!.slice(0, -4)}AAAA`;
    expect(await verify(tampered)).toMatchObject({ ok: false });
  });

  it("rejects garbage, alg=none and HS256", async () => {
    expect(await verify("not-a-jwt")).toMatchObject({ ok: false });
    const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
    const now = Math.floor(Date.now() / 1000);
    const body = b64({ aud: [AUD], iss: CONFIG.issuer, exp: now + 3600 });
    expect(await verify(`${b64({ alg: "none" })}.${body}.`)).toMatchObject({ ok: false });
    const hs = await new SignJWT({}).setProtectedHeader({ alg: "HS256", kid: KID }).setAudience(AUD)
      .setIssuer(CONFIG.issuer).setExpirationTime("1h").sign(new TextEncoder().encode("x".repeat(32)));
    expect(await verify(hs)).toMatchObject({ ok: false, reason: "ERR_JOSE_ALG_NOT_ALLOWED" });
  });

  it("fails closed when the JWKS cannot be fetched", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as FetchLike;
    const res = await verifyAccessToken(await token(), CONFIG, remoteJwks(CONFIG.certsUrl, down));
    expect(res).toEqual({ ok: false, reason: "jwks_unavailable" });
    expect(isJwksFailure("jwks_unavailable")).toBe(true);
    const bad = vi.fn(async () => new Response("nope", { status: 500 })) as unknown as FetchLike;
    const res2 = await verifyAccessToken(await token(), CONFIG, remoteJwks(CONFIG.certsUrl, bad));
    expect(res2.ok).toBe(false);
    expect(isJwksFailure((res2 as { reason: string }).reason)).toBe(true);
    expect(isJwksFailure("ERR_JWS_SIGNATURE_VERIFICATION_FAILED")).toBe(false);
  });
});

describe("accessToken", () => {
  it("prefers the Cf-Access-Jwt-Assertion header", () => {
    const h = new Headers({ [ACCESS_HEADER]: "hdr", cookie: "CF_Authorization=ck" });
    expect(accessToken(h)).toBe("hdr");
  });
  it("falls back to the CF_Authorization cookie", () => {
    expect(accessToken(new Headers({ cookie: "a=1; CF_Authorization=ck; b=2" }))).toBe("ck");
    expect(accessToken(new Headers({ cookie: "XCF_Authorization=ck" }))).toBeNull();
    expect(accessToken(new Headers())).toBeNull();
  });
});

describe("accessSettings", () => {
  it("is off when either var is unset or blank", () => {
    expect(accessSettings({})).toEqual({ mode: "off", partial: false });
    expect(accessSettings({ CF_ACCESS_TEAM_DOMAIN: TEAM })).toEqual({ mode: "off", partial: true });
    expect(accessSettings({ CF_ACCESS_AUD: AUD, CF_ACCESS_TEAM_DOMAIN: " " })).toEqual({ mode: "off", partial: true });
  });
  it("derives issuer and certs URL, tolerating a pasted scheme/slash", () => {
    expect(accessSettings({ CF_ACCESS_TEAM_DOMAIN: `https://${TEAM}/`, CF_ACCESS_AUD: AUD })).toEqual({
      mode: "on",
      config: CONFIG,
    });
  });
  it("fails closed on a team domain that is not a hostname", () => {
    expect(accessSettings({ CF_ACCESS_TEAM_DOMAIN: "evil.com/x?", CF_ACCESS_AUD: AUD })).toEqual({ mode: "invalid" });
    expect(accessSettings({ CF_ACCESS_TEAM_DOMAIN: "localhost", CF_ACCESS_AUD: AUD })).toEqual({ mode: "invalid" });
  });
});

describe("checkAccess", () => {
  it("bypasses when the vars are unset", async () => {
    expect(await checkAccess(new Headers(), {})).toEqual({ ok: true, bypass: true, partial: false });
  });
  it("requires a valid token when configured", async () => {
    const keys = remoteJwks(CONFIG.certsUrl, mockFetch());
    expect(await checkAccess(new Headers(), ENV, keys)).toEqual({ ok: false, reason: "missing" });
    const good = new Headers({ [ACCESS_HEADER]: await token() });
    expect(await checkAccess(good, ENV, keys)).toEqual({ ok: true });
    const viaCookie = new Headers({ cookie: `CF_Authorization=${await token()}` });
    expect(await checkAccess(viaCookie, ENV, keys)).toEqual({ ok: true });
    const wrongAud = new Headers({ [ACCESS_HEADER]: await token({ aud: "nope" }) });
    expect((await checkAccess(wrongAud, ENV, keys)).ok).toBe(false);
  });
  it("rejects everything when misconfigured", async () => {
    const res = await checkAccess(new Headers({ [ACCESS_HEADER]: "x" }), { ...ENV, CF_ACCESS_TEAM_DOMAIN: "a b" });
    expect(res).toEqual({ ok: false, reason: "misconfigured" });
  });
});
