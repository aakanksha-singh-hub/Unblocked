"""Name generation for the synthetic book.

Kept in its own module so it is obvious that nothing here is scraped from a real
customer list. Every name is assembled from generic components.
"""

from __future__ import annotations

import random

_PREFIX = [
    "Shree", "Om", "Sai", "Krishna", "Balaji", "Ganesh", "Laxmi", "Anand",
    "Bharat", "Deep", "Ekta", "Gokul", "Hari", "Indus", "Jai", "Kamal",
    "Mahavir", "Navkar", "Pragati", "Rajhans", "Sagar", "Trimurti", "Vishwa",
    "Yash", "Aditya", "Chetan", "Dhanraj", "Girish", "Kiran", "Milan",
]
_MID = [
    "Enterprises", "Industries", "Traders", "Agencies", "Packaging", "Polymers",
    "Distributors", "Marketing", "Corporation", "Overseas", "Impex", "Sales",
    "Products", "Textiles", "Engineering", "Plastics", "Consumer Products",
    "Retail", "Supply Co", "Trading Co",
]
_SUFFIX = ["Pvt Ltd", "Pvt Ltd", "Pvt Ltd", "LLP", "& Sons", "& Co", "Limited", ""]

_CITIES = [
    ("Bhiwandi", "MH"), ("Mumbai", "MH"), ("Pune", "MH"), ("Nashik", "MH"),
    ("Surat", "GJ"), ("Ahmedabad", "GJ"), ("Rajkot", "GJ"), ("Vapi", "GJ"),
    ("Delhi", "DL"), ("Noida", "UP"), ("Ghaziabad", "UP"), ("Kanpur", "UP"),
    ("Ludhiana", "PB"), ("Jaipur", "RJ"), ("Indore", "MP"), ("Nagpur", "MH"),
    ("Bengaluru", "KA"), ("Hosur", "TN"), ("Coimbatore", "TN"), ("Chennai", "TN"),
    ("Hyderabad", "TG"), ("Kolkata", "WB"), ("Faridabad", "HR"), ("Gurugram", "HR"),
]

_FIRST = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Suresh", "Kavita",
    "Manish", "Deepa", "Rajesh", "Meena", "Arun", "Pooja", "Sanjay", "Nisha",
    "Ravi", "Shalini", "Prakash", "Divya", "Naveen", "Rekha", "Ashok", "Swati",
]
_LAST = [
    "Sharma", "Patel", "Verma", "Iyer", "Reddy", "Nair", "Shah", "Gupta",
    "Mehta", "Joshi", "Kulkarni", "Desai", "Rao", "Chauhan", "Agarwal", "Bhat",
]

_STATE_GST_CODE = {
    "MH": "27", "GJ": "24", "DL": "07", "UP": "09", "PB": "03", "RJ": "08",
    "MP": "23", "KA": "29", "TN": "33", "TG": "36", "WB": "19", "HR": "06",
}


def company(rng: random.Random) -> str:
    parts = [rng.choice(_PREFIX), rng.choice(_MID), rng.choice(_SUFFIX)]
    return " ".join(p for p in parts if p)


def city(rng: random.Random) -> tuple[str, str]:
    return rng.choice(_CITIES)


def person(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def gstin(rng: random.Random, state: str) -> str:
    """Structurally shaped like a GSTIN. The checksum is not valid, deliberately -
    these must never be mistakable for real registrations."""
    code = _STATE_GST_CODE.get(state, "27")
    pan = (
        "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
        + "".join(rng.choice("0123456789") for _ in range(4))
        + rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
    )
    return f"{code}{pan}1Z0"


def email(rng: random.Random, name: str, company_name: str) -> str:
    handle = name.split()[0].lower()
    dom = "".join(c for c in company_name.split()[0].lower() if c.isalpha())
    return f"{handle}@{dom}{rng.choice(['corp', 'inds', 'ent', 'grp'])}.example"


def phone(rng: random.Random) -> str:
    return f"+91{rng.choice('6789')}{''.join(rng.choice('0123456789') for _ in range(9))}"
