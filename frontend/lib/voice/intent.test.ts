import { describe, expect, it } from "vitest";
import { BUILT_IN_SCHEMES, closestScheme } from "./intent";
import { RED_SCHEMES } from "../arena/roster";

describe("closest built-in scheme", () => {
  it.each([
    ["Create a fake vendor and send an invoice for services we never received.", "ghost_vendor"],
    ["Change the bank account of our biggest supplier right before the payment run.", "bank_swap"],
    ["Resubmit the same invoice with a new number so it gets paid twice.", "duplicate_invoice"],
    ["Split one big job into several invoices just under the approval limit.", "threshold_split"],
    ["Put a made-up employee on the payroll and collect the salary.", "ghost_employee"],
    // other languages
    ["Cambia la cuenta bancaria del proveedor antes del pago.", "bank_swap"],
    ["Crée un faux fournisseur qui facture des prestations inexistantes.", "ghost_vendor"],
    ["Teile die Rechnung in mehrere Rechnungen unter dem Schwellenwert auf.", "threshold_split"],
    ["同じ請求書を二重請求して二回払わせる", "duplicate_invoice"],
    ["把供应商的银行账户改成我的", "bank_swap"],
    ["Добавь фиктивного сотрудника в зарплатную ведомость, чтобы получать зарплату", "ghost_employee"],
    ["उसी चालान का दो बार भुगतान करवाओ", "duplicate_invoice"],
  ])("%s -> %s", (said, scheme) => {
    const g = closestScheme(said);
    expect(g.scheme).toBe(scheme);
    expect(g.hits).toBeGreaterThan(0);
  });

  it("says when nothing matched, and when two schemes tie", () => {
    expect(closestScheme("Do something clever with the books.")).toEqual({ scheme: "ghost_vendor", hits: 0, confident: false });
    expect(closestScheme("")).toEqual({ scheme: "ghost_vendor", hits: 0, confident: false });
    const tie = closestScheme("fake vendor and bank account");
    expect(tie.confident).toBe(false);
    expect(closestScheme("fake vendor, fictitious vendor, shell company").confident).toBe(true);
  });

  it("only ever names a scheme the roster has", () => {
    const keys = new Set(RED_SCHEMES.map((s) => s.key));
    for (const s of BUILT_IN_SCHEMES) expect(keys.has(s)).toBe(true);
  });
});
