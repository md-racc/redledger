// Which of red's eight built-in schemes is closest to what was said? Owner: Dev R.
//
// The spoken scheme goes to red in the judge's own words (POST /inputs, in whatever language they spoke). Red is an LLM agent and
// reads any language, but a battlefield episode can only be *forced* to run a scheme from the catalog (red's run_scheme takes
// catalog ids only). So there is always a closest built-in scheme to run, and this picks it: a plain keyword lexicon in the
// languages a judge is likely to speak. It is deliberately simple and visible (the UI shows its pick and lets the judge change
// it); it is not a translator, and an unfamiliar phrasing in an unfamiliar language falls back to "no clear match".
//
// The eight schemes in red/schemes/__init__.py, which are the eight in the arena's roster (lib/arena/roster.ts; a test keeps them
// the same).

export type BuiltInScheme =
  | "ghost_vendor"
  | "bank_swap"
  | "duplicate_invoice"
  | "threshold_split"
  | "ghost_employee"
  | "expense_inflation"
  | "po_mismatch"
  | "amount_drift";

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
  expense_inflation: [
    "inflate expense", "inflated expense", "padded expense", "pad the expense", "pad my expense", "pad expense", "expense report", "expense claim", "expenses", "reimburse", "overstate expense", "exaggerate expense", "fake receipt",
    "gastos inflados", "inflar los gastos", "inflar gastos", "reembolso", "informe de gastos", "gastos de viaje", "recibos falsos", "despesas infladas", "inflar despesas", "relatório de despesas",
    "notes de frais", "note de frais", "gonfler les frais", "frais gonflés", "remboursement", "faux justificatifs", "note spese", "nota spese", "gonfiare le spese", "rimborso spese", "spese gonfiate",
    "spesen", "spesenabrechnung", "aufgeblähte spesen", "reisekosten", "auslagen", "onkostendeclaratie", "declaraties opblazen", "onkosten",
    "报销", "虚报费用", "虚增费用", "夸大费用", "费用报销", "虚报开支", "费用虚高", "経費", "経費精算", "水増し", "立替", "경비", "비용 부풀", "경비 청구", "부풀려", "환급",
    "مصروفات", "تضخيم المصروفات", "تضخيم النفقات", "تعويض", "खर्च बढ़ा", "खर्चे बढ़ा", "प्रतिपूर्ति", "खर्च का दावा",
    "авансовый отчет", "завысить расходы", "завышенные расходы", "возмещение расходов", "командировочные", "masraf", "masrafları şişir", "şişirilmiş masraf", "gider pusulası",
  ],
  po_mismatch: [
    "purchase order", "over the po", "above the po", "above the purchase order", "exceeds the po", "exceed the po", "more than the purchase order", "po mismatch", "mismatched po", "overbill", "over-bill", "po amount",
    "orden de compra", "por encima de la orden", "sobrefacturar", "facturar de más", "ordem de compra", "pedido de compra", "acima do pedido", "faturar a mais", "superfaturar",
    "bon de commande", "dépasse le bon de commande", "surfacturer", "surfacturation", "ordine d'acquisto", "ordine di acquisto", "sopra l'ordine", "supera l'ordine", "sovrafatturare",
    "bestellung", "bestellwert", "überfakturieren", "überhöhte rechnung", "inkooporder", "boven de bestelling", "te veel factureren",
    "采购订单", "超出订单", "超过采购订单", "高于订单", "多开发票", "超额开票", "発注書", "注文書", "発注額を超", "水増し請求", "過大請求", "구매 주문서", "발주서", "발주 금액", "초과 청구", "과다 청구",
    "أمر الشراء", "فوق أمر الشراء", "تجاوز أمر الشراء", "فوترة زائدة", "खरीद आदेश", "पीओ से ज्यादा", "ऑर्डर से अधिक", "अधिक बिल",
    "заказ на покупку", "заказ поставщику", "сверх заказа", "превышающий заказ", "завысить счет", "satın alma siparişi", "sipariş tutarı", "siparişin üzerinde", "fazla fatura",
  ],
  amount_drift: [
    "drift", "creep up", "creeping up", "gradually increase", "gradually raise", "a little more each month", "a bit more each month", "slightly higher each month", "price creep", "raise the price", "little by little", "recurring vendor", "recurring invoice", "monthly invoice",
    "poco a poco", "aumento gradual", "subir el precio", "un poco más cada mes", "factura recurrente", "aos poucos", "pouco a pouco", "um pouco mais a cada mês", "fatura recorrente",
    "petit à petit", "peu à peu", "un peu plus chaque mois", "augmentation progressive", "facture récurrente", "hausse progressive", "a poco a poco", "un po' di più ogni mese", "aumento graduale", "fattura ricorrente",
    "nach und nach", "schrittweise erhöhen", "jeden monat ein bisschen mehr", "jeden monat etwas mehr", "wiederkehrende rechnung", "schleichend erhöhen", "beetje bij beetje", "elke maand een beetje meer", "geleidelijk verhogen", "terugkerende factuur",
    "逐月上涨", "逐渐增加", "每月多一点", "每个月多一点", "慢慢涨价", "逐步提高", "定期发票", "悄悄涨价", "少しずつ", "毎月少しずつ", "徐々に", "定期請求", "継続請求", "조금씩", "매달 조금씩", "서서히 올리", "점점 늘리", "정기 청구",
    "تدريجيا", "زيادة تدريجية", "كل شهر أكثر قليلا", "فاتورة متكررة", "धीरे-धीरे", "धीरे धीरे", "हर महीने थोड़ा", "आवर्ती चालान", "понемногу", "постепенно повышать", "каждый месяц чуть больше", "каждый месяц немного", "регулярный счет",
    "yavaş yavaş", "azar azar", "her ay biraz daha", "kademeli artır", "tekrarlayan fatura",
  ],
};

