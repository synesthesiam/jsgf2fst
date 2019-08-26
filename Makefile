.PHONY: dist antlr
CPPFLAGS:=$(CFLAGS) -lfst -g -Wall -ldl --std=c++11
antlr_jar := "antlr/antlr-4.7.2-complete.jar"

all: fstprint-all

%: %.cc
	$(CXX) $< $(CPPFLAGS) $(LDFLAGS) -o $@

clean:
	rm -f $(shell grep ^all: Makefile | cut -f2- -d" ")

dist:
	rm -rf dist/
	mkdir -p dist
	tar -czvf dist/jsgf2fst-0.2.0.tar.gz --exclude=__pycache__ README.md setup.py requirements.txt jsgf2fst/ jsgf/

antlr: JsgfLexer.g4 JsgfParser.g4
	java -jar $(antlr_jar) -Dlanguage=Python3 -o jsgf2fst/ $^
