// `next dev` against the fake battlefield: the whole live path (proxy, ws ticket, socket, controls) with no Docker.
//   node tools/dev-live.mjs [port]     frontend on :3000 (or the port you pass), fake battlefield on :8000
// Owner: Dev R.
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const bfPort = process.env.BF_PORT ?? "8000";
const env = {
  ...process.env,
  BF_PORT: bfPort,
  BATTLEFIELD_URL: `http://127.0.0.1:${bfPort}`,
  OPERATOR_TOKEN: process.env.OPERATOR_TOKEN ?? "change-me-operator",
  NEXT_PUBLIC_WS_URL: `ws://127.0.0.1:${bfPort}`,
  NEXT_PUBLIC_MOCK: "false",
};

const kids = [
  spawn(process.execPath, [join(here, "fake-battlefield.mjs")], { env, stdio: "inherit" }),
  spawn(process.execPath, [join(root, "node_modules/next/dist/bin/next"), "dev", root, "-p", process.argv[2] ?? process.env.FRONTEND_PORT ?? "3000"], { env, stdio: "inherit" }),
];
const stop = () => kids.forEach((k) => k.kill());
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
kids.forEach((k) => k.on("exit", stop));
