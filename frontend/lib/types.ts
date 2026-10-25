export type Role = "OWNER" | "ADMIN" | "FINANCE" | "OPS" | "VIEWER";
export type Agency = {
  id: string;
  name: string;
  slug: string;
  role: Role;
  default_currency: string;
  timezone: string;
};
export type Brand = {
  id: string;
  name: string;
  contact_email: string;
  contact_name: string;
  payment_terms_days: number;
  notes: string;
};
export type Creator = {
  id: string;
  name: string;
  email: string;
  default_payout_percentage: string;
  notes: string;
};
export type Campaign = {
  id: string;
  name: string;
  brand_id: string;
  creator_id: string;
  deal_value: string;
  currency: string;
  start_date: string;
  end_date: string;
  status: string;
  description: string;
};
export type Invoice = {
  id: string;
  invoice_number: string;
  brand_id: string;
  campaign_id: string;
  amount: string;
  currency: string;
  issue_date: string;
  due_date: string;
  status: string;
  description: string;
};
export type Task = {
  workflow_key: string;
  task_type: string;
  gmail_thread_id: string | null;
  id: string;
  invoice_id: string;
  status: string;
  recommended_action: string;
  draft_subject: string | null;
  draft_body: string | null;
  recipient: string | null;
  draft_revision: number;
  context_summary: {
    intent: string;
    reason: string;
    evidence: string;
    message_count: number;
    source: string;
  } | null;
  error_code: string | null;
  gmail_message_id: string | null;
  approved_at: string | null;
  sent_at: string | null;
};
export type Audit = {
  id: string;
  action: string;
  actor_type: string;
  entity_id: string;
  created_at: string;
  details: Record<string, unknown>;
};
export type Summary = {
  totals: {
    currency: string;
    total_outstanding: string;
    overdue_amount: string;
    due_soon_amount: string;
    paid_amount: string;
  }[];
  overdue_invoice_count: number;
  pending_approval_count: number;
  overdue_invoices: Invoice[];
};
export type Member = {
  id: string;
  name: string;
  email: string;
  role: Role;
  user_id: string;
};

export type InsightOutput = {
  classification: string;
  confidence: number;
  invoice_reference: string | null;
  brand_reference: string | null;
  promised_date: string | null;
  date_status: string;
  payment_amount: string | null;
  currency: string | null;
  payment_reference: string | null;
  delay_reason: string | null;
  missing_information: string[];
  summary: string;
  recommended_action: string;
  evidence: { field: string; quote: string }[];
};
export type EmailAnalysis = {
  id: string;
  message_id: string;
  invoice_id: string;
  status: string;
  schema_version: string;
  model_output: InsightOutput | null;
  classification: string | null;
  confidence: string | null;
  review_reasons: string[];
  revision: number;
  review_decision: {
    effective_output: InsightOutput;
    reason: string;
    decision: string;
  } | null;
  error_code: string | null;
  source: {
    id: string;
    subject: string;
    sender_email: string;
    body_text: string;
    sent_at: string;
  };
};
export type PromiseRecord = {
  id: string;
  invoice_id: string;
  analysis_id: string;
  source_message_id: string;
  promised_date: string | null;
  date_status: string;
  status: string;
  evidence: string;
};
export type InvoiceBalance = {
  invoice_id: string;
  currency: string;
  invoice_amount: string;
  paid_amount: string;
  outstanding_balance: string;
  overpaid_amount: string;
  reconciliation_managed: boolean;
  legacy_manual_paid: boolean;
};
export type PaymentTransaction = {
  id: string;
  external_id: string;
  amount: string;
  currency: string;
  transaction_date: string;
  external_reference: string | null;
  brand_id: string | null;
  invoice_id: string | null;
  invoice_reference: string | null;
  description: string;
  source: string;
  status: string;
  revision: number;
};
export type Allocation = {
  id: string;
  transaction_id: string;
  invoice_id: string;
  amount: string;
  status: string;
  confirmed_by: string;
  confirmed_at: string;
  reversed_at: string | null;
  reversal_reason: string | null;
};
export type Reconciliation = {
  transaction: PaymentTransaction;
  allocated_amount: string;
  unallocated_amount: string;
  match_status: string;
  warnings: string[];
  candidates: {
    invoice_id: string;
    invoice_number: string;
    currency: string;
    outstanding_balance: string;
    amount_difference: string;
    match_type: string;
    reasons: string[];
    warnings: string[];
  }[];
  allocations: Allocation[];
  history: {
    id: string;
    decision: string;
    details: { reason: string };
    created_at: string;
  }[];
};
