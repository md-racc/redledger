// What five large US lenders have said in public about outside AI agents in customer accounts, with the source of every line.
// Owner: Dev R. Researched 2026-10-25 from reporting dated 2026-10-15 to 2026-10-23; the same table, with the caveats in full, is
// root EVIDENCE.md, "Lenders on the record". Everything here is a paraphrase of someone else's reporting or statement, never a claim of ours.
//
// The rules this file keeps (lenders.test.ts checks them): a bank is only ever said to have *said* or *done* what a named source says
// it did; reporting that rests on anonymous sources says so; a bank that has not spoken, or that denies it, is shown as that, not as
// a victim. No bank is a partner, customer or sponsor of Red Ledger.

export type SourceKind = "earnings call" | "company statement" | "news report";

export interface Source {
  outlet: string;
  by?: string;
  /** ISO date of publication */
  date: string;
  url: string;
  kind: SourceKind;
  /** what the source is, when it is second-hand or syndicated */
  note?: string;
}

export interface Lender {
  id: "jpmorgan" | "bofa" | "citi" | "wells" | "morgan-stanley";
  name: string;
  /** one line for the card's header: where the bank stands, in its own reported terms */
  chip: string;
  /** a paraphrase, in our words, of what the sources report */
  says: string;
  /** what we do not claim about this bank */
  notClaimed: string;
  /** the bank itself (a named executive or a spokesperson) has said something on the record about outside agents */
  spoken: boolean;
  sources: Source[];
}

export const AS_OF = "2026-10-25";

export const AXIOS: Source = {
  outlet: "Axios (read as syndicated by Yahoo Finance)",
  by: "Madison Mills",
  date: "2026-10-22",
  url: "https://finance.yahoo.com/technology/ai/articles/scoop-unvetted-ai-agents-accessing-090006442.html",
  kind: "news report",
  note: "the Axios original is paywalled; its bank-by-bank claims rest on anonymous sources",
};

const CBS: Source = {
  outlet: "CBS News",
  by: "Megan Cerullo",
  date: "2026-10-23",
  url: "https://www.cbsnews.com/news/ai-agents-customer-bank-accounts-security/",
  kind: "news report",
};

const FORTUNE: Source = {
  outlet: "Fortune",
  by: "Joshua Hong",
  date: "2026-10-15",
  url: "https://fortune.com/2026/10/15/jamie-dimon-ai-agents-meta-muse-jpmorgan/",
  kind: "news report",
  note: "reports the Oct 13 earnings call and a bank spokesperson",
};

const RBI: Source = {
  outlet: "Retail Banker International",
  by: "Vidhya Edwards Munnangi",
  date: "2026-10-19",
  url: "https://www.retailbankerinternational.com/?p=108841",
  kind: "news report",
  note: "carries Citi's statement to the outlet; the Bank of America lines are second-hand from the Financial Times and CNBC",
};

const PYMNTS_BIG_BANKS: Source = {
  outlet: "PYMNTS",
  date: "2026-10-19",
  url: "https://www.pymnts.com/?p=4326961",
  kind: "news report",
  note: "second-hand: summarises the Financial Times, Bloomberg and the earnings calls",
};

const PYMNTS_CRACK_DOWN: Source = {
  outlet: "PYMNTS",
  date: "2026-10-22",
  url: "https://www.pymnts.com/news/banking/2026/banks-crack-down-on-unauthorized-ai-agents-operating-inside-customer-accounts/",
  kind: "news report",
  note: "second-hand: summarises Reuters, which summarises the Axios report",
};

const BANKING_DIVE: Source = {
  outlet: "Banking Dive",
  by: "Makenzie Holland",
  date: "2026-10-15",
  url: "https://www.bankingdive.com/news/ai-citi-fraser-wells-fargo-scharf-goldman-sachs-solomon-morgan-stanley-pick-bofa-moynihan-dimon/833087/",
  kind: "earnings call",
  note: "the third-quarter earnings calls of the large banks",
};

