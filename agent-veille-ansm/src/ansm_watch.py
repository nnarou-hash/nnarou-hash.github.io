#!/usr/bin/env python3
"""Collecte, normalisation et historisation des informations publiques ANSM."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments"
USER_AGENT = "AgentVeillePenuriesANSM/1.0 (+https://github.com/nnarou-hash/nnarou-hash.github.io)"
TIMEOUT_SECONDS = 40

CURRENT_FIELDS = [
    "record_key", "status", "source_updated_at", "specialty",
    "availability_date", "medical_domains", "detail_url",
    "first_seen_at", "last_seen_at", "last_changed_at",
]
EVENT_FIELDS = [
    "event_at", "event_type", "record_key", "specialty",
    "previous_status", "current_status", "changed_fields",
    "source_url", "interpretation_note",
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
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def make_record_key(specialty: str, medical_domains: str, detail_url: str) -> str:
    identity = detail_url.strip() or (
        normalize_text(specialty) + "|" + normalize_text(medical_domains)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _cell_text(cell: Any) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def parse_availability_html(html: str, source_url: str = SOURCE_URL) -> list[Signal]:
    """Parse le tableau public ANSM. Échoue explicitement si sa structure change."""
    soup = BeautifulSoup(html, "html.parser")
    aliases = {
        "status": {"statut"},
        "source_updated_at": {"mise a jour"},
        "specialty": {"specialite"},
        "availability_date": {"remise a disposition"},
        "medical_domains": {"domaines medicaux"},
    }
    required = set(aliases)
    selected_table = None
    selected_headers: dict[str, int] = {}
    selected_header_row = -1

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row_index, row in enumerate(rows[:5]):
            cells = row.find_all(["th", "td"], recursive=False)
            headers = [normalize_text(_cell_text(cell)) for cell in cells]
            candidate: dict[str, int] = {}
            for field, accepted in aliases.items():
                for index, header in enumerate(headers):
                    if header in accepted:
                        candidate[field] = index
                        break
            if required.issubset(candidate):
                selected_table = table
                selected_headers = candidate
                selected_header_row = row_index
                break
        if selected_table is not None:
            break

    if selected_table is None:
        raise ValueError(
            "Tableau ANSM introuvable ou en-têtes modifiés. "
            "Collecte interrompue : aucun ancien instantané n'a été remplacé."
        )

    signals: list[Signal] = []
    rows = selected_table.find_all("tr")
    for row in rows[selected_header_row + 1:]:
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells or len(cells) <= max(selected_headers.values()):
            continue
        values = {
            field: _cell_text(cells[index])
            for field, index in selected_headers.items()
        }
        specialty = values["specialty"]
        if not specialty:
            continue

        specialty_cell = cells[selected_headers["specialty"]]
        link = specialty_cell.find("a", href=True)
        detail_url = urljoin(source_url, link["href"]) if link else ""
        medical_domains = values["medical_domains"]
        signals.append(Signal(
            status=values["status"],
            source_updated_at=normalize_date(values["source_updated_at"]),
            specialty=specialty,
            availability_date=normalize_date(values["availability_date"]),
            medical_domains=medical_domains,
            detail_url=detail_url,
            record_key=make_record_key(specialty, medical_domains, detail_url),
        ))

    if not signals:
        raise ValueError(
            "Le tableau ANSM a été identifié mais aucune spécialité n'a été extraite. "
            "Collecte interrompue pour éviter de publier un tableau vide."
        )

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


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def append_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    has_content = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        if not has_content:
            writer.writeheader()
        writer.writerows(rows)


def write_current_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CURRENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(path)


def build_state(
    signals: list[Signal],
    previous_snapshot: dict[str, Any],
    previous_history: dict[str, Any],
    observed_at: str,
    source_url: str = SOURCE_URL,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    """Construit le nouvel état et les événements sans interpréter une disparition comme une rupture résolue."""
    history = dict(previous_history)
    previous_current = {
        item["record_key"]: item
        for item in previous_snapshot.get("records", [])
        if isinstance(item, dict) and item.get("record_key")
    }
    current_records: list[dict[str, Any]] = []
    events: list[dict[str, str]] = []
    current_keys: set[str] = set()

    for signal in signals:
        current_keys.add(signal.record_key)
        current = asdict(signal)
        old_history = history.get(signal.record_key)
        old_current = previous_current.get(signal.record_key)
        if old_history is None:
            current["first_seen_at"] = observed_at
            current["last_seen_at"] = observed_at
            current["last_changed_at"] = observed_at
            event_type = "nouvelle_entree"
            events.append({
                "event_at": observed_at,
                "event_type": event_type,
                "record_key": signal.record_key,
                "specialty": signal.specialty,
                "previous_status": "",
                "current_status": signal.status,
                "changed_fields": "entrée observée pour la première fois",
                "source_url": source_url,
                "interpretation_note": "Nouvelle entrée dans la liste publique observée par le collecteur.",
            })
        else:
            compared = [
                "status", "source_updated_at", "specialty",
                "availability_date", "medical_domains", "detail_url",
            ]
            baseline = old_current or old_history
            changed = [field for field in compared if baseline.get(field, "") != current[field]]
            current["first_seen_at"] = old_history.get("first_seen_at", observed_at)
            current["last_seen_at"] = observed_at
            current["last_changed_at"] = observed_at if changed else old_history.get("last_changed_at", observed_at)
            if changed:
                events.append({
                    "event_at": observed_at,
                    "event_type": "modification",
                    "record_key": signal.record_key,
                    "specialty": signal.specialty,
                    "previous_status": str(baseline.get("status", "")),
                    "current_status": signal.status,
                    "changed_fields": ", ".join(changed),
                    "source_url": source_url,
                    "interpretation_note": "Modification des informations publiées ; vérifier le détail sur la page ANSM.",
                })

        current["listed_in_latest_snapshot"] = True
        history[signal.record_key] = dict(current)
        current_records.append(current)

    # Une disparition de la liste est enregistrée comme telle, sans supposer une remise à disposition.
    previous_keys = set(previous_current)
    for missing_key in sorted(previous_keys - current_keys):
        old = previous_current[missing_key]
        hist = dict(history.get(missing_key, old))
        hist["listed_in_latest_snapshot"] = False
        history[missing_key] = hist
        events.append({
            "event_at": observed_at,
            "event_type": "sortie_de_liste",
            "record_key": missing_key,
            "specialty": str(old.get("specialty", "")),
            "previous_status": str(old.get("status", "")),
            "current_status": "",
            "changed_fields": "entrée absente du dernier instantané",
            "source_url": source_url,
            "interpretation_note": "Sortie de la liste observée. Ne signifie pas à elle seule que la disponibilité est rétablie.",
        })

    current_records.sort(key=lambda row: (row["specialty"].casefold(), row["status"]))
    snapshot = {
        "source_url": source_url,
        "observed_at": observed_at,
        "record_count": len(current_records),
        "records": current_records,
    }
    history_payload = {
        "source_url": source_url,
        "updated_at": observed_at,
        "records": history,
    }
    return snapshot, history_payload, events


def build_report(snapshot: dict[str, Any], events: list[dict[str, str]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    for row in snapshot["records"]:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        for domain in [part.strip() for part in row["medical_domains"].split(",") if part.strip()]:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
    return {
        "source_url": snapshot["source_url"],
        "observed_at": snapshot["observed_at"],
        "record_count": snapshot["record_count"],
        "status_counts": dict(sorted(status_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))),
        "events_this_run": {
            "nouvelle_entree": sum(e["event_type"] == "nouvelle_entree" for e in events),
            "modification": sum(e["event_type"] == "modification" for e in events),
            "sortie_de_liste": sum(e["event_type"] == "sortie_de_liste" for e in events),
        },
        "recent_events": events[-30:],
        "scope_note": (
            "La liste ANSM porte sur les médicaments d'intérêt thérapeutique majeur (MITM) "
            "suivis par l'ANSM et les situations récemment normalisées. "
            "Une sortie de liste n'est pas une preuve de retour à la normale."
        ),
    }


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Rapport de veille ANSM",
        "",
        f"- Dernière collecte réussie : {report['observed_at']}",
        f"- Entrées publiées : {report['record_count']}",
        f"- Source : {report['source_url']}",
        "",
        "## Répartition par statut",
        "",
    ]
    lines.extend(f"- {status} : {count}" for status, count in report["status_counts"].items())
    lines += ["", "## Changements détectés lors de cette collecte", ""]
    events = report["events_this_run"]
    lines += [
        f"- Nouvelles entrées : {events['nouvelle_entree']}",
        f"- Modifications : {events['modification']}",
        f"- Sorties de liste : {events['sortie_de_liste']}",
        "",
        "## Limite d'interprétation",
        "",
        report["scope_note"],
        "",
        "Les informations doivent être vérifiées sur la page officielle avant toute décision.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_monitor(data_dir: Path, url: str = SOURCE_URL) -> dict[str, Any]:
    data_dir.mkdir(parents=True, exist_ok=True)
    # Collecte et parsing avant les écritures : en cas d'erreur, l'état validé est conservé.
    html = fetch_source(url)
    signals = parse_availability_html(html, source_url=url)

    previous_snapshot = read_json(data_dir / "latest_snapshot.json", {"records": []})
    history_doc = read_json(data_dir / "history_index.json", {"records": {}})
    if not isinstance(history_doc, dict) or not isinstance(history_doc.get("records", {}), dict):
        raise ValueError("L'index d'historique est invalide ; aucune donnée ne sera remplacée.")
    history = history_doc.get("records", {})

    observed_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    snapshot, new_history, events = build_state(
        signals, previous_snapshot, history, observed_at, source_url=url
    )
    report = build_report(snapshot, events)

    # Instantané immuable par collecte (heure UTC dans le nom).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(data_dir / "snapshots" / f"{stamp}.json", snapshot)
    write_json(data_dir / "latest_snapshot.json", snapshot)
    write_json(data_dir / "history_index.json", new_history)
    write_json(data_dir / "report.json", report)
    write_current_csv(data_dir / "current_signals.csv", snapshot["records"])
    append_csv(data_dir / "events.csv", EVENT_FIELDS, events)
    write_markdown_report(data_dir / "report.md", report)

    return {
        "signals": len(signals),
        "new_entries": report["events_this_run"]["nouvelle_entree"],
        "modifications": report["events_this_run"]["modification"],
        "removed_from_list": report["events_this_run"]["sortie_de_liste"],
        "observed_at": observed_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Veille documentaire des disponibilités publiées par l'ANSM")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--url", default=SOURCE_URL)
    args = parser.parse_args()
    try:
        summary = run_monitor(args.data_dir, url=args.url)
    except (requests.RequestException, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERREUR — collecte ANSM interrompue : {exc}", file=sys.stderr)
        return 1
    print(
        f"Collecte ANSM réussie : {summary['signals']} entrée(s), "
        f"{summary['new_entries']} nouvelle(s), {summary['modifications']} modification(s), "
        f"{summary['removed_from_list']} sortie(s) de liste."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
