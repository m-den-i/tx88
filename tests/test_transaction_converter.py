import csv
import io
import json
import os

import pytest
from pydantic import ValidationError

from transaction_converter import (
    AmountType,
    AccountIdentification,
    ExchangeRate,
    PartyIdentification,
    PostalAddress,
    Transaction,
    TransactionConverter,
    _flatten,
)

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(
    ROOT,
    "fixtures",
    "transactions.json",
)
CSV_COMPARE = os.path.join(ROOT, "tests", "test.csv")
MINIMAL = {
    "transaction_amount": {"currency": "PLN", "amount": "10.00"},
    "credit_debit_indicator": "DBIT",
    "status": "BOOK",
    "booking_date": "2026-01-01",
}


# --- Validation ---

class TestTransactionValidation:
    def test_minimal_valid(self):
        t = Transaction(**MINIMAL)
        assert t.transaction_amount.currency == "PLN"
        assert t.credit_debit_indicator == "DBIT"

    def test_missing_required_amount(self):
        data = {**MINIMAL}
        del data["transaction_amount"]
        with pytest.raises(ValidationError):
            Transaction(**data)

    def test_missing_required_indicator(self):
        data = {**MINIMAL}
        del data["credit_debit_indicator"]
        with pytest.raises(ValidationError):
            Transaction(**data)

    def test_optional_fields_default_none(self):
        t = Transaction(**MINIMAL)
        assert t.creditor is None
        assert t.debtor is None
        assert t.remittance_information is None
        assert t.note is None

    def test_nested_amount_validation(self):
        data = {**MINIMAL, "transaction_amount": {"currency": "EUR"}}  # missing amount
        with pytest.raises(ValidationError):
            Transaction(**data)

    def test_full_nested_fields(self):
        data = {
            **MINIMAL,
            "creditor": {
                "name": "Acme Corp",
                "postal_address": {
                    "street_name": "Main St",
                    "country": "PL",
                    "address_line": ["Line 1", "Line 2"],
                },
            },
            "creditor_account": {"iban": "PL00000000000000000000000001"},
            "remittance_information": ["Invoice 42"],
            "exchange_rate": {
                "unit_currency": "EUR",
                "exchange_rate": "4.25",
                "instructed_amount": {"currency": "EUR", "amount": "100.00"},
            },
        }
        t = Transaction(**data)
        assert t.creditor.name == "Acme Corp"
        assert t.creditor.postal_address.country == "PL"
        assert t.exchange_rate.instructed_amount.currency == "EUR"


# --- _flatten helper ---

