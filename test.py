import unittest
import logging

logging.basicConfig(level=logging.DEBUG)

import jsgf
from jsgf2fst import jsgf2fst, fstaccept, read_slots


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

        intent = fstaccept(
            fst,
            "set a timer for one hour and ten minutes and forty two seconds",
            intent_name="SetTimer",
        )

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

        intent = fstaccept(fst, "set color to orange", intent_name="ChangeLightColor")

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
        intent = fstaccept(fst, "turn off", intent_name="ChangeLight")

        logging.debug(intent)
        assert intent["intent"]["name"] == "ChangeLight"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 1

        ev = intent["entities"][0]
        assert ev["entity"] == "state"
        assert ev["value"] == "off"

        # Change color
        intent = fstaccept(fst, "set color to orange", intent_name="ChangeLight")

        logging.debug(intent)
        assert intent["intent"]["name"] == "ChangeLight"
        assert intent["intent"]["confidence"] == 1
        assert len(intent["entities"]) == 1

        ev = intent["entities"][0]
        assert ev["entity"] == "color"
        assert ev["value"] == "orange"


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
