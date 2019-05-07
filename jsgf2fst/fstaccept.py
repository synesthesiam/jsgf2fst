#!/usr/bin/env python3
import os
import sys
import argparse
import re
import json
import logging
from typing import Dict, Any, List, Optional, TextIO, Mapping, Union

import pywrapfst as fst


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser("fstaccept")
    parser.add_argument("fst", help="Path to FST")
    parser.add_argument("sentences", nargs="+", help="Sentences to parse")
    parser.add_argument(
        "--dont-replace",
        action="store_true",
        help="Disable automation TAG:REPLACE behavior",
    )
    args = parser.parse_args()

    grammar_fst = fst.Fst.read(args.fst)
    intent_name = os.path.splitext(os.path.split(args.fst)[1])[0]
    results = {}

    # Run each sentence through FST acceptor
    for sentence in args.sentences:
        results[sentence] = fstaccept(
            grammar_fst,
            sentence,
            intent_name=intent_name,
            replace_tags=not args.dont_replace,
        )

    json.dump(results, sys.stdout)


# -----------------------------------------------------------------------------


def fstaccept(
    in_fst: fst.Fst,
    sentence: Union[str, List[str]],
    intent_name: Optional[str] = None,
    replace_tags: bool = True,
) -> List[Dict[str, Any]]:
    """Recognizes an intent from a sentence using a FST."""

    if isinstance(sentence, str):
        # Assume lower case, white-space separated tokens
        sentence = sentence.strip().lower()
        words = re.split(r"\s+", sentence)
    else:
        words = sentence

    intents = []

    try:
        out_fst = apply_fst(words, in_fst)

        # Get output symbols
        out_sentences = fstprintall(out_fst, exclude_meta=False)
        for out_sentence in out_sentences:
            out_intent_name = intent_name
            intent = symbols2intent(
                out_sentence, intent_name=out_intent_name, replace_tags=replace_tags
            )
            intent["intent"]["confidence"] /= len(out_sentences)
            intents.append(intent)
    except:
        # Error, assign blank result
        logging.exception(sentence)

    return intents


# -----------------------------------------------------------------------------


def symbols2intent(
    symbols: List[str],
    eps: str = "<eps>",
    intent: Optional[Dict[str, Any]] = None,
    intent_name: Optional[str] = None,
    replace_tags: bool = True,
) -> Dict[str, Any]:
    intent = intent or empty_intent()
    tag = None
    tag_symbols: List[str] = []
    out_symbols: List[str] = []
    tag_start_index = 0
    out_index = 0

    for sym in symbols:
        if sym == eps:
            continue

        if sym.startswith("__begin__"):
            # Begin tag
            tag = sym[9:]
            tag_symbols = []
            tag_start_index = out_index
        elif sym.startswith("__end__"):
            # End tag
            assert tag == sym[7:], f"Mismatched tags: {tag} {sym[7:]}"

            if replace_tags and (":" in tag):
                # Use replacement string in the tag
                tag, tag_value = tag.split(":", maxsplit=1)
                out_symbols.extend(re.split(r"\s+", tag_value))
            else:
                # Use text between begin/end
                tag_value = " ".join(tag_symbols)
                out_symbols.extend(tag_symbols)

            out_index += len(tag_value) + 1  # space
            intent["entities"].append(
                {
                    "entity": tag,
                    "value": tag_value,
                    "start": tag_start_index,
                    "end": out_index - 1,
                }
            )

            tag = None
            tag_start_index = 0
        elif sym.startswith("__label__"):
            # Intent label
            if intent_name is None:
                intent_name = sym[9:]
        elif tag:
            # Inside tag
            tag_symbols.append(sym)
        else:
            # Outside tag
            out_symbols.append(sym)
            out_index += len(sym) + 1  # space

    intent["text"] = " ".join(out_symbols)
    intent["tokens"] = out_symbols

    if len(out_symbols) > 0:
        intent["intent"]["name"] = intent_name or ""
        intent["intent"]["confidence"] = 1

    return intent


# -----------------------------------------------------------------------------


def fstprintall(
    in_fst: fst.Fst,
    out_file: Optional[TextIO] = None,
    exclude_meta: bool = True,
    state: Optional[int] = None,
    path: Optional[List[fst.Arc]] = None,
    zero_weight: Optional[fst.Weight] = None,
    eps: int = 0,
) -> List[List[str]]:
    sentences = []
    path = path or []
    state = state or in_fst.start()
    zero_weight = zero_weight or fst.Weight.Zero(in_fst.weight_type())

    for arc in in_fst.arcs(state):
        path.append(arc)

        if in_fst.final(arc.nextstate) != zero_weight:
            # Final state
            out_syms = in_fst.output_symbols()
            sentence = []
            for p_arc in path:
                if p_arc.olabel != eps:
                    osym = out_syms.find(p_arc.olabel).decode()
                    if exclude_meta and osym.startswith("__"):
                        continue  # skip __label__, etc.

                    if out_file:
                        print(osym, "", end="", file=out_file)
                    else:
                        sentence.append(osym)

            if out_file:
                print("", file=out_file)
            else:
                sentences.append(sentence)
        else:
            # Non-final state
            sentences.extend(
                fstprintall(
                    in_fst,
                    out_file=out_file,
                    state=arc.nextstate,
                    path=path,
                    zero_weight=zero_weight,
                    eps=eps,
                    exclude_meta=exclude_meta,
                )
            )

        path.pop()

    return sentences


# -----------------------------------------------------------------------------

# From:
# https://stackoverflow.com/questions/9390536/how-do-you-even-give-an-openfst-made-fst-input-where-does-the-output-go


def linear_fst(
    elements: List[str],
    automata_op: fst.Fst,
    keep_isymbols: bool = True,
    **kwargs: Mapping[Any, Any],
) -> fst.Fst:
    """Produce a linear automata."""
    assert len(elements) > 0, "No elements"
    compiler = fst.Compiler(
        isymbols=automata_op.input_symbols().copy(),
        acceptor=keep_isymbols,
        keep_isymbols=keep_isymbols,
        **kwargs,
    )

    num_elements = 0
    for i, el in enumerate(elements):
        print("{} {} {}".format(i, i + 1, el), file=compiler)
        num_elements += 1

    print(str(num_elements), file=compiler)

    return compiler.compile()


def apply_fst(
    elements: List[str],
    automata_op: fst.Fst,
    is_project: bool = True,
    **kwargs: Mapping[Any, Any],
) -> fst.Fst:
    """Compose a linear automata generated from `elements` with `automata_op`.

    Args:
        elements (list): ordered list of edge symbols for a linear automata.
        automata_op (Fst): automata that will be applied.
        is_project (bool, optional): whether to keep only the output labels.
        kwargs:
            Additional arguments to the compiler of the linear automata .
    """
    linear_automata = linear_fst(elements, automata_op, keep_isymbols=True, **kwargs)
    out = fst.compose(linear_automata, automata_op)
    if is_project:
        out.project(project_output=True)
    return out


# -----------------------------------------------------------------------------


def empty_intent() -> Dict[str, Any]:
    return {"text": "", "intent": {"name": "", "confidence": 0}, "entities": []}


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
