import io
from glob import glob
import unittest
import logging
import tempfile

logging.basicConfig(level=logging.DEBUG)

import jsgf
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
        grammar = jsgf.parse_grammar_file("test/SetTimer.gram")
        fst = jsgf2fst(grammar)
        self.assertGreater(len(list(fst.states())), 0)

        intents = fstaccept(
            fst,
            "set a timer for one hour and ten minutes and forty two seconds",
            intent_name="SetTimer",
        )

        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "SetTimer")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 3)

        text = intent["text"]
        expected = {"hours": "one", "minutes": "ten", "seconds": "forty two"}
        for ev in intent["entities"]:
            entity = ev["entity"]
            if (entity in expected) and (ev["value"] == expected[entity]):
                start, end = ev["start"], ev["end"]
                self.assertEqual(text[start:end], ev["value"])
                expected.pop(entity)

        self.assertDictEqual(expected, {})

    # -------------------------------------------------------------------------

    def test_slots(self):
        grammar = jsgf.parse_grammar_file("test/ChangeLightColor.gram")
        slots = read_slots("test/slots")
        fst = jsgf2fst(grammar, slots=slots)
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
        grammars = [
            jsgf.parse_grammar_file(p)
            for p in ["test/ChangeLight.gram", "test/ChangeLightColor.gram"]
        ]
        slots = read_slots("test/slots")
        fsts = jsgf2fst(grammars, slots=slots)
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
        grammar = jsgf.parse_grammar_file("test/SetTimer.gram")
        fst = jsgf2fst(grammar)
        self.assertGreater(len(list(fst.states())), 0)

        with tempfile.NamedTemporaryFile(mode="wb+") as fst_file:
            fst.write(fst_file.name)

            fst_file.seek(0)
            arpa = fst2arpa(fst_file.name)
            self.assertGreater(len(arpa), 0)

    # -------------------------------------------------------------------------

    def test_printall(self):
        grammar = jsgf.parse_grammar_file("test/ChangeLightColor.gram")
        slots = read_slots("test/slots")
        fst = jsgf2fst(grammar, slots=slots)
        self.assertGreater(len(list(fst.states())), 0)
        sentences = fstprintall(fst, exclude_meta=False)
        self.assertEqual(len(sentences), 12)

        # Verify all sentences have intent/entity meta tokens
        for sentence in sentences:
            self.assertIn("__begin__color", sentence)
            self.assertIn("__end__color", sentence)

    # -------------------------------------------------------------------------

    def test_intent_fst(self):
        grammars = [jsgf.parse_grammar_file(p) for p in glob("test/*.gram")]
        slots = read_slots("test/slots")
        grammar_fsts = jsgf2fst(grammars, slots=slots)
        intent_fst = make_intent_fst(grammar_fsts)

        # Check timer input
        intents = fstaccept(
            intent_fst, "set a timer for one hour and ten minutes and forty two seconds"
        )

        intent = intents[0]

        logging.debug(intent)
        self.assertEqual(intent["intent"]["name"], "SetTimer")
        self.assertEqual(intent["intent"]["confidence"], 1)
        self.assertEqual(len(intent["entities"]), 3)

        expected = {"hours": "one", "minutes": "ten", "seconds": "forty two"}
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
