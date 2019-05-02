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
        assert len(list(fst.states())) > 0, "Empty FST"

        intents = fstaccept(
            fst,
            "set a timer for one hour and ten minutes and forty two seconds",
            intent_name="SetTimer",
        )

        intent = intents[0]

        logging.debug(intent)
        assert intent["intent"]["name"] == "SetTimer"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 3

        expected = {"hours": "one", "minutes": "ten", "seconds": "forty two"}
        for ev in intent["entities"]:
            entity = ev["entity"]
            if (entity in expected) and (ev["value"] == expected[entity]):
                expected.pop(entity)

        assert len(expected) == 0, expected

    # -------------------------------------------------------------------------

    def test_slots(self):
        grammar = jsgf.parse_grammar_file("test/ChangeLightColor.gram")
        slots = read_slots("test/slots")
        fst = jsgf2fst(grammar, slots=slots)
        assert len(list(fst.states())) > 0, "Empty FST"

        intents = fstaccept(fst, "set color to orange", intent_name="ChangeLightColor")
        intent = intents[0]

        logging.debug(intent)
        assert intent["intent"]["name"] == "ChangeLightColor"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 1

        ev = intent["entities"][0]
        assert ev["entity"] == "color"
        assert ev["value"] == "orange"

    # -------------------------------------------------------------------------

    def test_reference(self):
        grammars = [
            jsgf.parse_grammar_file(p)
            for p in ["test/ChangeLight.gram", "test/ChangeLightColor.gram"]
        ]
        slots = read_slots("test/slots")
        fsts = jsgf2fst(grammars, slots=slots)
        fst = fsts["ChangeLight"]
        assert len(list(fst.states())) > 0, "Empty FST"

        # Change state
        intents = fstaccept(fst, "turn off", intent_name="ChangeLight")
        intent = intents[0]

        logging.debug(intent)
        assert intent["intent"]["name"] == "ChangeLight"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 1

        ev = intent["entities"][0]
        assert ev["entity"] == "state"
        assert ev["value"] == "off"

        # Change color
        intents = fstaccept(fst, "set color to orange", intent_name="ChangeLight")
        intent = intents[0]

        logging.debug(intent)
        assert intent["intent"]["name"] == "ChangeLight"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 1

        ev = intent["entities"][0]
        assert ev["entity"] == "color"
        assert ev["value"] == "orange"

    # -------------------------------------------------------------------------

    def test_arpa(self):
        grammar = jsgf.parse_grammar_file("test/SetTimer.gram")
        fst = jsgf2fst(grammar)
        assert len(list(fst.states())) > 0, "Empty FST"

        with tempfile.NamedTemporaryFile(mode="wb+") as fst_file:
            fst.write(fst_file.name)

            fst_file.seek(0)
            arpa = fst2arpa(fst_file.name)
            assert len(arpa) > 0, "Empty ARPA"

    # -------------------------------------------------------------------------

    def test_printall(self):
        grammar = jsgf.parse_grammar_file("test/ChangeLightColor.gram")
        slots = read_slots("test/slots")
        fst = jsgf2fst(grammar, slots=slots)
        assert len(list(fst.states())) > 0, "Empty FST"
        sentences = fstprintall(fst)
        assert len(sentences) == 6, len(sentences)

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
        assert intent["intent"]["name"] == "SetTimer"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 3

        expected = {"hours": "one", "minutes": "ten", "seconds": "forty two"}
        for ev in intent["entities"]:
            entity = ev["entity"]
            if (entity in expected) and (ev["value"] == expected[entity]):
                expected.pop(entity)

        assert len(expected) == 0, expected

        # Verify multiple interpretations
        intents = fstaccept(
            intent_fst, "set color to purple"
        )

        logging.debug(intents)
        assert len(intents) == 2, "Expected multiple intents"

        for intent in intents:
            assert intent["intent"]["name"] in ["ChangeLight", "ChangeLightColor"]
            assert intent["intent"]["confidence"] < 1
            assert len(intent["entities"]) == 1

            ev = intent["entities"][0]
            assert ev["entity"] == "color"
            assert ev["value"] == "purple"


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
