#!/usr/bin/env python3
import os
import sys
import argparse
import re
import subprocess
import tempfile
import shutil
import collections
import logging
from typing import List, Dict, Union, Any

import jsgf
from jsgf.rules import Rule
from jsgf.expansions import Literal, Sequence, AlternativeSet, OptionalGrouping
import pywrapfst as fst


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser("jsgf2fst")
    parser.add_argument("grammars", nargs="+", help="JSGF grammars to convert")
    parser.add_argument("--out-dir", default=".", help="Directory to write FST files")
    parser.add_argument("--intent-fst", default=None, help="Path to write intent FST")
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

    if not args.no_slots and args.slots_dir:
        # Directory where slot values are stored ($slot_name -> dir/slot_name)
        slots = read_slots(args.slots_dir)
    else:
        slots = {}  # no slots

    # Convert to FSTs
    grammar_fsts = jsgf2fst(grammars, slots=slots)

    # Write FSTs
    for grammar_name, grammar_fst in grammar_fsts.items():
        fst_path = os.path.abspath(os.path.join(args.out_dir, f"{grammar_name}.fst"))
        grammar_fst.write(fst_path)
        logging.info(f"Wrote grammar FST to {fst_path}")

    if args.intent_fst:
        intent_fst = make_intent_fst(grammar_fsts)
        intent_fst.write(args.intent_fst)
        logging.info(f"Wrote intent FST to {args.intent_fst}")


# -----------------------------------------------------------------------------


def jsgf2fst(
    grammars: Union[jsgf.Grammar, List[jsgf.Grammar]], slots: Dict[str, List[str]] = {}
) -> Dict[str, fst.Fst]:
    """Converts JSGF grammars to FSTs.
    Returns dictionary mapping grammar names to FSTs."""

    is_list = isinstance(grammars, collections.Iterable)
    if not is_list:
        grammars = [grammars]

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
                    if ":" in sym:
                        in_sym, out_sym = sym.split(":", maxsplit=1)
                    else:
                        in_sym = sym
                        out_sym = sym

                    sym_table.add_symbol(in_sym)
                    sym_table.add_symbol(sym)

                    if in_sym.startswith("__"):
                        # Tag (__begin__/__end__ surrounding content)
                        print(f"{parts[0]} {parts[1]} <eps> {sym}", file=compiler)
                    else:
                        # Regular transition
                        print(f"{parts[0]} {parts[1]} {in_sym} {sym}", file=compiler)

            grammar_fst = compiler.compile()
            grammar_fsts[grammar.name] = grammar_fst

        # sym_table = fst.SymbolTable()
        # sym_table.add_symbol("<eps>", 0)
        # grammar_fst = fst.Fst()

        # start_state = grammar_fst.add_state()
        # grammar_fst.set_start(start_state)

        # final_state = grammar_fst.add_state()
        # grammar_fst.set_final(final_state)

        # _rule_to_fst(grammar_fst, sym_table, top_rule, start_state, final_state)

        # grammar_fst.set_input_symbols(sym_table)
        # grammar_fst.set_output_symbols(sym_table)
        # grammar_fsts[grammar.name] = grammar_fst

    if not is_list:
        # Single input, single output
        return next(iter(grammar_fsts.values()))

    return grammar_fsts


def _rule_to_fst(
    grammar_fst: fst.Fst,
    sym_table: fst.SymbolTable,
    rule: Rule,
    from_state: int,
    to_state: int,
    eps=0,
):
    one_weight = fst.Weight.One(grammar_fst.weight_type())

    if isinstance(rule, Literal):
        text = rule.text.strip().lower()
        if " " in text:
            # Split text into tokens (words)
            word_seq = Sequence()
            for word in re.split(r"\s+", text):
                word_seq.children.append(Literal(word))

            # Handle sequence
            _rule_to_fst(
                grammar_fst, sym_table, word_seq, from_state, to_state, eps=eps
            )
        else:
            word = text
            if ":" in word:
                # input:output
                in_word, out_word = word.split(":", maxsplit=1)
                in_sym, out_sym = (
                    sym_table.add_symbol(in_word),
                    sym_table.add_symbol(out_word),
                )
            elif word.startswith("__"):
                # meta token
                in_sym = eps
                out_sym = sym_table.add_symbol(word)
            else:
                # regular word
                in_sym = sym_table.add_symbol(word)
                out_sym = in_sym

            # Add arc for word
            grammar_fst.add_arc(
                from_state, fst.Arc(in_sym, out_sym, one_weight, to_state)
            )
    elif isinstance(rule, OptionalGrouping):
        # Handle child
        _rule_to_fst(grammar_fst, sym_table, rule.child, from_state, to_state, eps=eps)

        # Add optional arc
        grammar_fst.add_arc(from_state, fst.Arc(eps, eps, one_weight, to_state))
    elif isinstance(rule, AlternativeSet):
        for child in rule.children:
            # Handle child
            _rule_to_fst(grammar_fst, sym_table, child, from_state, to_state, eps=eps)
    elif isinstance(rule, Sequence):
        current_state = from_state
        last_state = to_state

        # Connect children in linear chain
        for child in rule.children:
            child_state = grammar_fst.add_state()
            _rule_to_fst(
                grammar_fst, sym_table, child, current_state, child_state, eps=eps
            )
            current_state = child_state

        # Connect to final state
        grammar_fst.add_arc(current_state, fst.Arc(eps, eps, one_weight, last_state))
    elif isinstance(rule, Rule):
        _rule_to_fst(
            grammar_fst, sym_table, rule.expansion, from_state, to_state, eps=eps
        )
    else:
        assert False, f"Unsupported rule: {rule}"


