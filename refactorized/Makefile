CC      = gcc
CFLAGS  = -O3 -march=native -ffast-math -funroll-loops -fopenmp
LIBS    = -lm

all: grayscale

grayscale: main.c parallel_to_grayscale.c parallel_to_grayscale.h
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)

clean:
	rm -f grayscale
