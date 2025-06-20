CC=gcc
CFLAGS=-O3 -fopenmp -Iinclude
SRC=src/main.c src/parallel_to_grayscale.c
BIN=../bin/grayscale

all: $(BIN)

$(BIN): $(SRC)
	mkdir -p ../bin
	$(CC) $(CFLAGS) $(SRC) -lm -o $(BIN)

clean:
	rm -f $(BIN)
