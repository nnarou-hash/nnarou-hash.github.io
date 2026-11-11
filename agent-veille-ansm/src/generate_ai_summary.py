#!/usr/bin/env python3
"""Résumé optionnel des évolutions publiques ANSM via l'API Responses d'OpenAI."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

INSTRUCTIONS = """Tu rédiges une synthèse factuelle en français d'un relevé public de disponibilité des médicaments ANSM.
Utilise exclusivement les données fournies. Ne déduis jamais les stocks réels, la durée d'une pénurie, un risque patient,
une cause, une date de retour ou une recommandation thérapeutique. Ne recommande jamais une substitution.
Distingue explicitement : état observé, changements par rapport au précédent relevé, limites et points à vérifier.
Une sortie de liste n'est pas une preuve de remise à disposition. Si l'historique est insuffisant, dis-le.
Rappelle que la liste concerne les MITM suivis par l'ANSM et que la source officielle doit être consultée.
Rédige des titres courts et des listes compactes. N'invente aucun chiffre."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Génère une synthèse IA des données publiques ANSM")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY absent : la synthèse IA n'a pas été générée.")

    snapshot_path = args.data_dir / "latest_snapshot.json"
    report_path = args.data_dir / "report.json"
    if not snapshot_path.exists() or not report_path.exists():
        raise SystemExit("Aucun relevé ANSM valide : exécuter la collecte avant le résumé IA.")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = {
        "source_url": snapshot.get("source_url"),
        "observed_at": snapshot.get("observed_at"),
        "record_count": snapshot.get("record_count"),
        "status_counts": report.get("status_counts", {}),
        "events_this_run": report.get("events_this_run", {}),
        "recent_events": report.get("recent_events", [])[-25:],
        "signals": [
            {
                "specialty": row.get("specialty"),
                "status": row.get("status"),
                "source_updated_at": row.get("source_updated_at"),
                "availability_date": row.get("availability_date"),
                "medical_domains": row.get("medical_domains"),
                "detail_url": row.get("detail_url"),
            }
            for row in snapshot.get("records", [])[:120]
        ],
    }

    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL", "gpt-6-luna")
    response = client.responses.create(
        model=model,
        instructions=INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False),
        store=False,
    )
    output = (response.output_text or "").strip()
    if not output:
        raise SystemExit("L'API n'a pas retourné de synthèse textuelle.")

    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    document = (
        "# Synthèse générée par IA\n\n"
        f"- Générée le : {stamp}\n"
        f"- Modèle : {model}\n"
        f"- Relevé analysé : {snapshot.get('observed_at', 'inconnu')}\n"
        f"- Source : {snapshot.get('source_url', '')}\n\n"
        "> Synthèse automatique des informations publiques. Elle ne remplace pas la consultation "
        "des publications officielles et ne constitue pas un avis médical.\n\n"
        + output
        + "\n"
    )
    (args.data_dir / "ai_summary.md").write_text(document, encoding="utf-8")
    (args.data_dir / "ai_summary_meta.json").write_text(
        json.dumps({"generated_at": stamp, "model": model, "snapshot_at": snapshot.get("observed_at")}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Synthèse IA enregistrée avec le modèle {model}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
