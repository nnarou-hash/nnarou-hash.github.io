#!/usr/bin/env python3
"""Build a compact, public dashboard payload from the project's Silver CSVs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REGIONS = {
    11: "Île-de-France",
    24: "Centre-Val de Loire",
    27: "Bourgogne-Franche-Comté",
    28: "Normandie",
    32: "Hauts-de-France",
    44: "Grand Est",
    52: "Pays de la Loire",
    53: "Bretagne",
    75: "Nouvelle-Aquitaine",
    76: "Occitanie",
    84: "Auvergne-Rhône-Alpes",
    93: "PACA",
    5: "Corse",
    99: "Hors région",
    0: "Non renseigné",
}
REGION_POP = {
    "Île-de-France": 12271794,
    "Centre-Val de Loire": 2572853,
    "Bourgogne-Franche-Comté": 2811423,
    "Normandie": 3310317,
    "Hauts-de-France": 6001897,
    "Grand Est": 5581676,
    "Pays de la Loire": 3877171,
    "Bretagne": 3398083,
    "Nouvelle-Aquitaine": 6109551,
    "Occitanie": 6078468,
    "Auvergne-Rhône-Alpes": 8087100,
    "PACA": 5115265,
    "Corse": 344679,
}
AGE_LABELS = {0: "0–19 ans", 20: "20–59 ans", 60: "60 ans et +", 99: "Non renseigné"}
SEX_LABELS = {1: "Hommes", 2: "Femmes", 9: "Non renseigné"}
POLLEN_COLUMNS = {
    "Graminées": "graminees_conc",
    "Bouleau": "bouleau_conc",
    "Ambroisie": "ambroisie_conc",
    "Aulne": "aulne_conc",
    "Armoise": "armoise_conc",
    "Olivier": "olivier_conc",
}


def read_required(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Fichier Silver requis absent : {path}")
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False, **kwargs)


def truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "vrai", "yes"})


def number(value: Any) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (float, int)):
        if not np.isfinite(value):
            return None
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return float(value)
    return value


def records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    data = frame.head(limit) if limit else frame
    result = []
    for row in data.to_dict(orient="records"):
        result.append({str(k): number(v) for k, v in row.items()})
    return result


def compact_group(parts: list[pd.DataFrame], keys: list[str], sums: dict[str, str]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame(columns=keys + list(sums))
    frame = pd.concat(parts, ignore_index=True)
    return frame.groupby(keys, dropna=False, as_index=False).agg(sums)


def load_medicaments(silver: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = silver / "J0_silver_medicaments.csv"
    df = read_required(path)
    code = df.get("code_atc", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
    if "est_antihistaminique" in df.columns:
        mask = truthy(df["est_antihistaminique"]) | code.str.startswith("R06")
    else:
        mask = code.str.startswith("R06")
    df = df.loc[mask].copy()
    if df.empty:
        raise ValueError("Aucune spécialité R06 détectée dans le Silver médicaments.")

    for col in ["nb_patients_ville", "pct_age_0_19_ans", "pct_age_20_59_ans",
                "pct_age_60_ans_et_plus", "pct_sexe_female", "pct_sexe_male"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    molecule_col = "molecule" if "molecule" in df.columns else "substance_active"
    molecule_count = int(df[molecule_col].dropna().nunique()) if molecule_col in df else 0
    lab_count = int(df["laboratoire"].dropna().nunique()) if "laboratoire" in df else 0
    patient_total = float(df["nb_patients_ville"].fillna(0).sum()) if "nb_patients_ville" in df else None

    profile_columns = [
        c for c in ["pct_age_0_19_ans", "pct_age_20_59_ans", "pct_age_60_ans_et_plus",
                    "pct_sexe_female", "pct_sexe_male"] if c in df.columns
    ]
    profile = []
    if profile_columns:
        profile = [{"variable": c, "percentage": number(df[c].mean())} for c in profile_columns]

    top_molecules = []
    if molecule_col in df.columns:
        grouped = (df.groupby(molecule_col, dropna=False)
                     .agg(specialties=(molecule_col, "size"),
                          patient_volume=("nb_patients_ville", "sum") if "nb_patients_ville" in df else (molecule_col, "size"))
                     .reset_index()
                     .rename(columns={molecule_col: "molecule"})
                     .sort_values("patient_volume", ascending=False))
        top_molecules = records(grouped, 20)

    top_labs = []
    if "laboratoire" in df.columns:
        labs = df["laboratoire"].fillna("Non renseigné").value_counts().head(15).rename_axis("laboratoire").reset_index(name="specialties")
        top_labs = records(labs)

    return df, {
        "specialty_count": int(len(df)),
        "molecule_count": molecule_count,
        "laboratory_count": lab_count,
        "sum_patient_volume": number(patient_total),
        "average_patient_age_sex_profile": profile,
        "top_molecules_by_patient_volume": top_molecules,
        "top_laboratories": top_labs,
    }


def load_ruptures(silver: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    base = read_required(silver / "J0_silver_ruptures.csv")
    code = base.get("code_atc", pd.Series("", index=base.index)).fillna("").astype(str).str.upper()
    if "est_antihistaminique" in base.columns:
        mask = truthy(base["est_antihistaminique"]) | code.str.startswith("R06")
    else:
        mask = code.str.startswith("R06")
    base = base.loc[mask].copy()
    date = pd.to_datetime(base.get("date_evenement"), errors="coerce")
    base["year"] = pd.to_numeric(base.get("annee"), errors="coerce")
    base["month"] = pd.to_numeric(base.get("mois"), errors="coerce")
    base.loc[base["year"].isna(), "year"] = date.dt.year
    base.loc[base["month"].isna(), "month"] = date.dt.month
    base["year_month"] = date.dt.to_period("M").astype(str)
    missing_period = base["year_month"].isin(["NaT", "nan", ""])
    base.loc[missing_period, "year_month"] = (
        base.loc[missing_period, "year"].fillna(0).astype(int).astype(str)
        + "-"
        + base.loc[missing_period, "month"].fillna(0).astype(int).astype(str).str.zfill(2)
    )
    base["event_category"] = base.get("classification", pd.Series("Autre", index=base.index)).fillna("Autre").astype(str).str.lower().map(
        lambda x: "Rupture" if "rupture" in x else ("Risque de rupture" if "risque" in x else ("Tension" if "tension" in x else x.title()))
    )
    base["molecule_clean"] = base.get("molecule", pd.Series("Non renseignée", index=base.index)).fillna("Non renseignée").astype(str)
    base["medicine"] = base.get("nom_medicament", pd.Series("", index=base.index)).fillna("").astype(str)
    base["laboratory"] = base.get("laboratoire", pd.Series("Non renseigné", index=base.index)).fillna("Non renseigné").astype(str)
    base["source"] = "ANSM / CADA"
    frames.append(base[["year", "month", "year_month", "event_category", "molecule_clean", "medicine", "laboratory", "source"]])

    recent_path = silver / "J0_silver_ruptures_ansm_2026.csv"
    if recent_path.exists():
        recent = read_required(recent_path)
        atc = recent.get("ATC4", pd.Series("", index=recent.index)).fillna("").astype(str).str.upper()
        recent = recent.loc[atc.str.startswith("R06")].copy()
        recent["year"] = pd.to_numeric(recent.get("annee_debut"), errors="coerce")
        recent["month"] = pd.to_numeric(recent.get("mois_debut"), errors="coerce")
        recent["year_month"] = recent.get("annee_mois", pd.Series("", index=recent.index)).fillna("").astype(str)
        invalid = recent["year_month"].isin(["NaT", "nan", ""])
        recent.loc[invalid, "year_month"] = (
            recent.loc[invalid, "year"].fillna(0).astype(int).astype(str)
            + "-"
            + recent.loc[invalid, "month"].fillna(0).astype(int).astype(str).str.zfill(2)
        )
        status = recent.get("statut", pd.Series("Autre", index=recent.index)).fillna("Autre").astype(str)
        def category(value: str) -> str:
            low = value.lower()
            if "rupture" in low:
                return "Rupture"
            if "tension" in low:
                return "Tension"
            if "remise" in low or "disposition" in low:
                return "Remise à disposition"
            if "arrêt" in low or "arret" in low:
                return "Arrêt de commercialisation"
            return "Autre"
        recent["event_category"] = status.map(category)
        recent["molecule_clean"] = recent.get("dci_norm", pd.Series("", index=recent.index)).fillna("").astype(str)
        recent["medicine"] = recent.get("nom_commercial", pd.Series("", index=recent.index)).fillna("").astype(str)
        recent["laboratory"] = "Non renseigné"
        recent["source"] = "ANSM disponibilités 2025–2026"
        frames.append(recent[["year", "month", "year_month", "event_category", "molecule_clean", "medicine", "laboratory", "source"]])

    events = pd.concat(frames, ignore_index=True)
    events["year"] = pd.to_numeric(events["year"], errors="coerce")
    events["month"] = pd.to_numeric(events["month"], errors="coerce")
    events = events.dropna(subset=["year", "month"])
    events["year"] = events["year"].astype(int)
    events["month"] = events["month"].astype(int)
    events = events[(events["year"] >= 2021) & (events["month"].between(1, 12))]
    events["year_month"] = events["year"].astype(str) + "-" + events["month"].astype(str).str.zfill(2)
    events = events.drop_duplicates(subset=["year", "month", "event_category", "molecule_clean", "medicine", "source"])
    return events


def aggregate_openmedic(silver: Path) -> dict[str, Any]:
    path = silver / "J0_silver_openmedic_2021_2025_20260607.csv"
    if not path.exists():
        # Fallback to the earlier documented filename when present.
        path = silver / "J0_silver_openmedic_2021_2025.csv"
    if not path.exists():
        raise FileNotFoundError("Silver OpenMedic introuvable.")

    usecols = ["ATC3", "L_ATC5", "BEN_REG", "annee", "BOITES", "REM_clean", "age", "sexe"]
    annual_parts: list[pd.DataFrame] = []
    region_parts: list[pd.DataFrame] = []
    molecule_parts: list[pd.DataFrame] = []
    demographic_parts: list[pd.DataFrame] = []
    processed_rows = 0

    for chunk in pd.read_csv(path, usecols=lambda c: c in usecols, chunksize=250_000, low_memory=False):
        if "ATC3" not in chunk.columns:
            raise ValueError("La colonne ATC3 est absente du Silver OpenMedic.")
        filtered = chunk[chunk["ATC3"].fillna("").astype(str).str.upper().str.startswith("R06")].copy()
        if filtered.empty:
            continue
        processed_rows += len(filtered)
        filtered["year"] = pd.to_numeric(filtered["annee"], errors="coerce")
        filtered["boxes"] = pd.to_numeric(filtered["BOITES"], errors="coerce").fillna(0)
        filtered["reimbursement_eur"] = pd.to_numeric(filtered.get("REM_clean"), errors="coerce").fillna(0)
        filtered["region"] = pd.to_numeric(filtered["BEN_REG"], errors="coerce").map(REGIONS).fillna("Non renseigné")
        filtered["molecule"] = filtered.get("L_ATC5", pd.Series("Non renseignée", index=filtered.index)).fillna("Non renseignée").astype(str).str.strip()
        age = pd.to_numeric(filtered.get("age"), errors="coerce")
        sex = pd.to_numeric(filtered.get("sexe"), errors="coerce")
        filtered["age_group"] = age.map(AGE_LABELS).fillna("Non renseigné")
        filtered["sex_group"] = sex.map(SEX_LABELS).fillna("Non renseigné")

        valid = filtered.dropna(subset=["year"]).copy()
        valid["year"] = valid["year"].astype(int)
        annual_parts.append(valid.groupby("year", as_index=False).agg(boxes=("boxes", "sum"), reimbursement_eur=("reimbursement_eur", "sum"), records=("boxes", "size")))
        region_parts.append(valid.groupby(["year", "region"], as_index=False).agg(boxes=("boxes", "sum")))
        molecule_parts.append(valid.groupby(["year", "molecule"], as_index=False).agg(boxes=("boxes", "sum")))
        demographic_parts.append(valid.groupby(["age_group", "sex_group"], as_index=False).agg(boxes=("boxes", "sum")))

    annual = compact_group(annual_parts, ["year"], {"boxes": "sum", "reimbursement_eur": "sum", "records": "sum"}).sort_values("year")
    regional = compact_group(region_parts, ["year", "region"], {"boxes": "sum"})
    if not regional.empty:
        regional["population"] = regional["region"].map(REGION_POP)
        regional["boxes_per_1000"] = np.where(regional["population"].notna(), regional["boxes"] / regional["population"] * 1000, np.nan)
        regional = regional.sort_values(["year", "boxes"], ascending=[True, False])
    molecules = compact_group(molecule_parts, ["year", "molecule"], {"boxes": "sum"}).sort_values("boxes", ascending=False)
    demographics = compact_group(demographic_parts, ["age_group", "sex_group"], {"boxes": "sum"}).sort_values("boxes", ascending=False)

    return {
        "rows_r06": int(processed_rows),
        "annual": records(annual),
        "regional": records(regional),
        "molecules": records(molecules, 100),
        "demographics": records(demographics),
        "top_molecules": records(molecules.groupby("molecule", as_index=False).boxes.sum().sort_values("boxes", ascending=False), 20),
    }


def aggregate_pollen(silver: Path) -> list[dict[str, Any]]:
    path = silver / "J0_silver_pollen_2021_2026.csv"
    if not path.exists():
        return []
    df = read_required(path)
    if "date" not in df.columns:
        return []
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    columns = [col for col in POLLEN_COLUMNS.values() if col in df.columns]
    if not columns:
        return []
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    group_keys = ["year_month"]
    if "source" in df.columns:
        group_keys.append("source")
    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Moyenne par jour/source pour éviter de pondérer les dates ayant davantage de stations.
    daily_keys = ["date"] + (["source"] if "source" in df.columns else [])
    daily = df.groupby(daily_keys, as_index=False)[columns].mean()
    daily["year_month"] = daily["date"].dt.to_period("M").astype(str)
    monthly = daily.groupby(group_keys, as_index=False)[columns].mean()
    rename = {value: key for key, value in POLLEN_COLUMNS.items()}
    return records(monthly.rename(columns=rename).sort_values("year_month"))


def aggregate_weather(silver: Path) -> list[dict[str, Any]]:
    path = silver / "J0_silver_meteo_openmeteo_2021_2026.csv"
    if not path.exists():
        return []
    df = read_required(path)
    date_col = "time" if "time" in df.columns else ("date" if "date" in df.columns else None)
    if not date_col:
        return []
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    df["year_month"] = df[date_col].dt.to_period("M").astype(str)
    fields = [c for c in ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min",
                          "precipitation_sum", "wind_speed_10m_max"] if c in df.columns]
    for col in fields:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "region" in df.columns:
        return records(df.groupby(["year_month", "region"], as_index=False)[fields].mean().sort_values("year_month"))
    return records(df.groupby("year_month", as_index=False)[fields].mean().sort_values("year_month"))


def aggregate_sentinelles(silver: Path) -> list[dict[str, Any]]:
    path = silver / "J0_silver_sentinelles.csv"
    if not path.exists():
        return []
    df = read_required(path)
    if "annee_mois" not in df.columns:
        return []
    keep = ["annee_mois"] + [c for c in df.columns if c.endswith("_inc100_moy") or c.endswith("_inc100_max")]
    return records(df[keep].sort_values("annee_mois"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    silver = args.source_dir

    medicines, medicine_summary = load_medicaments(silver)
    events = load_ruptures(silver)
    openmedic = aggregate_openmedic(silver)
    pollen = aggregate_pollen(silver)
    weather = aggregate_weather(silver)
    epidemiology = aggregate_sentinelles(silver)

    yearly_events = (events.groupby(["year", "event_category"], as_index=False)
                     .size().rename(columns={"size": "events"}).sort_values(["year", "event_category"]))
    monthly_events = (events.groupby(["year_month", "event_category"], as_index=False)
                      .size().rename(columns={"size": "events"}).sort_values(["year_month", "event_category"]))
    top_event_molecules = (events.groupby("molecule_clean", as_index=False).size()
                           .rename(columns={"molecule_clean": "molecule", "size": "events"})
                           .sort_values("events", ascending=False))
    recent_year = int(events["year"].max()) if not events.empty else None
    train_months = pd.period_range("2021-01", "2025-12", freq="M").astype(str)
    event_months = set(events.loc[events["year"].between(2021, 2025), "year_month"].unique())
    observed_months = len(event_months.intersection(set(train_months)))
    month_rate = observed_months / len(train_months) * 100 if len(train_months) else None

    annual = pd.DataFrame(openmedic["annual"])
    total_boxes = float(annual["boxes"].sum()) if not annual.empty else 0.0
    total_reimbursement = float(annual["reimbursement_eur"].sum()) if not annual.empty else 0.0

    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "origin": "Tables Silver du dépôt antihistaminiques-pipeline",
            "scope": "R06 / antihistaminiques",
            "openmedic_file": "J0_silver_openmedic_2021_2025_20260607.csv",
            "note": "Indicateurs agrégés à partir des tables Silver ; aucune ligne individuelle n'est publiée.",
        },
        "summary": {
            "medicine_specialties": medicine_summary["specialty_count"],
            "molecule_count": medicine_summary["molecule_count"],
            "laboratory_count": medicine_summary["laboratory_count"],
            "patient_volume_sum_across_specialties": medicine_summary["sum_patient_volume"],
            "total_boxes_2021_2025": number(total_boxes),
            "total_reimbursement_eur_2021_2025": number(total_reimbursement),
            "openmedic_r06_rows": openmedic["rows_r06"],
            "rupture_event_count": int(len(events)),
            "latest_event_year": recent_year,
            "months_with_event_2021_2025": int(observed_months),
            "months_in_training_window": int(len(train_months)),
            "month_with_event_rate_2021_2025": number(month_rate),
        },
        "medicines": medicine_summary,
        "consumption": openmedic,
        "ruptures": {
            "yearly": records(yearly_events),
            "monthly": records(monthly_events),
            "top_molecules": records(top_event_molecules, 20),
            "events": records(events.sort_values(["year", "month"], ascending=False), 500),
        },
        "pollen_monthly": pollen,
        "weather_monthly": weather,
        "epidemiology_monthly": epidemiology,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    temporary.replace(args.output)
    print(
        "Dashboard Silver généré : "
        f"{len(events)} événements, {openmedic['rows_r06']} lignes OpenMedic R06, "
        f"{medicine_summary['specialty_count']} spécialités, "
        f"{len(pollen)} agrégats pollen, {len(weather)} agrégats météo."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
