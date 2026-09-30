"""Static ISO 4217 currency codes used by Routebook.

This is a bundled snapshot of ISO 4217 List One (current currencies and
funds), refreshed 2026-09-17.  It is intentionally static: Routebook does
not fetch currency data or perform foreign-exchange conversion at runtime.
"""

# Current ISO 4217 alphabetic codes, including funds, precious metals, and
# the standard no-currency code.  Historical/withdrawn codes are omitted.
ISO_4217_CODES = (
    "AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BHD", "BIF", "BMD", "BND", "BOB", "BOV",
    "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE",
    "CHF", "CHW", "CLF", "CLP", "CNY", "COP", "COU", "CRC", "CUP",
    "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB",
    "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF",
    "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR",
    "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR",
    "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR",
    "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT",
    "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MXV", "MYR", "MZN",
    "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN",
    "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB",
    "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE",
    "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX",
    "USD", "USN", "UYI", "UYU", "UYW", "UZS", "VED", "VES", "VND",
    "VUV", "WST", "XAD", "XAF", "XAG", "XAU", "XBA", "XBB", "XBC",
    "XBD", "XCD", "XCG", "XDR", "XOF", "XPD", "XPF", "XPT", "XSU",
    "XTS", "XUA", "XXX", "YER", "ZAR", "ZMW", "ZWG",
)

PREFERRED_CURRENCIES = (
    "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "CHF", "JPY", "INR",
)

# Preferred options first, then every other current code alphabetically.
CURRENCIES = PREFERRED_CURRENCIES + tuple(
    code for code in ISO_4217_CODES if code not in PREFERRED_CURRENCIES
)

assert len(ISO_4217_CODES) == 178
assert len(CURRENCIES) == len(set(CURRENCIES)) == len(ISO_4217_CODES)
