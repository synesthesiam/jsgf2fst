#!/usr/bin/env python3
import sys
import argparse
import re
import json
import logging

logging.basicConfig(level=logging.INFO)

import pywrapfst as fst


def main():
    parser = argparse.ArgumentParser("fstaccept")
    parser.add_argument("fst", help="Path to FST")
    parser.add_argument("sentences", nargs="+", help="Sentences to parse")
    args = parser.parse_args()

    grammar_fst = fst.Fst.read(args.fst)
    results = {}

    # Run each sentence through FST acceptor
    for sentence in args.sentences:
        # Assume lower case, white-space separated tokens
        sentence = sentence.strip().lower()
        words = re.split(r"\s+", sentence)
        intent = empty_intent()

        try:
            out_fst = apply_fst(words, grammar_fst)

            # Get output symbols
            out_symbols = []
            tag_symbols = []
            tag = None
            for state in out_fst.states():
                for arc in out_fst.arcs(state):
                    sym = out_fst.output_symbols().find(arc.olabel).decode()
                    if sym == "<eps>":
                        continue

                    if sym.startswith("__begin__"):
                        tag = sym[9:]
                        tag_symbols = []
                    elif sym.startswith("__end__"):
                        assert tag == sym[7:], f"Mismatched tags: {tag} {sym[7:]}"
                        intent["entities"].append({
                            "entity": tag,
                            "value": " ".join(tag_symbols)
                        })

                        tag = None
                    elif tag:
                        tag_symbols.append(sym)
                    else:
                        out_symbols.append(sym)

            intent["text"] = " ".join(out_symbols)
        except:
            # Error, assign blank result
            logging.exception(sentence)

        results[sentence] = intent

    json.dump(results, sys.stdout)


# -----------------------------------------------------------------------------

# From:
# https://stackoverflow.com/questions/9390536/how-do-you-even-give-an-openfst-made-fst-input-where-does-the-output-go


def linear_fst(elements, automata_op, keep_isymbols=True, **kwargs):
    """Produce a linear automata."""
    compiler = fst.Compiler(
        isymbols=automata_op.input_symbols().copy(),
        acceptor=keep_isymbols,
        keep_isymbols=keep_isymbols,
        **kwargs
    )

    for i, el in enumerate(elements):
        print("{} {} {}".format(i, i + 1, el), file=compiler)
    print(str(i + 1), file=compiler)

    return compiler.compile()


def apply_fst(elements, automata_op, is_project=True, **kwargs):
    """Compose a linear automata generated from `elements` with `automata_op`.

    Args:
        elements (list): ordered list of edge symbols for a linear automata.
        automata_op (Fst): automata that will be applied.
        is_project (bool, optional): whether to keep only the output labels.
        kwargs:
            Additional arguments to the compiler of the linear automata .
    """
    linear_automata = linear_fst(elements, automata_op, **kwargs)
    out = fst.compose(linear_automata, automata_op)
    if is_project:
        out.project(project_output=True)
    return out


# -----------------------------------------------------------------------------


def empty_intent():
    return {"text": "", "intent": {"name": "", "confidence": 0}, "entities": []}


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
