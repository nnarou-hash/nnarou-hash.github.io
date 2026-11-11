#!/usr/bin/env python3
"""Collecte et suivi des informations publiques de disponibilité des médicaments ANSM."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments"
USER_AGENT = "AgentVeillePenuriesANSM/0.1 (public-data monitoring prototype)"
TIMEOUT_SECONDS = 30

CSV_FIELDS = [
    "record_key",
    "status",
    "source_updated_at",
    "specialty",
    "availability_date",
    "medical_domains",
    "detail_url",
    "first_seen_at",
    "last_changed_at",
]

EVENT_FIELDS = [
    "event_at",
    "event_type",
    "record_key",
    "specialty",
    "previous_status",
    "current_status",
    "changed_fields",
    "source_url",
]


@dataclass(frozen=True)
class Signal:
    status: str
    source_updated_at: str
    specialty: str
    availability_date: str
    medical_domains: str
    detail_url: str
    record_key: str


def normalize_text(value: str) -> str:
    """Normalise un texte pour comparer les libellés et les en-têtes."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_date(value: str) -> str:
    """Convertit une date française JJ/MM/AAAA en AAAA-MM-JJ."""
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def make_record_key(specialty: str, medical_domains: str, detail_url: str) -> str:
    """Construit une clé stable sans dépendre de la position de la ligne."""
    identity = detail_url.strip() or (
        normalize_text(specialty) + "|" + normalize_text(medical_domains)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _cell_text(cell: Any) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def parse_availability_html(html: str, source_url: str = SOURCE_URL) -> list[Signal]:
    """Extrait les signaux du tableau de disponibilité publié par l'ANSM."""
    soup = BeautifulSoup(html, "html.parser")
    aliases = {
        "status": {"statut"},
        "source_updated_at": {"mise a jour"},
        "specialty": {"specialite"},
        "availability_date": {"remise a disposition"},
        "medical_domains": {"domaines medicaux"},
    }
    required = set(aliases)
    matching_table = None
    column_map: dict[str, int] = {}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"], recursive=False)
        headers = [normalize_text(_cell_text(cell)) for cell in header_cells]
        candidate: dict[str, int] = {}
        for field, names in aliases.items():
            for index, header in enumerate(headers):
                if header in names:
                    candidate[field] = index
                    break
        if required.issubset(candidate):
            matching_table = table
            column_map = candidate
            break

    if matching_table is None:
        raise ValueError(
            "Tableau ANSM introuvable : les en-têtes attendus ont peut-être changé. "
            "La collecte est arrêtée pour éviter de produire un export incomplet."
        )

    signals: list[Signal] = []
    for row in matching_table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        max_index = max(column_map.values())
        if len(cells) <= max_index:
            continue

        values = {
            field: _cell_text(cells[index])
            for field, index in column_map.items()
        }
        specialty_cell = cells[column_map["specialty"]]
        link = specialty_cell.find("a", href=True)
        detail_url = urljoin(source_url, link["href"]) if link else ""

        specialty = values["specialty"]
        if not specialty:
            continue

        medical_domains = values["medical_domains"]
        signal = Signal(
            status=values["status"],
            source_updated_at=normalize_date(values["source_updated_at"]),
            specialty=specialty,
            availability_date=normalize_date(values["availability_date"]),
            medical_domains=medical_domains,
            detail_url=detail_url,
            record_key=make_record_key(specialty, medical_domains, detail_url),
        )
        signals.append(signal)

    if not signals:
        raise ValueError(
            "Aucune entrée extraite du tableau ANSM. Vérifier la structure de la source."
        )

    # Une même entrée peut être répétée dans le HTML : on conserve une seule occurrence.
    unique: dict[str, Signal] = {}
    for signal in signals:
        unique[signal.record_key] = signal
    return sorted(unique.values(), key=lambda item: (item.specialty.casefold(), item.status))


def fetch_source(url: str = SOURCE_URL) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def load_previous_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"source_url": SOURCE_URL, "records": []}
    with state_path.open("r", encoding="utf-8") as file:
        state = json.load(file)
    if not isinstance(state, dict) or not isinstance(state.get("records"), list):
        raise ValueError("Le fichier d'état est invalide ; aucune donnée n'a été écrasée.")
    return state


