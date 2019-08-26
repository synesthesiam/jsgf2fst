import io
from glob import glob
import unittest
import logging
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)

from jsgf2fst import (
    jsgf2fst,
    fstaccept,
    read_slots,
    fst2arpa,
    fstprintall,
    make_intent_fst,
)


class Jsgf2FstTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    # -------------------------------------------------------------------------

    def test_timer(self):
        timer_fst = jsgf2fst(Path("test/SetTimer.gram"))
        self.assertGreater(len(list(timer_fst.states())), 0)

        intents = fstaccept(
            timer_fst,
            "set a timer for ten minutes and forty two seconds",
            intent_name="SetTimer",
        )

        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "SetTimer")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 2)

        # Verify text with replacements
        text = intent["text"]
        self.assertEqual(text, "set a timer for 10 minutes and 40 2 seconds")

        # Verify "raw" text (no replacements)
        raw_text = intent["raw_text"]
        self.assertEqual(raw_text, "set a timer for ten minutes and forty two seconds")

        # Verify individual entities
        expected = {"minutes": "10", "seconds": "40 2"}
        raw_expected = {"minutes": "ten", "seconds": "forty two"}

        for ev in intent["entities"]:
            entity = ev["entity"]
            if (entity in expected) and (ev["value"] == expected[entity]):
                # Check start/end inside text
                start, end = ev["start"], ev["end"]
                self.assertEqual(text[start:end], ev["value"])
                expected.pop(entity)

            if (entity in raw_expected) and (ev["raw_value"] == raw_expected[entity]):
                raw_expected.pop(entity)

        self.assertDictEqual(expected, {})
        self.assertDictEqual(raw_expected, {})

        # Verify number of sentences (takes a long time)
        logging.debug("Counting all possible test sentences...")
        sentences = fstprintall(timer_fst, exclude_meta=False)
        self.assertEqual(len(sentences), 2 * (59 * (1 + (2 * 59))))

    # -------------------------------------------------------------------------

    def test_slots(self):
        slots = read_slots("test/slots")
        fst = jsgf2fst(Path("test/ChangeLightColor.gram"), slots=slots)
        self.assertGreater(len(list(fst.states())), 0)

        intents = fstaccept(fst, "set color to orange", intent_name="ChangeLightColor")
        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "ChangeLightColor")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 1)

        ev = intent["entities"][0]
        self.assertEqual(ev["entity"], "color")
        self.assertEqual(ev["value"], "orange")

    # -------------------------------------------------------------------------

    def test_reference(self):
        slots = read_slots("test/slots")
        fsts = jsgf2fst(
            [Path("test/ChangeLight.gram"), Path("test/ChangeLightColor.gram")],
            slots=slots,
        )
        fst = fsts["ChangeLight"]
        self.assertGreater(len(list(fst.states())), 0)

        # Change state
        intents = fstaccept(fst, "turn off", intent_name="ChangeLight")
        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "ChangeLight")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 1)

        ev = intent["entities"][0]
        self.assertEqual(ev["entity"], "state")
        self.assertEqual(ev["value"], "off")

        # Change color
        intents = fstaccept(fst, "set color to orange", intent_name="ChangeLight")
        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "ChangeLight")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 1)

        ev = intent["entities"][0]
        self.assertEqual(ev["entity"], "color")
        self.assertEqual(ev["value"], "orange")

    # -------------------------------------------------------------------------

    def test_arpa(self):
        fst = jsgf2fst(Path("test/SetTimer.gram"))
        self.assertGreater(len(list(fst.states())), 0)

        with tempfile.NamedTemporaryFile(mode="wb+") as fst_file:
            fst.write(fst_file.name)

            fst_file.seek(0)
            arpa = fst2arpa(fst_file.name)
            self.assertGreater(len(arpa), 0)

    # -------------------------------------------------------------------------

    def test_printall(self):
        slots = read_slots("test/slots")
        fst = jsgf2fst(Path("test/ChangeLightColor.gram"), slots=slots)
        self.assertGreater(len(list(fst.states())), 0)
        sentences = fstprintall(fst, exclude_meta=False)
        self.assertEqual(len(sentences), 12)

        # Verify all sentences have intent/entity meta tokens
        for sentence in sentences:
            self.assertIn("__begin__color", sentence)
            self.assertIn("__end__color", sentence)

    # -------------------------------------------------------------------------

    def test_end_disjunction(self):
        fst = jsgf2fst(Path("test/GetGarageState.gram"))
        self.assertGreater(len(list(fst.states())), 0)
        sentences = fstprintall(fst, exclude_meta=False)
        self.assertEqual(len(sentences), 2)

        # Join strings
        sentences = [" ".join(s) for s in sentences]

        self.assertIn("is the garage door open", sentences)
        self.assertIn("is the garage door closed", sentences)

    # -------------------------------------------------------------------------

    def test_intent_fst(self):
        slots = read_slots("test/slots")
        grammar_fsts = jsgf2fst(Path("test").glob("*.gram"), slots=slots)
        intent_fst = make_intent_fst(grammar_fsts)

        # Check timer input
        intents = fstaccept(
            intent_fst, "set a timer for ten minutes and forty two seconds"
        )

        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "SetTimer")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 2)

        expected = {"minutes": "10", "seconds": "40 2"}
        for ev in intent["entities"]:
            entity = ev["entity"]
            if (entity in expected) and (ev["value"] == expected[entity]):
                expected.pop(entity)

        self.assertDictEqual(expected, {})

        # Verify multiple interpretations
        intents = fstaccept(intent_fst, "set color to purple")

        logging.debug(intents)
        self.assertEqual(len(intents), 2)

        for intent in intents:
            self.assertIn(intent["intent"]["name"], ["ChangeLight", "ChangeLightColor"])
            self.assertEqual(intent["intent"]["confidence"], 0.5)
            self.assertEqual(len(intent["entities"]), 1)

            ev = intent["entities"][0]
            self.assertEqual(ev["entity"], "color")
            self.assertEqual(ev["value"], "purple")


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
