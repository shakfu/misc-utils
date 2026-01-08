
.PHONY: all build clean test test-regen


all: build


webloc2md: 
	@clang++ -std=c++17 -Wall -Wextra -O2 \
		webloc2md.cpp \
		-o webloc2md \
		-framework CoreFoundation

build: webloc2md

rebuild: clean webloc2md test

test: webloc2md tests/EXPECTED.md
	@tmp=$$(mktemp) && \
	trap 'rm -f "$$tmp"' EXIT && \
	./webloc2md -o "$$tmp" tests/data >/dev/null && \
	diff -u tests/EXPECTED.md "$$tmp"

test-regen: webloc2md
	@./webloc2md -o tests/EXPECTED.md tests/data

clean:
	@rm -f webloc2md