/** The one report the others follow. */
export const HEADLINE =
  "Axios reported on Oct 22 that large US banks are finding third-party AI agents they never vetted inside customer accounts, mostly logging in with the customer's own password. Some did things the customer had not asked for. A bank executive said they struggle to tell an authorised agent from a rogue one. The sourcing is anonymous, and the reporter told CBS the agents were not hacking accounts or draining funds.";

export const LENDERS: Lender[] = [
  {
    id: "jpmorgan",
    name: "JPMorgan Chase",
    chip: "Won't let outside agents in",
    says: "CEO Jamie Dimon said on the Oct 13 earnings call that the bank will not let outside AI agents inside, and warned of “rogue agents”. A spokesperson said that when the bank detects a third-party agent using a customer's banking credentials, it does not allow it. Read-only data through open-banking connectors continues.",
    notClaimed: "No count of agents found has been published.",
    spoken: true,
    sources: [FORTUNE, CBS],
  },
  {
    id: "bofa",
    name: "Bank of America",
    chip: "A human approves money out",
    says: "CEO Brian Moynihan told CNBC that a person should approve any money leaving an account, and that the bank is working out who is liable when an AI authorises a payment. The Financial Times reported, from an unnamed source, that it limits agents' access to consumer deposits. The bank did not answer CBS.",
    notClaimed: "The bank has not said it found agents inside accounts.",
    spoken: true,
    sources: [RBI, PYMNTS_BIG_BANKS],
  },
  {
    id: "citi",
    name: "Citi",
    chip: "No outside agents; read-only via approved providers",
    says: "A spokesperson told Retail Banker International that Citi does not let third-party AI agents or assistants log in to a customer's account or transact on its digital banking platforms. Customers can still give read-only access through approved open-banking providers.",
    notClaimed: "The bank has not said it found agents inside accounts.",
    spoken: true,
    sources: [RBI],
  },
  {
    id: "wells",
    name: "Wells Fargo",
    chip: "No statement found",
    says: "We found no statement from Wells Fargo on outside agents in customer accounts. CEO Charlie Scharf said on the third-quarter call that the bank takes a disciplined approach to risk and will weigh whether third-party models and agents add value for clients. Axios lists Wells Fargo among banks racing to contain agent risk, with no detail; the bank did not answer CBS.",
    notClaimed: "We do not say Wells Fargo found agents in its accounts. We found no statement that it did.",
    spoken: false,
    sources: [BANKING_DIVE, AXIOS],
  },
  {
    id: "morgan-stanley",
    name: "Morgan Stanley",
    chip: "Says it has seen none",
    says: "A spokesperson told CBS the firm has not observed unauthorized AI agent activity on its platforms. Axios, from anonymous sources, says it has begun blocking third-party agents. The two accounts are not reconciled.",
    notClaimed: "We do not say Morgan Stanley found agents in its accounts. It says it has not.",
    spoken: true,
    sources: [CBS, AXIOS],
  },
];

/** Two more lenders on the record in the same reporting; not among the five, so not in the card's columns. */
export const ALSO: { name: string; says: string; source: Source }[] = [
  {
    name: "Charles Schwab",
    says: "CEO Rick Wurster told Bloomberg on Oct 16 that Schwab blocks unauthorized agents that try to log in for clients and will not let outside agents move money.",
    source: PYMNTS_BIG_BANKS,
  },
  {
    name: "PNC",
    says: "CEO William Demchak called agents transacting inside customer accounts unsafe on the Oct 15 call, and said it would take liability law and secure authentication.",
    source: PYMNTS_CRACK_DOWN,
  },
];

/** How Red Ledger stands next to this. Only things the demo does. */
export const TIE =
  "The banks are blocking agents at the door. Red Ledger tests the other case: an agent already inside the books, and a gate that must say allow, block, or ask a human. A human approving money out is the rule our gate escalates to, and no answer in 90 seconds is a block.";

export const DISCLAIMER =
  "Paraphrased from the cited reporting, as of Oct 25, 2026. These banks are not partners, customers or sponsors of Red Ledger, and nothing here is their statement about us. The company in this demo is synthetic.";
