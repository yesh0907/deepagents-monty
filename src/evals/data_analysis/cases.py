"""Deterministic data-analysis eval cases for the transaction dataset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DATASET_DIR = Path(__file__).with_name("dataset")
CSV_PATH = DATASET_DIR / "transactions.csv"
SQLITE_PATH = DATASET_DIR / "transactions.sqlite"
AGENT_DATASET_PATH = "/transactions.csv"


@dataclass(frozen=True)
class EvalCase:
    """A single data-analysis question with a deterministic SQL answer key."""

    id: str
    question: str
    sql: str
    answer_template: str
    tolerance: float = 0.0


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="october_2023_orbit_card_spend",
        question=(
            "Can you check how much I spent on my Orbit card in October 2023? "
            "Just give me the amount."
        ),
        sql=(
            "select round(sum(amount), 2) from transactions "
            "where account_name = 'ORBIT CARD' "
            "and date >= '2023-10-01' and date < '2023-11-01' "
            "and amount > 0"
        ),
        answer_template="{value:.2f}",
    ),
    EvalCase(
        id="largest_spending_category_all_time",
        question=(
            "What have I spent the most money on overall? Don't count income, card payments, "
            "or internal transfers. Just tell me the category."
        ),
        sql=(
            "select category from transactions "
            "where amount > 0 "
            "and category not in ('Income', 'Credit Card Payment', 'Internal Transfers') "
            "group by category order by sum(amount) desc limit 1"
        ),
        answer_template="{value}",
    ),
    EvalCase(
        id="highest_month_groceries",
        question=("When was my worst grocery month? I only need the month, like YYYY-MM."),
        sql=(
            "select substr(date, 1, 7) from transactions "
            "where amount > 0 and category = 'Groceries' "
            "group by substr(date, 1, 7) order by sum(amount) desc limit 1"
        ),
        answer_template="{value}",
    ),
    EvalCase(
        id="transaction_count_2024_dining",
        question=(
            "How many times did I spend on dining or drinks in 2024? Just the count is fine."
        ),
        sql=(
            "select count(*) from transactions "
            "where category = 'Dining & Drinks' and date >= '2024-01-01' and date < '2025-01-01'"
        ),
        answer_template="{value}",
    ),
    EvalCase(
        id="average_auto_transport_2022",
        question=("What was my typical auto/transport charge in 2022? Give me the average amount."),
        sql=(
            "select round(avg(amount), 2) from transactions "
            "where category = 'Auto & Transport' and amount > 0 "
            "and date >= '2022-01-01' and date < '2023-01-01'"
        ),
        answer_template="{value:.2f}",
    ),
    EvalCase(
        id="top_merchant_2025_shopping",
        question=(
            "Which shopping merchant did I spend the most at in 2025? Just give me the merchant name."
        ),
        sql=(
            "select name from transactions "
            "where category = 'Shopping' and amount > 0 "
            "and date >= '2025-01-01' and date < '2026-01-01' "
            "group by name order by sum(amount) desc limit 1"
        ),
        answer_template="{value}",
    ),
    EvalCase(
        id="net_income_2023",
        question=(
            "What does my income total come out to for 2023 if you keep the signs as-is? "
            "Just the number."
        ),
        sql=(
            "select round(sum(amount), 2) from transactions "
            "where category = 'Income' and date >= '2023-01-01' and date < '2024-01-01'"
        ),
        answer_template="{value:.2f}",
    ),
    EvalCase(
        id="largest_single_transaction",
        question=(
            "What's the biggest single charge anywhere in my transactions? Just give me the amount."
        ),
        sql="select round(max(amount), 2) from transactions where amount > 0",
        answer_template="{value:.2f}",
    ),
)
