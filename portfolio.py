"""Build both the API portfolio and the read-only Pages snapshot from the pilot inputs."""
import json
from datetime import date
from pathlib import Path

from construction_progress import Scene, compare

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WEIGHTS = {"Solar": (.4, .25, .2, .15), "Wind": (.45, .15, .2, .2)}


def rankings(sites, mode):
    weights = WEIGHTS[mode]
    result = []
    for site in sites:
        factors = [site[mode.lower()], site["slope"], site["land"], site["grid"]]
        score = round(100 * sum(w * factor for w, factor in zip(weights, factors)))
        explanation = ", ".join(
            f"{label} {factor:.2f} × {weight:.0%}"
            for label, factor, weight in zip(("Resource", "Slope", "Eligible land", "Grid proximity"), factors, weights)
        )
        result.append(dict(
            **site, score=score, value=f"{score} / 100", measure=f"{mode} suitability",
            detail="Weighted screening score", review="Survey decision",
            finding="Check available land and grid connection feasibility before commissioning a survey.",
            source=f"Illustrative normalized inputs. {explanation}."
        ))
    return sorted(result, key=lambda row: -row["score"])


def construction():
    def scene(year):
        return Scene(DATA / f"{year}.mask", date(year, 3, 1), "pilot-100x100", "synthetic-v1", 10000, 100)
    change = compare(scene(2024), scene(2025))
    coverage = change.valid_pixels / change.footprint_pixels if change.footprint_pixels else 0
    return dict(
        id="K", name="Khavda pilot", x=46, y=43,
        value=f"{change.newly_visible_ha:.1f} ha" if change.status == "reviewable" else "Unavailable",
        measure="Newly visible infrastructure", detail=f"{coverage:.0%} common valid coverage",
        review="Milestone review", finding="Review the change footprint before accepting this visible milestone.",
        source=f"Simulated masks for March 2024 and March 2025. {change.valid_pixels:,} of "
               f"{change.footprint_pixels:,} footprint pixels are comparable. Each pixel covers 100 m². "
               "The estimate requires at least 70% common coverage."
    )


def portfolio():
    pilot = json.loads((DATA / "pilot.json").read_text())
    watch = [dict(**case, value="Review", detail="Simulated orbital observation",
                  review="Next evidence request", source="Simulated satellite → HAPS → field evidence scenario.")
             for case in pilot["cases"]]
    return {"siting": {mode: rankings(pilot["sites"], mode) for mode in WEIGHTS},
            "build": [construction()], "watch": watch}


if __name__ == "__main__":
    (ROOT / "docs/pilot.json").write_text(json.dumps(portfolio(), indent=2, ensure_ascii=False) + "\n")
