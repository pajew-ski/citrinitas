"""Licences travel with every row; a derived row inherits every restriction of its inputs (Spec C12, C36)."""
from __future__ import annotations

# flags: by = attribution, sa = share-alike, nc = non-commercial, nd = no derivatives, rs = other restrictions
LICENSES: dict[str, frozenset[str]] = {
    "CC0-1.0": frozenset(),
    "PDM": frozenset(),
    "US-PD": frozenset(),
    "CC-BY-4.0": frozenset({"by"}),
    "dl-de/by-2-0": frozenset({"by"}),
    "GDELT-terms": frozenset({"by"}),          # free use and redistribution with citation of the GDELT Project
    "CC-BY-SA-4.0": frozenset({"by", "sa"}),
    "ODbL-1.0": frozenset({"by", "sa"}),
    "CC-BY-NC-4.0": frozenset({"by", "nc"}),
    "CC-BY-NC-SA-4.0": frozenset({"by", "nc", "sa"}),
    "CC-BY-ND-4.0": frozenset({"by", "nd"}),
    "restricted": frozenset({"by", "rs"}),
}
_ORDER = ("by", "nc", "nd", "sa", "rs")


def flags(license_id: str) -> frozenset[str]:
    """An unknown licence counts as restricted: what is not known to be free stays inside."""
    return LICENSES.get(license_id, LICENSES["restricted"])


def combine(license_ids) -> str:
    """The licence of a row derived from several inputs: the union of all restrictions."""
    union = frozenset().union(*(flags(x) for x in license_ids)) if license_ids else frozenset()
    if "rs" in union:
        return "restricted"
    for name, f in LICENSES.items():
        if f == union and name.startswith(("CC", "PDM")):
            return name
    return "+".join(x for x in _ORDER if x in union) or "CC0-1.0"


def publishable(license_id: str) -> bool:
    """True if a row may leave the system as open data: no share-alike, non-commercial, no-derivatives or other limits."""
    return flags(license_id) <= {"by"}


def values_sql() -> str:
    rows = ",".join(f"('{k}', {'by' in f}, {'sa' in f}, {'nc' in f}, {'nd' in f}, {'rs' in f}, {f <= {'by'}})"
                    for k, f in LICENSES.items())
    return f"SELECT * FROM (VALUES {rows}) AS t(license, by_, sa, nc, nd, rs, publishable)"
