"""Idempotent demo dataset attached to an authenticated application user."""

import argparse
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import Scope
from app.models.entities import (
    Agency,
    Brand,
    Campaign,
    Creator,
    EmailMessage,
    EmailThread,
    Invoice,
    Membership,
    User,
)
from app.schemas.contracts import AgencyIn
from app.services.entities import EntityService
from app.services.finance import scan_agency, today_for
from app.services.workspace import create_agency


def seed(db, user):
    agency = db.scalar(
        select(Agency)
        .join(Membership, Membership.agency_id == Agency.id)
        .where(Membership.user_id == user.id, Agency.name == "Acme Creator Management")
    )
    if not agency:
        data = create_agency(db, user, AgencyIn(name="Acme Creator Management"))
        agency = db.get(Agency, data["id"])
    ctx = Scope(agency.id, user.id, "OWNER")
    today = today_for(agency)
    for index, (brand_name, creator_name) in enumerate(
        zip(
            ["Nike", "Google", "Amazon"], ["Rahul Sharma", "Aisha Khan", "John Carter"], strict=True
        )
    ):
        brand_service = EntityService(db, ctx, "brands")
        brand = db.scalar(brand_service.repo.query(Brand).where(Brand.name == brand_name))
        if not brand:
            brand = brand_service.save(
                {
                    "name": brand_name,
                    "contact_email": f"finance@{brand_name.lower()}.example",
                    "contact_name": f"{brand_name} Finance",
                    "notes": "Demo record. Replace this address with a real contact before sending.",
                }
            )
        creator_service = EntityService(db, ctx, "creators")
        creator = db.scalar(creator_service.repo.query(Creator).where(Creator.name == creator_name))
        if not creator:
            creator = creator_service.save(
                {
                    "name": creator_name,
                    "email": f"creator-{index}@example.com",
                    "default_payout_percentage": Decimal("80.00"),
                }
            )
        campaign_service = EntityService(db, ctx, "campaigns")
        campaign = db.scalar(
            campaign_service.repo.query(Campaign).where(Campaign.brand_id == brand.id)
        )
        if not campaign:
            campaign = campaign_service.save(
                {
                    "name": f"{brand_name} Creator Campaign",
                    "brand_id": brand.id,
                    "creator_id": creator.id,
                    "deal_value": Decimal("25000.00"),
                    "currency": "USD",
                    "start_date": today - timedelta(days=60),
                    "end_date": today + timedelta(days=10),
                    "status": "ACTIVE",
                }
            )
        for position in range(2):
            number = f"INV-{1001 + index * 2 + position}"
            invoice_service = EntityService(db, ctx, "invoices")
            if db.scalar(
                invoice_service.repo.query(Invoice).where(Invoice.invoice_number == number)
            ):
                continue
            offset = [-9, -6, -3, 2, 5, -15][index * 2 + position]
            status = "PAID" if index == 2 and position == 1 else "SENT"
            invoice = invoice_service.save(
                {
                    "invoice_number": number,
                    "brand_id": brand.id,
                    "campaign_id": campaign.id,
                    "amount": Decimal(
                        ["10000", "5000", "8000", "6000", "4500", "7000"][index * 2 + position]
                    ),
                    "currency": "USD",
                    "issue_date": today - timedelta(days=30),
                    "due_date": today + timedelta(days=offset),
                    "status": status,
                    "description": f"Creator campaign deliverables — {creator_name}",
                }
            )
            if offset < 0 and status != "PAID":
                thread = EmailThread(
                    agency_id=agency.id,
                    invoice_id=invoice.id,
                    brand_id=brand.id,
                    gmail_thread_id=f"seed-thread-{invoice.id}",
                    subject=f"Invoice {number}",
                )
                db.add(thread)
                db.flush()
                db.add(
                    EmailMessage(
                        agency_id=agency.id,
                        thread_id=thread.id,
                        gmail_message_id=f"seed-message-{invoice.id}",
                        direction="OUTBOUND",
                        sender_email=user.email,
                        recipient_emails=[brand.contact_email],
                        subject=f"Invoice {number}",
                        body_text=f"Hi team, just checking in on invoice {number}. Please let us know if you need anything from us. Thanks.",
                        sent_at=thread.created_at,
                    )
                )
                db.commit()
    scan_agency(db, agency)
    return agency


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--email", required=True, help="Email of a user who has signed in to CreatorOps"
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if not user:
            parser.error(
                "Sign up and access CreatorOps first; seed never creates a fake production identity"
            )
        agency = seed(db, user)
        print(f"Seeded {agency.name}: {agency.id}. All .example recipients are placeholders.")