# -----------------------------------------------------------------------------


def make_intent_fst(grammar_fsts: Dict[str, fst.Fst], eps=0) -> fst.Fst:
    """Merges grammar FSTs created with jsgf2fst into a single acceptor FST."""
    intent_fst = fst.Fst()
    all_symbols = fst.SymbolTable()
    all_symbols.add_symbol("<eps>", eps)

    # Merge symbols from all FSTs
    tables = [
        t
        for gf in grammar_fsts.values()
        for t in [gf.input_symbols(), gf.output_symbols()]
    ]

    for table in tables:
        for i in range(table.num_symbols()):
            all_symbols.add_symbol(table.find(i).decode())

    # Add __label__ for each intent
    for intent_name in grammar_fsts.keys():
        all_symbols.add_symbol(f"__label__{intent_name}")

    intent_fst.set_input_symbols(all_symbols)
    intent_fst.set_output_symbols(all_symbols)

    # Create start/final states
    start_state = intent_fst.add_state()
    intent_fst.set_start(start_state)

    final_state = intent_fst.add_state()
    intent_fst.set_final(final_state)

    # Merge FSTs in
    for intent_name, grammar_fst in grammar_fsts.items():
        label_sym = all_symbols.find(f"__label__{intent_name}")
        replace_and_patch(
            intent_fst, start_state, final_state, grammar_fst, label_sym, eps=eps
        )

    # BUG: Fst.minimize does not pass allow_nondet through, so we have to call out to the command-line
    minimize_cmd = ["fstminimize", "--allow_nondet"]
    return fst.Fst.read_from_string(
        subprocess.check_output(minimize_cmd, input=intent_fst.WriteToString())
    )


def replace_and_patch(
    outer_fst: fst.Fst,
    outer_start_state: int,
    outer_final_state: int,
    inner_fst: fst.Fst,
    label_sym: int,
    eps: int = 0,
) -> None:
    """Copies an inner FST into an outer FST, creating states and mapping symbols.
    Creates arcs from outer start/final states to inner start/final states."""

    in_symbols = outer_fst.input_symbols()
    out_symbols = outer_fst.output_symbols()
    inner_zero = fst.Weight.Zero(inner_fst.weight_type())
    outer_one = fst.Weight.One(outer_fst.weight_type())

    state_map = {}
    in_symbol_map = {}
    out_symbol_map = {}

    for i in range(inner_fst.output_symbols().num_symbols()):
        sym_str = inner_fst.output_symbols().find(i).decode()
        out_symbol_map[i] = out_symbols.find(sym_str)

    for i in range(inner_fst.input_symbols().num_symbols()):
        sym_str = inner_fst.input_symbols().find(i).decode()
        in_symbol_map[i] = in_symbols.find(sym_str)

    # Create states in outer FST
    for inner_state in inner_fst.states():
        state_map[inner_state] = outer_fst.add_state()

    # Create arcs in outer FST
    for inner_state in inner_fst.states():
        if inner_state == inner_fst.start():
            outer_fst.add_arc(
                outer_start_state,
                fst.Arc(eps, label_sym, outer_one, state_map[inner_state]),
            )

        for inner_arc in inner_fst.arcs(inner_state):
            outer_fst.add_arc(
                state_map[inner_state],
                fst.Arc(
                    in_symbol_map[inner_arc.ilabel],
                    out_symbol_map[inner_arc.olabel],
                    outer_one,
                    state_map[inner_arc.nextstate],
                ),
            )

            if inner_fst.final(inner_arc.nextstate) != inner_zero:
                outer_fst.add_arc(
                    state_map[inner_arc.nextstate],
                    fst.Arc(eps, eps, outer_one, outer_final_state),
                )


# -----------------------------------------------------------------------------


def read_slots(slots_dir: str) -> Dict[str, List[str]]:
    """Load slot values (lines) from all files in the given directory."""
    slots = {}
    if os.path.exists(slots_dir):
        for slot_path in os.listdir(slots_dir):
            slot_name = os.path.splitext(slot_path)[0]
            slot_path = os.path.join(slots_dir, slot_path)
            with open(slot_path, "r") as slot_file:
                slots[slot_name] = [line.strip().lower() for line in slot_file]

    return slots


# -----------------------------------------------------------------------------


def replace_tags_and_rules(
    rule: Rule, rule_map: Dict[str, Rule], slots: Dict[str, List[str]] = {}
) -> Rule:
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
            rule_copy = rule.copy()
            rule_copy.tag = None

            tag_seq = jsgf.expansions.Sequence()
            tag_seq.children.extend(
                [
                    jsgf.expansions.Literal(f"__begin__{tag}"),
                    replace_tags_and_rules(rule_copy, rule_map, slots=slots),
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
