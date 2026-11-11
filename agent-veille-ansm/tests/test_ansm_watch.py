import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ansm_watch import build_state, normalize_date, parse_availability_html


FIXTURE = """<!doctype html>
<html lang="fr">
  <body>
    <table>
      <thead>
        <tr>
          <th>Statut</th>
          <th>Mise à jour</th>
          <th>Spécialité</th>
          <th>Remise à disposition</th>
          <th>Domaines médicaux</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Tension d'approvisionnement</td>
          <td>10/08/2026</td>
          <td><a href="/exemple/medicament-a">Médicament A 10 mg, comprimé</a></td>
          <td></td>
          <td>Cardiologie</td>
        </tr>
        <tr>
          <td>Remise à disposition</td>
          <td>08/08/2026</td>
          <td>Médicament B, solution injectable</td>
          <td>07/08/2026</td>
          <td>Infectiologie, Hématologie</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


class AnsmWatchTests(unittest.TestCase):
    def test_french_date_normalization(self):
        self.assertEqual(normalize_date("10/08/2026"), "2026-08-10")
        self.assertEqual(normalize_date(""), "")

    def test_parse_expected_columns_and_links(self):
        records = parse_availability_html(FIXTURE)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].specialty, "Médicament A 10 mg, comprimé")
        self.assertEqual(records[0].source_updated_at, "2026-08-10")
        self.assertEqual(
            records[0].detail_url,
            "https://ansm.sante.fr/exemple/medicament-a",
        )
        self.assertEqual(records[1].availability_date, "2026-08-07")

    def test_build_state_detects_new_entries(self):
        records = parse_availability_html(FIXTURE)
        state, events = build_state(records, {"records": []}, "2026-08-11T08:00:00+02:00")
        self.assertEqual(len(state["records"]), 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event["event_type"] == "nouvelle_entree" for event in events))

    def test_build_state_detects_status_change_and_preserves_first_seen(self):
        records = parse_availability_html(FIXTURE)
        first_state, _ = build_state(records, {"records": []}, "2026-08-11T08:00:00+02:00")

        changed_html = FIXTURE.replace(
            "Tension d'approvisionnement",
            "Rupture de stock",
            1,
        )
        changed_records = parse_availability_html(changed_html)
        next_state, events = build_state(
            changed_records,
            first_state,
            "2026-08-12T08:00:00+02:00",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "modification")
        self.assertEqual(events[0]["previous_status"], "Tension d'approvisionnement")
        self.assertEqual(events[0]["current_status"], "Rupture de stock")
        self.assertEqual(
            next_state["records"][0]["first_seen_at"],
            "2026-08-11T08:00:00+02:00",
        )

    def test_missing_table_fails_loudly(self):
        with self.assertRaises(ValueError):
            parse_availability_html("<html><body>Page indisponible</body></html>")


if __name__ == "__main__":
    unittest.main()
