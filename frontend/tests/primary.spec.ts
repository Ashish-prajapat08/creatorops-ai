import { test, expect, type Page } from "@playwright/test";
import { createHmac, randomUUID } from "node:crypto";

function sessionToken() {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  const payload = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: randomUUID(), email: `e2e-${randomUUID()}@example.com`, name: "E2E Finance Owner", aud: "creatorops-test", iss: "creatorops-test", exp: Math.floor(Date.now() / 1000) + 3600 })}`;
  return `${payload}.${createHmac("sha256", "e2e-only-signing-secret-at-least-32-characters").update(payload).digest("base64url")}`;
}
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Test session token").fill(sessionToken());
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Agency name").fill("Acme E2E Creator Management");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Agency overview" }),
  ).toBeVisible();
}
test("primary agency workflow: create records, draft, edit, approve, send, audit", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "Brands", exact: true }).click();
  await page.getByRole("button", { name: "New brand", exact: true }).click();
  await page.getByLabel("Brand name", { exact: true }).fill("Nike");
  await page
    .getByLabel("Contact email", { exact: true })
    .fill("finance@nike.example");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "Nike", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Creators", exact: true }).click();
  await page.getByRole("button", { name: "New creator", exact: true }).click();
  await page.getByLabel("Creator name").fill("Rahul Sharma");
  await page.getByLabel("Email", { exact: true }).fill("rahul@example.com");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "Rahul Sharma", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Campaigns", exact: true }).click();
  await page.getByRole("button", { name: "New campaign", exact: true }).click();
  await page.getByLabel("Campaign name").fill("Nike Summer Campaign");
  await page
    .getByLabel("Brand", { exact: true })
    .selectOption({ label: "Nike" });
  await page
    .getByLabel("Creator", { exact: true })
    .selectOption({ label: "Rahul Sharma" });
  await page.getByLabel("Deal value").fill("10000.00");
  await page.getByLabel("Start date").fill("2026-01-01");
  await page.getByLabel("End date").fill("2026-02-01");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "Nike Summer Campaign", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Invoices", exact: true }).click();
  await page.getByRole("button", { name: "New invoice", exact: true }).click();
  await page.getByLabel("Invoice number").fill("INV-E2E-001");
  await page
    .getByLabel("Brand", { exact: true })
    .selectOption({ label: "Nike" });
  await page
    .getByLabel("Campaign", { exact: true })
    .selectOption({ label: "Nike Summer Campaign" });
  await page.getByLabel("Amount", { exact: true }).fill("10000.00");
  await page.getByLabel("Issue date").fill("2026-01-01");
  await page.getByLabel("Due date").fill("2026-02-01");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "OVERDUE", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Collections", exact: true }).click();
  await page
    .getByRole("button", { name: "Scan overdue invoices", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.getByLabel("Body", { exact: true })).toHaveValue(
    /USD 10000\.00/,
  );
  const body = page.getByLabel("Body", { exact: true });
  await body.fill((await body.inputValue()) + "\nThank you for your help.");
  await expect(
    page.getByRole("button", { name: "Approve & send" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save edits" }).click();
  await expect(
    page.getByRole("button", { name: "Approve & send" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Approve & send" }).click();
  await expect(
    page.getByText("Email sent through Gmail.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "View the complete audit trail" })
    .click();
  await expect(
    page.getByRole("heading", { name: "INV-E2E-001" }),
  ).toBeVisible();
  await expect(
    page.getByText("collection approved", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("email sent", { exact: true })).toBeVisible();
  await expect(
    page.getByText("collection draft edited", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/primary-workflow.png",
    fullPage: true,
  });
});

test("protected routes send unauthenticated users to sign in", async ({
  page,
}) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});

test("V2: review an email promise, allocate a manual partial payment, then reverse it", async ({
  page,
  request,
}) => {
  await login(page);
  const accessToken = await page.evaluate(() =>
    sessionStorage.getItem("creatorops-test-token"),
  );
  const authHeaders = { Authorization: `Bearer ${accessToken}` };
  const agencyResponse = await request.get(
    "http://127.0.0.1:8001/api/v1/agencies",
    { headers: authHeaders },
  );
  const agency = (await agencyResponse.json()).data[0];
  const headers = { ...authHeaders, "X-Agency-ID": agency.id };
  async function create(path: string, data: Record<string, unknown>) {
    const result = await request.post(`http://127.0.0.1:8001/api/v1${path}`, {
      headers,
      data,
    });
    expect(result.status(), await result.text()).toBe(201);
    return (await result.json()).data;
  }
  const brand = await create("/brands", {
    name: "Nike",
    contact_email: "finance@nike.example",
  });
  const creator = await create("/creators", {
    name: "Aisha Khan",
    email: "aisha@example.com",
  });
  const campaign = await create("/campaigns", {
    name: "V2 Campaign",
    brand_id: brand.id,
    creator_id: creator.id,
    deal_value: "10000.00",
    currency: "USD",
    start_date: "2026-01-01",
    end_date: "2026-02-01",
  });
  const invoice = await create("/invoices", {
    invoice_number: "INV-E2E-V2",
    brand_id: brand.id,
    campaign_id: campaign.id,
    amount: "10000.00",
    currency: "USD",
    issue_date: "2026-01-01",
    due_date: "2026-02-01",
  });
  await page
    .getByRole("link", { name: "Email intelligence", exact: true })
    .click();
  await page
    .getByLabel("Invoice to synchronize")
    .selectOption({ label: "INV-E2E-V2" });
  await page.getByRole("button", { name: "Sync email", exact: true }).click();
  await expect(page.getByLabel("Reviewed classification")).toBeVisible();
  await expect(page.getByLabel("Reviewed classification")).toHaveValue(
    "PAYMENT_PROMISED",
  );
  await page.getByLabel("Reviewed payment date").fill("2026-10-01");
  await page
    .getByLabel("Review reason")
    .fill("Finance clarified the ambiguous date with the brand.");
  await page.getByRole("button", { name: "Accept reviewed claim" }).click();
  await expect(
    page.getByText("Human review saved", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue(
    "Finance clarified the ambiguous date with the brand.",
  );
  await page.reload();
  await expect(
    page.getByText("Human review saved", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue(
    "Finance clarified the ambiguous date with the brand.",
  );
  await expect
    .poll(async () => {
      const response = await request.get(
        `http://127.0.0.1:8001/api/v1/invoices/${invoice.id}/promises`,
        { headers },
      );
      return (await response.json()).data[0]?.status;
    })
    .toBe("CLAIMED");
  await page.getByRole("link", { name: "Reconciliation", exact: true }).click();
  await page
    .getByRole("button", { name: "Enter manual transaction", exact: true })
    .click();
  await page.getByLabel("Source transaction ID").fill("MANUAL-E2E-PARTIAL");
  await page.getByLabel("Transaction amount").fill("4000.00");
  await page.getByLabel("Transaction date").fill("2026-10-21");
  await page.getByLabel("Known invoice").selectOption({ label: "INV-E2E-V2" });
  await page.getByRole("button", { name: "Save manual transaction" }).click();
  await page
    .getByRole("button", { name: "Select invoice", exact: true })
    .click();
  await page
    .getByLabel("Decision reason")
    .fill("Confirmed allocation of this manually entered partial payment.");
  await page
    .getByRole("button", { name: "Confirm allocation", exact: true })
    .click();
  await expect
    .poll(async () => {
      const response = await request.get(
        `http://127.0.0.1:8001/api/v1/invoices/${invoice.id}/balance`,
        { headers },
      );
      return (await response.json()).data.outstanding_balance;
    })
    .toBe("6000.00");
  await page
    .getByRole("button", { name: "Reverse allocation", exact: true })
    .click();
  await page
    .getByLabel("Reversal reason")
    .fill(
      "Incorrect manual payment evidence; retaining an audited correction.",
    );
  await page
    .getByRole("button", { name: "Confirm reversal", exact: true })
    .click();
  await expect
    .poll(async () => {
      const response = await request.get(
        `http://127.0.0.1:8001/api/v1/invoices/${invoice.id}/balance`,
        { headers },
      );
      return (await response.json()).data.outstanding_balance;
    })
    .toBe("10000.00");
  await page.goto(`/invoices/${invoice.id}`);
  await expect(
    page.getByRole("heading", { name: "Payment promise history", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("payment allocation reversed", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/v2-workflow.png",
    fullPage: true,
  });
});
