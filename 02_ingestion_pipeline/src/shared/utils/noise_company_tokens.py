"""Noise token dictionary for company name normalization and fuzzy matching."""

from __future__ import annotations

import re


LEGAL_ENTITY_TOKENS_VI: set[str] = {
    "công",
    "ty",
    "tnhh",
    "mtv",
    "cp",
    "trách",
    "nhiệm",
    "hữu",
    "hạn",
    "cổ",
    "phần",
    "doanh",
    "nghiệp",
}


LEGAL_ENTITY_TOKENS_EN: set[str] = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "llc",
    "plc",
    "jsc",
    "group",
    "holding",
    "holdings",
}


INDUSTRY_GENERIC_TOKENS: set[str] = {
    "garment",
    "garments",
    "textile",
    "textiles",
    "manufacturing",
    "manufacture",
    "factory",
    "industrial",
    "industry",
    "production",
    "trading",
    "commerce",
    "commercial",
    "service",
    "services",
    "import",
    "export",
    "logistics",
    "technology",
    "processing",
    "engineering",
    "construction",
}


GEOGRAPHIC_TOKENS: set[str] = {
    "việt",
    "viet",
    "vietnam",
    "nam",
    "asia",
    "global",
    "international",
    "world",
    "worldwide",
    "china",
    "korea",
    "japan",
    "taiwan",
}


WEAK_BRAND_TOKENS: set[str] = {
    "south",
    "north",
    "east",
    "west",
    "new",
    "best",
    "gold",
    "star",
    "sun",
    "moon",
    "green",
    "blue",
    "red",
    "super",
    "mega",
}


NOISE_COMPANY_TOKENS: set[str] = (
    LEGAL_ENTITY_TOKENS_VI
    | LEGAL_ENTITY_TOKENS_EN
    | INDUSTRY_GENERIC_TOKENS
    | GEOGRAPHIC_TOKENS
    | WEAK_BRAND_TOKENS
)


TOKEN_PATTERN = re.compile(r"\b\w+\b")


def tokenize_company_name(company_name: str) -> list[str]:
    """Tokenize company name into lowercase word tokens."""

    return TOKEN_PATTERN.findall(company_name.lower())


def remove_noise_tokens(tokens: list[str]) -> list[str]:
    """Remove non-discriminative company tokens."""

    return [
        token
        for token in tokens
        if token not in NOISE_COMPANY_TOKENS
    ]


def normalize_company_name(company_name: str) -> list[str]:
    """Normalize company name into meaningful tokens."""

    tokens = tokenize_company_name(company_name)

    return remove_noise_tokens(tokens)