export interface SchemeGuess {
  scheme: BuiltInScheme;
  /** how many phrases of that scheme were heard; 0 means nothing matched and `scheme` is only the default */
  hits: number;
  /** a clear single winner (more phrases than any other scheme) */
  confident: boolean;
}

/**
 * Lower case, quotes straightened, spaces collapsed, and the accents taken off Latin and Cyrillic letters, so "nomina" still
 * finds "nómina" (speech-to-text drops or adds accents as it likes). Only the combining marks in U+0300–U+036F go; everything
 * else is put back together (NFC), so Hindi vowel signs, kana and Hangul are untouched.
 */
const fold = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").normalize("NFC").replace(/[’‘]/g, "'").replace(/\s+/g, " ");

const FOLDED: [BuiltInScheme, string[]][] = (Object.keys(LEXICON) as BuiltInScheme[]).map((k) => [k, LEXICON[k].map(fold)]);

/**
 * The built-in scheme closest to `text`, by phrases heard. The scheme with the most phrases wins; if two have the same number,
 * the one whose phrases cover more of what was said wins (still "not confident"), and a dead heat goes to the earlier scheme in
 * the catalog's order.
 */
export function closestScheme(text: string): SchemeGuess {
  const t = ` ${fold(text)} `;
  let best: BuiltInScheme = "ghost_vendor";
  let bestHits = 0;
  let bestChars = 0;
  let second = 0;
  for (const [scheme, phrases] of FOLDED) {
    let hits = 0;
    let chars = 0;
    for (const phrase of phrases) if (t.includes(phrase)) { hits++; chars += phrase.length; }
    if (hits > bestHits || (hits === bestHits && hits > 0 && chars > bestChars)) {
      second = Math.max(second, bestHits);
      bestHits = hits;
      bestChars = chars;
      best = scheme;
    } else if (hits > second) {
      second = hits;
    }
  }
  return { scheme: best, hits: bestHits, confident: bestHits > 0 && bestHits > second };
}

export const BUILT_IN_SCHEMES = Object.keys(LEXICON) as BuiltInScheme[];
