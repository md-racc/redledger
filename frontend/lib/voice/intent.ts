// Which of the five built-in schemes is closest to what was said? Owner: Dev R.
//
// The spoken scheme goes to red in the judge's own words (POST /inputs, in whatever language they spoke). Red is an LLM agent and
// reads any language, but a battlefield episode can only be *forced* to run a scheme from the catalog. So there is always a closest
// built-in scheme to run, and this picks it: a plain keyword lexicon in the languages a judge is likely to speak. It is deliberately
// simple and visible (the UI shows its pick and lets the judge change it); it is not a translator, and an unfamiliar phrasing in
// an unfamiliar language falls back to "no clear match".
//
// Only the five schemes red can actually run today (red/schemes/__init__.py). The other three in the arena's roster are not built.

export type BuiltInScheme = "ghost_vendor" | "bank_swap" | "duplicate_invoice" | "threshold_split" | "ghost_employee";

const LEXICON: Record<BuiltInScheme, string[]> = {
  ghost_vendor: [
    // en
    "ghost vendor", "fake vendor", "fictitious vendor", "phantom vendor", "dummy vendor", "made-up vendor", "made up vendor", "shell company", "shell vendor", "nonexistent vendor", "non-existent vendor", "fake supplier", "fake company",
    // es pt fr it de nl
    "proveedor falso", "proveedor fantasma", "proveedor ficticio", "empresa fantasma", "empresa falsa", "fornecedor falso", "fornecedor fantasma", "fornecedor fictício", "empresa de fachada",
    "faux fournisseur", "fournisseur fictif", "fournisseur fantôme", "société écran", "fausse société", "fornitore fittizio", "fornitore fantasma", "società di comodo", "società fittizia",
    "scheinfirma", "fiktiver lieferant", "erfundener lieferant", "briefkastenfirma", "fiktive firma", "nepleverancier", "nep-leverancier",
    // zh ja ko
    "虚假供应商", "假供应商", "幽灵供应商", "虚构供应商", "皮包公司", "空壳公司", "假公司", "架空の取引先", "架空の仕入先", "ダミー会社", "ペーパーカンパニー", "架空会社", "유령 업체", "가짜 업체", "가짜 거래처", "유령 회사",
    // ar hi ru tr
    "مورد وهمي", "مورد مزيف", "شركة وهمية", "फर्जी विक्रेता", "नकली विक्रेता", "फर्जी कंपनी", "фиктивный поставщик", "фирма-однодневка", "фиктивная компания", "hayalet satıcı", "sahte tedarikçi", "paravan şirket",
  ],
  bank_swap: [
    "bank account", "bank details", "banking details", "change the bank", "swap the bank", "routing number", "account number", "redirect the payment", "redirect payment", "reroute the payment", "payment details", "wire instructions",
    "cuenta bancaria", "datos bancarios", "cambiar la cuenta", "desviar el pago", "conta bancária", "dados bancários", "desviar o pagamento", "trocar a conta",
    "compte bancaire", "coordonnées bancaires", "détourner le paiement", "changer le rib", "conto bancario", "coordinate bancarie", "cambiare l'iban", "deviare il pagamento",
    "bankverbindung", "kontodaten", "bankdaten", "iban ändern", "kontonummer ändern", "zahlung umleiten", "bankrekening", "rekeningnummer",
    "银行账户", "银行账号", "银行卡号", "更改账户", "更换账户", "收款账户", "换银行", "转移付款", "銀行口座", "口座を変更", "口座を変え", "振込先", "은행 계좌", "계좌 변경", "계좌번호",
    "حساب مصرفي", "حساب بنكي", "تغيير الحساب", "बैंक खाता", "बैंक विवरण", "खाता बदल", "банковские реквизиты", "банковский счет", "банковский счёт", "реквизиты", "banka hesabı", "iban değiş",
  ],
  duplicate_invoice: [
    "duplicate invoice", "duplicate", "same invoice", "pay twice", "paid twice", "pay it twice", "resubmit", "re-submit", "submit it again", "double bill", "double pay", "billed twice",
    "factura duplicada", "duplicar la factura", "pagar dos veces", "misma factura", "fatura duplicada", "pagar duas vezes", "mesma fatura", "cobrar duas vezes",
    "facture en double", "doublon", "payer deux fois", "même facture", "fattura duplicata", "pagare due volte", "stessa fattura", "doppia fattura",
    "doppelte rechnung", "rechnung doppelt", "zweimal bezahlen", "doppelt bezahlen", "dublette", "dubbele factuur", "twee keer betalen",
    "重复发票", "重复付款", "重复报销", "重复开票", "同一张发票", "二重請求", "重複請求", "同じ請求書", "二重払い", "중복 청구", "이중 지불", "중복 송장", "같은 청구서",
    "فاتورة مكررة", "دفع مرتين", "दोहरा चालान", "दो बार भुगतान", "डुप्लिकेट", "дубликат счета", "дубликат счёта", "оплатить дважды", "повторный счет", "mükerrer fatura", "çift ödeme",
  ],
  threshold_split: [
    "split", "under the limit", "below the limit", "under the threshold", "below the threshold", "approval limit", "approval threshold", "smaller invoices", "several invoices", "multiple invoices", "break it up", "break up", "structuring", "just under", "slip under",
    "dividir", "fraccionar", "por debajo del límite", "bajo el umbral", "varias facturas", "abaixo do limite", "várias faturas", "fracionar", "limite de aprovação",
    "fractionner", "diviser", "sous le seuil", "en dessous du seuil", "plusieurs factures", "frazionare", "sotto la soglia", "più fatture", "soglia di approvazione",
    "aufteilen", "stückeln", "unter dem schwellenwert", "unter der grenze", "unter dem limit", "mehrere rechnungen", "splitsen", "onder de limiet",
    "拆分", "分拆", "低于限额", "低于审批", "化整为零", "多张发票", "分成多", "分割", "限度額未満", "承認限度", "小分け", "分割して", "분할", "한도 미만", "쪼개", "나누어",
    "تقسيم", "أقل من الحد", "विभाजित", "सीमा से कम", "तोड़", "разбить", "раздробить", "ниже лимита", "ниже порога", "несколько счетов", "дробить", "bölmek", "limitin altında", "eşiğin altında",
  ],
  ghost_employee: [
    "ghost employee", "fake employee", "phantom employee", "fictitious employee", "made-up employee", "made up employee", "nonexistent employee", "fake worker", "payroll", "salary", "paycheck", "on the payroll",
    "empleado fantasma", "empleado falso", "nómina", "salario", "funcionário fantasma", "funcionário falso", "folha de pagamento", "salário",
    "employé fictif", "salarié fantôme", "faux employé", "fausse paie", "paie ", "dipendente fittizio", "dipendente fantasma", "busta paga", "stipendio",
    "fiktiver mitarbeiter", "scheinmitarbeiter", "gehaltsliste", "lohnliste", "gehalt", "geisterarbeiter", "spookwerknemer", "loonlijst",
    "虚构员工", "假员工", "幽灵员工", "虚假员工", "工资", "薪资", "薪水", "架空の従業員", "架空社員", "給与", "給料", "유령 직원", "가짜 직원", "급여", "월급",
    "موظف وهمي", "رواتب", "راتب", "काल्पनिक कर्मचारी", "फर्जी कर्मचारी", "वेतन", "фиктивный сотрудник", "подставной сотрудник", "зарплат", "hayalet çalışan", "sahte çalışan", "maaş",
  ],
};

export interface SchemeGuess {
  scheme: BuiltInScheme;
  /** how many phrases of that scheme were heard; 0 means nothing matched and `scheme` is only the default */
  hits: number;
  /** a clear single winner */
  confident: boolean;
}

const normalise = (s: string) => s.toLowerCase().normalize("NFC").replace(/[’‘]/g, "'").replace(/\s+/g, " ");

/** The built-in scheme closest to `text`, by phrases heard. Ties go to the earlier scheme in the catalog's order. */
export function closestScheme(text: string): SchemeGuess {
  const t = ` ${normalise(text)} `;
  let best: BuiltInScheme = "ghost_vendor";
  let bestHits = 0;
  let second = 0;
  for (const scheme of Object.keys(LEXICON) as BuiltInScheme[]) {
    let hits = 0;
    for (const phrase of LEXICON[scheme]) if (t.includes(phrase)) hits++;
    if (hits > bestHits) { second = bestHits; bestHits = hits; best = scheme; }
    else if (hits > second) second = hits;
  }
  return { scheme: best, hits: bestHits, confident: bestHits > 0 && bestHits > second };
}

export const BUILT_IN_SCHEMES = Object.keys(LEXICON) as BuiltInScheme[];
