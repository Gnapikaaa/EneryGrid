from enum import Enum

# Supported active ISO-4217 currency codes (explicit validation; no implicit USD default)
SUPPORTED_ISO4217_CURRENCIES: frozenset[str] = frozenset(
    {
        "AED",
        "AUD",
        "BDT",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "DKK",
        "EUR",
        "GBP",
        "HKD",
        "IDR",
        "ILS",
        "INR",
        "JPY",
        "KRW",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "PHP",
        "PLN",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TRY",
        "TWD",
        "USD",
        "ZAR",
    }
)

MAX_INTEGRATION_GAP_SECONDS = 7200  # 2 hours max before outage gap bounding
MIN_BASELINE_SAMPLES = 14


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class UserRole(str, Enum):
    ADMIN = "admin"
    FACILITY_MANAGER = "facility_manager"
    UTILITY_ENGINEER = "utility_engineer"
    VIEWER = "viewer"


class HealthStatus(str, Enum):
    NOMINAL = "Nominal"
    WARNING = "Warning"
    FAULT = "Fault"


class TariffPeriod(str, Enum):
    PEAK = "Peak"
    MID_PEAK = "Mid-Peak"
    OFF_PEAK = "Off-Peak"


class BaselineStatus(str, Enum):
    READY = "ready"
    INSUFFICIENT_HISTORY = "insufficient_history"


class QualityFlag(str, Enum):
    VALID = "valid"
    GAP_BOUNDED = "gap_bounded"
    SIMULATED = "simulated"


class TelemetrySource(str, Enum):
    METER_FEED = "meter_feed"
    CSV_IMPORT = "csv_import"
    SEED = "seed"
    SIMULATION = "simulation"


class AnomalySeverity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    ELEVATED = "Elevated"


class AnomalyStatus(str, Enum):
    OPEN = "Open"
    ACKNOWLEDGED = "Acknowledged"
    ASSIGNED = "Assigned"
    RESOLVED = "Resolved"


class InsightCategory(str, Enum):
    LOAD_SHIFTING = "Load Shifting"
    POWER_QUALITY = "Power Quality"
    HVAC_THERMAL = "HVAC & Thermal"
    COMPRESSED_AIR = "Compressed Air"


class InsightPriority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"


class InsightStatus(str, Enum):
    RECOMMENDED = "Recommended"
    IN_PROGRESS = "In Progress"
    IMPLEMENTED = "Implemented"


class CostEstimateStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE_TARIFF = "unavailable_tariff"
    NOT_QUANTIFIABLE = "not_quantifiable"
    LEGACY_UNVERIFIED = "legacy_unverified"


ANOMALY_COST_ESTIMATE_STATUSES: tuple[CostEstimateStatus, ...] = (
    CostEstimateStatus.AVAILABLE,
    CostEstimateStatus.UNAVAILABLE_TARIFF,
    CostEstimateStatus.LEGACY_UNVERIFIED,
)

INSIGHT_COST_ESTIMATE_STATUSES: tuple[CostEstimateStatus, ...] = (
    CostEstimateStatus.AVAILABLE,
    CostEstimateStatus.UNAVAILABLE_TARIFF,
    CostEstimateStatus.NOT_QUANTIFIABLE,
    CostEstimateStatus.LEGACY_UNVERIFIED,
)


class InsightSavingsBasis(str, Enum):
    TARIFF_ARBITRAGE_ONLY = "tariff_arbitrage_only"
    ESTIMATED_EXCESS_AVOIDANCE = "estimated_excess_avoidance"
    UNQUANTIFIED_TELEMETRY = "unquantified_telemetry"
    LEGACY_MIGRATED = "legacy_migrated"


class InsightRuleCode(str, Enum):
    PEAK_LOAD_SHIFT = "PEAK_LOAD_SHIFT"
    LOW_POWER_FACTOR = "LOW_POWER_FACTOR"
    OFF_PEAK_BASELOAD_PATTERN = "OFF_PEAK_BASELOAD_PATTERN"
    THERMAL_CORRELATED_LOAD = "THERMAL_CORRELATED_LOAD"


def validate_iso4217_currency(code: str) -> str:
    """Validate that a currency code is a supported uppercase 3-letter ISO-4217 code."""
    normalized = code.strip().upper() if isinstance(code, str) else ""
    if normalized not in SUPPORTED_ISO4217_CURRENCIES:
        raise ValueError(
            f"Unsupported currency code '{code}'. Must be a supported ISO-4217 code."
        )
    return normalized
