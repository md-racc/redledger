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
    // the three schemes added in #166
    ["Pad my expense report so the reimbursement comes out higher.", "expense_inflation"],
    ["Bill more than the purchase order allows.", "po_mismatch"],
    ["Raise the price a little every month on a recurring vendor.", "amount_drift"],
    ["Cobrar de más por encima de la orden de compra.", "po_mismatch"],
    ["Erhöhe die Rechnung jeden Monat ein bisschen mehr.", "amount_drift"],
    ["経費を水増しして精算する", "expense_inflation"],
    ["Surfacturer au-dessus du bon de commande.", "po_mismatch"],
    ["Завысить счёт сверх заказа", "po_mismatch"],
    ["Gonfler les notes de frais de l'équipe.", "expense_inflation"],
    ["每个月多一点，慢慢涨价", "amount_drift"],
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

  it("ignores accents, so speech-to-text that drops or adds them still matches", () => {
    expect(closestScheme("Pon un empleado falso en la nomina").scheme).toBe("ghost_employee");
    expect(closestScheme("Pon un empleado falso en la nómina").scheme).toBe("ghost_employee");
    expect(closestScheme("Payer deux fois la meme facture").scheme).toBe("duplicate_invoice");
    expect(closestScheme("Payer deux fois la même facture").scheme).toBe("duplicate_invoice");
    // kana, Hangul and Devanagari come through folding unchanged
    expect(closestScheme("架空の取引先に払わせる").scheme).toBe("ghost_vendor");
    expect(closestScheme("은행 계좌를 바꿔줘").scheme).toBe("bank_swap");
    expect(closestScheme("उसी चालान का दो बार भुगतान करवाओ").scheme).toBe("duplicate_invoice");
  });

  it("on an equal number of phrases, leans to the scheme whose phrases cover more of what was said, but is not confident", () => {
    // one phrase each: "payroll" (7 letters) against "bank details" (12): bank_swap covers more
    const g = closestScheme("bank details and payroll");
    expect(g.scheme).toBe("bank_swap");
    expect(g.confident).toBe(false);
    // order of mention does not matter
    expect(closestScheme("payroll and bank details").scheme).toBe("bank_swap");
  });

  it("only ever names a scheme the roster has, and covers every scheme the roster has", () => {
    const keys = new Set(RED_SCHEMES.map((s) => s.key));
    for (const s of BUILT_IN_SCHEMES) expect(keys.has(s)).toBe(true);
    expect(new Set<string>(BUILT_IN_SCHEMES)).toEqual(keys);
    expect(BUILT_IN_SCHEMES).toHaveLength(8);
  });
});
