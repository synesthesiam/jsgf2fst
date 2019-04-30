#!/usr/bin/env python3
import os
import sys
import argparse
import re
import subprocess
import tempfile
import shutil
import logging

import jsgf
import pywrapfst as fst


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser("jsgf2fst")
    parser.add_argument("grammars", nargs="+", help="JSGF grammars to convert")
    parser.add_argument("--out-dir", default=".", help="Directory to write FST files")
    parser.add_argument(
        "--slots-dir", default=None, help="Directory to read slot files"
    )
    parser.add_argument("--no-slots", action="store_true", help="Don't expand $slots")
    args = parser.parse_args()

    # Create output directory
    os.makedirs(args.out_dir, exist_ok=True)

    # Load JSGF grammars
    grammars = []
    for grammar_path in args.grammars:
        logging.debug(f"Parsing {grammar_path}")
        grammars.append(jsgf.parse_grammar_file(grammar_path))

    # Directory where slot values are stored ($slot_name -> dir/slot_name)
    slots = {}

    if not args.no_slots and args.slots_dir:
        # Load all slot values
        for slot_path in os.listdir(args.slots_dir):
            slot_name = os.path.splitext(slot_path)[0]
            slot_path = os.path.join(args.slots_dir, slot_path)
            with open(slot_path, "r") as slot_file:
                slots[slot_name] = [line.strip().lower() for line in slot_file]

    # Convert to FSTs
    grammar_fsts = jsgf2fst(grammars, slots=slots)

    # Write FSTs
    for grammar_name, grammar_fst in grammar_fsts.items():
        fst_path = os.path.abspath(os.path.join(args.out_dir, f"{grammar_name}.fst"))
        grammar_fst.write(fst_path)
        logging.info(f"Wrote to {fst_path}")


# -----------------------------------------------------------------------------


def jsgf2fst(grammars, slots={}):
    """Converts JSGF grammars to FSTs.
    Returns dictionary mapping grammar names to FSTs."""

    # grammar name -> fst
    grammar_fsts = {}

    if not shutil.which("sphinx_jsgf2fsg"):
        logging.fatal("Missing sphinx_jsgf2fst (expected in PATH)")
        sys.exit(1)

    # Gather map of all grammar rules
    global_rule_map = {
        f"{grammar.name}.{rule.name}": rule
        for grammar in grammars
        for rule in grammar.rules
    }

    # Process each grammar
    for grammar in grammars:
        logging.debug(f"Processing {grammar.name}")
        top_rule = grammar.get_rule_from_name(grammar.name)
        rule_map = {rule.name: rule for rule in grammar.rules}
        for name, rule in global_rule_map.items():
            rule_map[name] = rule

        # Expand referenced rules and replace tags with __begin__/__end__
        replace_tags_and_rules(top_rule, rule_map, slots=slots)
        new_grammar_string = grammar.compile()

        logging.debug(f"Converting to FST")

        # Convert JSGF to Sphinx FSM.
        # ASsumes sphinx_jsgf2fsg is in PATH.
        with tempfile.NamedTemporaryFile(mode="w+") as fsm_file:
            proc = subprocess.run(
                ["sphinx_jsgf2fsg", "-jsgf", "/dev/stdin", "-fsm", fsm_file.name],
                input=new_grammar_string.encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Convert to fst
            sym_table = fst.SymbolTable()
            sym_table.add_symbol("<eps>", 0)
            compiler = fst.Compiler(
                isymbols=sym_table,
                osymbols=sym_table,
                keep_isymbols=True,
                keep_osymbols=True,
            )

            # Rewind temp file
            fsm_file.seek(0)
            for line in fsm_file:
                line = line.strip()
                parts = re.split(r"\s+", line)

                if len(parts) == 2:
                    # Final state
                    print(line, file=compiler)
                else:
                    # FROM_STATE TO_STATE SYMBOL
                    sym = parts[2]
                    sym_table.add_symbol(sym)

                    if sym.startswith("__"):
                        # Tag (__begin__/__end__ surrounding content)
                        print(f"{parts[0]} {parts[1]} <eps> {sym}", file=compiler)
                    else:
                        # Regular transition
                        print(f"{parts[0]} {parts[1]} {sym} {sym}", file=compiler)

            grammar_fst = compiler.compile()
            grammar_fsts[grammar.name] = grammar_fst

    return grammar_fsts


# -----------------------------------------------------------------------------


def replace_tags_and_rules(rule, rule_map, slots={}):
    """Replace named rules from other grammars with their expansions.
    Replace tags with sequences of __begin__TAG ... __end__TAG."""
    if isinstance(rule, jsgf.rules.Rule):
        # Unpack
        return replace_tags_and_rules(rule.expansion, rule_map, slots=slots)
    else:
        # Extract tag
        tag = rule.tag
        if tag and len(tag) == 0:
            tag = None

        if tag:
            # Replace with __begin__/__end__ sequence
            rule.tag = None
            tag_seq = jsgf.expansions.Sequence()
            tag_seq.children.extend(
                [
                    jsgf.expansions.Literal(f"__begin__{tag}"),
                    replace_tags_and_rules(rule, rule_map, slots=slots),
                    jsgf.expansions.Literal(f"__end__{tag}"),
                ]
            )
            return tag_seq

        if isinstance(rule, jsgf.expansions.NamedRuleRef):
            # <OtherGrammar.otherRule>
            ref_rule = rule_map.get(rule.name, None)
            if ref_rule is None:
                grammar_name = rule.rule.grammar.name
                ref_rule = rule_map[f"{grammar_name}.{rule.name}"]

            # Expand rule
            return replace_tags_and_rules(ref_rule.expansion, rule_map, slots=slots)
        elif isinstance(rule, jsgf.expansions.Literal):
            if rule.text.startswith("$"):
                # $slot -> (all | slot | values)
                slot_name = rule.text[1:]
                if slot_name in slots:
                    logging.debug(f"Replacing slot {slot_name}")

                    # Replace with alternative set of values
                    slot_alt = jsgf.expansions.AlternativeSet()
                    for slot_value in slots[slot_name]:
                        slot_alt.children.append(jsgf.expansions.Literal(slot_value))

                    return slot_alt

            return rule
        elif hasattr(rule, "children"):
            # Replace children
            rule.children = [
                replace_tags_and_rules(child, rule_map, slots=slots)
                for child in rule.children
            ]

            return rule
        elif hasattr(rule, "child"):
            # Replace child
            rule.child = replace_tags_and_rules(rule.child, rule_map, slots=slots)
            return rule
        else:
            # Unsupported
            assert False, rule.__class__


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
