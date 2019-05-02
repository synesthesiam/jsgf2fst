# JSGF to FST

This Python module takes one or more [JSGF grammars](https://www.w3.org/TR/jsgf/) and converts them to finite state transducers using [OpenFST](https://www.openfst.org).

Optionally, ARPA language models can be created using [Opengrm](https://www.opengrm.org).

## Dependencies

Requires OpenFST and the `sphinx_jsgf2fst` command. These are usually found in the `libfst-dev` and `sphinxbase-utils` Debian packages. Opengrm must be installed from source.
