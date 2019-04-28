CPPFLAGS:=$(CFLAGS) -lfst -g -Wall -ldl --std=c++11
all: fstprint-nbest-strings
%: %.cc
	$(CXX) $< $(CPPFLAGS) $(LDFLAGS) -o $@
clean:
	rm -f $(shell grep ^all: Makefile | cut -f2- -d" ")