def build_state(
    signals: list[Signal],
    previous_state: dict[str, Any],
    observed_at: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    previous = {
        item["record_key"]: item
        for item in previous_state.get("records", [])
        if isinstance(item, dict) and item.get("record_key")
    }

    current_records: list[dict[str, Any]] = []
    events: list[dict[str, str]] = []

    for signal in signals:
        current = asdict(signal)
        old = previous.get(signal.record_key)

        if old is None:
            current["first_seen_at"] = observed_at
            current["last_changed_at"] = observed_at
            event_type = "nouvelle_entree"
            previous_status = ""
            changed_fields = list(current.keys())
            events.append({
                "event_at": observed_at,
                "event_type": event_type,
                "record_key": signal.record_key,
                "specialty": signal.specialty,
                "previous_status": previous_status,
                "current_status": signal.status,
                "changed_fields": ", ".join(changed_fields),
                "source_url": SOURCE_URL,
            })
        else:
            compared_fields = [
                "status",
                "source_updated_at",
                "specialty",
                "availability_date",
                "medical_domains",
                "detail_url",
            ]
            changed_fields = [
                field for field in compared_fields if old.get(field, "") != current[field]
            ]
            current["first_seen_at"] = old.get("first_seen_at", observed_at)
            current["last_changed_at"] = (
                observed_at if changed_fields else old.get("last_changed_at", observed_at)
            )

            if changed_fields:
                events.append({
                    "event_at": observed_at,
                    "event_type": "modification",
                    "record_key": signal.record_key,
                    "specialty": signal.specialty,
                    "previous_status": str(old.get("status", "")),
                    "current_status": signal.status,
                    "changed_fields": ", ".join(changed_fields),
                    "source_url": SOURCE_URL,
                })

        current_records.append(current)

    new_state = {
        "source_url": SOURCE_URL,
        "last_successful_check": observed_at,
        "records": current_records,
    }
    return new_state, events


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def write_current_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def append_events_csv(path: Path, events: list[dict[str, str]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(events)


def run_monitor(data_dir: Path, url: str = SOURCE_URL) -> dict[str, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "latest_snapshot.json"
    current_csv_path = data_dir / "current_signals.csv"
    events_csv_path = data_dir / "events.csv"

    # Récupération et parsing avant toute écriture : en cas d'erreur source,
    # le dernier état valide reste intact.
    html = fetch_source(url)
    signals = parse_availability_html(html, source_url=url)
    previous_state = load_previous_state(state_path)
    observed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    new_state, events = build_state(signals, previous_state, observed_at)

    new_state["source_url"] = url
    for event in events:
        event["source_url"] = url

    write_json(state_path, new_state)
    write_current_csv(current_csv_path, new_state["records"])
    append_events_csv(events_csv_path, events)

    return {
        "signals": len(signals),
        "new_entries": sum(event["event_type"] == "nouvelle_entree" for event in events),
        "modifications": sum(event["event_type"] == "modification" for event in events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Veille des disponibilités publiées par l'ANSM")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Dossier de sortie des snapshots et journaux CSV",
    )
    parser.add_argument("--url", default=SOURCE_URL, help="URL de la source ANSM")
    args = parser.parse_args()

    try:
        summary = run_monitor(args.data_dir, url=args.url)
    except (requests.RequestException, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERREUR — collecte ANSM interrompue : {exc}", file=sys.stderr)
        return 1

    print(
        "Collecte ANSM terminée : "
        f"{summary['signals']} entrées, "
        f"{summary['new_entries']} nouvelle(s), "
        f"{summary['modifications']} modification(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