class TestFlatten:
    def test_scalar(self):
        assert _flatten("hello", "key") == {"key": "hello"}

    def test_none(self):
        assert _flatten(None, "key") == {"key": None}

    def test_flat_dict(self):
        assert _flatten({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_nested_dict(self):
        result = _flatten({"amount": {"currency": "PLN", "value": "9.99"}})
        assert result == {"amount_currency": "PLN", "amount_value": "9.99"}

    def test_list_takes_first(self):
        assert _flatten(["first", "second"], "info") == {"info": "first"}

    def test_empty_list(self):
        assert _flatten([], "info") == {"info": None}

    def test_list_of_dicts_takes_first(self):
        result = _flatten([{"id": "A"}, {"id": "B"}], "item")
        assert result == {"item_id": "A"}

    def test_deep_nesting(self):
        data = {"creditor": {"postal_address": {"country": "PL", "address_line": ["Line1"]}}}
        result = _flatten(data)
        assert result["creditor_postal_address_country"] == "PL"
        assert result["creditor_postal_address_address_line"] == "Line1"


# --- TransactionConverter.to_flat_dict ---

class TestToFlatDict:
    def test_minimal_transaction(self):
        t = Transaction(**MINIMAL)
        row = TransactionConverter.to_flat_dict(t)
        assert row["transaction_amount_currency"] == "PLN"
        assert row["transaction_amount_amount"] == "10.00"
        assert row["credit_debit_indicator"] == "DBIT"
        assert row["status"] == "BOOK"
        assert row["booking_date"] == "2026-01-01"
        assert row["creditor"] is None  # no nested keys when whole object is None

    def test_creditor_flattened(self):
        data = {
            **MINIMAL,
            "creditor": {
                "name": "John",
                "postal_address": {"country": "PL", "street_name": "Oak Ave"},
            },
        }
        row = TransactionConverter.to_flat_dict(Transaction(**data))
        assert row["creditor_name"] == "John"
        assert row["creditor_postal_address_country"] == "PL"
        assert row["creditor_postal_address_street_name"] == "Oak Ave"

    def test_remittance_first_item_only(self):
        data = {**MINIMAL, "remittance_information": ["Payment for invoice", "Extra note"]}
        row = TransactionConverter.to_flat_dict(Transaction(**data))
        assert row["remittance_information"] == "Payment for invoice"

    def test_remittance_empty_list(self):
        data = {**MINIMAL, "remittance_information": []}
        row = TransactionConverter.to_flat_dict(Transaction(**data))
        assert row["remittance_information"] is None

    def test_exchange_rate_with_nested_amount(self):
        data = {
            **MINIMAL,
            "exchange_rate": {
                "unit_currency": "EUR",
                "exchange_rate": "4.20",
                "instructed_amount": {"currency": "EUR", "amount": "50.00"},
            },
        }
        row = TransactionConverter.to_flat_dict(Transaction(**data))
        assert row["exchange_rate_unit_currency"] == "EUR"
        assert row["exchange_rate_instructed_amount_currency"] == "EUR"
        assert row["exchange_rate_instructed_amount_amount"] == "50.00"

    def test_address_line_first_item(self):
        data = {
            **MINIMAL,
            "debtor": {
                "postal_address": {"address_line": ["123 Main St", "Suite 4"]},
            },
        }
        row = TransactionConverter.to_flat_dict(Transaction(**data))
        assert row["debtor_postal_address_address_line"] == "123 Main St"


# --- TransactionConverter.to_csv ---

class TestToCsv:
    def _parse_csv(self, csv_str: str) -> list[dict]:
        return list(csv.DictReader(io.StringIO(csv_str)))

    def test_single_row_headers(self):
        t = Transaction(**MINIMAL)
        output = TransactionConverter.to_csv([t])
        rows = self._parse_csv(output)
        assert len(rows) == 1
        assert "transaction_amount_currency" in rows[0]
        assert rows[0]["transaction_amount_currency"] == "PLN"

    def test_multiple_rows(self):
        t1 = Transaction(**MINIMAL)
        t2 = Transaction(**{**MINIMAL, "transaction_amount": {"currency": "EUR", "amount": "5.00"}})
        output = TransactionConverter.to_csv([t1, t2])
        rows = self._parse_csv(output)
        assert len(rows) == 2
        assert rows[0]["transaction_amount_currency"] == "PLN"
        assert rows[1]["transaction_amount_currency"] == "EUR"

    def test_output_to_stringio(self):
        buf = io.StringIO()
        result = TransactionConverter.to_csv([Transaction(**MINIMAL)], output=buf)
        assert result == ""
        buf.seek(0)
        assert "transaction_amount_currency" in buf.read()

    def test_empty_list(self):
        output = TransactionConverter.to_csv([])
        assert output == ""

    def test_csv_has_no_extra_quotes_for_none(self):
        t = Transaction(**MINIMAL)
        row = self._parse_csv(TransactionConverter.to_csv([t]))[0]
        # None fields appear as empty string in CSV
        assert row.get("creditor") == "" or row.get("creditor") is None


# --- Integration with real fixture ---

class TestRealFixture:
    @pytest.fixture
    def transactions(self):
        with open(FIXTURE, encoding="utf-8") as f:
            data = json.load(f)
        return [Transaction(**tx) for tx in data["transactions"]]

    def test_all_transactions_parse(self, transactions):
        assert len(transactions) > 0

    def test_csv_matches(self, transactions):
        output = TransactionConverter.to_csv(transactions)
        with open(CSV_COMPARE, "rt") as f:
            rows_1 = list(csv.DictReader(f))
        rows_2 = list(csv.DictReader(io.StringIO(output)))
        assert rows_1 == rows_2

    def test_flat_dict_has_no_nested_dicts(self, transactions):
        for tx in transactions:
            row = TransactionConverter.to_flat_dict(tx)
            for value in row.values():
                assert not isinstance(value, dict), f"Nested dict found: {value}"
                assert not isinstance(value, list), f"List found: {value}"

    def test_booking_date_preserved(self, transactions):
        row = TransactionConverter.to_flat_dict(transactions[0])
        assert row["booking_date"] == "2026-02-27"

    def test_entry_reference_preserved(self, transactions):
        row = TransactionConverter.to_flat_dict(transactions[0])
        assert row["entry_reference"] == "2026-02-27/39701992459/1414522671"
