.PHONY: dist
CPPFLAGS:=$(CFLAGS) -lfst -g -Wall -ldl --std=c++11

all: fstprint-all

%: %.cc
	$(CXX) $< $(CPPFLAGS) $(LDFLAGS) -o $@

clean:
	rm -f $(shell grep ^all: Makefile | cut -f2- -d" ")

dist:
	rm -rf dist/
	mkdir -p dist
	tar -czvf dist/jsgf2fst-0.1.1.tar.gz --exclude=__pycache__ README.md setup.py requirements.txt jsgf2fst/ jsgf/
