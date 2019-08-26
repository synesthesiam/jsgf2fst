#!/usr/bin/env python3
import os
import sys
import argparse
import re
import io
import subprocess
import tempfile
import shutil
import itertools
import collections
from collections import defaultdict, deque
import logging
from pathlib import Path
from typing import Set, List, Dict, Union, Any

import antlr4
import pywrapfst as fst

from .JsgfParser import JsgfParser
from .JsgfLexer import JsgfLexer
from .JsgfParserListener import JsgfParserListener

import antlr4

logger = logging.getLogger("jsgf2fst")


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
        logger.debug(f"Parsing {grammar_path}")
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
        logger.info(f"Wrote grammar FST to {fst_path}")

    if args.intent_fst:
        intent_fst = make_intent_fst(grammar_fsts)
        intent_fst.write(args.intent_fst)
        logger.info(f"Wrote intent FST to {args.intent_fst}")


# -----------------------------------------------------------------------------


def jsgf2fst(
    grammar_paths: Union[Path, List[Path]],
    slots: Dict[str, List[str]] = {},
    eps: str = "<eps>",
) -> Dict[str, fst.Fst]:
    """Converts JSGF grammars to FSTs.
    Returns dictionary mapping grammar names to FSTs."""

    is_list = isinstance(grammar_paths, collections.Iterable)
    if not is_list:
        grammar_paths = [grammar_paths]

    # grammar name -> fst
    grammar_fsts: Dict[str, fst.Fst] = {}

    # rule name -> fst
    rule_fsts: Dict[str, fst.Fst] = {}

    # rule name -> fst
    replaced_fsts: Dict[str, fst.Fst] = {}

    # grammar name -> listener
    listeners: Dict[str, FSTListener] = {}

    # Share symbol tables between all FSTs
    input_symbols = fst.SymbolTable()
    output_symbols = fst.SymbolTable()
    input_symbols.add_symbol(eps)
    output_symbols.add_symbol(eps)

    # Set of all input symbols that are __begin__ or __end__
    tag_input_symbols : Set[int] = set()

    # Set of all slot names that were used
    slots_to_replace : Set[str] = set()

    # Process each grammar
    for grammar_path in grammar_paths:
        logger.debug(f"Processing {grammar_path}")

        with open(grammar_path, "r") as grammar_file:
            # Tokenize
            input_stream = antlr4.InputStream(grammar_file.read())
            lexer = JsgfLexer(input_stream)
            tokens = antlr4.CommonTokenStream(lexer)

            # Parse
            parser = JsgfParser(tokens)

            # Transform to FST
            context = parser.r()
            walker = antlr4.ParseTreeWalker()

            # Create FST and symbol tables
            grammar_fst = fst.Fst()

            start = grammar_fst.add_state()
            grammar_fst.set_start(start)

            listener = FSTListener(grammar_fst, input_symbols, output_symbols, start)
            walker.walk(listener, context)

            # Merge with set of all tag input symbols
            tag_input_symbols.update(listener.tag_input_symbols)

            # Merge with set of all used slots
            slots_to_replace.update(listener.slot_references)

            # Save FSTs for all rules
            for rule_name, rule_fst in listener.fsts.items():
                rule_fsts[rule_name] = rule_fst
                listeners[rule_name] = listener

                # Record FSTs that have no rule references
                if len(listener.rule_references[rule_name]) == 0:
                    replaced_fsts[rule_name] = rule_fst

            # Save for later
            grammar_fsts[listener.grammar_name] = grammar_fst

    # -------------------------------------------------------------------------

    # grammar name -> (slot names)
    def replace_fsts(rule_name):
        nonlocal replaced_fsts, slots_to_replace
        rule_fst = replaced_fsts.get(rule_name)
        if rule_fst is not None:
            return rule_fst

        listener = listeners[rule_name]

        rule_fst = rule_fsts[rule_name]
        for ref_name in listener.rule_references[rule_name]:
            ref_fst = replace_fsts(ref_name)

            # Replace rule in grammar FST
            replace_symbol = "__replace__" + ref_name
            replace_idx = input_symbols.find(replace_symbol)
            if replace_idx >= 0:
                logger.debug(f"Replacing rule {ref_name} in {rule_name}")
                rule_fst = fst.replace(
                    [(-1, rule_fst), (replace_idx, ref_fst)], epsilon_on_replace=True
                )

        replaced_fsts[rule_name] = rule_fst
        return rule_fst

    # Do rule replacements
    for grammar_name in list(grammar_fsts.keys()):
        main_rule_name = grammar_name + "." + grammar_name
        grammar_fsts[grammar_name] = replace_fsts(main_rule_name)

    # -------------------------------------------------------------------------

    # Do slot replacements
    slot_fsts: Dict[str, fst.Fst] = {}
    for grammar_name, grammar_fst in grammar_fsts.items():
        main_rule_name = grammar_name + "." + grammar_name
        listener = listeners[main_rule_name]

        for slot_name in slots_to_replace:
            if slot_name not in slot_fsts:
                # Create FST for slot values
                logger.debug(f"Creating FST for slot {slot_name}")

                slot_fst = fst.Fst()
                start = slot_fst.add_state()
                slot_fst.set_start(start)

                # Create a single slot grammar
                with io.StringIO() as text_file:
                    print("#JSGF v1.0;", file=text_file)
                    print(f"grammar {slot_name};", file=text_file)
                    print("", file=text_file)

                    choices = " | ".join(
                        [
                            "(" + v + ")"
                            for v in itertools.chain(
                                slots.get_text(slot_name), slots.get_jsgf(slot_name)
                            )
                        ]
                    )

                    # All slot values
                    print(f"public <{slot_name}> = ({choices});", file=text_file)
                    text_file.seek(0)

                    # Tokenize
                    input_stream = antlr4.InputStream(text_file.getvalue())
                    lexer = JsgfLexer(input_stream)
                    tokens = antlr4.CommonTokenStream(lexer)

                    # Parse
                    parser = JsgfParser(tokens)

                    # Transform to FST
                    context = parser.r()
                    walker = antlr4.ParseTreeWalker()

                    # Fill in slot_fst
                    slot_listener = FSTListener(
                        slot_fst, input_symbols, output_symbols, start
                    )
                    walker.walk(slot_listener, context)

                # Cache for other grammars
                slot_fsts[slot_name] = slot_fst

            # -----------------------------------------------------------------

            # Replace slot in grammar FST
            replace_symbol = "__replace__$" + slot_name
            replace_idx = input_symbols.find(replace_symbol)
            if replace_idx >= 0:
                logger.debug(f"Replacing slot {slot_name} in {main_rule_name}")
                grammar_fst = fst.replace(
                    [(-1, grammar_fst), (replace_idx, slot_fst)],
                    epsilon_on_replace=True,
                )

                grammar_fsts[grammar_name] = grammar_fst

    # -------------------------------------------------------------------------

    # Remove tag start symbols.
    # TODO: Only do this for FSTs that actually have tags.
    for grammar_name, grammar_fst in grammar_fsts.items():
        main_rule_name = grammar_name + "." + grammar_name
        listener = listeners[main_rule_name]

        # Create a copy of the grammar FST with __begin__ and __end__ input
        # labels replaced by <eps>. For some reason, fstreplace fails when this
        # is done beforehand, whining about cyclic dependencies.
        in_eps = input_symbols.find(eps)
        old_fst = grammar_fst
        grammar_fst = fst.Fst()
        state_map: Dict[int, int] = {}
        weight_zero = fst.Weight.Zero(old_fst.weight_type())

        # Copy states with final status
        for old_state in old_fst.states():
            new_state = grammar_fst.add_state()
            state_map[old_state] = new_state
            if old_fst.final(old_state) != weight_zero:
                grammar_fst.set_final(new_state)

        # Start state
        grammar_fst.set_start(state_map[old_fst.start()])

        # Copy arcs
        for old_state, new_state in state_map.items():
            for old_arc in old_fst.arcs(old_state):
                # Replace tag input labels with <eps>
                input_idx = (
                    in_eps
                    if old_arc.ilabel in tag_input_symbols
                    else old_arc.ilabel
                )

                grammar_fst.add_arc(
                    new_state,
                    fst.Arc(
                        input_idx,
                        old_arc.olabel,
                        fst.Weight.One(grammar_fst.weight_type()),
                        state_map[old_arc.nextstate],
                    ),
                )

        grammar_fst.set_input_symbols(input_symbols)
        grammar_fst.set_output_symbols(output_symbols)

        # Replace FST
        grammar_fsts[grammar_name] = grammar_fst

    # -------------------------------------------------------------------------

    if not is_list:
        # Single input, single output
        return next(iter(grammar_fsts.values()))

    return grammar_fsts


