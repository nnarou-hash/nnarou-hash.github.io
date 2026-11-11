import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ansm_watch import (
    build_report,
    build_state,
    normalize_date,
    parse_availability_html,
    run_monitor,
)


FIXTURE = """<!doctype html>
<html lang="fr">
<body>
<table>
  <thead><tr>
    <th>Statut</th><th>Mise à jour</th><th>Spécialité</th>
    <th>Remise à disposition</th><th>Domaines médicaux</th>
  </tr></thead>
  <tbody>
    <tr><td>Tension d'approvisionnement</td><td>10/08/2026</td>
      <td><a href="/exemple/medicament-a">Médicament A 10 mg, comprimé</a></td>
      <td></td><td>Cardiologie</td></tr>
    <tr><td>Remise à disposition</td><td>08/08/2026</td>
      <td>Médicament B, solution injectable</td>
      <td>07/08/2026</td><td>Infectiologie, Hématologie</td></tr>
  </tbody>
</table>
</body></html>"""


class AnsmWatchTests(unittest.TestCase):
    def test_french_date_normalization(self):
        self.assertEqual(normalize_date("10/08/2026"), "2026-08-10")
        self.assertEqual(normalize_date(""), "")

    def test_real_column_names_and_detail_link(self):
        records = parse_availability_html(FIXTURE)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].specialty, "Médicament A 10 mg, comprimé")
        self.assertEqual(records[0].source_updated_at, "2026-08-10")
        self.assertEqual(
            records[0].detail_url,
            "https://ansm.sante.fr/exemple/medicament-a",
        )
        self.assertEqual(records[1].availability_date, "2026-08-07")

    def test_new_entries_are_logged(self):
        records = parse_availability_html(FIXTURE)
        snapshot, history, events = build_state(
            records, {"records": []}, {}, "2026-08-11T08:00:00+02:00"
        )
        self.assertEqual(snapshot["record_count"], 2)
        self.assertEqual(len(history["records"]), 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["event_type"] == "nouvelle_entree" for e in events))

    def test_status_change_is_detected(self):
        first_records = parse_availability_html(FIXTURE)
        first_snapshot, first_history, _ = build_state(
            first_records, {"records": []}, {}, "2026-08-11T08:00:00+02:00"
        )
        changed_html = FIXTURE.replace("Tension d'approvisionnement", "Rupture de stock", 1)
        second_records = parse_availability_html(changed_html)
        second_snapshot, second_history, events = build_state(
            second_records, first_snapshot, first_history["records"], "2026-08-12T08:00:00+02:00"
        )
        changed = [e for e in events if e["event_type"] == "modification"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["previous_status"], "Tension d'approvisionnement")
        self.assertEqual(changed[0]["current_status"], "Rupture de stock")
        self.assertEqual(
            second_snapshot["records"][0]["first_seen_at"],
            "2026-08-11T08:00:00+02:00",
        )
        self.assertEqual(len(second_history["records"]), 2)

    def test_disappearance_is_not_labeled_as_restored(self):
        first_records = parse_availability_html(FIXTURE)
        first_snapshot, first_history, _ = build_state(
            first_records, {"records": []}, {}, "2026-08-11T08:00:00+02:00"
        )
        only_one = parse_availability_html(FIXTURE.replace(
            '<tr><td>Remise à disposition</td><td>08/08/2026</td>\n      <td>Médicament B, solution injectable</td>\n      <td>07/08/2026</td><td>Infectiologie, Hématologie</td></tr>', ""
        ))
        snapshot, history, events = build_state(
            only_one, first_snapshot, first_history["records"], "2026-08-12T08:00:00+02:00"
        )
        removed = [e for e in events if e["event_type"] == "sortie_de_liste"]
        self.assertEqual(len(removed), 1)
        self.assertIn("Ne signifie pas", removed[0]["interpretation_note"])
        self.assertNotIn("retour à la normale", removed[0]["event_type"])

    def test_report_counts_statuses(self):
        records = parse_availability_html(FIXTURE)
        snapshot, history, events = build_state(records, {"records": []}, {}, "2026-08-11T08:00:00+02:00")
        report = build_report(snapshot, events)
        self.assertEqual(report["record_count"], 2)
        self.assertEqual(report["status_counts"]["Tension d'approvisionnement"], 1)
        self.assertEqual(report["events_this_run"]["nouvelle_entree"], 2)

    def test_unchanged_source_does_not_create_a_new_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch("ansm_watch.fetch_source", return_value=FIXTURE):
                first = run_monitor(data_dir)
                self.assertTrue(first["changed"])
                files_before = {
                    path.relative_to(data_dir).as_posix(): path.read_bytes()
                    for path in data_dir.rglob("*") if path.is_file()
                }
                second = run_monitor(data_dir)

            self.assertFalse(second["changed"])
            files_after = {
                path.relative_to(data_dir).as_posix(): path.read_bytes()
                for path in data_dir.rglob("*") if path.is_file()
            }
            self.assertEqual(files_after, files_before)

    def test_unexpected_html_fails_explicitly(self):
        with self.assertRaises(ValueError):
            parse_availability_html("<html><body>page indisponible</body></html>")


if __name__ == "__main__":
    unittest.main()
