#!/usr/bin/env python3
import os
import sys
import argparse
import re
import subprocess
import tempfile
import shutil
import logging

logging.basicConfig(level=logging.DEBUG)

import jsgf
import pywrapfst as fst


def main():
    parser = argparse.ArgumentParser("jsgf2fst")
    parser.add_argument("grammars", nargs="+", help="JSGF grammars to convert")
    parser.add_argument("--out-dir", default=".", help="Directory to write FST files")
    args = parser.parse_args()

    if not shutil.which("sphinx_jsgf2fsg"):
        logging.fatal("Missing sphinx_jsgf2fst (expected in PATH)")
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)

    grammars = []

    for grammar_path in args.grammars:
        logging.debug(f"Parsing {grammar_path}")
        grammars.append(jsgf.parse_grammar_file(grammar_path))

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

        replace_tags_and_rules(top_rule, rule_map)
        new_grammar_string = grammar.compile()

        logging.debug(f"Converting to FST")
        fst_path = os.path.abspath(os.path.join(args.out_dir, f"{grammar.name}.fst"))

        with tempfile.NamedTemporaryFile(mode="w+") as fsm_file:
            proc = subprocess.run(
                ["sphinx_jsgf2fsg", "-jsgf", "/dev/stdin", "-fsm", fsm_file.name],
                input=new_grammar_string.encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
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

            fsm_file.seek(0)
            for line in fsm_file:
                line = line.strip()
                parts = re.split(r"\s+", line)

                if len(parts) == 2:
                    print(line, file=compiler)
                else:
                    sym = parts[2]
                    sym_table.add_symbol(sym)

                    if sym.startswith("__"):
                        print(f"{parts[0]} {parts[1]} <eps> {sym}", file=compiler)
                    else:
                        print(f"{parts[0]} {parts[1]} {sym} {sym}", file=compiler)

            grammar_fst = compiler.compile()
            grammar_fst.write(fst_path)
            logging.info(f"Wrote to {fst_path}")


# -----------------------------------------------------------------------------


def replace_tags_and_rules(rule, rule_map):
    """Replace named rules from other grammars with their expansions.
    Replace tags with sequences of __begin__TAG ... __end__TAG."""
    if isinstance(rule, jsgf.rules.Rule):
        # Unpack
        return replace_tags_and_rules(rule.expansion, rule_map)
    else:
        # TODO: Handle tags on rule refs and literals
        tag = rule.tag
        if tag and len(tag) == 0:
            tag = None

        if tag:
            rule.tag = None
            tag_seq = jsgf.expansions.Sequence()
            tag_seq.children.extend(
                [
                    jsgf.expansions.Literal(f"__begin__{tag}"),
                    replace_tags_and_rules(rule, rule_map),
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

            return replace_tags_and_rules(ref_rule.expansion, rule_map)
        elif hasattr(rule, "children"):
            rule.children = [
                replace_tags_and_rules(child, rule_map) for child in rule.children
            ]

            return rule
        elif hasattr(rule, "child"):
            rule.child = replace_tags_and_rules(rule.child, rule_map)
            return rule
        else:
            # Unsupported
            assert False, rule.__class__


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