# -----------------------------------------------------------------------------


def make_intent_fst(grammar_fsts: Dict[str, fst.Fst], eps=0) -> fst.Fst:
    """Merges grammar FSTs created with jsgf2fst into a single acceptor FST."""
    intent_fst = fst.Fst()
    all_in_symbols = fst.SymbolTable()
    all_out_symbols = fst.SymbolTable()
    all_in_symbols.add_symbol("<eps>", eps)
    all_out_symbols.add_symbol("<eps>", eps)

    # Merge symbols from all FSTs
    for grammar_fst in grammar_fsts.values():
        in_symbols = grammar_fst.input_symbols()
        for i in range(in_symbols.num_symbols()):
            all_in_symbols.add_symbol(in_symbols.find(i).decode())

        out_symbols = grammar_fst.output_symbols()
        for i in range(out_symbols.num_symbols()):
            all_out_symbols.add_symbol(out_symbols.find(i).decode())

    # Add __label__ for each intent
    for intent_name in grammar_fsts.keys():
        all_out_symbols.add_symbol(f"__label__{intent_name}")

    intent_fst.set_input_symbols(all_in_symbols)
    intent_fst.set_output_symbols(all_out_symbols)

    # Create start/final states
    start_state = intent_fst.add_state()
    intent_fst.set_start(start_state)

    final_state = intent_fst.add_state()
    intent_fst.set_final(final_state)

    # Merge FSTs in
    for intent_name, grammar_fst in grammar_fsts.items():
        label_sym = all_out_symbols.find(f"__label__{intent_name}")
        replace_and_patch(
            intent_fst, start_state, final_state, grammar_fst, label_sym, eps=eps
        )

    # BUG: Fst.minimize does not pass allow_nondet through, so we have to call out to the command-line
    minimize_cmd = ["fstminimize", "--allow_nondet"]
    return fst.Fst.read_from_string(
        subprocess.check_output(minimize_cmd, input=intent_fst.write_to_string())
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


class SlotValues:
    def __init__(self) -> None:
        self.text: Dict[str, List[str]] = {}
        self.jsgf: Dict[str, List[str]] = {}

    def add_text(self, key: str, value: str) -> None:
        if key in self.text:
            self.text[key].append(value)
        else:
            self.text[key] = [value]

    def add_jsgf(self, key: str, value: str) -> None:
        if key in self.jsgf:
            self.jsgf[key].append(value)
        else:
            self.jsgf[key] = [value]

    def get_text(self, key: str):
        return self.text.get(key, [])

    def get_jsgf(self, key: str):
        return self.jsgf.get(key, [])

    def __getitem__(self, key: str):
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return (key in self.text) or (key in self.jsgf)


def read_slots(slots_dir: str) -> SlotValues:
    """Load slot values (lines) from all files in the given directory."""
    slots = SlotValues()
    if os.path.exists(slots_dir):
        for slot_path in os.listdir(slots_dir):
            slot_name, slot_ext = os.path.splitext(slot_path)
            is_jsgf = slot_ext.lower() == ".jsgf"
            slot_path = os.path.join(slots_dir, slot_path)

            with open(slot_path, "r") as slot_file:
                for line in slot_file:
                    line = line.strip()
                    if len(line) == 0:
                        continue

                    if is_jsgf:
                        slots.add_jsgf(slot_name, line)
                    else:
                        slots.add_text(slot_name, line)

    return slots


# -----------------------------------------------------------------------------


class FSTListener(JsgfParserListener):
    def __init__(
        self,
        this_fst: fst.Fst,
        input_symbols: fst.SymbolTable,
        output_symbols: fst.SymbolTable,
        start_state: int,
        eps: str = "<eps>",
    ):
        self.grammar_name: Optional[str] = None
        self.is_public = False
        self.in_rule = False
        self.in_rule_reference = False
        self.rule_name = None
        self.in_optional = False
        self.in_alternative = False

        self.group_depth: int = 0
        self.opt_states: Dict[int, int] = {}
        self.alt_states: Dict[int, int] = {}
        self.alt_ends: Dict[int, int] = {}
        self.tag_states: Dict[int, int] = {}
        self.exp_states: Dict[int, int] = {}
        self.last_states: Dict[str, int] = {}

        # Initial FST
        self.start_state: int = start_state
        self.fst: fst.Fst = this_fst
        self.fsts: Dict[str, fst.Fst] = {}
        self.rule_references: Dict[str, Set[str]] = defaultdict(set)
        self.slot_references: Set[str] = set()
        self.tag_input_symbols: Set[int] = set()

        # Shared symbol tables
        self.input_symbols: fst.SymbolTable = input_symbols
        self.output_symbols: fst.SymbolTable = output_symbols
        self.weight_one: fst.Weight = fst.Weight.One(self.fst.weight_type())

        # Indices of <eps> tokens
        self.in_eps: int = self.input_symbols.find(eps)
        self.out_eps: int = self.output_symbols.find(eps)

    def enterGrammarName(self, ctx):
        self.grammar_name = ctx.getText()

    def enterRuleDefinition(self, ctx):
        # Only a single public rule is expected
        self.is_public = ctx.PUBLIC() is not None

    def exitRuleDefinition(self, ctx):
        self.is_public = False
        self.fst.set_final(self.last_states[self.rule_name])

    def enterRuleName(self, ctx):
        # Create qualified rule name
        self.rule_name = self.grammar_name + "." + ctx.getText()

    def enterRuleBody(self, ctx):
        self.in_rule = True

        if self.is_public:
            # Use main start state
            self.last_states[self.rule_name] = self.start_state
        else:
            # Create new FST
            self.fst = fst.Fst()
            self.start_state = self.fst.add_state()
            self.fst.set_start(self.start_state)
            self.last_states[self.rule_name] = self.start_state

        self.fsts[self.rule_name] = self.fst

        # Reset
        self.group_depth = 0
        self.opt_states = {}
        self.alt_states = {}
        self.tag_states = {}
        self.exp_states = {}
        self.alt_ends = {}

        # Save anchor state
        self.alt_states[self.group_depth] = self.last_states[self.rule_name]

    def exitRuleBody(self, ctx):
        self.in_rule = False

    def enterExpression(self, ctx):
        self.in_expression = True
        self.exp_states[self.group_depth] = self.last_states[self.rule_name]

    def exitExpression(self, ctx):
        self.in_expression = False

    def enterAlternative(self, ctx):
        anchor_state = self.alt_states[self.group_depth]

        if self.group_depth not in self.alt_ends:
            # Patch start of alternative
            next_state = self.fst.add_state()
            for arc in self.fst.arcs(anchor_state):
                self.fst.add_arc(next_state, arc)

            self.fst.delete_arcs(anchor_state)
            self.fst.add_arc(
                anchor_state,
                fst.Arc(self.in_eps, self.out_eps, self.weight_one, next_state),
            )

            # Create shared end state for alternatives
            self.alt_ends[self.group_depth] = self.fst.add_state()

        # Close previous alternative
        last_state = self.last_states[self.rule_name]
        end_state = self.alt_ends[self.group_depth]
        self.fst.add_arc(
            last_state, fst.Arc(self.in_eps, self.out_eps, self.weight_one, end_state)
        )

        # Add new intermediary state
        next_state = self.fst.add_state()
        self.fst.add_arc(
            anchor_state,
            fst.Arc(self.in_eps, self.out_eps, self.weight_one, next_state),
        )
        self.last_states[self.rule_name] = next_state

        self.in_alternative = True

    def exitAlternative(self, ctx):
        self.in_alternative = False

        # Create arc to shared end state
        last_state = self.last_states[self.rule_name]
        end_state = self.alt_ends[self.group_depth]
        if last_state != end_state:
            self.fst.add_arc(
                last_state,
                fst.Arc(self.in_eps, self.out_eps, self.weight_one, end_state),
            )

        self.last_states[self.rule_name] = end_state

    def enterOptional(self, ctx):
        # Save anchor state
        self.opt_states[self.group_depth] = self.last_states[self.rule_name]

        # Optionals are honorary groups
        self.group_depth += 1

        # Save anchor state
        self.alt_states[self.group_depth] = self.last_states[self.rule_name]

        self.in_optional = True

    def exitOptional(self, ctx):
        # Optionals are honorary groups
        self.alt_ends.pop(self.group_depth, None)
        self.group_depth -= 1

        anchor_state = self.opt_states[self.group_depth]
        last_state = self.last_states[self.rule_name]

        # Add optional by-pass arc
        # --[<eps>]-->
        self.fst.add_arc(
            anchor_state,
            fst.Arc(self.in_eps, self.out_eps, self.weight_one, last_state),
        )

        self.in_optional = False

    def enterGroup(self, ctx):
        self.group_depth += 1

        # Save anchor state
        self.alt_states[self.group_depth] = self.last_states[self.rule_name]

    def exitGroup(self, ctx):
        self.alt_ends.pop(self.group_depth, None)
        self.group_depth -= 1

    def enterRuleReference(self, ctx):
        self.in_rule_reference = True
        rule_name = ctx.getText()[1:-1]
        if "." not in rule_name:
            # Assume current grammar
            rule_name = self.grammar_name + "." + rule_name

        self.rule_references[self.rule_name].add(rule_name)

        # Create transition that will be replaced with a different FST
        rule_symbol = "__replace__" + rule_name
        input_idx = self.input_symbols.add_symbol(rule_symbol)
        output_idx = self.output_symbols.add_symbol(rule_symbol)

        # --[__replace__RULE]-->
        last_state = self.last_states[self.rule_name]
        next_state = self.fst.add_state()
        self.fst.add_arc(
            last_state, fst.Arc(input_idx, output_idx, self.weight_one, next_state)
        )
        self.last_states[self.rule_name] = next_state

    def exitRuleReference(self, ctx):
        self.in_rule_reference = False

    def enterTagBody(self, ctx):
        # Get the original text *with* whitespace from ANTLR
        input_stream = ctx.start.getInputStream()
        start = ctx.start.start
        stop = ctx.stop.stop
        tag_text = input_stream.getText(start, stop)

        # Patch start of tag
        anchor_state = self.exp_states[self.group_depth]
        next_state = self.fst.add_state()

        # --[__begin__TAG]-->
        begin_symbol = "__begin__" + tag_text
        input_idx = self.input_symbols.add_symbol(begin_symbol)
        output_idx = self.output_symbols.add_symbol(begin_symbol)

        self.tag_input_symbols.add(input_idx)

        # Move outgoing anchor arcs
        for arc in self.fst.arcs(anchor_state):
            self.fst.add_arc(
                next_state, fst.Arc(arc.ilabel, arc.olabel, arc.weight, arc.nextstate)
            )

        # Patch anchor
        self.fst.delete_arcs(anchor_state)
        self.fst.add_arc(
            anchor_state, fst.Arc(input_idx, output_idx, self.weight_one, next_state)
        )

        # Patch end of tag
        last_state = self.last_states[self.rule_name]
        next_state = self.fst.add_state()

        # --[__end__TAG]-->
        end_symbol = "__end__" + tag_text
        input_idx = self.input_symbols.add_symbol(end_symbol)
        output_idx = self.output_symbols.add_symbol(end_symbol)

        self.tag_input_symbols.add(input_idx)

        self.fst.add_arc(
            last_state, fst.Arc(input_idx, output_idx, self.weight_one, next_state)
        )
        self.last_states[self.rule_name] = next_state

    def enterLiteral(self, ctx):
        if (not self.in_rule) or self.in_rule_reference:
            return

        # Get the original text *with* whitespace from ANTLR
        input_stream = ctx.start.getInputStream()
        start = ctx.start.start
        stop = ctx.stop.stop
        text = input_stream.getText(start, stop)
        last_state = self.last_states[self.rule_name]

        # Split words by whitespace
        for word in re.split(r"\s+", text):
            if ":" in word:
                # Word contains input:output pair
                input_symbol = word.split(":", maxsplit=1)[0]

                # NOTE: Entire word (with ":") is used as the output symbol so
                # that the fstaccept method can know what the original (raw)
                # text was.
                output_symbol = word
            elif word.startswith("$"):
                # Slot replacement
                input_symbol = "__replace__" + word
                output_symbol = input_symbol
                slot_name = word[1:]
                self.slot_references.add(slot_name)
            else:
                # Word itself is input and output
                input_symbol, output_symbol = word, word

            input_idx = self.input_symbols.add_symbol(input_symbol)
            output_idx = self.output_symbols.add_symbol(output_symbol)

            # --[word_in:word_out]-->
            next_state = self.fst.add_state()
            self.fst.add_arc(
                last_state, fst.Arc(input_idx, output_idx, self.weight_one, next_state)
            )
            self.exp_states[self.group_depth] = last_state
            last_state = next_state

        self.last_states[self.rule_name] = last_state


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
