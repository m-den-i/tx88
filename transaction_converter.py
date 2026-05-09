from __future__ import annotations

import csv
import io
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class TransactionStatus(str, Enum):
    BOOK = "BOOK"
    PDNG = "PDNG"
    HOLD = "HOLD"
    INFO = "INFO"


# --- Sub-schemas ---

class AmountType(BaseModel):
    currency: str
    amount: str


class PostalAddress(BaseModel):
    address_type: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    street_name: Optional[str] = None
    building_number: Optional[str] = None
    post_code: Optional[str] = None
    town_name: Optional[str] = None
    country_sub_division: Optional[str] = None
    country: Optional[str] = None
    address_line: Optional[list[str]] = None


class ContactDetails(BaseModel):
    email_address: Optional[str] = None
    phone_number: Optional[str] = None


class GenericIdentification(BaseModel):
    identification: Optional[str] = None
    scheme_name: Optional[str] = None


class AccountIdentification(BaseModel):
    iban: Optional[str] = None
    other: Optional[GenericIdentification] = None


class ClearingSystemMemberIdentification(BaseModel):
    clearing_system_id: Optional[str] = None
    member_id: Optional[str] = None


class FinancialInstitutionIdentification(BaseModel):
    bic_fi: Optional[str] = None
    clearing_system_member_id: Optional[ClearingSystemMemberIdentification] = None
    name: Optional[str] = None


class BankTransactionCode(BaseModel):
    description: Optional[str] = None
    code: Optional[str] = None
    sub_code: Optional[str] = None


class ExchangeRate(BaseModel):
    unit_currency: Optional[str] = None
    exchange_rate: Optional[str] = None
    rate_type: Optional[str] = None
    contract_identification: Optional[str] = None
    instructed_amount: Optional[AmountType] = None


class PartyIdentification(BaseModel):
    name: Optional[str] = None
    postal_address: Optional[PostalAddress] = None
    organisation_id: Optional[dict] = None
    private_id: Optional[dict] = None
    contact_details: Optional[ContactDetails] = None


# --- Main Transaction model ---

class Transaction(BaseModel):
    entry_reference: Optional[str] = None
    merchant_category_code: Optional[str] = None
    transaction_amount: AmountType
    creditor: Optional[PartyIdentification] = None
    creditor_account: Optional[AccountIdentification] = None
    creditor_agent: Optional[FinancialInstitutionIdentification] = None
    debtor: Optional[PartyIdentification] = None
    debtor_account: Optional[AccountIdentification] = None
    debtor_agent: Optional[FinancialInstitutionIdentification] = None
    bank_transaction_code: Optional[BankTransactionCode] = None
    credit_debit_indicator: str
    status: TransactionStatus
    booking_date: Optional[str] = None
    value_date: Optional[str] = None
    transaction_date: Optional[str] = None
    balance_after_transaction: Optional[AmountType] = None
    reference_number: Optional[str] = None
    reference_number_schema: Optional[str] = None
    remittance_information: Optional[list[str]] = None
    debtor_account_additional_identification: Optional[GenericIdentification] = None
    creditor_account_additional_identification: Optional[GenericIdentification] = None
    exchange_rate: Optional[ExchangeRate] = None
    note: Optional[str] = None
    transaction_id: Optional[str] = None


# --- Flattening ---

def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten nested dicts. Lists: take first item only."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            full_key = f"{prefix}_{key}" if prefix else key
            result.update(_flatten(value, full_key))
        return result
    if isinstance(data, list):
        first = data[0] if data else None
        return _flatten(first, prefix)
    return {prefix: data}


# --- Converter ---

class TransactionConverter:
    @staticmethod
    def to_flat_dict(transaction: Transaction) -> dict[str, Any]:
        return _flatten(transaction.model_dump())

    @classmethod
    def to_csv(cls, transactions: list[Transaction], output: io.StringIO | None = None) -> str:
        if not transactions:
            return ""
        rows = [cls.to_flat_dict(t) for t in transactions]
        fieldnames = list(dict.fromkeys(k for row in rows for k in row))

        buf = output or io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

        if output is None:
            return buf.getvalue()
        return ""
