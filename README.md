# JSGF to FST

This Python module takes one or more [JSGF grammars](https://www.w3.org/TR/jsgf/) and converts them to finite state transducers using [OpenFST](https://www.openfst.org).

Optionally, ARPA language models can be created using [Opengrm](https://www.opengrm.org).

## Dependencies

Requires OpenFST and the `sphinx_jsgf2fsg` command. These are usually found in the `libfst-dev` and `sphinxbase-utils` Debian packages. Opengrm must be installed from source.

## Usage

The typical usage for `jsgf2fst` is:

1. Create some JSGF grammars, one per intent
2. Tag critical pieces of each sentence with a JSGF tag (e.g., `(red | green){color}`)
3. Parse the JSGF grammar(s) using `pyjsgf`
4. Convert to FSTS with `jsgf2fst.jsgf2fst(...)`
5. Merge into a single acceptor FST with `jsgf2fst.make_intent_fst(...)`
6. Recognize intents from text with `jsgf2fst.fstaccept(...)`
